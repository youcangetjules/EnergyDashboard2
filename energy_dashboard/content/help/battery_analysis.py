"""
Help text for BatteryAnalysisTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "BatteryAnalysisTab"

HELP_TEXT = """\
<h2>Battery Analysis</h2><p>
Reads SOC and battery power over the last N days from the Growatt cloud and visualises charge/discharge patterns alongside PV.</p>
<p>
On the Power Flows chart, each <b>London calendar day</b> in view is annotated with <b>Tot kWh consumed</b> (house load from <code>sysOut</code>), <b>Tot kWh imported</b>, and <b>Tot kWh generated</b> (PV) for yesterday.</p>
<p>
<b>Use it for:</b> validating the simulator's assumptions, spotting calendar-aging or capacity-fade trends.</p>
"""
