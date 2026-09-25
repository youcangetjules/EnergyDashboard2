"""
Help text for DumpLogsTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "DumpLogsTab"

HELP_TEXT = """\
<h2>Dump logs</h2><p>
This page is in <b>Controls</b>. It shows
<code>~/.energy_dashboard_crash.log</code> — the record of fatal crashes
such as a segmentation fault. The Console tab cannot see those, because
the process is already dead when they happen.</p>
<p>
Each session starts with a header (pid and time). A crash adds the Python
stacks from every thread, and, when the system kept a core dump, a short
copy of that dump: pid, signal, time, and the crashing thread’s stack.
A clean exit is marked too. Newest text is at the bottom. A very long file
shows only the newest part.</p>
<p>
<b>Reload</b> re-reads the file. <b>Look for new dumps</b> asks the system
for dashboard core dumps that are not in the file yet. Neither button
deletes the log.</p>
"""
