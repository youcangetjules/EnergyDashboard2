#!/usr/bin/env bash
# Create a virtual environment and install PowerModel / EnergyDashboard dependencies.
# Usage: ./setup.sh
#        VENV=/path/to/other-venv ./setup.sh   # optional custom venv path

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${VENV:-$ROOT/.venv}"
REQ="$ROOT/requirements.txt"

if [[ ! -f "$REQ" ]]; then
  echo "Missing requirements.txt at $REQ" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found; install Python 3.10+ and try again." >&2
  exit 1
fi

echo "Creating venv: $VENV"
python3 -m venv "$VENV"

echo "Upgrading pip"
"$VENV/bin/python" -m pip install --upgrade pip

echo "Installing from requirements.txt"
"$VENV/bin/pip" install -r "$REQ"

echo
echo "Done. Activate the environment:"
echo "  source \"$VENV/bin/activate\""
echo "Then run, for example:"
echo "  python \"$ROOT/EnergyDashboard2.py\""
