"""
Energy Dashboard — `tabs/octopus_live.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
class OctopusLiveTab(QWidget):
    @staticmethod
    def _apply_figure_layout(fig):
        """Fixed margins for the stacked live charts.

        ``tight_layout`` warns (and often fails) once both axes carry rotated
        x-tick labels, day-date annotations above the plot, and per-day kWh
        totals — there is not enough vertical room for it to auto-pad.
        """
        fig.subplots_adjust(
            left=0.07, right=0.98,
            top=0.90, bottom=0.14,
            hspace=0.14,
        )

    @staticmethod
    def _tight_y_from_artists(ax, pad_frac=0.055):
        """Set y-limits from patches/collections/step lines only — trim default slack.

        Skips horizontal reference lines and vertical “Now” / “Latest data” lines
        so they do not dictate the scale.
        """
        import numpy as np
        ys = []
        for p in ax.patches:
            y0 = float(p.get_y())
            y1 = float(p.get_y() + p.get_height())
            if np.isfinite(y0) and np.isfinite(y1):
                ys.extend([y0, y1])
        for coll in ax.collections:
            for path in coll.get_paths():
                v = path.vertices[:, 1]
                vv = v[np.isfinite(v)]
                if vv.size:
                    ys.extend([float(vv.min()), float(vv.max())])
        import matplotlib.dates as _mdates
        for ln in ax.lines:
            lab = (ln.get_label() or '').replace('_nolegend_', '')
            if lab in ('Now', 'Latest data'):
                continue
            xd_raw = ln.get_xdata()
            try:
                xd = np.asarray(xd_raw, dtype=float)
            except (TypeError, ValueError):
                # `axvline` / time-series lines may carry datetimes / Timestamps
                # that do not coerce directly to float — convert via mdates.
                try:
                    xd = np.asarray(_mdates.date2num(xd_raw), dtype=float)
                except Exception:
                    xd = np.array([], dtype=float)
            xd = xd[np.isfinite(xd)]
            if xd.size >= 2:
                x0 = float(xd[0])
                if np.ptp(xd) <= 1e-12 * max(1.0, abs(x0)):
                    continue  # vertical guide — y spans padded ylim, would undo tightening
            yd = np.asarray(ln.get_ydata(), dtype=float)
            yd = yd[np.isfinite(yd)]
            if yd.size < 2:
                continue
            if np.ptp(yd) <= 1e-12 * max(1.0, abs(float(yd[0]))):
                continue
            ys.extend([float(yd.min()), float(yd.max())])
        if not ys:
            return
        arr = np.array(ys, dtype=float)
        lo, hi = float(np.min(arr)), float(np.max(arr))
        if not np.isfinite(lo) or not np.isfinite(hi):
            return
        if lo == hi:
            d = max(abs(lo) * 0.05, 1.0)
            lo, hi = lo - d, hi + d
        span = hi - lo
        pad = max(span * pad_frac, 1e-9)
        ax.set_ylim(lo - pad, hi + pad)

    @staticmethod
    def _slot_minutes(src, granularity_id=1):
        if src == 'GraphQL':
            return {1: 30, 2: 15, 3: 5}.get(granularity_id, 30)
        return 30

    @staticmethod
    def _net_bar_width_days(src, granularity_id=1):
        mins = OctopusLiveTab._slot_minutes(src, granularity_id)
        return mins / (24.0 * 60.0)

    @staticmethod
    def _floor_consumption_by_slot(df, slot_minutes: int):
        """Sum kWh per metering slot (import/export meters rarely share identical readAt)."""
        if df is None or df.empty:
            return pd.DataFrame(columns=['interval_start', 'consumption'])
        out = df[['interval_start', 'consumption']].copy()
        out['interval_start'] = pd.to_datetime(out['interval_start'])
        out['consumption'] = pd.to_numeric(out['consumption'], errors='coerce').fillna(0)
        slot = out['interval_start'].dt.floor(f'{int(slot_minutes)}min')
        return (
            out.assign(_slot=slot)
            .groupby('_slot', as_index=False)['consumption']
            .sum()
            .rename(columns={'_slot': 'interval_start'})
            .sort_values('interval_start')
            .reset_index(drop=True)
        )

    @staticmethod
    def _build_net_kwh_series(imp_view, exp_view, src='REST', granularity_id=1):
        """Import minus export kWh on aligned interval timestamps."""
        cols = ['interval_start', 'net_kwh']
        if (imp_view is None or imp_view.empty) and (exp_view is None or exp_view.empty):
            return pd.DataFrame(columns=cols)

        slot_min = OctopusLiveTab._slot_minutes(src, granularity_id)
        imp = OctopusLiveTab._floor_consumption_by_slot(imp_view, slot_min)
        exp = OctopusLiveTab._floor_consumption_by_slot(exp_view, slot_min)
        if imp.empty and exp.empty:
            return pd.DataFrame(columns=cols)
        if imp.empty:
            exp = exp.copy()
            exp['net_kwh'] = -exp['consumption']
            return exp[['interval_start', 'net_kwh']]
        if exp.empty:
            imp = imp.copy()
            imp['net_kwh'] = imp['consumption']
            return imp[['interval_start', 'net_kwh']]

        merged = imp.merge(
            exp, on='interval_start', how='outer', suffixes=('_imp', '_exp'),
        )
        merged['net_kwh'] = merged['consumption_imp'].fillna(0) - merged['consumption_exp'].fillna(0)
        return merged[['interval_start', 'net_kwh']].sort_values('interval_start').reset_index(drop=True)

    @staticmethod
    def _build_cumulative_kwh_series(imp_view, exp_view, src='REST', granularity_id=1):
        """Running totals of import and export kWh (integral of top-chart interval energy)."""
        cols = ['interval_start', 'cum_import_kwh', 'cum_export_kwh', 'cum_net_kwh']
        slot_min = OctopusLiveTab._slot_minutes(src, granularity_id)
        imp = OctopusLiveTab._floor_consumption_by_slot(imp_view, slot_min)
        exp = OctopusLiveTab._floor_consumption_by_slot(exp_view, slot_min)
        if imp.empty and exp.empty:
            return pd.DataFrame(columns=cols)
        if imp.empty:
            merged = exp.rename(columns={'consumption': 'consumption_exp'}).copy()
            merged['consumption_imp'] = 0.0
        elif exp.empty:
            merged = imp.rename(columns={'consumption': 'consumption_imp'}).copy()
            merged['consumption_exp'] = 0.0
        else:
            merged = imp.merge(
                exp, on='interval_start', how='outer', suffixes=('_imp', '_exp'),
            )
        merged = merged.sort_values('interval_start').reset_index(drop=True)
        imp_kwh = merged['consumption_imp'].fillna(0.0)
        exp_kwh = merged['consumption_exp'].fillna(0.0)
        merged['cum_import_kwh'] = imp_kwh.cumsum()
        merged['cum_export_kwh'] = exp_kwh.cumsum()
        merged['cum_net_kwh'] = merged['cum_import_kwh'] - merged['cum_export_kwh']
        return merged[cols]

    @staticmethod
    def _build_cumulative_kwh_series_from_demand(imp_view, src='GraphQL', granularity_id=3):
        """Running import/export/net kWh from signed demand (integral of top demand chart)."""
        cols = ['interval_start', 'cum_import_kwh', 'cum_export_kwh', 'cum_net_kwh']
        slot_min = OctopusLiveTab._slot_minutes(src, granularity_id)
        hrs = slot_min / 60.0
        out = imp_view[['interval_start', 'demand_w']].copy()
        out['interval_start'] = pd.to_datetime(out['interval_start'])
        out['demand_w'] = pd.to_numeric(out['demand_w'], errors='coerce')
        out = out.dropna(subset=['demand_w'])
        if out.empty:
            return pd.DataFrame(columns=cols)
        slot = out['interval_start'].dt.floor(f'{int(slot_min)}min')
        grouped = (
            out.assign(_slot=slot)
            .groupby('_slot', as_index=False)['demand_w']
            .mean()
            .rename(columns={'_slot': 'interval_start'})
            .sort_values('interval_start')
            .reset_index(drop=True)
        )
        w = grouped['demand_w']
        grouped['import_kwh'] = w.clip(lower=0) * hrs / 1000.0
        grouped['export_kwh'] = (-w.clip(upper=0)) * hrs / 1000.0
        grouped['cum_import_kwh'] = grouped['import_kwh'].cumsum()
        grouped['cum_export_kwh'] = grouped['export_kwh'].cumsum()
        grouped['cum_net_kwh'] = grouped['cum_import_kwh'] - grouped['cum_export_kwh']
        return grouped[cols]

    @staticmethod
    def _build_net_kwh_series_from_demand(imp_view, src='GraphQL', granularity_id=3):
        """Net kWh per slot from signed ``demand_w`` (matches the live demand chart)."""
        cols = ['interval_start', 'net_kwh']
        if imp_view is None or imp_view.empty or 'demand_w' not in imp_view.columns:
            return pd.DataFrame(columns=cols)
        out = imp_view[['interval_start', 'demand_w']].copy()
        out['interval_start'] = pd.to_datetime(out['interval_start'])
        out['demand_w'] = pd.to_numeric(out['demand_w'], errors='coerce')
        out = out.dropna(subset=['demand_w'])
        if out.empty:
            return pd.DataFrame(columns=cols)
        slot_min = OctopusLiveTab._slot_minutes(src, granularity_id)
        slot = out['interval_start'].dt.floor(f'{int(slot_min)}min')
        grouped = (
            out.assign(_slot=slot)
            .groupby('_slot', as_index=False)['demand_w']
            .mean()
            .rename(columns={'_slot': 'interval_start'})
        )
        hrs = slot_min / 60.0
        grouped['net_kwh'] = grouped['demand_w'] * hrs / 1000.0
        return grouped[cols].sort_values('interval_start').reset_index(drop=True)

    @staticmethod
    def _apply_net_chart_ylim(ax, net_vals):
        """Y scale for net kWh bars — always include zero; avoid flat −1…1 when all zeros."""
        import numpy as np
        vals = np.asarray(net_vals, dtype=float)
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            ax.set_ylim(-0.25, 0.25)
            return False
        vmax = float(np.max(np.abs(vals)))
        if vmax < 1e-9:
            ax.set_ylim(-0.01, 0.01)
            return False
        pad = max(vmax * 0.12, 0.001)
        lo = float(np.min(vals))
        hi = float(np.max(vals))
        ax.set_ylim(min(lo, 0.0) - pad, max(hi, 0.0) + pad)
        return True

    def __init__(self, status_callback):
        super().__init__()
        self.set_status = status_callback
        self._inv = Invoker(self)
        self.import_df = None
        self.export_df = None
        self._view_hours = 2
        self.fetching = False
        self.on_data_updated = None
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(30000)
        self._auto_timer.timeout.connect(self.fetch_data)
        self._auto_refresh_pending = False
        self._ctrl_filter_active = False
        # Holds the unit label widget for the live_demand card so we can
        # append "· N min ago" to it; populated in build_ui.
        self._live_demand_unit_label = None
        self.build_ui()
        self._load_saved_octopus_live()
        if self.isVisible():
            self._set_ctrl_show_filter(True)

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Vertical)

        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        ctrl_box = QGroupBox("Octopus Live Monitor")
        ctrl_vlayout = QVBoxLayout(ctrl_box)
        row0 = QHBoxLayout()
        row0.addWidget(QLabel("API Key:"))
        self.api_key_edit = QLineEdit(DEFAULT_OCTOPUS_KEY)
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setMinimumWidth(280)
        row0.addWidget(self.api_key_edit)
        row0.addSpacing(15)
        row0.addWidget(QLabel("Hours:"))
        self.hours_group = QButtonGroup(self)
        for text, val in [("2h", 2), ("6h", 6), ("12h", 12), ("24h", 24), ("48h", 48)]:
            rb = QRadioButton(text)
            self.hours_group.addButton(rb, val)
            row0.addWidget(rb)
        self.hours_group.button(2).setChecked(True)
        self.hours_group.idClicked.connect(self._on_hours_changed)
        self._show_api_key_btn = QPushButton("Show")
        self._show_api_key_btn.setVisible(False)
        self._show_api_key_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self._show_api_key_btn.setToolTip("Reveal API key (visible while Ctrl is held)")
        self._show_api_key_btn.clicked.connect(self._reveal_api_key)
        row0.addWidget(self._show_api_key_btn)
        row0.addStretch()
        ctrl_vlayout.addLayout(row0)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Account No:"))
        self.account_edit = QLineEdit(DEFAULT_OCTOPUS_ACCOUNT)
        self.account_edit.setFixedWidth(130)
        self.account_edit.setPlaceholderText("A-12345678")
        self.account_edit.setToolTip(
            "Octopus account number (e.g. A-12345678). "
            "Required for GraphQL granular telemetry."
        )
        row1.addWidget(self.account_edit)
        self.save_btn = QPushButton("Save")
        self.save_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self.save_btn.setToolTip(
            "Save API key, account number, import/export MPANs, granularity, and hours range"
        )
        self.save_btn.clicked.connect(self._save_octopus_live_clicked)
        row1.addWidget(self.save_btn)
        row1.addSpacing(15)
        row1.addWidget(QLabel("Granularity:"))
        self.granularity_group = QButtonGroup(self)
        for text, val in [("30 min", 1), ("15 min", 2), ("5 min", 3)]:
            rb = QRadioButton(text)
            self.granularity_group.addButton(rb, val)
            row1.addWidget(rb)
        self.granularity_group.button(3).setChecked(True)
        row1.addSpacing(15)
        row1.addWidget(QLabel("Import MPAN:"))
        self.import_mpan_edit = QLineEdit(DEFAULT_IMPORT_MPAN)
        self.import_mpan_edit.setFixedWidth(150)
        row1.addWidget(self.import_mpan_edit)
        row1.addWidget(QLabel("Serial:"))
        self.import_serial_edit = QLineEdit(DEFAULT_IMPORT_SERIAL)
        self.import_serial_edit.setFixedWidth(120)
        row1.addWidget(self.import_serial_edit)
        row1.addSpacing(15)
        # Fetch button + status blurb live on the same row as Import/Serial so
        # the chart area below doesn't lose two rows of vertical space to a
        # near-empty action bar.
        self.fetch_btn = QPushButton("Fetch Live Data")
        self.fetch_btn.clicked.connect(self.fetch_data)
        row1.addWidget(self.fetch_btn)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        self.status_label.setWordWrap(True)
        row1.addWidget(self.status_label, 1)
        ctrl_vlayout.addLayout(row1)

        row1b = QHBoxLayout()
        row1b.addWidget(QLabel("Export MPAN:"))
        self.export_mpan_edit = QLineEdit(DEFAULT_EXPORT_MPAN)
        self.export_mpan_edit.setFixedWidth(150)
        row1b.addWidget(self.export_mpan_edit)
        row1b.addWidget(QLabel("Serial:"))
        self.export_serial_edit = QLineEdit(DEFAULT_EXPORT_SERIAL)
        self.export_serial_edit.setFixedWidth(120)
        row1b.addWidget(self.export_serial_edit)
        row1b.addSpacing(15)
        self.gql_status = QLabel("")
        self.gql_status.setStyleSheet(f"color: {_UI_BLUE_MUTED}; font-size: 11px;")
        self.gql_status.setWordWrap(True)
        row1b.addWidget(self.gql_status, 1)
        ctrl_vlayout.addLayout(row1b)

        top_layout.addWidget(ctrl_box)

        # Cards
        cards_layout = QHBoxLayout()
        self.card_labels = {}
        for key, label, unit, color in [
            ('live_demand', 'Live Demand', 'W', '#fab387'),
            ('latest_import', 'Latest Import', 'kWh', '#F44336'),
            ('latest_export', 'Latest Export', 'kWh', '#4CAF50'),
            ('latest_net', 'Latest Net', 'kWh', '#2196F3'),
            ('total_import', 'Total Import', 'kWh', '#9C27B0'),
            ('total_export', 'Total Export', 'kWh', '#009688'),
        ]:
            if key == 'live_demand':
                card, val_label, unit_label = make_small_card(
                    label, unit, color, return_unit_label=True
                )
                self._live_demand_unit_label = unit_label
                card.setToolTip(
                    "Smart-meter household demand reported via the Octopus "
                    "GraphQL telemetry stream.\n\n"
                    "This is the meter's instantaneous power draw at the END "
                    "of the latest aggregation window — it can lag the "
                    "Growatt Load reading at the screen top by up to "
                    "(aggregation granularity + Octopus pipeline + tab "
                    "refresh interval). With 5-min granularity and a 60 s "
                    "tab refresh, the worst-case lag is ~6 minutes. The "
                    "\"· N min ago\" suffix tells you how stale the current "
                    "sample is."
                )
            else:
                card, val_label = make_small_card(label, unit, color)
            self.card_labels[key] = val_label
            cards_layout.addWidget(card)
        top_layout.addLayout(cards_layout)

        # Charts
        chart_widget = QWidget()
        chart_layout = QVBoxLayout(chart_widget)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        self.fig = Figure(figsize=(12, 5), dpi=100)
        self.ax_import = self.fig.add_subplot(211)
        self.ax_net = self.fig.add_subplot(212)
        _style_ax_dark(self.ax_import, self.fig)
        _style_ax_dark(self.ax_net, self.fig)
        self.ax_import.tick_params(axis='x', labelbottom=False)
        self._apply_figure_layout(self.fig)
        self.canvas = FigureCanvas(self.fig)
        chart_layout.addWidget(self.canvas)
        toolbar = DarkNavigationToolbar(self.canvas, self)
        chart_layout.addWidget(toolbar)
        self._chart_shimmer = ChartShimmerOverlay(self.canvas)
        top_layout.addWidget(chart_widget, 1)
        splitter.addWidget(top_widget)

        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        summary_box = QGroupBox("Live Summary")
        summary_layout = QVBoxLayout(summary_box)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setFont(QFont('Helvetica', 10))
        summary_layout.addWidget(self.summary_text)
        bottom_layout.addWidget(summary_box)
        splitter.addWidget(bottom_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)

    def showEvent(self, event):
        super().showEvent(event)
        self._set_ctrl_show_filter(True)

    def hideEvent(self, event):
        self._set_ctrl_show_filter(False)
        super().hideEvent(event)

    def _set_ctrl_show_filter(self, active: bool):
        app = QApplication.instance()
        if not app:
            return
        if active and not self._ctrl_filter_active:
            app.installEventFilter(self)
            self._ctrl_filter_active = True
        elif not active and self._ctrl_filter_active:
            app.removeEventFilter(self)
            self._ctrl_filter_active = False
            self._set_show_api_key_btn(False)

    def _set_show_api_key_btn(self, visible: bool):
        self._show_api_key_btn.setVisible(visible)
        if not visible:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)

    def eventFilter(self, watched, event):
        if not self._ctrl_filter_active:
            return super().eventFilter(watched, event)
        et = event.type()
        if et == QEvent.Type.KeyPress:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._show_api_key_btn.setVisible(True)
            elif event.key() == Qt.Key.Key_Control and not event.isAutoRepeat():
                self._show_api_key_btn.setVisible(True)
        elif et == QEvent.Type.KeyRelease:
            mods = QApplication.keyboardModifiers()
            if not (mods & Qt.KeyboardModifier.ControlModifier):
                self._set_show_api_key_btn(False)
        return super().eventFilter(watched, event)

    def _reveal_api_key(self):
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)

    @staticmethod
    def _octopus_live_settings():
        return QSettings("PowerModel", "EnergyDashboard2")

    def _load_saved_octopus_live(self):
        s = self._octopus_live_settings()
        api_key = s.value("octopus_live/api_key")
        if api_key:
            self.api_key_edit.setText(str(api_key).strip())
        for key, widget in [
            ("octopus_live/account", self.account_edit),
            ("octopus_live/import_mpan", self.import_mpan_edit),
            ("octopus_live/import_serial", self.import_serial_edit),
            ("octopus_live/export_mpan", self.export_mpan_edit),
            ("octopus_live/export_serial", self.export_serial_edit),
        ]:
            val = s.value(key)
            if val:
                widget.setText(str(val).strip())
        gran = s.value("octopus_live/granularity")
        if gran is not None:
            try:
                btn = self.granularity_group.button(int(gran))
                if btn:
                    btn.setChecked(True)
            except (ValueError, TypeError):
                pass
        hours = s.value("octopus_live/view_hours")
        if hours is not None:
            try:
                btn = self.hours_group.button(int(hours))
                if btn:
                    btn.setChecked(True)
                    self._view_hours = int(hours)
            except (ValueError, TypeError):
                pass

    def _save_octopus_live(self):
        s = self._octopus_live_settings()
        s.setValue("octopus_live/api_key", self.api_key_edit.text().strip())
        s.setValue("octopus_live/account", self.account_edit.text().strip())
        s.setValue("octopus_live/import_mpan", self.import_mpan_edit.text().strip())
        s.setValue("octopus_live/import_serial", self.import_serial_edit.text().strip())
        s.setValue("octopus_live/export_mpan", self.export_mpan_edit.text().strip())
        s.setValue("octopus_live/export_serial", self.export_serial_edit.text().strip())
        s.setValue("octopus_live/granularity", self.granularity_group.checkedId())
        s.setValue("octopus_live/view_hours", self._view_hours)
        s.sync()

    def _save_octopus_live_clicked(self):
        self._save_octopus_live()
        self.set_status("Octopus Live settings saved")
        self.gql_status.setText(
            "Saved — API key, account number, and meter details stored for next launch."
        )

    def auto_start(self):
        self.fetch_data()

    def _on_hours_changed(self, hours_id):
        self._view_hours = hours_id if hours_id > 0 else 2
        self._save_octopus_live()
        if self.import_df is not None or self.export_df is not None:
            self._plot_charts()
            self._update_summary()

    def _granularity_label(self):
        gid = self.granularity_group.checkedId()
        return {1: "HALF_HOURLY", 2: "QUARTER_HOURLY", 3: "FIVE_MINUTES"}.get(gid, "HALF_HOURLY")

    def fetch_data(self):
        if self.fetching:
            self._auto_refresh_pending = True
            return
        self.fetching = True
        self._auto_refresh_pending = False
        self._save_octopus_live()
        self.fetch_btn.setEnabled(False)
        self._chart_shimmer.start()
        self.set_status("Fetching live Octopus data...")
        api_key = self.api_key_edit.text()
        account = self.account_edit.text().strip()
        imp_mpan = self.import_mpan_edit.text()
        imp_serial = self.import_serial_edit.text()
        exp_mpan = self.export_mpan_edit.text()
        exp_serial = self.export_serial_edit.text()
        hours = self.hours_group.checkedId()
        if hours <= 0:
            hours = 2
        self._view_hours = hours
        granularity = self._granularity_label()
        threading.Thread(target=self._fetch_thread,
                         args=(api_key, account, imp_mpan, imp_serial,
                               exp_mpan, exp_serial, hours, granularity),
                         daemon=True).start()

    def _fetch_thread(self, api_key, account, imp_mpan, imp_serial,
                      exp_mpan, exp_serial, hours, granularity):
        try:
            import_df = export_df = pd.DataFrame()
            err_imp = err_exp = None
            gql_msg = ""
            self._data_source = "REST"

            if account:
                _log.info("Octopus Live", f"Trying GraphQL telemetry for account {account}, {granularity}")
                try:
                    gql_imp, gql_exp, gql_err = fetch_octopus_telemetry(
                        api_key, account, hours=hours, grouping=granularity)
                    if gql_err:
                        gql_msg = f"GraphQL: {gql_err} — falling back to REST"
                        _log.warn("Octopus Live", gql_msg)
                    elif gql_imp.empty and gql_exp.empty:
                        gql_msg = "GraphQL: auth OK but no telemetry data — falling back to REST"
                        _log.warn("Octopus Live", gql_msg)
                    else:
                        import_df = gql_imp
                        export_df = gql_exp
                        n = len(gql_imp) + len(gql_exp)
                        interval = {"HALF_HOURLY": "30min", "QUARTER_HOURLY": "15min",
                                    "FIVE_MINUTES": "5min"}.get(granularity, granularity)
                        gql_msg = f"GraphQL OK — {n} readings at {interval} granularity"
                        self._data_source = "GraphQL"
                        _log.info("Octopus Live", gql_msg)
                except Exception as e:
                    gql_msg = f"GraphQL error: {e} — falling back to REST"
                    _log.warn("Octopus Live", gql_msg)

            if self._data_source == "REST":
                if not gql_msg:
                    gql_msg = "No account number — using REST API (30-min intervals, ~24h delay)"
                _log.info("Octopus Live", f"Using REST API fallback for {hours}h window")
                try:
                    import_df, err_imp = fetch_octopus_recent(api_key, imp_mpan, imp_serial, hours)
                    _log.debug("Octopus Live", f"REST import: {len(import_df)} rows" if not import_df.empty else "REST import: empty")
                except Exception as e:
                    err_imp = str(e)
                    import_df = pd.DataFrame()
                    _log.warn("Octopus Live", f"REST import fetch error: {e}")
                try:
                    export_df, err_exp = fetch_octopus_recent(api_key, exp_mpan, exp_serial, hours)
                    _log.debug("Octopus Live", f"REST export: {len(export_df)} rows" if not export_df.empty else "REST export: empty")
                except Exception as e:
                    err_exp = str(e)
                    export_df = pd.DataFrame()
                    _log.warn("Octopus Live", f"REST export fetch error: {e}")

            self.import_df = import_df
            self.export_df = export_df
            self._live_err_imp = err_imp
            self._live_err_exp = err_exp
            self._gql_msg = gql_msg
            self._inv.invoke(self._update_display)
        except Exception as e:
            _log.warn("Octopus Live", f"Background refresh failed: {e}")
            self._inv.invoke(lambda msg=str(e): self._fetch_failed(msg))

    def _fetch_failed(self, msg):
        self._chart_shimmer.stop()
        self.fetching = False
        self.fetch_btn.setEnabled(True)
        pending = getattr(self, '_auto_refresh_pending', False)
        self._auto_refresh_pending = False
        short = (msg or "").replace("\n", " ").strip()
        if len(short) > 160:
            short = short[:157] + "..."
        self.status_label.setText(f"refresh error: {short}")
        self.gql_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
        self.gql_status.setText("Live refresh failed; the next auto-refresh tick will retry.")
        if pending:
            QTimer.singleShot(300, self.fetch_data)

    def _update_display(self):
        self._chart_shimmer.stop()
        self.fetching = False
        self.fetch_btn.setEnabled(True)
        pending = getattr(self, '_auto_refresh_pending', False)
        self._auto_refresh_pending = False
        ts = datetime.now().strftime('%H:%M:%S')
        n_imp = len(self.import_df) if self.import_df is not None else 0
        n_exp = len(self.export_df) if self.export_df is not None else 0
        src = getattr(self, '_data_source', 'REST')

        # Data freshness — how old is the latest reading?
        freshness = ""
        latest_ts = None
        for df in (self.import_df, self.export_df):
            if df is not None and not df.empty and 'interval_start' in df.columns:
                lt = df['interval_start'].max()
                if latest_ts is None or lt > latest_ts:
                    latest_ts = lt
        if latest_ts is not None:
            import pytz
            now_tz = datetime.now(pytz.timezone('Europe/London'))
            if hasattr(latest_ts, 'tzinfo') and latest_ts.tzinfo:
                age = now_tz - latest_ts
            else:
                age = datetime.now() - latest_ts
            age_min = age.total_seconds() / 60
            if age_min < 60:
                freshness = f"latest: {age_min:.0f}m ago"
            else:
                freshness = f"latest: {age_min/60:.1f}h ago"
            if age_min > self._view_hours * 60:
                freshness += " | chart shifted to latest available data"

        line = f"{src} | {n_imp} import + {n_exp} export | {freshness} | {ts}"
        tips = []
        if getattr(self, "_live_err_imp", None):
            tips.append(f"Import: {self._live_err_imp}")
        if getattr(self, "_live_err_exp", None):
            tips.append(f"Export: {self._live_err_exp}")
        self.status_label.setText(line)
        self.status_label.setToolTip("\n".join(tips) if tips else "")
        gql_msg = getattr(self, '_gql_msg', '')
        if gql_msg:
            if 'OK' in gql_msg:
                color = '#a6e3a1'
            elif 'REST API' in gql_msg or 'No account' in gql_msg:
                color = _UI_BLUE
            else:
                color = '#f38ba8'
            self.gql_status.setStyleSheet(f"color: {color}; font-size: 11px;")
            self.gql_status.setText(gql_msg)
        elif not self.account_edit.text().strip():
            self.gql_status.setStyleSheet("color: #6c7086; font-size: 11px;")
            self.gql_status.setText("Enter Account No (e.g. A-12345678) for granular GraphQL data")
        self._update_cards()
        try:
            self._plot_charts()
            self._update_summary()
        except Exception as e:
            _log.exception("Octopus Live", f"Chart update failed: {e}")
            self.set_status(f"Octopus Live chart error: {e}")
            return
        if self.on_data_updated and (n_imp > 0 or n_exp > 0):
            self.on_data_updated()
        if pending:
            QTimer.singleShot(300, self.fetch_data)

    def _update_cards(self):
        imp, exp = self.import_df, self.export_df
        has_imp = imp is not None and not imp.empty
        has_exp = exp is not None and not exp.empty

        demand_w = None
        demand_source = ""
        demand_ts = None
        # Prefer real demand_w from GraphQL telemetry
        if has_imp and 'demand_w' in imp.columns:
            valid = imp.dropna(subset=['demand_w'])
            if not valid.empty:
                demand_w = float(valid['demand_w'].iloc[-1])
                if 'interval_start' in valid.columns:
                    try:
                        demand_ts = pd.to_datetime(valid['interval_start'].iloc[-1])
                    except Exception:
                        demand_ts = None
                demand_source = "live"

        # Fallback: estimate demand from latest consumption interval
        if demand_w is None and has_imp:
            latest_kwh = imp.iloc[-1]['consumption']
            src = getattr(self, '_data_source', 'REST')
            if src == 'GraphQL':
                gid = self.granularity_group.checkedId()
                slots_per_hour = {1: 2, 2: 4, 3: 12}.get(gid, 2)
            else:
                slots_per_hour = 2  # REST is 30-min intervals
            demand_w = latest_kwh * slots_per_hour * 1000
            demand_source = "avg"
            if 'interval_start' in imp.columns:
                try:
                    demand_ts = pd.to_datetime(imp['interval_start'].iloc[-1])
                except Exception:
                    demand_ts = None

        # Compute age of the demand sample. Uses Europe/London (the GraphQL
        # fetcher returns London-localised timestamps). We tolerate a missing
        # tz on either side by stripping tz before subtracting.
        age_s = None
        if demand_ts is not None:
            try:
                import pytz
                now_tz = datetime.now(pytz.timezone('Europe/London'))
                if getattr(demand_ts, 'tzinfo', None) is None:
                    delta = now_tz.replace(tzinfo=None) - demand_ts.to_pydatetime()
                else:
                    delta = now_tz - demand_ts.to_pydatetime()
                age_s = max(0.0, delta.total_seconds())
            except Exception:
                age_s = None

        def _fmt_age(s):
            if s is None:
                return ""
            if s < 60:
                return f"{int(s)} s ago"
            if s < 3600:
                return f"{int(s // 60)} min ago"
            return f"{int(s // 3600)} h ago"

        if demand_w is not None:
            # Colour reflects BOTH polarity (import vs export) and freshness.
            # Stale data — even if positive — is muted so it doesn't pretend
            # to be a real-time reading.
            if age_s is not None and age_s > 600:
                dc = '#6c7086'  # 10 min+ stale: muted
            elif age_s is not None and age_s > 120:
                dc = '#fab387'  # 2-10 min stale: amber
            else:
                dc = '#f38ba8' if demand_w > 0 else '#a6e3a1'  # fresh
            suffix = " ~" if demand_source == "avg" else ""
            self.card_labels['live_demand'].setText(f"{demand_w:.0f}{suffix}")
            self.card_labels['live_demand'].setStyleSheet(f"color: {dc}; font-weight: bold;")
            if self._live_demand_unit_label is not None:
                age_str = _fmt_age(age_s)
                if age_str:
                    self._live_demand_unit_label.setText(f"W · {age_str}")
                    if age_s is not None and age_s > 120:
                        self._live_demand_unit_label.setStyleSheet(
                            f"color: {dc}; font-size: 11px;"
                        )
                    else:
                        self._live_demand_unit_label.setStyleSheet(
                            "color: #6c7086; font-size: 11px;"
                        )
                else:
                    self._live_demand_unit_label.setText("W")
                    self._live_demand_unit_label.setStyleSheet(
                        "color: #6c7086; font-size: 11px;"
                    )
        else:
            self.card_labels['live_demand'].setText("--")
            if self._live_demand_unit_label is not None:
                self._live_demand_unit_label.setText("W")
                self._live_demand_unit_label.setStyleSheet(
                    "color: #6c7086; font-size: 11px;"
                )

        li = imp.iloc[-1]['consumption'] if has_imp else 0
        le = exp.iloc[-1]['consumption'] if has_exp else 0
        src = getattr(self, '_data_source', 'REST')
        gid = self.granularity_group.checkedId() if src == 'GraphQL' else 1
        net_all = self._build_net_kwh_series(imp, exp, src, gid)
        ln = float(net_all['net_kwh'].iloc[-1]) if not net_all.empty else (li - le)
        self.card_labels['latest_import'].setText(f"{li:.3f}")
        self.card_labels['latest_export'].setText(f"{le:.3f}")
        nc = '#F44336' if ln > 0 else '#4CAF50'
        self.card_labels['latest_net'].setText(f"{ln:.3f}")
        self.card_labels['latest_net'].setStyleSheet(f"color: {nc}; font-weight: bold;")
        self.card_labels['total_import'].setText(f"{imp['consumption'].sum():.2f}" if has_imp else "--")
        self.card_labels['total_export'].setText(f"{exp['consumption'].sum():.2f}" if has_exp else "--")

    def _plot_charts(self):
        import pytz, matplotlib.dates as mdates
        london = pytz.timezone('Europe/London')
        self.ax_import.clear()
        self.ax_net.clear()
        _style_ax_dark(self.ax_import, self.fig)
        _style_ax_dark(self.ax_net, self.fig)

        hours = self._view_hours
        now = datetime.now(london)
        view_end = now
        view_start = now - timedelta(hours=hours)

        has_imp = self.import_df is not None and not self.import_df.empty
        has_exp = self.export_df is not None and not self.export_df.empty
        if not has_imp and not has_exp:
            self.ax_import.text(0.5, 0.5, 'No data', transform=self.ax_import.transAxes,
                                ha='center', va='center', fontsize=12, color='#6c7086')
            self.ax_net.text(0.5, 0.5, 'No data', transform=self.ax_net.transAxes,
                             ha='center', va='center', fontsize=12, color='#6c7086')
            self._apply_figure_layout(self.fig)
            self.canvas.draw()
            return

        latest_ts = None
        for df in (self.import_df, self.export_df):
            if df is not None and not df.empty and 'interval_start' in df.columns:
                lt = df['interval_start'].max()
                if latest_ts is None or lt > latest_ts:
                    latest_ts = lt
        stale_window = False
        if latest_ts is not None and latest_ts < view_start:
            stale_window = True
            view_end = latest_ts + timedelta(minutes=15)
            view_start = latest_ts - timedelta(hours=hours)

        imp_view = self.import_df[self.import_df['interval_start'] >= view_start] if has_imp else pd.DataFrame()
        exp_view = self.export_df[self.export_df['interval_start'] >= view_start] if has_exp else pd.DataFrame()

        has_demand = (has_imp and 'demand_w' in self.import_df.columns
                      and self.import_df['demand_w'].notna().any())
        src = getattr(self, '_data_source', 'REST')

        tick_interval = max(1, hours // 12)
        fmt = '%d/%m %H:%M' if hours > 24 else '%H:%M'

        if has_demand and src == 'GraphQL':
            # Top chart: real-time demand in watts (line chart)
            dv = imp_view.dropna(subset=['demand_w'])
            if not dv.empty:
                pos = dv['demand_w'].clip(lower=0)
                neg = dv['demand_w'].clip(upper=0)
                self.ax_import.fill_between(dv['interval_start'], pos, alpha=0.3, color='#f38ba8', step='mid')
                self.ax_import.fill_between(dv['interval_start'], neg, alpha=0.3, color='#a6e3a1', step='mid')
                self.ax_import.step(dv['interval_start'], dv['demand_w'], color='#cdd6f4',
                                    linewidth=1, where='mid', label='Demand')
                self.ax_import.axhline(0, color=_DARK_GRID, linewidth=0.6)
            self.ax_import.set_ylabel('Watts')
            title = (
                f'Live Demand — Previous {hours}h — +ve = import, -ve = export'
            )
            if stale_window:
                title += ' [latest available]'
            self.ax_import.set_title(title)
        else:
            # Bar chart of kWh consumption — adjust bar width to data granularity
            gid = self.granularity_group.checkedId() if src == 'GraphQL' else 1
            bw = {1: 1.0/48, 2: 1.0/96, 3: 1.0/288}.get(gid, 1.0/48)
            if not imp_view.empty:
                self.ax_import.bar(imp_view['interval_start'], imp_view['consumption'],
                                   width=bw, color='#F44336', alpha=0.7, align='edge', label='Import')
            if not exp_view.empty:
                self.ax_import.bar(exp_view['interval_start'], exp_view['consumption'],
                                   width=bw, color='#4CAF50', alpha=0.7, align='edge', label='Export')
            self.ax_import.set_ylabel('kWh per interval')
            title = f'Live Import / Export — Previous {hours}h'
            if stale_window:
                title += ' [latest available]'
            self.ax_import.set_title(title)

        if not stale_window:
            self.ax_import.axvline(now, color=_UI_BLUE, linestyle='--', linewidth=1, label='Now')
        if stale_window and latest_ts is not None:
            self.ax_import.axvline(latest_ts, color='#f9e2af', linestyle=':', linewidth=1, label='Latest data')
        self.ax_import.set_xlim(view_start, view_end)
        self.ax_import.legend(loc='upper left', fontsize=8, framealpha=0.6,
                              facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT)
        self.ax_import.xaxis.set_major_formatter(mdates.DateFormatter(fmt, tz=london))
        self.ax_import.xaxis.set_major_locator(mdates.HourLocator(interval=tick_interval))
        self.ax_import.tick_params(axis='x', rotation=30, labelbottom=False)
        self.ax_import.grid(axis='y', color=_DARK_GRID, linewidth=0.4)

        # Bottom chart: cumulative kWh (running integral of top-chart interval energy)
        import numpy as np
        gid = self.granularity_group.checkedId() if src == 'GraphQL' else 1
        cum_from_demand = has_demand and src == 'GraphQL'
        if cum_from_demand:
            cum_df = self._build_cumulative_kwh_series_from_demand(imp_view, src, gid)
            if cum_df.empty or max(
                float(cum_df['cum_import_kwh'].max()) if len(cum_df) else 0.0,
                float(cum_df['cum_export_kwh'].max()) if len(cum_df) else 0.0,
            ) < 1e-12:
                cum_df = self._build_cumulative_kwh_series(imp_view, exp_view, src, gid)
                cum_from_demand = False
        else:
            cum_df = self._build_cumulative_kwh_series(imp_view, exp_view, src, gid)
        has_cumulative = False
        if not cum_df.empty:
            ts = pd.to_datetime(cum_df['interval_start'])
            if ts.dt.tz is None:
                ts = ts.dt.tz_localize(london)
            else:
                ts = ts.dt.tz_convert(london)
            ci = cum_df['cum_import_kwh'].to_numpy(dtype=float)
            ce = cum_df['cum_export_kwh'].to_numpy(dtype=float)
            cn = cum_df['cum_net_kwh'].to_numpy(dtype=float)
            peak = max(
                float(ci.max()) if len(ci) else 0.0,
                float(ce.max()) if len(ce) else 0.0,
                float(np.abs(cn).max()) if len(cn) else 0.0,
            )
            if peak > 1e-9:
                has_cumulative = True
                self.ax_net.step(
                    ts, ci, where='post', color='#F44336', linewidth=1.6,
                    label='Cumulative import',
                )
                self.ax_net.step(
                    ts, ce, where='post', color='#4CAF50', linewidth=1.6,
                    label='Cumulative export',
                )
                self.ax_net.step(
                    ts, cn, where='post', color='#89b4fa', linewidth=1.2,
                    linestyle='--', label='Cumulative net (import − export)',
                )
                self.ax_net.axhline(0, color=_DARK_GRID, linewidth=0.6)
                ymin = float(min(0.0, cn.min(), ce.min()))
                ymax = float(max(ci.max(), ce.max(), cn.max()))
                pad = max((ymax - ymin) * 0.08, 0.01)
                self.ax_net.set_ylim(ymin - pad, ymax + pad)
                self.ax_net.legend(
                    loc='upper left', fontsize=8, framealpha=0.6,
                    facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT,
                )
            else:
                self.ax_net.text(
                    0.5, 0.5,
                    'No energy recorded in this window',
                    transform=self.ax_net.transAxes,
                    ha='center', va='center', fontsize=11, color=_DARK_SUBTEXT,
                )
        else:
            self.ax_net.text(
                0.5, 0.5, 'No cumulative consumption data',
                transform=self.ax_net.transAxes,
                ha='center', va='center', fontsize=12, color=_DARK_SUBTEXT,
            )
        if not stale_window:
            self.ax_net.axvline(now, color=_UI_BLUE, linestyle='--', linewidth=1)
        if stale_window and latest_ts is not None:
            self.ax_net.axvline(latest_ts, color='#f9e2af', linestyle=':', linewidth=1)
        self.ax_net.set_xlim(view_start, view_end)
        self.ax_net.set_ylabel('Cumulative kWh')
        cum_title = f'Cumulative import / export — running totals ({hours}h view)'
        if cum_from_demand and not cum_df.empty:
            cum_title += ' (from live demand)'
        if stale_window:
            cum_title += ' [latest available]'
        self.ax_net.set_title(cum_title)
        self.ax_net.xaxis.set_major_formatter(mdates.DateFormatter(fmt, tz=london))
        self.ax_net.xaxis.set_major_locator(mdates.HourLocator(interval=tick_interval))
        self.ax_net.tick_params(axis='x', rotation=30)
        self.ax_net.grid(axis='y', color=_DARK_GRID, linewidth=0.4)
        _draw_6h_vertical_grid(self.ax_import, london)
        _draw_6h_vertical_grid(self.ax_net, london)
        _draw_day_date_labels(self.ax_import, london)
        _draw_day_date_labels(self.ax_net, london)
        self._tight_y_from_artists(self.ax_import)
        if not has_cumulative:
            self._tight_y_from_artists(self.ax_net)
        if has_imp or has_exp:
            _octopus_live_draw_per_day_totals(
                self.ax_import, london, imp_view, exp_view, view_start, view_end)
        try:
            _demand_ok = (
                has_imp and 'demand_w' in self.import_df.columns
                and self.import_df['demand_w'].notna().any()
            )
        except Exception:
            _demand_ok = False
        _src = getattr(self, '_data_source', 'REST')
        if _demand_ok and _src == 'GraphQL':
            self.ax_import.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
                xv, yv, tz, "W",
                "instantaneous power at the meter (+ = net import, − = net export)",
            )
        else:
            self.ax_import.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
                xv, yv, tz, "kWh",
                "energy in one metering interval — bar = import (red) or export (green)",
            )
        self.ax_net.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
            xv, yv, tz, "cumulative kWh",
            "running total of import, export, or net since the start of this chart window",
        )
        self._apply_figure_layout(self.fig)
        self.canvas.draw()

    def _update_summary(self):
        has_imp = self.import_df is not None and not self.import_df.empty
        has_exp = self.export_df is not None and not self.export_df.empty
        if not has_imp and not has_exp:
            parts = []
            if getattr(self, "_live_err_imp", None):
                parts.append(f"Import meter: {self._live_err_imp}")
            if getattr(self, "_live_err_exp", None):
                parts.append(f"Export meter: {self._live_err_exp}")
            if not parts:
                parts.append(
                    "No half-hourly rows in this window. Smart-meter readings often reach Octopus hours "
                    "after real time; try the 48h range, or check API key / MPAN / serial match the Octopus Energy Data tab."
                )
            else:
                parts.append("Resolve the errors above or copy the same credentials as on Octopus Energy Data.")
            self.summary_text.setPlainText("\n".join(parts))
            return
        src = getattr(self, '_data_source', 'REST')
        gid = self.granularity_group.checkedId() if src == 'GraphQL' else 1
        interval_label = {1: '30m', 2: '15m', 3: '5m'}.get(gid, '30m')
        interval_hours = {1: 0.5, 2: 0.25, 3: 1/12}.get(gid, 0.5)
        lines = [f"Data source: {src} ({interval_label} intervals)"]
        if has_imp:
            imp = self.import_df
            total = imp['consumption'].sum()
            avg = imp['consumption'].mean()
            avg_kw = avg / interval_hours if interval_hours > 0 else 0
            peak_idx = imp['consumption'].idxmax()
            lines.append(f"IMPORT: {total:.2f} kWh total | avg {avg:.3f} kWh/{interval_label} ({avg_kw:.2f} kW) | "
                         f"peak {imp.loc[peak_idx, 'consumption']:.3f} kWh at {imp.loc[peak_idx, 'interval_start'].strftime('%H:%M')}")
        if has_exp:
            exp = self.export_df
            total = exp['consumption'].sum()
            avg = exp['consumption'].mean()
            peak_idx = exp['consumption'].idxmax()
            lines.append(f"EXPORT: {total:.2f} kWh total | avg {avg:.3f} kWh/{interval_label} | "
                         f"peak {exp.loc[peak_idx, 'consumption']:.3f} kWh at {exp.loc[peak_idx, 'interval_start'].strftime('%H:%M')}")
        if has_imp and has_exp:
            net = self.import_df['consumption'].sum() - self.export_df['consumption'].sum()
            lines.append(f"NET: {abs(net):.2f} kWh ({'net importer' if net > 0 else 'net exporter'})")
        self.summary_text.setPlainText('\n'.join(lines))


__all__ = [n for n in globals() if not n.startswith('__')]
