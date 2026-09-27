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
sounds. Choose <b>is seen</b> for no wait, a fixed time from 10 seconds up
to 30 minutes, or <b>custom value</b> to type your own. A built-in alarm
uses that wait. The older phrases, such as “the hold time”, still mean the
figure in Setup &amp; Info.</li>
<li><b>While</b> (orange) — an extra condition that also has to be true, for
example “logging is switched on”. Optional.</li>
<li><b>Outcome</b> (red) — warning or critical, and how you are told:
<b>send SMS</b> or <b>create a desktop alert</b>.</li>
</ul>
<p>
The palette is a short scrolling list for each colour. Drag a block from a
list into a slot of the same colour; a signal will not drop into a comparison
slot. You should see the coloured block follow the pointer. <b>Right-click</b>
a slot to empty it, <b>double-click</b> a block to take it off the rule, or drag
the block down to the bin. Drop a second signal onto a signal that is
already there and both stay, joined by “and”. Click that joining word and it
becomes <b>OR</b>: AND means both signals have to be true at the same time,
OR means either one is enough. Rules are numbered
down the left. The three bars on the left of a rule are its handle: drag
that to change the order, or drag it into the bin to remove the whole rule.
Hovering a rule shows the whole sentence.</p>
<p>
Comparisons are grouped: below and above together, then other level checks,
then phrases about a feed stopping, then ones about something you cannot reach.
The lists also include <b>string A voltage</b>, <b>string B voltage</b>,
<b>PV forecast</b>, <b>PVOutput.org</b>, <b>Wonderwatt</b>, <b>Octopus</b>,
<b>has a differential of</b>, and <b>Volts</b>. Click <b>Volts</b> to set how
many volts that block means. Click <b>Tasmota device</b> and enter that
plug’s IP address. With an address set, that alarm watches only that device.</p>
<p>
Click a block that has a number — a length of time, the hold time, the
low-battery line, the spare-solar minimum, or Volts — and a box opens so you
can change that figure. Where the sentence is one of the built-in alarms, the
alarm uses the new number.</p>
<p>
The line itself is the syntax, in the form
<b>WHEN</b> signal comparison threshold <b>FOR</b> how long
<b>WHILE</b> extra condition <b>THEN</b> outcome.
When that sentence is complete, and the pieces share a unit, the rule gets
a green fill and <b>Syntax Correct</b> on a green background under the
right-hand end. Battery charge is a percentage, spare solar, house load,
PV forecast, Wonderwatt, and PVOutput.org are power in kW, the string
voltages are volts, and Octopus is energy in kWh. Mixing those — or
comparing one of them to a limit in a different unit — turns the line
<b>Syntax incorrect</b>. Hover the rule to see which units clashed.
The block lists fill the space above the rules. Drag the bar between the
lists and the rules to give either side more room. A complete sentence that is
not one of the built-in alarms still does not fire — the hover says so.
The thing that actually raises alarms is still the built-in rule in the code.</p>
<p>
The outcome slot takes two blocks as well: keep the warning or critical
wording and drop <b>send SMS</b> or <b>create a desktop alert</b> beside it.
On a rule that matches a built-in alarm, that is what the alarm then does —
name only the text and it texts you without a pop-up; name only the alert and
it pops up without a text. Say nothing about channels and the tick on
<b>Controls → SMS gateway</b>, plus the desktop tick in Setup &amp; Info,
decide as before. A channel on its own, with no warning or critical
wording, no longer matches a built-in alarm, so it does not fire.</p>
<p>
<b>Add rule</b> gives you an empty line, and <b>Reset</b> puts the built-in
rules back. <b>Alarms page</b> jumps to the live view in Dashboards.</p>
"""
