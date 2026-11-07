"""Tasmota Historical Profile — cumulative and daily energy per device over time."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from energy_dashboard.common import *


_PALETTE = ('#a6e3a1', '#89b4fa', '#f38ba8', '#f9e2af', '#cba6f7',
            '#94e2d5', '#fab387', '#74c7ec', '#f5c2e7', '#b4befe')

_RANGE_OPTIONS = (
    ("Last 7 days", 7),
    ("Last 30 days", 30),
    ("Last 90 days", 90),
    ("All", 365 * 5),
)


class TasmotaHistoricalTab(QWidget):
    """Cumulative and daily kWh per Tasmota device over time."""

    def __init__(self, status_callback, dashboard=None):
        super().__init__()
        self.set_status = status_callback
        self.dash = dashboard
        self._device_checks: dict[str, QCheckBox] = {}
        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Top controls
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Date range:"))
        self.range_combo = QComboBox()
        for label, _days in _RANGE_OPTIONS:
            self.range_combo.addItem(label, _days)
        self.range_combo.setCurrentIndex(1)  # default 30 days
        apply_combo_field_motif(self.range_combo, width=150)
        ctrl.addWidget(self.range_combo)

        ctrl.addSpacing(20)
        ctrl.addWidget(QLabel("Chart:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Cumulative kWh", "cumulative")
        self.mode_combo.addItem("Daily kWh bars", "daily")
        apply_combo_field_motif(self.mode_combo, width=160)
        ctrl.addWidget(self.mode_combo)

        ctrl.addSpacing(20)
        self.load_btn = QPushButton("Load history")
        self.load_btn.clicked.connect(self._load_history)
        ctrl.addWidget(self.load_btn)
        ctrl.addStretch(1)
        layout.addLayout(ctrl)

        # Device filter row (populated dynamically)
        self.device_row = QHBoxLayout()
        self.device_row.addWidget(QLabel("Devices:"))
        self._device_box = QHBoxLayout()
        self.device_row.addLayout(self._device_box)
        self.device_row.addStretch(1)
        layout.addLayout(self.device_row)

        # Chart
        self.fig = Figure(figsize=(12, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        _style_ax_dark(self.ax, self.fig)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding,
        )
        self.canvas.setMinimumHeight(260)
        layout.addWidget(self.canvas, 1)

        toolbar = DarkNavigationToolbar(self.canvas, self)
        layout.addWidget(toolbar, 0)

        # Summary table
        self.summary_table = QTableWidget()
        self.summary_table.setMaximumHeight(180)
        self.summary_table.setColumnCount(5)
        self.summary_table.setHorizontalHeaderLabels(
            ["Device", "Total kWh", "Avg daily kWh", "First seen", "Last seen"]
        )
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.summary_table.setStyleSheet(
            "QTableWidget { background: #1e1e2e; color: #cdd6f4; gridline-color: #3a3a4c; }"
            "QHeaderView::section { background: #2a2a3c; color: #cdd6f4; border: 1px solid #3a3a4c; }"
        )
        layout.addWidget(self.summary_table)

    # ── Data ────────────────────────────────────────────────────────
    def _logger(self):
        dl = getattr(self.dash, "data_logger", None) if self.dash else None
        if dl is None:
            return None
        if not (dl.sqlite_enabled or dl.mysql_enabled or dl.pg_enabled):
            return None
        return dl

    def _load_history(self):
        logger = self._logger()
        if logger is None:
            self.set_status("No database backend enabled.")
            return
        days = self.range_combo.currentData() or 30
        self.set_status("Loading history\u2026")
        try:
            rows = logger.query_tasmota_power_history(60 * 24 * days)
        except Exception as exc:
            self.set_status(f"Query error: {exc}")
            return
        if not rows:
            self.set_status("No Tasmota data in the selected range.")
            return
        self._process_and_plot(rows, days)

    def _process_and_plot(self, rows, days):
        import numpy as np

        # Group by device and day, compute daily kWh via trapezoidal integration
        # of power_w readings
        device_days: dict[str, dict[str, list[tuple[datetime, float]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        device_labels: dict[str, str] = {}
        for ts_str, ip, name, power_w in rows:
            if not ip:
                continue
            device_labels[ip] = name or ip
            try:
                ts = datetime.strptime(str(ts_str)[:19], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
            day_key = ts.strftime("%Y-%m-%d")
            device_days[ip][day_key].append((ts, float(power_w or 0)))

        # Update device checkboxes
        self._update_device_checks(device_labels)

        # Compute daily kWh per device using trapezoid
        daily_kwh: dict[str, dict[str, float]] = {}
        for ip, day_map in device_days.items():
            daily_kwh[ip] = {}
            for day_key, points in day_map.items():
                points.sort(key=lambda p: p[0])
                if len(points) < 2:
                    # Single point: estimate from power_w * fraction of day available
                    daily_kwh[ip][day_key] = points[0][1] / 1000.0 * (5.0 / 60.0)
                    continue
                kwh = 0.0
                for i in range(1, len(points)):
                    dt_h = (points[i][0] - points[i - 1][0]).total_seconds() / 3600.0
                    avg_w = (points[i][1] + points[i - 1][1]) / 2.0
                    kwh += avg_w * dt_h / 1000.0
                daily_kwh[ip][day_key] = kwh

        # Determine visible devices
        visible = {
            ip for ip, chk in self._device_checks.items() if chk.isChecked()
        }
        if not visible:
            visible = set(device_labels.keys())

        mode = self.mode_combo.currentData() or "cumulative"
        if mode == "daily":
            self._plot_daily_bars(daily_kwh, device_labels, visible)
        else:
            self._plot_cumulative(daily_kwh, device_labels, visible)

        self._fill_summary(daily_kwh, device_labels, device_days)
        self.set_status(
            f"History loaded: {len(device_labels)} device(s), "
            f"{sum(len(d) for d in daily_kwh.values())} day-records."
        )

    # ── Device checkboxes ───────────────────────────────────────────
    def _update_device_checks(self, labels: dict[str, str]):
        new_ips = set(labels.keys())
        old_ips = set(self._device_checks.keys())
        if new_ips == old_ips:
            return
        # Remove stale
        for ip in old_ips - new_ips:
            chk = self._device_checks.pop(ip)
            self._device_box.removeWidget(chk)
            chk.deleteLater()
        # Add new
        for ip in sorted(new_ips - old_ips, key=lambda i: labels.get(i, i)):
            chk = QCheckBox(labels[ip])
            chk.setChecked(True)
            chk.setStyleSheet("color: #cdd6f4;")
            self._device_checks[ip] = chk
            self._device_box.addWidget(chk)

    # ── Charts ──────────────────────────────────────────────────────
    def _plot_cumulative(self, daily_kwh, labels, visible):
        self.ax.clear()
        _style_ax_dark(self.ax, self.fig)
        colour_idx = 0
        for ip in sorted(visible, key=lambda i: labels.get(i, i)):
            if ip not in daily_kwh:
                continue
            days_sorted = sorted(daily_kwh[ip].items())
            if not days_sorted:
                continue
            dates = [d for d, _ in days_sorted]
            cum = []
            total = 0.0
            for _, kwh in days_sorted:
                total += kwh
                cum.append(total)
            colour = _PALETTE[colour_idx % len(_PALETTE)]
            colour_idx += 1
            self.ax.plot(dates, cum, color=colour, linewidth=1.5, label=labels.get(ip, ip))
        self.ax.set_ylabel("Cumulative kWh")
        self.ax.set_title("Tasmota Historical Profile \u2014 cumulative energy")
        self.ax.legend(loc="upper left", fontsize=8)
        self.ax.grid(True, alpha=0.2)
        self.fig.autofmt_xdate(rotation=30, ha='right')
        self.fig.tight_layout()
        self.canvas.draw()

    def _plot_daily_bars(self, daily_kwh, labels, visible):
        import numpy as np

        self.ax.clear()
        _style_ax_dark(self.ax, self.fig)

        # Collect all days
        all_days: set[str] = set()
        for ip in visible:
            if ip in daily_kwh:
                all_days |= daily_kwh[ip].keys()
        if not all_days:
            self.canvas.draw()
            return
        all_days_sorted = sorted(all_days)
        n_devices = sum(1 for ip in visible if ip in daily_kwh)
        if n_devices == 0:
            self.canvas.draw()
            return
        bar_width = 0.8 / n_devices
        x = np.arange(len(all_days_sorted))
        colour_idx = 0
        offset = 0
        for ip in sorted(visible, key=lambda i: labels.get(i, i)):
            if ip not in daily_kwh:
                continue
            vals = [daily_kwh[ip].get(d, 0.0) for d in all_days_sorted]
            colour = _PALETTE[colour_idx % len(_PALETTE)]
            colour_idx += 1
            self.ax.bar(
                x + offset * bar_width, vals, bar_width,
                color=colour, alpha=0.85, label=labels.get(ip, ip),
            )
            offset += 1
        step = max(1, len(all_days_sorted) // 15)
        self.ax.set_xticks(x[::step])
        self.ax.set_xticklabels([all_days_sorted[i] for i in range(0, len(all_days_sorted), step)],
                                rotation=30, ha='right', fontsize=8)
        self.ax.set_ylabel("kWh")
        self.ax.set_title("Tasmota Historical Profile \u2014 daily energy")
        self.ax.legend(loc="upper left", fontsize=8)
        self.ax.grid(True, alpha=0.2, axis='y')
        self.fig.tight_layout()
        self.canvas.draw()

    # ── Summary table ───────────────────────────────────────────────
    def _fill_summary(self, daily_kwh, labels, device_days):
        ips = sorted(labels.keys(), key=lambda i: labels[i])
        self.summary_table.setRowCount(len(ips))
        for row_idx, ip in enumerate(ips):
            total = sum(daily_kwh.get(ip, {}).values())
            n_days = len(daily_kwh.get(ip, {}))
            avg = total / n_days if n_days else 0.0
            all_ts = []
            for pts in device_days.get(ip, {}).values():
                all_ts.extend(p[0] for p in pts)
            first = min(all_ts).strftime("%Y-%m-%d") if all_ts else "\u2014"
            last = max(all_ts).strftime("%Y-%m-%d") if all_ts else "\u2014"
            self.summary_table.setItem(row_idx, 0, QTableWidgetItem(labels[ip]))
            self.summary_table.setItem(row_idx, 1, QTableWidgetItem(f"{total:.2f}"))
            self.summary_table.setItem(row_idx, 2, QTableWidgetItem(f"{avg:.2f}"))
            self.summary_table.setItem(row_idx, 3, QTableWidgetItem(first))
            self.summary_table.setItem(row_idx, 4, QTableWidgetItem(last))
        self.summary_table.resizeColumnsToContents()


__all__ = [n for n in globals() if not n.startswith("__")]
