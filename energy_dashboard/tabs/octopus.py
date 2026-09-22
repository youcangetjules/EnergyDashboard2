"""
Energy Dashboard — `tabs/octopus.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *

_TREND_COLOUR = "#f9e2af"  # Catppuccin yellow — daily/weekly slope, not a 7-day avg


def _london_week_period(idx):
    """Monday–Sunday calendar weeks in Europe/London (pandas ``W-SUN``)."""
    s = pd.DatetimeIndex(idx)
    if s.tz is not None:
        s = s.tz_convert("Europe/London").tz_localize(None)
    return s.normalize().to_period("W-SUN")


def _weekly_from_daily(daily_totals, daily_gbp):
    """Sum daily import / export / £ into Mon–Sun weeks. Partial weeks kept as-is."""
    gbp = pd.Series(daily_gbp).reindex(daily_totals.index).fillna(0.0)
    df = pd.DataFrame(
        {
            "imp": daily_totals["Import (kWh)"].to_numpy(dtype=float),
            "exp": daily_totals["Export (kWh)"].to_numpy(dtype=float),
            "gbp": gbp.to_numpy(dtype=float),
            "week": _london_week_period(daily_totals.index),
        }
    )
    g = df.groupby("week", sort=True)
    out = g[["imp", "exp", "gbp"]].sum()
    out["n_days"] = g.size()
    out["net"] = out["imp"] - out["exp"]
    return out


def _fit_trend(values):
    """Linear fit across points. Returns ``(y_line, slope_per_step)`` or ``(None, None)``."""
    y = np.asarray(values, dtype=float)
    mask = np.isfinite(y)
    if int(mask.sum()) < 3:
        return None, None
    xs = np.arange(len(y), dtype=float)[mask]
    ys = y[mask]
    try:
        slope, intercept = np.polyfit(xs, ys, 1)
    except (np.linalg.LinAlgError, ValueError, TypeError):
        return None, None
    x_all = np.arange(len(y), dtype=float)
    return slope * x_all + intercept, float(slope)


class OctopusTab(QWidget):
    def __init__(self, status_callback, app_params=None):
        super().__init__()
        self.set_status = status_callback
        self.app_params = app_params
        self._inv = Invoker(self)
        self.daily_totals = None
        self.hh_data = None
        self._last_summary = None
        self.on_data_updated = None
        self._agile_import_series = None
        self._agile_export_series = None
        self._daily_net_cost_pence = None
        self._cost_uses_agile = False
        self.build_ui()
        self._load_saved_api_key()
        self._show_chart_message("Fetching Octopus meter data…")

    def _flat_import_p(self):
        if self.app_params is not None:
            return float(self.app_params.import_flat_pence)
        return 24.5

    def _flat_export_p(self):
        if self.app_params is not None:
            return float(self.app_params.export_flat_pence)
        return 15.0

    def recalc_estimated_cost(self):
        if self._last_summary is None:
            return
        total_import, total_export, net_usage, num_days = self._last_summary
        if num_days <= 0:
            return
        cost_p = self._recompute_energy_costs()
        if cost_p is None:
            ip, ep = self._flat_import_p(), self._flat_export_p()
            cost_p = total_import * ip - total_export * ep
        self.summary_labels['est_cost'].setText(f"\u00a3{cost_p / 100:.2f}")
        cost_c = '#f38ba8' if cost_p > 0 else '#a6e3a1'
        self.summary_labels['est_cost'].setStyleSheet(f"color: {cost_c}; font-weight: bold;")
        if self.daily_totals is not None:
            self._draw_charts(self.daily_totals)

    def _recompute_energy_costs(self):
        """Net cost in pence from half-hour slots: Agile (if loaded) else flat p/kWh."""
        self._daily_net_cost_pence = None
        self._cost_uses_agile = False
        if self.hh_data is None or self.hh_data.empty:
            return None
        hh = self.hh_data.sort_index()
        idx = hh.index
        fi, fe = self._flat_import_p(), self._flat_export_p()
        p_imp = _align_agile_rates_to_consumption_index(idx, self._agile_import_series, fi)
        p_exp = _align_agile_rates_to_consumption_index(idx, self._agile_export_series, fe)
        net_slot = hh["Import (kWh)"] * p_imp - hh["Export (kWh)"] * p_exp
        self._daily_net_cost_pence = net_slot.resample("D").sum()
        self._cost_uses_agile = bool(
            self._agile_import_series is not None and len(self._agile_import_series) > 0
        )
        return float(net_slot.sum())

    def build_ui(self):
        main_layout = QVBoxLayout(self)

        # --- Credentials ---
        cred_box = QGroupBox("Octopus Energy Credentials")
        cred_vlayout = QVBoxLayout(cred_box)

        row0 = QHBoxLayout()
        row0.addWidget(QLabel("API Key:"))
        self.api_key_edit = QLineEdit(DEFAULT_OCTOPUS_KEY)
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setMinimumWidth(300)
        row0.addWidget(self.api_key_edit)
        row0.addStretch()
        cred_vlayout.addLayout(row0)

        # Fixed label column so Import/Export MPAN fields share one left edge.
        _mpan_lbl_w = max(
            QFontMetrics(self.font()).horizontalAdvance(t)
            for t in ("Import MPAN:", "Export MPAN:")
        ) + 8
        _serial_lbl_w = max(
            QFontMetrics(self.font()).horizontalAdvance(t)
            for t in ("Import Serial:", "Export Serial:")
        ) + 8

        def _cred_label(text: str, width: int) -> QLabel:
            lbl = QLabel(text)
            lbl.setFixedWidth(width)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return lbl

        row1 = QHBoxLayout()
        row1.addWidget(_cred_label("Import MPAN:", _mpan_lbl_w))
        self.import_mpan_edit = QLineEdit(DEFAULT_IMPORT_MPAN)
        self.import_mpan_edit.setFixedWidth(160)
        row1.addWidget(self.import_mpan_edit)
        row1.addWidget(_cred_label("Import Serial:", _serial_lbl_w))
        self.import_serial_edit = QLineEdit(DEFAULT_IMPORT_SERIAL)
        self.import_serial_edit.setFixedWidth(130)
        row1.addWidget(self.import_serial_edit)
        row1.addStretch()
        cred_vlayout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(_cred_label("Export MPAN:", _mpan_lbl_w))
        self.export_mpan_edit = QLineEdit(DEFAULT_EXPORT_MPAN)
        self.export_mpan_edit.setFixedWidth(160)
        row2.addWidget(self.export_mpan_edit)
        row2.addWidget(_cred_label("Export Serial:", _serial_lbl_w))
        self.export_serial_edit = QLineEdit(DEFAULT_EXPORT_SERIAL)
        self.export_serial_edit.setFixedWidth(130)
        row2.addWidget(self.export_serial_edit)
        row2.addStretch()
        cred_vlayout.addLayout(row2)
        main_layout.addWidget(cred_box)

        # --- Controls ---
        ctrl_layout = QHBoxLayout()
        ctrl_layout.addWidget(QLabel("Date Range:"))
        self.days_group = QButtonGroup(self)
        for text, val in [("7 days", 7), ("14 days", 14), ("30 days", 30), ("90 days", 90)]:
            rb = QRadioButton(text)
            self.days_group.addButton(rb, val)
            ctrl_layout.addWidget(rb)
        self.days_group.button(30).setChecked(True)
        self.fetch_btn = QPushButton("Fetch Data")
        self.fetch_btn.clicked.connect(self.fetch_data)
        ctrl_layout.addWidget(self.fetch_btn)
        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export_csv)
        ctrl_layout.addWidget(self.export_btn)
        ctrl_layout.addStretch()
        main_layout.addLayout(ctrl_layout)

        # --- Summary ---
        summary_box = QGroupBox("Summary")
        summary_box.setStyleSheet(
            f"QGroupBox {{ background: {_DARK_SURFACE_BG}; border: 1px solid #313244; border-radius: 6px;"
            "  margin-top: 12px; padding: 8px 6px 6px 6px; color: #cdd6f4; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
        )
        # Single horizontal row of compact stat cards — saves a chunk of vertical
        # space vs the previous 2x4 grid and keeps the values readable.
        sg = QHBoxLayout(summary_box)
        sg.setContentsMargins(6, 4, 6, 4)
        sg.setSpacing(6)
        self.summary_labels = {}
        _stat_defs = [
            ('total_import',     'Import',           'kWh'),
            ('total_export',     'Export',           'kWh'),
            ('net_usage',        'Net',              'kWh'),
            ('days',             'Days',             ''),
            ('avg_daily_import', 'Avg Daily Import', 'kWh'),
            ('avg_daily_export', 'Avg Daily Export', 'kWh'),
            ('self_sufficiency', 'Self-Sufficiency', '%'),
            ('est_cost',         'Est. Net Cost',    ''),
        ]
        for key, title, unit in _stat_defs:
            frame = QFrame()
            frame.setStyleSheet(
                "QFrame { background: transparent; border: 1px solid #45475a; border-radius: 4px; padding: 2px; }"
            )
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(8, 3, 8, 3)
            fl.setSpacing(0)
            header = QLabel(title)
            header.setStyleSheet("color: #6c7086; font-size: 10px;")
            header.setAlignment(Qt.AlignCenter)
            fl.addWidget(header)
            val_lbl = QLabel("--")
            val_lbl.setFont(QFont('Helvetica', 16, QFont.Bold))
            val_lbl.setStyleSheet("color: #cdd6f4;")
            val_lbl.setAlignment(Qt.AlignCenter)
            fl.addWidget(val_lbl)
            # Always emit a unit row (use a non-breaking space when blank) so every
            # card has the same 3-line stack — keeps the header / value baselines
            # aligned across the row instead of QVBoxLayout re-centring the
            # shorter cards.
            unit_lbl = QLabel(unit if unit else '\u00a0')
            unit_lbl.setStyleSheet("color: #585b70; font-size: 9px;")
            unit_lbl.setAlignment(Qt.AlignCenter)
            fl.addWidget(unit_lbl)
            fl.addStretch(1)
            self.summary_labels[key] = val_lbl
            sg.addWidget(frame, 1)
        main_layout.addWidget(summary_box)

        # --- Charts (sub-tabs) ---
        _tab_style = (
            "QTabWidget::pane { border: 1px solid #313244; background: #1e1e2e; border-radius: 4px; }"
            "QTabBar::tab { background: #2a2a3c; color: #6c7086; padding: 6px 16px;"
            "  border: 1px solid #313244; border-bottom: none; border-top-left-radius: 4px;"
            "  border-top-right-radius: 4px; margin-right: 2px; }"
            "QTabBar::tab:selected { background: #1e1e2e; color: #cdd6f4; font-weight: bold; }"
        )
        self.chart_tabs = QTabWidget()
        self.chart_tabs.setStyleSheet(_tab_style)

        def _make_chart_tab(fig_attr, ax_attr):
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setContentsMargins(4, 4, 4, 4)
            fig = Figure(figsize=(12, 6), dpi=100)
            ax = fig.add_subplot(111)
            setattr(self, fig_attr, fig)
            setattr(self, ax_attr, ax)
            canvas = FigureCanvas(fig)
            lay.addWidget(canvas, 1)
            lay.addWidget(DarkNavigationToolbar(canvas, self))
            return w, canvas

        tab_daily, self.canvas_daily = _make_chart_tab('fig_daily', 'ax_daily')
        self.chart_tabs.addTab(tab_daily, "  Daily Import / Export  ")

        tab_hourly, self.canvas_hourly = _make_chart_tab('fig_hourly', 'ax_hourly')
        self.chart_tabs.addTab(tab_hourly, "  Typical Day Profile  ")

        tab_dow, self.canvas_dow = _make_chart_tab('fig_dow', 'ax_dow')
        self.chart_tabs.addTab(tab_dow, "  Day of Week  ")

        main_layout.addWidget(self.chart_tabs, 1)

    def _load_saved_api_key(self):
        """Use the API key saved on Octopus Live when this box still has the default.

        The default in the secrets file is rejected by Octopus (HTTP 401).
        The key saved from Octopus Live is the one that account accepts.
        """
        s = QSettings("PowerModel", "EnergyDashboard2")
        saved = str(s.value("octopus_live/api_key") or "").strip()
        if saved:
            self.api_key_edit.setText(saved)

    def _show_chart_message(self, message: str):
        """Dark placeholder so a failed or in-progress fetch is not a blank white plot."""
        for fig, canvas in (
            (self.fig_daily, self.canvas_daily),
            (self.fig_hourly, self.canvas_hourly),
            (self.fig_dow, self.canvas_dow),
        ):
            fig.clear()
            ax = fig.add_subplot(111)
            _style_ax_dark(ax, fig)
            ax.text(
                0.5, 0.5, message,
                transform=ax.transAxes, ha="center", va="center",
                fontsize=12, color="#cdd6f4", wrap=True,
            )
            ax.set_xticks([])
            ax.set_yticks([])
            canvas.draw_idle()

    def auto_start(self):
        self.fetch_data()

    def fetch_data(self):
        days = self.days_group.checkedId()
        if days < 1:
            days = 30
        cap = {
            "days": int(days),
            "api_key": self.api_key_edit.text().strip(),
            "imp_mpan": self.import_mpan_edit.text().strip(),
            "imp_serial": self.import_serial_edit.text().strip(),
            "exp_mpan": self.export_mpan_edit.text().strip(),
            "exp_serial": self.export_serial_edit.text().strip(),
        }
        self.fetch_btn.setEnabled(False)
        self._show_chart_message("Fetching Octopus meter data…")
        self.set_status("Fetching Octopus Energy data...")
        threading.Thread(target=self._fetch_thread, args=(cap,), daemon=True).start()

    def _fetch_thread(self, cap):
        from energy_dashboard.fetch.octopus_rest import get_meter_data_detailed
        try:
            days = int(cap["days"])
            current_date = datetime.now()
            end_date = current_date - timedelta(days=1)
            start_date = end_date - timedelta(days=days)
            api_key = cap["api_key"]
            df_import, err_imp = get_meter_data_detailed(
                api_key, cap["imp_mpan"], cap["imp_serial"], start_date, end_date,
            )
            df_export, err_exp = get_meter_data_detailed(
                api_key, cap["exp_mpan"], cap["exp_serial"], start_date, end_date,
            )
            if df_import.empty and df_export.empty:
                parts = [p for p in (err_imp, err_exp) if p]
                # Same rejection on both meters is one problem, not two.
                msg = parts[0] if len(set(parts)) <= 1 and parts else " | ".join(parts)
                msg = msg or "No Octopus data returned."
                self._inv.invoke(lambda m=msg: self._show_chart_message(m))
                self._inv.invoke(lambda m=msg: self.set_status(f"Octopus fetch failed: {m}"))
                self._inv.invoke(lambda: self.fetch_btn.setEnabled(True))
                return
            if not df_import.empty:
                df_import = df_import.rename(columns={'consumption': 'Import (kWh)'})
                df_import.set_index('interval_start', inplace=True)
            if not df_export.empty:
                df_export = df_export.rename(columns={'consumption': 'Export (kWh)'})
                df_export.set_index('interval_start', inplace=True)
            if df_import.empty:
                df_combined = df_export.copy()
                df_combined['Import (kWh)'] = 0.0
            elif df_export.empty:
                df_combined = df_import.copy()
                df_combined['Export (kWh)'] = 0.0
            else:
                df_combined = pd.merge(
                    df_import, df_export, left_index=True, right_index=True, how='outer'
                ).fillna(0)
            self._agile_import_series = None
            self._agile_export_series = None
            if not df_combined.empty:
                p0 = df_combined.index.min()
                p1 = df_combined.index.max() + pd.Timedelta(minutes=30)
                ap = self.app_params
                prod_ap = (ap.agile_product if ap else None) or DEFAULT_AGILE_PRODUCT
                tar_imp = (ap.agile_tariff if ap else None) or DEFAULT_AGILE_TARIFF
                tar_exp = (ap.agile_export_tariff if ap else None) or DEFAULT_AGILE_EXPORT_TARIFF
                imp_s = fetch_agile_rates_series_utc(prod_ap, tar_imp, p0, p1)
                if len(imp_s) > 0:
                    self._agile_import_series = imp_s
                exp_s = fetch_agile_rates_series_utc(prod_ap, tar_exp, p0, p1)
                if len(exp_s) > 0:
                    self._agile_export_series = exp_s
            self.hh_data = df_combined
            daily_totals = df_combined.resample('D').sum()
            daily_totals['Net (kWh)'] = daily_totals['Import (kWh)'] - daily_totals['Export (kWh)']
            self.daily_totals = daily_totals
            total_import = daily_totals['Import (kWh)'].sum()
            total_export = daily_totals['Export (kWh)'].sum()
            net_usage = total_import - total_export
            num_days = len(daily_totals)
            note = ""
            if df_import.empty and err_imp:
                note = f" Import meter: {err_imp}"
            elif df_export.empty and err_exp:
                note = f" Export meter: {err_exp}"
            self._inv.invoke(lambda n=note: self._update_display(
                total_import, total_export, net_usage, num_days, daily_totals, n,
            ))
        except Exception as e:
            err = str(e)
            self._inv.invoke(lambda msg=err: self.set_status(f"Octopus fetch error: {msg}"))
            self._inv.invoke(lambda: self.fetch_btn.setEnabled(True))

    def _update_display(self, total_import, total_export, net_usage, num_days, daily_totals, note=""):
        self.summary_labels['total_import'].setText(f"{total_import:.1f}")
        self.summary_labels['total_export'].setText(f"{total_export:.1f}")
        nc = '#f38ba8' if net_usage > 0 else '#a6e3a1'
        self.summary_labels['net_usage'].setText(f"{net_usage:.1f}")
        self.summary_labels['net_usage'].setStyleSheet(f"color: {nc}; font-weight: bold;")
        self.summary_labels['days'].setText(str(num_days))
        if num_days > 0:
            self.summary_labels['avg_daily_import'].setText(f"{total_import / num_days:.1f}")
            self.summary_labels['avg_daily_export'].setText(f"{total_export / num_days:.1f}")
            ss = (total_export / total_import * 100) if total_import > 0 else 0
            self.summary_labels['self_sufficiency'].setText(f"{ss:.0f}")
            ss_c = '#a6e3a1' if ss > 30 else '#fab387' if ss > 10 else '#f38ba8'
            self.summary_labels['self_sufficiency'].setStyleSheet(f"color: {ss_c}; font-weight: bold;")
            cost_p = self._recompute_energy_costs()
            if cost_p is None:
                ip, ep = self._flat_import_p(), self._flat_export_p()
                cost_p = total_import * ip - total_export * ep
                tip = "Flat import/export p/kWh from Parameters (no meter intervals loaded)."
            elif self._cost_uses_agile:
                tip = (
                    "Half-hourly Agile standard unit rates (Parameters import & export tariff codes) "
                    "matched to each meter slot: import cost minus export credit. Any gap uses flat p/kWh."
                )
            else:
                tip = (
                    "Agile rates were not returned for this date range; using flat import/export "
                    "p/kWh from Parameters for every slot."
                )
            self.summary_labels['est_cost'].setText(f"\u00a3{cost_p / 100:.2f}")
            self.summary_labels['est_cost'].setToolTip(tip)
            cost_c = '#f38ba8' if cost_p > 0 else '#a6e3a1'
            self.summary_labels['est_cost'].setStyleSheet(f"color: {cost_c}; font-weight: bold;")
        self._last_summary = (total_import, total_export, net_usage, num_days)
        self._draw_charts(daily_totals)
        self.export_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self.set_status(
            f"Octopus data loaded: {num_days} days, {total_import:.1f} kWh import, "
            f"{total_export:.1f} kWh export{note}"
        )
        if self.on_data_updated:
            self.on_data_updated()

    def _draw_charts(self, daily_totals):
        self._draw_daily(daily_totals)
        self._draw_hourly()
        self._draw_dow(daily_totals)

    def _draw_daily(self, daily_totals):
        """Render the Daily Import / Export sub-tab as a side-by-side pair of
        panels rather than the previous all-in-one chart that overlaid £
        figures as rotated text on top of the import bars (mixing kWh and £
        on a single axis was confusing — the two quantities are related via
        the tariff but only loosely correlate day-to-day on Agile).

        Layout:
          ┌──────────────────────┬──────────────────────┐
          │ Daily import/export  │ Daily net cost (£)   │
          ├──────────────────────┼──────────────────────┤
          │ Weekly power (kWh)   │ Weekly net cost (£)  │
          └──────────────────────┴──────────────────────┘
        Weeks are Monday–Sunday in Europe/London. Incomplete weeks at the
        ends of the fetch window are real meter totals (not scaled up).
        """
        fig = self.fig_daily
        fig.clear()
        gs = fig.add_gridspec(
            2, 2, wspace=0.16, hspace=0.42,
            height_ratios=[1.55, 1.05],
            left=0.055, right=0.985, top=0.95, bottom=0.08,
        )
        ax_kwh = fig.add_subplot(gs[0, 0])
        ax_gbp = fig.add_subplot(gs[0, 1])
        ax_wk_kwh = fig.add_subplot(gs[1, 0])
        ax_wk_gbp = fig.add_subplot(gs[1, 1])
        # Keep ax_daily pointing at the kWh panel so anything that still
        # reaches for self.ax_daily (e.g. external code, hover handlers)
        # sees a sensible default rather than a stale axis.
        self.ax_daily = ax_kwh
        for ax in (ax_kwh, ax_gbp, ax_wk_kwh, ax_wk_gbp):
            _style_ax_dark(ax, fig)

        dates = daily_totals.index
        x = np.arange(len(dates))
        fs = 7 if len(dates) > 45 else 8
        date_labels = [d.strftime('%a %d/%m') for d in dates]

        # ── LHS: Import / Export in kWh ──────────────────────────────────
        ax_kwh.bar(x, daily_totals['Import (kWh)'], 0.4, label='Import',
                   color='#f38ba8', alpha=0.75, align='edge', zorder=2)
        ax_kwh.bar(x + 0.4, -daily_totals['Export (kWh)'], 0.4, label='Export',
                   color='#a6e3a1', alpha=0.75, align='edge', zorder=2)
        if len(daily_totals) >= 7:
            ra = daily_totals['Net (kWh)'].rolling(7, center=True).mean()
            ax_kwh.plot(x + 0.4, ra, color=_UI_BLUE, linewidth=2,
                        label='7-day avg net', zorder=3)
        ax_kwh.axhline(y=0, color=_DARK_GRID, linewidth=0.6)
        ax_kwh.set_xticks(x + 0.4)
        ax_kwh.set_xticklabels(date_labels, rotation=45, ha='right', fontsize=fs)
        ax_kwh.set_ylabel('kWh', fontsize=10)
        ax_kwh.set_title('Daily Import & Export (kWh)',
                         fontsize=12, fontweight='bold', pad=8)
        ax_kwh.legend(fontsize=9, loc='upper right', framealpha=0.6,
                      facecolor=_DARK_FACE, edgecolor=_DARK_GRID,
                      labelcolor=_DARK_TEXT)
        ax_kwh.grid(axis='y', color=_DARK_GRID, linewidth=0.4)

        # ── RHS: Daily net charge in £, baselined at zero ───────────────
        # Bars are the absolute daily spend in £ (zero-baselined, growing
        # upwards). The £10/day budget is a dotted reference line — the
        # y-axis grows to the tallest bar (and never below the budget
        # line) so over-budget days are shown in full, in red.
        BUDGET_PER_DAY_GBP = 10.0
        ip = self._flat_import_p()
        ep = self._flat_export_p()
        if (self._daily_net_cost_pence is not None
                and len(self._daily_net_cost_pence) > 0):
            daily_gbp = (self._daily_net_cost_pence
                         .reindex(dates).fillna(0.0) / 100.0)
            cost_basis = "Agile half-hourly rates" if self._cost_uses_agile \
                else "flat p/kWh from Setup & Info"
        else:
            # Fall back to flat tariff-based per-day cost so the chart still
            # renders when Agile prices haven't been pulled yet.
            daily_gbp = (
                daily_totals['Import (kWh)'] * ip
                - daily_totals['Export (kWh)'] * ep
            ) / 100.0
            cost_basis = "flat p/kWh from Setup & Info"
        gbp_vals = daily_gbp.values
        cost_colours = [
            '#f38ba8' if v > BUDGET_PER_DAY_GBP else '#a6e3a1'
            for v in gbp_vals
        ]
        ax_gbp.bar(x + 0.2, gbp_vals, 0.6, color=cost_colours,
                   alpha=0.85, edgecolor=_DARK_FACE, linewidth=0.5, zorder=2)
        if len(gbp_vals) >= 7:
            avg_gbp = (pd.Series(gbp_vals, index=daily_gbp.index)
                       .rolling(7, center=True).mean())
            ax_gbp.plot(x + 0.2, avg_gbp.values, color=_UI_BLUE,
                        linewidth=2, label='7-day avg', zorder=3)
        # Linear trendline across the visible window — fitted over ALL
        # finite days (not the rolling avg, which has NaN tails) so the
        # slope reflects the entire selected date range. Renders only when
        # there are enough points for the fit to mean anything (≥4 days).
        # Annotate the slope at the right end so the user can read the
        # weekly drift without a ruler. Ignored if fitting fails for any
        # reason (e.g. all-NaN, all-zero degenerate data).
        try:
            mask = np.isfinite(gbp_vals)
            if int(mask.sum()) >= 4:
                xs = x[mask].astype(float)
                ys = gbp_vals[mask]
                slope, intercept = np.polyfit(xs, ys, 1)
                trend_x = np.array([x[0], x[-1]], dtype=float) + 0.2
                trend_y = slope * np.array([x[0], x[-1]], dtype=float) + intercept
                ax_gbp.plot(
                    trend_x, trend_y,
                    color=_TREND_COLOUR, linewidth=1.8, linestyle='--',
                    label=f'Trend ({slope * 7:+.2f} £/wk)', zorder=3,
                )
        except (np.linalg.LinAlgError, ValueError, TypeError):
            pass
        # £10/day budget reference (not a y-axis cap).
        ax_gbp.axhline(y=BUDGET_PER_DAY_GBP, color='#cdd6f4',
                       linewidth=1.0, linestyle=':', alpha=0.7, zorder=2)
        ax_gbp.text(
            len(x) - 0.5, BUDGET_PER_DAY_GBP,
            f' £{BUDGET_PER_DAY_GBP:.0f}/day budget ',
            ha='right', va='bottom', fontsize=fs - 1,
            color='#cdd6f4', alpha=0.85,
            bbox=dict(facecolor=_DARK_FACE, edgecolor='none',
                      alpha=0.7, pad=1.5),
            zorder=4,
        )
        ax_gbp.axhline(y=0, color=_DARK_GRID, linewidth=0.6, zorder=1)
        if ax_gbp.get_legend_handles_labels()[1]:
            ax_gbp.legend(fontsize=9, loc='upper left', framealpha=0.6,
                          facecolor=_DARK_FACE, edgecolor=_DARK_GRID,
                          labelcolor=_DARK_TEXT)
        ax_gbp.set_xticks(x + 0.2)
        ax_gbp.set_xticklabels(date_labels, rotation=45, ha='right', fontsize=fs)
        ax_gbp.set_ylabel('£', fontsize=10)
        ax_gbp.set_title(
            f'Daily Net Charge (£) — {cost_basis}',
            fontsize=12, fontweight='bold', pad=8,
        )
        ax_gbp.grid(axis='y', color=_DARK_GRID, linewidth=0.4)
        # Grow to the tallest bar; keep the budget line on-scale; pad so
        # value labels aren't clipped. Lower bound auto-extends if any
        # day is an export credit.
        finite_gbp = gbp_vals[np.isfinite(gbp_vals)]
        y_lo = min(0.0, float(finite_gbp.min()) - 0.5) if finite_gbp.size else 0.0
        y_peak = float(finite_gbp.max()) if finite_gbp.size else 0.0
        y_hi = max(BUDGET_PER_DAY_GBP, y_peak)
        y_span = max(y_hi - y_lo, 1.0)
        ax_gbp.set_ylim(y_lo, y_hi + 0.10 * y_span)
        if len(gbp_vals) <= 60:  # bail on dense charts to avoid clutter
            label_pad = 0.05 * y_span / 10.0
            for xi, v in zip(x, gbp_vals):
                if not np.isfinite(v) or abs(v) < 0.005:
                    continue
                over = v > BUDGET_PER_DAY_GBP
                va = 'bottom' if v >= 0 else 'top'
                offset = label_pad if v >= 0 else -label_pad
                ax_gbp.text(
                    xi + 0.2, v + offset, f"£{v:.2f}",
                    ha='center', va=va, fontsize=fs - 1,
                    color='#f38ba8' if over else _DARK_TEXT,
                    fontweight='bold' if over else 'normal',
                    zorder=4,
                )

        # ── Bottom row: Monday–Sunday weeks (power + cost) ──────────────
        self._draw_weekly_trends(ax_wk_kwh, ax_wk_gbp, daily_totals, daily_gbp, fs)

        # ── Rich cursor read-out (replaces matplotlib's "(x, y)" default)
        # Matplotlib's NavigationToolbar shows the format_coord() output of
        # the axes the mouse is in, in the bottom-right of the figure. The
        # default "(x, y)" — where x is a fractional bar index and y is
        # raw kWh / £ — carries no context: you can't tell which day the
        # cursor is on without counting tick labels. Override format_coord
        # on each axes so the toolbar shows the day, all the kWh/£ values
        # we'd normally have to dig out of the bar labels, AND the rolling
        # average. Closures capture daily_totals / dates / gbp_vals so each
        # axes has the right data; falls back to a clean "x=…, y=…" string
        # outside the data range so the cursor is still useful past the
        # first / last bar.
        n_days = len(dates)
        net_kwh_arr = (
            daily_totals['Import (kWh)'].values
            - daily_totals['Export (kWh)'].values
        )
        if n_days >= 7:
            ra_kwh = (
                pd.Series(net_kwh_arr, index=daily_totals.index)
                .rolling(7, center=True).mean().values
            )
            ra_gbp = (
                pd.Series(gbp_vals, index=daily_gbp.index)
                .rolling(7, center=True).mean().values
            )
        else:
            ra_kwh = np.full(n_days, np.nan)
            ra_gbp = np.full(n_days, np.nan)

        def _fmt_kwh_coord(xv, yv):
            idx = int(round(xv - 0.4))
            if 0 <= idx < n_days:
                d = dates[idx]
                imp = float(daily_totals['Import (kWh)'].iloc[idx])
                exp = float(daily_totals['Export (kWh)'].iloc[idx])
                net = imp - exp
                ra = ra_kwh[idx]
                ra_str = (f"  ·  7-day avg net {ra:+.2f} kWh"
                          if np.isfinite(ra) else "")
                return (
                    f"Horizontal (x): bar ~{xv:.2f} = day {d.strftime('%a %d %b %Y')}  |  "
                    f"That day: import {imp:.2f} kWh, export {exp:.2f} kWh, net {net:+.2f} kWh{ra_str}  |  "
                    f"Vertical (y, kWh): {yv:.2f} — position on the bar / net line at this x"
                )
            return (
                f"Horizontal (x): {xv:.2f} (between daily bars)  |  "
                f"Vertical (y, kWh): {yv:.2f} — out of bar range; use on-chart days"
            )

        def _fmt_gbp_coord(xv, yv):
            idx = int(round(xv - 0.2))
            if 0 <= idx < n_days:
                d = dates[idx]
                ab = float(gbp_vals[idx])
                de = ab - BUDGET_PER_DAY_GBP
                ra = ra_gbp[idx]
                ra_str = (f"  ·  7-day avg £{ra:.2f}"
                          if np.isfinite(ra) else "")
                under_over = "under" if de < 0 else "over"
                return (
                    f"Horizontal (x): bar ~{xv:.2f} = {d.strftime('%a %d %b %Y')}  |  "
                    f"That day est. cost £{ab:.2f} ({abs(de):.2f} {under_over} "
                    f"£{BUDGET_PER_DAY_GBP:.0f}/day budget){ra_str}  |  "
                    f"Vertical (y, £): {yv:.2f} — height on cost / net display"
                )
            return (
                f"Horizontal (x): {xv:.2f}  |  Vertical (y, £): {yv:.2f} — off bar range"
            )

        ax_kwh.format_coord = _fmt_kwh_coord
        ax_gbp.format_coord = _fmt_gbp_coord

        self.canvas_daily.draw()

    def _draw_weekly_trends(self, ax_kwh, ax_gbp, daily_totals, daily_gbp, fs):
        """Monday–Sunday totals under the daily pair: kWh and £, plus weekly slope."""
        weekly = _weekly_from_daily(daily_totals, daily_gbp)
        if weekly.empty:
            for ax, unit in ((ax_kwh, "kWh"), (ax_gbp, "£")):
                ax.text(
                    0.5, 0.5, "No weekly totals yet",
                    transform=ax.transAxes, ha="center", va="center",
                    fontsize=11, color="#6c7086",
                )
                ax.set_ylabel(unit, fontsize=10)
            return

        n = len(weekly)
        x = np.arange(n)
        labels = []
        for period, n_days in zip(weekly.index, weekly["n_days"]):
            start = period.start_time.to_pydatetime()
            tag = start.strftime("w/c %d %b")
            if int(n_days) < 6:
                tag += "*"
            labels.append(tag)
        tick_fs = 7 if n > 10 else fs

        # Power: import up, export down — same mapping as the daily kWh panel.
        b_imp = ax_kwh.bar(
            x, weekly["imp"].to_numpy(), 0.4, label="Import",
            color="#f38ba8", alpha=0.75, align="edge", zorder=2,
        )
        b_exp = ax_kwh.bar(
            x + 0.4, -weekly["exp"].to_numpy(), 0.4, label="Export",
            color="#a6e3a1", alpha=0.75, align="edge", zorder=2,
        )
        n_days_arr = weekly["n_days"].to_numpy()
        full_week = n_days_arr >= 6
        net = weekly["net"].to_numpy(dtype=float)
        for i, n_days in enumerate(n_days_arr):
            if int(n_days) < 6:
                b_imp[i].set_alpha(0.45)
                b_exp[i].set_alpha(0.45)
        net_fit = np.where(full_week, net, np.nan)
        trend_y, slope = _fit_trend(net_fit)
        if trend_y is not None:
            ax_kwh.plot(
                x + 0.4, trend_y, color=_TREND_COLOUR, linewidth=1.8,
                linestyle="--", label=f"Trend ({slope:+.1f} kWh/wk)", zorder=3,
            )
        ax_kwh.axhline(y=0, color=_DARK_GRID, linewidth=0.6)
        ax_kwh.set_xticks(x + 0.4)
        ax_kwh.set_xticklabels(labels, rotation=30, ha="right", fontsize=tick_fs)
        ax_kwh.set_ylabel("kWh / week", fontsize=10)
        ax_kwh.set_title(
            "Weekly power (Mon–Sun)",
            fontsize=11, fontweight="bold", pad=6,
        )
        ax_kwh.legend(
            fontsize=8, loc="upper right", framealpha=0.6,
            facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT,
        )
        ax_kwh.grid(axis="y", color=_DARK_GRID, linewidth=0.4)
        if any(int(d) < 6 for d in weekly["n_days"].to_numpy()):
            ax_kwh.text(
                0.0, -0.22, "* incomplete week in this date range (not scaled up)",
                transform=ax_kwh.transAxes, fontsize=8, color="#6c7086",
                ha="left", va="top", clip_on=False,
            )

        gbp_w = weekly["gbp"].to_numpy(dtype=float)
        cost_colours = ["#f38ba8" if v > 0 else "#a6e3a1" for v in gbp_w]
        bars = ax_gbp.bar(
            x + 0.2, gbp_w, 0.6, color=cost_colours, alpha=0.85,
            edgecolor=_DARK_FACE, linewidth=0.5, zorder=2,
        )
        for bar, n_days in zip(bars, n_days_arr):
            if int(n_days) < 6:
                bar.set_alpha(0.45)
        gbp_fit = np.where(full_week, gbp_w, np.nan)
        trend_y, slope = _fit_trend(gbp_fit)
        if trend_y is not None:
            ax_gbp.plot(
                x + 0.2, trend_y, color=_TREND_COLOUR, linewidth=1.8,
                linestyle="--", label=f"Trend ({slope:+.2f} £/wk)", zorder=3,
            )
        ax_gbp.axhline(y=0, color=_DARK_GRID, linewidth=0.6, zorder=1)
        if ax_gbp.get_legend_handles_labels()[1]:
            ax_gbp.legend(
                fontsize=8, loc="upper left", framealpha=0.6,
                facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT,
            )
        ax_gbp.set_xticks(x + 0.2)
        ax_gbp.set_xticklabels(labels, rotation=30, ha="right", fontsize=tick_fs)
        ax_gbp.set_ylabel("£ / week", fontsize=10)
        ax_gbp.set_title(
            "Weekly net charge (Mon–Sun)",
            fontsize=11, fontweight="bold", pad=6,
        )
        ax_gbp.grid(axis="y", color=_DARK_GRID, linewidth=0.4)
        finite = gbp_w[np.isfinite(gbp_w)]
        if finite.size:
            y_lo = min(0.0, float(finite.min()) - 0.5)
            y_hi = max(0.5, float(finite.max()))
            span = max(y_hi - y_lo, 1.0)
            ax_gbp.set_ylim(y_lo, y_hi + 0.12 * span)
            if n <= 16:
                pad = 0.04 * span
                for xi, v in zip(x, gbp_w):
                    if not np.isfinite(v) or abs(v) < 0.005:
                        continue
                    ax_gbp.text(
                        xi + 0.2, v + (pad if v >= 0 else -pad),
                        f"£{v:.0f}",
                        ha="center", va="bottom" if v >= 0 else "top",
                        fontsize=tick_fs - 1, color=_DARK_TEXT, zorder=4,
                    )

        weeks = list(weekly.index)
        n_days_arr = weekly["n_days"].to_numpy()
        imp_arr = weekly["imp"].to_numpy(dtype=float)
        exp_arr = weekly["exp"].to_numpy(dtype=float)
        net_arr = weekly["net"].to_numpy(dtype=float)

        def _fmt_wk_kwh(xv, yv):
            idx = int(round(xv - 0.4))
            if 0 <= idx < n:
                start = weeks[idx].start_time.to_pydatetime()
                partial = " (incomplete)" if int(n_days_arr[idx]) < 6 else ""
                return (
                    f"Week commencing {start.strftime('%a %d %b %Y')}{partial}  |  "
                    f"{int(n_days_arr[idx])} day(s)  |  "
                    f"import {imp_arr[idx]:.1f} kWh, export {exp_arr[idx]:.1f} kWh, "
                    f"net {net_arr[idx]:+.1f} kWh  |  y={yv:.1f} kWh"
                )
            return f"x={xv:.2f}  |  y={yv:.1f} kWh"

        def _fmt_wk_gbp(xv, yv):
            idx = int(round(xv - 0.2))
            if 0 <= idx < n:
                start = weeks[idx].start_time.to_pydatetime()
                partial = " (incomplete)" if int(n_days_arr[idx]) < 6 else ""
                return (
                    f"Week commencing {start.strftime('%a %d %b %Y')}{partial}  |  "
                    f"{int(n_days_arr[idx])} day(s)  |  "
                    f"net charge £{gbp_w[idx]:.2f}  |  y=£{yv:.2f}"
                )
            return f"x={xv:.2f}  |  y=£{yv:.2f}"

        ax_kwh.format_coord = _fmt_wk_kwh
        ax_gbp.format_coord = _fmt_wk_gbp

    def _draw_hourly(self):
        ax = self.ax_hourly
        ax.clear()
        _style_ax_dark(ax, self.fig_hourly)

        if self.hh_data is None or self.hh_data.empty:
            ax.text(0.5, 0.5, 'No half-hourly data',
                    transform=ax.transAxes, ha='center', va='center',
                    fontsize=13, color='#6c7086')
            self.fig_hourly.tight_layout()
            self.canvas_hourly.draw()
            return

        hh = self.hh_data.copy()
        hourly_imp = hh.groupby(hh.index.hour)['Import (kWh)'].mean()
        hourly_exp = hh.groupby(hh.index.hour)['Export (kWh)'].mean()
        hours = hourly_imp.index

        ax.fill_between(hours, hourly_imp, alpha=0.25, color='#f38ba8', step='mid')
        ax.step(hours, hourly_imp, color='#f38ba8', linewidth=2, where='mid', label='Avg Import')
        ax.fill_between(hours, -hourly_exp, alpha=0.25, color='#a6e3a1', step='mid')
        ax.step(hours, -hourly_exp, color='#a6e3a1', linewidth=2, where='mid', label='Avg Export')
        net_hourly = hourly_imp - hourly_exp
        ax.step(hours, net_hourly, color=_UI_BLUE, linewidth=1.5, linestyle='--',
                where='mid', label='Net', alpha=0.8)
        ax.axhline(y=0, color=_DARK_GRID, linewidth=0.6)

        peak_hour = hourly_imp.idxmax()
        peak_val = hourly_imp.max()
        ax.annotate(f'Peak: {peak_val:.2f} kWh @ {peak_hour:02d}:00',
                    xy=(peak_hour, peak_val), xytext=(peak_hour + 3, peak_val * 1.1),
                    fontsize=9, color='#fab387',
                    arrowprops=dict(arrowstyle='->', color='#fab387', lw=1.2))

        ax.set_xlabel('Hour of Day', fontsize=10)
        ax.set_ylabel('Avg kWh per half-hour slot', fontsize=10)
        ax.set_title('Typical Day Profile', fontsize=13, fontweight='bold', pad=10)
        ax.set_xticks(range(0, 24, 2))
        ax.set_xticklabels([f'{h:02d}:00' for h in range(0, 24, 2)], fontsize=8, rotation=30)
        ax.legend(fontsize=9, loc='upper left', framealpha=0.6,
                  facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT)
        ax.grid(axis='y', color=_DARK_GRID, linewidth=0.4)
        ax.format_coord = lambda xv, yv: (
            f"Horizontal (x): clock hour ~{xv:.1f} (0–24) — bucket for typical profile  |  "
            f"{_fmt_toolbar_y(yv, 'kWh', 'mean energy per ½h slot (import, export, or net line)')}"
        )
        self.fig_hourly.tight_layout(pad=2.0)
        self.canvas_hourly.draw()

    def _draw_dow(self, daily_totals):
        ax = self.ax_dow
        ax.clear()
        _style_ax_dark(ax, self.fig_dow)

        if len(daily_totals) < 7:
            ax.text(0.5, 0.5, 'Need 7+ days for weekly view',
                    transform=ax.transAxes, ha='center', va='center',
                    fontsize=13, color='#6c7086')
            self.fig_dow.tight_layout()
            self.canvas_dow.draw()
            return

        dow_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        dow_imp = daily_totals.groupby(daily_totals.index.dayofweek)['Import (kWh)'].mean()
        dow_exp = daily_totals.groupby(daily_totals.index.dayofweek)['Export (kWh)'].mean()
        dow_net = dow_imp - dow_exp
        dows = sorted(dow_imp.index)
        imp_vals = [dow_imp.get(d, 0) for d in dows]
        exp_vals = [dow_exp.get(d, 0) for d in dows]
        net_vals = [dow_net.get(d, 0) for d in dows]
        dx = np.arange(len(dows))

        ax.bar(dx - 0.25, imp_vals, 0.25, color='#f38ba8', alpha=0.75, label='Avg Import')
        ax.bar(dx, exp_vals, 0.25, color='#a6e3a1', alpha=0.75, label='Avg Export')
        ax.bar(dx + 0.25, net_vals, 0.25, color=_UI_BLUE, alpha=0.75, label='Avg Net')
        ax.axhline(y=0, color=_DARK_GRID, linewidth=0.6)

        for i, nv in enumerate(net_vals):
            color = '#f38ba8' if nv > 0 else '#a6e3a1'
            ax.text(dx[i] + 0.25, nv + max(imp_vals) * 0.02, f'{nv:.1f}',
                    ha='center', va='bottom', fontsize=9, color=color, fontweight='bold')

        ax.set_xticks(dx)
        ax.set_xticklabels([dow_names[d] for d in dows], fontsize=11)
        ax.set_ylabel('Avg kWh / day', fontsize=10)
        ax.set_title('Day of Week Breakdown', fontsize=13, fontweight='bold', pad=10)
        ax.legend(fontsize=9, loc='upper right', framealpha=0.6,
                  facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT)
        ax.grid(axis='y', color=_DARK_GRID, linewidth=0.4)
        ax.format_coord = lambda xv, yv: (
            f"Horizontal (x): weekday index ~{xv:.1f} (0=Mon … 6=Sun)  |  "
            f"{_fmt_toolbar_y(yv, 'kWh/day', 'average daily import / export / net for that weekday')}"
        )
        self.fig_dow.tight_layout(pad=2.0)
        self.canvas_dow.draw()

    def export_csv(self):
        if self.daily_totals is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "energy_data.csv", "CSV files (*.csv)")
        if path:
            self.daily_totals.to_csv(path)
            self.set_status(f"Exported to {path}")

    def get_daily_totals(self):
        return self.daily_totals


__all__ = [n for n in globals() if not n.startswith('__')]
