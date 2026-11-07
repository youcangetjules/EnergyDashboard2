"""Flexible Chart View — plot any database column against any other."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from energy_dashboard.common import *
from energy_dashboard.db.full_schema import TABLE_SUMMARIES

# ── Colour palette for multi-series charts ────────────────────────────
_CHART_COLORS = (
    '#89b4fa', '#fab387', '#a6e3a1', '#f38ba8',
    '#cba6f7', '#f9e2af', '#94e2d5', '#eba0ac',
    '#74c7ec', '#f5c2e7',
)

# ── Preset query templates ────────────────────────────────────────────
# (label, sql, description)
_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    ("(none)", "", ""),
    (
        "Daily import spend (Agile)",
        "SELECT o.interval_start, o.import_kwh, a.price_pence,\n"
        "       o.import_kwh * a.price_pence / 100.0 AS cost_pounds\n"
        "FROM octopus_readings o\n"
        "JOIN agile_price_snapshots a\n"
        "  ON o.interval_start = a.valid_from AND a.direction = 'import'\n"
        "ORDER BY o.interval_start\n"
        "LIMIT 5000",
        "Half-hourly import cost using Agile spot prices",
    ),
    (
        "SOC history (7 days)",
        "SELECT timestamp, soc_pct\n"
        "FROM growatt_readings\n"
        "WHERE timestamp >= datetime('now', '-7 days')\n"
        "ORDER BY timestamp",
        "Battery state of charge over the last week",
    ),
    (
        "PV generation vs load",
        "SELECT timestamp, pv_power_kw, load_power_kw\n"
        "FROM growatt_readings\n"
        "WHERE timestamp >= datetime('now', '-3 days')\n"
        "ORDER BY timestamp\n"
        "LIMIT 10000",
        "Compare solar generation with house load",
    ),
    (
        "Tasmota device power (24h)",
        "SELECT timestamp, device_name, power_w\n"
        "FROM tasmota_readings\n"
        "WHERE timestamp >= datetime('now', '-1 day')\n"
        "ORDER BY timestamp\n"
        "LIMIT 10000",
        "All Tasmota device wattage in the last 24 hours",
    ),
    (
        "Grid import vs export",
        "SELECT timestamp, grid_power_kw\n"
        "FROM growatt_readings\n"
        "WHERE timestamp >= datetime('now', '-3 days')\n"
        "ORDER BY timestamp\n"
        "LIMIT 10000",
        "Positive = import, negative = export",
    ),
    (
        "Agile price distribution",
        "SELECT valid_from, price_pence\n"
        "FROM agile_price_snapshots\n"
        "WHERE direction = 'import'\n"
        "ORDER BY valid_from DESC\n"
        "LIMIT 2000",
        "Recent import prices for scatter or time-series view",
    ),
    (
        "Battery charge/discharge vs price",
        "SELECT g.timestamp, g.battery_power_kw, a.price_pence\n"
        "FROM growatt_readings g\n"
        "LEFT JOIN agile_price_snapshots a\n"
        "  ON a.valid_from <= g.timestamp AND a.valid_to > g.timestamp\n"
        "     AND a.direction = 'import'\n"
        "WHERE g.timestamp >= datetime('now', '-3 days')\n"
        "ORDER BY g.timestamp\n"
        "LIMIT 10000",
        "Was the battery charging during cheap slots?",
    ),
    (
        "Daily energy totals",
        "SELECT date(timestamp) AS day,\n"
        "       MAX(pv_today_kwh) AS pv_kwh,\n"
        "       MAX(charge_today_kwh) AS charge_kwh,\n"
        "       MAX(discharge_today_kwh) AS discharge_kwh\n"
        "FROM growatt_readings\n"
        "GROUP BY date(timestamp)\n"
        "ORDER BY day DESC\n"
        "LIMIT 90",
        "Daily PV, charge, discharge totals from growatt_readings",
    ),
    (
        "PV string comparison",
        "SELECT time, pv_string1, pv_string2,\n"
        "       power_string1, power_string2\n"
        "FROM pv_string_charge\n"
        "WHERE time >= datetime('now', '-3 days')\n"
        "ORDER BY time\n"
        "LIMIT 10000",
        "Compare the two PV strings side by side",
    ),
    (
        "Shadow trial savings",
        "SELECT day_date, actual_cost_p, shadow_cost_p, baseline_cost_p\n"
        "FROM optimiser_shadow_scores\n"
        "ORDER BY day_date\n"
        "LIMIT 120",
        "Compare actual vs optimiser shadow costs",
    ),
)

_FORBIDDEN = frozenset({
    'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'TRUNCATE',
    'CREATE', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE',
})


class FlexibleChartTab(QWidget):
    """General-purpose chart view — query any table, pick axes, draw."""

    TABLES = tuple(name for name, _blurb in TABLE_SUMMARIES)

    def __init__(self, dashboard):
        super().__init__()
        self.dash = dashboard
        self._inv = Invoker(self)
        self._fetching = False
        self._df: pl.DataFrame | None = None
        self._y_combos: list[QComboBox] = []
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        # ── Row 1: mode toggle, template, run button, status ──────────
        r1 = QHBoxLayout()
        self._mode_group = QButtonGroup(self)
        self._rb_builder = QRadioButton("Builder")
        self._rb_sql = QRadioButton("SQL")
        self._rb_builder.setChecked(True)
        self._mode_group.addButton(self._rb_builder, 0)
        self._mode_group.addButton(self._rb_sql, 1)
        r1.addWidget(self._rb_builder)
        r1.addWidget(self._rb_sql)

        r1.addSpacing(16)
        r1.addWidget(QLabel("Template:"))
        self._template_combo = QComboBox()
        for label, _sql, desc in _TEMPLATES:
            self._template_combo.addItem(label)
        self._template_combo.setToolTip("Load a preset query into the SQL editor")
        apply_combo_field_motif(self._template_combo, width=220)
        r1.addWidget(self._template_combo)

        r1.addSpacing(16)
        self._run_btn = QPushButton("Run Query")
        _apply_primary_button_style(self._run_btn)
        r1.addWidget(self._run_btn)

        r1.addSpacing(16)
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
        self._status_lbl.setWordWrap(True)
        r1.addWidget(self._status_lbl, 1)
        root.addLayout(r1)

        # ── Row 2: stacked widget (builder / SQL editor) ─────────────
        self._stack = QStackedWidget()

        # Builder panel
        builder = QWidget()
        bl = QHBoxLayout(builder)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(QLabel("Table:"))
        self._tbl_combo = QComboBox()
        for name, blurb in TABLE_SUMMARIES:
            self._tbl_combo.addItem(f"{name}", name)
        self._tbl_combo.setMaxVisibleItems(max(len(TABLE_SUMMARIES), 1))
        self._tbl_combo.setToolTip("Database table to query")
        apply_combo_field_motif(self._tbl_combo, width=200)
        bl.addWidget(self._tbl_combo)

        bl.addSpacing(8)
        bl.addWidget(QLabel("Columns:"))
        self._cols_edit = QLineEdit("*")
        self._cols_edit.setPlaceholderText("* or col1, col2, …")
        self._cols_edit.setMinimumWidth(140)
        bl.addWidget(self._cols_edit)

        bl.addSpacing(8)
        bl.addWidget(QLabel("WHERE:"))
        self._where_edit = QLineEdit()
        self._where_edit.setPlaceholderText("e.g. soc_pct > 50")
        self._where_edit.setMinimumWidth(160)
        bl.addWidget(self._where_edit)

        bl.addSpacing(8)
        bl.addWidget(QLabel("ORDER BY:"))
        self._order_edit = QLineEdit()
        self._order_edit.setPlaceholderText("e.g. timestamp DESC")
        self._order_edit.setMinimumWidth(130)
        bl.addWidget(self._order_edit)

        bl.addSpacing(8)
        bl.addWidget(QLabel("LIMIT:"))
        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(50, 100000)
        self._limit_spin.setValue(5000)
        apply_spin_field_motif(self._limit_spin, width=90)
        bl.addWidget(self._limit_spin)
        bl.addStretch(1)
        self._stack.addWidget(builder)

        # SQL editor panel
        sql_panel = QWidget()
        sl = QVBoxLayout(sql_panel)
        sl.setContentsMargins(0, 0, 0, 0)
        self._sql_edit = QTextEdit()
        self._sql_edit.setMaximumHeight(110)
        self._sql_edit.setPlaceholderText(
            "SELECT timestamp, soc_pct FROM growatt_readings\n"
            "WHERE timestamp >= datetime('now', '-7 days')\n"
            "ORDER BY timestamp LIMIT 5000"
        )
        _apply_dark_log_view(self._sql_edit, object_name='flexChartSql',
                             extra_qss='font-family: monospace; font-size: 12px;')
        sl.addWidget(self._sql_edit)
        self._stack.addWidget(sql_panel)

        root.addWidget(self._stack)

        # ── Row 3: axis assignment + chart type ──────────────────────
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("X axis:"))
        self._x_combo = QComboBox()
        self._x_combo.setToolTip("Column for the horizontal axis")
        apply_combo_field_motif(self._x_combo, width=160)
        r3.addWidget(self._x_combo)

        r3.addSpacing(12)
        r3.addWidget(QLabel("Y axis:"))
        y0 = QComboBox()
        y0.setToolTip("Column for the vertical axis")
        apply_combo_field_motif(y0, width=160)
        self._y_combos.append(y0)
        r3.addWidget(y0)

        self._add_y_btn = QPushButton("+Y")
        self._add_y_btn.setToolTip("Add another Y series")
        self._add_y_btn.setFixedWidth(36)
        r3.addWidget(self._add_y_btn)

        r3.addSpacing(12)
        r3.addWidget(QLabel("Chart:"))
        self._chart_type = QComboBox()
        self._chart_type.addItems(["Line", "Scatter", "Bar", "Step", "Area"])
        apply_combo_field_motif(self._chart_type, width=100)
        r3.addWidget(self._chart_type)

        r3.addSpacing(12)
        self._draw_btn = QPushButton("Draw")
        _apply_primary_button_style(self._draw_btn)
        r3.addWidget(self._draw_btn)

        r3.addStretch(1)
        self._axis_row = r3
        root.addLayout(r3)

        # ── Row 4: chart canvas ──────────────────────────────────────
        self.fig = Figure(figsize=(12, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        _style_ax_dark(self.ax, self.fig)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding,
        )
        self.canvas.setMinimumHeight(260)
        root.addWidget(self.canvas, 1)

        toolbar = DarkNavigationToolbar(self.canvas, self)
        root.addWidget(toolbar, 0)

        # ── Signals ──────────────────────────────────────────────────
        self._mode_group.idToggled.connect(self._on_mode_changed)
        self._template_combo.currentIndexChanged.connect(self._on_template)
        self._run_btn.clicked.connect(self._run_query)
        self._draw_btn.clicked.connect(self._draw_chart)
        self._add_y_btn.clicked.connect(self._add_y_series)

    # ── Mode switching ───────────────────────────────────────────────
    def _on_mode_changed(self, btn_id: int, checked: bool):
        if checked:
            self._stack.setCurrentIndex(btn_id)

    # ── Template loading ─────────────────────────────────────────────
    def _on_template(self, idx: int):
        if idx <= 0 or idx >= len(_TEMPLATES):
            return
        _label, sql, desc = _TEMPLATES[idx]
        self._sql_edit.setPlainText(sql)
        self._rb_sql.setChecked(True)
        self._status_lbl.setText(desc)
        self._status_lbl.setStyleSheet("color: #6c7086; font-size: 11px;")

    # ── Add extra Y series combo ─────────────────────────────────────
    def _add_y_series(self):
        if len(self._y_combos) >= 6:
            return
        combo = QComboBox()
        apply_combo_field_motif(combo, width=160)
        # Populate from existing columns
        if self._df is not None:
            for col in self._df.columns:
                combo.addItem(col)
        # Insert before the +Y button in the axis row layout
        insert_pos = self._axis_row.indexOf(self._add_y_btn)
        self._axis_row.insertWidget(insert_pos, combo)
        self._y_combos.append(combo)

    # ── SQL construction ─────────────────────────────────────────────
    def _build_sql(self) -> str | None:
        if self._rb_sql.isChecked():
            sql = self._sql_edit.toPlainText().strip()
        else:
            table = self._tbl_combo.currentData()
            if not table:
                return None
            cols = self._cols_edit.text().strip() or "*"
            where = self._where_edit.text().strip()
            order = self._order_edit.text().strip()
            limit = self._limit_spin.value()
            sql = f"SELECT {cols} FROM {table}"
            if where:
                sql += f" WHERE {where}"
            if order:
                sql += f" ORDER BY {order}"
            sql += f" LIMIT {limit}"

        if not sql:
            self._set_error("Empty query.")
            return None

        first_word = sql.lstrip().split()[0].upper()
        if first_word in _FORBIDDEN:
            self._set_error(f"Only SELECT queries are allowed (got {first_word}).")
            return None
        if first_word not in ('SELECT', 'WITH'):
            self._set_error(f"Query must start with SELECT or WITH (got {first_word}).")
            return None
        return sql

    # ── Query execution ──────────────────────────────────────────────
    def _run_query(self):
        if self._fetching:
            return
        sql = self._build_sql()
        if sql is None:
            return
        self._fetching = True
        self._run_btn.setEnabled(False)
        self._status_lbl.setText("Running query\u2026")
        self._status_lbl.setStyleSheet("color: #6c7086; font-size: 11px;")

        cap = self._capture_params()
        backend = self._detect_backend()
        threading.Thread(
            target=self._query_thread,
            args=(sql, backend, cap),
            daemon=True,
        ).start()

    def _detect_backend(self) -> str:
        dl = getattr(self.dash, 'data_logger', None)
        if dl is not None:
            be = dl._primary_storage_backend()
            if be:
                return {'sqlite': 'SQLite', 'mysql': 'MySQL', 'pg': 'PostgreSQL'}.get(be, 'SQLite')
        return 'SQLite'

    def _capture_params(self) -> dict:
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

    def _query_thread(self, sql: str, backend: str, cap: dict):
        try:
            if backend == 'SQLite':
                path = cap['sqlite_path'] or str(Path.home() / "energy_dashboard.db")
                conn = sqlite3.connect(path)
                try:
                    df = pl.read_database(sql, connection=conn,
                                          infer_schema_length=None)
                finally:
                    conn.close()
            elif backend == 'MySQL':
                from energy_dashboard.db.connect_probe import mysql_connect
                conn = mysql_connect(
                    cap['mysql_host'] or 'localhost',
                    cap['mysql_port'],
                    cap['mysql_user'],
                    cap['mysql_pass'],
                    cap['mysql_db'] or 'energy',
                )
                try:
                    df = pl.read_database(sql, connection=conn,
                                          infer_schema_length=None)
                finally:
                    conn.close()
            else:
                from energy_dashboard.db.connect_probe import postgresql_connect
                conn = postgresql_connect(
                    cap['pg_host'] or 'localhost',
                    cap['pg_port'],
                    cap['pg_user'],
                    cap['pg_pass'],
                    cap['pg_db'] or 'powermon',
                )
                try:
                    df = pl.read_database(sql, connection=conn,
                                          infer_schema_length=None)
                finally:
                    conn.close()
            self._inv.invoke(lambda d=df: self._apply_result(d))
        except Exception as exc:
            msg = str(exc)
            self._inv.invoke(lambda m=msg: self._apply_error(m))

    def _apply_result(self, df: pl.DataFrame):
        self._fetching = False
        self._run_btn.setEnabled(True)
        self._df = df
        cols = df.columns

        # Populate axis combos
        self._x_combo.blockSignals(True)
        self._x_combo.clear()
        for c in cols:
            self._x_combo.addItem(c)
        self._x_combo.blockSignals(False)

        for yc in self._y_combos:
            yc.blockSignals(True)
            yc.clear()
            for c in cols:
                yc.addItem(c)
            yc.blockSignals(False)

        # Auto-select: first temporal-looking column for X, first numeric for Y
        temporal_idx = None
        numeric_idx = None
        for i, c in enumerate(cols):
            dtype = df.dtypes[i]
            if temporal_idx is None and (
                dtype in (pl.Date, pl.Time)
                or str(dtype).startswith('Datetime')
                or c.lower() in ('timestamp', 'interval_start', 'valid_from',
                                 'fetched_at', 'time', 'day_date', 'logged_at')
            ):
                temporal_idx = i
            if numeric_idx is None and dtype.is_numeric():
                numeric_idx = i

        if temporal_idx is not None:
            self._x_combo.setCurrentIndex(temporal_idx)
        if numeric_idx is not None and self._y_combos:
            self._y_combos[0].setCurrentIndex(numeric_idx)

        be = self._detect_backend()
        self._status_lbl.setText(
            f"{len(df)} rows, {len(cols)} columns ({be})"
        )
        self._status_lbl.setStyleSheet("color: #a6e3a1; font-size: 11px;")

    def _apply_error(self, err: str):
        self._fetching = False
        self._run_btn.setEnabled(True)
        self._set_error(err)

    def _set_error(self, msg: str):
        self._status_lbl.setText(msg)
        self._status_lbl.setStyleSheet("color: #f38ba8; font-size: 11px;")

    # ── Chart drawing ────────────────────────────────────────────────
    def _draw_chart(self):
        if self._df is None or self._df.is_empty():
            self._set_error("No data — run a query first.")
            return

        x_col = self._x_combo.currentText()
        y_cols = []
        for yc in self._y_combos:
            txt = yc.currentText()
            if txt and txt != x_col and txt not in y_cols:
                y_cols.append(txt)
        if not y_cols:
            self._set_error("Select at least one Y column different from X.")
            return

        chart_type = self._chart_type.currentText()
        df = self._df

        # Extract X values
        try:
            x_series = df[x_col]
        except Exception as exc:
            self._set_error(f"X column error: {exc}")
            return

        # Detect if X is temporal
        x_is_temporal = (
            x_series.dtype in (pl.Date, pl.Time)
            or str(x_series.dtype).startswith('Datetime')
        )
        # Try parsing string timestamps
        if not x_is_temporal and x_series.dtype == pl.Utf8:
            try:
                test = datetime.strptime(str(x_series[0])[:19], "%Y-%m-%d %H:%M:%S")
                x_is_temporal = True
            except (ValueError, TypeError, IndexError):
                pass

        import matplotlib.dates as mdates

        if x_is_temporal:
            if x_series.dtype == pl.Utf8:
                x_vals = []
                for v in x_series.to_list():
                    try:
                        x_vals.append(datetime.strptime(str(v)[:19], "%Y-%m-%d %H:%M:%S"))
                    except (ValueError, TypeError):
                        x_vals.append(None)
            else:
                x_vals = x_series.to_list()
        else:
            x_vals = x_series.to_list()

        # Draw
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        _style_ax_dark(ax, self.fig)

        for ci, y_col in enumerate(y_cols):
            try:
                y_vals = df[y_col].to_list()
            except Exception:
                continue
            colour = _CHART_COLORS[ci % len(_CHART_COLORS)]
            label = y_col

            # Filter out paired Nones
            if x_is_temporal:
                pairs = [(x, y) for x, y in zip(x_vals, y_vals)
                         if x is not None and y is not None]
                if not pairs:
                    continue
                xp, yp = zip(*pairs)
            else:
                xp, yp = x_vals, y_vals

            if chart_type == "Line":
                ax.plot(xp, yp, color=colour, linewidth=1.5, label=label)
            elif chart_type == "Scatter":
                ax.scatter(xp, yp, color=colour, s=8, alpha=0.7, label=label)
            elif chart_type == "Bar":
                import numpy as np
                xr = np.arange(len(xp))
                width = 0.8 / max(len(y_cols), 1)
                ax.bar(xr + ci * width, yp, width, color=colour, alpha=0.85, label=label)
                if ci == 0 and x_is_temporal:
                    step = max(1, len(xr) // 15)
                    ax.set_xticks(xr[::step])
                    ax.set_xticklabels(
                        [str(xp[i])[:10] for i in range(0, len(xp), step)],
                        rotation=30, ha='right', fontsize=8,
                    )
            elif chart_type == "Step":
                ax.step(xp, yp, color=colour, linewidth=1.5, where='post', label=label)
            elif chart_type == "Area":
                ax.fill_between(xp, yp, alpha=0.3, color=colour, label=label)
                ax.plot(xp, yp, color=colour, linewidth=1.0)

        if x_is_temporal and chart_type != "Bar":
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b %H:%M'))
            self.fig.autofmt_xdate(rotation=30, ha='right')

        ax.set_xlabel(x_col)
        if len(y_cols) == 1:
            ax.set_ylabel(y_cols[0])
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(True, alpha=0.2)
        self.fig.subplots_adjust(left=0.08, right=0.96, top=0.94, bottom=0.14)
        self.canvas.draw_idle()

        self._status_lbl.setText(
            f"Chart: {chart_type} — {x_col} vs {', '.join(y_cols)} "
            f"({len(df)} points)"
        )
        self._status_lbl.setStyleSheet("color: #a6e3a1; font-size: 11px;")


__all__ = [n for n in globals() if not n.startswith("__")]
