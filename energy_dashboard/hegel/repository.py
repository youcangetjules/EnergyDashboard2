"""Read and write the hegel database. Does not create the database or tables."""
from __future__ import annotations

import json
from dataclasses import dataclass

from energy_dashboard.hegel import HEGEL_DBNAME
from energy_dashboard.hegel.dedup import deduplicate
from energy_dashboard.hegel.models import Observation, Pod, Resource


class HegelDbError(Exception):
    """The hegel database could not be used. The message is safe to show."""


@dataclass(frozen=True)
class InventorySnapshot:
    pod: Pod | None
    observations: int
    resources: int
    detail: str


def connection_settings() -> dict[str, object]:
    """Same host, port, and login as the plant database. Different database name."""
    from energy_dashboard.deps import QSettings

    settings = QSettings("PowerModel", "EnergyDashboard2")
    try:
        port = int(settings.value("db/pg_port", 5432) or 5432)
    except (TypeError, ValueError):
        port = 5432
    return {
        "host": str(settings.value("db/pg_host", "localhost") or "localhost").strip() or "localhost",
        "port": port,
        "user": str(settings.value("db/pg_user", "") or "").strip(),
        "password": str(settings.value("db/pg_pass", "") or ""),
        "dbname": HEGEL_DBNAME,
    }


def connect():
    """Open hegel. Raises HegelDbError. Does not create anything."""
    from energy_dashboard.db.connect_probe import postgresql_connect

    cfg = connection_settings()
    if not cfg["user"]:
        raise HegelDbError(
            "PostgreSQL has no user yet. Set it under Setup & Info → Database, "
            "then check the inventory again."
        )
    try:
        return postgresql_connect(
            cfg["host"],
            cfg["port"],
            cfg["user"],
            cfg["password"],
            cfg["dbname"],
            timeout=3,
        )
    except Exception as exc:
        raise HegelDbError(_public_connect_error(exc, cfg)) from exc


def inventory_snapshot() -> InventorySnapshot:
    """Read the pod and how many rows are stored. One short connection."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pod_id, name, centre_lat, centre_lon, radius_km, locality_label
                FROM hegel_pod
                ORDER BY pod_id
                LIMIT 1
                """
            )
            row = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM hegel_observation")
            observations = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM hegel_resource")
            resources = int(cur.fetchone()[0])
    except Exception as exc:
        raise HegelDbError(_public_query_error(exc)) from exc
    finally:
        conn.close()
    pod = None
    if row:
        pod = Pod(
            pod_id=row[0],
            name=row[1],
            centre_lat=float(row[2]),
            centre_lon=float(row[3]),
            radius_km=float(row[4]),
            locality_label=row[5] or "",
        )
    if pod is None:
        detail = "The hegel database is there, and it has no pod row yet."
    else:
        detail = (
            f"{pod.name} is a {pod.radius_km:g} km circle around "
            f"{pod.centre_lat:.3f}, {pod.centre_lon:.3f}. "
            f"{pod.locality_label or 'The locality label'} names the area. "
            "It is not a rooftop pin. "
            f"{observations} source row{'s' if observations != 1 else ''}, "
            f"{resources} linked resource{'s' if resources != 1 else ''}."
        )
    return InventorySnapshot(pod, observations, resources, detail)


def replace_pod_inventory(pod: Pod, rows: list[Observation]) -> int:
    """Replace one pod's source rows and rebuild the linked resources.

    Returns the number of linked resources. Caller supplies rows already
    limited to the pod. This does not contact an external site.
    """
    resources = deduplicate(rows)
    conn = connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hegel_pod (
                        pod_id, name, centre_lat, centre_lon, radius_km, locality_label, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (pod_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        centre_lat = EXCLUDED.centre_lat,
                        centre_lon = EXCLUDED.centre_lon,
                        radius_km = EXCLUDED.radius_km,
                        locality_label = EXCLUDED.locality_label,
                        updated_at = now()
                    """,
                    (
                        pod.pod_id,
                        pod.name,
                        pod.centre_lat,
                        pod.centre_lon,
                        pod.radius_km,
                        pod.locality_label,
                    ),
                )
                cur.execute(
                    "DELETE FROM hegel_resource WHERE pod_id = %s",
                    (pod.pod_id,),
                )
                cur.execute(
                    "DELETE FROM hegel_observation WHERE pod_id = %s",
                    (pod.pod_id,),
                )
                id_by_key: dict[tuple[str, str], int] = {}
                for row in rows:
                    if row.pod_id != pod.pod_id:
                        raise HegelDbError("A source row names a different pod from the one being saved.")
                    cur.execute(
                        """
                        INSERT INTO hegel_observation (
                            pod_id, source, source_record_id, resource_type,
                            latitude, longitude, location_accuracy,
                            installed_capacity_kwp, storage_capacity_kwh,
                            equipment_metadata, observation_timestamp,
                            confidence, verification_status
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s::jsonb, %s,
                            %s, %s
                        )
                        RETURNING observation_id
                        """,
                        (
                            row.pod_id,
                            row.source,
                            row.source_record_id,
                            row.resource_type,
                            row.latitude,
                            row.longitude,
                            row.location_accuracy,
                            row.installed_capacity_kwp,
                            row.storage_capacity_kwh,
                            json.dumps(row.equipment_metadata or {}),
                            row.observation_timestamp,
                            row.confidence,
                            row.verification_status,
                        ),
                    )
                    id_by_key[(row.source, row.source_record_id)] = int(cur.fetchone()[0])
                for resource in resources:
                    _insert_resource(cur, resource, id_by_key)
    except HegelDbError:
        raise
    except Exception as exc:
        raise HegelDbError(_public_query_error(exc)) from exc
    finally:
        conn.close()
    return len(resources)


def _insert_resource(cur, resource: Resource, id_by_key: dict[tuple[str, str], int]) -> None:
    cur.execute(
        """
        INSERT INTO hegel_resource (
            resource_id, pod_id, resource_type, latitude, longitude,
            location_accuracy, installed_capacity_kwp, storage_capacity_kwh,
            equipment_metadata, confidence, verification_status, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s::jsonb, %s, %s, now()
        )
        """,
        (
            resource.resource_id,
            resource.pod_id,
            resource.resource_type,
            resource.latitude,
            resource.longitude,
            resource.location_accuracy,
            resource.installed_capacity_kwp,
            resource.storage_capacity_kwh,
            json.dumps(resource.equipment_metadata or {}),
            resource.confidence,
            resource.verification_status,
        ),
    )
    for key in resource.members:
        observation_id = id_by_key.get(key)
        if observation_id is None:
            continue
        cur.execute(
            """
            INSERT INTO hegel_resource_source (resource_id, observation_id)
            VALUES (%s, %s)
            """,
            (resource.resource_id, observation_id),
        )


def _public_connect_error(exc: BaseException, cfg: dict) -> str:
    text = str(exc).lower()
    host = cfg["host"]
    port = cfg["port"]
    if "does not exist" in text and HEGEL_DBNAME in text:
        return (
            f"PostgreSQL on {host}:{port} has no database named {HEGEL_DBNAME} yet. "
            "The database owner runs hegel_postgres.sql. The plant database is left as it is."
        )
    if "password" in text or "authentication" in text or "auth" in text:
        return (
            f"PostgreSQL on {host}:{port} refused the login from Setup & Info. "
            "The password is not shown here."
        )
    if "timeout" in text or "could not connect" in text or "connection refused" in text:
        return f"PostgreSQL on {host}:{port} did not answer."
    return f"Could not open the {HEGEL_DBNAME} database on {host}:{port}."


def _public_query_error(exc: BaseException) -> str:
    text = str(exc).lower()
    if "hegel_pod" in text or "hegel_observation" in text or "does not exist" in text:
        return (
            "The hegel database is missing its tables. "
            "The database owner runs hegel_postgres.sql."
        )
    if "permission" in text or "privilege" in text:
        return (
            "The dashboard login can see PostgreSQL, but it cannot read the hegel tables. "
            "The owner script grants that login SELECT, INSERT, UPDATE, and DELETE."
        )
    return "The hegel database refused the inventory read."
