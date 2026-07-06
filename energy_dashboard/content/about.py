"""
Energy Dashboard — `content/about.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.version import APP_VERSION
# Copy shown in the "About" dialog (Setup & Info tab → About button).
# Authored by the project owner; rendered as rich HTML in a QTextBrowser
# so the trailing mailto: link stays clickable.
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
