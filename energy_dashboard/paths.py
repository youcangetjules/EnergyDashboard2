"""Filesystem paths for repo-root assets (venv, _ui_assets, etc.)."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_ASSETS_DIR = REPO_ROOT / "_ui_assets"
ASSETS_DIR = REPO_ROOT / "assets"

__all__ = [n for n in globals() if not n.startswith("__")]
