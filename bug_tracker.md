# bug_tracker.md — PowerModel / Energy Dashboard

Part of the **basic instructions for the development environment** (see `AGENTS.md`).

**Every bug** that affects the app — crash, wrong diagram, bad chart maths, broken save, misleading UI — is logged here. Newest first.

## Agent duty

1. When a bug is reported or found, **append an entry immediately** (even before you fix it): timestamp, symptom, where it showed up.
2. When fixed, **update that same entry** with cause, resolution, fix time, and app version (if shipped). Do not delete entries.
3. Keep language plain English. Separate **what the user saw** from **what was wrong in software**.
4. This log does **not** replace the in-app About changelog or `worklog.md` — it is the standing defect history.

## Entry template

Copy this block for each new bug:

```markdown
### BUG-YYYYMMDD-NN — short title

| Field | Value |
|-------|--------|
| **Opened** | YYYY-MM-DD HH:MM (Europe/London) |
| **Status** | open / fixed |
| **Area** | tab or module |
| **Version found** | x.y.z or unknown |
| **Version fixed** | x.y.z / — |

**Symptom:** What the human saw (error text, wrong chart, crash).

**Cause:** Root cause once known (or “investigating”).

**Resolution:** What changed to fix it (files / behaviour). Empty while open.
```

IDs are `BUG-` + date + two-digit sequence for that day (`01`, `02`, …).

---

## Open

### BUG-20260923-10 — Octopus Live Cost hid the four energy measures

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-23 15:53 (Europe/London) |
| **Status** | fixed |
| **Area** | Octopus Live (`tabs/octopus_live.py`, `ui/chart_utils.py`) |
| **Version found** | 2.9.411 |
| **Version fixed** | 2.9.412 |

**Symptom:** In Cost view the charts showed Cost rate (£/h) and Cumulative £ (Import cost / Export credit / Net). The householder said that was wrong — the measures are Generated Energy (PV), Imported Energy, Total Used Energy, and Exported Energy.

**Cause:** Cost mode replaced both panes with money. The bottom cumulative chart should stay energy; only the top pane and cards are money. Power’s cumulative pane also omitted Exported as its own line (export was only inside the used-energy formula).

**Resolution:** Bottom chart always draws the four energy series in Power and Cost. Cost keeps £/h on top and £ on the cards. Day labels are Gen / Imp / Used / Exp.

### BUG-20260923-09 — Dashboard segmentation fault during Qt property update

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-23 10:13 (Europe/London) |
| **Status** | open |
| **Area** | GUI thread (PySide / Qt) |
| **Version found** | unknown (process `python EnergyDashboard2.py`, pid 823083) |
| **Version fixed** | — |

**Symptom:** `./run-dashboard.sh` died with `segmentation fault (core dumped)`. zsh job `[1] 823083`. systemd-coredump has the core at 10:12 BST.

**Cause:** Investigating. The crashing thread was inside PySide `getWrapperForQObject` while Qt was applying a property (`QObject::doSetProperty`) from the main event loop. That is the same family as a deleted widget still receiving an event (Shiboken wrapper). WebEngine threads were alive in the same process but were not the thread that faulted.

**Resolution:** Empty while open. From 2.9.411 a repeat is written to `~/.energy_dashboard_crash.log` (Python stacks plus this kind of core-dump stack) and a Crash line on the Console. That does not stop the fault.

### BUG-20260923-06 — Setup Database Export: status and SQL panes still misaligned

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-23 09:26 (Europe/London) |
| **Status** | open |
| **Area** | Setup & Info → Database Export (`tabs/parameters.py`) |
| **Version found** | 2.9.406 |
| **Version fixed** | — |

**Symptom:** On Setup & Info → Database Export, the layout still does not match the agreed motif (see `MOTIFS.md` §F). Reported again with a screenshot after earlier alignment work:

1. **Connected status** (e.g. “PostgreSQL DB seen” / “Database connected” / “Tables not connected (11/12)”) still sits in the **middle gap** between the Host/Port/… fields and the create-all SQL box — not immediately after the fields and left-aligned. SQLite/MySQL “Disabled” shows the same floating mid-row look.
2. **Create-all SQL** panes on the right are not lined up as one consistent column across SQLite, MySQL, and PostgreSQL (left edges / widths disagree between rows), and the SQL side still feels too wide vs “stop around mid-window” expectations from recent layout requests.

**Cause:** Investigating. Prior fix BUG-20260921-02 left-aligned status with `Maximum` width and gave leftover width to the SQL pane, but the three engine rows still do not share one field / status / SQL column grid in practice.

**Resolution:** Empty while open. Target per motif: status immediately after the host/file fields (left-aligned); SQL panes share one left edge and width across all three engines.

### BUG-20260923-04 — Dashboard freezes / goes sticky after running a while

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-23 09:15 (Europe/London) |
| **Status** | open |
| **Area** | GUI thread (Octopus Live, Growatt, matplotlib); Growatt HTTPS |
| **Version found** | ~2.9.404 (live PID 652826, ~9.5 h uptime) |
| **Version fixed** | — |

**Symptom:** After the dashboard has been open for a while, the window stops responding cleanly — clicks and tab changes lag or feel frozen. Reported by the human; confirmed against a live long-running process on this machine.

**Cause:** Investigating. Strong suspects from code + live process:

1. **GUI-thread database + chart work** — Octopus Live `_update_display` (GUI) calls `_attach_cumulative_pv` → `query_growatt_pv_actual`, which opens Postgres and scans `growatt_readings` with Polars `infer_schema_length=None`, then does synchronous `canvas.draw()`. Same pattern of sync `canvas.draw()` on Tasmota. A slow DB or a large window can stall the UI for seconds on every auto-refresh.
2. **Main-thread CPU** — live PID 652826 (~9.5 h): main thread alone was burning ~65 CPU ticks / 2 s while process RSS ~660 MB. Not a hard deadlock; more like the GUI event loop busy with work.
3. **Growatt HTTPS half-closed sockets** — same process had two `CLOSE-WAIT` connections to `openapi.growatt.com` / `api.growatt.com` (8.211.2.163). growattServer keeps a `requests.Session`; leaked sockets can pile up over a long session.
4. **Prior mid-session SEGV** — BUG-20260921-10 (Shiboken / worker race) can look like a freeze then crash; Invoker QueuedConnection partially hardened in 2.9.380 but root cause still open.

**Resolution:** Empty while open. Likely fixes: move PV DB attach off the GUI thread; prefer `draw_idle`; close / recycle Growatt HTTP sessions; re-check worker→GUI Invoker paths if SEGV returns.

### BUG-20260921-10 — Mid-session SEGV (Shiboken import vs GUI paint)

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-21 22:13 (Europe/London) |
| **Status** | open |
| **Area** | Qt / threading (`core/invoker.py`, worker threads) |
| **Version found** | ~2.9.379 (PID 345239) |
| **Version fixed** | — |

**Symptom:** zsh reported `[8] 345239 segmentation fault (core dumped)` for `./run-dashboard.sh` / `EnergyDashboard2.py`. Not an immediate launch crash — the process had been running for a long session.

**Cause:** Core dump (thread 356856): SEGV in `_Py_HandlePending` while a late-started worker was in `PyImport_Import` / Shiboken. Main thread (345239) was mid-widget paint (`paintAndFlush` → QtWidgets abi → Shiboken `ThreadStateSaver` / GIL). Not the Linux WebEngine/GPU startup path (BUG-20260915-05 / BUG-20260917-05). Likely a worker/GIL/Shiboken race; Invoker AutoConnection from plain `threading.Thread` can also run slots off the GUI thread.

**Resolution:** Partial hardening in **2.9.380** — `Invoker` now forces `QueuedConnection` so worker `invoke()` always posts to the GUI thread. Fresh `./run-dashboard.sh` smoke-tested ~12s without SEGV. Full root cause of the import race still open if it recurs.

## Fixed

### BUG-20260923-08 — Octopus Live Cost Import cost looked wrong without Today

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-23 09:46 (Europe/London) |
| **Status** | fixed |
| **Area** | Octopus Live Cost cards (`tabs/octopus_live.py`) |
| **Version found** | 2.9.408 |
| **Version fixed** | 2.9.409 |

**Symptom:** On Cost view with a 24 h window, **Import cost** showed ~£12.68 while the cumulative chart’s today import was ~£4.50. The card looked wrong; there was no today figure on the card.

**Cause:** The large card figure is the Hours window total (yesterday’s settled portion + today). That matched the chart’s day segments added together, but the card title did not say so and Today was only in the live summary text.

**Resolution:** Keep the window total as the large figure; add smaller muted `(Today: £…)` to the right (same for Export credit). Tooltips and help spell out window vs today.

### BUG-20260923-07 — Dashboard would not start (Command Sim NameError)

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-23 09:41 (Europe/London) |
| **Status** | fixed |
| **Area** | Command Sim (`modbus/command_sim.py`) |
| **Version found** | 2.9.407 |
| **Version fixed** | 2.9.408 |

**Symptom:** `./run-dashboard.sh` crashed on launch with `NameError: name '_SPIN_FIELD_MOTIF_DB_W' is not defined` while building Command Sim.

**Cause:** Command Sim is loaded via `common.py` and does `from energy_dashboard.common import *` while that module is still initialising. Without `__all__` yet, star-import skips underscore names, so motif helpers arrived but `_SPIN_FIELD_MOTIF_DB_W` did not.

**Resolution:** Import `_SPIN_FIELD_MOTIF_DB_W` and the motif helpers explicitly from `ui.palette` / `ui.styles`.

### BUG-20260923-05 — Grott Setup “connected · fresh” looked white

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-23 09:17 (Europe/London) |
| **Status** | fixed |
| **Area** | Grott Setup (`tabs/grott_setup.py`) |
| **Version found** | 2.9.404 |
| **Version fixed** | 2.9.405 |

**Symptom:** Live feed showed `Source: hybrid · connected · fresh` in plain white, so the healthy state did not read as OK.

**Cause:** `lbl_live` stylesheet set `color: #cdd6f4`, which overrides HTML `<span style='color:…'>` on Qt labels.

**Resolution:** Dropped the stylesheet colour; “connected · fresh” is bold green (`#a6e3a1`), with bold amber/red for stale / not connected.

### BUG-20260923-03 — Octopus Energy Data chart stays empty

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-23 00:54 (Europe/London) |
| **Status** | fixed |
| **Area** | Octopus Energy Data (`tabs/octopus.py`, `fetch/octopus_rest.py`) |
| **Version found** | 2.9.403 |
| **Version fixed** | 2.9.404 |

**Symptom:** Octopus Energy Data showed “--” on every summary card and a blank white chart. Octopus Live on the same account was still drawing.

**Cause:** This tab sent the default API key from the secrets file. Octopus rejected it (HTTP 401, “Invalid API key”). The failure was thrown away and looked like “no data”. The key saved on Octopus Live is a different key, and that one is accepted.

**Resolution:** The API key box and the fetch use the saved Octopus Live key. A rejected fetch writes the reason on the chart instead of leaving a white plot.

### BUG-20260923-02 — Database Viewer table list was missing logger tables

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-23 00:31 (Europe/London) |
| **Status** | fixed |
| **Area** | Database Viewer (`tabs/database_viewer.py`) |
| **Version found** | 2.9.402 |
| **Version fixed** | 2.9.403 |

**Symptom:** The Table menu on Database Viewer listed seven tables. Solar forecast, the MIX chart, shadow-trial plans, shadow-trial scores, and connectivity history were not there.

**Cause:** The menu was a short hardcoded list, not the full logger-table set used by Setup Database.

**Resolution:** The menu is now that full set (twelve tables), and the popup is tall enough to show every name. Status uses the same set, including the two shadow-trial tables.

### BUG-20260923-01 — Broker test hid where the database host is set

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-23 00:23 (Europe/London) |
| **Status** | fixed |
| **Area** | Setup & Info → Background collector (`tabs/parameters.py`, `services/energy_collector.py`) |
| **Version found** | 2.9.401 |
| **Version fixed** | 2.9.402 |

**Symptom:** Broker URL test said the collector could not reach PostgreSQL (“No route to host”) and printed an address, but not which setting that address came from.

**Cause:** `/health` only returned the database driver’s raw error. The host lives in Setup & Info → PostgreSQL Host (`db/pg_host`) and, for the collector, in `POWERMON_PG_HOST`. The example env file also carried a site address.

**Resolution:** The test and the collector status line name both places and the current values. `/health` reports the host, port, and database the process was started with (no password). The example env file no longer contains a site address.

### BUG-20260922-16 — Battery simulator stays blank when history is too short

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 23:05 (Europe/London) |
| **Status** | fixed |
| **Area** | Battery Expansion Simulator (`tabs/analytics.py`) |
| **Version found** | 2.9.398 |
| **Version fixed** | 2.9.399 |

**Symptom:** Run Simulation with no usable history left four empty white charts (axes 0 to 1). The only explanation was a short line in the status bar: “No data. Enable database logging or fetch Octopus data.”

**Cause:** The “not enough data” path updated the status bar only. The figure was never redrawn, so it stayed on Matplotlib’s default empty axes.

**Resolution:** **2.9.399** — fewer than 48 half-hour slots (one day) from Growatt or from the Octopus fallback stops the run. The charts and Simulation Results say how many slots were found and what to do next.

### BUG-20260922-15 — Run Advisor stays dark green after a good run

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 23:06 (Europe/London) |
| **Status** | fixed |
| **Area** | Smart Advisor (`tabs/smart_advisor.py`, `ui/buttons.py`) |
| **Version found** | 2.9.398 |
| **Version fixed** | 2.9.399 |

**Symptom:** Run Advisor completed (recommendation, charts, “Smart Advisor complete”) but the button stayed the ordinary muted green.

**Cause:** The button always used the default primary-button style. Nothing painted the “just refreshed” pale green after a successful run.

**Resolution:** **2.9.399** — a finished run paints Run Advisor `#5daf6e` with black text (same green as a fresh page tab). A failed run paints it black with white text.

### BUG-20260922-14 — Launch still prints EGL DRM and GPUInfo lines

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 21:43 (Europe/London) |
| **Status** | fixed |
| **Area** | Launch (`run-dashboard.sh`, `qt_env.py`) |
| **Version found** | 2.9.397 |
| **Version fixed** | 2.9.398 |

**Symptom:** `./run-dashboard.sh` printed `EGL: Failed to query DRM render node file path. Fallback to /dev/dri/renderD128.` then `GPUInfo not initialized on GpuInfoUpdate`.

**Cause:** The earlier quiet-GPU workaround (BUG-20260917-05) set `LIBGL_ALWAYS_SOFTWARE` and Chromium `--disable-gpu` / `--use-gl=disabled`. Those two settings are what print the lines. Qt software OpenGL by itself does not.

**Resolution:** **2.9.398** — drop those flags on launch. Keep `QT_OPENGL=software` and the software-OpenGL attribute. Hardware GPU is still `POWERMODEL_WEBENGINE_GPU=1`.

### BUG-20260922-13 — Maximise shortened the window

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 21:32 (Europe/London) |
| **Status** | fixed |
| **Area** | Main window (`ui/work_area.py`) |
| **Version found** | 2.9.396 |
| **Version fixed** | 2.9.397 |

**Symptom:** Maximising left a gap under the dashboard. The window was shorter than the screen.

**Cause:** The maximise snap subtracted a guessed title-bar height from the screen, then left the maximised state and applied that shorter size.

**Resolution:** **2.9.397** — maximise stays maximised. Height is the full usable screen (above the taskbar). Width is still capped to that monitor.

### BUG-20260922-12 — Maximise made the window wider than the screen

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 21:23 (Europe/London) |
| **Status** | fixed |
| **Area** | Main window (`ui/work_area.py`, `main_window.py`) |
| **Version found** | 2.9.392 |
| **Version fixed** | 2.9.396 |

**Symptom:** Maximising the dashboard made it wider than the screen it was on.

**Cause:** The window manager’s maximise ignores the Qt maximum size. Pages whose layout minimum is wider than the monitor (the tab widget takes the widest page) made that maximised width follow the layout, not the screen.

**Resolution:** **2.9.396** — maximise snaps the frame to that monitor’s usable resolution. The layout is not allowed to ask for a minimum bigger than that screen.

### BUG-20260922-11 — Main window could grow past its monitor

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 21:12 (Europe/London) |
| **Status** | fixed |
| **Area** | Main window (`ui/work_area.py`) |
| **Version found** | 2.9.391 |
| **Version fixed** | 2.9.392 |

**Symptom:** The dashboard could be made larger than the screen it was sitting on.

**Cause:** The maximum size was raised to the layout’s minimum whenever that minimum was bigger than the monitor, so the frame was allowed to extend past that screen.

**Resolution:** **2.9.392** — the maximum is the usable area of the screen the window is on (still clear of the taskbar). Moving to another monitor updates the limit.

### BUG-20260922-10 — Two dashboards kick each other off MQTT every few seconds

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 11:45 (Europe/London) |
| **Status** | fixed |
| **Area** | Grott MQTT / Tasmota MQTT (`fetch/mqtt_session.py`) |
| **Version found** | 2.9.388 |
| **Version fixed** | 2.9.391 |

**Symptom:** EMQX subscriptions show MQTT sessions dropping and coming back every few seconds. Several `energy_dashboard_grott_<time>` clients sit on the broker at once, plus one `energy_dashboard_tasmota`. Later the Tasmota alarm said the broker had been down for hours.

**Cause:** Two Energy Dashboard processes were logged into the same broker. Tasmota always used the client name `energy_dashboard_tasmota`, so the broker kept only one and the other immediately signed back in. Grott used a new client name on every start and did not always close the previous session, so those sessions piled up. The plugs were not doing this.

**Resolution:** **2.9.391** — one shared broker connection named `energy_dashboard` for Grott and Tasmota. A second dashboard does not open another session. Restart and leave a single window running.

### BUG-20260922-09 — Octopus link missing from the status line

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 11:30 (Europe/London) |
| **Status** | fixed |
| **Area** | Octopus Live, bottom status strip |
| **Version found** | 2.9.387 |
| **Version fixed** | 2.9.388 |

**Symptom:** On Octopus Live the status next to Fetch Live Data listed GraphQL, slot counts, and how old the newest reading was. It did not say whether the link to Octopus was up. The bottom strip showed the database and Growatt/Tasmota ingest, and not Octopus.

**Cause:** That line was built only from the dataframes after a fetch. A successful GraphQL answer and a failed request were not given a connectivity word, and the footer never read the Octopus Live result.

**Resolution:** **2.9.388** — the live line leads with Connectivity (OK / REST only / stale / failed) from the last real API attempt. The footer shows the same state as Octopus. Meter-slot age stays on the line as “latest … ago”.

### BUG-20260922-08 — Main window sized itself under the taskbar

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 11:07 (Europe/London) |
| **Status** | fixed |
| **Area** | Main window |
| **Version found** | 2.9.386 |
| **Version fixed** | 2.9.387 |

**Symptom:** A couple of seconds after launch the dashboard grew to the full monitor and the bottom of the window (status line) sat underneath the taskbar. The panel covered that strip, so the bottom of the app could not be used.

**Cause:** Startup called `setGeometry(availableGeometry())` and then `showMaximized()`. On this KDE Wayland desktop Qt reports the available screen as the full monitor — a floating panel does not reserve that space — so maximise placed the window in the strip the taskbar occupies.

**Resolution:** **2.9.387** — the window is fitted to the usable screen. Plasma panels are asked for their edge and thickness, and that strip is kept clear. Maximise is turned into the same fit, so the bottom edge stays above the taskbar.

### BUG-20260922-07 — Blocking OK/Cancel box can hide behind the main window

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 11:04 (Europe/London) |
| **Status** | fixed |
| **Area** | Dialogs / message boxes |
| **Version found** | 2.9.386 |
| **Version fixed** | 2.9.387 |

**Symptom:** A box that needed OK or Cancel could fall behind the main window. The rest of the dashboard would not take clicks until that box was answered, so the app looked frozen.

**Cause:** Modal dialogs block the other windows but were not kept above them, so the window manager could bury the box.

**Resolution:** **2.9.387** — every dialog that blocks the app is pinned to the top when it opens, and raised again if another window tries to cover it. Boxes that do not block the app can still go behind.

### BUG-20260922-06 — Connectivity Test line stuck on “Testing…”

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 11:03 (Europe/London) |
| **Status** | fixed |
| **Area** | Connectivity login panels (`dialogs/component_login.py`) |
| **Version found** | 2.9.385 |
| **Version fixed** | 2.9.386 |

**Symptom:** EMQX (and the other login popups) showed “Testing the EMQX broker with these fields…” under the buttons and never replaced it with the result. The result was a message box on Setup & Info. Closing the popup forgot the test. There was no place that said the last successful test was stale.

**Cause:** The popup only wrote a “testing” note. The test finished on the Setup tab and did not write back, and nothing stored the time of the last pass.

**Resolution:** **2.9.386** — each login panel keeps a connectivity line in the bottom-right. A fresh pass is green, a failure is red, and a pass older than one hour is amber with “Connectivity - last OK (Stale >1hr since last test)”. The time is stored in settings, so it is still there after the window is closed.

### BUG-20260922-05 — Agile Year end-of-chart spike ≠ table

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 10:45 (Europe/London) |
| **Status** | fixed |
| **Area** | Agile Year (`tabs/agile_year.py`) |
| **Version found** | 2.9.384 |
| **Version fixed** | 2.9.385 |

**Symptom:** The right-hand end of the year chart showed a sharp price spike. The daily high / low / average in the table for the newest days did not match that spike.

**Cause:** Two software issues, not a real Octopus day: (1) each redraw added a new matplotlib twin axis for “hours below 0p” without removing the old one, so leftover series stacked; (2) a 1–2 slot “day” at the end (open-ended standing unit rate or a timezone spill of the last half-hour) was aggregated as a full day, so its high/low/average was just those leftover slots.

**Resolution:** Remove twin axes before redraw. Ignore slots longer than two hours. Omit days with fewer than 40 half-hour slots from chart, table, and `agile_year_daily`. Daily stats are stored so the view can reload without that phantom point coming back.

### BUG-20260922-04 — Forecast charts wasted vertical space

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 10:35 (Europe/London) |
| **Status** | fixed |
| **Area** | Forecasts tab (Agile + solar charts) |
| **Version found** | 2.9.383 |
| **Version fixed** | 2.9.384 |

**Symptom:** The Agile price and solar panes looked squashed, with obvious empty bands above the top chart, between the two panes, and under the bottom one — the tab had the height, the charts were not using it.

**Cause:** Three separate margin costs stacked up. The per-day kWh totals drawn inside the solar pane were "made room for" by pulling the whole figure top down to 0.82, which only created dead space (the text is anchored to the axes, so it moved down too). The bottom band reserved up to 28% of the canvas for day labels, `hspace` gave the inter-pane gap 30% of a pane height, and the first build still used `tight_layout(pad=3.0)`.

**Resolution:** Margins are now computed from the real canvas height and shared between first build and redraw: top sized to the pane title (~24 px), bottom to the day-label band (capped at 18%), `hspace` 0.18. Text drawn inside the axes (day labels, per-day kWh totals) gets y-axis headroom instead of figure margin. The Forecast Summary panes start shorter (72 px) and the splitter favours the charts 8:1. Plot area goes from roughly 64% to about 80% of the canvas. File: `tabs/forecasts.py`.

### BUG-20260922-03 — Growatt Physical panel crowded, values clipped

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 10:20 (Europe/London) |
| **Status** | fixed |
| **Area** | Growatt Live Status (Physical — inverter & battery panel) |
| **Version found** | 2.9.383 |
| **Version fixed** | 2.9.384 |

**Symptom:** The bottom panel of Growatt Live Status was poorly arranged: three unbalanced columns, long field names running up against the value beside them, and one very tall live column.

**Cause:** Titles and values shared a free-width grid with no fixed label column, so a long title pushed into its neighbour's value. Grid items were also added with alignment flags, which shrinks a widget to its size hint — wrapping values were laid out at their minimum width and then clipped by a one-line row.

**Resolution:** Four columns (Dashboard model + Today | Battery equipage | Grid & PV live | Pack & status live) with a fixed 132 px wrapping title column, values that expand into the rest of the column, vertical dividers, and shorter titles with the full detail kept in tooltips. Alignment now lives on the labels, and wrapping labels declare height-for-width so rows grow instead of clipping. File: `tabs/growatt.py`.

### BUG-20260922-02 — Growatt API popup too narrow; no connection test

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 00:26 (Europe/London) |
| **Status** | fixed |
| **Area** | Connectivity Status (Growatt API login popup) |
| **Version found** | 2.9.382 |
| **Version fixed** | 2.9.383 |

**Symptom:** Clicking Growatt API opens a short/narrow credential popup. Username, password, API key, and serial fields feel cramped. Only **Save credentials** is offered — no way to test the cloud login from that dialog.

**Cause:** `_ConnectivityDetailDialog` used a ~680 px minimum when a login panel was present, and `_CloudLogin` used the default 200 px line fields with Save only (cloud Test lived on Growatt Live Status).

**Resolution:** Login popups open at 1200 px wide; cloud Username / Password / API key / Serial expand with the dialog. **Test connection** on the Growatt API popup (and Setup & Info) always probes Growatt cloud, not Grott MQTT. Result text stays on the popup status line.

### BUG-20260922-01 — Architecture diagram boxes clip subtitle text

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-22 00:08 (Europe/London) |
| **Status** | fixed |
| **Area** | Connectivity Status (architecture diagram) |
| **Version found** | 2.9.380 |
| **Version fixed** | 2.9.381 |

**Symptom:** On Energy Data Architecture, box subtitles (and ALARM/WARN lines) sit hard against the bottom edge; some secondary text looks cut off.

**Cause:** Blueprint cards in `_ARCH_SPEC` were only 40 px tall. Title + optional alarm line + subtitle need more height after scale-to-widget.

**Resolution:** Raised standard cards to 52 px (dashboard 118, inverter 190), gave battery packs a bit more height, and left more padding under titles for wrapped subtitle text. File: `tabs/connectivity.py`.

### BUG-20260921-09 — Sparse Grott heartbeats re-ambered registers a full frame had just published

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-21 21:43 (Europe/London) |
| **Status** | fixed |
| **Area** | Growatt Live / Connectivity (Grott fill-missing) |
| **Version found** | 2.9.378 |
| **Version fixed** | 2.9.379 |

**Symptom:** Connectivity showed “Grott missing N register(s) — patched from Growatt cloud (amber)” even while Grott MQTT was connected and Hybrid was selected.

**Cause:** Live MQTT on `energy/growatt` alternates full hybrid status frames (~28 keys: charge/discharge, load, grid, PV strings, today totals) with 5-key heartbeats (`soc`, `pvgridvoltage`, `pvfrequentie`, serials). `_record_grott_present` replaced the present-set with only the latest frame’s keys, so after each heartbeat every other register looked missing and fill-from-API re-ambered them. Gap-fill also keyed off the sparse frame alone, so heartbeats kept requesting cloud patches.

**Resolution:** Present-set is a union of recently published Grott keys, expired after the Grott fresh window. Amber sync and gap-fill use that set plus the display cache. The degradation banner lists the field names still cloud-filled.

---

### BUG-20260921-08 — Setup SQL created the tables but never granted access

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-21 21:17 (Europe/London) |
| **Status** | fixed |
| **Area** | Setup & Info, PostgreSQL logging |
| **Version found** | 2.9.377 |
| **Version fixed** | 2.9.378 |

**Symptom:** Setup still showed “Tables not readable (0/11)” with PostgreSQL connected, after the create script was available to run by hand.

**Cause:** All eleven logger tables already existed in `mqtt_user`, owned by `postgres`. The `emqx` login had no privilege on any of them (`has_table_privilege` false for SELECT and INSERT on all eleven) and no `CREATE` on `public`. Creating a table does not grant access to it, and the script only contained `CREATE` statements, so running it could never clear the warning.

**Resolution:** The PostgreSQL script now ends with `GRANT SELECT, INSERT, UPDATE, DELETE` on each logger table plus `USAGE, SELECT` on the `SERIAL` id sequences, naming the login from the Setup user field. UPDATE is needed by the upserts, DELETE by ring-buffer retention. The “not readable” tooltip now says a create does not imply access.

---

### BUG-20260921-07 — Tabs and Close frozen by Battery Analysis error box

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-21 21:03 (Europe/London) |
| **Status** | fixed |
| **Area** | Battery Analysis, main window |
| **Version found** | 2.9.376 |
| **Version fixed** | 2.9.377 |

**Symptom:** Page tabs would not change and the dashboard would not close. The window still painted.

**Cause:** Startup history load calls `QMessageBox.critical` when PostgreSQL has no usable `growatt_readings`. That box is modal to the main window, so tabs and Close are ignored until OK. On a wide desktop the box can sit off the screen you are looking at.

**Resolution:** The fetch failure is written to the status line. It no longer opens a dialog.

---

### BUG-20260921-06 — EMQX login tried to create logger tables and the server looked down

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-21 20:48 (Europe/London) |
| **Status** | fixed |
| **Area** | PostgreSQL logging, Setup & Info |
| **Version found** | 2.9.375 |
| **Version fixed** | 2.9.376 |

**Symptom:** Console repeated `permission denied for schema public` on `CREATE TABLE growatt_readings`, then “PostgreSQL unreachable”. Setup showed “Tables not readable (0/11)” while “Database connected” stayed green. Battery Analysis said there was no local history.

**Cause:** The app was logged in as `emqx` on database `mqtt_user` and issued `CREATE TABLE` itself. That role is not allowed to create objects in `public`. A refused create was treated as the server being down. “Not readable (0/11)” means none of the eleven logger tables can be read and written by this login (a table can exist and still be refused, as with `optimiser_shadow_plans`).

**Resolution:** The Setup CREATE script, run by hand as the database owner, is what creates every logger table. The dashboard and the collector no longer issue `CREATE TABLE` on PostgreSQL.

---

### BUG-20260921-05 — Ingest looked empty because the DB login cannot read logger tables

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-21 20:32 (Europe/London) |
| **Status** | fixed |
| **Area** | Octopus Live, footer ingest, Setup & Info |
| **Version found** | 2.9.373 |
| **Version fixed** | 2.9.374 |

**Symptom:** Octopus Live labelled “No Growatt PV in this window” on a day with real import/export; footer ingest sat at zero while PostgreSQL showed connected.

**Cause:** Setup used the MQTT broker PostgreSQL login on database `mqtt_user`. Logger tables exist and are owned by `postgres`; that login has SELECT only on EMQX’s `mqtt_users` / `mqtt_acl`. Ingest counts and the PV overlay treated permission-denied queries as “no rows”.

**Resolution:** Setup “Tables connected” now requires SELECT+INSERT on logger tables. Footer shows **INGEST no table access** with the real error. Octopus Live names a denied `growatt_readings` login instead of a missing-PV caption.

---

## Fixed

### BUG-20260921-04 — DB status said “not found” for a password failure

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-21 17:47 (Europe/London) |
| **Status** | fixed |
| **Area** | Setup & Info (`tabs/parameters.py`, `db/connect_probe.py`) |
| **Version found** | 2.9.369 |
| **Version fixed** | 2.9.370 |

**Symptom:** PostgreSQL showed “Database not found / Database not OK” when the server had answered `password authentication failed for user "emqx"`.

**Cause:** One “found” check and one “OK” check reused the same connect error. Auth failure was labelled as a missing database.

**Resolution:** Three explicit lines: `{engine} DB seen`, `Database connected`, `Tables connected (n/n)`. Hover for the real reason. Password failures mark DB seen (server answered) and not connected.

### BUG-20260921-03 — App sluggish when a database is disconnected

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-21 17:24 (Europe/London) |
| **Status** | fixed |
| **Area** | Database logging (`db/logger.py`, probes, Connectivity) |
| **Version found** | 2.9.368 |
| **Version fixed** | 2.9.369 |

**Symptom:** With PostgreSQL (or MySQL) ticked but unreachable, the whole dashboard feels stuck — clicks and tab changes lag for seconds at a time.

**Cause:** Connects to MySQL/Postgres used the OS TCP wait (often 1–2 minutes) with no timeout. Live PV-string writes and connectivity history called `_ensure_pg` on the GUI thread; the writer retried the same hang on every queued sample.

**Resolution:** 3-second connect timeout; exponential backoff (5–60 s) after failure; connectivity events and PV-string lots go through the writer thread. Test Connection still probes immediately (with the short timeout).

### BUG-20260921-02 — DB connected/disabled status centred on the right

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-21 17:06 (Europe/London) |
| **Status** | fixed |
| **Area** | Setup & Info (`tabs/parameters.py`) |
| **Version found** | 2.9.367 |
| **Version fixed** | 2.9.368 |

**Symptom:** SQLite/MySQL “Disabled” and PostgreSQL “Database not found / Database not OK” sat in the middle of the leftover row, looking right-justified against the window edge.

**Cause:** The backend HBox added stretch, then the status panel, then stretch (`AlignHCenter`), so the 300 px status block floated in leftover space.

**Resolution:** Status is left-aligned next to the fields (`Maximum` width). Remaining width is the create-all SQL pane.

**Follow-up:** Alignment still wrong in practice — see open **BUG-20260923-06** (status floats mid-row; SQL panes not one shared column).

### BUG-20260921-01 — Setup Database created only four tables

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-21 17:06 (Europe/London) |
| **Status** | fixed |
| **Area** | Database setup (`db/schema.py`, `db/full_schema.py`) |
| **Version found** | 2.9.367 |
| **Version fixed** | 2.9.368 |

**Symptom:** Setup Database on SQLite/MySQL/PostgreSQL did not create forecasts, Agile prices, MIX chart, shadow trial, connectivity history, or PV string charge. There was no CREATE script to inspect or copy.

**Cause:** `schema.py` only ran the original four CREATE statements. The rest existed only inside DataLogger `_ensure_*`. SQLite `_ensure` also skipped `tasmota_devices`.

**Resolution:** One `full_schema` statement list drives Setup Database, live `_ensure_*`, and the Setup & Info SQL viewer. `postgres_reset_schema.sql` now drops/recreates the same set (including current `pv_string_charge` columns).


### BUG-20260917-05 — Launch logs EGL DRM + GPUInfo

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-17 15:42 (Europe/London) |
| **Status** | fixed |
| **Area** | Launch (`run-dashboard.sh`, `qt_env.py`) |
| **Version found** | 2.9.366 |
| **Version fixed** | 2.9.367 |

**Symptom:** `./run-dashboard.sh` printed `EGL: Failed to query DRM render node file path. Fallback to /dev/dri/renderD128.` then `GPUInfo not initialized on GpuInfoUpdate`.

**Cause:** Qt still created an EGL context on Linux (xcb GL integration) even with Chromium `--disable-gpu`. Mesa then failed to name a DRM render node; Chromium logged GPUInfo. Same family as BUG-20260915-05, but the window could still appear after the noise.

**Resolution:** Software OpenGL attribute before `QApplication`, `QT_XCB_GL_INTEGRATION=none`, quieter EGL/Chromium logs. Hardware GPU remains `POWERMODEL_WEBENGINE_GPU=1`.

### BUG-20260917-04 — Battery Analysis capacity ignores Growatt Live Status

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-17 10:54 (Europe/London) |
| **Status** | fixed |
| **Area** | Battery Analysis (`tabs/battery_analysis.py`) |
| **Version found** | 2.9.364 |
| **Version fixed** | 2.9.365 |

**Symptom:** Battery Capacity on Battery Analysis showed 13 kWh from Setup, not the pack size Growatt Live Status already knows. Changing it here was not saved.

**Cause:** The field was a tiny line-edit filled only from Setup (`app_params.battery_capacity_kwh`). There was no Save on this tab, and Live Status equipage / rated capacity was never read.

**Resolution:** Capacity is a proper spin. Default is Growatt Live Status (detected modules × 6.5 kWh, or Grott rated capacity). The user can change it; **Save** stores it (and updates Setup). Live updates refresh the default until Save.

### BUG-20260917-03 — AC charge stop control unusable

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-17 10:54 (Europe/London) |
| **Status** | fixed |
| **Area** | Battery Analysis (`tabs/battery_analysis.py`) |
| **Version found** | 2.9.364 |
| **Version fixed** | 2.9.365 |

**Symptom:** AC charge stop % on Battery Analysis was a ~48 px box that clipped the value (looked empty / like “1”), so the stop SOC could not be read or set. No Save for the local target.

**Cause:** `setFixedWidth(48)` left no room for a three-digit value plus the stepper. Cloud reads used only `get_api()` (missed cached session) and a strict JSON shape, so parse often returned nothing. Writes did not read back.

**Resolution:** Full electric-blue spin 0–100%. **Save** keeps the local target. **Set on inverter** uses cached cloud auth, a more tolerant settings parse, and a 2.5 s read-back.

### BUG-20260917-02 — PV String Charge live kW missing from charts

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-17 10:41 (Europe/London) |
| **Status** | fixed |
| **Area** | PV String Charge (`tabs/pv_string_charge.py`) |
| **Version found** | 2.9.362 |
| **Version fixed** | 2.9.363 |

**Symptom:** Cards showed String 1 **0.31 kW** and String 2 **0.13 kW**, but neither appeared on the charts. Top pane was last-6-hours (forecast + a tall charge line); bottom was 00:00–24:00. Samples had only started ~10:38.

**Cause:** Instantaneous series were 2-minute *points* on a multi-hour axis, so a few minutes of 0.31 kW was a speck (and shorter than the 2.99 kW charge line). The two panes also used different x ranges, so “now” did not line up.

**Resolution:** Both panes use London midnight → +24 h, with a solid **Now** line. Lots are drawn as 2-minute steps and the live card kW is marked and labelled on that line so 0.31 / 0.13 stay readable. Charts are taller.

---

### BUG-20260917-01 — PV String Charge left axis ~40 kW at dawn

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-17 09:20 (Europe/London) |
| **Status** | fixed |
| **Area** | PV String Charge / Grott (`tabs/pv_string_charge.py`, `fetch/grott_mqtt.py`, `ui/cards.py`) |
| **Version found** | 2.9.359 |
| **Version fixed** | 2.9.360 |

**Symptom:** Chart left Y axis autoscaled to ~40 kW while live cards showed ~0.24 / 0.13 kW. String 2 “today” was ~11 kWh from 08:02 — implausible for this array. A sharp spike around 08:00 sat near 40.

**Cause:** Grott converts total PV (`ppv`) watts→kW but left `pPv1` / `pPv2` in watts. The tab then used `abs(n) > 50` before dividing: 240 W became 0.24 kW, but dawn 10–40 W stayed as 10–40 kW. Autoscale followed that leftover; integrating 40 kW for ~15 minutes produced the bogus today kWh.

**Resolution:** Grott and cloud mix_status now store string power in kW (same as `ppv`). The tab converts by comparing strings to total PV and a residential ceiling (not `> 50`). Stored lots are sanitised on load. Physical string readout still shows watts.

---

### BUG-20260916-02 — PV String Charge chart looked swapped vs cards

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-16 11:35 (Europe/London) |
| **Status** | fixed |
| **Area** | PV String Charge (`tabs/pv_string_charge.py`) |
| **Version found** | 2.9.356 |
| **Version fixed** | 2.9.357 |

**Symptom:** Cards said String 1 was charging more than String 2, but the history chart looked the other way around. Chart was session-only (lost on restart), stacked (so the second series sat on top), and had no 6-hour memory, cumulative energy, or solar forecast overlay.

**Cause:** The split maths and cards were correct (blue String 1, green String 2). Matplotlib `stackplot` drew String 1 from zero and stacked String 2 on top, so green sat higher on the plot even when it was the smaller share. History lived only in a RAM deque.

**Resolution:** Overlay each string from zero (50% fill, 1 px solid line). Persist samples in `pv_string_charge` and chart a rolling 6-hour window. Add cumulative estimated charge kWh (right axis) and the solar forecast (peach) for the same window.

---

### BUG-20260916-01 — Grott feed “lost” while MQTT still connected

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-16 10:27 (Europe/London) |
| **Status** | fixed |
| **Area** | Grott MQTT (`fetch/grott_mqtt.py`, alarms) |
| **Version found** | 2.9.355 |
| **Version fixed** | 2.9.356 |

**Symptom:** System-tray “Grott feed lost — no telemetry for 162s / 462s”. Detail said MQTT was connected but no inverter payload (fresh limit 120s). Looked like the feed kept dropping.

**Cause:** Two separate things. (1) The Shine datalogger reconnects to Grott (often around the hour) and then sends no live 0x0104/0x0136 for ~11 minutes while it handshakes with Growatt’s servers — Grott therefore publishes nothing; MQTT is fine. The 162s then 462s toasts were one gap, re-notified on the 5 min backoff. (2) Grott still MQTT’d `buffered: yes` midnight dumps (ini `sendbuf = False` stored as the string `"False"`, so the skip never fired). Those could merge old SOC/power into the live snapshot.

**Resolution:** Ignore historical/buffered Grott JSON in the dashboard. Alarm copy explains the Shine handshake quiet (not a broker drop). Log stale/recover on Connectivity history. Help/Grott Setup text updated. Grott container `sendbuf` parse patched on disk (honours `sendbuf = False` after the next Grott restart — not restarted now, to avoid another 11 min Shine handshake).

---

## Fixed

### BUG-20260915-12 — Intermittent Grott MQTT loss of communications

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-15 14:37 (Europe/London) |
| **Status** | fixed |
| **Area** | Grott MQTT (`fetch/grott_mqtt.py`, Growatt Live refresh) |
| **Version found** | 2.9.344 |
| **Version fixed** | 2.9.345 |

**Symptom:** Grott / GROTT MQTT link drops intermittently (Connectivity shows disconnected or stale; tray grott_lost may fire).

**Cause:** Auto / Refresh called full `apply_grott_settings()` (MQTT stop+start) whenever the snapshot was *stale*, even if the broker socket was still connected. Quiet Shine/Grott publish intervals (1–5 min) looked like “loss” and the reconnect flap made it worse. Disconnects also had weak logging/recovery.

**Resolution:** Soft re-subscribe when connected+stale; full reconnect only when the socket is down. MQTT client: reconnect backoff, watchdog reconnect, disconnect/reconnect counters, events into `connectivity_events` for Show history. Connectivity Grott row shows disconnect/reconnect counts.

---

## Fixed

### BUG-20260915-11 — Connectivity Status crash on launch (missing context menu handler)

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-15 14:36 (Europe/London) |
| **Status** | fixed |
| **Area** | Connectivity Status tab init |
| **Version found** | 2.9.343 |
| **Version fixed** | 2.9.344 |

**Symptom:** `./run-dashboard.sh` failed with `AttributeError: 'ConnectivityStatusTab' object has no attribute '_on_state_context_menu'`.

**Cause:** Highlight refactor accidentally merged the State context-menu body into `_on_row_selection_changed` and dropped the `_on_state_context_menu` method while `build_ui` still connected to it.

**Resolution:** Restored `_on_state_context_menu` as its own method; row-selection highlight stays separate.

---

### BUG-20260915-10 — Wonderwatt detail dialog showed raw HTML tags

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-15 13:24 (Europe/London) |
| **Status** | fixed |
| **Area** | Connectivity Status — Wonderwatt.com click dialog |
| **Version found** | 2.9.336 |
| **Version fixed** | 2.9.337 |

**Symptom:** Clicking Wonderwatt.com showed literal `<b>…</b>` tags instead of bold text. Share link was display-only (wattid only); no way to paste/edit the Advanced share URL in that window.

**Cause:** `_ConnectivityDetailDialog` used `QTextEdit.setPlainText`, so HTML in detail bodies was not rendered. Wonderwatt had no dedicated editor dialog (unlike Databases ring buffers).

**Resolution:** Detail dialogs render body as HTML. Wonderwatt opens `_WonderwattShareDialog` with an editable share-URL field plus Save / Test link, synced to Setup & Info and Pot. Issues. File: `tabs/connectivity.py`.

---

### BUG-20260915-09 — PVOutput upload thread TypeError on _log.info/warn

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-15 13:20 (Europe/London) |
| **Status** | fixed |
| **Area** | PVOutput upload (`main_window._maybe_upload_community_outputs`) |
| **Version found** | 2.9.334 |
| **Version fixed** | 2.9.335 |

**Symptom:** After `./run-dashboard.sh`, thread traceback `LogManager.info() missing 1 required positional argument: 'msg'` (and the same for `warn`), then a segfault.

**Cause:** `_log.info` / `_log.warn` require `(source, msg)`. The new PVOutput upload worker passed a single f-string. The exception handler made the same mistake, so recovery also failed.

**Resolution:** Call `_log.info("PVOutput", …)` / `_log.warn("PVOutput", …)`. Swept the same one-arg pattern in Refresh/Help logging and a few tab modules.

---

### BUG-20260915-08 — Modbus flow direction wrong; lines passed under boxes

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-15 12:15 (Europe/London) |
| **Status** | fixed |
| **Area** | Connectivity Status architecture diagram |
| **Version found** | 2.9.324 |
| **Version fixed** | 2.9.325 |

**Symptom:** Diagram sent Modbus straight to the dashboard instead of feeding EMQX, and some connection curves passed underneath boxes (Tasmota→EMQX clipped the Modbus box; the cloud→dashboard line grazed the EMQX box).

**Cause:** Modbus box sat in the Growatt column with a direct dashboard link; curve anchors were not checked against box footprints after the three-pipe rework.

**Resolution:** Data flow is now Modbus → EMQX → dashboard (one-way into the broker), with the Modbus box directly under EMQX so the feed is a short vertical line. Re-anchored Tasmota→EMQX (bottom-left of broker), Growatt API→dashboard (higher attach), and Octopus/forecast attach points so no route crosses a box. EMQX health/volumes now include bridged Modbus. File: `tabs/connectivity.py`.

---

### BUG-20260915-07 — Diagram still showed WiFi Direct + LAN Direct boxes

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-15 11:25 (Europe/London) |
| **Status** | fixed |
| **Area** | Connectivity Status architecture diagram |
| **Version found** | 2.9.323 |
| **Version fixed** | 2.9.324 |

**Symptom:** After the peer-wiring fix, the diagram still had separate “Growatt WiFi Direct” and “Growatt LAN Direct” boxes. The human wants only three Growatt connection methods: Growatt API, GROTT, Modbus.

**Cause:** WiFi Direct (stick web UI) and LAN Direct (a rename of Modbus) were kept as diagram nodes instead of collapsing to the three real pipes.

**Resolution:** Removed WiFi Direct from the architecture paint/layout. Renamed the Modbus box to **Modbus** (TCP/RTU) aligned with API and GROTT. Pipeline probe no longer treats WiFi Direct as a hop; Modbus hop id is `modbus`. Updated `architecture.md`.

---

### BUG-20260915-06 — Connectivity diagram chained Wi‑Fi→API and LAN→Grott

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-15 ~10:20 (Europe/London) |
| **Status** | fixed |
| **Area** | Connectivity Status architecture diagram |
| **Version found** | ≤2.9.322 |
| **Version fixed** | 2.9.323 |

**Symptom:** System diagram showed Growatt WiFi Direct feeding the Growatt cloud API, and LAN Direct (Modbus) feeding Grott — as if those were parent→child paths.

**Cause:** `_ConnectivityFlowDiagram` data/control edges and layout placed WiFi/LAN between the inverter and API/Grott and wired them as the upstream of those boxes. Docs had been corrected earlier; the **in-app paint** had not.

**Resolution:** Rewired peers: inverter→API, inverter→Grott→EMQX, WiFi Direct as local web-UI stub, LAN/Modbus as separate path to the dashboard. Updated click-detail text and pipeline-probe “inv_grott” so Modbus/WiFi are not treated as Grott’s parent. Files: `tabs/connectivity.py`, `connectivity/pipeline_probe.py`.

---

### BUG-20260915-05 — Startup SEGV “GPUInfo not initialized on GpuInfoUpdate”

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-15 ~10:32 (Europe/London) |
| **Status** | fixed |
| **Area** | Qt WebEngine / launch (`run-dashboard.sh`, `qt_env.py`) |
| **Version found** | ≤2.9.321 |
| **Version fixed** | 2.9.322 |

**Symptom:** `./run-dashboard.sh` printed `GPUInfo not initialized on GpuInfoUpdate` then segmentation fault.

**Cause:** Linux Mesa + Qt WebEngine Chromium GPU path; Chromium flags were applied too late / not strong enough before Qt loaded.

**Resolution:** Default software / no-GPU Chromium flags applied in `qt_env.py` at import time and again from `run-dashboard.sh`. Opt-in hardware GPU: `POWERMODEL_WEBENGINE_GPU=1`.

---

### BUG-20260915-04 — Tasmota pin-chart SyntaxError on launch

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-15 ~10:14 (Europe/London) |
| **Status** | fixed |
| **Area** | Tasmota tab (`tabs/tasmota.py`) |
| **Version found** | 2.9.320 (broken edit) |
| **Version fixed** | 2.9.320 (hotfix same day) |

**Symptom:** Dashboard failed to start with `SyntaxError` at `_set_hist_y_cap` (`blockSignals(False)        try:` jammed on one line).

**Cause:** Bad merge/edit concatenated two statements.

**Resolution:** Split into separate lines; verified with `py_compile`.

---

### BUG-20260915-03 — “Pin chart 2 to max 500 W” not user-settable

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-15 ~09:50 (Europe/London) |
| **Status** | fixed |
| **Area** | Tasmota Power History |
| **Version found** | ≤2.9.319 |
| **Version fixed** | 2.9.320 |

**Symptom:** Pin locked Y-axis hard to 500 W; user could not choose another ceiling when a spike (~3.5 kW) flattened quieter traces.

**Cause:** Pin checkbox forced 500 and disabled the flexible max control.

**Resolution:** “Pin chart 2 max” + editable watts spin (default 500), persisted; drag/presets retune the pin. Help text updated.

---

### BUG-20260915-02 — Roof Layout imagery chip covered map attribution

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-15 ~08:35 (Europe/London) |
| **Status** | fixed |
| **Area** | Roof Layout satellite map |
| **Version found** | ≤2.9.317 |
| **Version fixed** | 2.9.318 |

**Symptom:** “Imagery: Esri Wayback…” overlay sat on the bottom-right and obscured Leaflet/Esri attribution.

**Cause:** `.meta` CSS `right:8px; bottom:8px` over the attribution strip.

**Resolution:** Centre the chip (`left:50%; transform; bottom:28px`) so credits stay visible.

---

### BUG-20260915-01 — Tasmota matplotlib tight_layout UserWarning

| Field | Value |
|-------|--------|
| **Opened** | 2026-09-15 ~08:11 (Europe/London) |
| **Status** | fixed |
| **Area** | Tasmota charts |
| **Version found** | ≤2.9.315 |
| **Version fixed** | 2.9.316 |

**Symptom:** Console spam: `Tight layout not applied. The bottom and top margins cannot be made large enough…` attributed near `processEvents`.

**Cause:** `fig.tight_layout()` on a short chart pane; warning often surfaced on a later redraw.

**Resolution:** Replaced with fixed `subplots_adjust` + mid-split positions (same pattern as other tabs).
