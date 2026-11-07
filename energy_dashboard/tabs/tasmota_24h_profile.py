"""Tasmota 24 hr Profile — averaged daily power profile per device with outlier detection."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from energy_dashboard.common import *


_PALETTE = ('#a6e3a1', '#89b4fa', '#f38ba8', '#f9e2af', '#cba6f7',
            '#94e2d5', '#fab387', '#74c7ec', '#f5c2e7', '#b4befe')


def _enrich_device_names(logger, names: dict[str, str]) -> None:
    """Replace IP-only labels with friendly names from tasmota_devices."""
    need = [ip for ip, label in names.items() if label == ip]
    if not need or logger is None:
        return
    try:
        be = logger._primary_storage_backend()
        if not be:
            return
        df = logger._query_pl(
            be,
            "SELECT device_ip, device_name FROM tasmota_devices "
            "WHERE device_name IS NOT NULL",
            (),
        )
        for row in df.iter_rows(named=True):
            ip = row["device_ip"]
            dn = row["device_name"]
            if ip in names and dn and dn != ip:
                names[ip] = dn
    except Exception:
        pass


class Tasmota24hProfileTab(QWidget):
    """Averaged 24-hour power profile for a single Tasmota device."""

    def __init__(self, status_callback, dashboard=None):
        super().__init__()
        self.set_status = status_callback
        self.dash = dashboard
        self._build_ui()

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Controls row
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Device:"))
        self.device_combo = QComboBox()
        apply_combo_field_motif(self.device_combo, width=220)
        ctrl.addWidget(self.device_combo)

        ctrl.addSpacing(20)
        ctrl.addWidget(QLabel("Aggregation window:"))
        self.days_spin = QSpinBox()
        self.days_spin.setRange(2, 90)
        self.days_spin.setValue(7)
        self.days_spin.setSuffix(" days")
        apply_spin_field_motif(self.days_spin, width=100)
        ctrl.addWidget(self.days_spin)

        ctrl.addSpacing(20)
        self.load_btn = QPushButton("Load profile")
        self.load_btn.clicked.connect(self._load_profile)
        ctrl.addWidget(self.load_btn)
        ctrl.addStretch(1)
        layout.addLayout(ctrl)

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

        # Outlier list
        self.outlier_label = QLabel("Outlier days:")
        self.outlier_label.setStyleSheet("color: #cdd6f4; font-weight: bold;")
        layout.addWidget(self.outlier_label)

        self.outlier_list = QTextEdit()
        self.outlier_list.setReadOnly(True)
        self.outlier_list.setMaximumHeight(120)
        self.outlier_list.setStyleSheet(
            "QTextEdit { background: #1e1e2e; color: #cdd6f4; border: 1px solid #3a3a4c; }"
        )
        layout.addWidget(self.outlier_list)

    # ── Refresh device list ─────────────────────────────────────────
    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_device_list()

    def _refresh_device_list(self):
        logger = self._logger()
        if logger is None:
            return
        try:
            rows = logger.query_tasmota_power_history(60 * 24 * 7)
        except Exception:
            return
        names: dict[str, str] = {}
        for _ts, ip, name, _pw in rows:
            if not ip:
                continue
            # Prefer a non-IP-looking name; keep the best one seen so far.
            cur = names.get(ip)
            candidate = name or ip
            if cur is None or (cur == ip and candidate != ip):
                names[ip] = candidate
        # Enrich from tasmota_devices for any IP still without a friendly name.
        _enrich_device_names(logger, names)
        prev = self.device_combo.currentData()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for ip, label in sorted(names.items(), key=lambda kv: kv[1]):
            self.device_combo.addItem(f"{label}  ({ip})", ip)
        if prev:
            idx = self.device_combo.findData(prev)
            if idx >= 0:
                self.device_combo.setCurrentIndex(idx)
        self.device_combo.blockSignals(False)

    # ── Data loading ────────────────────────────────────────────────
    def _logger(self):
        dl = getattr(self.dash, "data_logger", None) if self.dash else None
        if dl is None:
            return None
        if not (dl.sqlite_enabled or dl.mysql_enabled or dl.pg_enabled):
            return None
        return dl

    def _load_profile(self):
        device_ip = self.device_combo.currentData()
        if not device_ip:
            self.set_status("Select a device first.")
            return
        days = self.days_spin.value()
        logger = self._logger()
        if logger is None:
            self.set_status("No database backend enabled.")
            return
        self.set_status("Loading profile\u2026")
        try:
            rows = logger.query_tasmota_power_history(60 * 24 * days)
        except Exception as exc:
            self.set_status(f"Query error: {exc}")
            return
        device_rows = [(ts, pw) for ts, ip, _name, pw in rows if ip == device_ip]
        if not device_rows:
            self.set_status("No data for this device in the selected window.")
            return
        self._plot(device_rows, days, self.device_combo.currentText())

    # ── Plotting ────────────────────────────────────────────────────
    def _plot(self, rows: list, days: int, device_label: str):
        import numpy as np

        # Parse timestamps and bucket into time-of-day (minutes since midnight)
        by_day: dict[str, list[tuple[int, float]]] = {}
        for ts_str, power_w in rows:
            try:
                ts = datetime.strptime(str(ts_str)[:19], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
            day_key = ts.strftime("%Y-%m-%d")
            minute = ts.hour * 60 + ts.minute
            by_day.setdefault(day_key, []).append((minute, float(power_w or 0)))

        if not by_day:
            self.set_status("No parseable data.")
            return

        # 15-minute bins (96 bins per day)
        n_bins = 96
        bin_size = 15
        bin_values: dict[int, list[float]] = {b: [] for b in range(n_bins)}
        day_curves: dict[str, list[float | None]] = {}

        for day_key, points in by_day.items():
            curve = [None] * n_bins
            for minute, pw in points:
                b = min(minute // bin_size, n_bins - 1)
                bin_values[b].append(pw)
                if curve[b] is None:
                    curve[b] = pw
                else:
                    curve[b] = (curve[b] + pw) / 2.0
            day_curves[day_key] = curve

        x = np.array([b * bin_size / 60.0 for b in range(n_bins)])
        mean = np.array([
            np.mean(bin_values[b]) if bin_values[b] else 0.0
            for b in range(n_bins)
        ])
        p10 = np.array([
            np.percentile(bin_values[b], 10) if len(bin_values[b]) >= 2 else mean[b]
            for b in range(n_bins)
        ])
        p90 = np.array([
            np.percentile(bin_values[b], 90) if len(bin_values[b]) >= 2 else mean[b]
            for b in range(n_bins)
        ])

        # Outlier detection: any day where power exceeds the P10–P90 envelope
        # for more than 1 continuous hour (4 bins)
        outliers: list[str] = []
        for day_key, curve in day_curves.items():
            run = 0
            for b in range(n_bins):
                val = curve[b]
                if val is not None and (val > p90[b] or val < p10[b]):
                    run += 1
                    if run >= 4:
                        outliers.append(day_key)
                        break
                else:
                    run = 0

        # Draw
        self.ax.clear()
        _style_ax_dark(self.ax, self.fig)
        self.ax.fill_between(x, p10, p90, alpha=0.25, color='#89b4fa', label='P10\u2013P90')
        self.ax.plot(x, mean, color='#a6e3a1', linewidth=2, label='Mean')

        # Overlay outlier days faintly
        for day_key in outliers:
            curve = day_curves[day_key]
            xs_d, ys_d = [], []
            for b in range(n_bins):
                if curve[b] is not None:
                    xs_d.append(x[b])
                    ys_d.append(curve[b])
            if xs_d:
                self.ax.plot(xs_d, ys_d, color='#f38ba8', alpha=0.4, linewidth=0.8)

        self.ax.set_xlim(0, 24)
        self.ax.set_xticks(range(0, 25, 3))
        self.ax.set_xlabel("Time of day")
        self.ax.set_ylabel("Watts")
        self.ax.set_title(f"{device_label.strip()} \u2014 24 hr profile (last {days} days)")
        self.ax.legend(loc="upper right", fontsize=8)
        self.ax.grid(True, alpha=0.2)
        self.fig.tight_layout()
        self.canvas.draw()

        # Outlier list
        if outliers:
            self.outlier_label.setText(f"Outlier days ({len(outliers)}):")
            self.outlier_list.setPlainText("\n".join(sorted(outliers)))
        else:
            self.outlier_label.setText("No outlier days detected.")
            self.outlier_list.clear()
        self.set_status(
            f"Profile drawn from {len(day_curves)} days, {len(outliers)} outlier(s)."
        )


__all__ = [n for n in globals() if not n.startswith("__")]
