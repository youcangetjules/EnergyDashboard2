# architecture.md — PowerModel / Energy Dashboard

Part of the **basic instructions for the development environment** (see `AGENTS.md`).

Living record of **how the application is structured** and **why** important architectural choices were made.

Agents: read this before large refactors, new tabs, new data sources, or anything that changes how telemetry flows. When you make a decision that affects architecture, **add a dated Decision entry here** (plain English + consequence).

---

## Big picture

The dashboard is a **publish / subscribe hub**: it pulls (and sometimes writes) several independent pipes, then charts and plans from what it has.

**Important:** from the Growatt inverter there are **three connection methods** into this app — **Growatt cloud API**, **GROTT** (→ EMQX MQTT), and **Modbus** (TCP/RTU). They are **separate peers**, not a chain. Do **not** draw “Wi‑Fi → API” or “LAN → Grott”. The stick’s local browser admin UI is **not** a dashboard connection method (Setup diagnostics only — never drawn as a fourth pipe).

```
  Battery 1/2/3 ──► Growatt inverter
                           │
     ┌──────────◄──────────┼──────────◄──────────┐
     ▼                     ▼                     ▼
 Growatt cloud API       GROTT                 Modbus
 (report up;             (local decode)        (read / write)
  schedule down)              │                     │
     │                        ▼                     ├──► Energy Dashboard
     │                      EMQX ◄──────────────────┘     (direct; amber
     │                   (MQTT broker)  (Modbus→EMQX        control when
     │                        ▲          bridge only;       writes enabled)
     │                        │          never reverse)
     │              Tasmota Wi‑Fi  ◄──►  (two-way MQTT)
     │                     │
     └──────────┬──────────┘
                │
         Energy Dashboard ◄──► AI Controller
         (PySide6 GUI)    ▲
                │         │
                └────► Databases ◄──── (two-way)
                │
     ┌──────────┼──────────────────┬──────────────────┐
                ▼                  ▼                  ▼
             PVOutput.org     Wonderwatt.com    (xlsx / CSV)

  Also into the dashboard (direct HTTP, not via Growatt kit):
    · Octopus Energy (REST / GraphQL — meters, Agile)
    · PV forecast (Forecast.Solar / Open‑Meteo)
```

**Growatt connection methods (the three pipes):**

| Path | Plain English | Typical role |
|------|----------------|--------------|
| **Growatt cloud API** | Dashboard talks to Growatt’s internet servers (REST). | Fallback / standby telemetry; many **schedule / mode writes** |
| **GROTT → EMQX MQTT** | Local process that intercepts/decodes Growatt’s **own cloud reporting stream** and republishes it on your MQTT broker | Often freshest live SOC / power |
| **Modbus TCP/RTU** | Direct register reads/writes on the LAN (inverter or serial–Ethernet gateway, e.g. USR). Dashboard talks to Modbus **directly**; readings can also be bridged onto EMQX (Modbus → broker only, never the reverse) | Fields Grott/cloud miss (e.g. multi-pack serials); Command Sim / probes |

**Community / external outputs:**

| Output | Plain English | Role |
|--------|----------------|------|
| **PVOutput.org** | Free community site for sharing live PV stats ([pvoutput.org](https://pvoutput.org/)) | We **push** live Add Status (Wh/W) when enabled in Setup |
| **Wonderwatt.com** | Hosted Growatt optimiser ([wonderwatt.com](https://www.wonderwatt.com/)) | Reads plant via **Growatt cloud** itself (no public upload API). We keep a share link for forecast compare on Potential Issues |

**Hybrid** in this app means: prefer Grott MQTT when healthy, fall back / patch gaps with the cloud API — still independent of Modbus.

Do not pretend any single pipe is complete. Connectivity / Setup UI should show which path is live.

The GUI is modular: one tab ≈ one module under `energy_dashboard/tabs/`. Shared chart/style helpers live in `ui/`. Pure planning maths belongs in `planner/`, not in widget code.

---

## Main layers

| Layer | Responsibility |
|-------|----------------|
| **Launcher** | `EnergyDashboard2.py` — venv re-exec, start Qt app. |
| **Main window** | `main_window.py` — tab host, global status, wiring. |
| **Tabs** | Feature UI and tab-local orchestration. |
| **Fetch** | Talk to external systems; parse into app-shaped data (Octopus, Grott MQTT, Growatt cloud, Tasmota, forecasts). |
| **DB** | Persist samples, retention, health stats. |
| **UI kit** | Dark theme, chart utilities, toasts, tab bar. Visual rules live in [`MOTIFS.md`](MOTIFS.md) (buttons, spin fields, alignment). |
| **Planner** | Optimiser / maximiser logic without Qt (“AI Controller” in the system diagram). |
| **Modbus** | Local Modbus TCP/RTU helpers, pack probes, Command Sim — peer to Grott/cloud for Growatt kit. |
| **Services** | Optional always-on collectors / brokers when the GUI is closed. |
| **Content** | About, changelog, per-tab help (plain English). |

Out of day-to-day scope: `legacy/`, `growatt2mqtt/`, one-off split tooling, virtualenv trees.

---

## Data paths (mental model)

1. **Live meters (Octopus)** — REST and/or GraphQL into Octopus / Octopus Live tabs; cumulative series may attach Growatt PV from the DB.
2. **Inverter / battery (Growatt) — three connection methods** (not a Wi‑Fi→API or LAN→Grott chain)
   - **Growatt cloud API**: REST to Growatt’s servers (fallback / writes).
   - **GROTT MQTT** (usually via **EMQX**): local decode of the inverter’s cloud reporting stream.
   - **Modbus TCP/RTU**: separate LAN register path; unrelated to Grott.
3. **Device watts (Tasmota)** — **two-way** with EMQX: devices publish `tele/` / `stat/`; the dashboard publishes `cmnd/` (and can HTTP-poll / send Power commands). Not a one-way sensor feed.
4. **PV forecast** — Forecast.Solar / Open-Meteo into Forecasts / Roof Layout.
5. **Writes to the inverter** — Treat as safety-sensitive. Many schedule/mode writes still go through **Growatt cloud**, even when live numbers are Grott or Modbus. Always confirm the write path before telling the human a setting “was applied”.

**Telemetry integrity:** architecture must not introduce display-side fudges. Estimates (e.g. coulomb-counted SOC) are separate, labelled series — see `AGENTS.md`.

---

## Decisions affecting architecture

Newest first. Keep each entry short: context → decision → consequence.

### 2026-09-26 — Collector stores PV string charge lots

- **Context:** String 1 and String 2 on PV String Charge only appeared from the moment the dashboard was opened. The chart reads `pv_string_charge`, and only the open dashboard was writing those 2-minute lots (BUG-071).
- **Decision:** `services/energy_collector.py` (the energy-collector boot service, also started as the broker) upserts the same lot on every Growatt poll: measured string kW, estimated charge from each string, and measured charge. It uses the table that already exists. It does not create it.
- **Consequence:** Do not log string contributions only from the GUI. Do not backfill hours the service did not see. Do not `CREATE TABLE` on the collector’s PostgreSQL login.

### 2026-09-26 — Popups stay ordinary windows

- **Context:** Every blocking popup was marked “keep above”, and a timer pulled focus back whenever the popup was not the active window. Copy and Paste menus closed at once, and a screenshot of the popup could not be taken (BUG-069).
- **Decision:** Do not set `WindowStaysOnTopHint` on dialogs. `ui/modal_ontop.py` raises a popup only when the main window is the one in front of it. A context menu, clipboard popup, or screenshot tool is left alone.
- **Consequence:** Do not put popups on the always-on-top layer to stop them slipping behind. Do not call `activateWindow()` on a dialog just because it is not active.

### 2026-09-26 — Maximise stops above the taskbar

- **Context:** On KDE Wayland a floating panel reserves no strut, so the compositor’s maximise is the full monitor. The earlier rule kept that maximised state and refused to shorten the height (a guessed title bar had left a gap). The window then covered the taskbar buttons (BUG-068).
- **Decision:** A maximise click snaps the window to the usable screen: Plasma panel thickness, plus a small pad when the panel floats. The compositor maximised state is cleared so that size sticks. The page area is not allowed to grow the window past that height, so the Refresh / Help / Close bar stays inside the window, above the taskbar. Do not subtract a guessed title bar; only a frame Qt has actually measured, or the overlap once the frame is seen hanging below the usable screen.
- **Consequence:** Do not leave the window in the compositor’s maximised state to “honour maximise”. Do not bring back a fixed title-bar cushion. Do not let a tall page push the bottom button bar off the screen. The 2026-09-22 “do not shorten maximised height” line is superseded by this.

### 2026-09-26 — Do not change a visible dialog’s window flags

- **Context:** Connectivity clicks open a blocking popup. The stay-on-top timer then added “keep above” by changing the window flags. Qt hides a window when its flags change. The popup was on screen for about a second, then gone, while the app was still waiting for an answer. On Wayland it did not come back, so the dashboard would not take another click (BUG-066).
- **Decision:** `ui/modal_ontop.py` sets stay-on-top only before the dialog is shown. Once it is visible, the timer may raise it. It must not call `setWindowFlags` on it.
- **Consequence:** Do not “fix” a dialog that slips behind by changing its flags while `exec()` is running. That hides the only window that can unblock the app.

### 2026-09-26 — Google historic is Earth, not a tile version

- **Context:** Roof layout used to offer older Google satellite versions. The public tile address now returns the current photo for every old version number. Dated Google photos are still in Google Earth, on its historical-imagery timeline. They are not the Esri Wayback archive.
- **Decision:** The imagery menu has a separate **Google historic** choice. It loads Google Earth web in the map panel at the roof. The outline map comes back with **Satellite map**. Do not decrypt Earth tile databases, and do not label Esri frames as Google.
- **Consequence:** Drawing a roof outline is paused while Earth is open. Historic satellite stays the Esri dated archive.

### 2026-09-25 — No Python event filter on the application

- **Context:** The dashboard segfaulted on the main thread (`getWrapperForQObject` re-entered from an application event filter during `doSetProperty`). On Roof layout the satellite map never appeared, because creating the map view sets a Qt property while that filter is live (BUG-060).
- **Decision:** Do not install a Python event filter on `QApplication`. `ui/modal_ontop.py` pins the active modal dialog from a short timer. Octopus Live watches Ctrl the same way, only while that page is shown.
- **Consequence:** A new blocking dialog is still covered without a call-site change. Do not add `app.installEventFilter` in Python. A filter on one widget is a different path; the application-wide one is what crashed the map.

### 2026-09-25 — Panel models are a house catalogue, not telemetry

- **Context:** Roof layout only offered a few generic wattages. Comparing a string’s measured volts with a module rating needs the datasheet the householder actually has, and that number must not be invented.
- **Decision:** **Physical Plant Tools → Panel database** stores maker, model, rated watts, size, and optional datasheet volts (Vmp, Voc, Imp) in app settings. A blank voltage stays blank. Roof layout’s panel menu reads this list. It is not a PostgreSQL table and it is not filled from Growatt.
- **Consequence:** Do not copy live string voltage into Vmp, and do not fill Vmp from a guessed datasheet.

### 2026-09-25 — String DC voltage is its own 2-minute table

- **Context:** Live MPPT volts (`vPv1` / `vPv2`) were only on Growatt Live Status. `growatt_readings` stores total PV power, not per-string volts, so a previous day had nothing to chart.
- **Decision:** `pv_string_voltage` keeps measured volts for each string, averaged into the same 2-minute UTC slots as string charge. A missing reading stays empty. It is not written as 0 V. PostgreSQL still gets the table from the owner script in Setup, not from the dashboard login.
- **Consequence:** History starts when this build is logging. Earlier days stay empty. Do not invent volts from power or from a panel datasheet. The chart is **Physical Plant Tools → String voltage**.

### 2026-09-25 — Qt wrappers stay out of the cycle collector; collection stays on

- **Context:** Long sessions segfaulted while a worker was inside Python’s cycle collector (`query_tasmota_power_history`) and the main thread was painting the tab bar. The 08:10 core dump shows the main thread destroying a Qt object (`_Py_Dealloc` / Shiboken `ThreadStateSaver`) and waiting for the Python lock, which the worker held inside the collector. 2.9.419 turned automatic collection off. That was rejected (BUG-059-20260925-02).
- **Decision:** Leave cyclic GC enabled. Remove PySide wrappers from the collector when they are created, and sweep any already alive. Reference counting still frees them on the thread that drops the last reference. Ordinary Python objects are still collected automatically.
- **Consequence:** Do not disable `gc` to paper over this crash. New Qt objects must stay out of the cycle collector. Do not put `QLabel` cell widgets back into a sorted table.

### 2026-09-24 — Agile Year prior-year delta via paint delegate (no cell widgets)

- **Context:** 2.9.417 put QLabel rich-text widgets in Avg −Ny table cells. A long-running 2.9.417 session then segfaulted in PySide `getWrapperForQObject` / `QObject::doSetProperty` — the same family as BUG-054-20260923-09. Sorted `QTableWidget` + `setCellWidget` is a known Shiboken lifetime trap.
- **Decision:** Keep the smaller bracketed (prior − this day) display, but paint it with a column `QStyledItemDelegate`. Store prior and this-day averages on the item roles; do not use `setCellWidget` for these columns.
- **Consequence:** Prefer item delegates over per-cell QWidgets in sortable tables. Do not reintroduce QLabel cell widgets here for styling.

### 2026-09-23 — Agile Year same-date prior-year averages (table only)

- **Context:** Comparing today’s Agile day to the same calendar date last year (and earlier) helps read whether a day is expensive for the season. The chart already shows a long window; the householder asked for the prior-year spot on the table, not another chart line. Fetch year had only asked for ~370 days, so the store stopped around 18 Sep 2025 even though Octopus had older rates for the current product. Later they asked for each past average to show how it sits relative to this year’s same-day average.
- **Decision:** Three table columns — Avg −1y / −2y / −3y — look up the stored daily average for the same month/day that many years earlier. Each cell shows that year’s average, then in brackets (2pt smaller) prior − this day’s average (negative = cheaper than this year). Missing history or an impossible date (29 Feb) show a dash. No invented prices; the chart is unchanged. Fetch year asks for about 1100 days so one and two years of same-date averages can populate when Octopus has that tariff history. (From 2.9.418 the smaller delta is painted by a delegate, not a cell QLabel.)
- **Consequence:** Do not invent prior-year rates from another tariff or from a rescaled trend. The earliest day is still whatever Octopus returns for the Forecasts tariff — not a fixed calendar start. Relative deltas are display-only arithmetic on measured daily averages, not a rescale of the prices themselves.

### 2026-09-23 — Cost view prices only import on the charts

- **Context:** Switching to Cost left the bottom chart as four energy lines, and the top chart mixed import with export credit. The householder wants Cost charts to change with the toggle: only the import line has a cost; Gen / Used / Exp (and the bottom-right energy labels) stay without cost.
- **Decision:** Cost top chart is import £/h only. Bottom chart keeps Gen / Used / Exp as kWh on the left axis; Imported becomes cumulative £ on a right-hand axis. Day notes on the top chart show import £ only.
- **Consequence:** Do not price PV, house use, or export on the Cost charts. Cards may still show export credit as a separate money figure.

### 2026-09-23 — Octopus Live bottom chart is always energy

- **Context:** Cost view replaced the cumulative bottom chart with import cost / export credit / net in pounds. That hid Generated (PV), Imported, Total Used, and Exported energy — the measures the householder uses to read the day.
- **Decision:** The bottom chart always keeps Gen / Used / Exp as kWh. Cost only turns the Imported series into £ (right axis). Total Used stays the labelled balance `import + PV − export`.
- **Consequence:** Do not put export or net money on the bottom pane. Day-end energy labels stay Gen / Used / Exp; Imp shows £ in Cost.

### 2026-09-23 — Fatal signals go to a crash log

- **Context:** A segmentation fault kills the process before Python’s exception hook or the Console logger can run. systemd-coredump keeps the core, but nothing in the app’s own log said the dashboard had died.
- **Decision:** `faulthandler` appends every thread’s Python stack to `~/.energy_dashboard_crash.log` at the fault. `run-dashboard.sh` waits for the process and appends the matching systemd core-dump stack (crashing thread plus where the core file is stored). The core file itself stays with systemd. A normal window close writes a clean-exit line and is not treated as a crash. The next launch copies any dashboard core the shell missed and adds one Crash line to the Console.
- **Consequence:** Do not turn this into a display-side workaround for a bad reading. Do not delete or rewrite `~/.energy_dashboard_crash.log` from the Console **Clear** button.

### 2026-09-22 — Octopus Live cost view

- **Context:** The live monitor showed watts and kWh. The householder also wants money, and the live stream does not match the half-hour meter Octopus later bills from.
- **Decision:** A Power / Cost radio on Octopus Live. Cost is interval energy × the Agile spot price (VAT included). Completed days that the half-hour meter has published stay as that meter × price — what Octopus states. Today is the live energy × the same price, multiplied by the median of (stated ÷ live) over recent settled days, clamped to 0.50–1.50, and labelled as an estimate. Standing charge is not included. The price and meter pull is throttled (about 20 minutes) and does not run while Power is selected. Cost only changes the top chart (£/h) and the cards; the bottom cumulative pane stays the four energy measures.
- **Consequence:** Do not present the scaled today line as a measurement or as a bill. Settled days must stay on the Octopus meter series. New cost maths live in `energy_dashboard/tabs/octopus_live_cost.py`. Do not put money series on the bottom pane.

### 2026-09-22 — Physical Plant Tools group

- **Context:** Battery Analysis, PV String Charge, and Potential Issues (formerly Pot. Issues) sat with the live dashboards or the import/export pages.
- **Decision:** Those three pages live in **Physical Plant Tools** (`physical_plant`), next to Dashboards, in that order. The tab title is **Potential Issues**. Dashboards is still the screen the app opens on.
- **Consequence:** New plant-side tools belong in that group. Page visibility stays the Setup checkboxes keyed `battery`, `pv_string_charge`, and `pot_issues`.

### 2026-09-22 — Maximise snaps to the monitor the window is on

- **Context:** Pressing maximise still made the frame wider than that screen. The window manager ignores Qt’s maximum size and will grow to the layout minimum when that minimum is wider than the monitor.
- **Decision:** Width is capped to `window.screen()` so a wide layout cannot spill past that monitor. Height follows the usable screen above the taskbar (see 2026-09-26 — Maximise stops above the taskbar). Do not subtract a guessed title bar.
- **Consequence:** Do not raise the window maximum to satisfy a layout minimum. Do not shrink the height for a guessed title bar. Do shorten it when the frame would cover the panel.

### 2026-09-22 — Window maximum is the screen it is on

- **Context:** The main window’s maximum was raised to the layout’s minimum size when that minimum was larger than the monitor. The frame could then be dragged bigger than the screen the window sits on.
- **Decision:** `fit_window_to_work_area` sets the maximum to the usable area of `window.screen()` (the screen the window is on), after room for the title bar and the taskbar. It is not increased to satisfy a larger layout minimum.
- **Consequence:** Moving the window to another monitor updates that cap (`screenChanged`). Do not call `setMaximumSize` with a size bigger than that screen.

### 2026-09-22 — One MQTT connection for the dashboard

- **Context:** Grott and the Tasmota tab each opened a paho client. Grott also used a new client name on every start (`energy_dashboard_grott_<time>`), so old sessions stayed on EMQX. Two dashboard windows shared the Tasmota name `energy_dashboard_tasmota` and kicked each other off every few seconds. The Tasmota alarm then sat on “no broker connection” for hours.
- **Decision:** `fetch/mqtt_session.py` owns a single client, `energy_dashboard`. Grott and Tasmota only subscribe on that socket. A second process does not connect (a lock file). Test and pipeline checks reuse the live session instead of opening another login. Reconnect uses that same client; the disconnect callback must not call `reconnect()` itself.
- **Consequence:** Do not construct a long-lived `mqtt.Client` in Grott or Tasmota. A one-shot test may still connect only when the shared session is down, and it must not use the client name `energy_dashboard`. Two dashboard windows cannot both be on the broker — close one.

### 2026-09-22 — Main window stays inside the usable screen; blocking dialogs stay on top

- **Context:** On KDE Wayland, Qt’s available geometry is the full monitor because a floating panel reserves no strut. Startup maximised the dashboard into that full rectangle, so the bottom of the window sat under the taskbar. Separately, a modal OK/Cancel box blocks the main window but could be stacked behind it, which freezes the app until the hidden box is found.
- **Decision:** `ui/work_area.py` fits the main window to the usable screen (Qt’s available geometry, further inset by Plasma panel thickness). Do not call `showMaximized()` for that fit. `ui/modal_ontop.py` raises a blocking dialog only when the main window has covered it (see 2026-09-26 — Popups stay ordinary windows). Do not mark the dialog always-on-top.
- **Consequence:** Do not size or maximise the main window to `screen.geometry()` or raw `availableGeometry()` on Wayland. A blocking dialog is raised again only when the main window covers it, not by an always-on-top flag, not by an application event filter, and not by changing window flags after the dialog is already visible. Non-modal windows (device web UI, toasts) may still go behind.

### 2026-09-22 — Agile Year daily stats are a logger table, not a one-shot API view

- **Context:** The year chart re-fetched ~370 days of half-hour rates every visit. Daily high / low / average lived only in memory, so a since-start trend could not outgrow one API window, and a sparse last day (standing rate / timezone spill) plus leftover twin axes drew a spike that was not in the table.
- **Decision:** Persist complete London days in `agile_year_daily` (upsert per tariff / direction / day). Half-hour slots stay in `agile_price_snapshots`. The tab loads stored days, merges a fresh Octopus fetch, and drops days with fewer than 40 slots. Trend lines are labelled fits of the daily average (monthly / YTD / yearly / since start); table LT columns use since start.
- **Consequence:** New PostgreSQL table must go through Setup CREATE (owner-run) like every other logger table. Do not invent missing days. Do not treat trend lines as measured prices.

### 2026-09-22 — Bug Tracker is a Controls tab over repo-root markdown

- **Context:** Defect history lived only in `bug_tracker.md` for agents; the householder had no in-app place to read open/fixed bugs.
- **Decision:** Controls group gains a static **Bug Tracker** tab that renders that file (Reload re-reads disk). Editing stays in the markdown file — the tab does not write bugs.
- **Consequence:** New defects still open in `bug_tracker.md` first. Do not duplicate the log into SQLite or invent a second store. Help / About changelog remain separate (product history vs defect history).

### 2026-09-21 — Grott present-set survives sparse Shine heartbeats

- **Context:** Connectivity showed “missing N registers — patched from Growatt cloud” while Grott MQTT was connected. Live MQTT alternates full hybrid frames with 5-key heartbeats (SOC + grid V/Hz).
- **Decision:** `_record_grott_present` unions keys across recent frames and expires them after the Grott fresh window. Gap-fill and amber sync use that set plus the display cache, not only the latest frame.
- **Consequence:** Do not treat a heartbeat-only payload as “Grott has no load/battery/PV”. Cloud fill-missing remains for registers Grott never publishes within the fresh window. Preferred long-term for fields Grott never sends is Modbus (peer path), not silent display fudge.

### 2026-09-21 — PostgreSQL logger tables are created by hand, not by the app login

- **Context:** The dashboard was signed in as the EMQX role on database `mqtt_user`. That role must not create objects in `public`. Live logging still ran `CREATE TABLE`, which PostgreSQL refused, and the app then treated the server as unreachable. Setup showed “Tables not readable (0/11)”.
- **Decision:** The Setup & Info PostgreSQL script is the full `CREATE IF NOT EXISTS` for every logger table. A person runs it as the database owner. The app login, the collector, and connectivity / PV-string writers only connect and use tables that already exist. SQLite and MySQL still create their own tables.
- **Consequence:** Do not put `CREATE TABLE` back on the PostgreSQL app connection. Do not grant the EMQX role `CREATE` on `public`. New logger tables still go in `full_schema.dialect_statements` so the hand-run script stays complete, and `TABLE_SUMMARIES` drives the matching `GRANT` lines.
- **Also:** ownership and access are separate. The script ends with `GRANT SELECT, INSERT, UPDATE, DELETE` per logger table (plus `USAGE, SELECT` on `SERIAL` sequences) for the login in Setup, because creating a table grants nothing to anyone else. `UPDATE` is required by the `ON CONFLICT DO UPDATE` upserts and `DELETE` by ring-buffer retention, so `SELECT`/`INSERT` alone is not enough.

### 2026-09-21 — Live alarms include database ingest and device silence

- **Context:** Battery/Grott alarms existed; the house also needed to know when rows stop landing in the logger and when kit (inverter / Tasmota) is not actually working.
- **Decision:** `AlarmMonitor` gained `db_disconnected`, `db_ingest_stale`, `inverter_comms_lost`, `tasmota_mqtt_lost`, `tasmota_offline`. Ingest stale only fires when Growatt or Tasmota is expected to be writing (fresh Grott / live cloud / named plugs) and the 15-minute insert count is zero — not when Grott is already stale and writes are skipped. Tasmota offline is named/seen devices only, not empty IPs in the scan range.
- **Consequence:** Same banner, tray backoff, and Connectivity diagram mapping as existing alarms. Do not invent device faults from unused addresses in the Tasmota IP range. A TCP connect is not ingest: if the login cannot SELECT/INSERT `growatt_readings`, treat that as table-access failure, not “zero rows / no PV today”.

### 2026-09-21 — Footer system strip polls DB off the GUI thread

- **Context:** Need a always-visible two-line footer (DB health + ingest 15m/1h/today, machine CPU/RAM with 1h rolling averages) without freezing the UI or adding psycopg3/psutil.
- **Decision:** `ui/system_status_bar.py` sits full-width above the existing QStatusBar. CPU/RAM come from `/proc`. DB identity and ingest use DataLogger’s primary backend (Setup & Info), a short-lived connection with the 3 s connect timeout, and `growatt_readings` + `tasmota_readings` insert timestamps (those columns are UTC write time). PostgreSQL can also report `pg_column_size` bytes; SQLite/MySQL show row counts. “Today” is Europe/London midnight.
- **Consequence:** Do not share the logger writer connection. Do not take ingest from device measurement time on other tables (e.g. Octopus `interval_start`). Do not poll on the GUI thread.

### 2026-09-21 — Agile Year uses Octopus historic unit rates, not a stretched slot grid

- **Context:** Agile Spot Prices is a three-day colour grid with a 90-day walk through stored snapshots. The house needed a year of daily high / low / average and hours with price below 0p.
- **Decision:** New **Agile Year** tab fetches ~370 London days of public `standard-unit-rates` for the Forecasts import/export tariff (`fetch_agile_standard_unit_rates`), merges any DB snapshots, and aggregates per Europe/London day. Negative hours = sum of slot durations where `price_pence < 0` (usually 0.5 h). Missing days are omitted.
- **Consequence:** Do not reuse the 90-day slot grid or Forecasts’ 7-day fetch for this view. Do not invent prices for days Octopus did not return (e.g. a product code you were not on). Persist fetched slots via `log_agile_forecast` when logging is on.

### 2026-09-21 — Unreachable databases must not block the UI

- **Context:** With PostgreSQL or MySQL enabled but the host down or firewalled, TCP connect could wait 1–2 minutes. Live Grott updates, connectivity history, and logger writes retried that wait on (or in front of) the GUI thread, so the whole app felt frozen.
- **Decision:** Bound MySQL/PG connect to 3 seconds. After a failure, skip that engine for 5–60 s (exponential backoff). Persist connectivity events and PV-string lots via the writer thread, not the GUI. User-initiated Test Connection still tries immediately.
- **Consequence:** A disconnected database must fail fast and stay out of the way. Do not reconnect on every sample from the UI thread. Do not raise the connect timeout back to OS defaults.

### 2026-09-21 — One create-all SQL source for every logger table

- **Context:** Setup Database only created four tables (`growatt_readings`, `tasmota_readings`, `tasmota_devices`, `octopus_readings`). Live logging later created the rest, so a fresh Postgres/MySQL/SQLite setup looked “OK” while forecasts, MIX chart, shadow trial, connectivity history, and PV string charge were missing. Setup & Info also had no script to copy.
- **Decision:** `energy_dashboard/db/full_schema.py` is the single ordered CREATE list for sqlite / mysql / pg. Setup Database, DataLogger `_ensure_*`, and the right-hand Setup & Info SQL pane all use it. `postgres_reset_schema.sql` is the wipe-and-recreate sibling (same tables, DROP first).
- **Consequence:** New logger tables must be added to `full_schema.dialect_statements` (and TABLE_SUMMARIES). Do not add a fourth copy of CREATE TABLE in `schema.py`.

### 2026-09-17 — PV String Charge: instantaneous kW vs daily kWh

- **Context:** One chart mixed 6-hour string/forecast kW with a cumulative kWh twin axis, so the energy line was unreadable against the power scale (and the reverse).
- **Decision:** Two stacked panes. Top: last 6 hours of measured string kW, charge kW, and forecast kW. Bottom: kWh from London midnight for String 1, String 2, both, and the forecast integrated the same way. Still stored as 2-minute lots in `pv_string_charge`.
- **Consequence:** Do not put kWh on the instantaneous axis (or kW on the daily energy axis). Cumulative forecast is labelled as forecast, not a meter.

### 2026-09-17 — mix_status string PV is kW, same as total PV

- **Context:** Grott/`ppv` and `chargePower` were kW, but `pPv1` / `pPv2` stayed in watts. PV String Charge then used `abs(n) > 50` to guess units, so dawn 10–50 W became 10–50 kW on the chart.
- **Decision:** Convert string power with the same watts→kW path as total PV (Grott `_maybe_w_to_kw`, cloud `_growatt_watts_to_kw`). The tab still sanitises leftover lots.
- **Consequence:** MIX `pPv1`/`pPv2` are kW everywhere (Growatt Physical formats them as W for the householder). Do not reintroduce a `> 50` unit heuristic.

### 2026-09-16 — PV string charge estimates persist in their own table

- **Context:** The PV String Charge tab only kept a session deque, so the 6-hour chart vanished on restart. A stacked area also made String 2 look “higher” even when String 1 contributed more.
- **Decision:** Store each estimate in `pv_string_charge` (SQLite / MySQL / PostgreSQL). The chart is a rolling 6-hour window of overlaid (not stacked) series, plus cumulative kWh and the solar forecast for the same window.
- **Consequence:** Do not reconstruct this from `growatt_readings` (no per-string PV there). Treat the series as labelled estimates. Retention / Database Viewer / Connectivity volumes include the new table. Chart layout later split (2026-09-17): 6-hour kW vs daily kWh — do not put them on one mixed axis.

### 2026-09-16 — Grott MQTT never treats Shine buffer dumps as live

- **Context:** Grott republishes historical Shine frames (`buffered: yes`, often stamped 00:10) on the same `energy/growatt` topic as live status. Grott’s `sendbuf = False` does not actually stop MQTT (ini boolean left as the string `"False"`). Merging those frames made live cards look fresh with midnight numbers.
- **Decision:** Dashboard ingest ignores historical/buffered Grott JSON. Freshness and alarms stay tied to live frames only. Shine’s ~11 min quiet after reconnect is a real gap (Hybrid may use cloud); the alarm must not call it an MQTT drop.
- **Consequence:** Agents must not “refresh” `received_at` from buffered payloads. Do not fudge the 11 min hole — explain it, Hybrid-fill, or fix Grott/Shine.

### 2026-09-15 — MOTIFS.md as UI design source of truth

- **Context:** Button green, electric-blue spins, and field alignment were encoded in `ui/` helpers but not written down; agents kept re-learning layout rules from chat.
- **Decision:** Root [`MOTIFS.md`](MOTIFS.md) documents those motifs and is part of the basic instruction set (`AGENTS.md`).
- **Consequence:** UI/layout work should follow MOTIFS first; motif changes in code must update the file.

### 2026-09-15 — Connectivity State menu is context-aware

- **Context:** One menu (Disable / Highlight / History) for every row; Databases should not be “disabled”, and external peers need Test / Downtime / Alarms during incidents (e.g. Grott lost).
- **Decision:** Per-row capabilities on `_SERVICE_ROW_META`: Show Alarms; Test Connection + Show Downtime for Octopus / Forecast.solar / PVOutput / Wonderwatt / Databases; no Disable on Databases.
- **Consequence:** New service rows must declare capabilities; downtime is derived from warn/fault → recover edges in `connectivity_events`.

### 2026-09-15 — Degradation must explain itself on the Connectivity diagram

- **Context:** Hybrid fallback showed only a short card subtitle (“fallback (Grott stale)”) while the rest of the diagram still looked healthy — hard to see what was carrying live data.
- **Decision:** When degraded, draw a DEGRADED banner with plain-English findings, escalate Grott/EMQX/cloud card borders and path colours, and put a “What’s happening right now” block in click details (age, disconnects, which path is live).
- **Consequence:** Agents must keep `_degradation_findings` in sync with new failure modes; do not rely on colour alone.

### 2026-09-15 — Alarms visible on Connectivity diagram boxes and links

- **Context:** Alarms only appeared in the top banner / tray; the architecture diagram did not show which pipe or device was implicated.
- **Decision:** Map AlarmMonitor keys onto diagram boxes and edges; tint borders, add WARN/ALARM badges, escalate link colour. Connectivity warn/bad from the status table also drives card borders.
- **Consequence:** Agents should keep `_ALARM_DIAGRAM_MAP` in sync when adding new alarm keys.

### 2026-09-15 — Inverter pipes show return lanes; Grott→EMQX must stay visible

- **Context:** Reverse Cloud/Grott/Modbus↔inverter edges and Grott→EMQX were defined but shared exact endpoints with the opposing amber/data lane, so they drew on top of each other and looked missing.
- **Decision:** Give each pair parallel ports (upper = telemetry away from inverter / Grott→EMQX; lower = return). Keep Modbus→EMQX one-way into the broker.
- **Consequence:** Connectivity diagram shows six inverter right-edge ports and a dedicated Grott→EMQX data lane that cannot be covered by the EMQX→Grott topology return.

### 2026-09-15 — Modbus inverter writes are opt-in

- **Context:** Connectivity showed Modbus as read-only; human wants local inverter writes to be enableable without inventing a schedule register map yet.
- **Decision:** Add `growatt_modbus_writes_enabled` (default off). Setup checkbox + Connectivity **Inverter write** right-click Enable/Disable. Diagram amber Dashboard→Modbus lights only when enabled. Cloud REST schedule push unchanged.
- **Consequence:** Command Sim / future local write paths must check `growatt_modbus_writes_allowed` before writing holding registers.

### 2026-09-15 — Connectivity State context menu (mute / highlight / history)

- **Context:** Human needs to mute a noisy row, find its diagram links, and see past alarms without leaving Connectivity Status.
- **Decision:** Right-click **State** cell → Disable/Enable (QSettings mute; does not tear down live feeds), Highlight on diagram (blink matching links at 2× thickness), Show history (`connectivity_events` table + AlarmMonitor buffer for Grott-related rows).
- **Consequence:** Schema gains `connectivity_events` on SQLite/MySQL/PostgreSQL; help text documents the menu.

### 2026-09-15 — Modbus → Dashboard is direct (plus EMQX bridge)

- **Context:** Diagram had Modbus only feeding EMQX then the dashboard; the app also reads/writes Modbus on the LAN without the broker.
- **Decision:** Draw a direct Modbus → Dashboard data lane (and keep Dashboard → Modbus control) in addition to the one-way Modbus → EMQX bridge. Left-edge ports stay equally spaced and nested under the EMQX lanes.
- **Consequence:** Click-copy and architecture text must not imply Modbus telemetry only arrives via MQTT.

### 2026-09-15 — AI Controller and Databases are two-way with the dashboard

- **Context:** Diagram showed single lines from dashboard up to AI / Databases; both are really bidirectional (live feed ↔ optimise; write/log ↔ read/query).
- **Decision:** Draw parallel lanes for AI ↔ Dashboard (violet data up, amber control down) and Databases ↔ Dashboard (violet both ways). Keep the AI ↔ Databases peer link on the same top row.
- **Consequence:** Card subtitles use ↔ wording; click-copy should not describe either as a one-way sink.

### 2026-09-15 — Tasmota ↔ EMQX is two-way MQTT

- **Context:** Diagram looked like Tasmota only fed the broker; in practice plugs accept `cmnd/` (and HTTP) as well as publishing telemetry.
- **Decision:** Draw two parallel Home-LAN lanes between Tasmota and EMQX (tele/stat up, cmnd down). Keep Modbus one-way into EMQX.
- **Consequence:** Click-copy and architecture text must not call Tasmota a one-way sensor path.

### 2026-09-15 — Community outputs: PVOutput push + Wonderwatt share

- **Context:** Human asked for dashboard outputs to pvoutput.org and wonderwatt.com.
- **Decision:** **PVOutput** is a real outbound upload (Add Status API; Setup credentials; throttled from Growatt live updates). **Wonderwatt** has no public upload API — it pulls Growatt cloud itself; we surface it as an architecture output and keep the Advanced share link for forecast compare. Both appear on the Connectivity diagram under the dashboard (planar stack).
- **Consequence:** Do not invent a Wonderwatt POST path. PVOutput must never fudge Wh/W — use reported `epvToday` / `ppv` (and optional load).

### 2026-09-15 — Modbus feeds EMQX (one-way) and routes must not cross boxes

- **Context:** Diagram had Modbus going straight to the dashboard, and some curves passed underneath the EMQX / Modbus boxes.
- **Decision:** Data flow is Modbus → EMQX → dashboard (the broker never drives Modbus registers). Modbus box sits directly under EMQX so the feed is a short vertical line; all anchors chosen so no line passes under a box. Dashboard→Modbus amber control (writes) stays direct.
- **Consequence:** EMQX health/volumes include bridged Modbus alongside Grott and Tasmota.

### 2026-09-15 — Connectivity diagram shows three Growatt methods only

- **Context:** The in-app diagram still showed separate “WiFi Direct” and “LAN Direct” boxes; the human wants only the three real connection methods.
- **Decision:** Diagram boxes are **Growatt API**, **GROTT**, and **Modbus** only. Stick web UI / ShineLan stays as optional Setup diagnostics, not a fourth architecture box.
- **Consequence:** Pipeline probe and health wiring follow the same three-pipe model; EMQX health is Grott + Tasmota MQTT, not Modbus.

### 2026-09-15 — Growatt peers are independent (not Wi‑Fi→API / LAN→Grott)

- **Context:** An early system drawing chained “Wi‑Fi Direct → Growatt API” and “LAN Direct (Modbus) → Grott”. That is wrong.
- **Decision:** Document three **independent** Growatt connection methods: cloud API, Grott (MQTT), Modbus TCP/RTU. Hybrid = Grott preferred + API fallback — not “Modbus feeds Grott.” Stick web UI is diagnostics only.
- **Consequence:** Agents and diagrams must not imply Wi‑Fi causes the API or LAN Modbus causes Grott. Pack serials / missing registers may still need Modbus while Grott and API are both fine.

### 2026-09-15 — Document Modbus as a peer Growatt path

- **Context:** Modbus TCP/RTU is used in production for fields Grott/cloud miss.
- **Decision:** Treat Modbus as a **first-class telemetry/control pipe** alongside Grott MQTT and the Growatt cloud API.
- **Consequence:** “Connected” / pack identity may be Modbus even when Grott and cloud look fine. “Local” does not mean Grott-only.

### 2026-09-15 — Agent operating docs at repo root

- **Context:** Need a durable brief for AI agents (tone, solar domain, where to look).
- **Decision:** Root `AGENTS.md` is the entry point to the **basic instructions for the development environment**: `architecture.md`, `worklog.md`, `skills.md`, and `bug_tracker.md`. Always-on Cursor rule forces reading that set every session.
- **Consequence:** Agents must open these files rather than inventing process from chat memory.

### Earlier (established in codebase) — Modular package over monolith

- **Context:** Original dashboard grew as a single large script.
- **Decision:** Split into `energy_dashboard/` package (tabs, fetch, db, ui, …) with a thin launcher.
- **Consequence:** New features land as tab/fetch modules; `legacy/` stays frozen unless explicitly revived.

### Established — Local Grott + cloud API + Modbus (three pipes)

- **Context:** Growatt cloud alone is laggy / incomplete; Grott is incomplete on some pack fields; some writes are cloud-only; some registers only appear on Modbus.
- **Decision:** Hybrid ingestion — **Grott MQTT + Growatt cloud API + Modbus TCP/RTU** as peers; do not pretend one pipe is universal.
- **Consequence:** UI and Connectivity/Setup must show which path is live; pack serials may need Modbus even when Grott “works.”

### Established — Europe/London day boundaries for daily charts

- **Context:** UK tariffs and household mental model are calendar-local, not UTC blobs.
- **Decision:** Daily resets / day labels for key cumulative views use **Europe/London** midnights.
- **Consequence:** Chart and aggregator code must convert timezones explicitly; “end of day” labels hang off London days.

### Established — QSettings for GUI prefs, env for secrets

- **Context:** Operators need sticky UI prefs without baking tokens into git.
- **Decision:** `QSettings("PowerModel", "EnergyDashboard2")` for GUI; prefer environment variables for credentials.
- **Consequence:** Save-settings bugs are often “load path missed”, not “disk write failed”.

---

## When you change architecture

1. Update this file (diagram and/or a new Decision).
2. Note the day in `worklog.md` in plain English.
3. If the change is user-visible, bump `energy_dashboard/version.py` and `content/about.py` as usual.
