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
<b>Broker URL → Test</b> checks the collector, then says where PostgreSQL’s host is set and what it is set to. The address is not written into the program. <b>Database → PostgreSQL → Host</b> is saved as <code>db/pg_host</code>. Installing the collector copies that into <code>POWERMON_PG_HOST</code> in <code>/etc/default/energy-collector</code>. The test shows both the Host box on this page and the host the running collector is actually using.</p>
<p>
<b>Main window — tab bar</b> lets you hide tabs you rarely use; Growatt, Octopus Energy Data, and this Setup tab always stay visible.</p>
<p>
<b>EMQX routing profile</b>: local <b>Tasmota</b>, <b>WiFi Direct</b>, and <b>LAN Direct</b> routes are configured to flow through <code>222.20.20.212</code>. Enter the EMQX <b>host</b>, <b>port</b>, <b>username</b>, and <b>password</b>. Use <b>Save</b> to store credentials only, <b>Test</b> to verify MQTT connect/auth, and <b>Apply EMQX route</b> to sync those credentials into Growatt Grott MQTT and Tasmota MQTT settings in one step.</p>
<p>
<b>Growatt local Modbus</b>: an RS485–Ethernet converter is <b>Modbus TCP</b> from this PC
(LAN IP of the box, usually port 502) after you set its transfer mode to
<b>Modbus TCP&lt;=&gt;Modbus RTU</b>. Transparent Mode needs
<b>RTU over TCP</b> (USR often uses port 8899). USB <code>/dev/ttyUSB0</code> is only for
an adapter plugged into this computer. UART on the box: 9600 8N1, 485 enabled,
baudrate-adaptive/RFC2217 off. Tick <b>Allow inverter writes via Modbus</b> only when
you intend this app to write holding registers on the LAN (default off — safety-sensitive).
You can also toggle that from Connectivity Status → Inverter write → right-click.</p>
<p>
<b>PVOutput.org</b>: optional live upload of today’s PV generation (and house load when available) via the Add Status API. Enable it, paste your API key and System Id from
<a href="https://pvoutput.org/">pvoutput.org</a> → Settings → API Access, then Save. Uploads run from fresh Growatt snapshots at the interval you set (default 5&nbsp;min; site limit 60/hour). Use <b>Test upload</b> to force one now.</p>
<p>
<b>Wonderwatt.com</b>: hosted optimiser that reads your inverter through the <b>Growatt cloud</b> itself — there is no public Wonderwatt upload API from this app. Paste an Advanced share link here (or on Potential Issues) so we can compare their forecast with ours.</p>
<p>
<b>Database Export</b>: tick SQLite, MySQL, or PostgreSQL to log live readings. Each row shows host/file settings, then three left-aligned checks — <b>DB seen</b>, <b>Database connected</b>, <b>Tables connected</b> — and on the right the prepared <b>CREATE</b> SQL that builds every logger table (inverter, Tasmota, Octopus, forecasts, Agile slot prices, Agile Year daily stats, MIX chart, shadow trial, connectivity history, PV string charge). <b>Tables connected</b> means those tables exist <i>and this login can read and write them</i>. A green “Database connected” with red “Tables not readable” means this login can open the database but cannot read the logger tables (often the EMQX user on a database owned by postgres). <b>0/N</b> means none of the logger tables listed in that script are usable by this login. PostgreSQL is set up by running the SQL on the right <b>by hand as the database owner</b> — the dashboard login is not allowed to create tables or to grant itself access. That script does both jobs: it creates every logger table, then grants the login named in the <b>User</b> field SELECT, INSERT, UPDATE, and DELETE on those tables (UPDATE covers the upserts, DELETE covers ring-buffer retention). Creating a table does not grant access to it, so tables can exist and still read as not usable. <b>Copy CREATE SQL</b> puts the whole script on the clipboard. <b>Show missing</b> lists only the logger tables that are not on that database yet and shows CREATE SQL for those tables alone (PostgreSQL includes GRANT lines for the User field). SQLite and MySQL <b>Setup Database</b> still runs their script. If a network database is ticked but unreachable, the dashboard stays responsive — it retries in the background instead of waiting on a long TCP timeout.</p>
<p>
<b>Live alarms (database, devices, battery)</b>: the same banner and system-tray path watches more than the battery. If logging is enabled but the database is unreachable for about a minute, or Growatt/Tasmota rows stop landing for 15 minutes while those devices are live, that fires. Grott MQTT drop still raises after about 20&nbsp;s; missing payloads use the Grott fresh window. Growatt reporting the inverter offline, Tasmota MQTT down, or named plugs going silent also fire. Low-SOC / spare-PV rules use the hold time below. Desktop notifications: immediate, then 4× every 5&nbsp;min, 4× every 10&nbsp;min, 4× every 30&nbsp;min, then hourly (resets when the alarm clears).</p>
"""
