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
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys, ensurepip, venv; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      echo "$py"; return 0
    fi
  done
  return 1
}

# Validate the installed editable package and real runtime imports, outside cwd lookup.
# Repair dependencies in place so interrupted setup does not delete an existing environment.
if ! .venv/bin/python -I -c 'import sys, pathlib, importlib.metadata, pitopt; import numpy, pandas, scipy, networkx, yaml, ezdxf, shapely, matplotlib, xlsxwriter, openpyxl, reportlab, plotly, PIL; assert sys.version_info >= (3,10); importlib.metadata.version("pitopt"); assert pathlib.Path(pitopt.__file__).resolve().parent == pathlib.Path(sys.argv[1]).resolve()/"pitopt"' "$PWD" >/dev/null 2>&1; then
  if ! PY="$(find_python)"; then
    echo "PitOpt needs Python 3.10 or newer. Install a supported Python and run this again."
    exit 1
  fi
  echo "Preparing PitOpt with $("$PY" --version): creating or repairing .venv and installing dependencies..."
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  INSTALL_ARGS=(--default-timeout=300 -e .)
  if [ -n "${PITOPT_CONSTRAINTS:-}" ]; then
    [ -f "$PITOPT_CONSTRAINTS" ] || { echo "Constraint file not found: $PITOPT_CONSTRAINTS"; exit 1; }
    INSTALL_ARGS+=(--constraint "$PITOPT_CONSTRAINTS")
  fi
  .venv/bin/python -m pip install "${INSTALL_ARGS[@]}"
fi

# Sample data and a first run, so the app does not open on an empty screen.
if [ ! -f projects/porphyry_synthetic/data/porphyry_blocks.csv ]; then
  .venv/bin/python scripts/make_synthetic_deposit.py --nx 60 --ny 60 --nz 28 >/dev/null
fi
if ! .venv/bin/python - <<'READY'
import json
from pathlib import Path
from pitopt.config import ProjectConfig
from pitopt.provenance import freshness
path=Path('outputs/example_tin/example_tin_results.json')
raise SystemExit(0 if path.exists() and freshness(json.loads(path.read_text()), ProjectConfig.from_yaml('projects/example_tin/project.yaml'))['status']=='current' else 1)
READY
then
  echo "Running the synthetic tin example (about 20 s)..."
  .venv/bin/python -m pitopt run --config projects/example_tin/project.yaml >/dev/null
fi

ARGS=(--root . --port "$PORT")
[ "${NO_BROWSER:-}" = "1" ] && ARGS+=(--no-browser)
exec .venv/bin/python -m pitopt ui "${ARGS[@]}"
