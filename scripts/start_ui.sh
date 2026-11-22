#!/usr/bin/env bash
# Start the PitOpt web UI natively on macOS/Linux (or inside WSL).
# First run creates .venv, installs the package, and prepares bundled synthetic examples.
# Usage: scripts/start_ui.sh [port] [--port PORT] [--check-only] [--no-browser]
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PITOPT_PORT:-8765}"
CHECK_ONLY=0
CLI_NO_BROWSER=0

usage() {
  cat <<'EOF'
Usage: scripts/start_ui.sh [PORT] [--port PORT] [--check-only] [--no-browser]
  PORT           Port for the local web UI (default: 8765, or $PITOPT_PORT)
  --check-only   Verify Python, pitopt package, CLI help, and port status without starting server
  --no-browser   Do not open a web browser automatically (also via NO_BROWSER=1)
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --check-only)
      CHECK_ONLY=1
      shift
      ;;
    --no-browser)
      CLI_NO_BROWSER=1
      shift
      ;;
    --port)
      [ "$#" -ge 2 ] || { echo "PitOpt: --port requires a port number." >&2; exit 1; }
      PORT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "PitOpt: unknown option '$1'" >&2
      usage >&2
      exit 1
      ;;
    *)
      PORT="$1"
      shift
      ;;
  esac
done

case "$PORT" in
  ''|*[!0-9]*)
    echo "PitOpt: invalid port '$PORT' (expected 1-65535)." >&2
    exit 1
    ;;
esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "PitOpt: invalid port '$PORT' (expected 1-65535)." >&2
  exit 1
fi

# The stock python3 on macOS is 3.9, which pip rejects; search 3.10+ first.
find_python() {
  for py in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys, ensurepip, venv; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      echo "$py"; return 0
    fi
  done
  return 1
}

check_python_env() {
  local py_bin="$1"
  "$py_bin" -c 'import sys, importlib.metadata, pitopt; import numpy, pandas, scipy, networkx, yaml, ezdxf, shapely, matplotlib, xlsxwriter, openpyxl, reportlab, plotly, PIL; assert sys.version_info >= (3, 10); importlib.metadata.version("pitopt")' >/dev/null 2>&1
}

check_port_available() {
  local py_bin="$1"
  local port="$2"
  "$py_bin" -c 'import socket, sys; s = socket.socket(); s.settimeout(0.5); busy = s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0; s.close(); raise SystemExit(1 if busy else 0)' "$port"
}

PY_BIN=""
if [ -x ".venv/bin/python" ] && check_python_env ".venv/bin/python"; then
  PY_BIN=".venv/bin/python"
else
  if [ "$CHECK_ONLY" -eq 1 ]; then
    if SYS_PY="$(find_python)" && check_python_env "$SYS_PY"; then
      PY_BIN="$SYS_PY"
    else
      echo "PitOpt check-only failed: .venv/bin/python is missing or incomplete and no native Python 3.10+ with pitopt was found." >&2
      exit 1
    fi
  else
    if ! PY="$(find_python)"; then
      echo "PitOpt needs Python 3.10 or newer. Install Python 3.10+ (e.g. from python.org or Homebrew) and run this again." >&2
      exit 1
    fi
    echo "Preparing PitOpt with $("$PY" --version): creating or repairing .venv and installing dependencies..."
    "$PY" -m venv .venv
    .venv/bin/python -m pip install --quiet --upgrade pip
    INSTALL_ARGS=(--default-timeout=300 -e .)
    if [ -n "${PITOPT_CONSTRAINTS:-}" ]; then
      [ -f "$PITOPT_CONSTRAINTS" ] || { echo "Constraint file not found: $PITOPT_CONSTRAINTS" >&2; exit 1; }
      INSTALL_ARGS+=(--constraint "$PITOPT_CONSTRAINTS")
    fi
    .venv/bin/python -m pip install "${INSTALL_ARGS[@]}"
    PY_BIN=".venv/bin/python"
  fi
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  "$PY_BIN" -m pitopt ui --help >/dev/null
  PORT_STATUS="available"
  if ! check_port_available "$PY_BIN" "$PORT"; then
    PORT_STATUS="in-use"
  fi
  echo "PitOpt check-only OK: python=$PY_BIN ($("$PY_BIN" --version 2>&1)), port=$PORT ($PORT_STATUS)"
  exit 0
fi

if ! check_port_available "$PY_BIN" "$PORT"; then
  echo "PitOpt: port $PORT is already in use on 127.0.0.1." >&2
  echo "Stop the existing server or run with another port: scripts/start_ui.sh 8766" >&2
  exit 1
fi

# Sample data and a first run, so the app does not open on an empty screen.
if [ ! -f projects/porphyry_synthetic/data/porphyry_blocks.csv ]; then
  "$PY_BIN" scripts/make_synthetic_deposit.py --nx 60 --ny 60 --nz 28 >/dev/null
fi
if ! "$PY_BIN" - <<'READY'
import json
from pathlib import Path
from pitopt.config import ProjectConfig
from pitopt.provenance import freshness
path=Path('outputs/example_tin/example_tin_results.json')
raise SystemExit(0 if path.exists() and freshness(json.loads(path.read_text()), ProjectConfig.from_yaml('projects/example_tin/project.yaml'))['status']=='current' else 1)
READY
then
  echo "Running the synthetic tin example (about 20 s)..."
  "$PY_BIN" -m pitopt run --config projects/example_tin/project.yaml >/dev/null
fi

ARGS=(--root . --port "$PORT")
if [ "${NO_BROWSER:-}" = "1" ] || [ "$CLI_NO_BROWSER" -eq 1 ]; then
  ARGS+=(--no-browser)
elif [ "$(uname -s)" != "Darwin" ] && [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  ARGS+=(--no-browser)
fi

exec "$PY_BIN" -m pitopt ui "${ARGS[@]}"
