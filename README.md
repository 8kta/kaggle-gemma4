# kaggle-gemma4

Working repo for the Kaggle **Gemma 4 Developer Agent Competition**. See
`agent-ideas/claude-idea.md` for the full working plan and
`agent-ideas/codex-idea.md` for a parallel plan draft; `docs/` holds the
competition's own reference material (Overview, Data, HARNESS_README).

## Layout

```
submission/       # Competition files only — this is what gets zipped as submission.zip
  configs/        # sampling.yaml etc., loaded via !include
  prompts/        # system.md etc., loaded via !include
  sub_agents/     # sub-agent / AgentTool YAML configs
  skills/         # ADK Skill directories (SKILL.md + scripts/resources)
  adapters/       # LoRA adapter directories (adapter_config.json + adapter_model.safetensors)
devtools/mlflow/  # Host-side MLflow wrappers (run_evaluation.py, ingest_results.py) — dev-only, never imported by submission/
experiments/      # CHANGELOG.md + per-run config snapshots
results/          # Native swegemma eval output (--results-dir target), gitignored
docs/             # Competition reference docs (Overview, Data, HARNESS_README)
agent-ideas/      # Planning docs
```

`requirements-dev.txt` holds dev-only dependencies (MLflow, kagglehub). Nothing
under `submission/` may depend on them — see `agent-ideas/claude-idea.md` step 2
and step 11 for the isolation checks that enforce this before packaging.
