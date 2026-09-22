"""
Energy Dashboard — `db/logger.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.db.connect_probe import (
    format_probe_summary,
    format_probe_tooltip,
    probe_mysql,
    probe_postgresql,
    probe_sqlite,
)
from energy_dashboard.config import *
from energy_dashboard.db.mix_chart import (
    upsert_mix_chart_rows,
)
from energy_dashboard.db.shadow_trial import (
    upsert_shadow_plan,
    upsert_shadow_score,
)
_GROWATT_DDL = """
CREATE TABLE IF NOT EXISTS growatt_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    soc_pct REAL,
    battery_power_kw REAL,
    pv_power_kw REAL,
    grid_power_kw REAL,
    load_power_kw REAL,
    charge_today_kwh REAL,
    discharge_today_kwh REAL,
    pv_today_kwh REAL
)"""

_TASMOTA_DDL = """
CREATE TABLE IF NOT EXISTS tasmota_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    device_ip TEXT,
    device_name TEXT,
    power_w REAL,
    voltage_v REAL,
    current_a REAL,
    today_kwh REAL,
    total_kwh REAL
)"""

_TASMOTA_DEVICES_DDL = """
CREATE TABLE IF NOT EXISTS tasmota_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_ip TEXT NOT NULL UNIQUE,
    device_name TEXT,
    relay_on INTEGER,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
)"""

_GROWATT_DDL_PG = _GROWATT_DDL.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                                        "SERIAL PRIMARY KEY")
_TASMOTA_DDL_PG = _TASMOTA_DDL.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                                        "SERIAL PRIMARY KEY")
_TASMOTA_DEVICES_DDL_PG = _TASMOTA_DEVICES_DDL.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                                                       "SERIAL PRIMARY KEY")
_GROWATT_DDL_MY = _GROWATT_DDL.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                                       "INTEGER PRIMARY KEY AUTO_INCREMENT")
_TASMOTA_DDL_MY = _TASMOTA_DDL.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                                       "INTEGER PRIMARY KEY AUTO_INCREMENT")
_TASMOTA_DEVICES_DDL_MY = _TASMOTA_DEVICES_DDL.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                                                     "INTEGER PRIMARY KEY AUTO_INCREMENT")

_GROWATT_INSERT = """
INSERT INTO growatt_readings
    (timestamp, soc_pct, battery_power_kw, pv_power_kw, grid_power_kw,
     load_power_kw, charge_today_kwh, discharge_today_kwh, pv_today_kwh)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""

_TASMOTA_INSERT = """
INSERT INTO tasmota_readings
    (timestamp, device_ip, device_name, power_w, voltage_v, current_a,
     today_kwh, total_kwh)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""

_GROWATT_INSERT_PG = _GROWATT_INSERT.replace("?", "%s")
_TASMOTA_INSERT_PG = _TASMOTA_INSERT.replace("?", "%s")
_GROWATT_INSERT_MY = _GROWATT_INSERT_PG
_TASMOTA_INSERT_MY = _TASMOTA_INSERT_PG

_TASMOTA_DEVICE_UPSERT_SQLITE = """
INSERT INTO tasmota_devices (device_ip, device_name, relay_on, first_seen, last_seen)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(device_ip) DO UPDATE SET
    device_name = excluded.device_name,
    relay_on = excluded.relay_on,
    last_seen = excluded.last_seen
"""

_TASMOTA_DEVICE_UPSERT_MY = """
INSERT INTO tasmota_devices (device_ip, device_name, relay_on, first_seen, last_seen)
VALUES (%s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    device_name = VALUES(device_name),
    relay_on = VALUES(relay_on),
    last_seen = VALUES(last_seen)
"""

_TASMOTA_DEVICE_UPSERT_PG = """
INSERT INTO tasmota_devices (device_ip, device_name, relay_on, first_seen, last_seen)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (device_ip) DO UPDATE SET
    device_name = EXCLUDED.device_name,
    relay_on = EXCLUDED.relay_on,
    last_seen = EXCLUDED.last_seen
"""

_OCTOPUS_DDL = """
CREATE TABLE IF NOT EXISTS octopus_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interval_start TEXT NOT NULL UNIQUE,
    import_kwh REAL,
    export_kwh REAL,
    logged_at TEXT NOT NULL
)"""

_OCTOPUS_DDL_PG = _OCTOPUS_DDL.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                                       "SERIAL PRIMARY KEY")
_OCTOPUS_DDL_MY = _OCTOPUS_DDL.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                                       "INTEGER PRIMARY KEY AUTO_INCREMENT")

_OCTOPUS_UPSERT_SQLITE = """
INSERT INTO octopus_readings (interval_start, import_kwh, export_kwh, logged_at)
VALUES (?, ?, ?, ?)
ON CONFLICT(interval_start) DO UPDATE SET
    import_kwh = excluded.import_kwh,
    export_kwh = excluded.export_kwh,
    logged_at = excluded.logged_at
"""

_OCTOPUS_UPSERT_MY = """
INSERT INTO octopus_readings (interval_start, import_kwh, export_kwh, logged_at)
VALUES (%s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    import_kwh = VALUES(import_kwh),
    export_kwh = VALUES(export_kwh),
    logged_at = VALUES(logged_at)
"""

_OCTOPUS_UPSERT_PG = """
INSERT INTO octopus_readings (interval_start, import_kwh, export_kwh, logged_at)
VALUES (%s, %s, %s, %s)
ON CONFLICT (interval_start) DO UPDATE SET
    import_kwh = EXCLUDED.import_kwh,
    export_kwh = EXCLUDED.export_kwh,
    logged_at = EXCLUDED.logged_at
"""


# ── Forecast snapshots ───────────────────────────────────────────────────
# Solar forecast snapshots: every fetch is appended (no UPSERT) because the
# whole point is to retain "what we *thought* yesterday's solar would be" so
# we can later compare planned vs actual. Indexed on (interval_start) so the
# "show me yesterday's planned curve" query is O(log n).
_SOLAR_FC_DDL = """
CREATE TABLE IF NOT EXISTS solar_forecast_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    tilt REAL,
    azimuth REAL,
    kwp REAL,
    interval_start TEXT NOT NULL,
    kw REAL NOT NULL
)"""
_SOLAR_FC_IDX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_solar_fc_interval "
    "ON solar_forecast_snapshots(interval_start)",
    "CREATE INDEX IF NOT EXISTS idx_solar_fc_fetched "
    "ON solar_forecast_snapshots(fetched_at)",
)

# Agile price snapshots: prices are immutable once published, so we use an
# upsert keyed on (tariff_code, direction, valid_from). One row per slot per
# tariff regardless of how often we re-fetch.
_AGILE_FC_DDL = """
CREATE TABLE IF NOT EXISTS agile_price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT NOT NULL,
    tariff_code TEXT NOT NULL,
    direction TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT NOT NULL,
    price_pence REAL,
    UNIQUE(tariff_code, direction, valid_from)
)"""
_AGILE_FC_IDX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_agile_fc_valid_from "
    "ON agile_price_snapshots(valid_from)",
)

_SOLAR_FC_DDL_PG = _SOLAR_FC_DDL.replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY"
)
_AGILE_FC_DDL_PG = _AGILE_FC_DDL.replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY"
)
_SOLAR_FC_DDL_MY = _SOLAR_FC_DDL.replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT", "INTEGER PRIMARY KEY AUTO_INCREMENT"
)
_AGILE_FC_DDL_MY = _AGILE_FC_DDL.replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT", "INTEGER PRIMARY KEY AUTO_INCREMENT"
)

_SOLAR_FC_INSERT = """
INSERT INTO solar_forecast_snapshots
    (fetched_at, lat, lon, tilt, azimuth, kwp, interval_start, kw)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
_SOLAR_FC_INSERT_PG = _SOLAR_FC_INSERT.replace("?", "%s")
_SOLAR_FC_INSERT_MY = _SOLAR_FC_INSERT_PG

_AGILE_FC_UPSERT_SQLITE = """
INSERT INTO agile_price_snapshots
    (fetched_at, tariff_code, direction, valid_from, valid_to, price_pence)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(tariff_code, direction, valid_from) DO UPDATE SET
    valid_to = excluded.valid_to,
    price_pence = excluded.price_pence,
    fetched_at = excluded.fetched_at
"""
_AGILE_FC_UPSERT_PG = """
INSERT INTO agile_price_snapshots
    (fetched_at, tariff_code, direction, valid_from, valid_to, price_pence)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (tariff_code, direction, valid_from) DO UPDATE SET
    valid_to = EXCLUDED.valid_to,
    price_pence = EXCLUDED.price_pence,
    fetched_at = EXCLUDED.fetched_at
"""
_AGILE_FC_UPSERT_MY = """
INSERT INTO agile_price_snapshots
    (fetched_at, tariff_code, direction, valid_from, valid_to, price_pence)
VALUES (%s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    valid_to = VALUES(valid_to),
    price_pence = VALUES(price_pence),
    fetched_at = VALUES(fetched_at)
"""


def _utc_sql_str(ts) -> str:
    """Format any datetime-like bound as UTC ``YYYY-MM-DD HH:MM:SS``."""
    if hasattr(ts, 'tz_convert'):
        ts = ts.tz_convert('UTC').to_pydatetime()
    elif isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
    return ts.strftime('%Y-%m-%d %H:%M:%S')


def _octopus_interval_key_utc(ts) -> str:
    return _utc_sql_str(ts)


def _frame_empty(df) -> bool:
    if df is None:
        return True
    if isinstance(df, pl.DataFrame):
        return df.is_empty()
    return bool(getattr(df, 'empty', True))


# Above any plausible single-inverter kW for this dashboard's home systems.
# Historical bugs stored dawn PV / standby load of 10–50 W as 10–50 kW;
# anything above this ceiling is treated as watts and divided by 1000.
_POWER_KW_SANITY_MAX = 9.0


def _sanitize_power_kw(val, *, max_abs_kw: float = _POWER_KW_SANITY_MAX):
    """Return kW, recovering values that were stored as watts by mistake."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    if abs(f) > max_abs_kw:
        f = f / 1000.0
    return f


def _sanitize_power_kw_expr(col: str, *, max_abs_kw: float = _POWER_KW_SANITY_MAX):
    """Polars expression: divide implausible kW samples by 1000."""
    c = pl.col(col)
    return (
        pl.when(c.abs() > max_abs_kw)
        .then(c / 1000.0)
        .otherwise(c)
        .alias(col)
    )


def _as_polars(df) -> pl.DataFrame:
    if isinstance(df, pl.DataFrame):
        return df
    try:
        return pl.from_pandas(df)
    except ImportError:
        return pl.DataFrame({c: df[c].to_list() for c in df.columns})


def _row_ts_utc(val) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    if isinstance(val, str):
        try:
            t = datetime.fromisoformat(val.replace('Z', '+00:00'))
        except ValueError:
            return None
        if t.tzinfo is None:
            return t.replace(tzinfo=timezone.utc)
        return t.astimezone(timezone.utc)
    if hasattr(val, 'to_pydatetime'):
        return _row_ts_utc(val.to_pydatetime())
    return None


def _utc_to_london_cols(df: pl.DataFrame, *names: str) -> pl.DataFrame:
    """Parse UTC timestamps and convert to Europe/London."""
    exprs = []
    for name in names:
        if name not in df.columns:
            continue
        dtype = df.schema[name]
        if dtype == pl.Utf8:
            base = pl.col(name).str.to_datetime(time_zone='UTC', strict=False)
        elif isinstance(dtype, pl.Datetime) and dtype.time_zone == 'Europe/London':
            continue
        elif isinstance(dtype, pl.Datetime) and dtype.time_zone:
            base = pl.col(name).dt.convert_time_zone('UTC')
        else:
            base = pl.col(name).cast(pl.Datetime('us', 'UTC'), strict=False).dt.replace_time_zone('UTC')
        exprs.append(base.dt.convert_time_zone('Europe/London').alias(name))
    return df.with_columns(exprs) if exprs else df


def _relay_to_db_int(relay_on):
    if relay_on is True:
        return 1
    if relay_on is False:
        return 0
    return None


class _BackendCooling(Exception):
    """MySQL/PostgreSQL skipped while reconnect backoff is active."""


_DB_BACKOFF_START_S = 5.0
_DB_BACKOFF_MAX_S = 60.0


class DataLogger:
    """Threaded writer that logs readings to SQLite / MySQL / PostgreSQL."""

    def __init__(self, status_callback=None):
        self.status_callback = status_callback
        self._q = queue.Queue()
        self._running = True
        self.sqlite_enabled = False
        self.sqlite_path = str(Path.home() / "energy_dashboard.db")
        self.mysql_enabled = False
        self.mysql_host = "localhost"
        self.mysql_port = 3306
        self.mysql_db = "energy"
        self.mysql_user = ""
        self.mysql_pass = ""
        self.pg_enabled = False
        self.pg_host = "localhost"
        self.pg_port = 5432
        self.pg_db = "powermon"
        self.pg_user = ""
        self.pg_pass = ""
        self._sqlite_conn = None
        self._mysql_conn = None
        self._pg_conn = None
        self._backend_fail_until = {"mysql": 0.0, "pg": 0.0}
        self._backend_backoff = {
            "mysql": _DB_BACKOFF_START_S,
            "pg": _DB_BACKOFF_START_S,
        }
        self._backend_had_outage = {"mysql": False, "pg": False}
        self._thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._thread.start()
        self._retention_write_ticks = 0
        # Last Growatt sample signature — identical re-logs of a stale GROTT
        # snapshot used to flood growatt_readings (e.g. 588 bit-identical rows
        # spanning ~30 h on 2026-08-18..20).
        self._last_growatt_sig = None
        self._growatt_dup_skips = 0
        self._last_growatt_write_at = None

    def _status(self, msg):
        if self.status_callback:
            try:
                self.status_callback(msg)
            except Exception:
                pass

    def reconfigure(self):
        self._close_all()
        self._clear_backend_cooldown()

    def _close_all(self):
        for attr in ('_sqlite_conn', '_mysql_conn', '_pg_conn'):
            conn = getattr(self, attr, None)
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
                setattr(self, attr, None)

    def backend_ready(self, name: str) -> bool:
        """True unless this network engine is in reconnect backoff."""
        if name == "sqlite":
            return True
        until = float(self._backend_fail_until.get(name, 0.0) or 0.0)
        return _time_mod.monotonic() >= until

    def _clear_backend_cooldown(self, name: str | None = None, *, reset_outage: bool = True) -> None:
        names = (name,) if name else ("mysql", "pg")
        for n in names:
            self._backend_fail_until[n] = 0.0
            self._backend_backoff[n] = _DB_BACKOFF_START_S
            if reset_outage:
                self._backend_had_outage[n] = False

    def _mark_backend_up(self, name: str) -> None:
        if self._backend_had_outage.get(name):
            label = "MySQL" if name == "mysql" else "PostgreSQL"
            self._status(f"{label} reachable again.")
        self._backend_had_outage[name] = False
        self._backend_fail_until[name] = 0.0
        self._backend_backoff[name] = _DB_BACKOFF_START_S

    def _mark_backend_down(self, name: str) -> None:
        now = _time_mod.monotonic()
        delay = float(self._backend_backoff.get(name, _DB_BACKOFF_START_S))
        delay = min(max(delay, _DB_BACKOFF_START_S), _DB_BACKOFF_MAX_S)
        self._backend_fail_until[name] = now + delay
        self._backend_backoff[name] = min(delay * 2.0, _DB_BACKOFF_MAX_S)
        first = not self._backend_had_outage.get(name)
        self._backend_had_outage[name] = True
        if first:
            label = "MySQL" if name == "mysql" else "PostgreSQL"
            self._status(
                f"{label} unreachable — retrying in {delay:.0f}s (app stays live)."
            )

    def _raise_if_cooling(self, name: str) -> None:
        if not self.backend_ready(name):
            raise _BackendCooling(name)

    def _fail_mysql(self, err: BaseException, msg: str) -> None:
        self._engine_write_failed("_mysql_conn", err, msg)

    def _fail_pg(self, err: BaseException, msg: str) -> None:
        self._engine_write_failed("_pg_conn", err, msg)

    def _note_read_error(self, err: BaseException, label: str) -> None:
        self._last_read_error = str(err)
        if isinstance(err, _BackendCooling):
            return
        self._status(f"DB read error ({label}): {err}")

    def _engine_write_failed(self, attr: str, err: BaseException, msg: str) -> None:
        if isinstance(err, _BackendCooling):
            return
        try:
            conn = getattr(self, attr, None)
            if conn is not None:
                conn.close()
        except Exception:
            pass
        setattr(self, attr, None)
        self._status(msg)

    def _ensure_sqlite(self):
        if self._sqlite_conn is None:
            from energy_dashboard.db.full_schema import apply_full_schema
            self._sqlite_conn = sqlite3.connect(self.sqlite_path)
            apply_full_schema(self._sqlite_conn, "sqlite")
        return self._sqlite_conn

    def _ensure_mysql(self):
        from energy_dashboard.db.connect_probe import mysql_connect
        from energy_dashboard.db.full_schema import apply_full_schema

        self._raise_if_cooling("mysql")
        if self._mysql_conn is None:
            try:
                self._mysql_conn = mysql_connect(
                    self.mysql_host, self.mysql_port,
                    self.mysql_user, self.mysql_pass, self.mysql_db,
                    autocommit=True,
                )
                apply_full_schema(self._mysql_conn, "mysql")
                self._mark_backend_up("mysql")
            except _BackendCooling:
                raise
            except Exception:
                self._mysql_conn = None
                self._mark_backend_down("mysql")
                raise
        return self._mysql_conn

    def _ensure_pg(self):
        """Open PostgreSQL. Does not create tables — the owner runs that SQL by hand."""
        from energy_dashboard.db.connect_probe import postgresql_connect

        self._raise_if_cooling("pg")
        if self._pg_conn is None:
            try:
                self._pg_conn = postgresql_connect(
                    self.pg_host, self.pg_port,
                    self.pg_user, self.pg_pass, self.pg_db,
                    autocommit=True,
                )
                self._mark_backend_up("pg")
            except _BackendCooling:
                raise
            except Exception:
                try:
                    if self._pg_conn is not None:
                        self._pg_conn.close()
                except Exception:
                    pass
                self._pg_conn = None
                self._mark_backend_down("pg")
                raise
        return self._pg_conn

    def _primary_storage_backend(self):
        """First enabled export backend (matches Setup & Info priority)."""
        if self.sqlite_enabled:
            return "sqlite"
        if self.mysql_enabled:
            return "mysql"
        if self.pg_enabled:
            return "pg"
        return None

    def _query_pl(self, backend: str, sql: str, params) -> pl.DataFrame:
        """Parameterized SELECT → Polars DataFrame on the given storage backend.

        Always opens a short-lived connection for reads. Sharing the writer
        thread's ``_pg_conn`` from Battery Analysis (and other UI workers)
        caused hangs and ``connection pointer is NULL`` once the writer
        reset the handle after a failed upsert.
        """
        q = sql.replace("%s", "?") if backend == "sqlite" else sql
        p = list(params) if params else None
        # Scan all rows for dtypes. Default inference (first 100 rows) breaks on
        # growatt_readings when early samples are whole-number floats (10, 20, …)
        # and later samples are fractional kW (1.81, 4.08).
        _read_kw = {"execute_options": {"parameters": p}, "infer_schema_length": None}
        if backend == "sqlite":
            conn = sqlite3.connect(self.sqlite_path)
            try:
                return pl.read_database(q, connection=conn, **_read_kw)
            finally:
                conn.close()
        if backend in ("mysql", "pg"):
            self._raise_if_cooling(backend)
        if backend == "mysql":
            from energy_dashboard.db.connect_probe import mysql_connect
            try:
                conn = mysql_connect(
                    self.mysql_host, self.mysql_port,
                    self.mysql_user, self.mysql_pass, self.mysql_db,
                )
            except Exception:
                self._mark_backend_down("mysql")
                raise
            try:
                df = pl.read_database(q, connection=conn, **_read_kw)
                self._mark_backend_up("mysql")
                return df
            finally:
                conn.close()
        from energy_dashboard.db.connect_probe import postgresql_connect
        try:
            conn = postgresql_connect(
                self.pg_host, self.pg_port,
                self.pg_user, self.pg_pass, self.pg_db,
                autocommit=True,
            )
        except Exception:
            self._mark_backend_down("pg")
            raise
        try:
            df = pl.read_database(q, connection=conn, **_read_kw)
            self._mark_backend_up("pg")
            return df
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def log_growatt(self, data):
        if not (self.sqlite_enabled or self.mysql_enabled or self.pg_enabled):
            return
        if not isinstance(data, dict):
            return
        # Cap write rate (~3/min). Never skip because values look unchanged —
        # a live Grott feed is continuous even when SOC/power sit still.
        now = datetime.now(timezone.utc)
        last_write = getattr(self, '_last_growatt_write_at', None)
        if last_write is not None and (now - last_write).total_seconds() < 20:
            return
        self._last_growatt_write_at = now
        self._q.put(('growatt', data))

    def log_growatt_mix_chart(self, device_sn, records):
        if not (self.sqlite_enabled or self.mysql_enabled or self.pg_enabled):
            return
        if not device_sn or not records:
            return
        self._q.put(('growatt_mix_chart', (device_sn, list(records))))

    def log_tasmota(self, records):
        if not (self.sqlite_enabled or self.mysql_enabled or self.pg_enabled):
            return
        self._q.put(('tasmota', records))

    def log_octopus(self, records):
        if not (self.sqlite_enabled or self.mysql_enabled or self.pg_enabled):
            return
        if not records:
            return
        self._q.put(('octopus', records))

    def log_solar_forecast(self, df, params):
        """Persist a solar forecast snapshot.

        ``df`` is a DataFrame with at least ``timestamp`` (UTC-aware or
        UTC-naive) and ``kW`` columns — same shape returned by
        ``fetch_solar_forecast``. ``params`` is a dict with lat/lon/tilt/
        azimuth/kwp (any string-convertible numeric).
        """
        if not (self.sqlite_enabled or self.mysql_enabled or self.pg_enabled):
            return
        if _frame_empty(df):
            return
        self._q.put(('solar_forecast', (df, params)))

    def log_agile_forecast(self, df, tariff_code, direction):
        """Persist an Agile-tariff price snapshot (UPSERT per tariff/slot)."""
        if not (self.sqlite_enabled or self.mysql_enabled or self.pg_enabled):
            return
        if _frame_empty(df) or not tariff_code:
            return
        self._q.put(('agile_forecast', (df, tariff_code, direction)))

    def log_agile_year_daily(self, rows, tariff_code, direction):
        """Persist Agile Year daily high / low / average (UPSERT per tariff/day)."""
        if not (self.sqlite_enabled or self.mysql_enabled or self.pg_enabled):
            return
        if not rows or not tariff_code:
            return
        self._q.put(('agile_year_daily', (list(rows), tariff_code, direction)))

    def log_shadow_plan(self, row: dict):
        """Persist a frozen Shadow Trial plan (UPSERT keyed on day_date)."""
        if not (self.sqlite_enabled or self.mysql_enabled or self.pg_enabled):
            return
        if not row or not row.get('day_date') or not row.get('plan_json'):
            return
        self._q.put(('shadow_plan', dict(row)))

    def enqueue_connectivity_event(self, row) -> None:
        if not (self.sqlite_enabled or self.mysql_enabled or self.pg_enabled):
            return
        self._q.put(('connectivity_event', row))

    def enqueue_pv_string_charge(self, row) -> None:
        if not (self.sqlite_enabled or self.mysql_enabled or self.pg_enabled):
            return
        self._q.put(('pv_string_charge', row))

    def _write_connectivity_event(self, row):
        from energy_dashboard.db.connectivity_events import write_connectivity_event

        write_connectivity_event(self, row)

    def _write_pv_string_charge(self, row):
        from energy_dashboard.db.pv_string_charge import write_pv_string_charge

        write_pv_string_charge(self, row)

    def log_shadow_score(self, row: dict):
        """Persist a Shadow Trial daily score (UPSERT keyed on day_date)."""
        if not (self.sqlite_enabled or self.mysql_enabled or self.pg_enabled):
            return
        if not row or not row.get('day_date'):
            return
        self._q.put(('shadow_score', dict(row)))

    def _writer_loop(self):
        while self._running:
            try:
                item = self._q.get(timeout=2)
            except queue.Empty:
                continue
            kind, payload = item
            try:
                if kind == 'growatt':
                    self._write_growatt(payload)
                elif kind == 'tasmota':
                    self._write_tasmota(payload)
                elif kind == 'octopus':
                    self._write_octopus(payload)
                elif kind == 'solar_forecast':
                    self._write_solar_forecast(*payload)
                elif kind == 'agile_forecast':
                    self._write_agile_forecast(*payload)
                elif kind == 'agile_year_daily':
                    self._write_agile_year_daily(*payload)
                elif kind == 'growatt_mix_chart':
                    self._write_growatt_mix_chart(*payload)
                elif kind == 'shadow_plan':
                    self._write_shadow_row(upsert_shadow_plan, payload, 'shadow plan')
                elif kind == 'shadow_score':
                    self._write_shadow_row(upsert_shadow_score, payload, 'shadow score')
                elif kind == 'connectivity_event':
                    self._write_connectivity_event(payload)
                elif kind == 'pv_string_charge':
                    self._write_pv_string_charge(payload)
                self._maybe_run_retention()
            except _BackendCooling:
                pass
            except Exception as e:
                self._status(f"DB write error: {e}")

    def _maybe_run_retention(self):
        """Periodically prune tables with ring-buffer policies enabled."""
        self._retention_write_ticks += 1
        if self._retention_write_ticks % 40 != 0:
            return
        try:
            from energy_dashboard.db.retention import prune_all_for_logger

            prune_all_for_logger(self)
        except Exception:
            pass

    def _write_growatt_mix_chart(self, device_sn, records):
        if self.sqlite_enabled:
            try:
                conn = self._ensure_sqlite()
                upsert_mix_chart_rows(conn.cursor(), 'sqlite', device_sn, records)
                conn.commit()
            except Exception as e:
                self._sqlite_conn = None
                self._status(f"SQLite mix chart error: {e}")
        if self.mysql_enabled:
            try:
                conn = self._ensure_mysql()
                with conn.cursor() as cur:
                    upsert_mix_chart_rows(cur, 'mysql', device_sn, records)
            except Exception as e:
                self._fail_mysql(e, f"MySQL mix chart error: {e}")
        if self.pg_enabled:
            try:
                conn = self._ensure_pg()
                with conn.cursor() as cur:
                    upsert_mix_chart_rows(cur, 'pg', device_sn, records)
            except Exception as e:
                self._fail_pg(e, f"PostgreSQL mix chart error: {e}")

    @staticmethod
    def _sql_scalar(v):
        """Coerce values for DB drivers (plain Python types only — no numpy)."""
        if v is None or isinstance(v, (str, bytes, bool)):
            return v
        try:
            if hasattr(v, "item"):
                v = v.item()
        except Exception:
            pass
        if isinstance(v, bool):
            return v
        if isinstance(v, int) and not isinstance(v, bool):
            return int(v)
        try:
            return float(v)
        except (TypeError, ValueError):
            return v

    def _write_shadow_row(self, upsert_fn, row, label):
        clean = {k: self._sql_scalar(v) for k, v in (row or {}).items()}
        if self.sqlite_enabled:
            try:
                conn = self._ensure_sqlite()
                upsert_fn(conn.cursor(), 'sqlite', clean)
                conn.commit()
            except Exception as e:
                self._sqlite_conn = None
                self._status(f"SQLite {label} error: {e}")
        if self.mysql_enabled:
            try:
                conn = self._ensure_mysql()
                with conn.cursor() as cur:
                    upsert_fn(cur, 'mysql', clean)
            except Exception as e:
                self._fail_mysql(e, f"MySQL {label} error: {e}")
        if self.pg_enabled:
            try:
                conn = self._ensure_pg()
                with conn.cursor() as cur:
                    upsert_fn(cur, 'pg', clean)
            except Exception as e:
                self._fail_pg(e, f"PostgreSQL {label} error: {e}")

    def query_shadow_plan(self, day_date: str):
        """Return the frozen Shadow Trial plan row for a London day, or None."""
        backend = self._primary_storage_backend()
        if backend is None or not day_date:
            return None
        q = ("SELECT day_date, built_at, soc_start_pct, soc_source, "
             "capacity_kwh, eta, max_kw, soc_min_pct, allow_export, "
             "planned_cost_p, slot_count, plan_json "
             "FROM optimiser_shadow_plans WHERE day_date = %s")
        try:
            df = self._query_pl(backend, q, (str(day_date),))
        except Exception as e:
            self._note_read_error(e, "shadow plan")
            return None
        if df.is_empty():
            return None
        return {c: df.item(0, c) for c in df.columns}

    def query_shadow_plan_days(self, limit_days: int = 120):
        """Return the day_date strings that have frozen plans, oldest first."""
        backend = self._primary_storage_backend()
        if backend is None:
            return []
        q = ("SELECT day_date FROM optimiser_shadow_plans "
             "ORDER BY day_date DESC LIMIT %s")
        try:
            df = self._query_pl(backend, q, (int(limit_days),))
        except Exception as e:
            self._note_read_error(e, "shadow plan days")
            return []
        return sorted(df.get_column('day_date').to_list()) if not df.is_empty() else []

    def query_shadow_scores(self, limit_days: int = 120) -> pl.DataFrame:
        """Return the Shadow Trial scoreboard rows, most recent day first."""
        empty = pl.DataFrame()
        backend = self._primary_storage_backend()
        if backend is None:
            return empty
        q = ("SELECT day_date, scored_at, octopus_complete, telemetry_slots, "
             "expected_slots, soc_start_pct, actual_cost_p, shadow_cost_p, "
             "baseline_cost_p, perfect_cost_p, actual_capture, shadow_capture "
             "FROM optimiser_shadow_scores "
             "ORDER BY day_date DESC LIMIT %s")
        try:
            return self._query_pl(backend, q, (int(limit_days),))
        except Exception as e:
            self._note_read_error(e, "shadow scores")
            return empty

    def query_growatt_mix_chart(self, device_sn, days, *, end_dt=None):
        """Load stored 5-minute MIX chart rows for Battery Analysis."""
        if not device_sn:
            return []
        end = end_dt or datetime.now()
        if isinstance(end, datetime):
            end_s = end.strftime("%Y-%m-%d %H:%M:%S")
            start_s = (end - timedelta(days=max(1, int(days)))).strftime("%Y-%m-%d %H:%M:%S")
        else:
            end_s = str(end)
            start_s = (datetime.now() - timedelta(days=max(1, int(days)))).strftime("%Y-%m-%d %H:%M:%S")
        q = (
            "SELECT timestamp, pv_kw, charge_kw, discharge_kw, "
            "grid_import_kw, grid_export_kw, load_kw "
            "FROM growatt_mix_chart "
            "WHERE device_sn = %s AND timestamp >= %s AND timestamp <= %s "
            "ORDER BY timestamp"
        )
        backend = self._primary_storage_backend()
        if backend is None:
            return []
        params = (device_sn, start_s, end_s)
        try:
            df = self._query_pl(backend, q, params)
        except Exception as e:
            self._note_read_error(e, "mix chart")
            return []
        if df.is_empty():
            return []
        out = []
        for row in df.iter_rows(named=True):
            ts = row.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
            out.append({
                "timestamp": ts,
                "pv_kW": row.get("pv_kw") or 0.0,
                "charge_kW": row.get("charge_kw") or 0.0,
                "discharge_kW": row.get("discharge_kw") or 0.0,
                "grid_import_kW": row.get("grid_import_kw") or 0.0,
                "grid_export_kW": row.get("grid_export_kw") or 0.0,
                "load_kW": row.get("load_kw") or 0.0,
            })
        return out

    def query_growatt_battery_history_from_readings(self, days, *, end_dt=None):
        """Build Battery Analysis rows from locally logged live Growatt readings.

        GROTT MQTT users may not have cloud MIX-chart history, but the dashboard
        still logs live inverter snapshots to ``growatt_readings``. Convert those
        rows into the same shape as ``growatt_mix_chart`` records so Battery
        Analysis can use local telemetry as the historical source.
        """
        end = end_dt or datetime.now(timezone.utc)
        if isinstance(end, datetime):
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            else:
                end = end.astimezone(timezone.utc)
            start = end - timedelta(days=max(1, int(days)))
            end_s = end.strftime("%Y-%m-%d %H:%M:%S")
            start_s = start.strftime("%Y-%m-%d %H:%M:%S")
        else:
            end_s = str(end)
            start_s = (
                datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
            ).strftime("%Y-%m-%d %H:%M:%S")

        q = (
            "SELECT timestamp, soc_pct, battery_power_kw, pv_power_kw, "
            "grid_power_kw, load_power_kw "
            "FROM growatt_readings "
            "WHERE timestamp >= %s AND timestamp <= %s "
            "ORDER BY timestamp"
        )
        backend = self._primary_storage_backend()
        if backend is None:
            return []
        try:
            df = self._query_pl(backend, q, (start_s, end_s))
        except Exception as e:
            self._status(f"Growatt readings history error: {e}")
            return []
        if df.is_empty():
            return []
        df = df.with_columns(
            pl.col('timestamp').cast(pl.Utf8, strict=False)
            .str.to_datetime(time_zone='UTC', strict=False)
            .fill_null(pl.col('timestamp').cast(pl.Datetime('us', 'UTC'), strict=False))
            .alias('timestamp'),
            pl.col('soc_pct').cast(pl.Float64, strict=False),
            pl.col('battery_power_kw').cast(pl.Float64, strict=False),
            pl.col('pv_power_kw').cast(pl.Float64, strict=False),
            pl.col('grid_power_kw').cast(pl.Float64, strict=False),
            pl.col('load_power_kw').cast(pl.Float64, strict=False),
        ).drop_nulls('timestamp')
        if df.is_empty():
            return []
        out = []
        for row in df.iter_rows(named=True):
            ts = row.get("timestamp")
            if hasattr(ts, "replace"):
                # Matplotlib/pandas handle naive datetimes consistently with
                # the cloud MIX chart rows; storage remains UTC.
                ts = ts.replace(tzinfo=None)
            bat = _sanitize_power_kw(row.get("battery_power_kw")) or 0.0
            grid = _sanitize_power_kw(row.get("grid_power_kw")) or 0.0
            out.append({
                "timestamp": ts,
                "soc_pct": row.get("soc_pct"),
                "pv_kW": _sanitize_power_kw(row.get("pv_power_kw")) or 0.0,
                "charge_kW": max(float(bat), 0.0),
                "discharge_kW": max(-float(bat), 0.0),
                "grid_import_kW": max(-float(grid), 0.0),
                "grid_export_kW": max(float(grid), 0.0),
                "load_kW": _sanitize_power_kw(row.get("load_power_kw")) or 0.0,
            })
        return out

    def _write_growatt(self, d):
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        row = (ts, d.get('soc'), d.get('bat_power'), d.get('pv_power'),
               d.get('grid_power'), d.get('load_power'),
               d.get('charge_today'), d.get('discharge_today'),
               d.get('pv_today'))
        row = tuple(self._to_float(v) if i > 0 else v for i, v in enumerate(row))
        # Power columns (indices 2–5): reject watts mis-labelled as kW.
        row = (
            row[0],
            row[1],
            _sanitize_power_kw(row[2]),
            _sanitize_power_kw(row[3]),
            _sanitize_power_kw(row[4]),
            _sanitize_power_kw(row[5]),
            row[6],
            row[7],
            row[8],
        )
        if self.sqlite_enabled:
            try:
                conn = self._ensure_sqlite()
                conn.execute(_GROWATT_INSERT, row)
                conn.commit()
            except Exception as e:
                self._sqlite_conn = None
                self._status(f"SQLite error: {e}")
        if self.mysql_enabled:
            try:
                conn = self._ensure_mysql()
                with conn.cursor() as cur:
                    cur.execute(_GROWATT_INSERT_MY, row)
            except Exception as e:
                self._fail_mysql(e, f"MySQL error: {e}")
        if self.pg_enabled:
            try:
                conn = self._ensure_pg()
                with conn.cursor() as cur:
                    cur.execute(_GROWATT_INSERT_PG, row)
            except Exception as e:
                self._fail_pg(e, f"PostgreSQL error: {e}")

    def _write_tasmota(self, records):
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        rows = []
        dev_rows = []
        for r in records:
            rows.append((ts, r.get('ip'), r.get('name'),
                         self._to_float(r.get('power_W')),
                         self._to_float(r.get('voltage_V')),
                         self._to_float(r.get('current_A')),
                         self._to_float(r.get('today_kWh')),
                         self._to_float(r.get('total_kWh'))))
            ip = r.get('ip')
            if ip:
                dev_rows.append((
                    ip,
                    (r.get('name') or '') or '',
                    _relay_to_db_int(r.get('relay_on')),
                    ts,
                    ts,
                ))
        if not rows:
            return
        if self.sqlite_enabled:
            try:
                conn = self._ensure_sqlite()
                conn.executemany(_TASMOTA_INSERT, rows)
                if dev_rows:
                    conn.executemany(_TASMOTA_DEVICE_UPSERT_SQLITE, dev_rows)
                conn.commit()
            except Exception as e:
                self._sqlite_conn = None
                self._status(f"SQLite error: {e}")
        if self.mysql_enabled:
            try:
                conn = self._ensure_mysql()
                with conn.cursor() as cur:
                    cur.executemany(_TASMOTA_INSERT_MY, rows)
                    if dev_rows:
                        cur.executemany(_TASMOTA_DEVICE_UPSERT_MY, dev_rows)
            except Exception as e:
                self._fail_mysql(e, f"MySQL error: {e}")
        if self.pg_enabled:
            try:
                conn = self._ensure_pg()
                with conn.cursor() as cur:
                    cur.executemany(_TASMOTA_INSERT_PG, rows)
                    if dev_rows:
                        cur.executemany(_TASMOTA_DEVICE_UPSERT_PG, dev_rows)
            except Exception as e:
                self._fail_pg(e, f"PostgreSQL error: {e}")

    def _write_octopus(self, records):
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        rows = []
        for r in records:
            key = r.get('interval_start')
            if not key:
                continue
            rows.append((
                key,
                self._to_float(r.get('import_kwh')),
                self._to_float(r.get('export_kwh')),
                ts,
            ))
        if not rows:
            return
        if self.sqlite_enabled:
            try:
                conn = self._ensure_sqlite()
                conn.executemany(_OCTOPUS_UPSERT_SQLITE, rows)
                conn.commit()
            except Exception as e:
                self._sqlite_conn = None
                self._status(f"SQLite error: {e}")
        if self.mysql_enabled:
            try:
                conn = self._ensure_mysql()
                with conn.cursor() as cur:
                    cur.executemany(_OCTOPUS_UPSERT_MY, rows)
            except Exception as e:
                self._fail_mysql(e, f"MySQL error: {e}")
        if self.pg_enabled:
            try:
                conn = self._ensure_pg()
                with conn.cursor() as cur:
                    cur.executemany(_OCTOPUS_UPSERT_PG, rows)
            except Exception as e:
                self._fail_pg(e, f"PostgreSQL error: {e}")

    def _write_solar_forecast(self, df, params):
        ts_now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        try:
            lat = float(params.get('lat'))
            lon = float(params.get('lon'))
        except (TypeError, ValueError):
            return  # without a valid lat/lon the snapshot is useless
        tilt = self._to_float(params.get('tilt'))
        azim = self._to_float(params.get('azimuth'))
        kwp = self._to_float(params.get('kwp'))
        rows = []
        for r in _as_polars(df).iter_rows(named=True):
            t = _row_ts_utc(r.get('timestamp'))
            if t is None:
                continue
            kw = self._to_float(r.get('kW'))
            if kw is None:
                continue
            rows.append((
                ts_now, lat, lon, tilt, azim, kwp,
                t.strftime('%Y-%m-%d %H:%M:%S'), kw,
            ))
        if not rows:
            return
        if self.sqlite_enabled:
            try:
                conn = self._ensure_sqlite()
                conn.executemany(_SOLAR_FC_INSERT, rows)
                conn.commit()
            except Exception as e:
                self._sqlite_conn = None
                self._status(f"SQLite error: {e}")
        if self.mysql_enabled:
            try:
                conn = self._ensure_mysql()
                with conn.cursor() as cur:
                    cur.executemany(_SOLAR_FC_INSERT_MY, rows)
            except Exception as e:
                self._fail_mysql(e, f"MySQL error: {e}")
        if self.pg_enabled:
            try:
                conn = self._ensure_pg()
                with conn.cursor() as cur:
                    cur.executemany(_SOLAR_FC_INSERT_PG, rows)
            except Exception as e:
                self._fail_pg(e, f"PostgreSQL error: {e}")

    def _write_agile_forecast(self, df, tariff_code, direction):
        ts_now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        rows = []
        for r in _as_polars(df).iter_rows(named=True):
            vf = _row_ts_utc(r.get('valid_from'))
            vt = _row_ts_utc(r.get('valid_to'))
            if vf is None or vt is None:
                continue
            price = self._to_float(r.get('price_pence'))
            if price is None:
                continue
            rows.append((
                ts_now, tariff_code, direction,
                vf.strftime('%Y-%m-%d %H:%M:%S'),
                vt.strftime('%Y-%m-%d %H:%M:%S'),
                price,
            ))
        if not rows:
            return
        if self.sqlite_enabled:
            try:
                conn = self._ensure_sqlite()
                conn.executemany(_AGILE_FC_UPSERT_SQLITE, rows)
                conn.commit()
            except Exception as e:
                self._sqlite_conn = None
                self._status(f"SQLite error: {e}")
        if self.mysql_enabled:
            try:
                conn = self._ensure_mysql()
                with conn.cursor() as cur:
                    cur.executemany(_AGILE_FC_UPSERT_MY, rows)
            except Exception as e:
                self._fail_mysql(e, f"MySQL error: {e}")
        if self.pg_enabled:
            try:
                conn = self._ensure_pg()
                with conn.cursor() as cur:
                    cur.executemany(_AGILE_FC_UPSERT_PG, rows)
            except Exception as e:
                self._fail_pg(e, f"PostgreSQL error: {e}")

    def _write_agile_year_daily(self, rows, tariff_code, direction):
        from energy_dashboard.db.agile_year_daily import write_agile_year_daily

        write_agile_year_daily(self, rows, tariff_code, direction)

    def query_agile_year_daily(self, tariff_code, direction='import'):
        """Newest-first daily Agile Year rows from ``agile_year_daily``."""
        from energy_dashboard.db.agile_year_daily import query_agile_year_daily

        return query_agile_year_daily(self, tariff_code, direction)

    # ── Read-side helpers (used by ForecastsTab to overlay history) ────

    def query_solar_forecast_snapshot(self, start_utc, end_utc, before_utc=None):
        """Return a Polars frame (interval_start UTC, kw) for the *most recent*
        snapshot whose ``fetched_at`` is at-or-before ``before_utc`` (default:
        ``end_utc``). Empty frame if no rows or DB not available.
        """
        empty = pl.DataFrame(schema={'interval_start': pl.Datetime('us', 'UTC'), 'kw': pl.Float64})
        backend = self._primary_storage_backend()
        if backend is None:
            return empty
        if before_utc is None:
            before_utc = end_utc
        s_start = _utc_sql_str(start_utc)
        s_end = _utc_sql_str(end_utc)
        s_before = _utc_sql_str(before_utc)
        max_sql = (
            "SELECT MAX(fetched_at) FROM solar_forecast_snapshots "
            "WHERE fetched_at <= %s AND interval_start BETWEEN %s AND %s"
        )
        rows_sql = (
            "SELECT interval_start, kw FROM solar_forecast_snapshots "
            "WHERE fetched_at = %s AND interval_start BETWEEN %s AND %s "
            "ORDER BY interval_start"
        )
        try:
            df_max = self._query_pl(backend, max_sql, (s_before, s_start, s_end))
            best_fetch = df_max.item(0, 0) if not df_max.is_empty() else None
            if best_fetch is None:
                return empty
            df = self._query_pl(backend, rows_sql, (best_fetch, s_start, s_end))
            if df.is_empty():
                return empty
            return df.with_columns(
                pl.col('interval_start').cast(pl.Utf8, strict=False)
                .str.to_datetime(time_zone='UTC', strict=False)
                .fill_null(pl.col('interval_start').cast(pl.Datetime('us', 'UTC'), strict=False))
                .alias('interval_start'),
                pl.col('kw').cast(pl.Float64, strict=False),
            )
        except Exception as e:
            self._note_read_error(e, "solar snapshot")
            return empty

    def query_growatt_pv_actual(self, start_utc, end_utc):
        """Return Polars (timestamp UTC, pv_kw) from growatt_readings in range."""
        from energy_dashboard.db.connect_probe import is_table_privilege_error
        flows = self.query_growatt_power_flows(start_utc, end_utc)
        err = getattr(self, "_last_read_error", "") or ""
        if flows.is_empty() and is_table_privilege_error(err):
            raise PermissionError(err)
        if flows.is_empty():
            return pl.DataFrame(schema={'timestamp': pl.Datetime('us', 'UTC'), 'pv_kw': pl.Float64})
        return flows.select('timestamp', 'pv_kw')

    def query_growatt_power_flows(self, start_utc, end_utc):
        """Return Polars (timestamp UTC, pv_kw, load_kw, grid_power_kw).

        ``grid_power_kw`` is net export minus import (positive = export).
        """
        empty = pl.DataFrame(schema={
            'timestamp': pl.Datetime('us', 'UTC'),
            'pv_kw': pl.Float64,
            'load_kw': pl.Float64,
            'grid_power_kw': pl.Float64,
        })
        backend = self._primary_storage_backend()
        if backend is None:
            return empty
        self._last_read_error = None
        s_start = _utc_sql_str(start_utc)
        s_end = _utc_sql_str(end_utc)
        # Multiply by 1.0 so drivers/Polars always see floats — mixed int/float
        # rows (legacy watt spikes vs normal kW) otherwise trip schema inference.
        q = (
            "SELECT timestamp, "
            "pv_power_kw * 1.0 AS pv_power_kw, "
            "load_power_kw * 1.0 AS load_power_kw, "
            "grid_power_kw * 1.0 AS grid_power_kw "
            "FROM growatt_readings "
            "WHERE timestamp >= %s AND timestamp <= %s ORDER BY timestamp"
        )
        try:
            df = self._query_pl(backend, q, (s_start, s_end))
            if df.is_empty():
                return empty
            return df.rename({
                'pv_power_kw': 'pv_kw',
                'load_power_kw': 'load_kw',
            }).with_columns(
                pl.col('timestamp').cast(pl.Utf8, strict=False)
                .str.to_datetime(time_zone='UTC', strict=False)
                .fill_null(pl.col('timestamp').cast(pl.Datetime('us', 'UTC'), strict=False))
                .alias('timestamp'),
                pl.col('pv_kw').cast(pl.Float64, strict=False),
                pl.col('load_kw').cast(pl.Float64, strict=False),
                pl.col('grid_power_kw').cast(pl.Float64, strict=False),
            ).with_columns(
                # Recover historical rows where 10–50 W was stored as 10–50 kW.
                _sanitize_power_kw_expr('pv_kw'),
                _sanitize_power_kw_expr('load_kw'),
                _sanitize_power_kw_expr('grid_power_kw'),
            )
        except Exception as e:
            self._note_read_error(e, "growatt flows")
            return empty

    def query_growatt_soc(self, start_utc, end_utc):
        """Return Polars (timestamp UTC, soc_pct) from growatt_readings in range."""
        empty = pl.DataFrame(schema={'timestamp': pl.Datetime('us', 'UTC'), 'soc_pct': pl.Float64})
        if not self.sqlite_enabled:
            return empty
        s_start = _utc_sql_str(start_utc)
        s_end = _utc_sql_str(end_utc)
        q = (
            "SELECT timestamp, soc_pct FROM growatt_readings "
            "WHERE timestamp BETWEEN ? AND ? "
            "  AND soc_pct IS NOT NULL "
            "ORDER BY timestamp"
        )
        try:
            df = self._query_pl('sqlite', q, (s_start, s_end))
            if df.is_empty():
                return empty
            return df.with_columns(
                pl.col('timestamp').cast(pl.Utf8, strict=False)
                .str.to_datetime(time_zone='UTC', strict=False)
                .fill_null(pl.col('timestamp').cast(pl.Datetime('us', 'UTC'), strict=False))
                .alias('timestamp'),
                pl.col('soc_pct').cast(pl.Float64, strict=False),
            )
        except Exception as e:
            self._status(f"SQLite read error (growatt SOC): {e}")
            return empty

    def query_growatt_soc_near(self, ts_utc, window_minutes: int = 120):
        """Return the soc_pct reading closest to ``ts_utc`` (any backend), or None."""
        backend = self._primary_storage_backend()
        if backend is None:
            return None
        if isinstance(ts_utc, datetime):
            center = ts_utc.astimezone(timezone.utc) if ts_utc.tzinfo else ts_utc.replace(tzinfo=timezone.utc)
        else:
            center = pd.Timestamp(ts_utc).tz_convert('UTC').to_pydatetime()
        half = timedelta(minutes=max(1, int(window_minutes)))
        q = (
            "SELECT timestamp, soc_pct FROM growatt_readings "
            "WHERE timestamp BETWEEN %s AND %s AND soc_pct IS NOT NULL "
            "ORDER BY timestamp"
        )
        try:
            df = self._query_pl(backend, q, (_utc_sql_str(center - half), _utc_sql_str(center + half)))
        except Exception as e:
            self._note_read_error(e, "soc near")
            return None
        if df.is_empty():
            return None
        best = None
        best_gap = None
        for row in df.iter_rows(named=True):
            t = _row_ts_utc(row.get('timestamp'))
            v = self._to_float(row.get('soc_pct'))
            if t is None or v is None:
                continue
            gap = abs((t - center).total_seconds())
            if best_gap is None or gap < best_gap:
                best, best_gap = v, gap
        return best

    def query_octopus_consumption_any(self, start_utc, end_utc):
        """Like query_octopus_consumption but on the primary backend (not just sqlite)."""
        empty = pl.DataFrame(schema={
            'interval_start': pl.Datetime('us', 'UTC'),
            'import_kwh': pl.Float64,
            'export_kwh': pl.Float64,
        })
        backend = self._primary_storage_backend()
        if backend is None:
            return empty
        q = (
            "SELECT interval_start, import_kwh, export_kwh "
            "FROM octopus_readings "
            "WHERE interval_start BETWEEN %s AND %s "
            "ORDER BY interval_start"
        )
        try:
            df = self._query_pl(backend, q, (_utc_sql_str(start_utc), _utc_sql_str(end_utc)))
            if df.is_empty():
                return empty
            return df.with_columns(
                pl.col('interval_start').cast(pl.Utf8, strict=False)
                .str.to_datetime(time_zone='UTC', strict=False)
                .fill_null(pl.col('interval_start').cast(pl.Datetime('us', 'UTC'), strict=False))
                .alias('interval_start'),
                pl.col('import_kwh').cast(pl.Float64, strict=False),
                pl.col('export_kwh').cast(pl.Float64, strict=False),
            )
        except Exception as e:
            self._note_read_error(e, "octopus any")
            return empty

    def query_tasmota_power_history(self, window_minutes: int) -> list:
        """Rows of (timestamp, device_ip, device_name, power_w) since window_minutes ago (UTC)."""
        if not (self.sqlite_enabled or self.mysql_enabled or self.pg_enabled):
            return []
        window_minutes = max(1, int(window_minutes))
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        q = (
            "SELECT timestamp, device_ip, device_name, power_w "
            "FROM tasmota_readings WHERE timestamp >= %s "
            "ORDER BY timestamp ASC"
        )
        try:
            if self.sqlite_enabled:
                conn = sqlite3.connect(self.sqlite_path)
                try:
                    cur = conn.cursor()
                    cur.execute(q.replace("%s", "?"), (cutoff_str,))
                    return cur.fetchall()
                finally:
                    conn.close()
            if self.mysql_enabled:
                if not self.backend_ready("mysql"):
                    return []
                from energy_dashboard.db.connect_probe import mysql_connect
                try:
                    conn = mysql_connect(
                        self.mysql_host, self.mysql_port,
                        self.mysql_user, self.mysql_pass, self.mysql_db,
                    )
                except Exception:
                    self._mark_backend_down("mysql")
                    raise
                try:
                    with conn.cursor() as cur:
                        cur.execute(q, (cutoff_str,))
                        rows = cur.fetchall()
                    self._mark_backend_up("mysql")
                    return rows
                finally:
                    conn.close()
            if self.pg_enabled:
                if not self.backend_ready("pg"):
                    return []
                from energy_dashboard.db.connect_probe import postgresql_connect
                try:
                    conn = postgresql_connect(
                        self.pg_host, self.pg_port,
                        self.pg_user, self.pg_pass, self.pg_db,
                        autocommit=True,
                    )
                except Exception:
                    self._mark_backend_down("pg")
                    raise
                try:
                    with conn.cursor() as cur:
                        cur.execute(q, (cutoff_str,))
                        rows = cur.fetchall()
                    self._mark_backend_up("pg")
                    return rows
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
        except Exception as e:
            self._note_read_error(e, "tasmota history")
        return []

    def query_octopus_consumption(self, start_utc, end_utc):
        """Return Polars (interval_start UTC, import_kwh, export_kwh) from octopus_readings."""
        empty = pl.DataFrame(schema={
            'interval_start': pl.Datetime('us', 'UTC'),
            'import_kwh': pl.Float64,
            'export_kwh': pl.Float64,
        })
        if not self.sqlite_enabled:
            return empty
        s_start = _utc_sql_str(start_utc)
        s_end = _utc_sql_str(end_utc)
        q = (
            "SELECT interval_start, import_kwh, export_kwh "
            "FROM octopus_readings "
            "WHERE interval_start BETWEEN ? AND ? "
            "ORDER BY interval_start"
        )
        try:
            df = self._query_pl('sqlite', q, (s_start, s_end))
            if df.is_empty():
                return empty
            return df.with_columns(
                pl.col('interval_start').cast(pl.Utf8, strict=False)
                .str.to_datetime(time_zone='UTC', strict=False)
                .fill_null(pl.col('interval_start').cast(pl.Datetime('us', 'UTC'), strict=False))
                .alias('interval_start'),
                pl.col('import_kwh').cast(pl.Float64, strict=False),
                pl.col('export_kwh').cast(pl.Float64, strict=False),
            )
        except Exception as e:
            self._status(f"SQLite read error (octopus consumption): {e}")
            return empty

    def query_agile_prices(self, start_utc, end_utc, tariff_code, direction='import'):
        """Return Polars Agile prices (valid_from/valid_to London, price_pence).

        When multiple snapshots cover the same valid_from we keep the latest fetched_at.
        """
        empty = pl.DataFrame(schema={
            'valid_from': pl.Datetime('us', 'Europe/London'),
            'valid_to': pl.Datetime('us', 'Europe/London'),
            'price_pence': pl.Float64,
        })
        backend = self._primary_storage_backend()
        if backend is None:
            return empty
        s_start = _utc_sql_str(start_utc)
        s_end = _utc_sql_str(end_utc)
        q = (
            "SELECT valid_from, valid_to, price_pence, fetched_at "
            "FROM agile_price_snapshots "
            "WHERE tariff_code = %s AND direction = %s "
            "  AND valid_from >= %s AND valid_from <= %s "
            "ORDER BY valid_from, fetched_at"
        )
        params = (tariff_code, direction, s_start, s_end)
        try:
            df = self._query_pl(backend, q, params)
            if df.is_empty():
                return empty
            df = (
                df.sort(['valid_from', 'fetched_at'])
                .unique(subset=['valid_from'], keep='last')
                .drop('fetched_at')
            )
            df = _utc_to_london_cols(df, 'valid_from', 'valid_to')
            if 'valid_to' not in df.columns:
                df = df.with_columns(
                    (pl.col('valid_from') + pl.duration(minutes=30)).alias('valid_to'),
                )
            return df.select('valid_from', 'valid_to', 'price_pence')
        except Exception as e:
            self._note_read_error(e, "agile prices")
            return empty

    @staticmethod
    def _to_float(v):
        if v is None or v == '--':
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def note_connect_result(self, name: str, ok: bool) -> None:
        """Record a Setup / Test Connection outcome for reconnect backoff."""
        if name not in ("mysql", "pg"):
            return
        self._clear_backend_cooldown(name, reset_outage=False)
        if ok:
            self._mark_backend_up(name)
        else:
            self._mark_backend_down(name)

    def test_connections(self):
        results = {}
        if self.sqlite_enabled:
            ok, detail = probe_sqlite(self.sqlite_path)
            results["SQLite"] = (ok, detail)
        if self.mysql_enabled:
            self._clear_backend_cooldown("mysql", reset_outage=False)
            ok, detail = probe_mysql(
                self.mysql_host, self.mysql_port, self.mysql_user,
                self.mysql_pass, self.mysql_db,
            )
            results["MySQL"] = (ok, detail)
            if ok:
                self._mark_backend_up("mysql")
            else:
                self._mark_backend_down("mysql")
        if self.pg_enabled:
            self._clear_backend_cooldown("pg", reset_outage=False)
            ok, detail = probe_postgresql(
                self.pg_host, self.pg_port, self.pg_user,
                self.pg_pass, self.pg_db,
            )
            results["PostgreSQL"] = (ok, detail)
            if ok:
                self._mark_backend_up("pg")
            else:
                self._mark_backend_down("pg")
        return results

    def shutdown(self):
        self._running = False
        self._close_all()


__all__ = [n for n in globals() if not n.startswith('__')]
