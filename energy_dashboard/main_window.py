"""
Energy Dashboard — `main_window.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.dialogs.about_history import AboutDialog, HelpDialog, HistoryDialog
from energy_dashboard.modbus.command_sim import CommandSimTab
from energy_dashboard.planner.maximiser import MaximiserTab
from energy_dashboard.tabs.agile_prices import AgileSpotPricesTab
from energy_dashboard.tabs.analytics import AnalyticsTab
from energy_dashboard.tabs.battery_analysis import BatteryAnalysisTab
from energy_dashboard.tabs.combined import CombinedTab
from energy_dashboard.tabs.connectivity import ConnectivityStatusTab
from energy_dashboard.tabs.console import ConsoleTab
from energy_dashboard.tabs.database_viewer import DatabaseViewerTab
from energy_dashboard.tabs.device_import_costs import DeviceImportCostsTab
from energy_dashboard.tabs.export_tab import ExportTab
from energy_dashboard.tabs.forecasts import ForecastsTab
from energy_dashboard.tabs.growatt import GrowattTab, growatt_format_live_kw
from energy_dashboard.tabs.license import LicenseTab
from energy_dashboard.tabs.octopus import OctopusTab
from energy_dashboard.tabs.octopus_live import OctopusLiveTab
from energy_dashboard.tabs.optimiser import OptimiserTab
from energy_dashboard.tabs.parameters import ParametersTab
from energy_dashboard.tabs.shadow_trial import ShadowTrialTab
from energy_dashboard.tabs.smart_advisor import SmartAdvisorTab
from energy_dashboard.tabs.tasmota import TasmotaTab
from energy_dashboard.ui.tab_bar import BannerTabScrollHold, FreshnessTabBar

# (dashboard attribute, refresh method) for Refresh Page / Refresh All.
_TAB_REFRESH_TARGETS = (
    ('growatt_tab', 'refresh_data'),
    ('octopus_tab', 'fetch_data'),
    ('octopus_live_tab', 'fetch_data'),
    ('tasmota_tab', 'poll_all'),
    ('forecasts_tab', 'fetch_forecasts'),
    ('agile_prices_tab', 'refresh_now'),
    ('battery_tab', 'fetch_history'),
    ('combined_tab', 'refresh'),
    ('device_costs_tab', '_refresh'),
    ('analytics_tab', 'run_simulation'),
    ('advisor_tab', 'run_advisor'),
    ('optimiser_tab', 'run_planner'),
    ('shadow_trial_tab', 'refresh_now'),
    ('maximiser_tab', 'run_analysis'),
    ('connectivity_tab', 'refresh_status'),
)


class EnergyDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Energy Dashboard - Growatt + Octopus  v{APP_VERSION}")
        self.resize(1400, 850)
        self.app_params = AppParameters()
        self.data_logger = DataLogger(status_callback=lambda m: _log.debug("DataLogger", m))
        self._load_saved_auto_refresh()
        self.build_ui()
        self.parameters_tab.load_db_config_from_settings()
        QTimer.singleShot(100, self._auto_start_all)

    def _load_saved_auto_refresh(self):
        s = QSettings("PowerModel", "EnergyDashboard2")
        p = self.app_params
        if s.contains("auto_refresh/enabled"):
            p.auto_refresh_enabled = s.value("auto_refresh/enabled", True, type=bool)
        if s.contains("auto_refresh/seconds"):
            v = int(s.value("auto_refresh/seconds", p.auto_refresh_seconds))
            p.auto_refresh_seconds = max(5, min(600, v))

    def _auto_start_all(self):
        _log.info("App", f"Energy Dashboard v{APP_VERSION} starting up")
        # #region agent log
        from energy_dashboard.core.debug_trace import debug_trace
        from energy_dashboard.config import read_growatt_telemetry_source, read_grott_fill_missing_api
        qs = QSettings("PowerModel", "EnergyDashboard2")
        debug_trace(
            "main_window.py:_auto_start_all",
            "auto_start begin",
            data={
                "version": APP_VERSION,
                "telemetry_source": read_growatt_telemetry_source(qs, self.app_params),
                "fill_missing_api": read_grott_fill_missing_api(qs, self.app_params),
            },
            hypothesis_id="H1",
        )
        # #endregion
        self.set_status("Starting up — connecting to all services...")
        self.growatt_tab.auto_start()
        self.octopus_tab.auto_start()
        self.forecasts_tab.auto_start()
        self.agile_prices_tab.auto_start()
        self.shadow_trial_tab.auto_start()
        self.octopus_live_tab.auto_start()
        self.tasmota_tab.auto_start()
        self.apply_auto_refresh_from_params()
        _log.info("App", "All services started")
        # #region agent log
        gt = self.growatt_tab
        gs = gt.grott_status() if hasattr(gt, "grott_status") else {}
        st = getattr(gt, "mix_status_data", None) or {}
        debug_trace(
            "main_window.py:_auto_start_all",
            "auto_start complete",
            data={
                "grott_fresh": bool(gs.get("fresh")),
                "grott_connected": bool(gs.get("connected")),
                "has_api": bool(gt.api),
                "device_sn": gt.device_sn,
                "status_keys": sorted(st.keys()) if isinstance(st, dict) else [],
                "pLocalLoad": st.get("pLocalLoad") if isinstance(st, dict) else None,
                "pactouser": st.get("pactouser") if isinstance(st, dict) else None,
                "gridPowerEstimated": st.get("gridPowerEstimated") if isinstance(st, dict) else None,
                "loadPowerEstimated": st.get("loadPowerEstimated") if isinstance(st, dict) else None,
            },
            hypothesis_id="H1",
        )
        # #endregion

    def _auto_refresh_timers(self):
        return (
            self.growatt_tab._auto_timer,
            self.octopus_live_tab._auto_timer,
            self.tasmota_tab._auto_timer,
        )

    def _soonest_auto_refresh_seconds(self):
        """Seconds until the next live-tab auto-refresh tick (for banner countdown)."""
        rems = []
        for t in self._auto_refresh_timers():
            if not t.isActive():
                continue
            rem_ms = t.remainingTime()
            if rem_ms < 0:
                rem_ms = t.interval()
            rems.append(max(0, (rem_ms + 999) // 1000))
        if rems:
            return min(rems)
        p = self.app_params
        return max(5, int(getattr(p, "auto_refresh_seconds", 60)))

    def apply_auto_refresh_from_params(self, *, kick=False):
        p = self.app_params
        ms = max(5, int(p.auto_refresh_seconds)) * 1000
        for tab in (self.growatt_tab, self.octopus_live_tab):
            t = tab._auto_timer
            interval_ms = getattr(tab, '_auto_timer_interval_override_ms', None)
            if interval_ms is None:
                interval_ms = ms
            else:
                interval_ms = max(5000, int(interval_ms))
            t.stop()
            t.setInterval(interval_ms)
            if p.auto_refresh_enabled:
                t.start()
            else:
                t.stop()
        # Keep Tasmota HTTP poll cadence in sync with the shared interval.
        sec = max(5, int(p.auto_refresh_seconds))
        try:
            s = QSettings("PowerModel", "EnergyDashboard2")
            s.setValue("tasmota/poll_interval_seconds", sec)
            tt = self.tasmota_tab
            if hasattr(tt, "sp_poll_interval"):
                tt.sp_poll_interval.blockSignals(True)
                tt.sp_poll_interval.setValue(sec)
                tt.sp_poll_interval.blockSignals(False)
        except Exception:
            pass
        self.tasmota_tab.apply_poll_timer(kick=False)
        self._update_refresh_cycle_button()
        if kick and p.auto_refresh_enabled:
            self.growatt_tab._on_auto_tick()
            self.octopus_live_tab.fetch_data()
        if kick and self.tasmota_tab.periodic_poll_enabled():
            self.tasmota_tab.poll_all()

    def _preload_main_tab_before_switch(self, idx):
        """Tab widgets are already children of the main QTabWidget; nudge layout before show."""
        bar = getattr(self, "tabs", None)
        if bar is None:
            return
        w = bar.widget(idx)
        if w is None:
            return
        try:
            polish = getattr(w, "ensurePolished", None)
            if callable(polish):
                polish()
            w.updateGeometry()
            w.update()
        except Exception:
            pass

    def _banner_tab_step(self, delta):
        """Move main window tab by delta (+1 = next, -1 = previous), wrapping."""
        bar = getattr(self, "tabs", None)
        if bar is None or bar.count() < 2:
            return
        cur = bar.currentIndex()
        n = bar.count()
        nxt = (cur + int(delta)) % n
        self._preload_main_tab_before_switch(nxt)
        bar.setCurrentIndex(nxt)

    def _rebuild_main_tab_bar(self):
        """Rebuild the main QTabWidget from `_MAIN_TAB_BAR_REGISTRY` and QSettings."""
        s = QSettings("PowerModel", "EnergyDashboard2")
        bar = self.tabs
        prev = bar.currentWidget()
        bar.blockSignals(True)
        try:
            while bar.count() > 0:
                bar.removeTab(0)
            for key, attr, title in _MAIN_TAB_BAR_REGISTRY:
                if key is None:
                    visible = True
                else:
                    visible = s.value(f"tabs/visible/{key}", True, type=bool)
                if visible:
                    w = getattr(self, attr)
                    bar.addTab(w, title)
        finally:
            bar.blockSignals(False)
        if prev is not None and bar.indexOf(prev) >= 0:
            bar.setCurrentWidget(prev)
        elif bar.count() > 0:
            bar.setCurrentIndex(0)
        if getattr(self, "_tab_last_update", None) is not None:
            self._refresh_tab_freshness()

    def build_ui(self):
        central = QWidget()
        central.setStyleSheet(f"background-color: {_DARK_BG};")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # Global live banner (visible on every tab)
        ban = QHBoxLayout()
        ban.setContentsMargins(0, 0, 0, 0)
        ban.setSpacing(6)

        def _banner_card(title, color):
            card = QFrame()
            card.setObjectName("liveBannerCard")
            card.setAttribute(Qt.WA_StyledBackground, True)
            card.setFixedHeight(42)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            cl = QHBoxLayout(card)
            cl.setContentsMargins(10, 2, 10, 2)
            cl.setSpacing(6)
            t = QLabel(f"{title}:")
            t.setStyleSheet("color: #6c7086; font-size: 11px; border: none;")
            t.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            v = QLabel("--")
            v.setFont(QFont('Helvetica', 13, QFont.Bold))
            v.setStyleSheet(f"color: {color}; border: none;")
            v.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            cl.addWidget(t)
            cl.addWidget(v, 1)
            ban.addWidget(card)
            return v

        self._ban_soc       = _banner_card("SOC", "#2196F3")
        self._ban_bat_state = _banner_card("Battery", "#a6e3a1")
        self._ban_load      = _banner_card("Load", "#fab387")
        self._ban_pv        = _banner_card("PV", "#FF9800")
        self._ban_grid      = _banner_card("Grid", "#cba6f7")
        # Right-most cluster: auto-refresh cycle + tab wheel/hold strip (›).
        self._ban_refresh = self._build_refresh_cycle_card(ban)
        main_layout.addLayout(ban)

        meta_bar = QWidget()
        meta_bar.setStyleSheet(f"background-color: {_DARK_BG};")
        meta_row = QHBoxLayout(meta_bar)
        meta_row.setContentsMargins(8, 0, 12, 2)
        meta_row.setSpacing(12)

        self._live_import_audit = QLabel("")
        self._live_import_audit.setWordWrap(False)
        self._live_import_audit.setTextFormat(Qt.RichText)
        self._live_import_audit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._live_import_audit.setStyleSheet(
            "color: #6c7086; font-size: 11px; padding: 0;"
        )
        self._live_import_audit.setText(
            "Import audit: updates when Growatt live data refreshes (usage profile + solar forecast + Agile)."
        )
        self._live_import_audit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred,
        )
        meta_row.addWidget(self._live_import_audit, 1)

        locale_cluster = QWidget()
        locale_cluster.setStyleSheet("background: transparent;")
        locale_row = QHBoxLayout(locale_cluster)
        locale_row.setContentsMargins(0, 0, 0, 0)
        locale_row.setSpacing(6)
        _locale_muted = "color: #6c7086; font-size: 11px;"
        _locale_sep_ss = "color: #45475a; font-size: 11px; padding: 0 2px;"

        def _locale_sep():
            s = QLabel("|")
            s.setStyleSheet(_locale_sep_ss)
            return s

        locale_title = QLabel("Locale:")
        locale_title.setStyleSheet(_locale_muted)
        locale_title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._banner_locale_place = QLabel("—")
        self._banner_locale_place.setStyleSheet(
            f"color: {_UI_BLUE}; font-weight: bold; font-size: 11px;"
        )
        self._banner_locale_place.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._banner_locale_place.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._banner_locale_place.setToolTip(
            "Village or town (when available), then county or region — "
            "reverse-geocoded from the saved solar Lat/Lon (Forecasts / Setup)."
        )

        self._banner_locale_coords = QLabel("Lat — · Lon —")
        self._banner_locale_coords.setStyleSheet(_locale_muted)
        self._banner_locale_coords.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._banner_locale_coords.setToolTip(
            "Solar installation coordinates (Forecasts / Setup). "
            "Used for PV forecasts and locale lookup."
        )

        crs_title = QLabel("CRS:")
        crs_title.setStyleSheet(_locale_muted)
        self._banner_locale_crs = QLabel("WGS 84 (EPSG:4326)")
        self._banner_locale_crs.setStyleSheet(_locale_muted)
        self._banner_locale_crs.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._banner_locale_crs.setToolTip(
            "Coordinate reference system for lat/lon (geographic WGS 84)."
        )

        self._banner_locale_set_btn = QPushButton("Set location…")
        self._banner_locale_set_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self._banner_locale_set_btn.setToolTip(
            "Pick lat/lon on a map (saved to Forecasts and Setup)."
        )
        self._banner_locale_set_btn.clicked.connect(self._open_banner_solar_location)

        locale_row.addWidget(locale_title)
        locale_row.addWidget(self._banner_locale_place)
        locale_row.addWidget(_locale_sep())
        locale_row.addWidget(self._banner_locale_coords)
        locale_row.addWidget(_locale_sep())
        locale_row.addWidget(crs_title)
        locale_row.addWidget(self._banner_locale_crs)
        locale_row.addWidget(self._banner_locale_set_btn)
        meta_row.addWidget(locale_cluster, 0)
        main_layout.addWidget(meta_bar)

        self.tabs = QTabWidget()
        self._fresh_tab_bar = FreshnessTabBar(self.tabs)
        self.tabs.setTabBar(self._fresh_tab_bar)
        main_layout.addWidget(self.tabs)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # ── Bottom-right action cluster ────────────────────────────────
        # addPermanentWidget appends to the right-hand group in
        # left-to-right order:
        #   [ Refresh Page ] [ Refresh All ] (gap) [ Help ] [ Close ]
        _ACTION_BTN_WIDTH = 110

        refresh_page_btn = QPushButton("Refresh Page")
        refresh_page_btn.setToolTip(
            "Refresh only the currently selected tab (same action each tab "
            "uses for live data or re-run, e.g. Build plan on Optimiser)."
        )
        refresh_page_btn.setFixedWidth(_ACTION_BTN_WIDTH)
        refresh_page_btn.clicked.connect(self._refresh_current_tab)
        self.status_bar.addPermanentWidget(refresh_page_btn)

        refresh_all_btn = QPushButton("Refresh All")
        refresh_all_btn.setToolTip(
            "Trigger a one-shot refresh on every tab that supports it "
            "(Growatt, Octopus, Tasmota, Forecasts, Battery, Optimiser…)"
        )
        refresh_all_btn.setFixedWidth(_ACTION_BTN_WIDTH)
        refresh_all_btn.clicked.connect(self._refresh_all_tabs)
        self.status_bar.addPermanentWidget(refresh_all_btn)

        spacer = QWidget()
        spacer.setFixedWidth(100)
        spacer.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.status_bar.addPermanentWidget(spacer)

        help_btn = QPushButton("Help")
        help_btn.setToolTip(
            "Show help for the currently selected tab "
            "(content is page-specific)."
        )
        help_btn.setFixedWidth(_ACTION_BTN_WIDTH)
        help_btn.clicked.connect(self._show_help_for_current_tab)
        self.status_bar.addPermanentWidget(help_btn)

        close_btn = QPushButton("Close")
        close_btn.setToolTip("Close the dashboard window")
        close_btn.clicked.connect(self.close)
        close_btn.setFixedWidth(_ACTION_BTN_WIDTH)
        self.status_bar.addPermanentWidget(close_btn)

        # ── Main tabs: construct in dependency order; add in grouped order below.
        self.growatt_tab = GrowattTab(self.set_status, self.app_params, dash=self)
        self.growatt_tab.on_data_updated = self._on_growatt_data_updated

        self.octopus_tab = OctopusTab(self.set_status, self.app_params)
        self.octopus_tab.on_data_updated = self._on_octopus_data_updated

        self.tasmota_tab = TasmotaTab(self.set_status, dashboard=self)
        self.tasmota_tab.on_data_updated = self._on_tasmota_data_updated

        self.device_costs_tab = DeviceImportCostsTab(
            self.octopus_tab, self.tasmota_tab, self.app_params, self.set_status
        )
        self.device_costs_tab.on_data_updated = (
            lambda: self.mark_tab_fresh(self.device_costs_tab)
        )

        self.combined_tab = CombinedTab(self.growatt_tab, self.octopus_tab, self.set_status)

        self.battery_tab = BatteryAnalysisTab(
            self.growatt_tab, self.set_status, self.app_params, dash=self,
        )
        self.battery_tab.on_data_updated = lambda: self.mark_tab_fresh(self.battery_tab)

        self.analytics_tab = AnalyticsTab(
            self.octopus_tab, self.growatt_tab, self.set_status, self.app_params,
            dashboard=self,
        )
        self.analytics_tab.on_data_updated = lambda: self.mark_tab_fresh(self.analytics_tab)

        self.forecasts_tab = ForecastsTab(self.set_status, data_logger=self.data_logger)

        self.agile_prices_tab = AgileSpotPricesTab(self.forecasts_tab, self.set_status)
        self.agile_prices_tab.on_data_updated = (
            lambda: self.mark_tab_fresh(self.agile_prices_tab)
        )

        def _on_forecasts_updated():
            self.mark_tab_fresh(self.forecasts_tab)
            self.agile_prices_tab.refresh_from_forecasts()

        self.forecasts_tab.on_data_updated = _on_forecasts_updated

        self.advisor_tab = SmartAdvisorTab(
            self.growatt_tab, self.octopus_tab, self.forecasts_tab,
            self.set_status, self.app_params,
        )
        self.advisor_tab.dash = self
        self.advisor_tab.on_data_updated = lambda: self.mark_tab_fresh(self.advisor_tab)

        self.optimiser_tab = OptimiserTab(
            self.growatt_tab, self.octopus_tab, self.forecasts_tab,
            self.advisor_tab, self.tasmota_tab,
            self.app_params, self.set_status,
        )
        self.optimiser_tab.on_data_updated = lambda: self.mark_tab_fresh(self.optimiser_tab)

        self.shadow_trial_tab = ShadowTrialTab(
            self.growatt_tab, self.forecasts_tab, self.advisor_tab,
            self.optimiser_tab, self.app_params, self.set_status,
            data_logger=self.data_logger,
        )
        self.shadow_trial_tab.on_data_updated = (
            lambda: self.mark_tab_fresh(self.shadow_trial_tab)
        )

        self.maximiser_tab = MaximiserTab(self)

        self.octopus_live_tab = OctopusLiveTab(self.set_status)
        self.octopus_live_tab.on_data_updated = (
            lambda: self.mark_tab_fresh(self.octopus_live_tab)
        )

        self.connectivity_tab = ConnectivityStatusTab(self)

        self.command_sim_tab = CommandSimTab(self.set_status)

        self.db_viewer_tab = DatabaseViewerTab(self)

        self.export_tab = ExportTab(
            self.app_params, self.data_logger, self.set_status,
        )
        self.export_tab.on_data_updated = lambda: self.mark_tab_fresh(self.export_tab)

        self.console_tab = ConsoleTab()

        self.parameters_tab = ParametersTab(self)

        self.license_tab = LicenseTab()

        # Tab bar: order and optional hiding come from `_MAIN_TAB_BAR_REGISTRY`
        # and QSettings (`tabs/visible/<key>`); see Setup && Info → tab bar.
        self._rebuild_main_tab_bar()
        nav = getattr(self, "_banner_tab_nav", None)
        if nav is not None:
            nav.bind_tabs(self.tabs, self)

        self.analytics_tab.apply_from_app_params()
        self.battery_tab.apply_from_app_params()

        self.tabs.currentChanged.connect(self._on_main_tab_changed)
        self.tabs.currentChanged.connect(lambda _idx: self._refresh_tab_freshness())

        # Tab-bar freshness tint (green → background over 10 min) + banner countdown.
        # Timer ticks every second so the fade and countdown stay smooth.
        self._tab_last_update = {}
        self._tab_color_timer = QTimer(self)
        self._tab_color_timer.setInterval(1000)
        self._tab_color_timer.timeout.connect(self._refresh_tab_freshness)
        self._tab_color_timer.start()
        self._refresh_tab_freshness()

        # Green primary motif on every action button (Toggle exempt via property).
        _style_all_primary_buttons(self)

        # Electric-blue 90×20 spin fields (Export p/kWh reference) on all tabs.
        apply_spin_field_motif_tree(self)

        QTimer.singleShot(0, self._init_banner_locale)

    # ── Locale bar (above main tabs) ─────────────────────────────────────

    _LOCALE_CRS_LABEL = "WGS 84 (EPSG:4326)"

    def sync_banner_locale_coords(self):
        """Refresh lat/lon on the locale bar from Forecasts / app_params."""
        lat_s = lon_s = ""
        ft = getattr(self, "forecasts_tab", None)
        if ft is not None:
            try:
                lat_s = ft.solar_edits["lat"].text().strip()
                lon_s = ft.solar_edits["lon"].text().strip()
            except (KeyError, AttributeError):
                pass
        if not lat_s or not lon_s:
            p = getattr(self, "app_params", None)
            if p is not None:
                lat_s = str(getattr(p, "solar_lat", "") or "").strip()
                lon_s = str(getattr(p, "solar_lon", "") or "").strip()
        coords_lbl = getattr(self, "_banner_locale_coords", None)
        if coords_lbl is None:
            return
        if lat_s and lon_s:
            try:
                lat_f = float(lat_s)
                lon_f = float(lon_s)
                coords_lbl.setText(f"Lat {lat_f:.5f}° · Lon {lon_f:.5f}°")
            except ValueError:
                coords_lbl.setText(f"Lat {lat_s} · Lon {lon_s}")
        else:
            coords_lbl.setText("Lat — · Lon —")
        crs_lbl = getattr(self, "_banner_locale_crs", None)
        if crs_lbl is not None:
            crs_lbl.setText(self._LOCALE_CRS_LABEL)

    def update_banner_locale_place(self, text):
        lbl = getattr(self, "_banner_locale_place", None)
        if lbl is not None:
            lbl.setText(text)

    def _open_banner_solar_location(self):
        ft = getattr(self, "forecasts_tab", None)
        if ft is None:
            return
        ft._open_map_picker()

    def _init_banner_locale(self):
        self.sync_banner_locale_coords()
        ft = getattr(self, "forecasts_tab", None)
        if ft is not None:
            ft._refresh_locale_label()

    # ── Tab freshness colour coding ────────────────────────────────────

    def mark_tab_fresh(self, tab_widget):
        """Record that `tab_widget` has just received fresh data."""
        if tab_widget is None:
            return
        self._tab_last_update[tab_widget] = datetime.now()
        self._refresh_tab_freshness()

    def _refresh_tab_freshness(self):
        bar = getattr(self, '_fresh_tab_bar', None) or self.tabs.tabBar()
        now = datetime.now()
        cur = self.tabs.currentIndex()
        bgs = {}
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            last = self._tab_last_update.get(widget)
            bgs[i] = _tab_freshness_background(last, now)
        if hasattr(bar, 'set_freshness_backgrounds'):
            bar.set_freshness_backgrounds(bgs)
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            last = self._tab_last_update.get(widget)
            fg = _tab_freshness_text_color(last, now, i == cur)
            bar.setTabTextColor(i, QColor(fg))

        self._update_refresh_cycle_button()

    # ── Refresh cycle button ───────────────────────────────────────────

    def _build_refresh_cycle_card(self, ban_layout):
        """Build the right-most banner row: auto-refresh cycle button + tab scroll/hold strip."""
        wrap = QWidget()
        wrap.setObjectName("liveBannerRefreshWrap")
        wrap.setStyleSheet(f"#liveBannerRefreshWrap {{ background-color: {_DARK_BG}; }}")
        wrap.setFixedHeight(42)
        wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        hl = QHBoxLayout(wrap)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(2)

        btn = QPushButton("Auto --s")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(42)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.setFont(QFont('Helvetica', 13, QFont.Bold))
        btn.setToolTip(
            "Click to cycle the shared auto-refresh interval:\n"
            "Auto 10s → 30s → 60s → 180s → 300s → 600s → Manual only.\n"
            "Uses the same green button style as Refresh All.\n\n"
            "The narrow › panel to the right: mouse wheel = previous/next main tab; "
            "press-and-hold = advance tabs."
        )
        btn.setStyleSheet(_BANNER_REFRESH_CYCLE_QSS)
        btn.clicked.connect(self._advance_refresh_cycle)
        hl.addWidget(btn, 1)

        self._banner_tab_nav = BannerTabScrollHold()
        hl.addWidget(self._banner_tab_nav, 0)

        ban_layout.addWidget(wrap)
        return btn

    def _current_refresh_cycle_index(self):
        """Find the cycle entry that matches the current app_params state.
        Falls back to the closest interval if there's no exact match."""
        p = self.app_params
        if not getattr(p, 'auto_refresh_enabled', False):
            for i, (sec, _c, _l) in enumerate(_REFRESH_CYCLE):
                if sec == 0:
                    return i
            return len(_REFRESH_CYCLE) - 1
        cur = max(5, int(getattr(p, 'auto_refresh_seconds', 60)))
        best_i = 0
        best_d = None
        for i, (sec, _c, _l) in enumerate(_REFRESH_CYCLE):
            if sec == 0:
                continue
            d = abs(sec - cur)
            if best_d is None or d < best_d:
                best_d, best_i = d, i
        return best_i

    def _advance_refresh_cycle(self):
        """User clicked the refresh card — bump to the next cycle entry,
        push the change into app_params + QSettings, restart the shared
        timers, and keep the Parameters tab UI in sync."""
        i = (self._current_refresh_cycle_index() + 1) % len(_REFRESH_CYCLE)
        sec, _color, label = _REFRESH_CYCLE[i]
        p = self.app_params
        if sec == 0:
            p.auto_refresh_enabled = False
        else:
            p.auto_refresh_enabled = True
            p.auto_refresh_seconds = int(sec)
        try:
            s = QSettings("PowerModel", "EnergyDashboard2")
            s.setValue("auto_refresh/enabled", bool(p.auto_refresh_enabled))
            s.setValue("auto_refresh/seconds", int(p.auto_refresh_seconds))
        except Exception:
            pass
        self.apply_auto_refresh_from_params(kick=True)
        # If the Parameters tab has already been built, keep its
        # checkbox / spinbox in sync with the new mode.
        try:
            pt = getattr(self, 'parameters_tab', None)
            if pt is not None:
                if hasattr(pt, 'chk_auto_refresh'):
                    pt.chk_auto_refresh.setChecked(bool(p.auto_refresh_enabled))
                if hasattr(pt, 'sp_refresh') and sec > 0:
                    pt.sp_refresh.setValue(int(sec))
        except Exception:
            pass
        _log.info("Refresh", f"Auto-refresh mode → {label}")
        self._update_refresh_cycle_button()

    def _update_refresh_cycle_button(self):
        """Redraw the refresh button with the current mode + countdown."""
        if not hasattr(self, '_ban_refresh'):
            return
        i = self._current_refresh_cycle_index()
        sec, _color, label = _REFRESH_CYCLE[i]
        if sec == 0:
            text = label
        else:
            rem_s = self._soonest_auto_refresh_seconds()
            if rem_s is None:
                rem_s = sec
            text = f"{label} · Next {rem_s}s"
        self._ban_refresh.setText(text)
        self._ban_refresh.setStyleSheet(_BANNER_REFRESH_CYCLE_QSS)

    def _on_main_tab_changed(self, index):
        if self.tabs.widget(index) is self.combined_tab:
            self.combined_tab.refresh()

    def _apply_live_import_audit(self, audit):
        if not audit or not hasattr(self, '_live_import_audit'):
            return
        summary = audit.get('summary') or ''
        if audit.get('unnecessary'):
            col = '#f38ba8'
        elif 'negligible' in summary.lower():
            col = '#6c7086'
        else:
            col = '#fab387'
        self._live_import_audit.setText(f"<span style='color:{col};'>{summary}</span>")
        self._live_import_audit.setToolTip('\n'.join(audit.get('lines', [])))

    def _update_live_import_audit(self):
        if not hasattr(self, 'advisor_tab'):
            return
        try:
            audit = self.advisor_tab.build_live_import_audit()
        except Exception as e:
            _log.warn("Import audit", str(e))
            return
        if audit:
            self._apply_live_import_audit(audit)

    def _on_growatt_data_updated(self):
        self._update_live_banner()
        self._update_live_import_audit()
        self._log_growatt_data()
        self.mark_tab_fresh(self.growatt_tab)
        # Combined Dashboard mirrors the live Growatt feed, so it's "fresh"
        # whenever Growatt is fresh.
        if hasattr(self, 'combined_tab'):
            self.mark_tab_fresh(self.combined_tab)
        if hasattr(self, 'connectivity_tab'):
            self.connectivity_tab.refresh_status(test_db=False)

    def _log_growatt_data(self):
        gt = self.growatt_tab
        d = gt.mix_status_data
        if not d:
            return
        discharge = float(d.get('pdisCharge1', 0) or 0)
        charge = float(d.get('chargePower', 0) or 0)
        grid_import = float(d.get('pactouser', 0) or 0)
        grid_export = float(d.get('pactogrid', 0) or 0)
        totals = getattr(gt, 'mix_totals_data', None) or {}
        self.data_logger.log_growatt({
            'soc': d.get('SOC'),
            'bat_power': charge - discharge,
            'pv_power': d.get('ppv'),
            'grid_power': grid_export - grid_import,
            'load_power': d.get('pLocalLoad'),
            'charge_today': totals.get('echargetoday'),
            'discharge_today': totals.get('edischarge1Today'),
            'pv_today': totals.get('epvToday'),
        })

    def _on_octopus_data_updated(self):
        hh = getattr(self.octopus_tab, 'hh_data', None)
        if hh is None or hh.empty:
            return
        records = []
        for idx, row in hh.iterrows():
            try:
                ikw = float(row['Import (kWh)'])
            except (KeyError, TypeError, ValueError):
                ikw = 0.0
            try:
                ekw = float(row['Export (kWh)'])
            except (KeyError, TypeError, ValueError):
                ekw = 0.0
            records.append({
                'interval_start': _octopus_interval_key_utc(idx),
                'import_kwh': ikw,
                'export_kwh': ekw,
            })
        if records:
            self.data_logger.log_octopus(records)
        self.mark_tab_fresh(self.octopus_tab)
        if hasattr(self, 'combined_tab'):
            self.mark_tab_fresh(self.combined_tab)
        # NOTE: do NOT proactively mark device_costs_tab fresh here. The
        # Daily Import Costs chart is only refreshed when the user clicks
        # its own "Refresh chart" button — flagging it green just because
        # upstream Octopus data arrived would lie about the displayed
        # chart's age (it might still be empty / from a previous session).
        if hasattr(self, 'connectivity_tab'):
            self.connectivity_tab.refresh_status(test_db=False)

    def _on_tasmota_data_updated(self):
        _ts = QSettings("PowerModel", "EnergyDashboard2")
        if _ts.value("tasmota/use_powermon_broker", False, type=bool):
            self.mark_tab_fresh(self.tasmota_tab)
            if hasattr(self, 'connectivity_tab'):
                self.connectivity_tab.refresh_status(test_db=False)
            return
        records = []
        for ip, d in self.tasmota_tab.device_data.items():
            if d:
                records.append({
                    'ip': ip,
                    'name': d.get('name', ''),
                    'relay_on': d.get('relay_on'),
                    'power_W': d.get('power_W'),
                    'voltage_V': d.get('voltage_V'),
                    'current_A': d.get('current_A'),
                    'today_kWh': d.get('today_kWh'),
                    'total_kWh': d.get('total_kWh'),
                })
        if records:
            self.data_logger.log_tasmota(records)
        self.mark_tab_fresh(self.tasmota_tab)
        # NOTE: device_costs_tab is intentionally NOT marked fresh here —
        # see the matching note in `_on_octopus_data_updated`. Its own
        # `_apply_plot` self-marks via `on_data_updated` once a chart has
        # actually been drawn from real data.
        if hasattr(self, 'connectivity_tab'):
            self.connectivity_tab.refresh_status(test_db=False)

    def _update_live_banner(self):
        data = self.growatt_tab.get_live_data_summary()
        if data is None:
            self._ban_soc.setText("--")
            self._ban_bat_state.setText("--")
            self._ban_bat_state.setStyleSheet("color: #6c7086;")
            self._ban_load.setText("--")
            self._ban_pv.setText("--")
            self._ban_grid.setText("--")
            return

        if data.get('comms_lost'):
            reason = (data.get('comms_reason') or 'lost').strip()
            self._ban_soc.setText("--")
            self._ban_soc.setStyleSheet("color: #6c7086;")
            self._ban_bat_state.setText("Comms lost")
            self._ban_bat_state.setStyleSheet("color: #fab387;")
            self._ban_load.setText("--")
            self._ban_pv.setText("--")
            self._ban_grid.setText("--")
            self._ban_grid.setStyleSheet("color: #6c7086;")
            self.set_status(
                f"Growatt inverter offline ({reason}) — live banner paused"
            )
            return

        soc = data.get('soc', '--')
        soc_text = soc if soc not in (None, '', '--') else '--'
        self._ban_soc.setText(f"{soc_text}%")
        try:
            soc_val = float(soc)
        except (TypeError, ValueError):
            soc_val = 50
        if soc_val > 80:
            self._ban_soc.setStyleSheet("color: #a6e3a1;")
        elif soc_val > 30:
            self._ban_soc.setStyleSheet(f"color: {_UI_BLUE};")
        else:
            self._ban_soc.setStyleSheet("color: #f38ba8;")

        bp = data.get('bat_power', 0)
        try:
            bp_f = float(bp)
        except (TypeError, ValueError):
            bp_f = 0
        if bp_f > 0.05:
            state_txt = f"Charging {bp_f:.2f} kW"
            state_col = "#a6e3a1"
        elif bp_f < -0.05:
            state_txt = f"Discharging {abs(bp_f):.2f} kW"
            state_col = "#fab387"
        else:
            state_txt = "Holding"
            state_col = "#6c7086"
        self._ban_bat_state.setText(state_txt)
        self._ban_bat_state.setStyleSheet(f"color: {state_col};")

        lp = data.get('load_power', '--')
        lp_txt = growatt_format_live_kw(lp)
        self._ban_load.setText(f"{lp_txt} kW" if lp_txt is not None else "--")

        pv_txt = growatt_format_live_kw(data.get('pv_power', '--'))
        self._ban_pv.setText(f"{pv_txt} kW" if pv_txt is not None else "--")

        gp = data.get('grid_power')
        if gp in (None, '', '--'):
            self._ban_grid.setText("--")
            self._ban_grid.setStyleSheet("color: #6c7086;")
        else:
            try:
                gp_f = float(gp)
            except (TypeError, ValueError):
                self._ban_grid.setText("--")
                self._ban_grid.setStyleSheet("color: #6c7086;")
            else:
                gp_txt = growatt_format_live_kw(gp_f)
                # #region agent log
                try:
                    from energy_dashboard.core.debug_trace import debug_trace
                    debug_trace(
                        "main_window.py:_update_live_banner",
                        "banner power values",
                        data={
                            "load_kw": lp_txt,
                            "pv_kw": pv_txt,
                            "grid_kw_signed": gp_txt,
                            "grid_raw": gp_f,
                        },
                        hypothesis_id="H5",
                    )
                except Exception:
                    pass
                # #endregion
                if gp_f > 0:
                    self._ban_grid.setText(f"Export {gp_txt} kW")
                    self._ban_grid.setStyleSheet("color: #a6e3a1;")
                elif gp_f < 0:
                    self._ban_grid.setText(f"Import {abs(gp_f):.2f} kW")
                    self._ban_grid.setStyleSheet("color: #f38ba8;")
                else:
                    self._ban_grid.setText("0.00 kW")
                    self._ban_grid.setStyleSheet("color: #6c7086;")

    def set_status(self, text):
        self.status_bar.showMessage(text)

    # ── Global Help / Refresh-All actions ──────────────────────────────

    def _show_help_for_current_tab(self):
        """Look up the page-specific help string keyed by the active tab's
        class name and open it in a HelpDialog. Falls back to a generic
        message for tabs that don't yet have a registered entry."""
        try:
            tab = self.tabs.currentWidget()
            cls_name = type(tab).__name__ if tab is not None else ""
            tab_title = self.tabs.tabText(self.tabs.currentIndex()).strip()
            HelpDialog(cls_name, tab_title=tab_title, parent=self).exec()
        except Exception as e:
            try:
                _log.warn(f"Dashboard: failed to show Help dialog: {e}")
            except Exception:
                pass
            QMessageBox.warning(self, "Help", f"Couldn't open help:\n{e}")

    def _refresh_hook_for_widget(self, widget):
        """Return (attr_name, method_name) if this tab widget supports refresh."""
        if widget is None:
            return None, None
        for attr, method in _TAB_REFRESH_TARGETS:
            if getattr(self, attr, None) is widget:
                return attr, method
        return None, None

    def _refresh_current_tab(self):
        """Re-run the canonical refresh entry-point for the visible tab only."""
        widget = self.tabs.currentWidget()
        title = self.tabs.tabText(self.tabs.currentIndex()).strip()
        attr, method = self._refresh_hook_for_widget(widget)
        if attr is None:
            self.set_status(f"Refresh Page: “{title}” has no automatic refresh.")
            return
        fn = getattr(widget, method, None)
        if not callable(fn):
            self.set_status(
                f"Refresh Page: “{title}” — {attr}.{method} is not available."
            )
            return
        try:
            fn()
            try:
                _log.info(f"Dashboard: Refresh Page — {attr}.{method}")
            except Exception:
                pass
            self.set_status(f"Refresh Page: {title}")
        except Exception as e:
            try:
                _log.warn(f"Dashboard: Refresh Page — {attr}.{method} failed: {e}")
            except Exception:
                pass
            self.set_status(f"Refresh Page failed on {title}: {e}")

    def _refresh_all_tabs(self):
        """Trigger a one-shot refresh on every tab that exposes a refresh
        entry-point. Each call is independently try/except'd so a failure
        in one tab can't block the rest. Reports a count via the status
        bar so the user gets immediate feedback."""
        fired, skipped = [], []
        for attr, method in _TAB_REFRESH_TARGETS:
            tab = getattr(self, attr, None)
            if tab is None:
                continue
            fn = getattr(tab, method, None)
            if not callable(fn):
                skipped.append(f"{attr}.{method}")
                continue
            try:
                fn()
                fired.append(attr)
            except Exception as e:
                skipped.append(f"{attr}.{method} ({e.__class__.__name__})")
                try:
                    _log.warn(
                        f"Dashboard: Refresh All — {attr}.{method} failed: {e}"
                    )
                except Exception:
                    pass
        try:
            _log.info(
                f"Dashboard: Refresh All triggered — fired on "
                f"{len(fired)} tabs ({', '.join(fired)})"
                + (f"; skipped: {', '.join(skipped)}" if skipped else "")
            )
        except Exception:
            pass
        self.set_status(
            f"Refresh All: requested on {len(fired)} tab"
            f"{'s' if len(fired) != 1 else ''}"
            + (f" (skipped {len(skipped)})" if skipped else "")
        )


__all__ = [n for n in globals() if not n.startswith('__')]
