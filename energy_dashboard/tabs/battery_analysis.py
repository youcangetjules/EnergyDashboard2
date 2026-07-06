"""
Energy Dashboard — `tabs/battery_analysis.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
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
        # Set by EnergyDashboard.build_ui so the global "freshness" colour-
        # coding on the tab bar updates when the user re-fetches.
        self.on_data_updated = None
        self.build_ui()

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
        ctrl_layout.addSpacing(20)
        ctrl_layout.addWidget(QLabel("Battery Capacity (kWh):"))
        self.capacity_edit = QLineEdit("13.0")
        self.capacity_edit.setFixedWidth(50)
        ctrl_layout.addWidget(self.capacity_edit)
        ctrl_layout.addWidget(QLabel("Low SOC Threshold (%):"))
        self.threshold_edit = QLineEdit("10")
        self.threshold_edit.setFixedWidth(40)
        ctrl_layout.addWidget(self.threshold_edit)
        self.fetch_btn = QPushButton("Fetch Battery History")
        self.fetch_btn.clicked.connect(self.fetch_history)
        ctrl_layout.addWidget(self.fetch_btn)
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
        self.events_tree = QTreeWidget()
        self.events_tree.setHeaderLabels(['Time', 'Min SOC %', 'Duration', 'Avg Load kW', 'Grid kWh'])
        self.events_tree.setColumnCount(5)
        self.events_tree.setColumnWidth(0, 110)
        self.events_tree.setColumnWidth(1, 65)
        self.events_tree.setColumnWidth(2, 65)
        self.events_tree.setColumnWidth(3, 70)
        self.events_tree.setColumnWidth(4, 65)
        qtree_set_column_width_key(self.events_tree, "battery_analysis_events")
        qtree_prepare_interactive_columns(self.events_tree)
        qtree_restore_column_widths(self.events_tree, "battery_analysis_events", resize_if_no_saved=True)
        qtree_attach_column_width_persistence(self.events_tree)
        events_layout.addWidget(self.events_tree)
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
        if self.app_params is None:
            return
        p = self.app_params
        self.capacity_edit.setText(f"{p.battery_capacity_kwh:.1f}".rstrip('0').rstrip('.'))
        self.threshold_edit.setText(str(int(p.battery_low_soc_threshold_pct)))

    def fetch_history(self):
        api, plant_id, device_sn = self.growatt_tab.get_api()
        try:
            self.battery_capacity = float(self.capacity_edit.text())
            self.soc_threshold = float(self.threshold_edit.text())
        except ValueError:
            QMessageBox.critical(self, "Invalid Input", "Battery capacity and threshold must be numbers.")
            return
        if self.fetching:
            return
        self.fetching = True
        self.fetch_btn.setEnabled(False)
        self._chart_shimmer.start()
        threading.Thread(target=self._fetch_thread, args=(api, plant_id, device_sn), daemon=True).start()

    def _fetch_thread(self, api, plant_id, device_sn):
        try:
            days = self.days_group.checkedId()
            all_records = []
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
            all_records = list(api_records)
            db_records = []
            readings_records = []
            dl = getattr(self.dash, "data_logger", None) if self.dash else None
            if dl is not None:
                if api_records:
                    dl.log_growatt_mix_chart(device_sn, api_records)
                else:
                    db_records = dl.query_growatt_mix_chart(device_sn, days) if device_sn else []
                    if db_records:
                        all_records = db_records
                    else:
                        readings_records = dl.query_growatt_battery_history_from_readings(days)
                        if readings_records:
                            all_records = readings_records
            if not all_records:
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
            source = (
                "Growatt cloud"
                if api_records
                else "stored MIX chart"
                if db_records
                else "local GROTT/Growatt readings"
            )
            df = pd.DataFrame(all_records).sort_values('timestamp').reset_index(drop=True)
            current_soc = self.growatt_tab.get_current_soc()
            df = self._reconstruct_soc(df, current_soc)
            self.low_soc_events = self._detect_low_soc(df)
            insights = self._generate_insights(df)
            self._inv.invoke(lambda: self._update_display(df, insights, source))
        except Exception as e:
            err = str(e)
            self._inv.invoke(lambda msg=err: self._fetch_done_error(f"Error: {msg}"))

    def _reconstruct_soc(self, df, current_soc):
        capacity = self.battery_capacity
        if 'soc_pct' in df.columns and df['soc_pct'].notna().any():
            df['soc_pct'] = pd.to_numeric(df['soc_pct'], errors='coerce').clip(0.0, 100.0)
            df['soc_pct'] = df['soc_pct'].interpolate(limit_direction='both')
            df['soc_kWh'] = (df['soc_pct'] / 100.0) * capacity
            return df
        interval_hours = 5.0 / 60.0
        df['energy_delta_kWh'] = (df['charge_kW'] - df['discharge_kW']) * interval_hours
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
        for idx, row in df.iterrows():
            if row['soc_pct'] < threshold:
                if not in_event:
                    in_event = True
                    event_start = row['timestamp']
                    event_rows = []
                event_rows.append(row)
            else:
                if in_event:
                    event_end = event_rows[-1]['timestamp']
                    duration_min = (event_end - event_start).total_seconds() / 60
                    min_soc = min(r['soc_pct'] for r in event_rows)
                    avg_load = np.mean([r['load_kW'] for r in event_rows])
                    grid_kwh = sum(r['grid_import_kW'] * (5.0 / 60.0) for r in event_rows)
                    events.append({'start': event_start, 'end': event_end, 'min_soc': min_soc,
                                   'duration_min': duration_min, 'avg_load_kW': avg_load, 'grid_import_kWh': grid_kwh})
                    in_event = False
                    event_rows = []
        if in_event and event_rows:
            event_end = event_rows[-1]['timestamp']
            duration_min = (event_end - event_start).total_seconds() / 60
            min_soc = min(r['soc_pct'] for r in event_rows)
            avg_load = np.mean([r['load_kW'] for r in event_rows])
            grid_kwh = sum(r['grid_import_kW'] * (5.0 / 60.0) for r in event_rows)
            events.append({'start': event_start, 'end': event_end, 'min_soc': min_soc,
                           'duration_min': duration_min, 'avg_load_kW': avg_load, 'grid_import_kWh': grid_kwh})
        return events

    def _generate_insights(self, df):
        lines = []
        threshold = self.soc_threshold
        capacity = self.battery_capacity
        days = self.days_group.checkedId()
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
        lines.append("")
        lines.append("--- Recommendations ---")
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

    def _fetch_done_error(self, msg):
        self._chart_shimmer.stop()
        self.fetching = False
        self.fetch_btn.setEnabled(True)
        self.progress_label.setText("")
        self.set_status(msg)
        QMessageBox.critical(self, "Battery Analysis", msg)

    _BATTERY_CHART_LEFT_PAD_PX = 50

    def _apply_battery_chart_layout(self):
        """Keep ~50 px between the canvas left edge and the plot area."""
        canvas_w = max(
            int(self.canvas.width()),
            int(self.fig.get_figwidth() * self.fig.dpi),
            1,
        )
        left = self._BATTERY_CHART_LEFT_PAD_PX / canvas_w
        self.fig.subplots_adjust(
            hspace=0.22, top=0.98, bottom=0.10,
            left=left, right=0.99,
        )

    def _on_battery_canvas_resize(self, _event):
        if self._battery_hover_df is None:
            return
        self._apply_battery_chart_layout()
        self.canvas.draw_idle()

    def _draw_charts(self, df):
        import matplotlib.dates as mdates

        self.ax_soc.clear()
        self.ax_power.clear()
        self.ax_soc.tick_params(labelbottom=False)
        threshold = self.soc_threshold
        timestamps = df['timestamp']
        soc = df['soc_pct']
        self.ax_soc.plot(timestamps, soc, color='#2196F3', linewidth=1.2, label='SOC %')
        self.ax_soc.fill_between(timestamps, soc, 50, where=(soc >= 50), alpha=0.3, color='green', interpolate=True)
        self.ax_soc.fill_between(timestamps, soc, 20, where=((soc >= 20) & (soc < 50)), alpha=0.3, color='#FFC107', interpolate=True)
        self.ax_soc.fill_between(timestamps, soc, 0, where=(soc < 20), alpha=0.3, color='red', interpolate=True)
        self.ax_soc.axhline(y=threshold, color='red', linestyle='--', linewidth=1, alpha=0.7, label=f'{threshold}% threshold')
        self.ax_soc.fill_between(timestamps, 0, 100, where=(soc < threshold), alpha=0.1, color='red', interpolate=True)
        self.ax_soc.set_ylabel('SOC %')
        self.ax_soc.set_ylim(0, 105)
        self.ax_soc.set_title('Battery State of Charge', pad=4)
        self.ax_soc.grid(True, which='major', alpha=0.3)
        self.ax_soc.grid(True, which='minor', alpha=0.12)
        self.ax_power.fill_between(timestamps, df['pv_kW'], alpha=0.6, color='#FF9800', label='PV')
        self.ax_power.fill_between(timestamps, df['charge_kW'], alpha=0.5, color='#4CAF50', label='Charge')
        self.ax_power.plot(timestamps, df['discharge_kW'], color='#2196F3', linewidth=1, label='Discharge')
        self.ax_power.plot(timestamps, df['grid_import_kW'], color='#F44336', linewidth=1, label='Grid Import')
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
        _battery_power_draw_prev_day_totals(self.ax_power, df, _lon_bt)
        for _leg in self.fig.legends:
            _leg.remove()
        _handles_soc, _labels_soc = self.ax_soc.get_legend_handles_labels()
        _handles_pwr, _labels_pwr = self.ax_power.get_legend_handles_labels()
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
        if event.inaxes not in (self.ax_soc, self.ax_power) or event.xdata is None:
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
        if event.inaxes == self.ax_soc and event.ydata is not None:
            self._hline_soc.set_ydata([event.ydata, event.ydata])
            self._hline_soc.set_visible(True)
            self._hline_power.set_visible(False)
        elif event.inaxes == self.ax_power and event.ydata is not None:
            self._hline_power.set_ydata([event.ydata, event.ydata])
            self._hline_power.set_visible(True)
            self._hline_soc.set_visible(False)
        self.cursor_info_label.setText(
            f"{ts_str}  |  SOC {row['soc_pct']:.1f}%  |  PV {row['pv_kW']:.2f}  Chg {row['charge_kW']:.2f}  "
            f"Dsch {row['discharge_kW']:.2f}  Imp {row['grid_import_kW']:.2f}  Exp {row['grid_export_kW']:.2f}  "
            f"Load {row['load_kW']:.2f} kW"
        )
        self.canvas.draw_idle()

    def _populate_events_table(self):
        self.events_tree.clear()
        for event in self.low_soc_events:
            dur = event['duration_min']
            dur_str = f"{int(dur//60)}h {int(dur%60)}m" if dur >= 60 else f"{int(dur)}m"
            item = QTreeWidgetItem([
                event['start'].strftime('%m-%d %H:%M'), f"{event['min_soc']:.1f}",
                dur_str, f"{event['avg_load_kW']:.2f}", f"{event['grid_import_kWh']:.2f}"])
            self.events_tree.addTopLevelItem(item)


__all__ = [n for n in globals() if not n.startswith('__')]
