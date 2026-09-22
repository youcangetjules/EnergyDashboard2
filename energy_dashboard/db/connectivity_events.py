"""Connectivity Status — alarms / faults / enable history.

Persisted so right-click → Show history on a State cell has something to show
beyond the in-memory AlarmMonitor buffer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_CONNECTIVITY_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS connectivity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    service_key TEXT NOT NULL,
    service_label TEXT,
    event_type TEXT NOT NULL,
    state_key TEXT,
    state_text TEXT,
    detail TEXT
)"""

_CONNECTIVITY_EVENTS_DDL_PG = _CONNECTIVITY_EVENTS_DDL.replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY"
)
_CONNECTIVITY_EVENTS_DDL_MY = _CONNECTIVITY_EVENTS_DDL.replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT", "INTEGER PRIMARY KEY AUTO_INCREMENT"
)

_CONNECTIVITY_EVENTS_IDX = (
    "CREATE INDEX IF NOT EXISTS idx_connectivity_events_service_ts "
    "ON connectivity_events (service_key, timestamp)",
)

_INSERT = """
INSERT INTO connectivity_events
    (timestamp, service_key, service_label, event_type, state_key, state_text, detail)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""
_INSERT_PG = _INSERT.replace("?", "%s")


def ensure_connectivity_events(conn, *, dialect: str = "sqlite") -> None:
    """CREATE TABLE / INDEX on an open connection."""
    if dialect == "pg":
        with conn.cursor() as cur:
            cur.execute(_CONNECTIVITY_EVENTS_DDL_PG)
            for stmt in _CONNECTIVITY_EVENTS_IDX:
                cur.execute(stmt)
        return
    if dialect == "mysql":
        with conn.cursor() as cur:
            cur.execute(_CONNECTIVITY_EVENTS_DDL_MY)
            for stmt in _CONNECTIVITY_EVENTS_IDX:
                try:
                    cur.execute(stmt)
                except Exception:
                    pass
        return
    conn.execute(_CONNECTIVITY_EVENTS_DDL)
    for stmt in _CONNECTIVITY_EVENTS_IDX:
        conn.execute(stmt)
    conn.commit()


def log_connectivity_event(
    data_logger,
    *,
    service_key: str,
    service_label: str,
    event_type: str,
    state_key: str = "",
    state_text: str = "",
    detail: str = "",
    when: datetime | None = None,
) -> None:
    """Append one event to every enabled backend (best-effort)."""
    if data_logger is None:
        return
    ts = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
    row = (
        ts,
        str(service_key or "")[:80],
        str(service_label or "")[:120],
        str(event_type or "info")[:40],
        str(state_key or "")[:40],
        str(state_text or "")[:120],
        str(detail or "")[:2000],
    )
    put = getattr(data_logger, "enqueue_connectivity_event", None)
    if callable(put):
        put(row)
        return
    write_connectivity_event(data_logger, row)


def _engine_ready(data_logger, name: str) -> bool:
    fn = getattr(data_logger, "backend_ready", None)
    if callable(fn):
        return bool(fn(name))
    return True


def write_connectivity_event(data_logger, row) -> None:
    """Writer-thread insert; skips engines in reconnect backoff."""
    try:
        if getattr(data_logger, "sqlite_enabled", False):
            conn = data_logger._ensure_sqlite()
            ensure_connectivity_events(conn, dialect="sqlite")
            conn.execute(_INSERT, row)
            conn.commit()
    except Exception:
        pass
    try:
        if getattr(data_logger, "mysql_enabled", False) and _engine_ready(data_logger, "mysql"):
            conn = data_logger._ensure_mysql()
            ensure_connectivity_events(conn, dialect="mysql")
            with conn.cursor() as cur:
                cur.execute(_INSERT_PG, row)
    except Exception:
        pass
    try:
        if getattr(data_logger, "pg_enabled", False) and _engine_ready(data_logger, "pg"):
            conn = data_logger._ensure_pg()
            with conn.cursor() as cur:
                cur.execute(_INSERT_PG, row)
    except Exception:
        pass


def query_connectivity_events(
    data_logger,
    service_key: str,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Newest-first events for one service key (first enabled backend wins)."""
    if data_logger is None or not service_key:
        return []
    limit = max(1, min(int(limit), 1000))
    sql = (
        "SELECT timestamp, event_type, state_key, state_text, detail, service_label "
        "FROM connectivity_events WHERE service_key = ? "
        "ORDER BY timestamp DESC, id DESC LIMIT ?"
    )
    sql_pg = sql.replace("?", "%s")

    def _rows(fetchall) -> list[dict[str, Any]]:
        out = []
        for r in fetchall or ():
            out.append({
                "timestamp": r[0],
                "event_type": r[1],
                "state_key": r[2],
                "state_text": r[3],
                "detail": r[4],
                "service_label": r[5] if len(r) > 5 else "",
            })
        return out

    try:
        if getattr(data_logger, "sqlite_enabled", False):
            conn = data_logger._ensure_sqlite()
            ensure_connectivity_events(conn, dialect="sqlite")
            cur = conn.execute(sql, (service_key, limit))
            return _rows(cur.fetchall())
    except Exception:
        pass
    try:
        if getattr(data_logger, "pg_enabled", False) and _engine_ready(data_logger, "pg"):
            conn = data_logger._ensure_pg()
            with conn.cursor() as cur:
                cur.execute(sql_pg, (service_key, limit))
                return _rows(cur.fetchall())
    except Exception:
        pass
    try:
        if getattr(data_logger, "mysql_enabled", False) and _engine_ready(data_logger, "mysql"):
            conn = data_logger._ensure_mysql()
            ensure_connectivity_events(conn, dialect="mysql")
            with conn.cursor() as cur:
                cur.execute(sql_pg, (service_key, limit))
                return _rows(cur.fetchall())
    except Exception:
        pass
    return []


__all__ = [
    "ensure_connectivity_events",
    "log_connectivity_event",
    "write_connectivity_event",
    "query_connectivity_events",
    "_CONNECTIVITY_EVENTS_DDL",
    "_CONNECTIVITY_EVENTS_DDL_PG",
    "_CONNECTIVITY_EVENTS_DDL_MY",
]
