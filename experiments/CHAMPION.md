# Current Champion

The best validated submission config so far. Every new candidate gets a
**paired comparison** against this champion (same task cohort, same model
backend, same budgets/sampling/seed) before it's allowed to replace it — see
`PROMOTION_CHECKLIST.md`. Update this file by hand when a candidate is
promoted; it is not automated (see plan step 4: "a discipline to follow, not
infrastructure to build").

## Status: none yet

No candidate has been promoted. This is **not** because `submission/` is
empty — it has had a real `agent.yaml`/`prompts`/`configs`/`skills` since
plan step 6, and has gone through two rounds of prompt-engineering (step 7)
plus a skills investigation (step 8). "None yet" reflects that no candidate
has cleared `PROMOTION_CHECKLIST.md`: none has been run on the official
model, passed the comparison cohort, or been checked against the held-out
slice. All work so far is `--fidelity proxy-model` (the `gemma4:e4b`
stand-in) — real prompt-mechanics evidence, but not a validated candidate.

---

Template for when a champion exists:

```
## Current champion: <label>
- Promoted: <date>
- Config snapshot: `experiments/<label>/submission_snapshot/`
- Config hash: `<sha256 from MLflow config_hash tag>`
- Results dir: `results/<label>/`
- MLflow: <url>
- Cohort + fidelity it was validated on: <cohort>, <fidelity>
- resolution_rate / proxy_resolution_rate: <value>
- Held-out slice result: <value> (only required once official-model runs are
  in play — see promotion checklist)
- Why it was promoted (what it beat, by how much): <note>
```
