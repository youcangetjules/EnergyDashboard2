# CLAUDE.md

This file provides guidance when working in this repository.

## Project Overview

**EnergyDashboard2.py** is the primary application: a PySide6 energy monitoring GUI that integrates Octopus Energy consumption data, Growatt inverter/battery APIs, Tasmota power monitors, PostgreSQL/SQLite logging, and matplotlib visualizations.

Older research scripts live in `legacy/` and are not part of day-to-day work.

## Running

```bash
./setup.sh
python EnergyDashboard2.py          # or: python -m energy_dashboard
```

Optional background service: `services/energy_collector.py` polls **Tasmota** and **Growatt cloud**, writes to PostgreSQL, serves `GET /snapshot` for the GUI.

Install **system service** (runs at boot, dashboard closed): `sudo ./services/install-energy-collector.sh`  
Install user service (dev / no root): `./services/install-powermon-broker-user.sh`

## Active layout

| Path | Purpose |
|------|---------|
| `EnergyDashboard2.py` | Thin launcher (venv re-exec + `energy_dashboard` package) |
| `energy_dashboard/` | Modular application code (split from the former monolith) |
| `energy_dashboard/main_window.py` | `EnergyDashboard` main window |
| `energy_dashboard/tabs/` | One module per dashboard tab |
| `energy_dashboard/fetch/` | Octopus / Tasmota / solar API clients |
| `energy_dashboard/db/` | `DataLogger` and schema setup |
| `energy_dashboard/ui/` | Styles, charts, widgets, tab bar chrome |
| `services/` | Sidecar services used by the dashboard |
| `assets/`, `_ui_assets/` | Images and spin-button SVGs |
| `requirements.txt` | Python dependencies |
| `postgres_reset_schema.sql` | PostgreSQL schema for DataLogger |
| `GROWATT_API.md` | Growatt API notes referenced during dashboard work |

## Legacy scripts

`legacy/` holds archived scripts (PowerModel*, BigSim*, EnergyDashboard.py v1, GetGrowatt.py, etc.). Do not modify unless explicitly requested.

## Security

API credentials may appear in script headers. Prefer environment variables; never commit live keys.
