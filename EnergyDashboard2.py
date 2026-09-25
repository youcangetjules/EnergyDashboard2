
import os
import sys
from pathlib import Path

# If not already running inside a project venv, re-exec with it (growattServer, PySide6, etc.).
_REPO_DIR = Path(__file__).resolve().parent
_VENV_PYTHONS = (
    _REPO_DIR / "octopus-ui" / "bin" / "python",
    _REPO_DIR / "venv" / "bin" / "python",
    _REPO_DIR / ".venv" / "bin" / "python",
    _REPO_DIR / "pyside6" / "bin" / "python",
)
_VENV_PYTHON = next((p for p in _VENV_PYTHONS if p.is_file()), None)
if _VENV_PYTHON is not None and Path(sys.executable).resolve() != _VENV_PYTHON.resolve():
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])

# Arm the crash log before importing the package. That import loads Qt, and a
# segmentation fault never reaches the Console logger.
import importlib.util

_crash_spec = importlib.util.spec_from_file_location(
    "_powermodel_crash_log_early",
    _REPO_DIR / "energy_dashboard" / "core" / "crash_log.py",
)
if _crash_spec is not None and _crash_spec.loader is not None:
    _crash_mod = importlib.util.module_from_spec(_crash_spec)
    _crash_spec.loader.exec_module(_crash_mod)
    _crash_mod.install_crash_logger()

# Load .env before config/tabs read credentials.
import energy_dashboard.secrets as _secrets

_secrets.load_secrets()

# Qt env (PySide6 backend, Linux a11y log noise) before any Qt import.
import energy_dashboard.qt_env  # noqa: F401

from energy_dashboard.__main__ import main

if __name__ == "__main__":
    main()
