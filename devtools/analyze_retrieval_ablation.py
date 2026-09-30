#!/usr/bin/env python3
"""Analyzes the step 8 retrieval ablation's 12 runs (see
devtools/run_retrieval_ablation.py) and prints per-variant navigation
metrics: tool calls before first file open, redundant-read rate, time to
first file open, time to first edit (total navigation time), plus
graph-tool usage counts and resolution_rate — per plan step 8's ask to
track these "alongside resolution rate", since the gemma4:e4b stand-in has
not resolved any smoke-cohort task to date (see experiments/CHANGELOG.md)
and resolution_rate alone would show no signal between arms.

A trace's `steps` list (schema_version ATIF-v1.7) has one entry per model
turn; "agent" steps carry `tool_calls` (list of {function_name, arguments})
and `extra.elapsed_s` (wall-clock seconds since task start). This script
walks that list per task to compute the metrics below — it does not
touch/modify any run, purely reads results/ already on disk.

Usage:
    python3 devtools/analyze_retrieval_ablation.py
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_DIR / "results"

SMOKE_TASK_IDS = ["fastapi_15661", "requests_7505", "rich_4070", "httpx_3672"]
VARIANTS = ["hybrid", "filesystem-only", "graph-first"]
GRAPH_TOOLS = {"get_code_neighbors", "search_similar_code", "get_code_subgraph"}
FILE_OPEN_TOOLS = {"read_file"}
FIX_TOOLS = {"edit_file", "write_file"}


def load_trace(variant: str, task_id: str) -> dict | None:
    label = f"2026-09-29_step8-retrieval-{variant}-{task_id}"
    trace_path = RESULTS_DIR / label / "traces" / f"trace_{task_id}.json"
    if not trace_path.exists():
        return None
    return json.loads(trace_path.read_text())


def load_task_result(variant: str, task_id: str) -> dict | None:
    label = f"2026-09-29_step8-retrieval-{variant}-{task_id}"
    tr_path = RESULTS_DIR / label / "task_results.jsonl"
    if not tr_path.exists():
        return None
    for line in tr_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        if d.get("instance_id") == task_id:
            return d
    return None


def tool_call_stream(trace: dict) -> list[dict]:
    """Flatten every tool call across all agent steps into one ordered list,
    each annotated with the elapsed_s of the step it belongs to."""
    calls = []
    for step in trace.get("steps", []):
        if step.get("source") != "agent":
            continue
        elapsed = (step.get("extra") or {}).get("elapsed_s")
        for tc in step.get("tool_calls") or []:
            calls.append({
                "function_name": tc.get("function_name"),
                "arguments": tc.get("arguments"),
                "elapsed_s": elapsed,
            })
    return calls


def compute_metrics(trace: dict) -> dict:
    calls = tool_call_stream(trace)

    first_file_open_idx = next(
        (i for i, c in enumerate(calls) if c["function_name"] in FILE_OPEN_TOOLS), None
    )
    first_fix_idx = next(
        (i for i, c in enumerate(calls) if c["function_name"] in FIX_TOOLS), None
    )

    seen_read_args: set[str] = set()
    redundant_reads = 0
    total_reads = 0
    for c in calls:
        if c["function_name"] in FILE_OPEN_TOOLS:
            total_reads += 1
            key = json.dumps(c["arguments"], sort_keys=True)
            if key in seen_read_args:
                redundant_reads += 1
            else:
                seen_read_args.add(key)

    graph_tool_calls = sum(1 for c in calls if c["function_name"] in GRAPH_TOOLS)

    return {
        "total_tool_calls": len(calls),
        "tool_calls_before_first_file_open": first_file_open_idx,
        "time_to_first_file_open_s": calls[first_file_open_idx]["elapsed_s"] if first_file_open_idx is not None else None,
        "time_to_first_fix_s": calls[first_fix_idx]["elapsed_s"] if first_fix_idx is not None else None,
        "total_reads": total_reads,
        "redundant_reads": redundant_reads,
        "redundant_read_rate": (redundant_reads / total_reads) if total_reads else None,
        "graph_tool_calls": graph_tool_calls,
    }


def fmt(v, nd=2):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def main() -> None:
    per_variant: dict[str, list[dict]] = {v: [] for v in VARIANTS}

    print(f"{'variant':16} {'task_id':16} {'resolved':9} {'error':22} {'calls':6} {'calls_b4_open':14} "
          f"{'t_open_s':9} {'t_fix_s':8} {'reads':6} {'redund':7} {'redund%':8} {'graph_calls':11}")
    for variant in VARIANTS:
        for task_id in SMOKE_TASK_IDS:
            trace = load_trace(variant, task_id)
            task_result = load_task_result(variant, task_id)
            if trace is None or task_result is None:
                print(f"{variant:16} {task_id:16} MISSING (run not found under results/)")
                continue
            m = compute_metrics(trace)
            m["resolved"] = task_result.get("resolved")
            m["error"] = task_result.get("error")
            m["duration_seconds"] = task_result.get("duration_seconds")
            per_variant[variant].append(m)

            redund_pct = (m["redundant_read_rate"] * 100) if m["redundant_read_rate"] is not None else None
            print(f"{variant:16} {task_id:16} {fmt(m['resolved']):9} {fmt(m['error'])[:22]:22} "
                  f"{fmt(m['total_tool_calls']):6} {fmt(m['tool_calls_before_first_file_open']):14} "
                  f"{fmt(m['time_to_first_file_open_s']):9} {fmt(m['time_to_first_fix_s']):8} "
                  f"{fmt(m['total_reads']):6} {fmt(m['redundant_reads']):7} {fmt(redund_pct):8} "
                  f"{fmt(m['graph_tool_calls']):11}")

    print("\n--- Per-variant aggregates (mean over available tasks) ---")
    print(f"{'variant':16} {'n':3} {'resolved_rate':13} {'mean_calls':10} {'mean_calls_b4_open':18} "
          f"{'mean_t_open_s':13} {'mean_t_fix_s':12} {'mean_redund%':12} {'mean_graph_calls':16}")
    for variant in VARIANTS:
        rows = per_variant[variant]
        n = len(rows)
        if n == 0:
            print(f"{variant:16} 0   (no completed runs)")
            continue

        def mean_of(key, rows=rows):
            vals = [r[key] for r in rows if r.get(key) is not None]
            return statistics.mean(vals) if vals else None

        resolved_rate = mean_of("resolved") if any(r.get("resolved") is not None for r in rows) else None
        redund_rate_mean = mean_of("redundant_read_rate")
        redund_pct_mean = redund_rate_mean * 100 if redund_rate_mean is not None else None

        print(f"{variant:16} {n:3} {fmt(resolved_rate):13} {fmt(mean_of('total_tool_calls')):10} "
              f"{fmt(mean_of('tool_calls_before_first_file_open')):18} "
              f"{fmt(mean_of('time_to_first_file_open_s')):13} {fmt(mean_of('time_to_first_fix_s')):12} "
              f"{fmt(redund_pct_mean):12} {fmt(mean_of('graph_tool_calls')):16}")


if __name__ == "__main__":
    main()
