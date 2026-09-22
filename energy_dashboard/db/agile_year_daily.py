"""Daily Agile high / low / average rows for the Agile Year tab.

One row per Europe/London calendar day per tariff and direction. Half-hour
slots still live in ``agile_price_snapshots``; this table is the year view
so it can load without re-pulling 370 days from Octopus, and so a
since-start trend can grow beyond one API window.

PostgreSQL: the dashboard login must not CREATE — the owner runs Setup SQL.
SQLite / MySQL still create via ``apply_full_schema``.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

_AGILE_YEAR_DAILY_DDL = """
CREATE TABLE IF NOT EXISTS agile_year_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
)"""
_AGILE_YEAR_DAILY_DDL_PG = _AGILE_YEAR_DAILY_DDL.replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY"
)
_AGILE_YEAR_DAILY_DDL_MY = _AGILE_YEAR_DAILY_DDL.replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT", "INTEGER PRIMARY KEY AUTO_INCREMENT"
)
_AGILE_YEAR_DAILY_IDX = (
    "CREATE INDEX IF NOT EXISTS idx_agile_year_daily_day "
    "ON agile_year_daily(day_date)",
)

_UPSERT_SQLITE = """
INSERT INTO agile_year_daily
    (fetched_at, tariff_code, direction, day_date,
     high_pence, low_pence, avg_pence, neg_hours, slots)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(tariff_code, direction, day_date) DO UPDATE SET
    high_pence = excluded.high_pence,
    low_pence = excluded.low_pence,
    avg_pence = excluded.avg_pence,
    neg_hours = excluded.neg_hours,
    slots = excluded.slots,
    fetched_at = excluded.fetched_at
"""
_UPSERT_PG = """
INSERT INTO agile_year_daily
    (fetched_at, tariff_code, direction, day_date,
     high_pence, low_pence, avg_pence, neg_hours, slots)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (tariff_code, direction, day_date) DO UPDATE SET
    high_pence = EXCLUDED.high_pence,
    low_pence = EXCLUDED.low_pence,
    avg_pence = EXCLUDED.avg_pence,
    neg_hours = EXCLUDED.neg_hours,
    slots = EXCLUDED.slots,
    fetched_at = EXCLUDED.fetched_at
"""
_UPSERT_MY = """
INSERT INTO agile_year_daily
    (fetched_at, tariff_code, direction, day_date,
     high_pence, low_pence, avg_pence, neg_hours, slots)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    high_pence = VALUES(high_pence),
    low_pence = VALUES(low_pence),
    avg_pence = VALUES(avg_pence),
    neg_hours = VALUES(neg_hours),
    slots = VALUES(slots),
    fetched_at = VALUES(fetched_at)
"""

# Sparse days (timezone spill, open-ended standing rates) are not real Agile days.
_DELETE_SPARSE_SQLITE = (
    "DELETE FROM agile_year_daily "
    "WHERE tariff_code = ? AND direction = ? AND slots < ?"
)
_DELETE_SPARSE_PG = (
    "DELETE FROM agile_year_daily "
    "WHERE tariff_code = %s AND direction = %s AND slots < %s"
)

_MIN_SLOTS = 40


def _day_iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip()
    return s[:10] if len(s) >= 10 else None


def _parse_day(value) -> date | None:
    iso = _day_iso(value)
    if not iso:
        return None
    try:
        return date.fromisoformat(iso)
    except ValueError:
        return None


def _sql_rows(rows, tariff_code, direction) -> list[tuple]:
    ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    out = []
    for rec in rows or ():
        day = _day_iso(rec.get("day"))
        if not day:
            continue
        try:
            slots = int(rec.get("slots") or 0)
        except (TypeError, ValueError):
            continue
        if slots < _MIN_SLOTS:
            continue
        try:
            high = float(rec["high"])
            low = float(rec["low"])
            avg = float(rec["avg"])
            neg = float(rec.get("neg_hours") or 0.0)
        except (TypeError, ValueError, KeyError):
            continue
        out.append((
            ts_now, tariff_code, direction, day,
            high, low, avg, neg, slots,
        ))
    return out


def _engine_ready(data_logger, name: str) -> bool:
    fn = getattr(data_logger, "backend_ready", None)
    if callable(fn):
        return bool(fn(name))
    return True


def write_agile_year_daily(data_logger, rows, tariff_code, direction) -> None:
    """Writer-thread upsert of daily Agile year stats. Does not CREATE on PostgreSQL."""
    tariff_code = (tariff_code or "").strip()
    direction = (direction or "import").strip() or "import"
    packed = _sql_rows(rows, tariff_code, direction)
    if not packed or data_logger is None:
        return
    sparse = (tariff_code, direction, _MIN_SLOTS)

    if getattr(data_logger, "sqlite_enabled", False):
        try:
            conn = data_logger._ensure_sqlite()
            conn.executemany(_UPSERT_SQLITE, packed)
            conn.execute(_DELETE_SPARSE_SQLITE, sparse)
            conn.commit()
        except Exception as e:
            data_logger._sqlite_conn = None
            data_logger._status(f"SQLite agile year error: {e}")
    if getattr(data_logger, "mysql_enabled", False) and _engine_ready(data_logger, "mysql"):
        try:
            conn = data_logger._ensure_mysql()
            with conn.cursor() as cur:
                cur.executemany(_UPSERT_MY, packed)
                cur.execute(_DELETE_SPARSE_PG, sparse)
        except Exception as e:
            data_logger._fail_mysql(e, f"MySQL agile year error: {e}")
    if getattr(data_logger, "pg_enabled", False) and _engine_ready(data_logger, "pg"):
        try:
            conn = data_logger._ensure_pg()
            with conn.cursor() as cur:
                cur.executemany(_UPSERT_PG, packed)
                cur.execute(_DELETE_SPARSE_PG, sparse)
        except Exception as e:
            data_logger._fail_pg(e, f"PostgreSQL agile year error: {e}")


def query_agile_year_daily(data_logger, tariff_code, direction="import") -> list[dict]:
    """Newest-first daily dicts (same shape as ``daily_agile_stats``)."""
    if data_logger is None:
        return []
    tariff_code = (tariff_code or "").strip()
    direction = (direction or "import").strip() or "import"
    if not tariff_code:
        return []
    backend = data_logger._primary_storage_backend()
    if backend is None:
        return []
    q = (
        "SELECT day_date, high_pence, low_pence, avg_pence, neg_hours, slots "
        "FROM agile_year_daily "
        "WHERE tariff_code = %s AND direction = %s "
        "ORDER BY day_date DESC"
    )
    try:
        df = data_logger._query_pl(backend, q, (tariff_code, direction))
    except Exception as e:
        data_logger._note_read_error(e, "agile year daily")
        return []
    if df is None or df.is_empty():
        return []
    out = []
    for row in df.iter_rows(named=True):
        day = _parse_day(row.get("day_date"))
        if day is None:
            continue
        try:
            slots = int(row.get("slots") or 0)
        except (TypeError, ValueError):
            continue
        if slots < _MIN_SLOTS:
            continue
        try:
            out.append({
                "day": day,
                "high": float(row["high_pence"]),
                "low": float(row["low_pence"]),
                "avg": float(row["avg_pence"]),
                "neg_hours": float(row.get("neg_hours") or 0.0),
                "slots": slots,
            })
        except (TypeError, ValueError, KeyError):
            continue
    return out


__all__ = [
    "_AGILE_YEAR_DAILY_DDL",
    "_AGILE_YEAR_DAILY_DDL_PG",
    "_AGILE_YEAR_DAILY_DDL_MY",
    "_AGILE_YEAR_DAILY_IDX",
    "_MIN_SLOTS",
    "query_agile_year_daily",
    "write_agile_year_daily",
]
