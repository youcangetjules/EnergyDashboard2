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
<li><b>GROTT MQTT</b> — decoded local telemetry via your MQTT broker (Setup → Grott fields). Grott republishes when the Shine stick sends a status or heartbeat (~1&nbsp;min). After the stick reconnects (often around the hour) it can go quiet for about 11 minutes while it handshakes with Growatt’s servers — MQTT stays up, but a tray alarm fires because live registers stopped. Historical buffer dumps are ignored.</li>
<li><b>Hybrid</b> — prefer fresh Grott; if no fresh snapshot, fall back to the cloud API. The UI can keep updating from cloud, but a system-tray alarm still fires because Grott must stay live.</li>
<li><b>Fill missing Grott data with API</b> — while Grott/Hybrid is live, patch only registers Grott did not publish from the cloud. Patched values show in <span style="color:#fab387">amber</span>.</li>
</ul>
<p>
<b>Buttons</b></p>
<ul>
<li><b>Test / Connect / Setup</b> — check the selected source, connect, or jump to Setup credentials.</li>
<li><b>Fetch / Refresh</b> — one-shot pull (Grott resubscribe or cloud fetch depending on source).</li>
<li>The banner auto-refresh button cycles 10 / 30 / 60 / 180 / 300 / 600&nbsp;s / Manual. It reports the <b>oldest</b> live source and how many are inside their own cadence, and names any that are late — hover for a per-source breakdown. GROTT MQTT is push-driven, so the interval governs cloud polling only.</li>
</ul>
<p>
<b>Open API rate limit:</b> Growatt's token-based Open API V1 only allows roughly one call per endpoint per <b>5 minutes</b>; faster polling returns error 10012 (<code>error_frequently_access</code>) and the tab pauses cloud calls for ~30&nbsp;min. The dashboard therefore never polls V1 faster than every 5 minutes regardless of the auto-refresh interval — the countdown under Refresh Now shows the true time to the next API call. For genuinely live (per-minute) data use <b>GROTT MQTT</b>, which is local and has no rate limit.</p>
<p>
<b>Battery equipage</b></p>
<p>
Parallel GBLI packs share one ~48&nbsp;V DC bus. <b>Growatt’s own website and cloud
API</b>, as well as Grott MQTT, typically publish only aggregate
<code>vBat</code>/<code>SOC</code> — there is usually no reliable signal for packs
2 or 3. This tab therefore does <b>not</b> invent a pack count from
<code>vbatdsp</code> or Setup capacity.</p>
<p>
When telemetry cannot count packs, use <b>Manual parallel modules</b> on the
Physical panel (e.g. 3 × 6.5&nbsp;kWh = 19.5&nbsp;kWh) and update
<b>Setup → Battery Analysis → Capacity</b> to match. With working
<b>Modbus TCP</b> (e.g. USR gateway on port 8899), <b>Probe packs</b> reads
holding 1125+ pack serials — on SPH that block lists every parallel pack even
when dedicated pack-count registers stay 0 (and Growatt’s website still shows
only the shared bus).</p>
<p>
<b>Battery pack serials</b> and <b>Faults / warnings</b> appear in the Physical
live column. Serials come from plant <code>device_list</code> storage devices when
present, otherwise from Modbus. Inverter fault/warning words come from Grott
(<code>systemfaultword0–7</code>, <code>faultBit</code>/<code>warningBit</code>)
and stack as separate rows. Dashboard alarms (database not logging, Grott MQTT lost, inverter offline, Tasmota silent, low SOC, spare PV)
have their own Physical row under the inverter words; they also remain on the
live banner (click for detail).</p>
<p>
<b>System status</b> is the inverter’s work-mode code from Grott/cloud
(<code>lost</code> / <code>status</code> / <code>pvstatus</code>) — not a fault
word. On SPH/MIX hybrids the usual meanings are: 0 standby, 5 PV charging the
battery, 6 grid charging, 7 battery discharging, 3 fault, and related combine/
bypass modes. Hover the value for the raw code and the full legend. If the stick
is offline Growatt may publish a string such as <code>lost</code> instead.</p>
"""
