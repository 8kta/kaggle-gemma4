#!/usr/bin/env python3
"""Generate a CPU-only Kaggle notebook that diagnoses empty search_similar_code results.

Reuses the environment, install, and task-loading cells of the comparison
notebook, then calls the real swegemma graph tool for the four failing
official-run tasks, using each task's own base commit. No model is loaded.
"""
import json
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import generate_official_comparison_notebook as comparison  # noqa: E402

VERSION_TAG = "graph-lookup-debug-v1"
OUT_PATH = REPO_DIR / "devtools" / "kaggle_notebooks" / f"{VERSION_TAG}.ipynb"

FAILING_QUERIES = [
    ("fastapi_14246", "get_openapi"),
    ("fastapi_9425", "response_model"),
    ("fastapi_14266", "openapi security"),
    ("rich_3521", "Segment.split_cells"),
]

SETUP_CELL_INDICES = [1, 2, 3, 4, 5, 8, 9]


def md(*lines: str) -> dict:
    return comparison.md(*lines)


def code(*lines: str) -> dict:
    return comparison.code(*lines)


def build_notebook() -> dict:
    base = comparison.build_notebook()
    setup_cells = [base["cells"][i] for i in SETUP_CELL_INDICES[:-2]]
    setup_cells.append(code("from pathlib import Path", "AGENT_DIR = Path('/kaggle/working/submission')"))
    setup_cells += [base["cells"][i] for i in SETUP_CELL_INDICES[-2:]]

    diagnosis_cells = [
        md(
            "# Graph lookup diagnosis",
            "",
            "Question: the official comparison run got `count: 0` from `search_similar_code`",
            "for queries that return results locally. This notebook runs the real swegemma tool",
            "against the four failing tasks, with each task's own base commit, and checks",
            "how `graph_dir` resolves in the Kaggle CWD. CPU only — no model is loaded.",
        ),
        md("## A. Resolve graph and embedding directories"),
        code(
            "import os",
            "",
            "print('CWD:', os.getcwd())",
            "for rel in ['data/graphs', 'data/embeddings']:",
            "    print(f'{rel} exists relative to CWD: {Path(rel).exists()}')",
            "GRAPH_DIR = DATA_DIR / 'graphs'",
            "EMB_DIR = DATA_DIR / 'embeddings'",
            "for d, pattern in [(GRAPH_DIR, '*.json'), (EMB_DIR, '*.npz')]:",
            "    n = len(list(d.glob(pattern))) if d.is_dir() else 0",
            "    print(f'{d}: is_dir={d.is_dir()}, files={n}')",
        ),
        md("## B. Call the real graph tool on the four failing tasks (competition graph_dir)"),
        code(
            "import json",
            "import traceback",
            "from swegemma.context import SwegemmaContext",
            "from swegemma.tools.graph import search_similar_code",
            "",
            "task_rows = {}",
            "with open(TASKS_PATH) as fh:",
            "    for line in fh:",
            "        row = json.loads(line)",
            "        task_rows[row['instance_id']] = row",
            "",
            f"FAILING_QUERIES = {FAILING_QUERIES!r}",
            "report = []",
            "for tid, query in FAILING_QUERIES:",
            "    row = task_rows[tid]",
            "    ctx = SwegemmaContext(task=row, repo=row['repo'], graph_dir=str(GRAPH_DIR), embeddings_dir=str(EMB_DIR))",
            "    try:",
            "        out = search_similar_code(ctx, query, k=3)",
            "    except Exception as exc:",
            "        out = f'EXCEPTION {type(exc).__name__}: {exc}'",
            "        traceback.print_exc()",
            "    print(f'{tid} | {query!r} | base={row[\"base_commit\"][:10]}')",
            "    print('   ', out[:400])",
            "    report.append({'task_id': tid, 'query': query, 'output': out})",
        ),
        md("## C. Failure-mode check: default relative `data/graphs` (what auto-detection skips)"),
        code(
            "print('Relative path data/graphs exists:', Path('data/graphs').exists())",
            "for tid, query in FAILING_QUERIES[:2]:",
            "    row = task_rows[tid]",
            "    ctx = SwegemmaContext(task=row, repo=row['repo'], graph_dir='data/graphs', embeddings_dir='data/embeddings')",
            "    try:",
            "        out = search_similar_code(ctx, query, k=3)",
            "    except Exception as exc:",
            "        out = f'EXCEPTION {type(exc).__name__}: {exc}'",
            "    print(f'{tid} | {query!r} | relative graph_dir ->', out[:300])",
        ),
        md("## D. Save the diagnosis for download"),
        code(
            "out_path = WORKING_DIR / 'graph_debug_results.json'",
            "out_path.write_text(json.dumps(report, indent=2))",
            "print(f'Wrote {out_path}')",
        ),
    ]

    return {
        "cells": setup_cells + diagnosis_cells,
        "metadata": base["metadata"],
        "nbformat": base["nbformat"],
        "nbformat_minor": base["nbformat_minor"],
    }


def main() -> None:
    nb = build_notebook()
    OUT_PATH.write_text(json.dumps(nb, indent=1))
    print(f"Wrote {OUT_PATH.relative_to(REPO_DIR)} ({len(nb['cells'])} cells)")


if __name__ == "__main__":
    main()
