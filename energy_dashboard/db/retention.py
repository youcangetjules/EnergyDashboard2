"""
Per-table / per-store ring-buffer retention policies (rows, age, size).

Policies are stored in QSettings and applied by prune_* helpers after writes
or on demand from Connectivity → Databases / Exported data.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from energy_dashboard.db.health_stats import (
    _fetch_scalar,
    _fmt_size,
    _open_db,
    _relation_size_bytes,
    _table_exists,
)

_SETTINGS_ORG = "PowerModel"
_SETTINGS_APP = "EnergyDashboard2"
_PREFIX = "retention/"


@dataclass(frozen=True)
class RetentionTarget:
    key: str
    label: str
    ts_column: str | None
    show_in_database: bool = True
    show_in_export: bool = False
    note: str = ""


# Telemetry + forecast tables logged by DataLogger / energy_collector.
RETENTION_TARGETS: tuple[RetentionTarget, ...] = (
    RetentionTarget("growatt_readings", "Growatt readings", "timestamp"),
    RetentionTarget(
        "growatt_mix_chart",
        "Growatt MIX chart (5 min)",
        "timestamp",
        note="5-minute power slots from mix_detail / Battery Analysis.",
    ),
    RetentionTarget("tasmota_readings", "Tasmota readings", "timestamp"),
    RetentionTarget(
        "tasmota_devices",
        "Tasmota devices",
        "last_seen",
        note="One row per device IP; age/row limits drop stale devices.",
    ),
    RetentionTarget("octopus_readings", "Octopus half-hour readings", "logged_at"),
    RetentionTarget(
        "solar_forecast_snapshots",
        "Solar forecast snapshots",
        "fetched_at",
        show_in_export=True,
        note="Append-only planned curves for planned-vs-actual charts.",
    ),
    RetentionTarget(
        "agile_price_snapshots",
        "Agile price snapshots",
        "fetched_at",
        show_in_export=True,
        note="Upserted by tariff slot; row count tracks unique price slots.",
    ),
    RetentionTarget(
        "agile_year_daily",
        "Agile Year daily stats",
        "day_date",
        show_in_export=True,
        note="One row per London day per tariff; keep long — since-start trend uses this.",
    ),
    RetentionTarget(
        "pv_string_charge",
        "PV string charge estimates",
        "timestamp",
        note="2-minute lots of per-string PV and attributed charge; chart shows last 6 hours.",
    ),
    RetentionTarget(
        "pv_string_voltage",
        "PV string voltage",
        "time",
        note="2-minute lots of measured DC volts on each MPPT string (vPv1 / vPv2).",
    ),
    RetentionTarget(
        "console_log",
        "Console log file",
        None,
        show_in_database=False,
        show_in_export=True,
        note=f"JSONL at {Path.home() / '.energy_dashboard_console.jsonl'}",
    ),
)


@dataclass
class RetentionPolicy:
    enabled: bool = False
    max_rows: int = 0  # 0 = unlimited
    max_age_days: int = 0  # 0 = unlimited
    max_size_mb: float = 0.0  # 0 = unlimited (best-effort per table)

    def summary(self) -> str:
        if not self.enabled:
            return "ring buffer off"
        parts = []
        if self.max_rows > 0:
            parts.append(f"≤{self.max_rows:,} rows")
        if self.max_age_days > 0:
            parts.append(f"≤{self.max_age_days} days")
        if self.max_size_mb > 0:
            parts.append(f"≤{self.max_size_mb:.0f} MB")
        return ", ".join(parts) if parts else "enabled (no limits set)"


def _settings():
    from PySide6.QtCore import QSettings

    return QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def load_policy(key: str) -> RetentionPolicy:
    s = _settings()
    base = f"{_PREFIX}{key}/"
    return RetentionPolicy(
        enabled=s.value(base + "enabled", False, type=bool),
        max_rows=int(s.value(base + "max_rows", 0) or 0),
        max_age_days=int(s.value(base + "max_age_days", 0) or 0),
        max_size_mb=float(s.value(base + "max_size_mb", 0) or 0),
    )


def save_policy(key: str, policy: RetentionPolicy) -> None:
    s = _settings()
    base = f"{_PREFIX}{key}/"
    s.setValue(base + "enabled", policy.enabled)
    s.setValue(base + "max_rows", policy.max_rows)
    s.setValue(base + "max_age_days", policy.max_age_days)
    s.setValue(base + "max_size_mb", policy.max_size_mb)
    s.sync()


def targets_for_box(box_key: str) -> list[RetentionTarget]:
    if box_key in ("database", "storage"):
        return [t for t in RETENTION_TARGETS if t.show_in_database]
    if box_key == "export":
        return [t for t in RETENTION_TARGETS if t.show_in_export]
    return []


def _cutoff_ts(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _delete_sql(dialect: str, table: str, ts_col: str, *, before_ts: str | None, excess_rows: int) -> tuple[str, tuple]:
    params: list[Any] = []
    clauses = []
    if before_ts:
        if dialect == "sqlite":
            clauses.append(f"{ts_col} < ?")
        else:
            clauses.append(f"{ts_col} < %s")
        params.append(before_ts)
    if excess_rows > 0:
        if dialect == "sqlite":
            sub = (
                f"SELECT id FROM {table} ORDER BY {ts_col} ASC, id ASC "
                f"LIMIT ?"
            )
            clauses.append(f"id IN ({sub})")
            params.append(excess_rows)
        else:
            sub = (
                f"SELECT id FROM {table} ORDER BY {ts_col} ASC, id ASC "
                f"LIMIT %s"
            )
            clauses.append(f"id IN ({sub})")
            params.append(excess_rows)
    if not clauses:
        return "", ()
    where = " OR ".join(f"({c})" for c in clauses) if len(clauses) > 1 else clauses[0]
    sql = f"DELETE FROM {table} WHERE {where}"
    return sql, tuple(params)


def prune_table(
    conn,
    dialect: str,
    table: str,
    ts_col: str,
    policy: RetentionPolicy,
    *,
    sqlite_path: str | None = None,
) -> int:
    """Delete oldest rows until policy limits are met. Returns rows removed."""
    if not policy.enabled:
        return 0
    if not _table_exists(conn.cursor(), dialect, table):
        return 0
    cur = conn.cursor()
    deleted = 0
    max_bytes = int(policy.max_size_mb * 1024 * 1024) if policy.max_size_mb > 0 else 0

    for _ in range(24):
        removed = 0
        if policy.max_age_days > 0:
            sql, params = _delete_sql(
                dialect, table, ts_col, before_ts=_cutoff_ts(policy.max_age_days), excess_rows=0
            )
            if sql:
                cur.execute(sql, params)
                removed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

        if policy.max_rows > 0:
            count = int(_fetch_scalar(cur, f"SELECT COUNT(*) FROM {table}") or 0)
            excess = count - policy.max_rows
            if excess > 0:
                batch = min(excess, 5000)
                sql, params = _delete_sql(
                    dialect, table, ts_col, before_ts=None, excess_rows=batch
                )
                cur.execute(sql, params)
                removed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

        if max_bytes > 0:
            sz = _relation_size_bytes(cur, dialect, table)
            if sz is not None and sz > max_bytes:
                sql, params = _delete_sql(
                    dialect, table, ts_col, before_ts=None, excess_rows=2000
                )
                cur.execute(sql, params)
                removed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

        if dialect == "sqlite":
            conn.commit()
        deleted += removed
        if removed == 0:
            break
    return deleted


def prune_console_log(policy: RetentionPolicy) -> int:
    """Trim ~/.energy_dashboard_console.jsonl by age, line count, and file size."""
    if not policy.enabled:
        return 0
    path = Path.home() / ".energy_dashboard_console.jsonl"
    if not path.is_file():
        return 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    if not lines:
        return 0
    start_n = len(lines)
    cutoff = None
    if policy.max_age_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=policy.max_age_days)

    kept: list[str] = []
    for ln in lines:
        if not ln.strip():
            continue
        if cutoff is not None:
            try:
                obj = json.loads(ln)
                iso = obj.get("iso_ts") or ""
                if iso:
                    dt = datetime.fromisoformat(iso)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
            except (json.JSONDecodeError, ValueError):
                pass
        kept.append(ln)

    if policy.max_rows > 0 and len(kept) > policy.max_rows:
        kept = kept[-policy.max_rows :]

    max_bytes = int(policy.max_size_mb * 1024 * 1024) if policy.max_size_mb > 0 else 0
    while max_bytes > 0 and kept:
        payload = "\n".join(kept) + "\n"
        if len(payload.encode("utf-8")) <= max_bytes:
            break
        kept = kept[max(1, len(kept) // 10) :]

    if len(kept) == start_n:
        return 0
    try:
        path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    except OSError:
        return 0
    return start_n - len(kept)


def _logger_cap_dict(logger) -> dict:
    return {
        "sqlite_path": getattr(logger, "sqlite_path", "") or "",
        "mysql_host": getattr(logger, "mysql_host", "localhost"),
        "mysql_port": getattr(logger, "mysql_port", 3306),
        "mysql_user": getattr(logger, "mysql_user", ""),
        "mysql_pass": getattr(logger, "mysql_pass", ""),
        "mysql_db": getattr(logger, "mysql_db", "energy"),
        "pg_host": getattr(logger, "pg_host", "localhost"),
        "pg_port": getattr(logger, "pg_port", 5432),
        "pg_user": getattr(logger, "pg_user", ""),
        "pg_pass": getattr(logger, "pg_pass", ""),
        "pg_db": getattr(logger, "pg_db", "powermon"),
    }


def _enabled_backends(logger) -> list[str]:
    out = []
    if getattr(logger, "sqlite_enabled", False):
        out.append("SQLite")
    if getattr(logger, "mysql_enabled", False):
        out.append("MySQL")
    if getattr(logger, "pg_enabled", False):
        out.append("PostgreSQL")
    return out


def prune_all_for_logger(logger, *, table_keys: list[str] | None = None) -> dict[str, int]:
    """Run retention on every enabled target for backends the logger has enabled."""
    results: dict[str, int] = {}
    keys = table_keys or [t.key for t in RETENTION_TARGETS]
    cap = _logger_cap_dict(logger)

    for target in RETENTION_TARGETS:
        if target.key not in keys:
            continue
        policy = load_policy(target.key)
        if not policy.enabled:
            continue
        if target.key == "console_log":
            n = prune_console_log(policy)
            if n:
                results[target.key] = n
            continue
        if not target.ts_column:
            continue
        for backend in _enabled_backends(logger):
            try:
                with _open_db(backend, cap) as (conn, dialect, sqlite_path):
                    n = prune_table(
                        conn,
                        dialect,
                        target.key,
                        target.ts_column,
                        policy,
                        sqlite_path=sqlite_path,
                    )
                    if n:
                        results[f"{target.key}:{backend}"] = n
            except Exception:
                continue
    return results


def format_policy_block(target: RetentionTarget, stats: dict | None) -> str:
    pol = load_policy(target.key)
    lines = [f"{target.label} [{target.key}]", f"  Ring buffer: {pol.summary()}"]
    if target.note:
        lines.append(f"  Note: {target.note}")
    if stats:
        if stats.get("row_count") is not None:
            lines.append(f"  Rows: {stats['row_count']:,}")
        if stats.get("last_activity"):
            lines.append(f"  Last activity: {stats['last_activity']}")
        if stats.get("size_human"):
            lines.append(f"  Approx. size: {stats['size_human']}")
    return "\n".join(lines)
