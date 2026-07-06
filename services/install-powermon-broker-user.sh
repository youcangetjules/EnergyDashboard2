#!/usr/bin/env bash
# Install energy collector as a user systemd service (no root).
# Usage: ./services/install-powermon-broker-user.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
ENV_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/energy-collector.env"
CONF="$HOME/.config/PowerModel/EnergyDashboard2.conf"
# shellcheck source=read-secrets.sh
source "$ROOT/services/read-secrets.sh"

read_ini() {
  local section="$1" key="$2" default="${3:-}"
  local val=""
  if [[ -f "$CONF" ]]; then
    val="$(awk -F= -v sec="[$section]" -v k="$key" '
      $0 == sec { in_sec=1; next }
      /^\[/ { in_sec=0 }
      in_sec && $1 == k { gsub(/^[^=]*=/, ""); print; exit }
    ' "$CONF")"
  fi
  if [[ -n "$val" ]]; then
    printf '%s' "$val"
  else
    printf '%s' "$default"
  fi
}

PG_HOST="$(read_ini db pg_host "$(read_repo_env PG_HOST localhost)")"
PG_PORT="$(read_ini db pg_port "$(read_repo_env PG_PORT 5432)")"
PG_DB="$(read_ini db pg_db "$(read_repo_env PG_DB powermon)")"
PG_USER="$(read_ini db pg_user "$(read_repo_env PG_USER "")")"
PG_PASS="$(read_ini db pg_pass "$(read_repo_env PG_PASSWORD "")")"
GROWATT_USER="$(read_repo_env GROWATT_USER "")"
GROWATT_PASS="$(read_repo_env GROWATT_PASSWORD "")"
GROWATT_TOKEN="$(read_repo_env GROWATT_API_TOKEN "")"

chmod +x "$ROOT/services/energy-collector-run.sh"

mkdir -p "$UNIT_DIR"
cat >"$ENV_FILE" <<EOF
POWERMON_PG_HOST=${PG_HOST}
POWERMON_PG_PORT=${PG_PORT}
POWERMON_PG_DB=${PG_DB}
POWERMON_PG_USER=${PG_USER}
POWERMON_PG_PASSWORD=${PG_PASS}
POWERMON_TASMOTA_IPS=222.20.20.211
POWERMON_TASMOTA_INTERVAL=30
POWERMON_GROWATT_INTERVAL=60
POWERMON_LOOP_INTERVAL=5
POWERMON_LISTEN=127.0.0.1:8765
POWERMON_GROWATT_USER=${GROWATT_USER}
POWERMON_GROWATT_PASSWORD=${GROWATT_PASS}
POWERMON_GROWATT_TOKEN=${GROWATT_TOKEN}
EOF
chmod 600 "$ENV_FILE"

cat >"$UNIT_DIR/energy-collector.service" <<EOF
[Unit]
Description=PowerModel energy collector (Tasmota + Growatt → PostgreSQL)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${ROOT}
EnvironmentFile=${ENV_FILE}
ExecStart=${ROOT}/services/energy-collector-run.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user disable powermon-broker.service 2>/dev/null || true
systemctl --user stop powermon-broker.service 2>/dev/null || true
systemctl --user enable energy-collector.service
systemctl --user restart energy-collector.service

echo
systemctl --user --no-pager status energy-collector.service || true
echo "For 24/7 without login: sudo loginctl enable-linger $(whoami)"
echo "For boot without login (recommended): sudo ./services/install-energy-collector.sh"
