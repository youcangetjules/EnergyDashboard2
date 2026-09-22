"""
Energy Dashboard — `tabs/optimiser.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

import time as _time_mod

from energy_dashboard.common import *
class OptimiserTab(QWidget):
    """Cost-minimising plan for the next 24-48 h.

    Pulls solar forecast (Forecasts), Agile import + export rates, live SOC (Growatt),
    and the SmartAdvisor's hour-of-day usage profile, then solves the dispatch DP
    and shows: an action card, a strip plot, a per-slot decision table, and a
    'why this plan?' panel. Inverter / Tasmota writes are NOT wired here yet."""

    def __init__(self, growatt_tab, octopus_tab, forecasts_tab, advisor_tab,
                 tasmota_tab, app_params, status_callback):
        super().__init__()
        self.growatt_tab = growatt_tab
        self.octopus_tab = octopus_tab
        self.forecasts_tab = forecasts_tab
        self.advisor_tab = advisor_tab
        self.tasmota_tab = tasmota_tab
        self.app_params = app_params
        self.set_status = status_callback
        self._inv = Invoker(self)
        self._running = False
        self._last_plan = None
        # Inverter writeback rollback state. Captured before each successful
        # write; cleared on a successful rollback.
        self._pre_write_raw = None       # raw `obj` dict from get_mix_inverter_settings
        self._pre_write_ac = None        # parsed AC-charge state, or None on parse failure
        self._pre_write_params = None    # paramN dict reconstructed from snapshot, or None
        self._pre_write_ts = None        # datetime of snapshot
        self._last_write_params = None   # paramN dict that was last written (for verify)
        # Parallel state for the forced-discharge writeback path.
        self._pre_write_discharge_raw = None
        self._pre_write_discharge_ac = None
        self._pre_write_discharge_params = None
        self._pre_write_discharge_ts = None
        self._last_discharge_write_params = None
        # Set by EnergyDashboard.build_ui — fired when a plan is rendered so
        # the global tab freshness colouring updates.
        self.on_data_updated = None
        # Auto-replan state. The timer is created in build_ui and is connected
        # to _check_auto_replan; it ticks every _PLAN_AUTO_REPLAN_TICK_S
        # regardless of the enabled flag (the slot returns early when off),
        # which keeps "Next check in X" labels accurate even when toggled off.
        self._last_auto_replan_ts = None     # last time _check_auto_replan FIRED
        self._last_plan_built_ts = None      # wall-clock when _last_plan was built
        self._auto_replan_timer = None       # QTimer; created in build_ui
        self.build_ui()

    # ── UI ─────────────────────────────────────────────────────────────

    def build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(6)

        ctrl_box = QGroupBox("Optimiser controls")
        ctrl = QHBoxLayout(ctrl_box)
        self.run_btn = QPushButton("Build plan")
        self.run_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self.run_btn.setToolTip(
            "Fetch fresh solar forecast + Agile import/export rates, read SOC, "
            "then run the dispatch DP and heater scheduler."
        )
        self.run_btn.clicked.connect(self.run_planner)
        ctrl.addWidget(self.run_btn)
        ctrl.addSpacing(10)

        ctrl.addWidget(QLabel("PV forecast scale:"))
        self.sp_pv_forecast_scale = QDoubleSpinBox()
        self.sp_pv_forecast_scale.setRange(0.3, 1.0)
        self.sp_pv_forecast_scale.setSingleStep(0.05)
        self.sp_pv_forecast_scale.setDecimals(2)
        self.sp_pv_forecast_scale.setValue(_PLAN_SOLAR_FORECAST_SCALE)
        self.sp_pv_forecast_scale.setToolTip(
            "Each half-hour's model solar yield is multiplied by this before the "
            "optimiser runs. 1.0 = use the Forecast.Solar curve as published; "
            "below 1.0 assumes less PV (more conservative overnight grid charging)."
        )
        ctrl.addWidget(self.sp_pv_forecast_scale)

        ctrl.addSpacing(10)
        ctrl.addWidget(QLabel("PV10 weight:"))
        self.sp_pv10_weight = QDoubleSpinBox()
        self.sp_pv10_weight.setRange(0.0, 1.0)
        self.sp_pv10_weight.setSingleStep(0.05)
        self.sp_pv10_weight.setDecimals(2)
        # Persist across sessions so risk-aversion preference sticks.
        _qs_pv10 = QSettings("PowerModel", "EnergyDashboard2")
        try:
            _persisted_pv10 = float(_qs_pv10.value(
                "optimiser/pv10_weight", _PLAN_PV10_WEIGHT, type=float))
        except Exception:
            _persisted_pv10 = _PLAN_PV10_WEIGHT
        self.sp_pv10_weight.setValue(_persisted_pv10)
        self.sp_pv10_weight.setToolTip(
            "Weight (0–1) on a synthetic PV10 (worst-case) curve, blended with the "
            "central PV50 forecast: pv_used = (1−w)·PV50 + w·PV10. Predbat's typical "
            "setting is 0.30. The PV10 curve is derived from PV50 with a *time-localised* "
            "ratio — peak-midday slots get derated less (≈0.75×PV50) and shoulder/cloudy "
            "slots get derated more (≈0.30×PV50), capturing that overcast days hit early/late "
            "generation harder than peak. Composes with PV forecast scale (PV10 blend "
            "applied first, then the flat scale). 0.0 = legacy behaviour (pure PV50)."
        )
        self.sp_pv10_weight.valueChanged.connect(self._on_pv10_weight_changed)
        ctrl.addWidget(self.sp_pv10_weight)

        ctrl.addSpacing(10)
        ctrl.addWidget(QLabel("Heater kW:"))
        self.sp_heater_kw = QDoubleSpinBox()
        self.sp_heater_kw.setRange(0.5, 6.0)
        self.sp_heater_kw.setSingleStep(0.1)
        self.sp_heater_kw.setDecimals(1)
        self.sp_heater_kw.setValue(_PLAN_HEATER_KW)
        ctrl.addWidget(self.sp_heater_kw)

        ctrl.addSpacing(10)
        ctrl.addWidget(QLabel("Day block (h):"))
        self.sp_day_block = QSpinBox()
        self.sp_day_block.setRange(1, 8)
        self.sp_day_block.setValue(_PLAN_DAY_BLOCK_H)
        ctrl.addWidget(self.sp_day_block)

        ctrl.addSpacing(10)
        ctrl.addWidget(QLabel("Export margin (p/kWh):"))
        self.sp_export_margin = QDoubleSpinBox()
        self.sp_export_margin.setRange(0.0, 30.0)
        self.sp_export_margin.setSingleStep(0.5)
        self.sp_export_margin.setDecimals(1)
        self.sp_export_margin.setValue(_PLAN_EXPORT_MARGIN_P)
        self.sp_export_margin.setToolTip(
            "Battery export only fires if the export price beats the cheapest reachable "
            "import slot by at least this margin."
        )
        ctrl.addWidget(self.sp_export_margin)

        ctrl.addSpacing(10)
        self.cb_allow_export = QCheckBox("Allow battery export")
        # Default OFF: until the discharge writeback has been watched land safely,
        # the DP refuses any batt_to_grid > 0 and the discharge button stays
        # greyed out. Persisted across sessions in QSettings.
        _qs_optim_exp = QSettings("PowerModel", "EnergyDashboard2")
        try:
            _persisted_export = bool(_qs_optim_exp.value(
                "optimiser/allow_battery_export", _PLAN_ALLOW_BATTERY_EXPORT, type=bool))
        except Exception:
            _persisted_export = _PLAN_ALLOW_BATTERY_EXPORT
        self.cb_allow_export.setChecked(_persisted_export)
        self.cb_allow_export.setToolTip(
            "Off (default): the DP will not plan any battery→grid windows; the "
            "“Send export schedule…” button stays disabled. On: the DP can plan "
            "forced-discharge windows when the export rate beats the cheapest "
            "future import slot by ≥ the Export margin, and the writeback button "
            "becomes available once a plan with export windows exists. "
            "Always confirm the windows look sensible before pressing it."
        )
        self.cb_allow_export.toggled.connect(self._on_allow_export_toggled)
        ctrl.addWidget(self.cb_allow_export)

        ctrl.addSpacing(10)
        ctrl.addWidget(QLabel("Terminal SOC value:"))
        self.sp_terminal_value_scale = QDoubleSpinBox()
        self.sp_terminal_value_scale.setRange(0.0, 2.0)
        self.sp_terminal_value_scale.setSingleStep(0.05)
        self.sp_terminal_value_scale.setDecimals(2)
        self.sp_terminal_value_scale.setValue(_PLAN_TERMINAL_VALUE_SCALE)
        self.sp_terminal_value_scale.setToolTip(
            "How much the DP values energy left in the battery at the end of the planning "
            "horizon, expressed as a multiple of (mean future import price × discharge "
            "efficiency). 1.0 ≈ Predbat's default — 1 stored kWh is worth roughly 1 kWh "
            "of avoided import at tomorrow's average rate. 0.0 reverts to the old behaviour "
            "(empty the battery by horizon-end). >1.0 makes the DP hoard SOC into the future."
        )
        ctrl.addWidget(self.sp_terminal_value_scale)

        ctrl.addSpacing(10)
        self.cb_auto_replan = QCheckBox("Auto re-plan")
        _qs_auto = QSettings("PowerModel", "EnergyDashboard2")
        try:
            _persisted_auto = bool(_qs_auto.value(
                "optimiser/auto_replan", _PLAN_AUTO_REPLAN_DEFAULT, type=bool))
        except Exception:
            _persisted_auto = _PLAN_AUTO_REPLAN_DEFAULT
        self.cb_auto_replan.setChecked(_persisted_auto)
        self.cb_auto_replan.setToolTip(
            f"When ON, the Optimiser silently re-runs Build plan in the background "
            f"every {_PLAN_AUTO_REPLAN_TICK_S}s tick if any of these triggers fire:\n"
            f"  • no plan exists yet,\n"
            f"  • the current plan was built > {_PLAN_AUTO_REPLAN_PLAN_AGE_MIN} min ago "
            f"(so it has slots that are now in the past),\n"
            f"  • the wall clock has crossed {_PLAN_AUTO_REPLAN_AGILE_PUBLISH_HOUR:02d}:00 "
            f"and the current plan was built BEFORE that boundary "
            f"(tomorrow's Agile rates have just landed),\n"
            f"  • actual SOC has drifted from the plan's predicted SOC at the current "
            f"slot by more than {_PLAN_AUTO_REPLAN_SOC_DRIFT_PP} percentage points "
            f"(forecast was wrong, surprise high consumption, etc.).\n"
            f"Cooldown {_PLAN_AUTO_REPLAN_COOLDOWN_S//60} min between auto-runs. "
            f"Skipped silently if a planner thread is already in flight. The trigger "
            f"reason is logged to the Optimiser channel each time it fires. "
            f"Persisted in QSettings (optimiser/auto_replan)."
        )
        self.cb_auto_replan.toggled.connect(self._on_auto_replan_toggled)
        ctrl.addWidget(self.cb_auto_replan)

        # Always-running tick (cheap), regardless of the flag — the slot returns
        # early when the flag is off but the timer object is reused so we don't
        # have to start/stop on every toggle.
        self._auto_replan_timer = QTimer(self)
        self._auto_replan_timer.setInterval(_PLAN_AUTO_REPLAN_TICK_S * 1000)
        self._auto_replan_timer.timeout.connect(self._check_auto_replan)
        self._auto_replan_timer.start()

        ctrl.addStretch()

        self.explain_btn = QPushButton("Explain this")
        self.explain_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self.explain_btn.setToolTip(
            "Show how the load is decomposed (fridge / Tasmota / heater) before the DP runs."
        )
        self.explain_btn.clicked.connect(self._show_explainer)
        ctrl.addWidget(self.explain_btn)

        # "What gets sent + when?" — opens a modal that lists, for the
        # current plan, (a) the actual REST writebacks the dashboard would
        # POST when you press Send (with full paramN bodies + click-to-copy
        # JSON) and (b) a chronological 24 h timeline of every state change
        # the inverter will execute as a result. Disabled until a plan
        # exists; toggled on in _apply_plan().
        self.command_schedule_btn = QPushButton("View command schedule…")
        self.command_schedule_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self.command_schedule_btn.setEnabled(False)
        self.command_schedule_btn.setToolTip(
            "Show the exact REST writebacks the dashboard will POST to the "
            "Growatt cloud (one per schedule type — charge and, if "
            "enabled, discharge) and a minute-by-minute timeline of when "
            "the inverter will start / stop each programmed window over "
            "the next 24 hours. Read-only — no commands are sent from "
            "this dialog."
        )
        self.command_schedule_btn.clicked.connect(self._show_command_schedule)
        ctrl.addWidget(self.command_schedule_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        ctrl.addWidget(self.status_label)
        main.addWidget(ctrl_box)

        self.action_card = QFrame()
        self.action_card.setStyleSheet(
            "QFrame { background: transparent; border: 1px solid #45475a; border-radius: 10px; }"
        )
        ac = QVBoxLayout(self.action_card)
        ac.setContentsMargins(14, 10, 14, 10)
        ac.setSpacing(2)
        self.action_title = QLabel('Press "Build plan" to optimise the next 24-48 h.')
        self.action_title.setFont(QFont('Helvetica', 16, QFont.Bold))
        self.action_title.setStyleSheet("color: #cdd6f4;")
        ac.addWidget(self.action_title)

        # All three action lines on one horizontal row, kept colour-coded so the
        # semantic groups (charge / export / heater) are still instantly readable.
        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 4, 0, 0)
        actions_row.setSpacing(20)
        self.action_overnight = QLabel("")
        self.action_overnight.setStyleSheet("color: #fab387; font-size: 13px;")
        self.action_overnight.setWordWrap(True)
        actions_row.addWidget(self.action_overnight, 1)
        self.action_export = QLabel("")
        self.action_export.setStyleSheet("color: #a6e3a1; font-size: 13px;")
        self.action_export.setWordWrap(True)
        actions_row.addWidget(self.action_export, 1)
        self.action_heater = QLabel("")
        self.action_heater.setStyleSheet("color: #b8dcff; font-size: 13px;")
        self.action_heater.setWordWrap(True)
        actions_row.addWidget(self.action_heater, 1)
        ac.addLayout(actions_row)

        # Writeback row: send the planned grid-charge windows to the MIX
        # inverter. Disabled until a plan exists.
        write_row = QHBoxLayout()
        write_row.setContentsMargins(0, 6, 0, 0)
        write_row.setSpacing(8)
        self.write_inverter_btn = QPushButton("Send schedule to inverter…")
        self.write_inverter_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self.write_inverter_btn.setEnabled(False)
        self.write_inverter_btn.setToolTip(
            "Push the plan's grid-charge windows to the MIX inverter "
            "(mix_ac_charge_time_period). You'll get a confirmation dialog "
            "showing the exact HH:MM windows, charge power % and stop-SOC "
            "before anything is sent. Wrong settings can affect battery "
            "behaviour — verify with Smart Advisor → Read Inverter Settings."
        )
        self.write_inverter_btn.clicked.connect(self._write_plan_to_inverter)
        write_row.addWidget(self.write_inverter_btn)

        self.rollback_inverter_btn = QPushButton("Rollback last write…")
        self.rollback_inverter_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self.rollback_inverter_btn.setEnabled(False)
        self.rollback_inverter_btn.setToolTip(
            "Restore the AC charge schedule that was on the inverter immediately "
            "before the last writeback. If the prior schedule could not be parsed, "
            "this becomes a panic-stop that disables grid charging entirely."
        )
        self.rollback_inverter_btn.clicked.connect(self._rollback_last_write)
        write_row.addWidget(self.rollback_inverter_btn)

        write_row.addSpacing(6)
        write_row.addWidget(QLabel("Charge power:"))
        self.sp_inv_charge_power = QSpinBox()
        self.sp_inv_charge_power.setRange(10, 100)
        self.sp_inv_charge_power.setSuffix(" %")
        self.sp_inv_charge_power.setToolTip(
            "Grid charging power limit as % of inverter capability. Lower "
            "values stretch each window over more time but are gentler on "
            "the battery."
        )
        _qs_optim = QSettings("PowerModel", "EnergyDashboard2")
        try:
            _persisted_pwr = int(_qs_optim.value(
                "optimiser/inverter_charge_power_pct", 100, type=int))
        except Exception:
            _persisted_pwr = 100
        self.sp_inv_charge_power.setValue(max(10, min(100, _persisted_pwr)))
        self.sp_inv_charge_power.valueChanged.connect(
            lambda v: QSettings("PowerModel", "EnergyDashboard2").setValue(
                "optimiser/inverter_charge_power_pct", int(v))
        )
        write_row.addWidget(self.sp_inv_charge_power)

        self.inv_write_status = QLabel("")
        self.inv_write_status.setStyleSheet("color: #a6adc8; font-size: 11px;")
        write_row.addWidget(self.inv_write_status)
        write_row.addStretch()
        ac.addLayout(write_row)

        # Second writeback row: forced-discharge schedule (battery → grid).
        # Both buttons stay disabled unless (a) the “Allow battery export”
        # checkbox is on AND (b) the current plan has at least one export
        # window. Snapshot/verify/auto-rollback machinery is parallel to the
        # charge writeback above but operates on `mix_ac_discharge_time_period`.
        discharge_row = QHBoxLayout()
        discharge_row.setContentsMargins(0, 4, 0, 0)
        discharge_row.setSpacing(8)
        self.write_discharge_btn = QPushButton("Send export schedule…")
        self.write_discharge_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self.write_discharge_btn.setEnabled(False)
        self.write_discharge_btn.setToolTip(
            "Push the plan's battery→grid windows to the MIX inverter "
            "(mix_ac_discharge_time_period). Disabled unless ‘Allow battery "
            "export’ is on and the plan contains at least one export window. "
            "Confirmation dialog shows the exact HH:MM windows, discharge "
            "power % and stop-SOC floor before anything is sent."
        )
        self.write_discharge_btn.clicked.connect(self._write_discharge_to_inverter)
        discharge_row.addWidget(self.write_discharge_btn)

        self.rollback_discharge_btn = QPushButton("Rollback last export write…")
        self.rollback_discharge_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self.rollback_discharge_btn.setEnabled(False)
        self.rollback_discharge_btn.setToolTip(
            "Restore the discharge schedule that was on the inverter immediately "
            "before the last export writeback. If the prior schedule could not be "
            "parsed, this becomes a panic-stop that disables forced-discharge entirely."
        )
        self.rollback_discharge_btn.clicked.connect(self._rollback_last_discharge_write)
        discharge_row.addWidget(self.rollback_discharge_btn)

        _optim_writeback_w = self.rollback_discharge_btn.sizeHint().width()
        for _ob in (
            self.write_inverter_btn,
            self.rollback_inverter_btn,
            self.write_discharge_btn,
            self.rollback_discharge_btn,
        ):
            _ob.setFixedWidth(_optim_writeback_w)

        discharge_row.addSpacing(6)
        discharge_row.addWidget(QLabel("Discharge power:"))
        self.sp_inv_discharge_power = QSpinBox()
        self.sp_inv_discharge_power.setRange(10, 100)
        self.sp_inv_discharge_power.setSuffix(" %")
        self.sp_inv_discharge_power.setToolTip(
            "Forced-discharge power as % of inverter rated rate. 100 % empties "
            "the battery as fast as the inverter and grid will allow within the "
            "scheduled window."
        )
        try:
            _persisted_dpwr = int(_qs_optim.value(
                "optimiser/inverter_discharge_power_pct",
                _PLAN_INV_DISCHARGE_POWER_DEFAULT, type=int))
        except Exception:
            _persisted_dpwr = _PLAN_INV_DISCHARGE_POWER_DEFAULT
        self.sp_inv_discharge_power.setValue(max(10, min(100, _persisted_dpwr)))
        self.sp_inv_discharge_power.valueChanged.connect(
            lambda v: QSettings("PowerModel", "EnergyDashboard2").setValue(
                "optimiser/inverter_discharge_power_pct", int(v))
        )
        discharge_row.addWidget(self.sp_inv_discharge_power)

        self.inv_discharge_status = QLabel("")
        self.inv_discharge_status.setStyleSheet("color: #a6adc8; font-size: 11px;")
        discharge_row.addWidget(self.inv_discharge_status)
        discharge_row.addStretch()
        ac.addLayout(discharge_row)

        main.addWidget(self.action_card)

        splitter = QSplitter(Qt.Vertical)

        chart_widget = QWidget()
        chart_lay = QVBoxLayout(chart_widget)
        chart_lay.setContentsMargins(0, 0, 0, 0)
        chart_lay.setSpacing(2)
        self.fig = Figure(figsize=(13, 8.5), dpi=100)
        # subplots_adjust (rather than tight_layout) lets us pin the top chart hard against the
        # top of the canvas so there's no gap above 'Optimised dispatch plan'.
        # Extra bottom room for two tick rows (6 h + 3 h) and the “Now” label.
        # hspace≈0.30 adds ~20px between the dispatch and price panels vs 0.18.
        _OPT_CHART_HSPACE = 0.30
        self.fig.subplots_adjust(
            top=0.965, bottom=0.16, left=0.06, right=0.94, hspace=_OPT_CHART_HSPACE,
        )
        gs = self.fig.add_gridspec(
            2, 1, hspace=_OPT_CHART_HSPACE, height_ratios=[3, 2],
        )
        self.ax_top = self.fig.add_subplot(gs[0, 0])
        self.ax_bot = self.fig.add_subplot(gs[1, 0], sharex=self.ax_top)
        for ax in (self.ax_top, self.ax_bot):
            _style_ax_dark(ax, self.fig)
        self.ax_soc = self.ax_top.twinx()
        _style_ax_dark(self.ax_soc, self.fig)
        self.ax_soc.set_facecolor((0, 0, 0, 0))
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setMinimumHeight(380)
        chart_lay.addWidget(self.canvas)
        toolbar = DarkNavigationToolbar(self.canvas, self)
        chart_lay.addWidget(toolbar)

        # Hover read-out for both subplots — populated by _on_chart_motion.
        self.cursor_label = QLabel(
            "Hover the charts: time · import · export · solar · load · heater · SOC."
        )
        self.cursor_label.setStyleSheet(
            f"color: {_UI_BLUE_MUTED}; font-size: 11px; padding: 2px 4px;"
        )
        self.cursor_label.setWordWrap(True)
        chart_lay.addWidget(self.cursor_label)

        # Mouse-motion crosshair (lines initialised lazily after first plot).
        self._opt_motion_cid = self.canvas.mpl_connect(
            'motion_notify_event', self._on_chart_motion
        )
        self._opt_cursor_lines = None
        self._chart_shimmer = ChartShimmerOverlay(self.canvas)

        splitter.addWidget(chart_widget)

        bottom = QSplitter(Qt.Horizontal)
        tbl_box = QGroupBox("Per-slot decisions")
        tbl_lay = QVBoxLayout(tbl_box)
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "Time", "p in", "p out", "Solar", "Load", "Heater",
            "Batt action", "SOC %", "£ net"
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        tbl_lay.addWidget(self.table)
        qtable_set_column_width_key(self.table, "optimiser_per_slot")
        qtable_prepare_interactive_columns(self.table)
        qtable_restore_column_widths(self.table, "optimiser_per_slot", resize_if_no_saved=True)
        qtable_attach_column_width_persistence(self.table)
        bottom.addWidget(tbl_box)

        why_box = QGroupBox("Why this plan?")
        why_lay = QVBoxLayout(why_box)
        self.why_text = QTextEdit()
        self.why_text.setReadOnly(True)
        self.why_text.setFont(QFont('Courier', 9))
        self.why_text.setPlaceholderText(
            "After Build plan: bridge-kWh calculation, expected solar, heater "
            "alternatives, and savings vs naive overnight charge."
        )
        why_lay.addWidget(self.why_text)
        bottom.addWidget(why_box)
        bottom.setStretchFactor(0, 3)
        bottom.setStretchFactor(1, 2)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 3)
        main.addWidget(splitter, 1)

    # ── orchestration ──────────────────────────────────────────────────

    def _on_auto_replan_toggled(self, checked):
        """Persist the flag. The QTimer is always running — the slot returns
        early when the flag is off — so toggling has no thread side-effects.
        """
        try:
            QSettings("PowerModel", "EnergyDashboard2").setValue(
                "optimiser/auto_replan", bool(checked))
        except Exception:
            pass
        # Reset cooldown so an immediate first auto-fire is possible after
        # the user enables the flag — but the trigger conditions still have
        # to actually be true.
        if checked:
            self._last_auto_replan_ts = None
            try:
                _log.info("Optimiser", "Auto re-plan enabled.")
            except Exception:
                pass
        else:
            try:
                _log.info("Optimiser", "Auto re-plan disabled.")
            except Exception:
                pass

    def _planned_soc_pct_at(self, when):
        """Return the planned SOC % at the slot covering ``when`` (a tz-aware
        datetime), or None if no plan exists / ``when`` is outside the plan
        horizon. Uses the ``soc_pct_trace`` from the DP result, indexed by
        slot start (= SOC at the start of that slot, before its action)."""
        if not self._last_plan:
            return None
        try:
            slot_starts = self._last_plan['slot_starts']
            trace = self._last_plan['result'].get('soc_pct_trace')
            if trace is None or len(trace) == 0 or len(slot_starts) == 0:
                return None
            now_ts = pd.Timestamp(when)
            if now_ts.tz is None:
                now_ts = now_ts.tz_localize('Europe/London')
            else:
                now_ts = now_ts.tz_convert('Europe/London')
            first = pd.Timestamp(slot_starts[0])
            if first.tz is None:
                first = first.tz_localize('Europe/London')
            else:
                first = first.tz_convert('Europe/London')
            if now_ts < first:
                return float(trace[0])  # before the plan starts: use start SOC
            slot_idx = int((now_ts - first).total_seconds() // (30 * 60))
            if slot_idx >= len(trace):
                return None  # past the horizon
            return float(trace[slot_idx])
        except Exception:
            return None

    def _check_auto_replan(self):
        """QTimer slot: evaluate trigger conditions and fire ``run_planner``
        if any are true and the cooldown has elapsed. Returns silently in all
        no-op paths so the timer can keep ticking without user-visible churn.
        """
        try:
            if not getattr(self, "cb_auto_replan", None) or not self.cb_auto_replan.isChecked():
                return
            if self._running:
                return  # planner already in flight; nothing to do
            import pytz
            now = datetime.now(pytz.timezone('Europe/London'))
            # Cooldown gate (only after the first auto-fire).
            if self._last_auto_replan_ts is not None:
                gap = (now - self._last_auto_replan_ts).total_seconds()
                if gap < _PLAN_AUTO_REPLAN_COOLDOWN_S:
                    return

            reasons = []
            # Trigger D: no plan exists yet — fire as soon as cooldown allows.
            if self._last_plan is None:
                reasons.append("no plan exists yet")
            else:
                # Trigger B: plan staleness (built more than N minutes ago).
                if self._last_plan_built_ts is not None:
                    age_min = (now - self._last_plan_built_ts).total_seconds() / 60.0
                    if age_min > _PLAN_AUTO_REPLAN_PLAN_AGE_MIN:
                        reasons.append(f"plan is {age_min:.0f} min old")
                # Trigger A: Agile publication boundary just crossed. Octopus
                # publishes tomorrow's Agile rates around 16:00 BST; if our
                # current plan was built BEFORE 16:00 today and we're now AFTER
                # 16:00, refresh so the planner can extend its horizon into
                # tomorrow's freshly-known rates.
                if (
                    self._last_plan_built_ts is not None
                    and now.hour >= _PLAN_AUTO_REPLAN_AGILE_PUBLISH_HOUR
                    and self._last_plan_built_ts.date() == now.date()
                    and self._last_plan_built_ts.hour < _PLAN_AUTO_REPLAN_AGILE_PUBLISH_HOUR
                ):
                    reasons.append("Agile publication boundary crossed")
                # Trigger C: SOC drift vs plan. Reads live SOC; gracefully
                # ignored if the Growatt tab can't supply one.
                try:
                    actual_soc = self.growatt_tab.get_current_soc()
                    if actual_soc is not None:
                        planned = self._planned_soc_pct_at(now)
                        if planned is not None:
                            drift = abs(float(actual_soc) - planned)
                            if drift > _PLAN_AUTO_REPLAN_SOC_DRIFT_PP:
                                reasons.append(
                                    f"SOC drift {drift:.1f} pp "
                                    f"(actual {float(actual_soc):.0f}%, planned {planned:.0f}%)"
                                )
                except Exception:
                    pass

            if not reasons:
                return

            reason_str = "; ".join(reasons)
            try:
                _log.info("Optimiser", f"Auto re-plan triggered: {reason_str}")
            except Exception:
                pass
            self.set_status(f"Optimiser: auto re-plan ({reason_str})")
            self._last_auto_replan_ts = now
            self.run_planner()
        except Exception as e:
            try:
                _log.warn("Optimiser", f"Auto re-plan check failed: {e}")
            except Exception:
                pass

    def _on_pv10_weight_changed(self, value):
        """Persist the PV10 blend weight. The plan itself is NOT re-run
        automatically — change the value then press Build plan to see the
        new solar curve flow through the DP."""
        try:
            QSettings("PowerModel", "EnergyDashboard2").setValue(
                "optimiser/pv10_weight", float(value))
        except Exception:
            pass

    def _on_allow_export_toggled(self, checked):
        """Persist the flag and update the discharge-write button availability.
        The plan itself is NOT re-run automatically — toggling export changes
        what the DP would plan, so we leave the user to press Build plan to see
        the new behaviour. Disable the discharge writeback if the flag is now
        off (since the gate would refuse it anyway)."""
        try:
            QSettings("PowerModel", "EnergyDashboard2").setValue(
                "optimiser/allow_battery_export", bool(checked))
        except Exception:
            pass
        if not checked:
            if hasattr(self, "write_discharge_btn"):
                self.write_discharge_btn.setEnabled(False)
        else:
            # Re-enable only if a current plan exists with export windows.
            self._refresh_discharge_button_enabled()
        if hasattr(self, "status_label"):
            self.status_label.setText(
                "Battery export {} — press Build plan to refresh.".format(
                    "ENABLED" if checked else "disabled"))

    def _refresh_discharge_button_enabled(self):
        """Enable the discharge writeback button only when (a) the export flag
        is on, (b) a plan exists, and (c) that plan has at least one
        battery→grid window."""
        if not hasattr(self, "write_discharge_btn"):
            return
        ok = (
            getattr(self, "cb_allow_export", None) is not None
            and self.cb_allow_export.isChecked()
            and self._last_plan is not None
        )
        if ok:
            try:
                exp = collapse_grid_export_runs(
                    self._last_plan['slot_starts'],
                    self._last_plan['result']['actions'],
                )
                ok = bool(exp)
            except Exception:
                ok = False
        self.write_discharge_btn.setEnabled(bool(ok))

    def run_planner(self):
        if self._running:
            return
        self._running = True
        self.run_btn.setEnabled(False)
        self._chart_shimmer.start()
        self.set_status("Optimiser: building plan...")
        self.status_label.setText("Fetching data...")
        threading.Thread(target=self._planner_thread, daemon=True).start()

    def _planner_thread(self):
        try:
            self._planner_thread_impl()
        except Exception as e:
            import traceback
            _log.warn("Optimiser", f"Planner failed: {e}\n{traceback.format_exc()}")
            err = str(e) or type(e).__name__
            self._inv.invoke(lambda msg=err: self._planner_failed(msg))

    def _planner_failed(self, message):
        self._chart_shimmer.stop()
        self._running = False
        self.run_btn.setEnabled(True)
        short = (message or "Unknown error").replace("\n", " ")
        if len(short) > 160:
            short = short[:157] + "..."
        self.status_label.setText(f"Failed: {short}")
        self.set_status(f"Optimiser failed: {short}")

    def _planner_thread_impl(self):
        import pytz
        london = pytz.timezone('Europe/London')
        now_l = datetime.now(london)
        slot_starts = plan_horizon_slot_starts(now_l, n_slots=_PLAN_SLOTS_DEFAULT)

        soc_box = {'v': None, 'done': False}

        def _read_soc():
            soc_box['v'] = self.growatt_tab.get_current_soc()
            soc_box['done'] = True

        self._inv.invoke(_read_soc)
        for _ in range(60):
            if soc_box['done']:
                break
            threading.Event().wait(0.05)
        soc_now = soc_box['v'] if soc_box['v'] is not None else 50.0
        soc_source = "live" if soc_box['v'] is not None else "assumed 50%"

        self._inv.invoke(lambda: self.status_label.setText("Fetching solar forecast..."))
        solar_df = pd.DataFrame()
        try:
            se = self.forecasts_tab.solar_edits
            solar_df, _ = fetch_solar_forecast(
                se['lat'].text(), se['lon'].text(), se['tilt'].text(),
                se['azimuth'].text(), se['kwp'].text()
            )
        except Exception as e:
            _log.warn("Optimiser", f"Solar forecast error: {e}")

        self._inv.invoke(lambda: self.status_label.setText("Fetching Agile prices..."))
        p = self.app_params
        agile_in = pd.DataFrame()
        try:
            agile_in = fetch_agile_prices(p.agile_product, p.agile_tariff)
        except Exception as e:
            _log.warn("Optimiser", f"Agile import price error: {e}")

        agile_ex_series = pd.Series(dtype=float)
        try:
            ts0 = pd.Timestamp(slot_starts[0]).tz_convert('UTC')
            ts1 = pd.Timestamp(slot_starts[-1]).tz_convert('UTC') + pd.Timedelta(hours=1)
            agile_ex_series = fetch_agile_rates_series_utc(
                p.agile_product, p.agile_export_tariff, ts0, ts1
            )
        except Exception as e:
            _log.warn("Optimiser", f"Agile export price error: {e}")

        self._inv.invoke(lambda: self.status_label.setText("Solving dispatch DP..."))

        # Read heater_kw FIRST so we can pass it to the usage-profile
        # builder. The builder needs it to skip any matching scheduled-load
        # entry (and decontaminate the Octopus floor) so the immersion
        # isn't counted both in the rigid load AND added again as
        # heater_kwh in dp_battery_dispatch.
        heater_kw = float(self.sp_heater_kw.value())
        day_block_h = int(self.sp_day_block.value())

        usage_profile = {}
        usage_profile_full = {}
        try:
            usage_profile = self.advisor_tab._build_usage_profile(
                exclude_heater_kw=heater_kw,
            )
        except Exception as e:
            _log.warn("Optimiser", f"Usage profile error: {e}")
        try:
            # Non-decontaminated profile for the past-extension chart, so the
            # historical bars accurately reflect what really happened (the
            # immersion that ran in the past is part of past load, even if
            # the Optimiser will re-schedule it differently going forward).
            usage_profile_full = self.advisor_tab._build_usage_profile()
        except Exception as e:
            _log.warn("Optimiser", f"Full usage profile error: {e}")
            usage_profile_full = usage_profile  # safe fallback

        load_kwh = plan_load_per_slot(slot_starts, usage_profile, p.base_load_kw)
        solar_kwh = plan_solar_per_slot(
            slot_starts, solar_df,
            forecast_scale=float(self.sp_pv_forecast_scale.value()),
            pv10_weight=float(self.sp_pv10_weight.value()),
        )
        p_in = plan_prices_per_slot(slot_starts, agile_in, p.import_flat_pence)
        p_ex = plan_export_prices_per_slot(slot_starts, agile_ex_series, p.export_flat_pence)

        heater = pick_heater_windows(
            slot_starts, p_in, p_ex, solar_kwh,
            heater_kw=heater_kw, day_block_h=day_block_h
        )

        capacity = float(p.battery_capacity_kwh)
        eta = float(p.analytics_efficiency_pct) / 100.0
        max_kw = float(p.analytics_max_charge_kw)
        soc_min_pct = float(p.battery_low_soc_threshold_pct)
        soc_now_kwh = capacity * (float(soc_now) / 100.0)

        result = dp_battery_dispatch(
            load_kwh, solar_kwh, p_in, p_ex,
            soc_now_kwh, capacity,
            eta=eta, max_kw=max_kw,
            soc_min_pct=soc_min_pct,
            export_margin_p=float(self.sp_export_margin.value()),
            heater_kwh=heater['heater_kwh'],
            terminal_value_scale=float(self.sp_terminal_value_scale.value()),
            allow_battery_export=bool(self.cb_allow_export.isChecked()),
        )

        baseline_cost = self._naive_overnight_cost(
            slot_starts, load_kwh, solar_kwh, p_in, p_ex,
            soc_now_kwh, capacity, eta, max_kw, soc_min_pct, heater['heater_kwh']
        )

        chart_past = build_optimiser_chart_past_extension(
            slot_starts, agile_in, agile_ex_series, solar_df, usage_profile_full,
            float(p.import_flat_pence), float(p.export_flat_pence),
            float(self.sp_pv_forecast_scale.value()), float(p.base_load_kw),
            pv10_weight=float(self.sp_pv10_weight.value()),
        )

        plan = {
            'slot_starts': slot_starts,
            'load_kwh': load_kwh,
            'solar_kwh': solar_kwh,
            'p_in': p_in, 'p_ex': p_ex,
            'heater': heater, 'heater_kw': heater_kw,
            'result': result,
            'baseline_cost_p': baseline_cost,
            'soc_now': soc_now, 'soc_source': soc_source,
            'capacity': capacity, 'eta': eta, 'max_kw': max_kw,
            'chart_past': chart_past,
        }
        self._inv.invoke(lambda pl=plan: self._apply_plan(pl))

    def _naive_overnight_cost(self, slot_starts, load_kwh, solar_kwh, p_in, p_ex,
                              soc_now_kwh, capacity, eta, max_kw, soc_min_pct, heater_kwh):
        """Cost if we just blindly charge to ~100% on the cheapest 5 overnight slots."""
        eff = float(eta) ** 0.5
        max_hh = max_kw * 0.5
        soc_min_kwh = capacity * (soc_min_pct / 100.0)
        soc = soc_now_kwh
        idx_overnight = [i for i, t in enumerate(slot_starts)
                         if pd.Timestamp(t).hour < 6 or pd.Timestamp(t).hour >= 23]
        idx_overnight.sort(key=lambda i: p_in[i])
        plan_charge = set(idx_overnight[:5])
        cost = 0.0
        for i in range(len(slot_starts)):
            L = load_kwh[i] + heater_kwh[i]
            S = solar_kwh[i]
            pi = p_in[i]
            pe = p_ex[i]
            grid_in = 0.0
            grid_out = 0.0
            if i in plan_charge and soc < capacity:
                ch = min(max_hh, (capacity - soc) / eff)
                grid_in += ch
                soc += ch * eff
            net = S - L
            if net > 0:
                room = (capacity - soc) / eff if soc < capacity else 0.0
                ch_solar = min(net, max(0.0, max_hh - grid_in), room)
                soc += ch_solar * eff
                exp = max(0.0, net - ch_solar)
                grid_out += exp
            elif net < 0:
                deficit = -net
                disch_max = max(0.0, soc - soc_min_kwh)
                disch = min(deficit / eff, max_hh, disch_max)
                soc -= disch
                deficit -= disch * eff
                if deficit > 0:
                    grid_in += deficit
            cost += grid_in * pi - grid_out * pe
        return cost

    # ── render ─────────────────────────────────────────────────────────

    def _apply_plan(self, plan):
        self._last_plan = plan
        try:
            import pytz
            self._last_plan_built_ts = datetime.now(pytz.timezone('Europe/London'))
        except Exception:
            self._last_plan_built_ts = None
        try:
            self._render_action_card(plan)
            self._render_chart(plan)
            self._render_table(plan)
            self._render_why(plan)
        finally:
            self._chart_shimmer.stop()
            self._running = False
            self.run_btn.setEnabled(True)
            self.status_label.setText("Plan ready.")
            self.set_status("Optimiser: plan ready.")
            if hasattr(self, "write_inverter_btn"):
                self.write_inverter_btn.setEnabled(True)
            if hasattr(self, "command_schedule_btn"):
                self.command_schedule_btn.setEnabled(True)
            self._refresh_discharge_button_enabled()
            if self.on_data_updated:
                self.on_data_updated()

    def _fmt_window(self, st, en):
        return f"{pd.Timestamp(st).strftime('%a %H:%M')}-{pd.Timestamp(en).strftime('%H:%M')}"

    # ── Command schedule preview ───────────────────────────────────────

    def _build_command_list(self):
        """Build a (commands, timeline) pair for the current plan.

        ``commands`` is the list of REST writebacks the dashboard would
        POST to the Growatt cloud — one per schedule type (charge,
        discharge). Each entry is a dict::

            {
              'title': human label,
              'endpoint': method signature shown verbatim in the UI,
              'params': the paramN dict (or None if it could not be built),
              'summary': list of summary lines,
              'when_human': when this command actually fires,
              'enabled': bool — does the inverter end up doing anything
                         when this is sent (False = panic/disable write),
              'kind': 'charge' or 'discharge',
              'periods': resolved 3-period structure,
              'stop_soc': computed stop-SOC %,
              'power_pct': configured power %,
            }

        ``timeline`` is a chronologically sorted list of inverter events
        the schedule will produce over the next 24 h. Each entry::

            {
              'when': tz-aware datetime in Europe/London,
              'kind': 'charge' or 'discharge',
              'phase': 'in_progress' | 'start' | 'stop',
              'period_idx': 1..3,
              'detail': free-text description,
            }

        Returns ``([], [])`` if no plan has been built yet. Never raises.
        """
        if self._last_plan is None:
            return [], []
        plan = self._last_plan

        commands = []

        # ── Charge writeback (always present — even if it's the
        #    "panic-disable, no grid charging" variant). Mirrors what
        #    _write_plan_to_inverter would actually send.
        try:
            c_payload = self._build_inverter_payload_from_plan(plan)
            (c_params, c_summary, c_mains, c_stop_soc,
             c_charge_pct, c_periods) = c_payload
            commands.append({
                'title': 'AC charge schedule',
                'endpoint': (
                    "api.update_mix_inverter_setting(serial_number, "
                    "'mix_ac_charge_time_period', params)"
                ),
                'params': c_params,
                'summary': c_summary,
                'when_human': (
                    "Sent IMMEDIATELY when you press “Send schedule to "
                    "inverter…” on the Optimiser tab. The dashboard "
                    "never auto-sends — every writeback is gated on a "
                    "confirmation dialog."
                ),
                'enabled': bool(c_mains),
                'kind': 'charge',
                'periods': c_periods,
                'stop_soc': c_stop_soc,
                'power_pct': c_charge_pct,
            })
        except Exception as e:
            commands.append({
                'title': 'AC charge schedule',
                'endpoint': (
                    "api.update_mix_inverter_setting(serial_number, "
                    "'mix_ac_charge_time_period', params)"
                ),
                'params': None,
                'summary': [f"Could not build charge payload: {e}"],
                'when_human': "(error — would not be sent)",
                'enabled': False,
                'kind': 'charge',
                'periods': [],
                'stop_soc': None,
                'power_pct': None,
            })

        # ── Discharge writeback (only listed if the plan contains export
        #    windows AND the user has opted into battery export). When
        #    omitted we add a stub note so the user can see *why* there's
        #    no second command.
        has_export = False
        try:
            actions = plan['result']['actions']
            exp_windows = collapse_grid_export_runs(plan['slot_starts'], actions)
            has_export = bool(exp_windows)
        except Exception:
            has_export = False
        allow_export = (
            hasattr(self, 'cb_allow_export') and self.cb_allow_export.isChecked()
        )

        if has_export and allow_export:
            try:
                d_payload = self._build_inverter_discharge_payload_from_plan(plan)
                (d_params, d_summary, d_any, d_stop_soc,
                 d_disch_pct, d_periods) = d_payload
                commands.append({
                    'title': 'Forced-discharge (battery → grid) schedule',
                    'endpoint': (
                        "api.update_mix_inverter_setting(serial_number, "
                        "'mix_ac_discharge_time_period', params)"
                    ),
                    'params': d_params,
                    'summary': d_summary,
                    'when_human': (
                        "Sent IMMEDIATELY when you press “Send export "
                        "schedule…” on the Optimiser tab. Disabled "
                        "until ‘Allow battery export’ is on AND the "
                        "current plan has at least one export window — "
                        "both currently true."
                    ),
                    'enabled': bool(d_any),
                    'kind': 'discharge',
                    'periods': d_periods,
                    'stop_soc': d_stop_soc,
                    'power_pct': d_disch_pct,
                })
            except Exception as e:
                commands.append({
                    'title': 'Forced-discharge (battery → grid) schedule',
                    'endpoint': (
                        "api.update_mix_inverter_setting(serial_number, "
                        "'mix_ac_discharge_time_period', params)"
                    ),
                    'params': None,
                    'summary': [f"Could not build discharge payload: {e}"],
                    'when_human': "(error — would not be sent)",
                    'enabled': False,
                    'kind': 'discharge',
                    'periods': [],
                    'stop_soc': None,
                    'power_pct': None,
                })
        else:
            if has_export and not allow_export:
                note = (
                    "Plan contains export windows but “Allow battery "
                    "export” is OFF — no discharge writeback would be "
                    "sent. Tick the checkbox in the controls row to "
                    "enable, then re-build the plan."
                )
            elif allow_export and not has_export:
                note = (
                    "“Allow battery export” is ON but the current plan "
                    "found no slot where export beats the cheapest "
                    "future import slot by ≥ the export margin — no "
                    "discharge writeback would be sent."
                )
            else:
                note = (
                    "“Allow battery export” is OFF and no export "
                    "windows in plan — no discharge writeback would "
                    "be sent."
                )
            commands.append({
                'title': 'Forced-discharge (battery → grid) schedule',
                'endpoint': (
                    "api.update_mix_inverter_setting(serial_number, "
                    "'mix_ac_discharge_time_period', params)"
                ),
                'params': None,
                'summary': [note],
                'when_human': "(not sent for this plan)",
                'enabled': False,
                'kind': 'discharge',
                'periods': [],
                'stop_soc': None,
                'power_pct': None,
            })

        # ── 24 h inverter event timeline.
        #
        # The MIX schedule is daily-recurring HH:MM. For each enabled
        # period in each command, find the next start- and stop-instant
        # in [now, now+24h] and emit one event per boundary. We also
        # surface "currently in window N" so the user can see in-progress
        # states immediately on opening the dialog.
        try:
            import pytz
            tz = pytz.timezone('Europe/London')
        except Exception:
            tz = None
        now = datetime.now(tz) if tz else datetime.now()
        horizon = now + timedelta(hours=24)
        timeline = []

        for cmd in commands:
            if not cmd['enabled']:
                continue
            kind = cmd['kind']
            verb_start = ('Begin grid charge' if kind == 'charge'
                          else 'Begin forced discharge to grid')
            verb_stop = ('End grid charge' if kind == 'charge'
                         else 'End forced discharge')
            if kind == 'charge':
                detail_start = (
                    f"up to {cmd['stop_soc']}% SOC, "
                    f"{cmd['power_pct']}% of rated charge rate"
                )
                detail_stop = (
                    "battery returns to its default mode "
                    "(self-consumption, solar-priority)"
                )
            else:
                detail_start = (
                    f"down to {cmd['stop_soc']}% SOC floor, "
                    f"{cmd['power_pct']}% of rated discharge rate"
                )
                detail_stop = (
                    "battery returns to its default mode "
                    "(self-consumption, solar-priority)"
                )
            for idx, p in enumerate(cmd['periods'], start=1):
                if not p['enabled']:
                    continue
                st_t = p['start_time']
                en_t = p['end_time']
                # Walk today and tomorrow; emit once for the first
                # occurrence whose [start, end] overlaps [now, horizon].
                emitted = False
                for day_offset in (0, 1):
                    occ_date = now.date() + timedelta(days=day_offset)
                    if tz is not None:
                        st_dt = tz.localize(datetime.combine(occ_date, st_t))
                        en_dt = tz.localize(datetime.combine(occ_date, en_t))
                    else:
                        st_dt = datetime.combine(occ_date, st_t)
                        en_dt = datetime.combine(occ_date, en_t)
                    if en_dt <= st_dt:
                        en_dt += timedelta(days=1)
                    if en_dt <= now:
                        continue  # already-finished window
                    if st_dt > horizon:
                        continue  # past 24 h horizon
                    if st_dt <= now < en_dt:
                        timeline.append({
                            'when': now,
                            'kind': kind,
                            'phase': 'in_progress',
                            'period_idx': idx,
                            'detail': (
                                f"NOW IN PROGRESS — period {idx} "
                                f"({st_t.strftime('%H:%M')}–"
                                f"{en_t.strftime('%H:%M')}); "
                                f"{detail_start}"
                            ),
                            'verb': (f"In {kind} window (period {idx})"),
                        })
                    else:
                        timeline.append({
                            'when': st_dt,
                            'kind': kind,
                            'phase': 'start',
                            'period_idx': idx,
                            'detail': detail_start,
                            'verb': f"{verb_start} (period {idx})",
                        })
                    if en_dt <= horizon:
                        timeline.append({
                            'when': en_dt,
                            'kind': kind,
                            'phase': 'stop',
                            'period_idx': idx,
                            'detail': detail_stop,
                            'verb': f"{verb_stop} (period {idx})",
                        })
                    emitted = True
                    break
                if not emitted:
                    pass  # window's next occurrence is past the horizon

        timeline.sort(key=lambda e: e['when'])
        return commands, timeline

    @staticmethod
    def _fmt_relative(when, now):
        """Return e.g. 'in 2 h 14 min' or '14 min ago' for ``when`` vs ``now``."""
        try:
            delta = (when - now).total_seconds()
        except Exception:
            return ""
        sign = "in " if delta >= 0 else ""
        suffix = "" if delta >= 0 else " ago"
        s = abs(int(delta))
        if s < 60:
            return f"{sign}{s} s{suffix}"
        if s < 3600:
            return f"{sign}{s // 60} min{suffix}"
        h, m = divmod(s, 3600)
        return f"{sign}{h} h {m // 60} min{suffix}"

    def _show_command_schedule(self):
        """Modal dialog: lists the REST writebacks the dashboard would
        POST for the current plan, plus a 24 h timeline of every state
        change the inverter will execute as a result. Read-only: no
        commands are sent from this dialog."""
        if self._last_plan is None:
            QMessageBox.information(
                self, "No plan",
                "Build a plan first — there's nothing to preview yet.",
            )
            return

        commands, timeline = self._build_command_list()

        try:
            import pytz
            now = datetime.now(pytz.timezone('Europe/London'))
        except Exception:
            now = datetime.now()

        # Plan vintage / serial header info.
        plan_built_str = (
            self._last_plan_built_ts.strftime('%a %d %b %H:%M:%S')
            if self._last_plan_built_ts else "unknown"
        )
        try:
            _api, _plant_id, sn = self.growatt_tab.get_api()
        except Exception:
            sn = None
        sn_str = sn if sn else "(not connected — connect on Growatt tab)"

        n_to_send = sum(1 for c in commands if c['enabled'])
        n_skip = len(commands) - n_to_send

        dlg = QDialog(self)
        dlg.setWindowTitle("Inverter command schedule (preview)")
        dlg.setSizeGripEnabled(True)
        dlg.setModal(True)
        dlg.resize(1080, 820)
        dlg.setMinimumSize(820, 520)
        dlg.setStyleSheet(
            f"QDialog {{ background: {_DARK_SURFACE_BG}; }}"
            "QLabel, QTextBrowser, QTextEdit, QTreeWidget, QTableWidget "
            "{ color: #cdd6f4; }"
        )

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        header = QLabel(
            f"<h3 style='margin:0'>Inverter command schedule</h3>"
            f"<p style='margin:2px 0 0 0; color:#a6adc8;'>"
            f"Plan built: <b>{plan_built_str}</b> · "
            f"Inverter serial: <code>{sn_str}</code> · "
            f"Now: <b>{now.strftime('%a %d %b %H:%M:%S')}</b><br>"
            f"<b>{n_to_send}</b> command{'' if n_to_send == 1 else 's'} "
            f"would be sent on the corresponding Send button "
            f"({n_skip} skipped). "
            f"Timeline below covers the next 24 hours.</p>"
        )
        header.setTextFormat(Qt.RichText)
        header.setWordWrap(True)
        outer.addWidget(header)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #313244; }"
            "QSplitter::handle:hover { background: #45475a; }"
            "QSplitter::handle:vertical { height: 6px; }"
        )

        # ── Top pane: Commands tabwidget (one tab per command + JSON tab)
        top_box = QGroupBox(
            "Commands the dashboard would send to the Growatt cloud "
            "(POST per Send button press)"
        )
        top_lay = QVBoxLayout(top_box)
        top_lay.setContentsMargins(8, 8, 8, 8)
        top_lay.setSpacing(4)

        cmd_tabs = QTabWidget()
        cmd_tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #313244; background: #1e1e2e;"
            " border-radius: 4px; }"
            "QTabBar::tab { background: #313244; color: #cdd6f4; padding: 4px 12px;"
            " border: 1px solid #45475a; border-bottom: none;"
            " border-top-left-radius: 4px; border-top-right-radius: 4px; }"
            "QTabBar::tab:selected { background: #45475a; }"
        )
        for cmd in commands:
            tab_w = QWidget()
            tab_lay = QVBoxLayout(tab_w)
            tab_lay.setContentsMargins(6, 6, 6, 6)
            tab_lay.setSpacing(4)
            status_colour = '#a6e3a1' if cmd['enabled'] else '#fab387'
            status_text = ('WILL TAKE EFFECT — sends an enabled schedule'
                           if cmd['enabled']
                           else 'NO-OP — would write disabled / panic / not sent')
            cmd_html = (
                f"<p style='margin:0'><b>{cmd['title']}</b> "
                f"<span style='color:{status_colour};'>· {status_text}</span></p>"
                f"<p style='margin:4px 0 0 0;'><b>Endpoint:</b> "
                f"<code>{cmd['endpoint']}</code></p>"
                f"<p style='margin:4px 0 0 0;'><b>When sent:</b> "
                f"{cmd['when_human']}</p>"
                f"<p style='margin:8px 0 2px 0;'><b>What this command does:</b></p>"
                f"<pre style='margin:0;background:#1e1e2e;padding:6px;"
                f"color:#cdd6f4;'>"
                f"{chr(10).join(cmd['summary'])}</pre>"
            )
            body = QTextBrowser()
            body.setHtml(cmd_html)
            body.setOpenExternalLinks(False)
            body.setStyleSheet(
                f"QTextBrowser {{ background: {_DARK_SURFACE_BG}; border: 1px solid #45475a;"
                " border-radius: 6px; padding: 6px; }"
            )
            body.setMaximumHeight(260)
            tab_lay.addWidget(body)

            json_view = QTextEdit()
            json_view.setReadOnly(True)
            json_view.setFont(QFont('Courier', 9))
            try:
                json_view.setPlainText(
                    json.dumps(cmd['params'], indent=2)
                    if cmd['params'] is not None
                    else "(no payload — command would not be sent)"
                )
            except Exception:
                json_view.setPlainText(str(cmd['params']))
            tab_lay.addWidget(json_view, 1)

            cmd_tabs.addTab(tab_w, cmd['title'])

        top_lay.addWidget(cmd_tabs)
        splitter.addWidget(top_box)

        # ── Bottom pane: 24 h inverter event timeline
        bot_box = QGroupBox(
            "What the inverter will do over the next 24 hours "
            "(once the commands above have been sent)"
        )
        bot_lay = QVBoxLayout(bot_box)
        bot_lay.setContentsMargins(8, 8, 8, 8)
        bot_lay.setSpacing(4)

        if not timeline:
            none_lbl = QLabel(
                "<i>No state changes scheduled in the next 24 h.</i><br>"
                "Either no enabled windows in the writebacks above, or "
                "the inverter has nothing to do until after the 24 h "
                "horizon (the schedule recurs daily — the next event "
                "outside this window will occur at the same HH:MM the "
                "following day)."
            )
            none_lbl.setTextFormat(Qt.RichText)
            none_lbl.setStyleSheet("color:#a6adc8; padding:8px;")
            none_lbl.setWordWrap(True)
            bot_lay.addWidget(none_lbl)
        else:
            tbl = QTableWidget()
            tbl.setColumnCount(5)
            tbl.setHorizontalHeaderLabels(
                ["When", "Relative", "Schedule", "Action", "Detail"]
            )
            tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
            tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
            tbl.verticalHeader().setVisible(False)
            tbl.setAlternatingRowColors(True)
            tbl.setStyleSheet(
                "QTableWidget { background: #1e1e2e; "
                "alternate-background-color: #1e1e2e; gridline-color: #45475a; }"
                "QHeaderView::section { background: #45475a; color: #cdd6f4;"
                " padding: 4px; border: none; }"
            )
            tbl.setRowCount(len(timeline))
            for r, ev in enumerate(timeline):
                when_str = ev['when'].strftime('%a %H:%M:%S')
                rel_str = self._fmt_relative(ev['when'], now)
                kind_str = ('Charge' if ev['kind'] == 'charge'
                            else 'Discharge')
                phase = ev['phase']
                # Colour-code by (kind, phase): start = bright,
                # stop = muted, in_progress = highlighted yellow.
                if phase == 'start':
                    fg = ('#fab387' if ev['kind'] == 'charge'
                          else '#f38ba8')
                elif phase == 'stop':
                    fg = '#6c7086'
                else:  # in_progress
                    fg = '#f9e2af'
                cells = [when_str, rel_str, kind_str,
                         ev['verb'], ev['detail']]
                for c, txt in enumerate(cells):
                    item = QTableWidgetItem(txt)
                    item.setForeground(QBrush(QColor(fg)))
                    if phase == 'in_progress':
                        f = item.font()
                        f.setBold(True)
                        item.setFont(f)
                    tbl.setItem(r, c, item)
            qtable_set_column_width_key(tbl, "dlg_optim_cmd_timeline")
            qtable_prepare_interactive_columns(tbl)
            qtable_restore_column_widths(tbl, "dlg_optim_cmd_timeline", resize_if_no_saved=True)
            qtable_attach_column_width_persistence(tbl)
            bot_lay.addWidget(tbl)

            legend = QLabel(
                "<span style='color:#fab387'>■ charge start</span>  "
                "<span style='color:#f38ba8'>■ discharge start</span>  "
                "<span style='color:#6c7086'>■ end of window</span>  "
                "<span style='color:#f9e2af'>■ currently in progress</span>"
                "<br><span style='color:#a6adc8;'>The MIX schedule is "
                "<b>daily-recurring</b> — events outside this 24 h window "
                "will repeat at the same HH:MM the next day until you "
                "write a new schedule or rollback.</span>"
            )
            legend.setTextFormat(Qt.RichText)
            legend.setStyleSheet("padding:4px;")
            legend.setWordWrap(True)
            bot_lay.addWidget(legend)

        splitter.addWidget(bot_box)
        splitter.setSizes([360, 460])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        outer.addWidget(splitter, 1)

        # ── Close button
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        outer.addWidget(btns)

        _prepare_dialog_buttons(dlg)
        dlg.exec()

    # ── Inverter writeback ─────────────────────────────────────────────

    @staticmethod
    def _split_window_at_midnight(st, en):
        """Return list of (start_time, end_time) HH:MM tuples, splitting at
        midnight. The Growatt mix_ac_charge_time_period schedule is a daily
        recurring HH:MM window, so a window that crosses midnight must be sent
        as two periods (start..23:59 and 00:00..end). Zero-length windows are
        dropped."""
        st = pd.Timestamp(st)
        en = pd.Timestamp(en)
        if en <= st:
            return []
        out = []
        cur = st
        while cur.date() < en.date() and cur < en:
            day_end = (cur + pd.Timedelta(days=1)).normalize()
            seg_end = min(day_end, en)
            if cur.time() == seg_end.time():
                cur = seg_end
                continue
            # Daily-recurring schedule maxes out at 23:59 (midnight is exclusive).
            ed = time(23, 59) if seg_end.time() == time(0, 0) else seg_end.time()
            out.append((cur.time(), ed))
            cur = seg_end
        if cur < en:
            out.append((cur.time(), en.time()))
        return out

    def _build_inverter_payload_from_plan(self, plan):
        """Convert the current plan into a (params_dict, summary_lines, debug)
        bundle ready for ``api.update_mix_inverter_setting('mix_ac_charge_time_period')``.

        Returns (params, summary, mains_enabled, stop_soc, charge_pct, periods)
        where summary is a list of human-readable lines for the confirmation
        dialog and periods is the resolved 3-period structure that we'll send.
        """
        slot_starts = plan['slot_starts']
        actions = plan['result']['actions']
        cap = plan['capacity']

        chg_windows = collapse_grid_charge_to_periods(slot_starts, actions, max_periods=3)

        # Split each window at midnight so it fits Growatt's daily HH:MM
        # schedule, then keep the largest 3 if we end up with more.
        split_periods = []  # list of (st_time, en_time, kwh)
        for st, en, kwh in chg_windows:
            segments = self._split_window_at_midnight(st, en)
            if not segments:
                continue
            # Apportion kWh by minute-share so the “largest” pick later is sane.
            total_min = sum(
                ((e.hour * 60 + e.minute) - (s.hour * 60 + s.minute)) % (24 * 60) or (24 * 60)
                for s, e in segments
            )
            for s, e in segments:
                seg_min = ((e.hour * 60 + e.minute) - (s.hour * 60 + s.minute)) % (24 * 60)
                if seg_min == 0:
                    seg_min = 24 * 60
                share = (seg_min / total_min) if total_min > 0 else 0.0
                split_periods.append((s, e, kwh * share))

        if len(split_periods) > 3:
            split_periods.sort(key=lambda r: r[2], reverse=True)
            split_periods = split_periods[:3]
            split_periods.sort(key=lambda r: (r[0].hour, r[0].minute))

        # Stop-SOC: use the peak SOC reached during any grid-charge slot in
        # the plan, rounded UP to the nearest 5%, clamped to [10, 100]. If
        # no grid-charge is planned we fall back to a safe 10% (and disable
        # the schedule via mains_enabled=False).
        chg_indices = []
        for st, en, _kwh in chg_windows:
            for i, t in enumerate(slot_starts):
                ts = pd.Timestamp(t)
                if st <= ts < en:
                    chg_indices.append(i)
        if chg_indices and cap > 0:
            peak_soc_kwh = max(actions[i]['soc_after_kwh'] for i in chg_indices)
            stop_pct = peak_soc_kwh / cap * 100.0
            stop_soc = int(min(100, max(10, ((int(stop_pct + 0.999) + 4) // 5) * 5)))
        else:
            stop_soc = 10

        mains_enabled = bool(split_periods)
        charge_pct = int(self.sp_inv_charge_power.value())

        # Pad to exactly 3 periods (disabled padding ones).
        periods = []
        for s, e in [(p[0], p[1]) for p in split_periods]:
            periods.append({'start_time': s, 'end_time': e, 'enabled': True})
        while len(periods) < 3:
            periods.append({
                'start_time': time(0, 0),
                'end_time': time(0, 0),
                'enabled': False,
            })

        params = _mix_ac_charge_api_params(charge_pct, stop_soc, mains_enabled, periods)

        summary = []
        if mains_enabled:
            summary.append(f"Charge power : {charge_pct} %")
            summary.append(f"Stop SOC     : {stop_soc} %  (peak in plan rounded up to nearest 5 %)")
            summary.append("AC charging  : ENABLED")
            summary.append("")
            summary.append("Daily-recurring grid-charge windows:")
            for i, p in enumerate(periods, start=1):
                if p['enabled']:
                    summary.append(
                        f"  {i}. {p['start_time'].strftime('%H:%M')}–"
                        f"{p['end_time'].strftime('%H:%M')}"
                    )
                else:
                    summary.append(f"  {i}. (disabled)")
        else:
            summary.append("Plan calls for NO grid-charging in this horizon.")
            summary.append("")
            summary.append("This will write three DISABLED periods and set")
            summary.append("mains_enabled = OFF, so the inverter will not run")
            summary.append("a previous day's schedule.")
            summary.append(f"Charge power and stop-SOC kept at {charge_pct} % / {stop_soc} %")
            summary.append("for when scheduling is later re-enabled.")

        return params, summary, mains_enabled, stop_soc, charge_pct, periods

    def _build_inverter_discharge_payload_from_plan(self, plan):
        """Convert a plan's ``batt_to_grid`` runs into a (params, summary,
        any_periods, stop_soc, discharge_pct, periods) bundle ready for
        ``api.update_mix_inverter_setting('mix_ac_discharge_time_period')``.

        The DP flag ``allow_battery_export`` upstream guarantees actions only
        contain ``batt_to_grid > 0`` runs when the user has explicitly opted
        in. ``stop_soc`` (the discharge floor) is set to the smaller of:

          * ``_PLAN_EXPORT_MIN_SOC`` (the planner's hard export floor)
          * the lowest SOC the plan ACTUALLY visits during any export slot,
            rounded DOWN to the nearest 5 % (so the inverter's SOC quantisation
            doesn't make it stop one slot early).

        Raises ``ValueError`` if no export windows are present (caller must
        check ``has_export`` on the plan before calling this).
        """
        slot_starts = plan['slot_starts']
        actions = plan['result']['actions']
        cap = plan['capacity']

        exp_windows = collapse_grid_export_runs(slot_starts, actions)
        if not exp_windows:
            raise ValueError("plan contains no battery-export windows")

        split_periods = []
        for st, en, kwh in exp_windows:
            segments = self._split_window_at_midnight(st, en)
            if not segments:
                continue
            total_min = sum(
                ((e.hour * 60 + e.minute) - (s.hour * 60 + s.minute)) % (24 * 60) or (24 * 60)
                for s, e in segments
            )
            for s, e in segments:
                seg_min = ((e.hour * 60 + e.minute) - (s.hour * 60 + s.minute)) % (24 * 60)
                if seg_min == 0:
                    seg_min = 24 * 60
                share = (seg_min / total_min) if total_min > 0 else 0.0
                split_periods.append((s, e, kwh * share))

        if len(split_periods) > 3:
            split_periods.sort(key=lambda r: r[2], reverse=True)
            split_periods = split_periods[:3]
            split_periods.sort(key=lambda r: (r[0].hour, r[0].minute))

        # Discharge floor: lowest SOC visited during any export slot, rounded
        # DOWN to nearest 5 %. Clamped to [_PLAN_EXPORT_MIN_SOC, 100] so we
        # never go below the planner's hard floor.
        exp_indices = []
        for st, en, _kwh in exp_windows:
            for i, t in enumerate(slot_starts):
                ts = pd.Timestamp(t)
                if st <= ts < en:
                    exp_indices.append(i)
        if exp_indices and cap > 0:
            min_soc_kwh = min(actions[i]['soc_after_kwh'] for i in exp_indices)
            min_pct = min_soc_kwh / cap * 100.0
            stop_soc = int(max(_PLAN_EXPORT_MIN_SOC, (int(min_pct) // 5) * 5))
            stop_soc = min(100, stop_soc)
        else:
            stop_soc = int(_PLAN_EXPORT_MIN_SOC)

        discharge_pct = int(self.sp_inv_discharge_power.value())

        periods = []
        for s, e in [(p[0], p[1]) for p in split_periods]:
            periods.append({'start_time': s, 'end_time': e, 'enabled': True})
        while len(periods) < 3:
            periods.append({
                'start_time': time(0, 0),
                'end_time': time(0, 0),
                'enabled': False,
            })

        params = _mix_ac_discharge_api_params(discharge_pct, stop_soc, periods)

        any_periods = any(p['enabled'] for p in periods)
        summary = []
        if any_periods:
            summary.append(f"Discharge power : {discharge_pct} %")
            summary.append(f"Stop-SOC floor  : {stop_soc} %  (battery won't discharge below this)")
            summary.append("")
            summary.append("Daily-recurring forced-discharge windows:")
            for i, p in enumerate(periods, start=1):
                if p['enabled']:
                    summary.append(
                        f"  {i}. {p['start_time'].strftime('%H:%M')}–"
                        f"{p['end_time'].strftime('%H:%M')}"
                    )
                else:
                    summary.append(f"  {i}. (disabled)")
        else:
            # Defensive: shouldn't happen because we raised above, but keep a
            # safe path so the caller never sends garbage.
            summary.append("No export windows in plan — would write 3 disabled periods.")

        return params, summary, any_periods, stop_soc, discharge_pct, periods

    # ---- Snapshot parsing (raw cloud dict → structured AC charge state) ----

    @staticmethod
    def _parse_ac_charge_from_settings(raw):
        """Decode an AC charge schedule from the response of
        ``api.get_mix_inverter_settings(sn)`` (which calls ``getMixSetParams``).
        Field names used by that endpoint are documented in
        growattServer.open_api_v1.devices.sph.read_ac_charge_times:

        * ``chargePowerCommand``        — charge power %
        * ``wchargeSOCLowLimit``        — stop charging at this SOC %
        * ``acChargeEnable``            — 0/1 mains-charge master switch
        * ``forcedChargeTimeStart{i}``  — "H:M" string, i in 1..3
        * ``forcedChargeTimeStop{i}``   — "H:M" string
        * ``forcedChargeStopSwitch{i}`` — 0/1 per-period enable

        Returns a dict with charge_power, stop_soc, mains_enabled, periods
        (each period: ``{'start_time': time, 'end_time': time, 'enabled': bool}``)
        OR ``None`` if the response can't be parsed (unexpected shape, missing
        all the expected fields, etc.). Designed to fail silently rather than
        raise so the snapshot path never blocks on shape surprises."""
        sentinels = ('acChargeEnable', 'chargePowerCommand', 'wchargeSOCLowLimit',
                     'forcedChargeTimeStart1', 'forcedChargeStopSwitch1')
        sentinel_l = {k.lower() for k in sentinels}

        def _unwrap_settings_obj(blob, depth=0):
            if not isinstance(blob, dict) or depth > 4:
                return None
            keys_l = {str(k).lower() for k in blob}
            if keys_l & sentinel_l:
                return blob
            for key in ('obj', 'data', 'result'):
                inner = blob.get(key)
                if inner is None:
                    inner = next(
                        (blob[k] for k in blob if str(k).lower() == key),
                        None,
                    )
                found = _unwrap_settings_obj(inner, depth + 1)
                if found is not None:
                    return found
            return None

        obj = _unwrap_settings_obj(raw if isinstance(raw, dict) else None)
        if not isinstance(obj, dict):
            return None

        lower = {str(k).lower(): v for k, v in obj.items()}

        def _get(name, default=None):
            if name in obj:
                return obj[name]
            return lower.get(name.lower(), default)

        def _to_int(v, default):
            if v is None or v == '' or v == 'null':
                return default
            try:
                return int(v)
            except (TypeError, ValueError):
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    return default

        def _parse_hm(s):
            if s is None or s == '' or s == 'null':
                return time(0, 0)
            try:
                hh, mm = str(s).split(':')[:2]
                hh = max(0, min(23, int(hh)))
                mm = max(0, min(59, int(mm)))
                return time(hh, mm)
            except Exception:
                return time(0, 0)

        charge_power = max(0, min(100, _to_int(_get('chargePowerCommand'), 0)))
        stop_soc = max(0, min(100, _to_int(_get('wchargeSOCLowLimit'), 100)))
        mains_enabled = _to_int(_get('acChargeEnable'), 0) == 1

        periods = []
        for i in range(1, 4):
            st = _parse_hm(_get(f'forcedChargeTimeStart{i}', '0:0'))
            en = _parse_hm(_get(f'forcedChargeTimeStop{i}', '0:0'))
            en_bit = _to_int(_get(f'forcedChargeStopSwitch{i}'), 0) == 1
            periods.append({'start_time': st, 'end_time': en, 'enabled': en_bit})

        return {
            'charge_power': charge_power,
            'stop_soc': stop_soc,
            'mains_enabled': mains_enabled,
            'periods': periods,
        }

    @staticmethod
    def _ac_state_to_params(ac):
        """Convert a parsed AC charge state (from _parse_ac_charge_from_settings)
        back into the paramN dict used by ``update_mix_inverter_setting``."""
        return _mix_ac_charge_api_params(
            ac['charge_power'],
            ac['stop_soc'],
            ac['mains_enabled'],
            ac['periods'],
        )

    @staticmethod
    def _safe_disable_params(charge_power=100, stop_soc=10):
        """Panic-stop payload: 3 disabled periods, mains_enabled OFF.
        Guarantees the inverter will not run a grid-charge schedule until the
        next deliberate write."""
        periods = [{'start_time': time(0, 0), 'end_time': time(0, 0),
                    'enabled': False} for _ in range(3)]
        return _mix_ac_charge_api_params(charge_power, stop_soc, False, periods)

    @staticmethod
    def _format_ac_state(ac):
        """Render a parsed AC charge state for display in the confirm dialog."""
        if ac is None:
            return "  (could not decode prior schedule from snapshot)"
        lines = [
            f"  Charge power : {ac['charge_power']} %",
            f"  Stop SOC     : {ac['stop_soc']} %",
            f"  AC charging  : {'ENABLED' if ac['mains_enabled'] else 'disabled'}",
            "  Periods      :",
        ]
        for i, p in enumerate(ac['periods'], start=1):
            tag = 'enabled' if p['enabled'] else 'disabled'
            lines.append(
                f"    {i}. {p['start_time'].strftime('%H:%M')}–"
                f"{p['end_time'].strftime('%H:%M')}  ({tag})"
            )
        return "\n".join(lines)

    @staticmethod
    def _ac_state_matches_params(ac, params, tolerance_min=2):
        """Return (matches: bool, mismatches: list[str]) comparing a parsed
        AC charge state against the paramN dict we sent. tolerance_min handles
        the case where the cloud rounds HH:MM in flight."""
        if ac is None:
            return False, ["could not parse read-back response"]
        mismatches = []
        try:
            exp_power = int(params['param1'])
            exp_stop = int(params['param2'])
            exp_mains = params['param3'] == '1'
        except Exception as e:
            return False, [f"could not parse expected params: {e}"]

        if ac['charge_power'] != exp_power:
            mismatches.append(
                f"charge_power: read {ac['charge_power']}, expected {exp_power}")
        if ac['stop_soc'] != exp_stop:
            mismatches.append(
                f"stop_soc: read {ac['stop_soc']}, expected {exp_stop}")
        if ac['mains_enabled'] != exp_mains:
            mismatches.append(
                f"mains_enabled: read {ac['mains_enabled']}, expected {exp_mains}")

        for i in range(3):
            base = i * 5 + 4
            try:
                exp_st = time(int(params[f'param{base}']),
                              int(params[f'param{base + 1}']))
                exp_en = time(int(params[f'param{base + 2}']),
                              int(params[f'param{base + 3}']))
                exp_on = params[f'param{base + 4}'] == '1'
            except Exception as e:
                mismatches.append(f"period {i+1}: could not parse expected: {e}")
                continue
            got = ac['periods'][i]
            if got['enabled'] != exp_on:
                mismatches.append(
                    f"period {i+1} enable: read {got['enabled']}, expected {exp_on}")
            if exp_on:
                def _delta(a, b):
                    return abs((a.hour * 60 + a.minute) - (b.hour * 60 + b.minute))
                if _delta(got['start_time'], exp_st) > tolerance_min:
                    mismatches.append(
                        f"period {i+1} start: read "
                        f"{got['start_time'].strftime('%H:%M')}, expected "
                        f"{exp_st.strftime('%H:%M')}")
                if _delta(got['end_time'], exp_en) > tolerance_min:
                    mismatches.append(
                        f"period {i+1} end: read "
                        f"{got['end_time'].strftime('%H:%M')}, expected "
                        f"{exp_en.strftime('%H:%M')}")
        return (len(mismatches) == 0), mismatches

    # ---- Discharge schedule helpers (parallel to AC-charge above) ---------
    #
    # Mirror the AC-charge snapshot/format/match helpers but for the
    # ``mix_ac_discharge_time_period`` setting type. Critical layout differences
    # vs AC-charge:
    #   * No global "discharge enable" master switch on the wire; period offsets
    #     therefore start at param3 (not param4).
    #   * Read-back fields are ``disChargePowerCommand`` / ``wdisChargeSOCLowLimit``
    #     and ``forcedDischarge*`` instead of ``acChargeEnable`` /
    #     ``chargePowerCommand`` / ``forcedCharge*``.
    #   * ``stop_soc`` is a FLOOR (stop discharging at this %), not a ceiling.
    # See growattServer/open_api_v1/devices/sph.py for reference.

    @staticmethod
    def _parse_ac_discharge_from_settings(raw):
        """Decode an AC discharge schedule from the response of
        ``api.get_mix_inverter_settings(sn)``. Returns the same shape as
        ``_parse_ac_charge_from_settings`` but with ``discharge_power`` /
        ``discharge_stop_soc`` keys (and no ``mains_enabled`` — discharge has
        no master switch, only per-period enable bits)."""
        if not isinstance(raw, dict):
            return None
        obj = raw.get('obj', raw) if isinstance(raw, dict) else None
        if not isinstance(obj, dict):
            return None

        def _to_int(v, default):
            if v is None or v == '' or v == 'null':
                return default
            try:
                return int(v)
            except (TypeError, ValueError):
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    return default

        def _parse_hm(s):
            if s is None or s == '' or s == 'null':
                return time(0, 0)
            try:
                hh, mm = str(s).split(':')[:2]
                hh = max(0, min(23, int(hh)))
                mm = max(0, min(59, int(mm)))
                return time(hh, mm)
            except Exception:
                return time(0, 0)

        sentinels = ('disChargePowerCommand', 'wdisChargeSOCLowLimit',
                     'forcedDischargeTimeStart1', 'forcedDischargeStopSwitch1')
        if not any(k in obj for k in sentinels):
            return None

        discharge_power = max(0, min(100, _to_int(obj.get('disChargePowerCommand'), 0)))
        discharge_stop_soc = max(0, min(100, _to_int(obj.get('wdisChargeSOCLowLimit'), 10)))

        periods = []
        for i in range(1, 4):
            st = _parse_hm(obj.get(f'forcedDischargeTimeStart{i}', '0:0'))
            en = _parse_hm(obj.get(f'forcedDischargeTimeStop{i}', '0:0'))
            en_bit = _to_int(obj.get(f'forcedDischargeStopSwitch{i}'), 0) == 1
            periods.append({'start_time': st, 'end_time': en, 'enabled': en_bit})

        return {
            'discharge_power': discharge_power,
            'discharge_stop_soc': discharge_stop_soc,
            'periods': periods,
        }

    @staticmethod
    def _ac_discharge_state_to_params(ac):
        return _mix_ac_discharge_api_params(
            ac['discharge_power'],
            ac['discharge_stop_soc'],
            ac['periods'],
        )

    @staticmethod
    def _safe_disable_discharge_params(discharge_power=100, discharge_stop_soc=100):
        """Panic-stop payload for the discharge schedule: 3 disabled periods
        and a 100 % stop-SOC floor (so even if a stale enable bit lingered the
        inverter would refuse to discharge below 100 %, i.e. never)."""
        periods = [{'start_time': time(0, 0), 'end_time': time(0, 0),
                    'enabled': False} for _ in range(3)]
        return _mix_ac_discharge_api_params(discharge_power, discharge_stop_soc, periods)

    @staticmethod
    def _format_ac_discharge_state(ac):
        if ac is None:
            return "  (could not decode prior discharge schedule from snapshot)"
        lines = [
            f"  Discharge power : {ac['discharge_power']} %",
            f"  Stop-SOC floor  : {ac['discharge_stop_soc']} %",
            "  Periods         :",
        ]
        for i, p in enumerate(ac['periods'], start=1):
            tag = 'enabled' if p['enabled'] else 'disabled'
            lines.append(
                f"    {i}. {p['start_time'].strftime('%H:%M')}–"
                f"{p['end_time'].strftime('%H:%M')}  ({tag})"
            )
        return "\n".join(lines)

    @staticmethod
    def _ac_discharge_state_matches_params(ac, params, tolerance_min=2):
        """Compare a parsed discharge state to the paramN dict we sent."""
        if ac is None:
            return False, ["could not parse read-back response"]
        mismatches = []
        try:
            exp_power = int(params['param1'])
            exp_stop = int(params['param2'])
        except Exception as e:
            return False, [f"could not parse expected params: {e}"]

        if ac['discharge_power'] != exp_power:
            mismatches.append(
                f"discharge_power: read {ac['discharge_power']}, expected {exp_power}")
        if ac['discharge_stop_soc'] != exp_stop:
            mismatches.append(
                f"discharge_stop_soc: read {ac['discharge_stop_soc']}, expected {exp_stop}")

        for i in range(3):
            base = i * 5 + 3
            try:
                exp_st = time(int(params[f'param{base}']),
                              int(params[f'param{base + 1}']))
                exp_en = time(int(params[f'param{base + 2}']),
                              int(params[f'param{base + 3}']))
                exp_on = params[f'param{base + 4}'] == '1'
            except Exception as e:
                mismatches.append(f"period {i+1}: could not parse expected: {e}")
                continue
            got = ac['periods'][i]
            if got['enabled'] != exp_on:
                mismatches.append(
                    f"period {i+1} enable: read {got['enabled']}, expected {exp_on}")
            if exp_on:
                def _delta(a, b):
                    return abs((a.hour * 60 + a.minute) - (b.hour * 60 + b.minute))
                if _delta(got['start_time'], exp_st) > tolerance_min:
                    mismatches.append(
                        f"period {i+1} start: read "
                        f"{got['start_time'].strftime('%H:%M')}, expected "
                        f"{exp_st.strftime('%H:%M')}")
                if _delta(got['end_time'], exp_en) > tolerance_min:
                    mismatches.append(
                        f"period {i+1} end: read "
                        f"{got['end_time'].strftime('%H:%M')}, expected "
                        f"{exp_en.strftime('%H:%M')}")
        return (len(mismatches) == 0), mismatches

    # ---- Confirmation dialog -----------------------------------------------

    @staticmethod
    def _param_explainer_rows(params, kind):
        """Return a structured per-param explainer for the paramN dict that
        will be sent on the wire, suitable for display in a QTreeWidget.

        ``kind`` is 'charge' (for ``mix_ac_charge_time_period``, param1..18,
        with a global mains-enable at param3) or 'discharge' (for
        ``mix_ac_discharge_time_period``, param1..17, no mains-enable).

        Returns a list of section dicts, each:
            {'title': str,             # e.g. 'Period 1 — 08:30 → 09:00, ENABLED'
             'rows':  [(name, value, hint), ...]}

        The rows mirror the exact wire layout one-for-one so the user can
        cross-check the JSON tab. Names are 'paramN', values are the raw
        strings as sent, hints are short English explanations.
        """
        def _g(k):
            v = params.get(k)
            return "" if v is None else str(v)

        def _bool_hint(v, on='ENABLED', off='DISABLED'):
            return on if str(v).strip() in ('1', 'true', 'True') else off

        sections = []
        if kind == 'charge':
            # Global params 1..3
            sections.append({
                'title': 'Master settings',
                'rows': [
                    ('param1', _g('param1'),
                     'Charge power — % of the inverter\'s rated AC charge rate '
                     '(100 = full rate, 50 = half rate). Higher = faster charge '
                     'but can stress the AC supply.'),
                    ('param2', _g('param2'),
                     'Stop SOC % — charging stops automatically when the battery '
                     'reaches this state of charge, even if the time-window is '
                     'still active.'),
                    ('param3', _g('param3'),
                     f'AC-charge master enable — {_bool_hint(_g("param3"))}. '
                     'Global on/off switch for grid charging. When 0, NO grid '
                     'charging happens regardless of the per-period enable bits.'),
                ],
            })
            # Three periods, 5 params each, starting at param4/9/14
            for i in range(3):
                base = 4 + i * 5
                sh, sm, eh, em, en = (_g(f'param{base + k}') for k in range(5))
                try:
                    sh_i, sm_i, eh_i, em_i = int(sh), int(sm), int(eh), int(em)
                    win_str = f'{sh_i:02d}:{sm_i:02d} → {eh_i:02d}:{em_i:02d}'
                except Exception:
                    win_str = f'{sh}:{sm} → {eh}:{em}'
                en_lbl = _bool_hint(en)
                title = f'Period {i + 1} — {win_str}, {en_lbl}'
                if en_lbl == 'DISABLED':
                    title += ' (won\'t fire)'
                sections.append({
                    'title': title,
                    'rows': [
                        (f'param{base}',     sh, f'Period {i + 1} start hour (0–23, local time)'),
                        (f'param{base + 1}', sm, f'Period {i + 1} start minute (0–59)'),
                        (f'param{base + 2}', eh, f'Period {i + 1} end hour (0–23, local time)'),
                        (f'param{base + 3}', em, f'Period {i + 1} end minute (0–59)'),
                        (f'param{base + 4}', en,
                         f'Period {i + 1} per-period enable — {en_lbl}. '
                         f'Both the master switch (param3) AND this bit must be '
                         f'1 for this window to actually fire.'),
                    ],
                })
        elif kind == 'discharge':
            sections.append({
                'title': 'Master settings (no global enable bit)',
                'rows': [
                    ('param1', _g('param1'),
                     'Discharge power — % of the inverter\'s rated AC discharge rate. '
                     '100 = full rate (typical for forced-export windows).'),
                    ('param2', _g('param2'),
                     'Discharge stop SOC % — battery floor. Discharge halts when '
                     'SOC drops to this value, protecting the battery from over-'
                     'depletion. Set to 100 to safely disable discharge entirely.'),
                ],
            })
            # Three periods, 5 params each, starting at param3/8/13
            # (note the offset is param3 not param4 — discharge has no
            # mains-enable master bit, unlike charge)
            for i in range(3):
                base = 3 + i * 5
                sh, sm, eh, em, en = (_g(f'param{base + k}') for k in range(5))
                try:
                    sh_i, sm_i, eh_i, em_i = int(sh), int(sm), int(eh), int(em)
                    win_str = f'{sh_i:02d}:{sm_i:02d} → {eh_i:02d}:{em_i:02d}'
                except Exception:
                    win_str = f'{sh}:{sm} → {eh}:{em}'
                en_lbl = _bool_hint(en)
                title = f'Period {i + 1} — {win_str}, {en_lbl}'
                if en_lbl == 'DISABLED':
                    title += ' (won\'t fire)'
                sections.append({
                    'title': title,
                    'rows': [
                        (f'param{base}',     sh, f'Period {i + 1} start hour (0–23, local time)'),
                        (f'param{base + 1}', sm, f'Period {i + 1} start minute (0–59)'),
                        (f'param{base + 2}', eh, f'Period {i + 1} end hour (0–23, local time)'),
                        (f'param{base + 3}', em, f'Period {i + 1} end minute (0–59)'),
                        (f'param{base + 4}', en,
                         f'Period {i + 1} per-period enable — {en_lbl}. '
                         f'Discharge has no global master bit; this per-period '
                         f'flag alone gates whether the window fires.'),
                    ],
                })
        else:
            sections.append({
                'title': 'Raw parameters',
                'rows': [(k, str(v), '') for k, v in sorted(params.items())],
            })
        return sections

    def _show_writeback_confirmation(self, *, title, body_html, params, kind,
                                     warning=True):
        """Custom resizable confirmation dialog used for both AC charge and
        AC discharge writeback flows. Replaces the old fixed-size QMessageBox.

        Layout:
          ┌── Title bar (resizable, with size grip) ─────────────────┐
          │  ┌── QSplitter (vertical, user-draggable) ──────────────┐ │
          │  │   Top pane: scrollable QTextBrowser (body_html)      │ │
          │  ├──── handle (drag up/down) ───────────────────────────┤ │
          │  │   Bottom pane: QTabWidget                            │ │
          │  │     • Parameter explainer (QTreeWidget, grouped)     │ │
          │  │     • Raw JSON (QTextEdit, monospace)                │ │
          │  └──────────────────────────────────────────────────────┘ │
          │  [✓ Yes]  [✗ No]                                         │
          └──────────────────────────────────────────────────────────┘

        Returns True if the user pressed Yes, False otherwise.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setSizeGripEnabled(True)
        dlg.setModal(True)
        dlg.resize(960, 820)
        dlg.setMinimumSize(720, 480)
        dlg.setStyleSheet(
            f"QDialog {{ background: {_DARK_SURFACE_BG}; }}"
            "QLabel, QTextBrowser, QTextEdit, QTreeWidget { color: #cdd6f4; }"
        )

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        # Optional warning banner so the elevated-risk discharge flow stands out.
        if warning:
            banner = QLabel(
                "<span style='color:#fab387; font-weight:bold;'>⚠ Elevated-risk "
                "writeback</span> — read the body text and parameter explainer "
                "below carefully before pressing Yes."
            )
            banner.setTextFormat(Qt.RichText)
            banner.setWordWrap(True)
            banner.setStyleSheet(
                "background: #45341e; border: 1px solid #fab387;"
                " border-radius: 4px; padding: 6px 8px;"
            )
            outer.addWidget(banner)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #313244; }"
            "QSplitter::handle:hover { background: #45475a; }"
            "QSplitter::handle:vertical { height: 6px; }"
        )

        # ── Top pane: scrollable rich-text body ──
        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        body.setHtml(body_html)
        body.setStyleSheet(
            "QTextBrowser { background: #2a2a3c; border: 1px solid #45475a;"
            " border-radius: 6px; padding: 8px; }"
        )
        splitter.addWidget(body)

        # ── Bottom pane: tabbed parameter explainer + raw JSON ──
        tabs = QTabWidget()
        tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #313244; background: #1e1e2e;"
            " border-radius: 4px; }"
            "QTabBar::tab { background: #313244; color: #cdd6f4; padding: 4px 12px;"
            " border: 1px solid #45475a; border-bottom: none;"
            " border-top-left-radius: 4px; border-top-right-radius: 4px; }"
            "QTabBar::tab:selected { background: #45475a; }"
        )

        # Tab 1: parameter explainer tree (grouped by section)
        tree = QTreeWidget()
        tree.setColumnCount(3)
        tree.setHeaderLabels(["Parameter", "Value", "Meaning"])
        tree.setAlternatingRowColors(True)
        tree.setRootIsDecorated(True)
        tree.setUniformRowHeights(False)
        tree.setWordWrap(True)
        tree.setStyleSheet(
            "QTreeWidget { background: #1e1e2e; border: 1px solid #45475a;"
            " border-radius: 6px; alternate-background-color: #1e1e2e; }"
            "QTreeWidget::item { padding: 3px; }"
            "QHeaderView::section { background: #45475a; color: #cdd6f4;"
            " padding: 4px; border: none; }"
        )
        sections = self._param_explainer_rows(params, kind)
        for sec in sections:
            top = QTreeWidgetItem([sec['title'], '', ''])
            top.setForeground(0, QBrush(QColor('#a6e3a1')))
            tree.addTopLevelItem(top)
            for name, value, hint in sec['rows']:
                child = QTreeWidgetItem([name, value, hint])
                child.setForeground(0, QBrush(QColor('#89b4fa')))
                child.setForeground(1, QBrush(QColor('#f9e2af')))
                top.addChild(child)
            top.setExpanded(True)
        tree.setColumnWidth(0, 110)
        tree.setColumnWidth(1, 90)
        qtree_set_column_width_key(tree, "dlg_writeback_param_explainer")
        qtree_prepare_interactive_columns(tree)
        qtree_restore_column_widths(tree, "dlg_writeback_param_explainer", resize_if_no_saved=True)
        qtree_attach_column_width_persistence(tree)
        tabs.addTab(tree, "Parameter explainer")

        # Tab 2: raw JSON
        json_view = QTextEdit()
        json_view.setReadOnly(True)
        json_view.setFont(QFont('Courier', 10))
        try:
            json_view.setPlainText(json.dumps(params, indent=2))
        except Exception:
            json_view.setPlainText(str(params))
        tabs.addTab(json_view, "Raw paramN dict (wire JSON)")

        splitter.addWidget(tabs)
        # Initial 65/35 split — top body gets more room because that's where
        # the user reads the explanation, but the user can drag the handle
        # upwards to enlarge the parameter explainer / JSON pane as far as
        # the body's minimum allows.
        splitter.setSizes([520, 280])
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, 1)

        # ── Buttons ──
        btns = QDialogButtonBox(QDialogButtonBox.Yes | QDialogButtonBox.No)
        btns.button(QDialogButtonBox.No).setDefault(True)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        outer.addWidget(btns)

        _prepare_dialog_buttons(dlg)
        return dlg.exec() == QDialog.Accepted

    def _build_confirm_dialog_html(self, summary, params, mains_enabled, sn):
        """Compose the rich-text body for the pre-write confirmation dialog."""
        plan_block = "\n".join(summary)
        try:
            param_block = json.dumps(params, indent=2)
        except Exception:
            param_block = str(params)

        snap_block = self._format_ac_state(self._pre_write_ac)
        snap_ts = (self._pre_write_ts.strftime('%H:%M:%S')
                   if self._pre_write_ts else "—")
        snap_parsed = self._pre_write_ac is not None

        if mains_enabled:
            behaviour = (
                "<li>During each <b>enabled</b> window above the inverter will draw "
                "from the grid to charge the battery, up to the charge-power % of "
                "its rated charge rate.</li>"
                "<li>Charging stops automatically when the battery reaches the "
                "stop-SOC, even if the window is still open.</li>"
                "<li>Outside the windows the inverter behaves normally — PV → "
                "battery → load → grid as configured by your other settings.</li>"
                "<li>This schedule is <b>daily-recurring</b>: the inverter has no "
                "concept of \"tomorrow only\". It will repeat every day, including "
                "weekends, until you write again or rollback.</li>"
            )
        else:
            behaviour = (
                "<li>All three periods will be marked <b>disabled</b> and the "
                "AC-charging master switch will be turned <b>OFF</b>.</li>"
                "<li>The inverter will not perform any scheduled grid-charging "
                "until you re-enable it (via this dashboard, ShinePhone, or "
                "your installer's tool).</li>"
                "<li>Solar charging, self-consumption and any discharge schedule "
                "are unaffected.</li>"
            )

        rollback_text = (
            "<li><b>Snapshot captured</b>: at {ts}, before any write — see "
            "\"Prior schedule on the inverter\" below.</li>"
            "<li><b>Auto-verify</b>: ~3 s after the write the dashboard reads the "
            "schedule back and compares field-by-field.</li>"
            "<li><b>Auto-rollback</b>: if the read-back does NOT match what we sent "
            "(within a 2-minute tolerance on times) the dashboard will "
            "{rollback_target} and report it.</li>"
            "<li><b>Manual rollback</b>: a \"Rollback last write\" button stays "
            "active and will {rollback_target_manual} when pressed.</li>"
            "<li><b>If the cloud is unreachable</b> after the write: read-back "
            "fails → status goes amber → no auto action; you can manually "
            "rollback or wait and verify later.</li>"
        ).format(
            ts=snap_ts,
            rollback_target=(
                "automatically restore the snapshot above"
                if snap_parsed else
                "automatically panic-stop to safe-disable (no grid charging)"
            ),
            rollback_target_manual=(
                "restore the snapshot above"
                if snap_parsed else
                "panic-stop to safe-disable (no grid charging)"
            ),
        )

        risks = (
            "<li><b>Wrong window times</b> can buy electricity at peak rates "
            "instead of cheap-rate windows. The plan is based on Agile rates and "
            "Forecast.Solar predictions — both can be wrong.</li>"
            "<li><b>Schedule overwrite</b>: the inverter only stores ONE AC "
            "charge schedule. This will replace anything set previously in "
            "ShinePhone or by your installer.</li>"
            "<li><b>Daily recurrence</b>: the optimiser plan is for the next "
            "24–48 h, but the inverter will replay these times every day until "
            "you change it.</li>"
            "<li><b>Forecast risk</b>: if tomorrow's solar is much higher than "
            "forecast, money spent grid-charging tonight is wasted.</li>"
            "<li><b>Cycle wear</b>: every grid-charge cycle is a battery cycle. "
            "Excessive scheduling shortens battery life slightly.</li>"
            "<li><b>Cloud latency</b>: writes go through the Growatt cloud and "
            "may take 30–90 s to fully propagate to the inverter. The dashboard "
            "waits 3 s before verify, which catches most cases but not all.</li>"
            "<li><b>Warranty</b>: changing inverter settings programmatically may "
            "be outside the scope of your installer's warranty. This software "
            "comes with no warranty (PolyForm Noncommercial 1.0.0 — see License "
            "tab).</li>"
        )

        return (
            f"<h3 style='margin:0 0 6px 0;'>Send AC charge schedule to "
            f"<code>{sn}</code>?</h3>"
            f"<p style='margin:0 0 4px 0;'><b>API call</b>: "
            f"<code>update_mix_inverter_setting(serial_number, "
            f"\"mix_ac_charge_time_period\", params)</code></p>"

            f"<p style='margin:8px 0 2px 0;'><b>What will be sent</b> "
            f"(decoded from the optimiser plan):</p>"
            f"<pre style='margin:0;background:#1e1e2e;padding:6px;'>"
            f"{plan_block}</pre>"

            f"<p style='margin:8px 0 2px 0;'><b>What the inverter will do</b>:</p>"
            f"<ul style='margin:0 0 0 18px;'>{behaviour}</ul>"

            f"<p style='margin:8px 0 2px 0;'><b>Prior schedule on the "
            f"inverter</b> (snapshot taken {snap_ts}):</p>"
            f"<pre style='margin:0;background:#1e1e2e;padding:6px;'>"
            f"{snap_block}</pre>"

            f"<p style='margin:8px 0 2px 0;'><b>Rollback plan</b>:</p>"
            f"<ul style='margin:0 0 0 18px;'>{rollback_text}</ul>"

            f"<p style='margin:8px 0 2px 0;'><b>Risks &amp; caveats</b>:</p>"
            f"<ul style='margin:0 0 0 18px;'>{risks}</ul>"

            f"<p style='margin:8px 0 0 0;color:#a6adc8;'>Click <b>Show "
            f"Details</b> below for the raw paramN dict that goes on the "
            f"wire.</p>"
        )

    # ---- Pre-write entry point --------------------------------------------

    def _write_plan_to_inverter(self):
        if self._last_plan is None:
            QMessageBox.information(
                self, "No plan",
                "Build a plan first — there's nothing to send to the inverter yet.",
            )
            return
        from energy_dashboard.tabs.shadow_trial import confirm_despite_shadow_trial
        if not confirm_despite_shadow_trial(self, "AC charge schedule"):
            return
        api, _plant_id, sn = self.growatt_tab.get_api()
        if api is None or not sn:
            QMessageBox.warning(
                self, "Not connected to Growatt",
                "Open the Growatt Live Status tab and connect first — the "
                "Optimiser needs the cloud API + device serial to write the "
                "schedule.",
            )
            return
        try:
            payload = self._build_inverter_payload_from_plan(self._last_plan)
        except Exception as e:
            QMessageBox.critical(
                self, "Could not build payload",
                f"Failed to assemble inverter parameters from the current plan:\n\n{e}",
            )
            return

        # Snapshot first — we refuse to write without an audit trail / rollback
        # source. Done synchronously here because we need the snapshot in the
        # confirmation dialog. UI is briefly held; for a typical Growatt
        # response (~1-3 s) this is preferable to dispatching the user through
        # an extra modal step.
        self.write_inverter_btn.setEnabled(False)
        self.inv_write_status.setText("Reading current inverter schedule for snapshot…")
        self.inv_write_status.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        QApplication.processEvents()
        try:
            raw_snap = api.get_mix_inverter_settings(sn)
        except Exception as e:
            self.write_inverter_btn.setEnabled(True)
            self.inv_write_status.setText(
                f"Snapshot failed — write aborted ({str(e)[:80]})")
            self.inv_write_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
            QMessageBox.critical(
                self, "Snapshot failed — nothing written",
                "Could not read the current inverter schedule. The write was "
                "aborted to ensure we always have a rollback source.\n\n"
                f"Error:\n{e}",
            )
            return

        self._pre_write_raw = raw_snap
        self._pre_write_ac = self._parse_ac_charge_from_settings(raw_snap)
        self._pre_write_ts = datetime.now()
        if self._pre_write_ac is not None:
            try:
                self._pre_write_params = self._ac_state_to_params(self._pre_write_ac)
            except Exception:
                self._pre_write_params = None
        else:
            self._pre_write_params = None

        params, summary, mains_enabled, _stop_soc, _charge_pct, _periods = payload

        body = self._build_confirm_dialog_html(summary, params, mains_enabled, sn)

        accepted = self._show_writeback_confirmation(
            title="Confirm inverter writeback",
            body_html=body,
            params=params,
            kind='charge',
            warning=bool(mains_enabled),
        )
        if not accepted:
            self.write_inverter_btn.setEnabled(True)
            self.inv_write_status.setText("Write cancelled — snapshot retained.")
            self.inv_write_status.setStyleSheet("color: #a6adc8; font-size: 11px;")
            return

        self.inv_write_status.setText("Writing schedule…")
        self.inv_write_status.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        self.set_status("Optimiser → inverter: writing AC charge schedule…")
        threading.Thread(
            target=self._write_workflow_thread,
            args=(api, sn, params),
            daemon=True,
        ).start()

    # ---- Worker thread: write → settle → verify ---------------------------

    def _write_workflow_thread(self, api, sn, params):
        # Step 1: write
        try:
            write_resp = api.update_mix_inverter_setting(
                sn, "mix_ac_charge_time_period", params)
        except Exception as e:
            self._inv.invoke(lambda err=str(e):
                             self._after_write(api, sn, params, None, err, None, None))
            return

        # Step 2: settle (let the cloud propagate to the device)
        _time_mod.sleep(3.0)

        # Step 3: verify by re-reading
        verify_err = None
        verify_raw = None
        verify_ac = None
        try:
            verify_raw = api.get_mix_inverter_settings(sn)
            verify_ac = self._parse_ac_charge_from_settings(verify_raw)
        except Exception as e:
            verify_err = str(e)

        self._inv.invoke(lambda:
                         self._after_write(api, sn, params, write_resp, None,
                                           verify_ac, verify_err))

    # ---- Result handler (GUI thread) --------------------------------------

    def _after_write(self, api, sn, params, write_resp, write_err,
                     verify_ac, verify_err):
        ts = datetime.now().strftime('%H:%M:%S')
        self.write_inverter_btn.setEnabled(True)
        self._last_write_params = params

        # Case A: write threw — state is presumed unchanged on the inverter.
        if write_err:
            self.inv_write_status.setText(f"Write FAILED at {ts}: {write_err[:100]}")
            self.inv_write_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
            self.set_status(f"Optimiser → inverter write FAILED: {write_err}")
            QMessageBox.critical(
                self, "Inverter write failed",
                "The Growatt cloud rejected the request. The inverter schedule "
                "should be unchanged from the snapshot taken just before. No "
                "rollback is being performed.\n\n"
                f"Error:\n{write_err}",
            )
            self.rollback_inverter_btn.setEnabled(self._pre_write_params is not None)
            return

        write_ok_flag = not (isinstance(write_resp, dict)
                             and write_resp.get('success') is False)

        # Case B: cloud explicitly returned success=False — likely rejected,
        # state likely unchanged.
        if not write_ok_flag:
            try:
                detail = json.dumps(write_resp, indent=2, default=str)
            except Exception:
                detail = str(write_resp)
            self.inv_write_status.setText(
                f"Server rejected write at {ts} — see dialog")
            self.inv_write_status.setStyleSheet("color: #fab387; font-size: 11px;")
            self.set_status("Optimiser → inverter: server rejected the write.")
            QMessageBox.warning(
                self, "Inverter write — server rejected",
                "The Growatt cloud accepted the request but returned an error "
                "indication. The inverter schedule should be unchanged. No "
                "rollback is being performed.\n\n"
                f"Response:\n{detail[:2000]}",
            )
            self.rollback_inverter_btn.setEnabled(self._pre_write_params is not None)
            return

        # Case C: write seemed OK, but verification read failed — we don't
        # know the actual state. Don't auto-rollback; leave the user a manual
        # rollback button.
        if verify_err is not None:
            self.inv_write_status.setText(
                f"Write OK at {ts} — VERIFY FAILED ({verify_err[:60]})")
            self.inv_write_status.setStyleSheet("color: #fab387; font-size: 11px;")
            self.set_status(
                "Optimiser → inverter: write OK but read-back failed — verify manually.")
            QMessageBox.warning(
                self, "Write OK but verification failed",
                "The write was accepted by the Growatt cloud, but the read-back "
                "to verify the schedule actually landed on the inverter failed.\n\n"
                "The inverter <i>probably</i> has the new schedule, but we can't "
                "confirm without a successful read. The dashboard is NOT auto-"
                "rolling back, because doing so on an unknown state could make "
                "things worse.\n\n"
                "Recommended: try Smart Advisor → Read Inverter Settings in a "
                "minute. If you want to undo, press <b>Rollback last write</b>.\n\n"
                f"Verify error:\n{verify_err}",
            )
            self.rollback_inverter_btn.setEnabled(True)
            return

        # Case D: write OK, verify read OK, comparison time.
        match, mismatches = self._ac_state_matches_params(verify_ac, params)
        if match:
            self.inv_write_status.setText(
                f"Write OK at {ts} ✓ verified field-by-field")
            self.inv_write_status.setStyleSheet("color: #a6e3a1; font-size: 11px;")
            self.set_status("Optimiser → inverter: schedule written and verified.")
            self.rollback_inverter_btn.setEnabled(True)
            return

        # Case E: VERIFIED MISMATCH — auto-rollback.
        diff_block = "\n".join(f"  • {m}" for m in mismatches)
        self.inv_write_status.setText(
            f"VERIFY MISMATCH at {ts} — auto-rolling back…")
        self.inv_write_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
        self.set_status(
            "Optimiser → inverter: read-back disagreed with what we sent — auto-rollback in progress.")
        QMessageBox.warning(
            self, "Verify mismatch — auto-rollback",
            "The schedule we read back from the inverter does NOT match what we "
            "just sent. The dashboard is automatically rolling back now.\n\n"
            f"Mismatches:\n<pre>{diff_block}</pre>\n"
            f"Rollback target: <b>"
            f"{'restore prior snapshot' if self._pre_write_params else 'safe-disable (no grid charging)'}"
            f"</b>",
        )
        self._do_rollback(api, sn, reason="verify_mismatch", silent=False)

    # ---- Rollback ----------------------------------------------------------

    def _rollback_last_write(self):
        api, _plant_id, sn = self.growatt_tab.get_api()
        if api is None or not sn:
            QMessageBox.warning(
                self, "Not connected",
                "Open the Growatt Live Status tab and connect first.",
            )
            return
        if self._pre_write_params is not None:
            target = "Restore the prior schedule captured before the last write"
            target_block = self._format_ac_state(self._pre_write_ac)
            kind = "snapshot"
        else:
            target = ("Panic-stop: write 3 disabled periods + AC charging OFF "
                      "(prior snapshot couldn't be parsed, so an exact restore "
                      "isn't possible)")
            target_block = ("  3 disabled periods, mains_enabled = OFF\n"
                            "  (charge_power 100 %, stop_soc 10 % — for when "
                            "you re-enable later)")
            kind = "safe_disable"
        body = (
            f"<h3 style='margin:0 0 6px 0;'>Rollback last inverter write?</h3>"
            f"<p>{target}.</p>"
            f"<pre style='background:#1e1e2e;padding:6px;'>{target_block}</pre>"
            f"<p>This is itself a write to the inverter "
            f"(<code>mix_ac_charge_time_period</code>) and will be verified the "
            f"same way.</p>"
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Confirm rollback")
        box.setTextFormat(Qt.RichText)
        box.setText(body)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        if box.exec() != QMessageBox.Yes:
            return
        self.rollback_inverter_btn.setEnabled(False)
        self.write_inverter_btn.setEnabled(False)
        self.inv_write_status.setText(f"Rolling back ({kind})…")
        self.inv_write_status.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        self.set_status(f"Optimiser → inverter: rollback ({kind}) in progress…")
        self._do_rollback(api, sn, reason="manual", silent=False)

    def _do_rollback(self, api, sn, reason, silent=False):
        """Perform the actual rollback write in a worker thread."""
        if self._pre_write_params is not None:
            params = self._pre_write_params
            kind = "snapshot"
        else:
            params = self._safe_disable_params()
            kind = "safe_disable"
        threading.Thread(
            target=self._rollback_thread,
            args=(api, sn, params, kind, reason, silent),
            daemon=True,
        ).start()

    def _rollback_thread(self, api, sn, params, kind, reason, silent):
        try:
            resp = api.update_mix_inverter_setting(
                sn, "mix_ac_charge_time_period", params)
        except Exception as e:
            self._inv.invoke(lambda err=str(e):
                             self._after_rollback(kind, reason, None, err, None, None))
            return
        _time_mod.sleep(3.0)
        verify_err = None
        verify_ac = None
        try:
            verify_raw = api.get_mix_inverter_settings(sn)
            verify_ac = self._parse_ac_charge_from_settings(verify_raw)
        except Exception as e:
            verify_err = str(e)
        self._inv.invoke(lambda:
                         self._after_rollback(kind, reason, resp, None,
                                              verify_ac, verify_err))

    def _after_rollback(self, kind, reason, resp, err, verify_ac, verify_err):
        ts = datetime.now().strftime('%H:%M:%S')
        self.write_inverter_btn.setEnabled(True)
        if err:
            self.inv_write_status.setText(
                f"ROLLBACK FAILED at {ts} ({kind}): {err[:80]}")
            self.inv_write_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
            self.set_status(
                f"Optimiser → inverter: ROLLBACK FAILED ({kind}): {err}")
            self.rollback_inverter_btn.setEnabled(True)
            QMessageBox.critical(
                self, "Rollback failed",
                f"The rollback write itself failed. The inverter may be in an "
                f"unknown state.\n\nReason for rollback: {reason}\n"
                f"Rollback kind: {kind}\n\nError:\n{err}\n\n"
                "Please verify manually via Smart Advisor → Read Inverter "
                "Settings, or use ShinePhone.",
            )
            return
        ok_flag = not (isinstance(resp, dict) and resp.get('success') is False)
        if not ok_flag:
            self.inv_write_status.setText(
                f"Rollback rejected by server at {ts} ({kind})")
            self.inv_write_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
            self.set_status(
                f"Optimiser → inverter: rollback rejected by server ({kind}).")
            self.rollback_inverter_btn.setEnabled(True)
            QMessageBox.warning(
                self, "Rollback rejected",
                f"The Growatt cloud rejected the rollback write. The inverter "
                f"may be in an unknown state.\n\nReason for rollback: {reason}\n"
                f"Rollback kind: {kind}\n\nResponse:\n"
                f"{json.dumps(resp, indent=2, default=str)[:1500]}",
            )
            return

        # Verify rollback landed.
        if verify_err is None and verify_ac is not None:
            match, mismatches = self._ac_state_matches_params(
                verify_ac, self._pre_write_params if kind == "snapshot"
                else self._safe_disable_params())
            if match:
                self.inv_write_status.setText(
                    f"Rollback OK at {ts} ({kind}) ✓ verified")
                self.inv_write_status.setStyleSheet(
                    "color: #a6e3a1; font-size: 11px;")
                self.set_status(
                    f"Optimiser → inverter: rollback complete and verified ({kind}).")
                # After a successful rollback, disable the button — there's
                # nothing left to roll back to.
                self.rollback_inverter_btn.setEnabled(False)
                self._pre_write_params = None
                return
            diff = "\n".join(f"  • {m}" for m in mismatches)
            self.inv_write_status.setText(
                f"Rollback verify MISMATCH at {ts} ({kind})")
            self.inv_write_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
            self.set_status(
                f"Optimiser → inverter: rollback verification mismatch ({kind}).")
            self.rollback_inverter_btn.setEnabled(True)
            QMessageBox.warning(
                self, "Rollback verify mismatch",
                "The rollback was accepted but the read-back doesn't match what "
                "we asked for. Inverter state is uncertain — please verify "
                f"manually.\n\nReason for rollback: {reason}\nKind: {kind}\n\n"
                f"<pre>{diff}</pre>",
            )
            return

        self.inv_write_status.setText(
            f"Rollback sent at {ts} ({kind}) — verify failed, check manually")
        self.inv_write_status.setStyleSheet("color: #fab387; font-size: 11px;")
        self.set_status(
            f"Optimiser → inverter: rollback sent ({kind}); verification could not be read.")
        self.rollback_inverter_btn.setEnabled(True)

    # ============================================================
    # Forced-discharge writeback (mix_ac_discharge_time_period)
    # Mirrors the AC-charge writeback above. Snapshot → confirm →
    # write → settle → verify → auto-rollback on mismatch.
    # ============================================================

    def _write_discharge_to_inverter(self):
        if self._last_plan is None:
            QMessageBox.information(
                self, "No plan",
                "Build a plan first — there's nothing to send to the inverter yet.",
            )
            return
        from energy_dashboard.tabs.shadow_trial import confirm_despite_shadow_trial
        if not confirm_despite_shadow_trial(self, "forced-discharge schedule"):
            return
        if not self.cb_allow_export.isChecked():
            QMessageBox.warning(
                self, "Battery export disabled",
                "Enable “Allow battery export” first. The DP only plans "
                "battery→grid windows when this is on, and the discharge "
                "writeback is gated by it as a safety belt.",
            )
            return
        api, _plant_id, sn = self.growatt_tab.get_api()
        if api is None or not sn:
            QMessageBox.warning(
                self, "Not connected to Growatt",
                "Open the Growatt Live Status tab and connect first.",
            )
            return
        try:
            payload = self._build_inverter_discharge_payload_from_plan(self._last_plan)
        except ValueError as e:
            QMessageBox.information(
                self, "No export windows",
                f"This plan has no battery→grid windows to write.\n\n{e}",
            )
            return
        except Exception as e:
            QMessageBox.critical(
                self, "Could not build discharge payload",
                f"Failed to assemble inverter parameters from the current plan:\n\n{e}",
            )
            return

        # Snapshot the current discharge schedule first — refuse to write
        # without a rollback source. Same pattern as the charge writeback.
        self.write_discharge_btn.setEnabled(False)
        self.inv_discharge_status.setText("Reading current inverter discharge schedule for snapshot…")
        self.inv_discharge_status.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        QApplication.processEvents()
        try:
            raw_snap = api.get_mix_inverter_settings(sn)
        except Exception as e:
            self.write_discharge_btn.setEnabled(True)
            self.inv_discharge_status.setText(
                f"Snapshot failed — write aborted ({str(e)[:80]})")
            self.inv_discharge_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
            QMessageBox.critical(
                self, "Snapshot failed — nothing written",
                "Could not read the current inverter schedule. The discharge "
                "write was aborted to ensure we always have a rollback source."
                f"\n\nError:\n{e}",
            )
            return

        self._pre_write_discharge_raw = raw_snap
        self._pre_write_discharge_ac = self._parse_ac_discharge_from_settings(raw_snap)
        self._pre_write_discharge_ts = datetime.now()
        if self._pre_write_discharge_ac is not None:
            try:
                self._pre_write_discharge_params = self._ac_discharge_state_to_params(
                    self._pre_write_discharge_ac)
            except Exception:
                self._pre_write_discharge_params = None
        else:
            self._pre_write_discharge_params = None

        params, summary, any_periods, _stop_soc, _pct, _periods = payload
        body = self._build_discharge_confirm_dialog_html(summary, params, any_periods, sn)

        accepted = self._show_writeback_confirmation(
            title="Confirm forced-discharge writeback",
            body_html=body,
            params=params,
            kind='discharge',
            warning=True,  # discharge → grid is always elevated risk
        )
        if not accepted:
            self.write_discharge_btn.setEnabled(True)
            self.inv_discharge_status.setText("Write cancelled — snapshot retained.")
            self.inv_discharge_status.setStyleSheet("color: #a6adc8; font-size: 11px;")
            return

        self.inv_discharge_status.setText("Writing discharge schedule…")
        self.inv_discharge_status.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        self.set_status("Optimiser → inverter: writing forced-discharge schedule…")
        threading.Thread(
            target=self._discharge_write_workflow_thread,
            args=(api, sn, params),
            daemon=True,
        ).start()

    def _build_discharge_confirm_dialog_html(self, summary, params, any_periods, sn):
        plan_block = "\n".join(summary)
        snap_block = self._format_ac_discharge_state(self._pre_write_discharge_ac)
        snap_ts = (self._pre_write_discharge_ts.strftime('%H:%M:%S')
                   if self._pre_write_discharge_ts else "—")
        snap_parsed = self._pre_write_discharge_ac is not None

        if any_periods:
            behaviour = (
                "<li>During each <b>enabled</b> window above the inverter will "
                "<b>force-discharge the battery into the grid</b>, at the "
                "discharge-power % of its rated rate.</li>"
                "<li>Discharge stops automatically when the battery drops to the "
                "stop-SOC floor.</li>"
                "<li>Outside the windows the inverter behaves normally.</li>"
                "<li>This schedule is <b>daily-recurring</b>: it will repeat "
                "every day, including weekends, until you write again or rollback.</li>"
            )
        else:
            behaviour = (
                "<li>All three periods will be marked <b>disabled</b>.</li>"
                "<li>The inverter will not perform any scheduled forced-discharge.</li>"
            )

        rollback_text = (
            "<li><b>Snapshot captured</b>: at {ts}, before any write.</li>"
            "<li><b>Auto-verify</b>: ~3 s after the write the dashboard reads the "
            "schedule back and compares field-by-field.</li>"
            "<li><b>Auto-rollback</b>: if the read-back does NOT match what we sent "
            "(within a 2-minute tolerance on times) the dashboard will "
            "{rollback_target} and report it.</li>"
            "<li><b>Manual rollback</b>: a \"Rollback last export write\" button "
            "stays active and will {rollback_target_manual} when pressed.</li>"
        ).format(
            ts=snap_ts,
            rollback_target=(
                "automatically restore the snapshot above"
                if snap_parsed else
                "automatically panic-stop to safe-disable (no forced discharge)"
            ),
            rollback_target_manual=(
                "restore the snapshot above"
                if snap_parsed else
                "panic-stop to safe-disable (no forced discharge)"
            ),
        )

        risks = (
            "<li><b>Selling at the wrong time</b> can dump your battery into the "
            "grid at a low export rate. The plan is based on Agile rates which "
            "can move; verify the windows look sensible before pressing Yes.</li>"
            "<li><b>Stop-SOC floor matters</b>: if it's too low you may discharge "
            "the battery further than you intended for evening self-consumption.</li>"
            "<li><b>Schedule overwrite</b>: this replaces any existing forced-"
            "discharge schedule set in ShinePhone or by your installer.</li>"
            "<li><b>Daily recurrence</b>: the plan covers 24–48 h, but the "
            "inverter will replay these times every day until you change it.</li>"
            "<li><b>Cycle wear</b>: every forced-discharge cycle counts.</li>"
            "<li><b>Cloud latency</b>: writes go through the Growatt cloud and "
            "may take 30–90 s to propagate. The dashboard waits 3 s before "
            "verify, which catches most cases but not all.</li>"
            "<li><b>Warranty</b>: changing inverter settings programmatically may "
            "be outside the scope of your installer's warranty.</li>"
        )

        return (
            f"<h3 style='margin:0 0 6px 0;'>Send forced-discharge schedule to "
            f"<code>{sn}</code>?</h3>"
            f"<p style='margin:0 0 4px 0;'><b>API call</b>: "
            f"<code>update_mix_inverter_setting(serial_number, "
            f"\"mix_ac_discharge_time_period\", params)</code></p>"

            f"<p style='margin:8px 0 2px 0;'><b>What will be sent</b>:</p>"
            f"<pre style='margin:0;background:#1e1e2e;padding:6px;'>"
            f"{plan_block}</pre>"

            f"<p style='margin:8px 0 2px 0;'><b>What the inverter will do</b>:</p>"
            f"<ul style='margin:0 0 0 18px;'>{behaviour}</ul>"

            f"<p style='margin:8px 0 2px 0;'><b>Prior discharge schedule on the "
            f"inverter</b> (snapshot taken {snap_ts}):</p>"
            f"<pre style='margin:0;background:#1e1e2e;padding:6px;'>"
            f"{snap_block}</pre>"

            f"<p style='margin:8px 0 2px 0;'><b>Rollback plan</b>:</p>"
            f"<ul style='margin:0 0 0 18px;'>{rollback_text}</ul>"

            f"<p style='margin:8px 0 2px 0;'><b>Risks &amp; caveats</b>:</p>"
            f"<ul style='margin:0 0 0 18px;'>{risks}</ul>"
        )

    def _discharge_write_workflow_thread(self, api, sn, params):
        try:
            write_resp = api.update_mix_inverter_setting(
                sn, "mix_ac_discharge_time_period", params)
        except Exception as e:
            self._inv.invoke(lambda err=str(e):
                             self._after_discharge_write(api, sn, params, None, err, None, None))
            return
        _time_mod.sleep(3.0)
        verify_err = None
        verify_ac = None
        try:
            verify_raw = api.get_mix_inverter_settings(sn)
            verify_ac = self._parse_ac_discharge_from_settings(verify_raw)
        except Exception as e:
            verify_err = str(e)
        self._inv.invoke(lambda:
                         self._after_discharge_write(api, sn, params, write_resp, None,
                                                     verify_ac, verify_err))

    def _after_discharge_write(self, api, sn, params, write_resp, write_err,
                               verify_ac, verify_err):
        ts = datetime.now().strftime('%H:%M:%S')
        self.write_discharge_btn.setEnabled(True)
        self._last_discharge_write_params = params

        if write_err:
            self.inv_discharge_status.setText(
                f"Write FAILED at {ts}: {write_err[:100]}")
            self.inv_discharge_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
            self.set_status(
                f"Optimiser → inverter (discharge) write FAILED: {write_err}")
            QMessageBox.critical(
                self, "Discharge write failed",
                "The Growatt cloud rejected the request. The inverter discharge "
                "schedule should be unchanged from the snapshot. No rollback is "
                f"being performed.\n\nError:\n{write_err}",
            )
            self.rollback_discharge_btn.setEnabled(
                self._pre_write_discharge_params is not None)
            return

        write_ok_flag = not (isinstance(write_resp, dict)
                             and write_resp.get('success') is False)
        if not write_ok_flag:
            try:
                detail = json.dumps(write_resp, indent=2, default=str)
            except Exception:
                detail = str(write_resp)
            self.inv_discharge_status.setText(
                f"Server rejected write at {ts} — see dialog")
            self.inv_discharge_status.setStyleSheet("color: #fab387; font-size: 11px;")
            self.set_status("Optimiser → inverter (discharge): server rejected the write.")
            QMessageBox.warning(
                self, "Discharge write — server rejected",
                "The Growatt cloud accepted the request but returned an error "
                "indication. The inverter schedule should be unchanged. No "
                f"rollback is being performed.\n\nResponse:\n{detail[:2000]}",
            )
            self.rollback_discharge_btn.setEnabled(
                self._pre_write_discharge_params is not None)
            return

        if verify_err is not None:
            self.inv_discharge_status.setText(
                f"Write OK at {ts} — VERIFY FAILED ({verify_err[:60]})")
            self.inv_discharge_status.setStyleSheet("color: #fab387; font-size: 11px;")
            self.set_status(
                "Optimiser → inverter (discharge): write OK but read-back failed — verify manually.")
            QMessageBox.warning(
                self, "Discharge write OK but verification failed",
                "The write was accepted by the Growatt cloud, but the read-back "
                "to verify the schedule actually landed failed.\n\n"
                "The inverter <i>probably</i> has the new discharge schedule, "
                "but we can't confirm. The dashboard is NOT auto-rolling back "
                "on an unknown state. If you want to undo, press <b>Rollback "
                "last export write</b>.\n\n"
                f"Verify error:\n{verify_err}",
            )
            self.rollback_discharge_btn.setEnabled(True)
            return

        match, mismatches = self._ac_discharge_state_matches_params(verify_ac, params)
        if match:
            self.inv_discharge_status.setText(
                f"Write OK at {ts} ✓ verified field-by-field")
            self.inv_discharge_status.setStyleSheet("color: #a6e3a1; font-size: 11px;")
            self.set_status(
                "Optimiser → inverter (discharge): schedule written and verified.")
            self.rollback_discharge_btn.setEnabled(True)
            return

        diff_block = "\n".join(f"  • {m}" for m in mismatches)
        self.inv_discharge_status.setText(
            f"VERIFY MISMATCH at {ts} — auto-rolling back…")
        self.inv_discharge_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
        self.set_status(
            "Optimiser → inverter (discharge): read-back disagreed — auto-rollback in progress.")
        QMessageBox.warning(
            self, "Discharge verify mismatch — auto-rollback",
            "The discharge schedule we read back from the inverter does NOT "
            "match what we just sent. The dashboard is automatically rolling "
            f"back now.\n\nMismatches:\n<pre>{diff_block}</pre>\n"
            f"Rollback target: <b>"
            f"{'restore prior snapshot' if self._pre_write_discharge_params else 'safe-disable (no forced discharge)'}"
            f"</b>",
        )
        self._do_discharge_rollback(api, sn, reason="verify_mismatch", silent=False)

    def _rollback_last_discharge_write(self):
        api, _plant_id, sn = self.growatt_tab.get_api()
        if api is None or not sn:
            QMessageBox.warning(
                self, "Not connected",
                "Open the Growatt Live Status tab and connect first.",
            )
            return
        if self._pre_write_discharge_params is not None:
            target = "Restore the prior discharge schedule captured before the last write"
            target_block = self._format_ac_discharge_state(self._pre_write_discharge_ac)
            kind = "snapshot"
        else:
            target = ("Panic-stop: write 3 disabled periods + 100 % stop-SOC "
                      "floor (prior snapshot couldn't be parsed, so an exact "
                      "restore isn't possible)")
            target_block = ("  3 disabled periods, stop_soc = 100 %\n"
                            "  (discharge_power 100 % — for when you re-enable later)")
            kind = "safe_disable"
        body = (
            f"<h3 style='margin:0 0 6px 0;'>Rollback last discharge write?</h3>"
            f"<p>{target}.</p>"
            f"<pre style='background:#1e1e2e;padding:6px;'>{target_block}</pre>"
            f"<p>This is itself a write to the inverter "
            f"(<code>mix_ac_discharge_time_period</code>) and will be verified "
            f"the same way.</p>"
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Confirm discharge rollback")
        box.setTextFormat(Qt.RichText)
        box.setText(body)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        if box.exec() != QMessageBox.Yes:
            return
        self.rollback_discharge_btn.setEnabled(False)
        self.write_discharge_btn.setEnabled(False)
        self.inv_discharge_status.setText(f"Rolling back ({kind})…")
        self.inv_discharge_status.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        self.set_status(f"Optimiser → inverter (discharge): rollback ({kind}) in progress…")
        self._do_discharge_rollback(api, sn, reason="manual", silent=False)

    def _do_discharge_rollback(self, api, sn, reason, silent=False):
        if self._pre_write_discharge_params is not None:
            params = self._pre_write_discharge_params
            kind = "snapshot"
        else:
            params = self._safe_disable_discharge_params()
            kind = "safe_disable"
        threading.Thread(
            target=self._discharge_rollback_thread,
            args=(api, sn, params, kind, reason, silent),
            daemon=True,
        ).start()

    def _discharge_rollback_thread(self, api, sn, params, kind, reason, silent):
        try:
            resp = api.update_mix_inverter_setting(
                sn, "mix_ac_discharge_time_period", params)
        except Exception as e:
            self._inv.invoke(lambda err=str(e):
                             self._after_discharge_rollback(kind, reason, None, err, None, None))
            return
        _time_mod.sleep(3.0)
        verify_err = None
        verify_ac = None
        try:
            verify_raw = api.get_mix_inverter_settings(sn)
            verify_ac = self._parse_ac_discharge_from_settings(verify_raw)
        except Exception as e:
            verify_err = str(e)
        self._inv.invoke(lambda:
                         self._after_discharge_rollback(kind, reason, resp, None,
                                                        verify_ac, verify_err))

    def _after_discharge_rollback(self, kind, reason, resp, err, verify_ac, verify_err):
        ts = datetime.now().strftime('%H:%M:%S')
        self.write_discharge_btn.setEnabled(True)
        if err:
            self.inv_discharge_status.setText(
                f"ROLLBACK FAILED at {ts} ({kind}): {err[:80]}")
            self.inv_discharge_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
            self.set_status(
                f"Optimiser → inverter (discharge): ROLLBACK FAILED ({kind}): {err}")
            self.rollback_discharge_btn.setEnabled(True)
            QMessageBox.critical(
                self, "Discharge rollback failed",
                f"The rollback write itself failed. The inverter may be in an "
                f"unknown state.\n\nReason for rollback: {reason}\n"
                f"Rollback kind: {kind}\n\nError:\n{err}\n\n"
                "Please verify manually via Smart Advisor → Read Inverter "
                "Settings, or use ShinePhone.",
            )
            return
        ok_flag = not (isinstance(resp, dict) and resp.get('success') is False)
        if not ok_flag:
            self.inv_discharge_status.setText(
                f"Rollback rejected by server at {ts} ({kind})")
            self.inv_discharge_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
            self.set_status(
                f"Optimiser → inverter (discharge): rollback rejected by server ({kind}).")
            self.rollback_discharge_btn.setEnabled(True)
            QMessageBox.warning(
                self, "Discharge rollback rejected",
                f"The Growatt cloud rejected the rollback write. The inverter "
                f"may be in an unknown state.\n\nReason for rollback: {reason}\n"
                f"Rollback kind: {kind}\n\nResponse:\n"
                f"{json.dumps(resp, indent=2, default=str)[:1500]}",
            )
            return

        if verify_err is None and verify_ac is not None:
            match, mismatches = self._ac_discharge_state_matches_params(
                verify_ac, self._pre_write_discharge_params if kind == "snapshot"
                else self._safe_disable_discharge_params())
            if match:
                self.inv_discharge_status.setText(
                    f"Rollback OK at {ts} ({kind}) ✓ verified")
                self.inv_discharge_status.setStyleSheet(
                    "color: #a6e3a1; font-size: 11px;")
                self.set_status(
                    f"Optimiser → inverter (discharge): rollback complete and verified ({kind}).")
                self.rollback_discharge_btn.setEnabled(False)
                self._pre_write_discharge_params = None
                return
            diff = "\n".join(f"  • {m}" for m in mismatches)
            self.inv_discharge_status.setText(
                f"Rollback verify MISMATCH at {ts} ({kind})")
            self.inv_discharge_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
            self.set_status(
                f"Optimiser → inverter (discharge): rollback verification mismatch ({kind}).")
            self.rollback_discharge_btn.setEnabled(True)
            QMessageBox.warning(
                self, "Discharge rollback verify mismatch",
                "The rollback was accepted but the read-back doesn't match what "
                "we asked for. Inverter state is uncertain — please verify "
                f"manually.\n\nReason for rollback: {reason}\nKind: {kind}\n\n"
                f"<pre>{diff}</pre>",
            )
            return

        self.inv_discharge_status.setText(
            f"Rollback sent at {ts} ({kind}) — verify failed, check manually")
        self.inv_discharge_status.setStyleSheet("color: #fab387; font-size: 11px;")
        self.set_status(
            f"Optimiser → inverter (discharge): rollback sent ({kind}); verification could not be read.")
        self.rollback_discharge_btn.setEnabled(True)

    def _render_action_card(self, plan):
        slot_starts = plan['slot_starts']
        actions = plan['result']['actions']
        p_in = plan['p_in']
        p_ex = plan['p_ex']
        cap = plan['capacity']

        net_cost_p = sum(a['slot_cost_p'] for a in actions)
        delta = plan['baseline_cost_p'] - net_cost_p

        self.action_title.setText(
            f"Plan total: £{net_cost_p / 100.0:.2f}   "
            f"(SOC now {plan['soc_now']:.0f}% · saves £{delta / 100.0:.2f} vs naive overnight)"
        )

        chg_windows = collapse_grid_charge_to_periods(slot_starts, actions, max_periods=3)
        if not chg_windows:
            self.action_overnight.setText(
                "Charge from grid: not needed — solar forecast covers the next solar window."
            )
        else:
            parts = []
            total_cost_p = 0.0
            for st, en, kwh in chg_windows:
                avg_p_list = [p_in[i] for i, t in enumerate(slot_starts)
                              if pd.Timestamp(t) >= st and pd.Timestamp(t) < en]
                avg_p = float(np.mean(avg_p_list)) if avg_p_list else 0.0
                cost_p = kwh * avg_p
                total_cost_p += cost_p
                parts.append(f"{self._fmt_window(st, en)} ({kwh:.1f} kWh @ {avg_p:.1f}p)")
            peak_pct = (max(a['soc_after_kwh'] for a in actions) / cap) * 100.0
            self.action_overnight.setText(
                "Charge from grid: " + ", ".join(parts)
                + f"   ⇒ peak SOC ≈ {peak_pct:.0f}%, est £{total_cost_p / 100.0:.2f}"
            )

        exp_windows = collapse_grid_export_runs(slot_starts, actions)
        if not exp_windows:
            self.action_export.setText(
                "Export to grid: none (no slot beats the export margin)."
            )
        else:
            parts = []
            total_credit_p = 0.0
            for st, en, kwh in exp_windows:
                wp = [p_ex[i] for i, t in enumerate(slot_starts)
                      if pd.Timestamp(t) >= st and pd.Timestamp(t) < en]
                avg_pe = float(np.mean(wp)) if wp else 0.0
                credit_p = kwh * avg_pe
                total_credit_p += credit_p
                parts.append(f"{self._fmt_window(st, en)} (≈ {kwh:.1f} kWh @ {avg_pe:.1f}p)")
            self.action_export.setText(
                "Export to grid: " + "; ".join(parts)
                + f"   ⇒ est £{total_credit_p / 100.0:.2f} credit"
            )

        heater = plan['heater']
        h_parts = []
        for a, b in heater['morning_blocks']:
            st = pd.Timestamp(slot_starts[a])
            en = pd.Timestamp(slot_starts[b - 1]) + pd.Timedelta(minutes=30)
            h_parts.append(f"pre-7am {self._fmt_window(st, en)}")
        for a, b in heater['day_blocks']:
            st = pd.Timestamp(slot_starts[a])
            en = pd.Timestamp(slot_starts[b - 1]) + pd.Timedelta(minutes=30)
            covered = sum(min(plan['heater_kw'] * 0.5, plan['solar_kwh'][k])
                          for k in range(a, b))
            total_h = (b - a) * plan['heater_kw'] * 0.5
            pct_solar = (covered / total_h * 100.0) if total_h > 0 else 0.0
            h_parts.append(
                f"4 h block {self._fmt_window(st, en)} "
                f"(solar covers {pct_solar:.0f}%)"
            )
        if h_parts:
            self.action_heater.setText("Hot water: " + "; ".join(h_parts))
        else:
            self.action_heater.setText("Hot water: no windows in this horizon.")

    def _render_chart(self, plan):
        ax_top = self.ax_top
        ax_bot = self.ax_bot
        ax_soc = self.ax_soc
        ax_top.clear()
        ax_bot.clear()
        ax_soc.clear()
        for ax in (ax_top, ax_bot, ax_soc):
            _style_ax_dark(ax, self.fig)
        ax_soc.set_facecolor((0, 0, 0, 0))

        # ── Visual polish helpers (scoped to this chart) ─────────────────
        # Soft, cohesive Catppuccin-Mocha palette with a darker-edged stack
        # so adjacent bar segments separate cleanly without harsh outlines.
        BAR_EDGE = _DARK_BG          # near-black hairline between stacked bars
        BAR_LW = 0.4
        BAR_ALPHA = 0.92
        SOC_COLOR = '#fab387'        # warm orange — pops against the cool stack
        SOC_GLOW = '#fab387'
        IMPORT_COLOR = '#f38ba8'
        EXPORT_COLOR = '#a6e3a1'

        def _polish(ax):
            """Hide top/right spines and soften the others — gives the panel
            a lighter, more 'editorial' feel without changing layout."""
            for side in ('top', 'right'):
                ax.spines[side].set_visible(False)
                ax.spines[side].set_linewidth(0)
            for side in ('left', 'bottom'):
                ax.spines[side].set_color('#45475a')
                ax.spines[side].set_linewidth(0.8)

        slot_starts_plan = plan['slot_starts']
        actions_plan = plan['result']['actions']
        soc_trace_plan = list(plan['result']['soc_pct_trace'])
        heater_kwh_plan = plan['heater']['heater_kwh']
        cp = plan.get('chart_past')

        import matplotlib.dates as mdates
        import pytz
        london = pytz.timezone('Europe/London')
        now_py = datetime.now(london)

        if cp is not None and int(cp.get('n_past', 0)) > 0:
            n_past = int(cp['n_past'])
            past_ss = cp['slot_starts']
            slot_starts = pd.DatetimeIndex(list(past_ss) + list(slot_starts_plan))
            actions = list(cp['actions']) + list(actions_plan)
            p_in_full = np.concatenate([
                np.asarray(cp['p_in'], dtype=float),
                np.asarray(plan['p_in'], dtype=float),
            ])
            p_ex_full = np.concatenate([
                np.asarray(cp['p_ex'], dtype=float),
                np.asarray(plan['p_ex'], dtype=float),
            ])
            solar_full = np.concatenate([
                np.asarray(cp['solar_kwh'], dtype=float),
                np.asarray(plan['solar_kwh'], dtype=float),
            ])
            load_full = np.concatenate([
                np.asarray(cp['load_kwh'], dtype=float),
                np.asarray(plan['load_kwh'], dtype=float),
            ])
            heater_kwh = np.concatenate([
                np.asarray(cp['heater_kwh'], dtype=float),
                np.asarray(heater_kwh_plan, dtype=float),
            ])
            soc0 = float(soc_trace_plan[0])
            soc_trace = [soc0] * (n_past + 1) + [float(v) for v in soc_trace_plan[1:]]
        else:
            n_past = 0
            slot_starts = slot_starts_plan
            actions = list(actions_plan)
            p_in_full = np.asarray(plan['p_in'], dtype=float)
            p_ex_full = np.asarray(plan['p_ex'], dtype=float)
            solar_full = np.asarray(plan['solar_kwh'], dtype=float)
            load_full = np.asarray(plan['load_kwh'], dtype=float)
            heater_kwh = np.asarray(heater_kwh_plan, dtype=float)
            soc_trace = soc_trace_plan

        x_dt = [pd.Timestamp(t).to_pydatetime() for t in slot_starts]
        x = mdates.date2num(x_dt)
        w = 30.0 / (24 * 60)

        bat_to_load = np.array([a['batt_to_load'] for a in actions])
        bat_to_grid = np.array([a['batt_to_grid'] for a in actions])
        grid_to_load = np.array([
            max(0.0, a['grid_in_kwh'] - a['grid_to_batt']) for a in actions
        ])
        grid_to_batt = np.array([a['grid_to_batt'] for a in actions])
        solar_to_load = np.array([a['solar_to_load'] for a in actions])
        solar_to_grid = np.array([a['solar_to_grid'] for a in actions])

        # Slim the bar slightly (0.96×) so adjacent slots breathe; the gap
        # is tiny but reads much more like a designed chart than a wall.
        bw = w * 0.96
        bx = x + (w - bw) / 2.0

        ax_top.bar(bx, solar_to_load, bw, color='#f9e2af', label='Solar→Load',
                   align='edge', alpha=BAR_ALPHA, edgecolor=BAR_EDGE,
                   linewidth=BAR_LW, zorder=3)
        ax_top.bar(bx, bat_to_load, bw, bottom=solar_to_load, color='#a6e3a1',
                   label='Batt→Load', align='edge', alpha=BAR_ALPHA,
                   edgecolor=BAR_EDGE, linewidth=BAR_LW, zorder=3)
        ax_top.bar(bx, grid_to_load, bw, bottom=solar_to_load + bat_to_load,
                   color='#f38ba8', label='Grid→Load', align='edge',
                   alpha=BAR_ALPHA, edgecolor=BAR_EDGE, linewidth=BAR_LW,
                   zorder=3)
        ax_top.bar(bx, heater_kwh, bw,
                   bottom=solar_to_load + bat_to_load + grid_to_load,
                   color='#74c7ec', label='Heater', align='edge', alpha=0.55,
                   edgecolor=BAR_EDGE, linewidth=BAR_LW, zorder=3)
        ax_top.bar(bx, grid_to_batt, bw,
                   bottom=solar_to_load + bat_to_load + grid_to_load + heater_kwh,
                   color='#fab387', label='Grid→Batt', align='edge',
                   alpha=BAR_ALPHA, edgecolor=BAR_EDGE, linewidth=BAR_LW,
                   zorder=3)
        ax_top.bar(bx, -solar_to_grid, bw, color='#94e2d5',
                   label='Solar→Grid', align='edge', alpha=BAR_ALPHA,
                   edgecolor=BAR_EDGE, linewidth=BAR_LW, zorder=3)
        ax_top.bar(bx, -bat_to_grid, bw, bottom=-solar_to_grid,
                   color='#cba6f7', label='Batt→Grid', align='edge',
                   alpha=BAR_ALPHA, edgecolor=BAR_EDGE, linewidth=BAR_LW,
                   zorder=3)

        soc_x = mdates.date2num(
            [pd.Timestamp(slot_starts[0]).to_pydatetime()] +
            [(pd.Timestamp(t) + pd.Timedelta(minutes=30)).to_pydatetime()
             for t in slot_starts]
        )
        now_x = mdates.date2num(now_py)
        # Soft halo behind the SOC line — a wider, low-alpha pass first,
        # then the crisp foreground line on top. Cheap "glow" with no extra
        # dependencies and reads beautifully on the dark backdrop.
        ax_soc.plot(soc_x, soc_trace, color=SOC_GLOW, linewidth=6.0,
                    alpha=0.16, solid_capstyle='round', zorder=4)
        ax_soc.plot(soc_x, soc_trace, color=SOC_GLOW, linewidth=3.5,
                    alpha=0.32, solid_capstyle='round', zorder=4.5)
        ax_soc.plot(soc_x, soc_trace, color=SOC_COLOR, linewidth=2.0,
                    label='SOC %', solid_capstyle='round', zorder=5)
        ax_soc.set_ylim(0, 100)
        ax_soc.set_ylabel('SOC %', color=SOC_COLOR, fontsize=10, fontweight='bold')
        ax_soc.tick_params(axis='y', colors=SOC_COLOR, labelsize=9)
        for side in ('top', 'right', 'left', 'bottom'):
            ax_soc.spines[side].set_visible(False)

        ax_top.set_ylabel('kWh / 30 min', color='#bac2de', fontsize=10)
        ax_top.set_title('Optimised dispatch plan', color='#e6ecff',
                         fontsize=13, fontweight='bold', pad=8, loc='left')
        ax_top.axhline(0, color='#6c7086', linewidth=0.7, alpha=0.7, zorder=2)
        ax_top.grid(axis='y', color='#3a3a4c', linewidth=0.6,
                    linestyle=(0, (1, 4)), alpha=0.7, zorder=0)
        leg_top = ax_top.legend(
            loc='upper left', bbox_to_anchor=(0.0, 1.0),
            fontsize=8.5, ncol=4, facecolor='#1e1e2e',
            edgecolor='#3a3a4c', labelcolor='#cdd6f4',
            framealpha=0.85, borderpad=0.6, columnspacing=1.4,
            handlelength=1.5, handleheight=0.9, handletextpad=0.6,
        )
        if leg_top is not None:
            leg_top.get_frame().set_linewidth(0.8)

        # Stepped lines + a translucent area under each makes the price
        # cadence read at a glance even on a wide axis. The areas use a
        # very low alpha so they suggest direction without dominating.
        ax_bot.fill_between(x, p_in_full, step='post',
                            color=IMPORT_COLOR, alpha=0.12, zorder=2)
        ax_bot.fill_between(x, p_ex_full, step='post',
                            color=EXPORT_COLOR, alpha=0.12, zorder=2)
        ax_bot.plot(x, p_in_full, color=IMPORT_COLOR, linewidth=1.7,
                    label='Agile import', drawstyle='steps-post',
                    solid_capstyle='round', zorder=4)
        ax_bot.plot(x, p_ex_full, color=EXPORT_COLOR, linewidth=1.7,
                    label='Agile export', drawstyle='steps-post',
                    solid_capstyle='round', zorder=4)
        ax_bot.set_ylabel('p / kWh', color='#bac2de', fontsize=10)
        ax_bot.set_title(
            'Agile import / export prices  ·  shaded blocks = chosen charge / export windows',
            color='#e6ecff', fontsize=12, fontweight='bold', pad=8, loc='left',
        )
        ax_bot.grid(axis='y', color='#3a3a4c', linewidth=0.6,
                    linestyle=(0, (1, 4)), alpha=0.7, zorder=0)
        leg_bot = ax_bot.legend(
            loc='upper left', bbox_to_anchor=(0.0, 1.0),
            fontsize=8.5, facecolor='#1e1e2e', edgecolor='#3a3a4c',
            labelcolor='#cdd6f4', framealpha=0.85, borderpad=0.6,
            handlelength=1.8, handletextpad=0.6,
        )
        if leg_bot is not None:
            leg_bot.get_frame().set_linewidth(0.8)

        for i, a in enumerate(actions):
            if a.get('grid_to_batt', 0.0) > 0.05:
                ax_bot.axvspan(x[i], x[i] + w, facecolor='#fab387', alpha=0.22,
                               edgecolor='none', zorder=1)
            if a.get('batt_to_grid', 0.0) > 0.05:
                ax_bot.axvspan(x[i], x[i] + w, facecolor='#cba6f7', alpha=0.22,
                               edgecolor='none', zorder=1)

        for a, b in plan['heater']['morning_blocks'] + plan['heater']['day_blocks']:
            ax_top.axvspan(
                x[a + n_past], x[b - 1 + n_past] + w, facecolor='#74c7ec', alpha=0.13,
                edgecolor='none', zorder=1,
            )

        _polish(ax_top)
        _polish(ax_bot)

        # Tie both the tick locator and formatter to London time so the bottom
        # axis labels sit on the same 00/06/12/18 boundaries as the dotted
        # vertical grid (which is drawn in London time). Without tz= matplotlib
        # uses UTC, which drifts by an hour during BST.
        ax_bot.xaxis_date(tz=london)
        ax_bot.xaxis.set_major_formatter(mdates.DateFormatter('%a %H:%M', tz=london))
        ax_bot.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 6, 12, 18], tz=london))
        # Half-step hours — same strftime as majors, fainter colour, second label row.
        ax_bot.xaxis.set_minor_locator(
            mdates.HourLocator(byhour=[3, 9, 15, 21], tz=london)
        )
        ax_bot.xaxis.set_minor_formatter(
            mdates.DateFormatter('%a %H:%M', tz=london)
        )
        x_right = float(x[-1] + w)
        if n_past > 0:
            x_left = mdates.date2num(now_py - timedelta(hours=_OPTIMISER_CHART_PAST_HOURS))
            ax_top.set_xlim(x_left, x_right)

        _draw_6h_vertical_grid(ax_top, london, force_intraday_secondary=True)
        _draw_6h_vertical_grid(ax_bot, london, force_intraday_secondary=True)
        _maj_pad, _min_pad = 6, 22
        # Time labels under the dispatch chart (top panel); price panel has no x labels.
        ax_top.tick_params(
            axis='x', which='major', labelbottom=True, pad=_maj_pad, labelsize=9,
            length=5, width=0.9, colors='#ffffff', labelcolor='#ffffff',
        )
        ax_top.tick_params(
            axis='x', which='minor', labelbottom=True, pad=_min_pad, labelsize=9,
            length=0, colors='#ffffff', labelcolor='#ffffff',
        )
        ax_bot.tick_params(axis='x', which='both', labelbottom=False)
        for label in ax_top.get_xticklabels():
            label.set_rotation(30)
            label.set_ha('right')
            label.set_color('#ffffff')
        for label in ax_top.xaxis.get_minorticklabels():
            label.set_rotation(30)
            label.set_ha('right')
            label.set_color('#ffffff')
        _draw_day_date_labels(ax_top, london, label_color='#ffffff')

        NOW_LINE_COLOR = '#89dceb'
        # Draw the clock line *below* the matplotlib legends (legend zorder ≈ 5)
        # so it does not streak through legend text/patches.
        NOW_LINE_Z = 4
        for ax_now in (ax_top, ax_bot):
            ax_now.axvline(
                now_x, color=NOW_LINE_COLOR, linewidth=2.0, alpha=0.95,
                zorder=NOW_LINE_Z, clip_on=True,
            )

        # “Now” like a tick label: below the bottom axis, same rotation/anchor as times.
        from matplotlib.transforms import blended_transform_factory
        trans_bot = blended_transform_factory(ax_bot.transData, ax_bot.transAxes)
        ax_bot.annotate(
            'Now',
            xy=(now_x, 0.0),
            xycoords=trans_bot,
            xytext=(0, -(_min_pad + 18)),
            textcoords='offset points',
            ha='right',
            va='top',
            rotation=30,
            fontsize=9,
            fontweight='bold',
            color=NOW_LINE_COLOR,
            zorder=7,
            annotation_clip=False,
        )

        # Cache lookup arrays for the crosshair hover.
        self._opt_xnum = x.copy()
        self._opt_x_end = x_right
        self._opt_x_start = float(mdates.date2num(
            now_py - timedelta(hours=_OPTIMISER_CHART_PAST_HOURS)
        )) if n_past > 0 else float(x[0])
        self._opt_p_in = np.asarray(p_in_full, dtype=float)
        self._opt_p_ex = np.asarray(p_ex_full, dtype=float)
        self._opt_solar = np.asarray(solar_full, dtype=float)
        self._opt_load = np.asarray(load_full, dtype=float)
        self._opt_heater = np.asarray(heater_kwh, dtype=float)
        self._opt_soc_pct = np.asarray(soc_trace, dtype=float)
        self._opt_soc_xnum = np.asarray(soc_x, dtype=float)
        self._opt_slot_starts = list(slot_starts)

        # (Re)create crosshair line artists — replaces any from a previous render.
        self._opt_vline_top = ax_top.axvline(x[0], color='#94e2d5', lw=1.05, alpha=0.92,
                                             visible=False, zorder=60)
        self._opt_hline_top = ax_top.axhline(0, color='#94e2d5', lw=1.0, alpha=0.88,
                                             visible=False, zorder=59)
        self._opt_vline_bot = ax_bot.axvline(x[0], color='#94e2d5', lw=1.05, alpha=0.92,
                                             visible=False, zorder=60)
        self._opt_hline_bot = ax_bot.axhline(0, color='#94e2d5', lw=1.0, alpha=0.88,
                                             visible=False, zorder=59)
        self._opt_cursor_lines = (
            self._opt_vline_top, self._opt_hline_top,
            self._opt_vline_bot, self._opt_hline_bot,
        )

        ax_top.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
            xv, yv, tz, "kWh / 30 min",
            "stacked energy dispatch — above 0 = load-related, below 0 = export to grid",
        )
        ax_bot.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
            xv, yv, tz, "p/kWh",
            "Agile import (pink) and export (green) prices; shading = charge/discharge windows",
        )
        ax_soc.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
            xv, yv, tz, "% SOC",
            "optimiser battery state of charge along the plan",
        )

        # Late pass: twinx/sharex can reset tick colours to black or theme blue.
        ax_top.tick_params(
            axis='x', labelbottom=True, colors='#ffffff', labelcolor='#ffffff',
        )
        ax_bot.tick_params(axis='x', labelbottom=False)
        for label in ax_top.get_xticklabels(which='both'):
            label.set_color('#ffffff')
        for label in ax_top.xaxis.get_minorticklabels():
            label.set_color('#ffffff')

        # subplots_adjust is set in build_ui — don't tight_layout here, it would
        # re-introduce the gap above the top chart.
        self.canvas.draw_idle()

    # ── crosshair hover ────────────────────────────────────────────────

    def _hide_chart_cursor(self):
        if not self._opt_cursor_lines:
            return
        for ln in self._opt_cursor_lines:
            ln.set_visible(False)
        self.cursor_label.setText(
            "Hover the charts: time · import · export · solar · load · heater · SOC."
        )
        self.canvas.draw_idle()

    def _on_chart_motion(self, event):
        if not self._opt_cursor_lines or self._last_plan is None:
            return
        if event.inaxes not in (self.ax_top, self.ax_bot, self.ax_soc) or event.xdata is None:
            self._hide_chart_cursor()
            return
        x = float(event.xdata)
        x_lo = float(getattr(self, '_opt_x_start', self._opt_xnum[0]))
        if x < x_lo or x > self._opt_x_end:
            self._hide_chart_cursor()
            return
        # Vertical crosshair on both subplots.
        self._opt_vline_top.set_xdata([x, x])
        self._opt_vline_bot.set_xdata([x, x])
        self._opt_vline_top.set_visible(True)
        self._opt_vline_bot.set_visible(True)
        # Horizontal crosshair only on the chart we're over.
        if event.inaxes in (self.ax_top, self.ax_soc) and event.ydata is not None:
            self._opt_hline_top.set_ydata([float(event.ydata), float(event.ydata)])
            self._opt_hline_top.set_visible(True)
            self._opt_hline_bot.set_visible(False)
        elif event.inaxes is self.ax_bot and event.ydata is not None:
            self._opt_hline_bot.set_ydata([float(event.ydata), float(event.ydata)])
            self._opt_hline_bot.set_visible(True)
            self._opt_hline_top.set_visible(False)

        # Find slot index for the slot that the cursor is INSIDE (start <= x < start + 30 min).
        idx = int(np.searchsorted(self._opt_xnum, x, side='right') - 1)
        idx = max(0, min(len(self._opt_xnum) - 1, idx))
        # SOC trace lookup is on the (T+1)-length axis; linear interp gives a smooth %.
        if self._opt_soc_xnum.size >= 2:
            soc_pct = float(np.interp(x, self._opt_soc_xnum, self._opt_soc_pct))
        else:
            soc_pct = float(self._opt_soc_pct[0]) if self._opt_soc_pct.size else 0.0

        t = pd.Timestamp(self._opt_slot_starts[idx])
        ts_str = t.strftime('%a %d %b %H:%M')
        parts = [
            ts_str,
            f"Import {self._opt_p_in[idx]:.1f} p",
            f"Export {self._opt_p_ex[idx]:.1f} p",
            f"Solar {self._opt_solar[idx]:.2f} kWh",
            f"Load {self._opt_load[idx]:.2f} kWh",
            f"Heater {self._opt_heater[idx]:.2f} kWh",
            f"SOC {soc_pct:.0f}%",
        ]
        self.cursor_label.setText("  |  ".join(parts))
        self.canvas.draw_idle()

    def _render_table(self, plan):
        slot_starts = plan['slot_starts']
        actions = plan['result']['actions']
        load = plan['load_kwh']
        solar = plan['solar_kwh']
        heater = plan['heater']['heater_kwh']
        cap = plan['capacity']

        self.table.setRowCount(len(actions))
        for i, a in enumerate(actions):
            t = pd.Timestamp(slot_starts[i])
            soc_pct = a['soc_after_kwh'] / cap * 100.0
            grid_to_batt = a.get('grid_to_batt', 0.0)
            batt_to_grid = a.get('batt_to_grid', 0.0)
            batt_to_load = a.get('batt_to_load', 0.0)
            solar_to_batt = a.get('solar_to_batt', 0.0)
            if grid_to_batt > 0.05:
                bat_action = f"grid-charge {grid_to_batt:.2f}"
                row_colour = QColor('#fab387')
            elif batt_to_grid > 0.05:
                bat_action = f"export {batt_to_grid:.2f}"
                row_colour = QColor('#cba6f7')
            elif batt_to_load > 0.05:
                bat_action = f"discharge {batt_to_load:.2f}"
                row_colour = QColor('#a6e3a1')
            elif solar_to_batt > 0.05:
                bat_action = f"solar-charge {solar_to_batt:.2f}"
                row_colour = QColor('#f9e2af')
            else:
                bat_action = "hold"
                row_colour = QColor('#cdd6f4')
            cells = [
                t.strftime('%a %H:%M'),
                f"{plan['p_in'][i]:.1f}",
                f"{plan['p_ex'][i]:.1f}",
                f"{solar[i]:.2f}",
                f"{load[i]:.2f}",
                f"{heater[i]:.2f}",
                bat_action,
                f"{soc_pct:.0f}",
                f"{a['slot_cost_p'] / 100.0:+.3f}",
            ]
            for col, txt in enumerate(cells):
                item = QTableWidgetItem(txt)
                item.setTextAlignment(Qt.AlignCenter)
                item.setForeground(QBrush(row_colour))
                self.table.setItem(i, col, item)
        qtable_prepare_interactive_columns(self.table)
        qtable_restore_column_widths(self.table, "optimiser_per_slot", resize_if_no_saved=False)

    # ── explainer dialog ───────────────────────────────────────────────

    _EXPLAINER_TEXT = (
        "BUILDING THE RIGID-LOAD FORECAST FOR TOMORROW\n"
        "(top row of the diagram — one number per half-hour)\n\n"
        "1. Start with what the meter actually saw historically  (OCTOPUS IMPORT, per ½h mean).\n\n"
        "2. Subtract what Tasmota measured at the same half-hours  (TASMOTA POWER).\n"
        "   Together these two cancel down to the non-Tasmota appliances.\n\n"
        "3. Subtract  HEATER HOURS MASK × 3 kW × 0.5 h  for the half-hours where the immersion\n"
        "   was historically on (detected by residual > ~1.2 kWh in a slot).\n"
        "   This is the ANTI-DOUBLE-COUNT step — without it, when the planner later adds its\n"
        "   own heater windows, the DP would be charged for heater energy twice.\n\n"
        "4. Add back the TASMOTA TYPICAL projection so we get tomorrow's expected device load\n"
        "   (forward-looking, not just the historical residual).\n\n"
        "What's left is the green box: the IRREDUCIBLE rigid load —\n"
        "    fridge  +  stove  +  outside lights  +  the 2 unmetered aircon units.\n"
        "These cannot be shifted in time, so the DP treats them as a fixed cost per slot.\n\n"
        "═════════════════════════════════════════════════════════════════════════════════\n\n"
        "WHAT THE DP ACTUALLY RECEIVES\n"
        "(bottom row of the diagram)\n\n"
        "Two SEPARATE arrays — never summed:\n\n"
        "    load[t]   = the green rigid baseline      (covers everything we cannot move)\n"
        "    heater[t] = whatever windows the heater scheduler picked\n"
        "                (mandatory pre-7am  +  best 4 h block, scored by net £)\n\n"
        "Why keep them separate?\n"
        "  When solar happens to be high during a heater window, the DP can correctly account\n"
        "  for solar covering the heater (vs uselessly exporting it).  If we summed them, the\n"
        "  DP could not see 'this kWh is heater-attributable' and so could not reason about\n"
        "  whether to MOVE the heater off-solar to free up battery export instead.\n\n"
        "═════════════════════════════════════════════════════════════════════════════════\n\n"
        "NOTE ON CONTROL\n\n"
        "The immersion is NOT on a Tasmota relay — heater windows are ADVISORY only.\n"
        "Switch the heater on manually at the start of each window; the DP assumes you do.\n"
        "Tasmota appliances (and any Shelly devices added later) are the candidates for full\n"
        "automatic write-back."
    )

    def _compute_decomposition_breakdown(self):
        """Gather the per-step numbers shown in the Load Decomposition diagram
        for the *current* plan (and recent history). Returns a dict — never
        raises — and indicates missing data with ``None`` so the renderer can
        gracefully say "n/a" for sources that aren't available yet (e.g. no
        plan built, no Octopus data, no Tasmota devices polled).
        """
        out = {
            'plan_window_start': None,
            'plan_window_end': None,
            'plan_n_slots': None,
            'rigid_total_kwh': None,
            'rigid_mean_kwh_per_slot': None,
            'heater_total_kwh': None,
            'heater_kw': None,
            'heater_windows': [],
            'octopus_history_mean_per_slot': None,
            'octopus_history_n_samples': None,
            'octopus_history_first': None,
            'octopus_history_last': None,
            'heater_decontam_matches': None,
            'heater_decontam_kwh_per_day': None,
            'tasmota_today_kwh': None,
            'tasmota_yesterday_kwh': None,
            'tasmota_active_count': None,
            'tasmota_total_count': None,
            'pv_forecast_horizon_kwh': None,
        }
        plan = self._last_plan
        if plan is not None:
            try:
                slots = plan['slot_starts']
                out['plan_window_start'] = pd.Timestamp(slots[0])
                out['plan_window_end'] = pd.Timestamp(slots[-1]) + pd.Timedelta(minutes=30)
                out['plan_n_slots'] = len(slots)
                load_arr = np.asarray(plan['load_kwh'], dtype=float)
                heater_arr = np.asarray(plan['heater']['heater_kwh'], dtype=float)
                out['rigid_total_kwh'] = float(load_arr.sum())
                out['rigid_mean_kwh_per_slot'] = float(load_arr.mean()) if load_arr.size else 0.0
                out['heater_total_kwh'] = float(heater_arr.sum())
                out['heater_kw'] = float(plan.get('heater_kw',
                                                  self.sp_heater_kw.value()))
                out['pv_forecast_horizon_kwh'] = float(np.sum(plan.get('solar_kwh', [])))
                wins = []
                for a, b in plan['heater'].get('morning_blocks', []):
                    st = pd.Timestamp(slots[a])
                    en = pd.Timestamp(slots[b - 1]) + pd.Timedelta(minutes=30)
                    wins.append(('Pre-7am', st, en, float(heater_arr[a:b].sum())))
                for a, b in plan['heater'].get('day_blocks', []):
                    st = pd.Timestamp(slots[a])
                    en = pd.Timestamp(slots[b - 1]) + pd.Timedelta(minutes=30)
                    wins.append(('Day block', st, en, float(heater_arr[a:b].sum())))
                out['heater_windows'] = wins
            except Exception:
                pass
        # Octopus historical — feeds the OCTOPUS IMPORT box (per-½h mean).
        try:
            hh = getattr(self.octopus_tab, 'hh_data', None)
            if hh is not None and not hh.empty and 'Import (kWh)' in hh.columns:
                imp = hh['Import (kWh)'].dropna()
                if len(imp):
                    out['octopus_history_mean_per_slot'] = float(imp.mean())
                    out['octopus_history_n_samples'] = int(len(imp))
                    try:
                        idx = pd.DatetimeIndex(pd.to_datetime(imp.index, utc=True))
                        out['octopus_history_first'] = idx.min().tz_convert('Europe/London')
                        out['octopus_history_last'] = idx.max().tz_convert('Europe/London')
                    except Exception:
                        pass
        except Exception:
            pass
        # Heater decontam — exact same matching logic as _build_usage_profile.
        try:
            heater_kw = float(self.sp_heater_kw.value())
            sched = getattr(self.app_params, 'scheduled_loads', []) or []
            matching = [s for s in sched
                        if abs(float(s['kw']) - heater_kw) <= 0.1]
            out['heater_decontam_matches'] = len(matching)
            out['heater_decontam_kwh_per_day'] = sum(
                float(s['kw']) * float(s['duration_min']) / 60.0 for s in matching
            )
        except Exception:
            pass
        # Tasmota — live device data (today / yesterday cumulative).
        try:
            td = getattr(self.tasmota_tab, 'device_data', None) or {}
            active = [d for d in td.values() if d]
            out['tasmota_total_count'] = len(td)
            out['tasmota_active_count'] = sum(
                1 for d in active if (d.get('power_W') or 0) > 0
            )
            if active:
                out['tasmota_today_kwh'] = sum(
                    float(d.get('today_kWh') or 0) for d in active
                )
                out['tasmota_yesterday_kwh'] = sum(
                    float(d.get('yesterday_kWh') or 0) for d in active
                )
        except Exception:
            pass
        return out

    @staticmethod
    def _fmt_window_range(st, en):
        """Render a (start, end) timestamp pair as 'Wed 22 Apr 23:00 → Fri 24 Apr 23:00'."""
        try:
            st = pd.Timestamp(st)
            en = pd.Timestamp(en)
            return f"{st.strftime('%a %d %b %H:%M')} → {en.strftime('%a %d %b %H:%M')}"
        except Exception:
            return "n/a"

    def _build_decomposition_numbers_panel(self, parent_layout):
        """Render a compact numeric panel under the diagram showing the actual
        kWh figures the planner used for the *current* plan + supporting history.
        Falls back to a friendly "press Build plan" hint when no plan exists.
        """
        b = self._compute_decomposition_breakdown()

        box = QGroupBox("Numbers for this plan")
        box.setStyleSheet(
            "QGroupBox { color: #cdd6f4; font-weight: bold; margin-top: 8px;"
            " border: 1px solid #45475a; border-radius: 6px; padding: 10px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px;"
            " padding: 0 4px; }"
        )
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 14, 10, 10)
        v.setSpacing(4)

        def na(v, fmt="{:.2f}", suffix=""):
            if v is None:
                return "<i style='color:#6c7086;'>n/a</i>"
            try:
                return fmt.format(v) + suffix
            except Exception:
                return str(v) + suffix

        # Header line: plan window
        if b['plan_window_start'] and b['plan_window_end']:
            window_txt = self._fmt_window_range(b['plan_window_start'], b['plan_window_end'])
            slot_txt = (
                f"  ({b['plan_n_slots']} half-hour slots, "
                f"{b['plan_n_slots'] * 0.5:.1f} h horizon)"
            )
            hdr = QLabel(
                f"<b>Plan window:</b> <span style='color:#a6e3a1;'>{window_txt}</span>"
                f"<span style='color:#6c7086;'>{slot_txt}</span>"
            )
        else:
            hdr = QLabel(
                "<i style='color:#f9e2af;'>No plan built yet — press "
                "<b>Build plan</b> to populate these numbers.</i>"
            )
        hdr.setTextFormat(Qt.RichText)
        v.addWidget(hdr)

        # Top row of the diagram — rigid-baseline build pipeline
        row1 = QLabel(
            "<div style='margin-top:6px;'>"
            "<b style='color:#fab387;'>Top row — building the rigid baseline:</b>"
            "</div>"
        )
        row1.setTextFormat(Qt.RichText)
        v.addWidget(row1)

        # Octopus historical
        oct_first = b['octopus_history_first']
        oct_last = b['octopus_history_last']
        oct_range = (
            f" ({oct_first.strftime('%d %b')} → {oct_last.strftime('%d %b')}, "
            f"{b['octopus_history_n_samples']} ½h samples)"
            if oct_first and oct_last and b['octopus_history_n_samples'] else ""
        )
        l1 = QLabel(
            f"  <span style='color:#f5c2e7;'>OCTOPUS IMPORT</span> (history mean):"
            f" <b>{na(b['octopus_history_mean_per_slot'], '{:.3f}')}</b> kWh / ½h"
            f"<span style='color:#6c7086;'>{oct_range}</span>"
        )
        l1.setTextFormat(Qt.RichText)
        v.addWidget(l1)

        # Tasmota historical
        if b['tasmota_today_kwh'] is not None:
            tas_txt = (
                f" today {b['tasmota_today_kwh']:.2f} kWh, "
                f"yesterday {b['tasmota_yesterday_kwh']:.2f} kWh"
            )
        else:
            tas_txt = " <i style='color:#6c7086;'>(no Tasmota devices polled)</i>"
        l2 = QLabel(
            f"  <span style='color:#fab387;'>TASMOTA POWER</span> (live devices):"
            f" {b['tasmota_active_count'] or 0}/{b['tasmota_total_count'] or 0} active —"
            f"<span>{tas_txt}</span>"
        )
        l2.setTextFormat(Qt.RichText)
        v.addWidget(l2)

        # Heater decontam mask (the v2.9.80 fix)
        if b['heater_decontam_matches']:
            decon_txt = (
                f"  <span style='color:#f9e2af;'>HEATER HOURS MASK</span>"
                f" × {b['heater_kw'] or 3.0:.1f} kW × 0.5 h:"
                f" <b>{b['heater_decontam_matches']}</b> scheduled-load entry"
                f"{'ies' if b['heater_decontam_matches'] != 1 else ''} matched"
                f"<span style='color:#6c7086;'>"
                f" → −{b['heater_decontam_kwh_per_day']:.2f} kWh/day subtracted from"
                f" Octopus floor (anti double-count)</span>"
            )
        else:
            decon_txt = (
                f"  <span style='color:#f9e2af;'>HEATER HOURS MASK</span>:"
                f" <i style='color:#6c7086;'>no scheduled_loads entry matches the"
                f" heater kW (heater is purely planner-scheduled)</i>"
            )
        l3 = QLabel(decon_txt)
        l3.setTextFormat(Qt.RichText)
        v.addWidget(l3)

        # Result: rigid baseline going into the DP
        rigid_total = b['rigid_total_kwh']
        rigid_mean = b['rigid_mean_kwh_per_slot']
        l4 = QLabel(
            f"  <span style='color:#a6e3a1;'>RIGID BASELINE [t]</span>:"
            f" total <b>{na(rigid_total, '{:.2f}')}</b> kWh over the plan horizon,"
            f" mean <b>{na(rigid_mean, '{:.3f}')}</b> kWh / ½h"
        )
        l4.setTextFormat(Qt.RichText)
        v.addWidget(l4)

        # Bottom row — DP input
        row2 = QLabel(
            "<div style='margin-top:8px;'>"
            "<b style='color:#cba6f7;'>Bottom row — what the DP sees:</b>"
            "</div>"
        )
        row2.setTextFormat(Qt.RichText)
        v.addWidget(row2)

        l5 = QLabel(
            f"  <span style='color:#a6e3a1;'>load[t]</span> total ="
            f" <b>{na(rigid_total, '{:.2f}')}</b> kWh"
            f"  <span style='color:#6c7086;'>(rigid baseline; cannot be moved)</span>"
        )
        l5.setTextFormat(Qt.RichText)
        v.addWidget(l5)

        l6 = QLabel(
            f"  <span style='color:#cba6f7;'>heater[t]</span> total ="
            f" <b>{na(b['heater_total_kwh'], '{:.2f}')}</b> kWh"
            f"  <span style='color:#6c7086;'>("
            f"{b['heater_kw'] or 3.0:.1f} kW immersion, planner-scheduled)</span>"
        )
        l6.setTextFormat(Qt.RichText)
        v.addWidget(l6)

        if b['heater_windows']:
            win_lines = []
            for kind, st, en, kwh in b['heater_windows']:
                win_lines.append(
                    f"    • {kind}: {pd.Timestamp(st).strftime('%a %H:%M')}–"
                    f"{pd.Timestamp(en).strftime('%H:%M')} = "
                    f"<b>{kwh:.2f}</b> kWh"
                )
            l7 = QLabel(
                "  <span style='color:#cba6f7;'>Heater windows chosen:</span><br>"
                + "<br>".join(win_lines)
            )
            l7.setTextFormat(Qt.RichText)
            v.addWidget(l7)

        # Combined load
        if rigid_total is not None and b['heater_total_kwh'] is not None:
            l8 = QLabel(
                f"  <span style='color:#f5c2e7;'>Combined</span> load[t] + heater[t] ="
                f" <b>{rigid_total + b['heater_total_kwh']:.2f}</b> kWh over horizon"
                f"  <span style='color:#6c7086;'>(reference total — not summed in the DP)</span>"
            )
            l8.setTextFormat(Qt.RichText)
            v.addWidget(l8)

        # Sanity / context line
        if b['pv_forecast_horizon_kwh'] is not None:
            l9 = QLabel(
                f"  <span style='color:#f9e2af;'>Solar forecast over horizon:</span>"
                f" <b>{b['pv_forecast_horizon_kwh']:.2f}</b> kWh"
                f" <span style='color:#6c7086;'>(after PV scale × PV10 blend)</span>"
            )
            l9.setTextFormat(Qt.RichText)
            v.addWidget(l9)

        parent_layout.addWidget(box)

    def _show_explainer(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Load decomposition — how the Optimiser splits the meter")
        dlg.setMinimumSize(1100, 820)
        dlg.setStyleSheet(
            f"QDialog {{ background: {_DARK_SURFACE_BG}; }} QLabel {{ color: #cdd6f4; }}"
        )

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        title = QLabel("Rigid Baseline + Heater — Load Decomposition for the Optimiser DP")
        title.setStyleSheet("color: #cdd6f4; font-size: 16px; font-weight: bold;")
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {_DARK_SURFACE_BG}; border: 1px solid #313244; }}"
        )
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(10, 10, 10, 10)
        body_lay.setSpacing(8)

        img_path = ASSETS_DIR / "load-decomposition.png"
        img_label = QLabel()
        img_label.setAlignment(Qt.AlignCenter)
        if img_path.is_file():
            pix = QPixmap(str(img_path))
            if not pix.isNull():
                img_label.setPixmap(
                    pix.scaledToWidth(1040, Qt.SmoothTransformation)
                )
            else:
                img_label.setText(f"(could not load image: {img_path.name})")
        else:
            img_label.setText(f"(diagram image not found at {img_path})")
        body_lay.addWidget(img_label)

        # Live numeric panel — populated from self._last_plan + Octopus
        # historical hh_data + Tasmota live device_data + scheduled_loads
        # decontam matches. Renders gracefully (with "n/a" placeholders)
        # when any source is missing.
        self._build_decomposition_numbers_panel(body_lay)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setFont(QFont('Courier', 10))
        text.setPlainText(self._EXPLAINER_TEXT)
        text.setMinimumHeight(360)
        body_lay.addWidget(text)

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        outer.addWidget(btns)

        _prepare_dialog_buttons(dlg)
        dlg.exec()

    def _render_why(self, plan):
        actions = plan['result']['actions']
        soc_now_kwh = plan['capacity'] * (plan['soc_now'] / 100.0)
        net_cost_p = sum(a['slot_cost_p'] for a in actions)
        baseline_p = plan['baseline_cost_p']
        chg_windows = collapse_grid_charge_to_periods(plan['slot_starts'], actions, max_periods=3)
        exp_windows = collapse_grid_export_runs(plan['slot_starts'], actions)
        total_solar = float(np.sum(plan['solar_kwh']))
        total_rigid = float(np.sum(plan['load_kwh']))
        total_heater = float(np.sum(plan['heater']['heater_kwh']))

        lines = []
        lines.append(
            f"SOC now      : {plan['soc_now']:.1f}%  "
            f"({soc_now_kwh:.2f} of {plan['capacity']:.1f} kWh, {plan['soc_source']})"
        )
        lines.append(
            f"Horizon load : {total_rigid + total_heater:.1f} kWh  "
            f"(rigid {total_rigid:.1f} + heater {total_heater:.1f})"
        )
        lines.append(
            f"Solar (PV forecast scale ×{self.sp_pv_forecast_scale.value():.2f}): "
            f"{total_solar:.1f} kWh"
        )
        lines.append("")
        lines.append("Bridge logic:")
        lines.append(
            "  Grid-charge ONLY enough to bridge to the next solar window,"
        )
        lines.append(
            "  plus a buffer for what solar can't refill before evening peak."
        )
        if not chg_windows:
            lines.append(
                "  -> 0 kWh of grid-charging needed (solar covers the gap)."
            )
        else:
            for st, en, kwh in chg_windows:
                lines.append(f"  -> {self._fmt_window(st, en)}: charge {kwh:.2f} kWh.")

        lines.append("")
        lines.append("Export logic:")
        lines.append(
            f"  Export only if export-price >= cheapest-future-import "
            f"+ {self.sp_export_margin.value():.1f} p/kWh,"
        )
        lines.append(
            f"  and SOC after stays >= {_PLAN_EXPORT_MIN_SOC}%."
        )
        if not exp_windows:
            lines.append("  -> no battery-export slot meets the bar in this horizon.")
        else:
            for st, en, kwh in exp_windows:
                lines.append(f"  -> {self._fmt_window(st, en)}: export {kwh:.2f} kWh.")

        lines.append("")
        lines.append("Heater logic:")
        for a, b in plan['heater']['morning_blocks']:
            st = pd.Timestamp(plan['slot_starts'][a])
            en = pd.Timestamp(plan['slot_starts'][b - 1]) + pd.Timedelta(minutes=30)
            lines.append(f"  Pre-7am (mandatory): {self._fmt_window(st, en)}")
        if plan['heater']['alternates']:
            lines.append("  Daytime block alternatives (cheapest first):")
            for net, a, b in plan['heater']['alternates']:
                st = pd.Timestamp(plan['slot_starts'][a])
                en = pd.Timestamp(plan['slot_starts'][b - 1]) + pd.Timedelta(minutes=30)
                lines.append(f"    {self._fmt_window(st, en)}: £{net / 100.0:+.2f}")

        lines.append("")
        lines.append(f"Net plan cost   : £{net_cost_p / 100.0:+.2f}")
        lines.append(f"Naive overnight : £{baseline_p / 100.0:+.2f}")
        lines.append(f"Saving          : £{(baseline_p - net_cost_p) / 100.0:+.2f}")

        self.why_text.setPlainText("\n".join(lines))


__all__ = [n for n in globals() if not n.startswith('__')]
