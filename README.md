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
devtools/setup_env.sh  # Reproducible local environment setup (see below)
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

Requires **Python 3.13** on PATH (matches the sandbox container — `swegemma`
won't install on 3.11/3.12), Docker running, and Kaggle credentials already
configured (`python3 -c "import kagglehub; kagglehub.login()"` once per
machine — prompts for an API token from kaggle.com/settings → API, writes it
to `~/.kaggle/access_token`; never paste the token in chat/logs).

```
./devtools/setup_env.sh
```

This is idempotent — re-running it skips whatever's already cached/installed.
It does, in order:

1. Creates `.venv` on Python 3.13 (fails loudly if `python3.13` isn't found).
2. Installs `kagglehub`, appends a `KAGGLEHUB_CACHE` export to
   `.venv/bin/activate` so all kagglehub downloads land in `downloads/`
   (gitignored) instead of the global `~/.cache/kagglehub`.
3. Verifies Kaggle auth (`kagglehub.whoami()`).
4. Downloads the competition dataset (`kagglehub.competition_download(...)`)
   → `downloads/kagglehub/competitions/gemma-4-developer-agent/` (~21 GB:
   tasks, snapshots, graphs, embeddings, wheels, docker specs, sample_submission).
5. Downloads the **harness wheelhouse** and installs the 4 pure-Python wheels
   from it. `swegemma`/`adk_submission`/`adk_eval_core` are **not on PyPI and
   not in the competition dataset** — not mentioned anywhere in
   `HARNESS_README.md`/`Overview`/`Data` either. They only surface via the
   organizer's getting-started Kaggle notebook
   (`kaggle kernels pull ryanholbrook/getting-started-gemma-4-developer-agent`),
   whose first cell references the Kaggle dataset handle
   `metric/gemma-4-developer-agent-wheelhouse`
   (`kagglehub.dataset_download('metric/gemma-4-developer-agent-wheelhouse')`).
   That dataset (~827 MB, currently version 25 — the script resolves whatever
   the *current* version is at install time rather than hardcoding it) has
   ~41 wheels; most (`vllm`, `bitsandbytes`, `flashinfer`, `apache_tvm_ffi`,
   etc.) are CUDA/`manylinux_x86_64`-only, for real vLLM serving on rented GPU
   hardware — not needed on the Mac. The four installed are pure Python
   (`py3-none-any`): `adk_eval_core`, `adk_submission`, `swegemma`, `google_adk`.
6. Installs every remaining transitive dependency pinned in
   `requirements-lock.txt` (regenerate via the command in that file's header
   after any deliberate dependency change).
7. Builds `swebench-sandbox:latest` from the dataset's `docker/Dockerfile.sandbox`
   if it doesn't already exist locally.

### Verified (2026-09-29)

- `swebench-sandbox:latest` builds and runs **natively on `arm64`** — no
  `--platform linux/amd64` emulation needed for the base image.
- Ran `swegemma eval --sandbox docker --skip-agent-patch` (bypasses Phase 1 —
  no model/vLLM server needed — and goes straight to Container B verification
  with an empty patch) against one task per repo: `fastapi_15661`,
  `requests_7505`, `rich_4070`, `httpx_3672`. All four: container spun up,
  snapshot extracted, editable install + wheel resolution succeeded, pytest
  ran to completion, `errors: 0` in `summary.json`, durations 3–20s. Two
  (`fastapi`, `httpx`) hit expected pytest **collection** errors (missing
  module / missing attribute) because the reference fix — which the test file
  depends on — was deliberately not applied (`--skip-agent-patch`); this is
  correct Fail-to-Pass behavior, not an infra problem. No wheel/architecture
  errors surfaced for any of the four repos.
- Still open: this only exercises Container B (`--skip-agent-patch` skips
  Container A / the actual agent loop entirely). A true end-to-end run needs
  either the real model on rented GPU or a local stand-in model — see plan
  step 3 ("three baselines").

## Development log / experiment tracking (plan step 2)

Every eval run should go through `devtools/mlflow/run_evaluation.py` rather
than calling `swegemma eval` directly — it wraps the file-based logging
practice (always the source of truth) with best-effort MLflow logging
(purely additive, never blocking):

```
python3 devtools/mlflow/run_evaluation.py \
  --label 2026-09-29_my-change \
  --submission-dir submission \
  --task-ids fastapi_15661 requests_7505 \
  --backend gemma-4-31b-qat --env local-mac --fidelity official-model \
  --cohort smoke \
  --hypothesis "What you expect this change to do"
```

What it does, every time, regardless of whether MLflow is reachable:
1. Snapshots the exact submission config used to
   `experiments/<label>/submission_snapshot/`.
2. Warns (doesn't block) if `submission/` has uncommitted changes — the run's
   `config_hash` still pins the exact bytes, but the `git_commit` tag won't
   point at a commit containing them.
3. Runs `swegemma eval` as a subprocess against a unique `results/<label>/`
   dir.
4. Appends a templated entry to `experiments/CHANGELOG.md` (hypothesis,
   change, cohort, result, results dir, commit, MLflow link).

Then, best-effort: logs one MLflow **parent run** (tags: `backend`, `env`,
`fidelity`, `git_commit`, `git_dirty`, `config_hash`, `hypothesis`; metrics:
`resolution_rate` for `fidelity=official-model` runs or
`proxy_resolution_rate` otherwise — never the same metric name, so a proxy
score can't be accidentally sorted against a real one; per-repo rates;
patch-generation/timeout rates) with one nested **child run per task** (tags:
`instance_id`/`repo`/`resolved`; metrics: tool calls, turns, duration, patch
size, test exit code). Trace + test-output log artifacts are attached only
for failed/errored tasks — routine successful-task traces stay on local disk
only. If MLflow logging fails for any reason (server down, network, etc.),
the run and CHANGELOG entry above are entirely unaffected; a warning prints
to stderr and `run_evaluation.py`'s exit code still reflects `swegemma eval`.

For a results dir produced elsewhere (e.g. downloaded after a rented-GPU run,
or a local run executed with an unreachable MLflow server), ingest it after
the fact without re-running the eval:

```
python3 devtools/mlflow/ingest_results.py \
  --results-dir results/<label> --label <label> \
  --submission-snapshot experiments/<label>/submission_snapshot \
  --backend gemma-4-31b-qat --env rented-gpu --fidelity official-model
```

Both scripts share `devtools/mlflow/mlflow_logging.py`. MLflow's tracking URI
defaults to `http://localhost:5001`. **Gotcha already fixed in this code**: a
freshly-created MLflow experiment can default to a local-filesystem artifact
root the client can't write to (varies by server config) — both scripts
explicitly create new experiments with a proxied `mlflow-artifacts:` location
to avoid this.

### Verified (2026-09-29)

Ran `run_evaluation.py` against the same 4-task `--skip-agent-patch` smoke
cohort from the step-1 structural test. Confirmed via the MLflow REST API:
parent run `FINISHED` with all 3 expected artifacts attached
(`config_snapshot/`, `summary.json`, `task_results.jsonl`); 4 child runs
`FINISHED` with correct tags/metrics; the checked child run (unresolved) had
its trace + test-output log correctly attached per the fail-only artifact
policy. `experiments/CHANGELOG.md` entry and MLflow link both correct. See
that file for the one bug this test caught and the fix.

## Baseline reproduction (plan step 3)

### Mac structural baseline — done (2026-09-29)

```
python3 devtools/mlflow/run_evaluation.py --label 00_baseline-structural \
  --submission-dir downloads/kagglehub/competitions/gemma-4-developer-agent/sample_submission \
  --skip-agent-patch --sandbox docker --concurrency 3 \
  --backend none --env local-mac --fidelity structural --cohort full-129 \
  --hypothesis "..."
```

Full 129-task run (not just the 4-task sample from steps 1–2): 19.5 min wall
clock at `--concurrency 3`, `errors: 0`. Full findings (exit-code breakdown,
a resource-constraint pattern isolated to `rich`, and a dataset-curation
finding — 4 tasks resolve with zero code changes) are in
`experiments/CHANGELOG.md`'s `00_baseline-structural` entry — read that
before interpreting any future resolution-rate number, since ~3.1% of tasks
carry "free credit" independent of agent quality in this environment.

> **Lesson learned**: don't combine the Bash tool's `run_in_background: true`
> with a manual trailing `&` on the same command — the outer wrapper reports
> "completed" almost immediately while the actual process gets orphaned and
> killed early (caught this after a first attempt silently stopped at 9/129
> tasks). Use one or the other, not both.

### Mac proxy-model baseline — wiring validated, model needs more budget

Pulled `gemma4:e4b` via Ollama (9.6 GB) — a genuine small Gemma 4 variant
(not the "uncensored-heretic" unofficial fine-tunes already present locally,
which wouldn't validate real tool-calling behavior against the harness's
`tool_call_parser=gemma4`/`reasoning_parser=gemma4` expectations). Confirmed
`tools` capability and real OpenAI-format tool-call output via a direct
`/v1/chat/completions` test before wiring it in.

`devtools/models-ollama-e4b.yaml` overrides the competition's required model
alias (`gemma-4-31b-it-qat-w4a16-ct`, plus the `main_lora`/`tool_lora`
adapter aliases `sample_submission/agent.yaml` references) to route to
Ollama instead of a real vLLM server — `sample_submission/agent.yaml` itself
is never modified. Pass it via `run_evaluation.py --models-yaml
devtools/models-ollama-e4b.yaml`.

```
python3 devtools/mlflow/run_evaluation.py --label <name> \
  --submission-dir downloads/kagglehub/competitions/gemma-4-developer-agent/sample_submission \
  --models-yaml devtools/models-ollama-e4b.yaml \
  --task-ids fastapi_15661 --sandbox docker \
  --max-tool-calls 15 --max-turns 10 --max-time-minutes 5 \
  --backend stand-in-e4b --env local-mac --fidelity proxy-model --cohort smoke \
  --hypothesis "..."
```

**Wiring fully validated**: an isolated single-task run produced 3 real tool
calls, 6 LLM turns, and a real 550-byte submitted patch in 189s — proving
the alias-override + Ollama routing + Container-A tool-calling all work
end-to-end. **But at scale (4-task smoke cohort, both `--concurrency 1` and
`--concurrency 2`) every task timed out at the 5-minute budget** — root
cause isolated via the trace files: `gemma4:e4b` tends to fall into
reasoning loops, restating near-identical analysis across many consecutive
turns instead of acting decisively (not a caching/latency problem — cache
hit rate was 77%). Full analysis in `experiments/CHANGELOG.md`'s
`00_baseline-proxy-model` entries. This is itself the kind of
orchestration/tool-calling finding this baseline exists to surface, per the
plan — not a benchmark number to report. Larger budgets and/or
anti-repetition prompt steering (step 6) would likely be needed before this
stand-in model is useful for real orchestration debugging at scale.

### Official GPU baseline — deferred

Needs rented NVIDIA hardware and real spend; out of scope to set up without
explicit go-ahead. Current plan: the user will run this via Kaggle notebooks
directly rather than this repo's local tooling.

## Evaluation cohorts & promotion checklist (plan step 4)

A discipline, not tooling — see the plan. `experiments/cohorts.json`
(generated once, reproducibly, by `devtools/define_cohorts.py`; don't
regenerate casually, membership must stay stable) defines: `smoke` (4 tasks,
the ones already used throughout steps 1-3), `held_out` (19 — **never
inspect these during prompt development**), `prompt_dev` (21), `comparison`
(19), and an `unassigned_pool` (66, no current purpose). It also flags which
cohorts contain step-3's known-anomalous tasks (zero-code-change resolves,
OOM/timeout) so results can be interpreted correctly.

`experiments/PROMOTION_CHECKLIST.md` is the literal, hand-walked gate to run
through before spending rented-GPU budget on a candidate: config validates →
Mac smoke → proxy-model smoke → beats/matches champion on
prompt-dev/comparison (official model) → beats/matches champion on held-out
→ full 129-task milestone check. `experiments/CHAMPION.md` tracks the
current best validated config — currently "none yet", since `submission/` is
still the empty scaffold from step 0.

## Failure-mode analysis (plan step 5)

Classified the 4 proxy-model-baseline traces into the plan's four failure
categories (Navigation / Reasoning / Operational / Constraint) — the
structural baseline can't be used for this since `--skip-agent-patch` means
no real agent reasoning ever happened there. Result, with all 4 tasks having
timed out without submitting a patch: **3/4 Operational** (2 reasoning
loops — same pattern found in `requests_7505` during step 3, now also seen
in `httpx_3672`; 1 tool-call parameter error in `rich_4070`), **1/4
Navigation** (`fastapi_15661` — model didn't realize it could explore via
`run_command`, compounded by a vague problem statement), **0/4** clear
Reasoning-quality or Constraint failures.

**Key takeaway**: this stand-in model never gets far enough for a
"right file, wrong logic" (Reasoning) failure to even become observable —
it's blocked at the Operational layer first. Per the plan's own
category→fix mapping, that points at prompt-level fixes (anti-repetition
steering, explicit exploration guidance, `edit_file` usage examples) as the
highest-leverage next step for this model — not graph-tool/retrieval
investment. Sample size is small (1 task per repo) — full write-up with
caveats in `experiments/CHANGELOG.md`.

## Agent architecture (plan step 6)

`submission/` now has a real `agent.yaml` + `prompts/system.md` +
`configs/sampling.yaml` — single `LlmAgent`, no sub-agents. The prompt
directly targets step 5's evidenced failures: anti-repetition steering,
explicit `run_command`-for-exploration guidance, worked `edit_file`
old_string/new_string examples.

**Caught a real packaging bug immediately**: `.gitkeep` placeholders left
over from initial scaffolding (`submission/adapters/`, `skills/`,
`sub_agents/`) have no file extension, which violates the harness's
allowlist — `Sandbox execution error: File has disallowed extension ''`.
This would have broken a real Kaggle submission too; removed.

Re-tested the exact two step-5 failure cases with a generous 15-min budget
(vs. the 5-min sanity budget, to separate "prompt is bad" from "budget is
too tight"): `fastapi_15661`'s Navigation failure looks **fixed** (real
exploration happened this time — read multiple files, ran a script,
investigated a real error — though this specific task is unusually hard and
still didn't finish in budget). `rich_4070`'s `edit_file` parameter-swap
mistake **did not recur**, but a *different* `edit_file` failure surfaced
("old_string too large/complex"), and getting stuck on it triggered the
same repetitive-restatement pattern again. Neither task completed within
budget. Full trace-level analysis in `experiments/CHANGELOG.md`.

**Architecture decision: single-agent for now, sub-agent ablation
deferred.** The Code Analyzer sub-agent's value proposition (reducing
`read_file` context noise) doesn't address the currently-dominant failure
mode (`edit_file` mechanics, residual repetition under difficulty) — running
the full ablation matrix now would likely just measure the same operational
noise across all variants rather than discriminate between them. Revisit
once step 7's prompt iteration clears the current operational issues.

## Prompt-engineering iteration (plan step 7)

**Round 1** (two independent fixes, tested against the two tasks that
originally exposed each): added explicit `old_string`-splitting guidance +
a "stop retrying, try something else" fallback to `system.md`, tested
against `rich_4070`; added a "don't resubmit the same tool-call arguments"
rule, tested against `requests_7505`.

- **`edit_file` fix: confirmed working.** `rich_4070` went from
  `agent_patch_size=0` to `556` — real edits landed, no more "old_string too
  large" failures.
- **Anti-repetition fix: partial — changed shape, didn't eliminate it.**
  `rich_4070` stalled in a *new* way after its successful edit (repeatedly
  re-summarizing progress instead of moving to the next file or verifying).
  `requests_7505` repeated the literal same `grep` command three times —
  directly against the new rule — before stalling on re-reading the same
  file without ever calling `edit_file`. More real tool calls happened
  (14 vs. 8), but "understanding something" still isn't reliably turning
  into "acting on it."
- **Read**: this is one underlying limitation (tracking "what have I
  already tried" precisely enough to act differently) surfacing in
  different forms, not two separate bugs. Full trace-level detail in
  `experiments/CHANGELOG.md`.

Stopped here per the round's scope (two hypotheses, two tests) rather than
continuing to iterate unilaterally — next-round ideas noted in the
CHANGELOG addendum (stronger same-call-detection wording; trying a lower
`thinking_budget` to force shorter, more decisive turns).
