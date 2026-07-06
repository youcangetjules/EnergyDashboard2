"""
Energy Dashboard — per-tab Help content.

Each module in this package exports:

- ``TAB_CLASS`` — the tab widget class name (e.g. ``"GrowattTab"``)
- ``HELP_TEXT`` — HTML shown by the global status-bar Help button

Adding help for a new tab: create ``content/help/<tab_slug>.py`` with those
two constants; it is picked up automatically on import — no registry edit.

``HelpDialog`` reads ``_HELP_TEXTS`` / ``_HELP_DEFAULT`` (re-exported here
for backward compatibility with ``from energy_dashboard.common import *``).
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from energy_dashboard.content.help._default import HELP_TEXT as _HELP_DEFAULT


def _discover_help_modules() -> dict[str, str]:
    """Build {TabClassName: html} from every submodule exporting TAB_CLASS."""
    registry: dict[str, str] = {}
    pkg_name = __name__
    pkg_path = Path(__file__).parent
    for mod_info in pkgutil.iter_modules([str(pkg_path)]):
        if mod_info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{pkg_name}.{mod_info.name}")
        cls = getattr(mod, "TAB_CLASS", None)
        text = getattr(mod, "HELP_TEXT", None)
        if not cls or not text:
            continue
        if cls in registry:
            raise RuntimeError(
                f"Duplicate help TAB_CLASS {cls!r} in {mod_info.name}")
        registry[str(cls)] = str(text)
    return registry


_HELP_TEXTS: dict[str, str] = _discover_help_modules()


def help_text_for(tab_class_name: str) -> str:
    """Return HTML help for ``tab_class_name``, or the default fallback."""
    return _HELP_TEXTS.get(tab_class_name, _HELP_DEFAULT)


__all__ = ["_HELP_DEFAULT", "_HELP_TEXTS", "help_text_for"]
