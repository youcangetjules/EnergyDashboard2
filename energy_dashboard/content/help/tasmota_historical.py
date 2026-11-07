"""
Help text for TasmotaHistoricalTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "TasmotaHistoricalTab"

HELP_TEXT = """\
<h2>Tasmota Historical Profile</h2>
<p>Shows cumulative and daily energy consumed by each Tasmota device over time.</p>
<p><b>Cumulative kWh</b> (default) draws one line per device, X = date, Y = running total of kWh since the first reading in the selected window.</p>
<p><b>Daily kWh bars</b> shows a grouped bar chart: one bar per device per day, computed by trapezoidal integration of the power readings.</p>
<p>Use the <b>date range</b> selector to choose 7, 30, 90 days or all available data. Device checkboxes let you show or hide individual devices.</p>
<p>The summary table below the chart shows: device name, total kWh, average daily kWh, and first/last seen dates.</p>
<p>Data comes from the <code>tasmota_readings</code> table in the logging database.</p>
"""
