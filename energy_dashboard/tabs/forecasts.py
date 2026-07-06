"""
Energy Dashboard — `tabs/forecasts.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.db.logger import _utc_to_london_cols


def _merge_agile_forecast_frames(live_df, db_df):
    """Combine Octopus live pull with DB snapshots; live wins on duplicate slots."""
    live = _coerce_agile_frame(live_df)
    db = _coerce_agile_frame(db_df)
    if live.is_empty():
        return db
    if db.is_empty():
        return live
    return (
        pl.concat([db, live], how='vertical')
        .sort('valid_from')
        .unique(subset=['valid_from'], keep='last')
    )


def _coerce_agile_frame(df):
    """Ensure Agile frames use London-aware ``valid_from`` / ``valid_to`` (Polars)."""
    if df is None:
        return pl.DataFrame()
    if isinstance(df, pd.DataFrame):
        if df.empty:
            return pl.DataFrame()
        try:
            df = pl.from_pandas(df)
        except ImportError:
            df = pl.DataFrame({c: df[c].to_list() for c in df.columns})
    elif isinstance(df, pl.DataFrame):
        if df.is_empty():
            return pl.DataFrame()
    else:
        return pl.DataFrame()
    if 'value_inc_vat' in df.columns and 'price_pence' not in df.columns:
        df = df.rename({'value_inc_vat': 'price_pence'})
    df = _utc_to_london_cols(df, 'valid_from', 'valid_to')
    df = df.filter(pl.col('valid_from').is_not_null())
    if 'price_pence' in df.columns:
        df = df.filter(pl.col('price_pence').is_not_null())
    return df
_FORECAST_LOCALE_CACHE_VER = 2
# Chart window and Nominatim zoom for locale label (Forecasts tab).
_FORECAST_CHART_DAYS_MAX = 7
_FORECAST_CHART_DAYS_DEFAULT = 4
_FORECAST_CHART_DAYS_SETTINGS_KEY = "forecasts/chart_days"
_FORECAST_NOMINATIM_LOCALE_ZOOM = 16


class ForecastsTab(QWidget):
    def __init__(self, status_callback, data_logger=None):
        super().__init__()
        self.set_status = status_callback
        self.data_logger = data_logger  # may be None during early init / tests
        self._inv = Invoker(self)
        self.agile_df = None
        self.agile_export_df = None
        self.solar_df = None
        self.fetching = False
        # ConnectivityStatusTab reads these after each forecast refresh.
        self._solar_last_msg = ""
        self._solar_last_refresh_local = None
        self.on_data_updated = None
        # Reverse-geocode cache so we don't hammer Nominatim while the user
        # is editing lat/lon or repeatedly opening the map picker. Keyed on
        # rounded lat/lon plus _FORECAST_LOCALE_CACHE_VER so display ↔ cache
        # agree and format logic can be invalidated in one bump.
        self._locale_cache = {}
        self._locale_in_flight_key = None
        self.build_ui()
        # Restore lat/lon/tilt/azimuth/kWp from the previous session BEFORE
        # the first locale lookup, so the locale label reflects the actual
        # saved location instead of the hard-coded defaults.
        self._load_saved_solar_params()
        self._load_saved_chart_days()
        # Kick off an initial reverse-geocode for whatever defaults shipped.
        QTimer.singleShot(0, self._refresh_locale_label)

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Vertical)

        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        ctrl_box = QGroupBox("Forecast Parameters")
        ctrl_vlayout = QVBoxLayout(ctrl_box)

        row_agile = QHBoxLayout()
        row_agile.addWidget(QLabel("Agile:"))
        row_agile.addWidget(QLabel("Product:"))
        self.product_edit = QLineEdit(DEFAULT_AGILE_PRODUCT)
        self.product_edit.setFixedWidth(160)
        row_agile.addWidget(self.product_edit)
        row_agile.addWidget(QLabel("Import tariff:"))
        self.tariff_edit = QLineEdit(DEFAULT_AGILE_TARIFF)
        self.tariff_edit.setFixedWidth(200)
        row_agile.addWidget(self.tariff_edit)
        row_agile.addWidget(QLabel("Export (outgoing):"))
        self.export_tariff_edit = QLineEdit(DEFAULT_AGILE_EXPORT_TARIFF)
        self.export_tariff_edit.setFixedWidth(220)
        self.export_tariff_edit.setToolTip(
            "Agile Outgoing / export tariff code from Octopus "
            "(offered export price per half-hour)"
        )
        row_agile.addWidget(self.export_tariff_edit)
        self.fetch_btn = QPushButton("Fetch Forecasts")
        self.fetch_btn.clicked.connect(self.fetch_forecasts)
        row_agile.addWidget(self.fetch_btn)
        row_agile.addWidget(QLabel("Chart days:"))
        self.chart_days_combo = QComboBox()
        for d in range(1, _FORECAST_CHART_DAYS_MAX + 1):
            self.chart_days_combo.addItem(
                f"{d} day{'s' if d != 1 else ''}", d,
            )
        self.chart_days_combo.setCurrentIndex(_FORECAST_CHART_DAYS_DEFAULT - 1)
        self.chart_days_combo.setFixedWidth(88)
        self.chart_days_combo.setToolTip(
            f"Past days to show on the charts (1–{_FORECAST_CHART_DAYS_MAX}). "
            "History is loaded from the database; each fetch also saves new snapshots."
        )
        self.chart_days_combo.currentIndexChanged.connect(self._on_chart_days_changed)
        row_agile.addWidget(self.chart_days_combo)
        self.rate_limit_label = QLabel("")
        self.rate_limit_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        row_agile.addWidget(self.rate_limit_label)
        row_agile.addStretch()
        ctrl_vlayout.addLayout(row_agile)

        row_solar = QHBoxLayout()
        row_solar.addWidget(QLabel("Solar:"))
        self.solar_edits = {}
        _spec = [
            ("Lat",     DEFAULT_FORECAST_LAT,         84, "lat",     ('latlon', -90.0,  90.0)),
            ("Lon",     DEFAULT_FORECAST_LON,         84, "lon",     ('latlon', -180.0, 180.0)),
            ("Tilt",    DEFAULT_FORECAST_DECLINATION, 44, "tilt",    None),
            ("Azimuth", DEFAULT_FORECAST_AZIMUTH,     44, "azimuth", None),
            ("kWp",     DEFAULT_FORECAST_KWP,         44, "kwp",     None),
        ]
        for label, default, width, key, kind in _spec:
            row_solar.addWidget(QLabel(f"{label}:"))
            edit = QLineEdit(default)
            edit.setFixedWidth(width)
            if kind is not None and kind[0] == 'latlon':
                _, lo, hi = kind
                from PySide6.QtGui import QDoubleValidator
                v = QDoubleValidator(lo, hi, 5, edit)
                v.setNotation(QDoubleValidator.StandardNotation)
                edit.setValidator(v)
                edit.setToolTip(
                    f"Decimal degrees, range [{lo:g}, {hi:g}] — WGS84 (EPSG:4326). "
                    f"Up to 5 decimal places (~1.1 m at the equator)."
                )
                edit.editingFinished.connect(
                    lambda e=edit: self._on_latlon_committed(e)
                )
            self.solar_edits[key] = edit
            row_solar.addWidget(edit)
            if key == 'lon':
                crs_label = QLabel("CRS: WGS84 (EPSG:4326)")
                crs_label.setStyleSheet(
                    "color: #6c7086; font-size: 11px; padding-left: 6px;"
                )
                crs_label.setToolTip(
                    "Coordinates are stored in the World Geodetic System 1984 (WGS84) "
                    "geographic CRS — the same datum used by GPS, OpenStreetMap and "
                    "the Octopus / forecast.solar APIs."
                )
                row_solar.addWidget(crs_label)
        for _k in ("tilt", "azimuth", "kwp"):
            self.solar_edits[_k].editingFinished.connect(
                self._on_solar_numeric_committed
            )
        self.map_btn = QPushButton("Set location…")
        self.map_btn.setToolTip(
            "Open the location picker (Leaflet map when PySide6-WebEngine is "
            "installed; otherwise place search and lat/lon). "
            "Set POWERMODEL_MAP_WEBENGINE=0 to force the text-only dialog."
        )
        self.map_btn.clicked.connect(self._open_map_picker)
        row_solar.addWidget(self.map_btn)
        row_solar.addStretch()
        ctrl_vlayout.addLayout(row_solar)
        top_layout.addWidget(ctrl_box, 0)

        chart_widget = QWidget()
        chart_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        chart_layout = QVBoxLayout(chart_widget)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(2)
        self.fig = Figure(figsize=(12, 11), dpi=100)
        self.ax_price = self.fig.add_subplot(211)
        self.ax_solar = self.fig.add_subplot(212, sharex=self.ax_price)
        self.ax_price.tick_params(labelbottom=False)
        for ax in (self.ax_price, self.ax_solar):
            _style_ax_dark(ax, self.fig)
        self.fig.tight_layout(pad=3.0)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setMinimumHeight(500)
        chart_layout.addWidget(self.canvas, 1)
        toolbar = DarkNavigationToolbar(self.canvas, self)
        chart_layout.addWidget(toolbar, 0)
        self._fc_motion_cid = self.canvas.mpl_connect('motion_notify_event', self._on_forecast_motion)
        self._chart_shimmer = ChartShimmerOverlay(self.canvas)
        top_layout.addWidget(chart_widget, 1)
        splitter.addWidget(top_widget)

        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        summary_box = QGroupBox("Forecast Summary")
        # Three side-by-side text panes (Agile import / Agile export / Solar)
        # use the full width of the bottom panel instead of one tall column.
        summary_layout = QHBoxLayout(summary_box)
        summary_layout.setContentsMargins(8, 8, 8, 8)
        summary_layout.setSpacing(10)

        def _make_summary_pane(title):
            pane = QGroupBox(title)
            pane.setStyleSheet(
                f"QGroupBox {{ background: {_DARK_SURFACE_BG}; border: 1px solid #45475a; "
                "border-radius: 4px; margin-top: 10px; padding: 6px; "
                "color: #cdd6f4; font-size: 11px; }"
                "QGroupBox::title { subcontrol-origin: margin; left: 8px; "
                "padding: 0 4px; }"
            )
            pl = QVBoxLayout(pane)
            pl.setContentsMargins(6, 4, 6, 4)
            te = QTextEdit()
            te.setReadOnly(True)
            te.setFont(QFont('Helvetica', 10))
            te.setMinimumHeight(96)
            te.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            pl.addWidget(te)
            return pane, te

        imp_pane, self.summary_imp = _make_summary_pane("Agile Import (household)")
        exp_pane, self.summary_exp = _make_summary_pane("Agile Export (outgoing / offered)")
        sol_pane, self.summary_sol = _make_summary_pane("Solar Forecast (kWh / day)")
        for pane in (imp_pane, exp_pane, sol_pane):
            summary_layout.addWidget(pane, 1)
        # Backwards-compatible alias: a few callers (and our own _update_summary
        # historic path) wrote to a single `summary_text` widget. Keep the name
        # pointing at the import pane so any leftover callers don't crash; the
        # canonical path is now the three split panes.
        self.summary_text = self.summary_imp
        bottom_layout.addWidget(summary_box)
        splitter.addWidget(bottom_widget)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([820, 220])
        main_layout.addWidget(splitter, 1)
        self.fc_cursor_label = QLabel("Hover charts: time, Agile import/export (top), solar kW (bottom).")
        self.fc_cursor_label.setStyleSheet(
            "color: #cdd6f4; padding: 6px 8px; background: transparent; border: 1px solid #45475a; border-radius: 4px; font-family: monospace; font-size: 10px;"
        )
        self.fc_cursor_label.setWordWrap(True)
        self.fc_cursor_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        main_layout.addWidget(self.fc_cursor_label, 0)

    def auto_start(self):
        self.fetch_forecasts()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.fetching:
            self._refresh_forecast_history_from_db_async(replot=True)

    def _chart_days(self) -> int:
        data = self.chart_days_combo.currentData()
        if data is not None:
            return int(data)
        return _FORECAST_CHART_DAYS_DEFAULT

    def _forecast_db_time_bounds(self, chart_days=None):
        """UTC (t0, t1) for DB history: chart_days back through +2d forward."""
        import pytz
        london = pytz.timezone('Europe/London')
        now_l = datetime.now(london)
        if chart_days is None:
            chart_days = self._chart_days()
        days = max(int(chart_days), _FORECAST_CHART_DAYS_MAX)
        t0 = (now_l - timedelta(days=days)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).astimezone(timezone.utc)
        t1 = (now_l + timedelta(days=2)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).astimezone(timezone.utc)
        return t0, t1

    def _refresh_forecast_history_from_db_async(self, *, replot=False):
        """Load DB snapshots on a worker thread, then merge on the GUI thread."""
        logger = self.data_logger
        if logger is None or logger._primary_storage_backend() is None:
            if replot:
                self._plot_charts()
            return
        import_tariff = self.tariff_edit.text().strip()
        export_tariff = self.export_tariff_edit.text().strip()
        t0, t1 = self._forecast_db_time_bounds()

        def _worker():
            db_imp = pl.DataFrame()
            db_ex = pl.DataFrame()
            try:
                db_imp = logger.query_agile_prices(t0, t1, import_tariff, 'import')
            except Exception as e:
                _log.warn("Forecasts", f"Agile import DB read failed: {e}")
            try:
                db_ex = logger.query_agile_prices(t0, t1, export_tariff, 'export')
            except Exception as e:
                _log.warn("Forecasts", f"Agile export DB read failed: {e}")
            self._inv.invoke(
                lambda imp=db_imp, ex=db_ex, rp=replot: self._apply_db_forecast_history(
                    imp, ex, replot=rp,
                )
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_db_forecast_history(self, db_imp, db_ex, *, replot=False):
        """Merge DB rows into in-memory frames (main thread only)."""
        try:
            self.agile_df = _merge_agile_forecast_frames(self.agile_df, db_imp)
            self.agile_export_df = _merge_agile_forecast_frames(
                self.agile_export_df, db_ex,
            )
        except Exception as e:
            _log.warn("Forecasts", f"Agile DB merge failed: {e}")
        if replot:
            self._plot_charts()

    def _on_chart_days_changed(self, _index=None):
        try:
            QSettings("PowerModel", "EnergyDashboard2").setValue(
                _FORECAST_CHART_DAYS_SETTINGS_KEY, self._chart_days(),
            )
        except Exception:
            pass
        self._refresh_forecast_history_from_db_async(replot=True)

    def fetch_forecasts(self):
        if self.fetching:
            return
        self.fetching = True
        self.fetch_btn.setEnabled(False)
        self._chart_shimmer.start()
        self.set_status("Fetching forecasts...")
        threading.Thread(target=self._fetch_thread, daemon=True).start()

    def _fetch_thread(self):
        agile_df = pd.DataFrame()
        agile_export_df = pd.DataFrame()
        solar_df = pd.DataFrame()
        solar_msg = ""
        import_tariff = self.tariff_edit.text().strip()
        export_tariff = self.export_tariff_edit.text().strip()
        try:
            agile_df = fetch_agile_prices(
                self.product_edit.text(), import_tariff,
                days_back=_FORECAST_CHART_DAYS_MAX,
            )
        except Exception as e:
            _log.warn("Forecasts", f"Agile fetch error: {e}")
        try:
            agile_export_df = fetch_agile_standard_unit_rates(
                self.product_edit.text(), export_tariff,
                days_back=_FORECAST_CHART_DAYS_MAX,
            )
        except Exception as e:
            _log.warn("Forecasts", f"Agile export fetch error: {e}")
        solar_params = {
            'lat': self.solar_edits['lat'].text(),
            'lon': self.solar_edits['lon'].text(),
            'tilt': self.solar_edits['tilt'].text(),
            'azimuth': self.solar_edits['azimuth'].text(),
            'kwp': self.solar_edits['kwp'].text(),
        }
        try:
            solar_df, solar_msg = fetch_solar_forecast(
                solar_params['lat'], solar_params['lon'],
                solar_params['tilt'], solar_params['azimuth'],
                solar_params['kwp'])
        except Exception as e:
            solar_msg = f"Solar error: {e}"
        agile_c = _coerce_agile_frame(agile_df)
        agile_ex_c = _coerce_agile_frame(agile_export_df)
        db_imp = pl.DataFrame()
        db_ex = pl.DataFrame()
        logger = self.data_logger
        if logger is not None and logger._primary_storage_backend() is not None:
            t0, t1 = self._forecast_db_time_bounds(_FORECAST_CHART_DAYS_MAX)
            try:
                db_imp = logger.query_agile_prices(t0, t1, import_tariff, 'import')
            except Exception as e:
                _log.warn("Forecasts", f"Agile import DB read failed: {e}")
            try:
                db_ex = logger.query_agile_prices(t0, t1, export_tariff, 'export')
            except Exception as e:
                _log.warn("Forecasts", f"Agile export DB read failed: {e}")
        # Persist snapshots so we can later overlay 'planned vs actual' on
        # historical days. log_* are no-ops when no DB backend is enabled.
        if logger is not None:
            try:
                logger.log_solar_forecast(solar_df, solar_params)
            except Exception as e:
                _log.warn("Forecasts", f"Solar snapshot save failed: {e}")
            try:
                logger.log_agile_forecast(agile_c, import_tariff, 'import')
            except Exception as e:
                _log.warn("Forecasts", f"Agile import snapshot save failed: {e}")
            try:
                logger.log_agile_forecast(agile_ex_c, export_tariff, 'export')
            except Exception as e:
                _log.warn("Forecasts", f"Agile export snapshot save failed: {e}")

        self._inv.invoke(
            lambda: self._finish_fetch(
                agile_c, agile_ex_c, solar_df, solar_msg, db_imp, db_ex,
            )
        )

    def _finish_fetch(self, agile_df, agile_export_df, solar_df, solar_msg, db_imp, db_ex):
        """Apply fetch results on the GUI thread."""
        self.agile_df = agile_df
        self.agile_export_df = agile_export_df
        self.solar_df = solar_df
        self._apply_db_forecast_history(db_imp, db_ex, replot=False)
        self._update_display(solar_msg)

    def _forecasts_have_data(self) -> bool:
        """True when at least one forecast series is loaded for the charts."""
        if isinstance(self.agile_df, pl.DataFrame) and not self.agile_df.is_empty():
            return True
        if (
            isinstance(self.agile_export_df, pl.DataFrame)
            and not self.agile_export_df.is_empty()
        ):
            return True
        if self.solar_df is not None and not getattr(self.solar_df, 'empty', True):
            return True
        return False

    def _update_display(self, solar_msg):
        self._chart_shimmer.stop()
        self.fetching = False
        self.fetch_btn.setEnabled(True)
        self._solar_last_msg = solar_msg if solar_msg is not None else ""
        self._solar_last_refresh_local = datetime.now().strftime('%H:%M:%S')
        self.rate_limit_label.setText(solar_msg)
        sm = (solar_msg or "").strip()
        solar_empty = self.solar_df is None or getattr(self.solar_df, 'empty', True)
        is_error = solar_empty and bool(sm)
        if is_error:
            self.rate_limit_label.setStyleSheet("color: #f38ba8; font-size: 11px;")
        else:
            self.rate_limit_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        try:
            self._plot_charts()
            self._update_summary()
        except Exception as e:
            _log.exception("Forecasts", f"Chart update failed: {e}")
            self.set_status(f"Forecast chart error: {e}")
            # Still mark fresh when series loaded — charts may fail independently.
            if self._forecasts_have_data() and self.on_data_updated:
                self.on_data_updated()
            return
        self.set_status("Forecasts loaded.")
        # Green tab tint while Agile and/or solar data is current (same as other tabs).
        if self._forecasts_have_data() and self.on_data_updated:
            self.on_data_updated()

    def _plot_charts(self):
        import pytz
        import matplotlib.dates as mdates
        london = pytz.timezone('Europe/London')
        now = datetime.now(london)
        chart_days = self._chart_days()
        today_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
        window_start = today_local - timedelta(days=chart_days - 1)
        self._fc_plot_df = None
        self._fc_agile_xnum = None
        self._fc_solar_tnums = None
        self._fc_solar_kw = None
        self.ax_price.clear()
        self.ax_solar.clear()
        self.agile_df = _coerce_agile_frame(self.agile_df)
        self.agile_export_df = _coerce_agile_frame(self.agile_export_df)
        if self.agile_df is not None and not self.agile_df.is_empty():
            ws = window_start
            if ws.tzinfo is None:
                import pytz
                ws = pytz.timezone('Europe/London').localize(ws)
            df = (
                self.agile_df.sort('valid_from')
                .unique(subset=['valid_from'], keep='first')
                .filter(pl.col('valid_from') >= ws)
            )
            if df.is_empty():
                self.ax_price.text(
                    0.5, 0.5,
                    'No Agile data in selected day window',
                    transform=self.ax_price.transAxes,
                    ha='center', va='center', fontsize=12, color=_DARK_SUBTEXT,
                )
            else:
                bar_width = 1.0 / 48
                if self.agile_export_df is not None and not self.agile_export_df.is_empty():
                    ex = (
                        self.agile_export_df.sort('valid_from')
                        .unique(subset=['valid_from'], keep='first')
                        .select(
                            'valid_from',
                            pl.col('price_pence').alias('export_pence'),
                        )
                    )
                    plot_df = df.join_asof(
                        ex.sort('valid_from'),
                        on='valid_from',
                        strategy='nearest',
                        tolerance='45m',
                    )
                else:
                    plot_df = df.with_columns(pl.lit(None).cast(pl.Float64).alias('export_pence'))
                off = timedelta(days=bar_width * 0.22)
                vf = plot_df['valid_from'].to_list()
                x_imp = [t - off for t in vf]
                prices = plot_df['price_pence'].to_list()
                colors = [
                    '#4CAF50' if p < 10 else '#FFC107' if p < 20 else '#FF9800' if p < 30 else '#F44336'
                    for p in prices
                ]
                self.ax_price.bar(
                    x_imp, prices, width=bar_width * 0.44, color=colors,
                    align='edge', edgecolor='none', alpha=0.88, label='Import',
                )
                sub = plot_df.filter(pl.col('export_pence').is_not_null())
                if not sub.is_empty():
                    exp_colors = [
                        '#26C6DA' if p < 8 else '#4DD0E1' if p < 15 else '#80DEEA' if p < 25 else '#B2EBF2'
                        for p in sub['export_pence'].to_list()
                    ]
                    x_exp = [t + off for t in sub['valid_from'].to_list()]
                    self.ax_price.bar(
                        x_exp, sub['export_pence'].to_list(), width=bar_width * 0.44,
                        color=exp_colors, align='edge', edgecolor='none', alpha=0.9,
                        label='Export (outgoing)',
                    )
                self._fc_plot_df = plot_df
                self._fc_agile_xnum = mdates.date2num(np.asarray(vf, dtype=object))
                self.ax_price.axvline(
                    now, color='#94e2d5', linestyle='--', linewidth=1, label='Now',
                )
                # 90° "NOW" at the top of the line (reads upward, centred on it).
                self.ax_price.annotate(
                    'NOW',
                    xy=(now, 1.0),
                    xycoords=('data', 'axes fraction'),
                    xytext=(0, 4),
                    textcoords='offset points',
                    rotation=90,
                    ha='left',
                    va='center',
                    fontsize=8,
                    fontweight='bold',
                    color='#94e2d5',
                    annotation_clip=False,
                    zorder=6,
                )
                self.ax_price.set_ylabel('p/kWh')
                self.ax_price.set_title('Agile Import & Export (p/kWh inc. VAT)')
                self.ax_price.legend(
                    loc='upper right', fontsize=8, framealpha=0.85,
                    facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT,
                )
                self.ax_price.xaxis.set_major_formatter(mdates.DateFormatter('%a %H:%M', tz=london))
                self.ax_price.xaxis.set_major_locator(mdates.HourLocator(interval=4))
                self.ax_price.tick_params(axis='x', rotation=30, colors=_DARK_TEXT)
                self.ax_price.grid(axis='y', color=_DARK_GRID, linewidth=0.4, alpha=0.65)
        else:
            self.ax_price.text(
                0.5, 0.5, 'No Agile price data', transform=self.ax_price.transAxes,
                ha='center', va='center', fontsize=12, color=_DARK_SUBTEXT,
            )
        _SOLAR_FILL = '#a05a2c'
        _FC_LEGEND = dict(
            loc='upper right', fontsize=8, framealpha=0.85,
            facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT,
        )
        main_tnums = None
        main_kw = None
        if self.solar_df is not None and not self.solar_df.empty:
            sdf = self.solar_df.copy()
            t_london = pd.to_datetime(sdf['timestamp'], utc=True).dt.tz_convert(london)
            mask_fc = t_london >= today_local
            if mask_fc.any():
                fc = sdf.loc[mask_fc].copy()
                ts_fc = t_london.loc[mask_fc].to_numpy()
                self.ax_solar.fill_between(
                    ts_fc, fc['kW'],
                    color=_SOLAR_FILL, alpha=0.5, zorder=2,
                )
                self.ax_solar.plot(
                    ts_fc, fc['kW'], color='#fab387', linewidth=1.5,
                    label='Forecast (model)', zorder=3,
                )
                main_tnums = mdates.date2num(ts_fc)
                main_kw = fc['kW'].to_numpy(dtype=float)
            self.ax_solar.xaxis.set_major_formatter(mdates.DateFormatter('%a %H:%M', tz=london))
            self.ax_solar.xaxis.set_major_locator(mdates.HourLocator(interval=4))
            self.ax_solar.tick_params(axis='x', rotation=30, colors=_DARK_TEXT)
            self.ax_solar.grid(axis='y', color=_DARK_GRID, linewidth=0.4, alpha=0.65)
        else:
            self.ax_solar.text(
                0.5, 0.5, 'No solar forecast data', transform=self.ax_solar.transAxes,
                ha='center', va='center', fontsize=12, color=_DARK_SUBTEXT,
            )
        self.ax_solar.set_ylabel('kW')
        self.ax_solar.set_title(
            f'Solar — measured + planned history ({chart_days}d) & forecast'
        )
        hist_tnums, hist_kw = self._draw_solar_measured_history(
            london, now, chart_days, _SOLAR_FILL,
        )
        self._draw_solar_planned_history(london, now, chart_days)
        self.ax_solar.axvline(
            now, color='#94e2d5', linestyle='--', linewidth=1, label='Now', zorder=5,
        )
        if main_tnums is not None and len(main_tnums) > 0:
            if hist_tnums is not None and len(hist_tnums) > 0:
                comb_t = np.concatenate([hist_tnums, main_tnums])
                comb_kw = np.concatenate([hist_kw, main_kw])
                order = np.argsort(comb_t)
                self._fc_solar_tnums = comb_t[order]
                self._fc_solar_kw = comb_kw[order]
            else:
                self._fc_solar_tnums = main_tnums
                self._fc_solar_kw = main_kw
        elif hist_tnums is not None and len(hist_tnums) > 0:
            self._fc_solar_tnums = hist_tnums
            self._fc_solar_kw = hist_kw
        else:
            self._fc_solar_tnums = None
            self._fc_solar_kw = None
        sol_handles, _ = self.ax_solar.get_legend_handles_labels()
        if sol_handles:
            self.ax_solar.legend(**_FC_LEGEND)
        # Clip both panels to the selected day window (history + forward forecast).
        x_start_num = float(mdates.date2num(window_start))
        x_candidates = [x_start_num]
        if self._fc_agile_xnum is not None and len(self._fc_agile_xnum) > 0:
            x_candidates.append(float(self._fc_agile_xnum.max()))
        if self._fc_solar_tnums is not None and len(self._fc_solar_tnums) > 0:
            x_candidates.append(float(self._fc_solar_tnums.max()))
        x_end_num = max(x_candidates)
        if x_end_num <= x_start_num:
            x_end_num = float(mdates.date2num(now + timedelta(days=2)))
        self.ax_price.set_xlim(x_start_num, x_end_num)
        self.ax_solar.set_xlim(x_start_num, x_end_num)
        _draw_history_future_shading(self.ax_price, now)
        _draw_history_future_shading(self.ax_solar, now)
        _draw_6h_vertical_grid(self.ax_price, london, force_intraday_secondary=True)
        _draw_6h_vertical_grid(self.ax_solar, london, force_intraday_secondary=True)
        _draw_day_date_labels(self.ax_price, london, anchor='top')
        solar_label_band = _draw_day_date_labels(
            self.ax_solar, london, anchor='bottom',
        )
        hist_totals = self._historical_day_energy_totals(london, window_start, now)
        hist_band = _draw_historical_day_energy_totals(
            self.ax_solar,
            hist_totals,
            anchor='top',
        )
        self._add_forecast_day_markers(
            london, window_start,
            label_band_px=solar_label_band,
            totals_band_px=0,
        )
        x0 = mdates.date2num(now)
        self._fc_vline_price = self.ax_price.axvline(
            x0, color='#94e2d5', lw=1.05, alpha=0.92, visible=False, zorder=50)
        self._fc_hline_price = self.ax_price.axhline(
            0, color='#94e2d5', lw=1.0, alpha=0.88, visible=False, zorder=49)
        self._fc_vline_solar = self.ax_solar.axvline(
            x0, color='#94e2d5', lw=1.05, alpha=0.92, visible=False, zorder=50)
        self._fc_hline_solar = self.ax_solar.axhline(
            0, color='#94e2d5', lw=1.0, alpha=0.88, visible=False, zorder=49)
        self.ax_price.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
            xv, yv, tz, "p/kWh",
            "Agile unit rate for that half-hour — coloured bars are import vs export prices",
        )
        self.ax_solar.format_coord = lambda xv, yv, tz=london: _fmt_toolbar_time_y(
            xv, yv, tz, "kW",
            "modelled solar AC output (forecast + measured / overlay traces)",
        )
        for ax in (self.ax_price, self.ax_solar):
            _style_ax_dark(ax, self.fig)
        fig_h_px = max(self.fig.get_figheight() * self.fig.dpi, 400)
        bottom_px = 52 + solar_label_band
        bottom_frac = min(0.28, max(0.12, bottom_px / fig_h_px))
        top_frac = 0.96
        if hist_band:
            top_frac = max(0.82, 0.96 - hist_band / fig_h_px)
        self.fig.subplots_adjust(
            left=0.07, right=0.98, top=top_frac, bottom=bottom_frac, hspace=0.30,
        )
        self.canvas.draw()

    def _hide_forecast_cursor(self):
        if not getattr(self, '_fc_vline_price', None):
            return
        self._fc_vline_price.set_visible(False)
        self._fc_hline_price.set_visible(False)
        self._fc_vline_solar.set_visible(False)
        self._fc_hline_solar.set_visible(False)
        self.fc_cursor_label.setText(
            "Hover charts: time, Agile import/export (top), solar kW (bottom)."
        )
        self.canvas.draw_idle()

    def _smooth_growatt_pv_window(self, start_ts_utc, end_ts_utc):
        """Return ``(t_london_numpy, smoothed_kw)`` for Growatt PV in
        ``[start_ts_utc, end_ts_utc)`` (UTC). ``None, None`` if no logger / no
        rows. Uses the same 5-minute resample + 3-bin rolling mean as today's
        actual overlay."""
        if self.data_logger is None:
            return None, None
        start_utc = pd.Timestamp(start_ts_utc).tz_convert('UTC')
        end_utc = pd.Timestamp(end_ts_utc).tz_convert('UTC')
        if end_utc <= start_utc:
            return None, None
        try:
            actual = self.data_logger.query_growatt_pv_actual(start_utc, end_utc)
        except Exception as e:
            _log.warn("Forecasts", f"Growatt PV window query failed: {e}")
            return None, None
        if actual is None or actual.is_empty():
            return None, None
        ts = (
            actual.sort('timestamp')
            .group_by_dynamic('timestamp', every='5m')
            .agg(pl.col('pv_kw').mean())
            .drop_nulls()
        )
        if ts.is_empty():
            return None, None
        smoothed = ts.with_columns(
            pl.col('pv_kw')
            .rolling_mean(window_size=3, min_samples=1, center=True)
            .alias('pv_kw'),
        )
        import pytz
        london = pytz.timezone('Europe/London')
        t_loc = (
            smoothed['timestamp']
            .dt.convert_time_zone('Europe/London')
            .to_numpy()
        )
        y = smoothed['pv_kw'].to_numpy()
        return t_loc, y

    def _draw_solar_measured_history(self, london, now_london, days_back, fill_color):
        """Measured PV (Growatt) for each day in the chart window up to now.

        Returns merged (mdates nums, kw) for hover interpolation, or (None, None).
        """
        import matplotlib.dates as mdates
        today_local = now_london.replace(hour=0, minute=0, second=0, microsecond=0)
        all_nums = []
        all_kw = []
        labelled = False
        for day_offset in range(days_back - 1, -1, -1):
            day_start = today_local - timedelta(days=day_offset)
            if day_offset == 0:
                end_local = now_london
            else:
                end_local = day_start + timedelta(days=1)
            t_loc, y = self._smooth_growatt_pv_window(
                day_start.astimezone(timezone.utc),
                end_local.astimezone(timezone.utc),
            )
            if t_loc is None or len(y) < 2:
                continue
            lbl = None if labelled else 'Measured (Growatt)'
            labelled = True
            self.ax_solar.fill_between(
                t_loc, y, color=fill_color, alpha=0.45, zorder=2.1,
            )
            self.ax_solar.plot(
                t_loc, y, color='#89dceb', linewidth=1.5, alpha=0.95,
                label=lbl, zorder=3.5,
            )
            nums = mdates.date2num(t_loc)
            all_nums.append(nums)
            all_kw.append(y.astype(float))
        if not all_nums:
            return None, None
        comb_t = np.concatenate(all_nums)
        comb_kw = np.concatenate(all_kw)
        order = np.argsort(comb_t)
        return comb_t[order], comb_kw[order]

    def _draw_solar_planned_history(self, london, now_london, days_back):
        """Stored solar forecast snapshots for past days in the chart window."""
        if self.data_logger is None:
            return
        today_local = now_london.replace(hour=0, minute=0, second=0, microsecond=0)
        labelled = False
        for day_offset in range(1, days_back):
            day_start = today_local - timedelta(days=day_offset)
            day_end = day_start + timedelta(days=1)
            before_utc = day_end.astimezone(timezone.utc)
            try:
                planned = self.data_logger.query_solar_forecast_snapshot(
                    day_start.astimezone(timezone.utc),
                    day_end.astimezone(timezone.utc),
                    before_utc=before_utc,
                )
            except Exception as e:
                _log.warn("Forecasts", f"Snapshot query failed: {e}")
                continue
            if planned.is_empty():
                continue
            t_loc = (
                planned['interval_start']
                .dt.convert_time_zone('Europe/London')
                .to_numpy()
            )
            lbl = None if labelled else 'Planned (saved forecast)'
            labelled = True
            self.ax_solar.plot(
                t_loc, planned['kw'],
                color='#cba6f7', linewidth=1.2, linestyle='--',
                alpha=0.8, label=lbl, zorder=3.2,
            )

    def _forecast_lookup_agile(self, xnum):
        df = getattr(self, '_fc_plot_df', None)
        nums = getattr(self, '_fc_agile_xnum', None)
        if df is None or nums is None or len(nums) == 0:
            return None, None, "no Agile data"
        i = int(np.abs(nums - xnum).argmin())
        row = df.row(i, named=True)
        imp = float(row['price_pence'])
        ex = row.get('export_pence')
        exp = float(ex) if ex is not None and ex == ex else None
        return imp, exp, ""

    def _forecast_lookup_solar(self, xnum):
        tn = getattr(self, '_fc_solar_tnums', None)
        kw = getattr(self, '_fc_solar_kw', None)
        if tn is None or kw is None or len(tn) < 2:
            return float('nan'), "no solar data"
        if xnum < float(tn[0]) or xnum > float(tn[-1]):
            return float('nan'), "outside solar forecast"
        return float(np.interp(xnum, tn, kw)), ""

    def _on_forecast_motion(self, event):
        import matplotlib.dates as mdates
        import pytz
        if not getattr(self, '_fc_vline_price', None):
            return
        if event.inaxes not in (self.ax_price, self.ax_solar) or event.xdata is None:
            self._hide_forecast_cursor()
            return
        x = float(event.xdata)
        self._fc_vline_price.set_xdata([x, x])
        self._fc_vline_solar.set_xdata([x, x])
        self._fc_vline_price.set_visible(True)
        self._fc_vline_solar.set_visible(True)

        if event.inaxes == self.ax_price and event.ydata is not None:
            y = float(event.ydata)
            self._fc_hline_price.set_ydata([y, y])
            self._fc_hline_price.set_visible(True)
            self._fc_hline_solar.set_visible(False)
        elif event.inaxes == self.ax_solar and event.ydata is not None:
            y = float(event.ydata)
            self._fc_hline_solar.set_ydata([y, y])
            self._fc_hline_solar.set_visible(True)
            self._fc_hline_price.set_visible(False)
        else:
            self._fc_hline_price.set_visible(False)
            self._fc_hline_solar.set_visible(False)

        london = pytz.timezone('Europe/London')
        dt = mdates.num2date(x)
        ts = pd.Timestamp(dt)
        if ts.tzinfo is None:
            t = ts.tz_localize('UTC').tz_convert(london)
        else:
            t = ts.tz_convert(london)
        ts_str = t.strftime('%a %d %H:%M')

        imp, exp, ag_msg = self._forecast_lookup_agile(x)
        skw, sol_msg = self._forecast_lookup_solar(x)

        parts = [ts_str]
        if imp is not None:
            parts.append(f"Import {imp:.1f} p/kWh")
        if exp is not None:
            parts.append(f"Export {exp:.1f} p/kWh")
        if imp is None and exp is None and ag_msg:
            parts.append(ag_msg)
        if not np.isnan(skw):
            parts.append(f"Solar {skw:.2f} kW")
        elif sol_msg:
            parts.append(sol_msg)
        self.fc_cursor_label.setText("  |  ".join(parts))
        self.canvas.draw_idle()

    def _forecast_solar_daily_kwh_entries(self, london, window_start):
        """List of (matplotlib date num at 12:00 London, kWh trapezoid) per calendar day."""
        import matplotlib.dates as mdates
        trap = getattr(np, 'trapezoid', None)
        out = []
        days_in_fc = set()
        if self.solar_df is not None and not self.solar_df.empty:
            sdf = self.solar_df.copy()
            sdf['_ts'] = pd.to_datetime(sdf['timestamp'], utc=True).dt.tz_convert(london)
            for day_date in sorted(sdf['_ts'].dt.date.unique()):
                days_in_fc.add(day_date)
                if pd.Timestamp(day_date, tz=london) < window_start:
                    continue
                day_df = sdf[sdf['_ts'].dt.date == day_date].sort_values('_ts')
                if day_df.empty:
                    continue
                if len(day_df) >= 2:
                    h = (day_df['_ts'] - day_df['_ts'].iloc[0]).dt.total_seconds() / 3600.0
                    kwv = day_df['kW'].to_numpy(dtype=float)
                    kwh = (
                        float(trap(kwv, h.to_numpy()))
                        if trap is not None
                        else float(np.trapz(kwv, h.to_numpy()))
                    )
                else:
                    kwh = 0.0
                noon = pd.Timestamp(
                    year=day_date.year,
                    month=day_date.month,
                    day=day_date.day,
                    hour=12,
                    minute=0,
                    second=0,
                    tz=london,
                )
                noon_num = float(mdates.date2num(noon.to_pydatetime()))
                out.append((noon_num, kwh))

        now = datetime.now(london)
        yesterday_date = now.date() - timedelta(days=1)
        if yesterday_date not in days_in_fc:
            y0 = datetime.combine(yesterday_date, time.min, tzinfo=london)
            y1 = datetime.combine(now.date(), time.min, tzinfo=london)
            t_loc, y = self._smooth_growatt_pv_window(
                pd.Timestamp(y0).tz_convert(timezone.utc),
                pd.Timestamp(y1).tz_convert(timezone.utc),
            )
            if t_loc is not None and len(y) >= 2:
                ts_num = mdates.date2num(t_loc)
                h_hours = (ts_num - ts_num[0]) * 24.0
                kwh = (
                    float(trap(y, h_hours))
                    if trap is not None
                    else float(np.trapz(y, h_hours))
                )
                noon = pd.Timestamp(
                    year=yesterday_date.year,
                    month=yesterday_date.month,
                    day=yesterday_date.day,
                    hour=12,
                    minute=0,
                    second=0,
                    tz=london,
                )
                noon_num = float(mdates.date2num(noon.to_pydatetime()))
                out.append((noon_num, kwh))
        out.sort(key=lambda z: z[0])
        return out

    def _solar_forecast_kwh_for_day(self, london, day_start):
        """Forecast / planned solar kWh for one London calendar day, or None."""
        import matplotlib.dates as mdates
        trap = getattr(np, 'trapezoid', None)
        day_date = day_start.date() if hasattr(day_start, 'date') else day_start
        day0 = datetime.combine(day_date, time.min, tzinfo=london)
        day1 = day0 + timedelta(days=1)

        # Prefer the live model curve when it covers this day.
        if self.solar_df is not None and not self.solar_df.empty:
            sdf = self.solar_df.copy()
            sdf['_ts'] = pd.to_datetime(sdf['timestamp'], utc=True).dt.tz_convert(london)
            day_df = sdf[sdf['_ts'].dt.date == day_date].sort_values('_ts')
            if len(day_df) >= 2:
                h = (day_df['_ts'] - day_df['_ts'].iloc[0]).dt.total_seconds() / 3600.0
                kwv = day_df['kW'].to_numpy(dtype=float)
                return (
                    float(trap(kwv, h.to_numpy()))
                    if trap is not None
                    else float(np.trapz(kwv, h.to_numpy()))
                )

        # Past days: integrate the DB-saved planned forecast snapshot.
        if self.data_logger is None:
            return None
        try:
            planned = self.data_logger.query_solar_forecast_snapshot(
                day0.astimezone(timezone.utc),
                day1.astimezone(timezone.utc),
                before_utc=day1.astimezone(timezone.utc),
            )
        except Exception as e:
            _log.warn("Forecasts", f"Snapshot query failed: {e}")
            return None
        if planned.is_empty() or planned.height < 2:
            return None
        t_num = mdates.date2num(
            planned['interval_start']
            .dt.convert_time_zone('Europe/London')
            .to_numpy()
        )
        h_hours = (t_num - t_num[0]) * 24.0
        # Polars Series.to_numpy() has no dtype= kwarg (unlike pandas).
        kw = planned['kw'].cast(pl.Float64).to_numpy()
        return (
            float(trap(kw, h_hours))
            if trap is not None
            else float(np.trapz(kw, h_hours))
        )

    def _historical_day_energy_totals(self, london, window_start, now_london):
        """Daily used / generated / imported / forecast kWh for past days."""
        import matplotlib.dates as mdates
        today_local = now_london.replace(hour=0, minute=0, second=0, microsecond=0)
        day = pd.Timestamp(window_start).replace(hour=0, minute=0, second=0, microsecond=0)
        if day.tzinfo is None:
            day = day.tz_localize(london)
        else:
            day = day.tz_convert(london)

        flows = None
        if self.data_logger is not None:
            start_utc = pd.Timestamp(window_start).tz_convert(timezone.utc)
            end_utc = pd.Timestamp(now_london).tz_convert(timezone.utc)
            if end_utc > start_utc:
                try:
                    flows = self.data_logger.query_growatt_power_flows(start_utc, end_utc)
                except Exception as e:
                    _log.warn("Forecasts", f"Growatt flows query failed: {e}")
                    flows = None
        if flows is not None and not flows.is_empty():
            df = flows.with_columns(
                pl.col('timestamp').dt.convert_time_zone('Europe/London').alias('_ts_local'),
                pl.col('pv_kw').fill_null(0.0),
                pl.col('load_kw').fill_null(0.0),
                pl.col('grid_power_kw').fill_null(0.0),
            )
        else:
            df = None

        trap = getattr(np, 'trapezoid', None)
        entries = []
        while day <= today_local:
            day_end = now_london if day == today_local else day + timedelta(days=1)
            # Polars compares cleanly against timezone-aware Python datetimes.
            day_py = day.to_pydatetime() if hasattr(day, 'to_pydatetime') else day
            end_py = (
                day_end.to_pydatetime()
                if hasattr(day_end, 'to_pydatetime')
                else day_end
            )
            totals = {}
            if df is not None:
                try:
                    sub = df.filter(
                        (pl.col('_ts_local') >= day_py)
                        & (pl.col('_ts_local') < end_py),
                    )
                except Exception as e:
                    _log.warn("Forecasts", f"Day totals filter failed: {e}")
                    sub = None
                if sub is not None and sub.height >= 2:
                    t_loc = sub['_ts_local'].to_numpy()
                    pv = sub['pv_kw'].to_numpy()
                    load = sub['load_kw'].to_numpy()
                    import_kw = np.maximum(-sub['grid_power_kw'].to_numpy(), 0.0)
                    nums = mdates.date2num(t_loc)
                    h_hours = (nums - nums[0]) * 24.0
                    if trap is not None:
                        totals['generated'] = float(trap(pv, h_hours))
                        totals['used'] = float(trap(load, h_hours))
                        totals['imported'] = float(trap(import_kw, h_hours))
                    else:
                        totals['generated'] = float(np.trapz(pv, h_hours))
                        totals['used'] = float(np.trapz(load, h_hours))
                        totals['imported'] = float(np.trapz(import_kw, h_hours))
            try:
                fc = self._solar_forecast_kwh_for_day(london, day)
            except Exception as e:
                _log.warn("Forecasts", f"Day forecast kWh failed: {e}")
                fc = None
            if fc is not None:
                totals['forecast'] = fc
            if totals:
                xn = float(mdates.date2num(day_py))
                entries.append((xn, totals))
            day += timedelta(days=1)
        return entries

    def _add_forecast_day_markers(
        self, london, window_start, *, label_band_px=0, totals_band_px=0,
    ):
        """Per-day forecast solar kWh badges below date labels and hist totals."""
        kwh_entries = self._forecast_solar_daily_kwh_entries(london, window_start)
        if not kwh_entries:
            return
        base_y = 6 + label_band_px + totals_band_px + 4
        for noon_num, kwh in kwh_entries:
            self.ax_solar.annotate(
                f"{kwh:.1f} kWh/d",
                xy=(noon_num, 0.0),
                xycoords=('data', 'axes fraction'),
                xytext=(0, -(base_y)),
                textcoords='offset pixels',
                ha='center',
                va='top',
                fontsize=9,
                color='#1e1e2e',
                zorder=25,
                clip_on=False,
                bbox=dict(
                    boxstyle='round,pad=0.35',
                    facecolor='#f9e2af',
                    edgecolor='#fab387',
                    linewidth=0.6,
                    alpha=0.95,
                ),
            )

    def _update_summary(self):
        import pytz
        london = pytz.timezone('Europe/London')
        now = datetime.now(london)
        today = now.date()
        tomorrow = today + timedelta(days=1)

        # ── Agile import pane ─────────────────────────────────────────────
        imp_lines = []
        if self.agile_df is not None and not self.agile_df.is_empty():
            df = self.agile_df
            for day_label, day_date in [("Today", today), ("Tomorrow", tomorrow)]:
                day_df = df.filter(pl.col('valid_from').dt.date() == day_date)
                if day_df.is_empty():
                    imp_lines.append(f"{day_label}: no data available")
                    continue
                prices = day_df['price_pence']
                cheapest_row = day_df.filter(
                    pl.col('price_pence') == prices.min(),
                ).row(0, named=True)
                cheapest_time = cheapest_row['valid_from'].strftime('%H:%M')
                imp_lines.append(
                    f"{day_label}: min {prices.min():.1f}p | max {prices.max():.1f}p | "
                    f"avg {prices.mean():.1f}p | cheapest {cheapest_time}"
                )
            if len(df) >= 4:
                future = df.filter(pl.col('valid_from') >= now).sort('valid_from')
                if len(future) >= 4:
                    roll = future.with_columns(
                        pl.col('price_pence').rolling_mean(window_size=4).alias('_avg'),
                    ).filter(pl.col('_avg').is_not_null())
                    if not roll.is_empty():
                        best = roll.sort('_avg').row(0, named=True)
                        end_ts = best['valid_from']
                        window = future.filter(
                            (pl.col('valid_from') >= end_ts - timedelta(minutes=90))
                            & (pl.col('valid_from') <= end_ts),
                        ).sort('valid_from')
                        if len(window) >= 1:
                            w0 = window.row(0, named=True)
                            w1 = window.row(-1, named=True)
                            imp_lines.append("")
                            imp_lines.append(
                                f"Best 2hr window: "
                                f"{w0['valid_from'].strftime('%a %H:%M')}–"
                                f"{w1['valid_to'].strftime('%H:%M')} "
                                f"(avg {window['price_pence'].mean():.1f} p/kWh)"
                            )
        else:
            imp_lines.append("No data")
        self.summary_imp.setPlainText('\n'.join(imp_lines))

        # ── Agile export pane ─────────────────────────────────────────────
        exp_lines = []
        if self.agile_export_df is not None and not self.agile_export_df.is_empty():
            edf = self.agile_export_df
            for day_label, day_date in [("Today", today), ("Tomorrow", tomorrow)]:
                day_df = edf.filter(pl.col('valid_from').dt.date() == day_date)
                if day_df.is_empty():
                    exp_lines.append(f"{day_label}: no data")
                    continue
                ep = day_df['price_pence']
                best_row = day_df.filter(
                    pl.col('price_pence') == ep.max(),
                ).row(0, named=True)
                best_time = best_row['valid_from'].strftime('%H:%M')
                exp_lines.append(
                    f"{day_label}: min {ep.min():.1f}p | max {ep.max():.1f}p | "
                    f"avg {ep.mean():.1f}p | best {best_time}"
                )
            if len(edf) >= 4:
                fut = edf.filter(pl.col('valid_from') >= now).sort('valid_from')
                if len(fut) >= 4:
                    roll = fut.with_columns(
                        pl.col('price_pence').rolling_mean(window_size=4).alias('_avg'),
                    ).filter(pl.col('_avg').is_not_null())
                    if not roll.is_empty():
                        best = roll.sort('_avg', descending=True).row(0, named=True)
                        end_ts = best['valid_from']
                        window = fut.filter(
                            (pl.col('valid_from') >= end_ts - timedelta(minutes=90))
                            & (pl.col('valid_from') <= end_ts),
                        ).sort('valid_from')
                        if len(window) >= 1:
                            w0 = window.row(0, named=True)
                            w1 = window.row(-1, named=True)
                            exp_lines.append("")
                            exp_lines.append(
                                f"Best 2hr export window: "
                                f"{w0['valid_from'].strftime('%a %H:%M')}–"
                                f"{w1['valid_to'].strftime('%H:%M')} "
                                f"(avg {window['price_pence'].mean():.1f} p/kWh)"
                            )
        else:
            exp_lines.append("No export tariff data")
        self.summary_exp.setPlainText('\n'.join(exp_lines))

        # ── Solar forecast pane ───────────────────────────────────────────
        sol_lines = []
        yesterday = today - timedelta(days=1)
        y0 = datetime.combine(yesterday, time.min, tzinfo=london)
        y1 = datetime.combine(today, time.min, tzinfo=london)
        t_loc, y_meas = self._smooth_growatt_pv_window(
            pd.Timestamp(y0).tz_convert(timezone.utc),
            pd.Timestamp(y1).tz_convert(timezone.utc),
        )
        y_summary_line = None
        if t_loc is not None and len(y_meas) >= 2:
            import matplotlib.dates as mdates
            ts_num = mdates.date2num(t_loc)
            h_hours = (ts_num - ts_num[0]) * 24.0
            trap = getattr(np, 'trapezoid', None)
            kwh_y = (
                float(trap(y_meas, h_hours))
                if trap is not None
                else float(np.trapz(y_meas, h_hours))
            )
            peak_idx = int(np.argmax(y_meas))
            peak_kw = float(y_meas[peak_idx])
            peak_pt = pd.Timestamp(t_loc[peak_idx])
            if peak_pt.tzinfo is None:
                peak_pt = peak_pt.tz_localize('UTC')
            peak_time = peak_pt.tz_convert(london).strftime('%H:%M')
            y_summary_line = (
                f"{yesterday.strftime('%a %d %b')} (yesterday, measured): "
                f"{kwh_y:.2f} kWh  |  peak {peak_kw:.2f} kW @ {peak_time}"
            )

        has_fc = self.solar_df is not None and not self.solar_df.empty
        if not has_fc and y_summary_line is None:
            sol_lines.append("No solar forecast data")
            self.summary_sol.setPlainText('\n'.join(sol_lines))
        else:
            if has_fc:
                sol_lines.append("Expected kWh per day (∫ kW dt, trapezoidal)")
            else:
                sol_lines.append(
                    "Yesterday: measured PV only (no forecast curve loaded)."
                )
            sol_lines.append("")
            if y_summary_line is not None:
                sol_lines.append(y_summary_line)
                sol_lines.append("")
            if has_fc:
                sdf = self.solar_df.copy()
                sdf['_ts'] = pd.to_datetime(sdf['timestamp'], utc=True).dt.tz_convert(london)
                for day_date in sorted(sdf['_ts'].dt.date.unique()):
                    if day_date == yesterday and y_summary_line is not None:
                        continue
                    day_df = sdf[sdf['_ts'].dt.date == day_date].sort_values('_ts')
                    if day_df.empty:
                        continue
                    if len(day_df) >= 2:
                        h = (day_df['_ts'] - day_df['_ts'].iloc[0]).dt.total_seconds() / 3600.0
                        kwv = day_df['kW'].to_numpy(dtype=float)
                        trap = getattr(np, 'trapezoid', None)
                        kwh = (
                            float(trap(kwv, h.to_numpy()))
                            if trap is not None
                            else float(np.trapz(kwv, h.to_numpy()))
                        )
                    else:
                        kwh = 0.0
                    day_word = ""
                    if day_date == today:
                        day_word = " (today)"
                    elif day_date == tomorrow:
                        day_word = " (tomorrow)"
                    day_title = day_date.strftime('%a %d %b') + day_word
                    peak_kw = float(day_df['kW'].max())
                    pti = day_df['kW'].idxmax()
                    peak_time = day_df.loc[pti, '_ts'].strftime('%H:%M')
                    sol_lines.append(
                        f"{day_title}: {kwh:.2f} kWh  |  peak {peak_kw:.2f} kW @ {peak_time}"
                    )
            self.summary_sol.setPlainText('\n'.join(sol_lines))

    # ── Lat/Lon helpers ──────────────────────────────────────────────────

    @staticmethod
    def _format_latlon_field(edit):
        """Reformat a Lat/Lon QLineEdit to 5 decimal places (DECIMAL(10,5))."""
        s = edit.text().strip()
        if not s:
            return
        try:
            v = float(s)
        except ValueError:
            return
        edit.setText(f"{v:.5f}")

    def _on_latlon_committed(self, edit):
        """Wired to editingFinished on Lat/Lon edits — snap to 5 dp, persist
        to QSettings (so the value survives a restart), then kick off a
        reverse-geocode so the Locale label stays in sync."""
        self._format_latlon_field(edit)
        self._persist_solar_params(announce=True)
        self._refresh_locale_label()

    def _on_solar_numeric_committed(self):
        """Tilt / Azimuth / kWp: persist to disk when the user leaves the field
        without flooding the status bar (same idea as lat/lon, quieter UX)."""
        self._persist_solar_params(announce=False)

    def _save_forecast_parameters_clicked(self):
        """Explicit save: normalise lat/lon, write all solar fields, confirm in status."""
        self._format_latlon_field(self.solar_edits["lat"])
        self._format_latlon_field(self.solar_edits["lon"])
        self._persist_solar_params(announce=True)
        self._refresh_locale_label()

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist_solar_params(self, announce=True):
        """Write the current Lat/Lon/Tilt/Azimuth/kWp values to QSettings
        under the same `params/solar_*` keys that the Setup & Info tab uses,
        so the two tabs share a single source of truth on disk. Also mirrors
        the values into the live AppParameters object when one is reachable
        via the parent dashboard, so any in-session reads see fresh data.

        When ``announce`` is true, also updates the dashboard status bar so the
        user can see saves fire; tilt/azimuth/kWp field commits use
        ``announce=False`` to avoid spamming. Logging still records every write."""
        try:
            s = QSettings("PowerModel", "EnergyDashboard2")
            mapping = {
                "params/solar_lat":     self.solar_edits['lat'].text().strip(),
                "params/solar_lon":     self.solar_edits['lon'].text().strip(),
                "params/solar_tilt":    self.solar_edits['tilt'].text().strip(),
                "params/solar_azimuth": self.solar_edits['azimuth'].text().strip(),
                "params/solar_kwp":     self.solar_edits['kwp'].text().strip(),
            }
            written = {}
            for k, v in mapping.items():
                if v != "":
                    s.setValue(k, v)
                    written[k] = v
            s.sync()
            try:
                _log.info(
                    f"ForecastsTab: persisted solar params to QSettings "
                    f"(lat={mapping['params/solar_lat']}, "
                    f"lon={mapping['params/solar_lon']}, "
                    f"tilt={mapping['params/solar_tilt']}, "
                    f"azimuth={mapping['params/solar_azimuth']}, "
                    f"kwp={mapping['params/solar_kwp']}, "
                    f"file={s.fileName()})"
                )
            except Exception:
                pass
            # Best-effort sync into AppParameters / Setup & Info edits so the
            # rest of the running app reflects the change immediately.
            dash = self._find_dashboard()
            if dash is not None:
                p = getattr(dash, 'app_params', None)
                if p is not None:
                    p.solar_lat     = mapping["params/solar_lat"]     or p.solar_lat
                    p.solar_lon     = mapping["params/solar_lon"]     or p.solar_lon
                    p.solar_tilt    = mapping["params/solar_tilt"]    or p.solar_tilt
                    p.solar_azimuth = mapping["params/solar_azimuth"] or p.solar_azimuth
                    p.solar_kwp     = mapping["params/solar_kwp"]     or p.solar_kwp
                params_tab = getattr(dash, 'parameters_tab', None)
                if params_tab is not None:
                    for attr, key in (
                        ('ed_lat',     'lat'),
                        ('ed_lon',     'lon'),
                        ('ed_tilt',    'tilt'),
                        ('ed_azimuth', 'azimuth'),
                        ('ed_kwp',     'kwp'),
                    ):
                        w = getattr(params_tab, attr, None)
                        if w is not None:
                            w.setText(self.solar_edits[key].text())
                # Surface in the status bar when requested (lat/lon commit, map
                # picker, or explicit Save — not every tilt/azimuth/kWp blur).
                try:
                    if announce and hasattr(dash, 'set_status'):
                        dash.set_status(
                            f"Saved location: {mapping['params/solar_lat']}, "
                            f"{mapping['params/solar_lon']} "
                            f"({mapping['params/solar_kwp']} kWp, "
                            f"tilt {mapping['params/solar_tilt']}°, "
                            f"az {mapping['params/solar_azimuth']}°)"
                        )
                except Exception:
                    pass
        except Exception as e:
            try:
                _log.warn(f"ForecastsTab: failed to persist solar params: {e}")
            except Exception:
                pass

    def _load_saved_solar_params(self):
        """Repopulate the Lat/Lon/Tilt/Azimuth/kWp inputs from QSettings on
        startup, so a location chosen via the map picker (or typed directly)
        in a previous session is restored automatically."""
        try:
            s = QSettings("PowerModel", "EnergyDashboard2")
            for skey, ekey in (
                ("params/solar_lat",     'lat'),
                ("params/solar_lon",     'lon'),
                ("params/solar_tilt",    'tilt'),
                ("params/solar_azimuth", 'azimuth'),
                ("params/solar_kwp",     'kwp'),
            ):
                if s.contains(skey):
                    val = s.value(skey, "")
                    if val is None:
                        continue
                    val = str(val).strip()
                    if val:
                        self.solar_edits[ekey].setText(val)
        except Exception as e:
            try:
                _log.warn(f"ForecastsTab: failed to load saved solar params: {e}")
            except Exception:
                pass

    def _load_saved_chart_days(self):
        """Restore the chart day-window combo from QSettings."""
        try:
            s = QSettings("PowerModel", "EnergyDashboard2")
            if not s.contains(_FORECAST_CHART_DAYS_SETTINGS_KEY):
                return
            val = int(s.value(_FORECAST_CHART_DAYS_SETTINGS_KEY, _FORECAST_CHART_DAYS_DEFAULT))
            val = max(1, min(_FORECAST_CHART_DAYS_MAX, val))
            self.chart_days_combo.blockSignals(True)
            self.chart_days_combo.setCurrentIndex(val - 1)
            self.chart_days_combo.blockSignals(False)
        except Exception as e:
            try:
                _log.warn(f"ForecastsTab: failed to load saved chart days: {e}")
            except Exception:
                pass

    def _find_dashboard(self):
        """Walk up the parent chain to find the EnergyDashboard host."""
        w = self.parent()
        while w is not None:
            if hasattr(w, 'app_params') and hasattr(w, 'parameters_tab'):
                return w
            w = w.parent() if hasattr(w, 'parent') else None
        return None

    # ── Locale (reverse geocode) ─────────────────────────────────────────

    def _apply_locale_display(self, text):
        """Update the global locale bar (above the main tab bar)."""
        dash = self._find_dashboard()
        if dash is not None and hasattr(dash, "update_banner_locale_place"):
            dash.update_banner_locale_place(text)

    def _current_latlon_5dp(self):
        """Return the (lat, lon) currently in the inputs as 5dp floats, or
        (None, None) if either field can't be parsed."""
        try:
            lat = round(float(self.solar_edits['lat'].text()), 5)
            lon = round(float(self.solar_edits['lon'].text()), 5)
        except (ValueError, KeyError, TypeError):
            return None, None
        return lat, lon

    def _refresh_locale_label(self):
        """Update the banner locale label to match current Lat/Lon. Uses an
        in-process cache plus a background Nominatim lookup so we never
        block the UI and never hammer the public service."""
        dash = self._find_dashboard()
        if dash is not None and hasattr(dash, "sync_banner_locale_coords"):
            dash.sync_banner_locale_coords()
        lat, lon = self._current_latlon_5dp()
        if lat is None or lon is None:
            self._apply_locale_display("—")
            return
        key = (lat, lon, _FORECAST_LOCALE_CACHE_VER)
        cached = self._locale_cache.get(key)
        if cached is not None:
            self._apply_locale_display(cached)
            return
        if self._locale_in_flight_key == key:
            return  # already looking this up; let it finish
        self._locale_in_flight_key = key
        self._apply_locale_display("Looking up…")
        threading.Thread(
            target=self._locale_thread, args=(lat, lon), daemon=True
        ).start()

    def _locale_thread(self, lat, lon):
        lookup_key = (lat, lon, _FORECAST_LOCALE_CACHE_VER)
        text = "—"
        try:
            r = requests.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={
                    "format": "jsonv2",
                    "lat": f"{lat:.5f}",
                    "lon": f"{lon:.5f}",
                    "zoom": _FORECAST_NOMINATIM_LOCALE_ZOOM,
                    "addressdetails": 1,
                },
                headers={
                    # Nominatim usage policy requires a contact-bearing UA
                    "User-Agent": f"PowerModel/{APP_VERSION} (energy-dashboard)",
                    "Accept-Language": "en-GB,en;q=0.9",
                },
                timeout=8,
            )
            if r.status_code == 200:
                addr = (r.json() or {}).get("address", {}) or {}
                # Prefer settlement-sized keys before "city": in the UK
                # Nominatim often puts the district (e.g. South Oxfordshire)
                # in city while village/town holds the actual town name.
                place = (
                    addr.get("village")
                    or addr.get("hamlet")
                    or addr.get("locality")
                    or addr.get("neighbourhood")
                    or addr.get("town")
                    or addr.get("suburb")
                    or addr.get("city")
                    or addr.get("municipality")
                    or addr.get("county")
                )
                region = (
                    addr.get("county")
                    or addr.get("state_district")
                    or addr.get("state")
                    or addr.get("region")
                )
                if place and region and place != region:
                    text = f"{place} · {region}"
                elif place:
                    text = str(place)
                elif region:
                    text = str(region)
                else:
                    text = "Unknown locale"
            else:
                _log.debug("Locale", f"Nominatim HTTP {r.status_code}")
        except requests.exceptions.RequestException as e:
            _log.debug("Locale", f"Nominatim request failed: {e}")
        except Exception as e:  # noqa: BLE001
            _log.exception("Locale", f"Reverse-geocode failed: {e}")
        self._inv.invoke(
            lambda t=text, k=lookup_key: self._locale_done(k, t)
        )

    def _locale_done(self, key, text):
        self._locale_cache[key] = text
        # Only paint if the current Lat/Lon still match the lookup we ran;
        # otherwise the user has edited again and another lookup is queued.
        cur = self._current_latlon_5dp()
        cur_key = (
            (cur[0], cur[1], _FORECAST_LOCALE_CACHE_VER)
            if cur[0] is not None
            else None
        )
        if cur_key == key:
            self._apply_locale_display(text)
        if self._locale_in_flight_key == key:
            self._locale_in_flight_key = None

    def _open_map_picker(self):
        try:
            lat = float(self.solar_edits['lat'].text())
            lon = float(self.solar_edits['lon'].text())
        except (ValueError, TypeError):
            lat, lon = 51.5, -0.1
        w3w_key = _forecast_w3w_api_key()
        dlg = _open_forecast_location_dialog(
            lat, lon, parent=self, w3w_api_key=w3w_key,
        )
        if dlg is None:
            return
        if dlg.exec() == QDialog.Accepted:
            new_lat, new_lon = dlg.chosen_latlon()
            if new_lat is not None and new_lon is not None:
                # Block editingFinished signals while we update both fields,
                # otherwise the per-field _on_latlon_committed handler also
                # fires _persist_solar_params and writes a half-updated state
                # (lat new, lon still old) before we have a chance to set lon.
                _sync_forecasts_tab_latlon(self, new_lat, new_lon)
                try:
                    _log.info(
                        f"ForecastsTab: map picker chose lat={new_lat:.5f} "
                        f"lon={new_lon:.5f}"
                    )
                except Exception:
                    pass
                # Persist the picked location so it survives a restart, and
                # mirror it into app_params (Setup & Info reads from there)
                # so the two tabs stay in sync within this session.
                self._persist_solar_params(announce=True)
                self._refresh_locale_label()
            else:
                try:
                    _log.warn(
                        "ForecastsTab: map picker accepted but returned no "
                        "coordinates (chosen_latlon was None) — nothing saved."
                    )
                except Exception:
                    pass
                QMessageBox.warning(
                    self,
                    "Map picker",
                    "The map picker closed without returning a pin location, "
                    "so nothing was saved. Try clicking the map to drop a pin "
                    "before pressing 'Use this location'."
                )


__all__ = [n for n in globals() if not n.startswith('__')]
