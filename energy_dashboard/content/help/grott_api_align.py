"""
Help text for GrottApiAlignTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "GrottApiAlignTab"

HELP_TEXT = """\
<h2>Grott / API Align</h2>
<p>
Compares the live <b>Grott MQTT</b> snapshot with one Growatt <b>cloud API</b>
live read. Both sides are the same MIX-style fields used on Growatt Live Status
(<code>status</code> / <code>totals</code>), not raw JSON. Grott is taken from
the MQTT snapshot, never from the API-patched live gauges.</p>
<p>
<b>Shared API budget:</b> this page never competes with Growatt Live Status for
the Open API quota. When the Live page has made a cloud read in the last
10&nbsp;minutes, the compare <b>reuses</b> that read (paired with the Grott
snapshot captured at the same moment) — no extra API call, and the Live page's
own polling is never delayed. Only when no recent read exists does the compare
make one poll of its own, through the same 5-minute spacing gate the Live page
uses.</p>
<p>
<b>Compare now</b> is a one-shot: it reuses a fresh Live read or fetches one
cloud live bundle and fills the table. If the cloud host cannot be reached
(DNS, timeout, connection refused, TLS), the status says the <b>API is not
contactable</b>. If Growatt is not connected yet, that is reported the same way
with a Connect hint.</p>
<p>
<b>Automatic every N minutes</b> (default <b>120</b>) runs the same compare on a
timer while the dashboard is open. The first automatic run waits one full
interval so startup does not steal the 5-minute V1 quota. All runs — including
one-shot Compare — skip the cloud call during an
<code>error_frequently_access</code> pause (calling during a pause could re-arm
it and take Live Status offline for longer) and show Grott-only results with
the pause time remaining.</p>
<p>
<b>Results:</b> Aligned means the two values differ by no more than the
tolerance (about 0.05–0.08&nbsp;kW for power, 1% SOC, 0.1–0.2&nbsp;kWh for
today totals, ~2&nbsp;V / 0.08&nbsp;Hz). Grott-estimated house load or grid
power is noted in the Notes column — it is not treated as a decode failure.
History keeps the last 48 runs in this session.</p>
<p>
Enable Grott MQTT (or Hybrid) on Growatt Live Status and Connect the cloud
session so both sides have data.</p>
"""
