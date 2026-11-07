"""
Help text for Tasmota24hProfileTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "Tasmota24hProfileTab"

HELP_TEXT = """\
<h2>Tasmota 24 hr Profile</h2>
<p>Shows what a normal day looks like for a single Tasmota device. Pick a device and an aggregation window (default 7 days, up to 90) and press <b>Load profile</b>.</p>
<p>The chart plots the mean power in watts across 15-minute time-of-day bins, with a P10\u2013P90 shaded envelope behind it. X-axis is 00:00\u201323:59; Y-axis is watts.</p>
<p><b>Outlier detection:</b> any historical day where the actual power exceeds or falls below the P10\u2013P90 envelope for more than one continuous hour is flagged as an outlier. Those days appear in the list below the chart and are drawn on the chart in red.</p>
<p>Data comes from the <code>tasmota_readings</code> table in the logging database.</p>
"""
