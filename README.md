# kaggle-gemma4

Working repo for the Kaggle **Gemma 4 Developer Agent Competition**. See
`agent-ideas/claude-idea.md` for the full working plan and
`agent-ideas/codex-idea.md` for a parallel plan draft; `docs/` holds the
competition's own reference material (Overview, Data, HARNESS_README).

## Layout

```
submission/       # Competition files only — this is what gets zipped as submission.zip
  configs/        # sampling.yaml etc., loaded via !include
  prompts/        # system.md etc., loaded via !include
  sub_agents/     # sub-agent / AgentTool YAML configs
  skills/         # ADK Skill directories (SKILL.md + scripts/resources)
  adapters/       # LoRA adapter directories (adapter_config.json + adapter_model.safetensors)
devtools/mlflow/  # Host-side MLflow wrappers (run_evaluation.py, ingest_results.py) — dev-only, never imported by submission/
experiments/      # CHANGELOG.md + per-run config snapshots
results/          # Native swegemma eval output (--results-dir target), gitignored
docs/             # Competition reference docs (Overview, Data, HARNESS_README)
agent-ideas/      # Planning docs
```

`requirements-dev.txt` holds dev-only dependencies (MLflow, kagglehub). Nothing
under `submission/` may depend on them — see `agent-ideas/claude-idea.md` step 2
and step 11 for the isolation checks that enforce this before packaging.

## Environment setup (plan step 1)

Requires **Python 3.13** (matches the sandbox container — `swegemma` won't
install on 3.11/3.12). Everything below assumes `source .venv/bin/activate`
first.

```
python3.13 -m venv .venv
source .venv/bin/activate
pip install kagglehub
```

The venv's `activate` script has a project-specific line appended exporting
`KAGGLEHUB_CACHE` so all kagglehub downloads land in `downloads/` (gitignored)
instead of the global `~/.cache/kagglehub`.

**Kaggle auth**: `python3 -c "import kagglehub; kagglehub.login()"` — prompts
for an API token (from kaggle.com/settings → API), writes it to
`~/.kaggle/access_token`. Do this once per machine; never paste the token in
chat/logs.

**Competition dataset**: `kagglehub.competition_download('gemma-4-developer-agent')`
→ `downloads/kagglehub/competitions/gemma-4-developer-agent/` (~21 GB: tasks,
snapshots, graphs, embeddings, wheels, docker specs, sample_submission).

**Harness packages (`swegemma`, `adk_submission`, `adk_eval_core`)**: these are
**not on PyPI** and **not in the competition dataset** — they're not mentioned
anywhere in `HARNESS_README.md`/`Overview`/`Data` either. They live in a
separate Kaggle *dataset* (a "wheelhouse") that only surfaces by pulling the
organizer's getting-started notebook source:

```
kaggle kernels pull ryanholbrook/getting-started-gemma-4-developer-agent -p downloads/kaggle-kernels
```

That notebook's first cell references
`/kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse` — i.e. the
Kaggle dataset handle `metric/gemma-4-developer-agent-wheelhouse`:

```python
import kagglehub
kagglehub.dataset_download('metric/gemma-4-developer-agent-wheelhouse')
```

That wheelhouse (~827 MB) contains ~41 wheels. Most (`vllm`, `bitsandbytes`,
`flashinfer`, `apache_tvm_ffi`, etc.) are CUDA/`manylinux_x86_64`-only — for
the real official-model vLLM serving on rented GPU hardware, not needed on the
Mac. The four we actually need are pure-Python (`py3-none-any`):

```
pip install \
  downloads/kagglehub/datasets/metric/gemma-4-developer-agent-wheelhouse/versions/<N>/adk_eval_core-0.1.0-py3-none-any.whl \
  downloads/kagglehub/datasets/metric/gemma-4-developer-agent-wheelhouse/versions/<N>/adk_submission-0.2.11-py3-none-any.whl \
  downloads/kagglehub/datasets/metric/gemma-4-developer-agent-wheelhouse/versions/<N>/swegemma-0.2.7-py3-none-any.whl \
  downloads/kagglehub/datasets/metric/gemma-4-developer-agent-wheelhouse/versions/<N>/google_adk-1.36.1-py3-none-any.whl
```

This installs the `swegemma` CLI into the venv (`swegemma eval ...`).

**Docker**: needs to be running for `--sandbox docker` (native `arm64` on
Apple Silicon; falls back to `--platform linux/amd64` emulation only if a
repo's wheels are x86_64-only — see `agent-ideas/claude-idea.md` step 1).
