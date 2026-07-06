"""
Growatt MIX 5-minute chart slots (mix_detail / sph_energy_history).

Stored per device_sn + timestamp for Battery Analysis and background collection.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from energy_dashboard.deps import growattServer

_GROWATT_MIX_CHART_DDL = """
CREATE TABLE IF NOT EXISTS growatt_mix_chart (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_sn TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    pv_kw REAL,
    charge_kw REAL,
    discharge_kw REAL,
    grid_import_kw REAL,
    grid_export_kw REAL,
    load_kw REAL,
    UNIQUE(device_sn, timestamp)
)"""

_GROWATT_MIX_CHART_IDX = (
    "CREATE INDEX IF NOT EXISTS idx_growatt_mix_chart_ts "
    "ON growatt_mix_chart(timestamp)",
)

_GROWATT_MIX_CHART_DDL_PG = _GROWATT_MIX_CHART_DDL.replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY"
)
_GROWATT_MIX_CHART_DDL_MY = _GROWATT_MIX_CHART_DDL.replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT", "INTEGER PRIMARY KEY AUTO_INCREMENT"
)

_GROWATT_MIX_CHART_UPSERT = """
INSERT INTO growatt_mix_chart
    (device_sn, timestamp, pv_kw, charge_kw, discharge_kw,
     grid_import_kw, grid_export_kw, load_kw)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(device_sn, timestamp) DO UPDATE SET
    pv_kw = excluded.pv_kw,
    charge_kw = excluded.charge_kw,
    discharge_kw = excluded.discharge_kw,
    grid_import_kw = excluded.grid_import_kw,
    grid_export_kw = excluded.grid_export_kw,
    load_kw = excluded.load_kw
"""

_GROWATT_MIX_CHART_UPSERT_PG = _GROWATT_MIX_CHART_UPSERT.replace("?", "%s")
_GROWATT_MIX_CHART_UPSERT_MY = """
INSERT INTO growatt_mix_chart
    (device_sn, timestamp, pv_kw, charge_kw, discharge_kw,
     grid_import_kw, grid_export_kw, load_kw)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    pv_kw = VALUES(pv_kw),
    charge_kw = VALUES(charge_kw),
    discharge_kw = VALUES(discharge_kw),
    grid_import_kw = VALUES(grid_import_kw),
    grid_export_kw = VALUES(grid_export_kw),
    load_kw = VALUES(load_kw)
"""


def _fval(raw, default=0.0) -> float:
    if raw is None or str(raw).strip() in ("", "--"):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _slot_values(values: dict) -> dict:
    """Normalise one 5-minute chart slot to kW fields."""
    if not isinstance(values, dict):
        values = {}
    charge = _fval(values.get("pcharge") or values.get("pcharge1"))
    discharge = _fval(values.get("pdischarge") or values.get("pdischarge1"))
    grid_import = _fval(values.get("pacToUser") or values.get("pactouser"))
    grid_export = _fval(values.get("pacToGrid") or values.get("pactogrid"))
    pv = _fval(values.get("ppv"))
    load = _fval(values.get("sysOut") or values.get("pLocalLoad") or values.get("elocalLoad"))
    if load <= 0.001:
        load = max(0.0, grid_import - grid_export + pv + discharge - charge)
    return {
        "pv_kW": pv,
        "charge_kW": charge,
        "discharge_kW": discharge,
        "grid_import_kW": grid_import,
        "grid_export_kW": grid_export,
        "load_kW": load,
    }


def _v1_watts_to_kw(raw, default=0.0) -> float:
    """Open API V1 mix_data history reports instantaneous power in watts."""
    v = _fval(raw, default)
    if v <= 0.001:
        return 0.0
    return v / 1000.0


def parse_v1_history_record(rec: dict) -> dict | None:
    """Parse one Open API V1 ``mix_data`` history snapshot."""
    if not isinstance(rec, dict):
        return None
    ct = rec.get("createTime")
    if ct is None:
        return None
    try:
        ts = datetime.fromtimestamp(int(ct) / 1000.0)
    except (TypeError, ValueError, OSError):
        return None
    # Use *R (realtime) fields — *Total suffix is often a cumulative counter.
    charge = _v1_watts_to_kw(rec.get("pcharge1") or rec.get("acChargePower"))
    discharge = _v1_watts_to_kw(rec.get("pdischarge1"))
    grid_import = _v1_watts_to_kw(rec.get("pacToUserR") or rec.get("pacToUserTotal"))
    grid_export = _v1_watts_to_kw(rec.get("pacToGridR") or rec.get("pacToGridTotal"))
    pv = _v1_watts_to_kw(rec.get("ppv"))
    if pv <= 0.001:
        pv = _v1_watts_to_kw(rec.get("ppv1")) + _v1_watts_to_kw(rec.get("ppv2"))
    load = _v1_watts_to_kw(rec.get("plocalLoadR") or rec.get("plocalLoadTotal"))
    if load <= 0.001:
        load = max(0.0, grid_import - grid_export + pv + discharge - charge)
    return {
        "timestamp": ts,
        "pv_kW": pv,
        "charge_kW": charge,
        "discharge_kW": discharge,
        "grid_import_kW": grid_import,
        "grid_export_kW": grid_export,
        "load_kW": load,
    }


def parse_v1_history_payload(payload: Any, *, device_sn: str = "") -> list[dict]:
    """Parse Open API V1 ``sph_energy_history`` / ``mix_data`` response."""
    if not isinstance(payload, dict):
        return []
    datas = payload.get("datas")
    if not isinstance(datas, list):
        return []
    records: list[dict] = []
    for rec in datas:
        row = parse_v1_history_record(rec)
        if row is None:
            continue
        if device_sn:
            row["device_sn"] = device_sn
        records.append(row)
    return records


def fetch_v1_mix_history_for_date(api, device_sn: str, day: date | datetime) -> list[dict]:
    """Fetch paginated Open API V1 MIX history for one calendar day."""
    if isinstance(day, datetime):
        day = day.date()
    records: list[dict] = []
    page = 1
    limit = 50
    while page <= 100:
        raw = api.sph_energy_history(
            device_sn,
            start_date=day,
            end_date=day,
            page=page,
            limit=limit,
        )
        batch = parse_v1_history_payload(raw, device_sn=device_sn)
        if not batch:
            break
        records.extend(batch)
        if len(batch) < limit:
            break
        page += 1
    return records


def parse_mix_chart_day(payload: Any, date_str: str, *, device_sn: str = "") -> list[dict]:
    """Parse mix_detail / mix_data payload into chart rows for one calendar day."""
    v1_rows = parse_v1_history_payload(payload, device_sn=device_sn)
    if v1_rows:
        return v1_rows
    if not payload or not isinstance(payload, dict):
        return []
    chart_data = payload.get("chartData")
    if isinstance(chart_data, dict) and chart_data:
        records = []
        for time_str, values in chart_data.items():
            try:
                hour, minute = map(int, str(time_str).split(":")[:2])
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    hour=hour, minute=minute, second=0, microsecond=0,
                )
            except (ValueError, TypeError):
                continue
            row = _slot_values(values)
            row["timestamp"] = dt
            if device_sn:
                row["device_sn"] = device_sn
            records.append(row)
        return records

    charts = payload.get("charts")
    if isinstance(charts, dict) and charts:
        times = payload.get("time") or payload.get("times") or charts.get("time") or []
        if not times:
            lens = [len(v) for v in charts.values() if isinstance(v, (list, tuple))]
            n = max(lens) if lens else 0
            times = [f"{(i * 5) // 60:02d}:{(i * 5) % 60:02d}" for i in range(n)]
        records = []
        for i, time_str in enumerate(times):
            values = {
                "ppv": _series_at(charts, ("ppv",), i),
                "pcharge": _series_at(charts, ("pcharge", "pcharge1"), i),
                "pdischarge": _series_at(charts, ("pdischarge", "pdischarge1"), i),
                "pacToUser": _series_at(charts, ("pacToUser", "pacToUserR"), i),
                "pacToGrid": _series_at(charts, ("pacToGrid", "pacToGridTotal"), i),
                "sysOut": _series_at(charts, ("sysOut", "elocalLoad"), i),
            }
            try:
                hour, minute = map(int, str(time_str).split(":")[:2])
                dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    hour=hour, minute=minute, second=0, microsecond=0,
                )
            except (ValueError, TypeError):
                continue
            row = _slot_values(values)
            row["timestamp"] = dt
            if device_sn:
                row["device_sn"] = device_sn
            records.append(row)
        return records
    return []


def _series_at(charts: dict, keys: tuple[str, ...], index: int):
    for key in keys:
        arr = charts.get(key)
        if isinstance(arr, (list, tuple)) and index < len(arr):
            return arr[index]
    return 0


def fetch_mix_chart_for_date(api, device_sn: str, plant_id, day: date | datetime) -> list[dict]:
    """Fetch one day of 5-minute MIX chart data (legacy or Open API V1)."""
    if isinstance(day, datetime):
        day = day.date()
    date_str = day.strftime("%Y-%m-%d")
    from energy_dashboard.ui.cards import _growatt_uses_open_api_v1

    if _growatt_uses_open_api_v1(api):
        recs = fetch_v1_mix_history_for_date(api, device_sn, day)
        if recs:
            return recs
        return []

    try:
        raw = api.mix_detail(
            device_sn, plant_id, timespan=growattServer.Timespan.hour, date=day,
        )
        return parse_mix_chart_day(raw, date_str, device_sn=device_sn)
    except Exception:
        return []


def fetch_mix_chart_range(
    api, device_sn: str, plant_id, days: int, *, end_day: date | None = None,
) -> list[dict]:
    """Fetch ``days`` consecutive calendar days ending at ``end_day`` (default today)."""
    end = end_day or date.today()
    all_records: list[dict] = []
    for i in range(max(1, int(days))):
        day = end - timedelta(days=(days - 1 - i))
        all_records.extend(fetch_mix_chart_for_date(api, device_sn, plant_id, day))
    return all_records


def mix_chart_row_tuple(device_sn: str, rec: dict) -> tuple:
    ts = rec["timestamp"]
    if isinstance(ts, datetime):
        ts_s = ts.strftime("%Y-%m-%d %H:%M:%S")
    else:
        ts_s = str(ts)
    return (
        device_sn,
        ts_s,
        _fval(rec.get("pv_kW"), None),
        _fval(rec.get("charge_kW"), None),
        _fval(rec.get("discharge_kW"), None),
        _fval(rec.get("grid_import_kW"), None),
        _fval(rec.get("grid_export_kW"), None),
        _fval(rec.get("load_kW"), None),
    )


def upsert_mix_chart_rows(cur, dialect: str, device_sn: str, records: list[dict]) -> int:
    """Upsert chart rows; returns number of rows written."""
    if not records:
        return 0
    sql = {
        "sqlite": _GROWATT_MIX_CHART_UPSERT,
        "pg": _GROWATT_MIX_CHART_UPSERT_PG,
        "mysql": _GROWATT_MIX_CHART_UPSERT_MY,
    }.get(dialect, _GROWATT_MIX_CHART_UPSERT_PG)
    rows = [mix_chart_row_tuple(device_sn, r) for r in records]
    cur.executemany(sql, rows)
    return len(rows)


__all__ = [n for n in globals() if not n.startswith("__")]
