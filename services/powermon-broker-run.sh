#!/usr/bin/env bash
# Launch powermon_broker.py with a project venv (system python lacks psycopg2).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${POWERMON_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  for candidate in \
    "$ROOT/.venv/bin/python" \
    "$ROOT/venv/bin/python" \
    "$ROOT/octopus-ui/bin/python" \
    "$ROOT/pyside6/bin/python"; do
    if [[ -x "$candidate" ]]; then
      PYTHON="$candidate"
      break
    fi
  done
fi
if [[ -z "$PYTHON" || ! -x "$PYTHON" ]]; then
  echo "powermon-broker-run: no venv python found under $ROOT" >&2
  echo "Run ./setup.sh or set POWERMON_PYTHON in /etc/default/powermon-broker" >&2
  exit 127
fi
exec "$PYTHON" "$ROOT/services/energy_collector.py" "$@"
