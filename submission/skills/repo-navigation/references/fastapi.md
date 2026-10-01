# fastapi/fastapi navigation notes

- Largest repo in the task set (67/129 public tasks) — most likely repo you'll see.
- Documentation code samples live under `docs_src/` and are executable — if the
  problem statement is about docs, edit the code under `docs_src/`, not the
  markdown/docs prose itself.
- Some tasks have vague, PR-template-style problem statements with no concrete
  error message or symbol name (e.g. a bare PR title like "Automate release
  preparation"). For these, use `run_command` with `find`/`grep`/`ls` to
  explore directly rather than concluding the task is impossible.
- Some tasks' test files reference helper modules (e.g. `scripts/` tooling)
  that may not resolve via normal imports in this environment due to how
  pytest is configured (`--import-mode=importlib` doesn't add the repo root to
  `sys.path` the way some tests may assume). If a test fails to even *collect*
  with a `ModuleNotFoundError` for something under `scripts/`, this may be a
  pre-existing environment quirk rather than something your fix caused — don't
  spend turns trying to "fix" the test's import machinery; focus on the
  reported issue in source code.
