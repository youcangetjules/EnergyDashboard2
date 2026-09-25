-- Energy Dashboard — PostgreSQL WIPE then recreate.
-- This file drops every logger table and builds them again. It deletes rows.
-- To create any missing tables without deleting data, copy the CREATE SQL
-- from Setup & Info (right-hand pane) and run that by hand as the database
-- owner. The dashboard login (including EMQX) must not create tables.
-- The CREATE list is energy_dashboard/db/full_schema.py.
--
-- Already in psql:  \c powermon
--                  \i postgres_reset_schema.sql
--
-- From shell:
--   psql "postgresql://USER:PASS@HOST:PORT/powermon" -f postgres_reset_schema.sql
--   PGPASSWORD=... psql -h HOST -p PORT -U USER -d powermon -f postgres_reset_schema.sql

BEGIN;

DROP TABLE IF EXISTS optimiser_shadow_scores;
DROP TABLE IF EXISTS optimiser_shadow_plans;
DROP TABLE IF EXISTS solar_forecast_snapshots;
DROP TABLE IF EXISTS agile_price_snapshots;
DROP TABLE IF EXISTS agile_year_daily;
DROP TABLE IF EXISTS growatt_mix_chart;
DROP TABLE IF EXISTS tasmota_readings;
DROP TABLE IF EXISTS tasmota_devices;
DROP TABLE IF EXISTS octopus_readings;
DROP TABLE IF EXISTS growatt_readings;
DROP TABLE IF EXISTS connectivity_events;
DROP TABLE IF EXISTS pv_string_voltage;
DROP TABLE IF EXISTS pv_string_charge;

CREATE TABLE growatt_readings (
    id SERIAL PRIMARY KEY,
    timestamp TEXT NOT NULL,
    soc_pct REAL,
    battery_power_kw REAL,
    pv_power_kw REAL,
    grid_power_kw REAL,
    load_power_kw REAL,
    charge_today_kwh REAL,
    discharge_today_kwh REAL,
    pv_today_kwh REAL
);

CREATE TABLE tasmota_readings (
    id SERIAL PRIMARY KEY,
    timestamp TEXT NOT NULL,
    device_ip TEXT,
    device_name TEXT,
    power_w REAL,
    voltage_v REAL,
    current_a REAL,
    today_kwh REAL,
    total_kwh REAL
);

CREATE TABLE tasmota_devices (
    id SERIAL PRIMARY KEY,
    device_ip TEXT NOT NULL UNIQUE,
    device_name TEXT,
    relay_on INTEGER,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE octopus_readings (
    id SERIAL PRIMARY KEY,
    interval_start TEXT NOT NULL UNIQUE,
    import_kwh REAL,
    export_kwh REAL,
    logged_at TEXT NOT NULL
);

CREATE TABLE solar_forecast_snapshots (
    id SERIAL PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    tilt REAL,
    azimuth REAL,
    kwp REAL,
    interval_start TEXT NOT NULL,
    kw REAL NOT NULL
);

CREATE TABLE agile_price_snapshots (
    id SERIAL PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    tariff_code TEXT NOT NULL,
    direction TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT NOT NULL,
    price_pence REAL,
    UNIQUE(tariff_code, direction, valid_from)
);

CREATE TABLE growatt_mix_chart (
    id SERIAL PRIMARY KEY,
    device_sn TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    pv_kw REAL,
    charge_kw REAL,
    discharge_kw REAL,
    grid_import_kw REAL,
    grid_export_kw REAL,
    load_kw REAL,
    UNIQUE(device_sn, timestamp)
);

CREATE INDEX idx_growatt_mix_chart_ts ON growatt_mix_chart(timestamp);

CREATE TABLE optimiser_shadow_plans (
    id SERIAL PRIMARY KEY,
    day_date TEXT NOT NULL UNIQUE,
    built_at TEXT NOT NULL,
    soc_start_pct REAL,
    soc_source TEXT,
    capacity_kwh REAL,
    eta REAL,
    max_kw REAL,
    soc_min_pct REAL,
    allow_export INTEGER,
    planned_cost_p REAL,
    slot_count INTEGER,
    plan_json TEXT NOT NULL
);

CREATE TABLE optimiser_shadow_scores (
    id SERIAL PRIMARY KEY,
    day_date TEXT NOT NULL UNIQUE,
    scored_at TEXT NOT NULL,
    octopus_complete INTEGER,
    telemetry_slots INTEGER,
    expected_slots INTEGER,
    soc_start_pct REAL,
    actual_cost_p REAL,
    shadow_cost_p REAL,
    baseline_cost_p REAL,
    perfect_cost_p REAL,
    actual_capture REAL,
    shadow_capture REAL,
    detail_json TEXT
);

CREATE INDEX idx_solar_fc_interval ON solar_forecast_snapshots(interval_start);
CREATE INDEX idx_solar_fc_fetched ON solar_forecast_snapshots(fetched_at);
CREATE INDEX idx_agile_fc_valid_from ON agile_price_snapshots(valid_from);

CREATE TABLE agile_year_daily (
    id SERIAL PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    tariff_code TEXT NOT NULL,
    direction TEXT NOT NULL,
    day_date TEXT NOT NULL,
    high_pence REAL NOT NULL,
    low_pence REAL NOT NULL,
    avg_pence REAL NOT NULL,
    neg_hours REAL NOT NULL,
    slots INTEGER NOT NULL,
    UNIQUE(tariff_code, direction, day_date)
);
CREATE INDEX idx_agile_year_daily_day ON agile_year_daily(day_date);

CREATE TABLE connectivity_events (
    id SERIAL PRIMARY KEY,
    timestamp TEXT NOT NULL,
    service_key TEXT NOT NULL,
    service_label TEXT,
    event_type TEXT NOT NULL,
    state_key TEXT,
    state_text TEXT,
    detail TEXT
);
CREATE INDEX idx_connectivity_events_service_ts
    ON connectivity_events (service_key, timestamp);

CREATE TABLE pv_string_charge (
    time TEXT NOT NULL PRIMARY KEY,
    pv_string1 REAL,
    pv_string2 REAL,
    power_string1 REAL,
    power_string2 REAL,
    charge_kw REAL,
    samples INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE pv_string_voltage (
    time TEXT NOT NULL PRIMARY KEY,
    v_string1 REAL,
    v_string2 REAL,
    samples INTEGER NOT NULL DEFAULT 1
);

COMMIT;
