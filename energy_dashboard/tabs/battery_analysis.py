"""
Energy Dashboard — `tabs/battery_analysis.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.core.alarms import (
    scan_history_sun_waste,
    summarise_solar_utilisation,
)
from energy_dashboard.db.mix_chart import fetch_mix_chart_range
class BatteryAnalysisTab(QWidget):
    def __init__(self, growatt_tab, status_callback, app_params=None, dash=None):
        super().__init__()
        self.growatt_tab = growatt_tab
        self.dash = dash
        self.set_status = status_callback
        self.app_params = app_params
        self._inv = Invoker(self)
        self.battery_capacity = 13.0
        self.soc_threshold = 10
        self.low_soc_events = []
        self.fetching = False
        self._battery_t_nums = None
        self._battery_hover_df = None
        self._battery_motion_cid = None
        self._ax_soc_rate = None
        self._soc_is_reconstructed = False
        # Set by EnergyDashboard.build_ui so the global "freshness" colour-
        # coding on the tab bar updates when the user re-fetches.
        self.on_data_updated = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._on_refresh_timer)
        self._capacity_dirty = False
        self._charge_stop_dirty = False
        self.build_ui()
        self._load_refresh_interval()
        self._apply_refresh_timer()
        self._load_analysis_config()

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Vertical)

        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # --- Controls ---
        ctrl_box = QGroupBox("Battery History Controls")
        ctrl_layout = QHBoxLayout(ctrl_box)
        ctrl_layout.addWidget(QLabel("Day Range:"))
        self.days_group = QButtonGroup(self)
        for text, val in [("1 day", 1), ("3 days", 3), ("7 days", 7), ("14 days", 14)]:
            rb = QRadioButton(text)
            self.days_group.addButton(rb, val)
            ctrl_layout.addWidget(rb)
        self.days_group.button(3).setChecked(True)
        self.days_group.idClicked.connect(self._on_day_range_changed)
        ctrl_layout.addSpacing(20)
        ctrl_layout.addWidget(QLabel("Battery Capacity (kWh):"))
        self.capacity_spin = QDoubleSpinBox()
        self.capacity_spin.setRange(1.0, 200.0)
        self.capacity_spin.setDecimals(1)
        self.capacity_spin.setSingleStep(0.5)
        self.capacity_spin.setValue(13.0)
        self.capacity_spin.setToolTip(
            "Pack size used for kWh insights on this tab. Defaults to the "
            "nominal capacity on Growatt Live Status (equipage / rated). "
            "You can change it here; Save remembers it."
        )
        apply_spin_field_motif(self.capacity_spin)
        self.capacity_spin.valueChanged.connect(self._on_capacity_edited)
        ctrl_layout.addWidget(self.capacity_spin)
        ctrl_layout.addWidget(QLabel("Low SOC Threshold (%):"))
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(0, 50)
        self.threshold_spin.setValue(10)
        self.threshold_spin.setToolTip(
            "SOC % treated as a low-battery event on this tab. Save remembers it."
        )
        apply_spin_field_motif(self.threshold_spin, width=72)
        self.threshold_spin.setProperty("_pm_spin_motif_w", 72)
        ctrl_layout.addWidget(self.threshold_spin)
        ctrl_layout.addWidget(QLabel("AC charge stop %:"))
        self.charge_stop_spin = QSpinBox()
        self.charge_stop_spin.setRange(0, 100)
        self.charge_stop_spin.setValue(100)
        self.charge_stop_spin.setToolTip(
            "Target stop SOC for Growatt MIX forced AC charging "
            "(wchargeSOCLowLimit). Save keeps this as the dashboard default. "
            "Set on inverter writes it to the inverter via Growatt cloud."
        )
        apply_spin_field_motif(self.charge_stop_spin)
        self.charge_stop_spin.valueChanged.connect(self._on_charge_stop_edited)
        ctrl_layout.addWidget(self.charge_stop_spin)
        self.btn_save_config = QPushButton("Save")
        self.btn_save_config.setToolTip(
            "Save battery capacity, low-SOC threshold, and AC charge stop % "
            "on this computer. Does not write the inverter — use Set on inverter "
            "for that."
        )
        self.btn_save_config.clicked.connect(self._save_analysis_config)
        _apply_primary_button_style(self.btn_save_config)
        ctrl_layout.addWidget(self.btn_save_config)
        self.btn_set_charge_stop = QPushButton("Set on inverter")
        self.btn_set_charge_stop.setToolTip(
            "Read the current AC charge schedule from Growatt cloud, set stop SOC "
            "to the value above, and write it back. Keeps charge power and time "
            "periods unchanged."
        )
        self.btn_set_charge_stop.clicked.connect(self._write_inverter_charge_stop)
        ctrl_layout.addWidget(self.btn_set_charge_stop)
        self.lbl_inv_charge_stop = QLabel("Inverter stop: —")
        self.lbl_inv_charge_stop.setStyleSheet("color: #6c7086; font-size: 11px;")
        self.lbl_inv_charge_stop.setToolTip(
            "wchargeSOCLowLimit from the last cloud read (AC grid-charge schedule)."
        )
        ctrl_layout.addWidget(self.lbl_inv_charge_stop)
        self.chk_soc_rate = QCheckBox("SOC change/hour")
        self.chk_soc_rate.setToolTip(
            "Overlay ΔSOC %/h (right axis) on the State of Charge chart."
        )
        self.chk_soc_rate.setChecked(self._soc_rate_saved_pref())
        self.chk_soc_rate.toggled.connect(self._on_soc_rate_toggled)
        ctrl_layout.addWidget(self.chk_soc_rate)
        self.fetch_btn = QPushButton("Fetch Battery History")
        self.fetch_btn.setToolTip(
            "Load SOC and power for the selected day range from Grott logs "
            "and/or Growatt cloud."
        )
        self.fetch_btn.clicked.connect(self.fetch_history)
        _apply_primary_button_style(self.fetch_btn)
        ctrl_layout.addWidget(self.fetch_btn)
        ctrl_layout.addSpacing(12)
        lbl_every = QLabel("Refresh every:")
        lbl_every.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        lbl_every.setToolTip(
            "How often to re-fetch battery history. 0 = Off. Remembered."
        )
        ctrl_layout.addWidget(lbl_every)
        self.sp_refresh_min = QSpinBox()
        self.sp_refresh_min.setRange(0, 120)
        self.sp_refresh_min.setSpecialValueText("Off")
        self.sp_refresh_min.setToolTip(
            "Minutes between automatic history fetches. Off (0) stops the timer. "
            "Fetch Battery History still works at any time."
        )
        apply_spin_field_motif(self.sp_refresh_min)
        self.sp_refresh_min.valueChanged.connect(self._on_refresh_interval_changed)
        ctrl_layout.addWidget(self.sp_refresh_min)
        lbl_min = QLabel("min")
        lbl_min.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        lbl_min.setStyleSheet(f"color: {_DARK_SUBTEXT};")
        ctrl_layout.addWidget(lbl_min)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"color: {_UI_BLUE};")
        ctrl_layout.addWidget(self.progress_label)
        ctrl_layout.addStretch()
        top_layout.addWidget(ctrl_box)

        # Charts + events table
        content_splitter = QSplitter(Qt.Horizontal)

        chart_widget = QWidget()
        chart_layout = QVBoxLayout(chart_widget)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        self.fig = Figure(figsize=(10, 6), dpi=100)
        self.ax_soc = self.fig.add_subplot(211)
        self.ax_power = self.fig.add_subplot(212, sharex=self.ax_soc)
        self.ax_soc.tick_params(labelbottom=False)
        self.canvas = FigureCanvas(self.fig)
        self.cursor_info_label = QLabel("Hover over charts for time-slot readings.")
        self.cursor_info_label.setFont(QFont('Courier', 9))
        self.cursor_info_label.setStyleSheet(
            "color: #cdd6f4; padding: 6px; background: transparent; border: 1px solid #45475a; border-radius: 4px;"
        )
        self.cursor_info_label.setWordWrap(True)
        self.cursor_info_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setMinimumHeight(240)
        chart_layout.addWidget(self.canvas, 1)
        toolbar = DarkNavigationToolbar(self.canvas, self)
        chart_layout.addWidget(toolbar, 0)
        chart_layout.addWidget(self.cursor_info_label, 0)
        self._battery_motion_cid = self.canvas.mpl_connect('motion_notify_event', self._on_battery_canvas_motion)
        self._battery_resize_cid = self.canvas.mpl_connect('resize_event', self._on_battery_canvas_resize)
        self._chart_shimmer = ChartShimmerOverlay(self.canvas)
        content_splitter.addWidget(chart_widget)

        events_box = QGroupBox("Low SOC Events")
        events_layout = QVBoxLayout(events_box)
        events_layout.setContentsMargins(8, 8, 8, 8)
        self.events_tree = QTreeWidget()
        self.events_tree.setHeaderLabels(['Time', 'Min SOC %', 'Duration', 'Avg Load kW', 'Grid kWh'])
        self.events_tree.setColumnCount(5)
        self.events_tree.setColumnWidth(0, 110)
        self.events_tree.setColumnWidth(1, 65)
        self.events_tree.setColumnWidth(2, 65)
        self.events_tree.setColumnWidth(3, 70)
        self.events_tree.setColumnWidth(4, 65)
        self.events_tree.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding,
        )
        self.events_tree.setRootIsDecorated(False)
        self.events_tree.setAlternatingRowColors(True)
        qtree_set_column_width_key(self.events_tree, "battery_analysis_events")
        qtree_prepare_interactive_columns(self.events_tree)
        qtree_restore_column_widths(self.events_tree, "battery_analysis_events", resize_if_no_saved=True)
        qtree_attach_column_width_persistence(self.events_tree)
        events_layout.addWidget(self.events_tree, 1)
        content_splitter.addWidget(events_box)
        content_splitter.setStretchFactor(0, 3)
        content_splitter.setStretchFactor(1, 1)
        top_layout.addWidget(content_splitter, 1)
        splitter.addWidget(top_widget)

        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        insights_box = QGroupBox("Optimization Insights")
        insights_layout = QVBoxLayout(insights_box)
        self.insights_text = QTextEdit()
        self.insights_text.setReadOnly(True)
        self.insights_text.setFont(QFont('Helvetica', 10))
        insights_layout.addWidget(self.insights_text)
        bottom_layout.addWidget(insights_box)
        splitter.addWidget(bottom_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)

    def apply_from_app_params(self):
        if self.app_params is not None:
            p = self.app_params
            self.threshold_spin.blockSignals(True)
            self.threshold_spin.setValue(int(p.battery_low_soc_threshold_pct))
            self.threshold_spin.blockSignals(False)
            self.soc_threshold = int(self.threshold_spin.value())
        self.sync_capacity_from_live()

    def auto_start(self):
        """Load battery history once when the dashboard starts."""
        self.sync_capacity_from_live()
        self.fetch_history()

    def _settings(self):
        return QSettings("PowerModel", "EnergyDashboard2")

    def _load_refresh_interval(self):
        raw = self._settings().value("battery_analysis/refresh_min", 0)
        try:
            mins = int(raw)
        except (TypeError, ValueError):
            mins = 0
        mins = max(0, min(120, mins))
        self.sp_refresh_min.blockSignals(True)
        self.sp_refresh_min.setValue(mins)
        self.sp_refresh_min.blockSignals(False)

    def _on_refresh_interval_changed(self, mins: int):
        self._settings().setValue("battery_analysis/refresh_min", int(mins))
        self._apply_refresh_timer()

    def _apply_refresh_timer(self):
        mins = int(self.sp_refresh_min.value())
        if mins <= 0:
            self._refresh_timer.stop()
            return
        self._refresh_timer.start(mins * 60 * 1000)

    def _on_refresh_timer(self):
        if self.fetching:
            return
        self.fetch_history()

    _QS_CAPACITY = "battery_analysis/capacity_kwh"
    _QS_CHARGE_STOP = "battery_analysis/charge_stop_pct"

    def _on_capacity_edited(self, _val=None):
        self._capacity_dirty = True
        self.battery_capacity = float(self.capacity_spin.value())

    def _on_charge_stop_edited(self, _val=None):
        self._charge_stop_dirty = True

    def _growatt_live_capacity_kwh(self) -> float | None:
        getter = getattr(self.growatt_tab, "get_live_battery_capacity_kwh", None)
        if not callable(getter):
            return None
        try:
            cap = getter()
        except Exception:
            return None
        try:
            v = float(cap)
        except (TypeError, ValueError):
            return None
        return v if v > 0 else None

    def sync_capacity_from_live(self) -> None:
        """Fill Battery Capacity from Growatt Live Status unless the user saved/edited it."""
        s = self._settings()
        if s.contains(self._QS_CAPACITY):
            try:
                saved = float(s.value(self._QS_CAPACITY))
            except (TypeError, ValueError):
                saved = None
            if saved is not None and saved > 0 and not self._capacity_dirty:
                self.capacity_spin.blockSignals(True)
                self.capacity_spin.setValue(saved)
                self.capacity_spin.blockSignals(False)
                self.battery_capacity = float(saved)
                self.capacity_spin.setToolTip(
                    "Saved pack size for this tab. Growatt Live Status is the "
                    "default until you Save a different value here."
                )
                return
        if self._capacity_dirty:
            return
        live = self._growatt_live_capacity_kwh()
        if live is not None:
            self.capacity_spin.blockSignals(True)
            self.capacity_spin.setValue(live)
            self.capacity_spin.blockSignals(False)
            self.battery_capacity = float(live)
            self.capacity_spin.setToolTip(
                f"Default from Growatt Live Status ({live:.1f} kWh). "
                "Change it here if you need a different figure; Save to keep it."
            )
            return
        if self.app_params is not None:
            val = float(self.app_params.battery_capacity_kwh)
            self.capacity_spin.blockSignals(True)
            self.capacity_spin.setValue(val)
            self.capacity_spin.blockSignals(False)
            self.battery_capacity = val
            self.capacity_spin.setToolTip(
                "Growatt Live Status has not reported a pack size yet; "
                "showing the Setup default. Save to keep a value of your own."
            )

    def _load_analysis_config(self):
        s = self._settings()
        self.sync_capacity_from_live()
        if self.app_params is not None:
            self.threshold_spin.blockSignals(True)
            self.threshold_spin.setValue(int(self.app_params.battery_low_soc_threshold_pct))
            self.threshold_spin.blockSignals(False)
            self.soc_threshold = int(self.threshold_spin.value())
        if s.contains(self._QS_CHARGE_STOP):
            try:
                stop = int(float(s.value(self._QS_CHARGE_STOP)))
            except (TypeError, ValueError):
                stop = None
            if stop is not None:
                stop = max(0, min(100, stop))
                self.charge_stop_spin.blockSignals(True)
                self.charge_stop_spin.setValue(stop)
                self.charge_stop_spin.blockSignals(False)

    def _save_analysis_config(self):
        cap = float(self.capacity_spin.value())
        thr = int(self.threshold_spin.value())
        stop = int(self.charge_stop_spin.value())
        self.battery_capacity = cap
        self.soc_threshold = float(thr)
        s = self._settings()
        s.setValue(self._QS_CAPACITY, cap)
        s.setValue(self._QS_CHARGE_STOP, stop)
        s.setValue("params/battery_capacity_kwh", cap)
        s.setValue("params/battery_low_soc_threshold_pct", thr)
        s.sync()
        self._capacity_dirty = False
        self._charge_stop_dirty = False
        if self.app_params is not None:
            self.app_params.battery_capacity_kwh = cap
            self.app_params.battery_low_soc_threshold_pct = float(thr)
        dash = self.dash
        if dash is not None:
            pt = getattr(dash, "parameters_tab", None)
            if pt is not None and getattr(pt, "sp_cap", None) is not None:
                pt.sp_cap.blockSignals(True)
                pt.sp_cap.setValue(cap)
                pt.sp_cap.blockSignals(False)
            if pt is not None and getattr(pt, "sp_soc_thr", None) is not None:
                pt.sp_soc_thr.blockSignals(True)
                pt.sp_soc_thr.setValue(thr)
                pt.sp_soc_thr.blockSignals(False)
            at = getattr(dash, "analytics_tab", None)
            if at is not None and hasattr(at, "apply_from_app_params"):
                try:
                    at.apply_from_app_params()
                except Exception:
                    pass
        self.set_status(
            f"Battery Analysis: saved capacity {cap:.1f} kWh, low-SOC {thr}%, "
            f"AC charge stop {stop}% (local). Use Set on inverter to write stop SOC."
        )

    def _cloud_api(self):
        """Return (api, plant_id, sn) using live session or cached Growatt cloud auth."""
        api, plant_id, sn = self.growatt_tab.get_api()
        if api and sn:
            return api, plant_id, sn
        getter = getattr(self.growatt_tab, "get_cloud_session", None)
        if callable(getter):
            api2, sn2, plant_id2 = getter()
            if api2 and sn2:
                return api2, plant_id2, sn2
        return api, plant_id, sn

    def _on_day_range_changed(self, _days: int):
        """Day-range radios used to leave a stale chart until Fetch was clicked."""
        self.fetch_history()

    def fetch_history(self):
        api, plant_id, device_sn = self.growatt_tab.get_api()
        try:
            self.battery_capacity = float(self.capacity_spin.value())
            self.soc_threshold = float(self.threshold_spin.value())
        except (TypeError, ValueError):
            QMessageBox.critical(self, "Invalid Input", "Battery capacity and threshold must be numbers.")
            return
        if self.fetching:
            # Previous fetch may have wedged (shared DB conn hang). Allow retry.
            self.fetching = False
            self.fetch_btn.setEnabled(True)
            try:
                self._chart_shimmer.stop()
            except Exception:
                pass
        self.fetching = True
        self.fetch_btn.setEnabled(False)
        self._chart_shimmer.start()
        threading.Thread(target=self._fetch_thread, args=(api, plant_id, device_sn), daemon=True).start()

    def _fetch_thread(self, api, plant_id, device_sn):
        try:
            days = self.days_group.checkedId()
            api_records = []
            for i in range(days):
                day_offset = days - 1 - i
                date = datetime.now() - timedelta(days=day_offset)
                date_str = date.strftime('%Y-%m-%d')
                self._inv.invoke(lambda ds=date_str, d=day_offset: (
                    self.progress_label.setText(f"Fetching {ds} ({days - d}/{days})..."),
                    self.set_status(f"Battery Analysis: fetching {ds}...")
                ))
            if api is not None and plant_id is not None and device_sn:
                try:
                    api_records = fetch_mix_chart_range(api, device_sn, plant_id, days)
                except Exception as e:
                    _log.warn("BatteryAnalysis", f"Growatt chart fetch failed: {e}")
            else:
                _log.info(
                    "BatteryAnalysis",
                    "Growatt cloud API unavailable; using local logged telemetry if present.",
                )
            db_records = []
            readings_records = []
            dl = getattr(self.dash, "data_logger", None) if self.dash else None
            if dl is not None:
                if api_records and device_sn:
                    dl.log_growatt_mix_chart(device_sn, api_records)
                # Always load local readings when available — they carry measured
                # SOC. Prefer them over MIX-chart-only reconstruction: a cloud
                # MIX fetch used to short-circuit this path and leave the chart
                # pinned at 0 % for hours with a fake "low SOC" event.
                try:
                    readings_records = dl.query_growatt_battery_history_from_readings(days)
                except Exception as e:
                    _log.warn("BatteryAnalysis", f"Readings history DB read failed: {e}")
                    readings_records = []
                if device_sn:
                    try:
                        db_records = dl.query_growatt_mix_chart(device_sn, days)
                    except Exception as e:
                        _log.warn("BatteryAnalysis", f"MIX chart DB read failed: {e}")
                        db_records = []

            power_records = self._combine_power_records(api_records, db_records)
            power_label = (
                "Growatt cloud + stored MIX"
                if api_records and db_records
                else "Growatt cloud"
                if api_records
                else "stored MIX chart"
                if db_records
                else None
            )
            df, source = self._build_history_frame(
                power_records, power_label, readings_records,
            )
            if df is None or df.empty:
                hint = (
                    "No local Growatt/GROTT history in the database for this range yet. "
                    "Leave the dashboard running with GROTT MQTT selected so "
                    "growatt_readings can accumulate, or connect Growatt cloud for "
                    "MIX-chart history."
                    if api is None
                    else "No chart data returned from Growatt or local database."
                )
                self._inv.invoke(lambda msg=hint: self._fetch_done_error(msg))
                return
            current_soc = self.growatt_tab.get_current_soc()
            df = self._reconstruct_soc(df, current_soc)
            # Coulomb-counted SOC drifts and pins at 0 % — do not invent
            # "Low SOC Events" from that artefact.
            if getattr(self, '_soc_is_reconstructed', False):
                self.low_soc_events = []
            else:
                self.low_soc_events = self._detect_low_soc(df)
            insights = self._generate_insights(df)
            self._inv.invoke(lambda: self._update_display(df, insights, source))
        except Exception as e:
            err = str(e)
            _log.warn("BatteryAnalysis", f"Fetch failed: {err}")
            self._inv.invoke(lambda msg=err: self._fetch_done_error(f"Error: {msg}"))

    @staticmethod
    def _normalise_history_timestamps(df):
        out = df.copy()
        out['timestamp'] = pd.to_datetime(out['timestamp'], errors='coerce')
        if getattr(out['timestamp'].dt, 'tz', None) is not None:
            out['timestamp'] = out['timestamp'].dt.tz_convert('UTC').dt.tz_localize(None)
        return out.dropna(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)

    @staticmethod
    def _combine_power_records(api_records, db_records):
        """Cloud MIX wins on the same timestamp; stored MIX fills the rest."""
        by_ts = {}
        for rec in list(db_records or []) + list(api_records or []):
            ts = rec.get("timestamp")
            if ts is None:
                continue
            ts = pd.Timestamp(ts)
            if ts.tzinfo is not None:
                ts = ts.tz_convert("UTC").tz_localize(None)
            by_ts[ts] = rec
        return [by_ts[k] for k in sorted(by_ts)]

    def _build_history_frame(self, power_records, power_label, readings_records):
        """Prefer measured SOC from local readings; use MIX as a dense power grid.

        Returns ``(df, source_label)`` or ``(None, "")`` when nothing usable.
        """
        power_df = None
        readings_df = None
        if power_records:
            power_df = self._normalise_history_timestamps(pd.DataFrame(power_records))
        if readings_records:
            readings_df = self._normalise_history_timestamps(pd.DataFrame(readings_records))
            if 'soc_pct' in readings_df.columns:
                readings_df['soc_pct'] = pd.to_numeric(
                    readings_df['soc_pct'], errors='coerce',
                ).clip(0.0, 100.0)
            readings_df = self._break_impossible_soc_jumps(
                readings_df, capacity_kwh=float(self.battery_capacity or 13.0),
            )

        if readings_df is not None and not readings_df.empty:
            if power_df is not None and not power_df.empty:
                readings_df = self._union_readings_and_mix(readings_df, power_df)
                label = f"local readings + {power_label or 'MIX'} power"
            else:
                label = "local GROTT/Growatt readings"
            return readings_df.reset_index(drop=True), label

        if power_df is not None and not power_df.empty:
            return power_df, power_label or "MIX chart (power only)"
        return None, ""

    # MIX chart is on 5-minute boundaries; Grott readings land on arbitrary
    # seconds. An outer union keeps both cadences, so PV zig-zags between two
    # values and fill_between looks like a shadow. Drop MIX-only rows when a
    # local reading is already within half a MIX slot.
    _MIX_NEAR_READING_S = 150.0

    @staticmethod
    def _union_readings_and_mix(readings_df, power_df):
        """Union Grott reading timestamps with MIX 5-minute power slots.

        Local rows keep measured SOC. MIX-only slots take MIX power and hold
        the last measured SOC when the next measured SOC is still a plateau
        (the live logger used to skip unchanged snapshots, which left overnight
        holes). A real SOC change across a long hole stays blank.

        MIX-only rows within ``_MIX_NEAR_READING_S`` of a local reading are
        dropped so power traces are not drawn at two cadences at once.
        """
        power_cols = [
            c for c in (
                'pv_kW', 'charge_kW', 'discharge_kW',
                'grid_import_kW', 'grid_export_kW', 'load_kW',
            )
            if c in power_df.columns or c in readings_df.columns
        ]
        r = readings_df.drop_duplicates('timestamp', keep='last').sort_values('timestamp')
        p = power_df.drop_duplicates('timestamp', keep='last').sort_values('timestamp')
        mix_cols = ['timestamp'] + [c for c in power_cols if c in p.columns]
        merged = pd.merge(
            r, p[mix_cols], on='timestamp', how='outer', suffixes=('', '_mix'),
        ).sort_values('timestamp').reset_index(drop=True)
        for c in power_cols:
            mix_c = f'{c}_mix'
            if mix_c in merged.columns:
                if c in merged.columns:
                    merged[c] = pd.to_numeric(merged[c], errors='coerce')
                    merged[c] = merged[c].where(merged[c].notna(), merged[mix_c])
                else:
                    merged[c] = merged[mix_c]
                merged.drop(columns=[mix_c], inplace=True, errors='ignore')
        if 'soc_pct' not in merged.columns:
            return merged
        soc = pd.to_numeric(merged['soc_pct'], errors='coerce')
        held = soc.copy()
        known = soc.dropna()
        idxs = list(known.index)
        for a, b in zip(idxs, idxs[1:]):
            if b <= a + 1:
                continue
            sa = float(soc.iloc[a])
            sb = float(soc.iloc[b])
            if abs(sa - sb) <= 3.0:
                held.iloc[a + 1:b] = sa
        merged['soc_pct'] = held
        reading_ts = pd.to_datetime(r['timestamp'], errors='coerce').dropna()
        if not reading_ts.empty and len(merged) > len(r):
            on_reading = merged['timestamp'].isin(reading_ts)
            mix_only = ~on_reading
            if mix_only.any():
                tol = pd.Timedelta(seconds=BatteryAnalysisTab._MIX_NEAR_READING_S)
                rt = reading_ts.sort_values()

                def _near_local_reading(ts):
                    return (rt - ts).abs().min() <= tol

                near = merged.loc[mix_only, 'timestamp'].map(_near_local_reading)
                drop_idx = near[near].index
                if len(drop_idx):
                    merged = merged.drop(index=drop_idx).reset_index(drop=True)
        return merged

    @staticmethod
    def _overlay_mix_power(readings_df, power_df):
        """Fill NaN / missing power on readings from nearest MIX row."""
        power_cols = [
            c for c in (
                'pv_kW', 'charge_kW', 'discharge_kW',
                'grid_import_kW', 'grid_export_kW', 'load_kW',
            )
            if c in power_df.columns
        ]
        if not power_cols:
            return readings_df
        mix = power_df[['timestamp'] + power_cols].sort_values('timestamp')
        base = readings_df.sort_values('timestamp')
        merged = pd.merge_asof(
            base, mix, on='timestamp', direction='nearest',
            tolerance=pd.Timedelta('10min'), suffixes=('', '_mix'),
        )
        for c in power_cols:
            mix_c = f'{c}_mix'
            if mix_c not in merged.columns:
                continue
            if c in merged.columns:
                merged[c] = pd.to_numeric(merged[c], errors='coerce')
                merged[c] = merged[c].where(merged[c].notna(), merged[mix_c])
            else:
                merged[c] = merged[mix_c]
            merged.drop(columns=[mix_c], inplace=True, errors='ignore')
        return merged

    @staticmethod
    def _break_impossible_soc_jumps(df, *, capacity_kwh: float, max_kw: float = 8.0):
        """NaN SOC samples that jump faster than the pack can physically move.

        A 13 kWh pack at 8 kW max moves ~61 %/h. A 64%→37% step in 3 minutes
        is ~540 %/h and is always a frozen-feed artefact, not real discharge.
        """
        if df is None or df.empty or 'soc_pct' not in df.columns:
            return df
        out = df.copy()
        soc = pd.to_numeric(out['soc_pct'], errors='coerce')
        ts = pd.to_datetime(out['timestamp'], errors='coerce')
        dt_h = ts.diff().dt.total_seconds() / 3600.0
        dsoc = soc.diff()
        cap = max(1.0, float(capacity_kwh or 13.0))
        max_pp_h = (float(max_kw) / cap) * 100.0 * 1.5  # 50% headroom
        rate = (dsoc.abs() / dt_h).replace([np.inf, -np.inf], np.nan)
        bad = (dt_h > 0) & rate.notna() & (rate > max_pp_h)
        n_bad = int(bad.sum())
        if n_bad:
            out.loc[bad, 'soc_pct'] = np.nan
            _log.info(
                "BatteryAnalysis",
                f"Blanked {n_bad} impossible SOC jump(s) "
                f"(>{max_pp_h:.0f} %/h for {cap:.1f} kWh).",
            )
        return out

    def _reconstruct_soc(self, df, current_soc):
        capacity = self.battery_capacity
        if 'soc_pct' in df.columns and df['soc_pct'].notna().any():
            # Measured SOC present (local growatt_readings, possibly overlaid
            # onto denser MIX power). Interpolate only between real samples —
            # never coulomb-count on top, which is what used to pin early
            # history at 0 % and invent a multi-hour "low SOC" event.
            df = df.copy()
            df['soc_pct'] = pd.to_numeric(df['soc_pct'], errors='coerce').clip(0.0, 100.0)
            # Only bridge tiny gaps (a couple of samples). Do not paint across
            # missing Grott stretches — those should stay as holes.
            df['soc_pct'] = df['soc_pct'].interpolate(limit=2, limit_area='inside')
            df['soc_kWh'] = (df['soc_pct'] / 100.0) * capacity
            self._soc_is_reconstructed = False
            return df
        # No measured SOC in this source (stored MIX-chart rows carry power
        # only). Everything below is an *integration* of charge − discharge
        # anchored to the live SOC, clamped to [0, capacity] each step, so
        # errors accumulate and long runs can pin to 0 %. Flagged so the chart
        # and insights never present it as a measurement.
        self._soc_is_reconstructed = True
        df = df.copy()
        # Use actual sample spacing when available; MIX is usually 5 min but
        # local readings can be denser/sparser — a fixed 5 min step made
        # reconstruction drift faster than the real pack.
        ts = pd.to_datetime(df['timestamp'], errors='coerce')
        dt_h = ts.diff().dt.total_seconds() / 3600.0
        median_dt = float(dt_h.dropna().median()) if dt_h.notna().any() else (5.0 / 60.0)
        if not np.isfinite(median_dt) or median_dt <= 0:
            median_dt = 5.0 / 60.0
        dt_h = dt_h.fillna(median_dt).clip(lower=1.0 / 60.0, upper=0.5)
        df['energy_delta_kWh'] = (df['charge_kW'] - df['discharge_kW']) * dt_h
        if current_soc is not None:
            soc_values = [0.0] * len(df)
            soc_values[-1] = current_soc / 100.0 * capacity
            for i in range(len(df) - 2, -1, -1):
                soc_values[i] = soc_values[i + 1] - df.iloc[i + 1]['energy_delta_kWh']
                soc_values[i] = max(0.0, min(capacity, soc_values[i]))
            df['soc_kWh'] = soc_values
        else:
            soc_values = [0.0] * len(df)
            soc_values[0] = capacity * 0.5
            for i in range(1, len(df)):
                soc_values[i] = soc_values[i - 1] + df.iloc[i]['energy_delta_kWh']
                soc_values[i] = max(0.0, min(capacity, soc_values[i]))
            df['soc_kWh'] = soc_values
        df['soc_pct'] = (df['soc_kWh'] / capacity) * 100.0
        return df

    def _detect_low_soc(self, df):
        threshold = self.soc_threshold
        events = []
        in_event = False
        event_start = None
        event_rows = []
        for _, row in df.iterrows():
            soc = pd.to_numeric(row.get('soc_pct'), errors='coerce')
            if pd.isna(soc):
                continue
            if soc < threshold:
                if not in_event:
                    in_event = True
                    event_start = pd.to_datetime(row['timestamp'], errors='coerce')
                    event_rows = []
                event_rows.append(row)
            elif in_event:
                self._close_low_soc_event(events, event_start, event_rows)
                in_event = False
                event_rows = []
        if in_event and event_rows:
            self._close_low_soc_event(events, event_start, event_rows)
        return events

    @staticmethod
    def _close_low_soc_event(events, event_start, event_rows):
        if not event_rows or event_start is None or pd.isna(event_start):
            return
        event_end = pd.to_datetime(event_rows[-1]['timestamp'], errors='coerce')
        if pd.isna(event_end):
            return
        duration_min = (event_end - event_start).total_seconds() / 60
        min_soc = min(
            float(pd.to_numeric(r['soc_pct'], errors='coerce')) for r in event_rows
        )
        avg_load = float(np.mean([
            float(pd.to_numeric(r.get('load_kW'), errors='coerce') or 0.0)
            for r in event_rows
        ]))
        grid_kwh = sum(
            float(pd.to_numeric(r.get('grid_import_kW'), errors='coerce') or 0.0)
            * (5.0 / 60.0)
            for r in event_rows
        )
        events.append({
            'start': pd.Timestamp(event_start),
            'end': pd.Timestamp(event_end),
            'min_soc': min_soc,
            'duration_min': duration_min,
            'avg_load_kW': avg_load,
            'grid_import_kWh': grid_kwh,
        })

    def _generate_insights(self, df):
        lines = []
        threshold = self.soc_threshold
        capacity = self.battery_capacity
        days = self.days_group.checkedId()
        recon = bool(getattr(self, '_soc_is_reconstructed', False))
        # Energy accounting first — these come straight from measured power,
        # so they stay valid even when SOC had to be reconstructed.
        util = summarise_solar_utilisation(df)
        if util["days"]:
            lines.append("--- Solar utilisation (measured power) ---")
            lines.append(
                f"{'Date':<12}{'PV kWh':>8}{'Load kWh':>10}{'Spare kWh':>11}"
                f"{'Charged':>9}{'Base kW':>9}{'Peak kW':>9}"
            )
            for row in util["days"]:
                lines.append(
                    f"{str(row['date']):<12}{row['pv_kwh']:>8.1f}{row['load_kwh']:>10.1f}"
                    f"{row['surplus_kwh']:>11.2f}{row['charged_kwh']:>9.2f}"
                    f"{row['base_load_kw']:>9.2f}{row['peak_load_kw']:>9.2f}"
                )
            spare = util["surplus_kwh"]
            got = util["charged_kwh"]
            if spare > 0.5:
                lines.append(
                    f"Spare PV (after house load) {spare:.1f} kWh vs {got:.1f} kWh "
                    f"charged — {min(100.0, 100.0 * got / spare):.0f}% of the available "
                    "surplus captured."
                )
                if got > spare * 1.05:
                    lines.append(
                        f"  (Charge exceeds solar surplus by {got - spare:.1f} kWh, so "
                        "the battery was also being AC-charged from the grid.)"
                    )
            else:
                lines.append(
                    f"Spare PV after house load was only {spare:.2f} kWh over this period: "
                    "the house consumed essentially all generation, so solar could not "
                    "refill the battery regardless of inverter settings."
                )
            worst = max(util["days"], key=lambda r: r["load_kwh"] - r["pv_kwh"])
            lines.append(
                f"Biggest shortfall {worst['date']}: load {worst['load_kwh']:.1f} kWh vs "
                f"PV {worst['pv_kwh']:.1f} kWh (base load {worst['base_load_kw']:.2f} kW "
                f"≈ {worst['base_load_kw'] * 24:.1f} kWh/day before anything is switched on)."
            )
            lines.append("")
        if recon:
            lines.append(
                "NOTE: this source has no measured SOC — the SOC trace and "
                "discharge depth below are INTEGRATED from charge/discharge "
                "power and anchored to the current SOC, so they drift and can "
                "pin at 0%. Low-SOC events are suppressed for reconstructed "
                "traces. Leave GROTT logging running so growatt_readings can "
                "supply real SOC; trust the energy table above meanwhile."
            )
            lines.append("")
        daily_groups = df.groupby(df['timestamp'].dt.date)
        daily_depths = []
        depletion_times = []
        for date, group in daily_groups:
            daily_depths.append(group['soc_pct'].max() - group['soc_pct'].min())
            below = group[group['soc_pct'] < threshold]
            if not below.empty:
                depletion_times.append(below.iloc[0]['timestamp'])
        avg_depth = np.mean(daily_depths) if daily_depths else 0
        lines.append(f"Average daily discharge depth: {avg_depth:.1f}% ({avg_depth / 100 * capacity:.1f} kWh)")
        num_events = len(self.low_soc_events)
        lines.append(f"Times battery hit <{threshold}% in {days} days: {num_events}")
        if depletion_times:
            avg_hour = np.mean([t.hour + t.minute / 60.0 for t in depletion_times])
            h, m = int(avg_hour), int((avg_hour - int(avg_hour)) * 60)
            lines.append(f"Average time battery depleted: {h:02d}:{m:02d}")
        else:
            lines.append("Battery did not drop below threshold in this period.")
        total_grid = sum(e['grid_import_kWh'] for e in self.low_soc_events)
        lines.append(f"Grid import while battery <{threshold}%: {total_grid:.2f} kWh")
        discharge_by_hour = df.groupby(df['timestamp'].dt.hour)['discharge_kW'].mean()
        if not discharge_by_hour.empty:
            peak_hour = discharge_by_hour.idxmax()
            lines.append(f"Peak average discharge hour: {peak_hour:02d}:00 ({discharge_by_hour.max():.2f} kW avg)")
        rate = self._soc_change_per_hour(
            df, capacity_kwh=float(self.battery_capacity or 13.0),
        )
        if rate.notna().any():
            peak_chg = float(rate.max())
            peak_dsch = float(rate.min())
            lines.append(
                f"Peak SOC change rate: charge {peak_chg:+.1f} %/h, "
                f"discharge {peak_dsch:+.1f} %/h"
            )
        sun_waste = scan_history_sun_waste(df, min_minutes=30.0)
        lines.append("")
        if sun_waste:
            lines.append("--- Spare PV that did NOT charge the battery ---")
            lines.append(
                f"{len(sun_waste)} window(s) ≥30 min with ≥1 kW spare PV "
                "(PV minus house load) while charge was ≈ 0:"
            )
            for ev in sun_waste[:5]:
                st = ev["start"]
                st_s = st.strftime("%m-%d %H:%M") if hasattr(st, "strftime") else str(st)
                lines.append(
                    f"  {st_s}  {ev['duration_min']:.0f} min  "
                    f"avg PV {ev['avg_pv_kW']:.2f} kW − load {ev['avg_load_kW']:.2f} kW, "
                    f"charge {ev['avg_charge_kW']:.2f} kW"
                )
            lines.append(
                "  → Real surplus was available and unused: check inverter charge/export "
                "priority, forced discharge windows and BMS charge limits."
            )
        else:
            lines.append(
                "No windows found where spare PV went uncharged — whenever generation "
                "exceeded house load, the battery did take it. Low SOC in this period "
                "is a consumption problem, not a charging fault."
            )
        lines.append("")
        lines.append("--- Recommendations ---")
        if sun_waste:
            lines.append(
                "Enable Setup → Battery alarms so the live banner / desktop warn you "
                "next time spare PV is not charging."
            )
        elif util["days"] and util["surplus_kwh"] < max(1.0, 0.1 * sum(
            r["pv_kwh"] for r in util["days"]
        )):
            lines.append(
                "Find the standing load first: base load above ~0.5 kW dominates the "
                "daily budget. Check Tasmota per-device history and immersion / heat "
                "pump schedules, then shift what remains into the solar window."
            )
        if num_events > days * 0.5:
            lines.append("Battery regularly hits low threshold. May be undersized for evening usage.")
        if df['soc_pct'].min() > 50:
            lines.append("Battery rarely drops below 50%. Capacity exceeds typical daily needs.")
        if not discharge_by_hour.empty:
            top_hours = discharge_by_hour.nlargest(3)
            if top_hours.index.max() - top_hours.index.min() <= 3:
                lines.append("Most discharge in a narrow window. Consider shifting loads to solar peak.")
        if num_events == 0 and avg_depth < 40:
            lines.append("Battery is well-sized for current usage patterns.")
        return "\n".join(lines)

    def _update_display(self, df, insights, source="Growatt cloud"):
        try:
            self._chart_shimmer.stop()
            self.fetching = False
            self.fetch_btn.setEnabled(True)
            self.progress_label.setText("")
            # Mark fresh BEFORE rendering — a downstream render exception must
            # not swallow the freshness signal.  See AnalyticsTab._update_display
            # for the same defensive pattern.
            if self.on_data_updated:
                try:
                    self.on_data_updated()
                except Exception as e:
                    _log.warn("BatteryAnalysis", f"on_data_updated callback failed: {e}")
            self._draw_charts(df)
            self._populate_events_table()
            self.insights_text.setPlainText(insights)
            self.set_status(
                f"Battery Analysis: {len(df)} points from {source}, "
                f"{len(self.low_soc_events)} low SOC events"
            )
            self._read_inverter_charge_stop_async()
        except Exception as e:
            self.fetching = False
            self.fetch_btn.setEnabled(True)
            try:
                self._chart_shimmer.stop()
            except Exception:
                pass
            _log.warn("BatteryAnalysis", f"Display update failed: {e}")
            self._fetch_done_error(f"Error drawing charts: {e}")

    def _fetch_done_error(self, msg):
        # Status line only. A modal box here blocks every tab and Close
        # until it is dismissed, including when the dialog is off-screen.
        self._chart_shimmer.stop()
        self.fetching = False
        self.fetch_btn.setEnabled(True)
        text = str(msg or "").strip() or "Battery history unavailable."
        self.progress_label.setText(text)
        self.set_status(text)

    _SOC_RATE_SETTINGS_KEY = "battery_analysis/show_soc_rate"
    _SOC_RATE_COLOR = '#8839ef'

    def _soc_rate_saved_pref(self) -> bool:
        try:
            return bool(QSettings("PowerModel", "EnergyDashboard2").value(
                self._SOC_RATE_SETTINGS_KEY, True, type=bool,
            ))
        except Exception:
            return True

    def _soc_rate_enabled(self) -> bool:
        chk = getattr(self, 'chk_soc_rate', None)
        if chk is not None:
            return chk.isChecked()
        return self._soc_rate_saved_pref()

    def _on_soc_rate_toggled(self, checked: bool):
        try:
            QSettings("PowerModel", "EnergyDashboard2").setValue(
                self._SOC_RATE_SETTINGS_KEY, bool(checked),
            )
        except Exception:
            pass
        df = getattr(self, '_battery_hover_df', None)
        if df is not None and len(df):
            self._draw_charts(df)

    # Left pad must clear the tick labels *and* the rotated axis title; the
    # right pad does the same for the ΔSOC %/h axis when it is shown.
    _BATTERY_CHART_LEFT_PAD_PX = 66
    _BATTERY_CHART_RIGHT_PAD_PX = 14
    _BATTERY_CHART_RIGHT_PAD_RATE_PX = 74

    def _apply_battery_chart_layout(self):
        """Pad both edges so the y-axis titles stay inside the canvas."""
        canvas_w = max(
            int(self.canvas.width()),
            int(self.fig.get_figwidth() * self.fig.dpi),
            1,
        )
        left = self._BATTERY_CHART_LEFT_PAD_PX / canvas_w
        right_pad = (
            self._BATTERY_CHART_RIGHT_PAD_RATE_PX
            if self._ax_soc_rate is not None
            else self._BATTERY_CHART_RIGHT_PAD_PX
        )
        right = 1.0 - (right_pad / canvas_w)
        self.fig.subplots_adjust(
            hspace=0.22, top=0.96, bottom=0.10,
            left=left, right=max(right, left + 0.4),
        )

    def _on_battery_canvas_resize(self, _event):
        if self._battery_hover_df is None:
            return
        self._apply_battery_chart_layout()
        self.canvas.draw_idle()

    @staticmethod
    def _soc_change_per_hour(
        df,
        *,
        window_minutes: float = 15.0,
        capacity_kwh: float = 13.0,
        max_kw: float = 8.0,
    ):
        """SOC slope in percentage points per hour over a rolling wall-clock window.

        Consecutive-sample ΔSOC/Δt is not a usable hourly rate: a 5 pp telemetry
        step in one minute is 300 %/h on the axis even though the pack cannot
        move that fast. Measure change over ``window_minutes`` of wall time and
        express it as %/h, then drop rates that exceed a physical bound for the
        configured capacity / max charge power.
        """
        if df is None or df.empty or 'timestamp' not in df.columns or 'soc_pct' not in df.columns:
            return pd.Series(dtype=float)
        ts = pd.to_datetime(df['timestamp'], errors='coerce')
        soc = pd.to_numeric(df['soc_pct'], errors='coerce')
        out = pd.Series(np.nan, index=df.index, dtype=float)
        work = pd.DataFrame({'ts': ts, 'soc': soc}, index=df.index).dropna()
        if len(work) < 2:
            return out
        work = work.sort_values('ts')
        tvals = work['ts'].to_numpy(dtype='datetime64[ns]')
        svals = work['soc'].to_numpy(dtype=float)
        win = np.timedelta64(int(max(1.0, float(window_minutes)) * 60.0), 's')
        hour = np.timedelta64(3600, 's')
        rates = np.full(len(work), np.nan, dtype=float)
        j = 0
        for i in range(len(work)):
            target = tvals[i] - win
            while j < i and tvals[j] < target:
                j += 1
            # Last sample at or before (t_i − window); else earliest prior sample.
            k = j - 1 if j > 0 else 0
            if k >= i:
                continue
            dt = tvals[i] - tvals[k]
            dt_h = float(dt / hour)
            if not np.isfinite(dt_h) or dt_h < (1.0 / 60.0):
                continue
            # Need a meaningful span — reject tiny lookbacks that inflate %/h.
            if dt_h < (float(window_minutes) / 60.0) * 0.4 and k == i - 1:
                # Only one previous sample and it is closer than ~40% of the
                # window: still allow if ≥ 5 minutes so sparse feeds work.
                if dt_h < (5.0 / 60.0):
                    continue
            rates[i] = (svals[i] - svals[k]) / dt_h

        cap = max(1.0, float(capacity_kwh or 13.0))
        # Physical ceiling (%/h) with modest headroom; never above 100 for the
        # display band the right-hand axis uses.
        max_pp_h = min(100.0, (float(max_kw) / cap) * 100.0 * 1.5)
        max_pp_h = max(25.0, max_pp_h)
        rates = np.where(np.abs(rates) > max_pp_h, np.nan, rates)
        out.loc[work.index] = rates
        return out.replace([np.inf, -np.inf], np.nan)

    _TELEMETRY_COLS = (
        'soc_pct', 'pv_kW', 'charge_kW', 'discharge_kW',
        'grid_import_kW', 'grid_export_kW', 'load_kW',
    )

    @staticmethod
    def _find_data_gaps(df, *, min_gap_minutes: float = 20.0):
        """(t_before, t_after) pairs where samples jump across a real hole.

        Unchanged telemetry at both ends is a held live sample (the logger
        used to skip bit-identical Grott snapshots). Draw that plateau; do
        not grey it as missing data.
        """
        if df is None or len(df) < 2:
            return []
        ts = pd.to_datetime(df['timestamp'], errors='coerce')
        if ts.notna().sum() < 2:
            return []
        dt_s = ts.diff().dt.total_seconds()
        med = float(dt_s.dropna().median()) if dt_s.notna().any() else 300.0
        gap_s = max(min_gap_minutes * 60.0, 6.0 * max(med, 1.0))
        cols = [
            c for c in BatteryAnalysisTab._TELEMETRY_COLS
            if c in df.columns
        ]
        gaps = []
        for i in range(1, len(df)):
            d = dt_s.iloc[i]
            if d is None or not np.isfinite(d) or d <= gap_s:
                continue
            same = True
            for c in cols:
                a = pd.to_numeric(df.iloc[i - 1][c], errors='coerce')
                b = pd.to_numeric(df.iloc[i][c], errors='coerce')
                if pd.isna(a) and pd.isna(b):
                    continue
                if pd.isna(a) or pd.isna(b) or abs(float(a) - float(b)) > 1e-3:
                    same = False
                    break
            if not same:
                gaps.append((ts.iloc[i - 1], ts.iloc[i]))
        return gaps

    @staticmethod
    def _insert_gap_breaks(df, gaps):
        """Insert a NaN row in each true gap so traces break instead of sloping."""
        if df is None or df.empty or not gaps:
            return df
        extra = []
        nan_row = {c: np.nan for c in df.columns}
        for t0, t1 in gaps:
            try:
                mid = t0 + (t1 - t0) / 2
            except TypeError:
                continue
            row = dict(nan_row)
            row['timestamp'] = mid
            extra.append(row)
        if not extra:
            return df
        out = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
        return out.sort_values('timestamp').reset_index(drop=True)

    _SOC_FILL_BANDS = (
        (lambda s: s < 20, '#f38ba8', 'SOC < 20%'),
        (lambda s: (s >= 20) & (s < 50), '#f9e2af', 'SOC 20–50%'),
        (lambda s: (s >= 50) & (s < 80), '#a6e3a1', 'SOC 50–80%'),
        (lambda s: s >= 80, '#40a02b', 'SOC ≥ 80%'),
    )

    @staticmethod
    def _annotate_data_gaps(ax, gaps, *, label=True):
        """Grey vertical bands over no-data windows, with an explanation."""
        import matplotlib.dates as mdates
        if not gaps:
            return
        x_lo, x_hi = ax.get_xlim()
        span = max(x_hi - x_lo, 1e-9)
        try:
            ax_px = float(ax.bbox.width)
        except Exception:
            ax_px = 800.0
        for t0, t1 in gaps:
            x0 = mdates.date2num(t0)
            x1 = mdates.date2num(t1)
            if x1 <= x_lo or x0 >= x_hi:
                continue
            ax.axvspan(x0, x1, color='#7f849c', alpha=0.15, zorder=1.5, lw=0)
            if not label:
                continue
            vis0, vis1 = max(x0, x_lo), min(x1, x_hi)
            width_px = (vis1 - vis0) / span * ax_px
            if width_px < 16:
                continue
            ax.text(
                (vis0 + vis1) / 2.0, 0.5,
                'No data',
                transform=ax.get_xaxis_transform(),
                ha='center', va='center',
                rotation=90 if width_px < 170 else 0,
                fontsize=7, color='#9399b2', alpha=0.95, zorder=6,
                clip_on=True,
            )

    def _draw_charts(self, df):
        import matplotlib.dates as mdates

        self.ax_soc.clear()
        self.ax_power.clear()
        if getattr(self, '_ax_soc_rate', None) is not None:
            try:
                self._ax_soc_rate.remove()
            except Exception:
                pass
            self._ax_soc_rate = None
        self.ax_soc.tick_params(labelbottom=False)
        threshold = self.soc_threshold
        df = df.copy().reset_index(drop=True)
        present = [c for c in self._TELEMETRY_COLS if c in df.columns]
        # Rows with no telemetry at all just split the traces for no reason —
        # drop them, then remember where the real holes are.
        if present:
            df = df.loc[df[present].notna().any(axis=1)].reset_index(drop=True)
        if df.empty:
            self.canvas.draw()
            return
        data_gaps = self._find_data_gaps(df)
        # Rate uses a rolling wall-clock window (not raw 1-sample ΔSOC/Δt).
        df['soc_chg_pct_per_h'] = self._soc_change_per_hour(
            df, capacity_kwh=float(self.battery_capacity or 13.0),
        )
        # Bridge only one- or two-sample holes. True gaps stay broken so PV /
        # grid do not draw fake diagonals through missing hours.
        for c in present:
            df[c] = pd.to_numeric(df[c], errors='coerce').interpolate(
                limit=2, limit_area='inside',
            )
        df = self._insert_gap_breaks(df, data_gaps)
        timestamps = df['timestamp']
        soc = df['soc_pct'] if 'soc_pct' in df.columns else pd.Series(np.nan, index=df.index)
        recon = bool(getattr(self, '_soc_is_reconstructed', False))
        soc_label = 'SOC % (reconstructed)' if recon else 'SOC %'
        self.ax_soc.plot(
            timestamps, soc, color='#2196F3', linewidth=1.2,
            linestyle='--' if recon else '-', label=soc_label, zorder=3,
        )
        soc_num = pd.to_numeric(soc, errors='coerce')
        for pred, colr, label in self._SOC_FILL_BANDS:
            cond = pred(soc_num) & soc_num.notna()
            self.ax_soc.fill_between(
                timestamps, 0, soc_num, where=cond.to_numpy(),
                alpha=0.38, color=colr, interpolate=False, linewidth=0,
                label=label, zorder=2,
            )
        self.ax_soc.axhline(y=threshold, color='red', linestyle='--', linewidth=1, alpha=0.7, label=f'{threshold}% threshold')
        self.ax_soc.set_ylabel(
            'Battery SOC (%)', color='#1565C0', fontsize=9, fontweight='bold',
            labelpad=6,
        )
        self.ax_soc.set_ylim(0, 105)
        self.ax_soc.set_title(
            'Battery State of Charge — RECONSTRUCTED from charge/discharge '
            '(no measured SOC in this source)'
            if recon else 'Battery State of Charge',
            pad=5,
            color='#000000',
        )
        rate = df['soc_chg_pct_per_h']
        if self._soc_rate_enabled() and rate.notna().any():
            rate_col = self._SOC_RATE_COLOR
            self._ax_soc_rate = self.ax_soc.twinx()
            self._ax_soc_rate.plot(
                timestamps, rate, color=rate_col, linewidth=0.9, alpha=0.85,
                label='ΔSOC %/h', zorder=2,
            )
            self._ax_soc_rate.axhline(0, color='#6c7086', linewidth=0.6, alpha=0.5)
            self._ax_soc_rate.set_ylabel(
                'SOC change (%/hour)', color=rate_col, fontsize=9,
                fontweight='bold', labelpad=6, rotation=270, va='bottom',
            )
            self._ax_soc_rate.tick_params(axis='y', colors=rate_col, labelsize=8)
            # Fixed ±100 %/h — matches the physical clip on the rolling rate
            # and keeps charge/discharge comparable without spike-driven scale.
            self._ax_soc_rate.set_ylim(-100.0, 100.0)
            self._ax_soc_rate.patch.set_visible(False)
            self._ax_soc_rate.set_zorder(self.ax_soc.get_zorder() + 1)
            self.ax_soc.set_zorder(self._ax_soc_rate.get_zorder() - 1)
            self.ax_soc.patch.set_visible(True)
        self.ax_soc.grid(True, which='major', alpha=0.3)
        self.ax_soc.grid(True, which='minor', alpha=0.12)
        self.ax_power.fill_between(timestamps, df['pv_kW'], alpha=0.6, color='#FF9800', label='PV')
        self.ax_power.fill_between(timestamps, df['charge_kW'], alpha=0.5, color='#4CAF50', label='Charge')
        _flow_lw = 72.0 / float(self.fig.dpi or 100)  # 1px
        self.ax_power.plot(
            timestamps, df['discharge_kW'], color='#2196F3',
            linewidth=_flow_lw, alpha=0.7, label='Discharge',
        )
        self.ax_power.plot(
            timestamps, df['grid_import_kW'], color='#F44336',
            linewidth=_flow_lw, alpha=0.7, label='Grid Import',
        )
        self.ax_power.plot(timestamps, df['grid_export_kW'], color='#8BC34A', linewidth=0.8, linestyle='--', label='Grid Export')
        self.ax_power.set_ylabel('kW')
        self.ax_power.set_xlabel('Time')
        self.ax_power.set_title('Power Flows', pad=4)
        self.ax_power.grid(True, which='major', alpha=0.3)
        self.ax_power.grid(True, which='minor', alpha=0.12)

        span_h = max((timestamps.max() - timestamps.min()).total_seconds() / 3600.0, 1e-6)
        if span_h <= 36:
            major_iv, minor_iv = 2, 1
        elif span_h <= 120:
            major_iv, minor_iv = 3, 1
        elif span_h <= 336:
            major_iv, minor_iv = 6, 2
        else:
            major_iv, minor_iv = 12, 4
        maj = mdates.HourLocator(interval=major_iv)
        mn = mdates.HourLocator(interval=minor_iv)
        self.ax_power.xaxis.set_major_locator(maj)
        self.ax_power.xaxis.set_minor_locator(mn)
        self.ax_power.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        self.ax_power.tick_params(axis='x', rotation=35)

        self._battery_hover_df = df
        self._battery_t_nums = mdates.date2num(pd.to_datetime(timestamps))

        self._vline_soc = self.ax_soc.axvline(
            timestamps.iloc[0], color='#cba6f7', lw=1.1, alpha=0.95, visible=False, zorder=20)
        self._vline_power = self.ax_power.axvline(
            timestamps.iloc[0], color='#cba6f7', lw=1.1, alpha=0.95, visible=False, zorder=20)
        self._hline_soc = self.ax_soc.axhline(
            0, color='#94e2d5', lw=0.9, alpha=0.85, visible=False, zorder=19)
        self._hline_power = self.ax_power.axhline(
            0, color='#94e2d5', lw=0.9, alpha=0.85, visible=False, zorder=19)

        self.cursor_info_label.setText("Hover over charts for time-slot readings (crosshair syncs both plots).")
        import pytz
        _lon_bt = pytz.timezone('Europe/London')
        _draw_6h_vertical_grid(self.ax_soc)
        _draw_6h_vertical_grid(self.ax_power)
        _draw_day_date_labels(self.ax_soc)
        _draw_day_date_labels(self.ax_power)
        _battery_power_draw_daily_totals(self.ax_power, df, _lon_bt)
        # Grey only true holes (values change across a long empty interval).
        # Idle holds stay unshaded so overnight 10 % SOC is not "no data".
        self._annotate_data_gaps(self.ax_soc, data_gaps, label=False)
        self._annotate_data_gaps(self.ax_power, data_gaps, label=True)
        for _leg in self.fig.legends:
            _leg.remove()
        _handles_soc, _labels_soc = self.ax_soc.get_legend_handles_labels()
        _handles_pwr, _labels_pwr = self.ax_power.get_legend_handles_labels()
        if getattr(self, '_ax_soc_rate', None) is not None:
            _hr, _lr = self._ax_soc_rate.get_legend_handles_labels()
            _handles_soc = _handles_soc + _hr
            _labels_soc = _labels_soc + _lr
        self.ax_soc.legend(
            _handles_soc + _handles_pwr,
            _labels_soc + _labels_pwr,
            loc='upper left',
            ncol=2,
            fontsize=7,
            frameon=True,
            framealpha=0.85,
            facecolor='#181825',
            edgecolor='#45475a',
            labelcolor='#cdd6f4',
        )
        self.ax_soc.format_coord = lambda xv, yv, tz=_lon_bt: _fmt_toolbar_time_y(
            xv, yv, tz, "% SOC",
            "battery state of charge (whole pack)",
        )
        if getattr(self, '_ax_soc_rate', None) is not None:
            self._ax_soc_rate.format_coord = lambda xv, yv, tz=_lon_bt: _fmt_toolbar_time_y(
                xv, yv, tz, "%/h",
                "SOC change rate (percentage points per hour)",
            )
        self.ax_power.format_coord = lambda xv, yv, tz=_lon_bt: _fmt_toolbar_time_y(
            xv, yv, tz, "kW",
            "instantaneous AC power — PV / charge / discharge / grid traces",
        )
        self._apply_battery_chart_layout()
        self.canvas.draw()

    def _hide_battery_cursor(self):
        if not getattr(self, '_vline_soc', None):
            return
        self._vline_soc.set_visible(False)
        self._vline_power.set_visible(False)
        self._hline_soc.set_visible(False)
        self._hline_power.set_visible(False)
        self.cursor_info_label.setText("Hover over charts for time-slot readings (crosshair syncs both plots).")
        self.canvas.draw_idle()

    def _on_battery_canvas_motion(self, event):
        df = getattr(self, '_battery_hover_df', None)
        tnums = self._battery_t_nums
        if df is None or tnums is None or len(df) == 0:
            return
        rate_ax = getattr(self, '_ax_soc_rate', None)
        if event.inaxes not in (self.ax_soc, self.ax_power, rate_ax) or event.xdata is None:
            self._hide_battery_cursor()
            return
        idx = int(np.abs(tnums - event.xdata).argmin())
        row = df.iloc[idx]
        x = float(tnums[idx])
        self._vline_soc.set_xdata([x, x])
        self._vline_power.set_xdata([x, x])
        self._vline_soc.set_visible(True)
        self._vline_power.set_visible(True)
        ts = row['timestamp']
        if hasattr(ts, 'strftime'):
            ts_str = ts.strftime('%Y-%m-%d %H:%M')
        else:
            ts_str = str(ts)
        if event.inaxes in (self.ax_soc, rate_ax) and event.ydata is not None:
            # Map hover y onto SOC % when over the rate twin, so the crosshair
            # still tracks pack SOC rather than %/h.
            y_soc = float(row['soc_pct']) if event.inaxes is rate_ax else float(event.ydata)
            self._hline_soc.set_ydata([y_soc, y_soc])
            self._hline_soc.set_visible(True)
            self._hline_power.set_visible(False)
        elif event.inaxes == self.ax_power and event.ydata is not None:
            self._hline_power.set_ydata([event.ydata, event.ydata])
            self._hline_power.set_visible(True)
            self._hline_soc.set_visible(False)
        rate = row['soc_chg_pct_per_h'] if 'soc_chg_pct_per_h' in row.index else float('nan')
        rate_str = f"{rate:+.1f} %/h" if pd.notna(rate) else "n/a"
        self.cursor_info_label.setText(
            f"{ts_str}  |  SOC {row['soc_pct']:.1f}%  Δ {rate_str}  |  "
            f"PV {row['pv_kW']:.2f}  Chg {row['charge_kW']:.2f}  "
            f"Dsch {row['discharge_kW']:.2f}  Imp {row['grid_import_kW']:.2f}  "
            f"Exp {row['grid_export_kW']:.2f}  Load {row['load_kW']:.2f} kW"
        )
        self.canvas.draw_idle()

    def _populate_events_table(self):
        self.events_tree.clear()
        for event in self.low_soc_events:
            dur = event['duration_min']
            dur_str = f"{int(dur//60)}h {int(dur%60)}m" if dur >= 60 else f"{int(dur)}m"
            ts = pd.to_datetime(event.get('start'), errors='coerce')
            if pd.isna(ts):
                time_s = '—'
            else:
                ts = pd.Timestamp(ts)
                if getattr(ts, 'tzinfo', None) is not None:
                    try:
                        ts = ts.tz_convert('Europe/London')
                    except Exception:
                        ts = ts.tz_localize(None)
                time_s = ts.strftime('%m-%d %H:%M')
            item = QTreeWidgetItem([
                time_s, f"{event['min_soc']:.1f}",
                dur_str, f"{event['avg_load_kW']:.2f}", f"{event['grid_import_kWh']:.2f}"])
            self.events_tree.addTopLevelItem(item)

    def _read_inverter_charge_stop_async(self) -> None:
        api, _plant_id, sn = self._cloud_api()
        if not api or not sn:
            self.lbl_inv_charge_stop.setText("Inverter stop: cloud not connected")
            self.lbl_inv_charge_stop.setStyleSheet("color: #6c7086; font-size: 11px;")
            return
        threading.Thread(
            target=self._read_inverter_charge_stop_thread, args=(api, sn), daemon=True,
        ).start()

    def _read_inverter_charge_stop_thread(self, api, sn) -> None:
        from energy_dashboard.tabs.optimiser import OptimiserTab
        try:
            raw = api.get_mix_inverter_settings(sn)
            ac = OptimiserTab._parse_ac_charge_from_settings(raw)
            stop = int(ac['stop_soc']) if ac else None
            self._inv.invoke(lambda s=stop: self._show_inverter_charge_stop(s))
        except Exception as exc:
            msg = str(exc)
            self._inv.invoke(lambda m=msg: self._show_inverter_charge_stop(None, m))

    def _show_inverter_charge_stop(self, stop, err: str | None = None) -> None:
        if err:
            self.lbl_inv_charge_stop.setText("Inverter stop: read failed")
            self.lbl_inv_charge_stop.setStyleSheet("color: #f38ba8; font-size: 11px;")
            self.lbl_inv_charge_stop.setToolTip(err[:300])
            return
        if stop is None:
            self.lbl_inv_charge_stop.setText("Inverter stop: —")
            self.lbl_inv_charge_stop.setStyleSheet("color: #6c7086; font-size: 11px;")
            self.lbl_inv_charge_stop.setToolTip(
                "Cloud settings did not include wchargeSOCLowLimit."
            )
            return
        col = '#a6e3a1' if stop >= 100 else '#fab387'
        self.lbl_inv_charge_stop.setText(f"Inverter stop: {stop}%")
        self.lbl_inv_charge_stop.setStyleSheet(f"color: {col}; font-size: 11px;")
        self.lbl_inv_charge_stop.setToolTip(
            "Growatt MIX AC charge stop SOC (wchargeSOCLowLimit) from cloud."
        )
        if not self._charge_stop_dirty and not self._settings().contains(self._QS_CHARGE_STOP):
            self.charge_stop_spin.blockSignals(True)
            self.charge_stop_spin.setValue(int(stop))
            self.charge_stop_spin.blockSignals(False)

    def _write_inverter_charge_stop(self) -> None:
        from energy_dashboard.tabs.shadow_trial import confirm_despite_shadow_trial
        target = int(self.charge_stop_spin.value())
        if not confirm_despite_shadow_trial(self, f"AC charge stop SOC → {target}%"):
            return
        api, _plant_id, sn = self._cloud_api()
        if api is None or not sn:
            QMessageBox.warning(
                self,
                "Growatt cloud required",
                "Inverter writes go through the Growatt cloud API.\n\n"
                "Connect Growatt cloud on the Live Status tab (or Hybrid with API "
                "credentials) before changing charge stop SOC.",
            )
            return
        r = QMessageBox.question(
            self,
            "Write inverter charge stop SOC",
            f"This reads your current MIX AC charge schedule from Growatt cloud, "
            f"sets stop SOC to {target}% (wchargeSOCLowLimit), and writes it back. "
            f"Charge power and time periods are left unchanged.\n\n"
            "This affects forced AC grid charging. Solar charging may still be "
            "limited separately by BMS/firmware.\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        self.btn_set_charge_stop.setEnabled(False)
        self.lbl_inv_charge_stop.setText("Writing inverter stop SOC…")
        self.lbl_inv_charge_stop.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        threading.Thread(
            target=self._write_inverter_charge_stop_thread,
            args=(api, sn, target),
            daemon=True,
        ).start()

    def _write_inverter_charge_stop_thread(self, api, sn, target: int) -> None:
        from energy_dashboard.tabs.optimiser import OptimiserTab
        from energy_dashboard.tabs.smart_advisor import _mix_ac_charge_api_params
        try:
            raw = api.get_mix_inverter_settings(sn)
            ac = OptimiserTab._parse_ac_charge_from_settings(raw)
            if not ac:
                raise RuntimeError("Could not parse AC charge schedule from inverter.")
            prev = int(ac['stop_soc'])
            ac = dict(ac)
            ac['stop_soc'] = int(target)
            params = _mix_ac_charge_api_params(
                ac['charge_power'], ac['stop_soc'], ac['mains_enabled'], ac['periods'],
            )
            result = api.update_mix_inverter_setting(sn, "mix_ac_charge_time_period", params)
            ok = not (isinstance(result, dict) and result.get("success") is False)
            verified = None
            verify_err = ""
            if ok:
                import time as _time_mod
                _time_mod.sleep(2.5)
                try:
                    verify_raw = api.get_mix_inverter_settings(sn)
                    verify_ac = OptimiserTab._parse_ac_charge_from_settings(verify_raw)
                    if verify_ac:
                        verified = int(verify_ac['stop_soc'])
                        if verified != int(target):
                            ok = False
                            verify_err = (
                                f"Inverter read-back is {verified}%, not {target}%."
                            )
                    else:
                        verify_err = "Wrote, but could not parse the read-back schedule."
                except Exception as vexc:
                    verify_err = f"Wrote, but verify read failed: {vexc}"
            self._inv.invoke(
                lambda p=prev, t=target, o=ok, r=result, v=verified, ve=verify_err: (
                    self._charge_stop_write_done(p, t, o, r, v, ve)
                )
            )
        except Exception as exc:
            self._inv.invoke(lambda err=str(exc): self._charge_stop_write_failed(err))

    def _charge_stop_write_done(
        self, prev: int, target: int, ok: bool, raw, verified=None, verify_err: str = "",
    ) -> None:
        self.btn_set_charge_stop.setEnabled(True)
        shown = verified if verified is not None else target
        if ok:
            self.lbl_inv_charge_stop.setText(f"Inverter stop: {shown}%")
            self.lbl_inv_charge_stop.setStyleSheet("color: #a6e3a1; font-size: 11px;")
            self.set_status(
                f"Battery Analysis: inverter AC charge stop SOC {prev}% → {shown}% written."
            )
            QMessageBox.information(
                self,
                "Inverter updated",
                f"AC charge stop SOC changed from {prev}% to {shown}%.\n\n"
                "Re-fetch history after the pack charges to confirm measured SOC rises.",
            )
        else:
            if verified is not None:
                self.lbl_inv_charge_stop.setText(f"Inverter stop: {verified}%")
            else:
                self.lbl_inv_charge_stop.setText("Inverter stop: write error")
            self.lbl_inv_charge_stop.setStyleSheet("color: #f38ba8; font-size: 11px;")
            self.set_status("Battery Analysis: inverter charge stop write returned an error.")
            detail = verify_err or (
                json.dumps(raw, indent=2, default=str) if isinstance(raw, dict) else str(raw)
            )
            QMessageBox.warning(self, "Write failed", detail[:2000])

    def _charge_stop_write_failed(self, err: str) -> None:
        self.btn_set_charge_stop.setEnabled(True)
        self.lbl_inv_charge_stop.setText("Inverter stop: write failed")
        self.lbl_inv_charge_stop.setStyleSheet("color: #f38ba8; font-size: 11px;")
        self.set_status(f"Battery Analysis: inverter charge stop write failed — {err[:120]}")
        QMessageBox.warning(self, "Write failed", err[:2000])


__all__ = [n for n in globals() if not n.startswith('__')]
