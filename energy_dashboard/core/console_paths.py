"""
Energy Dashboard — `core/console_paths.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from pathlib import Path
# Console log persistence: keep a rolling on-disk JSONL file so debug context
# from previous runs is still visible after a restart. Each entry is one JSON
# object per line; we cap how many are restored into the in-memory ring buffer
# and trim the file itself only when it grows past `_TRIM_AT` lines.
_CONSOLE_LOG_PATH = Path.home() / ".energy_dashboard_console.jsonl"
_CONSOLE_LOG_MAX_ENTRIES = 5000
_CONSOLE_LOG_FILE_TRIM_AT = 50000


__all__ = [n for n in globals() if not n.startswith('__')]
