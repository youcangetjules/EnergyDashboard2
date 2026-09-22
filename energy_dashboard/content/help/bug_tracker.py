"""
Help text for BugTrackerTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "BugTrackerTab"

HELP_TEXT = """\
<h2>Bug Tracker</h2><p>
This page shows the project’s standing defect log — the same
<code>bug_tracker.md</code> file at the root of the PowerModel folder.</p>
<p>
<b>Open</b> bugs are listed first, then <b>Fixed</b>, newest first in each
section. Each entry has a short ID (for example <code>BUG-20260922-01</code>),
what you saw, what was wrong in software, and what changed to fix it when
resolved.</p>
<p>
The tab is read-only. <b>Reload</b> re-reads the file from disk after an
agent or person has edited it. It does not replace the About changelog —
that is the versioned product history; this is the defect history.</p>
"""
