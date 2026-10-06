#!/usr/bin/env python3
"""Generate the local Ollama stress-test notebook.

Source of truth for devtools/local/local_model_stress_test.ipynb (notebooks are
never committed; regenerate with this script). Runs the same four stress tasks
and budgets as the Kaggle comparison notebooks, against a model chosen from an
enum built from `ollama list`.
"""
import json
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
OUT_PATH = REPO_DIR / "devtools" / "local" / "local_model_stress_test.ipynb"


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": text.splitlines(keepends=True)}


CELLS = [
    md("""# Local stress test — pick an Ollama model and run the same tasks as Kaggle

Runs the same four stress tasks and budgets as the Kaggle notebooks, against a local Ollama model. The model is chosen from an enum built from `ollama list`.

**Before running:** start Ollama (`ollama serve` or the app). Close other large apps: this machine has 24 GB unified memory, so keep `concurrency` at 1."""),
    code(r"""from enum import Enum
import json, re, shutil, subprocess, urllib.request
from pathlib import Path

REPO = Path('/Users/octavalo/CascadeProjects/GemmaKaggle/kaggle-gemma4')
DATA = REPO / 'downloads/kagglehub/competitions/gemma-4-developer-agent'
MEMORY_GB = 24
FIT_LIMIT_GB = MEMORY_GB * 0.75  # leave room for the OS, KV cache, and the agent"""),
    md("## 1. Models installed in Ollama"),
    code(r"""def ollama_models():
    with urllib.request.urlopen('http://localhost:11434/api/tags', timeout=5) as resp:
        raw = json.load(resp)['models']
    kept = []
    for m in raw:
        name, size_gb = m['name'], m['size'] / 1e9
        if 'cloud' in name or 'embed' in name or size_gb == 0:
            continue  # remote-only, or embedding models that can't run agent loops
        kept.append((name, size_gb))
    return kept

MODELS = ollama_models()
SIZE_GB = dict(MODELS)

def member_name(tag):
    return re.sub(r'\W+', '_', tag).strip('_').upper()

LocalModel = Enum('LocalModel', {member_name(n): n for n, _ in MODELS}, type=str)

print(f"{'#':>3}  {'enum member':36} {'ollama tag':48} {'GB':>5}  fit")
for i, m in enumerate(LocalModel, 1):
    gb = SIZE_GB[m.value]
    fit = 'ok' if gb <= FIT_LIMIT_GB else 'TIGHT'
    print(f"{i:>3}  {m.name:36} {m.value:48} {gb:5.1f}  {fit}")"""),
    md("""## 2. Choose the model

Change `SELECTED` to any member printed above, for example `LocalModel.DEVSTRAL_24B`."""),
    code("""SELECTED = LocalModel.GEMMA4_E4B
print('Selected:', SELECTED.name, '->', SELECTED.value, f'({SIZE_GB[SELECTED.value]:.1f} GB)')"""),
    md("""## 3. Recommended models for 24 GB

Sizes are approximate. Check the exact tag on ollama.com/library before `ollama pull`. The 31B Gemma 4 QAT model used on Kaggle needs more memory than this Mac has, so this notebook is for proxy-model iteration only.

| Model | ~Size | Why | Status |
|---|---|---|---|
| `gemma4:e4b` | 9.6 GB | Same family as the harness target; fast | installed |
| `devstral:24b` | 14 GB | Mistral's agentic coding model; built for repo-repair tasks | installed |
| `qwen3-coder:30b` | 18 GB | Mixture-of-experts (about 3B active): fast, strong on code; least headroom | installed |
| `gpt-oss:20b` | 13 GB | General reasoning with tool calling | installed |
| `qwen2.5-coder:14b` | ~9 GB | Coder with comfortable headroom | to download: `ollama pull qwen2.5-coder:14b` |
| `gemma3:12b` | ~8 GB | Gemma family at mid size | to download: `ollama pull gemma3:12b` |

Start with `devstral:24b` or `qwen2.5-coder:14b` for agent-loop quality, and use `gemma4:e4b` as the cheap baseline."""),
    md("## 4. Run settings (match the Kaggle comparison budgets)"),
    code(r"""TASK_IDS = ['fastapi_14186', 'rich_3953', 'fastapi_14266', 'rich_3518']
MAX_TOOL_CALLS, MAX_TURNS, MAX_TIME_MINUTES = 25, 15, 15
MAX_OUTPUT_TOKENS = None   # None = committed submission (8192). Set 6144 for the variant arm.

tag = 'default' if MAX_OUTPUT_TOKENS is None else str(MAX_OUTPUT_TOKENS)
RESULTS = REPO / 'local_runs' / f"{SELECTED.name.lower()}_maxtok_{tag}"
WORK = RESULTS / 'work'
if WORK.exists():
    shutil.rmtree(WORK)
WORK.mkdir(parents=True)

SUB = WORK / 'submission'
shutil.copytree(REPO / 'submission', SUB)
if MAX_OUTPUT_TOKENS is not None:
    cfg = SUB / 'configs' / 'sampling.yaml'
    text = cfg.read_text()
    assert text.count('max_output_tokens: 8192') == 1
    cfg.write_text(text.replace('max_output_tokens: 8192', f'max_output_tokens: {MAX_OUTPUT_TOKENS}'))

# The submission declares the competition model alias; point it at the selected Ollama model.
MODELS_YAML = WORK / 'models.yaml'
alias_lines = []
for alias in ['gemma-4-31b-it-qat-w4a16-ct', 'main_lora', 'tool_lora']:
    alias_lines += [
        f'  {alias}:',
        f'    path: openai/{SELECTED.value}',
        '    api_base: http://localhost:11434/v1',
        '    api_key: EMPTY',
    ]
MODELS_YAML.write_text('models:\n' + '\n'.join(alias_lines) + '\n')
print('Results:', RESULTS)
print('Submission copy:', SUB)"""),
    md("## 5. Run the evaluation"),
    code("""cmd = [
    str(REPO / '.venv/bin/swegemma'), 'eval',
    '--tasks', str(DATA / 'tasks.jsonl'),
    '--snapshots-dir', str(DATA / 'snapshots'),
    '--results-dir', str(RESULTS),
    '--submission-dir', str(SUB),
    '--models-yaml', str(MODELS_YAML),
    '--sandbox', 'subprocess',
    '--concurrency', '1',
    '--max-tool-calls', str(MAX_TOOL_CALLS),
    '--max-turns', str(MAX_TURNS),
    '--max-time-minutes', str(MAX_TIME_MINUTES),
    '--task-ids', *TASK_IDS,
]
proc = subprocess.run(cmd, cwd=REPO)
print('exit code', proc.returncode)"""),
    md("## 6. Results"),
    code("""summaries = sorted(RESULTS.rglob('summary.json'))
if not summaries:
    print('No summary.json. Check the output above for errors.')
else:
    summary = json.loads(summaries[0].read_text())
    print(json.dumps(summary, indent=2))"""),
]


def build_notebook() -> dict:
    return {
        "cells": CELLS,
        "metadata": {
            "kernelspec": {"display_name": "Python 3 (gemma venv)", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.13"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> None:
    OUT_PATH.write_text(json.dumps(build_notebook(), indent=1))
    print(f"Wrote {OUT_PATH.relative_to(REPO_DIR)} ({len(CELLS)} cells)")


if __name__ == "__main__":
    main()
