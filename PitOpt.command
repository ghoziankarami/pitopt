#!/usr/bin/env bash
# Linux/macOS launcher: ./PitOpt.command
cd "$(dirname "$0")" && (sleep 3; xdg-open http://localhost:8765 2>/dev/null || open http://localhost:8765 2>/dev/null) &
NO_BROWSER=1 exec "$(dirname "$0")/scripts/start_ui.sh"
