#!/bin/bash
# Run a panel-to-reels step with the skill's venv python.
#
# Usage: scripts/run.sh <step> <project-dir> [args...]
#   steps: fetch transcribe peek shots build captions cover render_all
#   e.g.   scripts/run.sh captions ~/reels/panel A buildup
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${PANEL_TO_REELS_HOME:-$HOME/.panel-to-reels}/venv"
if [ $# -lt 1 ]; then
  sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
fi
STEP="${1%.py}"; shift
if [ ! -f "$HERE/$STEP.py" ]; then
  echo "unknown step '$STEP' (no $HERE/$STEP.py)"; exit 1
fi
if [ ! -x "$VENV/bin/python" ]; then
  echo "venv missing at $VENV: run $HERE/setup.sh first"; exit 1
fi
export PYTHONNOUSERSITE=1
exec arch -arm64 "$VENV/bin/python" -s "$HERE/$STEP.py" "$@"
