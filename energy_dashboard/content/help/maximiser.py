"""
Help text for MaximiserTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "MaximiserTab"

HELP_TEXT = """\
<h2>Maximiser</h2><p>
Uses <b>yesterday’s</b> logged Growatt half-hours (load + PV) and <b>Agile</b> standard unit rates to show simple <i>lower-bound</i> spend scenarios: export allowed vs export forbidden (surplus wasted), plus a greedy “cheapest overnight slots” estimate for energy needed before PV ramps up.</p>
<p>
For full optimal dispatch use <b>Battery Simulation</b> or <b>Optimiser</b>; perfect hindsight scheduling is harder than these retrospective bounds.</p>
<p>
The tab chart plots heuristic <b>battery SOC %</b> (export allowed vs surplus not exported) and <b>cumulative net £</b> for the two <i>no-battery</i> scenarios — stepped at <b>10-minute</b> marks within each half-hour.</p>
<p>
The textual summary is shown in <b>three columns</b> so more vertical space remains for the charts.</p>
"""
