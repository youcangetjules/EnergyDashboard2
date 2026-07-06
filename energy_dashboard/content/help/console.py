"""
Help text for ConsoleTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "ConsoleTab"

HELP_TEXT = """\
<h2>Console</h2><p>
Tailing log of every <code>_log.info()</code> / <code>_log.warn()</code> / <code>_log.err()</code> call across the app. Persists across restarts via a JSONL file (auto-trimmed). <b>Clear</b> wipes both the in-memory ring and the on-disk file.</p>
"""
