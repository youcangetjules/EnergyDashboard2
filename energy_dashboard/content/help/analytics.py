"""
Help text for AnalyticsTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "AnalyticsTab"

HELP_TEXT = """\
<h2>Battery Simulation</h2><p>
Replays your historical Octopus consumption against a hypothetical battery (capacity, round-trip efficiency, charge / discharge rate, SOC floor) and a tariff to estimate annual savings, payback period and ROI.</p>
<p>
<b>Tweak in Setup &amp; Info:</b> battery capacity (kWh), low-SOC threshold (%), import / export pence, and the assumed install cost. Re-run the simulation after changes.</p>
"""
