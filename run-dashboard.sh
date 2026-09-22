#!/usr/bin/env bash
# Activate the project venv and launch Energy Dashboard.
# Creates or rebuilds the venv (via setup.sh) if it is missing or broken
# (e.g. system python3 was upgraded and no longer matches the venv).
# Usage: ./run-dashboard.sh
#        VENV=/path/to/other-venv ./run-dashboard.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${VENV:-$ROOT/.venv}"

_venv_ok() {
  local py="$VENV/bin/python"
  [[ -x "$py" ]] || return 1
  # Must be able to import a required dep from site-packages. A version
  # mismatch (venv built for 3.13, python3 now 3.14) leaves site-packages
  # empty for the active interpreter and fails here.
  "$py" -c "import growattServer" >/dev/null 2>&1
}

_ensure_venv() {
  if _venv_ok; then
    return 0
  fi
  if [[ ! -x "$ROOT/setup.sh" ]]; then
    echo "setup.sh missing or not executable at $ROOT/setup.sh" >&2
    exit 1
  fi
  if [[ -e "$VENV" ]]; then
    echo "Virtual env at $VENV is missing or broken (Python mismatch?) — rebuilding …" >&2
  else
    echo "Virtual env not found at $VENV — running ./setup.sh …" >&2
  fi
  VENV="$VENV" "$ROOT/setup.sh"
  if ! _venv_ok; then
    echo "Virtual env still unusable at $VENV after setup." >&2
    exit 1
  fi
}

_ensure_venv

cd "$ROOT"
# shellcheck source=/dev/null
source "$VENV/bin/activate"

# Qt widgets use software OpenGL unless the user opts into the GPU.
# Do not set LIBGL_ALWAYS_SOFTWARE or Chromium --disable-gpu: those make
# WebEngine print "Failed to query DRM render node" and
# "GPUInfo not initialized on GpuInfoUpdate".
# Hardware GPU: POWERMODEL_WEBENGINE_GPU=1 ./run-dashboard.sh
_web_gpu="$(echo "${POWERMODEL_WEBENGINE_GPU:-}" | tr '[:upper:]' '[:lower:]')"
if [[ "$_web_gpu" != "1" && "$_web_gpu" != "true" && "$_web_gpu" != "yes" && "$_web_gpu" != "on" ]]; then
  export QT_OPENGL="${QT_OPENGL:-software}"
  export QT_XCB_GL_INTEGRATION="${QT_XCB_GL_INTEGRATION:-none}"
  # Drop the old noisy flags if a parent shell still exported them.
  unset LIBGL_ALWAYS_SOFTWARE
  if [[ -n "${QTWEBENGINE_CHROMIUM_FLAGS:-}" ]]; then
    _kept=""
    for _opt in ${QTWEBENGINE_CHROMIUM_FLAGS}; do
      case "$_opt" in
        --disable-gpu|--disable-gpu-compositing|--disable-gpu-sandbox|--in-process-gpu|--disable-dev-shm-usage|--disable-gpu-early-init|--use-gl=disabled|--log-level=3|--disable-features=Vulkan)
          ;;
        *)
          _kept="${_kept} ${_opt}"
          ;;
      esac
    done
    export QTWEBENGINE_CHROMIUM_FLAGS="${_kept# }"
  fi
fi

exec python "$ROOT/EnergyDashboard2.py" "$@"
