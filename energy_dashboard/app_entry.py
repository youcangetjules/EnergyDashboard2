"""
Energy Dashboard — `app_entry.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
def dashboard_restart_argv() -> list[str]:
    """Command line that starts this same dashboard again.

    ``python -m energy_dashboard`` is restarted as a module. A script
    launch, including ``EnergyDashboard2.py``, is restarted with the same
    arguments.
    """
    import sys

    exe = sys.executable
    script = str(sys.argv[0] if sys.argv else "")
    rest = list(sys.argv[1:])
    norm = script.replace("\\", "/")
    if norm.endswith("/energy_dashboard/__main__.py"):
        return [exe, "-m", "energy_dashboard", *rest]
    return [exe, *sys.argv]


def _flush_qsettings_on_quit():
    """Belt-and-braces: ensure every QSettings change still pending in the
    in-memory buffer is flushed to disk when the app exits, even if a code
    path forgot to call ``s.sync()`` after ``setValue``. Without this, edits
    made through Setup & Info or any other tab can be lost on crash / kill."""
    try:
        QSettings("PowerModel", "EnergyDashboard2").sync()
    except Exception:
        pass


__all__ = [n for n in globals() if not n.startswith('__')]
