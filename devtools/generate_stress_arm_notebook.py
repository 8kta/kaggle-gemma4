#!/usr/bin/env python3
"""Generate one arm of the max_output_tokens stress experiment.

Reuses the comparison notebook generator with a 4-task stress subset of the
comparison cohort. The control arm embeds the committed submission. The variant
arm embeds a temporary copy with max_output_tokens overridden, so the committed
submission is not changed.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_official_comparison_notebook as comp  # noqa: E402

STRESS_IDS = ["fastapi_14186", "rich_3953", "fastapi_14266", "rich_3518"]
ARMS = {"control": None, "maxtok6144": 6144}


def main(arm: str) -> None:
    override = ARMS[arm]
    tmp = Path(tempfile.mkdtemp())
    cohorts = json.loads(comp.COHORTS_PATH.read_text())
    cohorts["comparison"]["ids"] = STRESS_IDS
    cohorts["comparison"]["by_repo"] = {}
    for tid in STRESS_IDS:
        repo = tid.split("_")[0]
        cohorts["comparison"]["by_repo"].setdefault(repo, []).append(tid)
    cohort_path = tmp / "cohorts.json"
    cohort_path.write_text(json.dumps(cohorts))

    submission = tmp / "submission"
    shutil.copytree(comp.SUBMISSION_DIR, submission)
    if override is not None:
        cfg = submission / "configs" / "sampling.yaml"
        text = cfg.read_text()
        assert text.count("max_output_tokens: 8192") == 1
        cfg.write_text(text.replace("max_output_tokens: 8192", f"max_output_tokens: {override}"))

    comp.COHORTS_PATH = cohort_path
    comp.SUBMISSION_DIR = submission
    comp.VERSION_TAG = f"stress-{arm}"
    nb = comp.build_notebook()
    out = REPO_DIR / "devtools" / "kaggle_notebooks" / f"official_baseline_stress_{arm}.ipynb"
    out.write_text(json.dumps(nb, indent=1))
    print(f"Wrote {out.relative_to(REPO_DIR)}")


if __name__ == "__main__":
    main(sys.argv[1])
