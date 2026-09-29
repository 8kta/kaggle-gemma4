# Experiment Changelog

One entry per iteration. See `agent-ideas/claude-idea.md` step 2 for the full
logging practice this supports.

Entry format:

```
## YYYY-MM-DD — <short label>
- Hypothesis: <what you expected this change to do>
- Change: <what actually changed — prompt/yaml/skill/adapter>
- Cohort: <smoke / prompt-dev / comparison / held-out / full-129>
- Result: <resolution_rate or proxy_resolution_rate, notable FAIL→PASS / PASS→FAIL>
- Results dir: `results/<run-label>/`
- Commit: `<git sha>`
```

---

## 2026-09-29 — Environment setup (plan step 1)
- Hypothesis: N/A — infrastructure setup, not an eval iteration.
- Change: Created `.venv` on Python 3.13 (required — `swegemma` needs >=3.12).
  Confirmed Docker running natively (`linux/aarch64`, no emulation needed yet).
  Installed `kagglehub`, authenticated, downloaded the competition dataset
  (21 GB) and the harness wheelhouse dataset (`metric/gemma-4-developer-agent-wheelhouse`,
  827 MB — not documented anywhere in the competition materials; found via the
  organizer's getting-started Kaggle notebook). Installed the four pure-Python
  wheels needed (`swegemma`, `adk_submission`, `adk_eval_core`, `google_adk`);
  skipped the ~37 CUDA-only wheels (vllm, bitsandbytes, etc. — rented-GPU work,
  not local). Consolidated all downloads under `downloads/` (gitignored),
  pointed via `KAGGLEHUB_CACHE` in the venv's activate script.
- Cohort: N/A.
- Result: `swegemma --help` runs; `swegemma`, `adk_submission`, `adk_eval_core`
  all import cleanly in the venv. No eval run yet.
- Results dir: N/A — full reproduction steps in `README.md` "Environment setup".
- Commit: see below.
