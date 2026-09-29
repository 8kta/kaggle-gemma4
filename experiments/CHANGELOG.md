# Experiment Changelog

One entry per iteration. See `agent-ideas/claude-idea.md` step 2 for the full
logging practice this supports.

Entry format:

```
## YYYY-MM-DD — <short label>
- Hypothesis: <what you expected this change to do>
- Change: <what actually changed — prompt/yaml/skill/adapter>
- Cohort: <smoke / prompt-dev / comparison / held-out / full-129>
- Result: <resolution_rate or proxy_resolution_rate, notable FAIL→PASS / PASS→FAIL>
- Results dir: `results/<run-label>/`
- Commit: `<git sha>`
```

---
