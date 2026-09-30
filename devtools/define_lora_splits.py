#!/usr/bin/env python3
"""One-shot, reproducible LoRA train/dev/validation split (plan step 9).

Per agent-ideas/claude-idea.md step 9: "split task IDs into train/dev/
validation sets first, and keep the held-out slice from step 4 out of the
training set entirely." This script draws exclusively from `cohorts.json`'s
`unassigned_pool` (66 tasks) — the one cohort that plan step 4 didn't
reserve for any evaluation purpose. `held_out` is explicitly forbidden by
the plan; `comparison` and `prompt_dev` are also excluded here even though
the plan doesn't name them, because training on a cohort used to judge
candidates (comparison) or already used to shape the prompt by hand
(prompt_dev) would contaminate the very evaluations meant to validate this
adapter. `smoke` is excluded for the same reason — its 4 tasks have been
directly inspected/tuned against since step 1 and are still used as the
cheapest promotion-checklist gate.

Run once, before generating any trajectories (per the plan's explicit
"do this before generating any trajectories, not after"). Re-running should
be rare and deliberate — split membership must stay stable, or a trajectory
generated against one split assignment could silently end up counted under
a different one later.

Usage:
    python3 devtools/define_lora_splits.py
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
COHORTS_PATH = REPO_DIR / "experiments" / "cohorts.json"
TASKS_PATH = REPO_DIR / "downloads/kagglehub/competitions/gemma-4-developer-agent/tasks.jsonl"
OUT_PATH = REPO_DIR / "experiments" / "lora_splits.json"

SEED = 20260930  # fixed — reruns must be deliberate, not accidental reshuffles

# Target sizes within the 66-task unassigned_pool, before repo-proportional
# stratification. Train gets the bulk; dev/validation just need to be large
# enough to catch overfitting/regressions in the training loop itself, not
# to serve as a full evaluation cohort (that's what prompt_dev/comparison/
# held_out are for, and none of this touches those).
DEV_TARGET = 10
VALIDATION_TARGET = 10
# Remainder goes to train.


def stratified_take(pool_by_repo: dict[str, list[str]], target_total: int, rng: random.Random) -> list[str]:
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

    cohorts = json.loads(COHORTS_PATH.read_text())
    unassigned = cohorts["unassigned_pool"]["ids"]

    task_repo: dict[str, str] = {}
    with open(TASKS_PATH) as f:
        for line in f:
            t = json.loads(line)
            task_repo[t["instance_id"]] = t["repo"]

    forbidden: set[str] = set()
    forbidden_by_cohort: dict[str, set[str]] = {}
    for name in ("held_out", "comparison", "prompt_dev", "smoke"):
        ids = set(cohorts[name]["ids"])
        forbidden_by_cohort[name] = ids
        forbidden |= ids

    overlap = set(unassigned) & forbidden
    assert not overlap, f"unassigned_pool overlaps a reserved cohort: {overlap}"

    pool: dict[str, list[str]] = defaultdict(list)
    for tid in unassigned:
        pool[task_repo[tid]].append(tid)

    dev = stratified_take(pool, DEV_TARGET, rng)
    validation = stratified_take(pool, VALIDATION_TARGET, rng)
    train = sorted(i for ids in pool.values() for i in ids)

    splits = {"train": sorted(train), "dev": sorted(dev), "validation": sorted(validation)}

    # Leakage checks: splits are pairwise disjoint, their union is exactly
    # unassigned_pool, and none of them touch a reserved cohort. This is the
    # explicit "verify no ... validation-cohort trajectory leaks into the
    # training data" step the plan calls for, run now rather than trusted.
    all_split_ids = splits["train"] + splits["dev"] + splits["validation"]
    assert len(all_split_ids) == len(set(all_split_ids)), "a task_id appears in more than one split"
    assert set(all_split_ids) == set(unassigned), "splits don't exactly partition unassigned_pool"
    for name, ids in splits.items():
        for forbidden_name, forbidden_ids in forbidden_by_cohort.items():
            bad = set(ids) & forbidden_ids
            assert not bad, f"split '{name}' leaks into reserved cohort '{forbidden_name}': {bad}"

    def repo_counts(ids: list[str]) -> dict[str, int]:
        c: dict[str, int] = defaultdict(int)
        for i in ids:
            c[task_repo[i]] += 1
        return dict(c)

    out = {
        "seed": SEED,
        "source_cohort": "unassigned_pool",
        "excluded_cohorts": sorted(forbidden_by_cohort.keys()),
        "train": {"ids": splits["train"], "by_repo": repo_counts(splits["train"])},
        "dev": {"ids": splits["dev"], "by_repo": repo_counts(splits["dev"])},
        "validation": {"ids": splits["validation"], "by_repo": repo_counts(splits["validation"])},
    }
    OUT_PATH.write_text(json.dumps(out, indent=2, sort_keys=False) + "\n")
    print(f"Wrote {OUT_PATH}")
    for name in ("train", "dev", "validation"):
        print(f"  {name}: {len(out[name]['ids'])} tasks, by_repo={out[name]['by_repo']}")
    print("Leakage checks passed: splits are pairwise disjoint, partition unassigned_pool exactly, "
          "and none overlap held_out/comparison/prompt_dev/smoke.")


if __name__ == "__main__":
    main()
