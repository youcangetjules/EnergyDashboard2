"""
Energy Dashboard — `tabs/analytics.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *


class AnalyticsTab(QWidget):
    BATTERY_UNIT_KWH = 6.5
    SCENARIOS = [("Current (2x)", 13.0, '#2196F3'), ("3 Batteries", 19.5, '#FF9800'), ("4 Batteries", 26.0, '#4CAF50')]

    def __init__(self, octopus_tab, growatt_tab, status_callback, app_params=None, dashboard=None):
        super().__init__()
        self.octopus_tab = octopus_tab
        self.growatt_tab = growatt_tab
        self.set_status = status_callback
        self.app_params = app_params
        self.dash = dashboard
        self._inv = Invoker(self)
        self.sim_results = None
        self.sim_actual_days = 1
        self._sim_context = None
        self.fetching = False
        # Set by EnergyDashboard.build_ui — fired when the user re-runs the
        # simulation so the tab text turns green.
        self.on_data_updated = None
        self.build_ui()

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Vertical)

        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # --- Controls ---
        ctrl_box = QGroupBox("Battery Expansion Simulator")
        ctrl_vlayout = QVBoxLayout(ctrl_box)

        row0 = QHBoxLayout()
        row0.addWidget(QLabel("Data source:"))
        self.days_group = QButtonGroup(self)
        for text, val in [("7 days", 7), ("14 days", 14), ("30 days", 30), ("90 days", 90)]:
            rb = QRadioButton(text)
            self.days_group.addButton(rb, val)
            row0.addWidget(rb)
        self.days_group.button(30).setChecked(True)
        row0.addSpacing(15)
        row0.addWidget(QLabel("Efficiency %:"))
        self.eff_edit = QLineEdit("90")
        self.eff_edit.setFixedWidth(40)
        row0.addWidget(self.eff_edit)
        row0.addWidget(QLabel("Max charge rate kW:"))
        self.charge_rate_edit = QLineEdit("3.3")
        self.charge_rate_edit.setFixedWidth(40)
        row0.addWidget(self.charge_rate_edit)
        row0.addStretch()
        ctrl_vlayout.addLayout(row0)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Import rate p/kWh:"))
        self.import_rate_edit = QLineEdit("24.5")
        self.import_rate_edit.setFixedWidth(50)
        row1.addWidget(self.import_rate_edit)
        row1.addWidget(QLabel("Export rate p/kWh:"))
        self.export_rate_edit = QLineEdit("15.0")
        self.export_rate_edit.setFixedWidth(50)
        row1.addWidget(self.export_rate_edit)
        row1.addWidget(QLabel("Battery cost each:"))
        self.battery_cost_edit = QLineEdit("2500")
        self.battery_cost_edit.setFixedWidth(60)
        row1.addWidget(self.battery_cost_edit)
        self.use_agile_check = QCheckBox("Use Agile prices (if available)")
        self.use_agile_check.setChecked(True)
        row1.addWidget(self.use_agile_check)
        self.tou_opt_check = QCheckBox("Smart charge (minimum grid, drain to 10%, cheapest slots)")
        self.tou_opt_check.setChecked(True)
        self.tou_opt_check.setToolTip(
            "Battery always discharges to 10% SOC to serve load. Grid charging is limited to the absolute "
            "minimum needed to maintain continuous supply until the next solar window. That minimum charge "
            "is placed into the cheapest Agile slots available."
        )
        row1.addWidget(self.tou_opt_check)
        self.run_btn = QPushButton("Run Simulation")
        self.run_btn.clicked.connect(self.run_simulation)
        row1.addWidget(self.run_btn)
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"color: {_UI_BLUE};")
        row1.addWidget(self.progress_label)
        row1.addStretch()
        ctrl_vlayout.addLayout(row1)
        top_layout.addWidget(ctrl_box)

        # --- Charts 2x2 ---
        chart_widget = QWidget()
        chart_layout = QVBoxLayout(chart_widget)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        self.fig = Figure(figsize=(14, 7), dpi=100)
        gs = self.fig.add_gridspec(2, 2, hspace=0.35, wspace=0.3)
        self.ax_bill = self.fig.add_subplot(gs[0, 0])
        self.ax_self = self.fig.add_subplot(gs[0, 1])
        self.ax_soc = self.fig.add_subplot(gs[1, 0])
        self.ax_payback = self.fig.add_subplot(gs[1, 1])
        self.canvas = FigureCanvas(self.fig)
        chart_layout.addWidget(self.canvas)
        toolbar = DarkNavigationToolbar(self.canvas, self)
        chart_layout.addWidget(toolbar)
        self._chart_shimmer = ChartShimmerOverlay(self.canvas)
        top_layout.addWidget(chart_widget, 1)
        splitter.addWidget(top_widget)

        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(8)
        builder_box = QGroupBox("Interactive Scenario Builder")
        builder_layout = QVBoxLayout(builder_box)
        builder_grid = QGridLayout()
        builder_grid.addWidget(QLabel("Battery units:"), 0, 0)
        self.builder_units_spin = QSpinBox()
        self.builder_units_spin.setRange(0, 8)
        self.builder_units_spin.setValue(2)
        self.builder_units_spin.valueChanged.connect(self._update_builder_capacity_label)
        builder_grid.addWidget(self.builder_units_spin, 0, 1)
        self.builder_capacity_label = QLabel("13.0 kWh nominal")
        builder_grid.addWidget(self.builder_capacity_label, 0, 2)

        builder_grid.addWidget(QLabel("Efficiency %:"), 1, 0)
        self.builder_eff_spin = QDoubleSpinBox()
        self.builder_eff_spin.setRange(50.0, 100.0)
        self.builder_eff_spin.setDecimals(1)
        self.builder_eff_spin.setValue(90.0)
        builder_grid.addWidget(self.builder_eff_spin, 1, 1)

        builder_grid.addWidget(QLabel("Max charge kW:"), 1, 2)
        self.builder_charge_spin = QDoubleSpinBox()
        self.builder_charge_spin.setRange(0.5, 15.0)
        self.builder_charge_spin.setDecimals(1)
        self.builder_charge_spin.setValue(3.3)
        builder_grid.addWidget(self.builder_charge_spin, 1, 3)

        builder_grid.addWidget(QLabel("Import p/kWh:"), 2, 0)
        self.builder_import_spin = QDoubleSpinBox()
        self.builder_import_spin.setRange(0.0, 100.0)
        self.builder_import_spin.setDecimals(2)
        self.builder_import_spin.setValue(24.5)
        builder_grid.addWidget(self.builder_import_spin, 2, 1)

        builder_grid.addWidget(QLabel("Export p/kWh:"), 2, 2)
        self.builder_export_spin = QDoubleSpinBox()
        self.builder_export_spin.setRange(0.0, 100.0)
        self.builder_export_spin.setDecimals(2)
        self.builder_export_spin.setValue(15.0)
        builder_grid.addWidget(self.builder_export_spin, 2, 3)

        self.builder_use_agile = QCheckBox("Use Agile prices")
        self.builder_use_agile.setChecked(True)
        builder_grid.addWidget(self.builder_use_agile, 3, 0, 1, 2)
        self.builder_smart = QCheckBox("Use smart charging")
        self.builder_smart.setChecked(True)
        builder_grid.addWidget(self.builder_smart, 3, 2, 1, 2)
        builder_layout.addLayout(builder_grid)

        builder_btn_row = QHBoxLayout()
        self.builder_preview_btn = QPushButton("Preview Scenario")
        self.builder_preview_btn.clicked.connect(self._preview_custom_scenario)
        builder_btn_row.addWidget(self.builder_preview_btn)
        self.builder_copy_btn = QPushButton("Use Main Controls")
        self.builder_copy_btn.clicked.connect(self._sync_builder_from_main_controls)
        builder_btn_row.addWidget(self.builder_copy_btn)
        self.builder_hint = QLabel("Run the main simulation once, then adjust these controls to preview alternatives.")
        self.builder_hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        builder_btn_row.addWidget(self.builder_hint, 1)
        builder_layout.addLayout(builder_btn_row)

        self.builder_summary = QTextEdit()
        self.builder_summary.setReadOnly(True)
        self.builder_summary.setFont(QFont('Courier', 10))
        self.builder_summary.setMinimumHeight(120)
        builder_layout.addWidget(self.builder_summary, 1)

        results_box = QGroupBox("Simulation Results")
        results_layout = QVBoxLayout(results_box)
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setFont(QFont('Courier', 10))
        results_layout.addWidget(self.results_text, 1)

        builder_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        results_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        bottom_layout.addWidget(builder_box, 1)
        bottom_layout.addWidget(results_box, 1)
        splitter.addWidget(bottom_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter)

    def apply_from_app_params(self):
        if self.app_params is None:
            return
        p = self.app_params
        self.eff_edit.setText(f"{p.analytics_efficiency_pct:.0f}")
        self.charge_rate_edit.setText(f"{p.analytics_max_charge_kw:.2f}".rstrip('0').rstrip('.'))
        self.import_rate_edit.setText(f"{p.import_flat_pence:.2f}".rstrip('0').rstrip('.'))
        self.export_rate_edit.setText(f"{p.export_flat_pence:.2f}".rstrip('0').rstrip('.'))
        self.battery_cost_edit.setText(f"{p.analytics_battery_cost_gbp:.0f}")
        self._sync_builder_from_main_controls()

    def _sync_builder_from_main_controls(self):
        self.builder_units_spin.setValue(2)
        try:
            self.builder_eff_spin.setValue(float(self.eff_edit.text()))
        except ValueError:
            pass
        try:
            self.builder_charge_spin.setValue(float(self.charge_rate_edit.text()))
        except ValueError:
            pass
        try:
            self.builder_import_spin.setValue(float(self.import_rate_edit.text()))
        except ValueError:
            pass
        try:
            self.builder_export_spin.setValue(float(self.export_rate_edit.text()))
        except ValueError:
            pass
        self.builder_use_agile.setChecked(self.use_agile_check.isChecked())
        self.builder_smart.setChecked(self.tou_opt_check.isChecked())
        self._update_builder_capacity_label()

    def _update_builder_capacity_label(self):
        units = self.builder_units_spin.value()
        cap = units * self.BATTERY_UNIT_KWH
        self.builder_capacity_label.setText(f"{cap:.1f} kWh nominal")

    def _preview_custom_scenario(self):
        self._update_builder_capacity_label()
        ctx = self._sim_context
        if not ctx:
            self.builder_summary.setPlainText(
                "Run the main simulation first. The scenario builder reuses the same historical data and pricing context."
            )
            return

        units = self.builder_units_spin.value()
        capacity = units * self.BATTERY_UNIT_KWH
        efficiency = self.builder_eff_spin.value() / 100.0
        max_charge_kw = self.builder_charge_spin.value()
        flat_import = self.builder_import_spin.value()
        flat_export = self.builder_export_spin.value()
        use_agile = self.builder_use_agile.isChecked()
        smart_charge = self.builder_smart.isChecked()

        agile_prices = ctx.get('agile_prices') if use_agile else None
        slot_prices = _align_agile_rates_to_consumption_index(
            ctx['merged'].index, agile_prices, flat_import
        )
        agile_ok = bool(use_agile and agile_prices is not None and len(agile_prices) > 0)
        cheap_mask = _daily_cheap_mask(slot_prices) if agile_ok else pd.Series(False, index=ctx['merged'].index)

        if capacity <= 0:
            res = self._simulate_no_battery(ctx['merged'], slot_prices, flat_export)
            label = "Preview: No Battery"
        else:
            res = self._simulate_battery(
                ctx['merged'], capacity, efficiency, max_charge_kw,
                slot_prices, flat_export, cheap_mask, bool(smart_charge and agile_ok)
            )
            label = f"Preview: {units} unit(s)"

        days = max(ctx.get('actual_days', 1), 1)
        res['daily_cost'] = res['total_cost_pence'] / days
        res['annual_cost'] = res['daily_cost'] * 365 / 100
        res['daily_export_revenue'] = res['total_export_revenue_pence'] / days
        res['annual_bill'] = (res['daily_cost'] - res['daily_export_revenue']) * 365 / 100
        current_annual = ctx.get('current_annual')
        delta = None if current_annual is None else current_annual - res['annual_bill']
        direct_cost = res.get('total_grid_direct_cost_pence', 0) * 365 / days / 100
        charge_cost = res.get('total_grid_charge_cost_pence', 0) * 365 / days / 100
        export_credit = res.get('daily_export_revenue', 0) * 365 / 100
        grid_day = res.get('total_grid_import_kwh', 0) / days
        export_day = res.get('total_grid_export_kwh', 0) / days
        charge_day = res.get('total_grid_charge_kwh', 0) / days

        lines = [
            f"{label}",
            "",
            f"Annual bill:          £{res['annual_bill']:.0f}",
            f"Direct import cost:   £{direct_cost:.0f}",
            f"Battery charge cost:  £{charge_cost:.0f}",
            f"Export credit:       -£{export_credit:.0f}",
            f"Equation:             £{res['annual_bill']:.0f} = £{direct_cost:.0f} + £{charge_cost:.0f} - £{export_credit:.0f}",
            "",
            f"Grid import:          {grid_day:.1f} kWh/day",
            f"Grid->battery:        {charge_day:.1f} kWh/day",
            f"Export:               {export_day:.1f} kWh/day",
            f"Battery nominal:      {capacity:.1f} kWh",
            f"Efficiency:           {efficiency*100:.1f}%",
            f"Charge rate:          {max_charge_kw:.1f} kW",
            f"Pricing mode:         {'Agile' if agile_ok else f'Flat {flat_import:.2f} p/kWh'}",
            f"Smart charging:       {'On' if smart_charge and agile_ok else 'Off'}",
        ]
        if delta is not None:
            lines.append(f"Saving vs Current:    £{delta:+.0f}/yr")
        if ctx.get('proxy'):
            lines.extend([
                "",
                "Note: this preview still uses Octopus proxy data.",
                "load = import + export, solar = export. Use Growatt DB data for physically reliable load/PV splits.",
            ])
        self.builder_summary.setPlainText("\n".join(lines))

    def run_simulation(self):
        if self.fetching:
            return
        self.fetching = True
        self.run_btn.setEnabled(False)
        self._chart_shimmer.start()
        self.set_status("Running battery expansion simulation...")
        self._sim_ui = {
            'days': self.days_group.checkedId(),
            'efficiency': float(self.eff_edit.text()) / 100.0,
            'max_charge_kw': float(self.charge_rate_edit.text()),
            'flat_import': float(self.import_rate_edit.text()),
            'flat_export': float(self.export_rate_edit.text()),
            'battery_cost': float(self.battery_cost_edit.text()),
            'use_agile': self.use_agile_check.isChecked(),
            'tou_opt': self.tou_opt_check.isChecked(),
        }
        threading.Thread(target=self._sim_thread, daemon=True).start()

    def _sim_thread(self):
        try:
            ui = self._sim_ui
            days = ui['days']
            efficiency = ui['efficiency']
            max_charge_kw = ui['max_charge_kw']
            flat_import = ui['flat_import']
            flat_export = ui['flat_export']
            battery_cost = ui['battery_cost']
            use_agile = ui['use_agile']
            tou_opt_requested = ui['tou_opt']
            # --- Primary: Growatt DB data (true load + solar) ---
            self._inv.invoke(lambda: self.progress_label.setText("Checking Growatt DB for load/solar history..."))
            growatt_hh = self._fetch_growatt_history(days)
            data_source = None

            growatt_slots = 0 if growatt_hh is None else len(growatt_hh)
            if growatt_hh is not None and growatt_slots >= 48:
                merged = growatt_hh
                data_source = "Growatt DB"
                _log.info("Analytics", f"Using Growatt DB: {len(merged)} half-hour slots, "
                      f"load={merged['load_kWh'].sum():.1f} kWh, solar={merged['solar_kWh'].sum():.1f} kWh")
            else:
                # --- Fallback: Octopus import/export (post-battery) ---
                self._inv.invoke(lambda: self.progress_label.setText("Fetching Octopus consumption data..."))
                api_key = self.octopus_tab.api_key_edit.text()
                import_mpan = self.octopus_tab.import_mpan_edit.text()
                import_serial = self.octopus_tab.import_serial_edit.text()
                export_mpan = self.octopus_tab.export_mpan_edit.text()
                export_serial = self.octopus_tab.export_serial_edit.text()
                now_dt = datetime.now()
                end_date = now_dt - timedelta(days=1)
                start_date = end_date - timedelta(days=days)
                df_import = get_meter_data(api_key, import_mpan, import_serial, start_date, end_date)
                df_export = get_meter_data(api_key, export_mpan, export_serial, start_date, end_date)
                if df_import.empty:
                    self._inv.invoke(lambda n=growatt_slots, d=days: self._sim_error(
                        self._not_enough_data_message(n, 0, d)
                    ))
                    return
                df_import['interval_start'] = pd.to_datetime(df_import['interval_start'], utc=True)
                df_import = df_import.set_index('interval_start').sort_index().rename(columns={'consumption': 'import_kWh'})
                if not df_export.empty:
                    df_export['interval_start'] = pd.to_datetime(df_export['interval_start'], utc=True)
                    df_export = df_export.set_index('interval_start').sort_index().rename(columns={'consumption': 'export_kWh'})
                    octopus_merged = df_import.join(df_export, how='outer').fillna(0)
                else:
                    octopus_merged = df_import.copy()
                    octopus_merged['export_kWh'] = 0

                # Reconstruct approximate load + solar from Octopus post-battery data.
                # load ≈ import + export (this underestimates by the existing battery's
                # self-consumption, but is the best we can do without Growatt data).
                octopus_merged['load_kWh'] = octopus_merged['import_kWh'] + octopus_merged['export_kWh']
                octopus_merged['solar_kWh'] = octopus_merged['export_kWh']
                merged = octopus_merged[['load_kWh', 'solar_kWh']]
                if len(merged) < 48:
                    octopus_slots = len(merged)
                    self._inv.invoke(lambda n=growatt_slots, o=octopus_slots, d=days: self._sim_error(
                        self._not_enough_data_message(n, o, d)
                    ))
                    return
                data_source = "Octopus (approximate)"

            self._data_source_label = data_source

            agile_prices = None
            data_start = merged.index.min().to_pydatetime()
            data_end = merged.index.max().to_pydatetime()
            if use_agile:
                self._inv.invoke(lambda: self.progress_label.setText("Fetching Agile prices..."))
                try:
                    prod = self.app_params.agile_product if self.app_params else DEFAULT_AGILE_PRODUCT
                    tar = self.app_params.agile_tariff if self.app_params else DEFAULT_AGILE_TARIFF
                    agile_url = (
                        f"https://api.octopus.energy/v1/products/{prod}/electricity-tariffs/{tar}/standard-unit-rates/"
                    )
                    agile_params = {"period_from": data_start.strftime("%Y-%m-%dT00:00:00Z"),
                                    "period_to": data_end.strftime("%Y-%m-%dT23:59:59Z"), "page_size": 25000}
                    all_agile = []
                    url = agile_url
                    while url:
                        resp = requests.get(url, params=agile_params, timeout=30)
                        resp.raise_for_status()
                        data = resp.json()
                        all_agile.extend(data.get('results', []))
                        url = data.get('next')
                        agile_params = None
                    if all_agile:
                        ap = pd.DataFrame(all_agile)
                        ap['valid_from'] = pd.to_datetime(ap['valid_from'], utc=True)
                        ap = ap.set_index('valid_from').sort_index()
                        ap = ap[~ap.index.duplicated(keep='first')]
                        agile_prices = ap['value_inc_vat']
                except Exception as e:
                    _log.warn("Analytics", f"Agile price fetch failed: {e}")

            agile_ok = bool(use_agile and agile_prices is not None and len(agile_prices) > 0)
            slot_prices = _align_agile_rates_to_consumption_index(
                merged.index, agile_prices if use_agile else None, flat_import
            )
            cheap_mask = _daily_cheap_mask(slot_prices) if agile_ok else pd.Series(False, index=merged.index)
            tou_opt = bool(tou_opt_requested) and agile_ok
            self._inv.invoke(lambda: self.progress_label.setText("Simulating battery scenarios..."))
            results = {}
            for label, capacity, color in self.SCENARIOS:
                res = self._simulate_battery(
                    merged, capacity, efficiency, max_charge_kw,
                    slot_prices, flat_export, cheap_mask, tou_opt,
                )
                res['label'] = label
                res['capacity'] = capacity
                res['color'] = color
                results[label] = res
            actual_days = (merged.index.max() - merged.index.min()).days or 1
            for label, res in results.items():
                res['daily_cost'] = res['total_cost_pence'] / actual_days
                res['annual_cost'] = res['daily_cost'] * 365 / 100
                res['daily_export_revenue'] = res['total_export_revenue_pence'] / actual_days
                res['annual_bill'] = (res['daily_cost'] - res['daily_export_revenue']) * 365 / 100
            baseline = self._simulate_no_battery(merged, slot_prices, flat_export)
            baseline['daily_cost'] = baseline['total_cost_pence'] / actual_days
            baseline['annual_cost'] = baseline['daily_cost'] * 365 / 100
            baseline['daily_export_revenue'] = baseline['total_export_revenue_pence'] / actual_days
            baseline['annual_bill'] = (baseline['daily_cost'] - baseline['daily_export_revenue']) * 365 / 100
            results['No Battery'] = baseline
            current_annual = results['Current (2x)']['annual_bill']
            self._sim_context = {
                'merged': merged,
                'agile_prices': agile_prices,
                'actual_days': actual_days,
                'current_annual': current_annual,
                'proxy': bool(data_source and 'approximate' in data_source.lower()),
            }
            for label, res in results.items():
                res['annual_saving_vs_current'] = current_annual - res['annual_bill']
                extra_batteries = max(0, (res.get('capacity', 0) - 13.0) / self.BATTERY_UNIT_KWH)
                res['extra_cost'] = extra_batteries * battery_cost
                if res['annual_saving_vs_current'] > 0 and res['extra_cost'] > 0:
                    res['payback_years'] = res['extra_cost'] / res['annual_saving_vs_current']
                else:
                    res['payback_years'] = None
            self.sim_results = results
            self.sim_actual_days = actual_days
            self._inv.invoke(lambda: self._update_display())
        except Exception as e:
            import traceback; traceback.print_exc()
            err = str(e)
            self._inv.invoke(lambda msg=err: self._sim_error(f"Simulation error: {msg}"))

    def _fetch_growatt_history(self, days):
        """Fetch load_power_kw and pv_power_kw from the growatt_readings DB table.
        Returns a DataFrame with half-hourly load_kWh and solar_kWh, or None."""
        if self.dash is None:
            return None
        logger = getattr(self.dash, 'data_logger', None)
        if logger is None:
            return None
        cutoff = (datetime.now() - timedelta(days=days + 1)).strftime("%Y-%m-%d %H:%M:%S")
        q = ("SELECT timestamp, load_power_kw, pv_power_kw FROM growatt_readings "
             "WHERE timestamp >= %s ORDER BY timestamp ASC")
        rows = []
        try:
            if logger.sqlite_enabled:
                conn = sqlite3.connect(logger.sqlite_path)
                try:
                    cur = conn.cursor()
                    cur.execute(q.replace('%s', '?'), (cutoff,))
                    rows = cur.fetchall()
                finally:
                    conn.close()
            elif logger.mysql_enabled:
                if not logger.backend_ready("mysql"):
                    return None
                from energy_dashboard.db.connect_probe import mysql_connect
                conn = mysql_connect(
                    logger.mysql_host, logger.mysql_port,
                    logger.mysql_user, logger.mysql_pass, logger.mysql_db,
                )
                try:
                    with conn.cursor() as cur:
                        cur.execute(q, (cutoff,))
                        rows = cur.fetchall()
                finally:
                    conn.close()
            elif logger.pg_enabled:
                if not logger.backend_ready("pg"):
                    return None
                from energy_dashboard.db.connect_probe import postgresql_connect
                conn = postgresql_connect(
                    logger.pg_host, logger.pg_port,
                    logger.pg_user, logger.pg_pass, logger.pg_db,
                )
                try:
                    with conn.cursor() as cur:
                        cur.execute(q, (cutoff,))
                        rows = cur.fetchall()
                finally:
                    conn.close()
            else:
                return None
        except Exception as e:
            _log.warn("Analytics", f"Growatt DB history error: {e}")
            return None

        if len(rows) < 10:
            return None

        records = []
        for ts_str, load_kw, pv_kw in rows:
            if isinstance(ts_str, str):
                try:
                    ts = pd.to_datetime(ts_str, utc=True)
                except Exception:
                    try:
                        ts = pd.to_datetime(ts_str).tz_localize('UTC')
                    except Exception:
                        continue
            else:
                ts = pd.to_datetime(ts_str, utc=True) if ts_str else None
            if ts is None:
                continue
            records.append({'timestamp': ts,
                            'load_kw': float(load_kw or 0),
                            'pv_kw': float(pv_kw or 0)})

        if not records:
            return None

        df = pd.DataFrame(records).set_index('timestamp').sort_index()
        df = df[~df.index.duplicated(keep='last')]
        hh = df.resample('30min').mean().dropna()
        if hh.empty:
            return None
        # kW average over 30 min → kWh for the slot
        hh['load_kWh'] = hh['load_kw'] * 0.5
        hh['solar_kWh'] = hh['pv_kw'] * 0.5
        return hh[['load_kWh', 'solar_kWh']]

    def _simulate_battery(self, merged, capacity, efficiency, max_charge_kw,
                          slot_prices, flat_export_p, cheap_mask, tou_opt,
                          allow_surplus_export=True):
        """Simulate a battery with smart minimum-grid-charge strategy.

        When TOU is enabled the battery always discharges to 10% to serve
        load and grid charging is limited to the absolute minimum needed to
        maintain continuous supply until the next solar window.  That minimum
        charge is placed preferentially into the cheapest available slots.
        """
        sqrt_eff = efficiency ** 0.5
        usable_capacity = capacity * 0.95
        min_soc = capacity * 0.10
        max_charge_per_slot = max_charge_kw * 0.5

        timestamps = list(merged.index)
        loads = merged['load_kWh'].values.astype(float)
        solars = merged['solar_kWh'].values.astype(float)
        n = len(timestamps)

        # ----------------------------------------------------------
        # Pre-compute look-ahead: for each slot, the cumulative net
        # energy (load − solar, floored at 0) until the next period
        # where solar exceeds load.  This tells us how much battery
        # energy is needed to survive without any grid charging.
        # ----------------------------------------------------------
        kwh_until_solar = np.zeros(n)
        running = 0.0
        for i in range(n - 1, -1, -1):
            if solars[i] > loads[i]:
                running = 0.0
            else:
                running += max(0.0, loads[i] - solars[i])
            kwh_until_solar[i] = running

        # ----------------------------------------------------------
        # Pre-compute slot prices for indexed lookup
        # ----------------------------------------------------------
        prices = np.array([
            float(slot_prices.loc[ts]) if ts in slot_prices.index else 24.5
            for ts in timestamps
        ])
        is_cheap = np.array([
            bool(tou_opt and ts in cheap_mask.index and cheap_mask.loc[ts])
            for ts in timestamps
        ])

        soc = capacity * 0.5
        total_grid_import_kwh = total_grid_export_kwh = 0.0
        total_cost_pence = total_export_revenue_pence = 0.0
        total_grid_direct_cost_pence = 0.0
        total_grid_charge_cost_pence = 0.0
        total_solar_self_consumed_kwh = total_battery_to_load_kwh = 0.0
        total_grid_charge_kwh = total_load_kwh = total_solar_kwh = 0.0
        soc_history = []
        grid_import_history = []

        # Track energy SOURCE in the battery.  Do not assume initial SOC is
        # "half solar" — that falsely inflates yellow bars vs grid kWh & bill.
        # Unknown prior charge is treated as grid-sourced (conservative for free).
        soc_from_solar = 0.0
        soc_from_grid = float(soc)
        total_solar_batt_to_load = 0.0
        total_grid_batt_to_load = 0.0

        for i in range(n):
            load_kwh = loads[i]
            solar_kwh = solars[i]
            import_price = prices[i]
            export_price = flat_export_p

            total_load_kwh += load_kwh
            total_solar_kwh += solar_kwh

            # 1) Solar directly serves load
            solar_to_load = min(solar_kwh, load_kwh)
            total_solar_self_consumed_kwh += solar_to_load
            surplus_solar = solar_kwh - solar_to_load
            remaining_load = load_kwh - solar_to_load

            # 2) Surplus solar charges battery (tracked as solar-sourced)
            charge_room = min(usable_capacity - soc, max_charge_per_slot)
            solar_absorbed = min(surplus_solar, charge_room)
            energy_in = solar_absorbed * sqrt_eff
            soc += energy_in
            soc_from_solar += energy_in
            exported_solar = surplus_solar - solar_absorbed

            # 3) Battery ALWAYS discharges to serve load (down to 10%)
            discharge_avail = max(0.0, soc - min_soc)
            discharge_room = min(discharge_avail, max_charge_per_slot)
            battery_to_load = min(remaining_load, discharge_room * sqrt_eff)
            if battery_to_load > 0 and sqrt_eff > 0:
                soc_withdrawn = battery_to_load / sqrt_eff
                soc -= soc_withdrawn
                # Attribute discharge proportionally to solar/grid in battery
                total_in_battery = soc_from_solar + soc_from_grid
                if total_in_battery > 1e-9:
                    sf = soc_from_solar / total_in_battery
                else:
                    sf = 0.0
                total_solar_batt_to_load += battery_to_load * sf
                total_grid_batt_to_load += battery_to_load * (1.0 - sf)
                soc_from_solar -= soc_withdrawn * sf
                soc_from_grid -= soc_withdrawn * (1.0 - sf)
                soc_from_solar = max(0.0, soc_from_solar)
                soc_from_grid = max(0.0, soc_from_grid)
            total_battery_to_load_kwh += battery_to_load
            remaining_load -= battery_to_load

            # 4) Grid import covers whatever battery couldn't
            grid_import = remaining_load
            total_grid_import_kwh += grid_import
            total_cost_pence += grid_import * import_price
            total_grid_direct_cost_pence += grid_import * import_price

            # 5) Smart grid charging — absolute minimum to maintain supply.
            if tou_opt and soc < usable_capacity - 1e-6:
                energy_ahead = kwh_until_solar[i]
                soc_needed = min_soc + energy_ahead / (sqrt_eff if sqrt_eff > 0 else 1.0)
                charge_deficit = max(0.0, soc_needed - soc)

                if charge_deficit > 0.01:
                    do_charge = False
                    if is_cheap[i]:
                        do_charge = True
                    elif soc <= min_soc + 0.05:
                        do_charge = True

                    if do_charge:
                        grid_kwh = min(charge_deficit / sqrt_eff,
                                       max_charge_per_slot,
                                       (usable_capacity - soc) / sqrt_eff)
                        if grid_kwh > 0.01:
                            energy_stored = grid_kwh * sqrt_eff
                            soc += energy_stored
                            soc_from_grid += energy_stored
                            total_grid_import_kwh += grid_kwh
                            total_grid_charge_kwh += grid_kwh
                            total_cost_pence += grid_kwh * import_price
                            total_grid_charge_cost_pence += grid_kwh * import_price

            # 6) Export remaining solar surplus (optional — Maximiser can mirror "no export")
            if allow_surplus_export:
                total_grid_export_kwh += exported_solar
                total_export_revenue_pence += exported_solar * export_price

            soc = max(min_soc, min(usable_capacity, soc))
            tot_src = soc_from_solar + soc_from_grid
            if tot_src > 1e-9 and abs(tot_src - soc) > 1e-4:
                rscale = soc / tot_src
                soc_from_solar = max(0.0, soc_from_solar * rscale)
                soc_from_grid = max(0.0, soc - soc_from_solar)
            elif tot_src <= 1e-9 and soc > 1e-9:
                soc_from_solar = 0.0
                soc_from_grid = soc
            soc_history.append((timestamps[i], soc / capacity * 100))
            grid_import_history.append((timestamps[i], grid_import))

        # free_kwh = solar direct + solar-sourced battery discharge
        # paid_kwh = grid direct + grid-sourced battery discharge + grid charge
        grid_direct_to_load = total_grid_import_kwh - total_grid_charge_kwh
        return {
            'total_grid_import_kwh': total_grid_import_kwh,
            'total_grid_export_kwh': total_grid_export_kwh,
            'total_cost_pence': total_cost_pence,
            'total_export_revenue_pence': total_export_revenue_pence,
            'total_solar_self_consumed_kwh': total_solar_self_consumed_kwh,
            'total_battery_to_load_kwh': total_battery_to_load_kwh,
            'total_solar_batt_to_load_kwh': total_solar_batt_to_load,
            'total_grid_batt_to_load_kwh': total_grid_batt_to_load,
            'total_self_consumed_kwh': total_solar_self_consumed_kwh + total_battery_to_load_kwh,
            'total_grid_charge_kwh': total_grid_charge_kwh,
            'grid_direct_to_load_kwh': grid_direct_to_load,
            'total_grid_direct_cost_pence': total_grid_direct_cost_pence,
            'total_grid_charge_cost_pence': total_grid_charge_cost_pence,
            'total_load_kwh': total_load_kwh,
            'total_solar_kwh': total_solar_kwh,
            'soc_history': soc_history,
            'grid_import_history': grid_import_history,
        }

    def _simulate_no_battery(self, merged, slot_prices, flat_export_p):
        """No-battery baseline: solar serves load directly, rest from grid, surplus exported."""
        total_cost_pence = total_export_revenue_pence = 0
        total_grid_import = total_grid_export = total_solar_direct = 0
        total_load = total_solar = 0
        for ts, row in merged.iterrows():
            load = row['load_kWh']
            solar = row['solar_kWh']
            import_price = float(slot_prices.loc[ts]) if ts in slot_prices.index else 24.5
            total_load += load
            total_solar += solar
            solar_to_load = min(solar, load)
            total_solar_direct += solar_to_load
            grid_import = load - solar_to_load
            grid_export = solar - solar_to_load
            total_grid_import += grid_import
            total_grid_export += grid_export
            total_cost_pence += grid_import * import_price
            total_export_revenue_pence += grid_export * flat_export_p
        return {
            'total_grid_import_kwh': total_grid_import,
            'total_grid_export_kwh': total_grid_export,
            'total_cost_pence': total_cost_pence,
            'total_export_revenue_pence': total_export_revenue_pence,
            'total_solar_self_consumed_kwh': total_solar_direct,
            'total_battery_to_load_kwh': 0,
            'total_solar_batt_to_load_kwh': 0,
            'total_grid_batt_to_load_kwh': 0,
            'total_self_consumed_kwh': total_solar_direct,
            'total_grid_charge_kwh': 0,
            'grid_direct_to_load_kwh': total_grid_import,
            'total_grid_direct_cost_pence': total_cost_pence,
            'total_grid_charge_cost_pence': 0,
            'total_load_kwh': total_load,
            'total_solar_kwh': total_solar,
            'soc_history': [], 'grid_import_history': [],
            'label': 'No Battery', 'capacity': 0, 'color': '#9E9E9E',
        }

    def _not_enough_data_message(self, growatt_slots, octopus_slots, days):
        """Plain-English reason the simulator refused to annualise a thin history."""
        lines = ["Not enough data to run this simulation.", ""]
        lines.append(
            "A useful run needs at least one full day of half-hour slots (48). "
            f"The window you asked for is {days} days."
        )
        lines.append("")
        if growatt_slots <= 0:
            lines.append("Growatt database: no load and solar history in that window.")
        else:
            lines.append(
                f"Growatt database: {growatt_slots} half-hour slots "
                "(need 48 or more)."
            )
        if octopus_slots <= 0:
            lines.append("Octopus import meter: no readings came back for that window.")
        else:
            lines.append(
                f"Octopus import meter: {octopus_slots} half-hour slots "
                "(need 48 or more)."
            )
        lines.append("")
        lines.append(
            "Enable database logging so Growatt load and solar are stored, "
            "or fetch Octopus data, then run the simulation again."
        )
        return "\n".join(lines)

    def _clear_chart_notice(self):
        notice = getattr(self, "_chart_notice", None)
        if notice is not None:
            try:
                notice.remove()
            except Exception:
                pass
            self._chart_notice = None

    def _show_chart_notice(self, message):
        """Replace the four plots with one centred explanation."""
        self._clear_chart_notice()
        self.fig.set_facecolor(_DARK_BG)
        for ax in (self.ax_bill, self.ax_self, self.ax_soc, self.ax_payback):
            ax.clear()
            ax.set_facecolor(_DARK_BG)
            ax.set_axis_off()
        self._chart_notice = self.fig.text(
            0.5, 0.5, message,
            ha="center", va="center",
            color=_DARK_TEXT,
            fontsize=12,
            multialignment="center",
        )
        self.canvas.draw_idle()

    def _sim_error(self, msg):
        self._chart_shimmer.stop()
        self.fetching = False
        self.run_btn.setEnabled(True)
        self.progress_label.setText("")
        self.results_text.setPlainText(msg)
        self._show_chart_notice(msg)
        self.set_status("Not enough data to run the battery expansion simulation.")

    def _update_display(self):
        self._chart_shimmer.stop()
        self.fetching = False
        self.run_btn.setEnabled(True)
        self.progress_label.setText("")
        # Fire the freshness callback BEFORE rendering — by the time we get
        # here the data is already computed and stored on `self.sim_results`,
        # so the tab is genuinely fresh even if a downstream render step
        # raises.  Otherwise a stray exception in `_plot_charts` (etc.) would
        # silently leave the tab text white.
        if self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception as e:
                _log.warn("Analytics", f"on_data_updated callback failed: {e}")
        self._plot_charts()
        self._write_results()
        self._preview_custom_scenario()
        self.set_status("Battery expansion simulation complete.")

    def _plot_charts(self):
        import matplotlib.dates as mdates
        results = self.sim_results
        self._clear_chart_notice()
        for ax in [self.ax_bill, self.ax_self, self.ax_soc, self.ax_payback]:
            ax.clear()
            ax.set_axis_on()
        scenarios = ['No Battery', 'Current (2x)', '3 Batteries', '4 Batteries']
        colors = ['#9E9E9E', '#2196F3', '#FF9800', '#4CAF50']
        present = [(s, c) for s, c in zip(scenarios, colors) if s in results]
        labels = [s for s, _ in present]
        cols = [c for _, c in present]
        bills = [results[s]['annual_bill'] for s in labels]
        bars = self.ax_bill.bar(labels, bills, color=cols, alpha=0.85, edgecolor='none')
        for bar, val in zip(bars, bills):
            self.ax_bill.text(bar.get_x()+bar.get_width()/2, bar.get_height()+max(bills)*0.02,
                              f'\u00a3{val:.0f}', ha='center', va='bottom', fontweight='bold', fontsize=9)
        self.ax_bill.set_ylabel('Annual Bill (\u00a3)')
        src = getattr(self, '_data_source_label', '')
        src_suffix = f'  [{src}]' if src else ''
        self.ax_bill.set_title(f'Projected Annual Electricity Bill{src_suffix}', fontsize=10)
        self.ax_bill.grid(axis='y', alpha=0.3)
        all_scenarios = [s for s in labels]
        if all_scenarios:
            import_cost_vals, charge_cost_vals, export_credit_vals = [], [], []
            for s in all_scenarios:
                r = results[s]
                import_cost_vals.append(
                    r.get('total_grid_direct_cost_pence', 0) * 365 / max(self.sim_actual_days, 1) / 100
                )
                charge_cost_vals.append(
                    r.get('total_grid_charge_cost_pence', 0) * 365 / max(self.sim_actual_days, 1) / 100
                )
                export_credit_vals.append(r.get('daily_export_revenue', 0) * 365 / 100)
            x = np.arange(len(all_scenarios))
            self.ax_self.bar(x, import_cost_vals, 0.55, color='#F44336', alpha=0.55,
                             label='Grid -> Load cost')
            self.ax_self.bar(x, charge_cost_vals, 0.55, bottom=import_cost_vals,
                             color='#fab005', alpha=0.7, label='Grid -> Battery cost')
            self.ax_self.bar(x, [-v for v in export_credit_vals], 0.55,
                             color='#40c057', alpha=0.8, label='Export credit')
            net_vals = [a + b - c for a, b, c in zip(import_cost_vals, charge_cost_vals, export_credit_vals)]
            for xi, net in zip(x, net_vals):
                self.ax_self.text(xi, net + max(bills) * 0.02, f'£{net:.0f}',
                                  ha='center', va='bottom', fontsize=8, fontweight='bold')
            self.ax_self.set_xticks(x)
            self.ax_self.set_xticklabels(all_scenarios, fontsize=8)
            self.ax_self.set_ylabel('Annual £')
            self.ax_self.set_title('Annual Cost Breakdown', fontsize=10)
            self.ax_self.legend(fontsize=7, loc='upper right')
            self.ax_self.axhline(y=0, color='gray', linewidth=0.8, alpha=0.7)
            self.ax_self.grid(axis='y', alpha=0.3)
        nd = max(1, int(self.sim_actual_days))
        for label, capacity, color in self.SCENARIOS:
            if label in results:
                soc_hist = results[label]['soc_history']
                if soc_hist:
                    times = [t for t, _ in soc_hist]
                    vals = [v for _, v in soc_hist]
                    self.ax_soc.plot(times, vals, color=color, linewidth=1, label=label, alpha=0.8)
        self.ax_soc.axhline(y=10, color='red', linestyle='--', linewidth=0.8, alpha=0.5, label='10% threshold')
        self.ax_soc.set_ylabel('SOC %')
        day_lbl = f'{nd} days' if nd != 1 else '1 day'
        self.ax_soc.set_title(f'Battery SOC Comparison ({day_lbl})')
        self.ax_soc.set_ylim(0, 105)
        self.ax_soc.legend(fontsize=7, loc='upper right')
        self.ax_soc.grid(True, alpha=0.3)
        soc_loc = mdates.AutoDateLocator(maxticks=min(14, max(5, nd)))
        self.ax_soc.xaxis.set_major_locator(soc_loc)
        self.ax_soc.xaxis.set_major_formatter(mdates.ConciseDateFormatter(soc_loc))
        self.ax_soc.tick_params(axis='x', rotation=25)
        upgrade_present = [s for s in ['3 Batteries', '4 Batteries'] if s in results]
        if upgrade_present:
            years = np.arange(0, 16)
            for s in upgrade_present:
                r = results[s]
                cumulative = -r['extra_cost'] + years * r['annual_saving_vs_current']
                color = [c for l, c in present if l == s][0]
                self.ax_payback.plot(years, cumulative, color=color, linewidth=2, label=s, marker='o', markersize=3)
                if r['annual_saving_vs_current'] > 0:
                    be = r['extra_cost'] / r['annual_saving_vs_current']
                    if be <= 15:
                        self.ax_payback.axvline(x=be, color=color, linestyle=':', alpha=0.5)
                        self.ax_payback.annotate(f'{be:.1f}yr', xy=(be, 0), fontsize=8, color=color)
            self.ax_payback.axhline(y=0, color='gray', linewidth=0.8)
            self.ax_payback.set_xlabel('Years')
            self.ax_payback.set_ylabel('Cumulative Saving (\u00a3)')
            self.ax_payback.set_title('Payback Period vs Current Setup')
            self.ax_payback.legend(fontsize=8)
            self.ax_payback.grid(True, alpha=0.3)
        # Multi-day SOC chart: only mark midnight boundaries — the intra-day
        # 3 / 6-hourly grid that suits the live tabs becomes visual noise
        # here where each day is just a few pixels wide.
        _draw_6h_vertical_grid(self.ax_soc, primary_hours=(0,), secondary_hours=())
        _draw_day_date_labels(self.ax_soc)
        self.ax_bill.format_coord = lambda xv, yv: (
            f"Horizontal (x): scenario index ~{xv:.2f} — which battery case  |  "
            f"{_fmt_toolbar_y(yv, '£/year', 'simulated annual electricity bill')}"
        )
        self.ax_self.format_coord = lambda xv, yv: (
            f"Horizontal (x): scenario index ~{xv:.2f} — stacked cost components  |  "
            f"{_fmt_toolbar_y(yv, '£/year', 'import cost stack minus export credit height')}"
        )
        self.ax_soc.format_coord = lambda xv, yv: _fmt_toolbar_time_y(
            xv, yv, None, "% SOC",
            "modelled battery charge level for the selected period",
        )
        self.ax_payback.format_coord = lambda xv, yv: (
            f"Horizontal (x): years after purchase  |  "
            f"{_fmt_toolbar_y(yv, '£', 'cumulative saving vs extra battery cost (upgrades)')}"
        )
        # GridSpec already owns spacing; tight_layout warns and can mis-pad.
        self.fig.subplots_adjust(
            left=0.07, right=0.98, top=0.93, bottom=0.08,
            hspace=0.35, wspace=0.30,
        )
        self.canvas.draw()

    def _write_results(self):
        results = self.sim_results
        days = self.sim_actual_days
        src = getattr(self, '_data_source_label', 'Unknown')
        lines = []
        lines.append(f"Data source: {src}   |   Period: {days} days")
        lines.append("")
        lines.append("Grid kWh = total electricity bought from the grid (includes overnight battery charging).")
        lines.append("That total, at Agile/flat rates, drives the annual bill — not the same as the red slice in the mix chart.")
        lines.append("")
        lines.append(f"{'Scenario':<18} {'Grid kWh':>10} {'Solar+Batt':>11} {'Annual Bill':>12} {'vs Current':>11} {'Payback':>10}")
        lines.append("-" * 80)
        for label in ['No Battery', 'Current (2x)', '3 Batteries', '4 Batteries']:
            if label not in results:
                continue
            r = results[label]
            payback_str = "--"
            if r.get('payback_years') is not None:
                payback_str = f"{r['payback_years']:.1f} yrs"
            elif label == 'Current (2x)':
                payback_str = "baseline"
            saving_str = f"\u00a3{r['annual_saving_vs_current']:+.0f}/yr" if label != 'No Battery' else "--"
            self_use = r.get('total_self_consumed_kwh', 0)
            lines.append(f"{label:<18} {r['total_grid_import_kwh']:>10.1f} {self_use:>11.1f} "
                         f"\u00a3{r['annual_bill']:>10.0f} {saving_str:>11} {payback_str:>10}")
        lines.append("")
        lines.append("DETAILED BREAKDOWN:")
        for label in ['No Battery', 'Current (2x)', '3 Batteries', '4 Batteries']:
            if label not in results:
                continue
            r = results[label]
            tl = r.get('total_load_kwh', 0)
            lines.append(f"\n  {label}  (total load: {tl:.1f} kWh = {tl/days:.1f} kWh/day):")
            if tl <= 0:
                continue
            solar_d = r.get('total_solar_self_consumed_kwh', 0)
            solar_b = r.get('total_solar_batt_to_load_kwh', 0)
            grid_b = r.get('total_grid_batt_to_load_kwh', 0)
            grid_d = r.get('grid_direct_to_load_kwh', r['total_grid_import_kwh'])
            gch = r.get('total_grid_charge_kwh', 0)
            free_kwh = solar_d + solar_b
            paid_kwh = grid_d + grid_b
            lines.append(f"    FREE ENERGY ({free_kwh/tl*100:.0f}% of load):")
            lines.append(f"      Solar → load:          {solar_d:>8.1f} kWh ({solar_d/days:.1f}/day)  {solar_d/tl*100:.0f}%")
            lines.append(f"      Solar → batt → load:   {solar_b:>8.1f} kWh ({solar_b/days:.1f}/day)  {solar_b/tl*100:.0f}%")
            lines.append(f"    PAID ENERGY ({paid_kwh/tl*100:.0f}% of load):")
            lines.append(f"      Grid → load:           {grid_d:>8.1f} kWh ({grid_d/days:.1f}/day)  {grid_d/tl*100:.0f}%")
            if grid_b > 0.1:
                lines.append(f"      Grid → batt → load:    {grid_b:>8.1f} kWh ({grid_b/days:.1f}/day)  {grid_b/tl*100:.0f}%")
            if gch > 0.1:
                lines.append(f"      Grid → battery total:  {gch:>8.1f} kWh ({gch/days:.1f}/day)  [smart charge]")
            lines.append(f"    Grid export:             {r['total_grid_export_kwh']:>8.1f} kWh ({r['total_grid_export_kwh']/days:.1f}/day)")
            ts_kwh = r.get('total_solar_kwh', 0)
            if ts_kwh > 0:
                lines.append(f"    Total solar generation:  {ts_kwh:>8.1f} kWh ({ts_kwh/days:.1f}/day)")
            lines.append(f"    Total grid import:       {r['total_grid_import_kwh']:>8.1f} kWh  →  cost basis for bill")
            if r.get('extra_cost', 0) > 0:
                lines.append(f"    Investment: \u00a3{r['extra_cost']:.0f}  |  "
                             f"Annual saving: \u00a3{r['annual_saving_vs_current']:.0f}")
                if r.get('payback_years'):
                    lines.append(f"    Payback: {r['payback_years']:.1f} years  |  "
                                 f"10-year ROI: \u00a3{r['annual_saving_vs_current']*10 - r['extra_cost']:.0f}")

        if src and 'approximate' in src.lower():
            lines.append("\n⚠ Octopus-only proxy: load = import+export and solar = export per half-hour.")
            lines.append("  Green in the chart labels export in that model — not measured on-site PV use.")
            lines.append("  Initial battery energy is no longer mis-labelled as 'free solar'.")
            lines.append("  For trustworthy load, PV generation, and mix vs bill: enable Growatt DB logging.")
        self.results_text.setPlainText('\n'.join(lines))


__all__ = [n for n in globals() if not n.startswith('__')]
