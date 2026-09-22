"""
Help text for OctopusTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "OctopusTab"

HELP_TEXT = """\
<h2>Octopus Energy Data</h2><p>
Half-hourly import and export from the Octopus REST API (your MPANs — the meter point numbers on the bill). The API key box starts as the key saved on Octopus Live, which is the login Octopus has accepted. The Summary cards and the Daily Import / Export tab use those meter readings. Estimated net cost uses Octopus Agile half-hourly rates when they load for the window; otherwise the flat pence in Setup &amp; Info.</p>
<p>
The Daily tab is four panels. Top row is each calendar day: import/export in kWh, and net charge in pounds. Bottom row rolls the same numbers into <b>Monday–Sunday weeks</b> so you can see the trend per week for both power and cost. A dashed yellow line is the linear slope (kWh/week and £/week). Weeks at the ends of the date range that do not have six days yet are paler and marked * — those totals are not scaled up to a full week.</p>
<p>
<b>Tips</b></p>
<ul>
<li>
The 7&nbsp;d / 14&nbsp;d / 30&nbsp;d / 90&nbsp;d toggle is the fetch window. 90 days gives more weeks on the trend; 7 days is usually only one partial week.</li>
<li>
Net = Import − Export. Green bars below zero are export-heavy days (or weeks).</li>
<li>
Typical Day Profile and Day of Week average the half-hours in this window — they are not a second data source.</li>
</ul>
"""
