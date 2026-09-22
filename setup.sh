#!/usr/bin/env bash
# Create a virtual environment and install PowerModel / EnergyDashboard dependencies.
# Usage: ./setup.sh
#        VENV=/path/to/other-venv ./setup.sh   # optional custom venv path
#
# Recreates the venv if it already exists (--clear) so a system Python upgrade
# (e.g. 3.13 → 3.14) does not leave a broken environment.

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

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "Using python3 ($PY_VER) → venv: $VENV"

# Drop any previous venv. After a distro upgrade (e.g. Ubuntu 26.04 →
# Python 3.14) the old tree is often for the previous interpreter; packages
# installed with sudo can also leave root-owned files that block deletion.
if [[ -e "$VENV" ]]; then
  echo "Removing existing venv: $VENV"
  if ! rm -rf "$VENV" 2>/dev/null; then
    broken="${VENV}.broken-$(date +%Y%m%d%H%M%S)"
    echo "Could not delete $VENV (root-owned files?) — moving aside to $broken" >&2
    if ! mv "$VENV" "$broken"; then
      echo "Run:  sudo rm -rf \"$VENV\"   then re-run ./setup.sh" >&2
      exit 1
    fi
    echo "You can free the space later with:  sudo rm -rf \"$broken\"" >&2
  fi
fi

python3 -m venv "$VENV"

echo "Upgrading pip"
"$VENV/bin/python" -m pip install --upgrade pip

echo "Installing from requirements.txt"
"$VENV/bin/pip" install -r "$REQ"

echo
echo "Done. Run the dashboard with:"
echo "  ./run-dashboard.sh"
echo "Or activate manually:"
echo "  source \"$VENV/bin/activate\""
echo "  python \"$ROOT/EnergyDashboard2.py\""
