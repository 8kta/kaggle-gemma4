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

## 2026-09-30 — Pipeline check before step 8 retrieval ablation: `.DS_Store` broke submission validation
- Hypothesis: N/A — pipeline smoke test, not a real ablation data point.
- Change: N/A. A test run of the new `filesystem-only` ablation variant
  (`experiments/step8-retrieval-ablation/variants/filesystem-only/`) crashed
  per-task with `SubmissionValidationError: File has disallowed extension
  '': .DS_Store` — macOS Finder had dropped `.DS_Store` files into
  `submission/` and its subdirectories, and `cp -R submission/. <variant>/`
  copied them into all 3 ablation variant dirs. Same failure mode as the
  earlier `.gitkeep`-extension bug. Removed `.DS_Store` from `submission/`
  and all 3 variant dirs; this run's placeholder result (crash, not a real
  resolution/navigation outcome) has been deleted, not counted in the
  ablation.
- Cohort: N/A — infra fix, verified by re-running the same task after the
  fix (see next entry).
- Result: N/A.
- Results dir: N/A (deleted — not a valid data point).
- Commit: `28b8e59eff52a01171988af33a5895710d1d96c4` (dirty worktree at run time)
- MLflow: N/A (the placeholder MLflow run from the crashed attempt was not cleaned up remotely — harmless, just an orphaned experiment row).

## 2026-09-30 — 2026-09-29_step8-retrieval-filesystem-only-fastapi_15661
- Hypothesis: Step 8 retrieval ablation [filesystem-only] on fastapi_15661: Graph tools removed from agent.yaml + prompt/skill mentions stripped. Does removing graph-tool availability change tool-calls-before-first-file-open, redundant-read rate, or navigation time vs. hybrid?
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-retrieval-filesystem-only-fastapi_15661/`
- Commit: `28b8e59eff52a01171988af33a5895710d1d96c4` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/b2153ef36a4746ce9039e392ffc092df

## 2026-09-30 — 2026-09-29_step8-retrieval-hybrid-fastapi_15661
- Hypothesis: Step 8 retrieval ablation [hybrid] on fastapi_15661: Control arm: current shipping submission/ unchanged (all 9 tools, current prompt).
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-retrieval-hybrid-fastapi_15661/`
- Commit: `28b8e59eff52a01171988af33a5895710d1d96c4` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/5ac0b6e49f1d41ada63896ea9ebd6bae

## 2026-09-30 — 2026-09-29_step8-retrieval-hybrid-requests_7505
- Hypothesis: Step 8 retrieval ablation [hybrid] on requests_7505: Control arm: current shipping submission/ unchanged (all 9 tools, current prompt).
- Change: `swegemma eval --sandbox docker` against task(s) requests_7505, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-retrieval-hybrid-requests_7505/`
- Commit: `28b8e59eff52a01171988af33a5895710d1d96c4` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/1c8966a8b4c74417891924b6cd659774

## 2026-09-30 — 2026-09-29_step8-retrieval-hybrid-rich_4070
- Hypothesis: Step 8 retrieval ablation [hybrid] on rich_4070: Control arm: current shipping submission/ unchanged (all 9 tools, current prompt).
- Change: `swegemma eval --sandbox docker` against task(s) rich_4070, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-retrieval-hybrid-rich_4070/`
- Commit: `28b8e59eff52a01171988af33a5895710d1d96c4` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/1815ddd6245449b3ac3188b57b687c24

## 2026-09-30 — 2026-09-29_step8-retrieval-hybrid-httpx_3672
- Hypothesis: Step 8 retrieval ablation [hybrid] on httpx_3672: Control arm: current shipping submission/ unchanged (all 9 tools, current prompt).
- Change: `swegemma eval --sandbox docker` against task(s) httpx_3672, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-retrieval-hybrid-httpx_3672/`
- Commit: `28b8e59eff52a01171988af33a5895710d1d96c4` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/f089bdc8abbd42f793438ce50f18b34c

## 2026-09-30 — 2026-09-29_step8-retrieval-graph-first-fastapi_15661
- Hypothesis: Step 8 retrieval ablation [graph-first] on fastapi_15661: All 9 tools kept, but 'Locating Target Files' now mandates a graph-tool call (search_similar_code/get_code_neighbors) before the first read_file/grep whenever a symbol is extractable. Does forcing graph-first navigation reduce tool-calls-before-first-file-open vs. hybrid, or just add an extra call that doesn't pay for itself?
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-retrieval-graph-first-fastapi_15661/`
- Commit: `28b8e59eff52a01171988af33a5895710d1d96c4` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/580efbe518ad423e9995d920170b3b81

## 2026-09-30 — 2026-09-29_step8-retrieval-graph-first-requests_7505
- Hypothesis: Step 8 retrieval ablation [graph-first] on requests_7505: All 9 tools kept, but 'Locating Target Files' now mandates a graph-tool call (search_similar_code/get_code_neighbors) before the first read_file/grep whenever a symbol is extractable. Does forcing graph-first navigation reduce tool-calls-before-first-file-open vs. hybrid, or just add an extra call that doesn't pay for itself?
- Change: `swegemma eval --sandbox docker` against task(s) requests_7505, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-retrieval-graph-first-requests_7505/`
- Commit: `28b8e59eff52a01171988af33a5895710d1d96c4` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/f588bba74aaf4094895eb1b2d69057c9

## 2026-09-30 — 2026-09-29_step8-retrieval-graph-first-rich_4070
- Hypothesis: Step 8 retrieval ablation [graph-first] on rich_4070: All 9 tools kept, but 'Locating Target Files' now mandates a graph-tool call (search_similar_code/get_code_neighbors) before the first read_file/grep whenever a symbol is extractable. Does forcing graph-first navigation reduce tool-calls-before-first-file-open vs. hybrid, or just add an extra call that doesn't pay for itself?
- Change: `swegemma eval --sandbox docker` against task(s) rich_4070, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-retrieval-graph-first-rich_4070/`
- Commit: `28b8e59eff52a01171988af33a5895710d1d96c4` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/b85e93359e9a49e5b9744bdf8008ba53

## 2026-09-30 — 2026-09-29_step8-retrieval-graph-first-httpx_3672
- Hypothesis: Step 8 retrieval ablation [graph-first] on httpx_3672: All 9 tools kept, but 'Locating Target Files' now mandates a graph-tool call (search_similar_code/get_code_neighbors) before the first read_file/grep whenever a symbol is extractable. Does forcing graph-first navigation reduce tool-calls-before-first-file-open vs. hybrid, or just add an extra call that doesn't pay for itself?
- Change: `swegemma eval --sandbox docker` against task(s) httpx_3672, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-retrieval-graph-first-httpx_3672/`
- Commit: `28b8e59eff52a01171988af33a5895710d1d96c4` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/71ab48581b9542a694b90c679a0e1411

## 2026-09-30 — 2026-09-29_step8-retrieval-filesystem-only-requests_7505
- Hypothesis: Step 8 retrieval ablation [filesystem-only] on requests_7505: Graph tools removed from agent.yaml + prompt/skill mentions stripped. Does removing graph-tool availability change tool-calls-before-first-file-open, redundant-read rate, or navigation time vs. hybrid?
- Change: `swegemma eval --sandbox docker` against task(s) requests_7505, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-retrieval-filesystem-only-requests_7505/`
- Commit: `28b8e59eff52a01171988af33a5895710d1d96c4` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/12ec66287330428e9b1c625b3c643a83

## 2026-09-30 — 2026-09-29_step8-retrieval-filesystem-only-rich_4070
- Hypothesis: Step 8 retrieval ablation [filesystem-only] on rich_4070: Graph tools removed from agent.yaml + prompt/skill mentions stripped. Does removing graph-tool availability change tool-calls-before-first-file-open, redundant-read rate, or navigation time vs. hybrid?
- Change: `swegemma eval --sandbox docker` against task(s) rich_4070, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-retrieval-filesystem-only-rich_4070/`
- Commit: `28b8e59eff52a01171988af33a5895710d1d96c4` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/8ecb5b2d3d0c440481ae7943fad04de5

## 2026-09-30 — 2026-09-29_step8-retrieval-filesystem-only-httpx_3672
- Hypothesis: Step 8 retrieval ablation [filesystem-only] on httpx_3672: Graph tools removed from agent.yaml + prompt/skill mentions stripped. Does removing graph-tool availability change tool-calls-before-first-file-open, redundant-read rate, or navigation time vs. hybrid?
- Change: `swegemma eval --sandbox docker` against task(s) httpx_3672, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-29_step8-retrieval-filesystem-only-httpx_3672/`
- Commit: `28b8e59eff52a01171988af33a5895710d1d96c4` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/4b1db520f13442cd92a79d4b5cca3cc5

### Analysis addendum — step 8 retrieval ablation (filesystem-only vs. graph-first vs. hybrid)
Per plan step 8: "compare filesystem-only vs. graph-first vs. hybrid
navigation on the smoke/prompt-dev cohort. Track tool calls and tokens
spent before opening the first relevant file, redundant-read rate, and
total navigation time, alongside resolution rate." Ran all 3 arms x all 4
`smoke` tasks (12 runs total), `--fidelity proxy-model`, identical budgets
(10 min / 25 tool calls / 15 turns) across every run. Variant configs:
`devtools/retrieval_ablation/variants/{hybrid,filesystem-only,graph-first}/`
(hybrid = byte-identical copy of shipping `submission/`; filesystem-only =
`agent.yaml` drops the 3 graph tools + prompt/skill mentions stripped;
graph-first = all 9 tools, but "Locating Target Files" mandates a
graph-tool call before the first `read_file`/grep whenever a symbol is
extractable). Metrics computed by `devtools/analyze_retrieval_ablation.py`
by walking each run's trace JSON.

- **Pipeline bug found and fixed before any real runs**: `cp -R
  submission/. <variant>/` picked up macOS `.DS_Store` files, which broke
  `compile_submission`'s extension allowlist (`SubmissionValidationError:
  File has disallowed extension '': .DS_Store`) — same failure class as the
  earlier `.gitkeep` bug. Removed from `submission/` and all 3 variants.
- **Bash-tool timeout bug found mid-batch**: launched all 12 runs as one
  `run_in_background` Bash call with an explicit 600000ms (10 min) timeout,
  not realizing that ceiling applies even to backgrounded commands — it was
  killed after 8/11 remaining runs (`hybrid` all 4, `graph-first` all 4)
  had completed, mid-way through `filesystem-only`/`requests_7505`. Cleaned
  up the orphaned sandbox container and the one partial run (no
  `summary.json` — discarded, not counted), then relaunched the final 3
  runs via `nohup ... & disown` (fully detached from the Bash tool's
  process tree, immune to its 10-minute ceiling) with a persistent
  `Monitor` watching the log for completion/error markers.
- **Result**: `resolution_rate=0/4` for all three arms — no discriminating
  signal from resolution rate alone (consistent with every prior
  proxy-model run in this project; gemma4:e4b has not resolved a
  smoke-cohort task yet regardless of prompt/tool changes). The ablation's
  actual signal is in the navigation/behavioral metrics:

  | variant | mean tool calls before 1st file open | mean graph-tool calls/task | tasks reaching a fix attempt (edit_file/write_file) | mean redundant-read rate |
  |---|---|---|---|---|
  | hybrid | 0.50 | 0.25 (1/4 tasks used it, voluntarily) | 2/4 | 29.3% |
  | filesystem-only | 0.75 | 0 (correctly can't call them) | **4/4** | 28.9% |
  | graph-first | 1.75 | 0.75 (3/4 tasks used it — mandate worked) | **1/4** | 33.8% |

  Trace inspection (not just the aggregate table) explains graph-first's
  low fix-reach rate: it's two distinct failure modes, not one. On
  `fastapi_15661`, the graph-first agent ran an existing script
  (`scripts/add_latest_release_date.py`) instead of editing source, then
  called `submit_patch` anyway — a clean completion with no real fix (the
  "Anti-Patterns to Avoid" section already warns against this; it happened
  anyway). On `requests_7505` and `httpx_3672`, the graph-first agent fell
  into a severe **redundant-read loop** — 9-14 consecutive `read_file`
  calls on the same file (`adapters.py`, `_parsers.py`), varying only
  `start_line`/`end_line`, never reaching `edit_file` before the budget ran
  out. Notably, the *same* loop happened to `hybrid` on `httpx_3672`
  (64.3% redundant-read rate) — but **not** to `filesystem-only` on the
  same task, which read `_parsers.py` 4 times, then made 3 real `edit_file`
  calls and even attempted test verification (`pytest
  tests/test_parsers.py`), producing a 2025-byte patch vs. the read-loop
  arms' comparatively empty trajectories.
- **Mechanism note**: the existing "mandatory pre-call check" in
  `prompts/system.md` forbids repeating an *identical* tool call, but a
  `read_file` call with a different `start_line`/`end_line` slice of the
  same file technically isn't identical — so this specific redundant-read
  pattern slips past the current check. Worth tightening in a future
  step-7-style prompt round (not done here — out of scope for this
  ablation).
- **Caveats — do not over-read this**: n=4 tasks/arm, single trial each, no
  repeated runs — this project has already documented real run-to-run
  variance on identical settings (step 7, `rich_4070`: 189s success vs.
  300s+ timeout). The `httpx_3672` graph-tools-correlate-with-read-loops
  observation is n=1 per arm on one task — suggestive, not confirmed.
  Everything here is `--fidelity proxy-model` on the small `gemma4:e4b`
  stand-in; the official 31B model may not share this failure mode at all
  (per the standing scope caveat above the step 6 section of `README.md`).
- **Decision**: no change to the shipping `submission/agent.yaml` or
  `prompts/system.md` — the current hybrid/optional-graph-tool default
  showed no clear downside vs. filesystem-only except on the one
  `httpx_3672` case, and graph-first's forced-usage framing showed a real,
  measurable cost (delayed first file open, crowded-out fix attempts) for
  this specific stand-in model that may not generalize to the official
  model this submission actually ships against. Re-validate on the
  official-model Kaggle notebook path
  (`devtools/generate_official_baseline_notebook.py`) once that's run, and
  revisit the redundant-`read_file`-slice mechanical-check gap noted above
  in a future prompt-iteration round.
- Results dirs: `results/2026-09-29_step8-retrieval-{hybrid,filesystem-only,graph-first}-{fastapi_15661,requests_7505,rich_4070,httpx_3672}/` (12 dirs, individual entries above this addendum).
- Commit: see below.

## 2026-09-30 — Step 9 (part 1): LoRA training data — splits + reference-patch trajectory synthesis
- Hypothesis: N/A — data engineering, not an eval iteration. The stand-in
  model has resolved zero smoke-cohort tasks throughout this project (see
  every prior entry above), so there is no pool of real *successful*
  trajectories to train on yet. Per claude-idea.md step 9 / codex-idea.md
  phase 5, built the "synthetic trajectory" path instead: turn each task's
  reference `patch` (tasks.jsonl ships one per task) directly into the
  exact tool-call sequence that would produce it.
- Change:
  1. `devtools/define_lora_splits.py` — train/dev/validation split drawn
     exclusively from `cohorts.json`'s `unassigned_pool` (66 tasks, the one
     cohort step 4 didn't reserve for any evaluation purpose).
     `held_out`/`comparison`/`prompt_dev`/`smoke` are all excluded (not
     just `held_out`, which is all the plan explicitly named — the other
     three are excluded too since training on what's used to judge/tune
     candidates would contaminate those evaluations). Explicit leakage
     assertions run every time: splits are pairwise disjoint, exactly
     partition `unassigned_pool`, and none overlap a reserved cohort.
     Wrote `experiments/lora_splits.json`: train=46, dev=10,
     validation=10, repo-stratified, seed=20260930.
  2. `devtools/build_lora_trajectories.py` — hand-rolled unified-diff
     parser (no new dependency; the format is simple and bounded) turns
     each file's hunks into `write_file` (new files) or `edit_file`
     (modified files, one call per hunk) calls, prefixed by a `read_file`
     for modified files and followed by a targeted `run_command pytest
     <test file from test_patch>` + `submit_patch`. The user turn reuses
     the harness's own `build_agent_prompt()` (same function
     `agent_runner.py` calls at real eval time) so the SFT prompt format
     exactly matches production, not a hand-approximated guess.
  3. **Every trajectory is verified before being written, not just
     assumed correct**: the synthesized edit_file/write_file sequence is
     replayed in-memory (real string substitution) against the actual
     pre-patch snapshot content, and the result is checked byte-for-byte
     against a real `git apply` of the reference patch in a copy of the
     same snapshot (snapshots are real git repos — confirmed via `tar -tzf`
     showing `.git/`). A task that can't be verified this way is skipped
     and logged, never silently included.
  4. Two real parser bugs found and fixed via this verification, not by
     inspection: (a) this dataset's "new file" patches don't consistently
     use `--- /dev/null` — some use a real-looking `--- a/<path>` header
     and signal "new file" only via the hunk (`@@ -0,0 ...` with zero old
     lines); fixed by also checking the hunk shape. (b) some patches lack
     a trailing newline after the final line, which `git apply` rejects
     as "corrupt patch" even though the diff content itself is valid;
     fixed by ensuring a trailing newline before feeding `git apply`
     (parser itself was unaffected — `str.splitlines()` doesn't care).
- Cohort: N/A (training data, drawn from `unassigned_pool`, disjoint from
  every eval cohort — see leakage assertions above).
- Result: 62/66 tasks (93.9%) produced a verified trajectory: train 44/46,
  dev 9/10, validation 9/10. The 4 skips are logged in
  `experiments/lora_training_data/{split}_skipped.jsonl`, not silently
  dropped: 3 are `edit_file`-shaped ambiguity (a hunk's old_string isn't
  unique in the file — the same real limitation `edit_file` itself would
  hit), 1 (`rich_3930`) is a genuine fidelity-check failure on a huge
  (308 KB, 29-hunk) patch touching an auto-generated Unicode width table
  (`rich/_cell_widths.py`) — root cause not chased further given the small
  residual (1/66) and that the check correctly caught and excluded it
  rather than shipping wrong data.
- Results dir: `experiments/lora_training_data/{train,dev,validation}.jsonl`
  (gitignored — deterministically regenerable from `tasks.jsonl` +
  `experiments/lora_splits.json` + `submission/prompts/system.md` via
  `devtools/build_lora_trajectories.py --split <name>`, same reproducibility
  posture as `results/`). Dataset hashes: train
  sha256=131b0357f4e11411... (44 trajectories, 841535 bytes), dev
  sha256=f65fff31040eec79... (9 trajectories, 207729 bytes), validation
  sha256=8a575530dbf9a73c... (9 trajectories, 153722 bytes).
- Commit: see below.
- **Still pending (step 9 part 2, not done here)**: actual LoRA/PEFT
  training needs a real GPU this Mac doesn't have — same constraint as the
  official-model baseline (step 3). Will need a Kaggle-notebook-based
  training run mirroring `devtools/generate_official_baseline_notebook.py`,
  targeting ranks 16/32 on `q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj`
  per `docs/HARNESS_README.md` §3.4's sizing table, with the resulting
  adapter evaluated against the `comparison` cohort before promotion per
  `PROMOTION_CHECKLIST.md`. Not started.

## 2026-09-30 — 2026-09-30_official-smoke-v1 (first official-model baseline)
- Hypothesis: First real official-model (`gemma-4-31b-it-qat-w4a16-ct`) run
  on the 4-task smoke cohort, via a personal Kaggle notebook
  (`devtools/generate_official_baseline_notebook.py`). Does the config
  that's only ever been proxy-tested on `gemma4:e4b` actually work against
  the real model?
- Change: none to the config being tested — this run used the submission as
  of commit `87fa3ad58c5c6e91887f210a53950dc814552e21` (the state at
  notebook-generation time), confirmed byte-identical to the locally
  committed `submission/` at that commit via `diff -r` before ingestion.
- Cohort: smoke, via Kaggle notebook, GPU accelerator varied across
  attempts (T4 x2 rejected for `bfloat16` — compute capability 7.5 < 8.0 —
  before landing on a 4-GPU accelerator that started cleanly with `tp=4`).
- Result: `resolution_rate=0/4`, `errors=4`. **3 of 4 tasks
  (`fastapi_15661`, `rich_4070`, `httpx_3672`) crashed with the identical
  `litellm.ContextWindowExceededError`**: "maximum context length is 32768
  tokens... requested 16384 output tokens and your prompt contains at
  least 16385 input tokens" — i.e. `submission/configs/sampling.yaml`'s
  `max_output_tokens: 16384` reserves exactly half the 32768-token context
  window on *every* turn, and real multi-turn conversations against the
  actual 31B model (real file-read content, real thinking traces) grew
  past the remaining 16384-token input budget by turn 8-10. The 4th task
  (`requests_7505`) didn't hit this — it cleanly exhausted its 15-turn
  budget instead (`tool_calls=14`, `duration=338.36s`), no crash.
  **The small `gemma4:e4b` proxy-model stand-in never surfaced this in any
  prior run this whole project** — its conversations never grew large
  enough, or Ollama's context handling differs from vLLM's strict
  enforcement. This is exactly the kind of official-model-only finding the
  standing scope caveat (top of this file, above the step 6 section) warned
  could exist.
- **Fix applied**: `submission/configs/sampling.yaml` `max_output_tokens`
  16384 → 8192, leaving 24576 tokens of input headroom instead of 16384
  (was already insufficient for even ~8-10 turns on the real model).
  `thinking_config.thinking_budget` (4096) left unchanged — still a strict
  sub-portion of the new, smaller `max_output_tokens`, so real completion
  text still has headroom beyond thinking. Not yet re-validated against
  the official model (needs another Kaggle-notebook run — expensive, not
  done reflexively after every local-only config edit).
- Results dir: N/A locally (ran on Kaggle, not `devtools/mlflow/run_evaluation.py`)
  — results downloaded and ingested via
  `devtools/mlflow/ingest_results.py --results-dir manual_kaggle_results/extracted/results/results
  --submission-snapshot manual_kaggle_results/extracted/submission/submission
  --git-commit 87fa3ad58c5c6e91887f210a53950dc814552e21
  --backend gemma-4-31b-qat --env kaggle-notebook --fidelity official-model`.
- Commit: `87fa3ad58c5c6e91887f210a53950dc814552e21` (submission/ was clean —
  confirmed via `git status --short submission/` and a `diff -r` against the
  downloaded submission snapshot before ingesting, so this commit accurately
  describes what ran, unlike every prior local run this project which always
  had a dirty worktree at run time).
- MLflow: http://localhost:5001/#/experiments/9/runs/cd3f6aec2be6458d8cd072080faf7b4d

## 2026-09-30 — 2026-09-30_official-smoke-v2 (context-window fix validated)
- Hypothesis: Re-run of `2026-09-30_official-smoke-v1` after fixing
  `max_output_tokens` 16384 → 8192 (fixed the `ContextWindowExceededError`
  that crashed 3/4 tasks last time). Does the fix hold?
- Change: none — same commit's submission, this is a re-run to validate
  the prior fix, not a new config change.
- Cohort: smoke, official model, Kaggle notebook (4-GPU accelerator,
  Internet off).
- Result: **fix confirmed — zero `ContextWindowExceededError` crashes this
  time**, on any of the 4 tasks. `resolution_rate=0/4` still, but the
  failure mode changed entirely:
  - `fastapi_15661`, `requests_7505`, `rich_4070`: cleanly exhausted the
    15-turn budget (`tool_calls=14` each) — no crash, same "clean
    completion, unresolved" pattern seen throughout proxy-model testing,
    now confirmed on the real model too.
  - `httpx_3672`: **first-ever fully clean completion on the real official
    model** — `error=None`, submitted within 11 tool calls, well under
    budget. Not resolved, but the agent loop itself worked end-to-end:
    explored, edited, verified, submitted, returned a final text response.
  - `errors: 3` in `summary.json` counts the 3 turn-budget-exhaustion
    outcomes as "errors" too (the harness doesn't distinguish "crashed"
    from "ran out of budget" in that field) — don't read `errors: 3` as
    "3 crashes"; it's 0 crashes, 3 budget-outs, 1 clean submit.
- Results dir: N/A locally — ingested from
  `manual_kaggle_results/extracted/results/results` (downloaded from the
  same Kaggle notebook run, re-executed top-to-bottom with the fixed
  `submission/configs/sampling.yaml` embedded).
- Commit: `7ad5019be8e7a91f0777775b32566e6571812b47` (submission/ clean,
  confirmed via `diff -r` against the downloaded snapshot before ingesting).
- MLflow: http://localhost:5001/#/experiments/9/runs/d146253fc73740d3ac70122a9c07efda

## 2026-09-30 — 2026-09-30_official-comparison-v1 (first-ever task resolutions)
- Hypothesis: First official-model run on the larger `comparison` cohort
  (19 tasks, vs. the 4-task `smoke` sample). Does `resolution_rate` move
  off 0, and does the `max_output_tokens=8192` fix (validated on smoke)
  hold at this scale?
- Change: none — same commit's submission as the smoke v2 validation run.
- Cohort: comparison (19 tasks: 10 fastapi/fastapi, 2 psf/requests,
  7 Textualize/rich), via Kaggle notebook
  (`devtools/generate_official_comparison_notebook.py`), same budgets as
  every prior official-model run (15 min / 25 tool calls / 15 turns),
  concurrency=1.
- Result: **`resolution_rate=2/19 (10.5%)` — the first task resolutions
  anywhere in this project**, proxy-model or official-model. Both verified
  non-trivial (not the known zero-diff-resolves anomaly, not in
  `KNOWN_ANOMALOUS`): `fastapi_14492` (391-byte patch, `test_exit_code=0`,
  12 tool calls, 100.2s, clean completion) and `rich_3518` (529-byte patch,
  `test_exit_code=0`, 14 tool calls, 120.4s, clean completion).
  - **16 of the remaining 17 tasks cleanly exhausted the 15-turn budget**
    (no crash) — and strikingly, every single one used *exactly* 14 tool
    calls before hitting the turn cap. That consistency suggests the
    **turn budget, not the 25-tool-call budget, is the actual binding
    constraint** for this model/prompt combination — worth testing
    `max_turns` higher in a future round to see if more tasks would
    resolve given more turns, independent of any prompt change.
  - **The `max_output_tokens=8192` fix reduced but did not eliminate the
    context-window crash**: `fastapi_14186` hit the identical
    `ContextWindowExceededError` again — "requested 8192 output tokens
    and your prompt contains at least 24577 input tokens" (24577+8192 =
    32769 > 32768). Only 7 tool calls but 351.5s duration — a
    verbose/long-thinking trajectory can still exhaust even the reduced
    reservation. Frequency dropped from 3/4 (75%) on the smoke v1 run to
    1/19 (5.3%) here — a real improvement, not a full fix. Candidate
    follow-up: lower `max_output_tokens` further, or (better) investigate
    whether thinking-token usage can be bounded more tightly per-turn
    rather than shrinking the ceiling for every task uniformly.
  - `errors: 17` in `summary.json` = 16 turn-budget-exhaustions + 1
    context-window crash — same counting caveat as before, don't read it
    as "17 crashes."
- Results dir: N/A locally — ingested from
  `manual_kaggle_results/extracted/results/results` via
  `devtools/mlflow/ingest_results.py --cohort comparison`.
- Commit: `4f8c05d05df5a5289b41f718524a5502b34787d6` (submission/ clean,
  confirmed via `diff -r` against the downloaded snapshot before ingesting).
- MLflow: http://localhost:5001/#/experiments/9/runs/904e7c404d464e12bd42cdb71b897594

## 2026-09-30 — 2026-09-30_official-maxturns-v1 (max_turns experiment: mixed, not a clean win)
- Hypothesis: 16/17 unresolved `comparison`-cohort tasks exhausted
  `max_turns=15` at *exactly* 14 tool calls each, suggesting turns (not
  the 25-tool-call budget) is the binding constraint. Tests `max_turns`
  15 → 25 in isolation on the `smoke` cohort (`max_tool_calls` 25 → 35 and
  `max_time_minutes` 15 → 25 also raised, purely so neither becomes a new
  hidden constraint in place of turns — not themselves under test). Does
  `resolution_rate` improve?
- Change: `devtools/generate_official_maxturns_notebook.py` — same
  submission, same smoke cohort, only the three budget values raised.
- Cohort: smoke (4 tasks), official model, Kaggle notebook.
- Result: **`resolution_rate` stayed `0/4` — not a clean win, but not a
  clean null result either.** Per-task, the extra budget cut both ways:
  - `requests_7505` and `rich_4070` **got substantially further**: 24 tool
    calls each (up from 14), used the *entire* new 25-turn budget, and
    produced real, sizeable patches (5866 and 3615 bytes) with
    `test_exit_code=1` (genuinely attempted and tested, just didn't pass)
    — vs. turn-budget-exhaustion with no patch detail logged last time.
    Real signal that turns *was* constraining these two specifically.
  - `fastapi_15661` and `httpx_3672` **got worse** — both now hit
    `ContextWindowExceededError` (the same error from the smoke v1 /
    comparison-v1 runs) instead of their previous outcomes.
    `fastapi_15661` previously cleanly exhausted the 15-turn budget; now
    the extra room let its context grow past the `max_output_tokens=8192`
    reservation before finishing (crashed at 15 tool calls). `httpx_3672`
    was this project's **only prior clean completion** — now it crashed
    at just 6 tool calls (but 296s — unusually slow per-call, consistent
    with a verbose trajectory), zero patch produced. This could be
    n=1 run-to-run variance (temperature=0.2, not deterministic) rather
    than a direct causal effect of the turns change — can't rule that out
    at this sample size, but the direction (more turns -> more chances to
    grow past the context ceiling before finishing) is mechanistically
    plausible independent of variance.
- **Interpretation**: raising `max_turns` alone doesn't safely help while
  `max_output_tokens` stays fixed — more turns means more opportunities
  for context to grow past the ~24576-token input headroom before the
  task finishes, trading "ran out of turns" failures for
  "context-window crash" failures on some tasks while genuinely helping
  others get further. A real fix likely needs `max_turns` raised
  *alongside* a context-budget-aware mechanism (shrinking
  `max_output_tokens` further, or truncating/summarizing older turns)
  rather than either knob in isolation. n=4, one trial — not enough to
  confirm the exact mechanism, just enough to say "raise max_turns alone"
  isn't a safe, unambiguous win.
- Results dir: N/A locally — ingested from
  `manual_kaggle_results/extracted/results/results` via
  `devtools/mlflow/ingest_results.py --cohort smoke`.
- Commit: `a37dbce3d814d601b93907d66dac4ada7f3922a6` (submission/ clean,
  confirmed via `diff -r` against the downloaded snapshot before ingesting).
- MLflow: http://localhost:5001/#/experiments/9/runs/0edd9f7265d54cccadf2e3df5ada4a38

## 2026-09-30 — Step 9 (part 2): LoRA training notebook — build + first-run debugging
- Hypothesis: N/A — infrastructure build, not an eval iteration. Building
  the actual GPU training step (data pipeline from step 9 part 1 already
  done) to test whether a LoRA adapter trained on the 44 verified
  reference-patch trajectories can improve on the 10.5% comparison-cohort
  resolution rate.
- Change: new `devtools/generate_lora_training_notebook.py` — QLoRA
  (4-bit NF4 via `bitsandbytes`+`transformers`+`peft`, no `trl`) on the
  `train`/`dev` splits. Base model `gemma-4-31b-it-qat-q4_0-unquantized`
  (transformers framework) — chosen specifically because it's the
  QAT-trained checkpoint before W4A16 packing, matching the competition's
  required serving checkpoint `gemma-4-31b-it-qat-w4a16-ct` (confirmed via
  the Kaggle Models UI: a plain `gemma-4-31b-it` and multiple
  `-assistant`-suffixed variants also exist, but `-assistant` is a
  separate fine-tune lineage present across every model size — using it
  would introduce base-weight mismatch vs. what's actually served).
  Rank 16, targets all 7 attention/MLP projections per
  `docs/HARNESS_README.md` §3.4's sizing table. Notebook deliberately
  does NOT attach the competition dataset (training only needs our own
  `experiments/lora_training_data/*.jsonl`, embedded verbatim) so Internet
  can stay on for `pip install peft accelerate` — confirmed the wheelhouse
  has zero training libraries (`peft`/`trl`/`accelerate`/`deepspeed` all
  absent; it's scoped purely for eval/serving).
- **Real bug #1 found before any Kaggle run**: the `py_literal()` helper
  shared by all four notebook generators only escaped backslashes in one
  edge case (a `"""`-collision fallback), never in the common path. The
  training data contains JSON-escaped unicode (`\uXXXX` sequences from a
  regex character class in some embedded source code, produced by
  `json.dumps`'s default `ensure_ascii=True`) — when embedded raw into a
  Python triple-quoted string, Python's own parser reinterpreted those as
  real unicode escapes, producing an invalid unpaired surrogate and
  crashing with `UnicodeEncodeError` the moment the notebook tried to
  write the file. Fixed in all four generators; re-verified with actual
  UTF-8 disk writes and byte-for-byte fidelity checks (not just JSON
  parsing) this time. The three already-used eval notebooks were never
  actually affected in practice — `submission/`'s own files happen to
  contain no backslashes — but the bug was real and latent.
- **Real bug #2 found before any Kaggle run**: hardcoded `torch.bfloat16`
  in three places (model loading, `bnb_4bit_compute_dtype`,
  `TrainingArguments.bf16`) would have crashed on a T4 GPU exactly like
  the vLLM eval notebooks did before their fix (compute capability 7.5 <
  8.0 required for bf16) — flagged proactively once the user mentioned
  Internet-on likely forces a T4 x2 accelerator. Applied the same
  compute-capability detection fix as the eval notebooks (`torch.cuda.
  get_device_capability(0)[0] >= 8`), now flowing into all three
  bf16-related call sites consistently.
- **Real bug #3 found on the actual first Kaggle run**: `get_peft_model()`
  raised `ValueError: Target module Gemma4ClippableLinear(...) is not
  supported` — this Gemma4 `transformers` checkpoint wraps its linear
  layers in a custom `Gemma4ClippableLinear` class (not a plain
  `torch.nn.Linear`/`Linear4bit`), which `peft`'s LoRA injection doesn't
  recognize even though it wraps a real `Linear4bit` internally (visible
  directly in the error's own repr: `Gemma4ClippableLinear(linear):
  Linear4bit(...)`). Fixed by unwrapping each targeted
  `Gemma4ClippableLinear` back to its `.linear` submodule in place before
  calling `get_peft_model()` — same weights/quantization, just without
  the wrapper. Training-time-only change: the deployed adapter (small
  low-rank matrices, saved separately) is what actually gets served later
  via vLLM, which never touches this module structure. **Not yet
  confirmed working** — fixed based on the error message alone (no local
  GPU to test against), with a loud `assert n_unwrapped > 0` guard so it
  fails clearly rather than silently no-opping if the assumption about
  the wrapper's attribute name is wrong. Given to the user as a drop-in
  cell-5 replacement rather than a full notebook re-run, since cell 4
  (model loading — the slow part) had already succeeded.
- Cohort: N/A — infrastructure, not an eval iteration.
- Result: training run not yet completed end-to-end; three real bugs
  found and fixed pre-emptively or reactively, one (`Gemma4ClippableLinear`
  unwrap) still awaiting confirmation on a re-run.
- Results dir: N/A.
- Commit: see below.

## 2026-09-30 — LoRA training notebook, bug #4: apply_chat_template's inconsistent return type
- Hypothesis: N/A — bugfix, continuation of "Step 9 (part 2)" above.
  `Gemma4ClippableLinear` unwrap fix worked (training reached
  `trainer.train()`, i.e. cells 1-7 — wheel install, data embedding,
  4-bit model load, LoRA wrap, dataset build — all ran without error this
  time), but hit a new `TypeError` inside the data collator.
- Change: `tokenizer.apply_chat_template(...)` doesn't consistently
  return a plain `list[int]` — depending on the tokenizer/processor it
  can return a `BatchEncoding`/dict, or a tensor (optionally with a
  leading batch dimension). Real error: `TypeError: unsupported operand
  type(s) for +: 'BatchEncoding' and 'list'` inside `collate_fn`'s
  `b['input_ids'] + [pad_id] * n_pad` — meaning `apply_chat_template` was
  silently returning a `BatchEncoding` here, and every downstream
  `len()`/slice/index call in `build_masked_example` had been operating
  on it without immediately erroring (`BatchEncoding` partially supports
  those via delegation) until the `+` concatenation finally broke.
  Added `_to_id_list()`: normalizes any of list/dict/`BatchEncoding`-like/
  tensor (with or without batch dim) into a plain `list[int]`, called at
  both `apply_chat_template` call sites in `build_masked_example`.
- Cohort: N/A.
- Result: unit-tested `_to_id_list()` in isolation against all 4 input
  shapes (plain list, dict, a `BatchEncoding`-like fake, tensor with/
  without batch dim) — all normalize correctly. **Not yet confirmed on
  the real tokenizer** — same caveat as the `Gemma4ClippableLinear` fix,
  no local GPU to verify against directly.
- Results dir: N/A.
- Commit: see below.

## 2026-09-30 — LoRA training notebook, bug #5: CUDA OOM on 2x T4
- Hypothesis: N/A — bugfix, continuation of "Step 9 (part 2)" above. Bug
  #4's fix worked: training actually reached the forward/backward pass
  this time (masking bug gone), then hit a real `CUDA out of memory`
  (`GPU 1 has a total capacity of 14.56 GiB... 13.44 GiB memory in use`).
- Change: two fixes. (1) `MAX_SEQ_LENGTH` 8192 → 4096 — checked the real
  `train.jsonl`'s size distribution: median ~16.7K chars (~4.2K est.
  tokens), but a real long tail up to ~54K chars (~13.5K est. tokens) for
  the largest trajectory (`fastapi_15800`). 8192 was too generous for 2x
  T4's actual free VRAM once the model's own sharded weights are
  accounted for; 4096 drops a meaningful chunk of the 44 examples but
  should avoid OOM. (2) Added explicit `max_memory` per GPU to
  `from_pretrained()` (`total_memory - 3GiB`), reserving headroom for
  activation memory instead of letting `device_map='auto'` fill each GPU
  close to capacity with weights alone.
- Cohort: N/A.
- Result: not yet confirmed — both fixes are reasoned from the real error
  message and the real training-data size distribution (not guessed), but
  unverified against an actual run. This one requires re-running from
  cell 4 (model loading), not just the later cells, since both changes
  touch how the model is loaded.
- Results dir: N/A.
- Commit: see below.

## 2026-09-30 — LoRA training notebook, bug #6: dirty GPU state from prior OOM
- Hypothesis: N/A — bugfix, continuation of "Step 9 (part 2)" above.
  Bug #5's fixes (MAX_SEQ_LENGTH 4096, max_memory cap) hit a *new* OOM —
  but this one during model *loading* itself (`caching_allocator_warmup`),
  with GPU 0 already showing 13.29 GiB in use *before* this cell's own
  allocation attempt. That's more than the ~11GiB `max_memory` cap should
  have allowed, and the traceback showed the same kernel PID
  (`ipykernel_58`) as the prior OOM — strong evidence the previous failed
  attempt left GPU memory occupied (an exception's traceback holds
  references to partially-allocated tensors, blocking garbage collection
  until the kernel actually restarts), not a flaw in the cap itself.
- Change: added a defensive `gc.collect()` + `torch.cuda.empty_cache()` +
  per-GPU memory report at the top of the model-loading cell, with an
  explicit warning if >1GiB is already allocated before loading even
  starts (signals a dirty session, prompting a kernel restart instead of
  just re-running the cell). Primary guidance given to the user: restart
  the kernel and re-run the whole notebook fresh rather than retrying in
  the same session — also ensures `PYTORCH_CUDA_ALLOC_CONF` (set in cell
  2) takes effect from a genuinely clean process state.
- Cohort: N/A.
- Result: not yet confirmed — awaiting a clean-kernel re-run.
- Results dir: N/A.
- Commit: see below.

## 2026-09-30 — LoRA training notebook, bug #7: OOM during actual training (not loading)
- Hypothesis: N/A — bugfix, continuation of "Step 9 (part 2)" above. After
  a genuine kernel restart, training reached `trainer.train()`'s real
  forward pass this time (bug #6's dirty-session diagnosis confirmed —
  clean restart got further), then hit a new OOM *inside* `down_proj`'s
  LoRA forward (`peft/tuners/lora/bnb.py`'s `result.clone()`), with GPU 1
  at 14.44/14.56 GiB — essentially full.
- Change: three fixes, motivated directly by the failure site. (1)
  `TARGET_MODULES` dropped the 3 MLP projections (`gate_proj`/`up_proj`/
  `down_proj`) — the actual OOM happened inside `down_proj`'s LoRA
  forward, and MLP projections are the largest matrices in a transformer;
  now attention-only (`q/k/v/o_proj`), a well-established lower-memory
  QLoRA configuration. (2) `max_memory` cap tightened from `total-3GiB` to
  `total-6GiB` per GPU — realized a 31B model at 4-bit only needs
  ~7.75GiB/GPU for weights across 2 GPUs, so the previous cap (~11GiB) had
  far more slack for weights than needed while leaving too little *real*
  headroom for training-time activations/gradients. (3) Added
  `gradient_checkpointing_kwargs={'use_reentrant': False}` — a known more
  memory-efficient checkpointing mode.
- **Self-caught mistake before telling the user to re-run**: initially
  also cut `MAX_SEQ_LENGTH` 4096 → 2048 as a fourth lever, without first
  checking the real survival rate at that cap. Computed it before
  shipping: even the *original* 4096 cap only keeps 20/44 (45%) of
  `train.jsonl`'s examples (long tail up to ~13.5K estimated tokens,
  median already ~4.2K); 3072 and 2048 both keep **zero** examples. Would
  have produced an empty dataset — a worse, more confusing failure than
  the OOM it was meant to fix. Reverted to 4096; the three fixes above are
  this round's actual levers.
- Cohort: N/A.
- Result: not yet confirmed — awaiting a re-run (needs a fresh kernel
  restart again, since this touches both the model-loading cell's
  `max_memory`/LoRA-wrapping cell's `target_modules` and the
  `TrainingArguments` cell).
- Results dir: N/A.
- Commit: see below.

## 2026-09-30 — LoRA training notebook, bug #8: max_memory too tight broke loading
- Hypothesis: N/A — bugfix, continuation of "Step 9 (part 2)" above. Bug
  #7's `max_memory` tightening (`total-3GiB` → `total-6GiB`) was wrong —
  it left too little room for the model's own weights, and `bitsandbytes`'
  4-bit quantizer refuses CPU/disk offload without an explicit
  `llm_int8_enable_fp32_cpu_offload=True` flag, raising `ValueError: Some
  modules are dispatched on the CPU or the disk` immediately at
  `from_pretrained()`.
- Change: reverted `max_memory` to `total-3GiB` — now backed by two real
  data points bracketing the actual per-GPU weight requirement: `total-3`
  (~11.56GiB) is proven to load successfully (multiple prior runs got
  past loading with this cap); `total-6` (~8.56GiB) doesn't even fit the
  weights. Kept this round's other two changes (attention-only
  `TARGET_MODULES`, non-reentrant gradient checkpointing) — those target
  the actual training-time OOM from bug #7, which the cap-tightening
  never got far enough to actually test before failing at load time.
- Cohort: N/A.
- Result: not yet confirmed — awaiting a re-run (fresh kernel restart,
  since this touches the model-loading cell again).
- Results dir: N/A.
- Commit: see below.

## 2026-09-30 — LoRA training notebook: torch_dtype deprecation (not a bug, proactive fix)
- Change: `transformers` warned `torch_dtype` is deprecated in favor of
  `dtype` on `AutoModelForCausalLM.from_pretrained()`. Not a failure —
  fixed proactively before it becomes a real break in a future
  `transformers` version.
- Commit: see below.

## 2026-09-30 — LoRA training notebook, bug #9: OOM moved into attention itself
- Hypothesis: N/A — bugfix, continuation of "Step 9 (part 2)" above. Bug
  #8's revert (max_memory back to total-3, attention-only TARGET_MODULES
  kept) got further — the OOM moved from `down_proj`'s LoRA forward to
  `scaled_dot_product_attention` itself, inside the base model's own
  `self_attn`, independent of LoRA. GPU 1: 13.85/14.56 GiB already
  allocated before this specific call.
- **Checked whether MAX_SEQ_LENGTH could go lower first, before touching
  anything else**: computed the real per-length survival counts at finer
  granularity. Found a hard floor — no training example is under ~3623
  estimated tokens (the dataset simply doesn't have shorter examples), and
  survival is a cliff: 0/44 at ≤3500, 10/44 at 3800, 20/44 at 4096.
  Sequence-length reduction is not a viable lever anymore without
  sacrificing all data, and we're already at the minimum useful length.
- Change: added `optim='paged_adamw_8bit'` to `TrainingArguments` —
  bitsandbytes' purpose-built fix for GPU memory that's momentarily too
  tight, paging optimizer state to CPU RAM on demand. **Honesty check
  before shipping this as a confident fix**: the crash is in the
  *forward* pass of the very first training step, before any optimizer
  state exists (PyTorch allocates optimizer state lazily on the first
  `.step()` call, which comes after backward, which comes after this
  forward pass) — so this fix may not address *this specific* crash
  point, even though it's a reasonable thing to have in place regardless
  for a later backward/optimizer-step OOM.
- Cohort: N/A.
- Result: not yet confirmed. Flagged explicitly to the user: we've now
  pulled every code-level lever with real confidence behind it
  (attention-only LoRA targeting, memory cap tuned via two real bracketing
  data points, non-reentrant checkpointing, sequence length at its
  floor), and the GPU is still essentially maxed out before backward pass
  even starts. This may be a genuine hardware ceiling — 2x T4 (29 GiB
  total) might not fit this 31B model's forward pass alone at the
  sequence lengths the real training data requires, independent of
  further tuning.
- Results dir: N/A.
- Commit: see below.

## 2026-10-01 — 2026-09-30_navigator-test
- Hypothesis: Does the new navigator_agent AgentTool (read-only, isolated context, skip_summarization) actually get invoked and function correctly at runtime, not just compile?
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-09-30_navigator-test/`
- Commit: `6e024accebc578028fda2cd3ddb9a90dbee0ce74` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/b307827b509a4196ae3d4542bc23b910

### Analysis addendum — navigator_agent architecture validated at runtime
Built per the pasted external proposal's "simpler first version" (verified
against `docs/HARNESS_README.md` before building: `SequentialAgent`,
`output_key`, `include_contents`, and the `AgentTool
(skip_summarization: true)` isolation pattern at line 668 all checked out
exactly as cited). Also verified the budget-sharing nuance the proposal
didn't address: `SwegemmaContext.check_budget()` tracks `tool_calls_used`/
`llm_calls_used` on one object per task, shared across the whole agent
tree — a navigator sub-agent does NOT grant extra total budget, it spends
the same pooled ceiling across isolated context windows instead of one
accumulating one.

Added `submission/sub_agents/navigator.yaml` (read-only: `read_file`,
`run_command`, `get_status`, the 3 graph tools, `repo-navigation` skill —
no `edit_file`/`write_file`/`submit_patch`) and
`submission/prompts/navigator.md` (mandatory anti-repetition check +
mechanical exploration steps + a fixed report format: relevant file(s),
root cause, suggested fix, suggested verification — mirroring this
project's established finding that mechanical framing works better than
soft framing for the stand-in model). Wired into the root agent as a 10th
tool (`agent_tool: {config_path: sub_agents/navigator.yaml,
skip_summarization: true}`), mentioned once in `system.md` as optional —
same framing the repo-navigation skill already uses, consistent with the
step-8 finding that making an extra step *mandatory* backfired.

**Verified in two stages, not just written**: (1) a real
`compile_submission()` dry-run confirmed the navigator compiles correctly
as an `AgentTool` alongside the 9 direct tools and the skill toolset. (2)
A real proxy-model run on `fastapi_15661` (the most-tested task in this
project) confirmed it actually works at runtime: the root agent delegated
to `navigator_agent` as its very first action (43.8s in), the navigator
explored independently in its own isolated context (4 read/list calls,
~106s) and returned a report in exactly the specified format, and —
critically — **the root agent's own reasoning explicitly referenced "the
navigator_agent's findings"** and took a genuinely new approach never seen
on this task before (`scripts/prepare_release.sh`, vs. every prior run's
README-edit or `fastapi/__init__.py` version-bump attempts). Real evidence
the delegation actually changes the root agent's strategy, not just adds
overhead.

Not resolved (`resolved=false`, `test_exit_code=2`) — expected, the
`gemma4:e4b` stand-in has never resolved a task in this project regardless
of architecture. Ended via `Agent exceeded turns budget (15 turns)`, the
same clean (non-crash) ending seen throughout proxy-model testing — not a
new failure mode. `tool_calls=12` for a 660-byte patch is consistent with
budget sharing correctly including the navigator's own calls (4 navigator
+ 1 delegation call + 7 root-agent calls ≈ 12).

**Correction (caught on closer trace review, not in the original writeup
above)**: the `scripts/prepare_release.sh` approach was not just "a new
strategy" — it was tried and failed. After the `chmod +x` self-recovery,
re-running the script hit a real, unresolved Python traceback from
`scripts/docs.py`. The agent then edited the script and re-ran it — same
traceback, still unfixed. Its last action before running out of budget was
starting to edit `scripts/test.sh` itself, which `system.md` explicitly
forbids ("NEVER modify, create, or delete test files"). The correct framing
is **mechanism validated, strategy benefit unproven**: real evidence the
navigator's report changes the root agent's chosen direction, but no
evidence yet that the resulting direction is better — this run shows it
can also be wrong, just like any other exploration path.

**Next**: this validates the mechanism works, not that it improves
resolution rate — that needs a real comparison against the pre-navigator
baseline on the same cohort (ideally the `comparison` cohort on the
official model, where the actual context-window pressure this was built
to relieve has been observed for real, not just estimated).

## 2026-10-01 — navigator_agent v2: tighter scope, evidence-based report, real bugfix
- Hypothesis: N/A — design refinement of the navigator built above, based
  on external review of the v1 design against real comparison-v1 data
  (13/19 zero-patch tasks, 4/6 non-zero-patch tasks still unresolved —
  confirming a navigator can only address the navigation-failure category,
  not implementation-failure) and the v1 proxy-test trace (its exploration
  used 4 tool calls, over an unbounded budget; its 250-word-unbounded
  report format risked eating root context the navigator was built to
  save).
- Change: three files.
  1. `sub_agents/navigator.yaml`: tools reduced from 6 to 2
     (`run_command`, `read_file` only — dropped `get_status` since the
     navigator never edits so it's always a no-op call, dropped all 3
     graph tools, dropped the `repo-navigation` skill since a 2-3-call
     budget can't afford spending one on loading it).
  2. `prompts/navigator.md`: rewritten — hard tool budget (target 2, max
     3, stop immediately after), read-only `run_command` allowlist with
     explicit banned operations (no `sed -i`/`chmod`/`rm`/`mv`/`cp`/git
     writes/Python execution/test commands), a **defensive zero-tool-call
     exit** for when the problem statement already specifies the target
     (redundant safety net alongside the root-side gate, since neither
     gate is perfectly reliable on a small model), evidence-only claims
     (no inference from filenames/plausibility), and a 250-word report
     format with explicit `Unknowns` and a confidence level instead of a
     mandatory "root cause."
  3. `prompts/system.md`: navigator gate tightened to mechanical criteria
     — call at most once, only when the target is unknown OR the root
     agent's own first direct search already came back empty (not "the
     problem statement alone isn't enough," which was softer/vaguer).
- **A real technical bug caught and fixed before implementing**: the
  external review's first draft also proposed `include_contents: none` on
  the navigator, reasoning it would stop root conversation history from
  leaking into the navigator's context. Verified against ADK's actual
  source before accepting this: `AgentTool.run_async`
  (`google/adk/tools/agent_tool.py`) already creates a brand-new,
  isolated `InMemorySessionService` + session per call, passing only the
  request string — there is no root-history leakage to prevent. Worse,
  `include_contents='none'`'s real behavior (`google/adk/flows/llm_flows/
  contents.py`) restricts an agent to its own *current turn only*,
  excluding history from its *own prior turns* — which would have made
  the navigator forget its own earlier search/read results by the time it
  reached the report step, directly undermining the tight call budget
  this whole revision is built around. Dropped this one change; kept
  `include_contents` at ADK's default. Confirmed via a real
  `compile_submission()` check that the final config compiles with
  `include_contents: default` and exactly the 2 intended tools.
- **Also verified, not just accepted**: the graph-tool claim was checked
  against the real comparison-v1 traces before being used as
  justification — in all 10 observed `search_similar_code` calls across
  the 19-task cohort, it was immediately followed by `run_command`. Real,
  consistent pattern (worth citing precisely: the traces don't establish
  whether this was a fallback from failure or routine complementary
  lookup — graph search was never used alone to find an edit target in
  this data).
- Cohort: N/A — design/config change, not an eval iteration yet.
- Result: compiles correctly (`navigator_agent` tools = `['run_command',
  'read_file']`, `include_contents='default'`, confirmed via a real
  `compile_submission()` call). Not yet re-tested at runtime (the v1
  proxy-model smoke test validated the AgentTool mechanism itself, which
  this change doesn't alter — only the navigator's own tool access,
  prompt, and the root's gating criteria changed).
- Results dir: N/A.
- Commit: see below.

## 2026-10-01 — 2026-10-01_navigator-v2-test
- Hypothesis: navigator_agent v2 (2 tools, hard 2-3-call budget, evidence-based report, defensive zero-tool exit). Does it stay within 3 tool calls, avoid proposing an unsupported implementation, and leave the root agent enough turns to edit/test/submit?
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-10-01_navigator-v2-test/`
- Commit: `b32c32eb30d2c4136afe44a7cafc79bf1c4e4625`
- MLflow: http://localhost:5001/#/experiments/9/runs/4b5da75e81d240b49c21942c675dd72d

### Analysis addendum — navigator v2 not invoked; honest result either way
**The navigator was never called in this run.** The stricter gate ("only
when the target is unknown OR your own first direct search already came
back empty") meant the root agent kept trying its own direct exploration
(5 read/list calls: `publish.yml`, `ls`, `pyproject.toml`, `README.md`,
`publish.yml` again) rather than falling back — on this genuinely vague,
PR-title-style task, it apparently judged its own search "good enough" at
each step, never hitting the fallback condition clearly enough to
delegate. This run does not test the delegation mechanism (v1's test
already did that); it tests whether the *tightened gate* leaves the
navigator under-used on a task that plausibly could have benefited from
it.

Result: a third distinct approach on this exact task (after the
README-edit, version-bump, and shell-script attempts in prior runs) —
edited `.github/workflows/publish.yml` to add a "Bump version and tag"
step, 882-byte patch, `error=null` (clean completion, 11/15 turns, 9/25
tool calls — efficient). **But it never ran any test before calling
`submit_patch`** — no `pytest` call anywhere in the trace, violating its
own Operating Loop's Verify step. `test_exit_code=2` (collection error),
unresolved. This echoes the v1 test's finding from a different angle:
whether or not the navigator is invoked, this specific task keeps
producing agent trajectories that skip real verification — a reasoning/
discipline gap orthogonal to the navigator entirely, not something this
architecture change was built to fix.

**Honest takeaway**: two tests, two different navigator-trigger outcomes
(v1: invoked, led to a failed shell-script approach; v2: not invoked, led
to an unverified-but-submitted edit), neither resolved, neither a clean
win or loss for the navigator specifically. n=1 per configuration on one
task — not enough to conclude anything about resolution-rate impact
either direction. The real test remains the planned official-model
`comparison`-cohort before/after run.

## 2026-10-01 — 2026-10-01_official-comparison-navigator-v2 (navigator rarely triggers; real failure mode identified)
- Hypothesis: Before/after test of `navigator_agent` v2 against
  `2026-09-30_official-comparison-v1` (pre-navigator baseline,
  `resolution_rate=2/19`). Does the navigator improve resolution rate or
  reduce turn-budget exhaustion on the `comparison` cohort?
- Change: none to the submission other than the navigator itself — same
  commit lineage, same cohort, same budgets as the baseline.
- Cohort: comparison (19 tasks), official model, Kaggle notebook.
- Result: **`resolution_rate=2/19 (10.5%)` — numerically identical to the
  pre-navigator baseline**, and the match goes deeper than the aggregate:
  the *same two tasks* resolved (`fastapi_14492`, `rich_3518`, same patch
  sizes 391/529 bytes), and the *same task* hit the context-window crash
  (`fastapi_14186`). Root cause: **the navigator was invoked exactly once
  across all 19 tasks** (`fastapi_9425`), and even there it didn't change
  the outcome (still unresolved, still zero patch). This isn't a failure
  of the navigator mechanism — it works when called (confirmed repeatedly
  now) — it's that the gate essentially never fires on the official model.
- **Why the gate almost never fires — a real, more precise finding than
  either the original navigator design or the external review assumed**:
  categorized every task's tool-call sequence into explore
  (`read_file`/`run_command`/graph tools) vs. implement
  (`edit_file`/`write_file`). Most turn-budget-exhausted tasks spent
  **13-15 of their 14-15 total calls purely exploring**, several (
  `fastapi_14099`, `fastapi_14246`, `fastapi_14266`, `rich_3777`) used
  **all 15 calls exploring and never called `edit_file`/`write_file`
  even once**. The navigator's gate ("target unknown OR your own first
  direct search already came back empty") is framed around a
  binary-failure model of navigation — but the real pattern here is
  **unbounded exploration that never technically fails, it just never
  converges**: `run_command`/`read_file` calls keep returning real
  results, so the gate's "search came back empty" condition is never
  true, even though the agent is burning its entire budget without ever
  reaching an edit. A navigator built to catch "I don't know where to
  look" doesn't address "I keep looking and never decide I've looked
  enough."
- **This reframes, not contradicts, the external review's own prediction**
  that a navigator "cannot repair implementation/reproduction loops" —
  the actual dominant pattern here is upstream of that: most tasks never
  even reach implementation, let alone loop within it. The fix this
  points to is different from what v2 built: not "delegate when search
  fails" but something like a hard exploration-call budget before the
  *root* agent itself (not a sub-agent) is forced to commit to an edit —
  closer to a mechanical turn-based gate than a failure-based one.
- Cohort: comparison.
- Results dir: N/A locally — ingested from
  `manual_kaggle_results/extracted/results/results` via
  `devtools/mlflow/ingest_results.py --cohort comparison`.
- Commit: `cc25d36a38580d7181a73d03e81587067263b53f` (submission/ clean,
  confirmed via `diff -r` against the downloaded snapshot before
  ingesting).
- MLflow: http://localhost:5001/#/experiments/9/runs/e66d6528ada04227972d83d4d72b806d

## 2026-10-01 — 2026-10-01_filesystem-only-test
- Hypothesis: Filesystem-only root agent (navigator and graph tools removed entirely, skill kept) - matches comparison-v1's tool list minus the 3 graph tools that returned 0 results in every observed call. Does it compile and run correctly at runtime?
- Change: `swegemma eval --sandbox docker` against task(s) fastapi_15661, backend=stand-in-e4b, env=local-mac, fidelity=proxy-model.
- Cohort: smoke
- Result: proxy_resolution_rate=0.0, resolved=0/1
- Results dir: `results/2026-10-01_filesystem-only-test/`
- Commit: `d710b57e2f17d5ed8579c618214f5f696ff5bd42` (dirty worktree at run time)
- MLflow: http://localhost:5001/#/experiments/9/runs/8cb1c307b2a243d696f67a008e7b481d

## 2026-10-01 — 2026-10-01_official-comparison-filesystem-only (real, mixed-but-net-positive result)
- Hypothesis: Removing the 3 graph tools (30/30 observed calls returned
  empty) and `navigator_agent` (no resolution gain, self-enforcement
  failure) — does this recover the wasted exploration budget and improve
  resolution rate vs. `2026-09-30_official-comparison-v1`
  (`resolution_rate=2/19`)?
- Change: `agent.yaml` tools 10→6 (dropped the 3 graph tools + the
  navigator `agent_tool`), `system.md`'s graph-search guidance replaced
  with direct `grep`/`find`, one stale `search_similar_code` mention
  scrubbed from the `repo-navigation` skill's `fastapi.md`. Sampling and
  all task budgets unchanged.
- Cohort: comparison (19 tasks), official model, Kaggle notebook.
- Result: **`resolution_rate=3/19 (15.8%)` — up from 2/19, a real,
  verified improvement**, with a third task now resolving
  (`rich_3521`, 480-byte patch, clean completion) that previously
  exhausted its turn budget with zero patch. Precise task-by-task diff
  against the original baseline (not navigator-v2, which was already
  near-identical to it):
  - **Improvements (5 tasks)**: `rich_3521` unresolved→**resolved**.
    `fastapi_14186`'s `ContextWindowExceededError` crash is **gone**
    (now a clean turn-budget exhaustion instead). Three previously
    zero-patch tasks now produce real patches: `fastapi_14873` (0→2158
    bytes), `fastapi_9753` (0→465 bytes), `fastapi_9425` (0→787 bytes) —
    still unresolved, but confirms the hypothesis directly: budget
    previously spent on always-empty graph searches is now reaching
    `edit_file`/`write_file` on some tasks.
  - **Regressions (3 tasks)**: `rich_3953` previously produced a 539-byte
    patch (unresolved but a real attempt); now 0 patch **and** a new
    `ContextWindowExceededError` on this task — the crash didn't
    disappear overall, it moved. `fastapi_14953` (560→0 bytes) and
    `rich_3468` (272→0 bytes) also regressed to zero-patch.
  - **Ambiguous (1 task)**: `fastapi_14791`'s patch grew substantially
    (578→2463 bytes) but hit a new, previously-unseen error type —
    `Failed to apply test_patch: git apply ...` — a verification-phase
    failure applying the gold test patch on top of the agent's own patch,
    not a crash in the agent loop itself. Not yet understood; worth a
    closer look in a future round, not chased here.
  - **Unchanged (10 tasks)**: everything else — same resolved/unresolved
    status, same (or absent) patch, same turn-budget-exhaustion ending.
- **Honest takeaway**: not a uniform win — this redistributes where the
  model spends its budget, helping some tasks and hurting others, net
  positive on the headline number (+1 resolved, +3 tasks reaching a real
  edit attempt) but with real, concrete costs on 3 other tasks. Consistent
  with everything else observed in this project: changes rarely help
  uniformly across a repo-diverse cohort. n=19, one trial — a second
  resolution out of one previously-zero-patch task crossing the resolve
  line is a meaningful signal, not yet a statistically overwhelming one.
- Results dir: N/A locally — ingested from
  `manual_kaggle_results/extracted/results/results` via
  `devtools/mlflow/ingest_results.py --cohort comparison`.
- Commit: `fe57fdd7828eeb8e86ebe18de9e8712cc7885f94` (submission/ clean,
  confirmed via `diff -r` against the downloaded snapshot before
  ingesting).
- MLflow: http://localhost:5001/#/experiments/9/runs/a855d60a9afa4d6786436f57a3d40d92

## 2026-10-05 — 2026-10-05_official-comparison-filesystem-only-wordingfix (re-run; not the same candidate)
- Hypothesis: re-run of the filesystem-only candidate to check whether the
  3/19 result holds. This is NOT byte-identical to the Oct 1 run: commit
  `a8f2d9a` changed the Reproduce wording in `prompts/system.md` (no more
  "write to /tmp" via write_file). Treat as a re-run with one prompt-wording
  difference, not a pure reproduction.
- Cohort: comparison (19 tasks), official model, Kaggle notebook.
- Result: `resolution_rate=4/19 (21.1%)` (Oct 1 run: 3/19).
  - Resolved: `fastapi_14492`, `rich_3518` (both resolved in every run so
    far), `fastapi_14873` (new), `fastapi_9753` (new).
  - Dropped vs Oct 1: `rich_3521` (resolved Oct 1, turn budget this run).
  - Changed errors: `rich_3953` no longer has the ContextWindowExceeded
    crash (now a turn-budget exhaustion with an 846-byte patch). Zero
    traces contain ContextWindowExceeded this run.
  - Still present: `fastapi_14791` "Failed to apply test_patch" (2563-byte
    patch), the verification-harness error seen Oct 1.
- Interpretation: the candidate moved 3 -> 4 but the solved set changed by
  two tasks in each direction. With one run per candidate and a wording
  change confounding it, this is consistent with run-to-run variance plus
  a small real effect. Not enough to claim a stable improvement.
- Provenance: the notebook header says `d40b23f` because it was generated
  from a dirty worktree (the generator embeds HEAD, not the committed
  content). The submission snapshot was verified byte-for-byte against
  `a8f2d9a` (`git archive` + `diff -r`), so `a8f2d9a` is the correct
  --git-commit for ingestion, not the header value.
- Not promoted: held-out gate (PROMOTION_CHECKLIST gate 5) still not run.
- Results dir: N/A locally (ingested from manual_kaggle_results).
- Commit: `a8f2d9a` (verified against the snapshot).
- MLflow: http://localhost:5001/#/experiments/9/runs/aa8fde5f105f48c6a6d5470dae98d3ad

## 2026-10-05 — graph lookup diagnosis (search_similar_code empties)
- Question: were the 30/30 empty `search_similar_code` results in the official
  runs evidence that graph retrieval doesn't work, or a lookup problem?
- Finding 1: graph and embedding data exist for every task. The competition
  dataset has 127 graph JSONs and 127 `.npz` files, one per base commit. For
  each failing task (`fastapi_14246`, `fastapi_9425`, `fastapi_14266`,
  `rich_3521`), the task's own base-commit graph file exists.
- Finding 2: the retrieval engine works locally. Using the task's `base_commit`
  and the harness's `repo_name` form (`fastapi/fastapi` or `fastapi`), the same
  queries the official run got 0 results for now return 3 each:
  `get_openapi`, `response_model`, `split_cells`. Using `class APIRouter`
  returns 0 locally too.
- Finding 3: query form matters. Queries with a space (`class X`, `def X`,
  `openapi security`) return 0 in `get_similar_nodes`; the node-name resolver
  matches on `.`/`;` boundaries, so a phrase never resolves. Bare identifiers
  return results, but they are embedding neighbors, not exact symbol matches:
  `get_openapi` returned `get_cached_model_fields` and `get_swagger_ui_html` as
  top hits, not `get_openapi` itself.
- Finding 4 (not resolved): the official run returned `status: ok, count: 0`
  for queries that return results locally. A missing graph file raises an
  error, so the graph was found, but something inside the Kaggle run returned
  no matches. Candidate: `graph_dir`/`embeddings_dir` resolution. Auto-detection
  in `swegemma/config.py` only runs when `graph_dir == 'data/graphs'` and that
  path does not exist relative to CWD; if a `data/graphs` exists in CWD, the
  shipped graphs are never used. The run artifacts do not record the
  resolved `graph_dir`, so this can't be checked from the downloads.
- Next check: add a notebook cell that prints `os.getcwd()`, `ctx.graph_dir`,
  `ctx.embeddings_dir`, and whether each exists, then re-run the 4 failing
  queries directly against those paths.
- Status: diagnosis only; no change to `submission/` or the notebooks.
  Uncommitted.

## 2026-10-05 — graph lookup debug notebook (built, locally dry-run; not yet run on Kaggle)
- Added `graph_dir` debug cell (section 5b) to the comparison generator, and
  bumped its VERSION_TAG to `filesystem-only-graphdebug` so the notebook that
  already ran is not overwritten. The submission is unchanged (no graph tools).
- Added `devtools/generate_graph_debug_notebook.py` → `graph-lookup-debug-v1.ipynb`.
  CPU-only: reuses the comparison setup cells, then calls the real
  `search_similar_code` tool on the four failing tasks with each task's own
  base commit, plus a relative-`data/graphs` failure-mode check.
- Local dry run against the downloaded competition data (same cell code,
  Kaggle paths replaced):
  - `get_openapi` (fastapi_14246), `response_model` (fastapi_9425), and
    `Segment.split_cells` (rich_3521) each return 3 results.
  - `openapi security` (fastapi_14266) returns 0: phrase queries never resolve.
  - **The relative-`data/graphs` check did NOT reproduce empties.** With no
    `data/graphs` in the CWD the tool still returned results. The
    auto-detection hypothesis from the previous entry is therefore not
    supported by this local run. The official-run empties are still unexplained.
- Next: run `graph-lookup-debug-v1.ipynb` on Kaggle. If the in-run results
  are empty again, the difference is inside the harness context, and the
  printed output of cells A and B is what will show it.
- Uncommitted: this CHANGELOG entry only (generator and notebook changes are in `7d4ac36`).

## 2026-10-05 — graph-lookup debug notebook: first Kaggle run
- Kaggle `graph_debug_results.json`: all four failing queries returned
  `status: ok, count: 0`, identical to the official comparison run. The notebook
  passed the competition `graphs/` and `embeddings/` paths explicitly, so path
  resolution is not the cause.
- Local .venv has the same swegemma version as the wheelhouse (0.2.7), and
  every layer works locally: the npz loads (3619 entries), the graph loads,
  `get_openapi` resolves to `fastapi.openapi.utils.get_openapi`, and embed returns
  a (256,) vector.
- Code path explaining silent empties: `embedding_utils.load_embeddings_from_npz`
  failures are caught in `_REPO_CACHES` population and only logged with
  `logger.warning`. An empty cache makes `embed()` return None, and
  `get_similar_nodes` returns `[]`, which the tool reports as `status: ok`.
  Unresolved: which layer fails on Kaggle.
- Added cell B2 (layer-by-layer): npz load, graph load, resolve, embed,
  each printed separately. Local dry run passes every step.
- Next: run the regenerated `graph-lookup-debug-v1.ipynb` on Kaggle and paste
  cells A, B, and B2 output, including any `Failed to load embeddings` warning
  printed to stderr.

## 2026-10-05 — Kaggle runs a different swegemma build than the local wheel (critical)
- Kaggle cell B2: `graph_utils` has no `resolve_node_name`; the local version-25 wheel does.
- Kaggle cell B: warning `Could not obtain embedding for node get_openapi`. That text is not in the local version-25 wheel.
- Kaggle cell C (relative `data/graphs`): error `Repository fastapi/fastapi not found in local files at data/graphs/...`. That text is not in the local version-25 wheel. Locally the same call returned results.
- Cause (strongly suggested, not yet confirmed): `devtools/generate_*_notebook.py` installs the wheelhouse by its unversioned Kaggle path, which resolves to the latest dataset version on Kaggle. The local copy is version 25, so the Kaggle build is probably newer.
- Impact: all official-model runs (comparison-v1, navigator-v2, filesystem-only, filesystem-only re-run) used this Kaggle build. The graph-tool conclusions and the local-dry-run analysis describe version 25, not what ran in the official runs.
- Next: cell A0 prints the installed swegemma version and the wheelhouse listing. Paste its output. Then pin the notebooks to a specific wheelhouse version, and re-check the graph tool on that build.

## 2026-10-05 — confirmed: Kaggle swegemma build differs from local wheel
- Kaggle A0: swegemma 0.2.7 installed at `/usr/local/lib/python3.12/dist-packages`, `resolve_node_name` missing. Python 3.12.13.
- Kaggle wheel sha256 `27a2f60f8db46c8fef5defc16df722dac0402446c9a6252e7e6b4c280e843c81`, installed `graph_utils.py` sha256 `e48d9f0cabe02e9ce8b1a0ab437de68a90e0a740b61a3f54ce5a95ab1f05c1cc`.
- Local wheelhouse v25 sha256 `2b74d402dc95a615f3b36c56fd3f9ba11ddbfb7db8a5a32ec259369a0f559d98`, installed `graph_utils.py` sha256 `b41439734ee0838acc7ae867b4718e9175bfea56830c4050e7789b4a0b713dcb`. Local Python 3.13.5.
- Conclusion: same version string, different build. The mounted Kaggle wheelhouse is not the version-25 dataset I downloaded.
- Official-run logs in `manual_kaggle_results` contain no "Could not obtain embedding" text. That is inconclusive: the warning went to notebook stderr, not per-task logs.
- Open: which wheelhouse dataset version Kaggle mounts (dataset page), and whether all official runs used the same mounted build. Future notebooks should print the wheel sha256 in every run.

## 2026-10-05 — root cause: wheelhouse v28 graph lookup defect; official runs used v28
- Kaggle mounts the latest wheelhouse, dataset version 28. Downloaded it with
  kagglehub: swegemma wheel sha256 `27a2f60f8db46c8fef5defc16df722dac0402446c9a6252e7e6b4c280e843c81`,
  matching Kaggle exactly. Our local analysis used version 25 (`2b74d402…`).
- v28 changes 10 swegemma files relative to v25, including `tools/graph.py`,
  `tools/base.py`, `tools/execution.py`, `tools/workspace.py`, and `context.py`.
- Running the four failing queries against the extracted v28 code reproduces the
  Kaggle output exactly: `status: ok, count: 0` and the `Could not obtain embedding`
  warning. v28's `graph_utils` has no `resolve_node_name`, so bare names and phrases
  never resolve to a node, and the embedding lookup fails silently.
- The official traces contain `is_truncated` in all search results. v25 never
  produces that field (0 matches in its `tools/graph.py`). So the official runs used
  the v28 build.
- Consequence: the 30/30 empty `search_similar_code` results came from a build
  defect in v28, not from the graph approach. The earlier conclusion that graph
  retrieval doesn't help is unsupported. Removing the graph tools was a reasonable
  response to a non-functional tool, but the reason was wrong.
- v28 also changes the shared tool layer (`base`, `execution`, `workspace`). Local
  proxy results from v25 may not reflect official behavior. Re-validate locally on v28.
- Recommended: point the local venv at v28, and add a notebook check that asserts the
  mounted wheel sha256 equals `27a2f60f…` so each run fails fast on a different build.

## 2026-10-05 — local venv pinned to wheelhouse v28; notebooks fail fast on a different build
- Reinstalled swegemma v28 into `.venv` (`pip install --no-deps --force-reinstall`).
  Installed `graph_utils.py` sha256 now `e48d9f0c…`, matching Kaggle's.
- All official notebook generators (baseline, comparison, maxturns) and the graph
  debug notebook now assert, right after install, that the mounted swegemma wheel
  has sha256 `27a2f60f…` and the installed `graph_utils.py` has sha256 `e48d9f0c…`.
  A different build stops the run immediately.
- Local v25 results are no longer the reference. Re-validate the candidate on v28 locally before trusting local proxy numbers.
