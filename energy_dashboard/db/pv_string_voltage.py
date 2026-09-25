"""Measured PV-string DC voltage in 2-minute lots.

Columns:

- ``time`` — UTC start of the 2-minute slot
- ``v_string1`` / ``v_string2`` — measured MPPT volts (vPv1 / vPv2), averaged
  across samples in the slot. A missing reading stays NULL; it is not stored as 0 V.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from energy_dashboard.db.pv_string_charge import lot_start

_WINDOW = timedelta(hours=6)

_DDL = """
CREATE TABLE IF NOT EXISTS pv_string_voltage (
    time TEXT NOT NULL PRIMARY KEY,
    v_string1 REAL,
    v_string2 REAL,
    samples INTEGER NOT NULL DEFAULT 1
)"""

_PV_STRING_VOLTAGE_DDL = _DDL
_PV_STRING_VOLTAGE_DDL_PG = _DDL
_PV_STRING_VOLTAGE_DDL_MY = _DDL

_AVG1 = """
    CASE
        WHEN excluded.v_string1 IS NULL THEN pv_string_voltage.v_string1
        WHEN pv_string_voltage.v_string1 IS NULL THEN excluded.v_string1
        ELSE (pv_string_voltage.v_string1 * pv_string_voltage.samples
              + excluded.v_string1) / (pv_string_voltage.samples + 1)
    END"""
_AVG2 = _AVG1.replace("v_string1", "v_string2")

_UPSERT = f"""
INSERT INTO pv_string_voltage (time, v_string1, v_string2, samples)
VALUES (?, ?, ?, 1)
ON CONFLICT(time) DO UPDATE SET
    v_string1 = {_AVG1},
    v_string2 = {_AVG2},
    samples = pv_string_voltage.samples + 1
"""
_UPSERT_PG = _UPSERT.replace("?", "%s")

_UPSERT_MY = """
INSERT INTO pv_string_voltage (time, v_string1, v_string2, samples)
VALUES (%s, %s, %s, 1)
ON DUPLICATE KEY UPDATE
    v_string1 = CASE
        WHEN VALUES(v_string1) IS NULL THEN v_string1
        WHEN v_string1 IS NULL THEN VALUES(v_string1)
        ELSE (v_string1 * samples + VALUES(v_string1)) / (samples + 1)
    END,
    v_string2 = CASE
        WHEN VALUES(v_string2) IS NULL THEN v_string2
        WHEN v_string2 IS NULL THEN VALUES(v_string2)
        ELSE (v_string2 * samples + VALUES(v_string2)) / (samples + 1)
    END,
    samples = samples + 1
"""

_SELECT = """
SELECT time, v_string1, v_string2, samples
FROM pv_string_voltage
WHERE time >= ? AND time <= ?
ORDER BY time ASC
"""
_SELECT_PG = _SELECT.replace("?", "%s")


def _sql_ts(when: datetime) -> str:
    return lot_start(when).strftime("%Y-%m-%d %H:%M:%S")


def _parse_ts(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    s = str(raw).strip()
    if len(s) >= 19:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _opt(val) -> float | None:
    if val is None or val in ("", "--", "—"):
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def ensure_pv_string_voltage(conn, *, dialect: str = "sqlite") -> None:
    """CREATE TABLE if missing. PostgreSQL setup is the owner script, not this call."""
    ddl = {
        "pg": _PV_STRING_VOLTAGE_DDL_PG,
        "mysql": _PV_STRING_VOLTAGE_DDL_MY,
    }.get(dialect, _PV_STRING_VOLTAGE_DDL)
    if dialect == "sqlite":
        conn.execute(ddl)
        conn.commit()
        return
    with conn.cursor() as cur:
        cur.execute(ddl)


def log_pv_string_voltage(data_logger, sample: dict[str, Any]) -> None:
    """Upsert one live sample into its 2-minute lot. Skip when both volts are missing."""
    if data_logger is None:
        return
    v1 = _opt(sample.get("v1"))
    v2 = _opt(sample.get("v2"))
    if v1 is None and v2 is None:
        return
    when = sample.get("t")
    if not isinstance(when, datetime):
        when = datetime.now(timezone.utc)
    row = (_sql_ts(when), v1, v2)
    put = getattr(data_logger, "enqueue_pv_string_voltage", None)
    if callable(put):
        put(row)
        return
    write_pv_string_voltage(data_logger, row)


def _engine_ready(data_logger, name: str) -> bool:
    fn = getattr(data_logger, "backend_ready", None)
    if callable(fn):
        return bool(fn(name))
    return True


def write_pv_string_voltage(data_logger, row) -> None:
    """Writer-thread upsert. Does not CREATE on PostgreSQL."""
    try:
        if getattr(data_logger, "sqlite_enabled", False):
            conn = data_logger._ensure_sqlite()
            ensure_pv_string_voltage(conn, dialect="sqlite")
            conn.execute(_UPSERT, row)
            conn.commit()
    except Exception:
        pass
    try:
        if getattr(data_logger, "mysql_enabled", False) and _engine_ready(data_logger, "mysql"):
            conn = data_logger._ensure_mysql()
            ensure_pv_string_voltage(conn, dialect="mysql")
            with conn.cursor() as cur:
                cur.execute(_UPSERT_MY, row)
    except Exception:
        pass
    try:
        if getattr(data_logger, "pg_enabled", False) and _engine_ready(data_logger, "pg"):
            conn = data_logger._ensure_pg()
            with conn.cursor() as cur:
                cur.execute(_UPSERT_PG, row)
    except Exception:
        pass


def query_pv_string_voltage(
    data_logger,
    *,
    start_utc: datetime | None = None,
    end_utc: datetime | None = None,
) -> list[dict[str, Any]]:
    """Oldest-first 2-minute lots in ``[start_utc, end_utc]`` (default last 6 hours)."""
    if data_logger is None:
        return []
    end = end_utc or datetime.now(timezone.utc)
    start = start_utc or (end - _WINDOW)
    params = (_sql_ts(start), _sql_ts(end))

    def _rows(fetchall) -> list[dict[str, Any]]:
        out = []
        for r in fetchall or ():
            ts = _parse_ts(r[0])
            if ts is None:
                continue
            out.append({
                "t": ts,
                "v1": _opt(r[1]),
                "v2": _opt(r[2]),
                "samples": int(r[3] or 1) if len(r) > 3 else 1,
            })
        return out

    try:
        if getattr(data_logger, "sqlite_enabled", False):
            conn = data_logger._ensure_sqlite()
            ensure_pv_string_voltage(conn, dialect="sqlite")
            cur = conn.execute(_SELECT, params)
            return _rows(cur.fetchall())
    except Exception:
        pass
    try:
        if getattr(data_logger, "pg_enabled", False) and _engine_ready(data_logger, "pg"):
            conn = data_logger._ensure_pg()
            with conn.cursor() as cur:
                cur.execute(_SELECT_PG, params)
                return _rows(cur.fetchall())
    except Exception:
        pass
    try:
        if getattr(data_logger, "mysql_enabled", False) and _engine_ready(data_logger, "mysql"):
            conn = data_logger._ensure_mysql()
            ensure_pv_string_voltage(conn, dialect="mysql")
            with conn.cursor() as cur:
                cur.execute(_SELECT_PG, params)
                return _rows(cur.fetchall())
    except Exception:
        pass
    return []


__all__ = [
    "ensure_pv_string_voltage",
    "log_pv_string_voltage",
    "write_pv_string_voltage",
    "query_pv_string_voltage",
    "_PV_STRING_VOLTAGE_DDL",
    "_PV_STRING_VOLTAGE_DDL_PG",
    "_PV_STRING_VOLTAGE_DDL_MY",
]
