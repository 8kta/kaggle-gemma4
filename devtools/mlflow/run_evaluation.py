#!/usr/bin/env python3
"""Host-side evaluation wrapper (dev tooling only — never imported by submission/).

Implements the practice from agent-ideas/claude-idea.md step 2:
  1. Snapshot the exact submission config used, under experiments/<label>/.
  2. Run `swegemma eval` as a subprocess against a unique results dir
     (results/<label>/) — this always happens and is always the source of
     truth, independent of anything below.
  3. Best-effort log the run to MLflow (never blocks/fails the run — see
     mlflow_logging.log_eval_run).
  4. Append a templated entry to experiments/CHANGELOG.md.

Example:
    python3 devtools/mlflow/run_evaluation.py \\
      --label 2026-09-29_smoke \\
      --submission-dir downloads/kagglehub/competitions/gemma-4-developer-agent/sample_submission \\
      --task-ids fastapi_15661 requests_7505 rich_4070 httpx_3672 \\
      --skip-agent-patch \\
      --backend stand-in-e4b --env local-mac --fidelity structural \\
      --hypothesis "Validate the logging wrapper end-to-end on a cheap smoke cohort."
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mlflow_logging  # noqa: E402

DEFAULT_TASKS = REPO_DIR / "downloads/kagglehub/competitions/gemma-4-developer-agent/tasks.jsonl"
DEFAULT_SNAPSHOTS = REPO_DIR / "downloads/kagglehub/competitions/gemma-4-developer-agent/snapshots"
DEFAULT_SUBMISSION = REPO_DIR / "submission"
CHANGELOG_PATH = REPO_DIR / "experiments" / "CHANGELOG.md"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", required=True, help="Run label, e.g. 2026-09-29_analyzer-subagent")
    p.add_argument("--tasks", default=str(DEFAULT_TASKS))
    p.add_argument("--snapshots-dir", default=str(DEFAULT_SNAPSHOTS))
    p.add_argument("--submission-dir", default=str(DEFAULT_SUBMISSION))
    p.add_argument("--task-id", dest="task_ids", action="append", default=None)
    p.add_argument("--task-ids", dest="task_ids", nargs="+", default=None)
    p.add_argument("--sandbox", choices=["docker", "subprocess"], default="docker")
    p.add_argument("--skip-agent-patch", action="store_true")
    p.add_argument("--max-tool-calls", type=int, default=None)
    p.add_argument("--max-turns", type=int, default=None)
    p.add_argument("--max-time-minutes", type=float, default=None)
    p.add_argument("--concurrency", type=int, default=None)
    p.add_argument("--display", default="quiet")

    p.add_argument("--backend", required=True, help="e.g. stand-in-e4b, gemma-4-31b-qat")
    p.add_argument("--env", required=True, choices=["local-mac", "rented-gpu", "kaggle-notebook"])
    p.add_argument("--fidelity", required=True, choices=sorted(mlflow_logging.VALID_FIDELITIES))
    p.add_argument("--hypothesis", default=None, help="What you expect this run to show")
    p.add_argument("--cohort", default="unspecified",
                    help="smoke / prompt-dev / comparison / held-out / full-129")
    p.add_argument("--no-mlflow", action="store_true", help="Skip MLflow logging entirely")
    return p.parse_args()


# Large binary weight files get hard-linked instead of copied so repeated
# snapshots don't each duplicate hundreds of MB-to-GB of LoRA adapter weights
# on disk. Hard links only work within the same filesystem/device, which
# holds here since experiments/ and submission/ are both inside this repo.
LARGE_BINARY_SUFFIXES = {".safetensors"}


def snapshot_submission(submission_dir: Path, dest: Path) -> dict[str, str]:
    """Snapshot submission_dir into dest. Returns {relpath: method} for any
    file handled specially (hardlink, or copy-fallback with a reason)."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    manifest: dict[str, str] = {}
    for src in sorted(submission_dir.rglob("*")):
        rel = src.relative_to(submission_dir)
        target = dest / rel
        if src.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        is_large_binary = src.suffix.lower() in LARGE_BINARY_SUFFIXES or "adapters" in rel.parts
        if is_large_binary:
            try:
                os.link(src, target)
                digest = hashlib.sha256(src.read_bytes()).hexdigest()
                manifest[str(rel)] = f"hardlink sha256:{digest}"
                continue
            except OSError as e:
                print(f"[run_evaluation] NOTE: hard link failed for {rel} ({e}); "
                      f"falling back to a real copy (uses full disk space).", file=sys.stderr)
        shutil.copy2(src, target)
        if is_large_binary:
            digest = hashlib.sha256(src.read_bytes()).hexdigest()
            manifest[str(rel)] = f"copy sha256:{digest}"

    if manifest:
        (dest / "ADAPTERS_MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def check_git_dirty(repo_dir: Path) -> bool:
    gi = mlflow_logging.git_info(repo_dir)
    if gi["git_dirty"]:
        print(
            f"[run_evaluation] NOTE: {repo_dir} has uncommitted changes. "
            "This run's config_hash still pins the exact bytes used, but the "
            "git_commit tag won't point at a commit containing them — commit "
            "submission/ before running if you want a clean commit-to-run mapping.",
            file=sys.stderr,
        )
    return gi["git_dirty"]


def run_swegemma_eval(args: argparse.Namespace, results_dir: Path) -> int:
    cmd = [
        "swegemma", "eval",
        "--tasks", args.tasks,
        "--snapshots-dir", args.snapshots_dir,
        "--results-dir", str(results_dir),
        "--submission-dir", args.submission_dir,
        "--sandbox", args.sandbox,
        "--display", args.display,
    ]
    if args.task_ids:
        cmd += ["--task-ids", *args.task_ids]
    if args.skip_agent_patch:
        cmd.append("--skip-agent-patch")
    if args.max_tool_calls is not None:
        cmd += ["--max-tool-calls", str(args.max_tool_calls)]
    if args.max_turns is not None:
        cmd += ["--max-turns", str(args.max_turns)]
    if args.max_time_minutes is not None:
        cmd += ["--max-time-minutes", str(args.max_time_minutes)]
    if args.concurrency is not None:
        cmd += ["--concurrency", str(args.concurrency)]

    print(f"[run_evaluation] {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.run(cmd)
    return proc.returncode


def append_changelog(
    *, label: str, hypothesis: str | None, cohort: str, args: argparse.Namespace,
    results_dir: Path, mlflow_url: str | None, git_commit: str, git_dirty: bool,
) -> None:
    try:
        summary = mlflow_logging._load_results(results_dir)[0]
    except Exception:
        summary = {}
    rate_key = "resolution_rate" if args.fidelity == "official-model" else "proxy_resolution_rate"
    rate = summary.get("resolution_rate")
    resolved = summary.get("resolved")
    total = summary.get("total_tasks")

    change_desc = (
        f"`swegemma eval --sandbox {args.sandbox}"
        f"{' --skip-agent-patch' if args.skip_agent_patch else ''}` "
        f"against {'task(s) ' + ', '.join(args.task_ids) if args.task_ids else 'the full task set'}, "
        f"backend={args.backend}, env={args.env}, fidelity={args.fidelity}."
    )

    entry = f"""
## {datetime.now(timezone.utc).strftime('%Y-%m-%d')} — {label}
- Hypothesis: {hypothesis or '(none provided — fill in manually)'}
- Change: {change_desc}
- Cohort: {cohort}
- Result: {rate_key}={rate}, resolved={resolved}/{total}
- Results dir: `{results_dir.relative_to(REPO_DIR)}/`
- Commit: `{git_commit}`{' (dirty worktree at run time)' if git_dirty else ''}
- MLflow: {mlflow_url or '(not logged — see stderr for reason)'}
"""
    with open(CHANGELOG_PATH, "a") as f:
        f.write(entry)
    print(f"[run_evaluation] Appended CHANGELOG entry for '{label}'", file=sys.stderr)


def main() -> int:
    args = parse_args()
    results_dir = REPO_DIR / "results" / args.label
    experiment_dir = REPO_DIR / "experiments" / args.label
    submission_dir = Path(args.submission_dir).resolve()

    experiment_dir.mkdir(parents=True, exist_ok=True)
    snapshot_submission(submission_dir, experiment_dir / "submission_snapshot")
    print(f"[run_evaluation] Snapshotted {submission_dir} -> {experiment_dir / 'submission_snapshot'}", file=sys.stderr)

    git_dirty = check_git_dirty(REPO_DIR)

    exit_code = run_swegemma_eval(args, results_dir)
    if exit_code != 0 and not (results_dir / "summary.json").exists():
        print(f"[run_evaluation] swegemma eval failed (exit {exit_code}) with no results produced.", file=sys.stderr)
        return exit_code

    mlflow_url = None
    if not args.no_mlflow:
        mlflow_url = mlflow_logging.log_eval_run(
            results_dir=results_dir,
            label=args.label,
            backend=args.backend,
            env=args.env,
            fidelity=args.fidelity,
            submission_dir=submission_dir,
            repo_dir=REPO_DIR,
            hypothesis=args.hypothesis,
            config_snapshot_dir=experiment_dir / "submission_snapshot",
        )
        print(f"[run_evaluation] MLflow: {mlflow_url or 'logging skipped/failed (see warnings above)'}", file=sys.stderr)

    git_commit = mlflow_logging.git_info(REPO_DIR)["git_commit"]
    append_changelog(
        label=args.label, hypothesis=args.hypothesis, cohort=args.cohort, args=args,
        results_dir=results_dir, mlflow_url=mlflow_url, git_commit=git_commit, git_dirty=git_dirty,
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
