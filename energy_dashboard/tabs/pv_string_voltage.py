"""
PV string DC voltage for one London day.

Measured volts only (vPv1 / vPv2), from the 2-minute lots in
``pv_string_voltage``. Earlier days stay empty until this build has been logging.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

from energy_dashboard.common import *
from energy_dashboard.db.pv_string_voltage import query_pv_string_voltage
from energy_dashboard.tabs.pv_string_charge import (
    _LondonDayPicker,
    _aware_utc,
    _london_today,
    _london_tz,
)

_COL_S1 = "#89b4fa"
_COL_S2 = "#a6e3a1"
_COL_NOW = "#94e2d5"


def _volts(val):
    if val is None or val in ("", "--", "—"):
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


class PvStringVoltageTab(QWidget):
    """Physical Plant Tools — measured volts on each MPPT string."""

    def __init__(self, growatt_tab, status_callback, data_logger=None):
        super().__init__()
        self.growatt_tab = growatt_tab
        self.data_logger = data_logger
        self.set_status = status_callback
        self.on_data_updated = None
        self._lots = deque()
        self._view_day = _london_today()
        self._live = (None, None)
        self.build_ui()
        self._load_day()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        intro = QLabel(
            "Measured DC volts on each string (MPPT inputs "
            "<b>vPv1</b> and <b>vPv2</b>). Stored as 2-minute lots. "
            "Days before logging started have no samples."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        root.addWidget(intro)

        ctrl = QHBoxLayout()
        self.btn_reload = QPushButton("Reload")
        self.btn_reload.setToolTip("Re-read stored voltage lots for the day on screen.")
        self.btn_reload.clicked.connect(self.refresh_now)
        _apply_primary_button_style(self.btn_reload)
        ctrl.addWidget(self.btn_reload)
        ctrl.addSpacing(16)
        lbl_day = QLabel("Day:")
        lbl_day.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        ctrl.addWidget(lbl_day)
        self.date_day = _LondonDayPicker(self._view_day)
        self.date_day.setToolTip(
            "London day. Today includes the live reading. "
            "An earlier day is stored lots only."
        )
        self.date_day.dateChanged.connect(self._on_view_day_changed)
        ctrl.addWidget(self.date_day)
        self.btn_today = QPushButton("Today")
        self.btn_today.setFixedWidth(72)
        self.btn_today.setEnabled(False)
        self.btn_today.clicked.connect(self._go_today)
        _apply_primary_button_style(self.btn_today)
        ctrl.addWidget(self.btn_today)
        ctrl.addStretch(1)
        self.lbl_updated = QLabel("")
        self.lbl_updated.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px;")
        ctrl.addWidget(self.lbl_updated)
        root.addLayout(ctrl)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.card_s1 = self._card("String 1", _COL_S1)
        self.card_s2 = self._card("String 2", _COL_S2)
        cards.addWidget(self.card_s1, 1)
        cards.addWidget(self.card_s2, 1)
        root.addLayout(cards)

        self.lbl_detail = QLabel("")
        self.lbl_detail.setWordWrap(True)
        self.lbl_detail.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px;")
        root.addWidget(self.lbl_detail)

        self.fig = Figure(figsize=(10, 5.2), dpi=100)
        self.ax = self.fig.add_subplot(111)
        _style_ax_dark(self.ax, self.fig)
        self.fig.subplots_adjust(left=0.07, right=0.98, top=0.90, bottom=0.12)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setMinimumHeight(360)
        root.addWidget(self.canvas, 1)

    def _card(self, title, accent):
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {_DARK_SURFACE_BG}; border: 1px solid #313244; "
            f"border-left: 3px solid {accent}; border-radius: 6px; }}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px; border: none;")
        value = QLabel("—")
        value.setStyleSheet(
            f"color: {accent}; font-size: 22px; font-weight: bold; border: none;"
        )
        sub = QLabel("")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px; border: none;")
        lay.addWidget(title_lbl)
        lay.addWidget(value)
        lay.addWidget(sub)
        frame._value = value
        frame._sub = sub
        return frame

    def refresh_now(self):
        self._sync_day_limit()
        self._load_day()
        self._paint()
        if self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception:
                pass

    def on_growatt_live_update(self):
        """Live volts on the cards. The chart stays the stored lots until Reload."""
        self._read_live()
        if self._viewing_today():
            self._paint_cards()
            self.lbl_updated.setText(f"Updated: {datetime.now().strftime('%H:%M:%S')}")

    def showEvent(self, event):
        super().showEvent(event)
        self._load_day()
        self._paint()

    def _viewing_today(self) -> bool:
        return self._view_day == _london_today()

    def _sync_day_limit(self):
        today = _london_today()
        self.date_day.blockSignals(True)
        self.date_day.setMaximumDate(QDate(today.year, today.month, today.day))
        self.date_day.blockSignals(False)
        self.btn_today.setEnabled(self._view_day < today)

    def _on_view_day_changed(self, qdate):
        self._view_day = qdate.toPython()
        self._sync_day_limit()
        self._load_day()
        self._paint()

    def _go_today(self):
        today = _london_today()
        self.date_day.setDate(QDate(today.year, today.month, today.day))

    def _day_bounds(self):
        london = _london_tz()
        day = self._view_day
        start = london.localize(datetime(day.year, day.month, day.day))
        end = start + timedelta(days=1)
        return start, end, london

    def _load_day(self):
        start, end, _london = self._day_bounds()
        rows = query_pv_string_voltage(
            self.data_logger,
            start_utc=start.astimezone(timezone.utc),
            end_utc=(end - timedelta(seconds=1)).astimezone(timezone.utc),
        )
        self._lots.clear()
        for row in rows:
            self._lots.append(row)
        self._read_live()
        label = "today" if self._viewing_today() else self._view_day.strftime("%a %-d %b")
        if self.set_status:
            self.set_status(f"String voltage: {len(self._lots)} lot(s) for {label}.")

    def _read_live(self):
        status = getattr(self.growatt_tab, "mix_status_data", None)
        if not isinstance(status, dict):
            self._live = (None, None)
            return
        self._live = (_volts(status.get("vPv1")), _volts(status.get("vPv2")))

    def _series_stats(self, key):
        vals = [row.get(key) for row in self._lots if row.get(key) is not None]
        if not vals:
            return None
        return min(vals), max(vals), sum(vals) / len(vals)

    def _fmt_v(self, v):
        if v is None:
            return "—"
        return f"{v:.0f} V"

    def _paint_cards(self):
        s1 = self._series_stats("v1")
        s2 = self._series_stats("v2")
        if self._viewing_today():
            v1, v2 = self._live
            self.card_s1._value.setText(self._fmt_v(v1))
            self.card_s2._value.setText(self._fmt_v(v2))
            self.card_s1._sub.setText(self._range_line(s1, "measured now"))
            self.card_s2._sub.setText(self._range_line(s2, "measured now"))
        else:
            self.card_s1._value.setText("—" if s1 is None else f"{s1[2]:.0f} V")
            self.card_s2._value.setText("—" if s2 is None else f"{s2[2]:.0f} V")
            self.card_s1._sub.setText(self._range_line(s1, "day average"))
            self.card_s2._sub.setText(self._range_line(s2, "day average"))

    @staticmethod
    def _range_line(stats, lead):
        if stats is None:
            return f"{lead} · no stored lots"
        lo, hi, _avg = stats
        return f"{lead} · low {lo:.0f} V · high {hi:.0f} V"

    def _paint(self):
        self._paint_cards()
        stamp = (
            "today from 00:00"
            if self._viewing_today()
            else self._view_day.strftime("%a %-d %b %Y")
        )
        start, end, london = self._day_bounds()
        now = datetime.now(london)
        ax = self.ax
        ax.clear()
        _style_ax_dark(ax, self.fig)
        ax.set_title(f"String voltage — {stamp}", fontsize=11, pad=4)
        ax.set_ylabel("V")
        times, v1, v2 = [], [], []
        for row in self._lots:
            ts = _aware_utc(row.get("t"))
            if ts is None:
                continue
            times.append(ts.astimezone(london))
            v1.append(row.get("v1"))
            v2.append(row.get("v2"))
        if self._viewing_today():
            live1, live2 = self._live
            if live1 is not None or live2 is not None:
                times.append(now)
                v1.append(live1)
                v2.append(live2)
        if times:
            ax.plot(times, v1, color=_COL_S1, linewidth=1.4, label="String 1")
            ax.plot(times, v2, color=_COL_S2, linewidth=1.4, label="String 2")
            finite = [v for v in v1 + v2 if v is not None]
            peak = max(finite) if finite else 0.0
            ax.set_ylim(0.0, max(10.0, peak * 1.12))
            ax.legend(
                loc="upper left", fontsize=8, framealpha=0.6,
                facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT,
            )
        else:
            ax.text(
                0.5, 0.5, "No stored voltage for this day",
                ha="center", va="center", transform=ax.transAxes,
                color=_DARK_SUBTEXT, fontsize=11,
            )
            ax.set_ylim(0.0, 10.0)
        import matplotlib.dates as mdates
        ax.set_xlim(start, end)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=london))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2, tz=london))
        ax.grid(axis="y", color=_DARK_GRID, linewidth=0.4)
        if self._viewing_today():
            ax.axvline(now, color=_COL_NOW, linestyle="--", linewidth=1.0)
        self.fig.subplots_adjust(left=0.07, right=0.98, top=0.90, bottom=0.12)
        self.canvas.draw_idle()
        if not self._lots:
            self.lbl_detail.setText(
                "Nothing stored for this day. Voltage is kept from the build "
                "that added the table onward, while the dashboard is open."
            )
        else:
            self.lbl_detail.setText(
                f"{len(self._lots)} stored lot(s). Each point is the average "
                "volts in that 2-minute slot. A missing string is left blank, not 0 V."
            )
        self.lbl_updated.setText(f"Updated: {datetime.now().strftime('%H:%M:%S')}")


__all__ = ["PvStringVoltageTab"]
