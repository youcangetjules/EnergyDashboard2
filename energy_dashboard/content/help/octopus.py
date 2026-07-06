"""
Help text for OctopusTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "OctopusTab"

HELP_TEXT = """\
<h2>Octopus Energy Data</h2><p>
Half-hourly import &amp; export consumption from the Octopus Energy REST API, aggregated into daily / typical-day / day-of-week views with summary metrics (totals, averages, self-sufficiency, estimated net cost on flat tariffs).</p>
<p>
<b>Tips</b></p>
<ul>
<li>
The 7&nbsp;d / 14&nbsp;d / 30&nbsp;d / 90&nbsp;d toggle controls the fetch window — wider windows take longer due to API pagination.</li>
<li>
Net = Import − Export; large green bars below zero indicate export-dominant days.</li>
<li>
Estimated cost uses the flat import/export pence in Setup &amp; Info; for Agile see the Forecasts and Optimiser tabs.</li>
</ul>
"""
