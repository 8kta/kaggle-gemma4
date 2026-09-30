#!/usr/bin/env python3
"""One-shot, reproducible cohort definition (plan step 4).

Per agent-ideas/claude-idea.md step 4, cohorts are "a discipline to follow,
not infrastructure to build" — this script exists only so the *static* task
lists in experiments/cohorts.json are reproducible/auditable rather than
"picked by hand with no documented rationale". Run once now, before any
prompt tuning starts (per the plan's explicit instruction to set the
held-out slice aside now). Re-running should be rare and deliberate — cohort
membership should stay stable across iterations so comparisons stay valid.

Stratifies by repo (proportional to each repo's share of the 129 tasks) with
a fixed seed for reproducibility. The smoke set is NOT sampled — it's fixed
to the 4 tasks already used throughout steps 1-3
(fastapi_15661, requests_7505, rich_4070, httpx_3672), for continuity with
the structural/proxy-model baselines already run against them.

Note: this makes `comparison` repo-*proportional* (matching each repo's
share of the 129), not repo-*balanced* (equal counts per repo) — the plan's
step 4 wording says "balanced" but true balance is impossible anyway given
httpx has only 1 public task total. Proportional was the deliberate choice.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
TASKS_PATH = REPO_DIR / "downloads/kagglehub/competitions/gemma-4-developer-agent/tasks.jsonl"
OUT_PATH = REPO_DIR / "experiments/cohorts.json"

SEED = 20260929  # fixed — reruns must be deliberate, not accidental reshuffles

# Already used throughout steps 1-3 (structural + proxy-model baselines) —
# kept as the smoke set for continuity rather than re-sampled.
SMOKE = ["fastapi_15661", "requests_7505", "rich_4070", "httpx_3672"]

# Target sizes (before repo-proportional stratification). httpx has only 1
# task total and it's already in SMOKE, so it won't appear elsewhere.
HELD_OUT_TARGET = 18
PROMPT_DEV_TARGET = 20
COMPARISON_TARGET = 18

# Known-anomalous tasks found during the step-3 structural baseline (see
# experiments/CHANGELOG.md's 00_baseline-structural entry): these either
# resolve with zero code changes (violates the documented Fail-to-Pass
# invariant — inflates any cohort containing them) or hit the sandbox's
# resource limits (timeout/OOM) independent of agent quality. Not excluded
# from sampling (they're real public tasks), but flagged wherever they land.
KNOWN_ANOMALOUS = {
    "requests_7427": "resolves with zero code changes (Fail-to-Pass violation)",
    "requests_7315": "resolves with zero code changes (Fail-to-Pass violation)",
    "requests_7309": "resolves with zero code changes (Fail-to-Pass violation)",
    "rich_3468": "resolves with zero code changes (Fail-to-Pass violation)",
    "rich_4006": "hit the 300s command timeout in the structural baseline",
    "rich_3772": "OOM-killed (exit 137) in the structural baseline",
    "rich_3480": "OOM-killed (exit 137) in the structural baseline",
}


def stratified_take(pool_by_repo: dict[str, list[str]], target_total: int, rng: random.Random) -> list[str]:
    """Take approximately target_total items from pool_by_repo, proportional
    to each repo's remaining share, mutating pool_by_repo in place."""
    total_remaining = sum(len(v) for v in pool_by_repo.values())
    if total_remaining == 0 or target_total <= 0:
        return []
    taken: list[str] = []
    for repo, items in pool_by_repo.items():
        share = round(target_total * len(items) / total_remaining)
        share = min(share, len(items))
        rng.shuffle(items)
        taken.extend(items[:share])
        del items[:share]
    return taken


def main() -> None:
    rng = random.Random(SEED)

    by_repo: dict[str, list[str]] = defaultdict(list)
    task_repo: dict[str, str] = {}
    with open(TASKS_PATH) as f:
        for line in f:
            t = json.loads(line)
            by_repo[t["repo"]].append(t["instance_id"])
            task_repo[t["instance_id"]] = t["repo"]

    all_ids = set(task_repo)
    assert all_ids.issuperset(SMOKE), "SMOKE contains an instance_id not in tasks.jsonl"

    # Remove SMOKE from the sampling pool.
    pool: dict[str, list[str]] = defaultdict(list)
    for repo, ids in by_repo.items():
        pool[repo] = [i for i in ids if i not in SMOKE]

    held_out = stratified_take(pool, HELD_OUT_TARGET, rng)
    prompt_dev = stratified_take(pool, PROMPT_DEV_TARGET, rng)
    comparison = stratified_take(pool, COMPARISON_TARGET, rng)
    remaining_unassigned = sorted(i for ids in pool.values() for i in ids)

    def repo_counts(ids: list[str]) -> dict[str, int]:
        c: dict[str, int] = defaultdict(int)
        for i in ids:
            c[task_repo[i]] += 1
        return dict(c)

    cohort_ids = {
        "smoke": sorted(SMOKE),
        "held_out": sorted(held_out),
        "prompt_dev": sorted(prompt_dev),
        "comparison": sorted(comparison),
        "unassigned_pool": remaining_unassigned,
    }
    caveats = {
        name: {tid: KNOWN_ANOMALOUS[tid] for tid in ids if tid in KNOWN_ANOMALOUS}
        for name, ids in cohort_ids.items()
    }
    caveats = {k: v for k, v in caveats.items() if v}

    cohorts = {
        "seed": SEED,
        "smoke": {"ids": cohort_ids["smoke"], "by_repo": repo_counts(cohort_ids["smoke"])},
        "held_out": {"ids": cohort_ids["held_out"], "by_repo": repo_counts(cohort_ids["held_out"])},
        "prompt_dev": {"ids": cohort_ids["prompt_dev"], "by_repo": repo_counts(cohort_ids["prompt_dev"])},
        "comparison": {"ids": cohort_ids["comparison"], "by_repo": repo_counts(cohort_ids["comparison"])},
        "unassigned_pool": {"ids": cohort_ids["unassigned_pool"], "by_repo": repo_counts(cohort_ids["unassigned_pool"])},
        "known_anomalous_task_caveats_by_cohort": caveats,
        "full_129_note": "Use the complete tasks.jsonl (no --task-ids filter) for milestone checkpoints only.",
    }

    OUT_PATH.write_text(json.dumps(cohorts, indent=2, sort_keys=False) + "\n")
    print(f"Wrote {OUT_PATH}")
    for name in ("smoke", "held_out", "prompt_dev", "comparison", "unassigned_pool"):
        c = cohorts[name]
        print(f"  {name}: {len(c['ids'])} tasks, by_repo={c['by_repo']}")
    if caveats:
        print("  Caveats:")
        for name, tasks in caveats.items():
            for tid, reason in tasks.items():
                print(f"    {name}/{tid}: {reason}")


if __name__ == "__main__":
    main()
