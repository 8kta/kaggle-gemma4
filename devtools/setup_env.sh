#!/usr/bin/env bash
# Reproduces the full local dev environment for the Gemma 4 Developer Agent
# Competition harness (plan step 1). Safe to re-run.
#
# Requires: python3.13 on PATH, Docker running, Kaggle credentials already
# configured (run `python3 -c "import kagglehub; kagglehub.login()"` once
# beforehand if ~/.kaggle/access_token doesn't exist yet — this script does
# not prompt for/handle credentials itself).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "== 1/6: Python 3.13 venv =="
if ! command -v python3.13 >/dev/null 2>&1; then
  echo "ERROR: python3.13 not found on PATH. swegemma requires Python >=3.12." >&2
  exit 1
fi
if [ ! -d .venv ]; then
  python3.13 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -V

# An existing .venv could have been created with a stale/wrong Python (e.g.
# manually, or by an older version of this script) — reusing it silently
# would fail later with a confusing error deep in `pip install`, not here.
# Fail loudly and immediately instead.
if ! python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"; then
  echo "ERROR: existing .venv is on $(python -V 2>&1), but swegemma requires >=3.12." >&2
  echo "  Fix: rm -rf .venv && ./devtools/setup_env.sh" >&2
  exit 1
fi

pip install --quiet --upgrade pip

echo "== 2/6: kagglehub + project-local cache =="
pip install --quiet kagglehub
if ! grep -q "KAGGLEHUB_CACHE" .venv/bin/activate; then
  cat >> .venv/bin/activate << EOF

# Project-specific: keep all kagglehub downloads inside the repo's downloads/ dir
export KAGGLEHUB_CACHE="$REPO_DIR/downloads/kagglehub"
EOF
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "== 3/6: Kaggle credential check =="
python3 -c "import kagglehub; print(kagglehub.whoami())" || {
  echo "ERROR: Kaggle not authenticated. Run:" >&2
  echo '  python3 -c "import kagglehub; kagglehub.login()"' >&2
  exit 1
}

echo "== 4/6: Competition dataset (~21 GB, skips if already cached) =="
DATA_DIR="$(python3 -c "import kagglehub; print(kagglehub.competition_download('gemma-4-developer-agent'))")"
echo "Data dir: $DATA_DIR"

echo "== 5/6: Harness wheelhouse (~827 MB, skips if already cached) =="
WHEELHOUSE_DIR="$(python3 -c "import kagglehub; print(kagglehub.dataset_download('metric/gemma-4-developer-agent-wheelhouse'))")"
echo "Wheelhouse dir: $WHEELHOUSE_DIR"

# Glob by package name prefix rather than hardcoding exact version numbers
# (adk_eval_core-0.1.0-py3-none-any.whl etc.) — a wheelhouse dataset version
# bump that ships a new package version would otherwise silently fail to
# match a hardcoded filename and break this script.
WHEEL_PATTERNS=(
  "adk_eval_core-*-py3-none-any.whl"
  "adk_submission-*-py3-none-any.whl"
  "swegemma-*-py3-none-any.whl"
  "google_adk-*-py3-none-any.whl"
)
WHEELS_TO_INSTALL=()
for pattern in "${WHEEL_PATTERNS[@]}"; do
  matches=("$WHEELHOUSE_DIR"/$pattern)
  if [ ! -e "${matches[0]}" ]; then
    echo "ERROR: no wheel matching '$pattern' found in $WHEELHOUSE_DIR." >&2
    echo "  The wheelhouse dataset layout may have changed — check its contents manually." >&2
    exit 1
  fi
  if [ "${#matches[@]}" -gt 1 ]; then
    echo "NOTE: multiple wheels matched '$pattern' in $WHEELHOUSE_DIR: ${matches[*]}" >&2
    echo "  Using the first match: ${matches[0]}" >&2
  fi
  WHEELS_TO_INSTALL+=("${matches[0]}")
done
pip install --quiet "${WHEELS_TO_INSTALL[@]}"

echo "== 6/6: Pin remaining transitive dependencies =="
pip install --quiet -r requirements-lock.txt

echo "== Sandbox image =="
if ! docker image inspect swebench-sandbox:latest >/dev/null 2>&1; then
  echo "Building swebench-sandbox:latest from the dataset's docker/Dockerfile.sandbox..."
  (cd "$DATA_DIR/docker" && docker build -f Dockerfile.sandbox -t swebench-sandbox:latest .)
else
  echo "swebench-sandbox:latest already present."
fi

echo
echo "Done. Verify with:"
echo "  source .venv/bin/activate"
echo "  swegemma --help"
echo "  docker images swebench-sandbox:latest"
