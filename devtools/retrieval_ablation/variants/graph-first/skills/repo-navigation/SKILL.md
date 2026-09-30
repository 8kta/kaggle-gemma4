---
name: repo-navigation
description: Repo-specific navigation notes and known gotchas for the four target repositories (fastapi/fastapi, Textualize/rich, psf/requests, encode/httpx), distilled from real evaluation runs on the public task set. Optional — load only if you want extra context beyond the problem statement.
---

# Repo Navigation Notes

This skill has one reference file per target repository under `references/`, named after the repo's short name: `fastapi.md`, `rich.md`, `requests.md`, `httpx.md`.

If you know which repository you're working in (it's given in the task header), load the matching file with `load_skill_resource(skill_name="repo-navigation", file_path="references/<repo>.md")` before you start exploring — it can save you a few tool calls of trial and error on things that are already known gotchas for that repo. This is optional: if the problem statement already gives you an exact file path and clear symptom, you likely don't need it.
