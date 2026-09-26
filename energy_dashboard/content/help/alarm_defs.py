"""
Help text for AlarmDefsTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "AlarmDefsTab"

HELP_TEXT = """\
<h2>Alarm defs</h2>
<p>
This page is in <b>Controls</b>. It lists every alarm the dashboard can raise:
the name, how serious it is, how long the condition has to last, and what it
means in the house.</p>
<p>
The line at the top is the thresholds saved in <b>Setup &amp; Info → Live alarms</b>
(on or off, hold time, spare-solar minimum, and the low-battery percentage).
Reload reads those again. The list itself is the built-in rule set — it is not
a place to add a new alarm.</p>
<p>
The <b>Alarms</b> button and the tray menu show what is firing right now.
This page is the definition of those rules.</p>
"""
