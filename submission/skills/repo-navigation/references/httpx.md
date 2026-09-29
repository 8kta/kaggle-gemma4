# encode/httpx navigation notes

- Only one public task from this repo in the training set, so there isn't
  enough evidence yet to know this repo's common quirks the way there is for
  the other three.
- Source lives under `src/httpx/` (e.g. `src/httpx/_parsers.py`,
  `src/httpx/_client.py`). Underscore-prefixed module names (`_parsers.py`,
  `_client.py`, etc.) are internal implementation modules — the public API
  usually re-exports from these in `src/httpx/__init__.py`.
