# Current Champion

The best validated submission config so far. Every new candidate gets a
**paired comparison** against this champion (same task cohort, same model
backend, same budgets/sampling/seed) before it's allowed to replace it — see
`PROMOTION_CHECKLIST.md`. Update this file by hand when a candidate is
promoted; it is not automated (see plan step 4: "a discipline to follow, not
infrastructure to build").

## Status: none yet

No candidate has been promoted. `submission/` is still the empty scaffold
from step 0 — nothing to compare against until a real `agent.yaml` exists
(plan steps 5-9).

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
