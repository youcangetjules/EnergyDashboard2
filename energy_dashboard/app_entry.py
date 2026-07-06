"""
Energy Dashboard — `app_entry.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
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
