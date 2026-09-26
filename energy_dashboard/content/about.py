"""
Energy Dashboard — `content/about.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.version import APP_VERSION
# Copy shown in the "About" dialog (Setup & Info tab → About button).
# Authored by the project owner; rendered as rich HTML in a QTextBrowser
# so the trailing mailto: link stays clickable.
# The GitHub README.md opens with these same words (markdown, not HTML).
# If this text changes, update README.md to match, including the version line.
_APP_ABOUT_TEXT = (
    "<h2 style='margin:0 0 6px 0;'>PowerModel — Energy Dashboard</h2>"
    f"<p style='margin:0 0 14px 0; color:#a6adc8;'>Version {APP_VERSION}</p>"

    "<p style='margin:0 0 12px 0; line-height:1.5;'>"
    "Somewhat experimental version that works specifically with "
    "<b>Growatt</b> and <b>Octopus Energy</b>. To integrate into any "
    "telemetry and/or control system requires API access — figuring out "
    "how to make it work with Growatt took a lot of trial and error, but "
    "we got there. I believe Octopus Energy's API is more complete / "
    "thorough than others."
    "</p>"

    "<p style='margin:0 0 12px 0; line-height:1.5;'>"
    "As for me, I'm just some coffee-addled, tech-obsessed former "
    "military officer who got spat out and found himself as a "
    "telecommunications "
    "consultant. I was the head of Network Automation for Vodafone at "
    "one point (\"So it's <i>YOU'RE</i> fault…\" I can hear you think — "
    "Vodafone is actually a very good network. Not that I am biased, of "
    "course), so automation is what I do — and man have I seen some "
    "\"sorry mate, you can't park there…\" moments in my 27 years."
    "</p>"

    "<p style='margin:0 0 14px 0; line-height:1.5;'>"
    "I work with the regulators and am a partner in one of the leading "
    "consultancies. At your service."
    "</p>"

    "<p style='margin:0; line-height:1.5;'>"
    "If you want to reach out, know anything further, or even just ask "
    "how the weather is in Oxfordshire, give me a shout — "
    "<a href='mailto:julian.garrett@aliniant.com' "
    "style='color:#89b4fa; text-decoration:none;'>"
    "julian.garrett@aliniant.com</a>"
    "</p>"
)

# Patch / change log shown by the History dialog. Each entry is a tuple of
# (version_string, ISO_date, list_of_change_bullets). Newest first. Add a
# new entry every time APP_VERSION_PATCH is bumped so the in-app history
# stays in lock-step with the code.
_APP_CHANGELOG = (
    ("2.9.445", "2026-09-26", [
        "Maximise stops above the taskbar, so the bottom buttons stay visible.",
    ]),
    ("2.9.444", "2026-09-26", [
        "A stronger 2px line in 70% grey runs under the tab bar.",
    ]),
    ("2.9.443", "2026-09-26", [
        "Bug Tracker starts with progress per day: how many bugs were "
        "opened, how many were fixed, and how many were still open at "
        "the end of that day.",
    ]),
    ("2.9.442", "2026-09-26", [
        "A Connectivity popup stays open. It was appearing for a second "
        "and then vanishing, which left the dashboard waiting and unable "
        "to take another click.",
    ]),
    ("2.9.441", "2026-09-26", [
        "Show Alarms on a Connectivity row no longer crashes. The live "
        "alarm list was being read as if it were already a plain list.",
    ]),
    ("2.9.440", "2026-09-26", [
        "Click the <b>DEGRADED</b> banner on Connectivity to see the exact "
        "problem. When Grott is missing registers, the window names each "
        "one and the Growatt field behind it.",
    ]),
    ("2.9.439", "2026-09-26", [
        "Connectivity Status shows each logged table’s row count and "
        "current disk size. <b>Table history</b> on a row opens a chart of "
        "how many rows were stored by the end of each day.",
    ]),
    ("2.9.438", "2026-09-26", [
        "Roof layout imagery has <b>Google historic</b>. It opens Google "
        "Earth’s timeline in the map panel. Satellite map brings the roof "
        "outline back. Historic satellite stays the separate dated archive.",
    ]),
    ("2.9.437", "2026-09-26", [
        "String voltage has <b>Today</b> and <b>Rolling 24Hr</b>. Today is "
        "one London day and is the default. Rolling 24Hr draws now where "
        "22:00 sits on the day chart (22 hours back, 2 hours ahead). The "
        "day menu can reach today after midnight.",
    ]),
    ("2.9.436", "2026-09-25", [
        "Octopus Live 15-minute view asks for 5-minute Home Mini readings "
        "and adds them into quarter-hour slots. The old 15-minute request "
        "was rejected, so the chart fell back to the slower meter and sat "
        "many hours behind.",
    ]),
    ("2.9.435", "2026-09-25", [
        "Roof layout imagery: Google Satellite is the current photo only. "
        "<b>Historic satellite</b> is the dated aerial archive (Year and "
        "Release). Google’s tile server no longer returns older satellite versions.",
    ]),
    ("2.9.434", "2026-09-25", [
        "Roof layout’s satellite map no longer crashes the dashboard as "
        "it opens. The fault was an application-wide event filter "
        "re-entering PySide while a property was set. Blocking dialogs "
        "still stay on top.",
    ]),
    ("2.9.433", "2026-09-25", [
        "<b>Panel database</b> is under <b>Physical Plant Tools</b>, after "
        "Roof layout. It keeps the module types on this roof (maker, model, "
        "watts, size, and optional datasheet volts). Roof layout’s panel "
        "list uses those rows. A blank voltage stays blank.",
    ]),
    ("2.9.432", "2026-09-25", [
        "String voltage writes each string’s latest volts beside the "
        "teal now line, so the last reading is visible on the chart.",
    ]),
    ("2.9.431", "2026-09-25", [
        "<b>Dump logs</b> is under <b>Controls</b>, after Console. It shows "
        "the crash log (segmentation faults and other fatal signals), "
        "including the core-dump stack when the system kept one.",
    ]),
    ("2.9.430", "2026-09-25", [
        "String voltage is a page under <b>Physical Plant Tools</b>, after "
        "PV String Charge. It charts measured volts for each string across "
        "a London day. Today includes the live reading. Earlier days use "
        "the stored 2-minute lots only.",
    ]),
    ("2.9.429", "2026-09-25", [
        "Stale page tabs keep the same header size as the others. The light "
        "outline is drawn inside the tab, so it no longer sits outside as a "
        "halo.",
    ]),
    ("2.9.428", "2026-09-25", [
        "String voltage is now stored. Each MPPT string’s measured volts "
        "(vPv1 and vPv2) are averaged into 2-minute lots in "
        "<code>pv_string_voltage</code>. On PostgreSQL, run the Setup "
        "CREATE script as the database owner so the new table exists.",
    ]),
    ("2.9.427", "2026-09-25", [
        "Page tabs that are not selected and have not updated pick up a "
        "stronger light border and a slight 10% white fill, so they stay "
        "visible on the black tab bar.",
    ]),
    ("2.9.426", "2026-09-25", [
        "PV String Charge, on a previous day, shows each string’s share of "
        "that day’s PV as a percentage, next to the kilowatt-hours. Measured "
        "battery charge is shown as a percentage of that day’s PV as well.",
    ]),
    ("2.9.425", "2026-09-25", [
        "Roof layout now lives under <b>Physical Plant Tools</b>, "
        "with the battery and string pages. Apply to Forecasts still "
        "feeds the forecast from those roof faces.",
    ]),
    ("2.9.424", "2026-09-25", [
        "PV String Charge: Day opens a calendar. On a previous day the "
        "cards lead with that day’s kWh for each string (and the estimated "
        "kWh into the battery), not the live 0 kW reading.",
    ]),
    ("2.9.423", "2026-09-25", [
        "PV String Charge can show a previous London day. The Day field "
        "and calendar load that day’s stored string and charge lots. Today "
        "still includes the live reading; a past day does not invent energy "
        "up to the current clock.",
    ]),
    ("2.9.422", "2026-09-25", [
        "Connectivity login panels put the test result on the same row as "
        "<b>Test connection</b>, at the right: green OK, red failed, amber "
        "when the last pass is more than an hour old.",
    ]),
    ("2.9.421", "2026-09-25", [
        "Fixed the overnight segmentation fault with garbage collection left "
        "on. A background history fetch was collecting cycles while the tab "
        "bar was destroying a Qt object mid-paint. Qt objects are no longer "
        "on that collector; ordinary Python objects still are.",
    ]),
    ("2.9.420", "2026-09-25", [
        "Bug Tracker IDs now start with a running number between BUG and the "
        "date (for example BUG-059-20260925-02). Open titles stay red and "
        "fixed titles stay green in the tab.",
    ]),
    ("2.9.419", "2026-09-25", [
        "Long sessions were dying with a segmentation fault while a background "
        "thread loaded Tasmota history and Python’s cycle collector walked Qt "
        "objects. That collector now runs only on the main thread, between "
        "screen updates.",
    ]),
    ("2.9.418", "2026-09-24", [
        "Agile Year prior-year cells: draw the smaller bracketed delta with a "
        "paint delegate instead of QLabel cell widgets (avoids a PySide "
        "segmentation fault seen on 2.9.417).",
    ]),
    ("2.9.417", "2026-09-23", [
        "Agile Year <b>Avg −1y / −2y / −3y</b>: each cell shows that year’s "
        "average, then in brackets (2pt smaller) the difference versus this "
        "day’s average (negative = cheaper than this year).",
    ]),
    ("2.9.416", "2026-09-23", [
        "Agile Year <b>Fetch year</b> asks Octopus for about three years of "
        "rates (not ~370 days), so the table can reach further back than "
        "18 Sep 2025 when that tariff has history, and <b>Avg −1y / −2y</b> "
        "can fill.",
    ]),
    ("2.9.415", "2026-09-23", [
        "Agile Year table: <b>Avg −1y</b>, <b>Avg −2y</b>, and <b>Avg −3y</b> "
        "show the daily average on the same calendar date one, two, and three "
        "years earlier (from stored days only — a dash means that prior date "
        "is not in the table yet). The chart is unchanged.",
    ]),
    ("2.9.414", "2026-09-23", [
        "Octopus Live Monitor title chip is opaque frosted glass with a 1px "
        "grey border.",
        "Cost view: charts change with the toggle. Only <b>Imported</b> is "
        "priced (£/h on top, cumulative £ on the bottom right axis). "
        "Generated / Total Used / Exported stay as kWh with no cost.",
    ]),
    ("2.9.413", "2026-09-23", [
        "Octopus Live Monitor: the panel title has a light glass wash and a "
        "neat 1px grey border.",
    ]),
    ("2.9.412", "2026-09-23", [
        "Octopus Live: the bottom chart always shows "
        "<b>Generated Energy (PV)</b>, <b>Imported Energy</b>, "
        "<b>Total Used Energy</b>, and <b>Exported Energy</b> — including in "
        "Cost view. Cost only changes the top chart and the cards to pounds.",
    ]),
    ("2.9.411", "2026-09-23", [
        "A segmentation fault or abort is written to "
        "<b>~/.energy_dashboard_crash.log</b> and a <b>Crash</b> line in the "
        "Console. That log has the Python stacks and the system core-dump "
        "stack. Closing the window normally is not recorded as a crash.",
    ]),
    ("2.9.410", "2026-09-23", [
        "PV String Charge: click <b>String 1</b> or <b>String 2</b> for a "
        "history table of measured generation. Rows open as "
        "<b>Month → Day → Hour</b> with String 1 / String 2 kWh, total, and "
        "the relative balance between the strings.",
    ]),
    ("2.9.409", "2026-09-23", [
        "Octopus Live Cost: <b>Import cost</b> and <b>Export credit</b> keep "
        "this Hours window as the large figure, and add a smaller "
        "<b>(Today: £…)</b> for London midnight to now so a multi-day window "
        "is not mistaken for today’s bill so far.",
    ]),
    ("2.9.408", "2026-09-23", [
        "Dashboard starts again. Command Sim had asked for a motif size "
        "name that was missing after a circular import, so launch crashed.",
    ]),
    ("2.9.407", "2026-09-23", [
        "Setup &amp; Info → Database Export: each engine has <b>Show missing</b>. "
        "It lists logger tables that are not on that database yet and shows "
        "CREATE SQL for only those tables (PostgreSQL includes GRANT lines "
        "for the User field).",
    ]),
    ("2.9.406", "2026-09-23", [
        "Command Sim: Bind address and the other fields use the grey fill "
        "with electric-blue border. Server and client controls sit left of "
        "centre instead of stretching across the window.",
    ]),
    ("2.9.405", "2026-09-23", [
        "Grott Setup Live feed shows <b>connected · fresh</b> in bold green "
        "(and stale / not connected in bold amber or red). A label colour rule "
        "had been painting that whole line white.",
        "Text boxes, combos, and spin fields share the same slight grey fill "
        "across the app (the fill spins already used), so fields no longer "
        "blend into the dark panel.",
    ]),
    ("2.9.404", "2026-09-23", [
        "Octopus Energy Data fetches with the API key saved on Octopus Live. "
        "The old default key was rejected by Octopus, so the charts stayed empty. "
        "A failed fetch now says why on the chart.",
    ]),
    ("2.9.403", "2026-09-23", [
        "Database Viewer’s <b>Table</b> list now includes every logger table: "
        "solar forecast, MIX chart, shadow-trial plans and scores, and "
        "connectivity history, as well as the ones that were already there. "
        "The list stays in step with the Setup CREATE script.",
    ]),
    ("2.9.402", "2026-09-23", [
        "Broker URL test names where the PostgreSQL host is set "
        "(Setup &amp; Info → Database → Host, saved as <code>db/pg_host</code>, "
        "copied to <code>POWERMON_PG_HOST</code>) and what that host is set to. "
        "The address is not hard-coded.",
    ]),
    ("2.9.401", "2026-09-22", [
        "Octopus Live: <b>Save</b> sits to the right of Hours and View, "
        "with a vertical rule between those two controls. <b>Test</b> is "
        "to the right of Save and checks the API key and account without "
        "reloading the charts.",
    ]),
    ("2.9.400", "2026-09-22", [
        "Octopus Live has a <b>Power / Cost</b> switch. Cost is energy "
        "times the Agile spot price. Days Octopus has already metered "
        "use that half-hour meter. Today is an estimate, scaled from "
        "those settled days. Standing charge is not included.",
    ]),
    ("2.9.399", "2026-09-22", [
        "<b>Run Advisor</b> turns pale green after a run that finishes, "
        "the same green as a tab that has just refreshed. A failed run "
        "turns that button black.",
        "<b>Battery Expansion Simulator</b> says so on the charts and in "
        "Simulation Results when there is not at least one day of half-hour "
        "history to work from, instead of leaving blank axes.",
    ]),
    ("2.9.398", "2026-09-22", [
        "Launch no longer prints “Failed to query DRM render node” or "
        "“GPUInfo not initialized”. Those lines were the old software-GPU "
        "workaround talking. Charts still use software drawing. "
        "Hardware GPU remains <code>POWERMODEL_WEBENGINE_GPU=1</code>.",
    ]),
    ("2.9.397", "2026-09-22", [
        "Maximise no longer shortens the window. Height is the full screen "
        "(above the taskbar). Width still cannot grow past that monitor.",
    ]),
    ("2.9.396", "2026-09-22", [
        "Maximise snaps the main window to the screen it is on — that "
        "monitor’s resolution, and no wider or taller.",
    ]),
    ("2.9.395", "2026-09-22", [
        "<b>PV String Charge</b> and <b>Potential Issues</b> (renamed from "
        "Pot. Issues) joined <b>Battery Analysis</b> in Physical Plant Tools.",
    ]),
    ("2.9.394", "2026-09-22", [
        "<b>Battery Analysis</b> moved out of Dashboards into a new group, "
        "<b>Physical Plant Tools</b>.",
    ]),
    ("2.9.393", "2026-09-22", [
        "The tab group that was <b>Energy Usage</b> is now <b>Dashboards</b>, "
        "first on the left. The app always opens on that group.",
    ]),
    ("2.9.392", "2026-09-22", [
        "The main window cannot be resized larger than the screen it is on. "
        "The limit follows that monitor, and still stops above the taskbar.",
    ]),
    ("2.9.391", "2026-09-22", [
        "The dashboard keeps <b>one</b> MQTT connection to EMQX, named "
        "<code>energy_dashboard</code>. Grott and the Tasmota tab share it. "
        "A second dashboard window does not open another session.",
    ]),
    ("2.9.390", "2026-09-22", [
        "Growatt Physical → Manual packs is one line: Auto, Apply, and "
        "Probe packs sit side by side.",
    ]),
    ("2.9.389", "2026-09-22", [
        "Tasmota Power History title no longer adds the “earlier gap” note "
        "(when stored samples start, or a reminder to check the collector). "
        "It stays the window, the source, and the Y-axis cap.",
    ]),
    ("2.9.388", "2026-09-22", [
        "Octopus Live now leads with connectivity: green <b>Connectivity — OK</b> "
        "when GraphQL answered, amber <b>REST only</b> or <b>stale</b>, red "
        "<b>failed</b>. The same state sits on the bottom strip as "
        "<b>Octopus</b>, beside the database. How old the newest meter slot is "
        "stays on that line as “latest … ago”.",
    ]),
    ("2.9.387", "2026-09-22", [
        "The main window no longer sizes itself underneath the taskbar. "
        "It fills the usable screen and stays above the panel, including "
        "when maximise would otherwise cover the bar.",
        "A message box that you must OK or Cancel before the rest of the "
        "app will respond stays on top. It can no longer slip behind the "
        "main window and leave the dashboard stuck.",
    ]),
    ("2.9.386", "2026-09-22", [
        "Connectivity login panels keep a test result in the bottom-right: "
        "green <b>Connectivity — OK</b> after a pass, red when it failed. "
        "A pass older than an hour turns amber: "
        "<b>Connectivity - last OK (Stale &gt;1hr since last test)</b>. "
        "Closing the window does not clear it.",
    ]),
    ("2.9.385", "2026-09-22", [
        "Agile Year stores daily high / low / average in "
        "<code>agile_year_daily</code> (half-hour slots still go in "
        "<code>agile_price_snapshots</code>). The spike at the right of the "
        "chart is gone — leftover twin axes and 1–2 slot phantom days are "
        "dropped so the line matches the table. Trend checkboxes: Monthly, "
        "YTD, Yearly, Since start. Table columns are resizable, with "
        "<b>% above/below LT trend</b> and <b>std. deviation from trend</b>.",
    ]),
    ("2.9.384", "2026-09-22", [
        "Growatt Live Status: the <b>Physical — inverter &amp; battery</b> panel "
        "is now four tidy columns (dashboard model + today, battery equipage, "
        "grid &amp; PV, pack &amp; status). Field names sit in their own fixed "
        "column with dividers between groups, so long names no longer run into "
        "the value next to them and wrapped values are no longer clipped.",
        "Forecasts: the Agile price and solar charts use the tab height "
        "properly — the dead bands above, between, and below the panes are "
        "gone (plot area up from roughly 64% to 80% of the canvas). Day labels "
        "and per-day kWh totals now get headroom inside the chart instead of "
        "shrinking it.",
    ]),
    ("2.9.383", "2026-09-22", [
        "Growatt API (and other Connectivity login) popups open ~1200&nbsp;px "
        "wide with roomy Username / Password / API key / Serial fields. "
        "<b>Test connection</b> on that dialog (and Setup &amp; Info) checks "
        "Growatt cloud login and a live read.",
    ]),
    ("2.9.382", "2026-09-22", [
        "Controls gains a <b>Bug Tracker</b> tab that shows the project’s "
        "standing defect log (<code>bug_tracker.md</code>). Reload re-reads "
        "the file from disk; the tab does not edit it.",
    ]),
    ("2.9.381", "2026-09-22", [
        "Connectivity architecture boxes are a little taller so titles, "
        "ALARM/WARN labels, and subtitles are not clipped against the bottom "
        "edge.",
    ]),
    ("2.9.380", "2026-09-22", [
        "Hardened background→GUI callbacks so worker threads always queue "
        "onto the main window thread (avoids a rare mid-session crash when "
        "the UI was painting at the same time).",
    ]),
    ("2.9.379", "2026-09-21", [
        "Grott “missing registers” amber was mostly a false alarm: Shine "
        "sends full status frames and short heartbeats (SOC + grid V/Hz). "
        "The heartbeat used to wipe the “Grott published this” set, so the "
        "app re-patched those fields from the cloud. Recent Grott registers "
        "now stay present across heartbeats (until the fresh window expires), "
        "and the Connectivity banner names which fields are still cloud-filled.",
    ]),
    ("2.9.378", "2026-09-21", [
        "The PostgreSQL script on Setup & Info now also grants the dashboard "
        "login access to the logger tables, named for the user in the field "
        "beside it. Creating a table does not grant access to it, so "
        "“Tables not readable” persisted after the tables existed. Run the "
        "whole script by hand as the database owner.",
    ]),
    ("2.9.377", "2026-09-21", [
        "Battery Analysis no longer pops a blocking error box when history "
        "cannot be loaded. That box froze every tab and the Close button "
        "until it was dismissed. The message stays on the status line.",
    ]),
    ("2.9.376", "2026-09-21", [
        "PostgreSQL logger tables are created by the Setup SQL, run by hand "
        "as the database owner. That script creates every logger table. The "
        "dashboard login (including EMQX) no longer issues CREATE TABLE, so a "
        "refused create is not reported as the database being down. “Tables "
        "not readable (0/11)” means this login can connect but cannot use "
        "those tables.",
    ]),
    ("2.9.375", "2026-09-21", [
        "Connectivity diagram popups now include the login for that box: "
        "Growatt cloud, Grott MQTT, EMQX, Tasmota (the EMQX broker), inverter "
        "web UI, Modbus access, Octopus API key and meters, PVOutput, and "
        "database usernames. Save and Test update the same fields as Setup "
        "& Info. Wonderwatt still uses its share link. Battery, forecast, "
        "AI, and the dashboard box have no separate login.",
    ]),
    ("2.9.374", "2026-09-21", [
        "Octopus Live “No Growatt PV” and footer ingest of 0 were hiding a "
        "PostgreSQL permission problem: the app can connect while the login "
        "cannot read growatt_readings. Setup now marks tables not readable "
        "(not connected); ingest says no table access; the chart names the "
        "denied table instead of looking like a quiet solar day.",
    ]),
    ("2.9.373", "2026-09-21", [
        "Live alarms now cover the logging database and devices as well as "
        "the battery: database unreachable, no new Growatt/Tasmota rows "
        "while kit is live, inverter reported offline, Tasmota MQTT down, "
        "or named plugs silent. Same banner, tray, and Connectivity diagram "
        "as Grott-lost / low SOC. Setup group renamed Live alarms.",
    ]),
    ("2.9.372", "2026-09-21", [
        "Two-line strip across the bottom of the window: database "
        "connected/disconnected plus ingest (last 15 minutes / hour / "
        "London today), and whole-machine CPU and RAM with a rolling "
        "one-hour average. Polls off the UI thread; hover CPU/RAM for "
        "this-process usage.",
    ]),
    ("2.9.371", "2026-09-21", [
        "Energy Forecasts: new <b>Agile Year</b> tab — about 12 months of "
        "Octopus Agile daily highest / lowest / average p/kWh (inc. VAT), "
        "and how many hours each day the rate was below 0p. "
        "Import or export; Fetch year pulls the public unit-rate history.",
    ]),
    ("2.9.370", "2026-09-21", [
        "Setup &amp; Info database status is three explicit lines: "
        "<b>PostgreSQL DB seen</b>, <b>Database connected</b>, and "
        "<b>Tables connected</b> (with a count). A wrong password no longer "
        "reads as “database not found”.",
    ]),
    ("2.9.369", "2026-09-21", [
        "Disconnected MySQL/PostgreSQL no longer freezes the dashboard. "
        "Connect waits cap at 3 seconds, then the app backs off and keeps "
        "the UI live until the server is reachable again.",
    ]),
    ("2.9.368", "2026-09-21", [
        "Setup &amp; Info: each database engine now shows the full CREATE script "
        "(every logger table) on the right, with Copy SQL. "
        "<b>Setup Database</b> runs that same script. "
        "Connected / Disabled / not-found status sits left of the SQL, not centred.",
    ]),
    ("2.9.367", "2026-09-17", [
        "Launch: Linux software-GL path now skips EGL/DRM GPU probes so "
        "<code>./run-dashboard.sh</code> no longer prints "
        "“Failed to query DRM render node” / “GPUInfo not initialized”. "
        "Hardware GPU still opt-in via <code>POWERMODEL_WEBENGINE_GPU=1</code>.",
    ]),
    ("2.9.366", "2026-09-17", [
        "PV String Charge: dropped the empty lifetime pane so the instantaneous "
        "kW and today’s cumulative kWh charts fill the remaining height.",
    ]),
    ("2.9.365", "2026-09-17", [
        "Battery Analysis: <b>AC charge stop %</b> is a full spin (was clipped). "
        "<b>Save</b> keeps capacity, low-SOC threshold, and stop %. Capacity "
        "defaults from Growatt Live Status. Set on inverter still writes the "
        "MIX and now reads back to confirm.",
    ]),
    ("2.9.364", "2026-09-17", [
        "Battery Analysis: <b>Refresh every: … min</b> next to Fetch Battery "
        "History auto-reloads SOC/power on that interval (Off at 0). Remembered.",
    ]),
    ("2.9.363", "2026-09-17", [
        "PV String Charge: <b>Scan every (min)</b> next to Refresh now / Reload "
        "charts auto-reads live string power on that interval (Off at 0). The "
        "choice is remembered.",
    ]),
    ("2.9.362", "2026-09-17", [
        "PV String Charge is two charts: instantaneous kW (last 6 hours — "
        "each string, charge, solar forecast) on top, and kWh accumulating "
        "from midnight underneath (each string, both together, and a "
        "cumulative forecast). kW and kWh no longer share one mixed axis.",
    ]),
    ("2.9.361", "2026-09-17", [
        "Octopus Energy Data → Daily Import / Export: a second row under the "
        "daily charts shows <b>Monday–Sunday weeks</b> for import/export kWh "
        "and net £, each with a dashed weekly trend. Incomplete weeks at the "
        "ends of the fetch window are paler and not scaled up.",
    ]),
    ("2.9.360", "2026-09-17", [
        "PV String Charge left axis is real kW again: Grott string power "
        "(<code>pPv1</code>/<code>pPv2</code>) is converted from watts like "
        "total PV, and stored lots that kept dawn 10–50 W as kW are corrected "
        "on load so a ~40 kW spike cannot stretch the scale or today’s kWh.",
    ]),
    ("2.9.359", "2026-09-16", [
        "PV String Charge cards show each string’s <b>now</b> PV power (kW) and "
        "<b>today since 00:00</b> energy (kWh generated, plus estimated kWh into the "
        "battery). Totals use stored 2-minute lots from London midnight — not a 6-hour "
        "slice, and not estimated charge disguised as live output.",
    ]),
    ("2.9.358", "2026-09-16", [
        "Roof Layout: <b>Use clearest image</b> scans Google, Esri Live, Esri Wayback "
        "archives, and Sentinel-2 at the roof and switches to the sharpest tiles "
        "(clearest panel edges). The choice is remembered.",
    ]),
    ("2.9.357", "2026-09-16", [
        "PV String Charge: String 1 / String 2 are overlaid from zero (not stacked) "
        "so the higher string is visibly higher; fills 50% opaque, 1 px solid lines. "
        "Chart is a stored 6-hour window (<code>pv_string_charge</code> table) with a "
        "cumulative kWh line and the solar forecast overlay.",
    ]),
    ("2.9.356", "2026-09-16", [
        "Grott MQTT ignores Shine historical buffer dumps (<code>buffered: yes</code> "
        "or an old frame time) so midnight SOC/power cannot overwrite live cards. "
        "The Grott-lost tray alarm now says MQTT is still up and that the Shine "
        "stick often goes quiet ~11 minutes after it reconnects (hourly handshake "
        "with Growatt’s servers). Stale/recover edges are written to Connectivity "
        "history.",
    ]),
    ("2.9.355", "2026-09-15", [
        "Roof Layout map: hint, imagery date, and Leaflet attribution sit on one baseline 10 px above the bottom edge.",
    ]),
    ("2.9.354", "2026-09-15", [
        "Roof Layout: faces table adds a String column (inverter MPPT / DC string number); saved with the layout.",
    ]),
    ("2.9.353", "2026-09-15", [
        "Octopus Live / historic: Account, Import MPAN, and Export MPAN fields share one left edge (Import stacked above Export).",
    ]),
    ("2.9.352", "2026-09-15", [
        "Growatt Physical: System status shows decoded hybrid work mode (e.g. 5 — PV charging the battery) with a tooltip legend; Help explains the codes.",
    ]),
    ("2.9.351", "2026-09-15", [
        "Connectivity: Tasmota devices State menu adds “Go to Tasmota Tab” (opens the Tasmota Devices page).",
    ]),
    ("2.9.350", "2026-09-15", [
        "Connectivity State menu is context-aware: Show Alarms; Test Connection + Show Downtime for Octopus / Forecast / PVOutput / Wonderwatt / Databases; no Disable on Databases.",
    ]),
    ("2.9.349", "2026-09-15", [
        "Connectivity diagram: on degradation, a DEGRADED banner plus WARN badges explain what failed and what is carrying live (e.g. Hybrid → Growatt cloud when Grott is stale).",
    ]),
    ("2.9.348", "2026-09-15", [
        "Connectivity diagram: stop flashing red on warn/alarm links — solid tint; ALARM badge only for live AlarmMonitor hits.",
    ]),
    ("2.9.347", "2026-09-15", [
        "Connectivity diagram: live alarms and connectivity warn/bad show on boxes (badge + border) and related links; click a box for alarm text.",
    ]),
    ("2.9.346", "2026-09-15", [
        "Connectivity: visible reverse lanes inverter↔Cloud/GROTT/Modbus; dedicated Grott→EMQX flow (no longer hidden under the amber return).",
    ]),
    ("2.9.345", "2026-09-15", [
        "Grott MQTT: stop tearing down a live broker session when payloads are merely late; soft re-subscribe + reconnect watchdog; disconnect/reconnect history on Connectivity.",
    ]),
    ("2.9.344", "2026-09-15", [
        "Fix: Connectivity Status launch crash — restore missing State right-click handler after highlight refactor.",
    ]),
    ("2.9.343", "2026-09-15", [
        "Connectivity highlight: selecting a State row blinks only that service’s diagram edges (not every link touching the dashboard).",
    ]),
    ("2.9.342", "2026-09-15", [
        "Inverter write via Modbus is opt-in: Setup checkbox + Connectivity State right-click Enable/Disable Modbus inverter writes (default off).",
    ]),
    ("2.9.341", "2026-09-15", [
        "Connectivity Status: right-click State for Disable/Enable, Highlight on diagram (blink 2× thick), and Show history (connectivity_events + live alarms).",
    ]),
    ("2.9.340", "2026-09-15", [
        "Connectivity diagram: add direct Modbus → Dashboard data lane (kept alongside Modbus → EMQX bridge).",
    ]),
    ("2.9.339", "2026-09-15", [
        "Connectivity diagram: uncross Growatt API ↔ Dashboard and EMQX ↔ Dashboard (parallel nested lanes).",
    ]),
    ("2.9.338", "2026-09-15", [
        "Connectivity diagram: Energy Dashboard left-edge connectors are equally spaced with 12 px inset from top and bottom.",
    ]),
    ("2.9.337", "2026-09-15", [
        "Connectivity Wonderwatt dialog: render bold HTML correctly and edit/save/test the Advanced share link in-place.",
    ]),
    ("2.9.336", "2026-09-15", [
        "Connectivity diagram: AI Controller ↔ Dashboard and Databases ↔ Dashboard are drawn as two-way links (parallel lanes).",
    ]),
    ("2.9.335", "2026-09-15", [
        "Fix: PVOutput upload thread (and a few other log calls) passed one string to _log.info/warn which needs source + message — stopped the TypeError that could take the dashboard down after a successful upload.",
    ]),
    ("2.9.334", "2026-09-15", [
        "Connectivity diagram: Modbus feeds EMQX from the broker’s left edge "
        "(not the bottom).",
    ]),
    ("2.9.333", "2026-09-15", [
        "Connectivity diagram: AI Controller and Databases are half-width on one row with a link between them; Energy Dashboard is 50 px wider.",
    ]),
    ("2.9.332", "2026-09-15", [
        "Setup & Info: PVOutput / Wonderwatt / auto-refresh Save buttons left-align with the spin/field above; Test sits to the right of Save.",
    ]),
    ("2.9.331", "2026-09-15", [
        "Connectivity diagram: Octopus, PV forecast, PVOutput, and Wonderwatt sit in an even bottom row.",
    ]),
    ("2.9.330", "2026-09-15", [
        "Connectivity diagram: EMQX sits vertically between GROTT and Tasmota.",
    ]),
    ("2.9.329", "2026-09-15", [
        "Connectivity diagram: Growatt Inverter is 50% taller and vertically "
        "centred on the four source boxes (API / GROTT / Tasmota / Modbus); "
        "battery packs shift with it and show full serial numbers.",
    ]),
    ("2.9.328", "2026-09-15", [
        "Connectivity diagram: Tasmota ↔ EMQX is drawn as two-way Home LAN "
        "(tele/stat up, cmnd down) — not a one-way sensor feed.",
    ]),
    ("2.9.327", "2026-09-15", [
        "Community outputs: PVOutput.org live Add Status upload (Setup API "
        "key + System Id; throttled from Growatt snapshots) and Wonderwatt.com "
        "on the Connectivity diagram (share link — Wonderwatt reads Growatt "
        "cloud itself; no public upload API).",
    ]),
    ("2.9.326", "2026-09-15", [
        "Connectivity diagram redesigned as a planar layout: local sources "
        "(Growatt API, GROTT, Tasmota, Modbus) stack in the middle column in "
        "the same order their lines enter EMQX / the dashboard, so no data "
        "flow line crosses another.",
    ]),
    ("2.9.325", "2026-09-15", [
        "Connectivity diagram: Modbus now feeds EMQX (one-way into the "
        "broker) and sits directly under it; connection routes retuned so "
        "no line passes under a box.",
    ]),
    ("2.9.324", "2026-09-15", [
        "Connectivity diagram: only three Growatt connection methods — "
        "Growatt API, GROTT, and Modbus. Removed WiFi Direct and LAN Direct "
        "boxes from the architecture view.",
    ]),
    ("2.9.323", "2026-09-15", [
        "Connectivity architecture diagram: WiFi Direct and LAN/Modbus are "
        "local stubs only — Growatt API and Grott are drawn as independent "
        "peers from the inverter (no WiFi→API or LAN→Grott chain).",
    ]),
    ("2.9.322", "2026-09-15", [
        "Startup SEGV hardening: Qt WebEngine Chromium flags "
        "(disable-gpu / software GL) apply before any Qt import, and "
        "run-dashboard.sh exports the same defaults — stops "
        "“GPUInfo not initialized on GpuInfoUpdate” crashes. "
        "Set POWERMODEL_WEBENGINE_GPU=1 to use the GPU again.",
    ]),
    ("2.9.321", "2026-09-15", [
        "All radio buttons (every tab): white 1 px solid halo on the round "
        "indicator so they stay visible on the dark theme.",
    ]),
    ("2.9.320", "2026-09-15", [
        "Tasmota: Pin chart 2 max is still a lock, but the watts ceiling is "
        "editable (default 500 W) and remembered; drag / presets retune the pin.",
    ]),
    ("2.9.319", "2026-09-15", [
        "Status bar: centred CPU and memory for this dashboard process "
        "(one-core CPU %, resident RAM), updated every second.",
    ]),
    ("2.9.318", "2026-09-15", [
        "Roof Layout: imagery date chip sits bottom-centre so it no longer "
        "covers the map attribution (Esri / Google / Sentinel credits).",
    ]),
    ("2.9.317", "2026-09-15", [
        "Octopus Live cumulative chart: end-of-day Imp / PV / Cons totals sit "
        "below the lines (stacking downward when values collide); today's "
        "running tally is unchanged.",
    ]),
    ("2.9.316", "2026-09-15", [
        "Tasmota charts: drop fig.tight_layout in favour of fixed "
        "subplots_adjust margins so short panes no longer emit "
        "“Tight layout not applied” UserWarnings during redraw.",
    ]),
    ("2.9.315", "2026-09-15", [
        "Octopus Live cumulative labels: when Imp / Cons / PV values are close "
        "(far-right running tally), stack them vertically with Cons above Imp "
        "above PV so the text does not overlap.",
    ]),
    ("2.9.314", "2026-09-15", [
        "Battery Analysis: “Battery State of Charge” title is black with 5 px "
        "pad above the plot.",
    ]),
    ("2.9.313", "2026-09-15", [
        "Battery Analysis ΔSOC %/h: rolling ~15 min wall-clock slope (not "
        "1-sample ΔSOC/Δt spikes), physical bound by pack capacity, and a fixed "
        "right-hand axis of −100…+100 %/h.",
    ]),
    ("2.9.312", "2026-09-15", [
        "Pot. Issues chart: x-axis dates include weekday (e.g. Tue 09-15).",
    ]),
    ("2.9.311", "2026-09-15", [
        "Pot. Issues chart title: “Estimated vs Actual consumption — last N days "
        "in &lt;locale&gt;” (e.g. Chinnor).",
    ]),
    ("2.9.310", "2026-09-15", [
        "Octopus Live cumulative chart: labels end-of-day Imp / PV / Cons under "
        "each completed day's last point, plus running tallies for today at the "
        "latest sample.",
    ]),
    ("2.9.309", "2026-09-15", [
        "Octopus Live bottom chart: cumulative import / PV / consumption now "
        "resets at each London calendar midnight (was a single running total "
        "from the left edge of the window).",
    ]),
    ("2.9.308", "2026-09-14", [
        "Connectivity <b>Inverter write</b>: clearer status when Hybrid/Grott "
        "has an SN but no cloud API session — schedule writeback needs Growatt "
        "Live cloud Connect; local Modbus stays read-only.",
    ]),
    ("2.9.307", "2026-09-14", [
        "Growatt Physical: when Setup Local Modbus TCP is enabled, pack serials "
        "and module count are polled automatically in the background (Grott MQTT "
        "never publishes packs 2/3). Probe packs still forces an immediate read; "
        "Modbus TCP access is serialised so Setup/Connectivity probes do not "
        "collide with Growatt.",
    ]),
    ("2.9.306", "2026-09-14", [
        "Setup → Local Modbus: shows <b>Connected</b> / <b>Disconnected</b> "
        "beside the mode (updated by Test Modbus, Save, and a quiet probe after "
        "loading saved settings).",
    ]),
    ("2.9.305", "2026-09-14", [
        "Setup → Growatt inverter: LAN/Wi‑Fi, Modbus, EMQX and related params "
        "are loaded from disk on startup again (Save already wrote them; the "
        "form was stuck on empty/Disabled defaults after restart).",
    ]),
    ("2.9.304", "2026-09-14", [
        "Startup crash hardening: Saved toast and status bar updates always "
        "run on the GUI thread (deferred off the paint path); locale "
        "Nominatim workers no longer touch QSettings; Linux Qt WebEngine "
        "defaults to <code>--disable-gpu</code> (set "
        "<code>POWERMODEL_WEBENGINE_GPU=1</code> to opt back in); Connectivity "
        "architecture paint errors are caught instead of segfaulting.",
    ]),
    ("2.9.303", "2026-09-14", [
        "Connectivity architecture: battery pack cards top-align with the "
        "Growatt inverter top, bottom pack with the inverter bottom, and "
        "packs in between are equi-spaced.",
    ]),
    ("2.9.302", "2026-09-14", [
        "Growatt Physical: Battery pack serials height capped to at most 4 lines "
        "(one SN per line, no soft-wrap inflation that stretched the row).",
    ]),
    ("2.9.301", "2026-09-14", [
        "Banner Locale: reverse-geocode no longer sticks on “—” (failed lookups "
        "are not cached; dash is used as soon as it exists; Setup load and a "
        "startup retry refresh the place name; successful results persist).",
    ]),
    ("2.9.300", "2026-09-14", [
        "Setup → Solar installation: Latitude and Longitude always use 5 decimal "
        "places (display, edit, and Save), matching Forecasts / map picker.",
    ]),
    ("2.9.299", "2026-09-14", [
        "Green on-screen <b>Saved</b> flash whenever a status message reports a "
        "successful save (Setup / Growatt / Modbus / EMQX and other Save actions).",
    ]),
    ("2.9.298", "2026-09-14", [
        "Pot. Issues locale title prefers Setup solar Lat/Lon (QSettings) over a "
        "stale banner label, so the chart names the settlement for your saved "
        "installation coords — not an unrelated nearby town.",
    ]),
    ("2.9.297", "2026-09-14", [
        "Pot. Issues chart title uses the banner/Setup locale place name "
        "from your solar Lat/Lon instead of hardcoded “London”.",
    ]),
    ("2.9.296", "2026-09-14", [
        "Grott MQTT: empty <code>grott_mqtt_host</code> is healed from EMQX / "
        "Tasmota MQTT (including <code>mqadmin</code> auth), persisted, and "
        "re-applied after Setup loads so Hybrid no longer stays "
        "“MQTT disconnected”.",
    ]),
    ("2.9.295", "2026-09-14", [
        "Growatt Physical: Battery pack serials show one SN per line and the "
        "row expands so wrapped serials no longer crowd Faults / warnings.",
    ]),
    ("2.9.294", "2026-09-14", [
        "Setup → Growatt inverter: Local Modbus has its own Save; "
        "Save / Test Modbus align with the HTTP Open/Save/Test row above.",
    ]),
    ("2.9.293", "2026-09-14", [
        "Setup → Growatt inverter Save: EMQX Save now also applies the broker to "
        "Grott + Tasmota (no more empty <code>grott_mqtt_host</code> while EMQX "
        "is set). Empty EMQX user/pass fall back to Tasmota MQTT auth. Modbus TCP "
        "no longer rewrites port 8899 → 502 on mode select.",
    ]),
    ("2.9.292", "2026-09-14", [
        "Console logger: background threads no longer crash with "
        "<code>Signal source has been deleted</code> when logging during "
        "app exit/restart (Octopus Live GraphQL/REST fetch).",
    ]),
    ("2.9.291", "2026-09-14", [
        "Growatt Physical Probe packs: when pack-count registers are 0, count "
        "parallel modules from holding 1125+ pack serials (SPH via Modbus TCP "
        "8899) so the 3rd GBLI pack is visible — same SNs the inverter stores.",
    ]),
    ("2.9.290", "2026-09-14", [
        "Console: <b>RS485 heartbeat</b> pings the Setup Modbus target on a timer "
        "(default 30&nbsp;s): gateway TCP connect plus one holding-register read. "
        "One log line per beat (OK / gateway DOWN / inverter silent). Shares a "
        "lock with Test Modbus so the USR single-session port is not contended.",
    ]),
    ("2.9.289", "2026-09-14", [
        "Console: Auto-scroll now reliably follows new lines (deferred scrollbar "
        "update after HTML insert). Setup / Connectivity Modbus probes log under "
        "source <b>RS485</b> — INFO for connect/result, DEBUG for each register try.",
    ]),
    ("2.9.288", "2026-09-14", [
        "Setup → Test Modbus: the button no longer overlays the Serial device "
        "field. The probe is time-bounded (fails within ~18s) and always shows "
        "pass or fail instead of hanging on a silent RS485 gateway.",
    ]),
    ("2.9.287", "2026-09-14", [
        "Setup → Growatt Modbus: added <b>RTU over TCP</b> for USR/Waveshare "
        "RS485–Ethernet boxes in Transparent Mode (typically port 8899). Native "
        "<b>Modbus TCP</b> remains the path when the box is set to "
        "Modbus TCP&lt;=&gt;Modbus RTU on port 502. Probe packs follows the same "
        "LAN framing. USB RTU is only for a serial adapter on this PC.",
    ]),
    ("2.9.286", "2026-09-14", [
        "Octopus Energy Data → Daily Net Charge: the y-axis now grows to the "
        "tallest day’s spend instead of clipping at the £10/day budget. The "
        "dotted £10/day line stays as a reference; over-budget bars are drawn "
        "in full (red) with the true £ label on the tip.",
    ]),
    ("2.9.285", "2026-09-01", [
        "Forecasts: <b>Chart days</b> now clips both Agile and Solar axes to that "
        "many calendar days (today + previous N−1). The 16-day Forecast.Solar / "
        "Open-Meteo tail no longer stretches the chart past the selected window.",
    ]),
    ("2.9.284", "2026-09-01", [
        "Roof layout: <b>Flip all</b> reverses azimuth on every enabled face "
        "(+180°). Use when imported faces show NE/NW but the arrays face SE/SW.",
    ]),
    ("2.9.283", "2026-09-01", [
        "Roof layout: satellite map defaults to <b>Esri Live</b> (Google tiles "
        "often stay blank in Qt WebEngine). Choosing Google still works when "
        "tiles load; after repeated tile errors the view falls back to Esri.",
    ]),
    ("2.9.282", "2026-09-01", [
        "Grott / API Align: automatic interval is now configurable (default "
        "<b>120</b> min). Compare now reports clearly when the Growatt cloud "
        "API is <b>not contactable</b> (network/TLS) instead of looking like a "
        "quiet pause; scheduled runs still skip during rate-limit pauses.",
    ]),
    ("2.9.281", "2026-09-01", [
        "Alarms: system-tray re-notifications now back off while an alarm stays "
        "active — immediate, then 4× every 5&nbsp;min, 4× every 10&nbsp;min, "
        "4× every 30&nbsp;min, then hourly. Clearing the alarm resets the schedule.",
    ]),
    ("2.9.280", "2026-08-24", [
        "Growatt Live (Grott): a persistent display cache now keeps the last "
        "good load/PV/grid readings across Grott MQTT reconnects and session "
        "resets, so a sparse SOC-only frame can no longer blank the banner "
        "when the Open API fill-missing patch is rate-limited.",
    ]),
    ("2.9.279", "2026-08-24", [
        "Growatt Live (Grott): partial MQTT frames no longer wipe load, PV, grid, "
        "and other fields that were already shown or filled from the cloud API. "
        "Incoming Grott snapshots merge into the live bundle instead of "
        "replacing it, and API-fill markers are kept until Grott publishes "
        "those registers itself.",
    ]),
    ("2.9.278", "2026-08-24", [
        "Tasmota Devices: both device columns now keep all <b>8</b> rows visible "
        "with fully formed action buttons. Row height is computed per tree from "
        "actual widget geometry (not a stale viewport), action cell widgets are "
        "pinned to the row height, and size hints apply on every column so Qt "
        "cannot inflate rows to ~54&nbsp;px and show only four.",
    ]),
    ("2.9.277", "2026-08-24", [
        "Tasmota Devices: action buttons can no longer be squashed below their "
        "natural size, so <b>Probe / Web UI / Diagnose / Toggle</b> labels stay "
        "fully formed. Row height now derives from that button size, and each "
        "device table reserves space for a full column of <b>8</b> rows "
        "(previously only 4), so all 16 devices show without scrolling.",
    ]),
    ("2.9.276", "2026-08-24", [
        "Tasmota Devices: action buttons are sized to the row height "
        "(height − 2&nbsp;px) immediately on creation instead of overflowing "
        "until the next resize.",
    ]),
    ("2.9.275", "2026-08-23", [
        "Battery Analysis: removed misleading SOC chart rescaling. Added "
        "<b>AC charge stop %</b> + <b>Set on inverter</b> to write real "
        "<code>wchargeSOCLowLimit</code> to the Growatt MIX via cloud.",
    ]),
    ("2.9.274", "2026-08-23", [
        "Battery Analysis: <b>BMS SOC ceiling %</b> rescales measured SOC so an "
        "inverter plateau (e.g. 85&nbsp;%) displays as 100&nbsp;% on the chart. "
        "Set on the tab or in Setup → Battery Analysis defaults.",
    ]),
    ("2.9.273", "2026-08-23", [
        "Octopus Live: Live Demand zone label renamed from <b>output</b> to <b>Export</b>.",
    ]),
    ("2.9.272", "2026-08-23", [
        "Octopus Live: <b>Import</b> / <b>output</b> zone labels on the Live Demand "
        "chart are now visible at the left edge (light text at 20% opacity, above "
        "the filled areas).",
    ]),
    ("2.9.271", "2026-08-23", [
        "Octopus Live: Live Demand chart shows faint <b>Import</b> (at +2000&nbsp;W) "
        "and <b>output</b> (at −2000&nbsp;W) zone labels inside the plot area.",
    ]),
    ("2.9.270", "2026-08-23", [
        "Battery Analysis: fetches history automatically once on dashboard startup "
        "(same as <b>Fetch Battery History</b>).",
    ]),
    ("2.9.269", "2026-08-23", [
        "Tasmota Devices: action buttons (Probe, Web UI, Diagnose, Toggle) are "
        "now row height minus 2&nbsp;px so rows are visually separated.",
    ]),
    ("2.9.268", "2026-08-23", [
        "Growatt Live: when Grott MQTT is live and only the optional "
        "<b>fill-missing</b> API patch is rate-limited, status now shows "
        "<b>Data flowing / Connected</b> instead of incorrectly saying "
        "<b>Inverter offline</b>.",
    ]),
    ("2.9.267", "2026-08-23", [
        "Setup &amp; Info: Agile <b>Tariff code</b> and alarm <b>Sun-waste PV min</b> "
        "line up with <b>Max charge kW</b>. Export tariff no longer spans the "
        "grid (it was pushing pair-1 columns right); alarm checkboxes sit "
        "above the field row.",
    ]),
    ("2.9.266", "2026-08-23", [
        "Controls: <b>Connectivity Status</b> and <b>Grott Setup</b> are static "
        "blue tabs (like Command Sim and Setup &amp; Info), not green "
        "updateable tabs.",
    ]),
    ("2.9.265", "2026-08-23", [
        "Setup &amp; Info: Battery alarm Hold / Sun-waste row and Save button "
        "line up with Battery Analysis defaults above. Agile product/tariff "
        "fields use the same electric-blue background as spin boxes; Tariff "
        "code aligns with Max charge kW.",
    ]),
    ("2.9.264", "2026-08-23", [
        "Controls: <b>Grott Setup</b> tab — configure Grott / Hybrid telemetry, "
        "MQTT broker fields, Test and Save, plus a live feed status panel. "
        "Same settings as Setup &amp; Info.",
    ]),
    ("2.9.263", "2026-08-23", [
        "Battery Analysis Power Flows: fixed PV looking like it was drawn twice. "
        "Only one PV trace is plotted; the shadow was Grott readings and "
        "5-minute MIX slots interleaving when timestamps did not align. "
        "MIX-only rows within 2½&nbsp;min of a local reading are dropped.",
    ]),
    ("2.9.262", "2026-08-23", [
        "Grott / API Align: column widths are saved when you leave the tab or "
        "close the dashboard, restored on open, and kept after each compare run.",
    ]),
    ("2.9.261", "2026-08-23", [
        "Calculators: <b>Grott / API Align</b> compares the live Grott MQTT "
        "snapshot with one Growatt cloud live read. Automatic every 30 minutes "
        "(one Open API poll); <b>Compare now</b> is a one-shot. Rate-limit "
        "pauses still show Grott.",
    ]),
    ("2.9.260", "2026-08-22", [
        "Battery Analysis: overnight / unchanged Grott snapshots are drawn as "
        "holds again instead of grey <b>No data</b> voids. MIX 5-minute power "
        "is unioned onto the local SOC timeline; Low SOC event times show "
        "properly; the events table fills its pane.",
    ]),
    ("2.9.259", "2026-08-22", [
        "Tasmota device tables expand to fill the pane below the summary "
        "banner. Rows share that height instead of leaving a blank strip "
        "under the last device.",
    ]),
    ("2.9.258", "2026-08-22", [
        "Growatt / Setup Grott MQTT Test: connecting to the broker in ~6&nbsp;s "
        "is the pass. No JSON in that window is normal (Grott publishes on "
        "Shine packets, ~1&nbsp;min heartbeat / ~5&nbsp;min full status) and "
        "is no longer shown as a connection failure.",
    ]),
    ("2.9.257", "2026-08-22", [
        "Live alarms: Grott is a continuous feed. When GROTT MQTT or Hybrid is "
        "selected, MQTT disconnect (after ~20&nbsp;s) or stale inverter "
        "payloads raise a system-tray alarm even if Hybrid is still serving "
        "cloud data. A 15&nbsp;s watchdog checks this without waiting for the "
        "next Growatt update.",
    ]),
    ("2.9.256", "2026-08-22", [
        "Setup → Database Export: SQLite <b>Browse…</b> is back on the file "
        "row beside the path field. <b>Disabled</b> / <b>Database found</b> / "
        "<b>Database OK</b> indicators are centred horizontally again (SQLite, "
        "MySQL, and PostgreSQL).",
    ]),
    ("2.9.255", "2026-08-22", [
        "Setup → Database Export: SQLite <b>Browse…</b> is no longer parked at "
        "the far right of the file row — it sits on its own line, left-aligned "
        "with the <b>Ring buffers…</b> button. <b>Disabled</b>, <b>Database "
        "found</b>, <b>Database OK</b>, and the shared PostgreSQL summary line "
        "now share one left-aligned status column.",
    ]),
    ("2.9.254", "2026-08-22", [
        "Setup → Background collector: <b>Start/Restart</b> no longer always "
        "targets the boot (system) unit, which needs <code>sudo</code> and "
        "failed with <i>Not authorized</i> when pkexec/sudo were unavailable. "
        "When a user-session unit is installed it is preferred for UI control "
        "(no root); privilege failures on the boot unit fall back to the user "
        "copy automatically. Status hints and error dialogs now explain both "
        "paths.",
    ]),
    ("2.9.253", "2026-08-22", [
        "Roof Layout: the satellite map's QWebEngineView (a full Chromium "
        "browser) was created at app startup and stayed alive for the whole "
        "session — a two-day-old idle instance segfaulted inside "
        "<code>libQt6WebEngineCore</code> on 22&nbsp;Aug and this is the "
        "likely source of the startup <code>GPUInfo not initialized</code> "
        "warning. Chromium now starts lazily on first view of the map page "
        "(tab shown on the map, Satellite view button, Trace roof, edge "
        "picking); rings/centre/draw state set before that are queued and "
        "applied when the page loads.",
    ]),
    ("2.9.252", "2026-08-21", [
        "Growatt Live: fixed the perpetual \u201cOpen API paused "
        "(error_frequently_access)\u201d message. Root cause: in Cloud API mode "
        "the tab polled Open API V1 every 30&nbsp;s while Growatt only allows "
        "roughly one call per endpoint per 5&nbsp;min — and every rejected "
        "call (10012) re-armed the local 30-min pause, so it never counted "
        "down. All live V1 calls (cloud poll, Connect/Test probe, GROTT "
        "fill-missing) now share a 5-minute minimum poll interval and stop "
        "calling entirely while a pause is active, letting it expire for real.",
        "Growatt Live: the countdown label shows the true time to the next "
        "Open API poll instead of a 30&nbsp;s tick that silently failed; the "
        "banner refresh pill expects the 5-min V1 cadence so the tab is not "
        "flagged as late. Auth-result cache extended 3→10&nbsp;min (a fresh "
        "authenticate costs 3+ V1 calls). Legacy password-login sessions and "
        "GROTT MQTT are unaffected.",
    ]),
    ("2.9.251", "2026-08-21", [
        "Battery Analysis: SOC colour fill no longer double-paints. The "
        "below-threshold red shade used to sit on top of the red under-curve "
        "band (0→threshold over 0→SOC), producing dark overlapping patches; "
        "it now shades only the <i>deficit</i> between the SOC curve and the "
        "threshold line.",
        "Battery Analysis: windows where the database simply has no telemetry "
        "(e.g. the frozen-feed outage 18&nbsp;Aug&nbsp;18:28 → "
        "20&nbsp;Aug&nbsp;00:16) are now drawn as grey vertical bands labelled "
        "\u201cNo data — interpolated between endpoints\u201d on both charts. "
        "The traces inside a band are straight lines joining the last and "
        "next real sample, not measurements.",
        "Battery Analysis: interior NaN holes (masked frozen runs, impossible "
        "SOC jumps) are interpolated for display so fills don't fragment, and "
        "gap detection adapts to the actual sample cadence (6× median "
        "spacing, ≥20 min).",
    ]),
    ("2.9.250", "2026-08-21", [
        "Battery Analysis: the chart was still lying because frozen "
        "<code>growatt_readings</code> SOC was overlaid onto varying MIX power "
        "— the freeze mask never matched, so you got vertical SOC cliffs "
        "(64%→37% in 3&nbsp;min) and multi-hour flat plateaus. History now "
        "starts from cleaned readings (collapse exact duplicates, mask "
        "≥12&nbsp;min freezes, blank physically impossible SOC jumps), then "
        "optionally densifies power from MIX.",
        "SOC chart fills are under the curve (not floating mid-air bands); "
        "day-range radios re-fetch immediately; daily kWh totals use London "
        "calendar days on UTC-naive timestamps.",
    ]),
    ("2.9.249", "2026-08-21", [
        "PostgreSQL <code>growatt_readings</code>: auto-refresh was re-inserting "
        "the same frozen GROTT snapshot under a new wall-clock timestamp every "
        "tick — Aug&nbsp;19 alone has 472 bit-identical rows (SOC 10%, load "
        "1.198&nbsp;kW, PV 0.007&nbsp;kW, grid −1.190&nbsp;kW). "
        "<code>DataLogger.log_growatt</code> now skips unchanged payloads, and "
        "live logging refuses stale GROTT snapshots.",
        "Battery Analysis: mask frozen identical runs (≥20&nbsp;min) to NaN so "
        "Power Flows / SOC show a gap instead of a fake flat day, and stop "
        "interpolating SOC across those blanks.",
    ]),
    ("2.9.248", "2026-08-21", [
        "Battery Analysis: measured-SOC chart draw crashed with "
        "<code>None is not a valid value for color</code> — "
        "<code>set_title(..., color=None)</code> when the trace was not "
        "reconstructed. Use the theme text colour instead.",
    ]),
    ("2.9.247", "2026-08-21", [
        "Battery Analysis: a Growatt cloud MIX-chart fetch used to skip "
        "<code>growatt_readings</code> entirely, so the SOC chart was rebuilt "
        "from charge/discharge only — it pinned at 0% for hours, painted a "
        "full-height red \"low SOC\" band across half the plot, and invented "
        "an 11&nbsp;h event while live GROTT on the banner still showed a real "
        "SOC. The tab now always loads local readings, overlays measured SOC "
        "onto MIX power (15&nbsp;min nearest match), and falls back to "
        "readings alone when that is all that exists.",
        "Reconstructed (coulomb-counted) SOC no longer feeds the Low SOC "
        "Events table; the under-threshold highlight only shades 0→threshold "
        "instead of the full plot height; reconstruction uses actual sample "
        "spacing instead of a fixed 5&nbsp;min step.",
    ]),
    ("2.9.246", "2026-08-20", [
        "Growatt GROTT: a <b>stale</b> snapshot no longer counts as a completed "
        "refresh. <code>_apply_grott_snapshot_if_needed</code> returned True for "
        "a cached-but-old payload, so <code>refresh_data</code> and "
        "<code>_refresh_grott_data</code> both returned early and the "
        "resubscribe path never ran — once the feed went quiet the tab sat on "
        "frozen values indefinitely, even when the user pressed Refresh. Stale "
        "snapshots are still displayed (with the age in the status line) but "
        "now fall through to a resubscribe, rate-limited to one attempt per "
        "60&nbsp;s, and no longer fire the downstream fresh-data callbacks that "
        "kept the tab bar green.",
        "Live tabs keep their own cadence again. The per-tab "
        "<code>_auto_timer_interval_override_ms</code> hook was still honoured "
        "by <code>apply_auto_refresh_from_params</code> but no tab set it any "
        "more, so Octopus Live had silently dropped to the shared interval "
        "(up to 600&nbsp;s) — it is back to 60&nbsp;s. Tasmota's poll interval "
        "now comes from the Tasmota tab: the shared cycle no longer overwrites "
        "<code>tasmota/poll_interval_seconds</code> and its spin box.",
        "Banner refresh pill is honest about staleness: it reports the "
        "<b>oldest</b> live source instead of the newest (a 1&nbsp;Hz MQTT feed "
        "used to mask a tab that had not updated for hours), scores each source "
        "against its own expected cadence via a new "
        "<code>live_refresh_expectation()</code> hook, excludes sources that are "
        "switched off from the completeness score, names late sources on line 2, "
        "and lists per-source age / cadence / state in the tooltip.",
        "Tab-freshness repaints are coalesced: <code>mark_tab_fresh</code> now "
        "only records the timestamp and lets the 1&nbsp;Hz tick restyle the tab "
        "bar, instead of restyling on every MQTT packet from every source.",
    ]),
    ("2.9.245", "2026-07-03", [
        "Growatt fill-missing: reuse the live bundle from the auth probe instead "
        "of calling <code>sph_energy</code> a second time — the duplicate call "
        "was tripping Growatt’s rate limit and leaving load/grid as <b>--</b>.",
    ]),
    ("2.9.244", "2026-07-03", [
        "Growatt GROTT + fill-missing: when Grott omits grid registers, Grid "
        "Power and the live banner show <b>--</b> instead of a false 0.00 kW. "
        "Fill-missing no longer burns its retry interval while Open API is "
        "rate-limited; the link status and status bar explain the pause and "
        "retry automatically when the pause expires (GROTT-only mode included).",
    ]),
    ("2.9.243", "2026-07-02", [
        "Growatt GROTT MQTT: fixed circular load/grid estimation. The dashboard "
        "no longer derives house load from an estimated grid value, and no "
        "longer derives grid from an estimated load. If Grott publishes neither "
        "real load nor real grid, load stays unknown instead of incorrectly "
        "showing 0.00 kW while the battery is charging.",
    ]),
    ("2.9.242", "2026-07-02", [
        "Growatt GROTT MQTT: fixed missing/incorrect house load when Grott "
        "splits PV, grid, and battery across separate MQTT messages — load is "
        "now back-solved on the merged snapshot (symmetric to the existing "
        "grid backfill) when a real grid reading is available. Banner "
        "load no longer shows “None”; estimated load gets a tooltip.",
    ]),
    ("2.9.241", "2026-07-02", [
        "Connectivity: diagram and status rows now reflect Growatt "
        "<b>Hybrid</b> and <b>Fill missing Grott with API</b> — GROTT box "
        "subtitle, cloud API fallback label, amber Hybrid↔API link, Grott "
        "health on the MQTT path, EMQX/Growatt volume hints, and summary "
        "footer source line.",
    ]),
    ("2.9.240", "2026-07-02", [
        "Growatt telemetry: new <b>Hybrid</b> source (Grott first, cloud API "
        "fallback when Grott is stale) plus a separate "
        "<b>Fill missing Grott data with API</b> checkbox that patches "
        "individual registers Grott omitted without switching the whole "
        "source. API-patched fields render in amber (text or 1 px border on "
        "physical rows). Setup and the Growatt tab stay in sync via "
        "params/growatt_telemetry_source.",
    ]),
    ("2.9.239", "2026-07-02", [
        "Growatt Live Status: fixed Refresh Page / Refresh All not updating "
        "the Growatt tab — the global refresh hook called growatt_tab.fetch_data "
        "but the tab only exposed refresh_data, so the status bar reported the "
        "method as unavailable. Added fetch_data as an alias. GROTT MQTT: a "
        "signed grid-power register stuck at 0.00 (common on some MIX layouts) "
        "no longer blocks the estimated grid backfill, so PV / Battery / Load / "
        "Grid can update correctly again when the real grid register isn't live.",
    ]),
    ("2.9.238", "2026-07-02", [
        "Help: split the monolithic content/help.py into one file per tab under "
        "content/help/ (e.g. shadow_trial.py, growatt.py). Each module exports "
        "TAB_CLASS + HELP_TEXT; the package auto-discovers them for the global "
        "status-bar Help button. Adding help for a new tab is now 'drop a file "
        "in content/help/' — see content/help/_template.py. help_text_for() "
        "helper added for programmatic lookup.",
    ]),
    ("2.9.237", "2026-07-02", [
        "New 'Shadow Trial' tab: benchmark the inverter's live controller "
        "(e.g. Growatt's Smart Scheduling AI) against the dashboard Optimiser "
        "without ever writing to the inverter. Every night at ~23:35 the "
        "Optimiser plan for tomorrow is frozen to the database using only "
        "what was knowable at that moment; after each day completes, a "
        "four-way scoreboard compares Actual (Octopus meter data), Shadow "
        "(frozen plan replayed against realised load/PV), a dumb "
        "self-consumption Baseline, and the hindsight-perfect DP ceiling, "
        "with per-day and cumulative capture ratios. While the trial runs, "
        "the Optimiser / Smart Advisor inverter write buttons show an extra "
        "guard warning (toggleable) so a habit click can't contaminate the "
        "benchmark. New tables: optimiser_shadow_plans / "
        "optimiser_shadow_scores (SQLite/MySQL/PostgreSQL).",
        "DataLogger: fixed ALL database logging silently failing — the "
        "growatt_mix_chart index DDL (a tuple of statements) was passed "
        "directly to execute(), which raised on every connection open and "
        "aborted every subsequent write on SQLite, MySQL and PostgreSQL "
        "alike. Readings now log again.",
    ]),
    ("2.9.236", "2026-07-01", [
        "Growatt Live Status (GROTT MQTT): fixed PV/Load/Grid still showing "
        "'--' after restarting the dashboard. Some Grott setups spread PV, "
        "battery, and load across separate cyclical MQTT messages rather than "
        "one combined frame, so the 2.9.235 grid-balance estimate — which only "
        "looked at a single incoming message — often never saw all three "
        "together and stayed blank. The estimate now runs on the combined "
        "live snapshot instead, so it fires as soon as PV, battery, and load "
        "have each arrived at least once, however many messages that takes. "
        "Also fixed a related bug where a PV-only (or battery-only) message "
        "could fabricate a bogus Load figure by assuming grid/battery were "
        "zero; Load is now only back-solved when the same message actually "
        "carries grid data too.",
    ]),
    ("2.9.235", "2026-07-01", [
        "Growatt Live Status (GROTT MQTT): fixed Battery/PV/Grid/Load power not "
        "adding up. Some Grott layouts (seen on certain MIX/hybrid inverters) "
        "never publish a grid-power register at all, so Grid Power silently "
        "defaulted to 0.00 kW even while charging/load clearly required grid "
        "import. When grid data is completely absent but PV/battery/load are "
        "known, Grid Power is now back-solved from the power balance and "
        "labelled '(est.)' with an explanatory tooltip; it reverts to the real "
        "reading automatically once Grott actually publishes one. Also fixes "
        "the same numbers in the top banner and in logged `growatt_readings` "
        "used by Battery Analysis/Optimiser.",
    ]),
    ("2.9.234", "2026-07-01", [
        "Agile Spot Prices: Today and Tomorrow now both show by default, "
        "stacked (Today above, Tomorrow below) instead of a toggle — no need "
        "to click through to see both. Slot cell size unchanged.",
    ]),
    ("2.9.233", "2026-07-01", [
        "New 'Agile Spot Prices' tab: a colour-coded grid of Octopus Agile "
        "half-hourly slot prices for Today/Tomorrow, styled after Octopus "
        "Energy's own Agile schedule screen, with an Import/Export toggle and "
        "a price-band legend. Reuses the Agile data already fetched by the "
        "Forecasts tab rather than issuing extra API calls.",
    ]),
    ("2.9.232", "2026-06-29", [
        "Battery Analysis: no longer blocks with 'Connect to Growatt first' when "
        "GROTT MQTT is the selected telemetry source. If Growatt cloud MIX-chart "
        "history is unavailable, the tab now falls back to stored local "
        "`growatt_readings` written by the live GROTT/Growatt feed and reconstructs "
        "PV, charge, discharge, grid import/export, load, and SOC for the same "
        "charts.",
        "Smart Advisor inverter settings/write controls now explicitly say that "
        "Growatt cloud credentials are only required for cloud-side inverter "
        "reads/writes; GROTT MQTT remains the live telemetry source.",
    ]),
    ("2.9.231", "2026-06-26", [
        "Growatt Live Status: aligned the default GROTT MQTT topic with the actual "
        "Grott server configuration (`energy/growatt`). Existing saved `grott/#` "
        "settings now subscribe to both `grott/#` and `energy/growatt` for "
        "backwards compatibility.",
        "Growatt Live Status: fixed parsing of standard Grott JSON published on "
        "`energy/growatt`, including PV string watts, SOC, battery charge/discharge, "
        "grid voltage/frequency, daily/lifetime PV totals, and estimated house load "
        "when Grott does not publish an explicit load field.",
    ]),
    ("2.9.230", "2026-06-26", [
        "Growatt Live Status: fixed Refresh Now behavior when GROTT MQTT is the "
        "selected source. The button now explicitly applies the latest cached "
        "GROTT snapshot, reports its age/topic, and resubscribes to the GROTT MQTT "
        "feed when the cached snapshot is stale or missing so the action is visible "
        "and useful.",
    ]),
    ("2.9.229", "2026-06-26", [
        "Growatt Live Status: broadened GROTT MQTT payload normalisation so standard "
        "Grott fields such as pvpowerout, pvgridpower, pvloadpower, pvgridvoltage, "
        "pvfrequentie, vbatdsp, batterytype, pvstatus, and standard energy counters "
        "are mapped into the live Growatt cards and physical telemetry fields.",
        "Growatt Live Status: GROTT payload model hints (for example pvmodel / "
        "inverterModel and batteryModel) can now populate the inverter and battery "
        "model labels when the cloud API is not being used.",
    ]),
    ("2.9.228", "2026-06-26", [
        "Growatt Live Status: throttled expensive downstream callbacks from high-rate "
        "GROTT MQTT updates. The visible live cards still update for each accepted "
        "snapshot, but DB logging, connectivity refreshes, and advisory/banner fan-out "
        "now run at a lower cadence (or immediately on manual refresh) so GROTT traffic "
        "does not overload the UI thread.",
    ]),
    ("2.9.227", "2026-06-26", [
        "Growatt Live Status: the credentials box is now a telemetry-source toggle "
        "(Growatt Cloud API / GROTT MQTT) that mirrors the Setup tab. The Save button "
        "was removed and a new Setup button jumps straight to the Setup tab's Growatt "
        "inverter section.",
        "Setup → Growatt: renamed the section from 'Growatt inverter (local network)' "
        "to 'Growatt inverter' and added a 'Growatt cloud login (server.growatt.com)' "
        "subsection with Username, Password, API key, and Serial fields, saved to the "
        "shared Growatt credential settings.",
        "Growatt credentials entered on Setup are picked up by the Live Status page "
        "immediately on save and whenever the page is shown.",
    ]),
    ("2.9.226", "2026-06-26", [
        "Tasmota Devices: fixed action-button labels (notably 'Diagnose') being "
        "clipped on both sides by the green primary-button padding. The compact "
        "padding override now uses a higher-specificity attribute selector so it "
        "actually wins, and the button width accounts for the exact padding so no "
        "label is obscured.",
    ]),
    ("2.9.225", "2026-06-26", [
        "Tasmota Devices: fixed a KeyError ('power_W') crash introduced with the "
        "relay-state fix. Rows that carry only relay state (learned before any "
        "energy telemetry) are now created with a complete, zeroed reading, and the "
        "power banner, table cells, and bar chart read energy fields defensively.",
    ]),
    ("2.9.224", "2026-06-26", [
        "Tasmota Devices: the Name column now sizes to the longest device name "
        "actually shown, so it is as narrow as possible while keeping every name "
        "fully visible instead of hogging spare width.",
        "Tasmota Devices: the Actions column is correspondingly wider with larger, "
        "more comfortable action buttons, and the reclaimed width is shared across "
        "the data columns.",
        "Tasmota Devices: fixed the Toggle switch state showing as greyed/unknown in "
        "MQTT mode. Relay state is now parsed from tele/STATE and stat/RESULT (not "
        "just stat/POWER, which Tasmota only sends on a state change), and the app "
        "queries each device's POWER state on first sight so the switch shows ON/OFF "
        "immediately.",
    ]),
    ("2.9.223", "2026-06-26", [
        "Tasmota Devices: tidied the per-row action buttons. The table and action "
        "buttons now use a legible 8pt font with even padding so Probe / Web UI / "
        "Diagnose / Toggle labels never clip.",
        "Tasmota Devices: replaced the cramped vertical separator before Toggle with a "
        "clean fixed gap, set uniform 4px button spacing, and recalculated the Actions "
        "column to fit the row exactly so the layout stays neat and aligned.",
    ]),
    ("2.9.222", "2026-06-25", [
        "Setup → Growatt telemetry source: fixed overlapping controls by moving Save source "
        "and Test Grott MQTT onto their own row beneath the username/password fields.",
        "Setup → Growatt telemetry source: gave the source buttons fixed widths and extra "
        "row spacing so they no longer collide with the GROTT credentials fields.",
    ]),
    ("2.9.221", "2026-06-25", [
        "Tasmota Devices: device table columns now use a proportional width allocator "
        "based on the current table viewport. The Name column receives most spare width, "
        "numeric columns stay compact, and the Actions column is protected so all four "
        "buttons and their labels remain visible.",
        "Tasmota Devices: column widths are recalculated on refresh and window resize, "
        "instead of relying on saved/auto content widths that could waste space or clip text.",
    ]),
    ("2.9.220", "2026-06-25", [
        "Tasmota Devices: made the device table text sizing explicit and compact, rather "
        "than depending on the desktop default font. The table and action buttons now use "
        "a 7pt font and the Actions column is recalculated from that actual rendered text "
        "so button labels remain fully visible.",
    ]),
    ("2.9.219", "2026-06-25", [
        "Tasmota Devices: rebalanced the page layout so device tables use only their "
        "content height instead of holding large blank areas, and the freed vertical "
        "space is given to the charts.",
        "Tasmota Devices: tightened the chart canvas layout and margins so Current Power "
        "Draw and Power History use more of the available plotting area.",
    ]),
    ("2.9.218", "2026-06-25", [
        "Tasmota Devices: removed the visible Power History DB status blurb from the "
        "bottom-right chart toolbar while keeping the internal history DB status tracking.",
        "Tasmota Devices: reduced the device table font by two points and applied the same "
        "smaller font to the in-row action buttons.",
    ]),
    ("2.9.217", "2026-06-25", [
        "Tasmota Devices: removed the remaining horizontal padding from the row action "
        "buttons so Probe, Web UI, Diagnose, and Toggle can use the full button width "
        "for text instead of clipping behind internal padding.",
    ]),
    ("2.9.216", "2026-06-25", [
        "Tasmota Devices: reduced the per-row action button widths evenly and tightened "
        "the internal action-row spacing so Probe, Web UI, Diagnose, and Toggle remain "
        "fully visible in both device tables.",
        "Tasmota Devices: the Actions column is re-applied after saved column widths are "
        "restored, preventing old persisted widths from clipping the buttons.",
    ]),
    ("2.9.215", "2026-06-22", [
        "Growatt Live Status: debugged the page becoming stuck in a Growatt Open API "
        "pause state. The Open API V1 rate-limit guard now only applies when an API "
        "token is actually being used, so it no longer blocks legacy username/password "
        "login.",
        "Growatt Live Status: GROTT MQTT is checked before cloud rate-limit handling on "
        "startup, so selecting GROTT as the telemetry source cannot be blocked by a "
        "cloud Open API pause.",
        "Growatt Live Status: Open API pause messages now show the real remaining time "
        "from settings and automatically clear stale/expired pause keys instead of leaving "
        "the page stuck on a red paused status.",
    ]),
    ("2.9.214", "2026-06-21", [
        "Setup → Database Export: each backend row (SQLite, MySQL, PostgreSQL) now has "
        "its own Save DB Config, Test Connection, Setup Database, and Ring buffers buttons.",
        "Per-row Test and Setup actions target that backend's fields directly, even if its "
        "automatic-logging checkbox is currently off. The checkbox still controls whether "
        "that backend participates in automatic logging.",
    ]),
    ("2.9.213", "2026-06-21", [
        "Setup → Database Export: tightened the SQLite file field so it ends at the "
        "same right edge as the host/port field group beneath it, instead of stretching "
        "across the page.",
        "Database status text is now a consistent right-side column for SQLite, MySQL, "
        "and PostgreSQL. Disabled backends show a vertically centred red 'Disabled' "
        "label, keeping status text left-aligned with the other database status panels "
        "and clear of the input fields.",
    ]),
    ("2.9.212", "2026-06-21", [
        "Setup → Growatt inverter (local network): cleaned up section C. It is now "
        "an explicit Growatt telemetry source selector with mutually exclusive choices: "
        "Growatt Cloud API or GROTT MQTT.",
        "GROTT is no longer described or treated as a fallback. When GROTT MQTT is selected, "
        "the Growatt live tab uses fresh MQTT snapshots as the primary source; when Growatt "
        "Cloud API is selected, GROTT fields are inactive and MQTT data is not overlaid onto "
        "cloud telemetry.",
    ]),
    ("2.9.211", "2026-06-21", [
        "Setup → Growatt inverter (local network): added a right-aligned local connection "
        "status badge. It shows green '✓ Connected' after a successful Web UI TCP or "
        "Modbus probe, red '✗ Not Connected' when not configured or the probe fails, and "
        "a blue testing state while a probe is running.",
    ]),
    ("2.9.210", "2026-06-21", [
        "Connectivity Status diagram: rewritten as a faithful port of the reference React "
        "architecture diagram. Nodes now use the exact 1100x500 blueprint coordinates mapped "
        "into the widget, and the two storage cards are merged back into a single "
        "'Databases & Exports' node.",
        "Connectors now use the React Bezier routing: control points extend perpendicular to "
        "each box edge, so every link leaves/enters its node cleanly and no longer cuts across "
        "other boxes. Straight links and the GROTT↔EMQX curve match the original spec exactly.",
    ]),
    ("2.9.209", "2026-06-21", [
        "Setup → Background collector: fixed the row layout. The Broker URL field now sits "
        "compactly on the left, the Save/Test buttons are a fixed proportional size (default "
        "QPushButton policy let them balloon to fill surplus width), and a trailing spacer "
        "absorbs slack so the row no longer overflows into a horizontal scroll bar.",
        "Applied the same fixed-width treatment to the collector control buttons "
        "(Refresh, Start/Restart, Stop, Boot Start) and the EMQX routing row for a consistent look.",
    ]),
    ("2.9.208", "2026-06-21", [
        "Connectivity Status diagram: rebuilt the layout so the dashboard spans the full height "
        "of the left-hand source stack. Every source (WiFi Direct, LAN Direct, Tasmota, Octopus, "
        "PV forecast, EMQX, Growatt API) now feeds straight into its own dashboard row.",
        "All connectors now use a single drawing routine — they render straight when aligned and "
        "only bow gently when off-axis — and route through clear vertical lanes so no connector "
        "passes underneath a box.",
        "Inactive/degraded links stay faintly visible so the topology always reads clearly.",
    ]),
    ("2.9.207", "2026-06-21", [
        "Connectivity Status diagram: connector routing is now adaptive — links are straight by "
        "default and only curve when endpoints are clearly off-axis, keeping the diagram cleaner "
        "while still avoiding awkward misaligned diagonals.",
    ]),
    ("2.9.206", "2026-06-21", [
        "Connectivity Status diagram: Databases and Exported data cards are now "
        "shorter and placed side-by-side on the same row (instead of stacked), "
        "making better use of horizontal space.",
    ]),
    ("2.9.205", "2026-06-21", [
        "Connectivity Status diagram: all connectors are now rendered as curved Bezier links.",
        "Reverse control connectors are now explicitly drawn in amber (active + idle variants), "
        "matching the architecture style used in the design reference.",
    ]),
    ("2.9.204", "2026-06-21", [
        "Connectivity Status diagram: increased vertical distribution of the left-side "
        "source boxes (WiFi Direct, LAN Direct, Tasmota, Octopus, PV forecast) so the "
        "panel uses more of the available height; inverter anchor is re-centered to stay "
        "aligned with the upper-left paths.",
    ]),
    ("2.9.203", "2026-06-21", [
        "Connectivity Status architecture panel refreshed to a React-style visual layout "
        "(gradient canvas, subtle grid, grouped node cards, richer routing paths) while "
        "keeping live RAG flow colouring and click-through detail dialogs.",
        "Diagram now explicitly shows Growatt API, GROTT, EMQX, AI Controller, "
        "Energy Dashboard, Databases, and Exported data with forward data links and "
        "reverse control links (including idle/defunct control paths as muted dashed lines).",
    ]),
    ("2.9.202", "2026-06-20", [
        "Setup & Info → Growatt inverter (local network): added an EMQX routing profile "
        "banner and controls for host/port (default 222.20.20.212:1883) to reflect that "
        "Tasmota, WiFi Direct, and LAN Direct are now routed via EMQX.",
        "New “Apply EMQX route” button copies that host/port into both Growatt Grott MQTT "
        "and Tasmota MQTT settings, persists to QSettings, syncs open tab fields immediately, "
        "and refreshes Connectivity Status.",
    ]),
    ("2.9.201", "2026-06-14", [
        "Setup & Info (and all spin fields): fill 15% lighter grey than the panel "
        "(was 10%).",
    ]),
    ("2.9.200", "2026-06-14", [
        "Battery Analysis: 5-minute MIX chart data stored in growatt_mix_chart "
        "(PostgreSQL/SQLite/MySQL) on fetch; loads from DB when cloud fetch fails.",
        "Battery Analysis: Open API V1 uses sph_energy_history (mix_detail fallback).",
        "energy_collector service: upserts today+yesterday chart slots every 15 min by "
        "default; supports POWERMON_GROWATT_TOKEN; live poll uses shared V1 mapping.",
    ]),
    ("2.9.199", "2026-06-14", [
        "Growatt Live: fix Load Power showing 0 kW on token (Open API V1) connect — "
        "derive house load from grid import/export, PV, and battery when the API omits "
        "pLocalLoad; sum PV strings when total ppv is zero.",
    ]),
    ("2.9.198", "2026-06-14", [
        "Ring buffers: clicking Databases / Exported data in Connectivity Status now "
        "opens the full per-table controls (Activate, max rows/age/size, Save, Prune) "
        "instead of a read-only summary.",
        "Ring buffers: new Ring buffers… buttons on Connectivity Status and "
        "Setup & Info → Database backends.",
    ]),
    ("2.9.197", "2026-06-14", [
        "Growatt Live: fix live refresh after token connect (_growatt_first_nonempty "
        "key tuples — sph_energy / sph_detail mapping no longer raises TypeError).",
        "Connectivity Status: architecture diagram adds LAN Direct (Modbus TCP/RTU) "
        "and WiFi Direct (inverter web UI port) pills with RAG status and background probes.",
    ]),
    ("2.9.196", "2026-06-14", [
        "Growatt Live: API token connect now fetches live data via Open API V1 "
        "(sph_energy / sph_detail) instead of legacy mix_* endpoints that fail "
        "after token login.",
        "Growatt Live: Connection Status text scales down for long messages (507 rate "
        "limit, Open API errors) so they fit in the Device Information column.",
        "Growatt Live: token connect failures show Growatt Open API error code and "
        "detail instead of the generic \"Error during getting plant list\".",
        "Growatt Live: API token help points to server.growatt.com → Settings → "
        "Account Management → API Key (ShinePhone Me → API Token noted as alternate).",
        "Setup & Info: first-column field labels no longer truncate — full measured "
        "label width, tighter spin-box padding, reduced label↔field grid gaps.",
        "Setup & Info: History dialog opens again (HistoryDialog import).",
    ]),
    ("2.9.195", "2026-05-25", [
        "Setup & Info -> Flat tariff import/export boxes now sit 10% above the "
        "panel background and use chevron stepper arrows.",
    ]),
    ("2.9.194", "2026-05-25", [
        "Auto-refresh: restored Octopus Live (60 s) and Tasmota (30 s) live-tab "
        "cadence overrides, and unexpected background refresh errors now clear "
        "the busy state so later auto-refresh ticks keep working.",
    ]),
    ("2.9.193", "2026-05-22", [
        "Map location picker: what3words is bidirectional — Look up moves the pin; "
        "moving the pin updates the three words (when an API key is set).",
    ]),
    ("2.9.192", "2026-05-22", [
        "All tabs: line edits, spin/combo boxes, and read-only text panels use the same "
        "subtle input shading as Command Sim (Console/Export logs stay main background).",
    ]),
    ("2.9.191", "2026-05-22", [
        "Forecasts charts: dark theme; 7-day Agile window; solar panel shows measured "
        "PV and stored planned forecasts for each day in the chart range.",
    ]),
    ("2.9.190", "2026-05-22", [
        "Set location…: embedded Leaflet map on by default when PySide6-WebEngine "
        "is installed (opt out with POWERMODEL_MAP_WEBENGINE=0).",
    ]),
    ("2.9.189", "2026-05-22", [
        "Combo boxes: visible down-chevron; drop-down zone flush with the field "
        "(no divider). Spin steppers match (chevrons, no seam).",
    ]),
    ("2.9.188", "2026-05-22", [
        "Text fields and dialogue panels: subtler fill (~6% / ~10% above app "
        "background) and softer borders so inputs do not overpower the UI.",
    ]),
    ("2.9.187", "2026-05-22", [
        "Text fields and spin boxes: fill 20% lighter than the panel behind them "
        "(group boxes stay 20% above app background).",
    ]),
    ("2.9.186", "2026-05-22", [
        "Spin boxes: visible chevron up/down steppers on the dark theme "
        "(Setup, Optimiser, and all QSpinBox / QDoubleSpinBox fields).",
    ]),
    ("2.9.185", "2026-05-22", [
        "Locale bar (above tabs): place name, lat/lon, CRS, and Set location…; "
        "wired to ForecastsTab reverse-geocode and map picker.",
    ]),
    ("2.9.184", "2026-05-22", [
        "Optimiser charts: +20px gap between dispatch and price panels; top-panel "
        "time-axis tick labels forced white.",
    ]),
    ("2.9.183", "2026-05-22", [
        "Status bar: <b>Refresh Page</b> re-runs the refresh hook for the "
        "current tab only (left of Refresh All).",
    ]),
    ("2.9.182", "2026-05-22", [
        "Removed Simulation Engine tab (redundant with Battery Simulation and "
        "other planning modules).",
    ]),
    ("2.9.181", "2026-05-22", [
        "Forecasts: Agile tariffs on row 1; solar location + Set location on row 2; "
        "Save parameters moved into the location dialog.",
    ]),
    ("2.9.180", "2026-05-22", [
        "Fix FreshnessTabBar paintEvent crash: use SE_TabBarTabText (PySide6) "
        "and always end the QPainter.",
    ]),
    ("2.9.179", "2026-05-22", [
        "Main tab bar: selected labels drawn with WCAG contrast vs the freshness "
        "tint (fixes white-on-green unreadable titles); QSS no longer overrides.",
    ]),
    ("2.9.178", "2026-05-22", [
        "Console / Export log views: force dark background on QTextEdit "
        "viewport and HTML document (fixes lifted-grey panel on some themes).",
    ]),
    ("2.9.177", "2026-05-22", [
        "Read-only log/preview panels (Export, Console) use the main app "
        "background instead of the lighter input-panel grey.",
    ]),
    ("2.9.176", "2026-05-22", [
        "Set location… uses the safe lat/lon + place-search dialog by default; "
        "Qt WebEngine map only when POWERMODEL_MAP_WEBENGINE=1 (avoids segfault).",
    ]),
    ("2.9.175", "2026-05-22", [
        "Solar forecast locale (reverse-geocoded town/region) is always shown on "
        "the bar above the main tab row, right-aligned.",
    ]),
    ("2.9.174", "2026-05-22", [
        "Live banner SOC / Battery / Load / PV / Grid cards use the same dark "
        "background as the header (not the lifted input-panel grey).",
    ]),
    ("2.9.173", "2026-05-22", [
        "Main tab bar: selected tab label picks black or white from the tab "
        "background luminance so non-refreshable tabs stay readable and "
        "freshness fade keeps contrast.",
    ]),
    ("2.9.172", "2026-05-22", [
        "Text fields and dialogue/group panels use a fill 20% lighter than the "
        "app background (was 10%).",
    ]),
    ("2.9.171", "2026-05-22", [
        "Tasmota <b>Pin chart 2 to max 500 W</b>: white label + soft halo so the "
        "toolbar checkbox stays visible on the dark chart bar.",
    ]),
    ("2.9.170", "2026-05-22", [
        "Selected main tab label text is solid black for readability on the green freshness tint.",
    ]),
    ("2.9.169", "2026-05-22", [
        "<b>Console</b>: DEBUG / INFO / WARN lines are colour-coded (grey, blue, amber); "
        "live tail uses HTML so new lines keep their colours.",
    ]),
    ("2.9.168", "2026-05-22", [
        "Text fields (<code>QLineEdit</code>, spin/combo/time, multiline editors) use a fill "
        "10% lighter than the app background; buttons unchanged.",
    ]),
    ("2.9.167", "2026-05-22", [
        "Main tab bar: faint rounded outline on every tab; selected tab outline slightly stronger.",
    ]),
    ("2.9.166", "2026-05-22", [
        "Main <b>tab bar</b>: selected tab stays bold <code>#cdd6f4</code> on freshness tint "
        "(no dark-green label); tabs have rounded top corners.",
    ]),
    ("2.9.165", "2026-05-22", [
        "<b>Tasmota Power History</b>: merges database + in-session samples on one timeline; "
        "matplotlib x-axis uses consistent UTC conversion so traces align with the window.",
    ]),
    ("2.9.164", "2026-05-22", [
        "<b>Tab freshness tint</b>: main tab bar paints green → background fade "
        "(10&nbsp;min) itself — global stylesheet no longer blocks it.",
    ]),
    ("2.9.163", "2026-05-22", [
        "<b>Auto-refresh</b>: Growatt, Octopus Live, and Tasmota now share the same "
        "interval from Setup or the banner cycle; timers restart when you change it; "
        "a poll still runs if a tick fired while the previous fetch was busy; banner "
        "countdown shows the soonest next refresh.",
    ]),
    ("2.9.162", "2026-05-22", [
        "<b>Web UI browser launch</b>: calls <code>/snap/bin/firefox</code> directly (skips the "
        "<code>/usr/bin/firefox</code> wrapper that hangs on KDE); when the app runs as root, "
        "starts the browser as the logged-in desktop user with the correct DISPLAY.",
    ]),
    ("2.9.161", "2026-05-22", [
        "<b>Tasmota Web UI</b>: no longer uses Qt WebEngine by default (fixes segfault on "
        "some Linux/root setups); launches Firefox/Chromium directly or shows a copy-URL dialog.",
    ]),
    ("2.9.160", "2026-05-22", [
        "<b>Web UI</b>: always uses the in-app browser when Qt WebEngine is installed "
        "(avoids broken KDE portal / <code>xdg-open</code> on some desktops).",
    ]),
    ("2.9.159", "2026-05-22", [
        "<b>Tasmota Web UI</b>: opens in an in-app browser when the system browser "
        "cannot launch (e.g. running as root); Growatt “Open web UI” uses the same path.",
    ]),
    ("2.9.158", "2026-05-22", [
        "<b>Forecast location</b>: fallback dialog (lat/lon + place search) when the "
        "map picker cannot run; Chromium <code>--no-sandbox</code> when started as root.",
    ]),
    ("2.9.157", "2026-05-22", [
        "App-wide <b>primary button motif</b>: every action button gets the green "
        "fill on startup (Tasmota <b>Toggle</b> exempt — relay on/off colours).",
    ]),
    ("2.9.156", "2026-05-22", [
        "Primary buttons use a <b>visible green fill</b> (not just an outline) — "
        "Save, Poll Now, Connect, etc. match Refresh All.",
    ]),
    ("2.9.155", "2026-05-22", [
        "Fix <b>tab bar</b> crash on startup (PySide6 has no <code>CE_TabBarBase</code>; "
        "freshness tint uses palette + default painting).",
    ]),
    ("2.9.154", "2026-05-22", [
        "All <b>QPushButton</b> controls use the same muted green tint as "
        "<b>Refresh All</b> (Tasmota <b>Toggle</b> still green/red by relay state).",
    ]),
    ("2.9.153", "2026-05-22", [
        "<b>Growatt Live</b>: richer inverter/battery model parsing (device_list, "
        "inverter_detail, mix_info, plant_info); one-time device_list log to "
        "<b>Console</b>; Setup battery capacity used when the cloud omits a pack model.",
    ]),
    ("2.9.152", "2026-05-22", [
        "Matplotlib chart toolbars (home / pan / zoom / save): <b>white icons</b> and "
        "coordinate read-out on every tab.",
    ]),
    ("2.9.151", "2026-05-22", [
        "Fix main <b>tab bar</b>: tabs visible again; freshness uses a custom tab bar "
        "(green tint fading over 10&nbsp;min) instead of broken stylesheet rules.",
    ]),
    ("2.9.150", "2026-05-22", [
        "<b>Chrome</b>: live banner and tab bar share the same dark background as the app. "
        "Tabs with data refreshed in the last 10&nbsp;min get a light-green tint that "
        "fades back to the background over 10&nbsp;min.",
    ]),
    ("2.9.149", "2026-05-22", [
        "Tasmota <b>Toggle</b>: white label text on all relay states; "
        "10&nbsp;px spacing each side of the Probe/Web UI divider.",
    ]),
    ("2.9.148", "2026-05-06", [
        "<b>Dark theme</b>: one flat background — labels and read-only text are "
        "<b>transparent</b> (no black/grey boxes); only real input fields show a subtle border.",
    ]),
    ("2.9.147", "2026-05-06", [
        "Restore <b>global dark theme</b> (Catppuccin surfaces) on the main window, tabs, "
        "group boxes, tables, and inputs — fixes the accidental light-grey background.",
    ]),
    ("2.9.146", "2026-05-06", [
        "<b>Tasmota Devices</b>: <b>Firmware</b> column (StatusFWR from each device); "
        "<b>Toggle</b> action separated from Probe / Web UI with a divider and distinct styling.",
    ]),
    ("2.9.145", "2026-05-06", [
        "<b>Tasmota Power History</b>: right-click chart 2 for Y-axis max presets; "
        "toolbar checkbox <b>Pin chart 2 to max 500 W</b> (saved to QSettings).",
    ]),
    ("2.9.144", "2026-05-06", [
        "<b>Live import audit</b>: when Growatt shows grid import at high SOC with strong PV, "
        "the banner and Smart Advisor estimate midday immersion load (usage profile), remaining "
        "solar forecast, and Agile spot price to flag unnecessary MIX grid-charge.",
    ]),
    ("2.9.143", "2026-05-06", [
        "<b>Tasmota Power History</b>: hover a trace to see <b>device name</b>, IP, power at the "
        "cursor time, and <b>energy over the history window</b> (est. kWh, avg/peak W) plus "
        "Today/Total kWh when live data is available.",
    ]),
    ("2.9.142", "2026-05-06", [
        "<b>Live banner</b>: narrow <b>›</b> control to the right of the auto-refresh card — "
        "<b>mouse wheel</b> for previous/next main tab, <b>press-and-hold</b> to step forward "
        "repeatedly; tab pages stay constructed in the tab widget before each switch.",
    ]),
    ("2.9.141", "2026-05-06", [
        "<b>Tasmota</b>: optional <b>power-monitor broker</b> mode — GUI reads "
        "<code>GET /snapshot</code> from a local service (<code>services/powermon_broker.py</code>) "
        "that polls devices and writes <b>PostgreSQL</b>; enable in the Tasmota tab to avoid duplicate "
        "LAN polling and double DB inserts.",
    ]),
    ("2.9.140", "2026-05-06", [
        "<b>Tasmota</b> <b>Power History</b>: time window now matches the History slider — "
        "DB timestamps are <b>UTC</b> (same as the logger); cutoffs, filtering, and x-axis "
        "limits use UTC consistently, with tick labels in <b>Europe/London</b>.",
    ]),
    ("2.9.139", "2026-05-06", [
        "<b>Daily import costs</b>: bold white <b>horizontal</b> total (£/day) above each stacked bar.",
    ]),
    ("2.9.138", "2026-05-06", [
        "<b>Charts</b>: translucent <b>shimmer sweep</b> overlay on matplotlib canvases while tab "
        "data loads (Battery Analysis, Battery Simulation, Forecasts, Octopus Live, Maximiser, "
        "Tasmota poll, Optimiser Build plan, Daily import costs refresh).",
    ]),
    ("2.9.137", "2026-05-06", [
        "<b>Maximiser</b>: summary text split across <b>three columns</b> (overview + Scenario A / "
        "Scenario B + overnight / battery); default splitter bias gives more vertical space to the charts.",
    ]),
    ("2.9.136", "2026-05-06", [
        "App-wide <b>QPushButton</b> / <b>QToolButton</b> interaction: clearer hover tint and "
        "pressed “click” feedback (padding shift + border); tinted buttons (green / pink / yellow "
        "/ red) use the same pattern.",
    ]),
    ("2.9.135", "2026-05-06", [
        "<b>Maximiser</b>: chart below the summary — battery <b>SOC %</b> for export-allowed vs "
        "export-blocked heuristic dispatch, and <b>cumulative net £</b> (no-battery scenarios A/B) "
        "at <b>10-minute</b> resolution.",
    ]),
    ("2.9.134", "2026-05-06", [
        "<b>Connectivity Status</b>: draggable splitter between the status table and "
        "the architecture diagram (sizes saved to QSettings).",
    ]),
    ("2.9.133", "2026-05-06", [
        "New <b>Maximiser</b> tab: retrospective lower-bound electricity spend for "
        "<b>yesterday</b> (Growatt DB load/PV vs Agile half-hourly rates) — "
        "<b>export allowed</b> vs <b>export forbidden</b> (surplus PV wasted), plus "
        "an <b>overnight cheapest-slot</b> breakdown for energy needed before solar picks up.",
    ]),
    ("2.9.132", "2026-05-06", [
        "<b>Connectivity Status</b>: animated architecture diagram under the table "
        "(internet APIs → dashboard house → databases → export, plus LAN sources "
        "into the house) — colours reflect the same row states; dashed flows pulse.",
    ]),
    ("2.9.131", "2026-05-06", [
        "<b>Solar forecast backup</b>: if <code>api.forecast.solar</code> fails or returns "
        "no curve (SSL, outage, empty watts), the dashboard falls back to "
        "<b>Open-Meteo</b> hourly <code>global_tilted_irradiance</code> at your tilt/azimuth, "
        "scaled to kWp (fixed performance ratio). Status text notes backup vs primary.",
    ]),
    ("2.9.130", "2026-05-06", [
        "<b>Column widths</b>: resized table/tree headers are flushed to QSettings on "
        "<b>application quit</b> as well as after the resize debounce — fixes widths "
        "(e.g. <b>Connectivity Status</b>) not sticking when closing quickly after a drag.",
    ]),
    ("2.9.129", "2026-05-06", [
        "<b>Forecasts</b> tab: <b>Save parameters</b> button writes lat/lon/tilt/"
        "azimuth/kWp to QSettings (same keys as Setup && Info). Tilt, azimuth and "
        "kWp also auto-save on field commit without spamming the status bar.",
    ]),
    ("2.9.128", "2026-04-30", [
        "Column width persistence: wired the shared helpers to <b>Tasmota</b> (both "
        "device trees), <b>Optimiser</b> per-slot table + command-schedule dialog, "
        "<b>Connectivity Status</b>, <b>Database Viewer</b> (per selected SQL table), "
        "<b>Setup</b> heating schedule tree, and writeback <b>Parameter explainer</b> tree.",
    ]),
    ("2.9.127", "2026-04-30", [
        "All <b>QTableWidget</b> and <b>QTreeWidget</b> column headers are "
        "<b>user-resizable</b> (Interactive mode); widths are <b>saved to QSettings</b> "
        "and restored on the next launch (per-widget keys, including Database Viewer "
        "per SQL table).",
    ]),
    ("2.9.126", "2026-04-30", [
        "New <b>Simulation Engine</b> tab: standalone half-hourly battery model "
        "(solar→load→pack→load, grid import/export, <code>√η</code> charge/discharge "
        "convention matching Battery Simulation) <i>without</i> smart TOU grid-charging; "
        "presets plus optional import of the first N slots from the last "
        "<b>Battery Simulation</b> run; SOC + grid charts.",
    ]),
    ("2.9.125", "2026-04-30", [
        "<b>Command Sim</b>: explains slave vs client; built-in <b>Modbus TCP client</b> "
        "buttons for quick read and manual read/write so you get a positive "
        "<i>round-trip confirmed</i> without switching tabs; dark-theme styling for "
        "bind/port fields.",
    ]),
    ("2.9.124", "2026-04-30", [
        "<b>Connectivity Status</b>: new row <b>Inverter write (this app)</b> — "
        "states whether schedule/control writeback is available (Growatt <b>cloud REST</b> "
        "when logged in), that PowerModel does not Modbus-write locally, and how that "
        "relates to the optional Modbus read probe.",
    ]),
    ("2.9.123", "2026-04-30", [
        "Growatt live tab: larger typography in <b>Device Information</b> and the "
        "<b>Physical — inverter &amp; battery</b> block (titles, values, column "
        "headers, spacing, minimum panel height) for easier reading on high-DPI "
        "screens.",
    ]),
    ("2.9.122", "2026-05-02", [
        "Optimiser dispatch chart: force white (and off-white minor) x-axis time "
        "labels plus bright per-day date annotations so nothing renders black on the "
        "dark theme after twinx / DateFormatter styling.",
    ]),
    ("2.9.121", "2026-05-02", [
        "Octopus Live — top chart: each London calendar day in view shows "
        "<b>Total imported</b> (kWh, top-right of that day) and "
        "<b>Total exported</b> (kWh, bottom-left); partial days use only intervals "
        "visible in the window.",
    ]),
    ("2.9.120", "2026-05-02", [
        "New <b>Command Sim</b> tab: local Modbus TCP simulator (pymodbus "
        "<code>SimDevice</code>) — rough stand-in for growatt2mqtt’s serial simulator "
        "and useful to exercise the Connectivity Modbus probe against "
        "<code>127.0.0.1</code> without hardware.",
    ]),
    ("2.9.119", "2026-05-02", [
        "Growatt Modbus TCP: longer timeouts + brief connect retries; probe reads "
        "aligned with Growatt holding-register blocks; Setup hint explains ShineWiFi‑X "
        "TCP gateway vs sticks that only offer web UI; richer “Unreachable” detail text.",
    ]),
    ("2.9.118", "2026-04-30", [
        "Growatt Energy Totals: clearer titles (today’s / lifetime solar; into "
        "battery vs from battery), tooltips, and lifetime PV shown as MWh when "
        "≥ 1000 kWh.",
    ]),
    ("2.9.117", "2026-04-30", [
        "All matplotlib toolbars: NavigationToolbar (x,y) read-out now explains "
        "what the horizontal and vertical axes represent — time vs £/kWh/W/% "
        "etc. — on Octopus Live, Battery Analysis, Forecasts, Combined, "
        "Tasmota, Smart Advisor, Optimiser, Analytics, Device Costs, and "
        "Octopus Energy Data chart tabs.",
    ]),
    ("2.9.116", "2026-04-30", [
        "Growatt Live Status → Energy Totals: same large metric cards as Live "
        "Status (48 pt coloured values, kWh units) — four blocks across the row.",
    ]),
    ("2.9.115", "2026-04-30", [
        "Setup & Info → Growatt inverter (local network): new “Test connection” "
        "button — TCP check on the web UI port plus optional Modbus probe when "
        "Local Modbus check is TCP or RTU (uses current form values; no Save required).",
    ]),
    ("2.9.114", "2026-04-30", [
        "Invoker: parent each tab's invoker to the tab widget and ignore "
        "RuntimeError when emitting after teardown — avoids crashes when the "
        "window closes while Tasmota or other workers still call invoke().",
        "Forecasts solar chart: mdates.date2num(timestamps) instead of "
        "Series.dt.to_pydatetime() to silence pandas FutureWarning.",
    ]),
    ("2.9.102", "2026-04-26", [
        "Forecasts tab solar chart: the previous calendar day (London) is now "
        "filled using measured Growatt PV (same 5-minute resample + rolling "
        "smooth as 'Actual (today)'), because api.forecast.solar estimate "
        "never returns past intervals — the Wed column was empty while Agile "
        "still showed Wed. Historical overlay keeps only the dashed "
        "'Planned (yesterday)' snapshot line (actual yesterday is the new "
        "fill+solid line). Solar summary and per-day kWh badges include "
        "yesterday with a '(measured)' tag; hover interpolation spans "
        "yesterday actual + live forecast.",
    ]),
    ("2.9.101", "2026-04-26", [
        "Forecasts tab Locale (Nominatim): reverse lookup now uses zoom 16 "
        "so settlement names (village/town) appear for typical UK coords "
        "where zoom 12 only returned the district in the \"city\" slot "
        "(e.g. Chinnor · Oxfordshire instead of South Oxfordshire · "
        "Oxfordshire). The place line prefers village, hamlet, locality, "
        "neighbourhood, town, suburb, then city. Locale cache version "
        "bumped so existing sessions re-fetch once.",
    ]),
    ("2.9.100", "2026-04-26", [
        "Connectivity Status tab: new table row \"Forecast.solar\" "
        "(PV forecast from api.forecast.solar) alongside Growatt, Octopus, "
        "Tasmota, and Databases. States: Fetching while the Forecasts tab "
        "thread runs; Loaded + OK when solar_df has points and the last "
        "message is not an error/rate-limit; Warn for rate-limit or empty "
        "curve with a benign message; Bad for HTTP/parse failures. Details "
        "show sample count, kWp from the Forecasts form, and the hourly "
        "rate-limit hint when present. Freshness column shows wall-clock "
        "time of the last Forecasts-tab refresh (same moment Agile + solar "
        "were pulled). ForecastsTab now stores _solar_last_msg and "
        "_solar_last_refresh_local on each _update_display. In-app help for "
        "Connectivity already mentioned Forecast.Solar — the table now "
        "matches that promise.",
    ]),
    ("2.9.99", "2026-04-26", [
        "Growatt Live Status → Physical panel: battery chemistry row no "
        "longer concatenates a long em-dash hint onto a firmware string "
        "that may already contain text (which could look garbled in a "
        "narrow grid cell). New helper sanitises control characters, "
        "collapses whitespace, forces Qt.PlainText, and uses a single "
        "compact line: numeric wBatteryType → \"Code N - …\" with a "
        "short ASCII legend; non-numeric → cleaned raw capped at 48 "
        "characters. Full raw value (repr) lives in the tooltip only. "
        "The value QLabel gets a minimum height so word-wrap does not "
        "paint overlapping lines.",
    ]),
    ("2.9.98", "2026-04-26", [
        "Growatt Live Status: physical panel is taller and reclaims the "
        "vertical space that used to sit under Live Status beside "
        "\"Refresh Now\". The physical GroupBox now has a higher minimum "
        "height, looser row spacing in its grids, and Expanding vertical "
        "size policy so the two data columns breathe. \"Refresh Now\", "
        "auto-refresh countdown, and \"Last refresh\" are moved into a "
        "narrow column on the RIGHT of the physical panel (same horizontal "
        "strip), stacked top-to-bottom with stretch below — so the strip "
        "uses full width and the dead strip under the power cards is gone.",
    ]),
    ("2.9.97", "2026-04-26", [
        "Growatt Live Status → Physical panel: two-column layout so the "
        "block uses horizontal space instead of a single tall strip. Left "
        "column: dashboard battery model + “today” energy from mix_totals; "
        "right column: live inverter / pack telemetry (grid V/Hz, battery "
        "V, PV strings, status). Equal column stretch; section headers "
        "kept per column.",
    ]),
    ("2.9.96", "2026-04-26", [
        "Growatt Live Status: new \"Physical — inverter & battery\" panel "
        "between Device Information and Live Status. Shows (A) battery "
        "model parameters from Setup / Parameters (nominal kWh, max charge "
        "kW, assumed round-trip efficiency %, low-SOC floor %) so they sit "
        "next to live telemetry; (B) live AC/DC electrical readings from "
        "mix_system_status (grid V & Hz, battery V, PV1/PV2 string V & W, "
        "PV max rating hint pmax, raw system status string); (C) BMS display "
        "voltage from mix_info when available; (D) Growatt battery chemistry "
        "code (wBatteryType) with a short tooltip legend; (E) today's load "
        "and grid-export kWh from mix_totals. mix_info is fetched on each "
        "refresh alongside status/totals. Values clear to \"—\" on "
        "disconnect. GrowattTab now accepts optional app_params for the "
        "dashboard model row; EnergyDashboard passes self.app_params.",
    ]),
    ("2.9.95", "2026-04-22", [
        "Optimiser tab: new \"View command schedule…\" button (next to "
        "\"Explain this\") opens a read-only modal that, for the "
        "current plan, lists EXACTLY what would happen if you pressed "
        "the Send buttons — answering the recurring \"what's actually "
        "going to be sent to my inverter, and when?\" question without "
        "having to step through the writeback confirmation dialogs. "
        "Two-pane layout (resizable splitter): the TOP pane shows one "
        "tab per REST writeback the dashboard would POST to the "
        "Growatt cloud — currently AC charge schedule "
        "(mix_ac_charge_time_period) and, when “Allow battery "
        "export” is on AND the plan contains export windows, the "
        "forced-discharge schedule (mix_ac_discharge_time_period). Each "
        "tab exposes the full method signature, a coloured "
        "WILL-TAKE-EFFECT / NO-OP banner, when the command actually "
        "fires (always: \"on press of the corresponding Send button — "
        "the dashboard never auto-sends\"), the human-readable summary, "
        "and the raw paramN dict that goes on the wire in pretty-"
        "printed JSON. Skipped commands still appear with an "
        "explanation of why they wouldn't be sent (allow-export off, "
        "no export windows, etc.). The BOTTOM pane is a chronological "
        "24-hour table of every state change the inverter will execute "
        "as a result — start of charge window, end of discharge "
        "window, currently-in-progress markers — with absolute time, "
        "relative time (\"in 2 h 14 min\"), schedule kind, action verb "
        "(\"Begin grid charge (period 1)\") and detail (target SOC, "
        "power %, etc.). Colour legend at the bottom: amber = charge "
        "start, red = discharge start, grey = window end, yellow-bold "
        "= currently in progress. Reminder banner spells out that the "
        "MIX schedule is daily-recurring so any window outside the "
        "24 h horizon will repeat at the same HH:MM the next day. "
        "Disabled until a plan exists; auto-enabled in _apply_plan. "
        "Read-only — no commands are ever sent from this dialog.",
    ]),
    ("2.9.94", "2026-04-22", [
        "Tasmota Devices → Power History chart: y-axis is now user-"
        "resizable in two complementary ways. (1) A new \"Max W (Y-axis)\" "
        "spinbox in the controls row sets a hard cap in Watts; the value "
        "is persisted across sessions in QSettings under "
        "tasmota/history_max_w, and 0 means \"auto\" (defer to "
        "matplotlib's auto-fit, the previous behaviour). When the cap is "
        "set the title gains a \" · max NNNN W\" suffix so the active "
        "scale is visible at a glance. (2) Click-and-drag directly on "
        "the y-axis tick-label region of the history chart now rescales "
        "the cap interactively — drag UP to zoom out, DOWN to zoom in, "
        "with sensitivity tuned so a full axis-height drag changes the "
        "cap by ~2x. The drag mirrors live into the spinbox (signals "
        "blocked to avoid triggering a second replot per motion event), "
        "snaps to nice round Watt values (10 W steps below 1 kW, 100 W "
        "above), shows a SizeVerCursor while active, and persists the "
        "final value on button-release. Hit-test region is the 60 px "
        "strip just left of the y-axis spine plus 6 px of inside "
        "tolerance, so the toolbar's pan/zoom modes — which already own "
        "drags inside the plot area — remain untouched.",
    ]),
    ("2.9.93", "2026-04-22", [
        "Octopus Energy Data → Daily Net Charge chart: corrected the £10/day "
        "treatment from \"baseline\" to \"y-axis MAX\" (v2.9.90's design "
        "was a misread of the requirement). Bars now grow upward from zero "
        "showing absolute daily £ spend (the natural direction); the y-axis "
        "is HARD-CAPPED at £10/day with a dotted reference line labelled "
        "\"£10/day budget\" sitting at the top of the visible range. Days "
        "that break the cap are drawn red and clipped, with an inline "
        "overflow tag \"▲ £X.XX\" just below the cap so the over-spend "
        "is unambiguously surfaced without warping the rest of the chart's "
        "scale (a single £15 day used to dominate the y-axis and squash 20 "
        "ordinary days into illegible 1-pixel bars). The lower y-bound "
        "auto-extends below zero when there's an export-credit day. "
        "7-day rolling average and the linear trendline are now both fitted "
        "on absolute £ values (renamed back to \"7-day avg\"; trendline "
        "still shows slope in £/wk). Bar labels stay on top of the bar tip "
        "for under-budget days and on the overflow tag for over-budget "
        "ones. Cursor read-out (format_coord) updated to match — shows "
        "\"Cost £4.14 · £5.86 under £10/day budget · 7-day avg £4.42\" "
        "with a \"▲ over cap\" suffix when the day broke budget.",
    ]),
    ("2.9.92", "2026-04-22", [
        "Octopus Energy Data → Daily Import / Export sub-tab: matplotlib's "
        "default \"(x, y)\" cursor read-out in the bottom-right of the "
        "navigation toolbar now shows rich per-day context for the chart "
        "the mouse is on, instead of meaningless raw axes coords (the x "
        "value was a fractional bar index, the y value was kWh / £, and "
        "neither carried a date). Implemented by overriding "
        "Axes.format_coord on each subplot:\n"
        "  • LHS (Daily Import & Export, kWh): \"Mon 03 Mar 2026 · "
        "Import 42.50 kWh · Export 5.10 kWh · Net +37.40 kWh · 7-day avg "
        "net +28.90 kWh · cursor y=24.00 kWh\"\n"
        "  • RHS (Daily Net Charge, £ vs £10/day): \"Mon 03 Mar 2026 · "
        "Cost £4.14 · £5.86 under £10/day · 7-day avg Δ -3.20 £ · "
        "cursor y=-5.86 £\"\n"
        "Each closure captures dates, daily_totals and gbp/Δ arrays so "
        "lookup is O(1). Handles the bar-offset (LHS bars are at x+0.4, "
        "RHS bars at x+0.2) so rounding lands on the correct day. The "
        "RHS cursor read-out also computes the cursor's *absolute* £ "
        "value (Δ + £10/day baseline) when the mouse strays past the "
        "first/last bar so the figure is still useful in the empty "
        "margins. Falls back to a clean \"x=…, y=…\" string if the "
        "cursor is outside the data range entirely.",
    ]),
    ("2.9.91", "2026-04-22", [
        "Octopus Energy Data → Daily Net Charge chart: added a linear "
        "trendline fitted across the visible date-range window (whatever "
        "the user picked from the 7/14/30/90-day selector). It's a single "
        "straight Catppuccin-yellow dashed line so it's visually distinct "
        "from both the bars and the blue 7-day rolling average; the legend "
        "entry shows the slope in £/week (e.g. \"Trend (+0.42 £/wk)\") so "
        "you can read the directional drift in budget terms without needing "
        "a ruler. Fitted with np.polyfit on (day_index, Δ_£) over all "
        "finite delta values — gracefully skips the line entirely if "
        "fewer than 4 days are available or the fit fails. The legend "
        "gate was widened from \"only when 7-day avg renders\" to \"any "
        "labelled artist on the axes\", so the trendline still gets a "
        "legend even on small (<7-day) windows.",
    ]),
    ("2.9.90", "2026-04-22", [
        "Octopus Energy Data → Daily Import / Export sub-tab → Daily Net "
        "Charge chart (RHS): now baselined against £10/day instead of "
        "£0/day. Each bar shows the day's deviation from the £10 reference "
        "— bars below zero are days you came in under budget (green / good), "
        "bars above zero are over-budget days (red / bad), and the zero "
        "line itself IS the £10/day mark, drawn as a thicker pale "
        "reference line with an inline \"£10/day baseline\" label so the "
        "axis is self-documenting. Bar labels still show the ABSOLUTE £ "
        "figure (e.g. £3.14) — not the delta — because the absolute spend "
        "is the number the user usually wants to read; the deviation is "
        "communicated by the bar height and colour. The 7-day rolling "
        "average line is now computed on the deltas (renamed to "
        "\"7-day avg Δ\") so it tracks budget performance rather than the "
        "raw spend. Y-axis label changed to \"Δ £ vs £10/day\" and the "
        "chart title reads \"Daily Net Charge vs £10/day baseline — Agile "
        "half-hourly rates\". The £10/day budget is held as a constant "
        "(BUDGET_PER_DAY_GBP) right next to the chart code — easy to "
        "promote to a Setup && Info spinbox later if a per-user budget "
        "becomes useful.",
    ]),
    ("2.9.89", "2026-04-22", [
        "Octopus Live tab → Live Demand card: now shows the AGE of the "
        "underlying smart-meter sample (e.g. \"3238 W · 4 min ago\") so it's "
        "obvious why the value diverges from the inverter's instantaneous "
        "Load reading at the screen top. Root cause: the GraphQL "
        "smartMeterTelemetry feed reports `demand` only once per aggregation "
        "window (5 min at the finest granularity) and the tab was being "
        "polled at the global cadence (default 600 s) — so the displayed "
        "Live Demand could legitimately be 10–15 minutes stale. Two fixes: "
        "(1) added _auto_timer_interval_override_ms = 60000 on OctopusLiveTab "
        "so the tab refreshes every 60 s independent of the global "
        "auto-refresh setting (Tasmota uses the same opt-in mechanism — "
        "Growatt Live still follows the global cadence); (2) the value "
        "label is colour-coded by freshness — fresh (<2 min) keeps the "
        "polarity colour (red import / green export), 2-10 min goes amber, "
        ">10 min muted gray; the unit label below the value shows the age "
        "string. Refactored make_small_card to optionally return the unit "
        "label widget (return_unit_label=True) so the OctopusLiveTab can "
        "mutate it at runtime — backward-compatible with existing callers. "
        "Added a tooltip on the Live Demand card explaining the lag and "
        "where it comes from.",
    ]),
    ("2.9.88", "2026-04-22", [
        "Tasmota Devices tab now polls every 30 s independent of the global "
        "auto-refresh cadence. Root cause: TasmotaTab.__init__ already created "
        "a 30 000 ms QTimer wired to poll_all, but EnergyDashboard."
        "apply_auto_refresh_from_params() unconditionally overwrote the "
        "interval with QSettings.auto_refresh/seconds (default 600 s) for "
        "every live-tab in the loop — so the user-visible interval was always "
        "the global one. Added an opt-in per-tab attribute "
        "_auto_timer_interval_override_ms; apply_auto_refresh_from_params now "
        "honours the override when present and falls back to the global value "
        "otherwise. TasmotaTab sets it to 30 000 ms in __init__. The master "
        "auto-refresh enable/disable toggle is still respected (so flipping "
        "auto-refresh off in the toolbar still freezes Tasmota too). Growatt "
        "Live and Octopus Live continue to follow the global setting.",
    ]),
    ("2.9.87", "2026-04-22", [
        "Setup && Info → Main window — tab bar: checkboxes are now laid out "
        "in a 2-column QGridLayout (split top-half / bottom-half, balanced) "
        "instead of one-per-row in stacked QHBoxLayouts. Reclaims roughly half "
        "the vertical space the section used to consume — with 11 toggleable "
        "tabs on the registry that's 11 rows → 6 rows — pushing the Flat tariff "
        "and Analytics groups visibly higher up the page so they're reachable "
        "without scrolling on a 768-px-tall window. Column-stretch is "
        "1:1 so the two columns share the panel width evenly; vertical spacing "
        "tightened to 2 px (was the default ~6 px) since checkboxes don't need "
        "the breathing room a labelled spinbox would. Label text, tooltips, "
        "Apply/Show-all buttons, and QSettings keys are unchanged.",
    ]),
    ("2.9.86", "2026-04-22", [
        "Combined Dashboard → Live Power Flow: x-axis is now static at "
        "(−3 kW, +8 kW) instead of auto-scaling around max_abs. 0 is marked "
        "with a dim vertical reference line so the negative-vs-positive "
        "split stays visually anchored even though the limits are "
        "asymmetric. Stops the chart from “jumping” between snapshots when "
        "one signal momentarily spikes (was very distracting at a glance). "
        "Labels were previously offset by max_abs * 0.03 — that scaled with "
        "the dynamic range and would shift around between refreshes; "
        "replaced with a fixed 0.18 kW offset, with negative bars now "
        "labelled to the LEFT of the tip (ha='right') so the text never "
        "overlaps the bar or the y-axis tick labels. Label positions are "
        "clamped inside the visible range so a value pinned at the limit "
        "(battery at −3 kW or load at +8 kW) still gets a readable label "
        "rather than disappearing past the spine.",
    ]),
    ("2.9.85", "2026-04-22", [
        "Smart Advisor tab: 2×2 chart grid (Projected SOC, Agile Price + "
        "Solar, Cost Breakdown, Grid Flows) now uses the full horizontal "
        "width of the dashboard. Root cause: matplotlib's tight_layout(pad=2.5) "
        "over-pads the right edge when one of the subplots has a twinx (the "
        "Agile-Price chart twins on Solar kW) — that mis-aligns both columns "
        "of the gridspec and leaves a 10–15 % vertical empty strip on the "
        "right of the figure. Replaced with explicit subplots_adjust(left=0.035, "
        "right=0.965, top=0.93, bottom=0.10, hspace=0.42, wspace=0.18) so both "
        "columns reach to the canvas edge while still leaving room for the "
        "Solar-kW twinx ylabel on the far right. Also: explicit Expanding/"
        "Expanding size policy on both the chart_widget and the FigureCanvas "
        "(matches BatterySimulationTab/OptimiserTab convention), drop the "
        "canvas's minimumSize hint so it can be shrunk by the parent layout, "
        "zero margins/spacing on the chart QVBoxLayout, and bump initial "
        "figsize to 16×8 so the Qt size hint matches a landscape window.",
    ]),
    ("2.9.84", "2026-04-22", [
        "Inverter writeback confirmation dialogs (both AC charge and forced "
        "discharge) replaced with a custom resizable QDialog. Fixes the "
        "QMessageBox right-edge truncation reported on the AC-charge confirm "
        "screen — the body text now wraps to the dialog width instead of being "
        "clipped by the fixed-width QLabel layout. The dialog has a vertical "
        "QSplitter so the bottom pane (parameter explainer + raw JSON) is "
        "user-draggable upwards as far as the body's minimum allows; the "
        "splitter handle is highlighted on hover. The bottom pane is now a "
        "QTabWidget with two tabs: (1) “Parameter explainer” — a grouped "
        "QTreeWidget that decodes every paramN that goes on the wire, with "
        "the master settings (charge: param1 charge_power, param2 stop_soc, "
        "param3 mains_enabled; discharge: param1 discharge_power, param2 "
        "discharge_stop_soc) collected at the top, and each of the three "
        "time periods broken down into start_h/start_m/end_h/end_m/enabled "
        "rows under a header that summarises the window (e.g. “Period 1 — "
        "08:30 → 09:00, ENABLED”). Disabled periods are flagged “(won't "
        "fire)” inline. (2) “Raw paramN dict (wire JSON)” — the existing "
        "json.dumps view, now monospace and readable. The discharge flow "
        "additionally surfaces an amber “Elevated-risk writeback” banner at "
        "the top. Window is resizable with a size grip (default 960×820, "
        "min 720×480) so the user can grow it on large monitors.",
    ]),
    ("2.9.83", "2026-04-22", [
        "Optimiser → Explain this dialog: the Load Decomposition diagram now "
        "renders a “Numbers for this plan” panel underneath the static flowchart "
        "with the actual kWh figures the planner used for the *current* plan + "
        "supporting history. Top row (rigid-baseline build) shows OCTOPUS IMPORT "
        "history mean per ½h with sample range, TASMOTA POWER live "
        "active/total device count + today's & yesterday's cumulative kWh, "
        "HEATER HOURS MASK with how many scheduled_loads entries matched the "
        "heater kW (and how much kWh/day was subtracted from the Octopus floor "
        "by the v2.9.80 anti-double-count fix), and the resulting RIGID "
        "BASELINE [t] mean and total over the horizon. Bottom row (DP input) "
        "lists load[t] / heater[t] totals, the chosen heater windows with "
        "per-window kWh, the (reference) combined load + heater total, and the "
        "horizon solar forecast after PV scale × PV10 blend. Plan window header "
        "shows the exact start → end (e.g. “Wed 22 Apr 23:00 → Fri 24 Apr 23:00, "
        "48 half-hour slots, 24.0 h horizon”). Each missing source renders as "
        "“n/a” instead of failing — opening the dialog before pressing Build "
        "plan now shows a friendly hint instead of zeros.",
    ]),
    ("2.9.82", "2026-04-22", [
        "Optimiser: opt-in auto re-plan cadence (Predbat-style 5-min loop). "
        "New “Auto re-plan” checkbox in the controls bar (default OFF, "
        "persisted under optimiser/auto_replan). When ON a 60s QTimer wakes "
        "_check_auto_replan, which silently triggers Build plan if any of "
        "four conditions hold: (A) wall clock has crossed 16:00 BST and the "
        "current plan was built before that boundary today (so tomorrow's "
        "Agile rates are now published and we should extend the horizon); "
        "(B) the plan was built > 30 min ago (slots are now in the past); "
        "(C) live SOC drifts > 15 percentage points from the plan's "
        "predicted SOC at the current slot (forecast was wrong / surprise "
        "consumption); (D) no plan exists yet. 5-minute cooldown between "
        "auto-fires; skipped silently when a planner thread is already in "
        "flight; trigger reason logged to the Optimiser channel each time. "
        "_apply_plan now stamps _last_plan_built_ts so staleness math is "
        "wall-clock honest. New helper _planned_soc_pct_at(now) reads the "
        "soc_pct_trace from the DP result (already exposed since v2.9.78). "
        "Inverter writeback is unaffected — auto re-plan only re-runs the "
        "DP, it never auto-pushes to the inverter; the user still confirms "
        "every charge/discharge schedule push manually.",
    ]),
    ("2.9.81", "2026-04-22", [
        "Optimiser: probabilistic PV10/PV50 solar blend (Predbat-style risk "
        "awareness). plan_solar_per_slot() now accepts pv10_weight (default 0.0 "
        "= legacy pure-PV50 behaviour). When > 0 the planner blends a synthetic "
        "PV10 (worst-case) curve with the central PV50 forecast: pv_used = "
        "(1−w)·PV50 + w·PV10, then multiplies by the existing PV forecast scale. "
        "PV10 is derived from PV50 with a *time-localised* ratio: peak-midday "
        "slots ≈0.75×PV50, shoulder/cloudy slots ≈0.30×PV50 (square-root "
        "irradiance interpolation). This captures the well-documented behaviour "
        "that overcast days hit early/late generation harder than peak — "
        "something a flat haircut can't model. New “PV10 weight” spinbox in the "
        "Optimiser controls (range 0.00–1.00, persisted to QSettings under "
        "optimiser/pv10_weight). Past-extension chart honours the same weight so "
        "the displayed past solar matches the planner's view. Free Forecast.Solar "
        "tier doesn't expose PV10 directly (Pro feature), so this is a pure "
        "client-side derivation — no extra API calls or quotas consumed.",
    ]),
    ("2.9.80", "2026-04-22", [
        "Optimiser: fix immersion double-counting in dp_battery_dispatch. "
        "Previously, if the user had configured an immersion as a recurring "
        "scheduled_loads entry (e.g. 3 kW @ 04:00 for 60 min) AND the "
        "Optimiser was also planning a heater via pick_heater_windows at "
        "the same kW, the immersion's energy would be added to the load "
        "profile (rigid scheduled-load layer + Octopus historical floor "
        "that already baked in the immersion's draw) AND added again as "
        "heater_kwh inside the DP — inflating planned grid-charge needs and "
        "starving export windows. _build_usage_profile() now accepts "
        "exclude_heater_kw=<float kW>: any scheduled_loads entry whose kw "
        "is within ±0.1 kW of that value is (1) omitted from the additive "
        "scheduled-load layer and (2) subtracted from the Octopus hourly "
        "historical overlay (clamped to the base-load floor). The Optimiser "
        "planner thread now passes exclude_heater_kw=sp_heater_kw.value() "
        "for the DP load_kwh; the past-extension chart still uses the "
        "non-decontaminated profile so historical bars remain truthful. "
        "Decontamination events are logged to the Optimiser log channel "
        "(matched-entry count + max kWh/slot subtracted). SmartAdvisor and "
        "all other callers are unchanged (they pass no exclude_heater_kw "
        "and get the same full profile as before).",
    ]),
    ("2.9.79", "2026-04-22", [
        "Optimiser: forced-discharge writeback (battery → grid) now actually "
        "executes on the inverter instead of just appearing in the chart. "
        "New “Allow battery export” checkbox (default OFF, persisted). When "
        "off the DP refuses any batt_to_grid action and the chart's green "
        "“export to grid” bars stay empty — honest about what will happen. "
        "When on, the DP plans forced-discharge windows and a new “Send "
        "export schedule…” button writes them via the Growatt cloud "
        "(mix_ac_discharge_time_period). Full snapshot + verify + auto-"
        "rollback parity with the existing AC-charge writeback: pre-write "
        "snapshot of disChargePowerCommand / wdisChargeSOCLowLimit / "
        "forcedDischargeTimeStart|Stop|StopSwitch{1..3}; aborts on snapshot "
        "failure; 3 s settle then field-by-field verify with 2-min HH:MM "
        "tolerance; auto-rollback to snapshot (or panic safe-disable with "
        "stop_soc=100% so the inverter physically cannot discharge) on a "
        "verified mismatch. New “Rollback last export write…” button restores "
        "the snapshot at any time. Discharge power % persisted in QSettings "
        "(optimiser/inverter_discharge_power_pct), default 100%. Stop-SOC "
        "floor auto-derived from the lowest SOC the plan visits during any "
        "export window, rounded down to 5%, clamped ≥ _PLAN_EXPORT_MIN_SOC.",
    ]),
    ("2.9.78", "2026-04-22", [
        "Optimiser DP: added a terminal-value term so the dispatch DP no longer "
        "prefers to empty the battery in the final slots of the planning horizon. "
        "End-of-horizon SOC is now valued at (mean future import price × √η) per "
        "stored kWh, scaled by a new “Terminal SOC value” spinbox (default 1.0, "
        "matching Predbat's metric_battery_value_scaling). Set to 0.0 to revert to "
        "the old behaviour. dp_battery_dispatch() now also returns objective_p, "
        "terminal_value_p and terminal_value_p_per_kwh; total_cost_p still reports "
        "the raw plan spend (sum of slot_cost_p) so existing UI/baseline "
        "comparisons are unchanged.",
    ]),
    ("2.9.77", "2026-04-22", [
        "Optimiser → inverter writeback now does snapshot + verify + rollback. "
        "Pre-write: reads & decodes the prior AC charge schedule "
        "(chargePowerCommand / wchargeSOCLowLimit / acChargeEnable / "
        "forcedChargeTimeStart|Stop|StopSwitch{1..3}); aborts if the snapshot "
        "fails. Confirmation dialog now spells out exactly what params go on "
        "the wire, what the inverter will physically do, the specific risks, "
        "the prior state being overwritten, and the auto + manual rollback "
        "plan. Post-write: re-reads the schedule after a 3 s settle, compares "
        "field-by-field, and auto-rolls-back to the snapshot (or safe-disable "
        "as panic-stop) on a verified mismatch. New “Rollback last write” "
        "button restores the snapshot at any time.",
    ]),
    ("2.9.76", "2026-04-22", [
        "Optimiser: new “Send schedule to inverter…” button writes the plan’s "
        "grid-charge windows back to the MIX inverter (mix_ac_charge_time_period). "
        "Computes stop-SOC from the plan’s peak charging SOC, splits any window "
        "that crosses midnight, drops to the largest 3 if needed, and shows a "
        "confirmation dialog with exact HH:MM windows / charge-power % / stop SOC. "
        "If the plan calls for no overnight grid-charge it disables AC charging on "
        "the inverter so it won’t run a previous day’s window. Charge-power % is "
        "persisted in QSettings (optimiser/inverter_charge_power_pct).",
    ]),
    ("2.9.75", "2026-04-22", [
        "Setup && Info: new “Main window — tab bar” section — checkboxes to hide "
        "optional tabs (Growatt, Octopus Energy Data, and Setup && Info always "
        "remain). Apply saves to QSettings and rebuilds the tab bar immediately; "
        "“Show all tabs” resets visibility.",
    ]),
    ("2.9.74", "2026-04-22", [
        "Main tab bar: reordered into coherent groups — live feeds (Growatt, "
        "Octopus Live, Tasmota), historic utility & costs (Octopus Energy Data, "
        "Daily import costs), integrated & battery (Combined, Analysis, "
        "Simulation), planning (Forecasts, Smart Advisor, Optimiser), "
        "infrastructure (Connectivity, Database Viewer, Export), then app "
        "(Console, Setup & Info, License). Tab construction order unchanged "
        "for dependencies.",
    ]),
    ("2.9.73", "2026-04-22", [
        "Optimiser: renamed the “Solar haircut” control to “PV forecast scale” "
        "(clearer label + tooltip); planner code uses `forecast_scale` / "
        "`_PLAN_SOLAR_FORECAST_SCALE` instead of “haircut”.",
    ]),
    ("2.9.72", "2026-04-22", [
        "`_draw_day_date_labels`: day labels (e.g. “Thu 23 Apr”) are now plain "
        "`_DARK_TEXT` at tick fontsize with no dark pill — matches the Optimiser "
        "(and other tabs’) bottom-axis time styling instead of a black box.",
    ]),
    ("2.9.71", "2026-04-22", [
        "License tab: replaced the bespoke wording with the off-the-shelf "
        "PolyForm Noncommercial 1.0.0 licence (verbatim) plus the Aliniant UK "
        "Ltd copyright notice as the Required Notice. Removes the contradictions "
        "of the earlier MIT-with-restrictions draft and gives downstream users "
        "a known, lawyer-drafted text to evaluate.",
    ]),
    ("2.9.70", "2026-04-22", [
        "License tab: rewrote the permission grant so it no longer contradicts "
        "the additional terms — removed the MIT-style “sublicense / sell” "
        "wording (which conflicted with the no-onselling / no-personal-gain "
        "clauses) and stopped labelling the licence as MIT, since a modified "
        "MIT is not MIT. The warranty disclaimer (the genuinely useful part) "
        "is retained verbatim. Help / changelog text updated to match.",
    ]),
    ("2.9.69", "2026-04-22", [
        "Octopus Live: fix TypeError in `_tight_y_from_artists` when an axvline "
        "carries pandas Timestamps (e.g. the “Now” marker on the live demand "
        "chart) — xdata is now coerced via `mdates.date2num` when a direct "
        "float cast fails, so the vertical-line skip works for both numeric "
        "and datetime axes.",
    ]),
    ("2.9.68", "2026-04-22", [
        "License tab: copyright is now held by Aliniant UK Ltd, with explicit "
        "no-onselling and no-personal-financial-gain (other than lower energy "
        "bills) terms, and a clause stating that any user modifications are at "
        "the user's own risk and that the developer assumes no risk.",
    ]),
    ("2.9.67", "2026-04-22", [
        "New License tab: MIT terms plus an explicit notice that the software is "
        "provided without express or implied warranties and that using the tool "
        "constitutes acceptance of those terms.",
    ]),
    ("2.9.66", "2026-04-22", [
        "Octopus Live: y-axis tightening now ignores all vertical reference lines "
        "(constant x), not only labelled ones — unlabelled “now” markers on the "
        "net chart no longer pin the scale to matplotlib’s padded autoscale band. "
        "Initial figure layout matches the post-plot tight_layout / hspace.",
    ]),
    ("2.9.65", "2026-04-22", [
        "Octopus Live: chart titles now say “Previous Nh” for the rolling window; "
        "y-axis limits are tightened from the plotted bars/lines/fills (skipping "
        "horizontal and “Now” reference lines) so less empty band appears above "
        "and below the data. Slightly tighter subplot spacing and tight_layout "
        "padding reclaim vertical canvas space.",
    ]),
    ("2.9.64", "2026-04-22", [
        "Optimiser x-axis: minor ticks at 03:00 / 09:00 / 15:00 / 21:00 (London) "
        "now show the same %a %H:%M labels as the six-hour majors, rotated 30° "
        "and placed on a second row with a softer colour; the vertical guides "
        "remain the existing faint `_draw_6h_vertical_grid` lines. The “Now” "
        "caption is an annotation below the bottom axis with the same rotation "
        "and alignment as tick labels (no in-axes text box). Figure bottom "
        "margin widened slightly so the extra row fits.",
    ]),
    ("2.9.63", "2026-04-22", [
        "Tasmota Actions column: each row’s Probe / Toggle / Web UI buttons now "
        "use MinimumExpanding vertical size policy so they stretch to the full "
        "row height with only 2 px top and bottom inset (QTreeWidget::item "
        "padding tightened to match). A slimmer button stylesheet avoids tall "
        "built-in padding fighting the layout.",
    ]),
    ("2.9.62", "2026-04-22", [
        "Optimiser: the “Now” caption moves from the top of the dispatch chart "
        "to the bottom panel, sitting just above the x-axis in the same band as "
        "the Wed 12:00-style tick labels (still offset a few minutes from the "
        "line so it does not collide with the vertical marker).",
    ]),
    ("2.9.61", "2026-04-22", [
        "Time-axis vertical guides: the shared `_draw_6h_vertical_grid` helper "
        "already had 03:00 / 09:00 / 15:00 / 21:00 as secondary lines, but they "
        "were suppressed whenever a day column was under 100 px wide — easy on "
        "short-horizon charts. Those half-step lines are now drawn slightly "
        "clearer (still fainter than 00/06/12/18). The Optimiser, Forecasts, "
        "and Smart Advisor battery-strategy charts pass "
        "`force_intraday_secondary` so those guides always show on short "
        "horizons; the Optimiser grid pass runs after the final `set_xlim` so "
        "ticks align with the 2 h past window.",
    ]),
    ("2.9.60", "2026-04-22", [
        "Optimiser “now” marker: the vertical clock line is drawn under the "
        "matplotlib legends so it no longer paints through them; a bold “Now” "
        "label sits just inside the top of the dispatch chart, offset a few "
        "minutes to the left or right of the line (depending on which half of "
        "the axis “now” falls in) so it stays clear of the upper-left legends.",
    ]),
    ("2.9.59", "2026-04-22", [
        "Tasmota device tables: Probe / Toggle / Web UI sit in one “Actions” "
        "column with 5 px gaps between buttons; row vertical padding +3 px. "
        "Column widths are now variable: the Name column stretches with the "
        "window; other columns start sized-to-contents and can be dragged "
        "(interactive headers) instead of staying fixed-width.",
    ]),
    ("2.9.58", "2026-04-22", [
        "Tasmota Devices: the device list is split into two equal-width tables "
        "(first seven IPs in the scan range on the left, the remainder on the "
        "right) so wide layouts use the empty space beside the old single column. "
        "Probe / Toggle / Web UI buttons are 15 px wider than before.",
    ]),
    ("2.9.57", "2026-04-22", [
        "Tasmota Devices table: each row now has 4 px top/bottom padding; three "
        "action columns after Total (Probe, Toggle, Web UI) use equal-width "
        "buttons sized to the widest label. Probe re-polls a single IP; Toggle "
        "sends Tasmota Power Toggle after a Yes/No confirmation; Web UI opens "
        "the device root URL in the default browser.",
    ]),
    ("2.9.56", "2026-04-22", [
        "Optimiser charts: prepend two hours of context before the live clock — "
        "the same Agile prices / solar forecast / rigid load model as the plan, "
        "with a simple no-battery solar-vs-grid split for the stacked bars and "
        "SOC held flat at the DP starting level. A fixed 2 px vertical “now” "
        "line marks the current London time on both subplots; the x-axis window "
        "is pinned from (now − 2 h) through the end of the horizon so the past "
        "strip stays aligned with the NOW marker.",
    ]),
    ("2.9.55", "2026-04-22", [
        "Setup & Info: new “Growatt inverter (local network)” group with "
        "IP/hostname, HTTP port (default 80), Save to disk, and “Open web UI” "
        "(browser) so the Shine / inverter LAN address is documented alongside "
        "other house-energy settings. Values live on AppParameters as "
        "growatt_local_ip / growatt_local_port and restore from QSettings on "
        "startup.",
    ]),
    ("2.9.54", "2026-04-19", [
        "Growatt Live Status → Energy Totals: enlarged the row so it "
        "stops being a tiny footnote under the headline live cards. "
        "Labels (Energy Today / Total / Charged / Discharged) now "
        "render at 14 pt and the bold values at 18 pt (was an "
        "unstyled label + 11 pt bold value), with a touch more "
        "horizontal breathing room (24 px between metrics, 12/8 px "
        "groupbox padding) so it reads as a proper secondary metric "
        "strip.",
    ]),
    ("2.9.53", "2026-04-19", [
        "Growatt Live Status: doubled the font size of the headline "
        "live readings (Battery SOC, Battery Power, PV Power, Grid "
        "Power, Load Power) from 24 pt to 48 pt in make_power_card so "
        "they're readable at a glance from across the room — these are "
        "the numbers the user actually monitors live, the surrounding "
        "card chrome already had the space.",
    ]),
    ("2.9.52", "2026-04-19", [
        "Status-bar Close button now carries a faint Catppuccin-red "
        "tint (~20 % alpha / ~80 % transparency) matching the green/"
        "yellow scheme of Refresh All and Help. The trio is now fully "
        "colour-coded: green = go (refresh), yellow = info (help), red "
        "= stop (close).",
    ]),
    ("2.9.51", "2026-04-19", [
        "Status-bar action cluster: shrunk all three buttons from "
        "220 px to 110 px wide so they take up less of the status bar. "
        "'Refresh All' now carries a faint Catppuccin-green tint "
        "(~20 % alpha / ~80 % transparency) and 'Help' a faint "
        "Catppuccin-yellow tint at the same opacity, so the two action "
        "buttons are colour-coded at a glance without overpowering the "
        "neutral Close button.",
    ]),
    ("2.9.50", "2026-04-19", [
        "Status-bar action cluster: 'Refresh All', 'Help' and 'Close' "
        "are all pinned to 220 px wide so the trio reads as a balanced "
        "row of equal-width chips on the right-hand side of the status "
        "bar.",
    ]),
    ("2.9.49", "2026-04-19", [
        "Status-bar 'Refresh All' and 'Help' buttons now share the "
        "dashboard's _SUBTLE_BTN_QSS instead of their previous loud "
        "green / yellow translucent fills — they now match the Close "
        "button's neutral dark chrome. 'Refresh All' is also pinned to "
        "the same width as the Close button (measured via "
        "close_btn.sizeHint()) so the right-hand action cluster reads "
        "as a balanced trio rather than an attention grab.",
    ]),
    ("2.9.48", "2026-04-19", [
        "Octopus Energy Data → Daily Import / Export sub-tab: split the "
        "single overloaded chart into two side-by-side panels. LHS now "
        "shows just Import / Export bars in kWh with the 7-day average "
        "net line; RHS shows the daily net charge in £ (red bars = cost, "
        "green bars = credit) with its own 7-day rolling-average line "
        "and per-bar £ totals. Removes the previous rotated-text £ "
        "overlay on top of the import bars, which mixed kWh and £ on "
        "the same axis and visually implied a tighter correlation than "
        "actually exists on Agile (where the daily £ figure is driven "
        "as much by spot-price timing as by total kWh).",
        "RHS chart title surfaces the cost basis ('Agile half-hourly "
        "rates' vs 'flat p/kWh from Setup & Info') so it's obvious "
        "whether you're looking at modelled flat-tariff costs or real "
        "Agile-priced costs.",
    ]),
    ("2.9.47", "2026-04-19", [
        "New status-bar action cluster, immediately left of the existing "
        "Close button: a green 'Refresh All' button (~50% alpha fill) "
        "that triggers a one-shot refresh on every tab that exposes a "
        "fetch / poll / run hook (Growatt, Octopus, Octopus Live, "
        "Tasmota, Forecasts, Battery Analysis, Combined, Daily Import "
        "Costs, Battery Simulation, Smart Advisor, Optimiser, "
        "Connectivity Status), and a yellow 'Help' button (~50% alpha "
        "fill) that opens a page-specific HelpDialog keyed by the "
        "currently-active tab class.",
        "New _HELP_TEXTS registry covering every user-facing tab "
        "(Growatt Live Status, Octopus Energy Data, Daily Import "
        "Costs, Combined Dashboard, Battery Analysis, Battery "
        "Simulation, Forecasts, Smart Advisor, Optimiser, Octopus "
        "Live, Tasmota Devices, Connectivity Status, Database Viewer, "
        "Export, Console, Setup & Info) plus a graceful default for "
        "any future tab that hasn't been registered yet.",
        "Refresh-All telemetry: every successful or failed per-tab "
        "trigger is logged via _log.info / _log.warn, and the status "
        "bar reports how many tabs were refreshed (and how many were "
        "skipped) so the user can see at a glance whether the click "
        "actually did anything.",
    ]),
    ("2.9.46", "2026-04-19", [
        "Fix: Setup & Info save methods (_save_solar_installation, "
        "_save_battery_defaults, _save_load_profile) now call s.sync() "
        "after setValue, so edits hit disk immediately rather than only "
        "on clean app exit. This was the root cause of the location "
        "field appearing not to persist across restarts.",
        "Fix: ForecastsTab map picker now blocks editingFinished signals "
        "while updating both Lat and Lon fields, so the per-field "
        "_on_latlon_committed handler can no longer half-save (lat new, "
        "lon still old) before both fields are populated. This explained "
        "the on-disk asymmetry of solar_lat=51.50000 alongside "
        "solar_lon=-0.1 we found while debugging.",
        "Fix: belt-and-braces QApplication.aboutToQuit handler now flushes "
        "QSettings on shutdown, so any future code path that forgets to "
        "call sync() can no longer silently lose user edits on crash.",
        "Diagnostics: ForecastsTab._persist_solar_params and the map "
        "picker accept path now log every save (with the QSettings file "
        "path) and surface the saved location in the dashboard status "
        "bar, so silent saves are now impossible.",
        "Diagnostics: Setup & Info 'Save Solar Installation' status "
        "message now reports the saved Lat/Lon/Tilt/Azimuth/kWp instead "
        "of the previous opaque 'Solar installation saved.'",
    ]),
    ("2.9.45", "2026-04-19", [
        "New Export tab: builds a 30-min sliding-window .xlsx workbook "
        "centred on 'now' (configurable half-width, default 1.5 days) "
        "with columns for spot price (Agile import + export), historic "
        "usage, usage prediction (weekday × half-hour median over the "
        "last N weeks of measured Octopus data) and SOC %. Includes "
        "Preview, Export, an in-app summary, and a README sheet inside "
        "the workbook describing each column and the prediction method.",
        "New DataLogger query helpers: query_octopus_consumption, "
        "query_growatt_soc, query_agile_prices — used by the Export tab "
        "and reusable by other future analytics tabs.",
    ]),
    ("2.9.44", "2026-04-19", [
        "Optimiser charts polished: stacked dispatch bars now have a "
        "hairline edge in the panel-background colour for crisp "
        "separation, slightly slimmer width and a subtle gap between "
        "slots; price chart gained translucent fills under each step "
        "line; SOC overlay rendered with a soft warm-orange halo + "
        "crisp line for a layered glow; legends restyled, top/right "
        "spines hidden, dotted-style horizontal gridlines and a "
        "left-aligned bold title hierarchy throughout.",
    ]),
    ("2.9.43", "2026-04-19", [
        "About dialog now shows the full author bio supplied by the "
        "project owner — Growatt + Octopus focus, the API-integration "
        "story, a note from Julian (ex-Army, ex-Vodafone Network "
        "Automation lead, now consulting / regulator side) and a "
        "clickable mailto link to julian.garrett@aliniant.com.",
    ]),
    ("2.9.42", "2026-04-19", [
        "About dialog populated with the real description supplied by the "
        "user — covers the experimental Growatt + Octopus focus, the API "
        "integrations and the household battery / solar use case.",
    ]),
    ("2.9.41", "2026-04-19", [
        "Daily Import Costs tab no longer turns green just because Octopus "
        "or Tasmota data updated upstream — it now only flips to fresh "
        "once its own chart is actually rendered from real data, "
        "matching what the user sees on screen.",
    ]),
    ("2.9.40", "2026-04-19", [
        "Multi-day charts: vertical grid auto-thins to midnight-only when "
        "each day occupies less than ~40 px of axis width (e.g. the "
        "Daily Energy Trends chart), so wide-span views stay clean.",
        "Day/date labels on charts now auto-stagger across two rows when "
        "they would otherwise overlap, alternating row 1 / row 2; if "
        "they would still collide, the helper additionally thins the "
        "labels so the survivors stay legible.",
    ]),
    ("2.9.39", "2026-04-19", [
        "Added About and History buttons to the Setup & Info tab.",
        "Introduced an in-app changelog so each patch is documented and "
        "viewable without leaving the dashboard.",
    ]),
    ("2.9.38", "2026-04-19", [
        "Forecasts tab: lat/lon picked from the OSM map (or typed manually) "
        "now persist across restarts via QSettings, and are mirrored into "
        "AppParameters and the Setup & Info edits in the same session.",
    ]),
    ("2.9.37", "2026-04-19", [
        "Renamed the 'Parameters' tab to 'Setup & Info'.",
    ]),
    ("2.9.36", "2026-04-19", [
        "Battery SOC Comparison chart now shows a single midnight gridline "
        "instead of the full 6-hour grid, reducing clutter.",
        "Fixed freshness indicator on Battery Simulation, Battery Analysis, "
        "Device Import Costs, Smart Advisor and Optimiser tabs by firing "
        "the on_data_updated callback before chart rendering.",
    ]),
    ("2.9.35", "2026-04-19", [
        "Solar Forecast chart: added smoothed red 'today actual' line over "
        "the forecast, with a stronger brown fill under both curves.",
        "Live banner: 'Auto 300s' converted to a click-through button "
        "cycling 10s / 30s / 60s / 180s / 300s / 600s / Manual with colour "
        "coding from red (aggressive) to purple (manual only).",
    ]),
    ("2.9.34", "2026-04-19", [
        "All time-series charts: vertical gridlines at 00:00, 06:00, 12:00, "
        "18:00 (prominent) and 03:00, 09:00, 15:00, 21:00 (lighter).",
        "Day-of-week and date labels added to every supported chart, "
        "anchored to the 00:00 gridline.",
        "Octopus Live tab: Fetch button moved next to Serial input to "
        "reclaim vertical space for the charts.",
    ]),
    ("2.9.33", "2026-04-19", [
        "Console output now persists between sessions in "
        "~/.energy_dashboard_console.jsonl, with auto-trim and "
        "session-start markers for easier post-mortem debugging.",
        "Tab text colour-coded for freshness: green if data is <30 min "
        "old, blue if older, white if not loaded.",
        "Live banner gained a 'next refresh in' countdown column.",
    ]),
    ("2.9.32", "2026-04-19", [
        "Forecasts tab: added Locale field (town/city + county) via "
        "Nominatim reverse geocoding, with caching and threading.",
        "Lat/Lon inputs upgraded to validated DECIMAL(10,5) QLineEdits "
        "with 5dp auto-formatting on commit.",
        "Added 'Show on map' button opening an OSM/Leaflet picker with "
        "what3words lookup support.",
    ]),
    ("2.9.31", "2026-04-19", [
        "Persisted solar-forecast and Agile-price snapshots to the "
        "database so historical 'planned vs actual' overlays survive.",
        "Solar chart now overlays yesterday's planned forecast (dashed) "
        "and yesterday's actual Growatt PV (solid grey) for accuracy "
        "checks at a glance.",
    ]),
    ("2.9.30", "2026-04-19", [
        "Smart Advisor: recommendation moved up to the Run row, units "
        "inlined with values, vertical space reclaimed for charts.",
        "Optimiser: action card consolidated to a single horizontal line "
        "with semantic colour coding and 20px padding.",
        "Forecasts tab: summary panel restructured into 3 horizontal "
        "groups (Agile Import, Agile Export, Solar Forecast).",
    ]),
    ("2.9.29", "2026-04-19", [
        "Optimiser: top chart pinned to the top of the chart window, "
        "title added to the bottom chart, mouse-following crosshairs on "
        "both panels, and 6-hour vertical gridlines (2px at midnight, "
        "1px elsewhere).",
        "Octopus Energy Data summary cards laid out horizontally, "
        "vertically aligned, slightly larger font.",
        "Renamed 'Analytics' to 'Battery Simulation'.",
    ]),
    ("≤ 2.9.28", "—", [
        "Earlier patches: Smart Advisor optimiser design (DP-based "
        "battery dispatch, water-heater heuristics), Tasmota integration, "
        "Growatt + Octopus dual-meter handling, database persistence "
        "(SQLite / MySQL / PostgreSQL), Forecasts tab introduction, and "
        "the initial PySide6 multi-tab dashboard scaffold.",
    ]),
)


__all__ = [n for n in globals() if not n.startswith('__')]
