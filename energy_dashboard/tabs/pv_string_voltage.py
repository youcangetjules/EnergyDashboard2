"""
PV string DC voltage.

Measured volts only (vPv1 / vPv2), from the 2-minute lots in
``pv_string_voltage``. Earlier days stay empty until this build has been logging.

Today is one London day, midnight to midnight. Rolling 24Hr is 22 hours
behind now and 2 hours ahead, so the now line sits where 22:00 sits on
the day chart.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QDate

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
_MODE_TODAY = 0
_MODE_ROLLING = 1
# 22:00 on a midnight-to-midnight chart is 22/24 of the width.
_ROLL_BEHIND = timedelta(hours=22)
_ROLL_AHEAD = timedelta(hours=2)


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
        self._pinned_day = False
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
        self.btn_reload.setToolTip("Re-read stored voltage lots for the window on screen.")
        self.btn_reload.clicked.connect(self.refresh_now)
        _apply_primary_button_style(self.btn_reload)
        ctrl.addWidget(self.btn_reload)
        ctrl.addSpacing(16)
        self.mode_group = QButtonGroup(self)
        self.rb_mode_today = QRadioButton("Today")
        self.rb_mode_today.setToolTip(
            "One London day, midnight to midnight. The day menu picks which day."
        )
        self.rb_mode_roll = QRadioButton("Rolling 24Hr")
        self.rb_mode_roll.setToolTip(
            "22 hours behind now and 2 hours ahead, so the now line sits "
            "where 22:00 sits on the day chart."
        )
        self.mode_group.addButton(self.rb_mode_today, _MODE_TODAY)
        self.mode_group.addButton(self.rb_mode_roll, _MODE_ROLLING)
        self.rb_mode_today.setChecked(True)
        self.mode_group.idClicked.connect(self._on_mode_changed)
        ctrl.addWidget(self.rb_mode_today)
        ctrl.addWidget(self.rb_mode_roll)
        ctrl.addSpacing(16)
        self.lbl_day = QLabel("Day:")
        self.lbl_day.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        ctrl.addWidget(self.lbl_day)
        self.date_day = _LondonDayPicker(self._view_day)
        self.date_day.setToolTip(
            "London day. Today includes the live reading. "
            "An earlier day is stored lots only."
        )
        self.date_day.dateChanged.connect(self._on_view_day_changed)
        ctrl.addWidget(self.date_day)
        self.btn_today = QPushButton("Today")
        self.btn_today.setFixedWidth(72)
        self.btn_today.setToolTip("Jump the day menu back to today (London).")
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
        """Live volts on the cards, and beside the now line when that line is shown."""
        self._read_live()
        before = self._view_day
        self._sync_day_limit()
        if self._view_day != before:
            self._load_day()
            self._paint()
            return
        if self._show_now():
            self._paint()
            return
        self._paint_cards()
        self.lbl_updated.setText(f"Updated: {datetime.now().strftime('%H:%M:%S')}")

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_day_limit()
        self._load_day()
        self._paint()

    def _rolling(self) -> bool:
        return self.mode_group.checkedId() == _MODE_ROLLING

    def _viewing_today(self) -> bool:
        return (not self._rolling()) and self._view_day == _london_today()

    def _show_now(self) -> bool:
        return self._rolling() or self._viewing_today()

    def _on_mode_changed(self, _mode_id):
        self._sync_day_limit()
        self._load_day()
        self._paint()

    def _sync_day_limit(self):
        today = _london_today()
        rolling = self._rolling()
        self.date_day.blockSignals(True)
        self.date_day.setMaximumDate(QDate(today.year, today.month, today.day))
        if not rolling and not self._pinned_day and self._view_day != today:
            self._view_day = today
            self.date_day.setDate(QDate(today.year, today.month, today.day))
        self.date_day.blockSignals(False)
        self.lbl_day.setEnabled(not rolling)
        self.date_day.setEnabled(not rolling)
        self.btn_today.setEnabled((not rolling) and self._view_day < today)

    def _on_view_day_changed(self, qdate):
        self._view_day = qdate.toPython()
        self._pinned_day = self._view_day != _london_today()
        self._sync_day_limit()
        self._load_day()
        self._paint()

    def _go_today(self):
        self._pinned_day = False
        today = _london_today()
        self._sync_day_limit()
        qtoday = QDate(today.year, today.month, today.day)
        if self._view_day != today or self.date_day.date() != qtoday:
            self.date_day.setDate(qtoday)
            return
        self._load_day()
        self._paint()

    def _day_bounds(self):
        london = _london_tz()
        day = self._view_day
        start = london.localize(datetime(day.year, day.month, day.day))
        end = start + timedelta(days=1)
        return start, end, london

    def _window_bounds(self):
        """Start, end, timezone, and now. Rolling ends two hours after now."""
        london = _london_tz()
        now = datetime.now(london)
        if self._rolling():
            return now - _ROLL_BEHIND, now + _ROLL_AHEAD, london, now
        start, end, london = self._day_bounds()
        return start, end, london, now

    def _load_day(self):
        start, end, _london, now = self._window_bounds()
        query_end = now if self._rolling() else (end - timedelta(seconds=1))
        rows = query_pv_string_voltage(
            self.data_logger,
            start_utc=start.astimezone(timezone.utc),
            end_utc=query_end.astimezone(timezone.utc),
        )
        self._lots.clear()
        for row in rows:
            self._lots.append(row)
        self._read_live()
        if self._rolling():
            label = "the rolling 24 h"
        elif self._viewing_today():
            label = "today"
        else:
            label = self._view_day.strftime("%a %-d %b")
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
        if self._show_now():
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
        if self._rolling():
            stamp = "rolling 24 h"
        elif self._viewing_today():
            stamp = "today from 00:00"
        else:
            stamp = self._view_day.strftime("%a %-d %b %Y")
        start, end, london, now = self._window_bounds()
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
        if self._show_now():
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
                0.5, 0.5,
                "No stored voltage in this window" if self._rolling()
                else "No stored voltage for this day",
                ha="center", va="center", transform=ax.transAxes,
                color=_DARK_SUBTEXT, fontsize=11,
            )
            ax.set_ylim(0.0, 10.0)
        import matplotlib.dates as mdates
        ax.set_xlim(start, end)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=london))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2, tz=london))
        ax.grid(axis="y", color=_DARK_GRID, linewidth=0.4)
        if self._show_now():
            ax.axvline(now, color=_COL_NOW, linestyle="--", linewidth=1.0, zorder=4)
            self._label_beside_now(ax, now, end, v1, v2)
        self.fig.subplots_adjust(left=0.07, right=0.98, top=0.90, bottom=0.12)
        self.canvas.draw_idle()
        if not self._lots:
            if self._rolling():
                self.lbl_detail.setText(
                    "Nothing stored in the last 22 hours. Voltage is kept from "
                    "the build that added the table onward, while the dashboard is open."
                )
            else:
                self.lbl_detail.setText(
                    "Nothing stored for this day. Voltage is kept from the build "
                    "that added the table onward, while the dashboard is open."
                )
        elif self._rolling():
            self.lbl_detail.setText(
                f"{len(self._lots)} stored lot(s) from 22 hours ago up to now. "
                "The chart runs two hours past now, so the teal line sits where "
                "22:00 sits on a day chart. A missing string is left blank, not 0 V."
            )
        else:
            self.lbl_detail.setText(
                f"{len(self._lots)} stored lot(s). Each point is the average "
                "volts in that 2-minute slot. A missing string is left blank, not 0 V."
            )
        self.lbl_updated.setText(f"Updated: {datetime.now().strftime('%H:%M:%S')}")

    def _label_beside_now(self, ax, now, day_end, v1, v2):
        """Write each string's latest volts just beside the now line."""
        latest = []
        for values, color in ((v1, _COL_S1), (v2, _COL_S2)):
            reading = None
            for item in reversed(values):
                if item is not None:
                    reading = item
                    break
            if reading is not None:
                latest.append((reading, color))
        if not latest:
            return
        hours_left = (day_end - now).total_seconds() / 3600.0
        if hours_left < 2.0:
            dx, ha = -8, "right"
        else:
            dx, ha = 8, "left"
        y0, y1 = ax.get_ylim()
        span = max(float(y1 - y0), 1.0)
        placed = []
        for reading, color in latest:
            dy = 0
            for prev in placed:
                if abs(reading - prev) < span * 0.05:
                    dy = 11 if reading >= prev else -11
            placed.append(reading)
            ax.annotate(
                f"{reading:.0f} V",
                xy=(now, reading),
                xytext=(dx, dy),
                textcoords="offset points",
                ha=ha,
                va="center",
                color=color,
                fontsize=9,
                zorder=9,
                annotation_clip=False,
            )


__all__ = ["PvStringVoltageTab"]
