"""
Help text for DeviceImportCostsTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "DeviceImportCostsTab"

HELP_TEXT = """\
<h2>Daily Import Costs</h2><p>
Breaks down each day's grid import into the part attributable to your monitored Tasmota devices versus the residual house load, and values both at the configured flat tariff. Useful for spotting which appliance is actually driving the bill.</p>
<p>
<b>Note:</b> the chart only fills once both Octopus consumption and Tasmota historical readings are present; the tab title goes green only after a successful render.</p>
"""
