"""
Database health, activity, and growth statistics for the Database Viewer.
"""
from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from energy_dashboard.db.connect_probe import (
    format_probe_summary,
    mysql_connect,
    postgresql_connect,
    probe_mysql,
    probe_postgresql,
    probe_sqlite,
)

KNOWN_TABLES = (
    ("growatt_readings", "timestamp"),
    ("growatt_mix_chart", "timestamp"),
    ("tasmota_readings", "timestamp"),
    ("tasmota_devices", "last_seen"),
    ("octopus_readings", "logged_at"),
    ("solar_forecast_snapshots", "fetched_at"),
    ("agile_price_snapshots", "fetched_at"),
    ("agile_year_daily", "fetched_at"),
    ("connectivity_events", "timestamp"),
    ("pv_string_charge", "timestamp"),
)

GROWTH_TABLES = (
    ("growatt_readings", "timestamp"),
    ("growatt_mix_chart", "timestamp"),
    ("tasmota_readings", "timestamp"),
    ("octopus_readings", "logged_at"),
    ("solar_forecast_snapshots", "fetched_at"),
    ("agile_price_snapshots", "fetched_at"),
    ("agile_year_daily", "fetched_at"),
    ("pv_string_charge", "timestamp"),
)


def _fmt_size(nbytes: int | float | None) -> str:
    if nbytes is None:
        return "—"
    n = float(nbytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


def _parse_ts(raw) -> datetime | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if len(s) >= 19:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    if len(s) >= 10:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso_week_label(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _last_n_days(n: int) -> list[str]:
    today = date.today()
    return [(today - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def _last_n_weeks(n: int) -> list[str]:
    today = date.today()
    seen = []
    for i in range(n * 7):
        lbl = _iso_week_label(today - timedelta(days=i))
        if lbl not in seen:
            seen.append(lbl)
        if len(seen) >= n:
            break
    return list(reversed(seen))


@contextmanager
def _open_db(backend: str, cap: dict):
    backend = backend or "SQLite"
    if backend == "SQLite":
        path = cap.get("sqlite_path") or str(Path.home() / "energy_dashboard.db")
        conn = sqlite3.connect(path)
        try:
            yield conn, "sqlite", path
        finally:
            conn.close()
    elif backend == "MySQL":
        conn = mysql_connect(
            cap.get("mysql_host") or "localhost",
            cap.get("mysql_port") or 3306,
            cap.get("mysql_user") or "",
            cap.get("mysql_pass") or "",
            cap.get("mysql_db") or "energy",
        )
        try:
            yield conn, "mysql", None
        finally:
            conn.close()
    else:
        conn = postgresql_connect(
            cap.get("pg_host") or "localhost",
            cap.get("pg_port") or 5432,
            cap.get("pg_user") or "",
            cap.get("pg_pass") or "",
            cap.get("pg_db") or "powermon",
        )
        try:
            yield conn, "pg", None
        finally:
            conn.close()


def _table_exists(cur, dialect: str, table: str) -> bool:
    if dialect == "sqlite":
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        )
    elif dialect == "mysql":
        cur.execute("SHOW TABLES LIKE %s", (table,))
    else:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
    return cur.fetchone() is not None


def _fetch_scalar(cur, sql, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def _db_size(cur, dialect: str, sqlite_path: str | None) -> str:
    if dialect == "sqlite" and sqlite_path:
        p = Path(sqlite_path)
        return _fmt_size(p.stat().st_size) if p.exists() else "file missing"
    if dialect == "mysql":
        n = _fetch_scalar(
            cur,
            "SELECT SUM(data_length + index_length) FROM information_schema.tables "
            "WHERE table_schema = DATABASE()",
        )
        return _fmt_size(n)
    n = _fetch_scalar(cur, "SELECT pg_database_size(current_database())")
    return _fmt_size(n)


def _relation_size_bytes(cur, dialect: str, table: str) -> int | None:
    """Best-effort on-disk size for a table (PG / MySQL / SQLite dbstat)."""
    if dialect == "pg":
        try:
            n = _fetch_scalar(
                cur,
                "SELECT pg_total_relation_size(%s::regclass)",
                (table,),
            )
            return int(n) if n is not None else None
        except Exception:
            return None
    if dialect == "mysql":
        try:
            n = _fetch_scalar(
                cur,
                "SELECT data_length + index_length FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = %s",
                (table,),
            )
            return int(n) if n is not None else None
        except Exception:
            return None
    if dialect == "sqlite":
        try:
            n = _fetch_scalar(
                cur,
                "SELECT SUM(pgsize) FROM dbstat WHERE name = ?",
                (table,),
            )
            return int(n) if n is not None else None
        except Exception:
            return None
    return None


def _daily_counts(cur, dialect: str, table: str, ts_col: str, days: int) -> dict[str, int]:
    if dialect == "sqlite":
        sql = (
            f"SELECT SUBSTR({ts_col}, 1, 10) AS d, COUNT(*) FROM {table} "
            f"WHERE SUBSTR({ts_col}, 1, 10) >= date('now', ?) "
            f"GROUP BY d"
        )
        params = (f"-{days - 1} days",)
    elif dialect == "mysql":
        sql = (
            f"SELECT LEFT({ts_col}, 10) AS d, COUNT(*) FROM {table} "
            f"WHERE LEFT({ts_col}, 10) >= DATE_SUB(CURDATE(), INTERVAL %s DAY) "
            f"GROUP BY d"
        )
        params = (days - 1,)
    else:
        sql = (
            f"SELECT LEFT({ts_col}, 10) AS d, COUNT(*) FROM {table} "
            f"WHERE LEFT({ts_col}, 10)::date >= CURRENT_DATE - %s "
            f"GROUP BY d"
        )
        params = (days - 1,)
    cur.execute(sql, params)
    return {str(d): int(n) for d, n in cur.fetchall() if d}


def _weekly_counts(cur, dialect: str, table: str, ts_col: str, weeks: int) -> dict[str, int]:
    lookback_days = weeks * 7
    if dialect == "sqlite":
        sql = (
            f"SELECT strftime('%Y-W%W', {ts_col}) AS w, COUNT(*) FROM {table} "
            f"WHERE {ts_col} >= date('now', ?) GROUP BY w"
        )
        params = (f"-{lookback_days} days",)
    elif dialect == "mysql":
        sql = (
            f"SELECT CONCAT(YEAR({ts_col}), '-W', LPAD(WEEK({ts_col}, 3), 2, '0')) AS w, "
            f"COUNT(*) FROM {table} "
            f"WHERE {ts_col} >= DATE_SUB(CURDATE(), INTERVAL %s DAY) GROUP BY w"
        )
        params = (lookback_days,)
    else:
        sql = (
            f"SELECT TO_CHAR({ts_col}::timestamp, 'IYYY-\"W\"IW') AS w, COUNT(*) FROM {table} "
            f"WHERE {ts_col}::timestamp >= CURRENT_DATE - %s GROUP BY w"
        )
        params = (lookback_days,)
    cur.execute(sql, params)
    return {str(w): int(n) for w, n in cur.fetchall() if w}


def _probe_backend(backend: str, cap: dict) -> tuple[bool, dict | str]:
    if backend == "SQLite":
        return probe_sqlite(cap.get("sqlite_path") or "")
    if backend == "MySQL":
        return probe_mysql(
            cap.get("mysql_host"),
            cap.get("mysql_port"),
            cap.get("mysql_user"),
            cap.get("mysql_pass"),
            cap.get("mysql_db"),
        )
    return probe_postgresql(
        cap.get("pg_host"),
        cap.get("pg_port"),
        cap.get("pg_user"),
        cap.get("pg_pass"),
        cap.get("pg_db"),
    )


def collect_health_stats(backend: str, cap: dict) -> dict:
    """Gather connection health, table activity, and growth metrics."""
    out = {
        "backend": backend,
        "ok": False,
        "error": None,
        "probe_ok": False,
        "probe_detail": None,
        "probe_summary": "",
        "db_size": "—",
        "tables": {},
        "last_activity_overall": None,
        "daily_growth": [],
        "weekly_growth": [],
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    probe_ok, probe_detail = _probe_backend(backend, cap)
    out["probe_ok"] = probe_ok
    out["probe_detail"] = probe_detail
    if probe_ok and isinstance(probe_detail, dict):
        out["probe_summary"] = format_probe_summary(probe_detail)
    elif probe_ok:
        out["probe_summary"] = str(probe_detail)
    else:
        out["error"] = str(probe_detail)
        return out

    try:
        with _open_db(backend, cap) as (conn, dialect, sqlite_path):
            if dialect == "sqlite":
                cur = conn.cursor()
            else:
                cur = conn.cursor()

            out["db_size"] = _db_size(cur, dialect, sqlite_path)

            latest_ts: datetime | None = None
            for table, ts_col in KNOWN_TABLES:
                info = {
                    "exists": False,
                    "row_count": 0,
                    "last_activity": None,
                    "size_bytes": None,
                    "size_human": None,
                }
                if _table_exists(cur, dialect, table):
                    info["exists"] = True
                    try:
                        info["row_count"] = int(
                            _fetch_scalar(cur, f"SELECT COUNT(*) FROM {table}") or 0
                        )
                        raw_last = _fetch_scalar(
                            cur, f"SELECT MAX({ts_col}) FROM {table}"
                        )
                        info["last_activity"] = str(raw_last) if raw_last else None
                        parsed = _parse_ts(raw_last)
                        if parsed and (latest_ts is None or parsed > latest_ts):
                            latest_ts = parsed
                        sz = _relation_size_bytes(cur, dialect, table)
                        if sz is not None:
                            info["size_bytes"] = int(sz)
                            info["size_human"] = _fmt_size(sz)
                    except Exception as exc:
                        info["error"] = str(exc)
                out["tables"][table] = info

            if latest_ts:
                out["last_activity_overall"] = latest_ts.strftime("%Y-%m-%d %H:%M:%S UTC")

            daily_by_table: dict[str, dict[str, int]] = {}
            weekly_by_table: dict[str, dict[str, int]] = {}
            for table, ts_col in GROWTH_TABLES:
                if not out["tables"].get(table, {}).get("exists"):
                    continue
                try:
                    daily_by_table[table] = _daily_counts(cur, dialect, table, ts_col, 7)
                    weekly_by_table[table] = _weekly_counts(
                        cur, dialect, table, ts_col, 4
                    )
                except Exception:
                    daily_by_table[table] = {}
                    weekly_by_table[table] = {}

            day_labels = _last_n_days(7)
            for d in day_labels:
                per = {t: daily_by_table.get(t, {}).get(d, 0) for t, _ in GROWTH_TABLES}
                out["daily_growth"].append(
                    {"date": d, "per_table": per, "total": sum(per.values())}
                )

            week_labels = _last_n_weeks(4)
            for w in week_labels:
                per = {t: weekly_by_table.get(t, {}).get(w, 0) for t, _ in GROWTH_TABLES}
                out["weekly_growth"].append(
                    {"week": w, "per_table": per, "total": sum(per.values())}
                )

            out["ok"] = True
    except ImportError as e:
        out["error"] = str(e)
    except Exception as e:
        out["error"] = str(e)

    return out
