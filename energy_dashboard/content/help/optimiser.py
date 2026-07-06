"""
Help text for OptimiserTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "OptimiserTab"

HELP_TEXT = """\
<h2>Optimiser</h2><p>
Full 48-slot dynamic-programming optimiser: minimises tomorrow's net energy cost across import, export, battery dispatch and water-heater scheduling, given your forecasts and tariff.</p>
<p>
<b>How to read the charts</b></p>
<ul>
<li>
Top: stacked dispatch bars (charge / discharge / direct PV / load) with SOC overlay.</li>
<li>
Bottom: import &amp; export prices with the chosen action band; x-axis shows six-hour ticks plus fainter 03 / 09 / 15 / 21 labels underneath.</li>
<li>
Crosshair-on-hover reads out values for the slot under your cursor.</li>
</ul>
<p>
Click <b>Explain this</b> on the tab for the methodology details (rigid baseline + heater windows + DP).</p>
<p>
<b>PV forecast scale</b> multiplies the Forecast.Solar curve before the plan runs (1.0 = as published; lower = more conservative).</p>
"""
