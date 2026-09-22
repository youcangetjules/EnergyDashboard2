"""Persisted PV-string charge in 2-minute lots.

Columns (plus an internal ``samples`` count for averaging the lot):

- ``time`` — UTC start of the 2-minute slot
- ``pv_string1`` / ``pv_string2`` — measured string PV (pPv1 / pPv2, kW)
- ``power_string1`` / ``power_string2`` — estimated battery charge from that string (kW)
- ``charge_kw`` — measured battery chargePower (kW); needed because estimated
  string charge can be zero while the pack is still AC-charging
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

_WINDOW = timedelta(hours=6)
_LOT_S = 120

_PV_STRING_CHARGE_DDL = """
CREATE TABLE IF NOT EXISTS pv_string_charge (
    time TEXT NOT NULL PRIMARY KEY,
    pv_string1 REAL,
    pv_string2 REAL,
    power_string1 REAL,
    power_string2 REAL,
    charge_kw REAL,
    samples INTEGER NOT NULL DEFAULT 1
)"""

_PV_STRING_CHARGE_DDL_PG = _PV_STRING_CHARGE_DDL
_PV_STRING_CHARGE_DDL_MY = _PV_STRING_CHARGE_DDL

_UPSERT = """
INSERT INTO pv_string_charge
    (time, pv_string1, pv_string2, power_string1, power_string2, charge_kw, samples)
VALUES (?, ?, ?, ?, ?, ?, 1)
ON CONFLICT(time) DO UPDATE SET
    pv_string1 = (COALESCE(pv_string_charge.pv_string1, 0)
                  * pv_string_charge.samples + excluded.pv_string1)
                 / (pv_string_charge.samples + 1),
    pv_string2 = (COALESCE(pv_string_charge.pv_string2, 0)
                  * pv_string_charge.samples + excluded.pv_string2)
                 / (pv_string_charge.samples + 1),
    power_string1 = (COALESCE(pv_string_charge.power_string1, 0)
                     * pv_string_charge.samples + excluded.power_string1)
                    / (pv_string_charge.samples + 1),
    power_string2 = (COALESCE(pv_string_charge.power_string2, 0)
                     * pv_string_charge.samples + excluded.power_string2)
                    / (pv_string_charge.samples + 1),
    charge_kw = (COALESCE(pv_string_charge.charge_kw, 0)
                 * pv_string_charge.samples + excluded.charge_kw)
                / (pv_string_charge.samples + 1),
    samples = pv_string_charge.samples + 1
"""
_UPSERT_PG = _UPSERT.replace("?", "%s")

_UPSERT_MY = """
INSERT INTO pv_string_charge
    (time, pv_string1, pv_string2, power_string1, power_string2, charge_kw, samples)
VALUES (%s, %s, %s, %s, %s, %s, 1)
ON DUPLICATE KEY UPDATE
    pv_string1 = (COALESCE(pv_string1, 0) * samples + VALUES(pv_string1))
                 / (samples + 1),
    pv_string2 = (COALESCE(pv_string2, 0) * samples + VALUES(pv_string2))
                 / (samples + 1),
    power_string1 = (COALESCE(power_string1, 0) * samples + VALUES(power_string1))
                    / (samples + 1),
    power_string2 = (COALESCE(power_string2, 0) * samples + VALUES(power_string2))
                    / (samples + 1),
    charge_kw = (COALESCE(charge_kw, 0) * samples + VALUES(charge_kw))
                / (samples + 1),
    samples = samples + 1
"""

_SELECT = """
SELECT time, pv_string1, pv_string2, power_string1, power_string2, charge_kw, samples
FROM pv_string_charge
WHERE time >= ? AND time <= ?
ORDER BY time ASC
"""
_SELECT_PG = _SELECT.replace("?", "%s")


def lot_start(when: datetime | None = None) -> datetime:
    """Floor ``when`` (default now) to the UTC 2-minute lot start."""
    dt = when or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    epoch = int(dt.timestamp())
    floored = epoch - (epoch % _LOT_S)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


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
    if not s:
        return None
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


def _f(val, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _column_names(conn, *, dialect: str) -> list[str]:
    try:
        if dialect == "sqlite":
            rows = conn.execute("PRAGMA table_info(pv_string_charge)").fetchall()
            return [str(r[1]) for r in rows]
        sql = (
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'pv_string_charge'"
        )
        if dialect == "pg":
            with conn.cursor() as cur:
                cur.execute(sql)
                return [str(r[0]) for r in cur.fetchall()]
        with conn.cursor() as cur:
            cur.execute(sql)
            return [str(r[0]) for r in cur.fetchall()]
    except Exception:
        return []


def _schema_ok(cols: list[str]) -> bool:
    need = {"time", "pv_string1", "pv_string2", "power_string1", "power_string2"}
    lower = {c.lower() for c in cols}
    return need <= lower


def _drop_table(conn, *, dialect: str) -> None:
    if dialect == "sqlite":
        conn.execute("DROP TABLE IF EXISTS pv_string_charge")
        return
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS pv_string_charge")


def ensure_pv_string_charge(conn, *, dialect: str = "sqlite") -> None:
    """CREATE TABLE; rebuild if this is the older wide-column schema."""
    cols = _column_names(conn, dialect=dialect)
    if cols and not _schema_ok(cols):
        _drop_table(conn, dialect=dialect)
        cols = []
    ddl = {
        "pg": _PV_STRING_CHARGE_DDL_PG,
        "mysql": _PV_STRING_CHARGE_DDL_MY,
    }.get(dialect, _PV_STRING_CHARGE_DDL)
    if dialect == "sqlite":
        conn.execute(ddl)
        conn.commit()
        return
    with conn.cursor() as cur:
        cur.execute(ddl)


def log_pv_string_charge(data_logger, sample: dict[str, Any]) -> None:
    """Upsert one live sample into its 2-minute lot (running mean)."""
    if data_logger is None:
        return
    when = sample.get("t")
    if not isinstance(when, datetime):
        when = datetime.now(timezone.utc)
    row = (
        _sql_ts(when),
        _f(sample.get("pv1"), 0.0),
        _f(sample.get("pv2"), 0.0),
        _f(sample.get("s1"), 0.0),
        _f(sample.get("s2"), 0.0),
        _f(sample.get("chg"), 0.0),
    )
    put = getattr(data_logger, "enqueue_pv_string_charge", None)
    if callable(put):
        put(row)
        return
    write_pv_string_charge(data_logger, row)


def _engine_ready(data_logger, name: str) -> bool:
    fn = getattr(data_logger, "backend_ready", None)
    if callable(fn):
        return bool(fn(name))
    return True


def write_pv_string_charge(data_logger, row) -> None:
    """Writer-thread upsert; skips engines in reconnect backoff."""
    try:
        if getattr(data_logger, "sqlite_enabled", False):
            conn = data_logger._ensure_sqlite()
            ensure_pv_string_charge(conn, dialect="sqlite")
            conn.execute(_UPSERT, row)
            conn.commit()
    except Exception:
        pass
    try:
        if getattr(data_logger, "mysql_enabled", False) and _engine_ready(data_logger, "mysql"):
            conn = data_logger._ensure_mysql()
            ensure_pv_string_charge(conn, dialect="mysql")
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


def query_pv_string_charge(
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
                "pv1": _f(r[1]),
                "pv2": _f(r[2]),
                "s1": _f(r[3]),
                "s2": _f(r[4]),
                "chg": _f(r[5]),
                "samples": int(r[6] or 1) if len(r) > 6 else 1,
            })
        return out

    try:
        if getattr(data_logger, "sqlite_enabled", False):
            conn = data_logger._ensure_sqlite()
            ensure_pv_string_charge(conn, dialect="sqlite")
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
            ensure_pv_string_charge(conn, dialect="mysql")
            with conn.cursor() as cur:
                cur.execute(_SELECT_PG, params)
                return _rows(cur.fetchall())
    except Exception:
        pass
    return []


__all__ = [
    "ensure_pv_string_charge",
    "log_pv_string_charge",
    "write_pv_string_charge",
    "query_pv_string_charge",
    "lot_start",
    "_WINDOW",
    "_LOT_S",
    "_PV_STRING_CHARGE_DDL",
    "_PV_STRING_CHARGE_DDL_PG",
    "_PV_STRING_CHARGE_DDL_MY",
]
