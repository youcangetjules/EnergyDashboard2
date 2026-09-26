"""
Energy Dashboard — `main_window.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.core.invoker import Invoker
from energy_dashboard.core.alarms import (
    AlarmMonitor,
    DEFAULT_HOLD_MINUTES,
    DEFAULT_PV_MIN_KW,
    DEFAULT_NOTIFY_COOLDOWN_S,
)
import re
from energy_dashboard.dialogs.about_history import AboutDialog, HelpDialog, HistoryDialog
from energy_dashboard.modbus.command_sim import CommandSimTab
from energy_dashboard.planner.maximiser import MaximiserTab
from energy_dashboard.tabs.agile_prices import AgileSpotPricesTab
from energy_dashboard.tabs.agile_year import AgileYearTab
from energy_dashboard.tabs.analytics import AnalyticsTab
from energy_dashboard.tabs.battery_analysis import BatteryAnalysisTab
from energy_dashboard.tabs.alarm_defs import AlarmDefsTab
from energy_dashboard.tabs.bug_tracker import BugTrackerTab
from energy_dashboard.tabs.combined import CombinedTab
from energy_dashboard.tabs.connectivity import ConnectivityStatusTab
from energy_dashboard.tabs.console import ConsoleTab
from energy_dashboard.tabs.dump_logs import DumpLogsTab
from energy_dashboard.tabs.database_viewer import DatabaseViewerTab
from energy_dashboard.tabs.device_import_costs import DeviceImportCostsTab
from energy_dashboard.tabs.export_tab import ExportTab
from energy_dashboard.tabs.forecasts import ForecastsTab
from energy_dashboard.tabs.growatt import GrowattTab, growatt_format_live_kw
from energy_dashboard.tabs.grott_api_align import GrottApiAlignTab
from energy_dashboard.tabs.grott_setup import GrottSetupTab
from energy_dashboard.tabs.license import LicenseTab
from energy_dashboard.tabs.octopus import OctopusTab
from energy_dashboard.tabs.octopus_live import OctopusLiveTab
from energy_dashboard.tabs.optimiser import OptimiserTab
from energy_dashboard.tabs.pot_issues import PotIssuesTab
from energy_dashboard.tabs.pv_string_charge import PvStringChargeTab
from energy_dashboard.tabs.pv_string_voltage import PvStringVoltageTab
from energy_dashboard.tabs.panel_database import PanelDatabaseTab
from energy_dashboard.tabs.roof_layout import RoofLayoutTab
from energy_dashboard.tabs.parameters import ParametersTab
from energy_dashboard.tabs.shadow_trial import ShadowTrialTab
from PySide6.QtWidgets import QWidgetAction

from energy_dashboard.ui.system_status_bar import tray_database_lines
from energy_dashboard.ui.tray_icon import (
    TrayInfoLine,
    powermon_tray_icon,
    style_tray_info,
)
from energy_dashboard.ui.work_area import client_cap, fit_window_to_work_area
from energy_dashboard.tabs.smart_advisor import SmartAdvisorTab
from energy_dashboard.tabs.tasmota import TasmotaTab
from energy_dashboard.ui.tab_bar import (
    BannerRefreshCyclePill,
    BannerTabScrollHold,
    FreshnessTabBar,
    MainTabGroupStrip,
)

# (dashboard attribute, refresh method) for Refresh Page / Refresh All.
_TAB_REFRESH_TARGETS = (
    ('growatt_tab', 'refresh_data'),
    ('octopus_tab', 'fetch_data'),
    ('octopus_live_tab', 'fetch_data'),
    ('tasmota_tab', 'poll_all'),
    ('forecasts_tab', 'fetch_forecasts'),
    ('agile_prices_tab', 'refresh_now'),
    ('agile_year_tab', 'refresh_now'),
    ('battery_tab', 'fetch_history'),
    ('combined_tab', 'refresh'),
    ('device_costs_tab', '_refresh'),
    ('pv_string_charge_tab', 'refresh_now'),
    ('pv_string_voltage_tab', 'refresh_now'),
    ('pot_issues_tab', 'refresh_now'),
    ('analytics_tab', 'run_simulation'),
    ('advisor_tab', 'run_advisor'),
    ('optimiser_tab', 'run_planner'),
    ('shadow_trial_tab', 'refresh_now'),
    ('maximiser_tab', 'run_analysis'),
    ('grott_align_tab', 'compare_now'),
    ('connectivity_tab', 'refresh_status'),
    ('grott_setup_tab', 'refresh_status'),
)


class EnergyDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self._work_area_filled = False
        self._work_area_guard = False
        self._work_area_clamp_pending = False
        self._work_area_screen_hooked = False
        self.setWindowTitle(f"Energy Dashboard - Growatt + Octopus  v{APP_VERSION}")
        self.resize(1400, 850)
        self.app_params = AppParameters()
        self.data_logger = DataLogger(status_callback=lambda m: _log.debug("DataLogger", m))
        self.alarm_monitor = AlarmMonitor()
        self._alarm_tray = None
        self._tray_quit = False
        self._tray_hide_hinted = False
        self._tray_broker_status = None
        self._tray_broker_busy = False
        self._tray_probe_busy = False
        self._tray_inv = Invoker(self)
        self._load_saved_auto_refresh()
        self._load_alarm_settings()
        self.build_ui()
        self._init_alarm_tray()
        self._alarm_watch = QTimer(self)
        self._alarm_watch.setInterval(15_000)
        self._alarm_watch.timeout.connect(self._evaluate_alarms)
        self._alarm_watch.start()
        self.parameters_tab.load_db_config_from_settings()
        try:
            self.system_status.refresh_db_now()
        except Exception:
            pass
        QTimer.singleShot(100, self._auto_start_all)

    def minimumSizeHint(self):
        """Never ask the window manager for a size wider than this monitor."""
        hint = super().minimumSizeHint()
        cap_w, cap_h = client_cap(self)
        return QSize(min(int(hint.width()), cap_w), min(int(hint.height()), cap_h))

    def event(self, event):
        result = super().event(event)
        # A layout pass can raise the minimum above the screen. Put the cap
        # back before the window manager maximises to that minimum.
        if (
            event.type() == QEvent.Type.LayoutRequest
            and not self._work_area_guard
            and self._work_area_filled
        ):
            self._work_area_guard = True
            try:
                cap_w, cap_h = client_cap(self)
                if self.minimumWidth() > cap_w or self.minimumHeight() > cap_h:
                    self.setMinimumSize(
                        min(self.minimumWidth(), cap_w),
                        min(self.minimumHeight(), cap_h),
                    )
                if self.maximumWidth() != cap_w or self.maximumHeight() != cap_h:
                    self.setMaximumSize(cap_w, cap_h)
                self._keep_button_bar_visible(cap_h)
            finally:
                self._work_area_guard = False
        return result

    def showEvent(self, event):
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not self._work_area_screen_hooked:
            handle.screenChanged.connect(lambda *_: self._clamp_work_area())
            self._work_area_screen_hooked = True
        if not self._work_area_filled:
            self._work_area_filled = True
            # Twice: the first pass runs before the title-bar size is known.
            QTimer.singleShot(0, self._fill_work_area)
            QTimer.singleShot(300, self._fill_work_area)

    def changeEvent(self, event):
        super().changeEvent(event)
        if self._work_area_guard:
            return
        if event.type() == QEvent.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMaximized:
                # Snap to this monitor. A second pass catches the window
                # manager if it applies a wider size after we have snapped.
                QTimer.singleShot(0, self._fill_work_area)
                # The compositor may put the frame back over the taskbar
                # a moment later. Snap to the usable screen again.
                QTimer.singleShot(80, self._fill_work_area)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_work_area_clamp()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_work_area_clamp()

    def _schedule_work_area_clamp(self):
        if self._work_area_guard or self._work_area_clamp_pending:
            return
        if not self._work_area_filled:
            return
        self._work_area_clamp_pending = True
        QTimer.singleShot(0, self._clamp_work_area)

    def _fill_work_area(self):
        """Snap the window to this monitor's usable resolution."""
        self._apply_work_area(fill=True)

    def _clamp_work_area(self):
        self._work_area_clamp_pending = False
        self._apply_work_area(fill=False)

    def _keep_button_bar_visible(self, cap_h: int) -> None:
        """Keep Refresh / Help / Close inside the window, above the taskbar.

        A tall page would otherwise stretch the window past the screen and
        lay that button bar out below the visible area.
        """
        bar = getattr(self, "status_bar", None)
        if bar is None or cap_h < 1:
            return
        bar.setVisible(True)
        bar_h = max(int(bar.sizeHint().height()), 28)
        room = max(160, int(cap_h) - bar_h)
        central = self.centralWidget()
        if central is None:
            return
        if central.minimumHeight() > room:
            central.setMinimumHeight(0)
        if central.maximumHeight() != room:
            central.setMaximumHeight(room)

    def _apply_work_area(self, *, fill: bool):
        if self._work_area_guard:
            return
        self._work_area_guard = True
        try:
            _cap_w, cap_h = client_cap(self)
            self._keep_button_bar_visible(cap_h)
            fit_window_to_work_area(self, fill=fill)
            # The frame may now include a title bar. Cap again so the
            # button bar is still inside the shorter client.
            _cap_w, cap_h = client_cap(self)
            self._keep_button_bar_visible(cap_h)
            if self.height() > cap_h:
                self.resize(min(self.width(), _cap_w), cap_h)
        except Exception as exc:
            _log.warn("App", f"Could not keep the window above the taskbar: {exc}")
        finally:
            self._work_area_guard = False

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
        self.set_status("Starting up — connecting to all services...")
        self.growatt_tab.auto_start()
        self.battery_tab.auto_start()
        self.octopus_tab.auto_start()
        self.forecasts_tab.auto_start()
        self.agile_prices_tab.auto_start()
        self.shadow_trial_tab.auto_start()
        self.octopus_live_tab.auto_start()
        self.tasmota_tab.auto_start()
        self.apply_auto_refresh_from_params()
        _log.info("App", "All services started")

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
        # Tasmota keeps whatever poll interval is saved on its own tab; the
        # shared cycle only decides whether periodic polling runs at all.
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

    def show_main_page(self, page_widget):
        """Select a main page, switching group first if it lives in another group."""
        if page_widget is None:
            return False
        target_group = None
        for _key, attr, _title, gid, _upd in _MAIN_TAB_BAR_REGISTRY:
            if getattr(self, attr, None) is page_widget:
                target_group = gid
                break
        if target_group is None:
            return False
        if getattr(self, "_active_tab_group", None) != target_group:
            if not hasattr(self, "_last_page_by_group"):
                self._last_page_by_group = {}
            self._last_page_by_group[target_group] = page_widget
            self._active_tab_group = target_group
            QSettings("PowerModel", "EnergyDashboard2").setValue(
                "tabs/active_group", target_group,
            )
            strip = getattr(self, "_tab_group_strip", None)
            if strip is not None:
                strip.set_active_group(target_group)
            self._rebuild_main_tab_bar()
        elif self.tabs.indexOf(page_widget) < 0:
            # Page was hidden via Setup visibility — rebuild won't include it.
            return False
        else:
            self.tabs.setCurrentWidget(page_widget)
        if self.tabs.indexOf(page_widget) >= 0:
            self.tabs.setCurrentWidget(page_widget)
            return True
        return False

    def _ensure_main_tab_group_strip(self):
        """Amber group strip in the tab-bar corner (same row; no extra height)."""
        strip = getattr(self, "_tab_group_strip", None)
        if strip is not None:
            return strip
        strip = MainTabGroupStrip(_MAIN_TAB_GROUPS, self.tabs)
        strip.groupSelected.connect(self._on_main_tab_group_selected)
        self.tabs.setCornerWidget(strip, Qt.Corner.TopLeftCorner)
        self._tab_group_strip = strip
        # Always open on Dashboards. A saved group is only for switches
        # during this session, not for the next launch.
        self._active_tab_group = strip.set_active_group("usage")
        QSettings("PowerModel", "EnergyDashboard2").setValue(
            "tabs/active_group", "usage",
        )
        return strip

    def _on_main_tab_group_selected(self, group_id):
        """Switch group: show that group's pages on the right of the strip."""
        if not group_id or group_id == getattr(self, "_active_tab_group", None):
            return
        # Remember the page left behind in the previous group.
        prev_w = self.tabs.currentWidget()
        prev_g = getattr(self, "_active_tab_group", None)
        if prev_g and prev_w is not None:
            if not hasattr(self, "_last_page_by_group"):
                self._last_page_by_group = {}
            self._last_page_by_group[prev_g] = prev_w
        self._active_tab_group = group_id
        QSettings("PowerModel", "EnergyDashboard2").setValue(
            "tabs/active_group", group_id,
        )
        strip = getattr(self, "_tab_group_strip", None)
        if strip is not None:
            strip.set_active_group(group_id)
        self._rebuild_main_tab_bar()

    def _rebuild_main_tab_bar(self):
        """Rebuild page tabs for the active group from registry + QSettings."""
        self._ensure_main_tab_group_strip()
        s = QSettings("PowerModel", "EnergyDashboard2")
        group_id = getattr(self, "_active_tab_group", None)
        if not group_id:
            group_id = _MAIN_TAB_GROUPS[0][0]
            self._active_tab_group = group_id
        bar = self.tabs
        prev = bar.currentWidget()
        prefer = None
        by_group = getattr(self, "_last_page_by_group", None) or {}
        prefer = by_group.get(group_id)
        bar.blockSignals(True)
        try:
            while bar.count() > 0:
                bar.removeTab(0)
            for key, attr, title, gid, updateable in _MAIN_TAB_BAR_REGISTRY:
                if gid != group_id:
                    continue
                if key is None:
                    visible = True
                else:
                    visible = s.value(f"tabs/visible/{key}", True, type=bool)
                if visible:
                    w = getattr(self, attr)
                    bar.addTab(w, title)
                    w.setProperty("_pm_tab_updateable", bool(updateable))
        finally:
            bar.blockSignals(False)
        if prefer is not None and bar.indexOf(prefer) >= 0:
            bar.setCurrentWidget(prefer)
        elif prev is not None and bar.indexOf(prev) >= 0:
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

        self._alarm_banner = QLabel("")
        self._alarm_banner.setWordWrap(False)
        self._alarm_banner.setTextFormat(Qt.RichText)
        self._alarm_banner.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._alarm_banner.setCursor(QCursor(Qt.PointingHandCursor))
        self._alarm_banner.setToolTip("Click for alarm detail and recent history.")
        self._alarm_banner.setStyleSheet(
            "color: #6c7086; font-size: 11px; padding: 0 8px 0 0;"
        )
        self._alarm_banner.hide()
        self._alarm_banner.installEventFilter(self)
        meta_row.addWidget(self._alarm_banner, 0)

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
        self.tabs.setObjectName("mainPageTabs")
        self._fresh_tab_bar = FreshnessTabBar(self.tabs)
        self.tabs.setTabBar(self._fresh_tab_bar)
        main_layout.addWidget(self.tabs, 1)

        from energy_dashboard.ui.system_status_bar import SystemStatusBar

        self.system_status = SystemStatusBar(self.data_logger, parent=central)
        main_layout.addWidget(self.system_status, 0)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # ── Bottom-right action cluster ────────────────────────────────
        # addPermanentWidget appends to the right-hand group in
        # left-to-right order:
        # [ Alarms ] 30px [ Refresh Page ] [ Refresh All ] [ Help ] [ Close ]
        # Machine CPU / RAM / DB ingest live in the two-line strip above this bar.
        _ACTION_BTN_WIDTH = 110

        refresh_page_btn = QPushButton("Refresh Page")
        refresh_page_btn.setToolTip(
            "Refresh only the currently selected tab (same action each tab "
            "uses for live data or re-run, e.g. Build plan on Optimiser)."
        )
        refresh_page_btn.setFixedWidth(_ACTION_BTN_WIDTH)
        refresh_page_btn.clicked.connect(self._refresh_current_tab)

        alarms_btn = QPushButton("Alarms")
        alarms_btn.setToolTip("Show active alarms and alarms from this session.")
        alarms_btn.setFixedWidth(_ACTION_BTN_WIDTH)
        alarms_btn.setProperty(PRIMARY_BUTTON_EXEMPT, True)
        alarms_btn.setStyleSheet(_ALARMS_BTN_QSS)
        alarms_btn.clicked.connect(self._show_alarm_dialog)

        refresh_pair = QWidget()
        refresh_pair_row = QHBoxLayout(refresh_pair)
        refresh_pair_row.setContentsMargins(0, 0, 0, 0)
        refresh_pair_row.setSpacing(0)
        refresh_pair_row.addWidget(alarms_btn)
        refresh_pair_row.addSpacing(30)
        refresh_pair_row.addWidget(refresh_page_btn)
        self.status_bar.addPermanentWidget(refresh_pair)

        refresh_all_btn = QPushButton("Refresh All")
        refresh_all_btn.setToolTip(
            "Trigger a one-shot refresh on every tab that supports it "
            "(Growatt, Octopus, Tasmota, Forecasts, Battery, Optimiser…)"
        )
        refresh_all_btn.setFixedWidth(_ACTION_BTN_WIDTH)
        refresh_all_btn.clicked.connect(self._refresh_all_tabs)
        self.status_bar.addPermanentWidget(refresh_all_btn)

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

        self.pv_string_charge_tab = PvStringChargeTab(
            self.growatt_tab, self.set_status, data_logger=self.data_logger,
        )
        self.pv_string_charge_tab.on_data_updated = (
            lambda: self.mark_tab_fresh(self.pv_string_charge_tab)
        )
        self.pv_string_voltage_tab = PvStringVoltageTab(
            self.growatt_tab, self.set_status, data_logger=self.data_logger,
        )
        self.pv_string_voltage_tab.on_data_updated = (
            lambda: self.mark_tab_fresh(self.pv_string_voltage_tab)
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
        self.pv_string_charge_tab.forecasts_tab = self.forecasts_tab

        self.pot_issues_tab = PotIssuesTab(
            self.forecasts_tab, self.data_logger, self.growatt_tab, self.set_status,
        )
        self.pot_issues_tab.on_data_updated = (
            lambda: self.mark_tab_fresh(self.pot_issues_tab)
        )

        self.agile_prices_tab = AgileSpotPricesTab(self.forecasts_tab, self.set_status)
        self.agile_prices_tab.on_data_updated = (
            lambda: self.mark_tab_fresh(self.agile_prices_tab)
        )

        self.agile_year_tab = AgileYearTab(self.forecasts_tab, self.set_status)
        self.agile_year_tab.on_data_updated = (
            lambda: self.mark_tab_fresh(self.agile_year_tab)
        )

        self.roof_layout_tab = RoofLayoutTab(
            self.forecasts_tab, self.set_status, dash=self,
        )
        self.roof_layout_tab.on_data_updated = (
            lambda: self.mark_tab_fresh(self.roof_layout_tab)
        )

        self.panel_database_tab = PanelDatabaseTab(self.set_status, dash=self)
        self.panel_database_tab.on_data_updated = (
            lambda: self.mark_tab_fresh(self.panel_database_tab)
        )
        # Let Forecasts resolve multi-plane roof faces via the dashboard.
        self.forecasts_tab.dash = self

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

        self.grott_align_tab = GrottApiAlignTab(self.growatt_tab, self.set_status)
        self.grott_align_tab.on_data_updated = (
            lambda: self.mark_tab_fresh(self.grott_align_tab)
        )

        self.octopus_live_tab = OctopusLiveTab(
            self.set_status, data_logger=self.data_logger, app_params=self.app_params,
        )
        self.octopus_live_tab.on_data_updated = (
            lambda: self.mark_tab_fresh(self.octopus_live_tab)
        )

        self.connectivity_tab = ConnectivityStatusTab(self)

        self.grott_setup_tab = GrottSetupTab(self)

        self.command_sim_tab = CommandSimTab(self.set_status)

        self.db_viewer_tab = DatabaseViewerTab(self)

        self.export_tab = ExportTab(
            self.app_params, self.data_logger, self.set_status,
        )
        self.export_tab.on_data_updated = lambda: self.mark_tab_fresh(self.export_tab)

        self.console_tab = ConsoleTab(self)

        self.dump_logs_tab = DumpLogsTab(self)

        self.bug_tracker_tab = BugTrackerTab(self)

        self.alarm_defs_tab = AlarmDefsTab(self)

        self.parameters_tab = ParametersTab(self)

        self.license_tab = LicenseTab()

        # GrottTab connects at construct time — re-apply after Setup has healed
        # empty grott_mqtt_host from EMQX / Tasmota MQTT credentials.
        try:
            self.growatt_tab.apply_grott_settings()
        except Exception:
            pass
        QTimer.singleShot(1500, self._reapply_grott_after_setup)

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

        # Banner countdown every 1s; tab-colour fade is slower (20 min) so
        # repaint the hatch/colours only every ~15s (plus on mark_tab_fresh).
        self._tab_last_update = {}
        self._tab_freshness_tick = 0
        self._tab_freshness_dirty = False
        self._tab_color_timer = QTimer(self)
        self._tab_color_timer.setInterval(1000)
        self._tab_color_timer.timeout.connect(self._on_tab_freshness_tick)
        self._tab_color_timer.start()
        self._refresh_tab_freshness()

        # Green primary motif on every action button (Toggle exempt via property).
        _style_all_primary_buttons(self)

        # Electric-blue 90×20 spin fields (Export p/kWh reference) on all tabs.
        apply_spin_field_motif_tree(self)
        # Same slight-grey fill on plain line edits / combos / time fields.
        apply_input_field_fill_tree(self)

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
            ft._refresh_locale_label(force=True)
        # Second pass after Setup has finished pushing solar coords into Forecasts.
        QTimer.singleShot(800, self._retry_banner_locale)

    def _retry_banner_locale(self):
        ft = getattr(self, "forecasts_tab", None)
        if ft is not None:
            try:
                ft._refresh_locale_label(force=False)
            except Exception:
                pass

    # ── Tab freshness colour coding ────────────────────────────────────

    def mark_tab_fresh(self, tab_widget):
        """Record that `tab_widget` has just received fresh data.

        Repainting is left to the freshness tick below: MQTT feeds call this
        about once a second per source, and restyling the whole tab bar on
        every call was a large slice of the UI jank.
        """
        if tab_widget is None:
            return
        self._tab_last_update[tab_widget] = datetime.now()
        self._tab_freshness_dirty = True

    def _on_tab_freshness_tick(self):
        """1 Hz: update banner countdown; only occasionally repaint tab colours."""
        self._tab_freshness_tick = int(getattr(self, "_tab_freshness_tick", 0)) + 1
        self._update_refresh_cycle_button()
        dirty = bool(getattr(self, "_tab_freshness_dirty", False))
        if self._tab_freshness_tick % 15 == 0 or (dirty and self._tab_freshness_tick % 5 == 0):
            self._tab_freshness_dirty = False
            self._refresh_tab_freshness(update_banner=False)

    def _refresh_tab_freshness(self, *, update_banner=True):
        """Page tabs: static=blue; updateable=green→black over 20 min (white on black when stale)."""
        bar = getattr(self, '_fresh_tab_bar', None) or self.tabs.tabBar()
        now = datetime.now()
        bgs = {}
        flags = {}
        fgs = {}
        last_map = getattr(self, "_tab_last_update", None) or {}
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            updateable = True
            if widget is not None:
                prop = widget.property("_pm_tab_updateable")
                if prop is not None:
                    updateable = bool(prop)
                else:
                    for _k, attr, _t, _g, upd in _MAIN_TAB_BAR_REGISTRY:
                        if getattr(self, attr, None) is widget:
                            updateable = bool(upd)
                            break
            flags[i] = updateable
            if not updateable:
                bgs[i] = _TAB_PAGE_STATIC
                fgs[i] = _contrasting_tab_text(_TAB_PAGE_STATIC)
            else:
                last = last_map.get(widget)
                bgs[i] = _tab_freshness_background(last, now)
                fgs[i] = _tab_freshness_text_color(last, now)
        if hasattr(bar, 'set_updateable_flags'):
            bar.set_updateable_flags(flags)
        if hasattr(bar, 'set_freshness_backgrounds'):
            bar.set_freshness_backgrounds(bgs)
        for i, fg in fgs.items():
            bar.setTabTextColor(i, QColor(fg))
        bar.update()

        if update_banner:
            self._update_refresh_cycle_button()

    # ── Refresh cycle button ───────────────────────────────────────────

    _LIVE_REFRESH_TAB_ATTRS = (
        ("growatt_tab", "Growatt"),
        ("octopus_live_tab", "Octopus Live"),
        ("tasmota_tab", "Tasmota"),
    )

    # Allowance on top of each source's own cadence before it counts as late.
    _LIVE_REFRESH_GRACE_S = 15.0

    @staticmethod
    def _format_age_short(seconds):
        """Compact age for the banner pill (e.g. 12s, 3m 05s, 1h 02m)."""
        if seconds is None:
            return "--"
        s = max(0, int(seconds))
        if s < 60:
            return f"{s}s"
        if s < 3600:
            return f"{s // 60}m {s % 60:02d}s"
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}h {m:02d}m"

    def _live_source_states(self):
        """Per-source freshness for the banner pill.

        Each live tab declares its own cadence through
        ``live_refresh_expectation()`` returning (active, seconds, detail), so
        an MQTT-driven tab is judged against its push rate rather than the
        shared auto-refresh interval, and a source that is switched off is
        reported as inactive instead of permanently late.
        """
        now = datetime.now()
        p = self.app_params
        fallback = float(max(5, int(getattr(p, "auto_refresh_seconds", 60))))
        enabled = bool(getattr(p, "auto_refresh_enabled", False))
        last_map = getattr(self, "_tab_last_update", None) or {}
        states = []
        for attr, label in self._LIVE_REFRESH_TAB_ATTRS:
            w = getattr(self, attr, None)
            if w is None:
                continue
            active, window, detail = enabled, fallback, ""
            fn = getattr(w, "live_refresh_expectation", None)
            if callable(fn):
                try:
                    active, window, detail = fn()
                except Exception:
                    active, window, detail = enabled, fallback, ""
            window = max(15.0, float(window)) + self._LIVE_REFRESH_GRACE_S
            last = last_map.get(w)
            age = None if last is None else (now - last).total_seconds()
            states.append({
                "label": label,
                "age": age,
                "window": window,
                "active": bool(active),
                "detail": str(detail or ""),
            })
        return states

    def _live_refresh_age_and_completeness(self):
        """Return (oldest active age, fresh_count, active_total, late_labels).

        The age is the *oldest* active source, not the newest: taking the
        newest let a 1 Hz MQTT feed report "Last 2s" while another live tab
        had not updated for hours.
        """
        states = [s for s in self._live_source_states() if s["active"]]
        ages = [s["age"] for s in states if s["age"] is not None]
        fresh = 0
        late = []
        for s in states:
            if s["age"] is not None and s["age"] <= s["window"]:
                fresh += 1
            else:
                late.append(s["label"])
        since = max(ages) if ages else None
        return since, fresh, len(states), late

    def _live_refresh_tooltip(self):
        """Per-source breakdown so a 'late' pill can be diagnosed on hover."""
        lines = [
            "Click to cycle the shared auto-refresh interval:",
            "Auto 10s → 30s → 60s → 180s → 300s → 600s → Manual only.",
            "",
            "Live sources (age · expected cadence):",
        ]
        for s in self._live_source_states():
            detail = f" — {s['detail']}" if s["detail"] else ""
            if not s["active"]:
                lines.append(f"  {s['label']}: inactive{detail}")
                continue
            age_txt = "never" if s["age"] is None else self._format_age_short(s["age"])
            state = (
                "late"
                if s["age"] is None or s["age"] > s["window"]
                else "ok"
            )
            lines.append(
                f"  {s['label']}: {age_txt} · expects ≤ "
                f"{self._format_age_short(s['window'])} · {state}{detail}"
            )
        lines.append("")
        lines.append(
            "MQTT sources are push-driven, so the shared interval does not "
            "change how often they arrive."
        )
        return "\n".join(lines)

    def _build_refresh_cycle_card(self, ban_layout):
        """Build the right-most banner row: two-line auto-refresh pill + tab › strip."""
        wrap = QWidget()
        wrap.setObjectName("liveBannerRefreshWrap")
        wrap.setStyleSheet(f"#liveBannerRefreshWrap {{ background-color: {_DARK_BG}; }}")
        wrap.setFixedHeight(42)
        wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        hl = QHBoxLayout(wrap)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(2)

        pill = BannerRefreshCyclePill()
        pill.clicked.connect(self._advance_refresh_cycle)
        hl.addWidget(pill, 1)

        self._banner_tab_nav = BannerTabScrollHold()
        hl.addWidget(self._banner_tab_nav, 0)

        ban_layout.addWidget(wrap)
        return pill

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
        """Redraw the two-line refresh pill: mode, clock, last, next, completeness."""
        if not hasattr(self, '_ban_refresh'):
            return
        i = self._current_refresh_cycle_index()
        sec, _color, label = _REFRESH_CYCLE[i]
        now_s = datetime.now().strftime("%H:%M:%S")
        since_s, fresh_n, total_n, late = self._live_refresh_age_and_completeness()
        last_txt = self._format_age_short(since_s)
        if since_s is None and total_n > 0:
            last_txt = "never"
        if sec == 0:
            next_txt = "—"
            mode_txt = "Manual"
        else:
            rem_s = self._soonest_auto_refresh_seconds()
            if rem_s is None:
                rem_s = sec
            next_txt = self._format_age_short(rem_s)
            mode_txt = label  # e.g. Auto 30s
        if total_n > 0:
            pct = int(round(100.0 * fresh_n / total_n))
            complete_detail = f"{fresh_n}/{total_n} ({pct}%)"
        else:
            complete_detail = "no live source active"
        line1 = f"Mode {mode_txt}  ·  Now {now_s}  ·  Oldest {last_txt}"
        line2 = f"Next {next_txt}  ·  Complete {complete_detail}"
        if late:
            line2 += "  ·  late: " + ", ".join(late)
        self._ban_refresh.set_lines(line1, line2)
        self._ban_refresh.set_detail_tooltip(self._live_refresh_tooltip())
        # Do not re-apply setStyleSheet on every tick — that forces expensive
        # style recalculation and was a major source of UI jank.

    def _on_main_tab_changed(self, index):
        w = self.tabs.widget(index)
        group_id = getattr(self, "_active_tab_group", None)
        if group_id and w is not None:
            if not hasattr(self, "_last_page_by_group"):
                self._last_page_by_group = {}
            self._last_page_by_group[group_id] = w
        if w is self.combined_tab:
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
        self._evaluate_alarms()
        self._log_growatt_data()
        self._maybe_upload_community_outputs()
        self.mark_tab_fresh(self.growatt_tab)
        # Combined Dashboard mirrors the live Growatt feed, so it's "fresh"
        # whenever Growatt is fresh.
        if hasattr(self, 'combined_tab'):
            self.mark_tab_fresh(self.combined_tab)
        pst = getattr(self, "pv_string_charge_tab", None)
        if pst is not None:
            try:
                pst.on_growatt_live_update()
            except Exception:
                pass
        psv = getattr(self, "pv_string_voltage_tab", None)
        if psv is not None:
            try:
                psv.on_growatt_live_update()
            except Exception:
                pass
        bt = getattr(self, "battery_tab", None)
        if bt is not None and hasattr(bt, "sync_capacity_from_live"):
            try:
                bt.sync_capacity_from_live()
            except Exception:
                pass
        # Connectivity has its own 15s timer — do not rebuild that tab on every
        # Growatt/Grott update (that was freezing the UI with sync DB work).

    def _load_alarm_settings(self):
        s = QSettings("PowerModel", "EnergyDashboard2")
        self.alarm_monitor.configure(
            enabled=s.value("alarms/enabled", True, type=bool),
            desktop_enabled=s.value("alarms/desktop", True, type=bool),
            hold_minutes=float(s.value("alarms/hold_minutes", DEFAULT_HOLD_MINUTES)),
            pv_min_kw=float(s.value("alarms/pv_min_kw", DEFAULT_PV_MIN_KW)),
            notify_cooldown_s=float(
                s.value("alarms/notify_cooldown_s", DEFAULT_NOTIFY_COOLDOWN_S)
            ),
        )

    def apply_alarm_settings_from_ui(
        self,
        *,
        enabled: bool,
        desktop: bool,
        hold_minutes: float,
        pv_min_kw: float,
    ):
        s = QSettings("PowerModel", "EnergyDashboard2")
        s.setValue("alarms/enabled", bool(enabled))
        s.setValue("alarms/desktop", bool(desktop))
        s.setValue("alarms/hold_minutes", float(hold_minutes))
        s.setValue("alarms/pv_min_kw", float(pv_min_kw))
        s.sync()
        self.alarm_monitor.configure(
            enabled=enabled,
            desktop_enabled=desktop,
            hold_minutes=hold_minutes,
            pv_min_kw=pv_min_kw,
        )
        if not enabled:
            self.alarm_monitor.clear()
            self._apply_alarm_banner([])

    def _init_alarm_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._alarm_tray = None
            return
        try:
            tray = QSystemTrayIcon(self)
            tray.setIcon(powermon_tray_icon())
            tray.setToolTip("PowerMon — right-click for broker, health, and alarms")
            menu = QMenu(self)
            self._tray_stat_labels = []
            for _ in range(4):
                lab = TrayInfoLine(menu)
                act = QWidgetAction(menu)
                act.setDefaultWidget(lab)
                menu.addAction(act)
                self._tray_stat_labels.append(lab)
            menu.addSeparator()
            self._tray_act_broker = menu.addAction("Start Broker")
            self._tray_act_broker.triggered.connect(self._tray_toggle_broker)
            menu.addAction("Show system health").triggered.connect(self._tray_show_health)
            menu.addAction("Settings").triggered.connect(self._tray_show_settings)
            menu.addAction("Alarms").triggered.connect(self._tray_show_alarms)
            menu.addSeparator()
            menu.addAction("Quit PowerMon").triggered.connect(self._tray_quit_app)
            style_tray_info(menu, self._tray_stat_labels)
            menu.aboutToShow.connect(self._tray_refresh_menu)
            tray.setContextMenu(menu)
            tray.activated.connect(self._tray_activated)
            tray.setVisible(True)
            tray.messageClicked.connect(self._show_alarm_dialog)
            self._alarm_tray = tray
            self._tray_menu = menu
            QTimer.singleShot(800, self._tray_probe_broker)
        except Exception as e:
            _log.warn("Alarms", f"System tray unavailable: {e}")
            self._alarm_tray = None

    def closeEvent(self, event):
        """Closing the window leaves PowerMon in the tray. Quit is on the menu."""
        if self._tray_quit or self._alarm_tray is None:
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self._tray_hide_hinted:
            self._tray_hide_hinted = True
            try:
                self._alarm_tray.showMessage(
                    "PowerMon",
                    "Still running in the tray. Right-click the icon to open "
                    "it again, or choose Quit PowerMon.",
                    QSystemTrayIcon.MessageIcon.Information,
                    8000,
                )
            except Exception:
                pass

    def _tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def _tray_refresh_menu(self):
        status = getattr(getattr(self, "system_status", None), "last_status", None)
        lines = tray_database_lines(status)
        for lab, text in zip(self._tray_stat_labels, lines):
            lab.setText(text)
        self._tray_apply_broker_label()
        self._tray_probe_broker()

    def _tray_apply_broker_label(self):
        act = getattr(self, "_tray_act_broker", None)
        if act is None:
            return
        running = self._tray_broker_is_running()
        if running is True:
            act.setText("Stop Broker")
        elif running is False:
            act.setText("Start Broker")
        else:
            act.setText("Start/Stop Broker")

    def _tray_broker_is_running(self):
        status = self._tray_broker_status
        if not isinstance(status, dict):
            return None
        for key in ("primary", "system_unit", "user_unit"):
            unit = status.get(key) or {}
            if unit.get("active_state") == "active":
                return True
        installed = any(
            (status.get(key) or {}).get("installed")
            for key in ("primary", "system_unit", "user_unit")
        )
        if installed:
            return False
        return None

    def _tray_probe_broker(self):
        if self._tray_probe_busy:
            return
        self._tray_probe_busy = True

        def work():
            from energy_dashboard.services.systemd_status import (
                collect_collector_service_status,
            )
            url = ""
            try:
                url = self.parameters_tab.ed_broker_url.text().strip()
            except Exception:
                url = ""
            try:
                status = collect_collector_service_status(url or None)
            except Exception as exc:
                status = {"error": str(exc)}
            self._tray_inv.invoke(lambda s=status: self._tray_probe_done(s))

        threading.Thread(target=work, daemon=True).start()

    def _tray_probe_done(self, status):
        self._tray_probe_busy = False
        if isinstance(status, dict):
            self._tray_broker_status = status
        self._tray_apply_broker_label()

    def _tray_toggle_broker(self):
        if self._tray_broker_busy:
            return
        running = self._tray_broker_is_running()
        status = self._tray_broker_status
        if running is None or not isinstance(status, dict) or "system_unit" not in status:
            self._tray_probe_broker()
            self._tray_ensure_visible()
            QMessageBox.information(
                self,
                "Broker",
                "Still checking whether the broker service is installed. "
                "Open the menu again in a moment.",
            )
            return
        action = "stop" if running else "start"
        self._tray_broker_busy = True

        def work():
            from energy_dashboard.services.systemd_status import (
                control_collector_service,
            )
            try:
                ok, msg = control_collector_service(action, status)
            except Exception as exc:
                ok, msg = False, str(exc)
            self._tray_inv.invoke(lambda o=ok, m=msg: self._tray_broker_done(o, m))

        threading.Thread(target=work, daemon=True).start()

    def _tray_broker_done(self, ok: bool, msg: str):
        self._tray_broker_busy = False
        self._tray_probe_busy = False
        self._tray_probe_broker()
        if not ok:
            self._tray_ensure_visible()
            QMessageBox.warning(self, "Broker", msg or "Could not change the broker.")
        elif self.isVisible():
            self.set_status(msg or "Broker updated.")
        elif self._alarm_tray is not None:
            self._alarm_tray.showMessage(
                "Broker", msg or "Broker updated.",
                QSystemTrayIcon.MessageIcon.Information, 5000,
            )

    def _tray_ensure_visible(self):
        if not self.isVisible():
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def _tray_show_health(self):
        self._tray_ensure_visible()
        ss = getattr(self, "system_status", None)
        lines = list(tray_database_lines(
            getattr(ss, "last_status", None) if ss is not None else None
        ))
        if ss is not None:
            for lab in (
                getattr(ss, "cpu_label", None),
                getattr(ss, "memory_label", None),
            ):
                text = lab.text().strip() if lab is not None else ""
                if text:
                    lines.append(text)
        QMessageBox.information(self, "System health", "\n".join(lines))

    def _tray_show_settings(self):
        self._tray_ensure_visible()
        QMessageBox.information(
            self,
            "Settings",
            "Settings from the tray icon are not available yet. "
            "Use Setup & Info in the dashboard.",
        )

    def _tray_show_alarms(self):
        self._tray_ensure_visible()
        self._show_alarm_dialog()

    def _tray_quit_app(self):
        self._tray_quit = True
        QApplication.quit()

    def _reapply_grott_after_setup(self):
        """Second Grott connect after Setup has loaded/healed broker settings."""
        gt = getattr(self, "growatt_tab", None)
        if gt is None:
            return
        try:
            gt.apply_grott_settings()
        except Exception as exc:
            try:
                _log.warn("Grott", f"Re-apply after Setup failed: {exc}")
            except Exception:
                pass

    def _evaluate_alarms(self):
        gt = getattr(self, "growatt_tab", None)
        if gt is None:
            return
        d = gt.mix_status_data or {}
        live = {}
        try:
            live = gt.get_live_data_summary() or {}
        except Exception:
            live = {}
        thr = float(getattr(self.app_params, "battery_low_soc_threshold_pct", 10) or 10)
        grott_expected = False
        grott_connected = False
        grott_fresh = False
        grott_age_s = None
        grott_fresh_s = 120.0
        try:
            grott_expected = bool(gt._uses_grott())
            gs = gt.grott_status() if grott_expected else {}
            grott_connected = bool(gs.get("connected"))
            grott_age_s = gs.get("age_s")
            grott_fresh_s = max(15, int(gt._grott_config().get("fresh_s", 120) or 120))
            try:
                grott_fresh = (
                    grott_age_s is not None
                    and float(grott_age_s) <= float(grott_fresh_s)
                )
            except (TypeError, ValueError):
                grott_fresh = False
        except Exception:
            grott_expected = bool(getattr(gt, "_uses_grott", lambda: False)())
        comms_lost = False
        comms_reason = ""
        try:
            comms_lost = bool(live.get("comms_lost"))
            comms_reason = str(live.get("comms_reason") or "")
        except Exception:
            pass
        db_logging = False
        try:
            db_logging = self.data_logger._primary_storage_backend() is not None
        except Exception:
            db_logging = False
        db_st = getattr(getattr(self, "system_status", None), "last_status", None)
        db_connected = None if db_st is None else bool(db_st.connected)
        db_error = (getattr(db_st, "error", "") or "") if db_st is not None else ""
        if db_st is not None and not db_error:
            db_error = getattr(db_st, "ingest_error", "") or ""
        db_engine = (getattr(db_st, "engine", "") or "") if db_st is not None else ""
        db_rows_15m = None
        if db_st is not None and db_st.connected:
            try:
                db_rows_15m = int(db_st.rows_15m or 0)
            except (TypeError, ValueError):
                db_rows_15m = 0
        growatt_writing = False
        if grott_expected:
            growatt_writing = bool(grott_fresh)
        elif live:
            growatt_writing = not comms_lost
        tas = {}
        try:
            tt = getattr(self, "tasmota_tab", None)
            if tt is not None and hasattr(tt, "alarm_snapshot"):
                tas = tt.alarm_snapshot() or {}
        except Exception:
            tas = {}
        tas_offline = list(tas.get("offline") or [])
        tas_mqtt = bool(tas.get("mqtt_mode"))
        tas_mqtt_ok = bool(tas.get("mqtt_connected"))
        tas_known = int(tas.get("known") or 0)
        tasmota_writing = tas_known > 0 and (
            (tas_mqtt and tas_mqtt_ok) or ((not tas_mqtt) and tas_known > len(tas_offline))
        )
        hits = self.alarm_monitor.evaluate(
            soc_pct=live.get("soc", d.get("SOC")),
            pv_kw=live.get("pv_power", d.get("ppv")),
            charge_kw=d.get("chargePower"),
            discharge_kw=d.get("pdisCharge1"),
            load_kw=live.get("load_power", d.get("pLocalLoad")),
            grid_import_kw=d.get("pactouser"),
            soc_threshold_pct=thr,
            grott_expected=grott_expected,
            grott_connected=grott_connected,
            grott_fresh=grott_fresh,
            grott_age_s=grott_age_s,
            grott_fresh_s=grott_fresh_s,
            db_logging_enabled=db_logging,
            db_connected=db_connected,
            db_error=db_error,
            db_engine=db_engine,
            db_rows_15m=db_rows_15m,
            growatt_writing=growatt_writing,
            tasmota_writing=tasmota_writing,
            inverter_comms_lost=comms_lost,
            inverter_comms_reason=comms_reason,
            tasmota_mqtt_expected=tas_mqtt,
            tasmota_mqtt_connected=tas_mqtt_ok,
            tasmota_offline=tas_offline,
        )
        self._log_grott_lost_edge(hits, grott_connected, grott_age_s)
        self._apply_alarm_banner(hits)
        try:
            ct = getattr(self, "connectivity_tab", None)
            if ct is not None and hasattr(ct, "set_diagram_alarms"):
                ct.set_diagram_alarms(hits)
        except Exception:
            pass
        for hit in hits:
            if hit.should_notify:
                self._desktop_alarm_notify(hit)

    def _log_grott_lost_edge(self, hits, grott_connected, grott_age_s) -> None:
        """Persist Grott stale / recover into connectivity_events (Show history)."""
        active = any(getattr(h, "key", "") == "grott_lost" for h in (hits or []))
        was = bool(getattr(self, "_grott_lost_event_active", False))
        if active == was:
            return
        self._grott_lost_event_active = active
        try:
            from energy_dashboard.db.connectivity_events import log_connectivity_event
            age = grott_age_s
            try:
                age_txt = f"{float(age):.0f}s since last live frame" if age is not None else "no live frame yet"
            except (TypeError, ValueError):
                age_txt = "age unknown"
            mqtt = "MQTT connected" if grott_connected else "MQTT disconnected"
            log_connectivity_event(
                getattr(self, "data_logger", None),
                service_key="grott_mqtt",
                service_label="Growatt local (Grott MQTT)",
                event_type="warn" if active else "recover",
                state_key="warn" if active else "ok",
                state_text="stale" if active else "fresh",
                detail=(
                    f"{mqtt}; {age_txt}. Shine often quiets ~11 min after reconnect."
                    if active
                    else f"{mqtt}; live Grott telemetry resumed ({age_txt})."
                ),
            )
        except Exception:
            pass

    def _apply_alarm_banner(self, hits):
        if not hasattr(self, "_alarm_banner"):
            return
        if not hits:
            self._alarm_banner.hide()
            self._alarm_banner.setText("")
            return
        summary = self.alarm_monitor.banner_summary(hits)
        crit = any(h.severity == "critical" for h in hits)
        col = "#f38ba8" if crit else "#fab387"
        self._alarm_banner.setText(
            f"<span style='color:{col}; font-weight:600;'>ALARM · {summary}</span>"
        )
        tip_lines = []
        for h in hits:
            tip_lines.append(h.title)
            tip_lines.append(h.detail)
            tip_lines.append("")
        tip_lines.append("Click for full history.")
        self._alarm_banner.setToolTip("\n".join(tip_lines).strip())
        self._alarm_banner.show()

    def _desktop_alarm_notify(self, hit):
        tray = getattr(self, "_alarm_tray", None)
        if tray is None or not self.alarm_monitor.desktop_enabled:
            return
        icon = (
            QSystemTrayIcon.MessageIcon.Critical
            if hit.severity == "critical"
            else QSystemTrayIcon.MessageIcon.Warning
        )
        try:
            tray.showMessage(hit.title, hit.detail, icon, 12000)
        except Exception as e:
            _log.warn("Alarms", f"Desktop notify failed: {e}")

    def eventFilter(self, obj, event):
        if (
            obj is getattr(self, "_alarm_banner", None)
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.LeftButton
        ):
            self._show_alarm_dialog()
            return True
        return super().eventFilter(obj, event)

    def _show_alarm_dialog(self):
        mon = self.alarm_monitor
        active = list(mon._active.values())
        lines = []
        if active:
            lines.append("Active now")
            lines.append("─" * 40)
            for h in active:
                lines.append(h.title)
                lines.append(h.detail)
                lines.append("")
        else:
            lines.append("No active alarms.")
            lines.append("")
        if mon.history:
            lines.append("Recent (this session)")
            lines.append("─" * 40)
            for row in mon.history[:12]:
                ts = _time_mod.strftime("%Y-%m-%d %H:%M", _time_mod.localtime(row["wall"]))
                lines.append(f"{ts}  [{row['severity']}]  {row['title']}")
                lines.append(f"  {row['detail']}")
                lines.append("")
        else:
            lines.append("No alarms have fired this session yet.")
        lines.append(
            f"Rules: Grott feed must stay live (~20s if MQTT drops, or after "
            f"Fresh max — often Shine’s ~11 min handshake); inverter reported "
            f"offline by Growatt; logging database unreachable, or no Growatt/"
            f"Tasmota rows for 15 min while devices are live; Tasmota MQTT down "
            f"or named plugs silent; SOC below Setup threshold for "
            f"≥{mon.hold_minutes:.0f} min; or spare PV ≥ {mon.pv_min_kw:.1f} kW "
            f"not charging (same hold). Tray repeats: immediate, then 4×/5 min, "
            f"4×/10 min, 4×/30 min, then hourly. Configure under Setup → Live alarms."
        )
        QMessageBox.information(self, "Alarms", "\n".join(lines))

    def _log_growatt_data(self):
        gt = self.growatt_tab
        d = gt.mix_status_data
        if not d:
            return
        # Never persist a stale GROTT snapshot — that is what filled Aug 19
        # with hundreds of identical rows while the feed was frozen.
        try:
            if gt._uses_grott():
                from energy_dashboard.fetch.grott_mqtt import grott_snapshot_fresh
                snap = gt._grott.snapshot() if getattr(gt, '_grott', None) else None
                fresh_s = max(15, int(gt._grott_config().get('fresh_s', 120) or 120))
                if not grott_snapshot_fresh(snap, fresh_s):
                    return
        except Exception:
            pass
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

    def _maybe_upload_community_outputs(self):
        """Throttle PVOutput Add Status uploads from the latest Growatt snapshot.

        Wonderwatt has no public upload API — it pulls Growatt cloud itself;
        we only keep a share link for forecast compare (Potential Issues / Setup).
        """
        try:
            from energy_dashboard.fetch.pvoutput import (
                load_pvoutput_config,
                should_upload_now,
                upload_from_growatt,
            )
        except Exception:
            return
        cfg = load_pvoutput_config()
        if not cfg.ready or not should_upload_now(cfg):
            return
        gt = self.growatt_tab
        status = getattr(gt, "mix_status_data", None) or {}
        totals = getattr(gt, "mix_totals_data", None) or {}
        if not status:
            return
        # Respect the same Grott-freshness guard as local DB logging.
        try:
            if gt._uses_grott():
                from energy_dashboard.fetch.grott_mqtt import grott_snapshot_fresh
                snap = gt._grott.snapshot() if getattr(gt, "_grott", None) else None
                fresh_s = max(15, int(gt._grott_config().get("fresh_s", 120) or 120))
                if not grott_snapshot_fresh(snap, fresh_s):
                    return
        except Exception:
            pass

        def _run():
            try:
                ok, msg = upload_from_growatt(status, totals, force=False)
                if ok:
                    _log.info("PVOutput", f"upload OK: {msg}")
                elif msg and not msg.startswith("Skipped"):
                    _log.warn("PVOutput", f"upload: {msg}")
            except Exception as exc:
                _log.warn("PVOutput", f"upload failed: {exc}")

        import threading
        threading.Thread(target=_run, daemon=True).start()

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
        # Connectivity has its own 15s timer — do not rebuild on every feed update.

    def _on_tasmota_data_updated(self):
        _ts = QSettings("PowerModel", "EnergyDashboard2")
        if _ts.value("tasmota/use_powermon_broker", False, type=bool):
            self.mark_tab_fresh(self.tasmota_tab)
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
        # Connectivity has its own 15s timer — do not rebuild on every poll.

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
        # Status bar + Saved toast must only touch widgets on the GUI thread.
        app = QApplication.instance()
        if app is not None and QThread.currentThread() is not app.thread():
            QTimer.singleShot(0, self, lambda t=text: self.set_status(t))
            return
        self.status_bar.showMessage(text)
        # Any status that reports a successful save gets a green "Saved" flash.
        try:
            msg = str(text or "")
            if re.search(r"\bsaved\b", msg, re.IGNORECASE):
                self.flash_saved()
        except Exception:
            pass

    def flash_saved(self, text: str = "Saved", *, ms: int = 1600):
        """Brief green on-screen confirmation for Save actions."""
        try:
            from energy_dashboard.ui.toast import flash_saved as _flash
            host = self.centralWidget() if self.centralWidget() is not None else self
            _flash(host, text, ms=ms)
        except Exception:
            pass

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
                _log.warn("Help", f"failed to show Help dialog: {e}")
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
                _log.info("Refresh", f"Refresh Page — {attr}.{method}")
            except Exception:
                pass
            self.set_status(f"Refresh Page: {title}")
        except Exception as e:
            try:
                _log.warn("Refresh", f"Refresh Page — {attr}.{method} failed: {e}")
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
