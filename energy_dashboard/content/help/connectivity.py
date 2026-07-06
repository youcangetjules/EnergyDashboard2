"""
Help text for ConnectivityStatusTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "ConnectivityStatusTab"

HELP_TEXT = """\
<h2>Connectivity Status</h2><p>
At-a-glance health of every external dependency: Octopus Energy API, Growatt API, the <b>Forecast.solar</b> PV curve (same fetch as the Forecasts tab), Tasmota IPs, and each configured database backend.</p>
<p>
The <b>Inverter write (this app)</b> row says whether this dashboard can push MIX schedules (Optimiser / AC charge / discharge windows): only via the <b>Growatt cloud</b> session when the Live tab is connected. The optional local Modbus line is a <b>read</b> health check — PowerModel does not send schedule writes over Modbus.</p>
<p>
Column widths are remembered across restarts (including if you close the app soon after resizing). The <b>Table size</b> column shows logged row counts and PostgreSQL relation sizes where available; the <b>Databases</b> row shows total size per enabled backend.</p>
<p>
Between the connectivity table and the text summary, an <b>animated diagram</b> shows external APIs, LAN devices, this dashboard (&quot;house&quot;), databases, and export — colours track connectivity states. Drag the horizontal <b>splitter</b> between the table and the diagram to resize the two panes.</p>
<p>
Click <b>Databases</b> or <b>Exported data</b> in the diagram for a detail window with live status <i>and</i> per-table <b>ring buffer</b> limits: max rows, max age (days), and max table size (MB). Oldest rows are removed first. Use <b>Prune now</b> to apply immediately; policies are saved in QSettings.</p>
"""
