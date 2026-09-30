#!/usr/bin/env python3
"""Synthesizes SFT training trajectories from reference patches (plan step 9).

The stand-in model (gemma4:e4b) has not resolved a single smoke-cohort task
in this whole project (see experiments/CHANGELOG.md) — there is no pool of
real *successful* trajectories to train on yet. Per codex-idea.md phase 5
("use successful and corrected failed trajectories") and claude-idea.md step
9 ("use synthetic trajectories from a stronger model as teacher"), this
script takes the third option available without any model calls at all:
turn each task's reference `patch` (tasks.jsonl ships one per task, a
standard unified diff) directly into the exact tool-call sequence
(`read_file` -> `edit_file`/`write_file` -> `run_command` (targeted test) ->
`submit_patch`) that would have produced it, using the harness's own
`build_agent_prompt()` for the user turn so the SFT examples' prompt format
exactly matches what the real harness shows at inference time.

This is 100% CPU/local — no GPU, no model calls. It does not train
anything; it only produces `experiments/lora_training_data/<split>.jsonl`,
one JSON-lines trajectory per task, for a still-to-be-built GPU training
step (mirrors the official-model baseline: training itself needs a real
GPU this Mac doesn't have, so it will run via a Kaggle notebook, same as
devtools/generate_official_baseline_notebook.py).

**Every trajectory is verified before being written**: the same edit_file/
write_file sequence this script derives is *actually replayed* (in-process
string substitution, not just "looks right") against the real pre-patch
snapshot content, and the result is checked byte-for-byte against `git
apply` of the real reference patch on a copy of the same snapshot. A task
whose patch can't be faithfully reconstructed this way (multi-match
old_string, a hunk pattern this parser doesn't handle, a real `git apply`
failure) is skipped and logged, never silently included with a guessed/
wrong trajectory.

Usage:
    python3 devtools/build_lora_trajectories.py --split train
    python3 devtools/build_lora_trajectories.py --split dev --limit 3 --verbose
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR))

DATA_DIR = REPO_DIR / "downloads/kagglehub/competitions/gemma-4-developer-agent"
TASKS_PATH = DATA_DIR / "tasks.jsonl"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
SPLITS_PATH = REPO_DIR / "experiments" / "lora_splits.json"
SYSTEM_PROMPT_PATH = REPO_DIR / "submission" / "prompts" / "system.md"
OUT_DIR = REPO_DIR / "experiments" / "lora_training_data"


# --- Minimal unified-diff parser -------------------------------------------
# Hand-rolled rather than a new dependency: the format used by tasks.jsonl's
# `patch`/`test_patch` fields is plain git unified diff, well-bounded and
# simple to parse exactly (no fuzzy/context-only patches, no binary hunks
# seen in this dataset).

@dataclass
class Hunk:
    old_start: int
    old_lines: list[str]  # content lines (context + removed), no leading char
    new_lines: list[str]  # content lines (context + added), no leading char


@dataclass
class FileDiff:
    old_path: str | None  # None if old header is literally /dev/null
    new_path: str | None  # None if new header is literally /dev/null
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def is_new_file(self) -> bool:
        # This dataset's patches don't consistently use `--- /dev/null` for
        # new files — some instead keep a real-looking `--- a/<path>` header
        # and signal "new file" only via the hunk itself: a single hunk
        # starting at old_start==0 with no context/removed lines (i.e. every
        # line is an addition). Check both conventions.
        if self.old_path is None:
            return True
        return (
            len(self.hunks) == 1
            and self.hunks[0].old_start == 0
            and not self.hunks[0].old_lines
        )

    @property
    def is_deleted_file(self) -> bool:
        return self.new_path is None

    @property
    def path(self) -> str:
        return self.new_path or self.old_path


def parse_unified_diff(patch_text: str) -> list[FileDiff]:
    lines = patch_text.splitlines()
    files: list[FileDiff] = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("--- "):
            i += 1
            continue
        old_header = lines[i]
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            raise ValueError(f"malformed diff: expected +++ after {old_header!r}")
        new_header = lines[i]
        i += 1

        old_path = old_header[4:].strip()
        new_path = new_header[4:].strip()
        old_path = None if old_path in ("/dev/null",) else _strip_ab_prefix(old_path)
        new_path = None if new_path in ("/dev/null",) else _strip_ab_prefix(new_path)

        fd = FileDiff(old_path=old_path, new_path=new_path)
        while i < len(lines) and lines[i].startswith("@@ "):
            header = lines[i]
            old_start = _parse_hunk_old_start(header)
            i += 1
            old_content: list[str] = []
            new_content: list[str] = []
            while i < len(lines) and not lines[i].startswith("@@ ") and not lines[i].startswith("--- "):
                line = lines[i]
                if line.startswith("+"):
                    new_content.append(line[1:])
                elif line.startswith("-"):
                    old_content.append(line[1:])
                elif line.startswith(" "):
                    old_content.append(line[1:])
                    new_content.append(line[1:])
                elif line == r"\ No newline at end of file":
                    pass
                elif line == "":
                    old_content.append("")
                    new_content.append("")
                else:
                    raise ValueError(f"unrecognized diff line: {line!r}")
                i += 1
            fd.hunks.append(Hunk(old_start=old_start, old_lines=old_content, new_lines=new_content))
        files.append(fd)
    return files


def _strip_ab_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _parse_hunk_old_start(header: str) -> int:
    # "@@ -12,5 +14,6 @@ optional trailing context"
    inner = header.split("@@")[1].strip()
    old_part = inner.split(" ")[0]  # "-12,5"
    old_start = int(old_part.split(",")[0].lstrip("-"))
    return old_start


# --- Trajectory construction -------------------------------------------

def extract_snapshot(task_id: str, dest: Path) -> Path:
    tarball = SNAPSHOTS_DIR / f"{task_id}.tgz"
    with tarfile.open(tarball) as tf:
        tf.extractall(dest, filter="data")
    return dest


def build_tool_calls_for_file(fd: FileDiff, pre_content: str | None) -> list[dict]:
    """Returns a list of {"function_name", "arguments"} tool calls for one
    file's diff. Raises ValueError if this file can't be represented
    faithfully (e.g. a deleted file, which no tool in the 9-tool registry
    directly supports)."""
    calls = []
    if fd.is_new_file:
        full_content = "".join(l + "\n" for l in fd.hunks[0].new_lines)
        if fd.hunks[0].new_lines and fd.hunks[0].new_lines[-1] == "":
            full_content = full_content[:-1]
        calls.append({"function_name": "write_file", "arguments": {"filepath": fd.path, "content": full_content}})
        return calls
    if fd.is_deleted_file:
        raise ValueError(f"deleted file {fd.old_path} not representable by any of the 9 harness tools")

    assert pre_content is not None
    calls.append({"function_name": "read_file", "arguments": {"filepath": fd.path}})
    for hunk in fd.hunks:
        old_string = "\n".join(hunk.old_lines)
        new_string = "\n".join(hunk.new_lines)
        if old_string == new_string:
            continue  # no-op hunk (shouldn't normally occur, guard anyway)
        if pre_content.count(old_string) != 1:
            raise ValueError(
                f"old_string for {fd.path} is not unique in pre-image "
                f"(count={pre_content.count(old_string)}) — cannot build a faithful edit_file call"
            )
        calls.append({"function_name": "edit_file", "arguments": {
            "filepath": fd.path, "old_string": old_string, "new_string": new_string,
        }})
    return calls


def apply_tool_calls_in_memory(file_contents: dict[str, str], calls: list[dict]) -> dict[str, str]:
    """Replays write_file/edit_file calls against an in-memory {path: content}
    map, returning the resulting map. Used to verify fidelity before trusting
    a synthesized trajectory."""
    result = dict(file_contents)
    for call in calls:
        fn, args = call["function_name"], call["arguments"]
        if fn == "write_file":
            result[args["filepath"]] = args["content"]
        elif fn == "edit_file":
            content = result[args["filepath"]]
            if content.count(args["old_string"]) != 1:
                raise ValueError(f"replay failed: old_string not unique for {args['filepath']}")
            result[args["filepath"]] = content.replace(args["old_string"], args["new_string"], 1)
    return result


def git_apply_reference(snapshot_dir: Path, patch_text: str) -> dict[str, str]:
    """Applies the real reference patch via `git apply` in the snapshot repo
    and returns {path: post-image content} for every touched file — the
    ground truth this script's synthesized trajectory is checked against."""
    # Some tasks' patch text in tasks.jsonl lacks a trailing newline after
    # the final context/added line (a dataset-storage artifact, not a real
    # diff corruption) — git apply rejects that as "corrupt patch". Ensure
    # one is present before feeding it in.
    patch_for_apply = patch_text if patch_text.endswith("\n") else patch_text + "\n"
    proc = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        input=patch_for_apply, text=True, cwd=str(snapshot_dir),
        capture_output=True,
    )
    if proc.returncode != 0:
        raise ValueError(f"git apply failed: {proc.stderr.strip()[:500]}")
    diffs = parse_unified_diff(patch_text)
    post: dict[str, str] = {}
    for fd in diffs:
        if fd.is_deleted_file:
            continue
        post[fd.path] = (snapshot_dir / fd.path).read_text()
    return post


def test_command_for(test_patch: str) -> str | None:
    diffs = parse_unified_diff(test_patch)
    test_files = [fd.path for fd in diffs if fd.path and fd.path.endswith(".py")]
    if not test_files:
        return None
    return f"pytest {test_files[0]}"


def build_trajectory(task: dict, system_prompt: str, verbose: bool = False) -> dict:
    task_id = task["instance_id"]
    patch_text = task["patch"]
    diffs = parse_unified_diff(patch_text)

    with tempfile.TemporaryDirectory(prefix=f"lora_traj_{task_id}_") as tmp:
        snap_dir = extract_snapshot(task_id, Path(tmp))

        pre_contents: dict[str, str] = {}
        for fd in diffs:
            if not fd.is_new_file and not fd.is_deleted_file:
                pre_contents[fd.path] = (snap_dir / fd.path).read_text()

        all_calls: list[dict] = []
        for fd in diffs:
            calls = build_tool_calls_for_file(fd, pre_contents.get(fd.path))
            all_calls.extend(calls)

        # Verify fidelity: replay in-memory vs. a real `git apply` on a
        # second, untouched copy of the same snapshot.
        replayed = apply_tool_calls_in_memory(pre_contents, [c for c in all_calls if c["function_name"] != "read_file"])
        ground_truth = git_apply_reference(snap_dir, patch_text)
        for path, expected in ground_truth.items():
            actual = replayed.get(path)
            if actual != expected:
                raise ValueError(f"fidelity check failed for {task_id}:{path} — replayed content diverges from `git apply` output")
        if verbose:
            print(f"  [{task_id}] fidelity check passed for {len(ground_truth)} file(s)")

    # Assemble messages (OpenAI-style tool-calling format).
    test_cmd = test_command_for(task.get("test_patch", ""))
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.append({"role": "user", "content": build_user_prompt(task)})

    call_counter = 0
    for call in all_calls:
        call_counter += 1
        call_id = f"call_{call_counter}"
        messages.append({
            "role": "assistant",
            "tool_calls": [{
                "id": call_id, "type": "function",
                "function": {"name": call["function_name"], "arguments": json.dumps(call["arguments"])},
            }],
        })
        messages.append({"role": "tool", "tool_call_id": call_id, "name": call["function_name"], "content": "ok"})

    if test_cmd:
        call_counter += 1
        call_id = f"call_{call_counter}"
        messages.append({
            "role": "assistant",
            "tool_calls": [{"id": call_id, "type": "function",
                             "function": {"name": "run_command", "arguments": json.dumps({"command": test_cmd})}}],
        })
        messages.append({"role": "tool", "tool_call_id": call_id, "name": "run_command", "content": "ok"})

    call_counter += 1
    call_id = f"call_{call_counter}"
    messages.append({
        "role": "assistant",
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": "submit_patch", "arguments": "{}"}}],
    })
    messages.append({"role": "tool", "tool_call_id": call_id, "name": "submit_patch", "content": "ok"})
    messages.append({"role": "assistant", "content": f"Applied the fix for {task_id} and submitted the patch."})

    return {
        "instance_id": task_id,
        "repo": task["repo"],
        "source": "reference_patch_synthetic",
        "messages": messages,
        "reference_patch_sha256": hashlib.sha256(patch_text.encode()).hexdigest(),
    }


def build_user_prompt(task: dict) -> str:
    """Reuses the harness's own build_agent_prompt() so the SFT user turn
    matches production formatting exactly, rather than a hand-approximated
    guess."""
    from swegemma.config import EvalConfig
    from swegemma.harness.agent_runner import build_agent_prompt
    from swegemma.models import Task as SwegemmaTask

    swe_task = SwegemmaTask(
        instance_id=task["instance_id"], repo=task["repo"], base_commit=task["base_commit"],
        patch=task["patch"], test_patch=task.get("test_patch", ""),
        problem_statement=task["problem_statement"], hints_text=task.get("hints_text", "") or "",
        created_at=task.get("created_at", ""),
    )
    cfg = EvalConfig(
        tasks_path=TASKS_PATH, snapshots_dir=SNAPSHOTS_DIR,
        results_dir=Path("/tmp/unused"), submission_dir=REPO_DIR / "submission",
        models={},
    )
    return build_agent_prompt(swe_task, cfg)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--split", choices=["train", "dev", "validation"], default="train")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    splits = json.loads(SPLITS_PATH.read_text())
    task_ids = splits[args.split]["ids"]
    if args.limit:
        task_ids = task_ids[: args.limit]

    tasks_by_id = {}
    with open(TASKS_PATH) as f:
        for line in f:
            t = json.loads(line)
            if t["instance_id"] in task_ids:
                tasks_by_id[t["instance_id"]] = t

    system_prompt = SYSTEM_PROMPT_PATH.read_text()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{args.split}.jsonl"
    skip_log_path = OUT_DIR / f"{args.split}_skipped.jsonl"

    written = 0
    skipped = []
    with open(out_path, "w") as out_f:
        for task_id in task_ids:
            task = tasks_by_id.get(task_id)
            if task is None:
                skipped.append({"instance_id": task_id, "reason": "not found in tasks.jsonl"})
                continue
            try:
                traj = build_trajectory(task, system_prompt, verbose=args.verbose)
            except Exception as e:
                skipped.append({"instance_id": task_id, "reason": str(e)[:300]})
                if args.verbose:
                    print(f"  [{task_id}] SKIPPED: {e}", file=sys.stderr)
                continue
            out_f.write(json.dumps(traj) + "\n")
            written += 1

    if skipped:
        skip_log_path.write_text("\n".join(json.dumps(s) for s in skipped) + "\n")

    print(f"Split '{args.split}': {written} trajectories written to {out_path}")
    print(f"  {len(skipped)} task(s) skipped (see {skip_log_path if skipped else 'n/a'})")
    for s in skipped[:10]:
        print(f"    {s['instance_id']}: {s['reason']}")
    if len(skipped) > 10:
        print(f"    ... and {len(skipped) - 10} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
