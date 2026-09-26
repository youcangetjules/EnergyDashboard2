"""
Help text for AlarmDefsTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "AlarmDefsTab"

HELP_TEXT = """\
<h2>Alarm defs</h2>
<p>
This page is in <b>Controls</b>, next to the Bug Tracker. It is where alarms
are <i>described</i>; what is actually sounding is on the <b>Alarms</b> page in
Dashboards.</p>
<p>
Every alarm is built from its smallest pieces, one colour each:</p>
<ul>
<li><b>Signal</b> (blue) — the thing being watched, such as battery state of
charge, spare solar, or the Grott feed.</li>
<li><b>Comparison</b> (green) — what it does: stays below, is at least, drops,
goes silent.</li>
<li><b>Threshold</b> (amber) — what it is compared against, such as the
low-battery line or the spare-solar minimum. Some alarms have nothing to
compare against, so this box can stay empty.</li>
<li><b>For how long</b> (purple) — how long it must hold before the alarm
sounds. “The hold time” is the figure in Setup &amp; Info.</li>
<li><b>While</b> (orange) — an extra condition that also has to be true, for
example “logging is switched on”. Optional.</li>
<li><b>Outcome</b> (red) — warning or critical.</li>
</ul>
<p>
The palette is a short scrolling list for each colour. Drag a block from a
list into a slot of the same colour on a rule line; a signal will not drop
into a comparison slot. <b>Right-click</b> a slot to empty it. Each rule is
a single line, and hovering it shows the whole sentence.</p>
<p>
The line itself is the syntax, in the form
<b>WHEN</b> signal comparison threshold <b>FOR</b> how long
<b>WHILE</b> extra condition <b>THEN</b> outcome.
If that whole sentence matches a built-in alarm, the end of the line says
<b>Live</b>. Any other mix says <b>Draft</b> and does not fire — change
one block of a live rule and it becomes a draft, because the thing that
actually raises alarms is still the built-in rule in the code.</p>
<p>
<b>Add rule</b> gives you an empty line, <b>Reset</b> puts the built-in rules
back, and the <b>×</b> at the end of a line takes it off the page.
<b>Alarms page</b> jumps to the live view in Dashboards.</p>
"""
