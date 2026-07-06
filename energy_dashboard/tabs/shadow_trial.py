"""
Energy Dashboard — `tabs/shadow_trial.py`.

Shadow Trial: benchmark the live controller (e.g. Growatt's Smart
Scheduling AI, or plain self-consumption) against this dashboard's
optimiser — WITHOUT ever writing to the inverter.

Each night at ~23:35 London the tab freezes the optimiser's plan for the
next calendar day, built only from what was knowable at that moment (live
SOC, current solar forecast, published Agile prices, learned usage
profile). After each day completes, the evaluator scores four contestants
on identical realised data:

  * Actual        — what the inverter really did (Octopus meter data)
  * Shadow        — the frozen plan replayed against realised load/PV
  * Baseline      — simulated dumb load-first self-consumption
  * Perfect       — hindsight-optimal DP (theoretical ceiling)

Capture ratio = (baseline − controller) / (baseline − perfect): the share
of the theoretically available savings each controller banked, comparable
across days with different weather and prices.
"""
from __future__ import annotations

import json as _json
import time as _time_mod

from energy_dashboard.common import *

_QS_ORG, _QS_APP = "PowerModel", "EnergyDashboard2"
_QS_ENABLED = "shadow_trial/enabled"
_QS_GUARD = "shadow_trial/guard_writes"

_FREEZE_WINDOW = (23, 32, 23, 58)   # HH:MM .. HH:MM London, nightly freeze
_SCORE_INTERVAL_S = 3600            # background scoring pass cadence
_RESCORE_LOOKBACK_DAYS = 21         # re-score while Octopus data still filling in
# Default Shadow Trial scoreboard column widths (px); last column stretches.
_SHADOW_TRIAL_COL_WIDTHS = (
    108, 102, 102, 108, 102, 124, 124, 100,
)


def shadow_trial_guard_active() -> bool:
    """True when inverter writebacks should warn that a shadow trial is live.

    Read straight from QSettings so OptimiserTab / SmartAdvisorTab don't
    need a reference to the ShadowTrialTab instance.
    """
    qs = QSettings(_QS_ORG, _QS_APP)
    try:
        return (bool(qs.value(_QS_ENABLED, True, type=bool))
                and bool(qs.value(_QS_GUARD, True, type=bool)))
    except Exception:
        return False


def confirm_despite_shadow_trial(parent, action: str) -> bool:
    """Extra Yes/No gate shown before inverter writes while the trial runs."""
    if not shadow_trial_guard_active():
        return True
    r = QMessageBox.warning(
        parent,
        "Shadow trial is running",
        f"The Shadow Trial is benchmarking the inverter's CURRENT controller "
        f"against the dashboard's optimiser. Writing a schedule now "
        f"({action}) would change the inverter's behaviour mid-trial and "
        f"contaminate the comparison.\n\n"
        f"You can disable this warning on the Shadow Trial tab "
        f"(Guard inverter writebacks).\n\nWrite anyway?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return r == QMessageBox.StandardButton.Yes


class ShadowTrialTab(QWidget):
    """Nightly frozen plans + daily four-way scoreboard (read-only trial)."""

    def __init__(self, growatt_tab, forecasts_tab, advisor_tab, optimiser_tab,
                 app_params, status_callback, data_logger=None):
        super().__init__()
        self.growatt_tab = growatt_tab
        self.forecasts_tab = forecasts_tab
        self.advisor_tab = advisor_tab
        self.optimiser_tab = optimiser_tab
        self.app_params = app_params
        self.set_status = status_callback
        self.data_logger = data_logger
        self._inv = Invoker(self)
        self.on_data_updated = None
        self._freeze_running = False
        self._score_running = False
        self._last_score_ts = None      # time.time() of last scoring pass
        self._freeze_done_day = None    # London 'YYYY-MM-DD' already frozen tonight
        self.build_ui()
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._on_tick)
        self._tick_timer.start(60_000)

    # ── UI ───────────────────────────────────────────────────────────────

    def build_ui(self):
        qs = QSettings(_QS_ORG, _QS_APP)
        main = QVBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(6)

        ctrl_box = QGroupBox("Shadow trial controls (no inverter writes — observation only)")
        ctrl = QHBoxLayout(ctrl_box)

        self.cb_enabled = QCheckBox("Nightly plan freeze (~23:35)")
        self.cb_enabled.setChecked(bool(qs.value(_QS_ENABLED, True, type=bool)))
        self.cb_enabled.setToolTip(
            "Every night at ~23:35 (while the dashboard is open) the optimiser "
            "plan for tomorrow is built from live SOC + current forecasts + "
            "published Agile prices, then frozen to the database. It is never "
            "sent to the inverter."
        )
        self.cb_enabled.toggled.connect(
            lambda v: QSettings(_QS_ORG, _QS_APP).setValue(_QS_ENABLED, bool(v)))
        ctrl.addWidget(self.cb_enabled)
        ctrl.addSpacing(12)

        self.cb_guard = QCheckBox("Guard inverter writebacks")
        self.cb_guard.setChecked(bool(qs.value(_QS_GUARD, True, type=bool)))
        self.cb_guard.setToolTip(
            "While the trial runs, the Optimiser / Smart Advisor inverter "
            "write buttons show an extra 'are you sure?' warning so a habit "
            "click can't contaminate weeks of benchmark data."
        )
        self.cb_guard.toggled.connect(
            lambda v: QSettings(_QS_ORG, _QS_APP).setValue(_QS_GUARD, bool(v)))
        ctrl.addWidget(self.cb_guard)
        ctrl.addSpacing(12)

        self.freeze_btn = QPushButton("Freeze plan now")
        self.freeze_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self.freeze_btn.setToolTip(
            "Freeze tomorrow's shadow plan immediately. The horizon always "
            "reaches the end of tomorrow, but a freeze before ~16:00 prices "
            "unpublished Agile slots at the flat fallback rate — the honest "
            "cost of planning early. The nightly ~23:35 freeze replaces any "
            "earlier one."
        )
        self.freeze_btn.clicked.connect(lambda: self._start_freeze(manual=True))
        ctrl.addWidget(self.freeze_btn)

        self.score_btn = QPushButton("Score days now")
        self.score_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self.score_btn.setToolTip(
            "Evaluate every unscored (or still-incomplete) past day: replay "
            "the frozen plan against realised load/PV, simulate the baseline "
            "and the perfect-foresight DP, and price the real day from "
            "Octopus meter data."
        )
        self.score_btn.clicked.connect(lambda: self._start_scoring(manual=True))
        ctrl.addWidget(self.score_btn)

        ctrl.addStretch(1)
        main.addWidget(ctrl_box)

        self.status_label = QLabel("Idle.")
        self.status_label.setStyleSheet(f"color: {_DARK_TEXT}; font-size: 11px;")
        main.addWidget(self.status_label)

        self.summary_label = QLabel("No scored days yet.")
        self.summary_label.setStyleSheet(
            f"color: {_DARK_TEXT}; font-weight: bold; font-size: 12px;")
        self.summary_label.setWordWrap(True)
        main.addWidget(self.summary_label)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Day", "Actual £", "Shadow £", "Baseline £", "Perfect £",
            "Actual capture", "Shadow capture", "Telemetry", "Meter data",
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self._apply_shadow_trial_table_columns()
        main.addWidget(self.table, 1)

        hint = QLabel(
            "Actual = what the inverter's current controller really did (priced "
            "from Octopus meter data, so it appears a day or two later). Shadow = "
            "this dashboard's optimiser plan, frozen the night before and replayed "
            "against the realised day. Capture = share of the day's theoretically "
            "available savings banked (vs dumb self-consumption baseline, ceiling = "
            "hindsight-perfect DP). Compare cumulative figures over weeks, not "
            "single days — day-boundary battery SOC differences wash out over time."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #a6adc8; font-size: 10px;")
        main.addWidget(hint)

    def _apply_shadow_trial_table_columns(self) -> None:
        tbl = self.table
        hdr = tbl.horizontalHeader()
        qtable_set_column_width_key(tbl, "shadow_trial_scores")
        qtable_prepare_interactive_columns(tbl)
        restored = qtable_restore_column_widths(tbl, "shadow_trial_scores")
        if not restored:
            for col, width in enumerate(_SHADOW_TRIAL_COL_WIDTHS):
                tbl.setColumnWidth(col, width)
        else:
            for col, width in enumerate(_SHADOW_TRIAL_COL_WIDTHS):
                if tbl.columnWidth(col) < width:
                    tbl.setColumnWidth(col, width)
        for col in range(tbl.columnCount() - 1):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(tbl.columnCount() - 1, QHeaderView.ResizeMode.Stretch)
        hdr.setStretchLastSection(True)
        if not getattr(tbl, "_qcol_persist_attached", False):
            qtable_attach_column_width_persistence(tbl)

    # ── lifecycle ────────────────────────────────────────────────────────

    def auto_start(self):
        self.refresh_scores()
        QTimer.singleShot(30_000, lambda: self._start_scoring(manual=False))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_scores()

    def refresh_now(self):
        """Refresh-page hook: reload scoreboard and kick a scoring pass."""
        self.refresh_scores()
        self._start_scoring(manual=False)

    # ── periodic driver ──────────────────────────────────────────────────

    def _on_tick(self):
        import pytz
        now_l = datetime.now(pytz.timezone('Europe/London'))
        h0, m0, h1, m1 = _FREEZE_WINDOW
        in_window = (h0, m0) <= (now_l.hour, now_l.minute) < (h1, m1)
        if in_window and self.cb_enabled.isChecked():
            target = (now_l + timedelta(days=1)).strftime('%Y-%m-%d')
            if self._freeze_done_day != target:
                self._start_freeze(manual=False)
        if self._last_score_ts is None or (_time_mod.time() - self._last_score_ts) > _SCORE_INTERVAL_S:
            self._start_scoring(manual=False)

    def _db_ready(self) -> bool:
        return bool(self.data_logger
                    and self.data_logger._primary_storage_backend() is not None)

    # ── nightly freeze ───────────────────────────────────────────────────

    def _start_freeze(self, manual: bool):
        if self._freeze_running:
            if manual:
                self.status_label.setText("A plan freeze is already running.")
            return
        if not self._db_ready():
            msg = ("No database backend enabled — enable SQLite/PostgreSQL in "
                   "Setup & Info so frozen plans and scores can be stored.")
            self.status_label.setText(msg)
            if manual:
                QMessageBox.warning(self, "No database", msg)
            return
        self._freeze_running = True
        self.freeze_btn.setEnabled(False)
        self.status_label.setText("Freezing shadow plan…")
        threading.Thread(target=self._freeze_thread, daemon=True).start()

    def _freeze_thread(self):
        try:
            row = self._build_frozen_plan()
            self.data_logger.log_shadow_plan(row)
            day = row['day_date']
            n = row['slot_count']
            self._freeze_done_day = day
            self._inv.invoke(lambda: self._freeze_done(
                f"Frozen plan for {day}: {n} slots, planned cost "
                f"£{row['planned_cost_p'] / 100.0:+.2f} "
                f"(SOC {row['soc_start_pct']:.0f}% {row['soc_source']})."))
        except Exception as e:
            import traceback
            _log.warn("ShadowTrial", f"Freeze failed: {e}\n{traceback.format_exc()}")
            err = str(e) or type(e).__name__
            self._inv.invoke(lambda: self._freeze_done(f"Freeze failed: {err[:160]}"))

    def _freeze_done(self, msg):
        self._freeze_running = False
        self.freeze_btn.setEnabled(True)
        self.status_label.setText(msg)
        self.set_status(f"Shadow Trial: {msg}")

    def _build_frozen_plan(self) -> dict:
        """Build tomorrow's plan exactly the way the Optimiser would, then
        keep only tomorrow's slots. Mirrors OptimiserTab._planner_thread_impl
        (fresh API fetches — the whole point is 'knowable at freeze time')."""
        import pytz
        london = pytz.timezone('Europe/London')
        now_l = datetime.now(london)
        target_day = (now_l + timedelta(days=1)).strftime('%Y-%m-%d')
        # Size the horizon to reach the END of tomorrow whatever the time of
        # day (the nightly ~23:35 freeze needs ~49 slots; a manual daytime
        # freeze needs up to ~96). Priced slots past Agile's published range
        # fall back to the flat rate — the honest cost of planning early.
        target_slots = day_slot_starts_london(target_day)
        first_slot = plan_horizon_slot_starts(now_l, n_slots=1)[0]
        n_slots = int((pd.Timestamp(target_slots[-1]) - pd.Timestamp(first_slot))
                      / pd.Timedelta(minutes=30)) + 1
        n_slots = max(_PLAN_SLOTS_DEFAULT, min(100, n_slots))
        slot_starts = plan_horizon_slot_starts(now_l, n_slots=n_slots)

        soc_box = {'v': None, 'done': False}

        def _read_soc():
            try:
                soc_box['v'] = self.growatt_tab.get_current_soc()
            finally:
                soc_box['done'] = True

        self._inv.invoke(_read_soc)
        for _ in range(60):
            if soc_box['done']:
                break
            threading.Event().wait(0.05)
        soc_now = soc_box['v'] if soc_box['v'] is not None else 50.0
        soc_source = "live" if soc_box['v'] is not None else "assumed 50%"

        solar_df = pd.DataFrame()
        try:
            se = self.forecasts_tab.solar_edits
            solar_df, _ = fetch_solar_forecast(
                se['lat'].text(), se['lon'].text(), se['tilt'].text(),
                se['azimuth'].text(), se['kwp'].text())
        except Exception as e:
            _log.warn("ShadowTrial", f"Solar forecast error: {e}")

        p = self.app_params
        agile_in = pd.DataFrame()
        try:
            agile_in = fetch_agile_prices(p.agile_product, p.agile_tariff)
        except Exception as e:
            _log.warn("ShadowTrial", f"Agile import price error: {e}")
        agile_ex_series = pd.Series(dtype=float)
        try:
            ts0 = pd.Timestamp(slot_starts[0]).tz_convert('UTC')
            ts1 = pd.Timestamp(slot_starts[-1]).tz_convert('UTC') + pd.Timedelta(hours=1)
            agile_ex_series = fetch_agile_rates_series_utc(
                p.agile_product, p.agile_export_tariff, ts0, ts1)
        except Exception as e:
            _log.warn("ShadowTrial", f"Agile export price error: {e}")

        # Mirror the Optimiser tab's tuning knobs so the shadow plan is the
        # plan the user would really have run.
        opt = self.optimiser_tab
        heater_kw = float(opt.sp_heater_kw.value())
        day_block_h = int(opt.sp_day_block.value())
        pv_scale = float(opt.sp_pv_forecast_scale.value())
        pv10_w = float(opt.sp_pv10_weight.value())
        export_margin = float(opt.sp_export_margin.value())
        terminal_scale = float(opt.sp_terminal_value_scale.value())
        allow_export = bool(opt.cb_allow_export.isChecked())

        usage_profile = {}
        try:
            usage_profile = self.advisor_tab._build_usage_profile(
                exclude_heater_kw=heater_kw)
        except Exception as e:
            _log.warn("ShadowTrial", f"Usage profile error: {e}")

        load_kwh = plan_load_per_slot(slot_starts, usage_profile, p.base_load_kw)
        solar_kwh = plan_solar_per_slot(
            slot_starts, solar_df, forecast_scale=pv_scale, pv10_weight=pv10_w)
        p_in = plan_prices_per_slot(slot_starts, agile_in, p.import_flat_pence)
        p_ex = plan_export_prices_per_slot(
            slot_starts, agile_ex_series, p.export_flat_pence)
        heater = pick_heater_windows(
            slot_starts, p_in, p_ex, solar_kwh,
            heater_kw=heater_kw, day_block_h=day_block_h)

        capacity = float(p.battery_capacity_kwh)
        eta = float(p.analytics_efficiency_pct) / 100.0
        max_kw = float(p.analytics_max_charge_kw)
        soc_min_pct = float(p.battery_low_soc_threshold_pct)

        result = dp_battery_dispatch(
            load_kwh, solar_kwh, p_in, p_ex,
            capacity * (float(soc_now) / 100.0), capacity,
            eta=eta, max_kw=max_kw, soc_min_pct=soc_min_pct,
            export_margin_p=export_margin,
            heater_kwh=heater['heater_kwh'],
            terminal_value_scale=terminal_scale,
            allow_battery_export=allow_export,
        )

        slots = []
        planned_cost = 0.0
        for i, t in enumerate(slot_starts):
            if pd.Timestamp(t).strftime('%Y-%m-%d') != target_day:
                continue
            act = result['actions'][i]
            slots.append({
                't': slot_key_utc(t),
                'load': round(float(load_kwh[i]), 4),
                'solar': round(float(solar_kwh[i]), 4),
                'heater': round(float(heater['heater_kwh'][i]), 4),
                'p_in': round(float(p_in[i]), 3),
                'p_ex': round(float(p_ex[i]), 3),
                'charge': round(float(act['grid_to_batt']), 4),
                'export': round(float(act['batt_to_grid']), 4),
                'soc_after': round(float(act['soc_after_kwh']), 3),
            })
            planned_cost += float(act['slot_cost_p'])

        if not slots:
            raise RuntimeError(
                f"Plan horizon contains no slots for {target_day} — "
                f"freeze closer to midnight for full coverage.")

        return {
            'day_date': target_day,
            'built_at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            'soc_start_pct': float(soc_now),
            'soc_source': soc_source,
            'capacity_kwh': capacity,
            'eta': eta,
            'max_kw': max_kw,
            'soc_min_pct': soc_min_pct,
            'allow_export': int(allow_export),
            'planned_cost_p': planned_cost,
            'slot_count': len(slots),
            'plan_json': _json.dumps({'slots': slots}),
        }

    # ── scoring ──────────────────────────────────────────────────────────

    def _start_scoring(self, manual: bool):
        if self._score_running:
            if manual:
                self.status_label.setText("A scoring pass is already running.")
            return
        if not self._db_ready():
            if manual:
                QMessageBox.warning(
                    self, "No database",
                    "No database backend enabled — enable SQLite/PostgreSQL in "
                    "Setup & Info first.")
            return
        self._score_running = True
        self._last_score_ts = _time_mod.time()
        self.score_btn.setEnabled(False)
        threading.Thread(target=self._scoring_thread, daemon=True).start()

    def _scoring_thread(self):
        try:
            n_scored = self._score_pending_days()
            msg = (f"Scoring pass complete: {n_scored} day(s) evaluated."
                   if n_scored else "Scoring pass complete: nothing new to score.")
        except Exception as e:
            import traceback
            _log.warn("ShadowTrial", f"Scoring failed: {e}\n{traceback.format_exc()}")
            msg = f"Scoring failed: {(str(e) or type(e).__name__)[:160]}"
        self._inv.invoke(lambda: self._scoring_done(msg))

    def _scoring_done(self, msg):
        self._score_running = False
        self.score_btn.setEnabled(True)
        self.status_label.setText(msg)
        self.refresh_scores()

    def _score_pending_days(self) -> int:
        import pytz
        today = datetime.now(pytz.timezone('Europe/London')).strftime('%Y-%m-%d')
        plan_days = [d for d in self.data_logger.query_shadow_plan_days()
                     if str(d) < today]
        if not plan_days:
            return 0
        scores = self.data_logger.query_shadow_scores(limit_days=365)
        complete = set()
        if not scores.is_empty():
            for row in scores.iter_rows(named=True):
                if row.get('octopus_complete'):
                    complete.add(str(row.get('day_date')))
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=_RESCORE_LOOKBACK_DAYS)).strftime('%Y-%m-%d')
        n = 0
        for day in plan_days:
            day = str(day)
            if day in complete or day < cutoff:
                continue
            row = self._score_one_day(day)
            if row is not None:
                self.data_logger.log_shadow_score(row)
                n += 1
        return n

    def _score_one_day(self, day_date: str) -> dict | None:
        plan = self.data_logger.query_shadow_plan(day_date)
        if plan is None:
            return None
        slot_starts = day_slot_starts_london(day_date)
        expected = len(slot_starts)
        start_utc = pd.Timestamp(slot_starts[0]).tz_convert('UTC')
        end_utc = pd.Timestamp(slot_starts[-1]).tz_convert('UTC') + pd.Timedelta(minutes=30)

        p = self.app_params

        # Realised prices: published Agile slots are immutable, so the DB
        # snapshot IS the realised price; flat-rate fallback fills any gap.
        def _prices(direction, tariff, fallback):
            pf = self.data_logger.query_agile_prices(
                start_utc, end_utc, tariff, direction=direction)
            pdf = pf.to_pandas() if not pf.is_empty() else pd.DataFrame()
            return plan_prices_per_slot(slot_starts, pdf, fallback)

        p_in = _prices('import', p.agile_tariff, p.import_flat_pence)
        p_ex = _prices('export', p.agile_export_tariff, p.export_flat_pence)

        # Realised load/PV from logged Grott/Growatt telemetry.
        flows = self.data_logger.query_growatt_power_flows(start_utc, end_utc)
        load_kwh, has_load = bucket_power_to_slot_kwh(flows, slot_starts, 'load_kw')
        solar_kwh, _has_pv = bucket_power_to_slot_kwh(flows, slot_starts, 'pv_kw')
        telemetry_slots = int(has_load.sum())
        # Slots with no telemetry: assume base load, zero PV (recorded in the
        # Telemetry column so thin days are visibly less trustworthy).
        floor = float(p.base_load_kw) * 0.5
        load_kwh = np.where(has_load, load_kwh, floor)

        soc_start = self.data_logger.query_growatt_soc_near(start_utc)
        if soc_start is None:
            soc_start = plan.get('soc_start_pct') or 50.0

        capacity = float(plan.get('capacity_kwh') or p.battery_capacity_kwh)
        eta = float(plan.get('eta') or (p.analytics_efficiency_pct / 100.0))
        max_kw = float(plan.get('max_kw') or p.analytics_max_charge_kw)
        soc_min_pct = float(plan.get('soc_min_pct') or p.battery_low_soc_threshold_pct)
        allow_export = bool(plan.get('allow_export'))
        soc_start_kwh = capacity * float(soc_start) / 100.0

        # Frozen plan actions mapped onto the day's slots by UTC key.
        charge = np.zeros(expected)
        export = np.zeros(expected)
        try:
            plan_slots = _json.loads(plan['plan_json'])['slots']
            by_key = {s['t']: s for s in plan_slots}
            for i, t in enumerate(slot_starts):
                s = by_key.get(slot_key_utc(t))
                if s:
                    charge[i] = float(s.get('charge') or 0.0)
                    export[i] = float(s.get('export') or 0.0)
        except Exception as e:
            _log.warn("ShadowTrial", f"Plan JSON parse error for {day_date}: {e}")

        shadow_cost = baseline_cost = perfect_cost = None
        if telemetry_slots > 0:
            shadow = simulate_day_execution(
                load_kwh, solar_kwh, p_in, p_ex, charge, export,
                soc_start_kwh, capacity, eta=eta, max_kw=max_kw,
                soc_min_pct=soc_min_pct)
            baseline = simulate_day_execution(
                load_kwh, solar_kwh, p_in, p_ex,
                np.zeros(expected), np.zeros(expected),
                soc_start_kwh, capacity, eta=eta, max_kw=max_kw,
                soc_min_pct=soc_min_pct)
            # Pure-cash hindsight optimum: no wear tax, no end-of-day SOC
            # credit, no export-margin heuristic. With those left at their
            # planning defaults the DP's raw spend is NOT a valid ceiling
            # (it happily spends cash today for terminal SOC value), and
            # capture ratios above 100% appear.
            perfect = dp_battery_dispatch(
                load_kwh, solar_kwh, p_in, p_ex,
                soc_start_kwh, capacity, eta=eta, max_kw=max_kw,
                soc_min_pct=soc_min_pct,
                export_margin_p=0.0,
                throughput_penalty_p=0.0,
                terminal_value_scale=0.0,
                allow_battery_export=allow_export)
            shadow_cost = float(shadow['total_cost_p'])
            baseline_cost = float(baseline['total_cost_p'])
            perfect_cost = float(perfect['total_cost_p'])

        # Actual cost from Octopus half-hourly meter data (billing-grade;
        # arrives a day or two late, hence octopus_complete + re-scoring).
        cons = self.data_logger.query_octopus_consumption_any(start_utc, end_utc)
        actual_cost = None
        octopus_slots = 0
        if not cons.is_empty():
            starts_utc = pd.DatetimeIndex(
                [pd.Timestamp(t).tz_convert('UTC') for t in slot_starts])
            total = 0.0
            for row in cons.iter_rows(named=True):
                t = row.get('interval_start')
                if t is None:
                    continue
                i = starts_utc.searchsorted(pd.Timestamp(t).tz_convert('UTC'))
                if i >= expected or starts_utc[i] != pd.Timestamp(t).tz_convert('UTC'):
                    continue
                imp = float(row.get('import_kwh') or 0.0)
                exp = float(row.get('export_kwh') or 0.0)
                total += imp * p_in[i] - exp * p_ex[i]
                octopus_slots += 1
            if octopus_slots:
                actual_cost = total
        octopus_complete = int(octopus_slots >= expected)

        return {
            'day_date': day_date,
            'scored_at': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            'octopus_complete': octopus_complete,
            'telemetry_slots': telemetry_slots,
            'expected_slots': expected,
            'soc_start_pct': float(soc_start),
            'actual_cost_p': actual_cost,
            'shadow_cost_p': shadow_cost,
            'baseline_cost_p': baseline_cost,
            'perfect_cost_p': perfect_cost,
            'actual_capture': capture_ratio(baseline_cost, actual_cost, perfect_cost),
            'shadow_capture': capture_ratio(baseline_cost, shadow_cost, perfect_cost),
            'detail_json': _json.dumps({
                'octopus_slots': octopus_slots,
            }),
        }

    # ── scoreboard rendering ─────────────────────────────────────────────

    def refresh_scores(self):
        if not self._db_ready():
            self.summary_label.setText(
                "No database backend enabled — the Shadow Trial needs "
                "SQLite/PostgreSQL (Setup & Info) to store plans and scores.")
            self.table.setRowCount(0)
            return
        df = self.data_logger.query_shadow_scores(limit_days=120)
        self.table.setRowCount(0)
        if df is None or df.is_empty():
            self.summary_label.setText(
                "No scored days yet — the first score appears the day after "
                "the first nightly plan freeze (Octopus meter data lags a "
                "day or two).")
            return

        def _money(v):
            return f"£{float(v) / 100.0:+.2f}" if v is not None else "—"

        def _pct(v):
            return f"{float(v) * 100.0:.0f}%" if v is not None else "—"

        rows = list(df.iter_rows(named=True))
        self.table.setRowCount(len(rows))
        sums = {'actual': 0.0, 'shadow': 0.0, 'baseline': 0.0, 'perfect': 0.0}
        n_full = 0
        for r_i, row in enumerate(rows):
            tele = f"{row.get('telemetry_slots') or 0}/{row.get('expected_slots') or 0}"
            meter = "complete" if row.get('octopus_complete') else "pending"
            vals = [
                str(row.get('day_date') or ''),
                _money(row.get('actual_cost_p')),
                _money(row.get('shadow_cost_p')),
                _money(row.get('baseline_cost_p')),
                _money(row.get('perfect_cost_p')),
                _pct(row.get('actual_capture')),
                _pct(row.get('shadow_capture')),
                tele,
                meter,
            ]
            for c_i, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c_i:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r_i, c_i, item)
            if all(row.get(k) is not None for k in
                   ('actual_cost_p', 'shadow_cost_p', 'baseline_cost_p', 'perfect_cost_p')):
                sums['actual'] += float(row['actual_cost_p'])
                sums['shadow'] += float(row['shadow_cost_p'])
                sums['baseline'] += float(row['baseline_cost_p'])
                sums['perfect'] += float(row['perfect_cost_p'])
                n_full += 1
        if n_full:
            cum_actual = capture_ratio(sums['baseline'], sums['actual'], sums['perfect'])
            cum_shadow = capture_ratio(sums['baseline'], sums['shadow'], sums['perfect'])
            self.summary_label.setText(
                f"Cumulative over {n_full} fully-scored day(s):  "
                f"Actual £{sums['actual'] / 100.0:+.2f}  ·  "
                f"Shadow £{sums['shadow'] / 100.0:+.2f}  ·  "
                f"Baseline £{sums['baseline'] / 100.0:+.2f}  ·  "
                f"Perfect £{sums['perfect'] / 100.0:+.2f}   |   "
                f"Capture — actual "
                f"{'—' if cum_actual is None else f'{cum_actual * 100.0:.0f}%'}, "
                f"shadow "
                f"{'—' if cum_shadow is None else f'{cum_shadow * 100.0:.0f}%'}")
        else:
            self.summary_label.setText(
                f"{len(rows)} day(s) scored, none with complete data yet "
                f"(waiting on Octopus meter data and/or telemetry).")
        if self.on_data_updated:
            self.on_data_updated()
