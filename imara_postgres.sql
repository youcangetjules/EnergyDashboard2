-- Imara-RDC inventory database. Separate from the plant log (powermon).
-- Run as a PostgreSQL superuser, from any database:
--
--   sudo -u postgres psql -v imara_login=YOUR_DASHBOARD_USER -f imara_postgres.sql
--
-- This creates the database "imara" if it is missing, then the tables.
-- It does not drop or alter powermon.
-- The dashboard login must not create databases or tables.
-- imara_login is that login's role name (Setup & Info → PostgreSQL user).

\set ON_ERROR_STOP on

SELECT 'CREATE DATABASE imara'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'imara')
\gexec

\c imara

CREATE TABLE IF NOT EXISTS imara_pod (
    pod_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    centre_lat DOUBLE PRECISION NOT NULL,
    centre_lon DOUBLE PRECISION NOT NULL,
    radius_km DOUBLE PRECISION NOT NULL,
    locality_label TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS imara_observation (
    observation_id BIGSERIAL PRIMARY KEY,
    pod_id TEXT NOT NULL REFERENCES imara_pod (pod_id),
    source TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    location_accuracy TEXT NOT NULL,
    installed_capacity_kwp DOUBLE PRECISION,
    storage_capacity_kwh DOUBLE PRECISION,
    equipment_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    observation_timestamp TIMESTAMPTZ,
    confidence DOUBLE PRECISION,
    verification_status TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (pod_id, source, source_record_id)
);

CREATE TABLE IF NOT EXISTS imara_resource (
    resource_id TEXT PRIMARY KEY,
    pod_id TEXT NOT NULL REFERENCES imara_pod (pod_id),
    resource_type TEXT NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    location_accuracy TEXT NOT NULL,
    installed_capacity_kwp DOUBLE PRECISION,
    storage_capacity_kwh DOUBLE PRECISION,
    equipment_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence DOUBLE PRECISION,
    verification_status TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS imara_resource_source (
    resource_id TEXT NOT NULL REFERENCES imara_resource (resource_id) ON DELETE CASCADE,
    observation_id BIGINT NOT NULL REFERENCES imara_observation (observation_id) ON DELETE CASCADE,
    PRIMARY KEY (resource_id, observation_id)
);

-- OX39 is the postcode district name. The coordinates are the configured
-- circle centre, not a rooftop and not the postcode centroid.
INSERT INTO imara_pod (pod_id, name, centre_lat, centre_lon, radius_km, locality_label)
VALUES ('chinnor', 'Chinnor', 51.701, -0.901, 5.0, 'OX39')
ON CONFLICT (pod_id) DO NOTHING;

\if :{?imara_login}
GRANT CONNECT ON DATABASE imara TO :"imara_login";
GRANT USAGE ON SCHEMA public TO :"imara_login";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"imara_login";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"imara_login";
\endif
