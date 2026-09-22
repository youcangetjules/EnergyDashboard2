# worklog.md — PowerModel / Energy Dashboard

Part of the **basic instructions for the development environment** (see `AGENTS.md`).

Plain-English **development diary**. Newest day first.

Agents: after meaningful development work in a session, **append what you did that day** here in language a non-expert can follow — what changed for the user or the system, and why it mattered. Skip trivia (typo-only) unless it fixed a user-facing bug.

Do not replace the in-app About changelog; that stays the versioned product history. This file is the human/agent work narrative.

---

## 2026-09-23

- The Broker URL test was showing a raw “no route to host” for the logging database without saying where that address comes from. It now says the host is the PostgreSQL Host box on Setup & Info (saved as db/pg_host), copied into POWERMON_PG_HOST for the collector, and it prints the value in the box and the value the collector is actually using. That address is not written into the program.

## 2026-09-22

- The GitHub front page now opens with the same introduction as the About popup in the app (Growatt and Octopus, and how to get in touch).
- On Octopus Live, Save has moved off the account row and now sits to the right of the Hours radios and the Power/Cost view, with a vertical line between those two controls so they do not read as one group. Test is immediately to the right of Save. It asks Octopus whether the API key and account are accepted, and it leaves the charts as they are.
- Commit messages on GitHub now include a short line for each change in that patch, in everyday language, so the history says what changed without opening the code.
- Octopus Live can now show money as well as power. A Power / Cost switch sits in the live monitor panel. Cost is the energy in each slot times the Agile spot price (import and export tariffs, VAT included). For earlier days that Octopus has already metered, the chart uses that half-hour meter — what Octopus will actually bill from — instead of the live stream. The gap between those settled days and the live stream is used as a scale on today’s running estimate, and the summary shows the factor and the days it came from. Today stays labelled as an estimate. The standing charge is not in the figure.
- From the next change onward, each version patch is its own git commit and is pushed to GitHub (`youcangetjules/EnergyDashboard2`, branch `main`). GitHub was still on 2.9.245 while this machine was on 2.9.399, and those in-between versions were never saved one at a time, so they go up together as one catch-up. After that, a patch is committed and pushed before the next one starts.
- Run Advisor now turns pale green when the run finishes cleanly, the same green a tab uses just after it refreshes. If the run fails, that button turns black so you can see the last attempt did not work.
- Battery Expansion Simulator used to leave blank charts when there was nothing to simulate, with only a short note in the status bar. It now writes on the charts and in Simulation Results that it needs at least a day of half-hour history, and how many slots it actually found.
- Starting the dashboard was still printing two graphics lines (it could not name a DRM render node, then Chromium said GPU info was not ready). Those lines were caused by the old “turn the GPU off” flags, not by a failed start. The flags are gone. The window still draws with software OpenGL, which stays quiet. Hardware graphics is still the opt-in `POWERMODEL_WEBENGINE_GPU=1`.
- Maximising was leaving a gap under the window. The snap had been cutting the title-bar height off the screen, so the window came up short. Maximise now keeps the full height of that screen, above the taskbar, and still will not grow wider than the monitor.
- Maximising the dashboard was still letting it grow wider than the screen it sits on, because the window manager’s maximise ignored the size cap and followed a layout that wanted to be wider than the monitor. Maximise now snaps the window to that screen’s usable resolution and will not go past it.
- Physical Plant Tools now holds Battery Analysis, PV String Charge, and Potential Issues (the page that was called Pot. Issues). Starting the app still opens Dashboards.
- The group that was labelled Energy Usage is now Dashboards, and it is the first group on the left. Starting the app always lands there (Growatt Live Status), instead of reopening whichever group you had open last time.
- The main window’s largest size is now the screen it is sitting on. It was allowed to grow past that monitor when the layout asked for more room than the screen had. Dragging it to another monitor updates the limit, and it still stops above the taskbar.
- The dashboard was opening a separate MQTT login for Grott and another for the Tasmota plugs, and Grott minted a new name every time it connected, so the broker filled up with sessions and two dashboard windows kicked each other off. There is now one connection, named energy_dashboard, shared by both. A second window will not open another one. Close any older dashboard before starting this version so the old sessions can drop.
- On Growatt Live, Manual packs (Auto, Apply, and Probe packs) now sits on one line instead of Probe packs dropping underneath.
- The Tasmota Power History chart title no longer explains a gap at the left of the window (when the database samples start, or a reminder to check the collector). The title is just the time window, where the line came from, and the watts cap if you pinned one.
- MQTT looked like it was dropping every few seconds on the EMQX subscriptions page. Two copies of the dashboard were signed into the broker at once (one left running since 02:47, another started at 11:28). They share one Tasmota client name, so the broker keeps kicking one off and that one signs back in and kicks the other. Extra Grott sessions from each launch were also left sitting there. The plugs themselves were not reconnecting on that few-second rhythm.
- Octopus Live used to say how many readings came back and how old the newest meter slot was, without saying whether Octopus itself answered. That line now starts with Connectivity — green when the live GraphQL stream answered, amber if only the slower half-hour REST meter is filling in or the link has gone quiet, red if the last request failed. The same word is on the bottom strip next to the database. The meter’s age is still shown separately, because a six-minute-old 5-minute slot can be a healthy link.
- The dashboard was stretching to the full monitor a moment after launch, so the bottom of the window sat under the taskbar and that strip could not be clicked. It now stops above the panel. Maximise does the same, instead of covering the bar. Message boxes that need OK or Cancel stay on top of the app so they cannot hide behind the main window and leave everything else stuck.
- Test on a Connectivity login (EMQX, Grott, Growatt cloud, the inverter web page, Modbus, PVOutput, and each database) now leaves a line in the bottom-right of that panel. Green means the last test passed, red means it failed. If that pass is more than an hour old the line turns amber and reads “Connectivity - last OK (Stale >1hr since last test)”. Closing the window does not wipe it — the time is remembered, and an open panel flips to amber on its own after the hour.
- Agile Year now writes each day’s high / low / average into the database (`agile_year_daily`) as well as the half-hour slots. Opening the tab can show stored days immediately, then Fetch year refreshes from Octopus. The spike at the far right of the chart was not a real expensive day in the table — it was leftover overlay axes plus a 1–2 slot “ghost” day (a standing rate or timezone spill). Those sparse days are dropped, so the line matches the table. Four trend-line tick boxes (Monthly, YTD, Yearly, Since start) sit on the toolbar; the table has resizable columns plus % vs long-term trend and how many standard deviations each day sits from that line. On PostgreSQL, run the Setup CREATE script once so the new table exists (the app login still cannot create tables).
- The bottom panel of Growatt Live Status is now four columns instead of three lopsided ones: dashboard model plus today's energy, battery equipage (packs, chemistry, serials), grid & PV live readings, and pack & status live readings, with a faint divider between each. Field names sit in their own fixed-width column that wraps, so a long name can no longer run under the value beside it, and values that need two lines get two lines instead of being cut off. Names are shorter; the full explanation is still in the hover tooltip.
- Forecast charts now use the height they are given. Previously the app shrank the whole figure to make room for the per-day kWh totals written inside the solar chart, which just left empty bands above and below — the totals moved down with the chart anyway. Those labels now get breathing room inside the chart (a little extra headroom on the y-axis) and the figure keeps its full height, so the two panes take about 80% of the canvas instead of roughly 64%. The Forecast Summary boxes at the bottom start shorter and the divider favours the charts.
- Growatt API popup (and other Connectivity logins) open about 1200 px wide so Username, Password, API key, and Serial have room. **Test connection** on that popup (and on Setup & Info) checks Growatt cloud login and a live inverter read — result stays on the popup line, not a blocking box.
- Controls group has a new **Bug Tracker** tab that shows the same `bug_tracker.md` file agents keep at the project root (open bugs, then fixed). Reload refreshes from disk; the tab does not write the file.
- Connectivity architecture boxes were too short: ALARM/WARN and the second line of text sat on the bottom edge. Cards are a little taller now so that text fits.

## 2026-09-21

- Long-running dashboard PID 345239 died with a segmentation fault around 22:13. Core dump shows a background thread importing through Shiboken while the main window was painting — not the old WebEngine GPU startup crash. Fresh launch is fine. Worker→GUI callbacks now always queue onto the GUI thread (`Invoker`) so a plain Python thread cannot run UI code by accident.
- Grott “missing registers” amber was misleading overnight: the stick publishes full status frames and short heartbeats (SOC + grid volts/hertz). The heartbeat was wiping the app’s memory of which registers Grott had already sent, so those fields were patched from the Growatt cloud again. Recent Grott registers now stay “present” across heartbeats, and the Connectivity banner names any fields that are still cloud-filled.
- Checked the actual database: all eleven logger tables already existed in `mqtt_user`, owned by `postgres`, and the `emqx` login had no rights on any of them. Creating a table does not give access to it, so the create script alone could never fix “Tables not readable”. The PostgreSQL script now also grants that login read and write on those tables (and the id sequences), named from the User field. Run the whole thing yourself as the database owner.
- Battery Analysis was opening a blocking error box when it could not read battery history. That froze the tab bar and the Close button. The same words now stay on the status line, so the rest of the window keeps working.
- PostgreSQL tables are created by the SQL on Setup & Info, which you run yourself as the database owner. That script creates every logger table. The EMQX login is not allowed to create them, and the app no longer tries. “Tables not readable (0/11)” means that login can connect but cannot use the eleven logger tables.
- Clicking a box on the Connectivity diagram now shows that component’s login under the status text — the same usernames, passwords, and API keys as Setup & Info (or the Octopus tabs, for the Octopus box). Save and Test write back to those same fields. Boxes with nothing to sign in to (battery, forecast, AI, the dashboard itself) stay as they were. Wonderwatt already had its share link.
- Setup & Info database rows now show the prepared CREATE script for that engine on the right (every table the dashboard logs into), plus Copy SQL. Setup Database runs that same script, so SQLite/MySQL/PostgreSQL get the full set — not just the old four tables.
- Connected / Disabled / Database not found text sits immediately left of that SQL, left-aligned, instead of floating in the middle of the leftover space.
- If MySQL or PostgreSQL is ticked but the server is down, the app used to stall on long network waits (clicks felt stuck). It now gives up after a few seconds, waits before retrying, and keeps the rest of the dashboard moving. Logging resumes on its own when the database is back.
- Setup database status now says three separate things: whether that engine’s database was seen, whether we connected, and whether the logger tables are there. Hover the red line for the detailed reason (wrong password vs missing database vs host down).
- New Energy Forecasts tab <b>Agile Year</b>, next to Agile Spot Prices. It looks back a bit over a year and, for each London day, shows the highest, lowest and average Agile slot price, plus how many hours that day were below 0p (the times Octopus paid you to import, on import view). Fetch year talks to Octopus; it does not invent missing days.
- A two-line strip now sits across the bottom of the window (above Refresh / Help / Close). Line 1 is whether the logging database is connected and how much Growatt + Tasmota data arrived in the last 15 minutes, hour, and since London midnight. Line 2 is the whole PC’s CPU and RAM, including a rolling one-hour average. Hover for this-app CPU/RAM. The database poll runs in the background and gives up after a few seconds if the server is down.
- Live alarms (banner + tray) now also fire when the logging database is unreachable, when Growatt/Tasmota rows stop landing while those devices are still live, when Growatt says the inverter is offline, when Tasmota MQTT drops, or when a named plug/CT goes quiet. Battery/Grott alarms are unchanged.
- Octopus Live “No Growatt PV” and a footer ingest of 0 were not a quiet solar day: PostgreSQL was connected as the MQTT user, which is not allowed to read `growatt_readings`. Setup now says tables are not readable; ingest says no table access; the chart names that permission problem.

---

## 2026-09-17

- `./run-dashboard.sh` was printing two GPU lines (EGL couldn’t find a DRM render node, then Chromium “GPUInfo not initialized”). That is the same Linux graphics probe that used to crash the app; it now stays on software drawing and those messages should stay quiet. Use `POWERMODEL_WEBENGINE_GPU=1` only if you want the real GPU back.
- PV String Charge: the third (lifetime) chart under today’s kW and kWh panes is gone. Those two charts now use the extra height.
- Battery Analysis: the AC charge stop box was too narrow to show the number, so it looked broken. It is a proper spin now (0–100%). Battery capacity defaults from Growatt Live Status (you can still change it here). <b>Save</b> stores capacity, low-SOC threshold, and charge-stop % on this computer; <b>Set on inverter</b> is the write to the MIX and now checks the inverter read-back.
- Battery Analysis: next to Fetch Battery History there is a <b>Refresh every: … min</b> spin so the SOC/power charts can keep up without clicking. 0 is Off; the interval is remembered.
- Octopus Energy Data: under the daily import/export and £ charts there is now a weekly row — Monday to Sunday totals for power (kWh) and net cost (£), with a dashed trend so you can see whether each is drifting up or down week by week. A week that only has a few days in the selected range is shown paler and not multiplied up to seven days.
- PV String Charge left axis was stretching to ~40 kW at sunrise. That was not a 40 kW array — Grott reports each string in watts, and readings under 50 W (typical at dawn) were stored as if they were already kW. String 2’s “today” kWh was inflated the same way. String power is now converted like total PV, old lots are corrected when loaded, and the scale follows real kilowatts.

---

## 2026-09-16

- Roof Layout: **Use clearest image** scans the satellite/aerial sources at your house (Google, Esri live mosaic, dated Esri Wayback snapshots, Sentinel-2 years) and switches the map to the sharpest one — so panel edges are easier to trace. It remembers that choice.
- PV String Charge: each string card now shows **now** (live kW from that string) and **today since 00:00** (kWh generated, plus estimated kWh into the battery). The big number is no longer “estimated charge”, which read 0.00 whenever the battery was discharging even though the strings were still producing.
- PV String Charge: the cards were right (String 1 higher) but the stacked chart put String 2 on top so it looked reversed. Series are now overlaid from zero with 50% fills and solid 1 px lines. The last 6 hours are stored in a new `pv_string_charge` table, with a cumulative kWh line and the solar forecast on the same chart.
- Grott “feed lost” tray toasts: MQTT was never dropping. The Shine stick reconnects (often hourly) and Grott has nothing live to publish for about 11 minutes. The two notifications (162s then 462s) were one gap on the 5-minute repeat. Alarm text now says that; Connectivity history records stale/recover. Historical Grott buffer dumps on the same topic are ignored so midnight numbers cannot overwrite live cards.

---

## 2026-09-15

- Roof Layout satellite map: hint, imagery-date, and attribution boxes share one baseline 10 px up from the bottom.
- Roof Layout faces table: new String column for which inverter MPPT / DC string that face feeds (editable, saved with the layout).
- Added **MOTIFS.md** as the standing UI design brief: muted green primary buttons, electric-blue spin/fields, and alignment rules (Setup grids, Save under field / Test to the right, Octopus MPAN stacks). Wired into `AGENTS.md` and the Cursor agent rules.
- Octopus Live: Import MPAN sits on its own row under Account, left-aligned with Export MPAN (same for historic Import/Export). Fields no longer sit mid-row past Granularity.
- Growatt Physical “System status” now explains the raw code in plain English (e.g. 5 = PV charging the battery on SPH/MIX hybrids); hover for the full legend. Help text updated.
- Connectivity State menu on Tasmota devices: “Go to Tasmota Tab” jumps straight to the Tasmota Devices page.
- Connectivity State right-click is context-aware: Show Alarms; Test Connection and Show Downtime for Octopus, Forecast.solar, PVOutput, Wonderwatt, and Databases; Databases no longer offers Disable.
- Connectivity diagram now gives a full degradation picture: a DEGRADED banner lists what failed (Grott stale/disconnected, alarms, amber API patches), cards say who is carrying live (e.g. cloud fallback), links tint amber/red on the broken path, and click-through adds “What’s happening right now”.
- Softened Connectivity alarm visuals: warn/alarm links are a steady red/amber tint (no marching dash that looked like flashing). The ALARM badge only appears for live AlarmMonitor hits.
- Connectivity diagram now surfaces live alarms (low SOC, sun wasted, Grott lost, …) and connectivity warn/bad on the matching boxes and links (badge, border tint, link colour). Click a box for the full alarm text.
- Connectivity diagram: reverse lines between the inverter and Cloud / GROTT / Modbus are now on parallel ports (they used to share endpoints and vanish). Grott→EMQX has its own clear emerald flow lane above the amber return.
- Debugged intermittent Grott loss: auto-refresh was fully reconnecting MQTT whenever telemetry looked stale. Now we keep the session and only soft re-subscribe; full reconnect if the socket is down. Disconnect/reconnect counts and history appear on Connectivity.
- Connectivity highlight now matches **exact link edges** for the selected row (no more lighting every line into the dashboard).
- Modbus inverter writes are now **opt-in**: Setup checkbox “Allow inverter writes via Modbus”, or right-click **Inverter write (this app)** → Enable. Default remains off (safety). Connectivity row and diagram amber control reflect the flag.
- Connectivity Status: right-click a **State** cell for Disable/Enable (mutes the row), Highlight on diagram (blinks matching links at double thickness), and Show history (new `connectivity_events` table plus live alarm buffer).
- Connectivity diagram: added a **direct Modbus → Dashboard** data lane (in addition to Modbus → EMQX); left-edge ports re-spaced to six equal slots.
- Connectivity diagram: uncrossed Growatt API ↔ Dashboard and EMQX ↔ Dashboard by nesting parallel lanes (upper↔upper, lower↔lower).
- Connectivity diagram: left-edge connectors on the Energy Dashboard are equally spaced, inset 12 px from the top and bottom of the box.
- Wonderwatt Connectivity dialog: fix HTML formatting; paste/save/test the Advanced share link there (synced with Setup / Pot. Issues).
- Connectivity diagram: AI Controller and Databases are each **two-way** with the Energy Dashboard (parallel lanes up and down).
- Bugfix: PVOutput upload logging used `_log.info("…")` with one argument; the console logger needs a source tag and a message. That TypeError in the upload thread was crashing after a good upload. Same pattern cleaned up in a few other places.
- Connectivity diagram: Modbus now joins EMQX on the **left** of the broker box (same side as GROTT and Tasmota), not the bottom.
- Connectivity diagram: AI Controller and Databases sit half-width on the same top row with a link between them; Energy Dashboard is 50 px wider.
- Setup & Info: Save buttons under PVOutput, Wonderwatt, and auto-refresh left-align with the spin/field above; Test buttons sit to the right of Save.
- Connectivity diagram: Octopus, PV forecast, PVOutput, and Wonderwatt moved to an even horizontal row along the bottom.
- Connectivity diagram: EMQX moved up, centred between GROTT and Tasmota.
- Connectivity diagram: Growatt Inverter is **50% taller** and centred on the four boxes to its right (API / GROTT / Tasmota / Modbus); battery packs move down with it and show the **full serial number** (wider cards, no ellipsis trim).
- Connectivity diagram: **Tasmota ↔ EMQX is two-way** — devices publish tele/stat and accept cmnd on the same broker (drawn as two parallel green lanes). Modbus stays one-way into EMQX.
- Added **community outputs**: **PVOutput.org** (we push live generation via Add Status when you enable it in Setup) and **Wonderwatt.com** on the Connectivity diagram. Wonderwatt has no public upload API — it already pulls your plant from Growatt’s cloud; we keep the Advanced share link for forecast compare on Pot. Issues / Setup.
- Connectivity diagram redesigned so **no data flow line crosses another**. Trick: the middle column stacks Growatt API, GROTT, Tasmota, Modbus top-to-bottom in the same order their lines enter EMQX (upper-left, mid-left, bottom) and the dashboard — every route nests inside the one above it. The cloud lane runs over EMQX, Octopus / PV forecast run under Modbus, and the dashboard's Modbus write command threads the free channel between the Octopus lane and the Modbus→EMQX feed. Verified with an offscreen render.
- Connectivity diagram: Modbus now feeds **into EMQX** (one-way — the broker never drives Modbus registers) and the Modbus box sits directly under EMQX so that feed is a clean vertical line. All routes re-anchored so no line passes under a box (Tasmota's line used to clip the Modbus box, and the cloud line grazed EMQX).
- Connectivity diagram corrected again: only **Growatt API**, **GROTT**, and **Modbus** as connection methods — dropped the WiFi Direct and LAN Direct boxes entirely (stick web UI remains Setup diagnostics only).
- Added **bug_tracker.md**: standing timestamped log of every bug (symptom, cause, resolution). Seeded with today’s fixes (Connectivity diagram, GPU crash, Tasmota pin/syntax, Roof imagery chip, tight_layout). `AGENTS.md` and the always-on Cursor rule now require agents to open an entry when a bug is found and update it when fixed.
- Connectivity diagram fixed in the app (not only the docs): Wi‑Fi Direct and Modbus no longer feed into Growatt API / Grott — those are separate peers from the inverter.
- Startup crash fix: WebEngine / GPU path now forced to software GL by default (avoids “GPUInfo not initialized” segfault). Use `POWERMODEL_WEBENGINE_GPU=1` only if you want hardware GPU back.
- Architecture corrected: Growatt **cloud API**, **Grott**, **Modbus**, and the **stick web UI** are independent peers — Wi‑Fi Direct does not feed the API, and LAN/Modbus does not feed Grott.
- Architecture doc updated so **Modbus TCP/RTU** is a first-class path alongside Grott and the Growatt cloud API.
- Radio buttons on every tab now have a white 1 px outline so Import/Export and other switches are easier to see on the dark background.
- Tasmota Power History: “Pin chart 2 max” still locks the scale, but you can type the watts yourself (not fixed at 500).
- Status bar now shows this app’s CPU and RAM use in the middle (how busy one core is, and how much memory the dashboard is holding right now), updated once a second.
- Roof Layout satellite view: moved the “Imagery: Esri Wayback…” chip to the bottom centre so it no longer covers the legal map credit in the corner.
- Added root **AGENTS.md** so every AI session starts from the same brief: solar-aware, plain English, no fudging live meter/battery numbers.
- Wired an always-on Cursor rule so agents must re-read that brief (not rely on chat memory).
- Added companion docs as the **basic instructions for the development environment**: **architecture.md** (how the app is built and why), **worklog.md** (this diary), **skills.md** (expected expert skills) — all referred to from `AGENTS.md`.
- Octopus Live cumulative chart: end-of-day Imp / PV / Cons labels sit **under** the lines; today’s running tallies stay on the right.
- Tasmota charts: stopped using matplotlib `tight_layout` (it was spamming warnings on short panes) and used fixed margins instead.
- Earlier the same calendar period (see About changelog): Modbus pack serials, Setup save/load battery-solar settings, Octopus Live midnight reset and label stacking, Battery Analysis ΔSOC slope, Pot. Issues chart titles/dates, and assorted connectivity hardening — details live in `energy_dashboard/content/about.py` by version.
