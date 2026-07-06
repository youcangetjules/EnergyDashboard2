#!/usr/bin/env bash
# Read KEY=value from repo .env (sourced by install scripts).
# Usage: source "$ROOT/services/read-secrets.sh"
#        val="$(read_repo_env GROWATT_USER)"

read_repo_env() {
  local key="$1" default="${2:-}"
  local env_file="${POWERMODEL_ENV:-${ROOT:-}/.env}"
  local line val
  if [[ -z "${ROOT:-}" || ! -f "$env_file" ]]; then
    printf '%s' "$default"
    return
  fi
  line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$env_file" 2>/dev/null | tail -1 || true)"
  if [[ -z "$line" ]]; then
    printf '%s' "$default"
    return
  fi
  val="${line#*=}"
  val="${val#"${val%%[![:space:]]*}"}"
  val="${val%"${val##*[![:space:]]}"}"
  if [[ "$val" =~ ^\".*\"$ || "$val" =~ ^\'.*\'$ ]]; then
    val="${val:1:-1}"
  fi
  if [[ -n "$val" ]]; then
    printf '%s' "$val"
  else
    printf '%s' "$default"
  fi
}
