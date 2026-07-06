#!/usr/bin/env bash
# Activate the project venv and launch Energy Dashboard.
# Usage: ./run-dashboard.sh
#        VENV=/path/to/other-venv ./run-dashboard.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${VENV:-$ROOT/.venv}"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Virtual env not found at $VENV — run ./setup.sh first." >&2
  exit 1
fi

cd "$ROOT"
# #region agent log
python3 -c "import json,time; open('/home/user/PowerModel/.cursor/debug-426585.log','a').write(json.dumps({'sessionId':'426585','timestamp':int(time.time()*1000),'location':'run-dashboard.sh:17','message':'launcher start','data':{'venv':'$VENV','root':'$ROOT','python':'$VENV/bin/python'},'hypothesisId':'H5','runId':'pre-fix'})+'\n')" 2>/dev/null || true
# #endregion
# shellcheck source=/dev/null
source "$VENV/bin/activate"
exec python "$ROOT/EnergyDashboard2.py" "$@"
