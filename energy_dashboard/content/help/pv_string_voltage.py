"""
Help text for PvStringVoltageTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "PvStringVoltageTab"

HELP_TEXT = """\
<h2>String voltage</h2><p>
This page is in <b>Physical Plant Tools</b>, next to PV String Charge.
It shows the measured DC volts on each string — Growatt’s MPPT inputs
<b>vPv1</b> and <b>vPv2</b>. These are the volts the inverter reports.
They are not a panel datasheet, and they are not estimated from power.</p>
<p>
<b>Today</b> is one London day, midnight to midnight. <b>Rolling 24Hr</b>
is the last 22 hours plus two empty hours after now, so the teal now line
sits where 22:00 sits on the day chart. Today is the default.</p>
<p>
<b>Day</b> opens a calendar for a London day, and it can always reach
today. The <b>Today</b> button returns the menu to the current day. On
today, and on the rolling window, the big figures are the live volts and
the chart includes that reading. The latest volts for each string are
written just beside the teal now line. On an earlier day the big figure
is the average of the stored lots, with the low and high beside it. That
line is hidden then.</p>
<p>
Samples are 2-minute lots in <code>pv_string_voltage</code>. A lot is
written while the dashboard is open and Growatt Live Status has a reading.
Days before that logging started are empty. A missing string is left blank.
It is not stored as 0 V. On PostgreSQL the table has to be created by the
Setup script, run as the database owner.</p>
"""
