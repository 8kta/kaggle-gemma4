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


def patch_max_output_tokens(submission: Path, value: int) -> None:
    cfg = submission / "configs" / "sampling.yaml"
    text = cfg.read_text()
    assert text.count("max_output_tokens: 8192") == 1
    cfg.write_text(text.replace("max_output_tokens: 8192", f"max_output_tokens: {value}"))


def patch_turn_efficiency(submission: Path) -> None:
    """v2: bounded-output batched search (cap 2 patterns + head -n 30), read only the
    edited range after a Fix instead of re-reading the whole file, use read_file line
    ranges instead of whole-file/cat reads, stop immediately after a passing test, and
    read the traceback before retrying a failing one.

    v1 (2026-10-07 stress test) regressed: an uncapped `grep -e A -e B -e C` returned
    6,601 chars in one call (rich_3953) and repeated whole-file read_file calls after
    each edit (fastapi_14186, 5 full reads of one file) pushed both tasks over the
    32768-token context ceiling in fewer turns than the unmodified prompt, with zero
    resolution gain. See experiments/CHANGELOG.md 2026-10-07 entries for the trace
    evidence. v2 bounds the two things that caused that: batched-call output size, and
    post-edit whole-file re-reads."""
    sysmd = submission / "prompts" / "system.md"
    text = sysmd.read_text()

    old_fix = "4. **Fix**: apply the minimal necessary change with `edit_file` or `write_file`."
    new_fix = (
        "4. **Fix**: apply the minimal necessary change with `edit_file` or `write_file`. "
        "If you need to confirm the result, read only the lines you changed with "
        "`read_file(filepath, start_line, end_line)` — do not re-read the whole file; "
        "`edit_file`'s own response already shows you the change took effect."
    )
    assert text.count(old_fix) == 1
    text = text.replace(old_fix, new_fix)

    old_verify = (
        "5. **Verify**: run ONLY the specific targeted test(s) for what you changed.\n"
        "6. **Submit**: call `submit_patch` immediately once verified, then stop."
    )
    new_verify = (
        "5. **Verify**: run ONLY the specific targeted test(s) for what you changed.\n"
        "   - If it **passes**: go straight to step 6 as your very next action. Do not run "
        "further searches, read other files, or check other call sites first — you no "
        "longer have turn budget to spare, and a passing targeted test is sufficient to submit.\n"
        "   - If it **fails**: read the exact traceback or assertion in the test output "
        "before touching any code. Identify the specific line and reason it failed, then "
        "make one targeted fix addressing that exact cause — do not guess at an unrelated change.\n"
        "6. **Submit**: call `submit_patch` immediately once verified, then stop."
    )
    assert text.count(old_verify) == 1
    text = text.replace(old_verify, new_verify)

    old_locate = (
        "- Read only the specific target files and lines using `read_file`. Do not wander across unrelated files.\n"
        "- If the problem statement gives you a symbol or error message but not a file path, "
        "search for it directly: `grep -rn 'symbol_or_keyword' --include='*.py' .` or "
        "`find . -iname '*keyword*'` via `run_command`."
    )
    new_locate = (
        "- Read only the specific target files and lines using `read_file`. Do not wander "
        "across unrelated files. `read_file(filepath, start_line, end_line)` reads just "
        "that line range — use it instead of reading a whole file or `cat`-ing it when you "
        "already know roughly where the relevant code is (e.g. from a grep match's line number).\n"
        "- If the problem statement gives you a symbol or error message but not a file path, "
        "search for it directly: `grep -rn 'symbol_or_keyword' --include='*.py' . | head -n 30` "
        "or `find . -iname '*keyword*'` via `run_command` — always pipe `grep -r` through "
        "`head -n 30` so one unexpectedly common term can't fill your context with matches. "
        "If you need to search for exactly two closely related names (e.g. a class and its "
        "one expected subclass), you may combine them in one call — "
        "`grep -rn -e 'NameA' -e 'NameB' --include='*.py' . | head -n 30` — but never combine "
        "more than two, and never combine unrelated terms: a bigger combined match list costs "
        "more context than the turn it saves. When in doubt, search one term at a time."
    )
    assert text.count(old_locate) == 1
    text = text.replace(old_locate, new_locate)
    sysmd.write_text(text)


ARMS = {
    "control": None,
    "maxtok6144": lambda sub: patch_max_output_tokens(sub, 6144),
    "turn-efficiency": patch_turn_efficiency,
}


def main(arm: str) -> None:
    patch_fn = ARMS[arm]
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
    if patch_fn is not None:
        patch_fn(submission)

    comp.COHORTS_PATH = cohort_path
    comp.SUBMISSION_DIR = submission
    comp.VERSION_TAG = f"stress-{arm}"
    nb = comp.build_notebook()
    out = REPO_DIR / "devtools" / "kaggle_notebooks" / f"official_baseline_stress_{arm}.ipynb"
    out.write_text(json.dumps(nb, indent=1))
    print(f"Wrote {out.relative_to(REPO_DIR)}")


if __name__ == "__main__":
    main(sys.argv[1])
