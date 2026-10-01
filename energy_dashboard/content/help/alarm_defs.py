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
charge, spare solar, or the Grott feed. On the right of each signal, in
dark grey, is its <b>alarm type</b>: Hardware (the inverter, a plug, a string voltage),
Data flow (the Grott and Tasmota MQTT feeds), Data ingestion (the logging
database), Energy (battery, spare solar, house load), Forecast, or
External service (PVOutput.org, Octopus).</li>
<li><b>Comparison</b> (green) — what it does: stays below, is at least, drops,
goes silent.</li>
<li><b>Threshold</b> (amber) — what it is compared against, such as the
low-battery line or the spare-solar minimum. Some alarms have nothing to
compare against, so this box can stay empty.</li>
<li><b>Duration</b> (purple) — how long it must hold before the alarm
sounds. Choose <b>is seen</b> for no wait, a fixed time from 10 seconds up
to 30 minutes, or <b>custom value</b> to type your own. <b>Is flapping</b>
is for a line that is crossed over and over rather than staying true. Dropping
it opens a box: Seen how many times in how many minutes, where the trigger
threshold is exceeded for how many seconds. On a built-in alarm that count
replaces the plain wait. The alarm sounds once it has been crossed that often
inside the window, and it clears once those crossings fall outside the window.
The older phrases, such as “the hold time”, still mean the figure in Setup
&amp; Info.</li>
<li><b>Additional Conditions</b> (orange) — an extra condition that also
has to be true, for example “logging is switched on”, “it is daytime”, “the
battery is charging”, “the grid is importing”, or “Agile is in a cheap slot”.
Optional. A condition only makes sense against some signals: “MQTT is still
up” says something about a feed or a plug, nothing about a string voltage. Put
a condition on a signal it has no bearing on and the rule still reads as a
sentence, so the chip says <b>Syntax Correct/Non-Standard Logic - please
check</b> on amber instead of plain green. Hover the chip to see why.</li>
<li><b>Alarm</b> (red) — the grade, and how you are told. The grades are
<b>Critical</b>, <b>Critical because Lesser Alarm repeating</b> (a major,
minor, or warning alarm that has kept coming back), <b>Major</b>,
<b>Minor</b>, and <b>Warning</b>. Beside the grade you can drop
<b>Send SMS</b> or <b>Create Desktop Alert</b>.</li>
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
<b>Edit</b>, on each column, is where you add your own blocks. A signal needs a
name, an alarm type, and either a logging table and field or an address and
port. A comparison needs words and what they mean: below a limit, above a
limit, at least a limit, or an address that cannot be reached. A threshold
needs a unit and a number. A duration is another length of time. An additional
condition watches one signal. An alarm grade uses your words and still counts
as critical, major, minor, or a warning. The blocks already in the lists stay.
Click a threshold you added, once it is on a rule, to change its number.</p>
<p>
Comparisons are grouped: below and above together, then other level checks,
then phrases about a feed stopping, then ones about something you cannot reach.
The lists also include <b>string A voltage</b>, <b>string B voltage</b>,
<b>PV forecast</b>, <b>PVOutput.org</b>, <b>Wonderwatt</b>, <b>Octopus</b>,
<b>has a differential of</b>, and <b>Volts</b>. Click <b>Volts</b> to set how
many volts that block means. Click <b>Tasmota device</b> and enter that
plug’s IP address. With an address set, that alarm watches only that device.
Right-click a signal in the <b>signal list</b> and choose <b>Define</b> to pick
the logging <b>table</b> and <b>field</b> that hold it. <b>Delete</b> on that
menu clears the choice. A signal already on a rule does not open this box.
String volts are on <b>pv_string_voltage</b>:
<b>v_string1</b> is string A, <b>v_string2</b> is string B. The alarm reads
the latest number in that field. The chip shows the table and field once
they are set.</p>
<p>
Click a block that has a number — a length of time, the hold time, the
low-battery line, the spare-solar minimum, Volts, or an Is flapping sentence —
and a box opens so you can change that figure. Where the sentence is one of
the built-in alarms, the alarm uses the new number.</p>
<p>
The line itself is the syntax, in the form
<b>WHEN</b> signal comparison threshold <b>FOR</b> how long
<b>WITH</b> additional condition <b>THEN</b> alarm.
When that sentence is complete, and the pieces share a unit, the rule gets
a green fill and <b>Syntax Correct</b> on a green background under the
right-hand end. Battery charge is a percentage, spare solar, house load,
PV forecast, Wonderwatt, and PVOutput.org are power in kW, the string
voltages are volts, and Octopus is energy in kWh. Mixing those — or
comparing one of them to a limit in a different unit — turns the line
<b>Syntax incorrect</b>. Hover the rule to see which units clashed.
The block lists fill the space above the rules. Drag the bar between the
lists and the rules to give either side more room. A complete sentence that is
not one of the built-in alarms is watched the same way, once you press
<b>Commit</b> and each measured signal has a table and field. Hover the rule
if a signal still needs a column.</p>
<p>
<b>Inspect</b>, on the right of each rule, opens the parts of that rule and
marks each one <b>Triggering</b> or <b>Not triggering</b> from the last live
check. Duration is triggering only once the wait, or the flapping count, has
been met. The last line says whether the alarm is sounding. If a signal has
no table and field yet, that line says so, and the rule does not fire.</p>
<p>
Adds, edits, and removals stay on the page until you press <b>Commit</b>.
Until then the alarms that are actually running are unchanged. A rule you
added or edited has an amber outline. <b>Commit</b> flashes while anything
is waiting. <b>Cancel</b>, at the right-hand edge, puts every rule back.
The <b>Rubbish Bin</b> is on the left: drop a block or a whole rule there.
That too waits for Commit.</p>
<p>
The alarm slot takes two blocks as well: keep the grade and drop
<b>Send SMS</b> or <b>Create Desktop Alert</b> beside it.
On a rule that matches a built-in alarm, that is what the alarm then does —
name only the text and it texts you without a pop-up; name only the alert and
it pops up without a text. Say nothing about channels and the tick on
<b>Controls → SMS gateway</b>, plus the desktop tick in Setup &amp; Info,
decide as before. A channel on its own, with no grade, is a warning, and
only that channel is used. A built-in alarm still decides its own grade
in the monitor (for example critical when the pack is very low). The grade
on the line is the one used for a rule you wrote yourself.</p>
<p>
<b>Add rule</b> gives you an empty line, and <b>Reset</b> puts the built-in
rules back. <b>Alarms page</b> jumps to the live view in Dashboards.</p>
"""
