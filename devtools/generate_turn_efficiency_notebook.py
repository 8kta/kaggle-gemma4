#!/usr/bin/env python3
"""Generate the 19-task turn-efficiency variant notebook.

Full comparison cohort (not the 4-task stress subset) with the turn-efficiency
prompt patch applied to a temporary submission copy — see
devtools/generate_stress_arm_notebook.py's patch_turn_efficiency for the exact
edits and the trace evidence behind them. The committed submission, and the
existing official_baseline_comparison_filesystem-only-pinned-v28.ipynb (the
19-task control), are both unchanged.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_official_comparison_notebook as comp  # noqa: E402
from generate_stress_arm_notebook import patch_turn_efficiency  # noqa: E402


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    submission = tmp / "submission"
    shutil.copytree(comp.SUBMISSION_DIR, submission)
    patch_turn_efficiency(submission)

    comp.SUBMISSION_DIR = submission
    comp.VERSION_TAG = "turn-efficiency-19task"
    nb = comp.build_notebook()
    out = REPO_DIR / "devtools" / "kaggle_notebooks" / "official_baseline_comparison_turn-efficiency-19task.ipynb"
    out.write_text(json.dumps(nb, indent=1))
    print(f"Wrote {out.relative_to(REPO_DIR)}")


if __name__ == "__main__":
    main()
