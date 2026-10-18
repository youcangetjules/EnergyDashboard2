"""PostgreSQL objects for the hegel database.

The plant log stays in its own database (powermon). These statements run
only inside the database named hegel, and only when the owner applies
``hegel_postgres.sql``. The dashboard login does not create them.
"""
from __future__ import annotations

HEGEL_TABLES = (
    "hegel_pod",
    "hegel_observation",
    "hegel_resource",
    "hegel_resource_source",
)

POD_DDL = """
CREATE TABLE IF NOT EXISTS hegel_pod (
    pod_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    centre_lat DOUBLE PRECISION NOT NULL,
    centre_lon DOUBLE PRECISION NOT NULL,
    radius_km DOUBLE PRECISION NOT NULL,
    locality_label TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
""".strip()

OBSERVATION_DDL = """
CREATE TABLE IF NOT EXISTS hegel_observation (
    observation_id BIGSERIAL PRIMARY KEY,
    pod_id TEXT NOT NULL REFERENCES hegel_pod (pod_id),
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
)
""".strip()

RESOURCE_DDL = """
CREATE TABLE IF NOT EXISTS hegel_resource (
    resource_id TEXT PRIMARY KEY,
    pod_id TEXT NOT NULL REFERENCES hegel_pod (pod_id),
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
)
""".strip()

LINK_DDL = """
CREATE TABLE IF NOT EXISTS hegel_resource_source (
    resource_id TEXT NOT NULL REFERENCES hegel_resource (resource_id) ON DELETE CASCADE,
    observation_id BIGINT NOT NULL REFERENCES hegel_observation (observation_id) ON DELETE CASCADE,
    PRIMARY KEY (resource_id, observation_id)
)
""".strip()

TABLE_DDL = (POD_DDL, OBSERVATION_DDL, RESOURCE_DDL, LINK_DDL)
