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

## 2026-09-29 — Define evaluation cohorts (plan step 4)
- Hypothesis: N/A — this is discipline/documentation, not an eval iteration
  (per the plan, step 4 is explicitly "a discipline to follow, not
  infrastructure to build").
- Change: Wrote `devtools/define_cohorts.py` (one-shot, fixed-seed,
  repo-stratified sampling over the 129 public tasks) and ran it to produce
  `experiments/cohorts.json`: `smoke` (4, fixed = the tasks already used in
  steps 1-3), `held_out` (19, never to be inspected during prompt
  development), `prompt_dev` (21), `comparison` (19), `unassigned_pool` (66,
  no current purpose). Cross-referenced against the step-3 structural
  baseline's known-anomalous tasks (zero-code-change resolves, OOM/timeout)
  and flagged wherever they landed. Also wrote `experiments/CHAMPION.md`
  (champion-tracking convention, currently "none yet" — `submission/` is
  still empty) and `experiments/PROMOTION_CHECKLIST.md` (the literal
  hand-walked gate from config-validates through held-out to full-129).
- Cohort: N/A.
- Result: `held_out` avoided all 4 zero-code-change-resolve anomalies
  (clean); `prompt_dev` has 1 (`requests_7315`) and `comparison` has 2
  (`rich_3468`, `rich_3772` — the latter also OOM-killed in the structural
  baseline). Full caveat list in `cohorts.json`'s
  `known_anomalous_task_caveats_by_cohort`.
- Results dir: N/A.
- Commit: see below.

## 2026-09-29 — Analyze failure modes (plan step 5)
- Hypothesis: N/A — analysis of already-collected data, not a new eval
  iteration. Mined the 4 proxy-model-baseline traces
  (`results/00_baseline-proxy-model/traces/`) for the four failure
  categories from the plan (Navigation / Reasoning / Operational /
  Constraint). Note: the structural baseline (`--skip-agent-patch`) can't be
  used for this — no real agent reasoning/tool-calling happened there, so
  its failures aren't classifiable into these categories at all.
- Change: none — pure analysis.
- Cohort: smoke (the same 4-task cohort from the proxy-model baseline; only
  1 sample per repo, so per-repo conclusions here are illustrative, not
  statistically meaningful — a real repo-level breakdown needs a
  larger/completed cohort).
- Result — classification (all 4 tasks timed out at 5 min without
  submitting a patch, so every failure here is "didn't finish" rather than
  "finished with the wrong fix"):
  - **`fastapi_15661` — Navigation**: "I cannot list the files in the
    repository directory structure" — the model didn't recognize it could
    just run `ls`/`find` via `run_command`; combined with a genuinely vague
    problem statement ("👷 Automate release preparation", not a concrete bug
    report). Never figured out *where* to look.
  - **`rich_4070` — Operational (tool-call error)**: correctly identified
    the right fix in principle (defer imports via `TYPE_CHECKING` to reduce
    import time) but called `edit_file` with `old_string`/`new_string`
    swapped — a mechanical tool-invocation mistake, not a reasoning failure.
  - **`httpx_3672` — Operational (reasoning loop)**: near-identical
    restated analysis across steps 5/6/8/9 instead of acting — same pattern
    already found in `requests_7505` during step 3.
  - **`requests_7505` — Operational (reasoning loop)**: see step-3 entry
    above (77% cache hit rate, so not a latency/caching issue — genuinely
    repeats the same plan instead of progressing).
  - **Totals**: 3/4 Operational (2 reasoning-loop, 1 tool-syntax error),
    1/4 Navigation, 0/4 Reasoning-quality, 0/4 Constraint.
  - **Key finding**: with this stand-in model, failures cluster at the
    Operational layer *before* reasoning-quality issues even become
    visible — it never gets far enough (no task reached `edit_file` success
    + `submit_patch`) for "right file, wrong logic" to be observable. Per
    the plan's own mapping (Navigation → retrieval/graph-tool fixes,
    Operational → tool/budget/prompt fixes), this points squarely at
    prompt-level fixes first (anti-repetition steering, explicit
    `run_command`-for-exploration guidance, `edit_file` parameter
    examples) — not graph-tool investment — as the highest-leverage next
    step for this model, at least until those Operational failures clear
    and Reasoning-layer issues become visible to diagnose.
- Results dir: `results/00_baseline-proxy-model/` (same as step 3, no new
  run).
- Commit: see below.

## 2026-09-29 — 2026-09-29_step6-single-agent-v1
- Hypothesis: Does our new submission/agent.yaml compile correctly, and does the rewritten system.md (anti-repetition steering + explicit run_command exploration guidance + edit_file usage examples) fix fastapi_15661's step-5 Navigation failure ('I cannot list the files...')? Using a generous 15-min budget (vs the 5-min sanity budget) to isolate prompt-quality from budget-too-tight.
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step6-single-agent-v1/`
- Commit: `139ee5ac44e247845bf5281e8f3de90f6021796a` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/a4ecf979ae73482494194c032097b89a

## 2026-09-29 — 2026-09-29_step6-single-agent-v1
- Hypothesis: Retry after removing disallowed .gitkeep placeholders from submission/adapters,skills,sub_agents (caused a packaging validation error, not a model issue). Does our new submission/agent.yaml compile correctly, and does the rewritten system.md fix fastapi_15661's step-5 Navigation failure?
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step6-single-agent-v1/`
- Commit: `139ee5ac44e247845bf5281e8f3de90f6021796a` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/a2928d14ca844e3fb27ca1742d6f1f29

## 2026-09-29 — 2026-09-29_step6-single-agent-rich
- Hypothesis: Does the new edit_file usage guidance in system.md fix rich_4070's step-5 failure (correct fix identified, but old_string/new_string parameters swapped)?
- Change: `swegemma eval --sandbox docker` against task(s) rich_4070, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step6-single-agent-rich/`
- Commit: `139ee5ac44e247845bf5281e8f3de90f6021796a` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/6f1dc181c366401ba085ee443b44dfdb

### Analysis addendum (plan step 6 — architecture design)
- **Real packaging bug found and fixed**: the first `2026-09-29_step6-single-agent-v1`
  attempt failed immediately with `Sandbox execution error: File has
  disallowed extension '': adapters/.gitkeep` — the `.gitkeep` placeholders
  created back in the initial project scaffolding (`submission/adapters/`,
  `skills/`, `sub_agents/`) violate the harness's own file-extension
  allowlist. This would have broken a **real Kaggle submission** too, not
  just local testing — worth having caught now. Removed all three; empty
  dirs are fine untracked by git since they'll get real content in later
  steps.
- **Built `submission/agent.yaml` + `submission/prompts/system.md`** (single
  `LlmAgent`, no sub-agents — see architecture decision below), directly
  targeting step 5's evidenced failures: explicit anti-repetition steering,
  explicit `run_command`-for-exploration guidance for vague/PR-style
  problem statements, and worked `edit_file` old_string/new_string usage
  examples. `submission/configs/sampling.yaml` copied unchanged from
  `sample_submission` (already sensible: temp 0.2, 4096 thinking budget,
  16384 max output). No `eval_config.yaml` — relying on the harness's
  generous defaults (100 tool calls / 500 turns / 60 min) rather than
  `sample_submission`'s artificially tight demo values (1 min).
- **Re-tested the exact two step-5 failure cases with a generous 15-min
  budget** (vs. the 5-min sanity budget that couldn't distinguish
  "prompt is bad" from "budget is too tight"):
  - `fastapi_15661` (previously: Navigation failure, "I cannot list the
    files..."): **fixed**. This run explored `publish.yml`, `pyproject.toml`,
    `README.md`, `scripts/add_latest_release_date.py`, ran a script, and
    investigated a real `ModuleNotFoundError` — genuine incremental
    progress, not stuck. Still ran out of the 15-turn budget without
    submitting; this specific task (a vague PR-template with no concrete
    bug, and previously found in step 1 to have its own separate
    `scripts.prepare_release` collection-error quirk) looks like a
    consistently hard/atypical task, not a clean prompt-quality signal.
  - `rich_4070` (previously: Operational failure, `edit_file`
    old_string/new_string swapped): **partially fixed, new issue found**.
    The swap mistake did not recur. Also self-corrected a wrong file-path
    guess (404 on `logging.py` → retried `rich/logging.py` successfully).
    But hit a *different* `edit_file` failure this time — "old_string
    context was too large or complex... error about missing mandatory
    parameters" — and once blocked on that, fell back into the same
    repetitive-restatement pattern from step 5 (many turns re-stating
    "I have already read `rich/logging.py` and identified..." without a
    successful edit). Timed out at 15 min, 8 tool calls, no patch.
- **Architecture decision: single-agent, sub-agent ablation deferred.**
  The Code Analyzer sub-agent's value proposition is keeping `read_file`
  noise out of the root agent's context — but our currently-dominant
  failure mode (per the two re-tests above) is `edit_file` mechanics and
  residual repetition-under-difficulty, not context clutter from file
  exploration. Running the full single/+analyzer/+verifier/+both ablation
  matrix now would likely just measure the same operational noise across
  all four variants rather than discriminating between them. Proceeding
  with single-agent as the working architecture; revisiting the ablation
  later if Navigation/context-clutter failures become dominant once the
  current operational issues are addressed (plan step 7).
- Results dirs: `results/2026-09-29_step6-single-agent-v1/`,
  `results/2026-09-29_step6-single-agent-rich/`.

## 2026-09-29 — 2026-09-29_step7-rich-v2
- Hypothesis: step 7 v2 prompt: added explicit 'split old_string to <=5 lines' guidance + 'on 2nd edit_file failure, stop retrying and try something else' fallback. Does this fix rich_4070's 'old_string too large/complex' edit_file failure from the step-6 re-test?
- Change: `swegemma eval --sandbox docker` against task(s) rich_4070, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke (rich_4070 is in the `smoke` cohort per `cohorts.json`, not
  `prompt_dev` — mislabeled at launch time, corrected here; doesn't affect
  the run itself, only this metadata)
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step7-rich-v2/`
- Commit: `9e1afa814dbdf8003638b7b3a0500dba04213450` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/dcf3d2b09a2948b1acf32c4d092b45d8

## 2026-09-29 — 2026-09-29_step7-requests-v2
- Hypothesis: step 7 v2 prompt: added explicit 'on tool-call failure, change approach after 2 attempts, then submit_patch rather than keep looping' fallback. Does this fix requests_7505's step-3/5 pure reasoning-loop failure (restated the same plan across 8+ of 13 steps without acting)?
- Change: `swegemma eval --sandbox docker` against task(s) requests_7505, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step7-requests-v2/`
- Commit: `9e1afa814dbdf8003638b7b3a0500dba04213450` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/51ee9e2f59d142c2a88f90e6b8195bdf

### Analysis addendum (plan step 7 — first prompt-iteration round)
- **`edit_file` fix confirmed working**: `rich_4070` went from
  `agent_patch_size=0` (step 6) to `agent_patch_size=556` — real edits
  landed (`import logging` → `from __future__ import annotations`,
  removed an unused `Traceback` import), no more "old_string too large"
  failures. `test_exit_code=1` this time (a normal test failure from the
  harness's Phase 2 verification, not a collection error) — the patch is
  incomplete relative to the task (which needed multi-file changes; only
  `rich/logging.py` was touched before running out of the 15-turn budget)
  but the *mechanism* that was broken is fixed.
- **Anti-repetition fix: partial, changed shape rather than eliminated
  the problem.** `rich_4070`: after the successful edit, it fell into a
  *new* repetition pattern — restating "I have already: 1. Read... 2.
  Added..." across steps 9-16 without moving to the next required file
  or running a verification test, and never called `submit_patch`
  explicitly (harness's automatic fallback capture produced the patch at
  session end). `requests_7505`: the model repeated the *literal same*
  `grep -r "hasattr(data, \"read\")" src/requests/` command three times
  ("tried it twice"... "tried it three times") — directly against the new
  "don't resubmit the same arguments" instruction — then shifted to
  repeatedly re-reading `src/requests/adapters.py` without ever calling
  `edit_file`, despite explicitly claiming to have "confirmed the
  structure" multiple times. More real tool calls happened this round (14
  vs. 8 originally) and no pure-text-only turns, but the core failure —
  not translating understanding into a completed edit — persists.
- **Interpretation**: the v1 anti-repetition instruction addressed
  "restating reasoning with zero tool calls." It does not reliably stop a
  small model from repeating a *specific tool call* verbatim, or from
  stalling after real progress when a multi-step task requires deciding
  "what's next" rather than "recover from failure." Both are the same
  underlying limitation (this model struggles to track "what have I
  already tried" state precisely enough to act on it) wearing different
  clothes.
- **Not chased further this round** (time-boxed per the batching agreement
  — two hypotheses, two tests, stop and report): a next iteration could
  try making the "don't repeat the same call" rule use a stronger,
  more concrete trigger (e.g. "if your last tool call's arguments matched
  a previous one exactly, that is disallowed — choose a different
  file/approach before calling any tool again") rather than the current
  general framing, or try lowering `thinking_budget` to force shorter,
  more decisive turns instead of letting the model reason at length before
  each (repeated) action.

## 2026-09-29 — 2026-09-29_step7-requests-v3
- Hypothesis: step 7 v3 prompt: replaced the general 'don't repeat reasoning' framing with a mandatory mechanical pre-call check ('compare this call's exact args against every prior call this session; identical = forbidden'), covering both failed-and-repeated and succeeded-and-repeated cases. v2 failed to stop requests_7505 from literally repeating the same grep 3x -- does the more concrete/mechanical version stop it this time?
- Change: `swegemma eval --sandbox docker` against task(s) requests_7505, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step7-requests-v3/`
- Commit: `cd3b78c9643cb6de0a96b3f2dbedadafadde21e8` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/4cf217aa6f9b4c6782f5b868009c02ec

### Analysis addendum — first clean completion of the whole project
- **`error: null` — no timeout, no budget exhaustion, for the first time
  ever on a real (non-`--skip-agent-patch`) proxy-model run.** Finished in
  338.56s, well inside the 15-min budget, with a real `agent_patch_size=609`
  and `test_exit_code=1` (patch applied, tests ran and failed — not a
  collection error). `tool_calls=11`, down from 14 in the v2 attempt on the
  same task, i.e. *more efficient*, not just longer.
- **The mechanical rule worked where the general framing (v2) didn't.**
  `grep` was still run twice (not once), but critically the model *used*
  the second result this time ("The grep output provided several hits")
  instead of discarding it and re-running again — v2's literal 3x repeat on
  this exact task did not recur. It also caught its own confusion mid-task
  at step 13 ("Wait, the file path is `src/requests/adapters.py`, but the
  content was read from `src/requests/models.py`...") instead of plowing
  ahead — a qualitatively new kind of self-correction not seen in any prior
  trace this project.
- **First observed Reasoning-layer (not Operational) issue — exactly as
  step 5 predicted.** The generated fix changed
  `isinstance(fp, _SupportsRead) or hasattr(fp, "read")` →
  `isinstance(fp, _SupportsRead)` (dropped the `hasattr` fallback), while
  the task's title is "Add hasattr checks for remaining protocol isinstance
  checks" — plausibly the opposite of the intended direction. Step 5 noted
  the model "never gets far enough for a right-file-wrong-logic failure to
  become observable" while blocked at the Operational layer; this is the
  first task where it got far enough to potentially exhibit exactly that.
  Not confirmed as a genuine reasoning error without reading the task's
  full problem statement/reference patch — noted here as a new, different
  category of thing to watch for in future rounds, not chased further this
  round.
- **v3 prompt change kept** (the mechanical pre-call check superseding the
  v2 general framing) — this is the current state of `system.md` going
  forward.

## 2026-09-29 — 2026-09-29_skill-test
- Hypothesis: Does declaring a skills: field in agent.yaml work locally, given compile_submission() isn't passed a skill_registry in swegemma's agent_runner.py?
- Change: `swegemma eval --sandbox docker --skip-agent-patch` against task(s) fastapi_15661, backend=none, env=local-mac, fidelity=structural.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_skill-test/`
- Commit: `fefe269ad4e1b501702faa840f59b78dbe7402b2` (dirty worktree at run time)
- MLflow: (not logged — see stderr for reason)

## 2026-09-29 — 2026-09-29_skill-test2
- Hypothesis: Real compile_submission() test: does declaring skills: [skills/test_skill] in agent.yaml crash compilation, given no skill_registry is passed in swegemma's agent_runner.py? Tiny budget - we only need to see if it gets past compilation, not complete the task.
- Change: `swegemma eval --sandbox docker` against task(s) httpx_3672, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_skill-test2/`
- Commit: `fefe269ad4e1b501702faa840f59b78dbe7402b2` (dirty worktree at run time)
- MLflow: (not logged — see stderr for reason)

## 2026-09-29 — 2026-09-29_skill-test3
- Hypothesis: Retry with valid kebab-case SKILL.md frontmatter. Does compilation succeed now?
- Change: `swegemma eval --sandbox docker` against task(s) httpx_3672, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_skill-test3/`
- Commit: `fefe269ad4e1b501702faa840f59b78dbe7402b2` (dirty worktree at run time)
- MLflow: (not logged — see stderr for reason)

## 2026-09-29 — 2026-09-29_step8-skill-fastapi
- Hypothesis: step 8: added a repo-navigation SKILL with per-repo notes (load_skill_resource, references/<repo>.md), optional per the prompt. Does the model actually invoke it on fastapi_15661 (the task its fastapi.md notes specifically address), and does it help vs the step7-v2/v3 runs on this task?
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-skill-fastapi/`
- Commit: `fefe269ad4e1b501702faa840f59b78dbe7402b2` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/d6366dad924644128217c4b7d5ac2eaa

### Analysis addendum (plan step 8, part 1 — skills)
- **Skills verification (before this run)**: initially assumed skills weren't
  wired up in the local `swegemma eval` CLI path, since
  `swegemma/harness/agent_runner.py`'s `compile_submission()` call doesn't
  pass a `skill_registry` argument. This was **wrong** — confirmed
  empirically with a minimal probe skill: compilation invokes
  `resolve_skills()` independently and does validate/load skills correctly
  (Pydantic frontmatter validation caught a snake_case name + missing
  `description` on the first attempt; a corrected kebab-case skill compiled
  cleanly, with the `google.adk` `SKILL_TOOLSET` experimental feature
  activating). Ground-truth checked directly in
  `google/adk/tools/skill_toolset.py`: the actual tool signatures are
  `load_skill(skill_name)`, `load_skill_resource(skill_name, file_path)`,
  `run_skill_script(skill_name, file_path)` — resource files must live under
  a **`references/`** subfolder specifically (not `resources/`, which is
  what `HARNESS_README.md`'s illustrative example tree uses — that doc
  example is misleading; the runtime code is the ground truth).
- **Built `submission/skills/repo-navigation/`**: one `references/<repo>.md`
  file per target repo (fastapi/rich/requests/httpx), distilling everything
  learned in steps 1-7 (fastapi's vague-PR-statement + `docs_src/` +
  `scripts.prepare_release` collection-error gotcha; rich's resource-limit
  and exact-terminal-output sensitivity; requests' clean `src/requests/`
  layout and the zero-code-change-resolve curation quirk; httpx's thin
  evidence base). Wired into `agent.yaml` via `skills:`, mentioned as
  *optional* in `system.md`'s Think step (to avoid taxing every task with a
  mandatory extra tool call).
- **Result: the skill was never invoked.** Full tool-call sequence for this
  run: `run_command(ls)` → `read_file(publish.yml)` → `read_file(README.md)`
  → `run_command(grep version)` → `run_command(grep __version__)` →
  `read_file(__init__.py)` → `edit_file(bump version)` →
  `run_command(pytest tests/)` → `submit_patch()`. No `load_skill`/
  `load_skill_resource` call anywhere. The clean completion here (see next
  bullet) is attributable to the already-validated v3 anti-repetition fix,
  **not** the skill — "optional" means it's untested, not proven useless.
  Would need either a mandatory-load variant or a larger sample to get real
  signal on whether it helps.
- **New finding, unrelated to skills**: the agent ran `pytest tests/` — a
  bare, full-repo sweep — directly against the existing "NEVER run bare
  pytest" rule in `system.md`. `test_exit_code=2` (collection error) is
  plausibly the exact `scripts.prepare_release` import issue that
  `references/fastapi.md` already documents — content that would have
  helped here but was never loaded (see above). Not chased further this
  round; candidate for a future prompt-iteration round (make the "no bare
  pytest" rule more mechanical, mirroring what worked for anti-repetition
  in step 7 round 2).
- **Positive, separate from the skill**: **2nd** consecutive
  agent-loop-finished-cleanly run (`error: null` — not "resolved", still
  `false`; correction: an earlier version of this entry said "3rd" — there
  was never a run labeled "2nd", the compile-only skill probes in between
  were deliberate structural/budget checks, not real attempts, so I
  miscounted) — `264.72s`, real 347-byte patch, only 8 tool calls (down from
  step 6's 11-tool-call non-completion on this exact task), and the **first
  explicit `submit_patch()` call** seen in any trace this project (all prior
  "successful" runs relied on the harness's automatic fallback capture). The
  v3 prompt fix continues to compound.

## 2026-09-29 — 2026-09-29_step8-pytest-fix
- Hypothesis: Replaced the soft 'never run bare pytest' framing with a mechanical pre-call check (literal yes/no on whether the pytest command string contains a .py path or -k/:: selector), mirroring the technique that fixed anti-repetition in step 7 round 2. Does this stop the bare 'pytest tests/' call seen on this exact task in the prior run?
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-pytest-fix/`
- Commit: `79d4524cae51017541652dec12a5fae176962843` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/83eb7ee211744408bb9818fc510b87f7

### Analysis addendum — mechanical fix confirmed working
- **Confirmed via full tool-call listing: zero `pytest`/`unittest` calls of
  any kind this run** (`ls` → `read_file`×3 → `search_similar_code` →
  `edit_file` → `ls scripts/` → `write_file(scripts/bump_version.py)` →
  `run_command(python scripts/bump_version.py)` → `submit_patch()`). The
  prior run's bare `pytest tests/` violation did not recur — the same
  mechanical-check technique that fixed anti-repetition in step 7 round 2
  (literal yes/no check on the command string, not a soft "don't do X")
  worked again here.
- **3rd consecutive clean agent-loop finish** (`error: null`), 513.14s (well under
  budget), `agent_patch_size=3072` — a substantially larger, more
  substantive patch than the 347-byte version from the same task two runs
  ago. `test_exit_code=2` persists (same `scripts.prepare_release`
  collection-error quirk documented since step 1 — a pre-existing harness/
  task issue, not something either prompt change could fix).
- **Secondary observation, not chased further**: with no obvious targeted
  test available for this task, the agent skipped the Verify step
  entirely rather than running anything resembling a broad sweep — a
  reasonable trade-off given the new forbidden-pattern rule, but means
  "Verify" isn't reliably happening when no clear test target exists. This
  specific task (`fastapi_15661`) has been atypically hard throughout the
  whole project (vague problem statement, no clear test, collection-error
  quirk) — plausibly more about task difficulty than a new prompt defect.
  Candidate for a future round: explicit guidance on what to do when no
  targeted test is obvious (e.g. write and run a small inline assertion
  instead of skipping verification outright).

## 2026-09-29 — 2026-09-29_step8-skill-mandatory
- Hypothesis: Made repo-navigation skill loading mandatory (first tool call every task) instead of optional, since the prior optional framing meant it was never invoked. Same task (fastapi_15661) as the immediately prior run for direct comparison. Does the agent actually load it now, and does having the fastapi.md notes (which specifically warn about the scripts.prepare_release collection-error quirk and the vague-PR-statement pattern this task has) change its behavior/efficiency?
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-skill-mandatory/`
- Commit: `dd7a165e88c6e7c17d2475148e2dd129869cef8b` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/88d6113519ef41ffa9c5b82040a0190f

### Analysis addendum — regression, and still no clear evidence the skill helps
- **The mandatory rule worked mechanically**: `load_skill_resource(skill_name="repo-navigation", file_path="references/fastapi.md")` was the very first tool call this run — confirmed via the full tool-call listing. So the "optional = never invoked" problem from the prior test is fixed at the mechanism level.
- **But this run broke the streak of 3 consecutive clean agent-loop finishes**:
  `error: "Agent exceeded turns budget (15 turns)"`, `agent_patch_size=0`,
  13 tool calls, 501.63s. Full tool sequence after loading the skill: explored
  `.github/workflows/build-docs.yml`, `pyproject.toml`, ran
  `search_similar_code`/`grep`, then made **three separate `edit_file`
  attempts on `README.md`** (different line ranges/content each time — looks
  like repeated struggling to land an edit on a badge/image URL), then
  pivoted to `scripts/docs.py` at the very end. It never touched
  `.github/workflows/publish.yml` — the file both of the two most recent
  *successful* runs on this exact task focused on (version bump /
  release-script approach).
- **Plausible but unconfirmed explanation**: `references/fastapi.md`
  mentions `docs_src/` for documentation tasks; this run may have
  interpreted the vague "Automate release preparation" statement as a
  documentation/README task instead of the version-bump interpretation that
  worked in the two prior runs — the skill notes may have introduced a
  distraction for this specific ambiguous task. Cannot be confirmed with
  n=1 — this exact task has previously shown run-to-run variance under
  *identical* settings (189s success vs. 300s+ timeout, back in step 7), so
  plain nondeterminism can't be ruled out either.
- **Conclusion for now**: no clear evidence the skill helps, one real
  fixed cost (an extra mandatory tool call every task, permanently), and a
  plausible (not confirmed) distraction risk on ambiguous tasks. Given
  this, reverting the skill-loading instruction from mandatory back to
  removed/optional-by-default is the more defensible default until there's
  positive evidence to justify the fixed cost — a proper verdict would need
  a larger sample (multiple tasks, several trials each) than the inference
  budget available for this round supports.

## 2026-09-29 — Fix snapshot/live-dir mismatch and label-reuse overwrite (audit item #3)
- Hypothesis: An external audit found two real bugs in `run_evaluation.py`:
  (a) `run_swegemma_eval` passed `args.submission_dir` (the live `submission/`)
  to `swegemma eval`, not the frozen `submission_snapshot/` — so the
  "exact config used" claim was false whenever `submission/` changed between
  snapshot time and eval start; (b) reusing a label silently `rmtree`'d the
  previous run's snapshot and results, breaking the "every modification must
  be versioned" principle. Confirmed 3 real duplicate labels already existed
  in this changelog (`step6-single-agent-v1`, `proxy-sanity`,
  `00_baseline-proxy-model`) as evidence.
- Change: `run_swegemma_eval` now takes and uses the snapshot path
  (`submission_dir_for_eval`), not the live dir; `mlflow_logging.log_eval_run`
  is now also given the snapshot dir for hashing, for the same reason. Added
  `archive_if_exists()`: if a label's `experiments/<label>/` or
  `results/<label>/` already exists, rename it to `..._superseded_<UTC
  timestamp>` instead of deleting it — no history is lost, but the label can
  still be reused for iteration (matches how this session has actually used
  labels throughout: same label, retry after a bug fix).
- Cohort: N/A — infra fix, verified with two back-to-back real test runs on
  the same label, not a real eval iteration (both test runs cleaned up after
  verification, along with this note's own placeholder changelog entries).
- Result: Verified both fixes empirically. Run 1: confirmed the actual
  `swegemma eval` subprocess command line used
  `--submission-dir .../experiments/<label>/submission_snapshot`, not
  `submission/`. Run 2 (same label): produced
  `[run_evaluation] NOTE: '<label>' already existed... archived the previous
  one to '<label>_superseded_20260929T235134Z'` for **both**
  `experiments/<label>/` and `results/<label>/`, with matching timestamps,
  and the run completed normally afterward.
- Results dir: N/A (cleaned up after verification).
- Commit: see below.
- Commit: `d23ed324efd3b6cf27c21913e9f616144ec346fc` (dirty worktree at run time)
- MLflow: (not logged — see stderr for reason)
