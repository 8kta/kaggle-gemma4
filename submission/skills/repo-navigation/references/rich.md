# Textualize/rich navigation notes

- Second-largest repo in the task set (48/129 public tasks).
- This repo's test suite is the one most likely to hit the sandbox's resource
  limits (4GB RAM cap, 300s default command timeout) — some tests here have
  been observed to hit the timeout or get OOM-killed even without any code
  change. Keep this in mind if a targeted test run seems to hang: don't
  broaden the test scope to "diagnose" it, and don't assume a timeout means
  your fix is wrong.
- Several tests (`test_syntax.py`, `test_console.py`) assert on *exact*
  terminal escape-sequence output (colors, cursor codes). These are extremely
  sensitive to incidental formatting changes — avoid touching rendering code
  unless the problem statement specifically asks for it, and don't "clean up"
  unrelated rendering logic as a side effect of your fix.
- Source lives directly under `rich/` (e.g. `rich/logging.py`,
  `rich/console.py`) — a flat, mostly single-level package layout.
