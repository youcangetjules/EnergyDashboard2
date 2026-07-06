"""
Help text for GrowattTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "GrowattTab"

HELP_TEXT = """\
<h2>Growatt Live Status</h2><p>
Live snapshot of the inverter: SOC, battery / PV / grid / load power, today's totals, device information, and the three-column physical panel. Data can come from the Growatt cloud API, local <b>GROTT MQTT</b>, or <b>Hybrid</b> (Grott first, cloud fallback when Grott is stale).</p>
<p>
<b>Telemetry source</b></p>
<ul>
<li><b>Growatt Cloud API</b> — server.growatt.com / Open API credentials from Setup.</li>
<li><b>GROTT MQTT</b> — decoded local telemetry via your MQTT broker (Setup → Grott fields).</li>
<li><b>Hybrid</b> — prefer fresh Grott; if no fresh snapshot, fall back to the cloud API.</li>
<li><b>Fill missing Grott data with API</b> — while Grott/Hybrid is live, patch only registers Grott did not publish from the cloud. Patched values show in <span style="color:#fab387">amber</span>.</li>
</ul>
<p>
<b>Buttons</b></p>
<ul>
<li><b>Test / Connect / Setup</b> — check the selected source, connect, or jump to Setup credentials.</li>
<li><b>Fetch / Refresh</b> — one-shot pull (Grott resubscribe or cloud fetch depending on source).</li>
<li>The banner auto-refresh button cycles 10 / 30 / 60 / 180 / 300 / 600&nbsp;s / Manual.</li>
</ul>
"""
