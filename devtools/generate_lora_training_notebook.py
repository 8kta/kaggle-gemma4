#!/usr/bin/env python3
"""Generates a Kaggle notebook that trains a LoRA adapter on the 44
reference-patch-derived trajectories from step 9 part 1 (plan step 9 part 2
— first attempt).

Approach: QLoRA (4-bit NF4 base via bitsandbytes + transformers + peft).
No `trl` — plain `transformers.Trainer` with a hand-rolled masked-SFT
Dataset, to keep the new-dependency surface as small as possible (the
competition wheelhouse has no training libraries at all — see
experiments/CHANGELOG.md's "LoRA training: wheelhouse gap" entry — so
`peft`/`accelerate` come from PyPI, everything else from the wheelhouse).

Base model: `gemma-4-31b-it-qat-q4_0-unquantized` (transformers framework),
NOT `gemma-4-31b-it` and NOT any `-assistant` variant. Reasoning: the
competition's required serving checkpoint is
`gemma-4-31b-it-qat-w4a16-ct` — a QAT (quantization-aware-trained)
checkpoint. `-qat-q4_0-unquantized` is almost certainly the same
QAT-trained weights before the final W4A16 packing step, i.e. the closest
available trainable checkpoint to what's actually served. Training against
plain `-it` (no QAT) or an `-assistant` variant (a different fine-tune
lineage — the suffix appears across every size in the Kaggle model list,
independent of quantization) would introduce base-weight mismatch when the
resulting adapter is later applied to the real `-w4a16-ct` checkpoint at
inference.

This notebook deliberately does NOT attach the competition dataset —
training doesn't need `tasks.jsonl` (only our own
`experiments/lora_training_data/{train,dev}.jsonl`, embedded verbatim
below), and Kaggle has been observed to block Internet on some
accelerators specifically when a competition is attached. Skipping that
attachment should keep Internet available for the `pip install peft
accelerate` step.

Loss masking: the Gemma4 chat template's exact tool-calling syntax can't
be inspected locally (no model download on this machine), so masking is
done template-agnostically — render the conversation prefix ending at each
message via `apply_chat_template`, and treat the token-length delta at
each assistant message as that turn's label span. This works for any
template that's a strict sequential concatenation (true for essentially
every mainstream chat template, Gemma included) — verified at runtime via
an explicit prefix assertion per example, falling back to an unmasked
(full-sequence) label with a printed warning if the assumption ever fails
for a given example, rather than silently producing wrong masks.

This is a first attempt, expected to need debugging iteration once it
actually runs against the real tokenizer/template — same pattern as every
other Kaggle notebook built this project (official baseline, comparison,
max_turns).

Usage:
    python3 devtools/generate_lora_training_notebook.py
    # writes devtools/kaggle_notebooks/lora_training_v1.ipynb

Prerequisites the notebook itself cannot set up (must be done in Kaggle's
own UI before running):
  1. Attach the wheelhouse dataset: metric/gemma-4-developer-agent-wheelhouse
     (pinned transformers/bitsandbytes/tokenizers/safetensors versions,
     known-compatible with the Gemma4 architecture — installed instead of
     whatever pip would otherwise resolve)
  2. Attach the model: google/gemma-4, variant
     gemma-4-31b-it-qat-q4_0-unquantized, **transformers** framework (not
     "other" — that's the inference-only serving checkpoint)
  3. Do NOT attach the competition dataset — not needed for training, and
     may force Internet off if attached.
  4. Accelerator: a 4-GPU option if available. Internet: ON (needed for
     `pip install peft accelerate`).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
LORA_DATA_DIR = REPO_DIR / "experiments" / "lora_training_data"
OUT_PATH = REPO_DIR / "devtools" / "kaggle_notebooks" / "lora_training_v1.ipynb"

BASE_MODEL_VARIANT = "gemma-4-31b-it-qat-q4_0-unquantized"
ADAPTER_NAME = "main_lora"

# Per docs/HARNESS_README.md §3.4's sizing table and claude-idea.md step 9's
# guidance ("start with modest ranks (16, 32)... r=16-32 is safest under
# the 3 GiB budget with headroom").
LORA_RANK = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05
# Dropped the 3 MLP projections (gate/up/down_proj) after a real OOM at
# MAX_SEQ_LENGTH=4096 failed *specifically inside down_proj's LoRA forward*
# (peft/tuners/lora/bnb.py's result.clone() call) — MLP projections are the
# largest in a transformer and were the actual failure site. Attention-only
# targeting is a well-established lower-memory QLoRA configuration; some
# adapter expressiveness is traded for fitting on 2x T4 at all.
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj"]

NUM_EPOCHS = 3
LEARNING_RATE = 2e-4
# 8192 OOM'd on 2x T4 (14.56 GiB/GPU) loading; dropping to 4096 fixed that
# but then OOM'd again *during training* (forward+backward activation memory,
# not weight loading — see TARGET_MODULES and max_memory comments above/below
# for the two other levers pulled instead of cutting this further). Checked
# the real survival rate before going lower: even 4096 only keeps 20/44
# (45%) of train.jsonl's examples (there's a long tail up to ~13.5K
# estimated tokens); 3072 and 2048 both keep ZERO — the median example is
# already ~4.2K estimated tokens. Cutting further would have produced an
# empty dataset, a worse failure than the OOM it was meant to fix. Left at
# 4096 — TARGET_MODULES/max_memory/gradient_checkpointing_kwargs are this
# round's actual levers. Truncated examples are dropped entirely, not
# silently corrupted, see the dataset cell.
MAX_SEQ_LENGTH = 4096


def git_commit() -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_DIR), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def git_dirty() -> bool:
    status = subprocess.run(
        ["git", "-C", str(REPO_DIR), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout
    return bool(status.strip())


def md(*lines: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _src(lines)}


def code(*lines: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": _src(lines)}


def _src(lines: tuple[str, ...]) -> list[str]:
    text = "\n".join(lines)
    out = [line + "\n" for line in text.split("\n")]
    if out:
        out[-1] = out[-1].rstrip("\n")
    return out


def py_literal(text: str) -> str:
    """Render text as a Python triple-quoted string literal, safe for
    embedding arbitrary file content. Backslashes are escaped
    unconditionally — without this, any content containing a sequence
    that looks like a Python string escape (e.g. JSON-escaped unicode
    like \\ud83d\\udc77 from ensure_ascii=True, regex patterns like \\d,
    Windows paths) gets reinterpreted by Python's own string-literal
    parser instead of reproduced as literal text. Found via a real bug:
    an embedded regex character class containing \\uXXXX escapes formed
    an unpaired surrogate when parsed, raising UnicodeEncodeError."""
    escaped = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    return f'"""{escaped}"""'


def build_notebook() -> dict:
    commit = git_commit()
    dirty = git_dirty()
    dirty_note = " **(worktree was DIRTY when this was generated)**" if dirty else ""

    train_content = (LORA_DATA_DIR / "train.jsonl").read_text()
    dev_content = (LORA_DATA_DIR / "dev.jsonl").read_text()
    train_count = sum(1 for line in train_content.splitlines() if line.strip())
    dev_count = sum(1 for line in dev_content.splitlines() if line.strip())

    cells = [
        md(
            "# LoRA training v1 — reference-patch trajectories",
            "",
            f"Generated from commit `{commit}`.{dirty_note}",
            "",
            f"Trains a rank-{LORA_RANK} QLoRA adapter (`{ADAPTER_NAME}`) on "
            f"the {train_count} verified reference-patch trajectories from "
            f"`experiments/lora_training_data/train.jsonl` (plan step 9 "
            f"part 1), validating against the {dev_count}-trajectory `dev` "
            f"split. Base model: `{BASE_MODEL_VARIANT}` (transformers "
            f"format) — the QAT-trained checkpoint before W4A16 packing, "
            f"matched to the competition's required serving checkpoint "
            f"`gemma-4-31b-it-qat-w4a16-ct` (not plain `-it`, not any "
            f"`-assistant` variant — see module docstring in "
            f"`devtools/generate_lora_training_notebook.py` for why).",
            "",
            "**First attempt — expect to need debugging iteration.** The "
            "Gemma4 chat template's exact tool-calling rendering can't be "
            "inspected without the actual tokenizer, so the loss-masking "
            "cell includes a runtime self-check and a loud fallback rather "
            "than silently training on a wrong mask.",
            "",
            "## Prerequisites (set up in Kaggle's UI before running)",
            "1. **Add data**: attach the wheelhouse dataset "
            "`metric/gemma-4-developer-agent-wheelhouse` (pinned "
            "transformers/bitsandbytes/tokenizers/safetensors versions, "
            "known-compatible with the Gemma4 architecture).",
            f"2. **Add model**: `google/gemma-4`, variant "
            f"`{BASE_MODEL_VARIANT}`, **transformers** framework "
            "(not \"other\" — that's the inference-only serving checkpoint).",
            "3. **Do NOT attach the competition dataset** — training doesn't "
            "need it, and attaching it may force Internet off.",
            "4. **Accelerator**: whatever keeps **Internet: ON** (needed for "
            "`pip install peft accelerate` — the wheelhouse has no training "
            "libraries at all) — likely **T4 x2** in practice, since some "
            "4-GPU options have been observed blocking Internet on this "
            "account. T4 doesn't support `bfloat16` (compute capability "
            "7.5 < 8.0); the model-loading and training cells below detect "
            "this and fall back to `float16` automatically, same fix as "
            "the eval notebooks. 2x T4 = 32GB total VRAM — a 31B model at "
            "4-bit is roughly ~16-18GB for weights alone, so this should "
            "fit via `device_map='auto'` sharding both GPUs, but it's "
            "tighter than the eval notebooks' 4-GPU runs and untested at "
            "this scale.",
            "",
            "After this notebook finishes, download "
            f"`/kaggle/working/{ADAPTER_NAME}_adapter.zip`, extract it into "
            f"`submission/adapters/{ADAPTER_NAME}/` locally, add "
            f"`adapter: {ADAPTER_NAME}` to the root agent in "
            "`submission/agent.yaml`, and re-run the official-model "
            "comparison-cohort notebook to see whether it actually helps "
            "vs. the un-adapted champion.",
        ),
        md("## 1. Kaggle environment defaults"),
        code(
            "# This Python 3 environment comes with many helpful analytics libraries installed",
            "# It is defined by the kaggle/python Docker image: https://github.com/kaggle/docker-python",
            "# For example, here's several helpful packages to load",
            "",
            "import numpy as np # linear algebra",
            "import pandas as pd # data processing, CSV file I/O (e.g. pd.read_csv)",
            "",
            "# Input data files are available in the read-only \"../input/\" directory",
            "# For example, running this (by clicking run or pressing Shift+Enter) will list all files under the input directory",
            "",
            "import os",
            "for dirname, _, filenames in os.walk('/kaggle/input'):",
            "    for filename in filenames:",
            "        print(os.path.join(dirname, filename))",
            "",
            "# You can write up to 20GB to the current directory (/kaggle/working/) that gets preserved as output when you create a version using \"Save & Run All\"",
            "# You can also write temporary files to /kaggle/temp/, but they won't be saved outside of the current session",
            "",
            "import kagglehub",
            "# kagglehub.dataset_download('<owner>/<dataset-slug>')",
        ),
        md("## 2. Install training-only dependencies (peft, accelerate) and pinned inference-stack wheels"),
        code(
            "import glob",
            "import subprocess",
            "import sys",
            "from pathlib import Path",
            "",
            "WHEELHOUSE_DIR = Path('/kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse')",
            "",
            "# transformers/bitsandbytes/tokenizers/safetensors: install the wheelhouse's",
            "# pinned versions (known to recognize Gemma4ForConditionalGeneration —",
            "# it's a very new architecture, a fresh pip-resolved transformers might not).",
            "PINNED_PREFIXES = ('transformers-', 'bitsandbytes-', 'tokenizers-', 'safetensors-')",
            "pinned_wheels = [w for w in WHEELHOUSE_DIR.glob('*.whl') if w.name.startswith(PINNED_PREFIXES)]",
            "print(f'Installing {len(pinned_wheels)} pinned wheels from the wheelhouse...')",
            "subprocess.run(",
            "    [sys.executable, '-m', 'pip', 'install', '-q', '--no-deps', *[str(w) for w in pinned_wheels]],",
            "    check=True,",
            ")",
            "",
            "# peft/accelerate: not in the wheelhouse at all (it's scoped for eval/serving,",
            "# not training) — from PyPI. This is why the competition dataset must NOT be",
            "# attached to this notebook: Internet has been observed blocked on some",
            "# accelerators when a competition is attached, and this install needs it.",
            "print('Installing peft, accelerate from PyPI...')",
            "subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'peft>=0.13', 'accelerate>=1.0'], check=True)",
            "print('Dependency installation complete.')",
            "",
            "import transformers, peft, accelerate, bitsandbytes",
            "print(f'transformers={transformers.__version__} peft={peft.__version__} accelerate={accelerate.__version__} bitsandbytes={bitsandbytes.__version__}')",
        ),
        md("## 3. Reconstruct LoRA training data (embedded verbatim from kaggle-gemma4 at the commit noted above)"),
        code(
            "from pathlib import Path",
            "",
            "DATA_DIR = Path('/kaggle/working/lora_data')",
            "DATA_DIR.mkdir(parents=True, exist_ok=True)",
            f"(DATA_DIR / 'train.jsonl').write_text({py_literal(train_content)})",
            f"(DATA_DIR / 'dev.jsonl').write_text({py_literal(dev_content)})",
            "",
            "import json",
            "train_examples = [json.loads(l) for l in (DATA_DIR / 'train.jsonl').read_text().splitlines() if l.strip()]",
            "dev_examples = [json.loads(l) for l in (DATA_DIR / 'dev.jsonl').read_text().splitlines() if l.strip()]",
            f"assert len(train_examples) == {train_count}, f'expected {train_count} train examples, got {{len(train_examples)}}'",
            f"assert len(dev_examples) == {dev_count}, f'expected {dev_count} dev examples, got {{len(dev_examples)}}'",
            "print(f'Loaded {len(train_examples)} train, {len(dev_examples)} dev trajectories.')",
        ),
        md("## 4. Load base model (4-bit NF4) and tokenizer"),
        code(
            "import torch",
            "from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig",
            "",
            f"MODEL_PATH = Path('/kaggle/input/models/google/gemma-4/transformers/{BASE_MODEL_VARIANT}/1')",
            "if not MODEL_PATH.exists():",
            "    # Kaggle model version numbers aren't guaranteed to be '1' — fall back to",
            "    # whatever version directory actually exists under this variant.",
            "    candidates = sorted((MODEL_PATH.parent).glob('*')) if MODEL_PATH.parent.exists() else []",
            "    assert candidates, f'No version directory found under {MODEL_PATH.parent} — check the model was attached with the transformers framework.'",
            "    MODEL_PATH = candidates[-1]",
            "print(f'Loading base model from {MODEL_PATH}')",
            "",
            "# torch.cuda.is_bf16_supported() has returned false positives on T4 in this",
            "# harness stack before (vLLM's own worker-side check rejected it: 'Bfloat16 is",
            "# only supported on GPUs with compute capability of at least 8.0. Your Tesla T4",
            "# GPU has compute capability 7.5.'). Check compute capability directly instead —",
            "# same fix as the eval notebooks, needed here too since T4 is a real accelerator",
            "# you may land on (e.g. if Internet-on forces a particular GPU choice).",
            "if torch.cuda.is_available():",
            "    major, _minor = torch.cuda.get_device_capability(0)",
            "    compute_dtype = torch.bfloat16 if major >= 8 else torch.float16",
            "else:",
            "    compute_dtype = torch.float16",
            "print(f'compute capability check -> dtype={compute_dtype}')",
            "",
            "bnb_config = BitsAndBytesConfig(",
            "    load_in_4bit=True,",
            "    bnb_4bit_quant_type='nf4',",
            "    bnb_4bit_compute_dtype=compute_dtype,",
            "    bnb_4bit_use_double_quant=True,",
            ")",
            "",
            "tokenizer = AutoTokenizer.from_pretrained(str(MODEL_PATH))",
            "if tokenizer.pad_token is None:",
            "    tokenizer.pad_token = tokenizer.eos_token",
            "",
            "# A failed load attempt earlier in the same kernel session can leave GPU",
            "# memory occupied (an exception's traceback holds references to partially",
            "# allocated tensors, blocking garbage collection) — found via a real OOM",
            "# where a GPU already showed >13GiB in use *before* this cell's own",
            "# allocation even started. Proactively clear + report state so a retry in",
            "# the same session doesn't silently inherit a dirty GPU (best fix is still",
            "# a full kernel restart if you're re-running this cell after a prior OOM).",
            "import gc",
            "gc.collect()",
            "if torch.cuda.is_available():",
            "    torch.cuda.empty_cache()",
            "    for i in range(torch.cuda.device_count()):",
            "        alloc = torch.cuda.memory_allocated(i) / 1024**3",
            "        reserv = torch.cuda.memory_reserved(i) / 1024**3",
            "        print(f'GPU {i}: {alloc:.2f} GiB allocated, {reserv:.2f} GiB reserved (before loading)')",
            "        if alloc > 1.0:",
            "            print(f'  WARNING: GPU {i} already has >1GiB allocated — if this is a retry '",
            "                  f'after a previous OOM in this session, restart the kernel instead of '",
            "                  f're-running this cell.')",
            "",
            "# Hit a real CUDA OOM on 2x T4 (14.56 GiB/GPU) without this: device_map='auto'",
            "# alone let the model's own sharded weights fill each GPU close to its full",
            "# capacity, leaving too little headroom for activation/gradient memory during",
            "# training. Tried tightening this to total-6GiB (~8.56GiB/GPU), reasoning the",
            "# ~7.75GiB/GPU weight footprint (31B @ 4-bit / 2 GPUs) didn't need the full",
            "# ~11GiB total-3GiB left available — that was wrong: total-6 didn't leave",
            "# enough room for the weights themselves, and bitsandbytes' 4-bit quantizer",
            "# refuses CPU/disk offload without an extra flag, raising ValueError at load",
            "# time. Two real data points now bracket the actual requirement: total-3",
            "# loads successfully, total-6 doesn't even fit the weights. Reverted to the",
            "# value that's proven to load — TARGET_MODULES (attention-only, see above)",
            "# and non-reentrant checkpointing are this round's actual levers against the",
            "# training-time OOM, untested on their own until this cap change is undone.",
            "max_memory = None",
            "if torch.cuda.is_available():",
            "    max_memory = {",
            "        i: f'{int(torch.cuda.get_device_properties(i).total_memory / 1024**3) - 3}GiB'",
            "        for i in range(torch.cuda.device_count())",
            "    }",
            "    print(f'max_memory per GPU (reserving ~3GiB headroom for activations/gradients): {max_memory}')",
            "",
            "base_model = AutoModelForCausalLM.from_pretrained(",
            "    str(MODEL_PATH),",
            "    quantization_config=bnb_config,",
            "    device_map='auto',",
            "    max_memory=max_memory,",
            "    dtype=compute_dtype,",
            ")",
            "print(f'Loaded {base_model.__class__.__name__}, {sum(p.numel() for p in base_model.parameters())/1e9:.1f}B params')",
        ),
        md("## 5. Wrap with LoRA (peft)"),
        code(
            "from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training",
            "",
            "",
            "def unwrap_clippable_linears(model, target_leaf_names):",
            "    \"\"\"peft's LoRA injection only recognizes torch.nn.Linear/Linear4bit/etc.",
            "    directly — Gemma4's transformers checkpoint wraps its linear layers in a",
            "    custom Gemma4ClippableLinear class instead, which get_peft_model() rejects",
            "    with 'Target module ... is not supported' even though it wraps a real",
            "    Linear4bit internally (confirmed from the real error's repr:",
            "    Gemma4ClippableLinear(linear): Linear4bit(...)). Unwrap each one targeted",
            "    by LoRA back to its .linear submodule in place — same weights, same",
            "    quantization, just without the wrapper. Training-time-only: the adapter",
            "    itself (small low-rank matrices, saved separately) is what actually gets",
            "    served later via vLLM, which never touches this module structure at all.",
            "    \"\"\"",
            "    unwrapped = 0",
            "    for name, module in list(model.named_modules()):",
            "        leaf = name.rsplit('.', 1)[-1]",
            "        if leaf in target_leaf_names and module.__class__.__name__ == 'Gemma4ClippableLinear' and hasattr(module, 'linear'):",
            "            parent_name, _, attr = name.rpartition('.')",
            "            parent = model.get_submodule(parent_name) if parent_name else model",
            "            setattr(parent, attr, module.linear)",
            "            unwrapped += 1",
            "    print(f'Unwrapped {unwrapped} Gemma4ClippableLinear -> Linear4bit modules for LoRA targeting')",
            "    return unwrapped",
            "",
            "",
            f"n_unwrapped = unwrap_clippable_linears(base_model, set({TARGET_MODULES!r}))",
            "assert n_unwrapped > 0, (",
            "    'No Gemma4ClippableLinear modules found to unwrap — either the error is '",
            "    'gone in this transformers version (safe to remove this cell), or the '",
            "    'wrapper class/attribute name changed and this needs updating.'",
            ")",
            "",
            "base_model = prepare_model_for_kbit_training(base_model)",
            "",
            "lora_config = LoraConfig(",
            f"    r={LORA_RANK},",
            f"    lora_alpha={LORA_ALPHA},",
            f"    lora_dropout={LORA_DROPOUT},",
            f"    target_modules={TARGET_MODULES!r},",
            "    task_type='CAUSAL_LM',",
            "    bias='none',",
            ")",
            "model = get_peft_model(base_model, lora_config)",
            "model.print_trainable_parameters()",
        ),
        md("## 6. Build the masked-SFT dataset"),
        code(
            "# Loss masking is template-agnostic: render the conversation prefix ending at",
            "# each message, and treat the token-length delta at each assistant message as",
            "# that turn's label span. Valid for any strictly-concatenative chat template",
            "# (true for every mainstream template, Gemma included) — verified per-example",
            "# via an explicit prefix assertion; falls back to an unmasked full-sequence",
            "# label with a printed warning rather than silently mis-masking if the",
            "# assumption ever fails for a given example.",
            "import torch",
            "from torch.utils.data import Dataset",
            "",
            "",
            "def _to_id_list(result):",
            "    \"\"\"apply_chat_template's return type isn't consistent across",
            "    tokenizers/processors — plain list[int], a BatchEncoding/dict (if the",
            "    template implies return_dict=True, e.g. some tool-calling-aware",
            "    processors), or a tensor, optionally with a leading batch dimension.",
            "    Found via a real TypeError at collate time: 'unsupported operand",
            "    type(s) for +: BatchEncoding and list' — apply_chat_template was",
            "    silently returning a BatchEncoding here, not the plain list every",
            "    downstream len()/slice/index call assumed. Normalize to plain",
            "    list[int] every time instead of assuming a type.\"\"\"",
            "    if hasattr(result, 'input_ids'):",
            "        result = result['input_ids'] if isinstance(result, dict) else result.input_ids",
            "    elif isinstance(result, dict) and 'input_ids' in result:",
            "        result = result['input_ids']",
            "    if hasattr(result, 'tolist'):",
            "        result = result.tolist()",
            "    if result and isinstance(result[0], list):",
            "        result = result[0]",
            "    return list(result)",
            "",
            "",
            "def build_masked_example(messages, tokenizer, max_length):",
            "    full_ids = _to_id_list(tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False))",
            "    if len(full_ids) > max_length:",
            "        return None  # dropped, not truncated — see module docstring",
            "    labels = [-100] * len(full_ids)",
            "    prefix_len = 0",
            "    prefix_ok = True",
            "    for i, msg in enumerate(messages):",
            "        prefix_ids = _to_id_list(tokenizer.apply_chat_template(messages[: i + 1], tokenize=True, add_generation_prompt=False))",
            "        if prefix_ids != full_ids[: len(prefix_ids)]:",
            "            prefix_ok = False",
            "            break",
            "        if msg['role'] == 'assistant':",
            "            for idx in range(prefix_len, len(prefix_ids)):",
            "                labels[idx] = full_ids[idx]",
            "        prefix_len = len(prefix_ids)",
            "    if not prefix_ok:",
            "        labels = list(full_ids)  # fallback: train on the full sequence, unmasked",
            "    return full_ids, labels, prefix_ok",
            "",
            "",
            "class TrajectoryDataset(Dataset):",
            "    def __init__(self, examples, tokenizer, max_length):",
            "        self.items = []",
            "        dropped, fallback = 0, 0",
            "        for ex in examples:",
            "            result = build_masked_example(ex['messages'], tokenizer, max_length)",
            "            if result is None:",
            "                dropped += 1",
            "                continue",
            "            input_ids, labels, prefix_ok = result",
            "            if not prefix_ok:",
            "                fallback += 1",
            "            self.items.append({'input_ids': input_ids, 'labels': labels})",
            "        print(f'Dataset: {len(self.items)} usable, {dropped} dropped (too long), {fallback} used the unmasked fallback (prefix assumption failed)')",
            "        if fallback > len(self.items) // 2:",
            "            print('WARNING: more than half the examples needed the unmasked fallback — '",
            "                  'the template-prefix assumption is probably wrong for this tokenizer. '",
            "                  'Masking is likely unreliable; inspect a few examples by hand before trusting this run.')",
            "",
            "    def __len__(self):",
            "        return len(self.items)",
            "",
            "    def __getitem__(self, idx):",
            "        return self.items[idx]",
            "",
            "",
            f"train_dataset = TrajectoryDataset(train_examples, tokenizer, {MAX_SEQ_LENGTH})",
            f"dev_dataset = TrajectoryDataset(dev_examples, tokenizer, {MAX_SEQ_LENGTH})",
        ),
        md("## 7. Data collator (pad to batch max, mask padding in labels)"),
        code(
            "def collate_fn(batch):",
            "    max_len = max(len(b['input_ids']) for b in batch)",
            "    pad_id = tokenizer.pad_token_id",
            "    input_ids, attention_mask, labels = [], [], []",
            "    for b in batch:",
            "        n_pad = max_len - len(b['input_ids'])",
            "        input_ids.append(b['input_ids'] + [pad_id] * n_pad)",
            "        attention_mask.append([1] * len(b['input_ids']) + [0] * n_pad)",
            "        labels.append(b['labels'] + [-100] * n_pad)",
            "    return {",
            "        'input_ids': torch.tensor(input_ids, dtype=torch.long),",
            "        'attention_mask': torch.tensor(attention_mask, dtype=torch.long),",
            "        'labels': torch.tensor(labels, dtype=torch.long),",
            "    }",
        ),
        md("## 8. Train"),
        code(
            "from transformers import Trainer, TrainingArguments",
            "",
            "OUTPUT_DIR = Path('/kaggle/working/lora_checkpoints')",
            "",
            "training_args = TrainingArguments(",
            "    output_dir=str(OUTPUT_DIR),",
            f"    num_train_epochs={NUM_EPOCHS},",
            "    per_device_train_batch_size=1,",
            "    per_device_eval_batch_size=1,",
            "    gradient_accumulation_steps=8,",
            "    gradient_checkpointing=True,",
            "    gradient_checkpointing_kwargs={'use_reentrant': False},",
            f"    learning_rate={LEARNING_RATE},",
            "    bf16=(compute_dtype == torch.bfloat16),",
            "    fp16=(compute_dtype == torch.float16),",
            "    logging_steps=1,",
            "    eval_strategy='epoch',",
            "    save_strategy='epoch',",
            "    save_total_limit=2,",
            "    report_to='none',",
            ")",
            "",
            "trainer = Trainer(",
            "    model=model,",
            "    args=training_args,",
            "    train_dataset=train_dataset,",
            "    eval_dataset=dev_dataset,",
            "    data_collator=collate_fn,",
            ")",
            "",
            "train_result = trainer.train()",
            "print(train_result)",
        ),
        md(f"## 9. Save the adapter as `{ADAPTER_NAME}` and package for download"),
        code(
            "import shutil",
            "",
            f"ADAPTER_DIR = Path('/kaggle/working/adapters/{ADAPTER_NAME}')",
            "ADAPTER_DIR.mkdir(parents=True, exist_ok=True)",
            "model.save_pretrained(str(ADAPTER_DIR))",
            "print(f'Saved adapter to {ADAPTER_DIR}:')",
            "for p in sorted(ADAPTER_DIR.rglob('*')):",
            "    if p.is_file():",
            "        print(' ', p.relative_to(ADAPTER_DIR), f'({p.stat().st_size} bytes)')",
            "",
            f"zip_path = shutil.make_archive('/kaggle/working/{ADAPTER_NAME}_adapter', 'zip', root_dir='/kaggle/working/adapters', base_dir='{ADAPTER_NAME}')",
            "print(f'Wrote {zip_path} — download this and extract into submission/adapters/ locally.')",
        ),
    ]

    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.13"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    nb = build_notebook()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(nb, indent=1))
    print(f"Wrote {OUT_PATH}")
    print(f"Embedded commit: {git_commit()}" + (" (DIRTY worktree)" if git_dirty() else ""))
    print(f"Base model: {BASE_MODEL_VARIANT} (transformers framework)")
    print(f"LoRA: r={LORA_RANK} alpha={LORA_ALPHA} target_modules={TARGET_MODULES}")


if __name__ == "__main__":
    main()
