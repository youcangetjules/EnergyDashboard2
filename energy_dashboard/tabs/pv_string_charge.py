"""
Energy Dashboard — PV string → battery charge estimate (Import/Export group).

Growatt does not report which PV string fed the battery. While charging from
solar, this tab apportions ``chargePower`` by each string's share of total PV:

    share_N ≈ chargePower × (pPvN / (pPv1 + pPv2))

That is an analysis estimate only — not a BMS / inverter measurement.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCalendarWidget,
    QMenu,
    QToolButton,
    QWidgetAction,
)

from energy_dashboard.common import *
from energy_dashboard.ui.styles import apply_date_picker_motif
from energy_dashboard.db.pv_string_charge import (
    log_pv_string_charge,
    lot_start,
    query_pv_string_charge,
)
from energy_dashboard.db.pv_string_voltage import log_pv_string_voltage

_COL_NOW = "#94e2d5"
_LOT = timedelta(minutes=2)
_AC_CHARGE_GRID_KW = 0.15  # grid import above this while charging → warn

_COL_S1 = "#89b4fa"
_COL_S2 = "#a6e3a1"
_COL_BOTH = "#cba6f7"
_COL_CHG = "#f38ba8"
_COL_FC_FILL = "#6B4423"
_COL_FC_LINE = "#3F2A14"
_FILL_ALPHA = 0.5
_FC_FILL_ALPHA = 0.30

# SPH/MIX houses here are a few kWp per string. Values above this in a "kW"
# field are leftover watts (the old abs(n)>50 heuristic left 10–50 W as kW).
_MAX_PLAUSIBLE_KW = 8.0


class _LondonDayPicker(QToolButton):
    """Dropdown calendar for one London day. Clicking the field opens it."""

    dateChanged = Signal(QDate)

    def __init__(self, day, parent=None):
        super().__init__(parent)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._day = day
        self._minimum = QDate(2020, 1, 1)
        self._maximum = QDate(day.year, day.month, day.day)
        self._menu = QMenu(self)
        self._menu.setStyleSheet(
            f"QMenu {{ background: {_DARK_SURFACE_BG}; border: 1px solid #45475a; }}"
        )
        self._cal = QCalendarWidget(self._menu)
        self._cal.setGridVisible(True)
        self._cal.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        self._cal.setMinimumDate(self._minimum)
        self._cal.setMaximumDate(self._maximum)
        self._cal.setSelectedDate(self._maximum)
        self._cal.clicked.connect(self._on_calendar)
        action = QWidgetAction(self._menu)
        action.setDefaultWidget(self._cal)
        self._menu.addAction(action)
        self._menu.aboutToShow.connect(self._prepare_calendar)
        self.setMenu(self._menu)
        apply_date_picker_motif(self, width=168)
        self._sync_label()

    def calendarWidget(self):
        return self._cal

    def date(self) -> QDate:
        d = self._day
        return QDate(d.year, d.month, d.day)

    def setMinimumDate(self, qdate: QDate) -> None:
        self._minimum = qdate
        self._cal.setMinimumDate(qdate)

    def setMaximumDate(self, qdate: QDate) -> None:
        self._maximum = qdate
        self._cal.setMaximumDate(qdate)
        if self.date() > qdate:
            self.setDate(qdate)

    def setDate(self, qdate: QDate) -> None:
        if qdate < self._minimum:
            qdate = self._minimum
        if qdate > self._maximum:
            qdate = self._maximum
        day = qdate.toPython()
        if day == self._day:
            self._sync_label()
            return
        self._day = day
        self._sync_label()
        self._cal.setSelectedDate(qdate)
        self.dateChanged.emit(qdate)

    def _sync_label(self) -> None:
        self.setText(self._day.strftime("%d %b %Y"))

    def _prepare_calendar(self) -> None:
        # The latest day is captured when the control is built. After midnight
        # that ceiling is still yesterday, so today cannot be chosen.
        today = _london_today()
        cap = QDate(today.year, today.month, today.day)
        if self._maximum != cap:
            self.setMaximumDate(cap)
        self._cal.setSelectedDate(self.date())
        hint = self._cal.sizeHint()
        self._cal.setMinimumSize(hint)
        self._menu.setMinimumSize(hint.width() + 8, hint.height() + 8)

    def _on_calendar(self, qdate: QDate) -> None:
        self._menu.close()
        self.setDate(qdate)


class _ClickableMetricCard(QFrame):
    """Metric card that emits ``clicked`` on left press (child labels pass through)."""

    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _as_float(val):
    if val is None or val in ("", "--", "—"):
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _watts_or_kw_to_kw(val):
    """Return kW. Watts leftover from Grott/cloud (or bad stored lots) / 1000.

    Do not use ``abs(n) > 50``: dawn 10–50 W then stays as 10–50 kW and the
    chart Y axis autoscale follows that spike (see BUG-015-20260917-01).
    """
    v = _as_float(val)
    if v is None:
        return None
    if abs(v) > _MAX_PLAUSIBLE_KW:
        return v / 1000.0
    return v


def _strings_to_kw(p1, p2, ppv_kw=None):
    """Normalise per-string PV to kW, using total PV when units disagree.

    Grott ``ppv`` is already kW; ``pPv1`` / ``pPv2`` were often still watts.
    """
    a = _as_float(p1)
    b = _as_float(p2)
    tot = (0.0 if a is None else a) + (0.0 if b is None else b)
    p = _watts_or_kw_to_kw(ppv_kw)
    if p is not None and tot > max(1.0, abs(p) * 50.0):
        if a is not None:
            a = a / 1000.0
        if b is not None:
            b = b / 1000.0
    a = _watts_or_kw_to_kw(a)
    b = _watts_or_kw_to_kw(b)
    return a, b, p


def _sanitize_lot(row: dict) -> dict:
    """Fix stored lots that kept dawn watts as kW (display + today kWh)."""
    if not isinstance(row, dict):
        return row
    pv1, pv2, _ = _strings_to_kw(row.get("pv1"), row.get("pv2"))
    row["pv1"] = 0.0 if pv1 is None else float(pv1)
    row["pv2"] = 0.0 if pv2 is None else float(pv2)
    for key in ("s1", "s2", "chg"):
        kw = _watts_or_kw_to_kw(row.get(key))
        row[key] = 0.0 if kw is None else float(kw)
    return row


def _cumulative_kwh(times, kw):
    """Running trapezoid integral of kW samples → kWh, starting at 0."""
    y = np.asarray(kw, dtype=float)
    n = y.size
    if n == 0:
        return y
    if n == 1:
        return np.array([0.0], dtype=float)
    epoch = np.array(
        [t.timestamp() if hasattr(t, "timestamp") else float(t) for t in times],
        dtype=float,
    )
    dt_h = np.diff(epoch) / 3600.0
    avg = 0.5 * (y[:-1] + y[1:])
    return np.concatenate([[0.0], np.cumsum(avg * np.maximum(0.0, dt_h))])


def _step_hold(times, series, until):
    """Hold each 2-minute lot across its slot so a single sample has width."""
    if not times:
        return [], [np.array([], dtype=float) for _ in series]
    out_t = []
    outs = [[] for _ in series]
    n = len(times)
    for i, t in enumerate(times):
        nxt = times[i + 1] if i + 1 < n else until
        end = t + _LOT
        if nxt is not None:
            end = min(end, nxt)
        if until is not None:
            end = min(end, until)
        if end <= t:
            end = t + timedelta(seconds=20)
        out_t.extend([t, end])
        for j, s in enumerate(series):
            y = float(s[i])
            outs[j].extend([y, y])
    return out_t, [np.asarray(o, dtype=float) for o in outs]


def _aware_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _london_tz():
    import pytz
    return pytz.timezone("Europe/London")


def _london_today():
    return datetime.now(_london_tz()).date()


def _integrate_kwh(rows, key: str, *, until=None) -> float:
    """Trapezoid integral of kW samples → kWh. ``until`` extends the last lot to now."""
    pts = []
    for r in rows or ():
        ts = _aware_utc(r.get("t"))
        if ts is None:
            continue
        pts.append((ts.timestamp(), float(r.get(key) or 0.0)))
    if until is not None and pts:
        end = _aware_utc(until).timestamp()
        if end > pts[-1][0]:
            pts.append((end, pts[-1][1]))
    if len(pts) < 2:
        if len(pts) == 1:
            return max(0.0, pts[0][1] * (_LOT_HOURS))
        return 0.0
    energy = 0.0
    for (t0, y0), (t1, y1) in zip(pts, pts[1:]):
        dt_h = max(0.0, (t1 - t0) / 3600.0)
        energy += 0.5 * (y0 + y1) * dt_h
    return max(0.0, energy)


_LOT_HOURS = 2.0 / 60.0  # one 2-minute lot if we only have a single sample


def estimate_string_charge(
    pv1_kw, pv2_kw, charge_kw, *, grid_import_kw=None, ppv_kw=None,
) -> dict:
    """Return estimated charge contributions from each PV string.

    Keys: pv1_kw, pv2_kw, ppv_kw, charge_kw, grid_import_kw,
    est_charge_s1_kw, est_charge_s2_kw, share_s1, share_s2,
    mode (charging_pv | charging_ac | discharging | idle | unknown), notes.
    """
    p1 = max(0.0, _as_float(pv1_kw) or 0.0)
    p2 = max(0.0, _as_float(pv2_kw) or 0.0)
    chg = _as_float(charge_kw)
    g_imp = _as_float(grid_import_kw)
    tot_pv = _as_float(ppv_kw)
    if tot_pv is None:
        tot_pv = p1 + p2
    else:
        tot_pv = max(0.0, float(tot_pv))

    out = {
        "pv1_kw": p1,
        "pv2_kw": p2,
        "ppv_kw": tot_pv,
        "charge_kw": chg,
        "grid_import_kw": g_imp,
        "est_charge_s1_kw": None,
        "est_charge_s2_kw": None,
        "share_s1": None,
        "share_s2": None,
        "mode": "unknown",
        "notes": "",
    }
    if chg is None:
        out["notes"] = "No chargePower reading from Growatt yet."
        return out

    if chg < 0.02:
        # Treat near-zero as idle / discharge handled separately by caller
        # when discharge power is known.
        out["mode"] = "idle"
        out["est_charge_s1_kw"] = 0.0
        out["est_charge_s2_kw"] = 0.0
        out["share_s1"] = 0.0
        out["share_s2"] = 0.0
        out["notes"] = "Battery not charging (chargePower ≈ 0)."
        return out

    if g_imp is not None and g_imp >= _AC_CHARGE_GRID_KW and tot_pv < chg * 0.5:
        out["mode"] = "charging_ac"
        out["est_charge_s1_kw"] = 0.0
        out["est_charge_s2_kw"] = 0.0
        out["share_s1"] = 0.0
        out["share_s2"] = 0.0
        out["notes"] = (
            f"Likely AC/grid charging (grid import {g_imp:.2f} kW, "
            f"PV {tot_pv:.2f} kW) — string split does not apply."
        )
        return out

    if tot_pv < 0.02:
        out["mode"] = "charging_ac"
        out["est_charge_s1_kw"] = 0.0
        out["est_charge_s2_kw"] = 0.0
        out["share_s1"] = 0.0
        out["share_s2"] = 0.0
        out["notes"] = (
            "Charging with near-zero PV — attributed to grid/AC, not strings."
        )
        return out

    share1 = p1 / tot_pv
    share2 = p2 / tot_pv
    # Cap attributed charge at available PV (load/export can eat the rest).
    attributable = min(chg, tot_pv)
    out["mode"] = "charging_pv"
    out["share_s1"] = share1
    out["share_s2"] = share2
    out["est_charge_s1_kw"] = attributable * share1
    out["est_charge_s2_kw"] = attributable * share2
    bits = [
        f"Estimate: charge {chg:.2f} kW split by PV share "
        f"(S1 {share1 * 100:.0f}% / S2 {share2 * 100:.0f}%)."
    ]
    if attributable + 0.05 < chg:
        bits.append(
            f"Only {attributable:.2f} kW of charge can come from PV "
            f"(rest likely grid/AC)."
        )
    if g_imp is not None and g_imp >= _AC_CHARGE_GRID_KW:
        bits.append(f"Grid also importing {g_imp:.2f} kW — hybrid charge.")
    out["notes"] = " ".join(bits)
    return out


class PvStringChargeTab(QWidget):
    """Live estimate of battery charge attributed to each PV string."""

    def __init__(self, growatt_tab, status_callback, data_logger=None):
        super().__init__()
        self.growatt_tab = growatt_tab
        self.data_logger = data_logger
        self.forecasts_tab = None
        self.set_status = status_callback
        self.on_data_updated = None
        self._history = deque()
        self._today = deque()
        self._view_day = _london_today()
        self._last_est = None
        self._ax_cum = None
        self._ax_day = None
        self._fc_cache = None
        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self.refresh_now)
        self.build_ui()
        self._load_scan_interval()
        self._apply_scan_timer()
        self._load_history()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        intro = QLabel(
            "<b>Estimate only.</b> Growatt does not report which PV string fed the "
            "battery. While charging from solar, charge power is apportioned by "
            "each string’s share of total PV "
            "(<code>charge × pPvN / (pPv1+pPv2)</code>). "
            "AC/grid charging is flagged separately — not split across strings."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        root.addWidget(intro)

        ctrl = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh now")
        self.btn_refresh.setToolTip(
            "Re-read the Growatt Live Status snapshot and update the estimate."
        )
        self.btn_refresh.clicked.connect(self.refresh_now)
        _apply_primary_button_style(self.btn_refresh)
        ctrl.addWidget(self.btn_refresh)
        self.btn_reload = QPushButton("Reload charts")
        self.btn_reload.setToolTip(
            "Re-read stored 2-minute lots for the day shown on the charts."
        )
        self.btn_reload.clicked.connect(self._reload_history)
        _apply_primary_button_style(self.btn_reload)
        ctrl.addWidget(self.btn_reload)
        ctrl.addSpacing(16)
        lbl_day = QLabel("Day:")
        lbl_day.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        lbl_day.setToolTip(
            "Open the calendar and pick a London day. Today includes the "
            "live reading. An earlier day shows that day’s stored lots, "
            "each string’s kWh, and that string’s share of the day’s PV."
        )
        ctrl.addWidget(lbl_day)
        self.date_day = _LondonDayPicker(self._view_day)
        self.date_day.setToolTip(lbl_day.toolTip())
        self._style_day_calendar()
        self.date_day.dateChanged.connect(self._on_view_day_changed)
        ctrl.addWidget(self.date_day)
        self.btn_today = QPushButton("Today")
        self.btn_today.setFixedWidth(72)
        self.btn_today.setToolTip("Show today’s charts again (London).")
        self.btn_today.setEnabled(False)
        self.btn_today.clicked.connect(self._go_today)
        _apply_primary_button_style(self.btn_today)
        ctrl.addWidget(self.btn_today)
        ctrl.addSpacing(16)
        lbl_scan = QLabel("Scan every (min):")
        lbl_scan.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        lbl_scan.setToolTip(
            "How often to re-read live string power and update the charts. "
            "0 = Off (Refresh now still works). Remembered."
        )
        ctrl.addWidget(lbl_scan)
        self.sp_scan_min = QSpinBox()
        self.sp_scan_min.setRange(0, 120)
        self.sp_scan_min.setSpecialValueText("Off")
        self.sp_scan_min.setToolTip(
            "Minutes between automatic scans of Growatt live status. "
            "Off (0) stops the timer. Default 2 minutes (same as the stored lots)."
        )
        apply_spin_field_motif(self.sp_scan_min)
        self.sp_scan_min.valueChanged.connect(self._on_scan_interval_changed)
        ctrl.addWidget(self.sp_scan_min)
        ctrl.addStretch(1)
        self.lbl_updated = QLabel("Updated: —")
        self.lbl_updated.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px;")
        ctrl.addWidget(self.lbl_updated)
        root.addLayout(ctrl)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.card_s1 = self._metric_card("String 1 — now", _COL_S1, clickable=True)
        self.card_s2 = self._metric_card("String 2 — now", _COL_S2, clickable=True)
        self.card_chg = self._metric_card("Battery charge (measured)", _COL_CHG)
        self.card_pv = self._metric_card("Total PV (measured)", "#fab387")
        self.card_s1.clicked.connect(lambda: self._open_string_history(1))
        self.card_s2.clicked.connect(lambda: self._open_string_history(2))
        for c in (self.card_s1, self.card_s2, self.card_chg, self.card_pv):
            cards.addWidget(c, 1)
        root.addLayout(cards)

        detail = QGroupBox("Live reading")
        self.box_live = detail
        detail_lay = QVBoxLayout(detail)
        self.lbl_mode = QLabel("Mode: —")
        self.lbl_mode.setStyleSheet("color: #cdd6f4; font-weight: bold; font-size: 12px;")
        detail_lay.addWidget(self.lbl_mode)
        self.lbl_detail = QLabel(
            "Open Growatt Live Status (or wait for auto-refresh) so this tab "
            "can read pPv1 / pPv2 / chargePower."
        )
        self.lbl_detail.setWordWrap(True)
        self.lbl_detail.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px;")
        detail_lay.addWidget(self.lbl_detail)
        root.addWidget(detail)

        chart_box = QGroupBox("Today (00:00–24:00)")
        chart_lay = QVBoxLayout(chart_box)
        self.fig = Figure(figsize=(10, 8.4), dpi=100)
        self.ax = self.fig.add_subplot(211)
        self.ax_day = self.fig.add_subplot(212, sharex=self.ax)
        _style_ax_dark(self.ax, self.fig)
        _style_ax_dark(self.ax_day, self.fig)
        self._apply_chart_layout()
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setMinimumHeight(520)
        enable_bar_value_hover(self.canvas)
        chart_lay.addWidget(self.canvas, 1)
        hint = QLabel(
            "Both charts share one London day, midnight to midnight. "
            "Day picks an earlier day from the stored lots. Today still "
            "includes the live reading; the teal line is Now and only "
            "appears on today. The top pane is instantaneous kW (strings, "
            "measured charge, solar forecast). The bottom pane is that "
            "day’s running kWh total."
        )
        hint.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 10px;")
        hint.setWordWrap(True)
        chart_lay.addWidget(hint)
        root.addWidget(chart_box, 1)

        self._draw_empty_chart()

    def _open_string_history(self, string_n: int):
        """Month → Day → Hour generation and balance from stored lots."""
        try:
            from energy_dashboard.dialogs.pv_string_history import PvStringHistoryDialog
            dlg = PvStringHistoryDialog(
                self, self.data_logger, focus_string=int(string_n),
            )
            dlg.exec()
        except Exception as e:
            try:
                _log.warn("PV String Charge", f"History dialog failed: {e}")
            except Exception:
                pass
            QMessageBox.warning(
                self, "PV string history",
                f"Couldn't open the string history table:\n{e}",
            )

    def _metric_card(self, title: str, accent: str, *, clickable: bool = False):
        frame = _ClickableMetricCard() if clickable else QFrame()
        hover = (
            f"QFrame:hover {{ border: 1px solid {accent}; "
            f"background: #262637; }}"
            if clickable else ""
        )
        frame.setStyleSheet(
            f"QFrame {{ background: {_DARK_SURFACE_BG}; border: 1px solid #313244; "
            f"border-radius: 8px; border-top: 3px solid {accent}; }}"
            f"{hover}"
        )
        if clickable:
            frame.setCursor(Qt.CursorShape.PointingHandCursor)
            frame.setToolTip(
                "Click for previous days: Month → Day → Hour generation "
                "and the balance between String 1 and String 2."
            )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px; border: none;")
        lay.addWidget(title_lbl)
        value_lbl = QLabel("—")
        value_lbl.setObjectName("value")
        value_lbl.setStyleSheet(
            f"color: {accent}; font-size: 22px; font-weight: bold; border: none;"
        )
        lay.addWidget(value_lbl)
        sub_lbl = QLabel("")
        sub_lbl.setObjectName("sub")
        sub_lbl.setWordWrap(True)
        sub_lbl.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 10px; border: none;")
        lay.addWidget(sub_lbl)
        today_lbl = QLabel("")
        today_lbl.setObjectName("today")
        today_lbl.setWordWrap(True)
        today_lbl.setStyleSheet(
            f"color: {accent}; font-size: 12px; font-weight: 600; border: none;"
        )
        lay.addWidget(today_lbl)
        for child in (title_lbl, value_lbl, sub_lbl, today_lbl):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        frame._title = title_lbl
        frame._value = value_lbl
        frame._sub = sub_lbl
        frame._today = today_lbl
        return frame

    def _set_card(self, card, value_txt: str, sub_txt: str = "", today_txt: str = ""):
        card._value.setText(value_txt)
        card._sub.setText(sub_txt)
        card._today.setText(today_txt)

    def _settings(self):
        return QSettings("PowerModel", "EnergyDashboard2")

    def _load_scan_interval(self):
        raw = self._settings().value("pv_string_charge/scan_min", 2)
        try:
            mins = int(raw)
        except (TypeError, ValueError):
            mins = 2
        mins = max(0, min(120, mins))
        self.sp_scan_min.blockSignals(True)
        self.sp_scan_min.setValue(mins)
        self.sp_scan_min.blockSignals(False)

    def _on_scan_interval_changed(self, mins: int):
        self._settings().setValue("pv_string_charge/scan_min", int(mins))
        self._apply_scan_timer()

    def _apply_scan_timer(self):
        mins = int(self.sp_scan_min.value())
        if mins <= 0:
            self._scan_timer.stop()
            return
        self._scan_timer.start(mins * 60 * 1000)

    def auto_start(self):
        self.refresh_now()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_now()

    def refresh_now(self):
        """Refresh Page / Refresh All / button hook."""
        self._sync_day_limit()
        self._sample(record_history=True)
        if self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception:
                pass

    def on_growatt_live_update(self):
        """Called from the main window when Growatt live data refreshes."""
        self._sample(record_history=True)

    def _viewing_today(self) -> bool:
        return self._view_day == _london_today()

    def _style_day_calendar(self):
        cal = self.date_day.calendarWidget()
        cal.setStyleSheet(
            f"QCalendarWidget QWidget {{ background: {_DARK_SURFACE_BG}; "
            f"color: {_DARK_TEXT}; }}"
            f"QCalendarWidget QToolButton {{ color: {_DARK_TEXT}; "
            f"background: {_DARK_SURFACE_BG}; }}"
            "QCalendarWidget QAbstractItemView:enabled {"
            f" color: {_DARK_TEXT}; background: {_DARK_SURFACE_BG};"
            " selection-background-color: #89b4fa; selection-color: #1e1e2e; }"
        )

    def _sync_day_limit(self):
        """Keep the picker from offering a future London day."""
        today = _london_today()
        self.date_day.blockSignals(True)
        self.date_day.setMaximumDate(QDate(today.year, today.month, today.day))
        self.date_day.blockSignals(False)
        if hasattr(self, "btn_today"):
            self.btn_today.setEnabled(self._view_day < today)

    def _on_view_day_changed(self, qdate: QDate):
        day = qdate.toPython()
        if day == self._view_day:
            return
        self._view_day = day
        self._sync_day_limit()
        self._load_history()
        self._draw_chart()
        self._refresh_day_summaries()

    def _go_today(self):
        self._sync_day_limit()
        today = _london_today()
        self.date_day.setDate(QDate(today.year, today.month, today.day))

    def _day_title_stamp(self) -> str:
        if self._viewing_today():
            return "today from 00:00"
        return self._view_day.strftime("%a %-d %b %Y")

    def _empty_lots_text(self) -> str:
        if self._viewing_today():
            return "No stored lots since midnight yet"
        return "No stored lots for this day"

    def _reload_history(self):
        self._load_history()
        self._draw_chart()
        self._refresh_day_summaries()

    def _load_history(self):
        start, _now, end, _london = self._day_bounds()
        rows = query_pv_string_charge(
            self.data_logger,
            start_utc=start.astimezone(timezone.utc),
            end_utc=(end - timedelta(seconds=1)).astimezone(timezone.utc),
        )
        self._today.clear()
        for raw in rows:
            row = _sanitize_lot(dict(raw))
            self._today.append(row)
        self._trim_today()
        self._sync_chart_history()

    def _trim_today(self):
        start, _now, end, _london = self._day_bounds()
        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)
        while self._today and _aware_utc(self._today[0]["t"]) < start_utc:
            self._today.popleft()
        while self._today and _aware_utc(self._today[-1]["t"]) >= end_utc:
            self._today.pop()

    def _sync_chart_history(self):
        self._history.clear()
        self._history.extend(self._today)

    def _trim_history(self):
        self._trim_today()
        self._sync_chart_history()

    def _read_growatt_snapshot(self) -> dict | None:
        gt = self.growatt_tab
        if gt is None:
            return None
        status = getattr(gt, "mix_status_data", None)
        if not isinstance(status, dict) or not status:
            return None
        return status

    def _sample(self, *, record_history: bool):
        status = self._read_growatt_snapshot()
        if status is None:
            self._refresh_day_summaries(live=False)
            if self._viewing_today():
                self.lbl_mode.setText("Mode: no Growatt data")
                self.lbl_detail.setText(
                    "No live MIX status yet. Connect / wait for Grott or Cloud "
                    "on Growatt Live Status."
                )
                self.lbl_updated.setText("Updated: —")
            self._draw_chart()
            return

        pv1, pv2, ppv = _strings_to_kw(
            status.get("pPv1"), status.get("pPv2"), status.get("ppv"),
        )
        charge = _watts_or_kw_to_kw(status.get("chargePower"))
        discharge = _watts_or_kw_to_kw(status.get("pdisCharge1")) or 0.0
        grid_imp = _watts_or_kw_to_kw(status.get("pactouser"))

        est = estimate_string_charge(
            pv1, pv2, charge, grid_import_kw=grid_imp, ppv_kw=ppv,
        )
        if discharge >= 0.05 and (charge or 0) < 0.02:
            est["mode"] = "discharging"
            est["est_charge_s1_kw"] = 0.0
            est["est_charge_s2_kw"] = 0.0
            est["share_s1"] = 0.0
            est["share_s2"] = 0.0
            est["notes"] = (
                f"Battery discharging at {discharge:.2f} kW — no charge "
                "to attribute to strings."
            )

        self._last_est = est
        if record_history:
            now = datetime.now(timezone.utc)
            sample = {
                "t": lot_start(now),
                "s1": float(est.get("est_charge_s1_kw") or 0.0),
                "s2": float(est.get("est_charge_s2_kw") or 0.0),
                "chg": float(est.get("charge_kw") or 0.0),
                "pv1": float(est.get("pv1_kw") or 0.0),
                "pv2": float(est.get("pv2_kw") or 0.0),
            }
            self._ingest_lot(_sanitize_lot(sample))
            log_pv_string_charge(self.data_logger, sample)
            log_pv_string_voltage(
                self.data_logger,
                {
                    "t": sample["t"],
                    "v1": status.get("vPv1"),
                    "v2": status.get("vPv2"),
                },
            )
        self._apply_estimate(est, status)
        if record_history:
            self._draw_chart()

    def _ingest_lot(self, sample: dict):
        """Keep at most one in-memory row per 2-minute lot (running mean).

        A past day on screen stays as stored. Live samples still go to the
        database from ``_sample``; they are not mixed into that day.
        """
        if not self._viewing_today():
            return
        lot_t = lot_start(sample["t"])
        keys = ("s1", "s2", "chg", "pv1", "pv2")
        target = self._today
        if target and lot_start(target[-1]["t"]) == lot_t:
            last = target[-1]
            n = int(last.get("samples") or 1)
            nxt = n + 1
            for k in keys:
                last[k] = (float(last.get(k) or 0.0) * n + float(sample.get(k) or 0.0)) / nxt
            last["samples"] = nxt
            last["t"] = lot_t
        else:
            row = {k: float(sample.get(k) or 0.0) for k in keys}
            row["t"] = lot_t
            row["samples"] = 1
            target.append(row)
        self._trim_history()

    def _today_totals(self) -> dict:
        # Hold the last power through "now" only on today. A finished day
        # is the stored samples — not stretched to the current clock.
        until = datetime.now(timezone.utc) if self._viewing_today() else None
        rows = list(self._today)
        return {
            "pv1": _integrate_kwh(rows, "pv1", until=until),
            "pv2": _integrate_kwh(rows, "pv2", until=until),
            "s1": _integrate_kwh(rows, "s1", until=until),
            "s2": _integrate_kwh(rows, "s2", until=until),
            "chg": _integrate_kwh(rows, "chg", until=until),
        }

    def _today_caption(self) -> str:
        """'since 00:00' or the first sample time if logging started late."""
        start, _now, _end, london = self._day_bounds()
        if not self._today:
            if self._viewing_today():
                return "since 00:00 (no stored lots yet)"
            return "no stored lots"
        first = _aware_utc(self._today[0]["t"]).astimezone(london)
        if first > start + timedelta(minutes=12):
            return f"since {first.strftime('%H:%M')} (samples start)"
        return "since 00:00"

    def _day_energy_prefix(self) -> str:
        cap = self._today_caption()
        if self._viewing_today():
            return f"Today {cap}"
        return f"{self._view_day.strftime('%a %-d %b')} {cap}"

    def _set_card_title(self, card, text: str) -> None:
        card._title.setText(text)

    @staticmethod
    def _share_pct(part: float, total: float) -> str:
        """One-decimal share of the day’s measured PV. Em dash when there is none."""
        if total <= 0.005:
            return "—"
        return f"{100.0 * part / total:.1f}%"

    def _show_past_day_totals(self) -> None:
        """Headline is that day’s kWh, with each string’s share of the day’s PV."""
        tot = self._today_totals()
        prefix = self._day_energy_prefix()
        pv = tot["pv1"] + tot["pv2"]
        p1 = self._share_pct(tot["pv1"], pv)
        p2 = self._share_pct(tot["pv2"], pv)
        self._set_card_title(self.card_s1, "String 1")
        self._set_card_title(self.card_s2, "String 2")
        self._set_card_title(self.card_chg, "Battery charge")
        self._set_card_title(self.card_pv, "Total PV")
        self._set_card(
            self.card_s1,
            f"{tot['pv1']:.2f} kWh",
            f"{tot['s1']:.2f} kWh to the battery (est.)",
            f"{p1} of this day’s PV · {prefix}",
        )
        self._set_card(
            self.card_s2,
            f"{tot['pv2']:.2f} kWh",
            f"{tot['s2']:.2f} kWh to the battery (est.)",
            f"{p2} of this day’s PV · {prefix}",
        )
        chg_share = self._share_pct(tot["chg"], pv)
        self._set_card(
            self.card_chg,
            f"{tot['chg']:.2f} kWh",
            f"{chg_share} of this day’s PV (measured charge)",
            prefix,
        )
        self._set_card(
            self.card_pv,
            f"{pv:.2f} kWh",
            f"S1 {tot['pv1']:.2f} kWh · S2 {tot['pv2']:.2f} kWh",
            f"S1 {p1} · S2 {p2}",
        )
        stamp = self._view_day.strftime("%a %-d %b")
        self.box_live.setTitle("Selected day")
        self.lbl_mode.setText(f"{stamp} — stored lots")
        if pv <= 0.005:
            self.lbl_detail.setText(
                f"No PV was stored for {stamp}. "
                f"Measured battery charge is {tot['chg']:.2f} kWh."
            )
        else:
            self.lbl_detail.setText(
                f"String 1 generated {tot['pv1']:.2f} kWh ({p1} of the day’s PV) "
                f"and String 2 {tot['pv2']:.2f} kWh ({p2}). Estimated charge into "
                f"the battery from those strings is {tot['s1']:.2f} kWh and "
                f"{tot['s2']:.2f} kWh. Measured battery charge is {tot['chg']:.2f} kWh "
                f"({chg_share} of the day’s PV)."
            )

    def _show_today_card_titles(self) -> None:
        self._set_card_title(self.card_s1, "String 1 — now")
        self._set_card_title(self.card_s2, "String 2 — now")
        self._set_card_title(self.card_chg, "Battery charge (measured)")
        self._set_card_title(self.card_pv, "Total PV (measured)")
        self.box_live.setTitle("Live reading")

    def _refresh_day_summaries(self, *, live: bool = True):
        """Rewrite the energy line on each card for the day on screen."""
        if not self._viewing_today():
            self._show_past_day_totals()
            label = self._view_day.strftime("%a %-d %b")
            self.set_status(f"PV string charge: {len(self._today)} lot(s) for {label}.")
            return
        self._show_today_card_titles()
        tot = self._today_totals()
        prefix = self._day_energy_prefix()
        if live and self._last_est is not None:
            self._apply_estimate(
                self._last_est, self._read_growatt_snapshot() or {},
            )
        else:
            self.card_s1._today.setText(
                f"{prefix}: {tot['pv1']:.2f} kWh PV · "
                f"{tot['s1']:.2f} kWh to battery (est.)"
            )
            self.card_s2._today.setText(
                f"{prefix}: {tot['pv2']:.2f} kWh PV · "
                f"{tot['s2']:.2f} kWh to battery (est.)"
            )
            self.card_chg._today.setText(
                f"{prefix}: {tot['chg']:.2f} kWh charged (measured)"
            )
            self.card_pv._today.setText(
                f"{prefix}: {tot['pv1'] + tot['pv2']:.2f} kWh"
            )
            self._set_card(
                self.card_s1, "—", "No live string reading",
                self.card_s1._today.text(),
            )
            self._set_card(
                self.card_s2, "—", "No live string reading",
                self.card_s2._today.text(),
            )
            self._set_card(self.card_chg, "—", "", self.card_chg._today.text())
            self._set_card(self.card_pv, "—", "", self.card_pv._today.text())
        label = "today" if self._viewing_today() else self._view_day.strftime("%a %-d %b")
        self.set_status(f"PV string charge: {len(self._today)} lot(s) for {label}.")

    def _apply_estimate(self, est: dict, status: dict):
        if not self._viewing_today():
            self._show_past_day_totals()
            self.lbl_updated.setText(f"Updated: {datetime.now().strftime('%H:%M:%S')}")
            return
        self._show_today_card_titles()
        tot = self._today_totals()
        prefix = self._day_energy_prefix()
        pv1 = float(est.get("pv1_kw") or 0.0)
        pv2 = float(est.get("pv2_kw") or 0.0)
        tot_pv = float(est.get("ppv_kw") or 0.0)
        s1 = est.get("est_charge_s1_kw")
        s2 = est.get("est_charge_s2_kw")
        share_pv1 = (pv1 / tot_pv * 100.0) if tot_pv > 0.02 else 0.0
        share_pv2 = (pv2 / tot_pv * 100.0) if tot_pv > 0.02 else 0.0
        chg_now = (
            f"now charging {s1:.2f} kW (est.)"
            if s1 is not None and s1 >= 0.02
            else "not charging the battery from this string now"
        )
        chg_now2 = (
            f"now charging {s2:.2f} kW (est.)"
            if s2 is not None and s2 >= 0.02
            else "not charging the battery from this string now"
        )
        self._set_card(
            self.card_s1,
            f"{pv1:.2f} kW",
            f"{share_pv1:.0f}% of PV now · {chg_now}",
            f"{prefix}: {tot['pv1']:.2f} kWh PV · "
            f"{tot['s1']:.2f} kWh to battery (est.)",
        )
        self._set_card(
            self.card_s2,
            f"{pv2:.2f} kW",
            f"{share_pv2:.0f}% of PV now · {chg_now2}",
            f"{prefix}: {tot['pv2']:.2f} kWh PV · "
            f"{tot['s2']:.2f} kWh to battery (est.)",
        )
        chg = est.get("charge_kw")
        self._set_card(
            self.card_chg,
            "—" if chg is None else f"{chg:.2f} kW",
            "chargePower (measured) now",
            f"{prefix}: {tot['chg']:.2f} kWh charged (measured)",
        )
        self._set_card(
            self.card_pv,
            f"{tot_pv:.2f} kW",
            f"S1 {pv1:.2f} · S2 {pv2:.2f} kW now",
            f"{prefix}: {tot['pv1'] + tot['pv2']:.2f} kWh (S1 {tot['pv1']:.2f} · "
            f"S2 {tot['pv2']:.2f})",
        )

        mode = est.get("mode") or "unknown"
        mode_labels = {
            "charging_pv": "Charging from PV (estimated string split)",
            "charging_ac": "Charging from grid/AC (no string split)",
            "discharging": "Discharging",
            "idle": "Idle / not charging",
            "unknown": "Unknown",
        }
        self.lbl_mode.setText(f"Mode: {mode_labels.get(mode, mode)}")
        v1 = status.get("vPv1")
        v2 = status.get("vPv2")
        extra = []
        if v1 not in (None, ""):
            try:
                extra.append(f"String 1 {float(v1):.0f} V")
            except (TypeError, ValueError):
                pass
        if v2 not in (None, ""):
            try:
                extra.append(f"String 2 {float(v2):.0f} V")
            except (TypeError, ValueError):
                pass
        detail = est.get("notes") or ""
        if extra:
            detail = f"{detail}  ·  {' · '.join(extra)}" if detail else " · ".join(extra)
        self.lbl_detail.setText(detail)
        self.lbl_updated.setText(f"Updated: {datetime.now().strftime('%H:%M:%S')}")

    def _line_w(self) -> float:
        return 72.0 / float(self.fig.dpi or 100)

    def _drop_cum_axis(self):
        ax2 = getattr(self, "_ax_cum", None)
        if ax2 is None:
            return
        try:
            ax2.remove()
        except Exception:
            pass
        self._ax_cum = None

    def _day_bounds(self):
        london = _london_tz()
        day = self._view_day
        start = london.localize(datetime(day.year, day.month, day.day, 0, 0, 0))
        now = datetime.now(london)
        end = start + timedelta(days=1)
        return start, now, end, london

    def _solar_forecast_series(self, t0_utc, t1_utc, london):
        """Times (London) and kW for the solar forecast in this window."""
        t0_key = _aware_utc(t0_utc)
        t1_key = _aware_utc(t1_utc)
        ft = getattr(self, "forecasts_tab", None)
        sdf = getattr(ft, "solar_df", None) if ft is not None else None
        if sdf is not None and not getattr(sdf, "empty", True):
            try:
                ts = pd.to_datetime(sdf["timestamp"], utc=True)
                kw = pd.to_numeric(sdf["kW"], errors="coerce")
                mask = (ts >= t0_key) & (ts <= t1_key) & kw.notna()
                if int(mask.sum()) >= 2:
                    t_loc = ts.loc[mask].dt.tz_convert(london)
                    return list(t_loc.to_pydatetime()), kw.loc[mask].to_numpy(dtype=float)
            except Exception:
                pass
        logger = self.data_logger
        if logger is None:
            return None, None
        now_m = _time_mod.monotonic()
        cache = self._fc_cache
        if (
            cache is not None
            and (now_m - cache[0]) < 60
            and cache[1] == t0_key
            and cache[2] == t1_key
        ):
            return cache[3], cache[4]
        try:
            planned = logger.query_solar_forecast_snapshot(t0_key, t1_key)
        except Exception:
            planned = None
        if planned is None or getattr(planned, "is_empty", lambda: True)():
            self._fc_cache = (now_m, t0_key, t1_key, None, None)
            return None, None
        try:
            t_loc = (
                planned["interval_start"]
                .dt.convert_time_zone("Europe/London")
                .to_list()
            )
            kw = planned["kw"].cast(pl.Float64).to_numpy()
        except Exception:
            self._fc_cache = (now_m, t0_key, t1_key, None, None)
            return None, None
        self._fc_cache = (now_m, t0_key, t1_key, t_loc, kw)
        return t_loc, kw

    def _apply_chart_layout(self):
        self.fig.subplots_adjust(
            left=0.07, right=0.98, top=0.95, bottom=0.08, hspace=0.28,
        )

    def _drop_life_axis(self):
        ax = getattr(self, "ax_life", None)
        if ax is None:
            return
        try:
            ax.remove()
        except Exception:
            pass
        self.ax_life = None

    def _prep_axes(self):
        """Two stacked axes: instantaneous kW (top) and daily kWh (bottom)."""
        self._drop_cum_axis()
        self._drop_life_axis()
        ax = self.ax
        ax_day = getattr(self, "ax_day", None)
        if ax_day is None:
            ax_day = self.fig.add_subplot(212, sharex=ax)
            self.ax_day = ax_day
        ax.clear()
        ax_day.clear()
        _style_ax_dark(ax, self.fig)
        _style_ax_dark(ax_day, self.fig)
        return ax, ax_day

    def _style_time_axis(self, ax, london, t0, t1, *, hour_interval: int):
        import matplotlib.dates as mdates

        ax.set_xlim(t0, t1)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=london))
        ax.xaxis.set_major_locator(
            mdates.HourLocator(interval=hour_interval, tz=london)
        )
        ax.tick_params(axis="x", rotation=0)
        ax.grid(axis="y", color=_DARK_GRID, linewidth=0.4)

    def _draw_empty_chart(self):
        ax, ax_day = self._prep_axes()
        d0, now, d1, london = self._day_bounds()
        stamp = self._day_title_stamp()
        empty = self._empty_lots_text()
        ax.set_title(f"Instantaneous (kW) — {stamp}", fontsize=11, pad=4)
        ax.set_ylabel("kW")
        ax.text(
            0.5, 0.5, empty,
            ha="center", va="center", transform=ax.transAxes,
            color=_DARK_SUBTEXT, fontsize=11,
        )
        self._style_time_axis(ax, london, d0, d1, hour_interval=2)
        ax.tick_params(labelbottom=False)
        if self._viewing_today():
            ax.axvline(now, color=_COL_NOW, linestyle="--", linewidth=self._line_w())
        ax_day.set_title(f"Cumulative (kWh) — {stamp}", fontsize=11, pad=4)
        ax_day.set_ylabel("kWh")
        ax_day.text(
            0.5, 0.5, empty,
            ha="center", va="center", transform=ax_day.transAxes,
            color=_DARK_SUBTEXT, fontsize=11,
        )
        self._style_time_axis(ax_day, london, d0, d1, hour_interval=2)
        if self._viewing_today():
            ax_day.axvline(now, color=_COL_NOW, linestyle="--", linewidth=self._line_w())
        self._apply_chart_layout()
        self.canvas.draw_idle()

    def _draw_instantaneous(self, ax, london, t0, t1, now, lw):
        """Measured string kW, charge kW, and forecast kW for the day on screen."""
        ax.set_title(
            f"Instantaneous (kW) — {self._day_title_stamp()}", fontsize=11, pad=4,
        )
        times, pv1, pv2, chg = [], None, None, None
        if self._history:
            times = [_aware_utc(h["t"]).astimezone(london) for h in self._history]
            pv1 = np.array([h.get("pv1") or 0.0 for h in self._history], dtype=float)
            pv2 = np.array([h.get("pv2") or 0.0 for h in self._history], dtype=float)
            chg = np.array([h.get("chg") or 0.0 for h in self._history], dtype=float)

        fc_t, fc_kw = self._solar_forecast_series(
            t0.astimezone(timezone.utc), t1.astimezone(timezone.utc), london,
        )
        if fc_t is not None and fc_kw is not None and len(fc_t) >= 2:
            ax.fill_between(
                fc_t, fc_kw, color=_COL_FC_FILL, alpha=_FC_FILL_ALPHA,
                linewidth=0, zorder=1,
            )
            ax.plot(
                fc_t, fc_kw, color=_COL_FC_LINE, linewidth=lw,
                solid_capstyle="butt", zorder=2, label="Solar forecast",
            )

        if times:
            ax.fill_between(
                times, pv1, color=_COL_S1, alpha=_FILL_ALPHA, linewidth=0, zorder=3,
            )
            ax.fill_between(
                times, pv2, color=_COL_S2, alpha=_FILL_ALPHA, linewidth=0, zorder=3,
            )
            ax.plot(
                times, pv1, color=_COL_S1, linewidth=lw, solid_capstyle="butt",
                zorder=5, label="String 1",
            )
            ax.plot(
                times, pv2, color=_COL_S2, linewidth=lw, solid_capstyle="butt",
                zorder=5, label="String 2",
            )
            ax.plot(
                times, chg, color=_COL_CHG, linewidth=lw, solid_capstyle="butt",
                zorder=6, label="Measured charge",
            )
        else:
            ax.text(
                0.5, 0.5, self._empty_lots_text(),
                ha="center", va="center", transform=ax.transAxes,
                color=_DARK_SUBTEXT, fontsize=11,
            )

        peak = 0.0
        for arr in (pv1, pv2, chg, fc_kw):
            if arr is None:
                continue
            try:
                if len(arr):
                    peak = max(peak, float(np.nanmax(arr)))
            except (TypeError, ValueError):
                pass
        ax.set_ylabel("kW")
        ax.set_ylim(0.0, max(0.5, peak * 1.15 if peak > 0 else 0.5))
        self._style_time_axis(ax, london, t0, t1, hour_interval=2)
        ax.tick_params(labelbottom=False)
        if self._viewing_today():
            ax.axvline(now, color=_COL_NOW, linestyle="--", linewidth=lw, zorder=8)
        if ax.get_legend_handles_labels()[1]:
            ax.legend(
                loc="upper left", fontsize=8, framealpha=0.6,
                facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT,
            )
        return fc_t, fc_kw

    def _draw_cumulative(self, ax, london, d0, now, d1, lw):
        """Energy for the day on screen: each string, both, forecast (all kWh)."""
        ax.set_title(
            f"Cumulative (kWh) — {self._day_title_stamp()}", fontsize=11, pad=4,
        )
        rows = list(self._today)
        times = []
        if rows:
            raw_t = [_aware_utc(h["t"]).astimezone(london) for h in rows]
            pv1 = np.array([h.get("pv1") or 0.0 for h in rows], dtype=float)
            pv2 = np.array([h.get("pv2") or 0.0 for h in rows], dtype=float)
            # On today, hold the last lot through now so the total matches the cards.
            if self._viewing_today() and raw_t[-1] < now:
                raw_t.append(now)
                pv1 = np.append(pv1, pv1[-1])
                pv2 = np.append(pv2, pv2[-1])
            times = raw_t
            cum1 = _cumulative_kwh(times, pv1)
            cum2 = _cumulative_kwh(times, pv2)
            both = cum1 + cum2
            ax.fill_between(
                times, cum1, color=_COL_S1, alpha=_FILL_ALPHA, linewidth=0, zorder=3,
            )
            ax.fill_between(
                times, cum2, color=_COL_S2, alpha=_FILL_ALPHA, linewidth=0, zorder=3,
            )
            ax.plot(
                times, cum1, color=_COL_S1, linewidth=lw, solid_capstyle="butt",
                zorder=5, label="String 1",
            )
            ax.plot(
                times, cum2, color=_COL_S2, linewidth=lw, solid_capstyle="butt",
                zorder=5, label="String 2",
            )
            ax.plot(
                times, both, color=_COL_BOTH, linewidth=lw * 1.6,
                solid_capstyle="butt", zorder=7, label="Both strings",
            )
        else:
            ax.text(
                0.5, 0.42, self._empty_lots_text(),
                ha="center", va="center", transform=ax.transAxes,
                color=_DARK_SUBTEXT, fontsize=11,
            )

        fc_t, fc_kw = self._solar_forecast_series(
            d0.astimezone(timezone.utc), d1.astimezone(timezone.utc), london,
        )
        if fc_t is not None and fc_kw is not None and len(fc_t) >= 2:
            fc_times = list(fc_t)
            fc_y = np.asarray(fc_kw, dtype=float)
            if fc_times[0] > d0:
                fc_times = [d0] + fc_times
                fc_y = np.concatenate([[0.0], fc_y])
            fc_cum = _cumulative_kwh(fc_times, fc_y)
            ax.fill_between(
                fc_times, fc_cum, color=_COL_FC_FILL, alpha=_FC_FILL_ALPHA,
                linewidth=0, zorder=1,
            )
            ax.plot(
                fc_times, fc_cum, color=_COL_FC_LINE, linewidth=lw,
                solid_capstyle="butt", zorder=2, label="Forecast (cumulative)",
            )
        else:
            fc_cum = None

        peak = 0.0
        if times:
            peak = max(peak, float(np.nanmax(both)))
        if fc_cum is not None and fc_cum.size:
            peak = max(peak, float(np.nanmax(fc_cum)))
        ax.set_ylabel("kWh")
        ax.set_ylim(0.0, max(0.2, peak * 1.15 if peak > 0 else 0.2))
        self._style_time_axis(ax, london, d0, d1, hour_interval=2)
        if self._viewing_today():
            ax.axvline(now, color=_COL_NOW, linestyle="--", linewidth=lw, zorder=8)
        if ax.get_legend_handles_labels()[1]:
            ax.legend(
                loc="upper left", fontsize=8, framealpha=0.6,
                facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT,
            )

    def _draw_chart(self):
        self._trim_history()
        ax, ax_day = self._prep_axes()
        d0, now, d1, london = self._day_bounds()
        lw = self._line_w()
        self._draw_instantaneous(ax, london, d0, d1, now, lw)
        self._draw_cumulative(ax_day, london, d0, now, d1, lw)
        self._apply_chart_layout()
        self.canvas.draw_idle()


__all__ = ["PvStringChargeTab", "estimate_string_charge"]
