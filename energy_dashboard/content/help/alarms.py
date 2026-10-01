"""
Help text for AlarmsTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "AlarmsTab"

HELP_TEXT = """\
<h2>Alarms</h2>
<p>
This page is in <b>Dashboards</b> and answers one question: is anything wrong
right now? The red <b>Alarms (n)</b> tab and the matching button on the bottom
bar show how many are sounding, with a space before the number. The red banner
at the top of the window, and <b>Alarms</b> in the system-tray menu, open this
page too. The tray menu opens with three rows: <b>Critical Alarms</b> on red,
<b>Major Alarms</b> on amber, and <b>Minor Alarms</b> on yellow. The number is
how many of that grade are sounding. Critical is a feed that has died, the
inverter offline, or the pack very low. Major still needs a look. Minor is
the house using almost all the solar, which is not a fault. Warning is its
own grade on this page, in blue.</p>
<p>
Each alarm is one row. The columns are <b>Rank</b>, <b>State</b>, <b>Time</b>,
<b>For</b>, <b>Alarm</b>, and <b>Detail</b>. Rank colours are critical red,
major amber, minor yellow, and warning blue. Unacknowledged alarms are listed
first.</p>
<p>
<b>Acknowledge</b> means you have seen it. The alarm stays on the list while
the condition is still true, and it stops repeating on the desktop and by
text. A new occurrence, after it has cleared, asks to be acknowledged again.</p>
<p>
<b>Suppress</b> shelves that alarm. It leaves the sounding list, it does not
notify, and it stays shelved — even after it clears and comes back — until
you press <b>Unsuppress</b>. Shelves are remembered after a restart.
<b>Suppressed</b> shows what is on the shelf, including an alarm that is not
sounding right now.</p>
<p>
<b>History</b> is this session: raised, acknowledged, suppressed, unsuppressed,
and cleared, newest first. Closing the app clears that log. The shelf list
is the part that is kept.</p>
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
