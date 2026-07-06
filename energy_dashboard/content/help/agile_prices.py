"""
Help text for AgileSpotPricesTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "AgileSpotPricesTab"

HELP_TEXT = """\
<h2>Agile Spot Prices</h2><p>
Colour-coded grid of Octopus Agile half-hourly slot prices, styled after Octopus Energy's own Agile schedule screen. <b>Today</b> and <b>Tomorrow</b> (once published — usually mid-afternoon) are shown stacked, Today above Tomorrow. Toggle <b>Import (household)</b> / <b>Export (outgoing)</b> to switch which price series fills both grids.</p>
<p>
This tab doesn't call the Octopus API itself — it reuses the same Agile data the <b>Forecasts</b> tab already fetches, so <b>Refresh</b> here simply triggers a Forecasts fetch and the grid redraws once it completes.</p>
<p>
The current half-hour slot (when visible) is outlined and marked <i>now</i>. Colours follow the legend at the top of the tab — from <b>Negative</b> (blue) through to <b>Over 40p</b> (magenta).</p>
"""
