"""
Help text for TasmotaTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "TasmotaTab"

HELP_TEXT = """\
<h2>Tasmota Devices</h2><p>
Polls every Tasmota device on the configured IP range (<code>TASMOTA_IP_START</code> – <code>TASMOTA_IP_END</code>) for live power and accumulated energy, and logs to the database for historical analysis.</p>
<p>
<b>Subscribe via MQTT</b> listens on <code>tele/+/SENSOR</code>, <code>tele/+/STATUS8</code>, <code>stat/+/POWER</code>, and <code>tele/+/STATE</code> instead of HTTP polling each device. Use <b>Test connection</b> to verify the broker, then <b>Save MQTT</b>. Devices are matched by <code>IPAddress</code> in the payload when present.</p>
<p>
<b>Poll every (s)</b> and <b>Auto poll</b> apply to HTTP LAN poll or broker <code>/snapshot</code> only (not MQTT). Click <b>Save</b> to apply.</p>
<p>
Per-row <b>Probe</b> re-polls one IP; <b>Web UI</b> opens the device; <b>Diagnose</b> (right of Web UI) explains blank or bad rows: live HTTP checks (Status 0/3/4/8/11, Power), briefly enables <code>WebLog 4</code> for verbose HW/socket errors, plus logging levels, heap/flash (Status 4), connectivity, WiFi RSSI, reboots, MQTT, and scheduler <code>LoadAvg</code>; <b>Toggle</b> sends <code>Power Toggle</code> after confirmation.</p>
<p>
Devices are shown in two side-by-side tables: the first seven addresses in the configured range on the left, the rest on the right.</p>
<p>
Action buttons (Probe, Web UI, Diagnose, Toggle) share one column with equal fixed widths and small gaps; an extra gap separates Diagnose from Toggle. Toggle is green when relay ON, red when OFF, slate when state unknown, and muted grey (disabled) when the device is unreachable. Relay ON/OFF is also shown in the State column. Other columns resize with the window (name stretches).</p>
"""
