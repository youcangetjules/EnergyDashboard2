"""
Help text for ConnectivityStatusTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "ConnectivityStatusTab"

HELP_TEXT = """\
<h2>Connectivity Status</h2><p>
At-a-glance health of every external dependency: Octopus Energy API, Growatt API, the <b>Forecast.solar</b> PV curve (same fetch as the Forecasts tab), Tasmota IPs, <b>PVOutput.org</b> upload status, <b>Wonderwatt.com</b> share link, and each configured database backend.</p>
<p>
The animated diagram also shows community <b>outputs</b> under the dashboard: local Databases &amp; Exports, PVOutput (we push live Add Status), and Wonderwatt (share / Growatt-cloud peer — Wonderwatt does not accept uploads from us).</p>
<p>
The <b>Inverter write (this app)</b> row says whether this dashboard can push MIX schedules and/or local register writes. Cloud schedule push (Optimiser / AC charge / discharge windows) needs a <b>Growatt cloud</b> session on the Live tab. Local <b>Modbus inverter writes</b> are a separate safety opt-in: right-click State → <b>Enable Modbus inverter writes</b>, or tick <b>Allow inverter writes via Modbus</b> under Setup &amp; Info (Modbus mode must already be configured). Default is off.</p>
<p>
Column widths are remembered across restarts (including if you close the app soon after resizing). The <b>Table size</b> column shows logged row counts and the current disk size where that row writes a table. The <b>Databases</b> row shows total size per enabled backend. <b>Table history</b> on each row opens a chart of how many rows were stored by the end of each day. Rows that do not write a table (a live feed, or a link check) say so in that window.</p>
<p>
Between the connectivity table and the text summary, an <b>animated diagram</b> shows external APIs, LAN devices, this dashboard (&quot;house&quot;), databases, and export. Box borders and link colours track connectivity health. When something is <b>degraded</b> (Grott stale in Hybrid, a live alarm, a failed service), a <b>DEGRADED</b> banner at the top spells out what failed and what is carrying live data (for example &quot;GROTT stale — Hybrid live path is Growatt cloud API&quot;). Click that banner for the exact problem — if Grott is missing registers, the window names each one (for example battery state of charge, string 1 voltage) and the Growatt field behind it. Affected boxes get WARN badges and plain-English subtitles; click any highlighted box for the full &quot;What&apos;s happening right now&quot; write-up. Where that box has a login (Growatt cloud, Grott, EMQX, Tasmota, the inverter web page, Modbus, PVOutput, or a database), the same window includes those username / password / API-key fields from Setup &amp; Info. <b>Test</b> leaves a connectivity line on the same row as the Test button, at the right. Green means the last test passed, red means it failed, and amber means the last pass is more than an hour old (<b>Connectivity - last OK (Stale &gt;1hr since last test)</b>). That line stays after you close the window. The Octopus box uses the API key and meter numbers from the Octopus tabs. <b>Save</b> and <b>Test</b> write the same place those screens do. Wonderwatt keeps its share-link field. Drag the horizontal <b>splitter</b> between the table and the diagram to resize the two panes.</p>
<p>
Right-click a <b>State</b> cell for context actions that match the row:
<b>Disable</b> / <b>Enable</b> (mutes monitoring for most feeds — not shown for Databases),
<b>Go to Tasmota Tab</b> (Tasmota devices — jumps to the Tasmota Devices page),
<b>Test Connection</b> and <b>Show Downtime</b> (Octopus, Forecast.solar, PVOutput, Wonderwatt, Databases),
<b>Show Alarms</b> (live + recent alarms / faults for that service),
<b>Highlight on diagram below</b>, and <b>Show history</b> (full <code>connectivity_events</code> log).</p>
<p>
Click <b>Databases</b> or <b>Exported data</b> in the diagram for a detail window with the database logins, live status, <i>and</i> per-table <b>ring buffer</b> limits: max rows, max age (days), and max table size (MB). Oldest rows are removed first. Use <b>Prune now</b> to apply immediately; policies are saved in QSettings.</p>
"""
