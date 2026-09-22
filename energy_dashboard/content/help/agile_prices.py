"""
Help text for AgileSpotPricesTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "AgileSpotPricesTab"

HELP_TEXT = """\
<h2>Agile Spot Prices</h2><p>
Colour-coded grid of Octopus Agile half-hourly slot prices, styled after Octopus Energy's own Agile schedule screen. The default window shows three rows — <b>Yesterday</b> (top), <b>Today</b> (middle), and <b>Tomorrow</b> (bottom, once published — usually mid-afternoon). Toggle <b>Import (household)</b> / <b>Export (outgoing)</b> to switch which price series fills the grids.</p>
<p>
<b>Older</b> / <b>Newer</b> / <b>Today</b> shift that three-day window through stored history (middle row moves one calendar day at a time; you cannot go past today as the middle). Historical days come from the <code>agile_price_snapshots</code> table — written whenever <b>Forecasts</b> (or this tab's <b>Refresh</b>) fetches Agile prices.</p>
<p>
This tab doesn't call the Octopus API itself for live rates — <b>Refresh</b> triggers a Forecasts fetch and the grid redraws once it completes. The current half-hour slot (when visible) is outlined and marked <i>now</i>. Colours follow the legend at the top — from <b>Negative</b> (blue) through to <b>Over 40p</b> (magenta).</p>
<p>
For a year of daily high / low / average and hours below 0p, use the sibling <b>Agile Year</b> tab in Energy Forecasts.</p>
"""
