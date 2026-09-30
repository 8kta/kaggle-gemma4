# Gemma 4 Developer Agent Competition — Starting Plan

This is the Kaggle **Gemma 4 Developer Agent Competition**: build a declarative ADK
agent (YAML config + optional LoRA adapters) that uses `gemma-4-31b-it-qat-w4a16-ct`
to autonomously fix real Python bugs (SWE-bench style), scored by pass/fail on
held-out tests. **Note (2026-09-29): this "no code yet" framing describes the
plan's starting point, not current state** — steps 1-8 below are now
implemented in the `kaggle-gemma4` working repo (this file lives at
`kaggle-gemma4/agent-ideas/claude-idea.md`); see `README.md`/
`experiments/CHANGELOG.md` there for what's actually been built and verified.

## 1. Get the environment and data in place
- Set up `kagglehub`, pull the dataset (`gemma-4-developer-agent`): `tasks.jsonl`,
  `snapshots/`, `graphs/`, `embeddings/`, `wheels/`, `docker/`, `sample_submission/`.
- Confirm Docker is available locally (harness defaults to `--sandbox docker` with
  `swebench-sandbox:latest`; fall back to `--sandbox subprocess` if not).
- Install the `swegemma` CLI + `adk-submission`/`adk-eval-core` libs.
- **Mac compatibility check**: inspect the supplied wheel architecture before
  picking a Docker platform. Use native Apple Silicon containers when compatible;
  otherwise use `--platform linux/amd64` and explicitly tag those runs as
  emulated. Never compare timing/duration from an emulated Docker run against a
  native-Mac or cloud-GPU run — only compare pass/fail correctness across those.

## 2. Establish a development log / experiment-tracking practice
Set this up before the first real eval run, since every later step produces a run
worth being able to re-inspect or re-run without guessing what changed.
- Keep a persistent `experiments/` (or `runs/`) directory outside of
  `sample_submission/`, one subfolder per iteration (e.g.
  `experiments/2026-09-28_baseline/`, `experiments/2026-09-29_analyzer-subagent/`).
  Point `swegemma eval --results-dir` at that subfolder so `summary.json`,
  `task_results.jsonl`, `patches/`, `traces/`, and `logs/` are preserved per-run
  instead of overwritten.
- Alongside each run's results, snapshot the exact submission config that produced
  it (copy or symlink the `agent.yaml`/`prompts/`/`sub_agents/` used, or just
  `git commit` the submission dir before running — see below).
- Maintain a single running `experiments/CHANGELOG.md` (one entry per iteration):
  date, **the hypothesis for the change** (what you expected to happen, not just
  what changed), resolution rate, notable regressions/improvements by task or
  repo, and the results-dir path. This is the fast index into "what did I try,
  why, and what happened" without re-reading every `summary.json` — and it's
  what a later promotion/comparison decision (step 4) gets justified against.
- Put the submission-in-progress under git (even though the outer project isn't a
  repo yet) so every eval run can be tagged/associated with a commit hash —
  turns "which prompt version produced this trace" into a one-line lookup, and
  makes it trivial to `git diff` between two iterations or revert a regression.
- When a run regresses or a task flips from pass→fail, the logged trace/log path
  from that exact run is what you pull up to debug — no need to reproduce blind.

### Optional layer: MLflow for metrics/params (dev-time only)
The file-based log above (`experiments/` + `CHANGELOG.md`) is the source of truth
and always works offline. MLflow (tracking server already running at
`http://localhost:5001/`) is a useful *additive* layer for cross-run comparison —
but only ever invoked from dev tooling, never from inside the submission itself.
- **Never call MLflow from within `agent.yaml`/tools/skills or anything that ships
  in `submission.zip`.** The graded rerun is a code competition scored in a
  black-box Kaggle notebook, and the agent's own sandbox containers already run
  with `network_mode=none` (per the harness README). A live tracking call on that
  path either fails outright or, worse, hangs/retries and burns into the 12-hour
  budget. MLflow logging happens in the *harness/eval driver*, wrapping each
  `swegemma eval` invocation — after the fact, not inside the agent loop.
- **Tag every run by environment/backend** so scores are never compared across
  incompatible setups: `backend=stand-in-e4b` (local Mac debug via
  Ollama/LM Studio), `backend=gemma-4-31b-qat` (real competition model, rented
  GPU), `env=local-mac` / `env=rented-gpu` / `env=kaggle-notebook`, plus a
  `fidelity` tag (`structural` / `proxy-model` / `official-model`). Also record
  git commit + dirty-worktree status and hashes of `agent.yaml`/prompts/skills/
  adapters/`eval_config.yaml` so a run is fully reproducible from its tags alone.
- **Reserve the metric name for real runs**: log `resolution_rate` only for
  official `gemma-4-31b-qat` runs; log stand-in-model runs as
  `proxy_resolution_rate`. This makes it structurally impossible to accidentally
  sort/compare a proxy score against a real one in an MLflow table.
- **Run hierarchy**: one parent run per agent version/eval batch, with one nested
  child run per task (task ID, repo, pass/fail, failure bucket, tool calls, turns,
  nudges, tokens, elapsed time, patch size, and pass↔fail regression direction
  vs. the comparison run). Parent-run metrics are the aggregate (resolution rate,
  error count, tool-call validity, patch-application rate, timeout rate). This
  gives queryable regression tracking instead of eyeballing `task_results.jsonl`
  diffs.
- Log params (agent variant, prompt/git hash, tool budgets, thinking_budget, LoRA
  rank) and metrics as above. Artifact policy: always attach config snapshots,
  `summary.json`, and `task_results.jsonl`; attach full traces/transcripts/test
  output only for **failed, regressed, or notably improved** tasks — routine
  successful-task traces stay on local disk with just their path/checksum logged
  to MLflow. Likewise, never re-upload `snapshots/`/`wheels/`/`graphs/`/
  `embeddings/` per run — record their dataset version/checksum instead.
- **Failure tolerance is a hard requirement, not a hope**: an MLflow outage must
  never block or fail an eval run. Local results (`experiments/<label>/`) are
  always written first and are the source of truth regardless of tracking-server
  reachability; wrap MLflow calls so failures there are caught and logged, with
  offline ingestion into MLflow supported later.
- **`localhost:5001` only resolves on the Mac itself.** For local-Mac and
  rented-GPU runs that's fine (or tunnel the rented box in). For a Kaggle
  notebook, "localhost" means the Kaggle container, not the Mac — reaching the
  home server needs a public tunnel (Tailscale funnel / ngrok / Cloudflare
  tunnel). Simpler and more robust: in a Kaggle notebook, use MLflow's local
  file-backed tracking (`mlruns/` written to notebook output, no live
  connection), then pull it down and merge into the real server afterward —
  avoids any dependency on a live connection stalling a dev session.
- **Repo layout enforces the dev/submission boundary structurally**, not just by
  convention: competition files live under `submission/` (this is what gets
  zipped); MLflow wrapper/ingestion scripts live under `devtools/mlflow/`; native
  `swegemma` output lives under `results/`; experiment snapshots/changelog live
  under `experiments/`. MLflow itself stays in `requirements-dev.txt` (a
  dev-only dependency group), never a dependency of anything under `submission/`.
  A host-side wrapper (`devtools/mlflow/run_evaluation.py`) starts the parent
  run, snapshots the config, launches `swegemma eval` as a subprocess against a
  unique results dir, then parses `summary.json`/`task_results.jsonl` into
  per-task child runs after the fact — the agent runtime itself never imports
  MLflow. A companion `devtools/mlflow/ingest_results.py` lets a completed
  local or rented-GPU results dir be logged after the fact without touching the
  agent runtime at all.
- Given the Mac's hardware limits, MLflow will mostly see three run families:
  sandbox/submission validation on the Mac (Docker, `--platform linux/amd64` if
  wheels are x86_64-only), stand-in-model agent-loop debugging on the Mac (small
  Gemma 4 variant like E4B via Ollama/LM Studio — scores are meaningless, bugs
  are free), and the real `gemma-4-31b-it-qat-w4a16-ct` eval + LoRA training on
  rented GPUs — keep these three visually distinct in MLflow via the tags above.

## 3. Reproduce the baseline before changing anything
- Run `swegemma eval` on `sample_submission/` against all 129 training tasks (or a
  small `--task-ids` subset first) to get a working end-to-end loop and a real
  resolution-rate number.
- Establish it as **three separate baselines**, not one number, since each tells
  you something different and each costs progressively more:
  - **Mac structural baseline**: agent compiles, includes resolve, tools/Docker
    setup works, patches extract and apply, selected tests run — no claim about
    model quality (this can even run with `--skip-agent-patch` or a trivial
    no-op agent just to validate the pipeline).
  - **Mac proxy-model baseline**: same suite driven by a small stand-in model
    (see step 6's local-loop debugging) — logged as `proxy_resolution_rate`,
    useful for orchestration/tool-calling bugs, not for judging solution quality.
  - **Official GPU baseline**: the real `gemma-4-31b-it-qat-w4a16-ct` via vLLM on
    rented hardware — the first number that's actually `resolution_rate`.
    **Done (2026-09-30)** — run via a personal Kaggle notebook
    (`devtools/generate_official_baseline_notebook.py`) rather than rented
    GPU hardware, on the smoke cohort. `resolution_rate=0/4`, but the real
    value was structural: caught a genuine config bug invisible to every
    proxy-model run this project has done — `max_output_tokens: 16384`
    left too little input headroom on the real model's 32768-token context
    window, crashing 3/4 tasks with `ContextWindowExceededError`. Fixed
    (→ 8192) and **re-validated same day**: re-ran clean, zero crashes,
    one task (`httpx_3672`) completed fully cleanly — first-ever clean
    agent-loop finish on the real official model. Still
    `resolution_rate=0/4` (n=4 smoke sample). **Scaled to the 19-task
    `comparison` cohort same day** (`devtools/generate_official_comparison_notebook.py`)
    — `resolution_rate=2/19 (10.5%)`, first-ever real resolutions in this
    project (verified non-trivial, `test_exit_code=0`). The
    `max_output_tokens` fix held mostly but not completely — crash rate
    dropped 75%→5.3%, one task still hit it on a long trajectory. 16/17
    unresolved tasks cleanly exhausted the turn budget at exactly 14 tool
    calls each, suggesting `max_turns` (not tool-call budget) is the
    binding constraint right now. See `experiments/CHANGELOG.md`
    "2026-09-30_official-smoke-v1", "-v2", "-comparison-v1", and
    `README.md`'s official-model-baseline section for full detail.
- Log each as its own `experiments/00_baseline-<tier>/` per the practice above —
  these are the reference points every later run gets compared against.
- **Resource profiling** alongside each run: container platform, CPU/memory
  limits and peak utilization, tool calls, turns, context usage, per-task
  duration, timeout rate, and a projected full-129-task runtime — this is what
  later tells you whether a fancier agent design will actually fit the 12-hour
  submission budget (see step 10).
- Inspect `summary.json`, `patches/`, `traces/`, `logs/` to understand what the
  baseline agent does well/poorly.

## 4. Define evaluation cohorts and a lightweight promotion checklist
This is a discipline to follow, not infrastructure to build — the goal is to stop
wasting rented-GPU budget on a candidate that a cheaper check would have already
rejected, and to stop prompt iteration from quietly overfitting to the 129 public
tasks.
- **Fixed cohorts**, reused consistently across iterations:
  - A small smoke set (one or two tasks per repo, covering common failure
    classes) — near-free, run on every change.
  - A prompt-development set (~15–25 tasks) — the day-to-day iteration set.
  - A comparison set for candidate-vs-champion decisions. **Implementation
    note (2026-09-29)**: `cohorts.json` made this repo-*proportional*
    (matching each repo's share of the 129 tasks: 10 fastapi / 2 requests /
    7 rich, 0 httpx since its 1 task is already in `smoke`), not strictly
    repo-*balanced* (equal counts per repo) — true balance is impossible
    anyway given httpx has only 1 public task total. Proportional was the
    deliberate, defensible choice; noted here so "balanced" isn't taken
    literally.
  - **A held-out slice of the public tasks that is never inspected during prompt
    development** — the only thing standing between "improved on my dev set" and
    "actually improved." Set this aside now, before any prompt tuning starts.
  - The full 129-task suite — reserved for milestone checkpoints only.
- **Champion tracking**: keep one current "champion" config (the best validated
  submission so far). Every new candidate gets a **paired comparison** against
  the champion — same task cohort, same model backend, same budgets/sampling/
  seed — before it's allowed to replace the champion. Note run-to-run variance
  if generation is nondeterministic; don't promote on noise.
- **Promotion checklist** (informal gate, run through it by hand before spending
  rented-GPU time): config validates → passes the Mac smoke set → passes the
  proxy-model set → beats or matches the champion on the prompt-dev/comparison
  cohort on the official model → beats or matches the champion on the held-out
  slice → only then run the full 129-task suite as a milestone check.
- Scope this to your actual solo-dev capacity: this is a checklist you walk
  through, not an automated system you build — building the gate itself is a
  time sink you don't have room for before the entry deadline.

## 5. Analyze failure modes
- Bucket failures into four crisp categories (matters because each points at a
  different fix — better retrieval vs. better reasoning vs. harness config vs.
  guardrails):
  - **Navigation**: failed to find the relevant file/function at all.
  - **Reasoning**: right file/function found, but wrong logic applied.
  - **Operational**: truncated tool calls, budget exhaustion, patch-apply
    failures.
  - **Constraint**: accidental tampering with `pytest.ini`/`conftest.py` or other
    protected paths.
- Look at repo-level breakdown across the **4 actual task repos** —
  fastapi/fastapi, Textualize/rich, psf/requests, encode/httpx (confirmed via
  `tasks.jsonl` in step 3; starlette/pydantic are fastapi's *dependencies*,
  bundled in `wheels/` — they never generate their own tasks) — to see if some
  repos need more graph-tool usage. A repo skewed toward Navigation failures
  needs better graph-tool prompting; one skewed toward Reasoning needs better
  fine-tuning/prompt logic, not more retrieval.

## 6. Design the agent architecture
- Decide: single `LlmAgent` vs. root + sub-agents. Candidate multi-agent split:
  - **Root Coder Agent** — orchestrator, high-level planner, final `submit_patch()` caller.
  - **Code Analyzer Sub-Agent** — read-only `AgentTool` (`skip_summarization: true`)
    for graph-based repo exploration, keeps `read_file` noise out of the root
    agent's context (per README §10.4).
  - **Verification Agent** (optional) — specialist that writes/runs reproduction
    scripts in `/tmp` and confirms the fix before handoff back to the coder.
- Encode a structured operating loop in the system prompt: **Think → Explore →
  Reproduce → Fix → Verify → Submit**, so the agent reliably reproduces the bug
  before editing and re-verifies before calling `submit_patch()`.
- Write/iterate `agent.yaml`, `prompts/system.md`, tool selection (all 9 tools vs.
  subset), `generate_content_config` (thinking budget vs. output tokens tradeoff —
  32k total ceiling).
- Decide whether to lean on `search_similar_code`/`get_code_neighbors`/
  `get_code_subgraph` heavily in the prompt strategy since graphs/embeddings are
  precomputed per repo — goal is fewer blind `read_file` calls per task.
- **Architecture ablation — cheap cohort only, never the full suite or the
  official model by default**: compare single-agent vs. +analyzer vs. +verifier
  vs. both, on the Mac proxy-model/smoke cohort from step 4. Keep a sub-agent
  only if its resolution gain on that cheap cohort justifies its added token and
  runtime cost; confirm the winner once on the official-model comparison cohort,
  not by running the full matrix on rented GPUs.

## 7. Prompt-engineering iteration loop
- Tight loop: edit YAML/prompts → `swegemma eval --task-ids ... --max-tool-calls
  ... --max-time-minutes ... --results-dir experiments/<label>/` on the
  prompt-development cohort (step 4) → check `task_results.jsonl` and traces →
  adjust → log in `experiments/CHANGELOG.md` with the hypothesis being tested.
- Apply the README's gotchas: keep edits incremental (avoid `<|tool_call>`
  truncation), never touch `pytest.ini`/`conftest.py`, keep scratch scripts out of
  `/workspace` (or delete before `submit_patch`), always call `submit_patch()`
  last.

## 8. Custom ADK Skills (optional force-multiplier)
- Consider packaging reusable `skills/<name>/SKILL.md` (+ `scripts/`, `resources/`)
  for things worth codifying once and reusing across tasks — e.g. a repo-mapping
  routine, a standardized regression-test scaffold, or repo-specific navigation
  notes for the 4 actual task repos (fastapi/fastapi, Textualize/rich,
  psf/requests, encode/httpx). Scripts run sandboxed via `run_skill_script`
  and debit the same execution budget, so scope them tightly.
- **Retrieval ablation — cheap cohort only**: compare filesystem-only vs.
  graph-first vs. hybrid navigation on the smoke/prompt-dev cohort. Track tool
  calls and tokens spent before opening the first relevant file, redundant-read
  rate, and total navigation time, alongside resolution rate — this is what
  tells you whether the graph tools are actually earning their token budget for
  a given repo, not just assumed to help.
  **Done (2026-09-30, proxy-model, `smoke` cohort, n=4/arm)** — see
  `experiments/CHANGELOG.md` "step 8 retrieval ablation" addendum for the full
  writeup. Headline: resolution rate gave no signal (0/4 all arms); on
  navigation metrics, forcing graph-first actually *hurt* this stand-in model
  (only 1/4 tasks reached a real fix attempt, vs. 4/4 for filesystem-only and
  2/4 for hybrid) — a mandatory graph-tool call plus a redundant-`read_file`
  loop pathology ate the turn/tool-call budget before it could edit. No change
  made to the shipping `submission/` (kept hybrid/optional) — small n,
  proxy-model only, re-validate on the official model before trusting this
  generalizes.

## 9. (Optional but likely needed for competitiveness) LoRA fine-tuning
- Build SFT/RL training data from the 129 tasks (problem_statement → tool-call
  trajectory → patch), or use synthetic trajectories from a stronger model as
  teacher.
- **Data discipline (do this before generating any trajectories, not after)**:
  split task IDs into train/dev/validation sets first, and keep the held-out
  slice from step 4 out of the training set entirely. Track which source task
  produced every training example, and explicitly verify no reference `patch` or
  validation-cohort trajectory leaks into the training data — easy to do
  accidentally since `tasks.jsonl` ships the reference patch right next to the
  problem statement.
  **Done (2026-09-30)** — see `experiments/CHANGELOG.md` "Step 9 (part 1)"
  entry. `devtools/define_lora_splits.py` draws train/dev/validation
  exclusively from `unassigned_pool` (46/10/10), excluding `held_out` plus
  `comparison`/`prompt_dev`/`smoke` too (not just what the plan names), with
  explicit leakage assertions.
  `devtools/build_lora_trajectories.py` turns each task's reference patch
  into the exact tool-call sequence that produces it, verified per-task by
  replaying it and diffing byte-for-byte against a real `git apply` — 62/66
  (93.9%) tasks produced a verified trajectory, the rest logged and skipped
  rather than guessed. No model calls, no GPU — this is the "synthetic
  trajectories" path since the stand-in model has zero real successful
  trajectories to draw on yet.
- Train LoRA adapter(s) for the coder agent (and optionally a separate lighter
  adapter for a navigator/analyzer sub-agent) — start with modest ranks (16, 32)
  and only expand rank if evaluation evidence on the comparison cohort actually
  supports it (r=16–32 is safest under the 3 GiB budget with headroom).
- Validate adapters don't break the single-base-model rule and fit `max_loras=8`,
  `max_lora_rank=128`.
- Log training runs too: dataset/trajectory hashes, hyperparameters, target
  modules, checkpoint/adapter checksums, and the exact official-model eval run
  (results-dir + MLflow run) the resulting adapter was benchmarked against.

## 10. Full local evaluation & scoring
- Run the full 129-task suite with realistic budgets matching what Kaggle will
  use, get a stable resolution-rate baseline to compare iterations against —
  reserved for milestone checkpoints per the promotion checklist in step 4, not
  every iteration.
- **Resumable batches**: skip task IDs that already have complete, valid results
  in the target results-dir; preserve partial output on interruption; resume
  without duplicating MLflow child runs for tasks already logged.
- **Budget validation**: before treating a full-suite run as final, confirm the
  projected full-suite runtime, per-task timeout, tool-call/turn budgets, context
  usage, and container resource limits actually fit inside the 12-hour total
  execution budget — this is a hard submission constraint, not just a nice
  number to hit.
- Watch for container resource limits (4GB RAM / 2 vCPU per sandbox) causing
  spurious failures.

## 11. Package and validate the submission
- Assemble `submission.zip` from an **explicit allowlist** of paths under
  `submission/` only: root YAML files plus `configs/`, `prompts/`, `sub_agents/`,
  `skills/`, `adapters/`. Reject anything else at packaging time — in particular
  MLflow directories, `devtools/`, `results/`, `experiments/`, `.env`/credential
  files, tracking URLs, unsupported extensions, and symlinks.
- Self-check against hard constraints: single declared model, <3 GiB unpacked,
  allowed file extensions only, no path traversal/symlinks, instruction/size
  ceilings.
- **Submission isolation checks** (closes the loop on step 2's dev/submission
  boundary — verify it actually held, don't just trust the layout):
  1. Extract the archive and validate/compile it in an environment with MLflow
     *uninstalled*.
  2. Grep the extracted contents for MLflow imports, tracking URLs, and MLflow
     env vars — must find none.
  3. Diff archive contents against the explicit allowlist above.
  4. Confirm exactly one root agent config exists (`MissingRootConfigError` /
     `MultipleRootConfigsError` guard).
  5. Compile and smoke-test the agent using *only* the extracted archive (not the
     working `submission/` tree, to catch anything the allowlist missed).
  6. Record the final archive checksum (in MLflow, as the candidate submission
     identifier) so the exact zip that was validated is traceable later.
- Optionally set `eval_config.yaml` budgets deliberately (time/tool-calls/turns)
  rather than relying on defaults.
- **Pre-submit cleanup check**: confirm no scratch/repro files remain untracked in
  `/workspace` (they'd get swept into the patch by `git add -N .`), and dry-run
  the zip through the same size/extension/model validation the harness applies.
- **Release candidate record**: once a candidate passes the full promotion
  checklist, treat it as immutable — record its archive checksum, git commit,
  the official-model eval run it was validated against, config hashes, and a
  short validation summary in both MLflow and `experiments/CHANGELOG.md`.

## 12. Track against competition timeline
- Entry/rules acceptance and team merger deadline: **Nov 25, 2026**. Final
  submission: **Dec 2, 2026**. Optional paper track: **Nov 12, 2026**. Plenty of
  runway from Sep 28, 2026, but the LoRA training step (if pursued) is the long
  pole — worth starting data prep early.
- Set internal milestones against those dates rather than working toward them
  blind. Proposed schedule (adjust as real progress dictates — this is a
  planning target, not a commitment):

  | Milestone | Target date | Status (2026-09-30) |
  |---|---|---|
  | Environment/data readiness | 2026-09-29 | **Done** |
  | First structural baseline | 2026-09-29 | **Done** |
  | First proxy-model loop | 2026-09-29 | **Done** |
  | Architecture decision (step 6) | 2026-09-29 | **Done** — single-agent |
  | Retrieval ablation (step 8 remainder) | 2026-10-06 | **Done** (2026-09-30) — filesystem-only vs. graph-first vs. hybrid, n=4/arm proxy-model; no shipping change |
  | LoRA training data (step 9 part 1) | — | **Done** (2026-09-30) — 62/66 verified reference-patch trajectories |
  | First official-model baseline | 2026-10-13 | **Done** (2026-09-30, ahead of schedule) — via personal Kaggle notebook, not rented GPU. Found, fixed, and re-validated a real `max_output_tokens` context-window bug; scaled to the 19-task `comparison` cohort same day — `resolution_rate=2/19 (10.5%)`, first-ever real resolutions in this project |
  | LoRA go/no-go decision | 2026-10-20 | Not started |
  | LoRA freeze (if pursued) | 2026-11-03 | — |
  | Full 129-task official-model evaluation | 2026-11-17 | — |
  | Final candidate freeze | 2026-11-25 | — (matches entry/merger deadline) |
  | Submission packaging + isolation checks + submit | 2026-11-30 | — (2-day buffer before Dec 2) |
