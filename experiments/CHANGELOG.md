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

## 2026-09-29 — 2026-09-29_wrapper-smoke
- Hypothesis: Validate the `devtools/mlflow/run_evaluation.py` + MLflow logging
  wrapper end-to-end using the same 4-task smoke cohort from the step-1
  structural test. First attempt caught a real bug: a freshly-created MLflow
  experiment defaulted to a local-filesystem artifact root the client
  couldn't write to, and the error handling was too coarse (one failed
  artifact call aborted the whole parent run, losing already-logged
  tags/metrics). Fixed by explicitly creating experiments with a proxied
  `mlflow-artifacts:` location and making artifact logging fail-soft per call.
- Change: `swegemma eval --sandbox docker --skip-agent-patch` against task(s)
  fastapi_15661, requests_7505, rich_4070, httpx_3672, backend=none,
  env=local-mac, fidelity=structural.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/4 (expected — same
  `--skip-agent-patch` semantics as the step-1 structural test). Verified via
  REST API: parent run `FINISHED` with all 3 expected artifacts
  (config_snapshot/, summary.json, task_results.jsonl); 4 child runs
  `FINISHED` with correct tags/metrics; the one checked child run
  (fastapi_15661, unresolved) correctly had its trace + test-output log
  attached per the fail-only artifact policy.
- Results dir: `results/2026-09-29_wrapper-smoke/`
- Commit: `58194788c7a4a8858b7070b660877099743e4d4b` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/749cdfb2c02f42d5a3a1020e5bb821c2

## 2026-09-29 — 00_baseline-structural
- Hypothesis: Validate the full harness pipeline (snapshot extraction, editable install, wheel resolution, pytest execution) across all 129 tasks natively on arm64, not just the 4-task sample tested in steps 1-2. Establishes the Mac structural baseline per plan step 3.
- Change: `swegemma eval --sandbox docker --skip-agent-patch` against the full task set, backend=none, env=local-mac, fidelity=structural.
- Cohort: full-129
- Result: proxy_resolution_rate=0.031, resolved=4/129
- Results dir: `results/00_baseline-structural/`
- Commit: `ad32741c65e05a84e7a4d1ea57e8f61264e4a607`
- MLflow: http://localhost:5001/#/experiments/9/runs/9dad7e3c3a2b428699bc402bcd8e27d9

### Analysis addendum (resource profile + findings, per step 3)
- **Wall clock**: 19.5 min for all 129 tasks at `--concurrency 3` (07:57:39 →
  08:17:10). Sum of per-task durations (serial-equivalent) is 2639.6s (~44
  min) — concurrency-3 gave ~2.25x speedup, short of the ideal 3x due to
  container overhead and two long-tail stragglers (see below). **This is
  structural-only timing (no model calls) — not a proxy for real-agent
  runtime**, which will be dominated by inference/tool-call latency, not
  container setup. Don't compare this number against a future real-agent
  projected runtime.
- **Exit code breakdown** (`test_exit_code` across all 129):
  `{2: 70, 1: 52, 0: 4, 137: 2, 124: 1}`. `errors: 0` in `summary.json` only
  counts harness-level errors — it does NOT surface timeouts (124) or
  OOM-kills (137), both of which showed up here. Don't rely on `errors: 0`
  alone to mean "nothing went wrong."
  - **Exit 2** (70 tasks, mostly `fastapi`): pytest collection errors —
    expected under `--skip-agent-patch` (test files reference code that only
    exists after the fix).
  - **Exit 1** (52 tasks): normal test failures — expected Fail-to-Pass
    behavior.
  - **Exit 124 / 137** (3 tasks, all `Textualize/rich`): `rich_4006` hit the
    300s default command timeout; `rich_3772` and `rich_3480` were SIGKILL'd
    (137), almost certainly the sandbox's 4GB RAM cap per HARNESS_README
    §4.1. All three in one repo — `rich`'s test suite is the one most likely
    to strain the resource-constrained sandbox even for a real agent run,
    independent of model quality. Worth budgeting extra timeout/memory
    margin for `rich` tasks specifically.
- **Dataset-curation finding — 4 tasks resolve with zero code changes**:
  `requests_7427`, `requests_7315`, `requests_7309`, `rich_3468` all pass
  their full test suite (`test_exit_code=0`) with `agent_patch_size=0` under
  `--skip-agent-patch`. Per `Data.md`'s own curation pipeline, the
  Fail-to-Pass check (`base_commit` + `test_patch`, no fix, tests must fail)
  should make this impossible — yet it happens for ~3.1% (4/129) of the
  public task set in our environment. Cause not yet isolated (could be a
  genuine curation gap, or a dependency-version difference between our
  `/wheels` resolution and the original curation environment). **Practical
  implication**: any future `resolution_rate`/`proxy_resolution_rate` should
  be read as "X%, of which up to ~3.1% would resolve even with a fully
  no-op agent" — these 4 tasks are candidates to exclude from the step-4
  comparison/held-out cohorts since they add noise unrelated to agent
  capability.
- **Repo breakdown**: `fastapi/fastapi` 0/67, `psf/requests` 3/13,
  `Textualize/rich` 1/48, `encode/httpx` 0/1 (only 1 httpx task in the public
  set total).

## 2026-09-29 — 2026-09-29_proxy-sanity
- Hypothesis: Sanity check: does gemma4:e4b via Ollama actually drive a real Container-A agent loop through swegemma eval, using the models.yaml alias override?
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_proxy-sanity/`
- Commit: `fe1e411cea8071a1253cada571d6d764bdf6d997` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/e3486875ae6e4a9a9731450941bc37d1

## 2026-09-29 — 2026-09-29_proxy-sanity
- Hypothesis: Sanity check: does gemma4:e4b via Ollama actually drive a real Container-A agent loop through swegemma eval, using the models.yaml alias override (now covering main_lora/tool_lora too)?
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_proxy-sanity/`
- Commit: `fe1e411cea8071a1253cada571d6d764bdf6d997` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/07c58c5020ce4361856e9c7ccda9ff20

## 2026-09-29 — 00_baseline-proxy-model
- Hypothesis: Mac proxy-model baseline (plan step 3): real Container-A agent loop driven by gemma4:e4b via Ollama across the same 4-repo smoke cohort used for the structural baseline, to catch orchestration/tool-calling bugs. Not a solution-quality signal (logged as proxy_resolution_rate).
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, requests_7505, rich_4070, httpx_3672, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/4
- Results dir: `results/00_baseline-proxy-model/`
- Commit: `fe1e411cea8071a1253cada571d6d764bdf6d997` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/070aa0414c9b42239d444f4ad57755bd

## 2026-09-29 — 00_baseline-proxy-model
- Hypothesis: Mac proxy-model baseline, retried at --concurrency 1 after concurrency=2 caused all 4 tasks to hit the 5-min session timeout with almost no progress (3-4 tool calls each) -- testing whether Ollama serializes/contends under concurrent requests, unlike the model-free structural baseline which handled concurrency=3 fine.
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, requests_7505, rich_4070, httpx_3672, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/4
- Results dir: `results/00_baseline-proxy-model/`
- Commit: `fe1e411cea8071a1253cada571d6d764bdf6d997` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/af0b387e4a684deb8c14d05222e59ee9

### Analysis addendum — root cause found, concurrency hypothesis disproven
- Concurrency wasn't the cause: `--concurrency 1` (fully serial) produced the
  *same* 4/4 timeout pattern as `--concurrency 2`, including the same
  `fastapi_15661` task that had succeeded in 189.55s (3 tool calls, real
  patch submitted) during the isolated sanity test just before this. Same
  task, same model, same concurrency — different outcome. Not a contention
  artifact.
- **Real cause, found in `results/00_baseline-proxy-model/traces/trace_requests_7505.json`**:
  the model repeats near-identical reasoning across many consecutive steps
  ("The user wants to modify the `requests` library to add `hasattr`
  checks..." restated with minor rewording across 8+ of the 13 total steps)
  instead of acting decisively. `final_metrics`: 64,162 prompt tokens with
  49,686 (77%) cached — so KV-cache reuse is working and prefill isn't the
  bottleneck — but only 6,440 completion tokens across 13 steps, i.e. a lot
  of that generation budget goes to restating the same plan rather than
  making progress. One step tried `read_file` on a directory
  (`src/requests/`), got an error, and the model visibly struggled to
  recover efficiently afterward.
- **Practical implication for future proxy-model use**: `gemma4:e4b`'s
  failure mode here is a reasoning loop, not raw latency — matches exactly
  what the harness's own continuation-nudge design anticipates ("Do NOT
  repeat your prior reasoning in thought" per HARNESS_README §5.3), so the
  fix path is prompt discipline / stronger anti-repetition steering for
  small models, not a bigger time budget alone (though `--max-time-minutes 5`
  is almost certainly too tight for this model regardless — 0/5 attempts
  across both runs completed within it). Out of scope for this step-3
  checkpoint; relevant for step 6 (prompt engineering) if `gemma4:e4b`
  continues to be used for local orchestration debugging.
- **Net assessment of the proxy-model wiring itself**: fully validated
  independent of this finding — the isolated sanity run proved the
  `models.yaml` alias-override mechanism, Ollama routing, and real
  Container-A tool-calling all work correctly end-to-end (see the
  `2026-09-29_proxy-sanity` entry above). This session's finding is about
  the *model's* behavior under budget pressure, not the harness wiring.
