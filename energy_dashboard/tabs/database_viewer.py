"""
Energy Dashboard — `tabs/database_viewer.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.db.health_stats import collect_health_stats
from energy_dashboard.dialogs.db_health import DbHealthDialog
class DatabaseViewerTab(QWidget):
    """Read-only browse of DataLogger tables using Parameters → Database Export fields."""

    TABLES = ("growatt_readings", "tasmota_readings", "tasmota_devices", "octopus_readings")

    def __init__(self, dashboard):
        super().__init__()
        self.dash = dashboard
        self._inv = Invoker(self)
        self._fetching = False
        self._health_dialog = None
        self.build_ui()

    def build_ui(self):
        lay = QVBoxLayout(self)
        box = QGroupBox("Browse logged data")
        row = QHBoxLayout()
        row.addWidget(QLabel("Backend:"))
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["SQLite", "MySQL", "PostgreSQL"])
        row.addWidget(self.backend_combo)
        row.addWidget(QLabel("Table:"))
        self.table_combo = QComboBox()
        self.table_combo.addItems(self.TABLES)
        row.addWidget(self.table_combo)
        row.addWidget(QLabel("Max rows:"))
        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(50, 10000)
        self.spin_limit.setValue(500)
        row.addWidget(self.spin_limit)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_data)
        row.addWidget(self.refresh_btn)
        self.status_btn = QPushButton("Status")
        self.status_btn.clicked.connect(self.show_status)
        row.addWidget(self.status_btn)
        self.status_lbl = QLabel(
            "Connection details are taken from the Parameters tab (Database Export). "
            "Run Setup Database there first if tables are missing."
        )
        self.status_lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
        self.status_lbl.setWordWrap(True)
        row.addWidget(self.status_lbl, 1)
        box.setLayout(row)
        lay.addWidget(box)

        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.table)
        qtable_attach_column_width_persistence(self.table)

    def _settings(self):
        return QSettings("PowerModel", "EnergyDashboard2")

    def _viewer_access_key(self, backend: str) -> str:
        return f"db_viewer/last_access/{backend}"

    def _record_viewer_access(self, backend: str | None = None):
        backend = backend or self.backend_combo.currentText()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._settings().setValue(self._viewer_access_key(backend), ts)

    def _viewer_last_access(self, backend: str | None = None) -> str | None:
        backend = backend or self.backend_combo.currentText()
        val = self._settings().value(self._viewer_access_key(backend))
        return str(val) if val else None

    def show_status(self):
        backend = self.backend_combo.currentText()
        self._record_viewer_access(backend)
        cap = self._capture_params()
        dlg = DbHealthDialog(self, backend)
        dlg.set_refresh_callback(lambda: self._load_health_stats(dlg, backend, cap))
        self._health_dialog = dlg
        dlg.show_loading()
        self._load_health_stats(dlg, backend, cap)
        dlg.exec()

    def _load_health_stats(self, dlg, backend, cap):
        def _worker():
            stats = collect_health_stats(backend, cap)
            viewer_ts = self._viewer_last_access(backend)
            self._inv.invoke(
                lambda s=stats, v=viewer_ts: dlg.apply_stats(s, v)
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _capture_params(self):
        pt = self.dash.parameters_tab
        return {
            'sqlite_path': pt.ed_sqlite_path.text().strip(),
            'mysql_host': pt.ed_mysql_host.text().strip(),
            'mysql_port': pt.ed_mysql_port.value(),
            'mysql_user': pt.ed_mysql_user.text().strip(),
            'mysql_pass': pt.ed_mysql_pass.text(),
            'mysql_db': pt.ed_mysql_db.text().strip(),
            'pg_host': pt.ed_pg_host.text().strip(),
            'pg_port': pt.ed_pg_port.value(),
            'pg_user': pt.ed_pg_user.text().strip(),
            'pg_pass': pt.ed_pg_pass.text(),
            'pg_db': pt.ed_pg_db.text().strip(),
        }

    def refresh_data(self):
        if self._fetching:
            return
        self._fetching = True
        self.refresh_btn.setEnabled(False)
        self.dash.set_status("Loading database…")
        cap = self._capture_params()
        backend = self.backend_combo.currentText()
        table = self.table_combo.currentText()
        limit = self.spin_limit.value()
        threading.Thread(
            target=self._fetch_thread,
            args=(backend, table, limit, cap),
            daemon=True,
        ).start()

    def _fetch_thread(self, backend, table, limit, cap):
        cols, rows = [], []
        err = None
        try:
            if table not in self.TABLES:
                raise ValueError("Invalid table name")
            lim = max(1, min(int(limit), 10000))
            q = f"SELECT * FROM {table} ORDER BY id DESC LIMIT {lim}"
            if backend == "SQLite":
                path = cap['sqlite_path'] or str(Path.home() / "energy_dashboard.db")
                conn = sqlite3.connect(path)
                try:
                    cur = conn.cursor()
                    cur.execute(q)
                    cols = [d[0] for d in cur.description]
                    rows = cur.fetchall()
                finally:
                    conn.close()
            elif backend == "MySQL":
                import pymysql
                conn = pymysql.connect(
                    host=cap['mysql_host'] or "localhost",
                    port=int(cap['mysql_port']),
                    user=cap['mysql_user'],
                    password=cap['mysql_pass'],
                    database=cap['mysql_db'] or "energy",
                    charset='utf8mb4',
                )
                try:
                    with conn.cursor() as cur:
                        cur.execute(q)
                        cols = [d[0] for d in cur.description]
                        rows = cur.fetchall()
                finally:
                    conn.close()
            else:
                import psycopg2
                conn = psycopg2.connect(
                    host=cap['pg_host'] or "localhost",
                    port=int(cap['pg_port']),
                    dbname=cap['pg_db'] or "powermon",
                    user=cap['pg_user'],
                    password=cap['pg_pass'],
                )
                try:
                    with conn.cursor() as cur:
                        cur.execute(q)
                        cols = [d[0] for d in cur.description]
                        rows = cur.fetchall()
                finally:
                    conn.close()
        except ImportError as e:
            err = str(e)
        except Exception as e:
            err = str(e)
        self._inv.invoke(
            lambda c=cols, r=rows, e=err, t=table: self._apply_result(c, r, e, t))

    def _apply_result(self, cols, rows, err, sql_table=""):
        self._fetching = False
        self.refresh_btn.setEnabled(True)
        if err:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.table.clearContents()
            self.status_lbl.setText(f"Error: {err}")
            self.status_lbl.setStyleSheet("color: #f38ba8; font-size: 11px;")
            self.dash.set_status(f"Database viewer error: {err}")
            return
        self.status_lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
        self.status_lbl.setText(f"{len(rows)} row(s) — newest first by id")
        self._record_viewer_access()
        self.table.clear()
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                txt = "" if val is None else str(val)
                self.table.setItem(r, c, QTableWidgetItem(txt))
        _db_key = f"dbview|{sql_table}"
        qtable_set_column_width_key(self.table, _db_key)
        qtable_prepare_interactive_columns(self.table)
        qtable_restore_column_widths(self.table, _db_key, resize_if_no_saved=True)
        self.dash.set_status(f"Database viewer: loaded {len(rows)} row(s).")


# ==================== CONSOLE TAB ====================


__all__ = [n for n in globals() if not n.startswith('__')]
