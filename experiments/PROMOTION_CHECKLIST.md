# Promotion Checklist

Per plan step 4: **a discipline to follow by hand, not infrastructure to
build.** The point is to stop wasting rented-GPU budget on a candidate a
cheaper check would already have rejected, and to stop prompt iteration from
quietly overfitting to the 129 public tasks. Walk through this list before
spending rented-GPU time on a candidate, and before updating
`CHAMPION.md`.

Cohort task-ID lists live in `experiments/cohorts.json`
(`devtools/define_cohorts.py` generated them once, reproducibly — do not
regenerate casually, membership needs to stay stable for comparisons to stay
valid). Check `known_anomalous_task_caveats_by_cohort` in that file before
interpreting any result — a few tasks are known to resolve with zero code
changes or hit sandbox resource limits independent of agent quality.

## Checklist (in order — stop at the first failure)

1. **Config validates.** `submission/` compiles; no YAML/schema errors.
2. **Passes the Mac smoke set** (`cohorts.json` → `smoke`, 4 tasks).
   `--fidelity structural` (or `proxy-model` if no structural-only path
   makes sense for the change being tested) via
   `devtools/mlflow/run_evaluation.py`.
3. **Passes the proxy-model set** (same smoke cohort, real Container-A loop,
   `--fidelity proxy-model`, `--backend stand-in-e4b` via
   `devtools/models-ollama-e4b.yaml`). Note: as of the 2026-09-29 proxy-model
   baseline, `gemma4:e4b` needs a larger budget than the 5 min/15 tool
   calls used in early sanity tests to reliably complete a task — see
   `experiments/CHANGELOG.md`. Budget accordingly or treat orchestration
   failures here as inconclusive rather than a real regression signal until
   that's better understood.
4. **Beats or matches the champion on the `prompt_dev`/`comparison` cohorts,
   on the official model.** Paired comparison: same cohort, same backend,
   same budgets/sampling/seed as the champion's last validated run. Note
   run-to-run variance if generation is nondeterministic — don't promote on
   noise (re-run if the margin is within noise range).
5. **Beats or matches the champion on the `held_out` cohort.** This is the
   check that catches "improved on my dev set" vs. "actually improved" — do
   not skip it, and do not inspect `held_out` task contents/traces during
   steps 1-4 above (that's what would silently defeat the point of holding
   it out).
6. **Only then**, run the full 129-task suite (`cohorts.json` →
   `full_129_note`, i.e. no `--task-ids` filter) as a milestone checkpoint.

## After promotion

Update `experiments/CHAMPION.md` with the new champion's label, config hash,
results dir, MLflow link, and what it beat. Log the promotion decision itself
as a `experiments/CHANGELOG.md` entry (hypothesis = what you expected to
improve; result = the paired-comparison numbers that justified the
promotion).
