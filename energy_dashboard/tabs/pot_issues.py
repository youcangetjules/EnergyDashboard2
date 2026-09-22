"""
Energy Dashboard — Potential Issues (Physical Plant Tools group).

Compare Growatt actual PV (+ usage) vs our solar forecast and Wonderwatt,
with an interactive Lock that ends the open learning period.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from energy_dashboard.common import *
from energy_dashboard.fetch.wonderwatt import (
    fetch_wonderwatt_daily_forecast,
    load_wonderwatt_share_url,
    merge_wonderwatt_daily_paste,
    parse_wonderwatt_share_url,
    save_wonderwatt_share_url,
    test_wonderwatt_connection,
)
from energy_dashboard.ui.buttons import _apply_primary_button_style

_LONDON = ZoneInfo("Europe/London")
_WINDOW_DAYS = 14
_QS_LOCKED = "pot_issues/locked"
_QS_LOCKED_AT = "pot_issues/locked_at"
_QS_BASELINE = "pot_issues/baseline_json"
_QS_THR_PCT = "pot_issues/threshold_pct"
_QS_THR_KWH = "pot_issues/threshold_kwh"
_DEFAULT_THR_PCT = 20.0
_DEFAULT_THR_KWH = 1.5


def _pot_settings():
    return QSettings("PowerModel", "EnergyDashboard2")


def _trap_kwh(ts_local, kw_arr) -> float | None:
    """Trapezoid integrate kW vs local timestamps → kWh, or None if sparse."""
    if ts_local is None or kw_arr is None:
        return None
    n = len(kw_arr)
    if n < 2:
        return None
    try:
        import matplotlib.dates as mdates
        import numpy as np
    except Exception:
        return None
    t_num = mdates.date2num(ts_local)
    h_hours = (t_num - t_num[0]) * 24.0
    trap = getattr(np, "trapezoid", None)
    if trap is not None:
        return float(trap(kw_arr, h_hours))
    return float(np.trapz(kw_arr, h_hours))


def _day_bounds_london(d: date):
    day0 = datetime.combine(d, time.min, tzinfo=_LONDON)
    day1 = day0 + timedelta(days=1)
    return day0, day1


def _fmt_kwh(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return "—"


def _delta_pct(actual, forecast) -> float | None:
    if actual is None or forecast is None:
        return None
    try:
        a, f = float(actual), float(forecast)
    except (TypeError, ValueError):
        return None
    if abs(f) < 1e-6:
        return None
    return 100.0 * (a - f) / f


def _misses_threshold(actual, forecast, thr_pct: float, thr_kwh: float) -> bool:
    if actual is None or forecast is None:
        return False
    try:
        a, f = float(actual), float(forecast)
    except (TypeError, ValueError):
        return False
    err = abs(a - f)
    floor = max(float(thr_kwh), abs(f) * float(thr_pct) / 100.0)
    return err > floor


class PotIssuesTab(QWidget):
    """Learning / Lock comparison of actual PV vs forecasts."""

    def __init__(self, forecasts_tab, data_logger, growatt_tab, status_callback):
        super().__init__()
        self.forecasts_tab = forecasts_tab
        self.data_logger = data_logger
        self.growatt_tab = growatt_tab
        self.set_status = status_callback
        self.on_data_updated = None
        self._rows: list[dict] = []
        self._ww_message = ""
        self._ww_conn_ok: bool | None = None
        self._ww_conn_detail = "Wonderwatt: not tested yet."
        self.build_ui()
        self._sync_lock_ui()

    # ── persistence ─────────────────────────────────────────────────────

    def is_locked(self) -> bool:
        v = _pot_settings().value(_QS_LOCKED, False)
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("1", "true", "yes")

    def locked_at(self) -> datetime | None:
        raw = str(_pot_settings().value(_QS_LOCKED_AT, "") or "").strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None

    def load_baseline(self) -> dict:
        raw = _pot_settings().value(_QS_BASELINE, "")
        if not raw:
            return {}
        try:
            data = json.loads(str(raw))
            return data if isinstance(data, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def threshold_pct(self) -> float:
        try:
            return float(_pot_settings().value(_QS_THR_PCT, _DEFAULT_THR_PCT))
        except (TypeError, ValueError):
            return _DEFAULT_THR_PCT

    def threshold_kwh(self) -> float:
        try:
            return float(_pot_settings().value(_QS_THR_KWH, _DEFAULT_THR_KWH))
        except (TypeError, ValueError):
            return _DEFAULT_THR_KWH

    def _save_thresholds_from_spin(self):
        s = _pot_settings()
        s.setValue(_QS_THR_PCT, float(self.spin_thr_pct.value()))
        s.setValue(_QS_THR_KWH, float(self.spin_thr_kwh.value()))
        s.sync()

    # ── UI ──────────────────────────────────────────────────────────────

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        intro = QLabel(
            "<b>Analysis only.</b> Comparisons use measured Growatt PV/load and "
            "forecast curves as stored — nothing is rescaled. "
            "<b>Lock</b> is your judgment that forecasts and generation look "
            "aligned; it is not automatic truth."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        root.addWidget(intro)

        # Wonderwatt
        ww_box = QGroupBox("Wonderwatt share link")
        ww_lay = QVBoxLayout(ww_box)
        row = QHBoxLayout()
        self.ww_url = QLineEdit()
        self.ww_url.setPlaceholderText(
            "https://app.wonderwatt.com/?wattid=…&sig=…&time=…"
        )
        self.ww_url.setText(load_wonderwatt_share_url())
        self.ww_url.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        row.addWidget(self.ww_url, 1)
        self.btn_ww_save = QPushButton("Save")
        self.btn_ww_save.clicked.connect(self._on_save_ww)
        _apply_primary_button_style(self.btn_ww_save)
        row.addWidget(self.btn_ww_save)
        self.btn_ww_test = QPushButton("Test connection")
        self.btn_ww_test.setToolTip(
            "Probe the Wonderwatt share link and show Connected or Failed."
        )
        self.btn_ww_test.clicked.connect(self._on_test_ww)
        _apply_primary_button_style(self.btn_ww_test)
        row.addWidget(self.btn_ww_test)
        self.lbl_ww_chip = QLabel("Not tested")
        self.lbl_ww_chip.setAlignment(Qt.AlignCenter)
        self.lbl_ww_chip.setMinimumWidth(96)
        row.addWidget(self.lbl_ww_chip)
        ww_lay.addLayout(row)
        self.lbl_ww_status = QLabel("Wonderwatt: not tested yet.")
        self.lbl_ww_status.setWordWrap(True)
        ww_lay.addWidget(self.lbl_ww_status)
        self._set_ww_connection_ui(None, "Wonderwatt: not tested yet.")

        paste_row = QHBoxLayout()
        self.ww_paste = QTextEdit()
        self.ww_paste.setPlaceholderText(
            "Optional daily WW kWh paste (one per line):\n"
            "2026-09-08 12.5\n"
            "or JSON {\"2026-09-08\": 12.5}"
        )
        self.ww_paste.setMaximumHeight(72)
        paste_row.addWidget(self.ww_paste, 1)
        self.btn_ww_paste = QPushButton("Merge paste")
        self.btn_ww_paste.setToolTip(
            "Merge pasted Wonderwatt daily kWh into local storage "
            "(used until a live forecast API is available)."
        )
        self.btn_ww_paste.clicked.connect(self._on_merge_paste)
        _apply_primary_button_style(self.btn_ww_paste)
        paste_row.addWidget(self.btn_ww_paste, 0, Qt.AlignTop)
        ww_lay.addLayout(paste_row)
        root.addWidget(ww_box)

        # Lock / learning
        lock_box = QGroupBox("Learning / Lock")
        lock_lay = QVBoxLayout(lock_box)
        chip_row = QHBoxLayout()
        self.lbl_lock_chip = QLabel("Learning")
        self.lbl_lock_chip.setStyleSheet(
            "background:#89b4fa; color:#1e1e2e; font-weight:bold; "
            "padding:4px 10px; border-radius:4px;"
        )
        chip_row.addWidget(self.lbl_lock_chip)
        chip_row.addStretch(1)
        self.btn_lock = QPushButton("Lock")
        self.btn_lock.setToolTip(
            "Record that forecast + generation (+ usage) look aligned as of now."
        )
        self.btn_lock.clicked.connect(self._on_lock)
        _apply_primary_button_style(self.btn_lock)
        chip_row.addWidget(self.btn_lock)
        self.btn_unlock = QPushButton("Unlock")
        self.btn_unlock.setToolTip("Clear the lock baseline and return to learning.")
        self.btn_unlock.clicked.connect(self._on_unlock)
        _apply_primary_button_style(self.btn_unlock)
        chip_row.addWidget(self.btn_unlock)
        lock_lay.addLayout(chip_row)
        self.lbl_lock_note = QLabel(
            "Lock captures today’s comparison snapshot (actual PV, our forecast, "
            "Wonderwatt if present, usage). After lock, days that miss the "
            "threshold below are listed as potential issues."
        )
        self.lbl_lock_note.setWordWrap(True)
        self.lbl_lock_note.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px;")
        lock_lay.addWidget(self.lbl_lock_note)

        thr_row = QHBoxLayout()
        thr_row.addWidget(QLabel("Issue if |actual − our forecast| >"))
        self.spin_thr_pct = QDoubleSpinBox()
        self.spin_thr_pct.setRange(1.0, 100.0)
        self.spin_thr_pct.setSuffix(" %")
        self.spin_thr_pct.setDecimals(0)
        self.spin_thr_pct.setValue(self.threshold_pct())
        thr_row.addWidget(self.spin_thr_pct)
        thr_row.addWidget(QLabel("or"))
        self.spin_thr_kwh = QDoubleSpinBox()
        self.spin_thr_kwh.setRange(0.1, 50.0)
        self.spin_thr_kwh.setSuffix(" kWh")
        self.spin_thr_kwh.setDecimals(1)
        self.spin_thr_kwh.setValue(self.threshold_kwh())
        thr_row.addWidget(self.spin_thr_kwh)
        thr_row.addWidget(QLabel("(whichever is larger)"))
        thr_row.addStretch(1)
        lock_lay.addLayout(thr_row)
        root.addWidget(lock_box)

        # Toolbar
        bar = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh_now)
        _apply_primary_button_style(self.btn_refresh)
        bar.addWidget(self.btn_refresh)
        bar.addStretch(1)
        self.lbl_updated = QLabel("Updated: —")
        self.lbl_updated.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px;")
        bar.addWidget(self.lbl_updated)
        root.addLayout(bar)

        # Issues strip
        self.lbl_issues = QLabel("Learning — Lock when aligned.")
        self.lbl_issues.setWordWrap(True)
        self.lbl_issues.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        root.addWidget(self.lbl_issues)

        # Table
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [
                "Day (local)",
                "Actual PV",
                "Our forecast",
                "Wonderwatt",
                "Usage",
                "Δ vs our forecast",
                "Status",
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(180)
        root.addWidget(self.table, 2)

        # Chart
        chart_box = QGroupBox("Daily kWh — actual vs forecasts")
        chart_lay = QVBoxLayout(chart_box)
        self.fig = Figure(figsize=(8, 3.2), tight_layout=True)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        chart_lay.addWidget(self.canvas)
        chart_lay.addWidget(DarkNavigationToolbar(self.canvas, self))
        root.addWidget(chart_box, 3)

        self._draw_empty_chart()

    def _sync_lock_ui(self):
        locked = self.is_locked()
        at = self.locked_at()
        if locked and at is not None:
            local = at.astimezone(_LONDON)
            self.lbl_lock_chip.setText(
                f"Locked since {local.strftime('%Y-%m-%d %H:%M %Z')}"
            )
            self.lbl_lock_chip.setStyleSheet(
                "background:#a6e3a1; color:#1e1e2e; font-weight:bold; "
                "padding:4px 10px; border-radius:4px;"
            )
            self.btn_lock.setEnabled(False)
            self.btn_unlock.setEnabled(True)
        else:
            self.lbl_lock_chip.setText("Learning")
            self.lbl_lock_chip.setStyleSheet(
                "background:#89b4fa; color:#1e1e2e; font-weight:bold; "
                "padding:4px 10px; border-radius:4px;"
            )
            self.btn_lock.setEnabled(True)
            self.btn_unlock.setEnabled(False)

    # ── Wonderwatt actions ──────────────────────────────────────────────

    def _set_ww_connection_ui(self, ok: bool | None, detail: str):
        """Update Connected/Failed chip + coloured detail line.

        ``ok`` is True (good), False (failed), or None (not tested / neutral).
        """
        detail = (detail or "").strip() or "—"
        if ok is True:
            chip, bg, fg = "Connected", "#a6e3a1", "#1e1e2e"
            detail_color = "#a6e3a1"
            prefix = "✓ Connection good — "
        elif ok is False:
            chip, bg, fg = "Failed", "#f38ba8", "#1e1e2e"
            detail_color = "#f38ba8"
            prefix = "✗ Connection failed — "
        else:
            chip, bg, fg = "Not tested", "#6c7086", "#cdd6f4"
            detail_color = _DARK_SUBTEXT
            prefix = ""
        self._ww_conn_ok = ok
        text = detail if detail.startswith(("✓", "✗")) else f"{prefix}{detail}"
        self._ww_conn_detail = text
        self.lbl_ww_chip.setText(chip)
        self.lbl_ww_chip.setStyleSheet(
            f"background:{bg}; color:{fg}; font-weight:bold; "
            f"padding:4px 10px; border-radius:4px; font-size:12px;"
        )
        self.lbl_ww_status.setText(text)
        self.lbl_ww_status.setStyleSheet(
            f"color: {detail_color}; font-size: 12px; font-weight: bold;"
        )

    def _on_save_ww(self):
        parsed = save_wonderwatt_share_url(self.ww_url.text())
        if parsed is None:
            self._set_ww_connection_ui(
                False,
                "Invalid share URL — need wattid, sig, and time query params.",
            )
            self.set_status("Wonderwatt share URL cleared / invalid.")
            return
        self.ww_url.setText(parsed["share_url"])
        self._set_ww_connection_ui(
            None,
            f"Saved share link for wattid={parsed['wattid']} "
            "(local QSettings only). Click Test connection to verify.",
        )
        self.set_status("Wonderwatt share URL saved.")

    def _on_test_ww(self):
        url = self.ww_url.text().strip() or load_wonderwatt_share_url()
        self.btn_ww_test.setEnabled(False)
        self._set_ww_connection_ui(None, "Testing Wonderwatt share link…")
        QApplication.processEvents()
        try:
            ok, msg = test_wonderwatt_connection(url)
        except Exception as exc:
            ok, msg = False, str(exc)
        finally:
            self.btn_ww_test.setEnabled(True)
        self._set_ww_connection_ui(ok, msg)
        if ok:
            self.set_status("Wonderwatt connection: good")
        else:
            self.set_status(f"Wonderwatt connection failed — {msg}")

    def _on_merge_paste(self):
        mapping = merge_wonderwatt_daily_paste(self.ww_paste.toPlainText())
        # Keep last connection chip; only update the detail note neutrally.
        self.lbl_ww_status.setText(
            f"Merged paste — {len(mapping)} Wonderwatt day(s) stored locally."
        )
        self.lbl_ww_status.setStyleSheet(
            f"color: {_DARK_SUBTEXT}; font-size: 12px; font-weight: bold;"
        )
        self.set_status(f"Wonderwatt daily paste: {len(mapping)} day(s).")
        self.refresh_now()

    # ── Lock ────────────────────────────────────────────────────────────

    def _on_lock(self):
        if not self._rows:
            self.refresh_now()
        today = datetime.now(_LONDON).date()
        today_row = next((r for r in self._rows if r.get("day") == today), None)
        baseline = {
            "day": today.isoformat(),
            "actual_pv": today_row.get("actual_pv") if today_row else None,
            "our_fc": today_row.get("our_fc") if today_row else None,
            "ww_fc": today_row.get("ww_fc") if today_row else None,
            "usage": today_row.get("usage") if today_row else None,
            "locked_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_thresholds_from_spin()
        s = _pot_settings()
        s.setValue(_QS_LOCKED, True)
        s.setValue(_QS_LOCKED_AT, baseline["locked_at"])
        s.setValue(_QS_BASELINE, json.dumps(baseline))
        s.sync()
        self._sync_lock_ui()
        self._populate_table_and_chart()
        self.set_status(
            f"Potential Issues locked — baseline day {baseline['day']}."
        )

    def _on_unlock(self):
        s = _pot_settings()
        s.setValue(_QS_LOCKED, False)
        s.remove(_QS_LOCKED_AT)
        s.remove(_QS_BASELINE)
        s.sync()
        self._sync_lock_ui()
        self._populate_table_and_chart()
        self.set_status("Potential Issues unlocked — learning mode.")

    # ── Data ────────────────────────────────────────────────────────────

    def _our_forecast_kwh(self, day: date) -> float | None:
        ft = self.forecasts_tab
        if ft is None:
            return None
        day0, _ = _day_bounds_london(day)
        try:
            return ft._solar_forecast_kwh_for_day(_LONDON, day0)
        except Exception as exc:
            _log.warn("PotIssues", f"Our forecast day {day}: {exc}")
            return None

    def _growatt_day_totals(self, day: date) -> tuple[float | None, float | None]:
        """Return (actual_pv_kwh, usage_kwh) via trapezoid of power flows."""
        logger = self.data_logger
        if logger is None:
            return None, None
        day0, day1 = _day_bounds_london(day)
        now_l = datetime.now(_LONDON)
        end = min(day1, now_l) if day == now_l.date() else day1
        try:
            flows = logger.query_growatt_power_flows(
                day0.astimezone(timezone.utc),
                end.astimezone(timezone.utc),
            )
        except Exception as exc:
            _log.warn("PotIssues", f"Growatt flows {day}: {exc}")
            return None, None
        if flows is None or flows.is_empty() or flows.height < 2:
            return None, None
        try:
            local = (
                flows["timestamp"]
                .dt.convert_time_zone("Europe/London")
                .to_numpy()
            )
            pv = flows["pv_kw"].fill_null(0.0).cast(pl.Float64).to_numpy()
            load = flows["load_kw"].fill_null(0.0).cast(pl.Float64).to_numpy()
        except Exception as exc:
            _log.warn("PotIssues", f"Growatt numpy {day}: {exc}")
            return None, None
        return _trap_kwh(local, pv), _trap_kwh(local, load)

    def _build_rows(self) -> list[dict]:
        today = datetime.now(_LONDON).date()
        start = today - timedelta(days=_WINDOW_DAYS - 1)
        ww = fetch_wonderwatt_daily_forecast(start, today)
        self._ww_message = ww.get("message") or ""
        # Refresh must not wipe a Connected/Failed result from Test connection.
        if self._ww_conn_ok is None and self._ww_message:
            self.lbl_ww_status.setText(self._ww_message)
            self.lbl_ww_status.setStyleSheet(
                f"color: {_DARK_SUBTEXT}; font-size: 12px; font-weight: bold;"
            )

        locked = self.is_locked()
        locked_at = self.locked_at()
        lock_day = None
        if locked_at is not None:
            lock_day = locked_at.astimezone(_LONDON).date()
        thr_pct = float(self.spin_thr_pct.value())
        thr_kwh = float(self.spin_thr_kwh.value())

        rows: list[dict] = []
        cur = start
        while cur <= today:
            actual, usage = self._growatt_day_totals(cur)
            our = self._our_forecast_kwh(cur)
            ww_fc = ww.get("days", {}).get(cur.isoformat())
            if ww_fc is not None:
                try:
                    ww_fc = float(ww_fc)
                except (TypeError, ValueError):
                    ww_fc = None
            dlt = _delta_pct(actual, our)
            if not locked:
                status = "learning"
            elif lock_day is not None and cur < lock_day:
                status = "pre-lock"
            elif _misses_threshold(actual, our, thr_pct, thr_kwh):
                status = "potential issue"
            elif actual is not None and our is not None:
                status = "aligned"
            else:
                status = "learning" if not locked else "incomplete"
            rows.append(
                {
                    "day": cur,
                    "actual_pv": actual,
                    "our_fc": our,
                    "ww_fc": ww_fc,
                    "usage": usage,
                    "delta_pct": dlt,
                    "status": status,
                }
            )
            cur += timedelta(days=1)
        return rows

    def refresh_now(self):
        self._save_thresholds_from_spin()
        try:
            self._rows = self._build_rows()
        except Exception as exc:
            _log.warn("PotIssues", f"Refresh failed: {exc}")
            self.set_status(f"Potential Issues refresh failed: {exc}")
            self._rows = []
        self._populate_table_and_chart()
        self.lbl_updated.setText(
            f"Updated: {datetime.now(_LONDON).strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )
        self.set_status(
            f"Potential Issues: {len(self._rows)} day(s) compared."
        )
        if callable(self.on_data_updated):
            try:
                self.on_data_updated()
            except Exception:
                pass

    def _populate_table_and_chart(self):
        rows = self._rows
        locked = self.is_locked()
        issues = [r for r in rows if r.get("status") == "potential issue"]
        if not locked:
            self.lbl_issues.setText("Learning — Lock when aligned.")
        elif not issues:
            self.lbl_issues.setText(
                "Locked — no potential issues in the visible window."
            )
        else:
            days = ", ".join(r["day"].isoformat() for r in issues)
            self.lbl_issues.setText(
                f"Potential issues ({len(issues)}): {days}"
            )

        self.table.setRowCount(len(rows))
        for i, r in enumerate(reversed(rows)):  # newest first
            vals = [
                r["day"].isoformat(),
                _fmt_kwh(r["actual_pv"]),
                _fmt_kwh(r["our_fc"]),
                _fmt_kwh(r["ww_fc"]),
                _fmt_kwh(r["usage"]),
                (
                    f"{r['delta_pct']:+.0f}%"
                    if r.get("delta_pct") is not None
                    else "—"
                ),
                r.get("status") or "—",
            ]
            for c, text in enumerate(vals):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                st = r.get("status")
                if st == "potential issue":
                    item.setForeground(QColor("#f38ba8"))
                elif st == "aligned":
                    item.setForeground(QColor("#a6e3a1"))
                elif st == "learning":
                    item.setForeground(QColor("#89b4fa"))
                self.table.setItem(i, c, item)

        self._draw_chart(rows)

    def _solar_latlon_for_locale(self) -> tuple[float | None, float | None]:
        """Prefer Setup/QSettings installation coords over live Forecasts fields."""
        try:
            s = _pot_settings()
            lat_s = str(s.value("params/solar_lat", "") or "").strip()
            lon_s = str(s.value("params/solar_lon", "") or "").strip()
            if lat_s and lon_s:
                return round(float(lat_s), 5), round(float(lon_s), 5)
        except (TypeError, ValueError):
            pass
        ft = self.forecasts_tab
        if ft is not None and hasattr(ft, "_current_latlon_5dp"):
            try:
                return ft._current_latlon_5dp()
            except Exception:
                pass
        return None, None

    def _locale_place_label(self) -> str:
        """Settlement name for the saved solar location (not a hardcoded city)."""
        lat, lon = self._solar_latlon_for_locale()
        candidates = []
        ft = self.forecasts_tab
        if lat is not None and lon is not None and ft is not None:
            try:
                from energy_dashboard.tabs.forecasts import _FORECAST_LOCALE_CACHE_VER
                cached = (getattr(ft, "_locale_cache", None) or {}).get(
                    (lat, lon, _FORECAST_LOCALE_CACHE_VER)
                )
                if cached:
                    candidates.append(str(cached).strip())
            except Exception:
                pass
            # If Forecasts fields match Setup coords, its cache / banner is trustworthy.
            try:
                flat, flon = ft._current_latlon_5dp()
                if flat == lat and flon == lon:
                    dash = getattr(ft, "dash", None)
                    if dash is None and hasattr(ft, "_find_dashboard"):
                        dash = ft._find_dashboard()
                    if dash is not None:
                        lbl = getattr(dash, "_banner_locale_place", None)
                        if lbl is not None:
                            candidates.append(str(lbl.text() or "").strip())
            except Exception:
                pass
        for raw in candidates:
            if not raw or raw in ("—", "-", "Looking up…", "Unknown locale"):
                continue
            place = raw.split("·", 1)[0].strip() or raw
            # Never present a district name as the locale (e.g. South Oxfordshire).
            if place.lower().endswith("oxfordshire") and " " in place.lower():
                continue
            if place:
                return place
        # Kick a locale refresh so the next chart draw can use Nominatim.
        if ft is not None and hasattr(ft, "_refresh_locale_label"):
            try:
                ft._refresh_locale_label()
            except Exception:
                pass
        return "local"

    def _draw_empty_chart(self):
        self.ax.clear()
        _style_ax_dark(self.ax, self.fig)
        self.ax.set_ylabel("kWh")
        self.ax.set_title("Refresh to load daily comparisons")
        self.canvas.draw_idle()

    def _draw_chart(self, rows: list[dict]):
        self.ax.clear()
        _style_ax_dark(self.ax, self.fig)
        if not rows:
            self.ax.set_title("No data")
            self.canvas.draw_idle()
            return
        import numpy as np

        labels = [r["day"].strftime("%a %m-%d") for r in rows]
        x = np.arange(len(rows))
        w = 0.25
        actual = [r["actual_pv"] if r["actual_pv"] is not None else 0.0 for r in rows]
        our = [r["our_fc"] if r["our_fc"] is not None else 0.0 for r in rows]
        ww = [r["ww_fc"] if r["ww_fc"] is not None else 0.0 for r in rows]
        has_ww = any(r["ww_fc"] is not None for r in rows)

        self.ax.bar(x - w, actual, w, label="Actual PV", color="#fab387", alpha=0.9)
        self.ax.bar(x, our, w, label="Our forecast", color="#f9e2af", alpha=0.9)
        if has_ww:
            self.ax.bar(x + w, ww, w, label="Wonderwatt", color="#89b4fa", alpha=0.9)
        self.ax.set_xticks(x)
        self.ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        self.ax.set_ylabel("kWh")
        self.ax.legend(loc="upper left", fontsize=8)
        place = self._locale_place_label()
        self.ax.set_title(
            f"Estimated vs Actual consumption — last {len(rows)} days in {place}"
        )
        # Keep table day column in sync with the same place name.
        try:
            item = self.table.horizontalHeaderItem(0)
            if item is not None:
                item.setText(f"Day ({place})")
        except Exception:
            pass
        self.fig.tight_layout()
        self.canvas.draw_idle()


__all__ = ["PotIssuesTab"]
