"""
Help text for OctopusLiveTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "OctopusLiveTab"

HELP_TEXT = """\
<h2>Octopus Live</h2><p>
Polls the Octopus consumption API on a tight cadence to give a near-real-time view of import / export and net at 1-min / 5-min / 30-min granularity. Useful when validating tariff assumptions or watching a particular event (e.g. EV charge session).</p>
<p>
On the top chart, each <b>London calendar day</b> in view is annotated with <b>Total imported</b> (kWh, top-right of that day) and <b>Total exported</b> (kWh, bottom-left); partial days count only intervals visible in the window.</p>
<p>
The <b>bottom chart</b> is the <b>cumulative integral</b> of that interval energy: running totals of import, export, and net (import − export) from the left edge of the view — not another per-interval snapshot.</p>
"""
