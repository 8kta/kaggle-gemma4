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
- Commit: `b7ce048`

## 2026-09-29 — Close step-1 validation gaps
- Hypothesis: the prior entry's "step 1 complete" was premature — package
  imports succeeding doesn't confirm the sandbox pipeline actually works, and
  nothing about the setup was reproducible without redoing manual archaeology.
- Change: (1) Wrote `devtools/setup_env.sh`, tested from a deleted `.venv` to
  confirm it's genuinely reproducible end-to-end. (2) Pinned all transitive
  deps to `requirements-lock.txt` (`pip freeze`, excluding the 4 wheelhouse
  packages whose local file paths aren't portable). (3) Fixed the `<N>`
  placeholder in README — setup script now resolves the wheelhouse version
  dynamically instead of hardcoding it. (4) Built and confirmed
  `swebench-sandbox:latest` from `docker/Dockerfile.sandbox` — this had never
  actually been built before. (5) Ran `swegemma eval --sandbox docker
  --skip-agent-patch` against one task per repo (fastapi, requests, rich,
  httpx) to validate the full container lifecycle without needing a model.
- Cohort: smoke (1 task × 4 repos, `--skip-agent-patch`).
- Result: `errors: 0` for all 4 tasks; `resolved: false` for all 4 (expected —
  no fix was applied). `test_exit_code`: 1 (requests, rich — normal pytest
  failure) or 2 (fastapi, httpx — pytest collection error, also expected:
  the failing test files reference code/attributes that only exist after the
  reference patch, which was deliberately skipped). All 4 ran natively on
  `arm64` — no `--platform linux/amd64` emulation triggered, no
  wheel/architecture errors. `swebench-sandbox:latest` confirmed `arm64/linux`
  via `docker inspect`.
- Results dir: `results/00_structural/`
- Commit: see below.
