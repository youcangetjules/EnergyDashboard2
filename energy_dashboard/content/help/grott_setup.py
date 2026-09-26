"""
Help text for GrottSetupTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "GrottSetupTab"

HELP_TEXT = """\
<h2>Grott Setup</h2>
<p>
Configure the local <b>Grott</b> MQTT path used by Growatt Live Status and the
database logger. The try-order here is the same as
<b>Setup &amp; Info → Telemetry source</b> and the live status bar.</p>
<p>
<b>Telemetry source:</b> rank <b>GROTT MQTT</b>, the Growatt cloud API, and
<b>Modbus RS485</b> as 1st, 2nd, and 3rd. The dashboard tries 1st first. If that
source has nothing fresh it uses the next. Modbus uses the mode under
Setup → Local Modbus check (that path does not use EMQX). Missing Grott
registers are left blank — they are not filled in from the cloud.</p>
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
