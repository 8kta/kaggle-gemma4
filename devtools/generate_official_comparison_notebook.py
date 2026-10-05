#!/usr/bin/env python3
"""Generates a Kaggle notebook that runs our submission/ against the real
gemma-4-31b-it-qat-w4a16-ct model on the `comparison` cohort (19 tasks) —
the first larger-than-smoke official-model sample.

Separate notebook from official_baseline_smoke.ipynb (not a parameterized
variant of it) per explicit instruction — the smoke notebook stays a small,
fast, known-working sanity check; this one is the bigger, slower run meant
to give real resolution-rate signal beyond n=4, feeding the LoRA go/no-go
decision (see agent-ideas/claude-idea.md step 12's milestone table).

Same reproducible-generation pattern as generate_official_baseline_notebook.py:
embeds submission/'s CURRENT file contents at generation time, and reads the
`comparison` cohort's task IDs from experiments/cohorts.json at generation
time too (not hardcoded), so a re-run always reflects whatever's actually
committed/defined right now.

Carries forward every fix found running the smoke notebook: the Kaggle
default boilerplate first cell, the compute-capability-based dtype check
(torch.cuda.is_bf16_supported() gave a false positive on a Tesla T4),
Evaluator.run() taking no arguments (filters via EvalConfig.task_ids
instead), and the correct TaskResult field names.

Usage:
    python3 devtools/generate_official_comparison_notebook.py
    # writes devtools/kaggle_notebooks/official_baseline_comparison.ipynb

Prerequisites the notebook itself cannot set up (must be done in Kaggle's
own UI before running):
  1. Attach the competition dataset: gemma-4-developer-agent
  2. Attach the wheelhouse dataset: metric/gemma-4-developer-agent-wheelhouse
  3. Attach the model: google/gemma-4 (variant gemma-4-31b-it-qat-w4a16-ct)
  4. Notebook accelerator: a 4-GPU option if available; disable Internet
     (required alongside some accelerators on competition-attached
     notebooks, and the harness doesn't need it anyway — fully offline by
     design)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
SUBMISSION_DIR = REPO_DIR / "submission"
COHORTS_PATH = REPO_DIR / "experiments" / "cohorts.json"
# Versioned per submission variant (not overwritten) so each tested config's
# exact notebook stays around — notebooks are gitignored, so a reused
# filename would silently lose the previous variant's file on regeneration
# (the prior "official_baseline_comparison.ipynb" for the pre-navigator
# baseline was lost this way before this convention started; its real
# results are still safe in MLflow/CHANGELOG under
# '2026-09-30_official-comparison-v1'). Bump VERSION_TAG for each new
# variant generated from this script.
VERSION_TAG = "filesystem-only-graphdebug"
OUT_PATH = REPO_DIR / "devtools" / "kaggle_notebooks" / f"official_baseline_comparison_{VERSION_TAG}.ipynb"

# Same budgets as the smoke notebook — identical methodology, so this run's
# numbers are directly comparable to the smoke-cohort results already logged.
MAX_TIME_MINUTES = 15
MAX_TOOL_CALLS = 25
MAX_TURNS = 15


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
    that looks like a Python string escape (e.g. JSON-escaped unicode,
    regex patterns like \\d, Windows paths) gets reinterpreted by
    Python's own string-literal parser instead of reproduced as literal
    text. Found via a real bug in generate_lora_training_notebook.py;
    fixed here too even though submission/'s own files happen to
    contain no backslashes (so this generator's prior output was never
    actually affected)."""
    escaped = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    return f'"""{escaped}"""'


def read(rel: str) -> str:
    return (SUBMISSION_DIR / rel).read_text()


def build_notebook() -> dict:
    commit = git_commit()
    dirty = git_dirty()
    dirty_note = " **(worktree was DIRTY when this was generated — the embedded content may not match any single commit exactly)**" if dirty else ""

    cohorts = json.loads(COHORTS_PATH.read_text())
    comparison = cohorts["comparison"]
    comparison_task_ids = comparison["ids"]
    by_repo = comparison["by_repo"]
    caveats = cohorts.get("known_anomalous_task_caveats_by_cohort", {}).get("comparison", {})

    submission_files = sorted(p.relative_to(SUBMISSION_DIR).as_posix() for p in SUBMISSION_DIR.rglob("*") if p.is_file())
    write_files_lines = [
        "# submission/ reconstructed from kaggle-gemma4 at the commit noted above.",
        "# Every file below is embedded verbatim from the repo at generation time —",
        "# see devtools/generate_official_comparison_notebook.py, do not hand-edit here.",
        "import os",
        "from pathlib import Path",
        "",
        "AGENT_DIR = Path('/kaggle/working/submission')",
        "if AGENT_DIR.exists():",
        "    import shutil; shutil.rmtree(AGENT_DIR)",
        "AGENT_DIR.mkdir(parents=True)",
        "",
    ]
    for rel in submission_files:
        content = read(rel)
        write_files_lines.append(f"(AGENT_DIR / {rel!r}).parent.mkdir(parents=True, exist_ok=True)")
        write_files_lines.append(f"(AGENT_DIR / {rel!r}).write_text({py_literal(content)})")
    write_files_lines.append("")
    write_files_lines.append("print(f'Wrote {len(list(AGENT_DIR.rglob(chr(42)))) } files under {AGENT_DIR}')")
    write_files_lines.append("for p in sorted(AGENT_DIR.rglob('*')):")
    write_files_lines.append("    if p.is_file():")
    write_files_lines.append("        print(' ', p.relative_to(AGENT_DIR))")

    caveat_lines = [f"- `{tid}`: {reason}" for tid, reason in caveats.items()] or ["- none recorded"]

    cells = [
        md(
            "# Official-model baseline — kaggle-gemma4 `comparison` cohort",
            "",
            f"Generated from commit `{commit}`.{dirty_note}",
            "",
            f"Runs our real `submission/` against the actual "
            f"`gemma-4-31b-it-qat-w4a16-ct` model on the `comparison` cohort "
            f"({len(comparison_task_ids)} tasks, by_repo={by_repo}) from "
            f"`experiments/cohorts.json`. This is a bigger sample than the "
            f"4-task `smoke` cohort already validated — the goal is real "
            f"resolution-rate signal to inform the LoRA go/no-go decision, "
            f"not just an orchestration sanity check.",
            "",
            "**This run removes the 3 graph tools** "
            "(`get_code_neighbors`/`search_similar_code`/`get_code_subgraph`) "
            "and the navigator sub-agent entirely, keeping only "
            "`run_command`/`read_file`/`edit_file`/`write_file`/`get_status`/"
            "`submit_patch` plus the `repo-navigation` skill — the system "
            "prompt's graph-search guidance is replaced with direct "
            "`grep`/`find`. Motivated by real evidence, not guessing: across "
            "the two prior official-model comparison-cohort runs "
            "(`2026-09-30_official-comparison-v1`, "
            "`2026-10-01_official-comparison-navigator-v2`), **all 30 "
            "`search_similar_code` calls returned `{\"results\": [], "
            "\"count\": 0}`** — including for generic queries like `class "
            "FastAPI` against the FastAPI repo itself, suggesting the "
            "graph/embedding data isn't functioning for these repos, not "
            "just that it wasn't useful. The navigator was dropped "
            "separately: official-model testing showed no resolution gain "
            "(`resolution_rate=2/19`, identical to the pre-navigator "
            "baseline) and a real self-enforcement failure (its own prompt "
            "capped it at 3 tool calls; it made 8 on its one invocation). "
            "See `experiments/CHANGELOG.md` for the full evidence behind "
            "both removals. `2026-09-30_official-comparison-v1` is this "
            "run's direct before/after baseline: same cohort, same "
            "budgets, same everything except these two tool removals.",
            "",
            "**Known-anomalous tasks in this cohort** (see `devtools/define_cohorts.py`'s "
            "`KNOWN_ANOMALOUS` — real public tasks, not excluded, just flagged):",
            *caveat_lines,
            "",
            f"**Expect this to take a while**: same per-task budgets as the smoke "
            f"notebook (15 min / 25 tool calls / 15 turns), run sequentially "
            f"(`concurrency` not set, defaults to 1 — matches the known-working "
            f"smoke-notebook recipe rather than introducing untested "
            f"concurrency on the first larger run). Smoke-cohort tasks actually "
            f"took ~3-7 minutes each in practice (well under the 15-minute cap) "
            f"— at that rate, {len(comparison_task_ids)} tasks is roughly "
            f"1-2.5 hours, but could run longer if more tasks hit their budget "
            f"ceiling. Kaggle notebook sessions can be closed/reopened; the "
            f"run itself will keep going as long as the session stays active.",
            "",
            "## Prerequisites (set up in Kaggle's UI before running — this notebook cannot do these itself)",
            "1. **Add competition data**: `gemma-4-developer-agent`",
            "2. **Add data**: search for and attach the dataset "
            "`metric/gemma-4-developer-agent-wheelhouse`",
            "3. **Add model**: `google/gemma-4`, variant "
            "`gemma-4-31b-it-qat-w4a16-ct`",
            "4. **Accelerator**: a 4-GPU option if available. **Disable Internet** "
            "— Kaggle blocks some accelerators when Internet is on for "
            "competition-attached notebooks, and this notebook doesn't need "
            "internet anyway (the wheelhouse is a pre-attached dataset, and "
            "the harness is designed to run fully offline).",
            "",
            "After this notebook finishes, download `/kaggle/working/results` "
            "and ingest it locally:",
            "```",
            "python3 devtools/mlflow/ingest_results.py \\",
            "  --results-dir <downloaded>/results \\",
            "  --label 2026-10-01_official-comparison-filesystem-only \\",
            "  --submission-snapshot <downloaded>/submission \\",
            f"  --git-commit {commit} \\",
            "  --backend gemma-4-31b-qat --env kaggle-notebook --fidelity official-model \\",
            "  --cohort comparison",
            "```",
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
            "# Use the kagglehub client library to attach Kaggle resources like competitions, datasets, and models to your session",
            "# Learn more about kagglehub: https://github.com/Kaggle/kagglehub/blob/main/README.md",
            "",
            "import kagglehub",
            "# kagglehub.dataset_download('<owner>/<dataset-slug>')",
        ),
        md(
            "Note: the `os.walk('/kaggle/input')` listing above can be very long once the "
            "competition dataset, wheelhouse dataset, and full model weights are all attached "
            "— that's expected, not an error. This cell is otherwise unused by the rest of the "
            "notebook: every path below is hardcoded to the attachment points this notebook's "
            "prerequisites section specifies (`/kaggle/input/competitions/...`, "
            "`/kaggle/input/datasets/...`, `/kaggle/input/models/...`), matching how the UI "
            "\"Add Input\" flow mounts them rather than the `kagglehub.*_download()` calls shown "
            "above (which would pull a second, separate copy into `/kaggle/working/` instead)."
        ),
        md("## 2. Environment configuration and package installation"),
        code(
            "import glob",
            "import importlib",
            "import os",
            "import shutil",
            "import subprocess",
            "import sys",
            "from pathlib import Path",
            "",
            "os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'",
            "os.environ['TRANSFORMERS_NO_TF'] = '1'",
            "os.environ['VLLM_WORKER_MULTIPROC_METHOD'] = 'spawn'",
            "os.environ['VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS'] = '1'",
            "os.environ['VLLM_ENGINE_READY_TIMEOUT_S'] = '1200'",
            "os.environ['VLLM_NO_USAGE_STATS'] = '1'",
            "os.environ['OTEL_SDK_DISABLED'] = 'true'",
            "os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'",
            "",
            "WHEELHOUSE_DIR = Path('/kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse')",
            "",
            "for pth_pattern in (",
            "    '/usr/local/lib/python*/dist-packages/*cutlass*.pth',",
            "    '/usr/local/lib/python*/site-packages/*cutlass*.pth',",
            "):",
            "    for pth in glob.glob(pth_pattern):",
            "        try:",
            "            os.unlink(pth)",
            "        except OSError:",
            "            pass",
            "",
            "tmp_whl = Path('/kaggle/temp/wheelhouse')",
            "tmp_whl.mkdir(parents=True, exist_ok=True)",
            "for w in WHEELHOUSE_DIR.glob('*.whl'):",
            "    if 'cutlass' in w.name.lower():",
            "        continue",
            "    target_name = (",
            "        w.name.replace('cu128', '+cu128')",
            "        if ('cu128' in w.name and '+' not in w.name)",
            "        else w.name",
            "    )",
            "    target = tmp_whl / target_name",
            "    if not target.exists():",
            "        os.symlink(w, target)",
            "",
            "wheels = sorted(str(w) for w in tmp_whl.glob('*.whl'))",
            "print(f'Installing {len(wheels)} wheels from {WHEELHOUSE_DIR}...')",
            "subprocess.run(",
            "    [sys.executable, '-m', 'pip', 'install', '-q', '--no-deps', '--force-reinstall', *wheels],",
            "    check=True,",
            ")",
            "importlib.invalidate_caches()",
            "print('Wheelhouse installation complete.')",
            "import hashlib",
            "import swegemma.graph.graph_utils as _gu",
            "_EXPECTED_SWEGEMMA_SHA256 = '27a2f60f8db46c8fef5defc16df722dac0402446c9a6252e7e6b4c280e843c81'",
            "_EXPECTED_GRAPH_UTILS_SHA256 = 'e48d9f0cabe02e9ce8b1a0ab437de68a90e0a740b61a3f54ce5a95ab1f05c1cc'",
            "_whl = next(WHEELHOUSE_DIR.rglob('swegemma-*.whl'))",
            "_whl_sha = hashlib.sha256(_whl.read_bytes()).hexdigest()",
            "_gu_sha = hashlib.sha256(open(_gu.__file__, 'rb').read()).hexdigest()",
            "assert _whl_sha == _EXPECTED_SWEGEMMA_SHA256, f'Unexpected swegemma wheel sha256: {_whl_sha}'",
            "assert _gu_sha == _EXPECTED_GRAPH_UTILS_SHA256, f'Unexpected installed graph_utils.py sha256: {_gu_sha}'",
            "print('swegemma build verified (wheel and installed graph_utils match the pinned v28 hashes)')",
        ),
        md("## 3. Reconstruct submission/ from kaggle-gemma4 (embedded verbatim, see notebook header for commit)"),
        code(*write_files_lines),
        md("## 4. Competition dataset and the `comparison` cohort"),
        code(
            "from swegemma.models import load_tasks",
            "",
            "DATA_DIR = Path('/kaggle/input/competitions/gemma-4-developer-agent')",
            "WORKING_DIR = Path('/kaggle/working')",
            "WORKING_DIR.mkdir(parents=True, exist_ok=True)",
            "",
            "TASKS_PATH = DATA_DIR / 'tasks.jsonl'",
            "all_tasks = load_tasks(TASKS_PATH)",
            f"COMPARISON_TASK_IDS = {comparison_task_ids!r}",
            "tasks = [t for t in all_tasks if t.instance_id in COMPARISON_TASK_IDS]",
            "assert len(tasks) == len(COMPARISON_TASK_IDS), f'expected {len(COMPARISON_TASK_IDS)} tasks, found {len(tasks)}'",
            "",
            "print(f'Data directory: {DATA_DIR}')",
            "print(f'Agent directory: {AGENT_DIR}')",
            "print(f'Loaded {len(tasks)} comparison-cohort tasks:')",
            "for t in tasks:",
            "    print(f'  - {t.instance_id} ({t.repo} @ {t.base_commit[:8]})')",
        ),
        md("## 5. Start vLLM server (real gemma-4-31b-it-qat-w4a16-ct)"),
        code(
            "import litellm",
            "import torch",
            "from adk_submission import VllmConfig, VllmServer, discover_adapters",
            "from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS",
            "from swegemma.models.discovery import validate_single_declared_model",
            "",
            "litellm.drop_params = True",
            "",
            "TARGET_MODEL_NAME = 'gemma-4-31b-it-qat-w4a16-ct'",
            "MODEL_PATH = Path('/kaggle/input/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2')",
            "INFERENCE_API_KEY = 'EMPTY'",
            "",
            "declared_model = validate_single_declared_model(AGENT_DIR)",
            "adapters = discover_adapters(str(AGENT_DIR), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)",
            "print(f'Declared model: {declared_model}; adapters found: {len(getattr(adapters, \"adapters\", []) or [])}')",
            "",
            "gpu_count = torch.cuda.device_count() if torch.cuda.is_available() else 1",
            "tp_size = 4 if gpu_count >= 4 else (2 if gpu_count >= 2 else 1)",
            "",
            "# torch.cuda.is_bf16_supported() has returned false positives on T4 in this",
            "# harness stack (reports bf16-capable, then vLLM's own worker-side compute-",
            "# capability check rejects it: 'Bfloat16 is only supported on GPUs with compute",
            "# capability of at least 8.0. Your Tesla T4 GPU has compute capability 7.5.').",
            "# The competition's real hardware is 4x L4 (compute capability 8.9, bf16-native);",
            "# Kaggle's free/standard notebook GPUs are T4 x2 or P100, both compute<8.0 and",
            "# fp16-only. Check compute capability directly instead of trusting the helper.",
            "if torch.cuda.is_available():",
            "    major, _minor = torch.cuda.get_device_capability(0)",
            "    inferred_dtype = 'bfloat16' if major >= 8 else 'float16'",
            "else:",
            "    inferred_dtype = 'float16'",
            "print(f'GPUs: {gpu_count}, compute capability check -> dtype={inferred_dtype}')",
            "",
            "vllm_cfg = VllmConfig(",
            "    model=str(MODEL_PATH),",
            "    port=8000,",
            "    host='127.0.0.1',",
            "    tool_call_parser='gemma4',",
            "    reasoning_parser='gemma4',",
            "    max_model_len=32768,",
            "    dtype=inferred_dtype,",
            "    gpu_memory_utilization=0.90,",
            "    enable_auto_tool_choice=True,",
            "    enable_lora=True,",
            "    max_loras=8,",
            "    max_lora_rank=128,",
            "    tensor_parallel_size=tp_size,",
            "    startup_timeout=60 * 20,",
            ")",
            "server_instance = VllmServer(vllm_cfg, adapter_manifest=adapters)",
            "server_instance.start()",
            "print(f'vLLM server started on {server_instance.base_url} (tp={tp_size})')",
            "",
            "models = server_instance.create_model_registry(",
            "    aliases=[declared_model, TARGET_MODEL_NAME],",
            "    model_prefix='openai/',",
            "    api_key=INFERENCE_API_KEY,",
            ")",
        ),
        md("## 5b. Graph directory resolution (debug)"),
        code(
            "import os",
            "",
            "print('CWD:', os.getcwd())",
            "for rel in ['data/graphs', 'data/embeddings']:",
            "    print(f'{rel} exists relative to CWD: {Path(rel).exists()}')",
            "for sub, pattern in [('graphs', '*.json'), ('embeddings', '*.npz')]:",
            "    d = TASKS_PATH.parent / sub",
            "    n = len(list(d.glob(pattern))) if d.is_dir() else 0",
            "    print(f'{d}: is_dir={d.is_dir()}, files={n}')",
        ),
        md("## 6. Run the comparison cohort — Phase 1 inference + Phase 2 verification"),
        code(
            "import asyncio",
            "import concurrent.futures",
            "from swegemma.config import EvalConfig, build_submission_limits",
            "from swegemma.evaluate import Evaluator",
            "",
            "",
            "def run_sync(coro_or_fn, *args, **kwargs):",
            "    fn = (lambda: coro_or_fn(*args, **kwargs)) if callable(coro_or_fn) else (lambda: coro_or_fn)",
            "    try:",
            "        loop = asyncio.get_running_loop()",
            "    except RuntimeError:",
            "        loop = None",
            "    if loop is not None and loop.is_running():",
            "        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:",
            "            return pool.submit(lambda: asyncio.run(fn())).result()",
            "    return asyncio.run(fn())",
            "",
            "",
            "RESULTS_DIR = WORKING_DIR / 'results'",
            "limits, gen_constraints = build_submission_limits()",
            "",
            "# Same budgets as the smoke notebook — keeps this run directly",
            "# comparable to the already-logged smoke-cohort results.",
            "eval_config = EvalConfig(",
            "    tasks_path=TASKS_PATH,",
            "    snapshots_dir=DATA_DIR / 'snapshots',",
            "    results_dir=RESULTS_DIR,",
            "    submission_dir=AGENT_DIR,",
            "    models=models,",
            "    sandbox='subprocess',",
            "    task_ids=COMPARISON_TASK_IDS,",
            f"    timeout_seconds=300,",
            f"    max_tool_calls={MAX_TOOL_CALLS},",
            f"    max_time_minutes={MAX_TIME_MINUTES},",
            f"    max_turns={MAX_TURNS},",
            "    limits=limits,",
            "    generation_constraints=gen_constraints,",
            ")",
            "",
            "# Evaluator.run() takes no arguments — it loads tasks from",
            "# eval_config.tasks_path itself and filters by eval_config.task_ids",
            "# (set above), rather than accepting a task list at call time.",
            "evaluator = Evaluator(eval_config)",
            "eval_result = run_sync(evaluator.run)",
            "print(f'Completed {len(eval_result.task_results)} task(s):')",
            "for r in eval_result.task_results:",
            "    print(f'  {r.task_id}: resolved={r.resolved}, status={r.status}, error={r.error_message}, tool_calls={r.tool_calls}, duration={r.duration_seconds:.1f}s')",
        ),
        md("## 7. Summarize and package for download"),
        code(
            "import json",
            "",
            "summary_path = RESULTS_DIR / 'summary.json'",
            "if summary_path.exists():",
            "    print(json.dumps(json.loads(summary_path.read_text()), indent=2))",
            "else:",
            "    print('No summary.json produced — check the Evaluator output above for errors.')",
            "",
            "# Zip results + the exact submission/ that was evaluated, for easy download",
            "# and later `devtools/mlflow/ingest_results.py` ingestion.",
            "import shutil as _shutil",
            f"_shutil.make_archive(str(WORKING_DIR / 'official_baseline_comparison_{VERSION_TAG}_results'), 'zip', root_dir=WORKING_DIR, base_dir='results')",
            f"_shutil.make_archive(str(WORKING_DIR / 'official_baseline_comparison_{VERSION_TAG}_submission'), 'zip', root_dir=WORKING_DIR, base_dir='submission')",
            f"print('Wrote official_baseline_comparison_{VERSION_TAG}_results.zip and official_baseline_comparison_{VERSION_TAG}_submission.zip under /kaggle/working — download both.')",
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
    cohorts = json.loads(COHORTS_PATH.read_text())
    comparison_task_ids = cohorts["comparison"]["ids"]
    print(f"Wrote {OUT_PATH}")
    print(f"Embedded commit: {git_commit()}" + (" (DIRTY worktree)" if git_dirty() else ""))
    print(f"Comparison cohort ({len(comparison_task_ids)} tasks): {', '.join(comparison_task_ids)}")


if __name__ == "__main__":
    main()
