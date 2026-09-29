"""Shared MLflow logging for swegemma eval runs (dev-tooling only).

Implements the logging policy from agent-ideas/claude-idea.md step 2:
  - MLflow is an *additive* layer on top of the file-based experiments/ log,
    never a replacement, and never on the path of anything shipped in
    submission.zip.
  - One parent run per eval batch, one nested child run per task.
  - resolution_rate is reserved for fidelity="official-model" runs;
    everything else logs proxy_resolution_rate instead, so a proxy score can
    never be sorted/compared against a real one by accident.
  - Full trace/test-output artifacts are attached only for tasks that failed
    or errored — routine successful-task traces stay on local disk only.
  - An MLflow outage must never raise into the caller: every public function
    here catches its own exceptions, logs a warning to stderr, and returns
    None instead of propagating.

This module is imported only by devtools/mlflow/*.py (host-side dev tooling).
Nothing under submission/ may import it — see step 11's submission isolation
checks.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

DEFAULT_TRACKING_URI = "http://localhost:5001"
DEFAULT_EXPERIMENT_NAME = "gemma4-developer-agent"

# Config files/dirs hashed to make a run reproducible from its tags alone.
CONFIG_HASH_TARGETS = [
    "agent.yaml",
    "agent.yml",
    "root_agent.yaml",
    "root_agent.yml",
    "eval_config.yaml",
    "configs",
    "prompts",
    "sub_agents",
    "skills",
    "adapters",
]

VALID_FIDELITIES = {"structural", "proxy-model", "official-model"}


def _warn(msg: str) -> None:
    print(f"[mlflow_logging] WARNING: {msg}", file=sys.stderr)


def _sanitize_metric_name(name: str) -> str:
    return "".join(c if (c.isalnum() or c in "_-. :/") else "_" for c in name)


def git_info(repo_dir: Path) -> dict[str, Any]:
    """Best-effort git commit sha + dirty-worktree status for repo_dir."""
    try:
        sha = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(repo_dir), "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout
        return {"git_commit": sha, "git_dirty": bool(status.strip())}
    except Exception as e:
        _warn(f"could not determine git info: {e}")
        return {"git_commit": "unknown", "git_dirty": True}


def hash_config(submission_dir: Path) -> dict[str, str]:
    """SHA256 per config target (file or directory), plus a combined hash."""
    hashes: dict[str, str] = {}
    combined = hashlib.sha256()
    for name in sorted(CONFIG_HASH_TARGETS):
        target = submission_dir / name
        if target.is_file():
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            hashes[name] = digest
            combined.update(digest.encode())
        elif target.is_dir():
            files = sorted(p for p in target.rglob("*") if p.is_file())
            dir_hasher = hashlib.sha256()
            for f in files:
                dir_hasher.update(str(f.relative_to(target)).encode())
                dir_hasher.update(f.read_bytes())
            digest = dir_hasher.hexdigest()
            hashes[name] = digest
            combined.update(digest.encode())
    hashes["_combined"] = combined.hexdigest()
    return hashes


def _load_results(results_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary_path = results_dir / "summary.json"
    tasks_path = results_dir / "task_results.jsonl"
    if not summary_path.exists():
        raise FileNotFoundError(f"summary.json not found in {results_dir}")
    summary = json.loads(summary_path.read_text())
    tasks: list[dict[str, Any]] = []
    if tasks_path.exists():
        for line in tasks_path.read_text().splitlines():
            line = line.strip()
            if line:
                tasks.append(json.loads(line))
    return summary, tasks


def log_eval_run(
    *,
    results_dir: Path,
    label: str,
    backend: str,
    env: str,
    fidelity: str,
    submission_dir: Path,
    repo_dir: Path,
    hypothesis: str | None = None,
    config_snapshot_dir: Path | None = None,
    extra_tags: dict[str, str] | None = None,
    tracking_uri: str = DEFAULT_TRACKING_URI,
    experiment_name: str = DEFAULT_EXPERIMENT_NAME,
) -> str | None:
    """Log a completed swegemma eval run to MLflow. Never raises.

    Returns the parent run's URL on success, or None if MLflow logging was
    skipped/failed for any reason (the caller should treat that as
    non-fatal — the local results_dir is always the source of truth).
    """
    if fidelity not in VALID_FIDELITIES:
        _warn(f"fidelity={fidelity!r} not in {VALID_FIDELITIES}; logging anyway")

    try:
        import mlflow
    except ImportError:
        _warn("mlflow not installed; skipping MLflow logging (local results are still saved)")
        return None

    try:
        summary, tasks = _load_results(results_dir)
    except Exception as e:
        _warn(f"could not load results from {results_dir}: {e}")
        return None

    try:
        mlflow.set_tracking_uri(tracking_uri)
        experiment = mlflow.get_experiment_by_name(experiment_name)
        if experiment is None:
            # Explicit proxied artifact location: writes route through the
            # tracking server over HTTP (mlflow-artifacts: scheme) instead of
            # requiring the client to share the server's local filesystem
            # (the server's bare default-artifact-root is a literal local
            # path — e.g. /mlflow — which only the server process can write).
            exp_id = mlflow.create_experiment(
                experiment_name, artifact_location=f"mlflow-artifacts:/{experiment_name}"
            )
            experiment = mlflow.get_experiment(exp_id)
        mlflow.set_experiment(experiment_name)
        gi = git_info(repo_dir)
        hashes = hash_config(submission_dir)

        rate_key = "resolution_rate" if fidelity == "official-model" else "proxy_resolution_rate"

        with mlflow.start_run(run_name=label) as parent_run:
            tags = {
                "backend": backend,
                "env": env,
                "fidelity": fidelity,
                "label": label,
                "git_commit": gi["git_commit"],
                "git_dirty": str(gi["git_dirty"]),
                "config_hash": hashes["_combined"],
            }
            if hypothesis:
                tags["hypothesis"] = hypothesis[:5000]
            if extra_tags:
                tags.update(extra_tags)
            mlflow.set_tags(tags)

            mlflow.log_params({
                "submission_dir": str(submission_dir),
                **{f"config_hash.{k}": v for k, v in hashes.items() if k != "_combined"},
            })

            resolved = int(summary.get("resolved", 0))
            total = int(summary.get("total_tasks", len(tasks)))
            errors = int(summary.get("errors", 0))
            metrics = {
                rate_key: float(summary.get("resolution_rate", 0.0)),
                "resolved_count": resolved,
                "total_tasks": total,
                "error_count": errors,
                "total_duration_seconds": sum(t.get("duration_seconds", 0.0) for t in tasks),
            }
            if tasks:
                patched = sum(1 for t in tasks if t.get("agent_patch_size", 0) > 0)
                metrics["patch_generation_rate"] = patched / len(tasks)
                timeouts = sum(1 for t in tasks if "timeout" in (t.get("error") or "").lower())
                metrics["timeout_rate"] = timeouts / len(tasks)
            for repo, stats in (summary.get("by_repo") or {}).items():
                safe_repo = _sanitize_metric_name(repo.replace("/", "_"))
                metrics[f"repo_rate_{safe_repo}"] = float(stats.get("rate", 0.0))
            mlflow.log_metrics(metrics)

            def _safe_log_artifact(path: str, **kwargs: Any) -> None:
                # Artifact writes hit the artifact store (proxied over HTTP
                # for mlflow-artifacts: locations, but still a separate
                # failure mode from tags/params/metrics, e.g. network hiccups
                # or a misconfigured artifact root on an older experiment).
                # One failed artifact must never cost us the metrics/tags/
                # child runs that already succeeded.
                try:
                    mlflow.log_artifact(path, **kwargs)
                except Exception as e:
                    _warn(f"log_artifact({path}) failed: {e}")

            def _safe_log_artifacts(path: str, **kwargs: Any) -> None:
                try:
                    mlflow.log_artifacts(path, **kwargs)
                except Exception as e:
                    _warn(f"log_artifacts({path}) failed: {e}")

            if (results_dir / "summary.json").exists():
                _safe_log_artifact(str(results_dir / "summary.json"))
            if (results_dir / "task_results.jsonl").exists():
                _safe_log_artifact(str(results_dir / "task_results.jsonl"))
            if config_snapshot_dir and config_snapshot_dir.exists():
                _safe_log_artifacts(str(config_snapshot_dir), artifact_path="config_snapshot")

            for task in tasks:
                instance_id = task.get("instance_id", "unknown")
                task_resolved = bool(task.get("resolved", False))
                task_failed = task_resolved is False or task.get("error") is not None
                try:
                    with mlflow.start_run(run_name=instance_id, nested=True):
                        mlflow.set_tags({
                            "instance_id": instance_id,
                            "repo": task.get("repo", ""),
                            "resolved": str(task_resolved),
                        })
                        mlflow.log_metrics({
                            k: v for k, v in {
                                "tool_calls": task.get("tool_calls"),
                                "total_llm_calls": task.get("total_llm_calls"),
                                "duration_seconds": task.get("duration_seconds"),
                                "patch_size": task.get("agent_patch_size"),
                                "test_exit_code": task.get("test_exit_code"),
                            }.items() if isinstance(v, (int, float))
                        })
                        if task_failed:
                            trace_path = results_dir / "traces" / f"trace_{instance_id}.json"
                            test_out_path = results_dir / "test_outputs" / f"{instance_id}.log"
                            if trace_path.exists():
                                _safe_log_artifact(str(trace_path))
                            if test_out_path.exists():
                                _safe_log_artifact(str(test_out_path))
                except Exception as e:
                    _warn(f"child run for task {instance_id} failed: {e}")

            run_id = parent_run.info.run_id
            return f"{tracking_uri}/#/experiments/{experiment.experiment_id}/runs/{run_id}"
    except Exception as e:
        _warn(f"MLflow logging failed ({e}); local results in {results_dir} are unaffected")
        return None
