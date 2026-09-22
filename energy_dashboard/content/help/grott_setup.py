"""
Help text for GrottSetupTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "GrottSetupTab"

HELP_TEXT = """\
<h2>Grott Setup</h2>
<p>
Configure the local <b>Grott</b> MQTT path used by Growatt Live Status and the
database logger. Settings here are the same as
<b>Setup &amp; Info → Growatt → telemetry source</b>.</p>
<p>
<b>Telemetry source:</b> choose <b>GROTT MQTT</b> for local-only data, or
<b>Hybrid</b> to fall back to the Growatt cloud API when Grott is stale.
<b>Fill missing Grott data with API</b> patches individual registers (shown in
amber on Growatt Live) without switching the whole source.</p>
<p>
<b>MQTT broker:</b> host, port, topic filter (usually <code>energy/growatt</code>),
credentials, and <b>Fresh max</b> — how old a payload may be before it counts
as stale.</p>
<p>
<b>Test Grott MQTT</b> checks broker connect and subscribe. No JSON within a
few seconds is normal — Grott publishes on Shine packets (~1&nbsp;min heartbeat,
~5&nbsp;min full status). After the Shine stick reconnects (often around the
hour) it can go quiet for about 11 minutes while it announces itself to
Growatt’s servers; MQTT stays connected. Historical buffer dumps on the same
topic are ignored so they never overwrite live cards.</p>
<p>
<b>Live feed</b> at the top shows subscriber state from the running dashboard.
<b>Save</b> writes settings and restarts the MQTT client.</p>
"""
