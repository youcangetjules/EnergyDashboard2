"""
Energy Dashboard — `tabs/octopus_live.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
import json

from energy_dashboard.tabs.octopus_live_cost import (
    COST_REFRESH_S,
    compose_cost_view,
    energy_slots_from_frames,
    rest_half_hour_slots,
    scales_from_history,
    summarise_days,
    summary_lines,
    update_history,
    price_slots,
)
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
    def _london_calendar_day(timestamps):
        """Timezone-aware London calendar day (midnight) for each timestamp."""
        import pytz
        london = pytz.timezone('Europe/London')
        ts = pd.to_datetime(timestamps)
        if getattr(ts, 'dt', None) is None:
            ts = pd.Series(ts)
        if ts.dt.tz is None:
            # Naive stamps from Octopus are treated as London local wall time.
            ts = ts.dt.tz_localize(london, ambiguous='infer', nonexistent='shift_forward')
        else:
            ts = ts.dt.tz_convert(london)
        return ts.dt.normalize()

    @staticmethod
    def _cumsum_reset_each_london_day(values, timestamps):
        """Running total that resets at each Europe/London calendar midnight."""
        s = pd.to_numeric(pd.Series(values), errors='coerce').fillna(0.0)
        day = OctopusLiveTab._london_calendar_day(timestamps)
        # groupby preserves row order within each day when the input is sorted.
        return s.groupby(day.values, sort=False).cumsum()

    @staticmethod
    def _build_cumulative_kwh_series(imp_view, exp_view, src='REST', granularity_id=1):
        """Per-day running import/export kWh (resets at London midnight)."""
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
        merged['cum_import_kwh'] = OctopusLiveTab._cumsum_reset_each_london_day(
            imp_kwh, merged['interval_start'],
        )
        merged['cum_export_kwh'] = OctopusLiveTab._cumsum_reset_each_london_day(
            exp_kwh, merged['interval_start'],
        )
        merged['cum_net_kwh'] = merged['cum_import_kwh'] - merged['cum_export_kwh']
        return merged[cols]

    @staticmethod
    def _build_cumulative_kwh_series_from_demand(imp_view, src='GraphQL', granularity_id=3):
        """Per-day running import/export/net from signed demand (London midnight reset)."""
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
        grouped['cum_import_kwh'] = OctopusLiveTab._cumsum_reset_each_london_day(
            grouped['import_kwh'], grouped['interval_start'],
        )
        grouped['cum_export_kwh'] = OctopusLiveTab._cumsum_reset_each_london_day(
            grouped['export_kwh'], grouped['interval_start'],
        )
        grouped['cum_net_kwh'] = grouped['cum_import_kwh'] - grouped['cum_export_kwh']
        return grouped[cols]

    @staticmethod
    def _pv_query_fail_text(exc) -> str:
        from energy_dashboard.db.connect_probe import is_table_privilege_error
        raw = str(exc or "").splitlines()[0].strip()
        if is_table_privilege_error(raw):
            return "Growatt PV: database login cannot read growatt_readings"
        short = raw[:80] if raw else exc.__class__.__name__
        return f"Growatt PV unavailable ({short})"

    def _pv_kwh_by_slot(self, view_start, view_end, slot_minutes, london):
        """Mean Growatt PV (kW) per slot → kWh for that slot. Empty if no DB/PV."""
        cols = ['interval_start', 'pv_kwh']
        self._cum_pv_note = ""
        logger = self.data_logger
        if logger is None or logger._primary_storage_backend() is None:
            self._cum_pv_note = "No logging database — PV overlay needs growatt_readings"
            return pd.DataFrame(columns=cols)
        try:
            start_utc = pd.Timestamp(view_start)
            end_utc = pd.Timestamp(view_end)
            if start_utc.tzinfo is None:
                start_utc = start_utc.tz_localize(london)
            if end_utc.tzinfo is None:
                end_utc = end_utc.tz_localize(london)
            start_utc = start_utc.tz_convert(timezone.utc)
            end_utc = end_utc.tz_convert(timezone.utc)
            pl_df = logger.query_growatt_pv_actual(start_utc, end_utc)
        except Exception as exc:
            self._cum_pv_note = self._pv_query_fail_text(exc)
            return pd.DataFrame(columns=cols)
        if pl_df is None or pl_df.is_empty():
            self._cum_pv_note = "No Growatt PV in this window"
            return pd.DataFrame(columns=cols)
        try:
            pdf = pl_df.to_pandas()
        except Exception:
            return pd.DataFrame(columns=cols)
        if pdf.empty or 'pv_kw' not in pdf.columns:
            return pd.DataFrame(columns=cols)
        ts = pd.to_datetime(pdf['timestamp'], utc=True, errors='coerce')
        ts = ts.dt.tz_convert(london)
        pv = pd.to_numeric(pdf['pv_kw'], errors='coerce')
        out = pd.DataFrame({'interval_start': ts, 'pv_kw': pv}).dropna()
        if out.empty:
            return pd.DataFrame(columns=cols)
        slot = out['interval_start'].dt.floor(f'{int(slot_minutes)}min')
        hrs = float(slot_minutes) / 60.0
        grouped = (
            out.assign(interval_start=slot)
            .groupby('interval_start', as_index=False)['pv_kw']
            .mean()
            .sort_values('interval_start')
            .reset_index(drop=True)
        )
        grouped['pv_kwh'] = grouped['pv_kw'].clip(lower=0.0) * hrs
        return grouped[['interval_start', 'pv_kwh']]

    def _attach_cumulative_pv(self, cum_df, view_start, view_end, slot_minutes, london):
        """Add ``cum_pv_kwh`` and ``cum_consumption_kwh`` on the import timeline.

        Consumption is the meter balance ``import + PV − export`` (labelled
        analysis, not a separate BMS/inverter register).
        """
        if cum_df is None or cum_df.empty:
            return cum_df
        out = cum_df.copy()
        out['interval_start'] = pd.to_datetime(out['interval_start'])
        if out['interval_start'].dt.tz is None:
            out['interval_start'] = out['interval_start'].dt.tz_localize(london)
        else:
            out['interval_start'] = out['interval_start'].dt.tz_convert(london)
        pv = self._pv_kwh_by_slot(view_start, view_end, slot_minutes, london)
        if pv.empty:
            out['cum_pv_kwh'] = 0.0
            cum_exp = (
                out['cum_export_kwh']
                if 'cum_export_kwh' in out.columns
                else 0.0
            )
            out['cum_consumption_kwh'] = (
                out['cum_import_kwh'].fillna(0.0)
                - pd.to_numeric(cum_exp, errors='coerce').fillna(0.0)
            )
            return out
        pv = pv.copy()
        pv['interval_start'] = pd.to_datetime(pv['interval_start'])
        if pv['interval_start'].dt.tz is None:
            pv['interval_start'] = pv['interval_start'].dt.tz_localize(london)
        else:
            pv['interval_start'] = pv['interval_start'].dt.tz_convert(london)
        # Match slot floors used on the import side.
        out['_slot'] = out['interval_start'].dt.floor(f'{int(slot_minutes)}min')
        pv['_slot'] = pv['interval_start'].dt.floor(f'{int(slot_minutes)}min')
        pv_map = pv.groupby('_slot', as_index=True)['pv_kwh'].sum()
        out['pv_kwh'] = out['_slot'].map(pv_map).fillna(0.0)
        out['cum_pv_kwh'] = OctopusLiveTab._cumsum_reset_each_london_day(
            out['pv_kwh'], out['interval_start'],
        )
        # House load from meter balance: import + generation − export.
        # Uses the same Octopus + Growatt series already on this chart (not rescaled).
        cum_exp = (
            out['cum_export_kwh']
            if 'cum_export_kwh' in out.columns
            else 0.0
        )
        out['cum_consumption_kwh'] = (
            out['cum_import_kwh'].fillna(0.0)
            + out['cum_pv_kwh'].fillna(0.0)
            - pd.to_numeric(cum_exp, errors='coerce').fillna(0.0)
        )
        return out.drop(columns=['_slot', 'pv_kwh'], errors='ignore')

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

    def __init__(self, status_callback, data_logger=None, app_params=None):
        super().__init__()
        self.set_status = status_callback
        self.data_logger = data_logger  # Growatt PV for the cumulative chart
        self.app_params = app_params
        self._inv = Invoker(self)
        self.import_df = None
        self.export_df = None
        self._view_hours = 2
        self.fetching = False
        self.on_data_updated = None
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(30000)
        self._auto_timer.timeout.connect(self.fetch_data)
        # smartMeterTelemetry aggregates to 5 min at its finest, so this tab
        # polls every 60 s regardless of the shared cycle — at the global 600 s
        # the displayed Live Demand could be 10+ minutes behind.
        self._auto_timer_interval_override_ms = 60000
        self._auto_refresh_pending = False
        self._ctrl_held = False
        self._ctrl_timer = QTimer(self)
        self._ctrl_timer.setInterval(80)
        self._ctrl_timer.timeout.connect(self._poll_ctrl)
        # Holds the unit label widget for the live_demand card so we can
        # append "· N min ago" to it; populated in build_ui.
        self._live_demand_unit_label = None
        # Last completed Octopus API attempt (not the age of the meter slot).
        self._link_state = "unknown"
        self._link_detail = ""
        self._link_at = None
        self._status_body = ""
        # Spot-price bundle and the remembered settled-day ratios (cost view).
        self._cost_bundle = None
        self._cost_history = {}
        self._card_boxes = {}
        self._card_units = {}
        self.build_ui()
        self._load_saved_octopus_live()
        self._link_timer = QTimer(self)
        self._link_timer.setInterval(30000)
        self._link_timer.timeout.connect(self._paint_connectivity)
        self._link_timer.start()
        QTimer.singleShot(800, self._paint_connectivity)
        if self.isVisible():
            self._set_ctrl_show_filter(True)

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Vertical)

        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        ctrl_box = QGroupBox("Octopus Live Monitor")
        ctrl_box.setObjectName("octopusLiveMonitor")
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
        row0.addSpacing(20)
        hours_view_rule = QFrame()
        hours_view_rule.setFrameShape(QFrame.Shape.VLine)
        hours_view_rule.setFrameShadow(QFrame.Shadow.Plain)
        hours_view_rule.setFixedSize(1, 22)
        hours_view_rule.setStyleSheet(
            "QFrame { color: #585b70; background-color: #585b70; border: none; }"
        )
        row0.addWidget(hours_view_rule)
        row0.addSpacing(20)
        row0.addWidget(QLabel("View:"))
        self.display_group = QButtonGroup(self)
        self.rb_view_power = QRadioButton("Power")
        self.rb_view_cost = QRadioButton("Cost")
        self.display_group.addButton(self.rb_view_power, 0)
        self.display_group.addButton(self.rb_view_cost, 1)
        self.rb_view_power.setChecked(True)
        self.rb_view_power.setToolTip("Watts and kWh from the live meter.")
        self.rb_view_cost.setToolTip(
            "Money for grid import on the charts: import £/h on top, "
            "cumulative import £ on the bottom right axis. "
            "Generated / Total Used / Exported stay as energy with no cost. "
            "Cards still show import cost and export credit. "
            "Standing charge is not included."
        )
        row0.addWidget(self.rb_view_power)
        row0.addWidget(self.rb_view_cost)
        self.display_group.idToggled.connect(self._on_display_mode)
        row0.addSpacing(16)
        self.save_btn = QPushButton("Save")
        self.save_btn.setFixedWidth(110)
        _apply_primary_button_style(self.save_btn)
        self.save_btn.setToolTip(
            "Save API key, account number, import/export MPANs, granularity, hours, and power/cost view"
        )
        self.save_btn.clicked.connect(self._save_octopus_live_clicked)
        row0.addWidget(self.save_btn)
        self.test_btn = QPushButton("Test")
        self.test_btn.setFixedWidth(110)
        _apply_primary_button_style(self.test_btn)
        self.test_btn.setToolTip(
            "Check the API key and account with Octopus. "
            "This does not reload the charts — use Fetch Live Data for that."
        )
        self.test_btn.clicked.connect(self._test_octopus_live)
        row0.addWidget(self.test_btn)
        self._show_api_key_btn = QPushButton("Show")
        self._show_api_key_btn.setVisible(False)
        self._show_api_key_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self._show_api_key_btn.setToolTip("Reveal API key (visible while Ctrl is held)")
        self._show_api_key_btn.clicked.connect(self._reveal_api_key)
        row0.addWidget(self._show_api_key_btn)
        row0.addStretch()
        ctrl_vlayout.addLayout(row0)

        # Shared label column so Account / Import MPAN / Export MPAN fields
        # share the same left edge (Export MPAN is the visual reference).
        _mpan_lbl_w = max(
            QFontMetrics(self.font()).horizontalAdvance(t)
            for t in ("Account No:", "Import MPAN:", "Export MPAN:")
        ) + 8

        def _mpan_row_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFixedWidth(_mpan_lbl_w)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return lbl

        row1 = QHBoxLayout()
        row1.addWidget(_mpan_row_label("Account No:"))
        self.account_edit = QLineEdit(DEFAULT_OCTOPUS_ACCOUNT)
        self.account_edit.setFixedWidth(150)
        self.account_edit.setPlaceholderText("A-12345678")
        self.account_edit.setToolTip(
            "Octopus account number (e.g. A-12345678). "
            "Required for GraphQL granular telemetry."
        )
        row1.addWidget(self.account_edit)
        row1.addSpacing(15)
        row1.addWidget(QLabel("Granularity:"))
        self.granularity_group = QButtonGroup(self)
        for text, val in [("30 min", 1), ("15 min", 2), ("5 min", 3)]:
            rb = QRadioButton(text)
            self.granularity_group.addButton(rb, val)
            row1.addWidget(rb)
        self.granularity_group.button(3).setChecked(True)
        row1.addSpacing(15)
        # Fetch + status on the account row so Import/Export MPAN stay stacked
        # and left-aligned with each other.
        self.fetch_btn = QPushButton("Fetch Live Data")
        self.fetch_btn.clicked.connect(self.fetch_data)
        row1.addWidget(self.fetch_btn)
        self.status_label = QLabel("Connectivity — not checked yet")
        self.status_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        self.status_label.setWordWrap(True)
        self.status_label.setToolTip(
            "Whether the last call to Octopus succeeded. "
            "This is the API link, not how old the meter reading is."
        )
        row1.addWidget(self.status_label, 1)
        ctrl_vlayout.addLayout(row1)

        row_imp = QHBoxLayout()
        row_imp.addWidget(_mpan_row_label("Import MPAN:"))
        self.import_mpan_edit = QLineEdit(DEFAULT_IMPORT_MPAN)
        self.import_mpan_edit.setFixedWidth(150)
        row_imp.addWidget(self.import_mpan_edit)
        row_imp.addWidget(QLabel("Serial:"))
        self.import_serial_edit = QLineEdit(DEFAULT_IMPORT_SERIAL)
        self.import_serial_edit.setFixedWidth(120)
        row_imp.addWidget(self.import_serial_edit)
        row_imp.addStretch(1)
        ctrl_vlayout.addLayout(row_imp)

        row1b = QHBoxLayout()
        row1b.addWidget(_mpan_row_label("Export MPAN:"))
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
            card, val_label, unit_label = make_small_card(
                label, unit, color, return_unit_label=True,
            )
            self._card_boxes[key] = card
            self._card_units[key] = unit_label
            if key == 'live_demand':
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
        # A filter on QApplication re-enters PySide while a property is set
        # and SIGSEGVs (BUG-060). Watch Ctrl from a timer on this page only.
        if active:
            if not self._ctrl_timer.isActive():
                self._ctrl_timer.start()
        else:
            self._ctrl_timer.stop()
            self._ctrl_held = False
            self._set_show_api_key_btn(False)

    def _poll_ctrl(self):
        held = bool(
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier
        )
        if held == self._ctrl_held:
            return
        self._ctrl_held = held
        if held:
            self._show_api_key_btn.setVisible(True)
        else:
            self._set_show_api_key_btn(False)

    def _set_show_api_key_btn(self, visible: bool):
        self._show_api_key_btn.setVisible(visible)
        if not visible:
            self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)

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
        if str(s.value("octopus_live/display_mode") or "") == "cost":
            self.display_group.blockSignals(True)
            self.rb_view_cost.setChecked(True)
            self.display_group.blockSignals(False)
        self._cost_history = self._read_cost_history(s.value("octopus_live/cost_history"))
        self._apply_card_chrome()

    @staticmethod
    def _read_cost_history(raw) -> dict:
        if raw is None:
            return {}
        if isinstance(raw, bytes):
            raw = raw.decode(errors="replace")
        try:
            data = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

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
        s.setValue(
            "octopus_live/display_mode",
            "cost" if self._is_cost_mode() else "power",
        )
        s.setValue("octopus_live/cost_history", json.dumps(self._cost_history or {}))
        s.sync()

    def _save_octopus_live_clicked(self):
        self._save_octopus_live()
        self.set_status("Octopus Live settings saved")
        self.gql_status.setText(
            "Saved — API key, account number, and meter details stored for next launch."
        )

    def _test_octopus_live(self):
        """Ask Octopus whether the API key and account are accepted.

        This is a login check only. It does not replace the live charts.
        """
        if getattr(self, "_testing", False):
            return
        if self.fetching:
            self.set_status("Octopus Live test: a fetch is already talking to Octopus.")
            return
        api_key = self.api_key_edit.text().strip()
        account = self.account_edit.text().strip()
        if not api_key:
            self._set_link("failed", "No API key to test.")
            self.gql_status.setText("Test failed — enter an API key first.")
            self.set_status("Octopus Live test: enter an API key first.")
            return
        self._testing = True
        self.test_btn.setEnabled(False)
        self._set_link("checking", "Testing the API key and account…")
        self.gql_status.setText("Testing Octopus…")
        self.set_status("Octopus Live: testing connection…")
        threading.Thread(
            target=self._test_octopus_thread,
            args=(api_key, account),
            daemon=True,
        ).start()

    def _test_octopus_thread(self, api_key: str, account: str):
        state = "failed"
        msg = "Octopus did not answer."
        try:
            token = octopus_gql_authenticate(api_key)
            if account:
                devices = octopus_gql_discover_devices(token, account)
                n = len(devices or [])
                if n:
                    state = "ok"
                    msg = (
                        f"API key accepted. Account {account} has "
                        f"{n} smart meter{'s' if n != 1 else ''}."
                    )
                else:
                    msg = (
                        f"API key accepted, but account {account} "
                        "returned no smart meters."
                    )
            else:
                state = "degraded"
                msg = "API key accepted. Add an account number to check the meters."
        except Exception as exc:
            msg = str(exc).strip() or type(exc).__name__
            state = "failed"

        def _finish():
            self._testing = False
            btn = getattr(self, "test_btn", None)
            if btn is not None:
                btn.setEnabled(True)
            self._set_link(state, msg)
            prefix = "Test OK — " if state == "ok" else (
                "Test — " if state == "degraded" else "Test failed — "
            )
            self.gql_status.setText(prefix + msg)
            self.set_status("Octopus Live test: " + msg)

        self._inv.invoke(_finish)

    def auto_start(self):
        self.fetch_data()

    def _on_hours_changed(self, hours_id):
        self._view_hours = hours_id if hours_id > 0 else 2
        self._save_octopus_live()
        if self.import_df is not None or self.export_df is not None:
            self._update_cards()
            self._plot_charts()
            self._update_summary()

    def _granularity_label(self):
        gid = self.granularity_group.checkedId()
        return {1: "HALF_HOURLY", 2: "QUARTER_HOURLY", 3: "FIVE_MINUTES"}.get(gid, "HALF_HOURLY")

    def live_refresh_expectation(self):
        """(active, expected_seconds, detail) for the banner refresh pill."""
        sec = max(5, int(self._auto_timer.interval() // 1000))
        if not self._auto_timer.isActive():
            return False, float(sec), "auto-refresh off"
        return True, float(sec), f"Octopus GraphQL poll every {sec}s"

    def _link_stale_after_s(self) -> float:
        """How long a successful Octopus answer may sit before the link is stale.

        The live tab polls about once a minute. A few missed polls means we
        have lost the API, even if the last meter slot was already a few
        minutes old when it arrived.
        """
        sec = 60.0
        timer = getattr(self, "_auto_timer", None)
        if timer is not None:
            try:
                sec = max(15.0, float(timer.interval()) / 1000.0)
            except Exception:
                sec = 60.0
        return max(180.0, sec * 3.0)

    def connectivity_view(self) -> dict:
        """Current Octopus API link, for this page and the footer strip."""
        state = getattr(self, "_link_state", "unknown") or "unknown"
        detail = getattr(self, "_link_detail", "") or ""
        at = getattr(self, "_link_at", None)
        age_s = None if at is None else (datetime.now() - at).total_seconds()
        polling = False
        timer = getattr(self, "_auto_timer", None)
        if timer is not None:
            try:
                polling = bool(timer.isActive())
            except Exception:
                polling = False
        if (
            state in ("ok", "degraded")
            and polling
            and age_s is not None
            and age_s > self._link_stale_after_s()
        ):
            state = "stale"
        words = {
            "ok": ("OK", "Connectivity — OK", "#a6e3a1", "ok"),
            "degraded": ("REST only", "Connectivity — REST only", "#fab387", "warn"),
            "stale": ("stale", "Connectivity — stale", "#fab387", "warn"),
            "failed": ("failed", "Connectivity — failed", "#f38ba8", "bad"),
            "checking": ("checking…", "Connectivity — checking…", "#b8dcff", "busy"),
            "unknown": ("—", "Connectivity — not checked yet", "#6c7086", "idle"),
        }
        short, prefix, color, health = words.get(state, words["unknown"])
        tips = [
            "Whether the last call to Octopus succeeded. "
            "This is the API link, not how old the meter reading is.",
        ]
        if detail:
            tips.append(detail)
        if at is not None:
            tips.append("Last result at " + at.strftime("%H:%M:%S"))
        if state == "ok":
            tips.append("GraphQL telemetry answered (the live smart-meter stream).")
        elif state == "degraded":
            tips.append(
                "GraphQL did not return live readings. Half-hour REST meter "
                "data is in use instead — that feed is often about a day behind."
            )
        elif state == "stale":
            tips.append(
                "Auto-refresh is on, but Octopus has not answered within the last few minutes."
            )
        elif state == "failed":
            tips.append("The last Octopus request failed. The next auto-refresh will try again.")
        elif state == "unknown":
            tips.append("Octopus Live has not completed a fetch yet.")
        for extra in (
            getattr(self, "_live_err_imp", None),
            getattr(self, "_live_err_exp", None),
        ):
            if extra:
                tips.append(str(extra))
        return {
            "state": state,
            "short": short,
            "prefix": prefix,
            "color": color,
            "health": health,
            "tooltip": "\n".join(tips),
        }

    def _set_link(self, state: str, detail: str = "") -> None:
        self._link_state = state
        self._link_detail = detail or ""
        if state != "checking":
            self._link_at = datetime.now()
        elif self._link_at is None:
            self._link_at = datetime.now()
        self._paint_connectivity()

    def _paint_connectivity(self) -> None:
        view = self.connectivity_view()
        body = getattr(self, "_status_body", "") or ""
        text = f"{view['prefix']} · {body}" if body else view["prefix"]
        label = getattr(self, "status_label", None)
        if label is not None:
            label.setText(text)
            label.setStyleSheet(f"color: {view['color']}; font-size: 11px;")
            label.setToolTip(view["tooltip"])
        dash = self.window()
        bar = getattr(dash, "system_status", None) if dash is not None else None
        if bar is not None and hasattr(bar, "set_octopus_link"):
            bar.set_octopus_link(view)

    def fetch_data(self):
        if self.fetching:
            self._auto_refresh_pending = True
            return
        if getattr(self, "_link_state", "unknown") == "unknown":
            self._set_link("checking", "Asking Octopus for live meter readings…")
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
        gid = self.granularity_group.checkedId()
        if gid <= 0:
            gid = 3
        want_cost = self._is_cost_mode() and self._cost_bundle_stale()
        tariffs = self._tariff_context()
        history = json.loads(json.dumps(self._cost_history or {}))
        threading.Thread(target=self._fetch_thread,
                         args=(api_key, account, imp_mpan, imp_serial,
                               exp_mpan, exp_serial, hours, granularity,
                               gid, want_cost, tariffs, history),
                         daemon=True).start()

    def _fetch_thread(self, api_key, account, imp_mpan, imp_serial,
                      exp_mpan, exp_serial, hours, granularity,
                      gid, want_cost, tariffs, history):
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
            if want_cost:
                try:
                    self._cost_bundle = self._build_cost_bundle(
                        api_key, account, imp_mpan, imp_serial,
                        exp_mpan, exp_serial, hours, granularity, gid,
                        self._data_source, import_df, export_df,
                        tariffs, history,
                    )
                except Exception as e:
                    _log.warn("Octopus Live", f"Cost prices failed: {e}")
                    self._cost_bundle = {
                        "error": str(e),
                        "fetched_at": datetime.now(timezone.utc),
                        "history": history,
                    }
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
        self._status_body = short
        self._set_link("failed", short or "Live refresh failed")
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

        bits = [src, f"{n_imp} import + {n_exp} export"]
        if freshness:
            bits.append(freshness)
        bits.append(ts)
        self._status_body = " | ".join(bits)
        gql_msg = getattr(self, "_gql_msg", "") or ""
        if src == "GraphQL" and (n_imp or n_exp):
            link_state, link_detail = "ok", gql_msg or "GraphQL telemetry answered"
        elif n_imp or n_exp:
            link_state, link_detail = "degraded", gql_msg or "REST meter data only"
        else:
            link_state = "failed"
            link_detail = gql_msg or "Octopus returned no live readings"
        self._set_link(link_state, link_detail)
        if gql_msg:
            if link_state == "ok":
                color = "#a6e3a1"
            elif link_state == "degraded":
                color = "#fab387"
            else:
                color = "#f38ba8"
            self.gql_status.setStyleSheet(f"color: {color}; font-size: 11px;")
            self.gql_status.setText(gql_msg)
        elif not self.account_edit.text().strip():
            self.gql_status.setStyleSheet("color: #6c7086; font-size: 11px;")
            self.gql_status.setText("Enter Account No (e.g. A-12345678) for granular GraphQL data")
        bundle = getattr(self, "_cost_bundle", None)
        if bundle and isinstance(bundle.get("history"), dict):
            self._cost_history = bundle["history"]
            fetched = bundle.get("fetched_at")
            fresh = False
            if fetched is not None:
                try:
                    fresh = (datetime.now(timezone.utc) - fetched).total_seconds() < 15
                except TypeError:
                    fresh = False
            if fresh:
                self._octopus_live_settings().setValue(
                    "octopus_live/cost_history",
                    json.dumps(self._cost_history or {}),
                )
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

    def _is_cost_mode(self) -> bool:
        group = getattr(self, "display_group", None)
        return group is not None and group.checkedId() == 1

    def _on_display_mode(self, _mode_id, checked=True):
        if not checked:
            return
        self._save_octopus_live()
        self._apply_card_chrome()
        if self._is_cost_mode() and self._cost_bundle_stale():
            for lab in self.card_labels.values():
                lab.setText("…")
            self.fetch_data()
            return
        if self.import_df is not None or self.export_df is not None:
            self._update_cards()
            try:
                self._plot_charts()
                self._update_summary()
            except Exception as e:
                _log.exception("Octopus Live", f"Cost view failed: {e}")
                self.set_status(f"Octopus Live cost view error: {e}")

    def _cost_bundle_stale(self) -> bool:
        bundle = getattr(self, "_cost_bundle", None)
        if not bundle or not bundle.get("fetched_at"):
            return True
        try:
            age = (datetime.now(timezone.utc) - bundle["fetched_at"]).total_seconds()
        except TypeError:
            return True
        if bundle.get("error"):
            return age > 120
        if "scales" not in bundle:
            return True
        return age > COST_REFRESH_S

    def _tariff_context(self) -> dict:
        ap = self.app_params
        return {
            "flat_import": float(getattr(ap, "import_flat_pence", 24.5) if ap else 24.5),
            "flat_export": float(getattr(ap, "export_flat_pence", 15.0) if ap else 15.0),
            "product": (getattr(ap, "agile_product", None) if ap else None) or DEFAULT_AGILE_PRODUCT,
            "tariff_import": (getattr(ap, "agile_tariff", None) if ap else None) or DEFAULT_AGILE_TARIFF,
            "tariff_export": (
                (getattr(ap, "agile_export_tariff", None) if ap else None)
                or DEFAULT_AGILE_EXPORT_TARIFF
            ),
        }

    def _load_rate_series(self, product, tariff, direction, start_utc, end_utc):
        """Agile unit rates (p/kWh inc. VAT). Live tariff first, then the database."""
        try:
            ser = fetch_agile_rates_series_utc(product, tariff, start_utc, end_utc)
        except Exception as e:
            _log.warn("Octopus Live", f"Agile {direction} rates: {e}")
            ser = pd.Series(dtype=float)
        if ser is not None and len(ser) > 0:
            return ser, "agile"
        logger = self.data_logger
        if logger is not None and tariff:
            try:
                pl_df = logger.query_agile_prices(start_utc, end_utc, tariff, direction)
            except Exception as e:
                _log.warn("Octopus Live", f"Stored Agile {direction} rates: {e}")
                pl_df = None
            if pl_df is not None and not pl_df.is_empty():
                pdf = pl_df.to_pandas()
                ts = pd.to_datetime(pdf["valid_from"])
                if getattr(ts.dt, "tz", None) is None:
                    ts = ts.dt.tz_localize(
                        "Europe/London", ambiguous="infer", nonexistent="shift_forward",
                    )
                ts = ts.dt.tz_convert("UTC")
                values = pd.to_numeric(pdf["price_pence"], errors="coerce")
                ser = pd.Series(values.to_numpy(), index=pd.DatetimeIndex(ts))
                ser = ser.dropna().sort_index()
                ser = ser[~ser.index.duplicated(keep="last")]
                if len(ser) > 0:
                    return ser, "database"
        return pd.Series(dtype=float), "flat"

    def _build_cost_bundle(
        self, api_key, account, imp_mpan, imp_serial, exp_mpan, exp_serial,
        hours, granularity, gid, src, import_df, export_df, tariffs, history,
    ):
        """Spot prices, Octopus's recent half-hour meter, and the tuning ratios.

        Runs on the fetch thread. The half-hour meter is what Octopus states.
        A separate 48 h live pull (throttled with this bundle) is what we
        compare it with, so today's estimate can be scaled.
        """
        import pytz
        london = pytz.timezone("Europe/London")
        now = datetime.now(london)
        today = pd.Timestamp(now)
        start_utc = (pd.Timestamp(now) - pd.Timedelta(days=9)).tz_convert("UTC")
        end_utc = (pd.Timestamp(now) + pd.Timedelta(days=2)).tz_convert("UTC")
        imp_rates, src_i = self._load_rate_series(
            tariffs["product"], tariffs["tariff_import"], "import", start_utc, end_utc,
        )
        exp_rates, src_e = self._load_rate_series(
            tariffs["product"], tariffs["tariff_export"], "export", start_utc, end_utc,
        )
        if src_i == "agile" or src_e == "agile":
            rates_source = "agile"
        elif src_i == "database" or src_e == "database":
            rates_source = "database"
        else:
            rates_source = "flat"

        day_from = datetime.now() - timedelta(days=9)
        day_to = datetime.now() + timedelta(days=1)
        imp_rest = get_meter_data(api_key, imp_mpan, imp_serial, day_from, day_to)
        exp_rest = get_meter_data(api_key, exp_mpan, exp_serial, day_from, day_to)
        export_known = exp_rest is not None and not exp_rest.empty
        stated = rest_half_hour_slots(imp_rest, exp_rest if export_known else pd.DataFrame())

        cal_imp, cal_exp = pd.DataFrame(), pd.DataFrame()
        if src == "GraphQL" and account:
            if int(hours) >= 48 and import_df is not None and not import_df.empty:
                cal_imp, cal_exp = import_df, export_df
            else:
                try:
                    got_imp, got_exp, err = fetch_octopus_telemetry(
                        api_key, account, hours=48, grouping=granularity,
                    )
                except Exception as e:
                    got_imp, got_exp, err = pd.DataFrame(), pd.DataFrame(), str(e)
                if err:
                    _log.warn("Octopus Live", f"Cost calibration telemetry: {err}")
                    cal_imp, cal_exp = import_df, export_df
                else:
                    cal_imp, cal_exp = got_imp, got_exp

        slot_min = self._slot_minutes("GraphQL" if src == "GraphQL" else "REST", gid)
        if src == "GraphQL":
            live_slots, _energy_src = energy_slots_from_frames(cal_imp, cal_exp, slot_min)
            live_priced = price_slots(
                live_slots, imp_rates, exp_rates,
                tariffs["flat_import"], tariffs["flat_export"],
            )
            live_days = summarise_days(live_priced, today, export_known=True)
        else:
            live_days = []
        stated_priced = price_slots(
            stated, imp_rates, exp_rates,
            tariffs["flat_import"], tariffs["flat_export"],
        )
        stated_days = summarise_days(stated_priced, today, export_known=export_known)
        history = update_history(history, live_days, stated_days, today)
        learned = scales_from_history(history)
        if src == "GraphQL":
            view_scales = learned
        else:
            view_scales = dict(learned)
            view_scales["scale_import"] = 1.0
            view_scales["scale_export"] = 1.0
            view_scales["tuned_import"] = False
            view_scales["tuned_export"] = False
        _log.info(
            "Octopus Live",
            "Cost "
            f"import ×{view_scales['scale_import']:.3f} "
            f"export ×{view_scales['scale_export']:.3f} "
            f"from {len(learned.get('days') or [])} settled day(s), prices={rates_source}",
        )
        return {
            "fetched_at": datetime.now(timezone.utc),
            "import_rates": imp_rates,
            "export_rates": exp_rates,
            "rates_source": rates_source,
            "stated_slots": stated,
            "export_known": export_known,
            "history": history,
            "scales": view_scales,
            "meter_direct": src != "GraphQL",
            "flat_import": tariffs["flat_import"],
            "flat_export": tariffs["flat_export"],
            "error": None,
        }

    def _apply_card_chrome(self):
        cost = self._is_cost_mode()
        spec = {
            "live_demand": ("Import £/h" if cost else "Live Demand", "£/h" if cost else "W"),
            "latest_import": ("Latest import" if cost else "Latest Import", "p" if cost else "kWh"),
            "latest_export": ("Latest export" if cost else "Latest Export", "p" if cost else "kWh"),
            "latest_net": ("Latest net" if cost else "Latest Net", "p" if cost else "kWh"),
            "total_import": ("Import cost" if cost else "Total Import", "£" if cost else "kWh"),
            "total_export": ("Export credit" if cost else "Total Export", "£" if cost else "kWh"),
        }
        power_demand_tip = (
            "Smart-meter household demand reported via the Octopus "
            "GraphQL telemetry stream.\n\n"
            "This is the meter's instantaneous power draw at the END "
            "of the latest aggregation window. The \"· N min ago\" suffix "
            "tells you how stale the current sample is."
        )
        cost_tips = {
            "live_demand": (
                "Import cost per hour for the latest slot. "
                "Export is not on this rate chart. Today is scaled when "
                "settled Octopus days have taught a factor."
            ),
            "latest_import": "Import cost of the latest slot, in pence.",
            "latest_export": "Export credit of the latest slot, in pence.",
            "latest_net": "Import cost minus export credit for the latest slot, in pence.",
            "total_import": (
                "Import cost for this Hours window, in pounds. "
                "Settled time uses Octopus's meter. "
                "The smaller (Today: …) figure is London midnight to now."
            ),
            "total_export": (
                "Export credit for this Hours window, in pounds. "
                "Standing charge is not included. "
                "The smaller (Today: …) figure is London midnight to now."
            ),
        }
        for key, (title, unit) in spec.items():
            box = self._card_boxes.get(key)
            if box is not None:
                box.setTitle(title)
                if cost:
                    box.setToolTip(cost_tips.get(key, ""))
                elif key == "live_demand":
                    box.setToolTip(power_demand_tip)
            unit_lbl = self._card_units.get(key)
            if unit_lbl is not None and key != "live_demand":
                unit_lbl.setText(unit)
            elif unit_lbl is not None and cost:
                unit_lbl.setText(unit)

    def _live_view_bounds(self):
        import pytz
        london = pytz.timezone("Europe/London")
        now = datetime.now(london)
        hours = self._view_hours or 2
        view_end = now
        view_start = now - timedelta(hours=hours)
        latest_ts = None
        for df in (self.import_df, self.export_df):
            if df is not None and not df.empty and "interval_start" in df.columns:
                lt = df["interval_start"].max()
                if latest_ts is None or lt > latest_ts:
                    latest_ts = lt
        stale = False
        if latest_ts is not None and latest_ts < view_start:
            stale = True
            view_end = latest_ts + timedelta(minutes=15)
            view_start = latest_ts - timedelta(hours=hours)
        return {
            "london": london,
            "now": now,
            "hours": hours,
            "view_start": view_start,
            "view_end": view_end,
            "stale": stale,
            "latest_ts": latest_ts,
        }

    def _cost_model_for_view(self):
        bundle = getattr(self, "_cost_bundle", None)
        bounds = self._live_view_bounds()
        if not bundle or bundle.get("error") or "scales" not in bundle:
            return None, bundle, "meter", bounds
        has_imp = self.import_df is not None and not self.import_df.empty
        has_exp = self.export_df is not None and not self.export_df.empty
        start = bounds["view_start"]
        imp_view = (
            self.import_df[self.import_df["interval_start"] >= start]
            if has_imp else pd.DataFrame()
        )
        exp_view = (
            self.export_df[self.export_df["interval_start"] >= start]
            if has_exp else pd.DataFrame()
        )
        src = getattr(self, "_data_source", "REST")
        gid = self.granularity_group.checkedId() if src == "GraphQL" else 1
        slot_min = self._slot_minutes(src, gid)
        live_slots, energy_source = energy_slots_from_frames(imp_view, exp_view, slot_min)
        if bundle.get("meter_direct"):
            energy_source = "meter"
        model = compose_cost_view(
            live_slots,
            bundle.get("stated_slots"),
            bundle.get("import_rates"),
            bundle.get("export_rates"),
            float(bundle.get("flat_import", 24.5)),
            float(bundle.get("flat_export", 15.0)),
            bundle.get("scales") or {},
            bounds["now"],
            bounds["view_start"],
            bounds["view_end"],
            export_known=bool(bundle.get("export_known", True)),
        )
        return model, bundle, energy_source, bounds

    @staticmethod
    def _set_cost_total_with_today(label, *, window_gbp: float, today_gbp, color: str):
        """Window £ as the main figure; smaller (Today: £…) to its right."""
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setStyleSheet("")
        if today_gbp is None:
            label.setText(
                f'<span style="color:{color}; font-size:18px; font-weight:bold;">'
                f"{window_gbp:.2f}</span>"
            )
            return
        label.setText(
            f'<span style="color:{color}; font-size:18px; font-weight:bold;">'
            f"{window_gbp:.2f}</span>"
            f'<span style="color:#6c7086; font-size:11px; font-weight:normal;">'
            f" (Today: £{float(today_gbp):.2f})</span>"
        )

    def _reset_cost_total_label(self, key: str, color: str):
        lab = self.card_labels.get(key)
        if lab is None:
            return
        lab.setTextFormat(Qt.TextFormat.PlainText)
        lab.setStyleSheet(f"color: {color};")
        lab.setText("--")

    def _update_cost_cards(self):
        model, _bundle, _src, _bounds = self._cost_model_for_view()
        slots = None if not model else model.get("slots")
        if slots is None or slots.empty:
            for lab in self.card_labels.values():
                lab.setTextFormat(Qt.TextFormat.PlainText)
                lab.setText("--")
            self._reset_cost_total_label("total_import", "#9C27B0")
            self._reset_cost_total_label("total_export", "#009688")
            if self._live_demand_unit_label is not None:
                self._live_demand_unit_label.setText("£/h")
            return
        last = slots.iloc[-1]
        rate = last.get("import_gbp_per_h")
        if rate is None or (isinstance(rate, float) and rate != rate):
            rate = last.get("gbp_per_h")
        try:
            rate_f = float(rate)
        except (TypeError, ValueError):
            rate_f = None
        if rate_f is None or rate_f != rate_f:
            self.card_labels["live_demand"].setText("--")
        else:
            self.card_labels["live_demand"].setText(f"{rate_f:.2f}")
            self.card_labels["live_demand"].setStyleSheet(
                "color: #f38ba8; font-weight: bold;"
            )
        if self._live_demand_unit_label is not None:
            age = self._sample_age_text(last.get("interval_start"))
            self._live_demand_unit_label.setText(f"£/h · {age}" if age else "£/h")
        self.card_labels["latest_import"].setText(f"{float(last['import_pence']):.1f}")
        self.card_labels["latest_export"].setText(f"{float(last['export_pence']):.1f}")
        net_p = float(last["net_pence"])
        self.card_labels["latest_net"].setText(f"{net_p:.1f}")
        nc = "#F44336" if net_p > 0 else "#4CAF50"
        self.card_labels["latest_net"].setStyleSheet(f"color: {nc}; font-weight: bold;")
        window = model.get("window") or {}
        today = model.get("today") or {}
        today_imp = today.get("import_pence")
        today_exp = today.get("export_pence")
        self._set_cost_total_with_today(
            self.card_labels["total_import"],
            window_gbp=float(window.get("import_pence", 0)) / 100.0,
            today_gbp=(float(today_imp) / 100.0) if today_imp is not None else None,
            color="#9C27B0",
        )
        self._set_cost_total_with_today(
            self.card_labels["total_export"],
            window_gbp=float(window.get("export_pence", 0)) / 100.0,
            today_gbp=(float(today_exp) / 100.0) if today_exp is not None else None,
            color="#009688",
        )

    @staticmethod
    def _sample_age_text(ts) -> str:
        if ts is None or (isinstance(ts, float) and ts != ts):
            return ""
        try:
            import pytz
            stamp = pd.Timestamp(ts)
            now_tz = datetime.now(pytz.timezone("Europe/London"))
            if stamp.tzinfo is None:
                delta = now_tz.replace(tzinfo=None) - stamp.to_pydatetime()
            else:
                delta = now_tz - stamp.to_pydatetime()
            s = max(0.0, delta.total_seconds())
        except Exception:
            return ""
        if s < 60:
            return f"{int(s)} s ago"
        if s < 3600:
            return f"{int(s // 60)} min ago"
        return f"{int(s // 3600)} h ago"

    def _plot_cost_charts(self):
        import matplotlib.dates as mdates
        self._clear_import_cost_axis()
        self.ax_import.clear()
        self.ax_net.clear()
        _style_ax_dark(self.ax_import, self.fig)
        _style_ax_dark(self.ax_net, self.fig)
        model, bundle, _energy, bounds = self._cost_model_for_view()
        london = bounds["london"]
        hours = bounds["hours"]
        now = bounds["now"]
        view_start = bounds["view_start"]
        view_end = bounds["view_end"]
        slots = None if not model else model.get("slots")
        if slots is None or slots.empty:
            if bundle and bundle.get("error"):
                msg = f"Cost prices unavailable:\n{bundle['error']}"
            elif not bundle or "scales" not in bundle:
                msg = "Fetching spot prices and recent Octopus meter days…"
            else:
                msg = "No cost in this window yet"
            self.ax_import.text(
                0.5, 0.5, msg, transform=self.ax_import.transAxes,
                ha="center", va="center", fontsize=12, color="#6c7086",
            )
            self._apply_figure_layout(self.fig)
            self.canvas.draw()
            return

        ts = slots["interval_start"]
        # Cost prices import only — export stays on the energy chart, not money.
        if "import_gbp_per_h" in slots.columns:
            rate = pd.to_numeric(slots["import_gbp_per_h"], errors="coerce")
        else:
            hours_slot = pd.to_numeric(slots["slot_hours"], errors="coerce").replace(0, pd.NA)
            rate = (pd.to_numeric(slots["import_pence"], errors="coerce") / 100.0) / hours_slot
        self.ax_import.fill_between(ts, rate.clip(lower=0), alpha=0.3, color="#f38ba8", step="mid")
        self.ax_import.step(ts, rate, color="#F44336", linewidth=1.2, where="mid", label="Import £/h")
        self.ax_import.axhline(0, color=_DARK_GRID, linewidth=0.6)
        self.ax_import.set_ylabel("£/h")
        title = (
            f"Import cost rate — previous {hours}h — "
            "£/h for grid import only (Gen / Used / Exp stay as energy below)"
        )
        if bounds["stale"]:
            title += " [latest available]"
        self.ax_import.set_title(title)
        if not bounds["stale"]:
            self.ax_import.axvline(now, color=_UI_BLUE, linestyle="--", linewidth=1, label="Now")
        if bounds["stale"] and bounds["latest_ts"] is not None:
            self.ax_import.axvline(
                bounds["latest_ts"], color="#f9e2af", linestyle=":", linewidth=1, label="Latest data",
            )
        tick_interval = max(1, hours // 12)
        fmt = "%d/%m %H:%M" if hours > 24 else "%H:%M"
        self.ax_import.set_xlim(view_start, view_end)
        self.ax_import.legend(
            loc="upper left", fontsize=8, framealpha=0.6,
            facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT,
        )
        self.ax_import.xaxis.set_major_formatter(mdates.DateFormatter(fmt, tz=london))
        self.ax_import.xaxis.set_major_locator(mdates.HourLocator(interval=tick_interval))
        self.ax_import.tick_params(axis="x", rotation=30, labelbottom=False)
        self.ax_import.grid(axis="y", color=_DARK_GRID, linewidth=0.4)

        has_imp = self.import_df is not None and not self.import_df.empty
        has_exp = self.export_df is not None and not self.export_df.empty
        imp_view = (
            self.import_df[self.import_df["interval_start"] >= view_start]
            if has_imp else pd.DataFrame()
        )
        exp_view = (
            self.export_df[self.export_df["interval_start"] >= view_start]
            if has_exp else pd.DataFrame()
        )
        has_demand = (
            has_imp and "demand_w" in self.import_df.columns
            and self.import_df["demand_w"].notna().any()
        )
        src = getattr(self, "_data_source", "REST")
        self._draw_cumulative_energy_pane(
            london=london,
            hours=hours,
            now=now,
            view_start=view_start,
            view_end=view_end,
            stale_window=bool(bounds["stale"]),
            latest_ts=bounds["latest_ts"],
            imp_view=imp_view,
            exp_view=exp_view,
            has_demand=has_demand,
            src=src,
            tick_interval=tick_interval,
            fmt=fmt,
            import_cost_slots=slots,
        )
        _draw_6h_vertical_grid(self.ax_import, london)
        _draw_day_date_labels(self.ax_import, london)
        self._tight_y_from_artists(self.ax_import)
        self._annotate_cost_days(self.ax_import, london, model.get("days") or [], view_start, view_end)
        scales = (bundle or {}).get("scales") or {}
        if scales.get("tuned_import"):
            self.ax_import.set_title(
                self.ax_import.get_title()
                + f" — today estimate import ×{scales['scale_import']:.2f}"
            )
        self.ax_import.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
            xv, yv, tz, "£/h",
            "import cost rate only. Today is an estimate when scaled from settled days",
        )
        self._apply_figure_layout(self.fig)
        self.canvas.draw()

    def _annotate_cost_days(self, ax, london, days, view_start, view_end):
        """Import £ top-right per London day (export stays energy — no £ note)."""
        import math
        import matplotlib.dates as mdates
        if not days:
            return
        rng = _resolve_axis_day_range(ax, london)
        if rng is None:
            return
        d_lo, _d_hi, n_days = rng
        if n_days > 120:
            return
        x_lo, x_hi = ax.get_xlim()
        ymin, ymax = ax.get_ylim()
        if not math.isfinite(ymin) or not math.isfinite(ymax) or ymax <= ymin:
            return
        span = max(1e-9, x_hi - x_lo)
        y_top = ymax - 0.06 * (ymax - ymin)
        x_pad = max(1e-5, span * 0.004)
        by_date = {d["date"]: d for d in days}
        for i in range(n_days):
            d = d_lo + timedelta(days=i)
            key = f"{d.year:04d}-{d.month:02d}-{d.day:02d}"
            row = by_date.get(key)
            if not row:
                continue
            midnight = pd.Timestamp(year=d.year, month=d.month, day=d.day, tz=london)
            next_mid = midnight + timedelta(days=1)
            x_day_l = mdates.date2num(midnight.to_pydatetime())
            x_day_r = mdates.date2num(next_mid.to_pydatetime())
            x_clip_l = max(x_day_l, x_lo, mdates.date2num(pd.Timestamp(view_start).to_pydatetime()))
            x_clip_r = min(x_day_r, x_hi, mdates.date2num(pd.Timestamp(view_end).to_pydatetime()))
            if x_clip_r - x_clip_l < span * 0.02:
                continue
            tag = {
                "settled": "settled",
                "tuned": "est.",
                "estimated": "est.",
                "mixed": "partial",
            }.get(row.get("basis"), "")
            imp = float(row["import_pence"]) / 100.0
            ax.text(
                x_clip_r - x_pad, y_top, f"Import £{imp:.2f}\n{tag}",
                ha="right", va="top", fontsize=8, color="#f38ba8", zorder=7, clip_on=True,
            )

    def _clear_import_cost_axis(self):
        """Remove a previous Cost twin £ axis on the bottom pane."""
        ax = getattr(self, "_ax_net_import_cost", None)
        if ax is None:
            return
        try:
            ax.remove()
        except Exception:
            try:
                self.fig.delaxes(ax)
            except Exception:
                pass
        self._ax_net_import_cost = None

    def _update_cost_summary(self):
        model, bundle, energy_source, _bounds = self._cost_model_for_view()
        if not bundle or bundle.get("error") or "scales" not in (bundle or {}):
            if bundle and bundle.get("error"):
                self.summary_text.setPlainText(
                    "Cost view could not load spot prices or the Octopus meter.\n"
                    + str(bundle["error"])
                )
            else:
                self.summary_text.setPlainText(
                    "Cost view is loading Agile spot prices and the last few days "
                    "of Octopus half-hour meter readings. Those settled days are "
                    "what tune today's estimate."
                )
            return
        if not model or model.get("slots") is None or model["slots"].empty:
            self.summary_text.setPlainText(
                "No energy in this window to price. Try a longer Hours range, "
                "or wait until the live meter returns a slot."
            )
            return
        lines = summary_lines(
            rates_source=bundle.get("rates_source") or "flat",
            scales=bundle.get("scales") or {},
            model=model,
            energy_source=energy_source,
            meter_direct=bool(bundle.get("meter_direct")),
        )
        self.summary_text.setPlainText("\n".join(lines))

    def _update_cards(self):
        if self._is_cost_mode():
            self._update_cost_cards()
            return
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
        for key, color, text in (
            ("total_import", "#9C27B0", f"{imp['consumption'].sum():.2f}" if has_imp else "--"),
            ("total_export", "#009688", f"{exp['consumption'].sum():.2f}" if has_exp else "--"),
        ):
            lab = self.card_labels[key]
            lab.setTextFormat(Qt.TextFormat.PlainText)
            lab.setStyleSheet(f"color: {color};")
            lab.setText(text)

    def _plot_charts(self):
        if self._is_cost_mode():
            self._plot_cost_charts()
            return
        import pytz, matplotlib.dates as mdates
        london = pytz.timezone('Europe/London')
        self._clear_import_cost_axis()
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

        self._draw_cumulative_energy_pane(
            london=london,
            hours=hours,
            now=now,
            view_start=view_start,
            view_end=view_end,
            stale_window=stale_window,
            latest_ts=latest_ts,
            imp_view=imp_view,
            exp_view=exp_view,
            has_demand=has_demand,
            src=src,
            tick_interval=tick_interval,
            fmt=fmt,
        )
        _draw_6h_vertical_grid(self.ax_import, london)
        _draw_day_date_labels(self.ax_import, london)
        self._tight_y_from_artists(self.ax_import)
        if has_demand and src == 'GraphQL':
            _octopus_live_draw_demand_zone_labels(self.ax_import, self.fig)
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
        self._apply_figure_layout(self.fig)
        self.canvas.draw()

    def _draw_cumulative_energy_pane(
        self, *, london, hours, now, view_start, view_end, stale_window, latest_ts,
        imp_view, exp_view, has_demand, src, tick_interval, fmt,
        import_cost_slots=None,
    ):
        """Bottom chart: Generated (PV), Imported, Total Used, Exported.

        In Power mode all four are kWh. In Cost mode only Imported is money
        (cumulative £ on a right-hand axis); Gen / Used / Exp stay as energy
        with no cost — including the bottom-right running labels.
        """
        import numpy as np
        import matplotlib.dates as mdates

        cost_import = (
            import_cost_slots is not None
            and not getattr(import_cost_slots, "empty", True)
            and "cum_import_gbp" in import_cost_slots.columns
        )

        gid = self.granularity_group.checkedId() if src == 'GraphQL' else 1
        slot_min = self._slot_minutes(src, gid)
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
        if not cum_df.empty:
            cum_df = self._attach_cumulative_pv(
                cum_df, view_start, view_end, slot_min, london,
            )
        has_cumulative = False
        legend_handles = []
        legend_labels = []
        if not cum_df.empty:
            ts = pd.to_datetime(cum_df['interval_start'])
            if ts.dt.tz is None:
                ts = ts.dt.tz_localize(london)
            else:
                ts = ts.dt.tz_convert(london)
            ci = cum_df['cum_import_kwh'].to_numpy(dtype=float)
            ce = (
                cum_df['cum_export_kwh'].to_numpy(dtype=float)
                if 'cum_export_kwh' in cum_df.columns
                else np.zeros_like(ci)
            )
            cpv = (
                cum_df['cum_pv_kwh'].to_numpy(dtype=float)
                if 'cum_pv_kwh' in cum_df.columns
                else np.zeros_like(ci)
            )
            ccons = (
                cum_df['cum_consumption_kwh'].to_numpy(dtype=float)
                if 'cum_consumption_kwh' in cum_df.columns
                else (ci + cpv - ce)
            )
            energy_peak = max(
                float(np.nanmax(ce)) if len(ce) else 0.0,
                float(np.nanmax(cpv)) if len(cpv) else 0.0,
                float(np.nanmax(ccons)) if len(ccons) else 0.0,
                0.0 if cost_import else (float(np.nanmax(ci)) if len(ci) else 0.0),
            )
            if energy_peak > 1e-9 or cost_import:
                has_cumulative = True
                ln_gen, = self.ax_net.step(
                    ts, cpv, where='post', color='#fab387', linewidth=1.6,
                    label='Generated Energy (PV)',
                )
                legend_handles.append(ln_gen)
                legend_labels.append('Generated Energy (PV)')
                if not cost_import:
                    ln_imp, = self.ax_net.step(
                        ts, ci, where='post', color='#F44336', linewidth=1.6,
                        label='Imported Energy',
                    )
                    legend_handles.append(ln_imp)
                    legend_labels.append('Imported Energy')
                ln_used, = self.ax_net.step(
                    ts, ccons, where='post', color='#cba6f7', linewidth=1.8,
                    label='Total Used Energy',
                )
                legend_handles.append(ln_used)
                legend_labels.append('Total Used Energy')
                ln_exp, = self.ax_net.step(
                    ts, ce, where='post', color='#4CAF50', linewidth=1.6,
                    label='Exported Energy',
                )
                legend_handles.append(ln_exp)
                legend_labels.append('Exported Energy')
                if float(np.nanmax(cpv)) <= 1e-9:
                    self.ax_net.text(
                        0.98, 0.05,
                        getattr(self, '_cum_pv_note', '') or 'No Growatt PV in this window',
                        transform=self.ax_net.transAxes,
                        ha='right', va='bottom', fontsize=9, color=_DARK_SUBTEXT,
                    )
                self.ax_net.axhline(0, color=_DARK_GRID, linewidth=0.6)
                if cost_import:
                    ymin = float(min(0.0, np.nanmin(ce), np.nanmin(cpv), np.nanmin(ccons)))
                    ymax = float(max(np.nanmax(ce), np.nanmax(cpv), np.nanmax(ccons), 0.01))
                else:
                    ymin = float(min(0.0, np.nanmin(ci), np.nanmin(ce), np.nanmin(cpv), np.nanmin(ccons)))
                    ymax = float(max(np.nanmax(ci), np.nanmax(ce), np.nanmax(cpv), np.nanmax(ccons)))
                pad = max((ymax - ymin) * 0.08, 0.01)
                self.ax_net.set_ylim(ymin - pad, ymax + pad)
            else:
                self.ax_net.text(
                    0.5, 0.5,
                    'No energy recorded in this window',
                    transform=self.ax_net.transAxes,
                    ha='center', va='center', fontsize=11, color=_DARK_SUBTEXT,
                )
        else:
            self.ax_net.text(
                0.5, 0.5, 'No cumulative energy data',
                transform=self.ax_net.transAxes,
                ha='center', va='center', fontsize=12, color=_DARK_SUBTEXT,
            )

        if cost_import:
            cost_df = import_cost_slots
            cts = pd.to_datetime(cost_df["interval_start"])
            if getattr(cts.dt, "tz", None) is None:
                cts = cts.dt.tz_localize(london, ambiguous="infer", nonexistent="shift_forward")
            else:
                cts = cts.dt.tz_convert(london)
            cimp = pd.to_numeric(cost_df["cum_import_gbp"], errors="coerce").fillna(0.0)
            ax_cost = self.ax_net.twinx()
            self._ax_net_import_cost = ax_cost
            _style_ax_dark(ax_cost, self.fig)
            ax_cost.set_frame_on(False)
            ax_cost.yaxis.set_label_position("right")
            ax_cost.yaxis.tick_right()
            ax_cost.tick_params(axis="y", colors="#F44336", labelsize=8)
            ax_cost.spines["right"].set_visible(True)
            ax_cost.spines["right"].set_color("#F44336")
            ln_imp_cost, = ax_cost.step(
                cts, cimp, where="post", color="#F44336", linewidth=1.8,
                label="Imported cost",
            )
            legend_handles.append(ln_imp_cost)
            legend_labels.append("Imported cost (£)")
            peak_cost = float(np.nanmax(cimp.to_numpy(dtype=float))) if len(cimp) else 0.0
            ax_cost.set_ylim(0.0, max(peak_cost * 1.12, 0.01))
            ax_cost.set_ylabel("Imported cost (£)", color="#F44336")
            ax_cost.set_xlim(view_start, view_end)
            has_cumulative = True

        if legend_handles:
            self.ax_net.legend(
                legend_handles, legend_labels,
                loc='upper left', fontsize=8, framealpha=0.6,
                facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT,
            )

        if not stale_window:
            self.ax_net.axvline(now, color=_UI_BLUE, linestyle='--', linewidth=1)
        if stale_window and latest_ts is not None:
            self.ax_net.axvline(latest_ts, color='#f9e2af', linestyle=':', linewidth=1)
        self.ax_net.set_xlim(view_start, view_end)
        self.ax_net.set_ylabel('Cumulative kWh')
        if cost_import:
            cum_title = (
                'Gen / Used / Exp (kWh) + Imported cost (£) — daily totals '
                f'(reset at London midnight, {hours}h view)'
            )
        else:
            cum_title = (
                'Generated / Imported / Total Used / Exported — daily totals '
                f'(reset at London midnight, {hours}h view)'
            )
        if cum_from_demand and not cum_df.empty:
            cum_title += ' (import/export from live demand)'
        if stale_window:
            cum_title += ' [latest available]'
        self.ax_net.set_title(cum_title)
        self.ax_net.xaxis.set_major_formatter(mdates.DateFormatter(fmt, tz=london))
        self.ax_net.xaxis.set_major_locator(mdates.HourLocator(interval=tick_interval))
        self.ax_net.tick_params(axis='x', rotation=30)
        self.ax_net.grid(axis='y', color=_DARK_GRID, linewidth=0.4)
        _draw_6h_vertical_grid(self.ax_net, london)
        _draw_day_date_labels(self.ax_net, london)
        if has_cumulative and not cum_df.empty:
            if cost_import:
                # Bottom-right energy labels without cost; Imp £ on the money axis.
                _octopus_live_draw_cumulative_day_labels(
                    self.ax_net, london, cum_df, now=now,
                    series=(
                        ('Gen', 'cum_pv_kwh', '#fab387'),
                        ('Used', 'cum_consumption_kwh', '#cba6f7'),
                        ('Exp', 'cum_export_kwh', '#4CAF50'),
                    ),
                )
                cost_lab = import_cost_slots.copy()
                _octopus_live_draw_cumulative_day_labels(
                    self._ax_net_import_cost, london, cost_lab, now=now,
                    series=(('Imp', 'cum_import_gbp', '#F44336'),),
                    value_fmt=lambda name, val: f"{name} £{val:.2f}",
                )
            else:
                _octopus_live_draw_cumulative_day_labels(
                    self.ax_net, london, cum_df, now=now,
                )
        if not has_cumulative:
            self._tight_y_from_artists(self.ax_net)
        if cost_import:
            self.ax_net.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
                xv, yv, tz, "cumulative kWh",
                "Generated / Total Used / Exported energy; Imported cost is on the right £ axis",
            )
        else:
            self.ax_net.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
                xv, yv, tz, "cumulative kWh",
                "daily running total of Generated (PV), Imported, Total Used "
                "(import+PV−export), or Exported; resets at London midnight",
            )

    def _update_summary(self):
        if self._is_cost_mode():
            self._update_cost_summary()
            return
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
