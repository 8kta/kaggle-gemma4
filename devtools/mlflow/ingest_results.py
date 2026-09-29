#!/usr/bin/env python3
"""Log an already-completed swegemma eval results dir into MLflow.

For runs executed elsewhere (e.g. a rented-GPU official-model run) whose
results/<label>/ directory has been copied back locally, or any local run
that was executed with --no-mlflow / MLflow was unreachable at the time.
Does not invoke swegemma eval — purely ingests existing results.

Example:
    python3 devtools/mlflow/ingest_results.py \\
      --results-dir results/2026-10-05_official_full \\
      --label 2026-10-05_official_full \\
      --submission-snapshot experiments/2026-10-05_official_full/submission_snapshot \\
      --backend gemma-4-31b-qat --env rented-gpu --fidelity official-model \\
      --hypothesis "Full 129-task run of the architecture-freeze candidate."
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mlflow_logging  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results-dir", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--submission-snapshot", required=True,
                    help="Directory with the exact submission config used for this run "
                         "(e.g. experiments/<label>/submission_snapshot from run_evaluation.py, "
                         "or a manually saved copy for a run executed elsewhere)")
    p.add_argument("--backend", required=True)
    p.add_argument("--env", required=True, choices=["local-mac", "rented-gpu", "kaggle-notebook"])
    p.add_argument("--fidelity", required=True, choices=sorted(mlflow_logging.VALID_FIDELITIES))
    p.add_argument("--hypothesis", default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    results_dir = Path(args.results_dir).resolve()
    submission_snapshot = Path(args.submission_snapshot).resolve()

    if not results_dir.exists():
        print(f"ERROR: results dir not found: {results_dir}", file=sys.stderr)
        return 1
    if not submission_snapshot.exists():
        print(f"ERROR: submission snapshot not found: {submission_snapshot}", file=sys.stderr)
        return 1

    url = mlflow_logging.log_eval_run(
        results_dir=results_dir,
        label=args.label,
        backend=args.backend,
        env=args.env,
        fidelity=args.fidelity,
        submission_dir=submission_snapshot,
        repo_dir=REPO_DIR,
        hypothesis=args.hypothesis,
        config_snapshot_dir=submission_snapshot,
    )
    if url:
        print(f"Logged to MLflow: {url}")
        return 0
    print("MLflow logging failed or was skipped — see warnings above. "
          "Local results are unaffected; you can retry this ingestion later.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
