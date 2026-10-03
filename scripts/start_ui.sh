#!/usr/bin/env bash
# Start the PitOpt web UI. First run creates .venv, installs the package and runs the bundled
# synthetic examples so the app opens with results to explore.
# Usage: scripts/start_ui.sh [port]   (default 8765; NO_BROWSER=1 skips opening a browser)
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${1:-8765}"

# The stock python3 on macOS is 3.9, which pip rejects with a cryptic message; find 3.10+ first.
find_python() {
  for py in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      echo "$py"; return 0
    fi
  done
  return 1
}

# Checked by import, not by the file existing: an interrupted install leaves a .venv without pitopt.
if ! .venv/bin/python -c "import pitopt" >/dev/null 2>&1; then
  if ! PY="$(find_python)"; then
    echo "PitOpt needs Python 3.10 or newer (found: $(python3 --version 2>&1 || echo none))."
    echo "Install it from https://www.python.org/downloads/ (macOS: or 'brew install python'), then run this again."
    exit 1
  fi
  echo "First-time setup with $("$PY" --version): creating .venv and installing PitOpt. This takes a few minutes..."
  rm -rf .venv
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --default-timeout=300 -e .
fi

# Sample data and a first run, so the app does not open on an empty screen.
if [ ! -f projects/porphyry_synthetic/data/porphyry_blocks.csv ]; then
  .venv/bin/python scripts/make_synthetic_deposit.py --nx 60 --ny 60 --nz 28 >/dev/null
fi
if [ ! -f outputs/example_tin/example_tin_results.json ]; then
  echo "Running the synthetic tin example (about 20 s)..."
  .venv/bin/python -m pitopt run --config projects/example_tin/project.yaml >/dev/null
fi

ARGS=(--root . --port "$PORT")
[ "${NO_BROWSER:-}" = "1" ] && ARGS+=(--no-browser)
exec .venv/bin/python -m pitopt ui "${ARGS[@]}"
