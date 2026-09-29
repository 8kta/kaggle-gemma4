# Enhanced Agent Development Plan: Gemma 4 Developer Agent

This project aims to build an autonomous software engineering agent using **Gemma 4** to solve real-world Python bug fixes and feature requests.

## Project Core Constraints
- **Base Model**: `gemma-4-31b-it-qat-w4a16-ct`.
- **Submission**: `submission.zip` with `agent.yaml` (declarative YAML format).
- **Evaluation**: Pass/Fail based on `pytest` validation of the submitted git patch.
- **Limits**: < 3 GiB total size, 32,768 token context window.
- **Key Tools**: Shell access (`run_command`), file manipulation, and code-graph intelligence (`get_code_neighbors`, `search_similar_code`, `get_code_subgraph`).

---

## Proposed Work Plan

### Phase 0: Infrastructure for Traceability & Provenance
- **Experiment Tracking**: Establish an `experiments/` directory and one running `experiments/CHANGELOG.md`. Every modification to prompts, YAML configs, skills, or adapters must be versioned.
- **Git-Backed Identity**: Associate every evaluation with a Git commit, dirty-worktree status, MLflow run ID, result-directory path, and hashes of all submission inputs. Commit or snapshot the exact configuration before important evaluations so any result can be reproduced or reverted.
- **Versioning Strategy**: Save each iteration under a stable label (for example, `experiments/v0_1_baseline/`) with the exact agent configuration, prompts, hypothesis, and native harness results.
- **Provenance Logging**: For every evaluation run, record:
    - The specific version of the config used.
    - The hypothesis for the change.
    - The execution profile, model backend, task cohort, budgets, sampling settings, and seed.
    - The resulting metrics and specific task-level changes (`FAIL` to `PASS` and `PASS` to `FAIL`).
- **Trace Archiving**: Archive the `traces/` and `logs/` of critical edge cases alongside the corresponding config version for rapid debugging.

### Phase 0A: External MLflow Tracking
- **Hard Architecture Boundary**: Run MLflow as a host-side observer around `swegemma eval`. The submitted agent must never import, call, depend on, or contain MLflow configuration.
- **Tracking Server**: Use `http://localhost:5001` for evaluations launched on the Mac. Use `http://host.docker.internal:5001` only if a development process inside Docker must report directly, although host-side ingestion is preferred.
- **Experiment Separation**: Keep runs with different levels of evaluation fidelity in separate MLflow experiments:
    - `gemma-agent/local-loop` for Ollama or LM Studio stand-in model runs.
    - `gemma-agent/sandbox-validation` for Docker, patch application, packaging, and test-pipeline checks.
    - `gemma-agent/official-eval` for rented NVIDIA infrastructure using the official model and vLLM.
    - `gemma-agent/lora-training` for adapter training, checkpoints, and validation.
- **Run Hierarchy**:
    - Create one parent run for each agent version or evaluation batch.
    - Create one nested child run for each benchmark task.
    - Give every run a stable agent version and result-directory identifier.
- **Required Run Tags**:
    - Execution profile: `mac-local`, `docker-arm64`, `docker-amd64-emulated`, or `cloud-nvidia`.
    - Fidelity: `structural`, `proxy-model`, or `official-model`.
    - Model, quantization, inference backend, hardware, architecture, and sandbox platform.
    - Git commit and dirty-worktree status, agent version, dataset version, task subset, and harness version.
    - Hashes for `agent.yaml`, prompts, skills, adapters, and `eval_config.yaml`.
- **Parent-Run Metrics**:
    - Overall resolution rate, resolved count, error count, total runtime, and repository-level resolution rates.
    - Tool-call validity, patch-generation rate, patch-application rate, test-execution rate, timeout rate, and agent-loop failure rate.
    - Treat local stand-in results as `proxy_resolution_rate`; reserve `resolution_rate` for representative official-model runs.
- **Task-Run Metrics**:
    - Task ID, repository, base commit, pass/fail result, and classified failure mode.
    - Tool calls, turns, nudges, tokens, elapsed time, patch size, test duration, and process exit codes.
    - Patch application status and regression direction relative to the comparison run (`FAIL` to `PASS` or `PASS` to `FAIL`).
- **Artifact Retention Policy**:
    - Always upload configuration snapshots, experiment hypothesis, environment manifest, harness summary, task results, and generated patches.
    - Upload full traces, transcripts, and test output for failures, regressions, and notable improvements.
    - Keep routine successful traces in the native result directory and record their paths and checksums in MLflow.
    - Promote essential artifacts to durable shared storage before deleting local results.
- **Large Dataset Policy**: Do not upload snapshots, wheels, graphs, or embeddings for every run. Record their versions, checksums, and local or remote locations.
- **Durable Local Results**: Keep the native `swegemma` result directory as the authoritative debugging record. MLflow indexes and compares those results but does not replace them.
- **Failure Tolerance**: MLflow outages must not stop an evaluation. Preserve partial results locally and support later ingestion into the tracking server.
- **Remote GPU Runs**: Reach the MLflow server through a private network or secure tunnel, use a shared remote tracking server, or download the completed result directory and ingest it from the Mac afterward.

### Phase 0B: Development and Submission Isolation
- **Repository Layout**:
    - Keep competition files under `submission/`.
    - Keep MLflow wrappers and ingestion utilities under `devtools/mlflow/`.
    - Keep native harness output under `results/` and experiment definitions under `experiments/`.
    - Keep MLflow in `requirements-dev.txt` or a development-only dependency group.
- **Host-Side Evaluation Wrapper**: Create `devtools/mlflow/run_evaluation.py` to:
    1. Start the parent MLflow run and capture provenance.
    2. Snapshot the agent configuration and prompts.
    3. Launch `swegemma eval` as a subprocess with a unique result directory.
    4. Parse `summary.json` and `task_results.jsonl` after execution.
    5. Create per-task child runs and upload metrics and debugging artifacts.
    6. Preserve and ingest partial results if evaluation or tracking fails.
- **Offline Result Ingestion**: Create `devtools/mlflow/ingest_results.py` so completed local or cloud result directories can be logged after evaluation without instrumenting the agent runtime.
- **Explicit Submission Allowlist**: Build `submission.zip` only from approved paths inside `submission/`: root YAML files plus `configs/`, `prompts/`, `sub_agents/`, `skills/`, and `adapters/`.
- **Packaging Exclusions**: Reject MLflow directories, development utilities, result directories, experiment logs, `.env` files, credentials, tracking URLs, unsupported extensions, symlinks, and paths outside `submission/`.
- **Submission Isolation Checks**:
    1. Validate the extracted submission with MLflow uninstalled.
    2. Search it for MLflow imports, tracking URLs, and MLflow environment variables.
    3. Compare archive contents with the explicit allowlist.
    4. Confirm exactly one root agent configuration exists.
    5. Compile and smoke-test the agent using only the extracted archive.
    6. Record the final archive checksum in MLflow as the candidate submission identifier.

### Phase 1: Environment & Data Pipeline (Operational Foundation)
- **Data Acquisition**: Pull the full competition dataset via `kagglehub` (`tasks.jsonl`, `snapshots/`, `graphs/`, `embeddings/`, `wheels/`, `docker/`, `sample_submission/`).
- **Harness Setup**: Install `swegemma`, `adk-submission`, and `adk-eval-core`. Configure Docker for `--sandbox docker`, with `subprocess` available as a development fallback.
- **Mac Compatibility Check**:
    - Inspect the supplied wheel architecture before selecting the Docker platform.
    - Use native Apple Silicon containers when compatible; otherwise use `--platform linux/amd64` and tag those runs as emulated.
    - Do not compare timing from emulated Docker runs directly with native Mac or cloud GPU runs.
- **Three Baselines**:
    - **Mac structural baseline**: Validate agent compilation, includes, tools, Docker setup, patch extraction, patch application, and selected tests without claiming a model-quality score.
    - **Mac proxy-model baseline**: Use a smaller stand-in model to debug orchestration and record `proxy_resolution_rate` plus engineering metrics.
    - **Official GPU baseline**: Use rented NVIDIA hardware, the required 31B model, and vLLM to establish the first meaningful `resolution_rate`.
- **Resource Profiling**: Record container platform, CPU and memory limits, peak utilization, tool calls, turns, context use, per-task duration, timeouts, and projected full-suite runtime.

### Phase 1A: Evaluation Cohorts & Promotion Gates
- **Fixed Task Cohorts**:
    - A small smoke set covering each repository and common failure class.
    - A prompt-development set for rapid iteration.
    - A repository-balanced comparison set for candidate-versus-champion evaluations.
    - A held-out public validation set that is not inspected during prompt development.
    - The complete 129-task suite for milestone evaluations on the official model.
- **Paired Comparisons**: Evaluate every candidate and the current champion on identical tasks, model backend, budgets, sampling settings, and seeds. Record confidence and run-to-run variance when generation is nondeterministic.
- **Promotion Pipeline**:
    1. Submission/configuration validation.
    2. Mac smoke suite.
    3. Proxy-model agent-loop suite.
    4. Official-model development suite.
    5. Held-out validation suite.
    6. Full official-model candidate evaluation.
- **Promotion Criteria**: Define minimum patch-generation, patch-application, tool-call-validity, test-execution, and resolution metrics, plus maximum regression, timeout, and runtime thresholds for each stage.
- **Champion Tracking**: Keep one immutable champion configuration and compare each candidate against it before promotion.

### Phase 2: Deep Failure Analysis & Repo Profiling
- **Failure Bucketing**: Categorize baseline misses into:
    - **Navigation**: Failure to find the relevant file/function.
    - **Reasoning**: Correct file found, but wrong logic applied.
    - **Operational**: Truncated tool calls, budget exhaustion, or patch-apply failures.
    - **Constraint**: Accidental tampering with `pytest.ini` or `conftest.py`.
- **Actionable Diagnosis**: Map navigation failures to retrieval and graph-tool changes, reasoning failures to prompt or training changes, operational failures to tool/budget changes, and constraint failures to explicit guardrails.
- **Repo-Specific Analysis**: Compare performance across `fastapi`, `starlette`, `pydantic`, `rich`, `requests`, and `httpx` to determine whether specific repositories need different navigation strategies.

### Phase 3: Agent Architecture & Prompt Engineering
- **Multi-Agent Design**:
    - **Root Coder Agent**: High-level planner and final patch submitter.
    - **Code Analyzer Sub-Agent**: A read-only `AgentTool` with `skip_summarization: true`, used for graph exploration (`get_code_neighbors`, `search_similar_code`) while keeping the root context lean.
    - **Verification Agent**: Specialized in creating and executing reproduction scripts in `/tmp`.
- **Loop Design**: Implement a strict "Think $\to$ Explore $\to$ Reproduce $\to$ Fix $\to$ Verify" prompt strategy.
- **Architecture Ablation**: Compare a single agent, root plus analyzer, root plus verifier, and root plus both sub-agents on the same cohort. Retain each sub-agent only if its resolution gain justifies its token and runtime cost.
- **Constraint Guardrails**: Embed explicit instructions in prompts to:
    - Keep `edit_file` payloads focused to avoid `<|tool_call>` truncation.
    - Never modify `/workspace/pytest.ini` or `/workspace/conftest.py`.
    - Store all scratch scripts in `/tmp` or delete them before `submit_patch()`.
- **Iterative Logging**: Record every prompt change in `experiments/CHANGELOG.md` with its hypothesis, Git commit, MLflow run, versioned snapshot, and associated `swegemma` results.

### Phase 4: Tool & Skill Optimization
- **Custom Skills**: Create narrowly scoped ADK Skills (`SKILL.md` plus optional scripts/resources) for repeated repository mapping or regression-test workflows. Account for skill-script calls in the same execution budget as other sandbox commands.
- **Graph Tool Integration**: Optimize pre-computed embeddings and graphs to reduce unnecessary `read_file` calls and prioritize high-probability symbols.
- **Retrieval Ablation**: Compare filesystem-only, graph-first, and hybrid navigation on an identical task cohort.
- **Retrieval Metrics**: Track tool calls and tokens before opening the first relevant file, successful symbol-discovery rate, redundant reads, total navigation time, and final resolution rate.

### Phase 5: Model Fine-Tuning (Optional/Competitive)
- **Data Discipline**: Split training, development, and validation task IDs before generating trajectories. Track every source task and prevent reference patches or validation trajectories from leaking into training.
- **LoRA Training**: Use successful and corrected failed trajectories to train PEFT adapters for:
    - Improved tool-calling precision.
    - Enhanced reasoning over graph structures.
    - More focused `edit_file` payloads.
- **Candidate Configurations**: Begin with ranks such as 16 and 32, then expand only when evaluation evidence supports it.
- **Adapter Validation**: Verify the single-base-model rule, total 3 GiB submission limit, `max_loras=8`, and `max_lora_rank=128`.
- **Training Provenance**: Log dataset and trajectory hashes, hyperparameters, target modules, checkpoint and adapter checksums, hardware, training metrics, and the exact official-model evaluation run used for comparison.

### Phase 6: Final Validation & Submission
- **Realistic Official Evaluation**: Run milestone and final scoring evaluations on suitable NVIDIA infrastructure with budgets matching the competition. Use Mac runs for structural, sandbox, and proxy-model validation.
- **Resumable Batches**: Skip task IDs with complete valid results, preserve partial outputs, and resume interrupted evaluations without duplicating MLflow child runs.
- **Budget Validation**: Confirm projected full-suite runtime, per-task timeout, tool-call and turn budgets, context use, container limits, and total 12-hour execution feasibility.
- **Submission Packaging**: Assemble `submission.zip` following the strict layout; validate file extensions and absence of path traversal/symlinks.
- **Final Verification**: Confirm no scratch files remain in `/workspace` prior to the final `submit_patch()` call.
- **Release Candidate Record**: Treat each final candidate as immutable and record its archive checksum, Git commit, official evaluation run, configuration hashes, and validation report in MLflow and `experiments/CHANGELOG.md`.

### Phase 7: Milestones & Competition Timeline
- **Milestones**: Schedule dates for environment readiness, first structural baseline, first proxy loop, first official-model baseline, architecture freeze, LoRA freeze, full evaluation, and final candidate freeze.
- **Competition Deadlines**:
    - Optional paper submission: November 12, 2026 at 11:59 PM UTC.
    - Entry and team-merger deadline: November 25, 2026 at 11:59 PM UTC.
    - Final competition submission: December 2, 2026 at 11:59 PM UTC.
- **Schedule Risk**: Start official-model access and LoRA data preparation early because they have the longest lead time and highest infrastructure dependency.
