"""
Help text for AlarmDefsTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "AlarmDefsTab"

HELP_TEXT = """\
<h2>Alarm defs</h2>
<p>
This page is in <b>Dashboards</b>. Each row is an alarm written as three pieces:
<b>What</b> (blue), <b>Condition</b> (amber), and <b>Outcome</b> (red).
Drag a piece from the top into the matching box. A what will not drop into
a condition box.</p>
<p>
The line under the row is the syntax, in the form
<b>WHEN</b> what <b>IF</b> condition <b>THEN</b> outcome.
If that sentence is one of the built-in rules, it is marked <b>Live rule</b>.
Any other mix is a <b>draft</b> and does not fire. The alarms that actually
raise are still the built-in rules.</p>
<p>
<b>Add rule</b> gives you an empty row. <b>Reset</b> puts the built-in
sentences back. <b>Remove</b> takes one row off the page.</p>
"""
