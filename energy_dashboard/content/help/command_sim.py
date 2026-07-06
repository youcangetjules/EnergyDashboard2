"""
Help text for CommandSimTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "CommandSimTab"

HELP_TEXT = """\
<h2>Command Sim</h2><p>
Starts a tiny <b>Modbus TCP slave</b> inside this process (pymodbus <code>SimDevice</code>) so you can point the Connectivity tab’s <b>Growatt local Modbus</b> probe at <code>127.0.0.1</code> and a chosen port (default 5502) without a real inverter.</p>
<p>
This tab is the <b>server</b> — it listens. A separate <b>client</b> (Connectivity probe, or the built-in <i>Test read / Manual command</i> buttons) must connect for “positive” Modbus traffic. Listening alone only proves the socket is open.</p>
<p>
This is <b>not</b> a Grott protocol clone (no Growatt encrypted payload tunnel to <code>server.growatt.com</code>); it only speaks standard Modbus TCP, similar in spirit to the <code>growatt2mqtt/src/tools/growatt_simulator.py</code> serial RTU helper.</p>
<p>
<b>Stop</b> before changing bind address or port. If start fails, another process may already own that port.</p>
"""
