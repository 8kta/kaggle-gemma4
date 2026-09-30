# psf/requests navigation notes

- Smaller repo in the task set (13/129 public tasks), compact and
  well-organized — usually the easiest repo to navigate quickly.
- Source lives under `src/requests/` with clear single-purpose modules:
  `models.py` (request/response objects), `adapters.py` (transport adapters),
  `sessions.py`, `utils.py`, `_types.py` (type-only protocol definitions like
  `SupportsRead`). A problem statement mentioning "protocol checks",
  "isinstance", or "hasattr" on file-like objects is very likely about
  `_types.py`'s `SupportsRead`/similar protocols and their usages in
  `models.py`/`adapters.py`.
- A small number of public tasks in this repo are known to already pass their
  full test suite even with zero code changes (a pre-existing data-curation
  quirk, not something to rely on or worry about) — always still verify with
  a real targeted test run rather than assuming a task is a no-op.
