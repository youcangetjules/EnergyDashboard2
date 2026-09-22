"""
Energy Dashboard — `tabs/growatt.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

import time as _time_mod

from energy_dashboard.common import *
from energy_dashboard.config import (
    GROWATT_TELEMETRY_API,
    GROWATT_TELEMETRY_GROTT,
    GROWATT_TELEMETRY_HYBRID,
    growatt_uses_grott,
    read_growatt_telemetry_source,
    read_grott_fill_missing_api,
    write_growatt_telemetry_settings,
)
from energy_dashboard.fetch.grott_mqtt import (
    GrottMqttSubscriber,
    _merge_nonempty_dict,
    grott_derive_load_kw,
    grott_snapshot_fresh,
    test_grott_mqtt_connection,
)

_GW_RAG_GREEN = "#a6e3a1"
_GW_RAG_AMBER = "#fab387"
_GW_RAG_RED = "#f38ba8"
_GW_RAG_GREY = "#6c7086"
_GW_CRED_FIELD_W = 180
_GW_CRED_TOKEN_W = 200
_GW_CRED_SERIAL_W = 160
_GROTT_DOWNSTREAM_NOTIFY_INTERVAL_S = 10.0
_GROTT_API_FILL_TIP = (
    "Value filled from Growatt cloud API (Grott did not publish this register)."
)
_GROTT_LIVE_API_PATCH_INTERVAL_S = 60.0
# A resubscribe tears the MQTT client down and reconnects, so recovery attempts
# on a quiet feed are rate-limited rather than fired on every refresh tick.
_GROTT_RESUBSCRIBE_COOLDOWN_S = 60.0
# Growatt Open API V1 rejects endpoints hit more often than ~once per 5 min per
# device (error 10012 / error_frequently_access). Polling faster only earns a
# ban — and each banned call used to re-arm the local 30-min pause, which is
# why the pause message never counted down. All live V1 calls share this gate.
_GROWATT_V1_LIVE_MIN_POLL_S = 300.0


def growatt_format_live_kw(val) -> str | None:
    """Format instantaneous kW for live banner + card displays."""
    if val in (None, "", "--"):
        return None
    try:
        return f"{float(val):.2f}"
    except (TypeError, ValueError):
        return None


def growatt_live_grid_kw(status: dict) -> float | None:
    """Signed grid kW (export − import), matching the Growatt live cards."""
    if not isinstance(status, dict):
        return None
    grid_estimated = bool(status.get("gridPowerEstimated", False))
    has_grid = grid_estimated or "pactouser" in status or "pactogrid" in status
    if not has_grid:
        return None
    try:
        grid_import = float(status.get("pactouser", 0) or 0)
        grid_export = float(status.get("pactogrid", 0) or 0)
        return grid_export - grid_import
    except (TypeError, ValueError):
        return None


def _growatt_value_missing(val) -> bool:
    if val is None:
        return True
    s = str(val).strip()
    return not s or s in ("--", "—", "-")


def _growatt_dict_has_field(data, keys, present_keys) -> bool:
    if not isinstance(data, dict):
        return False
    present = present_keys if isinstance(present_keys, set) else set(present_keys or [])
    for key in keys:
        if key in present and not _growatt_value_missing(data.get(key)):
            return True
    return False


def _patch_grott_live_from_api(
    grott_status,
    grott_info,
    grott_totals,
    present,
    api_status,
    api_info,
    api_totals,
):
    """Merge API live fields into a Grott snapshot where Grott omitted registers."""
    merged_status = dict(grott_status or {})
    merged_info = dict(grott_info or {})
    merged_totals = dict(grott_totals or {})
    api_filled = set()
    st_present = set((present or {}).get("status") or [])
    info_present = set((present or {}).get("info") or [])
    tot_present = set((present or {}).get("totals") or [])
    api_st = api_status if isinstance(api_status, dict) else {}
    api_info = api_info if isinstance(api_info, dict) else {}
    api_tot = api_totals if isinstance(api_totals, dict) else {}

    def _patch_status(ui_key, *field_keys):
        if _growatt_dict_has_field(merged_status, field_keys, st_present):
            return
        for fk in field_keys:
            if fk in api_st and not _growatt_value_missing(api_st.get(fk)):
                merged_status[fk] = api_st[fk]
                api_filled.add(ui_key)
                return

    def _patch_info(ui_key, *field_keys):
        if _growatt_dict_has_field(merged_info, field_keys, info_present):
            return
        for fk in field_keys:
            if fk in api_info and not _growatt_value_missing(api_info.get(fk)):
                merged_info[fk] = api_info[fk]
                api_filled.add(ui_key)
                return

    def _patch_totals(ui_key, *field_keys):
        if _growatt_dict_has_field(merged_totals, field_keys, tot_present):
            return
        for fk in field_keys:
            if fk in api_tot and not _growatt_value_missing(api_tot.get(fk)):
                merged_totals[fk] = api_tot[fk]
                api_filled.add(ui_key)
                return

    _patch_status("soc", "SOC")
    if not _growatt_dict_has_field(
        merged_status, ("chargePower", "pdisCharge1"), st_present,
    ):
        for fk in ("chargePower", "pdisCharge1"):
            if fk in api_st and not _growatt_value_missing(api_st.get(fk)):
                merged_status[fk] = api_st[fk]
        if _growatt_dict_has_field(merged_status, ("chargePower", "pdisCharge1"), set(api_st)):
            api_filled.add("bat_power")
    _patch_status("pv_power", "ppv")
    if not merged_status.get("gridPowerEstimated"):
        if not _growatt_dict_has_field(
            merged_status, ("pactouser", "pactogrid"), st_present,
        ):
            patched = False
            for fk in ("pactouser", "pactogrid"):
                if fk in api_st and not _growatt_value_missing(api_st.get(fk)):
                    merged_status[fk] = api_st[fk]
                    patched = True
            if patched:
                api_filled.add("grid_power")
    _patch_status("load_power", "pLocalLoad")

    _patch_totals("etoday", "epvToday")
    _patch_totals("etotal", "epvTotal")
    _patch_totals("echargetoday", "echargetoday")
    _patch_totals("edischargetoday", "edischarge1Today")

    _patch_status("grid_v", "vAc1", "vac1")
    _patch_status("grid_hz", "fAc")
    _patch_status("bat_v", "vBat")
    _patch_info("bat_vdsp", "vbatdsp", "vBatDsp")
    _patch_status("bat_type", "wBatteryType")
    if not _growatt_dict_has_field(merged_status, ("vPv1", "pPv1"), st_present):
        for fk in ("vPv1", "pPv1"):
            if fk in api_st and not _growatt_value_missing(api_st.get(fk)):
                merged_status[fk] = api_st[fk]
        if _growatt_dict_has_field(merged_status, ("vPv1", "pPv1"), set(api_st)):
            api_filled.add("pv1")
    if not _growatt_dict_has_field(merged_status, ("vPv2", "pPv2"), st_present):
        for fk in ("vPv2", "pPv2"):
            if fk in api_st and not _growatt_value_missing(api_st.get(fk)):
                merged_status[fk] = api_st[fk]
        if _growatt_dict_has_field(merged_status, ("vPv2", "pPv2"), set(api_st)):
            api_filled.add("pv2")
    _patch_status("pv_pmax", "pmax")
    if not _growatt_dict_has_field(merged_status, ("lost", "status"), st_present):
        for fk in ("lost", "status"):
            if fk in api_st and not _growatt_value_missing(api_st.get(fk)):
                merged_status[fk] = api_st[fk]
                api_filled.add("sys_lost")
                break
    _patch_totals("load_etoday", "elocalLoadToday")
    _patch_totals(
        "imp_etoday",
        "etouser",
        "eToUser",
        "eToUserToday",
        "efromGridToday",
        "eFromGridToday",
        "import_from_grid_energy_today",
        "import_from_grid_today",
    )
    _patch_totals("exp_etoday", "etoGridToday")

    return merged_status, merged_info, merged_totals, api_filled


class GrowattTab(QWidget):
    def __init__(self, status_callback, app_params=None, dash=None):
        super().__init__()
        self.set_status = status_callback
        self.app_params = app_params
        self.dash = dash
        self._inv = Invoker(self)
        self.on_data_updated = None
        self.api = None
        self.plant_id = None
        self.plant_name = None
        self.device_sn = None
        self.device_type = None
        self.mix_status_data = None
        self.mix_info_data = None
        self.mix_totals_data = None
        self._plant_devices = []
        self._model_inv = '—'
        self._model_bat = '—'
        self._battery_equipage = {}
        self._modbus_pack_serials = []
        self._modbus_pack_serials_detail = ""
        self._modbus_modules = None
        self._modbus_modules_detail = ""
        self._modbus_battery_polling = False
        self._modbus_battery_poll_ts = 0.0
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(30000)
        self._auto_timer.timeout.connect(self._on_auto_tick)
        self._auto_refresh_pending = False
        self._growatt_fetching = False
        self._last_v1_live_poll = 0.0
        # Last raw cloud live read + same-moment Grott snapshot, so sibling
        # tabs (Grott/API Align) can reuse it instead of spending the shared
        # Open API budget on their own polls.
        self._last_cloud_pair = None
        self._v1_throttle_notice_ts = 0.0
        self._growatt_testing = False
        self._growatt_auth_gen = 0
        self._growatt_connecting = False
        self._last_auth_result = None
        self._last_auth_key = None
        self._last_auth_time = None
        self._inverter_comms_lost = False
        self._conn_method = "—"
        self._v1_pause_notice_active = False
        self._grott_status = "Grott MQTT not started"
        self._shinelan_probe_running = False
        self._last_shinelan_probe = None
        self._last_shinelan_probe_time = None
        self._last_grott_downstream_notify = 0.0
        self._last_grott_resubscribe = 0.0
        self._grott_static_enriching = False
        self._last_grott_static_enrich = 0.0
        self._grott_static_enrich_interval_s = 900.0
        self._grott_live_api_patching = False
        self._last_grott_live_api_patch = 0.0
        self._grott_gap_fill_only = False
        self._last_grott_present = {"status": set(), "info": set(), "totals": set()}
        # Per-key last-seen times so sparse Shine heartbeats (SOC + grid V/Hz)
        # do not wipe the "Grott published this" set from a recent full frame.
        self._grott_present_seen_at = {
            "status": {}, "info": {}, "totals": {},
        }
        self._api_filled_fields = set()
        # Last good Grott display bundle — survives session reset and sparse MQTT.
        self._grott_display_cache = {"status": {}, "info": {}, "totals": {}}
        self._power_label_colors = {}
        self._total_label_colors = {}
        self._grott_ui_pending = False
        self._grott_ui_timer = QTimer(self)
        self._grott_ui_timer.setSingleShot(True)
        self._grott_ui_timer.setInterval(250)
        self._grott_ui_timer.timeout.connect(self._flush_grott_ui_apply)
        self._grott = GrottMqttSubscriber(
            on_update=lambda: self._inv.invoke(self._schedule_grott_ui_apply),
            on_status=lambda msg: self._inv.invoke(lambda m=msg: self._set_grott_status(m)),
            on_link_event=lambda et, detail: self._inv.invoke(
                lambda e=et, d=detail: self._on_grott_link_event(e, d)
            ),
        )
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._update_growatt_refresh_countdown)
        self.build_ui()
        self.apply_grott_settings()
        self._countdown_timer.start()

    def _schedule_grott_ui_apply(self):
        """Coalesce rapid Grott MQTT updates into one UI apply shortly."""
        self._grott_ui_pending = True
        if not self._grott_ui_timer.isActive():
            self._grott_ui_timer.start()

    def _flush_grott_ui_apply(self):
        if not self._grott_ui_pending:
            return
        self._grott_ui_pending = False
        self._apply_grott_snapshot_if_needed()

    def build_ui(self):
        main_layout = QVBoxLayout(self)

        # Credentials are now entered on the Setup tab (Growatt inverter →
        # Growatt cloud). These edits are kept as hidden data-holders so the
        # existing connect/test logic keeps reading the same values; they are
        # populated from QSettings via _load_growatt_credentials().
        self.username_edit = QLineEdit(DEFAULT_GROWATT_USER)
        self.username_edit.setVisible(False)
        self.password_edit = QLineEdit(DEFAULT_GROWATT_PASS)
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setVisible(False)
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setVisible(False)
        self.serial_edit = QLineEdit()
        self.serial_edit.setVisible(False)

        # --- Telemetry source toggle (mirrors Setup → Growatt telemetry source) ---
        cred_box = QGroupBox("Growatt Telemetry Source")
        cred_layout = QHBoxLayout(cred_box)
        cred_layout.setSpacing(10)
        cred_layout.addWidget(QLabel("Source:"))
        self._src_sync = False
        self.rb_src_api = QRadioButton("Growatt Cloud API")
        self.rb_src_api.setToolTip(
            "Use Growatt's cloud/Open API login as the live telemetry source. "
            "Credentials are entered on the Setup tab."
        )
        self.rb_src_grott = QRadioButton("GROTT MQTT")
        self.rb_src_grott.setToolTip(
            "Use decoded local Growatt telemetry from GROTT over MQTT (configured on the Setup tab)."
        )
        self.rb_src_hybrid = QRadioButton("Hybrid")
        self.rb_src_hybrid.setToolTip(
            "Prefer fresh GROTT MQTT telemetry; if Grott is stale or unavailable, "
            "fall back to the Growatt cloud API."
        )
        self._src_group = QButtonGroup(self)
        self._src_group.setExclusive(True)
        self._src_group.addButton(self.rb_src_api)
        self._src_group.addButton(self.rb_src_grott)
        self._src_group.addButton(self.rb_src_hybrid)
        self._sync_source_radios_from_settings()
        self.rb_src_api.toggled.connect(self._on_source_toggled)
        self.rb_src_grott.toggled.connect(self._on_source_toggled)
        self.rb_src_hybrid.toggled.connect(self._on_source_toggled)
        cred_layout.addWidget(self.rb_src_api)
        cred_layout.addWidget(self.rb_src_grott)
        cred_layout.addWidget(self.rb_src_hybrid)
        cred_layout.addSpacing(10)
        self.test_cred_btn = QPushButton("Test")
        self.test_cred_btn.setToolTip(
            "Check the selected source and whether live inverter data is reachable."
        )
        self.test_cred_btn.clicked.connect(self._test_growatt_credentials)
        _apply_primary_button_style(self.test_cred_btn)
        cred_layout.addWidget(self.test_cred_btn)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect)
        _apply_primary_button_style(self.connect_btn)
        cred_layout.addWidget(self.connect_btn)
        self.setup_btn = QPushButton("Setup")
        self.setup_btn.setToolTip(
            "Open the Setup tab at the Growatt inverter section to edit credentials and source."
        )
        self.setup_btn.clicked.connect(self._open_growatt_setup)
        _apply_primary_button_style(self.setup_btn)
        cred_layout.addWidget(self.setup_btn)
        cred_layout.addSpacing(12)
        self.chk_fill_missing_api = QCheckBox("Fill missing Grott data with API")
        self.chk_fill_missing_api.setToolTip(
            "While GROTT MQTT (or Hybrid with a fresh Grott snapshot) is the live "
            "source, fetch Growatt cloud data in the background and patch only "
            "registers Grott did not publish. Patched fields are shown in amber."
        )
        self.chk_fill_missing_api.setChecked(self._fill_missing_api_enabled())
        self.chk_fill_missing_api.toggled.connect(self._on_fill_missing_toggled)
        cred_layout.addWidget(self.chk_fill_missing_api)
        cred_layout.addStretch(1)
        self.lbl_cred_flow = QLabel("Not connected")
        self.lbl_cred_flow.setStyleSheet(
            f"color: {_GW_RAG_GREY}; font-size: 11px; font-weight: bold;"
        )
        self.lbl_cred_flow.setMinimumWidth(200)
        self.lbl_cred_method = QLabel("Connection: —")
        self.lbl_cred_method.setStyleSheet(f"color: {_GW_RAG_GREY}; font-size: 11px;")
        self.lbl_cred_method.setMinimumWidth(200)
        cred_status = QWidget()
        cred_status_lay = QVBoxLayout(cred_status)
        cred_status_lay.setContentsMargins(8, 0, 0, 0)
        cred_status_lay.setSpacing(2)
        cred_status_lay.addWidget(self.lbl_cred_flow)
        cred_status_lay.addWidget(self.lbl_cred_method)
        cred_layout.addWidget(cred_status, 0, Qt.AlignmentFlag.AlignVCenter)
        self._update_fill_missing_controls()
        main_layout.addWidget(cred_box)

        self._load_growatt_credentials()

        # --- Live Status (power cards only) ---
        live_box = QGroupBox("Live Status (MIX Device)")
        live_layout = QVBoxLayout(live_box)
        live_layout.setContentsMargins(8, 8, 8, 6)
        power_layout = QHBoxLayout()
        self.power_labels = {}
        power_items = [
            ('soc', 'Battery SOC', '%', '#2196F3'),
            ('bat_power', 'Battery Power', 'kW', '#4CAF50'),
            ('pv_power', 'PV Power', 'kW', '#FF9800'),
            ('grid_power', 'Grid Power', 'kW', '#F44336'),
            ('load_power', 'Load Power', 'kW', '#9C27B0'),
        ]
        for key, label, unit, color in power_items:
            card, val_label = make_power_card(label, unit, color)
            self.power_labels[key] = val_label
            self._power_label_colors[key] = color
            if key == 'grid_power':
                val_label.setWordWrap(True)
                val_label.setTextFormat(Qt.TextFormat.RichText)
            power_layout.addWidget(card)
        live_layout.addLayout(power_layout)
        main_layout.addWidget(live_box)

        # --- Energy Totals (same card style as Live Status above) ---
        totals_box = QGroupBox("Energy Totals")
        totals_layout = QHBoxLayout(totals_box)
        totals_layout.setContentsMargins(8, 8, 8, 6)
        self.total_labels = {}
        self.total_unit_labels = {}
        total_items = [
            ('etoday', "Today's solar", 'kWh', '#FF9800',
             "Electricity your PV panels produced today (from the inverter)."),
            ('etotal', 'Lifetime solar', 'kWh', '#2196F3',
             "All solar generation recorded since install — large values are shown in MWh."),
            ('echargetoday', 'Into battery today', 'kWh', '#4CAF50',
             "Energy stored in the battery today from solar or grid charging (into the pack)."),
            ('edischargetoday', 'From battery today', 'kWh', '#9C27B0',
             "Energy that left the battery today to run your home or export to the grid."),
        ]
        for key, label, unit, color, tip in total_items:
            card, val_label, unit_lbl = make_power_card(
                label, unit, color, return_unit_label=True)
            unit_lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
            card.setToolTip(tip)
            self.total_labels[key] = val_label
            self.total_unit_labels[key] = unit_lbl
            self._total_label_colors[key] = color
            totals_layout.addWidget(card)
        main_layout.addWidget(totals_box)

        # --- Device Info: 3 columns — plant/type | serial/status | inverter+battery models ---
        info_box = QGroupBox("Device Information")
        info_outer = QHBoxLayout(info_box)
        info_outer.setContentsMargins(10, 8, 10, 8)
        self.info_labels = {}

        _info_base_font = QFont('Helvetica', INFO_DEVICE_SECTION_PT)
        _info_fm = QFontMetrics(_info_base_font)
        # Two “tab stops” ≈ 2 × 8 space widths at this font (common monospaced tab width).
        _info_val_indent = 2 * 8 * _info_fm.horizontalAdvance(' ')

        def _device_info_column(rows):
            col = QWidget()
            v = QVBoxLayout(col)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(14)
            # Same label column width so values align (reference = widest title, usually bottom row).
            titles = [t for _, t in rows]
            _label_w = max(_info_fm.horizontalAdvance(t) for t in titles) if titles else 0
            for key, title in rows:
                row_w = QWidget()
                h = QHBoxLayout(row_w)
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(0)
                name = QLabel(title)
                name.setFont(_info_base_font)
                name.setFixedWidth(_label_w)
                name.setAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                val = QLabel('--')
                val.setFont(
                    QFont('Helvetica', INFO_DEVICE_SECTION_PT, QFont.Bold))
                val.setAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                val.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse)
                self.info_labels[key] = val
                h.addWidget(name, 0, Qt.AlignmentFlag.AlignLeft)
                h.addSpacing(_info_val_indent)
                h.addWidget(val, 0, Qt.AlignmentFlag.AlignLeft)
                h.addStretch(1)
                v.addWidget(row_w)
            return col

        left_col = _device_info_column([
            ('plant', 'Plant:'),
            ('type', 'Device Type:'),
        ])
        right_col = _device_info_column([
            ('serial', 'Device Serial:'),
            ('status', 'Connection Status:'),
        ])
        model_col = _device_info_column([
            ('inv_model', 'Inverter model:'),
            ('bat_model', 'Battery model:'),
        ])
        info_outer.addStretch(1)
        info_outer.addWidget(left_col, 0, Qt.AlignmentFlag.AlignTop)
        info_outer.addStretch(2)
        info_outer.addWidget(right_col, 0, Qt.AlignmentFlag.AlignTop)
        info_outer.addStretch(2)
        info_outer.addWidget(model_col, 0, Qt.AlignmentFlag.AlignTop)
        info_outer.addStretch(1)
        self.info_labels['status'].setWordWrap(True)
        main_layout.addWidget(info_box)

        # --- Physical: 4 columns — model & today | equipage | grid & PV | pack & status ---
        # Titles live in a fixed-width wrapping column so a long name can never
        # run under the value next to it; values own the rest of the column.
        _PHYS_TITLE_W = 132
        _PHYS_VALUE_MIN_W = 96
        _PHYS_COL_MIN_W = 248
        _PHYS_MULTILINE_PT = max(10, INFO_PHYSICAL_VALUE_PT - 2)

        def _phys_height_for_width(lbl):
            """Let a wrapping label claim the height its wrapped text needs.
            Without this a grid row keeps the one-line height and clips the
            second line."""
            sp = lbl.sizePolicy()
            sp.setHeightForWidth(True)
            lbl.setSizePolicy(sp)

        phys_box = QGroupBox(
            "Physical — inverter & battery "
            "(dashboard model + live telemetry + today’s energy)"
        )
        phys_box.setToolTip(
            "Column 1: Setup / Parameters battery model and today’s energy from "
            "mix_totals. Column 2: battery equipage (packs, chemistry, serials). "
            "Columns 3–4: live readings from mix_system_status / mix_info."
        )
        phys_outer = QHBoxLayout(phys_box)
        phys_outer.setSpacing(14)
        phys_outer.setContentsMargins(10, 8, 10, 8)
        phys_box.setMinimumHeight(320)
        phys_box.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.physical_labels = {}

        def _phys_row(
            grid, row, title, key, *, tip=None, value_font_pt=None,
            multiline=False,
        ):
            if value_font_pt is None:
                value_font_pt = (
                    _PHYS_MULTILINE_PT if multiline else INFO_PHYSICAL_VALUE_PT
                )
            tl = QLabel(title)
            tl.setStyleSheet(
                f"color: #a6adc8; font-size: {INFO_PHYSICAL_TITLE_PX}px;")
            tl.setWordWrap(True)
            tl.setFixedWidth(_PHYS_TITLE_W)
            _phys_height_for_width(tl)
            if tip:
                tl.setToolTip(tip)
            # Alignment goes on the labels, not on addWidget: a grid item with
            # an alignment flag is shrunk to its size hint, which would keep the
            # value column at its minimum width and wrap text into clipped rows.
            tl.setAlignment(
                Qt.AlignRight | Qt.AlignTop if multiline
                else Qt.AlignRight | Qt.AlignVCenter
            )
            grid.addWidget(tl, row, 0)
            vl = QLabel("—")
            vl.setFont(QFont('Helvetica', value_font_pt, QFont.Bold))
            vl.setStyleSheet("color: #cdd6f4;")
            vl.setWordWrap(True)
            vl.setMinimumWidth(_PHYS_VALUE_MIN_W)
            if multiline:
                vl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
                vl.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
                vl.setMinimumHeight(36)
                vl.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse)
            _phys_height_for_width(vl)
            if tip:
                vl.setToolTip(tip)
            vl.setAlignment(
                Qt.AlignLeft | Qt.AlignTop if multiline
                else Qt.AlignLeft | Qt.AlignVCenter
            )
            grid.addWidget(vl, row, 1)
            self.physical_labels[key] = vl

        def _phys_column():
            col = QWidget()
            col.setMinimumWidth(_PHYS_COL_MIN_W)
            lay = QVBoxLayout(col)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            return col, lay

        def _phys_section(lay, header):
            hdr = QLabel(header)
            hdr.setStyleSheet(
                f"color: #6c7086; font-size: {INFO_PHYSICAL_HDR_PX}px; "
                "font-weight: bold;")
            lay.addWidget(hdr)
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            grid.setVerticalSpacing(8)
            grid.setColumnMinimumWidth(0, _PHYS_TITLE_W)
            grid.setColumnStretch(0, 0)
            grid.setColumnStretch(1, 1)
            lay.addLayout(grid)
            return grid

        def _phys_divider():
            line = QFrame()
            line.setFrameShape(QFrame.Shape.VLine)
            line.setFrameShadow(QFrame.Shadow.Plain)
            line.setStyleSheet("color: #313244;")
            return line

        col_model, lay_model = _phys_column()
        grid_model = _phys_section(lay_model, "— Dashboard model —")
        _phys_row(
            grid_model, 0, "Nominal capacity", "dash_kwh",
            tip="Dashboard model: usable pack size used by Battery Analysis, "
                "Optimiser, etc. Edit in Setup / Parameters.",
        )
        _phys_row(
            grid_model, 1, "Max charge / discharge", "dash_kw",
            tip="Dashboard model: peak AC battery power assumed in simulations (kW).",
        )
        _phys_row(
            grid_model, 2, "Round-trip efficiency", "dash_eff",
            tip="Dashboard model: whole-cycle efficiency % used in battery simulations.",
        )
        _phys_row(
            grid_model, 3, "Low-SOC floor", "dash_soc_floor",
            tip="Dashboard model: minimum SOC % before the planner treats the "
                "pack as empty.",
        )
        lay_model.addSpacing(6)
        grid_today = _phys_section(lay_model, "— Today (from inverter totals) —")
        _phys_row(grid_today, 0, "House load", "load_etoday",
                  tip="Energy the house used today. mix_totals: elocalLoadToday (kWh).")
        _phys_row(grid_today, 1, "Imported", "imp_etoday",
                  tip="Bought from the grid today. mix_totals / mix_detail: etouser "
                      "(kWh). Includes grid energy used by load and AC battery charging.")
        _phys_row(grid_today, 2, "Exported", "exp_etoday",
                  tip="Sold to the grid today. mix_totals: etoGridToday (kWh).")
        lay_model.addStretch(1)

        col_equip, lay_equip = _phys_column()
        grid_equip = _phys_section(lay_equip, "— Battery equipage —")
        _phys_row(
            grid_equip, 0, "Packs seen (telemetry)", "equip_modules",
            tip=(
                "Growatt cloud, the Growatt website, and Grott MQTT only expose "
                "one shared battery bus for parallel GBLI packs — packs 2+ are "
                "usually not countable. Use Manual packs below when needed."
            ),
        )
        _phys_row(
            grid_equip, 1, "Equipage capacity", "equip_kwh",
            tip=(
                "modules × 6.5 kWh (GBLI-class) when a count is known "
                "(manual / Modbus / rare explicit field). Compare with Setup."
            ),
        )
        tl_mod = QLabel("Manual packs")
        tl_mod.setStyleSheet(
            f"color: #a6adc8; font-size: {INFO_PHYSICAL_TITLE_PX}px;")
        tl_mod.setWordWrap(True)
        tl_mod.setFixedWidth(_PHYS_TITLE_W)
        tl_mod.setToolTip(
            "Override when Growatt/Grott cannot see packs 2+. "
            "0 = Auto. Typical GBLI = 6.5 kWh each (3 → 19.5 kWh)."
        )
        tl_mod.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid_equip.addWidget(tl_mod, 2, 0)
        mod_row = QWidget(self)
        mod_lay = QHBoxLayout(mod_row)
        mod_lay.setContentsMargins(0, 0, 0, 0)
        mod_lay.setSpacing(6)
        self.equip_modules_spin = QSpinBox(mod_row)
        self.equip_modules_spin.setRange(0, 16)
        self.equip_modules_spin.setSpecialValueText("Auto")
        self.equip_modules_spin.setToolTip(
            "0 = Auto (telemetry only). Set 3 if you have three parallel packs."
        )
        try:
            _ov = _growatt_battery_modules_override()
            self.equip_modules_spin.setValue(int(_ov) if _ov else 0)
        except Exception:
            self.equip_modules_spin.setValue(0)
        self.equip_modules_apply_btn = QPushButton("Apply", mod_row)
        self.equip_modules_apply_btn.setToolTip(
            "Save manual module count (or Auto) and refresh equipage labels."
        )
        self.equip_modules_apply_btn.clicked.connect(self._apply_battery_modules_override)
        self.equip_modbus_probe_btn = QPushButton("Probe packs", mod_row)
        self.equip_modbus_probe_btn.setToolTip(
            "Modbus TCP: read pack serials at holding 1125+ (SPH) and derive "
            "module count from them when pack-count regs are 0. Also runs "
            "automatically when Local Modbus is enabled in Setup — Grott MQTT "
            "cannot see packs 2/3."
        )
        self.equip_modbus_probe_btn.clicked.connect(self._probe_battery_modules_modbus)
        mod_lay.addWidget(self.equip_modules_spin)
        mod_lay.addWidget(self.equip_modules_apply_btn)
        mod_lay.addWidget(self.equip_modbus_probe_btn)
        mod_lay.addStretch(1)
        grid_equip.addWidget(mod_row, 2, 1)
        _phys_row(grid_equip, 3, "Chemistry (BMS)", "bat_type",
                  tip="mix_system_status: wBatteryType — Growatt enum; legend is "
                      "indicative.")
        _lbl_bt = self.physical_labels['bat_type']
        _lbl_bt.setTextFormat(Qt.TextFormat.PlainText)
        _lbl_bt.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        _lbl_bt.setMinimumHeight(0)
        _phys_row(grid_equip, 4, "Pack serials", "bat_sns",
                  multiline=True,
                  tip=(
                      "Per-pack serials from plant device_list (storage devices), "
                      "live fields if published, or Modbus Probe packs "
                      "(holding 1125+ / input 3263). Cloud/Grott often omit these."
                  ))
        # One SN per line only — no soft-wrap (that inflated the row to dozens
        # of lines when the label width was still narrow during layout).
        _lbl_sns = self.physical_labels["bat_sns"]
        _lbl_sns.setWordWrap(False)
        _lbl_sns.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay_equip.addStretch(1)

        col_grid, lay_grid = _phys_column()
        grid_gridpv = _phys_section(lay_grid, "— Grid & PV (live) —")
        _phys_row(grid_gridpv, 0, "Grid voltage", "grid_v",
                  tip="mix_system_status: vAc1 / vac1 (V).")
        _phys_row(grid_gridpv, 1, "Grid frequency", "grid_hz",
                  tip="mix_system_status: fAc (Hz).")
        _phys_row(grid_gridpv, 2, "PV string 1", "pv1",
                  tip="Volts and watts on MPPT input 1. mix_system_status: vPv1, pPv1.")
        _phys_row(grid_gridpv, 3, "PV string 2", "pv2",
                  tip="Volts and watts on MPPT input 2. mix_system_status: vPv2, pPv2.")
        _phys_row(grid_gridpv, 4, "PV DC rating hint", "pv_pmax",
                  tip="mix_system_status: pmax (kW-ish; meaning varies by firmware).")
        lay_grid.addStretch(1)

        col_live, lay_live = _phys_column()
        grid_live = _phys_section(lay_live, "— Pack & status (live) —")
        _phys_row(grid_live, 0, "Battery voltage", "bat_v",
                  tip="Pack terminal voltage. mix_system_status: vBat (V).")
        _phys_row(grid_live, 1, "BMS voltage", "bat_vdsp",
                  tip="Voltage the BMS itself reports. mix_info: vbatdsp when "
                      "present (V).")
        _phys_row(grid_live, 2, "System status", "sys_lost",
                  tip=(
                      "Inverter work mode from Grott/cloud (lost / status / pvstatus). "
                      "Hover the value for the raw code and full legend. "
                      "Not the same as fault words below."
                  ))
        _phys_row(
            grid_live, 3, "Faults (inverter)", "sys_faults",
            multiline=True,
            tip=(
                "Grott/cloud faultBit, warningBit, systemfaultword0–7. "
                "Each non-zero word is one row."
            ),
        )
        _phys_row(
            grid_live, 4, "Faults (dashboard)", "sys_faults_dash",
            multiline=True,
            tip=(
                "Live dashboard alarms (Grott MQTT lost, low SOC, spare PV). "
                "Same set as the banner — one row per alarm."
            ),
        )
        lay_live.addStretch(1)

        for _idx, _col in enumerate((col_model, col_equip, col_grid, col_live)):
            if _idx:
                phys_outer.addWidget(_phys_divider(), 0)
            phys_outer.addWidget(_col, 1)

        phys_refresh_strip = QWidget()
        phys_refresh_strip.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        strip_lay = QHBoxLayout(phys_refresh_strip)
        strip_lay.setContentsMargins(0, 0, 0, 0)
        strip_lay.setSpacing(8)
        strip_lay.addWidget(phys_box, 1)

        refresh_col = QWidget()
        refresh_col.setFixedWidth(280)
        refresh_col.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.MinimumExpanding)
        refresh_v = QVBoxLayout(refresh_col)
        refresh_v.setContentsMargins(4, 8, 8, 8)
        refresh_v.setSpacing(8)
        self.refresh_btn = QPushButton("Refresh Now")
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.clicked.connect(self.refresh_data)
        self.refresh_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _apply_primary_button_style(self.refresh_btn)
        refresh_v.addWidget(self.refresh_btn, 0, Qt.AlignTop)
        self.countdown_label = QLabel("—")
        self.countdown_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 12px;")
        self.countdown_label.setWordWrap(True)
        refresh_v.addWidget(self.countdown_label, 0, Qt.AlignLeft | Qt.AlignTop)
        self.last_refresh_label = QLabel("Last refresh: --")
        self.last_refresh_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        self.last_refresh_label.setWordWrap(True)
        self.last_refresh_label.setMinimumWidth(250)
        self.last_refresh_label.setMinimumHeight(34)
        self.last_refresh_label.setMaximumHeight(48)
        refresh_v.addWidget(self.last_refresh_label, 0, Qt.AlignLeft | Qt.AlignTop)
        refresh_v.addStretch(1)
        strip_lay.addWidget(refresh_col, 0)

        main_layout.addWidget(phys_refresh_strip, 1)

    def _growatt_settings(self):
        return QSettings("PowerModel", "EnergyDashboard2")

    def _grott_config(self) -> dict:
        from energy_dashboard.config import heal_grott_mqtt_broker_settings

        s = self._growatt_settings()
        p = self.app_params
        broker = heal_grott_mqtt_broker_settings(s, p)
        return {
            "enabled": growatt_uses_grott(self._telemetry_source()),
            "telemetry_source": self._telemetry_source(),
            "fill_missing_api": self._fill_missing_api_enabled(),
            "host": broker.get("host") or "",
            "port": int(broker.get("port") or 1883),
            "username": broker.get("username") or "",
            "password": broker.get("password") or "",
            "topic": broker.get("topic") or "energy/growatt",
            "fresh_s": int(broker.get("fresh_s") or 120),
            "broker_source": broker.get("source") or "grott",
        }

    def _telemetry_source(self) -> str:
        return read_growatt_telemetry_source(self._growatt_settings(), self.app_params)

    def _fill_missing_api_enabled(self) -> bool:
        return read_grott_fill_missing_api(self._growatt_settings(), self.app_params)

    def _uses_grott(self) -> bool:
        return growatt_uses_grott(self._telemetry_source())

    def _hybrid_mode(self) -> bool:
        return self._telemetry_source() == GROWATT_TELEMETRY_HYBRID

    def _grott_only(self) -> bool:
        return self._telemetry_source() == GROWATT_TELEMETRY_GROTT

    def _grott_selected(self) -> bool:
        """True when Grott MQTT path is active (Grott-only or Hybrid)."""
        return self._uses_grott()

    def _grott_connection_method(self) -> str:
        if self._hybrid_mode():
            return "Hybrid · Grott + API fallback"
        return "Local · Grott MQTT"

    def _sync_source_radios_from_settings(self) -> None:
        src = self._telemetry_source()
        self._src_sync = True
        try:
            self.rb_src_api.setChecked(src == GROWATT_TELEMETRY_API)
            self.rb_src_grott.setChecked(src == GROWATT_TELEMETRY_GROTT)
            self.rb_src_hybrid.setChecked(src == GROWATT_TELEMETRY_HYBRID)
        finally:
            self._src_sync = False

    def _update_fill_missing_controls(self) -> None:
        if not hasattr(self, "chk_fill_missing_api"):
            return
        uses_grott = self._uses_grott()
        self.chk_fill_missing_api.setEnabled(uses_grott)
        if uses_grott:
            self.chk_fill_missing_api.setChecked(self._fill_missing_api_enabled())
        else:
            self.chk_fill_missing_api.setChecked(False)

    def _telemetry_source_label(self) -> str:
        src = self._telemetry_source()
        if src == GROWATT_TELEMETRY_GROTT:
            return "GROTT MQTT"
        if src == GROWATT_TELEMETRY_HYBRID:
            return "Hybrid (Grott → API fallback)"
        return "Growatt Cloud API"

    def apply_grott_settings(self) -> None:
        cfg = self._grott_config()
        # Keep Setup EMQX / Grott fields in sync when we healed from Tasmota.
        pt = getattr(getattr(self, "dash", None), "parameters_tab", None)
        if pt is not None and cfg.get("host"):
            try:
                if hasattr(pt, "ed_grott_host") and not pt.ed_grott_host.text().strip():
                    pt.ed_grott_host.setText(cfg["host"])
                    pt.sp_grott_port.setValue(int(cfg["port"]))
                if hasattr(pt, "ed_emqx_host") and not pt.ed_emqx_host.text().strip():
                    pt.ed_emqx_host.setText(cfg["host"])
                    pt.sp_emqx_port.setValue(int(cfg["port"]))
                if cfg.get("username"):
                    if hasattr(pt, "ed_grott_user") and not pt.ed_grott_user.text().strip():
                        pt.ed_grott_user.setText(cfg["username"])
                        pt.ed_grott_pass.setText(cfg.get("password") or "")
                    if hasattr(pt, "ed_emqx_user") and not pt.ed_emqx_user.text().strip():
                        pt.ed_emqx_user.setText(cfg["username"])
                        pt.ed_emqx_pass.setText(cfg.get("password") or "")
            except Exception:
                pass
        if not cfg["enabled"]:
            def _stop():
                self._grott.stop()
                self._inv.invoke(lambda: self._set_grott_status("Grott MQTT not selected"))
            threading.Thread(target=_stop, daemon=True).start()
            return
        if not cfg["host"]:
            self._set_grott_status(
                "Grott MQTT enabled but host is empty — set EMQX host or Grott MQTT host in Setup"
            )
            return
        who = cfg.get("broker_source") or "grott"
        self._set_grott_status(
            f"Grott MQTT connecting to {cfg['host']}:{cfg['port']} ({who})…"
        )

        def _worker():
            ok, msg = self._grott.start(
                cfg["host"],
                cfg["port"],
                username=cfg["username"],
                password=cfg["password"],
                topic=cfg["topic"],
            )
            self._inv.invoke(lambda: self._grott_start_done(ok, msg))

        threading.Thread(target=_worker, daemon=True).start()

    def _grott_start_done(self, ok: bool, msg: str) -> None:
        self._set_grott_status(msg)
        if not ok:
            self.set_status(f"Grott MQTT source failed: {msg}")

    def _set_grott_status(self, msg: str) -> None:
        self._grott_status = msg or "—"

    def _on_grott_link_event(self, event_type: str, detail: str) -> None:
        """Persist disconnect/reconnect edges for Connectivity → Show history."""
        try:
            from energy_dashboard.db.connectivity_events import log_connectivity_event

            severity = {
                "disconnect": "warn",
                "connect_fail": "bad",
                "reconnect_fail": "warn",
                "reconnect": "ok",
                "connect": "ok",
                "reconnect_attempt": "info",
            }.get(event_type, "info")
            dash = getattr(self, "dash", None)
            log_connectivity_event(
                getattr(dash, "data_logger", None) if dash is not None else None,
                service_key="grott_mqtt",
                service_label="Growatt local (Grott MQTT)",
                event_type=(
                    "fault" if severity == "bad"
                    else "warn" if severity == "warn"
                    else "recover" if event_type in ("reconnect", "connect")
                    else "info"
                ),
                state_key=severity,
                state_text=event_type,
                detail=str(detail or "")[:2000],
            )
        except Exception:
            pass
        if event_type in ("disconnect", "reconnect", "connect_fail"):
            try:
                self.set_status(f"Grott MQTT {event_type}: {detail}")
            except Exception:
                pass

    def grott_status(self) -> dict:
        status = self._grott.status()
        status["message"] = self._grott_status
        return status

    def _fresh_grott_snapshot(self):
        cfg = self._grott_config()
        if not cfg.get("enabled"):
            return None
        snap = self._grott.snapshot()
        if not grott_snapshot_fresh(snap, cfg.get("fresh_s", 120)):
            return None
        wanted = (self.device_sn or self.serial_edit.text().strip() or "").strip()
        got = str((snap or {}).get("serial") or "").strip()
        if wanted and got and wanted.lower() != got.lower():
            return None
        return snap

    def _grott_display_snapshot(self, *, allow_stale: bool = True):
        """Snapshot for UI: fresh first, optionally keep last good reading."""
        cfg = self._grott_config()
        if not cfg.get("enabled"):
            return None, False
        snap = self._grott.snapshot()
        if not snap:
            return None, False
        wanted = (self.device_sn or self.serial_edit.text().strip() or "").strip()
        got = str((snap or {}).get("serial") or "").strip()
        if wanted and got and wanted.lower() != got.lower():
            return None, False
        fresh_s = max(15, int(cfg.get("fresh_s", 120)))
        if grott_snapshot_fresh(snap, fresh_s):
            return snap, False
        if allow_stale and grott_snapshot_fresh(snap, max(fresh_s * 4, 600)):
            return snap, True
        return None, False

    def _maybe_grott_standby_api(self) -> None:
        """When Grott MQTT is quiet, pull live registers from cloud once."""
        if not self._uses_grott() or self._fresh_grott_snapshot():
            return
        if not (self.token_edit.text().strip() or self.username_edit.text().strip()):
            return
        self._start_grott_live_api_patch(gap_fill_only=True)

    def _growatt_rate_limited(self):
        until = self._growatt_settings().value("growatt/rate_limit_until")
        if not until:
            return False
        try:
            return datetime.now() < datetime.fromisoformat(str(until))
        except (TypeError, ValueError):
            return False

    def _mark_growatt_rate_limited(self):
        s = self._growatt_settings()
        s.setValue(
            "growatt/rate_limit_until",
            (datetime.now() + timedelta(hours=24)).isoformat(),
        )
        s.sync()

    def _bump_growatt_auth_gen(self) -> int:
        self._growatt_auth_gen += 1
        return self._growatt_auth_gen

    def _growatt_auth_stale(self, gen: int) -> bool:
        return gen != self._growatt_auth_gen

    def _mark_growatt_v1_rate_limited(self):
        s = self._growatt_settings()
        s.setValue(
            "growatt/v1_rate_limit_until",
            (datetime.now() + timedelta(minutes=30)).isoformat(),
        )
        s.sync()

    def _growatt_v1_rate_limit_remaining(self):
        until = self._growatt_settings().value("growatt/v1_rate_limit_until")
        if not until:
            return None
        try:
            remaining = datetime.fromisoformat(str(until)) - datetime.now()
        except (TypeError, ValueError):
            self._growatt_settings().remove("growatt/v1_rate_limit_until")
            return None
        if remaining.total_seconds() <= 0:
            s = self._growatt_settings()
            s.remove("growatt/v1_rate_limit_until")
            s.sync()
            return None
        return remaining

    def _growatt_v1_rate_limited(self):
        return self._growatt_v1_rate_limit_remaining() is not None

    def _uses_open_api_v1_creds(self) -> bool:
        """True when live calls would go to Open API V1 (token sessions)."""
        return bool(self.token_edit.text().strip()) or _growatt_uses_open_api_v1(self.api)

    def _mark_v1_live_poll(self):
        self._last_v1_live_poll = _time_mod.monotonic()

    def _cloud_live_fetch(self, api, device_sn, plant_id):
        """Single funnel for raw cloud live reads.

        Marks the shared Open API V1 poll gate and captures the raw bundle
        (paired with a same-moment Grott snapshot) so other pages can reuse
        it instead of issuing their own cloud polls.
        """
        if _growatt_uses_open_api_v1(api):
            self._mark_v1_live_poll()
        status, info, totals = _growatt_fetch_mix_live(api, device_sn, plant_id)
        self._remember_cloud_pair(status, info, totals)
        return status, info, totals

    def _remember_cloud_pair(self, status, info, totals):
        try:
            grott_snap = self._grott.snapshot()
        except Exception:
            grott_snap = None
        self._last_cloud_pair = {
            "status": status if isinstance(status, dict) else {},
            "info": info if isinstance(info, dict) else {},
            "totals": totals if isinstance(totals, dict) else {},
            "grott_snap": grott_snap,
            "at": _time_mod.monotonic(),
            "when": datetime.now(),
        }

    def _v1_poll_wait_s(self) -> float:
        """Seconds until the next Open API V1 live poll is allowed (0 = now).

        Combines the server-imposed 10012 pause with the local minimum poll
        interval so nothing anywhere in the tab can hammer the V1 endpoints.
        """
        if not self._uses_open_api_v1_creds():
            return 0.0
        wait = 0.0
        rem = self._growatt_v1_rate_limit_remaining()
        if rem is not None:
            wait = rem.total_seconds()
        since = _time_mod.monotonic() - self._last_v1_live_poll
        return max(wait, _GROWATT_V1_LIVE_MIN_POLL_S - since, 0.0)

    def _growatt_v1_rate_limit_message(self):
        remaining = self._growatt_v1_rate_limit_remaining()
        if remaining is None:
            return ""
        mins = max(1, int((remaining.total_seconds() + 59) // 60))
        return (
            f"Growatt Open API paused (~{mins} min rate limit — error_frequently_access). "
            "Wait before Connect/Test."
        )

    def _refresh_v1_pause_notice(self):
        if self._growatt_connecting or self._growatt_testing:
            return
        if not self.token_edit.text().strip():
            self._v1_pause_notice_active = False
            return
        # GROTT-only still needs Open API when fill-missing is enabled.
        if self._grott_only() and not self._fill_missing_api_enabled():
            self._v1_pause_notice_active = False
            return
        msg = self._growatt_v1_rate_limit_message()
        if msg:
            if self._uses_grott() and self._fill_missing_api_enabled():
                self._apply_growatt_link_status(
                    "ok",
                    self._grott_connection_method(),
                    f"Live Grott data; fill-missing paused ({msg})",
                    connected=True,
                )
            else:
                method = self._growatt_auth_method_label(self.token_edit.text().strip())
                self._apply_growatt_link_status("bad", method, msg)
            self._v1_pause_notice_active = True
            return
        if self._v1_pause_notice_active and not (self.api and self.device_sn):
            if self._uses_grott() and self._fill_missing_api_enabled():
                self._apply_growatt_link_status(
                    "ok",
                    self._grott_connection_method(),
                    "Live data from Grott MQTT; fill-missing available again",
                    connected=True,
                )
                self.set_status(
                    "Growatt Open API pause expired — fill-missing will retry on next snapshot."
                )
                self._start_grott_live_api_patch()
            else:
                self._apply_growatt_link_status(
                    "off",
                    self._growatt_auth_method_label(self.token_edit.text().strip()),
                    "Open API pause expired. Connect/Test is available.",
                )
                self.set_status("Growatt Open API pause expired — Connect/Test is available.")
        self._v1_pause_notice_active = False

    def _note_growatt_v1_rate_limit(self, message: str):
        low = (message or "").lower()
        if "10012" in message or "frequently" in low:
            self._mark_growatt_v1_rate_limited()

    def _load_growatt_credentials(self):
        s = self._growatt_settings()
        if s.contains("growatt/username"):
            self.username_edit.setText(s.value("growatt/username", DEFAULT_GROWATT_USER))
        if s.contains("growatt/password"):
            self.password_edit.setText(s.value("growatt/password", DEFAULT_GROWATT_PASS))
        tok = s.value("growatt/api_token", "")
        if tok:
            self.token_edit.setText(str(tok))
        if s.contains("growatt/serial"):
            self.serial_edit.setText(s.value("growatt/serial", ""))

    def sync_source_toggle(self) -> None:
        """Reflect the persisted telemetry source in the live-status radios."""
        if not hasattr(self, "rb_src_grott"):
            return
        self._sync_source_radios_from_settings()
        if hasattr(self, "chk_fill_missing_api"):
            self.chk_fill_missing_api.blockSignals(True)
            try:
                self.chk_fill_missing_api.setChecked(self._fill_missing_api_enabled())
            finally:
                self.chk_fill_missing_api.blockSignals(False)
        self._update_fill_missing_controls()

    def _persist_telemetry_settings(self, source: str, fill_missing: bool) -> None:
        s = self._growatt_settings()
        write_growatt_telemetry_settings(s, source, fill_missing_api=fill_missing)
        s.sync()
        if self.app_params is not None:
            self.app_params.growatt_telemetry_source = source
            self.app_params.grott_mqtt_enabled = growatt_uses_grott(source)
            self.app_params.grott_fill_missing_api = bool(fill_missing)

    def _on_source_toggled(self, _checked=False):
        if getattr(self, "_src_sync", False):
            return
        if not (
            self.rb_src_api.isChecked()
            or self.rb_src_grott.isChecked()
            or self.rb_src_hybrid.isChecked()
        ):
            return
        if self.rb_src_api.isChecked():
            source = GROWATT_TELEMETRY_API
        elif self.rb_src_hybrid.isChecked():
            source = GROWATT_TELEMETRY_HYBRID
        else:
            source = GROWATT_TELEMETRY_GROTT
        fill_missing = (
            self.chk_fill_missing_api.isChecked() if source != GROWATT_TELEMETRY_API else False
        )
        self._persist_telemetry_settings(source, fill_missing)
        pt = getattr(self.dash, "parameters_tab", None) if self.dash else None
        if pt is not None and hasattr(pt, "set_growatt_telemetry_source"):
            pt.set_growatt_telemetry_source(source, fill_missing)
        elif pt is not None and hasattr(pt, "set_growatt_source"):
            pt.set_growatt_source(source != GROWATT_TELEMETRY_API)
        self._update_fill_missing_controls()
        self.apply_grott_settings()
        self.set_status(f"Growatt telemetry source: {self._telemetry_source_label()}")

    def _on_fill_missing_toggled(self, checked: bool):
        if getattr(self, "_src_sync", False):
            return
        if not self._uses_grott():
            return
        self._persist_telemetry_settings(self._telemetry_source(), bool(checked))
        pt = getattr(self.dash, "parameters_tab", None) if self.dash else None
        if pt is not None and hasattr(pt, "set_growatt_telemetry_source"):
            pt.set_growatt_telemetry_source(self._telemetry_source(), bool(checked))
        if checked and self._apply_grott_snapshot_if_needed(force=True):
            self._start_grott_live_api_patch()

    def _open_growatt_setup(self):
        dash = self.dash
        if dash is None:
            self.set_status("Setup tab is not available.")
            return
        pt = getattr(dash, "parameters_tab", None)
        if pt is not None and hasattr(dash, "show_main_page"):
            dash.show_main_page(pt)
        elif getattr(dash, "tabs", None) is not None and pt is not None:
            dash.tabs.setCurrentWidget(pt)
        if pt is not None and hasattr(pt, "reveal_growatt_section"):
            pt.reveal_growatt_section()

    def showEvent(self, event):
        super().showEvent(event)
        # Pick up credentials/source edited on the Setup tab.
        try:
            self._load_growatt_credentials()
            self.sync_source_toggle()
            self._update_fill_missing_controls()
        except Exception:
            pass

    def _save_growatt_credentials(self):
        s = self._growatt_settings()
        s.setValue("growatt/username", self.username_edit.text().strip())
        s.setValue("growatt/password", self.password_edit.text())
        s.setValue("growatt/api_token", self.token_edit.text().strip())
        s.setValue("growatt/serial", self.serial_edit.text().strip())
        # A credential change should not inherit an old local pause timer.
        s.remove("growatt/rate_limit_until")
        s.remove("growatt/v1_rate_limit_until")
        s.sync()
        self._last_auth_result = None
        self._last_auth_key = None
        self._last_auth_time = None
        self.set_status("Growatt credentials saved.")

    def _set_cred_status(self, flow_key, method, detail=""):
        """Update credentials-row RAG status (flow + connection method)."""
        labels = {
            "off": ("Not connected", _GW_RAG_GREY),
            "auth_ok": ("Auth OK", _GW_RAG_AMBER),
            "ok": ("Data flowing", _GW_RAG_GREEN),
            "warn": ("Inverter offline", _GW_RAG_AMBER),
            "bad": ("Connection error", _GW_RAG_RED),
            "checking": ("Checking…", _UI_BLUE),
        }
        text, color = labels.get(flow_key, ("—", _GW_RAG_GREY))
        self.lbl_cred_flow.setText(text)
        self.lbl_cred_flow.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: bold;"
        )
        self.lbl_cred_flow.setToolTip(detail or text)
        if method and method != "—":
            self._conn_method = method
        method_line = method if str(method).startswith("Connection:") else f"Connection: {method}"
        self.lbl_cred_method.setText(method_line)
        self.lbl_cred_method.setStyleSheet(f"color: {_GW_RAG_GREY}; font-size: 11px;")
        self.lbl_cred_method.setToolTip(detail or method_line)

    def _apply_growatt_link_status(
        self,
        flow_key: str,
        method: str,
        detail: str = "",
        *,
        connected: bool = False,
    ) -> None:
        """Keep credentials-row RAG and Device Information status in sync."""
        self._set_cred_status(flow_key, method, detail)
        if flow_key == "checking":
            self._set_connection_status_label("Checking…", _UI_BLUE)
            return
        if flow_key == "bad":
            self._set_connection_status_label(detail or "Connection error", _GW_RAG_RED)
            return
        if flow_key == "warn":
            self._set_connection_status_label(detail or "Inverter offline", _GW_RAG_AMBER)
            return
        if flow_key == "ok":
            self._set_connection_status_label(
                "Connected" if connected else (detail or "Auth OK"),
                _GW_RAG_GREEN,
            )
            return
        if flow_key == "auth_ok":
            self._set_connection_status_label(detail or "Auth OK", _GW_RAG_AMBER)
            return
        self._set_connection_status_label("Not connected", _GW_RAG_GREY)

    def _growatt_auth_method_label(self, token: str) -> str:
        return "Cloud · Open API V1" if token else "Cloud · Legacy login"

    def _growatt_auth_cache_key(self):
        token = self.token_edit.text().strip()
        manual_sn = self.serial_edit.text().strip()
        if token:
            return ("token", token, manual_sn)
        return (
            "legacy",
            self.username_edit.text().strip(),
            self.password_edit.text(),
            manual_sn,
        )

    def _remember_growatt_auth_result(self, result):
        if result and result.get("ok") and result.get("api"):
            self._last_auth_result = dict(result)
            self._last_auth_key = self._growatt_auth_cache_key()
            self._last_auth_time = datetime.now()

    def _cached_growatt_auth_result(self):
        if not self._last_auth_result or self._last_auth_key != self._growatt_auth_cache_key():
            return None
        if self._last_auth_time is None:
            return None
        # 10 min: a fresh authenticate costs 3+ Open API calls (plant_list,
        # device_list, live probe) — re-doing that every 3 min ate the same
        # V1 budget the throttle is trying to protect.
        if (datetime.now() - self._last_auth_time).total_seconds() > 600:
            return None
        return dict(self._last_auth_result)

    def _growatt_resolve_devices(self, api, plant_id, token, manual_sn):
        if token:
            devices = _growatt_v1_plant_devices(api, plant_id)
            if not devices and manual_sn:
                devices = [{"deviceSn": manual_sn, "deviceType": "mix"}]
            return devices
        devices = _growatt_plant_devices(api, plant_id)
        if not devices and manual_sn:
            ok, dtype = _growatt_verify_plant_serial(api, plant_id, manual_sn)
            if ok:
                devices = [{"deviceSn": manual_sn, "deviceType": dtype or "mix"}]
        return devices

    def _growatt_probe_live(self, api, device_sn, plant_id):
        """Return (flow_key, detail, status, info, totals) after a single live read."""
        try:
            status, info, totals = self._cloud_live_fetch(api, device_sn, plant_id)
            lost, reason = _growatt_inverter_comms_lost(status)
            if lost:
                return (
                    "warn",
                    f"Auth OK — inverter offline ({reason or 'lost'})",
                    status,
                    info,
                    totals,
                )
            return "ok", "Auth OK — live data received", status, info, totals
        except Exception as e:
            msg = _growatt_v1_error_message(e)
            self._note_growatt_v1_rate_limit(msg)
            return "warn", f"Auth OK — live read failed: {msg}", None, None, None

    def _growatt_authenticate(self):
        """Validate current credential fields. Returns result dict."""
        token = self.token_edit.text().strip()
        manual_sn = self.serial_edit.text().strip()
        method = self._growatt_auth_method_label(token)
        if token:
            msg = self._growatt_v1_rate_limit_message()
            if msg:
                return {"ok": False, "method": method, "detail": msg, "flow_key": "bad"}
        try:
            if token:
                api, plant_id, plant_name = _growatt_open_api_v1_session(token)
                devices = self._growatt_resolve_devices(api, plant_id, token, manual_sn)
                if not devices:
                    msg = _growatt_no_devices_message(plant_name, 0)
                    return {"ok": False, "method": method, "detail": msg, "flow_key": "bad"}
                device = _growatt_pick_primary_device(devices)
                if device is None:
                    msg = _growatt_no_devices_message(plant_name, 0)
                    return {"ok": False, "method": method, "detail": msg, "flow_key": "bad"}
                device_sn = device.get("deviceSn")
                flow_key, detail, live_status, live_info, live_totals = (
                    self._growatt_probe_live(api, device_sn, plant_id)
                )
                return {
                    "ok": flow_key != "bad",
                    "method": method,
                    "flow_key": flow_key,
                    "detail": detail,
                    "api": api,
                    "plant_id": plant_id,
                    "plant_name": plant_name,
                    "devices": devices,
                    "device_sn": device_sn,
                    "device_type": device.get("deviceType"),
                    "live_status": live_status,
                    "live_info": live_info,
                    "live_totals": live_totals,
                }
            if self._growatt_rate_limited():
                msg = _growatt_login_error_message("507")
                return {"ok": False, "method": method, "detail": msg, "flow_key": "bad"}
            api = growattServer.GrowattApi(False, "https://server.growatt.com/")
            login_response = _growatt_retry_call(
                api.login,
                self.username_edit.text(),
                self.password_edit.text(),
                attempts=2,
            )
            if not login_response.get("success", True):
                msg_code = login_response.get("msg") or "Invalid username or password"
                if str(msg_code).strip() == "507":
                    self._mark_growatt_rate_limited()
                msg = _growatt_login_error_message(msg_code)
                return {"ok": False, "method": method, "detail": msg, "flow_key": "bad"}
            plants = login_response.get("data", [])
            if not plants:
                return {
                    "ok": False,
                    "method": method,
                    "detail": "Login OK but this account has no plants — create one in ShinePhone first",
                    "flow_key": "bad",
                }
            plant_id = plants[0]["plantId"]
            plant_name = plants[0]["plantName"]
            devices = self._growatt_resolve_devices(api, plant_id, "", manual_sn)
            if not devices:
                msg = _growatt_no_devices_message(
                    plant_name, login_response.get("deviceCount"),
                )
                return {"ok": False, "method": method, "detail": msg, "flow_key": "bad"}
            device = _growatt_pick_primary_device(devices)
            if device is None:
                msg = _growatt_no_devices_message(plant_name, 0)
                return {"ok": False, "method": method, "detail": msg, "flow_key": "bad"}
            device_sn = device.get("deviceSn")
            flow_key, detail, live_status, live_info, live_totals = (
                self._growatt_probe_live(api, device_sn, plant_id)
            )
            return {
                "ok": flow_key != "bad",
                "method": method,
                "flow_key": flow_key,
                "detail": detail,
                "api": api,
                "plant_id": plant_id,
                "plant_name": plant_name,
                "devices": devices,
                "device_sn": device_sn,
                "device_type": device.get("deviceType"),
                "live_status": live_status,
                "live_info": live_info,
                "live_totals": live_totals,
            }
        except Exception as exc:
            msg = _growatt_v1_error_message(exc)
            self._note_growatt_v1_rate_limit(msg)
            return {"ok": False, "method": method, "detail": msg, "flow_key": "bad"}

    def _test_growatt_credentials(self):
        if getattr(self, "_growatt_testing", False):
            return
        self._growatt_testing = True
        self._record_cloud_test = not self._uses_grott()
        gen = self._bump_growatt_auth_gen()
        self.test_cred_btn.setEnabled(False)
        if self._uses_grott():
            self._apply_growatt_link_status(
                "checking", self._grott_connection_method(), "Testing Grott MQTT…",
            )
            self.set_status("Testing Grott MQTT connection…")
            threading.Thread(target=self._test_grott_thread, args=(gen,), daemon=True).start()
            return
        method = self._growatt_auth_method_label(self.token_edit.text().strip())
        self._apply_growatt_link_status("checking", method, "Testing Growatt credentials…")
        self.set_status("Testing Growatt connection…")
        threading.Thread(target=self._test_growatt_thread, args=(gen,), daemon=True).start()

    def _test_growatt_cloud_credentials(self, *, on_done=None):
        """Always test Growatt cloud login (API key or username/password).

        Used by the Connectivity Growatt API popup so Hybrid / Grott source
        selection does not redirect the test to MQTT. ``on_done(ok, detail)``
        is optional UI feedback for that popup.
        """
        if getattr(self, "_growatt_testing", False):
            if callable(on_done):
                on_done(False, "A Growatt test is already running.")
            return
        self._growatt_testing = True
        self._record_cloud_test = True
        self._growatt_cloud_test_done = on_done
        gen = self._bump_growatt_auth_gen()
        if hasattr(self, "test_cred_btn"):
            self.test_cred_btn.setEnabled(False)
        method = self._growatt_auth_method_label(self.token_edit.text().strip())
        self._apply_growatt_link_status("checking", method, "Testing Growatt cloud…")
        self.set_status("Testing Growatt cloud connection…")
        threading.Thread(target=self._test_growatt_thread, args=(gen,), daemon=True).start()

    def _test_grott_thread(self, gen: int):
        cfg = self._grott_config()
        try:
            ok, msg = test_grott_mqtt_connection(
                cfg.get("host") or "",
                int(cfg.get("port") or 1883),
                username=cfg.get("username") or "",
                password=cfg.get("password") or "",
                topic=cfg.get("topic") or "energy/growatt",
            )
        except Exception as exc:
            ok, msg = False, f"Grott MQTT test failed: {exc}"
        if self._growatt_auth_stale(gen):
            self._growatt_testing = False
            self._inv.invoke(lambda: self.test_cred_btn.setEnabled(True))
            return
        detail = msg or ("OK" if ok else "Test failed")
        flow_key = "auth_ok" if ok else "bad"
        method = self._grott_connection_method()
        if self._hybrid_mode() and ok:
            detail = f"{detail}\n\nHybrid also needs Growatt cloud credentials for API fallback."
        self._inv.invoke(
            lambda o=ok, d=detail, f=flow_key, m=method, g=gen: self._finish_growatt_test(
                o, d, flow_key=f, method=m, gen=g,
            )
        )

    def _test_growatt_thread(self, gen: int):
        try:
            result = self._growatt_authenticate()
        except Exception as e:
            err = _growatt_v1_error_message(e)
            self._note_growatt_v1_rate_limit(err)
            if not self._growatt_auth_stale(gen):
                self._inv.invoke(lambda msg=err: self._finish_growatt_test(False, msg, gen=gen))
            else:
                self._growatt_testing = False
                self._inv.invoke(self._clear_growatt_test_ui)
            return
        if self._growatt_auth_stale(gen):
            self._growatt_testing = False
            self._inv.invoke(self._clear_growatt_test_ui)
            return
        ok = bool(result.get("ok"))
        detail = result.get("detail") or ("OK" if ok else "Test failed")
        flow_key = result.get("flow_key") or ("auth_ok" if ok else "bad")
        if ok:
            self._remember_growatt_auth_result(result)
        if ok and flow_key == "ok":
            flow_key = "auth_ok"
        method = result.get("method") or "—"
        self._inv.invoke(
            lambda o=ok, d=detail, f=flow_key, m=method, g=gen: self._finish_growatt_test(
                o, d, flow_key=f, method=m, gen=g,
            )
        )

    def _clear_growatt_test_ui(self):
        if hasattr(self, "test_cred_btn"):
            self.test_cred_btn.setEnabled(True)
        cb = getattr(self, "_growatt_cloud_test_done", None)
        self._growatt_cloud_test_done = None
        if callable(cb):
            try:
                cb(False, "Test cancelled.")
            except Exception:
                pass

    def _finish_growatt_test(self, ok, detail, *, flow_key=None, method="—", gen=0):
        if gen and self._growatt_auth_stale(gen):
            return
        self._growatt_testing = False
        if hasattr(self, "test_cred_btn"):
            self.test_cred_btn.setEnabled(True)
        if getattr(self, "_record_cloud_test", False):
            from energy_dashboard.dialogs.component_login import record_link_test
            record_link_test("cloud", bool(ok), str(detail or ""))
            self._record_cloud_test = False
        flow_key = flow_key or ("auth_ok" if ok else "bad")
        self._apply_growatt_link_status(flow_key, method, detail, connected=False)
        title = "Growatt — connection test"
        cb = getattr(self, "_growatt_cloud_test_done", None)
        self._growatt_cloud_test_done = None
        if callable(cb):
            try:
                cb(bool(ok), str(detail or ""))
            except Exception:
                pass
            # Popup already shows the result — skip the modal box.
            if ok:
                self.set_status(f"Growatt test OK — {detail}")
            else:
                self.set_status(f"Growatt test failed — {detail}")
            return
        if ok:
            self.set_status(f"Growatt test OK — {detail}")
            QMessageBox.information(self, title, detail)
        else:
            self.set_status(f"Growatt test failed — {detail}")
            QMessageBox.warning(self, title, detail)

    def _restore_grott_live_path(self) -> bool:
        """Start Grott MQTT when selected. Return True if cloud login should be skipped."""
        if not self._uses_grott():
            return False
        self.apply_grott_settings()
        if self._apply_grott_snapshot_if_needed(force=True):
            return self._grott_only()
        if self._grott_only():
            self._maybe_grott_standby_api()
            self._apply_growatt_link_status(
                "bad",
                self._grott_connection_method(),
                "GROTT MQTT is selected but no fresh snapshot is available yet.",
                connected=False,
            )
            self.set_status("Growatt: GROTT MQTT selected — waiting for a fresh MQTT payload.")
            return True
        self._maybe_grott_standby_api()
        return False

    def _begin_cloud_connect(self) -> bool:
        """Start Growatt cloud login if credentials allow. Returns True if connect started."""
        if self._growatt_connecting:
            return False
        token = self.token_edit.text().strip()
        if token:
            msg = self._growatt_v1_rate_limit_message()
            if msg:
                method = self._growatt_auth_method_label(token)
                self.set_status(msg)
                self._apply_growatt_link_status("bad", method, msg)
                return False
        elif self._growatt_rate_limited():
            msg = "Growatt password login paused (~24 h rate limit) — add API token or wait"
            self.set_status(msg)
            self._apply_growatt_link_status("bad", "Cloud · Legacy login", msg)
            return False
        self._growatt_connecting = True
        self.connect_btn.setEnabled(False)
        gen = self._bump_growatt_auth_gen()
        self.set_status("Connecting to Growatt...")
        threading.Thread(target=self._connect_thread, args=(gen,), daemon=True).start()
        return True

    def connect(self):
        if self._growatt_connecting:
            return
        if self._restore_grott_live_path():
            return
        self._begin_cloud_connect()

    def _connect_thread(self, gen: int):
        try:
            token = self.token_edit.text().strip()
            method = self._growatt_auth_method_label(token)
            if not self._growatt_auth_stale(gen):
                self._inv.invoke(
                    lambda m=method: self._apply_growatt_link_status(
                        "checking", m, "Connecting…",
                    )
                )
            result = self._cached_growatt_auth_result()
            if result:
                result["detail"] = "Connected using recent successful credential test"
                result["flow_key"] = result.get("flow_key") or "auth_ok"
            else:
                result = self._growatt_authenticate()
            if self._growatt_auth_stale(gen):
                return
            if not result.get("ok"):
                detail = result.get("detail") or "Connection failed"
                flow_key = result.get("flow_key") or "bad"
                transient = _growatt_is_transient_error(detail)
                preserve = bool(transient and self.api and self.device_sn)
                if not preserve:
                    self._growatt_reset_session_data()
                self._inv.invoke(
                    lambda d=detail, f=("warn" if transient else flow_key), m=method,
                    g=gen, p=preserve: (
                        self._update_connection(
                            d, False, flow_key=f, method=m, gen=g, preserve_session=p,
                        )
                    )
                )
                return
            self._remember_growatt_auth_result(result)
            self.api = result["api"]
            self.plant_id = result["plant_id"]
            self.plant_name = result["plant_name"]
            self._plant_devices = list(result.get("devices") or [])
            self.device_sn = result["device_sn"]
            self.device_type = result["device_type"]
            flow_key = result.get("flow_key") or "auth_ok"
            detail = result.get("detail") or "Connected"
            inv_m, bat_m, equip = _growatt_resolve_models(
                self.api,
                self.plant_id,
                self._plant_devices,
                self.device_sn,
                self.app_params,
                self.device_type,
                log_device_list=True,
            )
            self._model_inv, self._model_bat = inv_m, bat_m
            self._battery_equipage = equip
            if not self._growatt_auth_stale(gen):
                self._inv.invoke(
                    lambda d=detail, f=flow_key, m=method, g=gen: (
                        self._update_connection(
                            "Connected", True, flow_key=f, method=m, detail=d, gen=g,
                        )
                    )
                )
            self._fetch_live_data()
        except Exception as e:
            err = _growatt_v1_error_message(e)
            self._note_growatt_v1_rate_limit(err)
            method = self._growatt_auth_method_label(self.token_edit.text().strip())
            transient = _growatt_is_transient_error(err)
            preserve = bool(transient and self.api and self.device_sn)
            if not preserve:
                self._growatt_reset_session_data()
            if not self._growatt_auth_stale(gen):
                self._inv.invoke(
                    lambda msg=err, m=method, g=gen, p=preserve: (
                        self._update_connection(
                            msg,
                            False,
                            flow_key=("warn" if p else "bad"),
                            method=m,
                            gen=g,
                            preserve_session=p,
                        )
                    )
                )
        finally:
            if not self._growatt_auth_stale(gen):
                self._inv.invoke(lambda: self.connect_btn.setEnabled(True))
            self._growatt_connecting = False

    def auto_start(self):
        """Restore last session: reload saved source/credentials and reconnect."""
        self._load_growatt_credentials()
        self.sync_source_toggle()
        # Pack serials come from Modbus, not Grott — kick a first poll soon.
        QTimer.singleShot(
            900, lambda: self._schedule_modbus_battery_poll(force=True)
        )
        if self._restore_grott_live_path():
            return
        self._begin_cloud_connect()

    def _apply_device_model_labels(self):
        inv = getattr(self, '_model_inv', '—')
        # Always strip prior equipage suffixes before re-composing (refresh-safe).
        bat = _growatt_strip_equipage_from_model(getattr(self, '_model_bat', '—'))
        self._model_bat = bat
        equip = getattr(self, '_battery_equipage', None) or {}
        if equip.get('label'):
            bat = _growatt_prefer_detected_battery_label(bat, equip)
            # Persist only the stripped base in _model_bat; display uses composed bat.
            # Keep composed text in the widget only so the next refresh can strip cleanly.
        if 'inv_model' in self.info_labels:
            self.info_labels['inv_model'].setText(inv)
            tip = (
                "From Growatt cloud device_list / inverter_detail when available; "
                "otherwise device type or Setup defaults."
            )
            self.info_labels['inv_model'].setToolTip(tip)
        if 'bat_model' in self.info_labels:
            lbl = self.info_labels['bat_model']
            lbl.setWordWrap(True)
            lbl.setText(bat)
            tip_bits = []
            if equip.get('detail'):
                tip_bits.append(str(equip['detail']))
            if equip.get('mismatch'):
                tip_bits.append(str(equip['mismatch']))
            if equip.get('why_missing'):
                tip_bits.append(str(equip['why_missing']))
            if not tip_bits:
                tip_bits.append(
                    "Product/model from cloud when available; pack count lives "
                    "on Physical → Battery equipage."
                )
            lbl.setToolTip(' '.join(tip_bits))
            if equip.get('mismatch') or (
                (equip.get('confidence') or '') in ('partial', 'unknown')
                and equip.get('bus_count')
            ):
                lbl.setStyleSheet("color: #fab387; font-weight: bold;")
            else:
                lbl.setStyleSheet("")

    def _set_connection_status_label(self, text, color):
        lbl = self.info_labels['status']
        pt = _growatt_device_status_font_pt(text)
        lbl.setText(text)
        lbl.setToolTip(text)
        lbl.setFont(QFont('Helvetica', pt, QFont.Bold))
        lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: {pt}pt;")

    def _update_connection(
        self,
        status_text,
        success,
        *,
        flow_key=None,
        method=None,
        detail=None,
        gen=0,
        preserve_session=False,
    ):
        if gen and self._growatt_auth_stale(gen):
            return
        method = method or self._conn_method
        detail = detail if detail is not None else status_text
        if not success:
            self._apply_growatt_link_status(flow_key or "bad", method, detail, connected=False)
        elif flow_key:
            self._apply_growatt_link_status(flow_key, method, detail, connected=True)
        else:
            color = 'green' if success else 'red'
            self._set_connection_status_label(status_text, color)
        self._inverter_comms_lost = False
        if success:
            self.info_labels['plant'].setText(self.plant_name)
            self.info_labels['serial'].setText(self.device_sn)
            self.info_labels['type'].setText(self.device_type)
            self._apply_device_model_labels()
            self.refresh_btn.setEnabled(True)
            self.set_status(f"Connected to Growatt - {self.plant_name}")
        else:
            if not preserve_session:
                self._growatt_clear_session(keep_plant_label=bool(getattr(self, 'plant_name', None)))
            if getattr(self, 'plant_name', None):
                self.info_labels['plant'].setText(self.plant_name)
            if not preserve_session:
                self._model_inv = '—'
                self._model_bat = '—'
                self.info_labels['inv_model'].setText('—')
                self.info_labels['bat_model'].setText('—')
                self._update_physical_display({}, {}, {})
            self.set_status(f"Growatt: {status_text}")
            self._apply_grott_snapshot_if_needed(force=True)
        if not (gen and self._growatt_auth_stale(gen)):
            self.connect_btn.setEnabled(True)

    def _update_inverter_comms_state(self, status) -> None:
        """Cloud login can succeed while the inverter itself is offline."""
        lost, reason = _growatt_inverter_comms_lost(status)
        self._inverter_comms_lost = lost
        if not self.api or not self.device_sn:
            return
        if lost:
            detail = f"Inverter offline{(' (' + reason + ')') if reason and reason != '—' else ''}"
            self._apply_growatt_link_status(
                "warn",
                self._conn_method,
                f"Inverter not reporting live data ({reason or 'lost'}).",
                connected=True,
            )
            self._set_connection_status_label(detail, _GW_RAG_AMBER)
            self.set_status(
                "Growatt cloud OK — inverter not reporting live data "
                f"({reason or 'lost'}). Check datalogger / WiFi / inverter display."
            )
            self._start_shinelan_probe_for_offline(reason)
        else:
            self._set_connection_status_label("Connected", _GW_RAG_GREEN)
            self._apply_growatt_link_status(
                "ok", self._conn_method, "Live data flowing", connected=True,
            )

    def _shinelan_targets(self):
        p = self.app_params
        if p is None:
            return []
        targets = []
        seen = set()
        for label, host, user, pwd in (
            (
                "Wi‑Fi",
                growatt_wifi_host(p),
                getattr(p, "growatt_wifi_user", ""),
                getattr(p, "growatt_wifi_password", ""),
            ),
            (
                "LAN",
                growatt_lan_host(p),
                getattr(p, "growatt_lan_user", ""),
                getattr(p, "growatt_lan_password", ""),
            ),
        ):
            host = (host or "").strip()
            if not host or host in seen:
                continue
            seen.add(host)
            targets.append((label, host, user, pwd))
        return targets

    @staticmethod
    def _shinelan_offline_detail(reason, probe):
        base = f"Inverter offline{(' (' + reason + ')') if reason and reason != '—' else ''}"
        if not probe:
            return base
        if probe.get("server_ip"):
            target = f"{probe.get('server_ip')}:{probe.get('server_port') or '—'}"
            bits = [f"ShineLan target {target}"]
            if probe.get("interval_min"):
                bits.append(f"{probe.get('interval_min')} min")
            return f"{base}. {' | '.join(bits)}"
        detail = probe.get("detail") or probe.get("state_text") or ""
        return f"{base}. {detail}" if detail else base

    def _apply_shinelan_probe_to_offline_status(self, reason, probe):
        if not getattr(self, "_inverter_comms_lost", False):
            return
        detail = self._shinelan_offline_detail(reason, probe)
        self._set_connection_status_label(detail, _GW_RAG_AMBER)
        if probe and probe.get("server_ip"):
            self.set_status(
                "Growatt cloud OK but inverter offline — "
                f"ShineLan points at {probe.get('server_ip')}:{probe.get('server_port') or '—'}."
            )

    def _start_shinelan_probe_for_offline(self, reason):
        targets = self._shinelan_targets()
        if not targets:
            self._apply_shinelan_probe_to_offline_status(
                reason,
                {
                    "state_text": "Not configured",
                    "detail": "Set ShineLan IP under Setup & Info to read logger target",
                },
            )
            return
        if self._last_shinelan_probe and self._last_shinelan_probe_time:
            age_s = (datetime.now() - self._last_shinelan_probe_time).total_seconds()
            if age_s < 90:
                self._apply_shinelan_probe_to_offline_status(reason, self._last_shinelan_probe)
                return
        if self._shinelan_probe_running:
            return
        self._shinelan_probe_running = True
        port = getattr(self.app_params, "growatt_local_port", 80)

        def work():
            result = None
            for label, host, user, pwd in targets:
                r = _growatt_http_probe_sync(host, port, user, pwd)
                r["target_label"] = label
                if result is None or r.get("state_key") in ("ok", "warn"):
                    result = r
                if r.get("server_ip"):
                    break
            self._inv.invoke(lambda r=result, rsn=reason: self._finish_shinelan_probe(rsn, r))

        threading.Thread(target=work, daemon=True).start()

    def _finish_shinelan_probe(self, reason, result):
        self._shinelan_probe_running = False
        self._last_shinelan_probe = result or {}
        self._last_shinelan_probe_time = datetime.now()
        self._apply_shinelan_probe_to_offline_status(reason, self._last_shinelan_probe)

    def _growatt_reset_session_data(self):
        """Clear in-memory Growatt session fields (safe from worker threads)."""
        self.api = None
        self.plant_id = None
        self.device_sn = None
        self.device_type = None
        self.mix_status_data = None
        self.mix_info_data = None
        self.mix_totals_data = None
        self._plant_devices = []
        self._inverter_comms_lost = False

    def _remember_grott_display_bundle(self, status, info, totals) -> None:
        """Keep the last good live bundle for merge when Grott sends partial frames."""
        cache = self._grott_display_cache
        cache["status"] = _merge_nonempty_dict(cache.get("status"), status)
        cache["info"] = _merge_nonempty_dict(cache.get("info"), info)
        cache["totals"] = _merge_nonempty_dict(cache.get("totals"), totals)

    def _grott_display_merge_base(self):
        """Merge bases for an incoming Grott frame (cache → session → new)."""
        cache = self._grott_display_cache or {}
        status = _merge_nonempty_dict(cache.get("status"), self.mix_status_data)
        info = _merge_nonempty_dict(cache.get("info"), self.mix_info_data)
        totals = _merge_nonempty_dict(cache.get("totals"), self.mix_totals_data)
        return status, info, totals

    def _growatt_clear_session(self, *, keep_plant_label: bool = False):
        """Drop cloud API handles and reset UI after disconnect / failed connect."""
        self._growatt_reset_session_data()
        self.refresh_btn.setEnabled(False)
        if not keep_plant_label:
            self.plant_name = None
            if 'plant' in self.info_labels:
                self.info_labels['plant'].setText('—')
        if 'serial' in self.info_labels:
            self.info_labels['serial'].setText('—')
        if 'type' in self.info_labels:
            self.info_labels['type'].setText('—')

    def _invoke_or_call(self, fn, *, from_worker: bool):
        if from_worker:
            self._inv.invoke(fn)
        else:
            fn()

    def _apply_live_bundle(
        self,
        status,
        mix_info,
        mix_totals,
        *,
        source: str,
        from_worker: bool = True,
        notify_downstream: bool = True,
        api_filled_fields=None,
    ):
        if not isinstance(status, dict):
            status = {}
        self.mix_status_data = status
        info_d = mix_info if isinstance(mix_info, dict) else {}
        tot_d = mix_totals if isinstance(mix_totals, dict) else {}
        self._remember_grott_display_bundle(status, info_d, tot_d)
        soc = status.get('SOC', '--')
        discharge = float(status.get('pdisCharge1', 0) or 0)
        charge = float(status.get('chargePower', 0) or 0)
        bat_power = charge - discharge
        pv_power = status.get('ppv', '--')
        grid_estimated = bool(status.get('gridPowerEstimated', False))
        has_grid = (
            grid_estimated
            or "pactouser" in status
            or "pactogrid" in status
        )
        if has_grid:
            grid_import = float(status.get('pactouser', 0) or 0)
            grid_export = float(status.get('pactogrid', 0) or 0)
            grid_power = grid_export - grid_import
        else:
            grid_power = '--'
        load_raw = status.get('pLocalLoad')
        load_estimated = bool(status.get('loadPowerEstimated', False))
        if load_raw in (None, '', '--'):
            derived = grott_derive_load_kw(status)
            if derived is not None:
                load_raw = derived
                load_estimated = True
        try:
            load_power = f"{float(load_raw):.2f}"
        except (TypeError, ValueError):
            load_power = load_raw if load_raw not in (None, '') else '--'
        filled = set(api_filled_fields or [])
        # #region agent log
        from energy_dashboard.core.debug_trace import debug_trace
        debug_trace(
            "growatt.py:_apply_live_bundle",
            "live bundle applied",
            data={
                "source": source,
                "pLocalLoad_raw": status.get("pLocalLoad"),
                "load_power_display": load_power,
                "load_estimated": load_estimated,
                "grid_power_kw": grid_power,
                "grid_estimated": grid_estimated,
                "has_grid": has_grid,
                "pactouser": status.get("pactouser"),
                "pactogrid": status.get("pactogrid"),
                "chargePower": status.get("chargePower"),
                "pdisCharge1": status.get("pdisCharge1"),
                "ppv": status.get("ppv"),
                "api_filled_count": len(filled),
                "v1_rate_limited": self._growatt_v1_rate_limited(),
            },
            hypothesis_id="H3",
            run_id="post-fix",
        )
        # #endregion
        try:
            pv_power = f"{float(pv_power):.2f}"
        except (TypeError, ValueError):
            pass
        self._invoke_or_call(
            lambda: self._update_power_display(
                soc, f"{bat_power:+.2f}", pv_power, grid_power, load_power,
                notify_downstream=notify_downstream, grid_estimated=grid_estimated,
                load_estimated=load_estimated,
                api_filled_fields=filled,
            ),
            from_worker=from_worker,
        )
        if not notify_downstream and getattr(self, "dash", None) is not None:
            self._invoke_or_call(self.dash._update_live_banner, from_worker=from_worker)
        self.mix_info_data = mix_info if isinstance(mix_info, dict) else {}
        if getattr(self, '_model_inv', '—') == '—' or getattr(self, '_model_bat', '—') == '—':
            if source == "cloud":
                inv_m, bat_m, equip = _growatt_resolve_models(
                    self.api,
                    self.plant_id,
                    self._plant_devices,
                    self.device_sn,
                    self.app_params,
                    self.device_type,
                    mix_info=self.mix_info_data,
                    status=status if isinstance(status, dict) else None,
                )
                self._model_inv, self._model_bat = inv_m, bat_m
                self._battery_equipage = equip
                self._invoke_or_call(self._apply_device_model_labels, from_worker=from_worker)
            elif source == "grott":
                inv_m = (
                    self.mix_info_data.get("inverterModel")
                    or self.mix_info_data.get("invertermodel")
                    or self.mix_info_data.get("inv_model")
                    or self.mix_info_data.get("inverter_model")
                    or self.mix_info_data.get("pvmodel")
                    or self.mix_info_data.get("pvModel")
                    or self.mix_info_data.get("inverterType")
                    or self.mix_info_data.get("invertertype")
                    or self.mix_info_data.get("deviceType")
                    or self.mix_info_data.get("devicetype")
                    or self.mix_info_data.get("plantData_deviceType")
                    or self.mix_info_data.get("datalogger_deviceType")
                    or self.mix_info_data.get("model")
                )
                bat_m = (
                    self.mix_info_data.get("batteryModel")
                    or self.mix_info_data.get("batterymodel")
                    or self.mix_info_data.get("bat_model")
                    or self.mix_info_data.get("battery_model")
                    or self.mix_info_data.get("bmsmodel")
                    or self.mix_info_data.get("bmsModel")
                    or self.mix_info_data.get("batteryType")
                    or self.mix_info_data.get("batterytype")
                    or self.mix_info_data.get("batttype")
                )
                equip = _growatt_detect_battery_equipage(
                    devices=getattr(self, '_plant_devices', None),
                    status=status if isinstance(status, dict) else None,
                    info=self.mix_info_data,
                    app_params=self.app_params,
                    modbus_modules=getattr(self, '_modbus_modules', None),
                    modbus_detail=getattr(self, '_modbus_modules_detail', '') or '',
                    modbus_serials=getattr(self, '_modbus_pack_serials', None),
                )
                self._battery_equipage = equip
                changed = False
                if inv_m and getattr(self, '_model_inv', '—') == '—':
                    self._model_inv = str(inv_m)
                    changed = True
                if bat_m and getattr(self, '_model_bat', '—') == '—':
                    self._model_bat = str(bat_m)
                    changed = True
                if equip.get('label'):
                    base = _growatt_strip_equipage_from_model(
                        getattr(self, '_model_bat', '—'),
                    )
                    self._model_bat = base
                    changed = True
                if changed:
                    self._invoke_or_call(self._apply_device_model_labels, from_worker=from_worker)
                if getattr(self, '_model_inv', '—') == '—' or getattr(self, '_model_bat', '—') == '—':
                    self._start_grott_static_api_enrichment()
        self.mix_totals_data = mix_totals if isinstance(mix_totals, dict) else {}
        st = dict(status)
        mi = dict(self.mix_info_data or {})
        mt = dict(self.mix_totals_data or {})
        self._invoke_or_call(
            lambda mt2=mt, af=filled: self._update_totals_display(mt2, api_filled_fields=af),
            from_worker=from_worker,
        )
        self._invoke_or_call(
            lambda s=st, a=mi, b=mt, af=filled: self._update_physical_display(
                s, a, b, api_filled_fields=af,
            ),
            from_worker=from_worker,
        )
        # Grott/cloud never publish parallel pack SNs — keep Modbus pack cache warm.
        self._invoke_or_call(
            lambda: self._schedule_modbus_battery_poll(force=False),
            from_worker=from_worker,
        )
        if source == "cloud":
            self._invoke_or_call(
                lambda s=st: self._update_inverter_comms_state(s),
                from_worker=from_worker,
            )
        elif source == "grott":
            self._invoke_or_call(
                lambda af=filled: self._apply_grott_api_fill_styles(af),
                from_worker=from_worker,
            )

    def _start_grott_static_api_enrichment(self) -> None:
        """Use Growatt cloud only to fill missing static labels while GROTT is live.

        GROTT remains the selected telemetry source.  This background pass is
        deliberately throttled and only updates static metadata such as plant,
        serial, device type, inverter model, and battery model.
        """
        if not self._uses_grott():
            return
        if self._grott_static_enriching:
            return
        now = _time_mod.monotonic()
        if now - self._last_grott_static_enrich < self._grott_static_enrich_interval_s:
            return
        if not (self.token_edit.text().strip() or self.username_edit.text().strip()):
            return
        self._grott_static_enriching = True
        self._last_grott_static_enrich = now
        threading.Thread(target=self._grott_static_api_enrichment_thread, daemon=True).start()

    def _grott_static_api_enrichment_thread(self) -> None:
        try:
            result = self._cached_growatt_auth_result() or self._growatt_authenticate()
            if not result or not result.get("ok"):
                detail = (result or {}).get("detail") or "static API enrichment failed"
                self._inv.invoke(lambda d=detail: self.set_status(f"Growatt static info: {d}"))
                return
            api = result.get("api")
            plant_id = result.get("plant_id")
            devices = list(result.get("devices") or [])
            device_sn = result.get("device_sn") or self.device_sn
            device_type = result.get("device_type") or self.device_type or "mix"
            inv_m, bat_m, equip = _growatt_resolve_models(
                api,
                plant_id,
                devices,
                device_sn,
                self.app_params,
                device_type,
                mix_info=self.mix_info_data,
            )
            payload = {
                "plant_name": result.get("plant_name"),
                "device_sn": device_sn,
                "device_type": device_type,
                "devices": devices,
                "inv_model": inv_m,
                "bat_model": bat_m,
                "equipage": equip,
            }
            self._inv.invoke(lambda p=payload: self._finish_grott_static_api_enrichment(p))
        except Exception as exc:
            msg = _growatt_v1_error_message(exc)
            self._note_growatt_v1_rate_limit(msg)
            self._inv.invoke(lambda m=msg: self.set_status(f"Growatt static info: {m}"))
        finally:
            self._grott_static_enriching = False

    def _finish_grott_static_api_enrichment(self, payload: dict) -> None:
        if not self._uses_grott():
            return
        if payload.get("plant_name") and (not self.plant_name or self.plant_name == "Grott MQTT"):
            self.plant_name = payload["plant_name"]
            self.info_labels['plant'].setText(self.plant_name)
        if payload.get("device_sn") and (not self.device_sn or self.device_sn == "Grott"):
            self.device_sn = payload["device_sn"]
            self.info_labels['serial'].setText(self.device_sn)
        if payload.get("device_type") and (not self.device_type or self.device_type == "mix"):
            self.device_type = payload["device_type"]
            self.info_labels['type'].setText(self.device_type)
        if payload.get("devices"):
            self._plant_devices = list(payload.get("devices") or [])
        changed = False
        if payload.get("inv_model") and getattr(self, '_model_inv', '—') == '—':
            self._model_inv = str(payload["inv_model"])
            changed = True
        if payload.get("bat_model") and getattr(self, '_model_bat', '—') == '—':
            self._model_bat = str(payload["bat_model"])
            changed = True
        if payload.get("equipage"):
            self._battery_equipage = dict(payload.get("equipage") or {})
            changed = True
        if changed:
            self._apply_device_model_labels()
            st = dict(self.mix_status_data or {})
            mi = dict(self.mix_info_data or {})
            mt = dict(self.mix_totals_data or {})
            self._update_physical_display(st, mi, mt)
            self.set_status("Growatt: filled missing static info from cloud API; live data remains GROTT MQTT.")

    def _should_notify_grott_downstream(self, *, force: bool = False) -> bool:
        """Throttle expensive app-wide callbacks from high-rate Grott MQTT.

        The visible Growatt cards update for every accepted Grott snapshot, but
        ``on_data_updated`` fans out into logging, connectivity refreshes, and
        advisory calculations. Running that for every MQTT packet makes the UI
        feel slow, so let it through at a lower cadence.
        """
        if force:
            self._last_grott_downstream_notify = _time_mod.monotonic()
            return True
        now = _time_mod.monotonic()
        if now - self._last_grott_downstream_notify >= _GROTT_DOWNSTREAM_NOTIFY_INTERVAL_S:
            self._last_grott_downstream_notify = now
            return True
        return False

    def _record_grott_present(self, snap: dict) -> None:
        """Mark registers this Grott frame published, keeping recent ones alive.

        Shine/Grott often alternate a full status frame with a 5-key heartbeat
        (SOC, grid V, grid Hz). Replacing the present-set with only the
        heartbeat made every other register look "missing" and get cloud-patched
        amber even though the full frame had just supplied them.
        """
        now = _time_mod.monotonic()
        seen = getattr(self, "_grott_present_seen_at", None)
        if not isinstance(seen, dict):
            seen = {"status": {}, "info": {}, "totals": {}}
            self._grott_present_seen_at = seen
        for section in ("status", "info", "totals"):
            bucket = seen.setdefault(section, {})
            for key, val in dict(snap.get(section) or {}).items():
                if _growatt_value_missing(val):
                    continue
                bucket[str(key)] = now
        try:
            fresh_s = float(self._grott_config().get("fresh_s", 120) or 120)
        except (TypeError, ValueError):
            fresh_s = 120.0
        fresh_s = max(30.0, fresh_s)
        present = {}
        for section in ("status", "info", "totals"):
            bucket = seen.get(section) or {}
            kept = {
                key: ts for key, ts in bucket.items()
                if (now - float(ts)) <= fresh_s
            }
            seen[section] = kept
            present[section] = set(kept.keys())
        self._last_grott_present = present

    def _grott_snapshot_needs_api_gap_fill(self, snap: dict | None) -> bool:
        """True when Grott still has display fields empty that the cloud can supply.

        Uses the accumulated present-set plus merged display cache, not only this
        MQTT frame — otherwise every sparse heartbeat looks like a full gap.
        """
        if not isinstance(snap, dict):
            return False
        present = getattr(self, "_last_grott_present", None) or {}
        st_p = set(present.get("status") or ())
        info_p = set(present.get("info") or ())
        tot_p = set(present.get("totals") or ())
        cache = getattr(self, "_grott_display_cache", None) or {}
        st = _merge_nonempty_dict(cache.get("status"), snap.get("status") or {})
        tot = _merge_nonempty_dict(cache.get("totals"), snap.get("totals") or {})
        info = _merge_nonempty_dict(cache.get("info"), snap.get("info") or {})

        def _missing(d: dict, present_keys: set, *keys: str) -> bool:
            for k in keys:
                if k in present_keys:
                    return False
                if k in d and not _growatt_value_missing(d.get(k)):
                    return False
            return True

        if _missing(st, st_p, "pLocalLoad"):
            if not st.get("gridPowerEstimated") and _missing(
                st, st_p, "pactouser", "pactogrid",
            ):
                return True
        for key in (
            "echargetoday",
            "edischarge1Today",
            "elocalLoadToday",
            "etouser",
            "etoGridToday",
        ):
            if _missing(tot, tot_p, key):
                return True
        if _missing(info, info_p, "vbatdsp", "vBatDsp"):
            return True
        if _missing(st, st_p, "pmax"):
            return True
        if _missing(st, st_p, "wBatteryType"):
            return True
        return False

    def _start_grott_live_api_patch(self, *, gap_fill_only: bool = False) -> None:
        """Background cloud fetch to patch individual missing Grott live registers."""
        # #region agent log
        from energy_dashboard.core.debug_trace import debug_trace
        skip_reason = None
        allow = self._fill_missing_api_enabled() or gap_fill_only
        if not self._uses_grott() or not allow:
            skip_reason = "not_grott_or_fill_disabled"
        elif self._growatt_v1_rate_limited():
            skip_reason = "growatt_api_rate_limited"
        elif self._grott_live_api_patching:
            skip_reason = "already_patching"
        elif _time_mod.monotonic() - self._last_grott_live_api_patch < _GROTT_LIVE_API_PATCH_INTERVAL_S:
            skip_reason = "local_patch_interval"
        elif self._v1_poll_wait_s() > 0:
            skip_reason = "v1_min_poll_interval"
        elif not (self.token_edit.text().strip() or self.username_edit.text().strip()):
            skip_reason = "no_credentials"
        debug_trace(
            "growatt.py:_start_grott_live_api_patch",
            "api patch request",
            data={
                "skip_reason": skip_reason,
                "will_start": skip_reason is None,
                "gap_fill_only": gap_fill_only,
            },
            hypothesis_id="H4",
        )
        # #endregion
        if not self._uses_grott() or not allow:
            return
        # Do not burn the local patch interval while Open API is paused — retry
        # as soon as the pause expires (next Grott snapshot / refresh).
        if self._growatt_v1_rate_limited():
            msg = self._growatt_v1_rate_limit_message()
            if msg and not getattr(self, "_grott_fill_rate_limit_notice", False):
                self._grott_fill_rate_limit_notice = True
                self.set_status(
                    "Growatt: fill-missing paused — Open API rate limit active. "
                    f"{msg}"
                )
                if self.token_edit.text().strip():
                    self._apply_growatt_link_status(
                        "ok",
                        self._grott_connection_method(),
                        f"Live Grott data; fill-missing paused ({msg})",
                        connected=True,
                    )
            return
        self._grott_fill_rate_limit_notice = False
        if self._grott_live_api_patching:
            return
        now = _time_mod.monotonic()
        if now - self._last_grott_live_api_patch < _GROTT_LIVE_API_PATCH_INTERVAL_S:
            return
        # Token sessions share the Open API V1 minimum poll interval with the
        # cloud live poll — fill-missing at 60 s cadence was tripping 10012.
        if self._v1_poll_wait_s() > 0:
            return
        if not (self.token_edit.text().strip() or self.username_edit.text().strip()):
            return
        self._grott_gap_fill_only = gap_fill_only
        self._grott_live_api_patching = True
        self._last_grott_live_api_patch = now
        threading.Thread(target=self._grott_live_api_patch_thread, daemon=True).start()

    def _grott_live_api_patch_thread(self) -> None:
        # #region agent log
        from energy_dashboard.core.debug_trace import debug_trace
        # #endregion
        try:
            cached = self._cached_growatt_auth_result()
            result = cached or self._growatt_authenticate()
            # #region agent log
            debug_trace(
                "growatt.py:_grott_live_api_patch_thread",
                "auth result",
                data={
                    "used_cache": bool(cached),
                    "ok": bool(result and result.get("ok")),
                    "flow_key": (result or {}).get("flow_key"),
                    "detail": str((result or {}).get("detail") or "")[:160],
                    "has_api": bool((result or {}).get("api")),
                    "device_sn": (result or {}).get("device_sn") or self.device_sn,
                    "plant_id": (result or {}).get("plant_id"),
                },
                hypothesis_id="H4",
            )
            # #endregion
            if not result or not result.get("ok"):
                return
            self._remember_growatt_auth_result(result)
            api = result.get("api")
            device_sn = result.get("device_sn") or self.device_sn
            plant_id = result.get("plant_id")
            if not api or not device_sn:
                # #region agent log
                debug_trace(
                    "growatt.py:_grott_live_api_patch_thread",
                    "missing api or device_sn",
                    data={"has_api": bool(api), "device_sn": device_sn},
                    hypothesis_id="H4",
                )
                # #endregion
                return
            # Fresh authenticate already probed live once — reuse that bundle so
            # we do not call sph_energy twice (second call often trips rate limit).
            # Cached auth has no fresh probe; fetch live exactly once.
            if cached:
                api_status = api_info = api_totals = None
            else:
                api_status = result.get("live_status")
                api_info = result.get("live_info")
                api_totals = result.get("live_totals")
            reused_probe = isinstance(api_status, dict)
            if not reused_probe:
                api_status, api_info, api_totals = self._cloud_live_fetch(
                    api, device_sn, plant_id,
                )
            grott_status = dict(self.mix_status_data or {})
            grott_info = dict(self.mix_info_data or {})
            grott_totals = dict(self.mix_totals_data or {})
            present = self._last_grott_present
            merged_status, merged_info, merged_totals, api_filled = _patch_grott_live_from_api(
                grott_status,
                grott_info,
                grott_totals,
                present,
                api_status,
                api_info,
                api_totals,
            )
            # #region agent log
            api_st = api_status if isinstance(api_status, dict) else {}
            debug_trace(
                "growatt.py:_grott_live_api_patch_thread",
                "patch outcome",
                data={
                    "reused_probe": reused_probe,
                    "api_filled": sorted(api_filled or []),
                    "count": len(api_filled or []),
                    "grott_status_keys": sorted(grott_status.keys()),
                    "present_status": sorted((present or {}).get("status") or []),
                    "api_has_pLocalLoad": "pLocalLoad" in api_st,
                    "api_pLocalLoad": api_st.get("pLocalLoad"),
                    "api_has_pactouser": "pactouser" in api_st,
                    "api_pactouser": api_st.get("pactouser"),
                    "api_has_pactogrid": "pactogrid" in api_st,
                    "api_pactogrid": api_st.get("pactogrid"),
                    "api_has_ppv": "ppv" in api_st,
                    "api_ppv": api_st.get("ppv"),
                    "api_status_keys": sorted(api_st.keys())[:40],
                },
                hypothesis_id="H4",
                run_id="post-fix",
            )
            # #endregion
            if not api_filled:
                return
            payload = {
                "status": merged_status,
                "info": merged_info,
                "totals": merged_totals,
                "api_filled": api_filled,
            }
            self._inv.invoke(lambda p=payload: self._finish_grott_live_api_patch(p))
        except Exception as exc:
            msg = _growatt_v1_error_message(exc)
            # #region agent log
            debug_trace(
                "growatt.py:_grott_live_api_patch_thread",
                "patch exception",
                data={
                    "exc_type": type(exc).__name__,
                    "exc": str(exc)[:200],
                    "msg": msg[:240],
                },
                hypothesis_id="H4",
                run_id="post-fix",
            )
            # #endregion
            self._note_growatt_v1_rate_limit(msg)
        finally:
            self._grott_live_api_patching = False

    def _finish_grott_live_api_patch(self, payload: dict) -> None:
        if not self._uses_grott():
            return
        if not self._fill_missing_api_enabled() and not self._grott_gap_fill_only:
            return
        gap_only = self._grott_gap_fill_only
        self._grott_gap_fill_only = False
        api_filled = set(payload.get("api_filled") or [])
        if not api_filled:
            return
        self._apply_live_bundle(
            payload.get("status") or {},
            payload.get("info") or {},
            payload.get("totals") or {},
            source="grott",
            from_worker=False,
            notify_downstream=False,
            api_filled_fields=api_filled,
        )
        self.set_status(
            "Growatt: patched "
            f"{len(api_filled)} missing Grott field(s) from cloud API (amber)."
            if not gap_only
            else
            "Growatt: filled "
            f"{len(api_filled)} empty Grott display field(s) from cloud API (amber)."
        )

    def _apply_grott_api_fill_styles(self, api_filled) -> None:
        api_filled = set(api_filled or [])
        self._api_filled_fields = api_filled
        border_style = (
            f"color: {_GW_RAG_AMBER}; border: 1px solid {_GW_RAG_AMBER}; "
            "border-radius: 3px; padding: 0 3px;"
        )
        text_style = f"color: {_GW_RAG_AMBER};"
        for key, lbl in getattr(self, "power_labels", {}).items():
            base = self._power_label_colors.get(key, "#cdd6f4")
            if key in api_filled:
                lbl.setStyleSheet(text_style)
                lbl.setToolTip(_GROTT_API_FILL_TIP)
            else:
                lbl.setStyleSheet(f"color: {base};")
                if key != "grid_power":
                    lbl.setToolTip("")
        for key, lbl in getattr(self, "total_labels", {}).items():
            base = self._total_label_colors.get(key, "#cdd6f4")
            if key in api_filled:
                lbl.setStyleSheet(text_style)
                lbl.setToolTip(_GROTT_API_FILL_TIP)
            else:
                lbl.setStyleSheet(f"color: {base};")
                lbl.setToolTip("")
        for key, lbl in getattr(self, "physical_labels", {}).items():
            if key in ("dash_kwh", "dash_kw", "dash_eff", "dash_soc_floor",
                       "equip_modules", "equip_kwh", "bat_sns", "sys_faults",
                       "sys_faults_dash"):
                continue
            if key in api_filled:
                lbl.setStyleSheet(border_style)
                lbl.setToolTip(_GROTT_API_FILL_TIP)
            else:
                lbl.setStyleSheet(f"color: #cdd6f4;")
                if key not in ("sys_lost", "bat_type", "sys_faults",
                               "sys_faults_dash", "bat_sns"):
                    lbl.setToolTip("")

    def _sync_api_filled_after_grott_snap(self, api_filled: set, snap: dict) -> set:
        """Drop API-fill markers for registers Grott has published recently.

        Uses the accumulated present-set (union across recent frames) so a
        sparse heartbeat does not re-amber fields a full frame already covered.
        """
        out = set(api_filled or set())
        present = getattr(self, "_last_grott_present", None) or {}
        st_p = set(present.get("status") or ())
        info_p = set(present.get("info") or ())
        tot_p = set(present.get("totals") or ())
        # Also honour keys on this frame directly (covers first snap before
        # present-set rebuild races).
        st = snap.get("status") or {}
        info = snap.get("info") or {}
        tot = snap.get("totals") or {}

        def _grott_has(d: dict, present_keys: set, *keys: str) -> bool:
            for k in keys:
                if k in present_keys:
                    return True
                if k in d and not _growatt_value_missing(d.get(k)):
                    return True
            return False

        if _grott_has(st, st_p, "SOC"):
            out.discard("soc")
        if _grott_has(st, st_p, "ppv"):
            out.discard("pv_power")
        if _grott_has(st, st_p, "chargePower", "pdisCharge1"):
            out.discard("bat_power")
        if _grott_has(st, st_p, "pLocalLoad"):
            out.discard("load_power")
        if _grott_has(st, st_p, "pactouser", "pactogrid"):
            out.discard("grid_power")
        if _grott_has(st, st_p, "vAc1", "vac1"):
            out.discard("grid_v")
        if _grott_has(st, st_p, "fAc"):
            out.discard("grid_hz")
        if _grott_has(st, st_p, "vBat"):
            out.discard("bat_v")
        if _grott_has(st, st_p, "vPv1", "pPv1"):
            out.discard("pv1")
        if _grott_has(st, st_p, "vPv2", "pPv2"):
            out.discard("pv2")
        if _grott_has(st, st_p, "pmax"):
            out.discard("pv_pmax")
        if _grott_has(st, st_p, "wBatteryType"):
            out.discard("bat_type")
        if _grott_has(st, st_p, "lost", "status"):
            out.discard("sys_lost")
        if _grott_has(info, info_p, "vbatdsp", "vBatDsp"):
            out.discard("bat_vdsp")
        for ui_key, d, pset, keys in (
            ("etoday", tot, tot_p, ("epvToday",)),
            ("etotal", tot, tot_p, ("epvTotal",)),
            ("echargetoday", tot, tot_p, ("echargetoday",)),
            ("edischargetoday", tot, tot_p, ("edischarge1Today",)),
            ("load_etoday", tot, tot_p, ("elocalLoadToday",)),
            ("imp_etoday", tot, tot_p, ("etouser", "eToUser", "eToUserToday")),
            ("exp_etoday", tot, tot_p, ("etoGridToday",)),
        ):
            if _grott_has(d, pset, *keys):
                out.discard(ui_key)
        return out

    def _apply_grott_snapshot_if_needed(self, *, force: bool = False, allow_stale: bool = True):
        snap, stale = self._grott_display_snapshot(allow_stale=allow_stale)
        # #region agent log
        from energy_dashboard.core.debug_trace import debug_trace
        debug_trace(
            "growatt.py:_apply_grott_snapshot_if_needed",
            "snapshot check",
            data={
                "force": force,
                "has_snap": bool(snap),
                "stale": stale,
                "uses_grott": self._uses_grott(),
                "snap_age_s": self._grott_snapshot_age_s(snap),
            },
            hypothesis_id="H1",
        )
        # #endregion
        if not snap:
            self._maybe_grott_standby_api()
            return False
        if not self._uses_grott():
            return False
        self._record_grott_present(snap)
        prev_status, prev_info, prev_totals = self._grott_display_merge_base()
        cache_status = dict((self._grott_display_cache or {}).get("status") or {})
        new_status = snap.get("status") or {}
        new_info = snap.get("info") or {}
        new_totals = snap.get("totals") or {}
        merged_status = _merge_nonempty_dict(prev_status, new_status)
        merged_info = _merge_nonempty_dict(prev_info, new_info)
        merged_totals = _merge_nonempty_dict(prev_totals, new_totals)
        api_filled = self._sync_api_filled_after_grott_snap(
            set(getattr(self, "_api_filled_fields", None) or set()),
            snap,
        )
        # #region agent log
        debug_trace(
            "growatt.py:_apply_grott_snapshot_if_needed",
            "grott display merge",
            data={
                "cache_status_keys": len(cache_status),
                "prev_status_keys": len(prev_status),
                "new_status_keys": len(new_status),
                "merged_status_keys": len(merged_status),
                "kept_load": "pLocalLoad" in merged_status,
                "kept_ppv": "ppv" in merged_status,
                "api_filled_count": len(api_filled),
            },
            hypothesis_id="H7",
            run_id="post-fix",
        )
        # #endregion
        self.plant_name = snap.get("plant") or self.plant_name or "Grott MQTT"
        self.device_sn = snap.get("serial") or self.device_sn or self.serial_edit.text().strip() or "Grott"
        self.device_type = self.device_type or "mix"
        self.info_labels['plant'].setText(self.plant_name)
        self.info_labels['serial'].setText(self.device_sn)
        self.info_labels['type'].setText(self.device_type)
        self.refresh_btn.setEnabled(True)
        # A stale snapshot is still worth displaying, but it must not be
        # announced as fresh data: doing so kept the tab bar green and the
        # banner "complete" while the shown values had stopped moving.
        notify = (
            False if stale
            else self._should_notify_grott_downstream(force=force)
        )
        self._apply_live_bundle(
            merged_status,
            merged_info,
            merged_totals,
            source="grott",
            from_worker=False,
            notify_downstream=notify,
            api_filled_fields=api_filled,
        )
        detail = "Live data from Grott MQTT"
        if stale:
            age = self._grott_snapshot_age_s(snap)
            detail = (
                f"Showing last Grott MQTT reading ({age:.0f}s old) — waiting for fresh payload"
                if age is not None
                else "Showing last Grott MQTT reading — waiting for fresh payload"
            )
        self._apply_growatt_link_status(
            "ok" if not stale else "checking",
            self._grott_connection_method(),
            detail,
            connected=True,
        )
        self.last_refresh_label.setText(
            f"Last refresh: {datetime.now().strftime('%H:%M:%S')} (Grott"
            + (" stale)" if stale else ")")
        )
        if force:
            self.set_status(self._grott_refresh_status_text(snap))
        if self._fill_missing_api_enabled():
            self._start_grott_live_api_patch()
        elif self._grott_snapshot_needs_api_gap_fill(snap):
            self._start_grott_live_api_patch(gap_fill_only=True)
        # Only a *fresh* payload counts as a completed refresh. Reporting True
        # for a stale snapshot meant callers stopped trying to recover the feed
        # and the tab sat on frozen values indefinitely.
        return not stale

    @staticmethod
    def _grott_snapshot_age_s(snap: dict | None):
        if not snap:
            return None
        try:
            return max(0.0, _time_mod.time() - float(snap.get("received_at")))
        except (TypeError, ValueError):
            return None

    def _grott_refresh_status_text(self, snap: dict | None) -> str:
        age = self._grott_snapshot_age_s(snap)
        topic = str((snap or {}).get("topic") or "").strip()
        topic_part = f" from {topic}" if topic else ""
        if age is None:
            return f"Growatt: refreshed from cached GROTT MQTT snapshot{topic_part}."
        return f"Growatt: refreshed from GROTT MQTT snapshot{topic_part} ({age:.0f}s old)."

    def _refresh_grott_data(self):
        """Manual Refresh Now behavior while GROTT is the selected source."""
        if self._apply_grott_snapshot_if_needed(force=True):
            return

        # Missing/stale snapshot: do NOT tear down a live MQTT session just
        # because Grott has not published lately (Shine often waits 1–5 min).
        # Full stop/start flapped the broker and looked like intermittent loss.
        status = self.grott_status()
        connected = bool(status.get("connected"))
        now = _time_mod.monotonic()
        if connected:
            if now - self._last_grott_resubscribe >= _GROTT_RESUBSCRIBE_COOLDOWN_S:
                self._last_grott_resubscribe = now
                ok, msg = self._grott.soft_resubscribe()
                self._set_grott_status(msg)
                if not ok:
                    self.set_status(f"Grott MQTT soft recovery failed: {msg}")
        elif now - self._last_grott_resubscribe >= _GROTT_RESUBSCRIBE_COOLDOWN_S:
            self._last_grott_resubscribe = now
            self.apply_grott_settings()

        status = self.grott_status()
        host = status.get("host") or self._grott_config().get("host") or "broker"
        port = status.get("port") or self._grott_config().get("port") or ""
        topic = status.get("topic") or self._grott_config().get("topic") or "energy/growatt"
        age = status.get("age_s")
        age_txt = f"{age:.0f}s since last payload" if age is not None else "no payload yet"
        disc = int(status.get("disconnect_count") or 0)
        rec = int(status.get("reconnect_count") or 0)
        self._apply_growatt_link_status(
            "checking" if status.get("connected") else "warn",
            self._grott_connection_method(),
            "Waiting for the next fresh GROTT MQTT payload "
            f"({age_txt}; disconnects={disc}, reconnects={rec}).",
            connected=bool(status.get("connected")),
        )
        self._maybe_grott_standby_api()
        self.last_refresh_label.setText(
            f"Last refresh: waiting for Grott payload ({datetime.now().strftime('%H:%M:%S')})"
        )
        action = "kept MQTT session" if connected else "full reconnect"
        self.set_status(
            f"Growatt: GROTT MQTT {action} {host}:{port} · {topic}; "
            f"waiting for next payload ({age_txt})."
        )

    def refresh_data(self):
        if self._uses_grott():
            if self._grott_only():
                # Applies the newest snapshot, and resubscribes when the feed
                # has gone quiet instead of re-rendering stale values.
                self._refresh_grott_data()
                return
            if self._apply_grott_snapshot_if_needed(force=True):
                return
        if not self.api or not self.device_sn:
            if self._hybrid_mode():
                self.set_status(
                    "Growatt Hybrid: no fresh Grott snapshot — use Connect for cloud API fallback."
                )
            else:
                self.set_status("Growatt: not connected — use Connect first.")
            return
        if getattr(self, '_growatt_fetching', False):
            self._note_auto_refresh_busy()
            return
        if _growatt_uses_open_api_v1(self.api):
            wait = self._v1_poll_wait_s()
            if wait > 0:
                if self._growatt_v1_rate_limited():
                    self._refresh_v1_pause_notice()
                now = _time_mod.monotonic()
                if now - self._v1_throttle_notice_ts >= 60.0:
                    self._v1_throttle_notice_ts = now
                    self.set_status(
                        "Growatt: Open API V1 allows ~1 live poll per 5 min — "
                        f"next cloud poll in {int(wait)}s."
                    )
                return
        self._growatt_fetching = True
        self.set_status("Refreshing Growatt data...")
        threading.Thread(target=self._fetch_live_data, daemon=True).start()

    def fetch_data(self):
        """Alias for ``refresh_data`` (Refresh Page / Refresh All hook)."""
        self.refresh_data()

    def _fetch_live_data(self):
        if not self.api or not self.device_sn:
            self._growatt_fetching = False
            return
        try:
            if self.device_type == 'mix':
                status, mix_info, mix_totals = self._cloud_live_fetch(
                    self.api, self.device_sn, self.plant_id,
                )
                self._apply_live_bundle(status, mix_info, mix_totals, source="cloud")
            else:
                self._inv.invoke(lambda: self._update_physical_display({}, {}, {}))
            now = datetime.now().strftime("%H:%M:%S")
            self._inv.invoke(lambda: self.last_refresh_label.setText(f"Last refresh: {now}"))
            self._inv.invoke(lambda: self.set_status(f"Growatt data refreshed at {now}"))
        except Exception as e:
            err = _growatt_v1_error_message(e)
            self._note_growatt_v1_rate_limit(err)
            transient = _growatt_is_transient_error(err)
            self._inv.invoke(lambda msg=err: self.set_status(f"Refresh error: {msg}"))
            self._inv.invoke(
                lambda msg=err, tr=transient: self._apply_growatt_link_status(
                    "warn" if tr else "bad", self._conn_method, msg, connected=bool(self.api),
                )
            )
            self._inv.invoke(lambda: self._apply_grott_snapshot_if_needed(force=True))
            if not self.api:
                self._inv.invoke(lambda: self._growatt_clear_session(keep_plant_label=True))
        finally:
            pending = getattr(self, '_auto_refresh_pending', False)
            self._growatt_fetching = False
            self._auto_refresh_pending = False
            if pending and self.api and self.device_sn:
                self._inv.invoke(lambda: QTimer.singleShot(300, self.refresh_data))

    def _update_power_display(
        self,
        soc,
        bat_power,
        pv_power,
        grid_power,
        load_power,
        *,
        notify_downstream: bool = True,
        grid_estimated: bool = False,
        load_estimated: bool = False,
        api_filled_fields=None,
    ):
        api_filled = set(api_filled_fields or [])
        self.power_labels['soc'].setText(str(soc))
        self.power_labels['bat_power'].setText(str(bat_power))
        self.power_labels['pv_power'].setText(str(pv_power))
        # grid_power: numeric export−import (Growatt pactogrid − pactouser)
        glabel = self.power_labels['grid_power']
        _grid_hex = self._power_label_colors.get('grid_power', '#F44336')
        if 'grid_power' in api_filled:
            try:
                gp = float(grid_power)
                glabel.setTextFormat(Qt.TextFormat.PlainText)
                glabel.setText(f"{gp:+.2f}")
            except (TypeError, ValueError):
                glabel.setTextFormat(Qt.TextFormat.PlainText)
                glabel.setText(str(grid_power))
            glabel.setToolTip(_GROTT_API_FILL_TIP)
        else:
            try:
                gp = float(grid_power)
            except (TypeError, ValueError):
                glabel.setTextFormat(Qt.TextFormat.PlainText)
                glabel.setText(str(grid_power))
                glabel.setToolTip("")
            else:
                num = f"{gp:+.2f}"
                if gp > 0:
                    tag = "(exporting)"
                elif gp < 0:
                    tag = "(importing)"
                else:
                    tag = ""
                if grid_estimated:
                    tag = f"{tag} (est.)".strip()
                glabel.setTextFormat(Qt.TextFormat.RichText)
                glabel.setText(_html_grid_power_value(num, tag, _grid_hex))
                glabel.setToolTip(
                    "Grid power is back-solved from PV + battery + load "
                    "(Grott isn't publishing a grid-power register for this "
                    "inverter) — see the Battery Analysis / Optimiser tabs for "
                    "history once real grid data becomes available."
                    if grid_estimated
                    else ""
                )
        self.power_labels['load_power'].setText(str(load_power))
        load_lbl = self.power_labels['load_power']
        if load_estimated and 'load_power' not in api_filled:
            load_lbl.setToolTip(
                "Load is back-solved from grid import/export, PV, and battery "
                "(Grott isn't publishing a house-load register for this inverter)."
            )
        elif 'load_power' not in api_filled:
            load_lbl.setToolTip("")
        if notify_downstream and self.on_data_updated:
            self.on_data_updated()

    def _update_totals_display(self, totals, *, api_filled_fields=None):
        if not isinstance(totals, dict):
            return

        def _fmt_kwh_card(raw):
            if raw is None:
                return '--'
            s = str(raw).strip()
            if not s or s == '--':
                return '--'
            try:
                return f"{float(s):.1f}"
            except (TypeError, ValueError):
                return s

        def _fmt_lifetime_pv(raw):
            """Prefer MWh when the cumulative total is large (easier to read)."""
            ul = self.total_unit_labels.get('etotal')
            if raw is None:
                if ul is not None:
                    ul.setText('kWh')
                return '--'
            s = str(raw).strip()
            if not s or s == '--':
                if ul is not None:
                    ul.setText('kWh')
                return '--'
            try:
                kwh = float(s)
            except (TypeError, ValueError):
                if ul is not None:
                    ul.setText('kWh')
                return s
            if kwh >= 1000.0:
                if ul is not None:
                    ul.setText('MWh')
                return f"{kwh / 1000.0:.2f}"
            if ul is not None:
                ul.setText('kWh')
            return f"{kwh:.1f}"

        self.total_labels['etoday'].setText(_fmt_kwh_card(totals.get('epvToday')))
        self.total_labels['etotal'].setText(_fmt_lifetime_pv(totals.get('epvTotal')))
        self.total_labels['echargetoday'].setText(_fmt_kwh_card(totals.get('echargetoday')))
        self.total_labels['edischargetoday'].setText(
            _fmt_kwh_card(totals.get('edischarge1Today')))

    def _clear_physical_display(self):
        if not getattr(self, 'physical_labels', None):
            return
        for lbl in self.physical_labels.values():
            lbl.setText("—")

    def _apply_battery_modules_override(self):
        spin = getattr(self, "equip_modules_spin", None)
        if spin is None:
            return
        n = int(spin.value())
        if n <= 0:
            _growatt_set_battery_modules_override(None)
            self.set_status("Growatt: battery module count set to Auto (telemetry only).")
        else:
            _growatt_set_battery_modules_override(n)
            kwh = n * float(_GROWATT_BATTERY_UNIT_KWH)
            self.set_status(
                f"Growatt: manual equipage = {n} × {_GROWATT_BATTERY_UNIT_KWH:g} kWh "
                f"(={kwh:g} kWh). Update Setup capacity if planners should use it."
            )
        self._refresh_physical_from_cache()

    def _probe_battery_modules_modbus(self):
        """Manual Probe packs — force an immediate Modbus SN/count read."""
        self._schedule_modbus_battery_poll(force=True, status_msg=True)

    def _modbus_battery_poll_wanted(self) -> bool:
        p = self.app_params
        if p is None:
            return False
        mode = str(getattr(p, "growatt_modbus_mode", "off") or "off").lower()
        return mode in ("tcp", "tcp_rtu")

    def _schedule_modbus_battery_poll(self, *, force: bool = False, status_msg: bool = False):
        """Background Modbus pack SN / count poll (throttled unless force)."""
        if not self._modbus_battery_poll_wanted():
            if status_msg:
                self.set_status(
                    "Growatt Modbus probe — enable Modbus TCP (or RTU over TCP) "
                    "in Setup → Growatt inverter first."
                )
            return
        if getattr(self, "_modbus_battery_polling", False):
            if status_msg:
                self.set_status("Growatt Modbus probe — already running…")
            return
        now = _time_mod.monotonic()
        last = float(getattr(self, "_modbus_battery_poll_ts", 0.0) or 0.0)
        # Keep gateway traffic light: auto polls at most ~once per minute.
        if not force and (now - last) < 55.0:
            return
        btn = getattr(self, "equip_modbus_probe_btn", None)
        if btn is not None and status_msg:
            btn.setEnabled(False)
        self._modbus_battery_polling = True
        threading.Thread(
            target=self._modbus_battery_poll_worker,
            kwargs={"status_msg": bool(status_msg)},
            daemon=True,
        ).start()

    def _modbus_battery_poll_worker(self, *, status_msg: bool = False):
        sns: list[str] = []
        detail_s = ""
        n = None
        detail_n = ""
        err = None
        try:
            sns, detail_s = _growatt_modbus_read_battery_serials(self.app_params)
            n, detail_n = _growatt_modbus_read_battery_modules(
                self.app_params,
                serials=sns,
                serials_detail=detail_s,
            )
            if n is None and sns:
                n = len(sns)
                detail_n = f"Modbus pack SNs → {n} module(s)"
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
        self._inv.invoke(
            lambda: self._apply_modbus_battery_poll_result(
                sns, detail_s, n, detail_n, err=err, status_msg=status_msg
            )
        )

    def _apply_modbus_battery_poll_result(
        self,
        sns,
        detail_s,
        n,
        detail_n,
        *,
        err=None,
        status_msg: bool = False,
    ):
        self._modbus_battery_polling = False
        self._modbus_battery_poll_ts = _time_mod.monotonic()
        btn = getattr(self, "equip_modbus_probe_btn", None)
        if btn is not None:
            btn.setEnabled(True)
        if err:
            if status_msg:
                self.set_status(f"Growatt Modbus probe failed: {err}")
            return
        self._modbus_modules = n
        self._modbus_modules_detail = detail_n or ""
        self._modbus_pack_serials = list(sns or [])
        self._modbus_pack_serials_detail = detail_s or ""
        if status_msg:
            bits = []
            if n is not None:
                bits.append(f"{n} module(s)")
                spin = getattr(self, "equip_modules_spin", None)
                if spin is not None and int(spin.value()) <= 0:
                    try:
                        spin.setValue(int(n))
                    except Exception:
                        pass
            else:
                bits.append(f"count: {detail_n}")
            if sns:
                bits.append(f"SNs: {', '.join(sns)}")
            else:
                bits.append(f"SNs: {detail_s}")
            self.set_status("Growatt Modbus probe — " + " | ".join(bits))
        self._refresh_physical_from_cache()
        if getattr(self, "_model_bat", "—") != "—" or (n is not None) or sns:
            try:
                self._apply_device_model_labels()
            except Exception:
                pass

    def _refresh_physical_from_cache(self):
        st = self.mix_status_data if isinstance(self.mix_status_data, dict) else {}
        mi = self.mix_info_data if isinstance(self.mix_info_data, dict) else {}
        mt = self.mix_totals_data if isinstance(self.mix_totals_data, dict) else {}
        self._update_physical_display(
            st, mi, mt,
            api_filled_fields=getattr(self, "_api_filled_fields", None),
        )

    def _set_physical_wrap_label(
        self, key, text, *, color, tip="", min_lines=2, max_lines=None,
        soft_wrap=True,
    ):
        """Set a wrapping Physical value and reserve height for its rows."""
        lbl = self.physical_labels.get(key)
        if lbl is None:
            return
        text = (text or "").strip() or "—"
        lbl.setText(text)
        lbl.setToolTip(tip or text)
        lbl.setStyleSheet(f"color: {color}; font-weight: bold;")
        n = max(min_lines, text.count("\n") + 1)
        fm = lbl.fontMetrics()
        if soft_wrap:
            # Estimate soft-wrap when a long single line must break.
            try:
                avail = max(160, int(lbl.width()) - 8)
            except Exception:
                avail = 280
            for part in text.split("\n"):
                if not part:
                    continue
                tw = fm.horizontalAdvance(part)
                if tw > avail > 0:
                    n += max(0, (tw - 1) // avail)
        if max_lines is not None:
            n = min(int(max_lines), max(1, n))
        h = int(fm.lineSpacing() * n + 8)
        lbl.setMinimumHeight(h)
        if max_lines is not None:
            lbl.setMaximumHeight(h)
        else:
            lbl.setMaximumHeight(16777215)
        lbl.updateGeometry()
        parent = lbl.parentWidget()
        if parent is not None:
            parent.updateGeometry()

    def _update_physical_display(self, status, info, totals, *, api_filled_fields=None):
        """Populate the Physical panel from status / mix_info / totals dicts."""
        if not getattr(self, 'physical_labels', None):
            return
        p = self.app_params
        if p is not None:
            try:
                self.physical_labels['dash_kwh'].setText(
                    f"{float(p.battery_capacity_kwh):.2f} kWh")
                self.physical_labels['dash_kw'].setText(
                    f"{float(p.analytics_max_charge_kw):.2f} kW")
                self.physical_labels['dash_eff'].setText(
                    f"{float(p.analytics_efficiency_pct):.0f} %")
                self.physical_labels['dash_soc_floor'].setText(
                    f"{int(p.battery_low_soc_threshold_pct)} %")
            except Exception:
                for k in ('dash_kwh', 'dash_kw', 'dash_eff', 'dash_soc_floor'):
                    self.physical_labels[k].setText("—")
        else:
            for k in ('dash_kwh', 'dash_kw', 'dash_eff', 'dash_soc_floor'):
                self.physical_labels[k].setText("—")

        equip = getattr(self, '_battery_equipage', None) or {}
        # Refresh detection on every physical update.
        equip = _growatt_detect_battery_equipage(
            devices=getattr(self, '_plant_devices', None),
            status=status if isinstance(status, dict) else None,
            info=info if isinstance(info, dict) else None,
            app_params=self.app_params,
            modbus_modules=getattr(self, '_modbus_modules', None),
            modbus_detail=getattr(self, '_modbus_modules_detail', '') or '',
            modbus_serials=getattr(self, '_modbus_pack_serials', None),
        )
        self._battery_equipage = equip
        if equip.get('label'):
            # Recompose display from a stripped base — never append onto a prior note.
            base = _growatt_strip_equipage_from_model(getattr(self, '_model_bat', '—'))
            self._model_bat = base
            self._apply_device_model_labels()
        mods = equip.get('modules')
        if mods is not None and 'equip_modules' in self.physical_labels:
            src = equip.get('source') or ''
            suffix = ''
            if src == 'manual_override':
                suffix = ' (manual)'
            elif src == 'modbus':
                suffix = ' (Modbus)'
            self.physical_labels['equip_modules'].setText(
                f"{int(mods)} module{'s' if int(mods) != 1 else ''}{suffix}"
            )
            tip = equip.get('detail') or ''
            if equip.get('mismatch'):
                tip = f"{tip}\n{equip['mismatch']}".strip()
            if equip.get('why_missing'):
                tip = f"{tip}\n{equip['why_missing']}".strip()
            self.physical_labels['equip_modules'].setToolTip(tip)
            if equip.get('mismatch'):
                self.physical_labels['equip_modules'].setStyleSheet(
                    "color: #fab387; font-weight: bold;"
                )
            else:
                self.physical_labels['equip_modules'].setStyleSheet("color: #a6e3a1;")
        elif 'equip_modules' in self.physical_labels:
            why = equip.get('why_missing') or equip.get('detail') or ''
            label = equip.get('label') or 'count unknown'
            self.physical_labels['equip_modules'].setText(label)
            tip = why
            if equip.get('mismatch'):
                tip = f"{tip}\n{equip['mismatch']}".strip()
            self.physical_labels['equip_modules'].setToolTip(tip)
            self.physical_labels['equip_modules'].setStyleSheet(
                "color: #fab387;" if why else "color: #cdd6f4;"
            )
        if equip.get('capacity_kwh') is not None and 'equip_kwh' in self.physical_labels:
            self.physical_labels['equip_kwh'].setText(
                f"{float(equip['capacity_kwh']):.1f} kWh"
            )
            self.physical_labels['equip_kwh'].setToolTip(
                equip.get('detail') or 'modules × 6.5 kWh'
            )
        elif 'equip_kwh' in self.physical_labels:
            setup_m = equip.get('setup_modules')
            if setup_m:
                self.physical_labels['equip_kwh'].setText(
                    f"Setup implies {setup_m * float(equip.get('unit_kwh') or 6.5):.1f} kWh"
                )
            else:
                self.physical_labels['equip_kwh'].setText("—")
            self.physical_labels['equip_kwh'].setToolTip(
                equip.get('mismatch') or equip.get('detail') or ''
            )

        if not isinstance(status, dict):
            status = {}
        if not isinstance(info, dict):
            info = {}
        if not isinstance(totals, dict):
            totals = {}

        def _fmt_hz(x):
            if x is None or str(x).strip() == '':
                return "—"
            try:
                return f"{float(x):.2f} Hz"
            except (TypeError, ValueError):
                return _growatt_physical_str(x)

        def _fmt_v(x):
            if x is None or str(x).strip() == '':
                return "—"
            try:
                return f"{float(x):.1f} V"
            except (TypeError, ValueError):
                return _growatt_physical_str(x)

        def _fmt_w(x):
            if x is None or str(x).strip() == '':
                return "—"
            try:
                v = float(x)
                # mix_status string power is kW (Grott/cloud). Legacy watts
                # (dawn 10–50 used to leak through) still display as W.
                watts = v * 1000.0 if abs(v) < 50 else v
                if abs(watts) >= 1000:
                    return f"{watts / 1000.0:.2f} kW"
                return f"{watts:.0f} W"
            except (TypeError, ValueError):
                return _growatt_physical_str(x)

        def _fmt_kwh_day(x):
            if x is None or str(x).strip() == '':
                return "—"
            try:
                return f"{float(x):.2f} kWh"
            except (TypeError, ValueError):
                return _growatt_physical_str(x)

        gv = status.get('vAc1') if status.get('vAc1') not in (None, '') else status.get('vac1')
        self.physical_labels['grid_v'].setText(_fmt_v(gv))
        self.physical_labels['grid_hz'].setText(_fmt_hz(status.get('fAc')))

        self.physical_labels['bat_v'].setText(_fmt_v(status.get('vBat')))
        vdsp = info.get('vbatdsp') or info.get('vBatDsp')
        self.physical_labels['bat_vdsp'].setText(_fmt_v(vdsp))
        tip_vdsp = "mix_info / Grott bat_dsp: display voltage (V), not a pack counter."
        note = _growatt_anomalous_vdsp_note(status, info)
        if note:
            tip_vdsp = note
            self.physical_labels['bat_vdsp'].setStyleSheet("color: #fab387;")
        else:
            self.physical_labels['bat_vdsp'].setStyleSheet("color: #cdd6f4;")
        self.physical_labels['bat_vdsp'].setToolTip(tip_vdsp)

        disp_bt, tip_bt = _growatt_battery_chemistry_display(status, info)
        lbl_bt = self.physical_labels['bat_type']
        lbl_bt.setTextFormat(Qt.TextFormat.PlainText)
        lbl_bt.setText(disp_bt)
        lbl_bt.setToolTip(tip_bt)

        sn_info = _growatt_collect_battery_serials(
            devices=getattr(self, '_plant_devices', None),
            status=status,
            info=info,
            modbus_sns=getattr(self, '_modbus_pack_serials', None),
            modbus_detail=getattr(self, '_modbus_pack_serials_detail', '') or '',
        )
        if 'bat_sns' in self.physical_labels:
            try:
                sns = list(sn_info.get('serials') or [])
                if sns:
                    # One SN per line so the row grows instead of crowding Faults.
                    sn_text = "\n".join(sns)
                else:
                    sn_text = sn_info.get('label') or '—'
                sn_color = "#a6e3a1" if sn_info.get('count') else "#fab387"
                n_lines = max(1, min(4, len(sns) if sns else 1))
                self._set_physical_wrap_label(
                    'bat_sns', sn_text,
                    color=sn_color,
                    tip=sn_info.get('detail') or sn_text,
                    min_lines=n_lines,
                    max_lines=4,
                    soft_wrap=False,
                )
            except Exception:
                pass

        try:
            alerts = _growatt_decode_inverter_alerts(status, info)
        except Exception:
            alerts = {
                'summary': '—', 'detail': '', 'has_fault': False,
                'has_warning': False, 'healthy': False,
            }
        dash_bits = []
        try:
            win = self.window()
            mon = getattr(win, 'alarm_monitor', None)
            if mon is not None:
                for hit in list(getattr(mon, '_active', {}).values()):
                    title = getattr(hit, 'title', None) or str(hit)
                    dash_bits.append(title)
        except Exception:
            pass
        inv_rows = [
            str(x).strip() for x in (alerts.get('lines') or []) if str(x).strip()
        ]
        if not inv_rows:
            for part in (alerts.get('summary') or '—').split(' | '):
                part = part.strip()
                if part:
                    inv_rows.append(part)
        inv_text = "\n".join(inv_rows) if inv_rows else "—"
        if alerts.get('has_fault'):
            inv_color = "#f38ba8"
        elif alerts.get('has_warning'):
            inv_color = "#fab387"
        elif alerts.get('healthy'):
            inv_color = "#a6e3a1"
        else:
            inv_color = "#cdd6f4"
        self._set_physical_wrap_label(
            'sys_faults', inv_text,
            color=inv_color,
            tip=alerts.get('detail') or inv_text,
            min_lines=1,
        )
        dash_text = "\n".join(dash_bits) if dash_bits else "—"
        dash_color = "#fab387" if dash_bits else "#cdd6f4"
        dash_tip = (
            "Active dashboard alarms (banner):\n" + "\n".join(dash_bits)
            if dash_bits else "No dashboard alarms."
        )
        self._set_physical_wrap_label(
            'sys_faults_dash', dash_text,
            color=dash_color,
            tip=dash_tip,
            min_lines=2 if dash_bits else 1,
        )

        v1, p1 = status.get('vPv1'), status.get('pPv1')
        v2, p2 = status.get('vPv2'), status.get('pPv2')
        self.physical_labels['pv1'].setText(
            f"{_fmt_v(v1)}  ·  {_fmt_w(p1)}" if (v1 not in (None, '') or p1 not in (None, '')) else "—"
        )
        self.physical_labels['pv2'].setText(
            f"{_fmt_v(v2)}  ·  {_fmt_w(p2)}" if (v2 not in (None, '') or p2 not in (None, '')) else "—"
        )

        pm = status.get('pmax')
        if pm is not None and str(pm).strip() != '':
            try:
                self.physical_labels['pv_pmax'].setText(f"{float(pm):.2f} kW (hint)")
            except (TypeError, ValueError):
                self.physical_labels['pv_pmax'].setText(_growatt_physical_str(pm))
        else:
            self.physical_labels['pv_pmax'].setText("—")

        lost = status.get('lost') or status.get('status')
        lost_txt, lost_tip = _growatt_system_status_display(status)
        lbl_lost = self.physical_labels['sys_lost']
        comms_lost, _ = _growatt_inverter_comms_lost(status)
        if comms_lost:
            lbl_lost.setTextFormat(Qt.TextFormat.RichText)
            lbl_lost.setText(
                f"<span style='color:#f38ba8;font-weight:bold;'>{lost_txt}</span>"
            )
        else:
            lbl_lost.setTextFormat(Qt.TextFormat.PlainText)
            lbl_lost.setText(lost_txt)
        if lost_tip:
            lbl_lost.setToolTip(lost_tip)

        self.physical_labels['load_etoday'].setText(
            _fmt_kwh_day(totals.get('elocalLoadToday')))
        imp_today = _growatt_grid_import_today_kwh(totals)
        self.physical_labels['imp_etoday'].setText(
            _fmt_kwh_day(imp_today if imp_today is not None else totals.get('etouser')))
        self.physical_labels['exp_etoday'].setText(
            _fmt_kwh_day(totals.get('etoGridToday')))

    def _on_auto_tick(self):
        if self._uses_grott() or (self.api and self.device_sn):
            self.refresh_data()

    def live_refresh_expectation(self):
        """(active, expected_seconds, detail) for the banner refresh pill."""
        if self._uses_grott():
            fresh_s = max(15, int(self._grott_config().get("fresh_s", 120) or 120))
            return True, float(fresh_s), f"GROTT MQTT push, stale after {fresh_s}s"
        if not (self.api and self.device_sn):
            return False, 60.0, "cloud API not connected"
        if not self._auto_timer.isActive():
            return False, 60.0, "auto-refresh off"
        sec = max(5, int(self._auto_timer.interval() // 1000))
        if _growatt_uses_open_api_v1(self.api):
            sec = max(sec, int(_GROWATT_V1_LIVE_MIN_POLL_S))
            return True, float(sec), f"cloud Open API V1 poll every {sec}s (Growatt rate limit)"
        return True, float(sec), f"cloud API poll every {sec}s"

    def _note_auto_refresh_busy(self):
        """If an auto tick fired during refresh, run again when this fetch finishes."""
        self._auto_refresh_pending = True

    def _update_growatt_refresh_countdown(self):
        self._refresh_v1_pause_notice()
        if not self._auto_timer.isActive():
            self.countdown_label.setText("Auto-refresh off")
            self.countdown_label.setStyleSheet("color: #6c7086; font-size: 12px;")
            return
        rem_ms = self._auto_timer.remainingTime()
        if rem_ms < 0:
            rem_ms = self._auto_timer.interval()
        rem_s = max(0, (rem_ms + 999) // 1000)
        # Cloud V1 sessions poll no faster than the Open API allows — show the
        # real time to the next API call, not the raw timer tick.
        if not self._uses_grott() and _growatt_uses_open_api_v1(self.api):
            wait = self._v1_poll_wait_s()
            if wait > rem_s:
                w = int(wait)
                txt = f"{w // 60}m {w % 60:02d}s" if w >= 120 else f"{w}s"
                self.countdown_label.setText(
                    f"Next Open API poll in {txt} (~5 min rate limit)"
                )
                self.countdown_label.setStyleSheet("color: #fab387; font-size: 12px;")
                return
        self.countdown_label.setText(f"Refreshing in {rem_s}s")
        self.countdown_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 12px;")

    def get_live_data_summary(self):
        if not self.mix_status_data:
            return None
        d = self.mix_status_data
        discharge = float(d.get('pdisCharge1', 0) or 0)
        charge = float(d.get('chargePower', 0) or 0)
        grid_power = growatt_live_grid_kw(d)
        lost, reason = _growatt_inverter_comms_lost(d)
        load = d.get('pLocalLoad')
        if load in (None, '', '--'):
            derived = grott_derive_load_kw(d)
            if derived is not None:
                load = derived
        return {
            'soc': d.get('SOC'), 'bat_power': charge - discharge,
            'pv_power': d.get('ppv'), 'grid_power': grid_power,
            'load_power': load, 'plant_name': self.plant_name,
            'comms_lost': lost, 'comms_reason': reason,
        }

    def get_api(self):
        if self.api and self.device_sn and self.plant_id:
            return self.api, self.plant_id, self.device_sn
        # Still expose the serial when cloud auth is down (GROTT MQTT path) so
        # Battery Analysis can load stored MIX-chart rows for this inverter.
        sn = self.device_sn or (
            self.serial_edit.text().strip() if hasattr(self, "serial_edit") else ""
        )
        if sn in ("Grott",):
            sn = None
        return None, None, sn or None

    def get_current_soc(self):
        """Return cached SOC only — never block the GUI on a live Growatt HTTP call."""
        if self.mix_status_data:
            soc = self.mix_status_data.get('SOC')
            if soc is not None:
                try:
                    return float(soc)
                except (TypeError, ValueError):
                    pass
        return None

    # ── Public contract for sibling tabs ─────────────────────────────────
    # Other pages (Grott/API Align, …) must use ONLY these methods. Reaching
    # into private attributes couples the pages: a rename here silently
    # breaks the caller, and unmanaged cloud polls burn the shared Open API
    # budget and can pause this page for 30 minutes.

    def get_grott_snapshot(self, *, allow_stale: bool = True):
        """Return ``(snapshot, stale)`` — raw Grott MQTT view, never API-patched."""
        snap, stale = self._grott_display_snapshot(allow_stale=allow_stale)
        if snap is None:
            raw = self._grott.snapshot()
            if raw:
                return raw, True
        return snap, stale

    def get_live_battery_capacity_kwh(self):
        """Nominal pack kWh as Growatt Live Status would show, or None.

        Prefers detected equipage (modules × 6.5 kWh GBLI). Falls back to
        Grott ``RatedBatCapacity`` when that field is a plausible kWh figure.
        Does not return the Setup/dashboard-model number — callers that want
        a default should use this first, then Setup.
        """
        equip = getattr(self, "_battery_equipage", None) or {}
        cap = equip.get("capacity_kwh")
        try:
            if cap is not None and float(cap) > 0:
                return float(cap)
        except (TypeError, ValueError):
            pass
        snap = None
        try:
            snap, _stale = self.get_grott_snapshot(allow_stale=True)
        except Exception:
            snap = None
        info = (snap or {}).get("info") if isinstance(snap, dict) else None
        rated = None
        if isinstance(info, dict):
            rated = info.get("RatedBatCapacity") or info.get("ratedbatcapacity")
            if rated in (None, ""):
                rated = info.get("batteryCapacity")
        parsed = _kwh_from_rated_bat_capacity(rated)
        if parsed is not None:
            return parsed
        return None

    def get_cloud_session(self):
        """Return ``(api, device_sn, plant_id)`` from the live session or the
        cached auth result. Never triggers a new login. GUI thread only."""
        api, device_sn, plant_id = self.api, self.device_sn or "", self.plant_id
        if api is None:
            cached = self._cached_growatt_auth_result()
            if isinstance(cached, dict):
                api = cached.get("api")
                device_sn = device_sn or cached.get("device_sn") or ""
                if plant_id is None:
                    plant_id = cached.get("plant_id")
        if not str(device_sn).strip() and hasattr(self, "serial_edit"):
            device_sn = self.serial_edit.text().strip()
        return api, str(device_sn).strip(), plant_id

    def get_recent_cloud_pair(self, max_age_s: float):
        """Return the last raw cloud live read (with the Grott snapshot taken
        at the same moment) if it is younger than ``max_age_s``, else None.

        Reusing this pair costs zero Open API calls and never delays this
        page's own polling — always prefer it over ``fetch_cloud_live_for_sibling``.
        """
        pair = self._last_cloud_pair
        if not pair:
            return None
        age = _time_mod.monotonic() - pair["at"]
        if age > max_age_s:
            return None
        out = dict(pair)
        out["age_s"] = age
        return out

    def open_api_gate(self) -> dict:
        """State of the shared Open API budget:
        ``{"rate_limited": bool, "pause_s": float, "wait_s": float}``.
        ``wait_s`` is seconds until the next V1 live poll is allowed (0 = now).
        """
        rem = self._growatt_v1_rate_limit_remaining()
        pause_s = rem.total_seconds() if rem is not None else 0.0
        return {
            "rate_limited": pause_s > 0,
            "pause_s": pause_s,
            "wait_s": self._v1_poll_wait_s(),
        }

    def fetch_cloud_live_for_sibling(self, api, device_sn, plant_id):
        """One raw cloud live read on behalf of another page.

        Goes through this tab's poll gate and records rate-limit truth, so
        both pages keep one consistent view of the shared budget. Callers
        must check ``open_api_gate()`` first and prefer
        ``get_recent_cloud_pair``. Raises on API failure (caller reports it).
        Worker-thread safe.
        """
        try:
            return self._cloud_live_fetch(api, device_sn, plant_id)
        except Exception as exc:
            self._note_growatt_v1_rate_limit(_growatt_v1_error_message(exc))
            raise


__all__ = [n for n in globals() if not n.startswith('__')]
