"""
Database health status dialog for the Database Viewer tab.
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.db.health_stats import GROWTH_TABLES, KNOWN_TABLES


class DbHealthDialog(QDialog):
    """Modal window showing database health, last activity, and growth."""

    def __init__(self, parent, backend: str):
        super().__init__(parent)
        self._backend = backend
        self.setWindowTitle(f"Database status — {backend}")
        self.setModal(True)
        self.resize(920, 640)
        self.setMinimumSize(720, 480)
        self.setStyleSheet(
            f"QDialog {{ background: {_DARK_SURFACE_BG}; }}"
            "QLabel, QTableWidget { color: #cdd6f4; }"
            "QGroupBox { color: #cdd6f4; border: 1px solid #313244; "
            "border-radius: 6px; margin-top: 8px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        self.header_lbl = QLabel("Loading database status…")
        self.header_lbl.setTextFormat(Qt.RichText)
        self.header_lbl.setWordWrap(True)
        outer.addWidget(self.header_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {_DARK_SURFACE_BG}; border: none; }}"
        )
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(10)

        self.health_box = QGroupBox("Connection health")
        health_lay = QVBoxLayout(self.health_box)
        self.health_lbl = QLabel("Checking…")
        self.health_lbl.setWordWrap(True)
        health_lay.addWidget(self.health_lbl)
        body_lay.addWidget(self.health_box)

        self.activity_box = QGroupBox("Last activity")
        activity_lay = QVBoxLayout(self.activity_box)
        self.overall_lbl = QLabel("—")
        self.overall_lbl.setWordWrap(True)
        activity_lay.addWidget(self.overall_lbl)
        self.viewer_lbl = QLabel("—")
        self.viewer_lbl.setWordWrap(True)
        activity_lay.addWidget(self.viewer_lbl)
        self.tables_widget = QTableWidget()
        self.tables_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tables_widget.setAlternatingRowColors(True)
        self.tables_widget.setColumnCount(3)
        self.tables_widget.setHorizontalHeaderLabels(["Table", "Rows", "Last activity"])
        self.tables_widget.horizontalHeader().setStretchLastSection(True)
        activity_lay.addWidget(self.tables_widget)
        body_lay.addWidget(self.activity_box)

        self.daily_box = QGroupBox("Growth — day by day (last 7 days)")
        daily_lay = QVBoxLayout(self.daily_box)
        self.daily_widget = QTableWidget()
        self.daily_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.daily_widget.setAlternatingRowColors(True)
        daily_lay.addWidget(self.daily_widget)
        body_lay.addWidget(self.daily_box)

        self.weekly_box = QGroupBox("Growth — week by week (last 4 weeks)")
        weekly_lay = QVBoxLayout(self.weekly_box)
        self.weekly_widget = QTableWidget()
        self.weekly_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.weekly_widget.setAlternatingRowColors(True)
        weekly_lay.addWidget(self.weekly_widget)
        body_lay.addWidget(self.weekly_box)

        body_lay.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.footer_lbl = QLabel("")
        self.footer_lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
        outer.addWidget(self.footer_lbl)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        refresh_btn = btns.addButton("Refresh", QDialogButtonBox.ActionRole)
        refresh_btn.clicked.connect(self._request_refresh)
        outer.addWidget(btns)
        _prepare_dialog_buttons(self)

        self._refresh_cb = None

    def set_refresh_callback(self, cb):
        self._refresh_cb = cb

    def _request_refresh(self):
        if self._refresh_cb:
            self.show_loading()
            self._refresh_cb()

    def show_loading(self):
        self.header_lbl.setText(
            f"<h3 style='margin:0'>Database status — {self._backend}</h3>"
            f"<p style='margin:4px 0 0 0; color:#89b4fa;'>Loading…</p>"
        )
        self.health_lbl.setText("Checking connection…")
        self.health_lbl.setStyleSheet("color: #89b4fa; font-size: 12px;")
        self.overall_lbl.setText("Most recent logged data: …")
        self.viewer_lbl.setText("Last opened in Database Viewer: …")

    def apply_stats(self, stats: dict, viewer_last_access: str | None = None):
        backend = stats.get("backend", self._backend)
        checked = stats.get("checked_at", "—")
        db_size = stats.get("db_size", "—")

        if stats.get("error") and not stats.get("ok"):
            self.header_lbl.setText(
                f"<h3 style='margin:0'>Database status — {backend}</h3>"
                f"<p style='margin:4px 0 0 0; color:#f38ba8;'>"
                f"Could not read database: {stats['error']}</p>"
            )
            self.health_lbl.setText(f"<b>Connection failed</b><br>{stats['error']}")
            self.health_lbl.setStyleSheet("color: #f38ba8; font-size: 12px; font-weight: bold;")
            self.footer_lbl.setText(f"Checked at {checked}")
            return

        summary = stats.get("probe_summary") or "—"
        access_line = ""
        probe = stats.get("probe_detail")
        if isinstance(probe, dict):
            access_line = (
                f"<br>Port <b>{probe.get('port', '—')}</b>, "
                f"username <b>{probe.get('user', '—')}</b>, "
                f"access <b>{probe.get('access', '—')}</b>"
            )

        self.header_lbl.setText(
            f"<h3 style='margin:0'>Database status — {backend}</h3>"
            f"<p style='margin:4px 0 0 0; color:#a6adc8;'>"
            f"Size: <b>{db_size}</b> · {summary}</p>"
        )

        if stats.get("probe_ok"):
            self.health_lbl.setText(
                f"<span style='color:#a6e3a1;'><b>Healthy</b></span> — "
                f"connection OK{access_line}"
            )
            self.health_lbl.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        else:
            self.health_lbl.setText(
                f"<span style='color:#f38ba8;'><b>Unhealthy</b></span> — "
                f"{stats.get('error') or 'connection probe failed'}"
            )
            self.health_lbl.setStyleSheet("color: #f38ba8; font-size: 12px; font-weight: bold;")

        last_overall = stats.get("last_activity_overall") or "no logged data yet"
        self.overall_lbl.setText(
            f"<b>Most recent logged data:</b> "
            f"<span style='color:#a6e3a1;'>{last_overall}</span>"
        )
        if viewer_last_access:
            self.viewer_lbl.setText(
                f"<b>Last opened in Database Viewer:</b> {viewer_last_access}"
            )
        else:
            self.viewer_lbl.setText(
                "<b>Last opened in Database Viewer:</b> "
                "<span style='color:#f38ba8; font-weight:bold;'>never</span>"
            )

        tables = stats.get("tables") or {}
        self.tables_widget.setRowCount(len(KNOWN_TABLES))
        for row, (name, _col) in enumerate(KNOWN_TABLES):
            info = tables.get(name, {})
            exists = info.get("exists")
            if not exists:
                rows_txt = "—"
                last_txt = "—"
                name_txt = f"{name} (missing)"
                missing = True
            else:
                rows_txt = f"{info.get('row_count', 0):,}"
                last_txt = info.get("last_activity") or "—"
                name_txt = name
                missing = False
            for col, txt in enumerate((name_txt, rows_txt, last_txt)):
                item = QTableWidgetItem(txt)
                if missing:
                    item.setForeground(QColor("#f38ba8"))
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                self.tables_widget.setItem(row, col, item)
        self.tables_widget.resizeColumnsToContents()

        growth_tables = [t for t, _ in GROWTH_TABLES]
        self._fill_growth_table(
            self.daily_widget,
            stats.get("daily_growth") or [],
            "date",
            growth_tables,
        )
        self._fill_growth_table(
            self.weekly_widget,
            stats.get("weekly_growth") or [],
            "week",
            growth_tables,
        )
        self.footer_lbl.setText(f"Checked at {checked}")

    @staticmethod
    def _fill_growth_table(widget, rows, label_key, table_names):
        headers = [label_key.capitalize()] + list(table_names) + ["Total"]
        widget.setColumnCount(len(headers))
        widget.setHorizontalHeaderLabels(headers)
        widget.setRowCount(len(rows))
        for r, row in enumerate(rows):
            widget.setItem(r, 0, QTableWidgetItem(str(row.get(label_key, ""))))
            per = row.get("per_table") or {}
            for c, tname in enumerate(table_names, start=1):
                n = per.get(tname, 0)
                item = QTableWidgetItem(f"{n:,}")
                if n == 0:
                    item.setForeground(QColor("#6c7086"))
                widget.setItem(r, c, item)
            total_item = QTableWidgetItem(f"{row.get('total', 0):,}")
            f = total_item.font()
            f.setBold(True)
            total_item.setFont(f)
            widget.setItem(r, len(headers) - 1, total_item)
        widget.resizeColumnsToContents()


__all__ = ["DbHealthDialog"]
