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
list into a slot of the same colour; a signal will not drop into a comparison
slot. You should see the coloured block follow the pointer. <b>Right-click</b>
a slot to empty it, or drag the block down to the bin. Rules are numbered
down the left. The three bars on the left of a rule are its handle: drag
that to change the order, or drag it into the bin to remove the whole rule.
Hovering a rule shows the whole sentence.</p>
<p>
Click a block that has a number — a length of time, the hold time, the
low-battery line, or the spare-solar minimum — and a box opens so you can
change that figure. The alarm uses the new number. The sentence stays one
of the built-in alarms, so it still fires.</p>
<p>
The line itself is the syntax, in the form
<b>WHEN</b> signal comparison threshold <b>FOR</b> how long
<b>WHILE</b> extra condition <b>THEN</b> outcome.
When that sentence is complete the rule gets a green fill and
<b>Syntax Correct</b> on a green background under the right-hand end.
The block lists fill the space above the rules. Drag the bar between the
lists and the rules to give either side more room. A complete sentence that is
not one of the built-in alarms still does not fire — the hover says so.
The thing that actually raises alarms is still the built-in rule in the code.</p>
<p>
<b>Add rule</b> gives you an empty line, and <b>Reset</b> puts the built-in
rules back. <b>Alarms page</b> jumps to the live view in Dashboards.</p>
"""
