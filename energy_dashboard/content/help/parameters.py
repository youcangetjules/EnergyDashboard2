"""
Help text for ParametersTab (global status-bar Help button).
"""
from __future__ import annotations

TAB_CLASS = "ParametersTab"

HELP_TEXT = """\
<h2>Setup &amp; Info</h2><p>
One-stop config: API credentials, tariff parameters, battery defaults, solar installation, scheduled loads, database backends, and Agile product / tariff codes. Save buttons write to QSettings (<code>~/.config/PowerModel/EnergyDashboard2.conf</code>) and immediately push values into the live AppParameters object so the rest of the app sees them without restart.</p>
<p>
Use <b>Apply to all tabs</b> to push battery / solar / Agile settings into the simulator, Forecasts and Smart Advisor tabs in one click.</p>
<p>
<b>Main window — tab bar</b> lets you hide tabs you rarely use; Growatt, Octopus Energy Data, and this Setup tab always stay visible.</p>
<p>
<b>EMQX routing profile</b>: local <b>Tasmota</b>, <b>WiFi Direct</b>, and <b>LAN Direct</b> routes are configured to flow through <code>222.20.20.212</code>. Use <b>Apply EMQX route</b> to sync that host/port into Growatt Grott MQTT and Tasmota MQTT settings in one step.</p>
"""
