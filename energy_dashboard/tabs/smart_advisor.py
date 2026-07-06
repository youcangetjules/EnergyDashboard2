"""
Energy Dashboard — `tabs/smart_advisor.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
def _mix_ac_charge_api_params(charge_power, charge_stop_soc, mains_enabled, periods):
    """Param dict for GrowattApi.update_mix_inverter_setting(..., 'mix_ac_charge_time_period', params).

    Layout matches growattServer SPH write_ac_charge_times (mixSet / mixSetApiNew).
    """
    if not (0 <= charge_power <= 100 and 0 <= charge_stop_soc <= 100):
        raise ValueError("charge power and stop SOC must be 0–100")
    if len(periods) != 3:
        raise ValueError("exactly 3 time periods required")
    req = {
        "param1": str(int(charge_power)),
        "param2": str(int(charge_stop_soc)),
        "param3": "1" if mains_enabled else "0",
    }
    for i, period in enumerate(periods):
        base = i * 5 + 4
        st = period["start_time"]
        et = period["end_time"]
        req[f"param{base}"] = str(st.hour)
        req[f"param{base + 1}"] = str(st.minute)
        req[f"param{base + 2}"] = str(et.hour)
        req[f"param{base + 3}"] = str(et.minute)
        req[f"param{base + 4}"] = "1" if period["enabled"] else "0"
    return req


def _mix_ac_discharge_api_params(discharge_power, discharge_stop_soc, periods):
    """Param dict for GrowattApi.update_mix_inverter_setting(..., 'mix_ac_discharge_time_period', params).

    Layout matches growattServer SPH write_ac_discharge_times. NOTE: unlike the
    AC-charge schedule there is NO global ``mains_enabled`` master switch — the
    period offsets therefore start at ``param3`` instead of ``param4``. Each of
    the 3 periods gets 5 params: start_h, start_m, end_h, end_m, enabled.

    Total wire layout (param1..param17):
        param1 = discharge_power %
        param2 = discharge_stop_soc % (battery floor — discharge stops here)
        param{3..7}   = period 1
        param{8..12}  = period 2
        param{13..17} = period 3
    """
    if not (0 <= discharge_power <= 100 and 0 <= discharge_stop_soc <= 100):
        raise ValueError("discharge power and stop SOC must be 0–100")
    if len(periods) != 3:
        raise ValueError("exactly 3 time periods required")
    req = {
        "param1": str(int(discharge_power)),
        "param2": str(int(discharge_stop_soc)),
    }
    for i, period in enumerate(periods):
        base = i * 5 + 3
        st = period["start_time"]
        et = period["end_time"]
        req[f"param{base}"] = str(st.hour)
        req[f"param{base + 1}"] = str(st.minute)
        req[f"param{base + 2}"] = str(et.hour)
        req[f"param{base + 3}"] = str(et.minute)
        req[f"param{base + 4}"] = "1" if period["enabled"] else "0"
    return req


def _qtime_to_time(qt):
    return time(qt.hour(), qt.minute(), qt.second() if qt.second() else 0)


def _solar_kwh_from_now(solar_df, now_london, end_hour=20, forecast_scale=0.7):
    """Integrate forecast.solar kW from ``now`` through ``end_hour`` local (kWh)."""
    if solar_df is None or solar_df.empty or 'kW' not in solar_df.columns:
        return None
    london = pd.Timestamp(now_london)
    if london.tzinfo is None:
        london = london.tz_localize('Europe/London')
    else:
        london = london.tz_convert('Europe/London')
    end = london.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if end <= london:
        end = end + pd.Timedelta(days=1)
    sdf = solar_df.copy()
    ts = pd.to_datetime(sdf['timestamp'], utc=True).dt.tz_convert('Europe/London')
    sdf = sdf.assign(_t=ts).sort_values('_t')
    m = (sdf['_t'] >= london) & (sdf['_t'] <= end)
    sdf = sdf.loc[m]
    if len(sdf) < 2:
        return 0.0
    t_h = sdf['_t'].astype('int64').to_numpy(dtype=float) / 3.6e12
    kw = sdf['kW'].to_numpy(dtype=float)
    trap = getattr(np, 'trapezoid', None) or np.trapz
    kwh = float(trap(kw, t_h)) * float(forecast_scale)
    return max(0.0, kwh)


def _estimate_midday_heater_kw(usage_profile_by_hour, scheduled_loads=None,
                               window_hours=(11, 14), default_kw=_PLAN_HEATER_KW):
    """Typical immersion draw (kW) from profile bump or scheduled_loads in the window."""
    lo, hi = window_hours
    peak_kw = 0.0
    for h in range(lo, hi + 1):
        peak_kw = max(peak_kw, float(usage_profile_by_hour.get(h, 0.2)) * 2.0)
    for sched in scheduled_loads or []:
        sh = int(sched.get('hour', 0))
        kw = float(sched.get('kw', 0))
        if kw <= 0:
            continue
        dur_h = max(1, (int(sched.get('duration_min', 60)) + 29) // 60)
        for h in range(sh, min(sh + dur_h, 24)):
            if lo <= h <= hi:
                peak_kw = max(peak_kw, kw)
    if peak_kw < 1.5:
        peak_kw = float(default_kw)
    return peak_kw


def assess_live_grid_import_need(
    *,
    now_london,
    soc_pct,
    pv_kw,
    load_kw,
    bat_power_kw,
    grid_import_kw,
    usage_profile_by_hour,
    solar_df=None,
    agile_price_p=None,
    cheap_threshold_p=15.0,
    capacity_kwh=13.0,
    max_charge_kw=3.3,
    solar_forecast_scale=_PLAN_SOLAR_FORECAST_SCALE,
    scheduled_loads=None,
):
    """Judge whether present grid import is justified (midday PV + high SOC scenario).

    Returns a dict with ``summary`` (one line), ``lines`` (detail), ``unnecessary`` (bool).
    """
    lines = []
    try:
        soc = float(soc_pct)
    except (TypeError, ValueError):
        soc = 50.0
    pv = max(0.0, float(pv_kw or 0))
    load = max(0.0, float(load_kw or 0))
    bat = float(bat_power_kw or 0)
    g_imp = max(0.0, float(grid_import_kw or 0))
    charge_kw = max(0.0, bat)

    hour = int(pd.Timestamp(now_london).hour) if now_london is not None else 12
    is_daylight = 9 <= hour < 18

    heater_kw = _estimate_midday_heater_kw(
        usage_profile_by_hour, scheduled_loads, window_hours=(11, 14)
    )
    # kWh in each half-hour slot for hours 11–14 from profile (immersion block).
    heater_kwh_2h = sum(
        float(usage_profile_by_hour.get(h, 0.4 * 0.5))
        for h in (11, 12, 13, 14)
    )
    if heater_kwh_2h < 1.0:
        heater_kwh_2h = heater_kw * 2.0  # ~2 h at rated kW

    solar_remain = _solar_kwh_from_now(
        solar_df, now_london, end_hour=20, forecast_scale=solar_forecast_scale
    )
    load_to_evening = sum(
        float(usage_profile_by_hour.get(h, 0.4 * 0.5)) * 2.0
        for h in range(hour, 20)
    )

    net_instant_kw = load + charge_kw - pv
    headroom_kwh = max(0.0, capacity_kwh * 0.92 - capacity_kwh * soc / 100.0)

    spot = agile_price_p
    if spot is None:
        spot_s = "—"
    else:
        spot_s = f"{float(spot):.1f}"

    lines.append(f"  Live @ {pd.Timestamp(now_london).strftime('%H:%M')} London")
    lines.append(
        f"  PV {pv:.2f} kW  |  Load {load:.2f} kW  |  Battery {'+' if bat >= 0 else ''}{bat:.2f} kW"
        f"  |  Grid import {g_imp:.2f} kW  |  SOC {soc:.0f}%"
    )
    lines.append(
        f"  Usage profile: ~{heater_kw:.1f} kW immersion (11:00–14:00), "
        f"~{heater_kwh_2h:.1f} kWh over that block"
    )
    if solar_remain is not None:
        lines.append(
            f"  Solar still forecast today (now→20:00): ~{solar_remain:.1f} kWh  |  "
            f"Profile load same period: ~{load_to_evening:.1f} kWh"
        )
    lines.append(f"  Agile import now: {spot_s} p/kWh  (cheap threshold {cheap_threshold_p:.1f}p)")

    unnecessary = False
    verdict_parts = []

    if g_imp < 0.15:
        summary = "Grid import negligible — no action."
        lines.append("  >> Import is near zero.")
        return {
            'summary': summary, 'lines': lines, 'unnecessary': False,
            'heater_kw': heater_kw, 'solar_remain_kwh': solar_remain,
        }

    if is_daylight and soc >= 75 and pv >= 1.0:
        if net_instant_kw < 0.4:
            unnecessary = True
            verdict_parts.append(
                f"PV ({pv:.1f} kW) already covers load ({load:.1f} kW)"
                + (f" and battery charge ({charge_kw:.1f} kW)" if charge_kw > 0.05 else "")
            )
        elif charge_kw > 0.2 and soc >= 85:
            unnecessary = True
            verdict_parts.append(
                f"Battery at {soc:.0f}% — topping up from grid while PV is strong is usually wasteful"
            )

    if solar_remain is not None and solar_remain > load_to_evening + 0.5:
        if soc >= 70:
            unnecessary = True
            verdict_parts.append(
                f"~{solar_remain:.1f} kWh solar still expected vs ~{load_to_evening:.1f} kWh "
                f"profile load to 20:00 (incl. midday heater)"
            )

    if spot is not None and float(spot) <= 3.0 and unnecessary:
        lines.append(
            "  Note: spot price is very low — grid import is cheap even if not strictly needed."
        )
        unnecessary = False
        verdict_parts.append(f"spot import only {float(spot):.1f}p — marginal cost is tiny")
    elif spot is not None and float(spot) > cheap_threshold_p and unnecessary:
        verdict_parts.append(
            f"paying {float(spot):.1f}p/kWh for import you may not need"
        )

    if unnecessary:
        summary = (
            f"Import ~{g_imp:.1f} kW likely unnecessary — "
            + verdict_parts[0][:80]
        )
        lines.append("  >> LIKELY UNNECESSARY GRID IMPORT <<")
        for vp in verdict_parts:
            lines.append(f"     • {vp}")
        lines.append(
            "  Suggest: disable or narrow MIX AC grid-charge window; let PV + battery "
            f"cover ~{heater_kw:.0f} kW midday immersion."
        )
        if headroom_kwh < 0.5:
            lines.append("  Battery nearly full — any grid charge mostly heats the tariff, not the pack.")
    else:
        if net_instant_kw > 0.5:
            summary = (
                f"Import ~{g_imp:.1f} kW plausibly needed now "
                f"(load+charge {load + charge_kw:.1f} kW > PV {pv:.1f} kW)."
            )
            lines.append(
                f"  >> Import may be justified: shortfall ~{net_instant_kw:.1f} kW at the meter."
            )
        else:
            summary = f"Grid import {g_imp:.1f} kW — review inverter MIX schedule / export limits."
            lines.append("  >> Mixed signals — check Growatt grid-charge timer and export cap.")

    return {
        'summary': summary,
        'lines': lines,
        'unnecessary': unnecessary,
        'heater_kw': heater_kw,
        'solar_remain_kwh': solar_remain,
        'net_instant_kw': net_instant_kw,
    }


class SmartAdvisorTab(QWidget):
    """Combines solar forecast, battery SOC, usage profile, and Agile prices
    to recommend overnight charging vs solar-only vs hybrid strategies."""

    STRATEGY_SMART     = 'smart'
    STRATEGY_OVERNIGHT = 'overnight'
    STRATEGY_SOLAR     = 'solar'
    STRATEGY_HYBRID    = 'hybrid'

    COLORS = {
        STRATEGY_SMART:     '#fab387',
        STRATEGY_OVERNIGHT: _UI_BLUE,
        STRATEGY_SOLAR:     '#a6e3a1',
        STRATEGY_HYBRID:    '#cba6f7',
    }
    LABELS = {
        STRATEGY_SMART:     'Smart (Forecast-Gated)',
        STRATEGY_OVERNIGHT: 'Charge Overnight',
        STRATEGY_SOLAR:     'Wait for Solar',
        STRATEGY_HYBRID:    'Hybrid Charge',
    }

    def __init__(self, growatt_tab, octopus_tab, forecasts_tab, status_callback, app_params):
        super().__init__()
        self.growatt_tab = growatt_tab
        self.octopus_tab = octopus_tab
        self.forecasts_tab = forecasts_tab
        self.set_status = status_callback
        self.app_params = app_params
        self._inv = Invoker(self)
        self.running = False
        # Set by EnergyDashboard.build_ui — fired when the advisor finishes
        # so the global tab freshness colouring updates.
        self.on_data_updated = None
        self.build_ui()

    # ── UI ─────────────────────────────────────────────────────────────

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Vertical)

        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        ctrl_box = QGroupBox("Smart Advisor Controls")
        ctrl_lay = QHBoxLayout(ctrl_box)
        ctrl_lay.setContentsMargins(8, 4, 8, 4)
        self.run_btn = QPushButton("Run Advisor")
        self.run_btn.setToolTip("Fetch fresh solar & Agile data, read SOC, build usage profile, simulate strategies")
        self.run_btn.clicked.connect(self.run_advisor)
        ctrl_lay.addWidget(self.run_btn)
        ctrl_lay.addSpacing(12)
        ctrl_lay.addWidget(QLabel("Cheap-price threshold (p/kWh):"))
        self.sp_cheap = QDoubleSpinBox()
        self.sp_cheap.setRange(0, 50)
        self.sp_cheap.setDecimals(1)
        self.sp_cheap.setValue(15.0)
        self.sp_cheap.setToolTip("Import prices below this are considered cheap enough to grid-charge")
        ctrl_lay.addWidget(self.sp_cheap)
        ctrl_lay.addSpacing(12)
        ctrl_lay.addWidget(QLabel("Overnight target SOC %:"))
        self.sp_target_soc = QSpinBox()
        self.sp_target_soc.setRange(20, 100)
        self.sp_target_soc.setValue(90)
        self.sp_target_soc.setToolTip("Target battery SOC for the overnight-charge strategy")
        ctrl_lay.addWidget(self.sp_target_soc)
        # Recommendation banner now lives on the same row as the controls so
        # the standalone full-width banner frame is gone — gives ~80 px back
        # to the charts. Title still stands out (16 pt bold) but is no longer
        # huge; the explanatory subtitle drops to a thin line below this row.
        ctrl_lay.addSpacing(16)
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #45475a;")
        ctrl_lay.addWidget(sep)
        ctrl_lay.addSpacing(12)
        self.advice_title = QLabel("Run the advisor to get a recommendation")
        self.advice_title.setFont(QFont('Helvetica', 16, QFont.Bold))
        self.advice_title.setStyleSheet("color: #6c7086;")
        self.advice_title.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.advice_title.setWordWrap(True)
        ctrl_lay.addWidget(self.advice_title, 1)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        ctrl_lay.addWidget(self.status_label)
        top_layout.addWidget(ctrl_box)

        # Subtitle row: thin one-liner directly under the controls. Replaces
        # the old banner subtitle and inherits the same content via
        # `advice_sub`, so existing code paths keep working unchanged.
        self.advice_sub = QLabel("")
        self.advice_sub.setStyleSheet(
            "color: #cdd6f4; font-size: 12px; padding: 2px 12px 4px 12px;"
        )
        self.advice_sub.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.advice_sub.setWordWrap(True)
        top_layout.addWidget(self.advice_sub)

        # Metric cards row
        cards_layout = QHBoxLayout()
        self.metric_cards = {}
        for key, label, unit, color in [
            ('soc', 'Current SOC', '%', _UI_BLUE),
            ('solar', 'Expected Solar', 'kWh', '#FF9800'),
            ('usage', 'Expected Usage', 'kWh', '#f38ba8'),
            ('smart_charge', 'Smart Grid Need', 'kWh', '#fab387'),
            ('best_price', 'Best Agile Price', 'p/kWh', '#4CAF50'),
            ('cost_smart', 'Cost: Smart', 'p/day', '#fab387'),
            ('cost_overnight', 'Cost: Overnight', 'p/day', _UI_BLUE),
            ('cost_solar', 'Cost: Solar Only', 'p/day', '#a6e3a1'),
            ('cost_hybrid', 'Cost: Hybrid', 'p/day', '#cba6f7'),
        ]:
            card, val_label = make_small_card(label, unit, color)
            self.metric_cards[key] = val_label
            cards_layout.addWidget(card)
        top_layout.addLayout(cards_layout)

        # Charts. Wider initial figsize hints to Qt that the chart row should
        # consume landscape pixels (we update _SMART_ADVISOR_AXES_RECT in
        # _plot_charts to reach the right edge — see comment there).
        chart_widget = QWidget()
        chart_widget.setSizePolicy(QSizePolicy.Policy.Expanding,
                                   QSizePolicy.Policy.Expanding)
        chart_lay = QVBoxLayout(chart_widget)
        chart_lay.setContentsMargins(0, 0, 0, 0)
        chart_lay.setSpacing(0)
        self.fig = Figure(figsize=(16, 8), dpi=100)
        gs = self.fig.add_gridspec(2, 2, hspace=0.42, wspace=0.18)
        self.ax_soc   = self.fig.add_subplot(gs[0, 0])
        self.ax_price = self.fig.add_subplot(gs[0, 1])
        self.ax_cost  = self.fig.add_subplot(gs[1, 0])
        self.ax_slot  = self.fig.add_subplot(gs[1, 1])
        for ax in (self.ax_soc, self.ax_price, self.ax_cost, self.ax_slot):
            _style_ax_dark(ax, self.fig)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Expanding)
        # FigureCanvasQTAgg's minimumSize of 1×1 isn't enough to override
        # the figsize hint for some Qt styles — explicitly drop the minimum
        # so the canvas can be re-flowed by the parent layout without holding
        # onto a bigger size hint than the row deserves.
        self.canvas.setMinimumSize(1, 1)
        chart_lay.addWidget(self.canvas, 1)
        toolbar = DarkNavigationToolbar(self.canvas, self)
        chart_lay.addWidget(toolbar)
        top_layout.addWidget(chart_widget, 1)
        splitter.addWidget(top_widget)

        # Bottom: detail text + inverter settings (side-by-side)
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_split = QSplitter(Qt.Horizontal)

        detail_box = QGroupBox("Advisor Detail")
        detail_lay = QVBoxLayout(detail_box)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setFont(QFont('Courier', 9))
        detail_lay.addWidget(self.detail_text)
        bottom_split.addWidget(detail_box)

        inv_box = QGroupBox("Inverter Control (read + MIX grid-charge schedule)")
        inv_lay = QVBoxLayout(inv_box)
        inv_btn_row = QHBoxLayout()
        self.read_inv_btn = QPushButton("Read Inverter Settings")
        self.read_inv_btn.setToolTip(
            "Fetch current MIX inverter battery/schedule settings from Growatt cloud (read-only)"
        )
        self.read_inv_btn.clicked.connect(self._read_inverter_settings)
        inv_btn_row.addWidget(self.read_inv_btn)
        self.inv_status_label = QLabel("")
        self.inv_status_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        inv_btn_row.addWidget(self.inv_status_label)
        inv_btn_row.addStretch()
        inv_lay.addLayout(inv_btn_row)

        ac_box = QGroupBox("Phase 2 — Write AC grid-charge window (MIX)")
        ac_lay = QGridLayout(ac_box)
        ac_lay.addWidget(QLabel("Charge power %:"), 0, 0)
        self.ac_chg_power_spin = QSpinBox()
        self.ac_chg_power_spin.setRange(0, 100)
        self.ac_chg_power_spin.setValue(100)
        self.ac_chg_power_spin.setToolTip("Grid charging power limit as % of inverter capability")
        ac_lay.addWidget(self.ac_chg_power_spin, 0, 1)
        ac_lay.addWidget(QLabel("Stop charge at SOC %:"), 0, 2)
        self.ac_chg_stop_soc_spin = QSpinBox()
        self.ac_chg_stop_soc_spin.setRange(0, 100)
        self.ac_chg_stop_soc_spin.setValue(90)
        ac_lay.addWidget(self.ac_chg_stop_soc_spin, 0, 3)
        self.ac_mains_charge_check = QCheckBox("Enable scheduled grid (AC) charging")
        self.ac_mains_charge_check.setChecked(True)
        ac_lay.addWidget(self.ac_mains_charge_check, 1, 0, 1, 4)

        self._ac_period_start = []
        self._ac_period_end = []
        self._ac_period_en = []
        defaults = [
            (QTime(1, 0), QTime(5, 30), True),
            (QTime(0, 0), QTime(0, 0), False),
            (QTime(0, 0), QTime(0, 0), False),
        ]
        for row, (st, et, on) in enumerate(defaults, start=2):
            ac_lay.addWidget(QLabel(f"Period {row - 1} start"), row, 0)
            te_s = QTimeEdit()
            te_s.setDisplayFormat("HH:mm")
            te_s.setTime(st)
            self._ac_period_start.append(te_s)
            ac_lay.addWidget(te_s, row, 1)
            ac_lay.addWidget(QLabel("end"), row, 2)
            te_e = QTimeEdit()
            te_e.setDisplayFormat("HH:mm")
            te_e.setTime(et)
            self._ac_period_end.append(te_e)
            ac_lay.addWidget(te_e, row, 3)
            cb = QCheckBox("enabled")
            cb.setChecked(on)
            self._ac_period_en.append(cb)
            ac_lay.addWidget(cb, row, 4)

        self.write_ac_chg_btn = QPushButton("Write AC charge schedule to inverter…")
        self.write_ac_chg_btn.setToolTip(
            "Sends mix_ac_charge_time_period via Growatt cloud (same param layout as growattServer SPH helpers). "
            "Verify with Read after writing."
        )
        self.write_ac_chg_btn.clicked.connect(self._write_mix_ac_charge_schedule)
        ac_lay.addWidget(self.write_ac_chg_btn, 5, 0, 1, 5)
        hint = QLabel(
            "Uses overnight-style slots (e.g. 01:00–05:30) for Agile cheap power. "
            "Wrong parameters can affect battery behaviour — confirm on your hardware / warranty."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6c7086; font-size: 10px;")
        ac_lay.addWidget(hint, 6, 0, 1, 5)
        inv_lay.addWidget(ac_box)

        self.inv_settings_text = QTextEdit()
        self.inv_settings_text.setReadOnly(True)
        self.inv_settings_text.setFont(QFont('Courier', 9))
        self.inv_settings_text.setPlaceholderText(
            "Connect to Growatt first, then press Read Inverter Settings.\n"
            "This will show the raw JSON that your MIX inverter reports —\n"
            "we need this to map settings before any write commands."
        )
        inv_lay.addWidget(self.inv_settings_text)
        bottom_split.addWidget(inv_box)
        bottom_split.setStretchFactor(0, 3)
        bottom_split.setStretchFactor(1, 2)

        bottom_layout.addWidget(bottom_split)
        splitter.addWidget(bottom_widget)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)

    # ── Usage profile builder ──────────────────────────────────────────

    def _build_usage_profile(self, exclude_heater_kw=None, exclude_tolerance=0.1):
        """Return a dict mapping hour (0-23) -> average half-hourly kWh consumption.

        The Octopus import data understates real consumption during hours
        when the battery or solar is covering load.  We fix this by using
        the configured base load as a floor for every hour, then overlaying
        the Octopus import data (which is accurate only when the battery is
        depleted), and finally adding any user-defined scheduled loads.

        ``exclude_heater_kw`` (default ``None``): when set, any
        :attr:`scheduled_loads` entry whose ``kw`` is within
        ``exclude_tolerance`` (default 0.1 kW) of that value is treated as
        a flexible immersion managed by the Optimiser (see
        :func:`pick_heater_windows`). Such entries are
        (1) **omitted** from the additive scheduled-load layer, and
        (2) **subtracted** from the Octopus historical hourly overlay
        (clamped to the base-load floor). This prevents triple-counting
        the immersion: in the recurring-load schedule, baked into Octopus
        history, AND added again by the Optimiser's ``heater_kwh`` term in
        :func:`dp_battery_dispatch`.
        Pass ``None`` (default) for the SmartAdvisor / charts path, which
        wants the full picture of real recurring consumption. Pass the
        Optimiser's heater-kW spinbox value from the Optimiser's planner
        thread.
        """
        p = self.app_params
        base_hh = p.base_load_kw * 0.5  # kWh per 30-min slot

        profile = {h: base_hh for h in range(24)}

        # Pre-compute the per-hour kWh contribution of any
        # "flexible heater" scheduled-load entry that the Optimiser will
        # re-schedule on its own. Used both to skip the additive layer
        # below AND to decontaminate the Octopus historical floor.
        heater_decontam = {h: 0.0 for h in range(24)}
        managed_heater_count = 0
        if exclude_heater_kw is not None:
            for sched in p.scheduled_loads:
                if abs(float(sched['kw']) - float(exclude_heater_kw)) > exclude_tolerance:
                    continue
                managed_heater_count += 1
                start_min = sched['hour'] * 60
                kw = float(sched['kw'])
                dur_min = int(sched['duration_min'])
                for h in range(24):
                    h_start = h * 60
                    h_end = h_start + 60
                    overlap = max(0, min(start_min + dur_min, h_end) - max(start_min, h_start))
                    if start_min + dur_min > 24 * 60:
                        wrap_end = (start_min + dur_min) - 24 * 60
                        overlap += max(0, min(wrap_end, h_end) - max(0, h_start))
                    if overlap > 0:
                        heater_decontam[h] += kw * (overlap / 60.0) * 0.5

        hh = getattr(self.octopus_tab, 'hh_data', None)
        if hh is not None and not hh.empty:
            imp = hh['Import (kWh)'] if 'Import (kWh)' in hh.columns else pd.Series(0, index=hh.index)
            # Octopus tab uses DatetimeIndex in normal paths, but the index can be a plain Index
            # (object dtype); only DatetimeIndex exposes .hour — normalize first.
            dt_idx = pd.DatetimeIndex(pd.to_datetime(imp.index, utc=True))
            hourly_avg = imp.groupby(dt_idx.hour).mean()
            for h in range(24):
                # Subtract the heater's expected kWh-per-slot contribution
                # from the Octopus average for that hour. We never drop
                # below the configured base-load floor (already in
                # `profile[h]`), so the worst case is "no heater visible
                # in history" rather than negative load.
                octopus_val = float(hourly_avg.get(h, 0)) - heater_decontam[h]
                profile[h] = max(profile[h], octopus_val)

        # Overlay scheduled loads (e.g. water heater at 04:00, 3kW, 60min).
        # Profile values are kWh-per-30-min-slot; both slots in an hour
        # get the same value, so we add  kw × (active_minutes / 60) × 0.5.
        for sched in p.scheduled_loads:
            if exclude_heater_kw is not None and \
                    abs(float(sched['kw']) - float(exclude_heater_kw)) <= exclude_tolerance:
                continue  # managed by the Optimiser; do not add here
            start_min = sched['hour'] * 60
            kw = sched['kw']
            dur_min = sched['duration_min']
            for h in range(24):
                h_start = h * 60
                h_end = h_start + 60
                overlap = max(0, min(start_min + dur_min, h_end) - max(start_min, h_start))
                if start_min + dur_min > 24 * 60:
                    wrap_end = (start_min + dur_min) - 24 * 60
                    overlap += max(0, min(wrap_end, h_end) - max(0, h_start))
                if overlap > 0:
                    profile[h] += kw * (overlap / 60.0) * 0.5

        if exclude_heater_kw is not None and managed_heater_count > 0:
            try:
                _log.info(
                    "Optimiser",
                    f"Usage profile: excluded {managed_heater_count} scheduled-load "
                    f"entry/entries matching heater kW={exclude_heater_kw:.2f} ±"
                    f"{exclude_tolerance:.2f}; subtracted up to "
                    f"{max(heater_decontam.values()):.3f} kWh/slot from the Octopus "
                    f"hourly floor to avoid double counting with pick_heater_windows."
                )
            except Exception:
                pass

        return profile

    def build_live_import_audit(self):
        """Live Growatt snapshot vs usage profile, solar forecast, Agile spot."""
        live = self.growatt_tab.get_live_data_summary()
        if not live:
            return None
        d = self.growatt_tab.mix_status_data or {}
        grid_import = float(d.get('pactouser', 0) or 0)
        try:
            soc = float(live.get('soc') or 50)
        except (TypeError, ValueError):
            soc = 50.0
        pv = float(live.get('pv_power') or 0)
        load = float(live.get('load_power') or 0)
        bat = float(live.get('bat_power') or 0)

        usage_profile = self._build_usage_profile()
        solar_df = getattr(self.forecasts_tab, 'solar_df', None)
        agile_p = None
        agile_df = getattr(self.forecasts_tab, 'agile_df', None)
        if agile_df is not None and not agile_df.empty and 'price_pence' in agile_df.columns:
            now = pd.Timestamp.now(tz='Europe/London')
            s = agile_df.set_index('valid_from')['price_pence'].astype(float)
            if s.index.tz is None:
                s.index = s.index.tz_localize('UTC').tz_convert('Europe/London')
            else:
                s.index = s.index.tz_convert('Europe/London')
            v = s.reindex([now], method='pad')
            if len(v) and np.isfinite(v.iloc[0]):
                agile_p = float(v.iloc[0])

        p = self.app_params
        return assess_live_grid_import_need(
            now_london=pd.Timestamp.now(tz='Europe/London'),
            soc_pct=soc,
            pv_kw=pv,
            load_kw=load,
            bat_power_kw=bat,
            grid_import_kw=grid_import,
            usage_profile_by_hour=usage_profile,
            solar_df=solar_df,
            agile_price_p=agile_p,
            cheap_threshold_p=float(self.sp_cheap.value()),
            capacity_kwh=float(p.battery_capacity_kwh),
            max_charge_kw=float(p.analytics_max_charge_kw),
            scheduled_loads=list(p.scheduled_loads or []),
        )

    # ── Simulation engine ──────────────────────────────────────────────

    def _plan_smart_grid_charge(self, slots, soc_start, capacity, efficiency,
                                max_charge_kw, low_soc_pct, cheap_threshold):
        """Pre-plan exact grid-charge slots for the smart strategy.

        Walk the timeline forward to find the minimum SOC the battery needs
        at each point to survive until the next period of net-positive solar.
        Then schedule grid charging only to cover the shortfall, placed into
        the cheapest-priced slots available before solar ramps up.
        """
        eff = (efficiency / 100.0) ** 0.5
        min_soc = capacity * (low_soc_pct / 100.0)
        max_charge_hh = max_charge_kw * 0.5
        n = len(slots)

        # 1) Compute the net energy balance (solar - load) per slot
        net_balance = [s['solar_kwh'] - s['load_kwh'] for s in slots]

        # 2) Walk backwards: at each slot, compute the worst cumulative
        #    deficit from that slot to the end.  This is the minimum stored
        #    energy the battery must hold at that moment to avoid importing.
        #    We track (deficit_kwh, accounting for battery efficiency on
        #    discharge and charge).
        need_at = [0.0] * n
        cumulative = 0.0
        worst_ahead = 0.0
        for i in range(n - 1, -1, -1):
            nb = net_balance[i]
            if nb < 0:
                cumulative += abs(nb) / eff   # battery kWh consumed
            else:
                cumulative -= nb * eff         # battery kWh gained from solar
            worst_ahead = max(worst_ahead, cumulative)
            need_at[i] = worst_ahead
            cumulative = max(cumulative, 0)

        # 3) The shortfall is: what the battery needs minus what it has
        total_shortfall = max(0, need_at[0] + min_soc - soc_start)

        # 4) Find candidate grid-charge slots (before solar surplus arrives)
        #    and rank by price.  We only look at slots where the battery
        #    would otherwise be draining or flat (no solar surplus).
        candidates = []
        for i, s in enumerate(slots):
            if s['price_pence'] <= cheap_threshold and net_balance[i] <= 0:
                candidates.append((i, s['price_pence']))
        candidates.sort(key=lambda x: x[1])

        # 5) Allocate just enough charge across cheapest slots
        charge_plan = {}
        remaining = total_shortfall
        for idx, price in candidates:
            if remaining <= 0:
                break
            amount = min(max_charge_hh, remaining / eff)
            charge_plan[idx] = amount
            remaining -= amount * eff

        return charge_plan

    def _simulate_strategy(self, strategy, slots, soc_start, capacity, efficiency,
                           max_charge_kw, low_soc_pct, cheap_threshold,
                           target_overnight_soc, smart_charge_plan=None):
        """Run a 30-min slot-by-slot simulation for one strategy.
        Returns dict with soc_trace, cost_pence, export_revenue_pence, slot_log."""
        eff = (efficiency / 100.0) ** 0.5
        max_charge_hh = max_charge_kw * 0.5
        soc = soc_start
        total_import_cost = 0.0
        total_export_rev = 0.0
        soc_trace = []
        slot_log = []

        for slot_idx, s in enumerate(slots):
            solar_kwh = s['solar_kwh']
            load_kwh  = s['load_kwh']
            price     = s['price_pence']
            export_p  = self.app_params.export_flat_pence
            ts        = s['time']

            net = solar_kwh - load_kwh
            grid_import = 0.0
            grid_export = 0.0
            bat_delta = 0.0
            action = ''

            is_overnight = ts.hour < 6 or ts.hour >= 23

            if strategy == self.STRATEGY_SMART and smart_charge_plan:
                planned = smart_charge_plan.get(slot_idx, 0)
                if planned > 0 and soc < capacity:
                    can_charge = min(planned, max_charge_hh, (capacity - soc) / eff)
                    grid_import = can_charge
                    bat_delta = can_charge * eff
                    total_import_cost += grid_import * price
                    action = f'smart-charge {can_charge:.2f}kWh @{price:.1f}p'
            elif strategy == self.STRATEGY_OVERNIGHT and is_overnight:
                target_kwh = capacity * (target_overnight_soc / 100.0)
                if soc < target_kwh and price <= cheap_threshold:
                    can_charge = min(max_charge_hh, (target_kwh - soc) / eff)
                    grid_import = can_charge
                    bat_delta = can_charge * eff
                    total_import_cost += grid_import * price
                    action = f'grid-charge {can_charge:.2f}'
            elif strategy == self.STRATEGY_HYBRID and is_overnight:
                hybrid_target_kwh = capacity * 0.5
                if soc < hybrid_target_kwh and price <= cheap_threshold:
                    can_charge = min(max_charge_hh, (hybrid_target_kwh - soc) / eff)
                    grid_import = can_charge
                    bat_delta = can_charge * eff
                    total_import_cost += grid_import * price
                    action = f'grid-charge(hybrid) {can_charge:.2f}'

            if net > 0:
                room = (capacity - soc) / eff if soc < capacity else 0
                charge_from_solar = min(net, max_charge_hh - max(bat_delta, 0), room)
                if charge_from_solar > 0:
                    bat_delta += charge_from_solar * eff
                    net -= charge_from_solar
                    action += f' +solar-charge {charge_from_solar:.2f}'
                if net > 0:
                    grid_export += net
                    total_export_rev += net * export_p
                    action += f' +export {net:.2f}'
            elif net < 0:
                deficit = abs(net)
                dischargeable = max(0, soc - capacity * (low_soc_pct / 100.0))
                discharge = min(deficit, max_charge_hh, dischargeable)
                if discharge > 0:
                    bat_delta -= discharge
                    deficit -= discharge * eff
                    action += f' discharge {discharge:.2f}'
                if deficit > 0:
                    grid_import += deficit
                    total_import_cost += deficit * price
                    action += f' import {deficit:.2f}'

            soc = max(0, min(capacity, soc + bat_delta))
            soc_trace.append({'time': ts, 'soc_pct': soc / capacity * 100})
            slot_log.append({
                'time': ts, 'solar': solar_kwh, 'load': load_kwh,
                'price': price, 'grid_import': grid_import,
                'grid_export': grid_export, 'soc_pct': soc / capacity * 100,
                'action': action.strip(),
            })

        return {
            'soc_trace': soc_trace,
            'total_import_cost_pence': total_import_cost,
            'total_export_revenue_pence': total_export_rev,
            'net_cost_pence': total_import_cost - total_export_rev,
            'slot_log': slot_log,
            'final_soc_pct': soc / capacity * 100,
        }

    def _build_slots(self, solar_df, agile_df, usage_profile):
        """Build list of 30-min slots for next 24h with solar, load, price."""
        import pytz
        london = pytz.timezone('Europe/London')
        now = datetime.now(london).replace(second=0, microsecond=0)
        if now.minute >= 30:
            slot_start = now.replace(minute=30)
        else:
            slot_start = now.replace(minute=0)

        slots = []
        for i in range(48):
            t = slot_start + timedelta(minutes=30 * i)
            solar_kwh = 0.0
            if solar_df is not None and not solar_df.empty:
                ts_col = solar_df['timestamp']
                if ts_col.dt.tz is None:
                    ts_col = ts_col.dt.tz_localize(london)
                else:
                    ts_col = ts_col.dt.tz_convert(london)
                mask = (ts_col >= t) & (ts_col < t + timedelta(minutes=30))
                matched = solar_df.loc[mask]
                if not matched.empty:
                    solar_kwh = matched['kW'].mean() * 0.5
                else:
                    nearest_idx = (ts_col - t).abs().idxmin()
                    if abs((ts_col.iloc[nearest_idx] - t).total_seconds()) < 3600:
                        solar_kwh = max(0, solar_df.loc[nearest_idx, 'kW']) * 0.5

            load_kwh = usage_profile.get(t.hour, 0.4)

            price = self.app_params.import_flat_pence
            if agile_df is not None and not agile_df.empty:
                vf = agile_df['valid_from']
                pmask = (vf <= t) & (agile_df['valid_to'] > t)
                pmatched = agile_df.loc[pmask]
                if not pmatched.empty:
                    price = float(pmatched.iloc[0]['price_pence'])

            slots.append({'time': t, 'solar_kwh': solar_kwh, 'load_kwh': load_kwh, 'price_pence': price})
        return slots

    # ── Main run ───────────────────────────────────────────────────────

    def run_advisor(self):
        if self.running:
            return
        self.running = True
        self.run_btn.setEnabled(False)
        self.set_status("Running Smart Advisor...")
        self.status_label.setText("Fetching data...")
        threading.Thread(target=self._advisor_thread, daemon=True).start()

    def _advisor_failed(self, message):
        """Reset UI after a worker-thread failure (always re-enable Run)."""
        self.running = False
        self.run_btn.setEnabled(True)
        short = (message or "Unknown error").replace("\n", " ")
        if len(short) > 160:
            short = short[:157] + "..."
        self.status_label.setText(f"Failed: {short}")
        self.set_status(f"Smart Advisor failed: {short}")

    def _advisor_thread(self):
        try:
            self._advisor_thread_impl()
        except Exception as e:
            import traceback
            _log.warn("Advisor", f"Advisor thread failed: {e}\n{traceback.format_exc()}")
            err = str(e) or type(e).__name__
            self._inv.invoke(lambda msg=err: self._advisor_failed(msg))

    def _advisor_thread_impl(self):
        p = self.app_params

        # Read SOC on the GUI thread so Growatt API calls use the same threading rules as the rest of the app.
        soc_box = {'v': None}

        def _read_soc_main():
            soc_box['v'] = self.growatt_tab.get_current_soc()

        self._inv.invoke(_read_soc_main)
        soc_now = soc_box['v']
        if soc_now is None:
            soc_now = 50.0
            soc_source = "assumed 50%"
        else:
            soc_source = "live"

        self._inv.invoke(lambda: self.status_label.setText("Fetching solar forecast..."))
        solar_df = pd.DataFrame()
        try:
            se = self.forecasts_tab.solar_edits
            solar_df, _ = fetch_solar_forecast(
                se['lat'].text(), se['lon'].text(), se['tilt'].text(),
                se['azimuth'].text(), se['kwp'].text()
            )
        except Exception as e:
            _log.warn("Advisor", f"Solar forecast error: {e}")

        self._inv.invoke(lambda: self.status_label.setText("Fetching Agile prices..."))
        agile_df = pd.DataFrame()
        try:
            agile_df = fetch_agile_prices(p.agile_product, p.agile_tariff)
        except Exception as e:
            _log.warn("Advisor", f"Agile price error: {e}")

        self._inv.invoke(lambda: self.status_label.setText("Simulating strategies..."))
        usage_profile = self._build_usage_profile()
        slots = self._build_slots(solar_df, agile_df, usage_profile)

        capacity  = p.battery_capacity_kwh
        eff       = p.analytics_efficiency_pct
        max_kw    = p.analytics_max_charge_kw
        low_soc   = p.battery_low_soc_threshold_pct
        cheap_thr = self.sp_cheap.value()
        target_soc = self.sp_target_soc.value()

        soc_kwh_now = capacity * (soc_now / 100.0)

        # Smart strategy: look ahead at solar forecast, compute minimum grid
        # charge needed, place it into cheapest available slots.
        smart_plan = self._plan_smart_grid_charge(
            slots, soc_kwh_now, capacity, eff, max_kw, low_soc, cheap_thr
        )
        smart_grid_kwh = sum(smart_plan.values())

        strategies = {}
        strategies[self.STRATEGY_SMART] = self._simulate_strategy(
            self.STRATEGY_SMART, slots, soc_kwh_now, capacity, eff, max_kw,
            low_soc, cheap_thr, target_soc, smart_charge_plan=smart_plan
        )
        for strat in (self.STRATEGY_OVERNIGHT, self.STRATEGY_SOLAR, self.STRATEGY_HYBRID):
            strategies[strat] = self._simulate_strategy(
                strat, slots, soc_kwh_now, capacity, eff, max_kw,
                low_soc, cheap_thr, target_soc
            )

        total_solar_kwh = sum(s['solar_kwh'] for s in slots)
        total_usage_kwh = sum(s['load_kwh'] for s in slots)
        best_agile = min((s['price_pence'] for s in slots), default=p.import_flat_pence)

        best_strat = min(strategies, key=lambda k: strategies[k]['net_cost_pence'])

        # Verdict: the smart strategy decides whether any grid charge is needed
        solar_sufficient = smart_grid_kwh < 0.05

        daylight_solar = sum(s['solar_kwh'] for s in slots if 6 <= s['time'].hour < 20)
        daylight_usage = sum(s['load_kwh'] for s in slots if 6 <= s['time'].hour < 20)
        night_usage = sum(s['load_kwh'] for s in slots if s['time'].hour >= 20 or s['time'].hour < 6)
        solar_surplus = max(0, daylight_solar - daylight_usage)

        soc_usable_kwh = max(0, soc_kwh_now - capacity * (low_soc / 100.0))

        # How many cheap slots did the smart strategy actually use?
        smart_slot_count = len(smart_plan)
        smart_avg_price = (
            sum(slots[i]['price_pence'] * kwh for i, kwh in smart_plan.items()) /
            smart_grid_kwh if smart_grid_kwh > 0 else 0
        )

        verdict = {
            'solar_sufficient': solar_sufficient,
            'smart_grid_kwh': smart_grid_kwh,
            'smart_slot_count': smart_slot_count,
            'smart_avg_price': smart_avg_price,
            'daylight_solar_kwh': daylight_solar,
            'daylight_usage_kwh': daylight_usage,
            'solar_surplus_kwh': solar_surplus,
            'night_usage_kwh': night_usage,
            'soc_usable_kwh': soc_usable_kwh,
            'capacity_kwh': capacity,
            'low_soc_pct': low_soc,
        }

        results = {
            'strategies': strategies,
            'best': best_strat,
            'soc_now': soc_now,
            'soc_source': soc_source,
            'total_solar_kwh': total_solar_kwh,
            'total_usage_kwh': total_usage_kwh,
            'best_agile': best_agile,
            'slots': slots,
            'solar_df': solar_df,
            'agile_df': agile_df,
            'cheap_threshold': cheap_thr,
            'verdict': verdict,
            'smart_plan': smart_plan,
        }
        self._inv.invoke(lambda: self._display_results(results))

    # ── Display ────────────────────────────────────────────────────────

    def _display_results(self, r):
        self.running = False
        self.run_btn.setEnabled(True)
        self.status_label.setText(f"Done | SOC {r['soc_source']}")

        best = r['best']
        strats = r['strategies']
        v = r['verdict']

        smart_cost = strats[self.STRATEGY_SMART]['net_cost_pence']
        overnight_cost = strats[self.STRATEGY_OVERNIGHT]['net_cost_pence']

        if v['solar_sufficient']:
            verdict_text = "SKIP TONIGHT'S CHARGE — SOLAR IS SUFFICIENT"
            verdict_color = '#a6e3a1'
        else:
            verdict_text = f"SMART CHARGE {v['smart_grid_kwh']:.1f} kWh — MINIMUM GRID NEEDED"
            verdict_color = '#fab387'

        self.advice_title.setText(verdict_text)
        self.advice_title.setStyleSheet(f"color: {verdict_color};")

        savings_vs_overnight = overnight_cost - smart_cost
        sub_parts = []
        if v['solar_sufficient']:
            sub_parts.append(
                f"Tomorrow's solar ({v['daylight_solar_kwh']:.1f} kWh) fully covers "
                f"usage ({v['daylight_usage_kwh']:.1f} kWh daytime + "
                f"{v['night_usage_kwh']:.1f} kWh overnight). No grid charge needed."
            )
        else:
            sub_parts.append(
                f"Solar forecast: {v['daylight_solar_kwh']:.1f} kWh  |  "
                f"Surplus after daytime load: {v['solar_surplus_kwh']:.1f} kWh  |  "
                f"Overnight usage: {v['night_usage_kwh']:.1f} kWh."
            )
            sub_parts.append(
                f"Smart plan: charge {v['smart_grid_kwh']:.1f} kWh across "
                f"{v['smart_slot_count']} cheap slot(s) "
                f"(avg {v['smart_avg_price']:.1f}p/kWh) — "
                f"just enough to bridge the gap until solar kicks in."
            )
        if savings_vs_overnight > 0:
            sub_parts.append(
                f"Saves {savings_vs_overnight:.0f}p vs blind overnight charge to {self.sp_target_soc.value()}%."
            )
        self.advice_sub.setText("  ".join(sub_parts))

        self.metric_cards['soc'].setText(f"{r['soc_now']:.0f}")
        self.metric_cards['solar'].setText(f"{r['total_solar_kwh']:.1f}")
        self.metric_cards['usage'].setText(f"{r['total_usage_kwh']:.1f}")
        sgk = v['smart_grid_kwh']
        self.metric_cards['smart_charge'].setText(f"{sgk:.1f}")
        self.metric_cards['smart_charge'].setStyleSheet(
            f"color: {'#a6e3a1' if sgk < 0.05 else '#fab387'}; font-weight: bold;")
        self.metric_cards['best_price'].setText(f"{r['best_agile']:.1f}")
        for skey, ckey in [(self.STRATEGY_SMART, 'cost_smart'),
                           (self.STRATEGY_OVERNIGHT, 'cost_overnight'),
                           (self.STRATEGY_SOLAR, 'cost_solar'),
                           (self.STRATEGY_HYBRID, 'cost_hybrid')]:
            net = strats[skey]['net_cost_pence']
            self.metric_cards[ckey].setText(f"{net:.0f}")
            is_best = skey == best
            col = self.COLORS[skey]
            style = f"color: {col}; font-weight: bold;" if is_best else f"color: {col};"
            self.metric_cards[ckey].setStyleSheet(style)

        self._plot_charts(r)
        self._update_detail_text(r)
        self.set_status("Smart Advisor complete.")
        if self.on_data_updated:
            self.on_data_updated()
        dash = getattr(self, 'dash', None)
        if dash is not None:
            audit = self.build_live_import_audit()
            if audit:
                dash._apply_live_import_audit(audit)

    # ── Charts ─────────────────────────────────────────────────────────

    def _plot_charts(self, r):
        import pytz
        import matplotlib.dates as mdates
        london = pytz.timezone('Europe/London')

        for ax in (self.ax_soc, self.ax_price, self.ax_cost, self.ax_slot):
            ax.clear()
            _style_ax_dark(ax, self.fig)

        strats = r['strategies']
        all_strats = (self.STRATEGY_SMART, self.STRATEGY_OVERNIGHT, self.STRATEGY_SOLAR, self.STRATEGY_HYBRID)
        # ── Chart 1: Projected SOC over 24h ──
        for skey in all_strats:
            trace = strats[skey]['soc_trace']
            times = [t['time'] for t in trace]
            socs  = [t['soc_pct'] for t in trace]
            is_best = skey == r['best']
            self.ax_soc.plot(times, socs, color=self.COLORS[skey],
                             linewidth=2.5 if is_best else 1.2,
                             alpha=1.0 if is_best else 0.4,
                             label=self.LABELS[skey])
        self.ax_soc.axhline(self.app_params.battery_low_soc_threshold_pct,
                            color='#f38ba8', linestyle=':', linewidth=0.8, label='Low SOC')
        self.ax_soc.set_ylabel('SOC %')
        self.ax_soc.set_title('Projected Battery SOC (24h)')
        self.ax_soc.set_ylim(-2, 105)
        self.ax_soc.legend(fontsize=7, loc='lower left', framealpha=0.6,
                           facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT)
        self.ax_soc.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=london))
        self.ax_soc.xaxis.set_major_locator(mdates.HourLocator(interval=3))
        self.ax_soc.tick_params(axis='x', rotation=30)
        self.ax_soc.grid(axis='y', color=_DARK_GRID, linewidth=0.4)

        # ── Chart 2: Agile price bars + solar overlay ──
        slots = r['slots']
        times_slot = [s['time'] for s in slots]
        prices = [s['price_pence'] for s in slots]
        cheap = r['cheap_threshold']
        price_colors = ['#4CAF50' if p <= cheap else '#FF9800' if p < 30 else '#F44336' for p in prices]
        bar_w = 1.0 / 48
        self.ax_price.bar(times_slot, prices, width=bar_w, color=price_colors,
                          alpha=0.75, align='edge', label='Agile price')
        self.ax_price.axhline(cheap, color='#a6e3a1', linestyle='--', linewidth=0.8,
                              label=f'Cheap threshold ({cheap:.0f}p)')
        self.ax_price.set_ylabel('p/kWh')
        self.ax_price.set_title('Agile Price + Solar Forecast')
        self.ax_price.legend(fontsize=7, loc='upper left', framealpha=0.6,
                             facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT)

        ax2 = self.ax_price.twinx()
        solar_kw = [s['solar_kwh'] * 2 for s in slots]
        ax2.fill_between(times_slot, solar_kw, alpha=0.25, color='#FF9800', step='mid')
        ax2.step(times_slot, solar_kw, color='#FF9800', linewidth=1.2, where='mid', label='Solar kW')
        ax2.set_ylabel('Solar kW', color='#FF9800')
        ax2.tick_params(axis='y', labelcolor='#FF9800', labelsize=8)
        ax2.spines['right'].set_color('#FF9800')

        self.ax_price.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=london))
        self.ax_price.xaxis.set_major_locator(mdates.HourLocator(interval=3))
        self.ax_price.tick_params(axis='x', rotation=30)
        self.ax_price.grid(axis='y', color=_DARK_GRID, linewidth=0.4)
        self.ax_price.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
            xv, yv, tz, "p/kWh",
            "Agile import price (this axis) at the half-hour slot",
        )
        ax2.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
            xv, yv, tz, "kW",
            "solar power (right axis) — 2× slot energy / 1h for display scale",
        )

        # ── Chart 3: Cost breakdown ──
        chart_strats = (self.STRATEGY_SMART, self.STRATEGY_OVERNIGHT, self.STRATEGY_SOLAR, self.STRATEGY_HYBRID)
        labels = [self.LABELS[k] for k in chart_strats]
        import_costs = [strats[k]['total_import_cost_pence'] / 100 for k in chart_strats]
        export_revs  = [strats[k]['total_export_revenue_pence'] / 100 for k in chart_strats]
        net_costs    = [strats[k]['net_cost_pence'] / 100 for k in chart_strats]
        x = np.arange(len(labels))
        w = 0.25
        self.ax_cost.bar(x - w, import_costs, w, color='#f38ba8', alpha=0.8, label='Import cost')
        self.ax_cost.bar(x,     export_revs,  w, color='#a6e3a1', alpha=0.8, label='Export revenue')
        self.ax_cost.bar(x + w, net_costs,    w, color=_UI_BLUE, alpha=0.8, label='Net cost')
        self.ax_cost.set_xticks(x)
        self.ax_cost.set_xticklabels(labels, fontsize=8)
        self.ax_cost.set_ylabel('GBP (£)')
        self.ax_cost.set_title('Cost Breakdown by Strategy')
        self.ax_cost.legend(fontsize=7, loc='upper right', framealpha=0.6,
                            facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT)
        self.ax_cost.grid(axis='y', color=_DARK_GRID, linewidth=0.4)
        best_idx = list(chart_strats).index(r['best'])
        self.ax_cost.annotate('BEST', xy=(x[best_idx] + w, net_costs[best_idx]),
                              fontsize=9, fontweight='bold', color=self.COLORS[r['best']],
                              ha='center', va='bottom')

        # ── Chart 4: Slot actions for best strategy ──
        best_log = strats[r['best']]['slot_log']
        t_ax = [s['time'] for s in best_log]
        imports = [s['grid_import'] for s in best_log]
        exports = [-s['grid_export'] for s in best_log]
        self.ax_slot.bar(t_ax, imports, width=bar_w, color='#f38ba8', alpha=0.75,
                         align='edge', label='Grid import')
        self.ax_slot.bar(t_ax, exports, width=bar_w, color='#a6e3a1', alpha=0.75,
                         align='edge', label='Grid export')
        self.ax_slot.axhline(0, color=_DARK_GRID, linewidth=0.5)
        self.ax_slot.set_ylabel('kWh per slot')
        self.ax_slot.set_title(f'Grid Flows — {self.LABELS[r["best"]]} (best)')
        self.ax_slot.legend(fontsize=7, loc='upper right', framealpha=0.6,
                            facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT)
        self.ax_slot.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=london))
        self.ax_slot.xaxis.set_major_locator(mdates.HourLocator(interval=3))
        self.ax_slot.tick_params(axis='x', rotation=30)
        self.ax_slot.grid(axis='y', color=_DARK_GRID, linewidth=0.4)

        self.ax_soc.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
            xv, yv, tz, "% SOC",
            "modelled battery charge through the day (per strategy trace)",
        )
        self.ax_cost.format_coord = lambda xv, yv: (
            f"Horizontal (x): strategy column ~{xv:.2f}  |  "
            f"{_fmt_toolbar_y(yv, '£', 'import, export, or net bar for that strategy')}"
        )
        self.ax_slot.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
            xv, yv, tz, "kWh / ½h",
            "simulated grid import (positive) or export (negative) for the best plan",
        )

        _draw_6h_vertical_grid(self.ax_soc, london, force_intraday_secondary=True)
        _draw_6h_vertical_grid(self.ax_price, london, force_intraday_secondary=True)
        _draw_6h_vertical_grid(self.ax_slot, london, force_intraday_secondary=True)
        _draw_day_date_labels(self.ax_soc, london)
        _draw_day_date_labels(self.ax_price, london)
        _draw_day_date_labels(self.ax_slot, london)

        # Use explicit subplots_adjust instead of tight_layout — tight_layout
        # over-pads the right edge when one of the subplots has a twinx (the
        # Agile-Price chart twins on Solar kW). That mis-aligns the right
        # column in the gridspec and leaves a wide vertical empty strip on
        # the right of the figure (≈10–15 % of the available width). The
        # explicit values below claw that back: the plotting region runs
        # from 3.5 % to 96.5 % of the figure width so both columns reach
        # nearly to the edge of the canvas.
        self.fig.subplots_adjust(
            left=0.035, right=0.965,
            top=0.93, bottom=0.10,
            hspace=0.42, wspace=0.18,
        )
        self.canvas.draw()

    # ── Detail text ────────────────────────────────────────────────────

    def _update_detail_text(self, r):
        strats = r['strategies']
        best = r['best']
        v = r['verdict']
        lines = [
            f"{'='*70}",
            "  SMART CHARGING VERDICT",
            f"{'='*70}",
        ]
        if v['solar_sufficient']:
            lines.append("  >> NO GRID CHARGE NEEDED — SOLAR COVERS EVERYTHING <<")
            lines += [
                "",
                "  Tomorrow's solar forecast covers all usage.",
                f"  Daylight solar: {v['daylight_solar_kwh']:.1f} kWh  |  "
                f"Daytime load: {v['daylight_usage_kwh']:.1f} kWh",
                f"  Solar surplus: {v['solar_surplus_kwh']:.1f} kWh  |  "
                f"Overnight load: {v['night_usage_kwh']:.1f} kWh",
                f"  Current battery: {v['soc_usable_kwh']:.1f} kWh usable",
            ]
        else:
            lines += [
                f"  >> SMART CHARGE: {v['smart_grid_kwh']:.1f} kWh across "
                f"{v['smart_slot_count']} slot(s) <<",
                "",
                "  This is the MINIMUM grid energy needed to avoid running",
                "  the battery flat before solar production starts.",
                "",
                f"  Daylight solar forecast (06-20):   {v['daylight_solar_kwh']:.1f} kWh",
                f"  Daytime usage (06-20):             {v['daylight_usage_kwh']:.1f} kWh",
                f"  Solar surplus for battery:          {v['solar_surplus_kwh']:.1f} kWh",
                f"  Overnight usage (20-06):           {v['night_usage_kwh']:.1f} kWh",
                f"  Current battery usable:             {v['soc_usable_kwh']:.1f} kWh",
                "",
                "  Grid charge placed in cheapest slots:",
            ]
            for idx, kwh in sorted(r.get('smart_plan', {}).items()):
                s = r['slots'][idx]
                lines.append(
                    f"    {s['time'].strftime('%H:%M')}  "
                    f"{kwh:.2f} kWh  @  {s['price_pence']:.1f} p/kWh"
                )
            if v['smart_avg_price'] > 0:
                lines.append(
                    f"  Weighted avg price: {v['smart_avg_price']:.1f} p/kWh"
                )
        lines += [
            "",
            f"{'='*70}",
            "  STRATEGY COMPARISON",
            f"  SOC now: {r['soc_now']:.0f}% ({r['soc_source']})",
            f"  Expected solar (24h): {r['total_solar_kwh']:.1f} kWh",
            f"  Expected usage (24h): {r['total_usage_kwh']:.1f} kWh",
            f"  Best Agile price: {r['best_agile']:.1f} p/kWh",
            f"  Cheap threshold: {r['cheap_threshold']:.1f} p/kWh",
            f"{'='*70}",
            "",
        ]
        for skey in (self.STRATEGY_SMART, self.STRATEGY_OVERNIGHT, self.STRATEGY_SOLAR, self.STRATEGY_HYBRID):
            s = strats[skey]
            winner = " << RECOMMENDED" if skey == best else ""
            lines.append(f"--- {self.LABELS[skey]}{winner} ---")
            lines.append(f"  Import cost:     {s['total_import_cost_pence']:.1f} p  (£{s['total_import_cost_pence']/100:.2f})")
            lines.append(f"  Export revenue:  {s['total_export_revenue_pence']:.1f} p  (£{s['total_export_revenue_pence']/100:.2f})")
            lines.append(f"  Net cost:        {s['net_cost_pence']:.1f} p  (£{s['net_cost_pence']/100:.2f})")
            lines.append(f"  Final SOC:       {s['final_soc_pct']:.0f}%")
            lines.append("")

        lines.append(f"{'='*70}")
        lines.append(f"  SLOT-BY-SLOT LOG — {self.LABELS[best]} (best)")
        lines.append(f"{'='*70}")
        lines.append(f"{'Time':>8}  {'Solar':>6}  {'Load':>6}  {'Price':>6}  {'Import':>7}  {'Export':>7}  {'SOC%':>5}  Action")
        lines.append(f"{'-'*8}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*7}  {'-'*7}  {'-'*5}  {'-'*20}")
        live_audit = self.build_live_import_audit()
        if live_audit:
            lines += [
                "",
                f"{'='*70}",
                "  LIVE GRID IMPORT AUDIT (Growatt now)",
                f"{'='*70}",
            ]
            lines.extend(live_audit.get('lines', []))

        for sl in strats[best]['slot_log']:
            lines.append(
                f"{sl['time'].strftime('%H:%M'):>8}  {sl['solar']:6.3f}  {sl['load']:6.3f}  "
                f"{sl['price']:6.1f}  {sl['grid_import']:7.3f}  {sl['grid_export']:7.3f}  "
                f"{sl['soc_pct']:5.1f}  {sl['action']}"
            )
        self.detail_text.setPlainText('\n'.join(lines))

    # ── Inverter settings discovery ────────────────────────────────────

    def _read_inverter_settings(self):
        api, plant_id, sn = self.growatt_tab.get_api()
        if api is None:
            self.inv_status_label.setText(
                "Growatt cloud credentials required for inverter settings "
                "(GROTT MQTT is telemetry-only)"
            )
            self.inv_status_label.setStyleSheet("color: #f38ba8; font-size: 11px;")
            return
        self.read_inv_btn.setEnabled(False)
        self.inv_status_label.setText("Reading...")
        self.inv_status_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        threading.Thread(target=self._read_inv_thread, args=(api, sn), daemon=True).start()

    def _read_inv_thread(self, api, sn):
        try:
            raw = api.get_mix_inverter_settings(sn)
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self._inv.invoke(lambda: self._show_inv_settings(raw, sn, ts))
        except Exception as e:
            err = str(e)
            self._inv.invoke(lambda msg=err: self._show_inv_error(msg))

    def _show_inv_settings(self, raw, sn, ts):
        self.read_inv_btn.setEnabled(True)
        self.inv_status_label.setText(f"Read OK | {ts}")
        self.inv_status_label.setStyleSheet("color: #a6e3a1; font-size: 11px;")

        lines = [
            f"{'='*60}",
            f"  INVERTER SETTINGS — {sn}",
            f"  Retrieved: {ts}",
            f"{'='*60}",
            "",
        ]

        if isinstance(raw, dict):
            obj = raw.get('obj', raw)
            if isinstance(obj, dict):
                max_key_len = max((len(str(k)) for k in obj), default=10)
                for k, v in sorted(obj.items()):
                    lines.append(f"  {str(k):<{max_key_len}}  =  {v}")
            else:
                lines.append(str(obj))
            lines.append("")
            lines.append(f"{'='*60}")
            lines.append("  RAW JSON")
            lines.append(f"{'='*60}")
            lines.append(json.dumps(raw, indent=2, default=str))
        else:
            lines.append(f"  Unexpected response type: {type(raw).__name__}")
            lines.append(str(raw))

        self.inv_settings_text.setPlainText('\n'.join(lines))

    def _show_inv_error(self, msg):
        self.read_inv_btn.setEnabled(True)
        self.inv_status_label.setText(f"Error: {msg}")
        self.inv_status_label.setStyleSheet("color: #f38ba8; font-size: 11px;")
        self.inv_settings_text.setPlainText(f"Failed to read inverter settings:\n{msg}")

    def _write_mix_ac_charge_schedule(self):
        from energy_dashboard.tabs.shadow_trial import confirm_despite_shadow_trial
        if not confirm_despite_shadow_trial(self, "AC charge schedule"):
            return
        api, _plant_id, sn = self.growatt_tab.get_api()
        if api is None:
            QMessageBox.warning(
                self,
                "Growatt cloud required",
                "GROTT MQTT provides live telemetry, but inverter schedule writes "
                "still have to go through the Growatt cloud API.\n\n"
                "Add/test Growatt cloud credentials in Setup if you want to write "
                "the AC charge schedule.",
            )
            return
        r = QMessageBox.question(
            self,
            "Confirm inverter write",
            "This sends the AC grid-charge schedule to your MIX inverter through the Growatt cloud "
            "(type <mix_ac_charge_time_period>). Wrong times or firmware mismatch can cause unexpected "
            "charging behaviour.\n\nUse Read Inverter Settings after a write to confirm.\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        try:
            periods = []
            for i in range(3):
                periods.append({
                    'start_time': _qtime_to_time(self._ac_period_start[i].time()),
                    'end_time': _qtime_to_time(self._ac_period_end[i].time()),
                    'enabled': self._ac_period_en[i].isChecked(),
                })
            params = _mix_ac_charge_api_params(
                self.ac_chg_power_spin.value(),
                self.ac_chg_stop_soc_spin.value(),
                self.ac_mains_charge_check.isChecked(),
                periods,
            )
        except Exception as e:
            QMessageBox.warning(self, "Invalid input", str(e))
            return
        self.write_ac_chg_btn.setEnabled(False)
        self.inv_status_label.setText("Writing AC charge schedule…")
        self.inv_status_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        threading.Thread(
            target=self._write_mix_ac_charge_thread, args=(api, sn, params), daemon=True
        ).start()

    def _write_mix_ac_charge_thread(self, api, sn, params):
        try:
            raw = api.update_mix_inverter_setting(sn, "mix_ac_charge_time_period", params)
            self._inv.invoke(lambda r=raw: self._show_mix_write_done(r, None))
        except Exception as e:
            self._inv.invoke(lambda err=str(e): self._show_mix_write_done(None, err))

    def _show_mix_write_done(self, raw, err):
        self.write_ac_chg_btn.setEnabled(True)
        if err:
            self.inv_status_label.setText(f"Write failed: {err[:100]}")
            self.inv_status_label.setStyleSheet("color: #f38ba8; font-size: 11px;")
            self.set_status(f"MIX AC charge write failed: {err}")
            return
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        txt = json.dumps(raw, indent=2, default=str) if isinstance(raw, dict) else str(raw)
        ok = not (isinstance(raw, dict) and raw.get("success") is False)
        if ok:
            self.inv_status_label.setText(f"Write OK | {ts} — Read settings to verify")
            self.inv_status_label.setStyleSheet("color: #a6e3a1; font-size: 11px;")
            self.set_status("MIX AC charge schedule write completed.")
        else:
            self.inv_status_label.setText("Write returned error — see response below")
            self.inv_status_label.setStyleSheet("color: #fab387; font-size: 11px;")
            self.set_status("MIX AC charge write: server reported an error (see inverter panel).")
        prev = self.inv_settings_text.toPlainText()
        self.inv_settings_text.setPlainText(
            f"--- mix_ac_charge_time_period write @ {ts} ---\n{txt}\n\n{prev}"
        )
        _log.info("Advisor", f"MIX AC charge write response: {txt[:500]}")


__all__ = [n for n in globals() if not n.startswith('__')]
