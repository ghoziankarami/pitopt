#!/usr/bin/env bash
# Start the PitOpt web UI. First run creates .venv and installs the package.
# Usage: scripts/start_ui.sh [port]   (default 8765; NO_BROWSER=1 skips opening a browser)
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${1:-8765}"

if [ ! -x .venv/bin/python ]; then
  echo "First-time setup: creating a local environment and installing PitOpt. This may take a few minutes..."
  python3 -m venv .venv
  .venv/bin/pip install --default-timeout=300 -e .
fi

ARGS=(--root . --port "$PORT")
[ "${NO_BROWSER:-}" = "1" ] && ARGS+=(--no-browser)
exec .venv/bin/python -m pitopt ui "${ARGS[@]}"
