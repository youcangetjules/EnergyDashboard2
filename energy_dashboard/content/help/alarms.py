"""
Help text for AlarmsTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "AlarmsTab"

HELP_TEXT = """\
<h2>Alarms</h2>
<p>
This page is in <b>Dashboards</b> and answers one question: is anything wrong
right now? The <b>Alarms</b> button on the bottom bar, the red banner at the
top of the window, and <b>Alarms</b> in the system-tray menu all open it.</p>
<p>
<b>Sounding now</b> lists every alarm that is currently raised, worst first.
Each card gives the plain-English reason, and how long the condition has been
true. A red edge is critical, amber is a warning.</p>
<p>
<b>Since the app started</b> is the history for this session only. It records
the moment each alarm was first raised, so you can see that (say) the Grott
feed dropped at 14:05 even though it has since recovered. Closing the app
clears it; the window has no long-term alarm log.</p>
<p>
An alarm does not fire the instant a reading looks bad. Most conditions have
to hold for the <b>hold time</b> in Setup &amp; Info (10 minutes by default),
which is what stops a passing cloud or a one-second network blip from raising
anything. Feed and database faults are faster, in the region of 20 to 90
seconds, because those are never normal.</p>
<p>
The figures shown are the ones the inverter, Grott, the database, and the
Tasmota monitors actually reported. Nothing on this page is smoothed or
estimated.</p>
<p>
To read the rules themselves &mdash; what each alarm watches and what it
raises &mdash; open <b>Alarm defs</b> in Controls. Thresholds (low-battery
level, spare-solar minimum, hold time, desktop pop-ups on or off) are in
<b>Setup &amp; Info</b>.</p>
"""
