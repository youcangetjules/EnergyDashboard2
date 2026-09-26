"""Two-line footer: database health/ingest and whole-machine CPU / RAM.

PostgreSQL / MySQL / SQLite settings come from DataLogger (Setup & Info),
not environment variables. Ingest counts use ``growatt_readings`` and
``tasmota_readings`` ``timestamp`` columns — those are written as UTC
*insert* time when the logger stores a sample, so a delayed Grott dump
counts when it actually lands.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time, timezone

from energy_dashboard.deps import *
from energy_dashboard.db.connect_probe import (
    DB_CONNECT_TIMEOUT_S,
    is_table_privilege_error,
    mysql_connect,
    postgresql_connect,
)
from energy_dashboard.ui.palette import *
from energy_dashboard.ui.proc_stats import ProcessResourceSampler

# Live logger tables whose ``timestamp`` is UTC insert time (see DataLogger).
_INGEST_TABLES = (
    ("growatt_readings", "timestamp"),
    ("tasmota_readings", "timestamp"),
)


def human_bytes(value: int | float | None) -> str:
    if value is None:
        return "—"
    value = float(value)
    if value < 0:
        return "—"
    units = ("B", "KB", "MB", "GB", "TB")
    unit = 0
    while value >= 1024.0 and unit < len(units) - 1:
        value /= 1024.0
        unit += 1
    if unit == 0:
        return f"{value:.0f}{units[unit]}"
    if value >= 100:
        return f"{value:.0f}{units[unit]}"
    if value >= 10:
        return f"{value:.1f}{units[unit]}"
    return f"{value:.2f}{units[unit]}"


def tray_database_lines(status: DatabaseStatus | None) -> tuple[str, str, str, str]:
    """Four lines for the tray menu: host, 15 minutes, 1 hour, live streams.

    Streams are the logger tables that actually received rows in the last
    15 minutes (Growatt and Tasmota). A table with no new rows is not counted.
    """
    if status is None:
        return (
            "Database  —",
            "Last 15 minutes  —",
            "Last hour  —",
            "Streams loading  —",
        )
    host = (status.host or "").strip()
    if (status.engine or "").lower() == "sqlite" or host == "file":
        where = status.database or "SQLite file"
    else:
        where = host or "—"
    if not status.connected:
        return (
            f"Database  {where}  (not connected)",
            "Last 15 minutes  —",
            "Last hour  —",
            "Streams loading  —",
        )

    def amount(nbytes, nrows) -> str:
        rows = compact_count(int(nrows or 0))
        if nbytes is None:
            return f"{rows} rows"
        return f"{human_bytes(nbytes)}  ({rows} rows)"

    streams = []
    if int(status.rows_15m_growatt or 0) > 0:
        streams.append("Growatt")
    if int(status.rows_15m_tasmota or 0) > 0:
        streams.append("Tasmota")
    if streams:
        stream_line = f"{len(streams)}  ({', '.join(streams)})"
    else:
        stream_line = "0  (none in the last 15 minutes)"
    return (
        f"Database  {where}",
        f"Last 15 minutes  {amount(status.bytes_15m, status.rows_15m)}",
        f"Last hour  {amount(status.bytes_1h, status.rows_1h)}",
        f"Streams loading  {stream_line}",
    )


def compact_count(value: int | None) -> str:
    if value is None:
        return "—"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(int(value))


def _utc_sql(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _read_cpu_times():
    """(total_jiffies, idle_jiffies) from /proc/stat first ``cpu `` line."""
    with open("/proc/stat", encoding="utf-8") as fh:
        parts = fh.readline().split()
    nums = [int(x) for x in parts[1:11]]
    # user nice system idle iowait irq softirq steal guest guest_nice
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
    total = sum(nums[:8])
    return total, idle


def _read_mem_bytes():
    """(used, total, available) from /proc/meminfo."""
    total = avail = None
    with open("/proc/meminfo", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) * 1024
            elif line.startswith("MemAvailable:"):
                avail = int(line.split()[1]) * 1024
            if total is not None and avail is not None:
                break
    if total is None:
        return None, None, None
    if avail is None:
        avail = 0
    used = max(0, total - avail)
    return used, total, avail


@dataclass
class DatabaseStatus:
    connected: bool
    engine: str = ""
    database: str = ""
    host: str = ""
    username: str = ""
    error: str = ""
    rows_15m: int = 0
    bytes_15m: int | None = 0
    rows_1h: int = 0
    bytes_1h: int | None = 0
    rows_today: int = 0
    bytes_today: int | None = 0
    tables: str = ""
    extras: dict = field(default_factory=dict)
    rows_15m_growatt: int = 0
    rows_15m_tasmota: int = 0
    ingest_error: str = ""


def _empty_status(*, engine="", database="", host="", username="", error="") -> DatabaseStatus:
    return DatabaseStatus(
        connected=False,
        engine=engine,
        database=database,
        host=host,
        username=username,
        error=error,
        bytes_15m=None,
        bytes_1h=None,
        bytes_today=None,
    )


def _window_bounds():
    """UTC SQL strings: 15 minutes ago, 1 hour ago, London midnight today."""
    now = datetime.now(timezone.utc)
    try:
        import pytz
        london = pytz.timezone("Europe/London")
        now_l = datetime.now(london)
        today0 = london.localize(
            datetime.combine(now_l.date(), time.min)
        ).astimezone(timezone.utc)
    except Exception:
        today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        _utc_sql(now - timedelta(minutes=15)),
        _utc_sql(now - timedelta(hours=1)),
        _utc_sql(today0),
    )


def _sum_ingest(dst: DatabaseStatus, rows_15, bytes_15, rows_1h, bytes_1h, rows_td, bytes_td):
    dst.rows_15m += int(rows_15 or 0)
    dst.rows_1h += int(rows_1h or 0)
    dst.rows_today += int(rows_td or 0)
    if bytes_15 is None and dst.bytes_15m is not None:
        pass
    if bytes_15 is not None:
        dst.bytes_15m = int(dst.bytes_15m or 0) + int(bytes_15)
        dst.bytes_1h = int(dst.bytes_1h or 0) + int(bytes_1h or 0)
        dst.bytes_today = int(dst.bytes_today or 0) + int(bytes_td or 0)
    else:
        dst.bytes_15m = None
        dst.bytes_1h = None
        dst.bytes_today = None


def _ingest_table_error(table: str, exc: Exception) -> str:
    raw = str(exc).splitlines()[0].strip()[:180]
    if is_table_privilege_error(raw):
        return (
            f"This database login cannot read {table} (permission denied). "
            "Grant SELECT and INSERT on the logger tables, or use a dedicated "
            "dashboard user — not the MQTT broker account."
        )
    return f"{table}: {raw or exc.__class__.__name__}"


def _note_table_15m(status: DatabaseStatus, table: str, n) -> None:
    try:
        count = int(n or 0)
    except (TypeError, ValueError):
        count = 0
    if table == "growatt_readings":
        status.rows_15m_growatt = count
    elif table == "tasmota_readings":
        status.rows_15m_tasmota = count


def _poll_postgres(logger) -> DatabaseStatus:
    from psycopg2 import sql

    status = DatabaseStatus(
        connected=False,
        engine="PostgreSQL",
        database=str(logger.pg_db or ""),
        host=str(logger.pg_host or ""),
        username=str(logger.pg_user or ""),
    )
    conn = postgresql_connect(
        logger.pg_host, logger.pg_port, logger.pg_user, logger.pg_pass, logger.pg_db,
        autocommit=True, timeout=DB_CONNECT_TIMEOUT_S,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
            try:
                cur.execute("SET statement_timeout = 2500")
            except Exception:
                pass
        status.connected = True
        t15, t1h, tday = _window_bounds()
        names = []
        for table, ts_col in _INGEST_TABLES:
            q = sql.SQL(
                """
                SELECT
                    COUNT(*) FILTER (WHERE {ts} >= %s),
                    COALESCE(SUM(pg_column_size(t)) FILTER (WHERE {ts} >= %s), 0),
                    COUNT(*) FILTER (WHERE {ts} >= %s),
                    COALESCE(SUM(pg_column_size(t)) FILTER (WHERE {ts} >= %s), 0),
                    COUNT(*) FILTER (WHERE {ts} >= %s),
                    COALESCE(SUM(pg_column_size(t)) FILTER (WHERE {ts} >= %s), 0)
                FROM {table} AS t
                """
            ).format(
                ts=sql.Identifier(ts_col),
                table=sql.Identifier(table),
            )
            try:
                with conn.cursor() as cur:
                    cur.execute(q, (t15, t15, t1h, t1h, tday, tday))
                    row = cur.fetchone()
                if row:
                    _sum_ingest(status, *row)
                    _note_table_15m(status, table, row[0])
                    names.append(table)
            except Exception as exc:
                status.ingest_error = status.ingest_error or _ingest_table_error(table, exc)
                try:
                    conn.rollback()
                except Exception:
                    pass
        status.tables = ", ".join(names) if names else "no ingest tables"
        if not names and status.ingest_error:
            status.error = status.ingest_error
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return status


def _poll_mysql(logger) -> DatabaseStatus:
    status = DatabaseStatus(
        connected=False,
        engine="MySQL",
        database=str(logger.mysql_db or ""),
        host=str(logger.mysql_host or ""),
        username=str(logger.mysql_user or ""),
        bytes_15m=None,
        bytes_1h=None,
        bytes_today=None,
    )
    conn = mysql_connect(
        logger.mysql_host, logger.mysql_port,
        logger.mysql_user, logger.mysql_pass, logger.mysql_db,
        autocommit=True, timeout=DB_CONNECT_TIMEOUT_S,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        status.connected = True
        t15, t1h, tday = _window_bounds()
        names = []
        for table, ts_col in _INGEST_TABLES:
            q = (
                f"SELECT "
                f"SUM(CASE WHEN `{ts_col}` >= %s THEN 1 ELSE 0 END), "
                f"SUM(CASE WHEN `{ts_col}` >= %s THEN 1 ELSE 0 END), "
                f"SUM(CASE WHEN `{ts_col}` >= %s THEN 1 ELSE 0 END) "
                f"FROM `{table}`"
            )
            try:
                with conn.cursor() as cur:
                    cur.execute(q, (t15, t1h, tday))
                    row = cur.fetchone()
                if row:
                    _sum_ingest(
                        status,
                        row[0], None, row[1], None, row[2], None,
                    )
                    _note_table_15m(status, table, row[0])
                    names.append(table)
            except Exception as exc:
                status.ingest_error = status.ingest_error or _ingest_table_error(table, exc)
        status.tables = ", ".join(names) if names else "no ingest tables"
        if not names and status.ingest_error:
            status.error = status.ingest_error
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return status


def _poll_sqlite(logger) -> DatabaseStatus:
    path = str(logger.sqlite_path or "")
    status = DatabaseStatus(
        connected=False,
        engine="SQLite",
        database=path,
        host="file",
        username="",
        bytes_15m=None,
        bytes_1h=None,
        bytes_today=None,
    )
    if not path or not Path(path).is_file():
        status.error = "SQLite file not found"
        return status
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=DB_CONNECT_TIMEOUT_S)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        status.connected = True
        t15, t1h, tday = _window_bounds()
        names = []
        for table, ts_col in _INGEST_TABLES:
            q = (
                f"SELECT "
                f"SUM(CASE WHEN {ts_col} >= ? THEN 1 ELSE 0 END), "
                f"SUM(CASE WHEN {ts_col} >= ? THEN 1 ELSE 0 END), "
                f"SUM(CASE WHEN {ts_col} >= ? THEN 1 ELSE 0 END) "
                f"FROM {table}"
            )
            try:
                cur.execute(q, (t15, t1h, tday))
                row = cur.fetchone()
                if row:
                    _sum_ingest(
                        status,
                        row[0], None, row[1], None, row[2], None,
                    )
                    _note_table_15m(status, table, row[0])
                    names.append(table)
            except Exception as exc:
                status.ingest_error = status.ingest_error or _ingest_table_error(table, exc)
        status.tables = ", ".join(names) if names else "no ingest tables"
        if not names and status.ingest_error:
            status.error = status.ingest_error
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return status


def poll_logger_status(logger) -> DatabaseStatus:
    """Short-lived connection; never shares DataLogger's writer handle."""
    if logger is None:
        return _empty_status(error="No data logger")
    backend = None
    try:
        backend = logger._primary_storage_backend()
    except Exception:
        backend = None
    if backend is None:
        return _empty_status(error="No database enabled in Setup & Info")
    if hasattr(logger, "backend_ready") and not logger.backend_ready(backend):
        return _empty_status(
            engine={"pg": "PostgreSQL", "mysql": "MySQL", "sqlite": "SQLite"}.get(backend, backend),
            error="Database reconnect backoff — skipped this poll",
        )
    try:
        if backend == "pg":
            return _poll_postgres(logger)
        if backend == "mysql":
            return _poll_mysql(logger)
        return _poll_sqlite(logger)
    except Exception as exc:
        if backend == "pg":
            return _empty_status(
                engine="PostgreSQL",
                database=str(getattr(logger, "pg_db", "") or ""),
                host=str(getattr(logger, "pg_host", "") or ""),
                username=str(getattr(logger, "pg_user", "") or ""),
                error=str(exc),
            )
        if backend == "mysql":
            return _empty_status(
                engine="MySQL",
                database=str(getattr(logger, "mysql_db", "") or ""),
                host=str(getattr(logger, "mysql_host", "") or ""),
                username=str(getattr(logger, "mysql_user", "") or ""),
                error=str(exc),
            )
        return _empty_status(
            engine="SQLite",
            database=str(getattr(logger, "sqlite_path", "") or ""),
            host="file",
            error=str(exc),
        )


class _DatabaseWorker(QRunnable):
    def __init__(self, logger, finished_signal):
        super().__init__()
        self.setAutoDelete(True)
        self._logger = logger
        self._finished = finished_signal

    def run(self):
        try:
            result = poll_logger_status(self._logger)
        except Exception as exc:
            result = _empty_status(error=str(exc))
        try:
            self._finished.emit(result)
        except RuntimeError:
            pass


class SystemStatusBar(QFrame):
    """Compact two-line strip for the main-window footer.

    Row 1: DB health / identity | Octopus Live API link | ingest (15m / 1h / London today)
    Row 2: CPU now + rolling 1h average | memory now + 1h avg/max/available
    """

    SAMPLE_SECONDS = 10
    HISTORY_SECONDS = 3600
    DB_POLL_SECONDS = 30

    _db_finished = Signal(object)

    def __init__(self, data_logger, parent: QWidget | None = None):
        super().__init__(parent)
        self.data_logger = data_logger
        self.logical_cores = os.cpu_count() or 1
        history_samples = max(1, self.HISTORY_SECONDS // self.SAMPLE_SECONDS)
        self.cpu_history = deque(maxlen=history_samples)
        self.memory_history = deque(maxlen=history_samples)
        self._prev_cpu = None
        self._proc_sampler = ProcessResourceSampler()
        self._proc_cpu = "—"
        self._proc_mem = "—"
        self.db_query_running = False
        self._pool = QThreadPool.globalInstance()
        self._db_finished.connect(self._database_status_received)
        self.last_status: DatabaseStatus | None = None

        self._build_ui()
        try:
            self._prev_cpu = _read_cpu_times()
        except (OSError, ValueError, IndexError):
            self._prev_cpu = None

        self.system_timer = QTimer(self)
        self.system_timer.timeout.connect(self._update_system_metrics)
        self.system_timer.start(self.SAMPLE_SECONDS * 1000)

        self.db_timer = QTimer(self)
        self.db_timer.timeout.connect(self._request_database_status)
        self.db_timer.start(self.DB_POLL_SECONDS * 1000)

        QTimer.singleShot(400, self._update_system_metrics)

    def _build_ui(self):
        self.setObjectName("systemStatusBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QGridLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setHorizontalSpacing(18)
        layout.setVerticalSpacing(2)

        self.db_label = QLabel("● DB  Checking…")
        self.db_label.setObjectName("dbStatus")
        self.octopus_label = QLabel("● Octopus  —")
        self.octopus_label.setObjectName("octopusStatus")
        self.octopus_label.setProperty("octopusHealth", "idle")
        self.octopus_label.setToolTip(
            "Last Octopus Live API result. Green means GraphQL answered. "
            "Amber means only the slower REST meter, or the link has gone quiet. "
            "Red means the last request failed."
        )
        self.ingest_label = QLabel("INGEST  15m —   1h —   Today —")
        self.cpu_label = QLabel(
            f"CPU  — / —c   1h avg — / —c   [{self.logical_cores} logical]"
        )
        self.memory_label = QLabel("MEM  —   1h avg —   max —   avail —")
        for lbl in (
            self.db_label, self.octopus_label, self.ingest_label,
            self.cpu_label, self.memory_label,
        ):
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addWidget(self.db_label, 0, 0)
        layout.addWidget(self.octopus_label, 0, 1)
        layout.addWidget(self.ingest_label, 0, 2)
        layout.addWidget(self.cpu_label, 1, 0)
        layout.addWidget(self.memory_label, 1, 2)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 2)
        self.setMinimumHeight(44)
        self.setMaximumHeight(62)

    def refresh_db_now(self):
        """Call after Setup loads DB settings so the first poll is not empty."""
        self._request_database_status()

    def set_octopus_link(self, view: dict) -> None:
        """Mirror Octopus Live's last API result. ``view`` comes from that tab."""
        if not isinstance(view, dict):
            return
        short = str(view.get("short") or "—")
        health = str(view.get("health") or "idle")
        self.octopus_label.setText(f"● Octopus  {short}")
        self.octopus_label.setProperty("octopusHealth", health)
        tip = str(view.get("tooltip") or "").strip()
        if tip:
            self.octopus_label.setToolTip(tip)
        self._repolish(self.octopus_label)

    def _update_system_metrics(self):
        try:
            self._proc_cpu, self._proc_mem = self._proc_sampler.sample()
        except Exception:
            pass
        cpu_percent = None
        try:
            cur = _read_cpu_times()
            prev = self._prev_cpu
            self._prev_cpu = cur
            if prev is not None:
                d_total = cur[0] - prev[0]
                d_idle = cur[1] - prev[1]
                if d_total > 0:
                    cpu_percent = max(0.0, min(100.0, (1.0 - d_idle / d_total) * 100.0))
        except (OSError, ValueError, IndexError, TypeError):
            self._prev_cpu = None

        used = total = avail = None
        try:
            used, total, avail = _read_mem_bytes()
        except (OSError, ValueError, IndexError):
            pass

        if cpu_percent is not None:
            self.cpu_history.append(cpu_percent)
            cpu_avg = sum(self.cpu_history) / len(self.cpu_history)
            cores_now = (cpu_percent / 100.0) * self.logical_cores
            cores_avg = (cpu_avg / 100.0) * self.logical_cores
            self.cpu_label.setText(
                f"CPU  {cpu_percent:.1f}% / {cores_now:.2f}c   "
                f"1h avg {cpu_avg:.1f}% / {cores_avg:.2f}c   "
                f"[{self.logical_cores} logical]"
            )
            self.cpu_label.setToolTip(
                "Whole machine (all programs), not just this dashboard.\n"
                f"Now {cpu_percent:.1f}% of every core together "
                f"({cores_now:.2f} of {self.logical_cores} logical cores busy).\n"
                "1h avg is the mean of 10-second samples (up to the last hour).\n"
                f"This Energy Dashboard process: CPU {self._proc_cpu}  ·  RAM {self._proc_mem}"
            )

        if used is not None and total:
            self.memory_history.append(used)
            memory_avg = sum(self.memory_history) / len(self.memory_history)
            memory_max = max(self.memory_history)
            pct = 100.0 * used / total if total else 0.0
            self.memory_label.setText(
                f"MEM  {human_bytes(used)}/{human_bytes(total)} {pct:.1f}%   "
                f"1h avg {human_bytes(memory_avg)}   "
                f"max {human_bytes(memory_max)}   "
                f"avail {human_bytes(avail)}"
            )
            self.memory_label.setToolTip(
                "Whole machine RAM (MemTotal − MemAvailable).\n"
                f"Used {human_bytes(used)} of {human_bytes(total)} "
                f"({pct:.1f}%). Available {human_bytes(avail)}.\n"
                "1h avg / max are used-RAM samples every 10 seconds.\n"
                f"This Energy Dashboard process RSS: {self._proc_mem}"
            )

    def _request_database_status(self):
        if self.db_query_running:
            return
        self.db_query_running = True
        worker = _DatabaseWorker(self.data_logger, self._db_finished)
        self._pool.start(worker)

    @Slot(object)
    def _database_status_received(self, status: DatabaseStatus):
        self.db_query_running = False
        if status is None:
            return
        self.last_status = status
        ident = self._identity_text(status)
        if status.connected:
            self.db_label.setText(f"● DB  {ident}")
            self.db_label.setProperty("dbHealth", "ok")
            self.db_label.setToolTip(
                f"{status.engine} connection healthy.\n"
                f"Ingest windows use UTC insert time on {status.tables or '—'}.\n"
                "Today is Europe/London midnight."
            )
            denied = bool(status.ingest_error)
            if denied:
                self.ingest_label.setText("INGEST  no table access")
                self.ingest_label.setProperty("ingestHealth", "bad")
                self.ingest_label.setToolTip(status.ingest_error)
            else:
                self.ingest_label.setText(self._ingest_text(status))
                dry = int(status.rows_15m or 0) <= 0
                self.ingest_label.setProperty("ingestHealth", "dry" if dry else "ok")
                self.ingest_label.setToolTip(
                    "Rows (and bytes, on PostgreSQL) whose stored timestamp falls "
                    "in the last 15 minutes, last hour, and since London midnight.\n"
                    "growatt_readings + tasmota_readings — timestamp is when the "
                    "logger wrote the row, not a delayed device clock."
                )
            self._repolish(self.ingest_label)
        else:
            self.db_label.setText(f"● DB  DISCONNECTED   {ident}".rstrip())
            self.db_label.setProperty("dbHealth", "bad")
            self.db_label.setToolTip(status.error or "Database unavailable")
            self.ingest_label.setText("INGEST  unavailable")
            self.ingest_label.setProperty("ingestHealth", "bad")
            self._repolish(self.ingest_label)
            self.ingest_label.setToolTip(status.error or "Database unavailable")
        self._repolish(self.db_label)

    @staticmethod
    def _repolish(widget):
        st = widget.style()
        st.unpolish(widget)
        st.polish(widget)
        widget.update()

    @staticmethod
    def _identity_text(status: DatabaseStatus) -> str:
        eng = status.engine or "DB"
        if (status.engine or "").lower() == "sqlite" or status.host == "file":
            name = status.database or "—"
            if len(name) > 42:
                name = "…" + name[-40:]
            return f"{eng}  {name}"
        db = status.database or "—"
        host = status.host or "—"
        user = status.username or "—"
        return f"{eng}  {db} @ {host}   user: {user}"

    @staticmethod
    def _ingest_text(status: DatabaseStatus) -> str:
        def chunk(label, nbytes, nrows):
            n = compact_count(nrows)
            if nbytes is None:
                return f"{label} {n}"
            return f"{label} {human_bytes(nbytes)}/{n}"

        return (
            "INGEST  "
            f"{chunk('15m', status.bytes_15m, status.rows_15m)}   "
            f"{chunk('1h', status.bytes_1h, status.rows_1h)}   "
            f"{chunk('Today', status.bytes_today, status.rows_today)}"
        )


__all__ = ["SystemStatusBar", "human_bytes", "compact_count", "tray_database_lines"]
