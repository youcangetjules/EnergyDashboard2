"""
Help text for PotIssuesTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "PotIssuesTab"

HELP_TEXT = """\
<h2>Potential Issues</h2>
<p>
This page is in the <b>Physical Plant</b> group. It compares <b>Growatt actual PV</b> (and load usage when available) against this
dashboard’s <b>solar forecast</b> and an optional <b>Wonderwatt</b> forecast for
the same local calendar days (from your Setup / banner locale). Values are
measured or labelled estimates — nothing is rescaled to “look right.”</p>
<p><b>Learning vs Lock</b></p>
<ul>
<li>While unlocked the tab is in <b>Learning</b> mode: comparisons are shown but
no day is flagged as a potential issue.</li>
<li><b>Lock</b> records your judgment that forecasts and generation (and usage)
look aligned <i>as of now</i>. After lock, days that miss a simple threshold
(|actual − our forecast| above ~20% or 1.5 kWh) appear as potential issues.</li>
<li><b>Unlock</b> clears the baseline and returns to learning.</li>
</ul>
<p><b>Wonderwatt</b></p>
<ul>
<li>Paste the share link from Wonderwatt Advanced
(<code>?wattid=…&amp;sig=…&amp;time=…</code>). It is stored only in local
QSettings — treat it as a credential and rotate it if it was exposed.</li>
<li>Wonderwatt’s app is Blazor Server (no public JSON forecast API).
<b>Test connection</b> checks that the share cookies are accepted.
Daily WW kWh can be pasted until a live curve fetch is available.</li>
</ul>
<p><b>Data sources</b></p>
<ul>
<li>Our forecast: live Forecasts curve or <code>solar_forecast_snapshots</code>.</li>
<li>Actual PV / usage: trapezoid integrate of Growatt <code>pv_power_kw</code> /
<code>load_power_kw</code> from the database.</li>
</ul>
"""
