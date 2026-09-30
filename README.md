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

Requires **Python 3.13** on PATH (matches the sandbox container; `swegemma`'s
actual requirement is `>=3.12` — 3.13 was chosen to match the container, not
because 3.12 is unsupported), Docker running, and Kaggle credentials already
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
   not in the competition dataset.** `HARNESS_README.md` documents these
   libraries' *behavior* extensively (that's its whole purpose) but never
   says where to actually get/install them, and `Overview`/`Data` don't
   mention them at all. They only surface via the organizer's getting-started
   Kaggle notebook
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
  --models-yaml devtools/models-ollama-e4b.yaml \
  --task-ids fastapi_15661 requests_7505 \
  --backend stand-in-e4b --env local-mac --fidelity proxy-model \
  --cohort smoke \
  --hypothesis "What you expect this change to do"
```

What it does, every time, regardless of whether MLflow is reachable:
1. Snapshots the exact submission config used to
   `experiments/<label>/submission_snapshot/` — if that label already has a
   snapshot (label reuse), the old one is renamed to
   `..._superseded_<UTC timestamp>` first, never deleted.
2. Warns (doesn't block) if `submission/` has uncommitted changes — the run's
   `config_hash` still pins the exact bytes, but the `git_commit` tag won't
   point at a commit containing them.
3. Runs `swegemma eval` as a subprocess **against the frozen snapshot from
   step 1, not the live `submission/`** — so a concurrent edit to
   `submission/` after the snapshot can't silently change what actually gets
   evaluated. `results/<label>/` gets the same archive-on-reuse treatment as
   the snapshot — "unique" means "unique after archiving," not
   collision-proof on its own.
4. Appends a templated entry to `experiments/CHANGELOG.md` (hypothesis,
   change, cohort, result, results dir, commit, MLflow link) — **unless the
   eval subprocess itself failed with no `summary.json` produced at all**, in
   which case the run exits early with no changelog entry (nothing to
   summarize).

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

### Official GPU baseline — done (2026-09-30)

Ran via a personal Kaggle notebook rather than rented hardware — see
"First official-model baseline" below for the full writeup. Short version:
`resolution_rate=0/4` on the smoke cohort, but the run's real value was
catching a `max_output_tokens` context-window bug invisible to every
proxy-model run this project has done. Fix applied and **re-validated**
(2026-09-30) — zero crashes on the re-run, including the project's
first-ever fully clean completion on the real official model.

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
current best validated config — currently "none yet": `submission/` has had
a real `agent.yaml`/`prompts`/`configs`/`skills` since step 6, but no
candidate has passed the promotion checklist above (no official-model run,
no comparison-cohort pass, no held-out check) — "no champion" reflects that
gate, not an empty directory.

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

> **Scope caveat covering steps 6-8 below**: everything below was built and
> tested exclusively with `--fidelity proxy-model` (the `gemma4:e4b`
> stand-in via Ollama) — treat every "clean completion" / "fix confirmed"
> claim as *prompt-mechanics* evidence on a small stand-in model, not a
> validated improvement on the actual competition model. Three
> official-model runs now exist (2026-09-30, see step 3 above): a 4-task
> smoke run that crashed 3/4 on a `max_output_tokens` bug, a re-validation
> of the fix (clean, `resolution_rate=0/4`), and a 19-task `comparison`
> run — `resolution_rate=2/19 (10.5%)`, the project's first real
> resolutions. That's real signal that **the current submission as a
> whole** (this exact prompt, skill, and tool configuration) works on the
> real model — but it is not a controlled test of steps 6-8's *individual*
> claims below. None of the ablations that produced those claims (the
> prompt-iteration rounds, the retrieval ablation's filesystem-only vs.
> graph-first vs. hybrid comparison) have been re-run on the official
> model — only the single current configuration has real-model data. Which
> specific prior decisions are actually responsible for the 10.5%, versus
> which might be neutral or even holding it back, is still unknown.

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

Stopped there per the round's scope (two hypotheses, two tests) rather than
continuing to iterate unilaterally — next-round ideas noted in the
CHANGELOG addendum (stronger same-call-detection wording; trying a lower
`thinking_budget` to force shorter, more decisive turns).

**Round 2**: replaced the general "don't repeat reasoning" framing with a
mandatory, mechanical pre-call check ("compare this call's exact args
against every prior call this session; identical = forbidden, whether the
prior call succeeded or failed"). Tested on `requests_7505` again — the
exact task where round 1's general framing had failed (literal 3x `grep`
repeat).

**First clean completion of the whole project** (meaning: the agent loop
finished on its own — no timeout, no budget exhaustion — not that the task
was solved; `resolved` was still `false`). `error: null`, for the first time
on any real (non-`--skip-agent-patch`) proxy-model run. Finished in 338.56s (well under
the 15-min budget) with a real 609-byte patch, 11 tool calls (down from 14
in round 1 on the same task — more efficient, not just longer). `grep` was
still run twice, but this time the model actually *used* the second
result instead of discarding it and repeating again; it also caught its
own confusion mid-task about which file it was editing and self-corrected,
rather than continuing blindly.

Interesting wrinkle: the generated fix removed a `hasattr` fallback
(`isinstance(fp, _SupportsRead) or hasattr(fp, "read")` →
`isinstance(fp, _SupportsRead)`) on a task titled "Add hasattr checks" —
plausibly the wrong direction. If so, this is the **first observed
Reasoning-layer failure** in the whole project — exactly what step 5
predicted would become visible once Operational failures stopped blocking
everything. Not confirmed without reading the full problem statement; noted
for a future round, not chased further now. Full detail in
`experiments/CHANGELOG.md`.

## Custom skills (plan step 8, part 1)

Initially assumed skills weren't wired up locally (`compile_submission()`'s
call site doesn't pass a `skill_registry`) — **wrong**, confirmed
empirically: compilation independently resolves/validates skills, and a
minimal probe skill compiled cleanly once given correct kebab-case
frontmatter. Ground-truth tool signatures checked directly in
`google/adk/tools/skill_toolset.py`: resource files must live under
**`references/`** (not `resources/`, which is what `HARNESS_README.md`'s
example tree misleadingly shows).

Built `submission/skills/repo-navigation/` — one `references/<repo>.md` per
target repo, distilling everything learned in steps 1-7. Framed as
*optional* in the prompt to avoid taxing every task with an extra tool call.

**Result: never invoked.** The one test run that exercised it (`fastapi_15661`,
the exact task its notes address) never called `load_skill`/
`load_skill_resource` — full tool sequence was `ls` → read → grep → read →
edit → `pytest tests/` → `submit_patch`. So "optional" currently means
"untested," not "proven useless." Separately, that run also surfaced a real,
new issue: it ran a bare `pytest tests/` sweep against the existing "never
run bare pytest" rule — and `test_exit_code=2` is plausibly the exact
collection-error gotcha the (unloaded) skill notes already documented.

On the positive side, unrelated to the skill: **2nd** consecutive
agent-loop-finished-cleanly run (not "resolved" — same caveat as above),
264.72s, real patch, 8 tool calls, and the **first explicit
`submit_patch()` call** seen in any trace this project (every prior success
relied on the harness's automatic fallback capture). The v3 anti-repetition
fix keeps compounding. (Correction: an earlier version of this doc mislabeled
this as "3rd" — there was no run ever labeled "2nd"; the compile-only skill
probes in between were deliberate structural/budget checks, not real task
attempts, and were never meant to count either way.)

## Fixing the bare-pytest violation (plan step 8, part 2)

Applied the same mechanical-check technique that fixed anti-repetition in
step 7 round 2 to the "never run bare pytest" rule: instead of a soft
"NEVER run full-repo sweeps," a literal yes/no check on the command string
("does it contain a `.py` path or `-k`/`::` selector? If not, forbidden —
don't send it") before every `pytest`/`unittest` call.

**Confirmed working**: re-tested on the exact task that produced the
violation. Zero `pytest`/`unittest` calls of any kind this run — instead of
falling back to a broad sweep when no test file was obvious, the agent
wrote and ran its own script directly. **3rd** consecutive clean
agent-loop finish (again: loop finished without error, task still not
resolved), with a substantially larger, more substantive patch (3072 bytes
vs. 347 two runs ago on the same task).

One secondary, not-chased-further observation: with no obvious targeted
test available, the agent skipped Verify entirely rather than run anything
resembling a sweep — reasonable given the new rule, but means Verify isn't
reliably happening when no clear test target exists. Candidate for a future
round (explicit guidance for the no-obvious-test case). Full detail in
`experiments/CHANGELOG.md`.

**Mandatory skill loading — tried, reverted.** Made the repo-navigation
skill load mandatory (first tool call every task) and re-tested on the same
task. The rule worked mechanically (`load_skill_resource` was the actual
first call), but the run **broke the 3-run clean streak** — exceeded the
turn budget, zero patch. Instead of the version-bump approach that worked
in the two prior runs, it spent most of its turns on repeated `README.md`
edit attempts before pivoting to `scripts/docs.py` at the very end, never
touching the file the successful runs focused on. Plausible (not
confirmed) explanation: the skill notes mention `docs_src/` for docs
tasks, which may have nudged this ambiguous task toward a less productive
interpretation — but this exact task has shown run-to-run variance under
identical settings before, so plain nondeterminism can't be ruled out with
n=1. **Reverted to optional** — no clear evidence of benefit, one real
fixed cost (an extra turn every task), and a plausible distraction risk.
A real verdict would need a larger sample than one round's inference
budget supports. Full detail in `experiments/CHANGELOG.md`.

## Retrieval ablation: filesystem-only vs. graph-first vs. hybrid (plan step 8, part 3)

Built 3 submission variants (`devtools/retrieval_ablation/variants/`) —
`hybrid` (unchanged shipping `submission/`), `filesystem-only` (`agent.yaml`
drops the 3 graph tools, prompt/skill mentions stripped), `graph-first`
(all 9 tools, but "Locating Target Files" mandates a graph-tool call before
the first `read_file`/grep) — and ran all 3 arms × all 4 `smoke` tasks (12
runs, `--fidelity proxy-model`, identical budgets) via
`devtools/run_retrieval_ablation.py`. The harness auto-injects a
"Code Intelligence Tools" prompt section whenever graph/embedding data
exists for a task's repo, independent of `agent.yaml`'s declared tools —
confirmed this empirically before writing the runner, and suppressed it for
`filesystem-only` via a scratch cwd with empty `data/graphs`/`data/embeddings`
dirs (`devtools/retrieval_ablation/fs_only_cwd/`), so that arm's prompt
doesn't misleadingly advertise tools it can't call.

**Resolution rate gave no signal** (0/4 for all three arms — consistent
with every proxy-model run to date). The real signal is in the navigation
metrics computed by `devtools/analyze_retrieval_ablation.py` from each
run's trace: forcing graph-first measurably *hurt* this stand-in model —
only 1/4 tasks reached a real fix attempt (`edit_file`/`write_file`), vs.
4/4 for `filesystem-only` and 2/4 for `hybrid`. Trace inspection found two
distinct causes: one task where the graph-first agent ran an existing
script instead of editing source then submitted anyway (anti-pattern), and
two tasks where it fell into a 9-14-call redundant-`read_file` loop (same
file, varying line ranges) that consumed the entire budget before ever
reaching `edit_file`. The same read-loop also hit `hybrid` on one task
(`httpx_3672`) but not `filesystem-only` on that same task — suggestive
that having graph tools available at all (used or not) may correlate with
this small model's known repeated-reasoning failure mode, though this is
n=1 per cell, not confirmed.

**No change made to the shipping `submission/`** — kept the current
hybrid/optional default. The evidence is real but thin (n=4/arm, single
trial, proxy-model only) and the failure modes found are plausibly specific
to this small stand-in's weaker multi-step planning, not necessarily the
official 31B model this submission actually ships against. Re-validate once
the official-model Kaggle notebook path has run. One concrete follow-up
identified but not acted on here: the existing "mandatory pre-call check"
forbids *identical* repeated tool calls, but a `read_file` with a different
`start_line`/`end_line` slice of the same file isn't caught by that check —
candidate for a future step-7-style prompt round. Full writeup in
`experiments/CHANGELOG.md`.

## LoRA training data: splits + reference-patch trajectory synthesis (plan step 9, part 1)

Built the data pipeline for step 9's LoRA fine-tuning — no GPU involved yet,
this is pure CPU data engineering. `devtools/define_lora_splits.py` draws
train/dev/validation (46/10/10 tasks) exclusively from `cohorts.json`'s
`unassigned_pool`, the one cohort not reserved for any evaluation purpose;
`held_out`, `comparison`, `prompt_dev`, and `smoke` are all excluded (the
plan only names `held_out`, but training on what's used to judge or tune
candidates would contaminate those evaluations), with explicit leakage
assertions run every time.

`devtools/build_lora_trajectories.py` then turns each training task's
reference `patch` (tasks.jsonl ships one per task) directly into the
tool-call sequence that produces it — `write_file` for new files,
`read_file` + one `edit_file` per hunk for modified files, a targeted
`pytest` verification, `submit_patch`. This is the "synthetic trajectories"
path from the plan: the stand-in model has resolved zero smoke-cohort tasks
all project, so there's no pool of real successful trajectories to draw on
yet. The user-turn prompt reuses the harness's own `build_agent_prompt()`
so it matches production formatting exactly.

**Every trajectory is verified, not assumed correct**: the synthesized
edit sequence is replayed in-memory against the real pre-patch snapshot
content (snapshots are real git repos) and checked byte-for-byte against
an actual `git apply` of the reference patch. This caught two real parser
bugs during development — the dataset doesn't consistently mark new files
with `--- /dev/null` (some use a real-looking path with a `@@ -0,0 ...`
hunk instead), and some patches lack a trailing newline that `git apply`
rejects as "corrupt" even though the diff is valid — both fixed and
re-verified before trusting the output.

**Result**: 62/66 tasks (93.9%) produced a verified trajectory (train
44/46, dev 9/10, validation 9/10); the remaining 4 are logged as skips,
not silently dropped — 3 are genuine `edit_file` ambiguity (a hunk's
target text isn't unique in the file), 1 is a real fidelity-check failure
on a large auto-generated data file, not chased further given it's 1/66.
Training data lives in `experiments/lora_training_data/` (gitignored,
deterministically regenerable — same posture as `results/`).

**Not done yet**: actual LoRA/PEFT training needs a real GPU this Mac
doesn't have, same constraint as the official-model baseline (step 3) —
will need a Kaggle-notebook-based training run, still to be built. Full
detail in `experiments/CHANGELOG.md`.

## First official-model baseline (plan step 3, completed)

Ran the real `gemma-4-31b-it-qat-w4a16-ct` model against the smoke cohort
via a personal Kaggle notebook (`devtools/kaggle_notebooks/official_baseline_smoke.ipynb`).
Two Kaggle-platform gotchas along the way, not code issues: the free/standard
notebook GPU options (T4 x2, or whatever accelerator you land on) don't
necessarily match the competition's actual 4x L4 hardware — a T4 run failed
immediately (`bfloat16` needs compute capability ≥8.0; T4 is 7.5), and
Kaggle blocks Internet + certain accelerators together on competition-attached
notebooks (our notebook doesn't need internet — the wheelhouse is a
pre-attached dataset — so disabling it is both safe and actually the
harness's expected offline mode).

**Real finding**: 3 of 4 tasks crashed with `litellm.ContextWindowExceededError`
— `submission/configs/sampling.yaml`'s `max_output_tokens: 16384` reserves
half the 32768-token context window on every turn, and real multi-turn
conversations against the actual model (not the small `gemma4:e4b` stand-in,
which never surfaced this in any prior run) grew past the remaining input
budget by turn 8-10. Fixed: `max_output_tokens` 16384 → 8192.

**Re-validated same day**: re-ran the identical notebook top-to-bottom with
the fix. Zero `ContextWindowExceededError` crashes on any of the 4 tasks.
3 tasks cleanly exhausted their 15-turn budget instead (no crash); the 4th
(`httpx_3672`) completed fully cleanly — submitted within budget with
`error=None`, the project's first-ever clean agent-loop completion on the
real official model. Still `resolution_rate=0/4` (expected for a 4-task
smoke sample), but the orchestration/config layer now demonstrably works
end-to-end against the real model.

**Scaled up to the `comparison` cohort (19 tasks) same day, via a separate
notebook** (`devtools/generate_official_comparison_notebook.py`) —
**`resolution_rate=2/19 (10.5%)`, the first task resolutions anywhere in
this project**, proxy-model or official-model, both verified non-trivial
(real patches, `test_exit_code=0`, not in the known zero-diff-resolves
list). 16 of the remaining 17 tasks cleanly exhausted the 15-turn budget
at *exactly* 14 tool calls each — suggesting the turn budget, not the
tool-call budget, is the binding constraint right now. The
`max_output_tokens=8192` fix reduced the context-window crash rate a lot
(75% → 5.3% of tasks) but didn't eliminate it — one task still hit it on
an unusually long trajectory.

**Tested the turn-budget hypothesis directly, same day**
(`devtools/generate_official_maxturns_notebook.py`): raised `max_turns`
15 → 25 on the smoke cohort (with `max_tool_calls`/`max_time_minutes`
also raised, so neither became a new hidden constraint). Result: mixed,
not a clean win. `resolution_rate` stayed `0/4`, but 2 of the 4 tasks
(`requests_7505`, `rich_4070`) used the *entire* new budget and produced
real, substantial patches that actually got tested (just didn't pass) —
real evidence turns was constraining them. The other 2
(`fastapi_15661`, and `httpx_3672` — this project's only prior clean
completion) instead hit `ContextWindowExceededError`, trading a
turn-exhaustion failure for a context-window failure. Raising `max_turns`
alone, without also addressing `max_output_tokens`, just shifts *where*
some tasks fail rather than unambiguously helping. Full detail, including
the exact error and per-task breakdown for all four official-model runs,
in `experiments/CHANGELOG.md`.

This is exactly why the scope caveat above the step 6 section exists — every
proxy-model finding to date was validated only on a model that never grew
its context enough to hit a real constraint that the actual competition
model hits almost immediately.

## LoRA training: QLoRA notebook build + first-run debugging (plan step 9, part 2)

Built the actual GPU training step (`devtools/generate_lora_training_notebook.py`)
on top of step 9 part 1's already-verified data pipeline — QLoRA (4-bit
NF4 via `bitsandbytes`+`transformers`+`peft`) on the 44 reference-patch
trajectories, base model `gemma-4-31b-it-qat-q4_0-unquantized`
(`transformers` framework — chosen because it's the QAT-trained checkpoint
before W4A16 packing, matching the competition's actual serving checkpoint;
a plain `-it` or any `-assistant`-suffixed variant would introduce a
base-weight mismatch). Rank 16, all 7 attention/MLP projections. The
notebook skips attaching the competition dataset entirely so Internet can
stay on for `pip install peft accelerate` — confirmed the wheelhouse has
zero training libraries at all, only eval/serving ones.

Caught two real bugs before ever touching Kaggle GPU time: a latent
backslash-escaping bug in the `py_literal()` helper shared by every
notebook generator (JSON-escaped unicode in the training data was getting
reinterpreted by Python's own string parser, producing an invalid
surrogate that would have crashed `write_text()`), and a hardcoded
`torch.bfloat16` that would have failed on T4 exactly like the eval
notebooks did before their fix. A third bug only showed up on the actual
first run: `peft` doesn't recognize Gemma4's custom
`Gemma4ClippableLinear` wrapper around its linear layers, so
`get_peft_model()` failed immediately. Fixed by unwrapping the targeted
layers back to their inner `Linear4bit` before LoRA injection — a
training-time-only change, since the deployed adapter never goes through
this module structure at inference. **Not yet confirmed working** — this
fix is based on the error message alone (no local GPU to verify against)
and awaiting a re-run. Full detail in `experiments/CHANGELOG.md`.
