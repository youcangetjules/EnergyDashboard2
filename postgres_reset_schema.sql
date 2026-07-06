-- Energy Dashboard (EnergyDashboard2.py DataLogger) — PostgreSQL
-- Drops dashboard tables, then recreates them.
--
-- Already in psql:  \c powermon
--                  \i postgres_reset_schema.sql
--
-- From shell:
--   psql "postgresql://USER:PASS@HOST:PORT/powermon" -f postgres_reset_schema.sql
--   PGPASSWORD=... psql -h HOST -p PORT -U USER -d powermon -f postgres_reset_schema.sql

BEGIN;

DROP TABLE IF EXISTS growatt_mix_chart;
DROP TABLE IF EXISTS tasmota_readings;
DROP TABLE IF EXISTS tasmota_devices;
DROP TABLE IF EXISTS octopus_readings;
DROP TABLE IF EXISTS growatt_readings;

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

-- One row per device (IP); updated on each successful Tasmota poll
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

COMMIT;
