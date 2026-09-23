"""
Energy Dashboard — `tabs/parameters.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.dialogs.about_history import AboutDialog, HistoryDialog
from energy_dashboard.db.connect_probe import (
    probe_engine_stages,
)
from energy_dashboard.services.systemd_status import (
    broker_unreachable_hint,
    collect_collector_service_status,
    control_collector_service,
    format_updated_at,
    is_boot_enabled,
    pick_control_scope,
    resolve_broker_base,
)
from energy_dashboard.fetch.grott_mqtt import test_grott_mqtt_connection
from energy_dashboard.fetch.tasmota_mqtt import test_tasmota_mqtt_connection
from energy_dashboard.config import (
    GROWATT_TELEMETRY_API,
    GROWATT_TELEMETRY_GROTT,
    GROWATT_TELEMETRY_HYBRID,
    growatt_uses_grott,
    read_growatt_telemetry_source,
    read_grott_fill_missing_api,
    write_growatt_telemetry_settings,
)

_SETUP_INFO_LABEL_WIDTH = 200
_SETUP_INFO_PAIR_LABEL_WIDTH = 132
_SETUP_INFO_SHORT_LABEL_WIDTH = 64
_SETUP_INFO_SPIN_BTN_GAP = 20
_PARAMS_MAX_PAIRS = 3
# Each pair uses four columns: title, gap, field, then gap before the next title.
# Title columns are anchored to the widest title so every field lines up vertically.
_PARAMS_PAIR_STRIDE = 4
_PARAMS_LABEL_SPIN_GAP = 12
_PARAMS_SPIN_NEXT_GAP = 24
_PARAMS_LABEL_COL_TRIM = 0
_PARAMS_DB_COL0_LEFT = 100
_PARAMS_DB_COL1_LEFT = 50
_PARAMS_DB_CHK_W = 96
_PARAMS_DB_LABEL0_W = 48
_PARAMS_DB_LABEL1_W = 64
_PARAMS_DB_SPIN_LEFT = 120
_PARAMS_DB_PORT_USER_FIELD_LEFT = 200
_PARAMS_DB_PAIR1_FIELD_COL_OFFSET = 3
_PARAMS_DB_PAIR1_FIELD_EXTRA_INSET = 30
_PARAMS_DB_PAIR1_TITLE_LEFT = 30
_PARAMS_DB_PAIR1_COL1_REDUCE = 8
_PARAMS_DB_PAIR1_LABEL_SPIN_GAP = 4
_PARAMS_DB_FIELD_W = _SETUP_INFO_SPIN_W + 30
_PARAMS_DB_GRID_VSPACE = 10
_PARAMS_DB_ROW_MIN_H = _SETUP_INFO_SPIN_H + 8
_PARAMS_DB_SQLITE_SEEN_PAD = 20
_PARAMS_GRID_SPAN = _PARAMS_MAX_PAIRS * _PARAMS_PAIR_STRIDE
_PARAMS_DB_STATUS_MIN_W = 160
_PARAMS_DB_STATUS_MAX_W = 300
_PARAMS_DB_SCHEMA_MIN_W = 280
_DB_RAG_GREEN = "#a6e3a1"
_DB_RAG_AMBER = "#fab387"
_DB_RAG_RED = "#f38ba8"
_DB_RAG_GREY = "#6c7086"
_EMQX_ROUTE_DEFAULT_HOST = "222.20.20.212"
_EMQX_ROUTE_DEFAULT_PORT = 1883


def _params_soft_wrap_html(text) -> str:
    """Escape text for rich labels and add HTML break hints inside long URLs/paths."""
    s = html.escape(str(text or ""))
    for ch in ("/", ".", ":", "-", "_", "?", "&amp;", "="):
        s = s.replace(ch, f"{ch}&#8203;")
    return s


def _params_left_inset(widget: QWidget, px: int, *, min_h: int = 0) -> QWidget:
    if px <= 0 and min_h <= 0:
        return widget
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(max(0, px), 0, 0, 0)
    row.setSpacing(0)
    row.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
    if min_h > 0:
        box.setMinimumHeight(min_h)
    return box


def _params_label_col(pair_index: int) -> int:
    return pair_index * _PARAMS_PAIR_STRIDE


def _params_field_col(pair_index: int) -> int:
    return pair_index * _PARAMS_PAIR_STRIDE + 2


def _params_field_label(text: str, *, pair: bool = False) -> QLabel:
    """Title that shows its full text (no truncation); column width anchors layout."""
    lbl = QLabel(text)
    lbl.setFixedHeight(_SETUP_INFO_SPIN_H)
    lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return lbl


def _params_label_text_width(text: str, font) -> int:
    return QFontMetrics(font).horizontalAdvance(text.strip()) + 6


def _params_grid_field_width_needs(grid: QGridLayout) -> dict[int, int]:
    """Minimum field-column width per pair index (from widgets in the grid)."""
    needs: dict[int, int] = {}
    default = (
        _PARAMS_DB_FIELD_W if grid.property("_params_db_backend_grid") else _SETUP_INFO_SPIN_W
    )
    for i in range(grid.count()):
        w = grid.itemAt(i).widget()
        if w is None:
            continue
        _, col, _, _ = grid.getItemPosition(i)
        if col % _PARAMS_PAIR_STRIDE != 2:
            continue
        pos = col // _PARAMS_PAIR_STRIDE
        mw = w.minimumWidth()
        need = max(default, mw) if mw > 0 else default
        needs[pos] = max(needs.get(pos, 0), need)
    return needs


def _params_apply_grid_columns(
    grid: QGridLayout,
    label_widths: dict | None = None,
    field_widths: dict | None = None,
) -> None:
    """Title columns = widest title; compact gap before field and before next title."""
    widths = label_widths or {}
    fw = field_widths or {}
    label_gap = _PARAMS_LABEL_SPIN_GAP
    spin_next_gap = _PARAMS_SPIN_NEXT_GAP
    field_w = (
        _PARAMS_DB_FIELD_W if grid.property("_params_db_backend_grid") else _SETUP_INFO_SPIN_W
    )
    db_grid = bool(grid.property("_params_db_backend_grid"))
    for p in range(_PARAMS_MAX_PAIRS):
        b = p * _PARAMS_PAIR_STRIDE
        if db_grid and p == 0:
            label_w = _PARAMS_DB_LABEL0_W
        elif db_grid and p == 1:
            label_w = _PARAMS_DB_LABEL1_W
        else:
            label_w = widths.get(p, _SETUP_INFO_LABEL_WIDTH)
        grid.setColumnMinimumWidth(b, label_w)
        pair_label_gap = label_gap
        if db_grid and p == 0:
            pair_label_gap = max(
                0,
                label_gap
                - max(0, _PARAMS_DB_SPIN_LEFT - _PARAMS_DB_COL0_LEFT)
                - _PARAMS_DB_PAIR1_COL1_REDUCE,
            )
        grid.setColumnMinimumWidth(b + 1, pair_label_gap)
        grid.setColumnMinimumWidth(b + 2, fw.get(p, field_w))
        gap_after = spin_next_gap
        if db_grid and p == 0:
            gap_after = max(
                0,
                spin_next_gap
                - max(0, _PARAMS_DB_SPIN_LEFT - _PARAMS_DB_COL1_LEFT),
            )
        grid.setColumnMinimumWidth(b + 3, gap_after)
        for c in range(b, b + _PARAMS_PAIR_STRIDE):
            grid.setColumnStretch(c, 0)
    grid.setColumnStretch(_PARAMS_GRID_SPAN, 1)


def _params_grid_add_pairs(grid: QGridLayout, row: int, pairs: list) -> None:
    """Up to three title+field pairs per row, condensed with fixed 30/40px gaps."""
    align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    grid.setRowMinimumHeight(row, _SETUP_INFO_SPIN_H)
    for i, (text, widget) in enumerate(pairs[:_PARAMS_MAX_PAIRS]):
        grid.addWidget(_params_field_label(text, pair=i > 0), row, _params_label_col(i), align)
        grid.addWidget(widget, row, _params_field_col(i), align)


def _params_add_field_grid(parent_layout: QVBoxLayout, grid: QGridLayout) -> None:
    parent_layout.addLayout(grid)


def _params_add_db_section_rule(parent_layout: QVBoxLayout) -> None:
    """Thin horizontal rule between database backend sections."""
    parent_layout.addSpacing(8)
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setFixedHeight(1)
    line.setStyleSheet(f"QFrame {{ background-color: {_DARK_GRID}; border: none; max-height: 1px; }}")
    parent_layout.addWidget(line)
    parent_layout.addSpacing(8)


def _params_db_pair1_labeled_field(text: str, field: QWidget, *, min_h: int) -> QWidget:
    """Pair-1 title + field in one cell; fixed label width keeps spin boxes left-aligned."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(_PARAMS_DB_PAIR1_LABEL_SPIN_GAP)
    lbl = _params_field_label(text, pair=True)
    lbl.setFixedWidth(_PARAMS_DB_LABEL1_W)
    lay.addWidget(lbl)
    field_cell = QWidget()
    field_cell.setFixedWidth(_PARAMS_DB_FIELD_W)
    field_lay = QHBoxLayout(field_cell)
    field_lay.setContentsMargins(0, 0, 0, 0)
    field_lay.setSpacing(0)
    field_lay.addWidget(field, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    lay.addWidget(field_cell)
    if min_h > 0:
        row.setMinimumHeight(min_h)
    return row


def _params_db_pass_field_width(
    c0_field: int,
    c1_field_inset: int,
    *,
    grid_hspace: int,
) -> int:
    """Width from pass field left edge (host column) to user field right edge."""
    return (
        _PARAMS_DB_FIELD_W
        + grid_hspace
        + c1_field_inset
        + _PARAMS_DB_LABEL1_W
        + _PARAMS_DB_PAIR1_LABEL_SPIN_GAP
        + _PARAMS_DB_FIELD_W
        - c0_field
    )


def _params_add_db_backend_grid(
    parent_layout: QVBoxLayout,
    chk: QCheckBox,
    host_edit: QLineEdit,
    port_spin: QSpinBox,
    db_edit: QLineEdit,
    user_edit: QLineEdit,
    pass_edit: QLineEdit,
    status_panel: QWidget,
    schema_panel: QWidget,
) -> None:
    """Checkbox, fields, left-aligned status, then create-all SQL on the right."""
    section = QHBoxLayout()
    section.setContentsMargins(0, 0, 0, 0)
    section.setSpacing(8)
    section.addWidget(chk, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    grid = _params_make_field_grid()
    grid.setProperty("_params_db_backend_grid", True)
    grid.setVerticalSpacing(_PARAMS_DB_GRID_VSPACE)
    for row in range(3):
        grid.setRowMinimumHeight(row, _PARAMS_DB_ROW_MIN_H)
    align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    port_spin.setProperty("_params_db_field", True)
    c0 = _PARAMS_DB_COL0_LEFT
    c0_field = max(0, c0 - _PARAMS_DB_SPIN_LEFT)
    c1_field_col = _params_field_col(1) - _PARAMS_DB_PAIR1_FIELD_COL_OFFSET
    c1_field_inset = _PARAMS_DB_PAIR1_FIELD_EXTRA_INSET - _PARAMS_DB_PAIR1_TITLE_LEFT
    pass_w = _params_db_pass_field_width(
        c0_field, c1_field_inset, grid_hspace=grid.horizontalSpacing()
    )
    for edit in (host_edit, db_edit, user_edit, pass_edit):
        edit.setObjectName("paramsDbField")
        edit.setFixedWidth(_PARAMS_DB_FIELD_W)
        edit.setFixedHeight(_SETUP_INFO_SPIN_H)
    pass_edit.setFixedWidth(pass_w)
    row_h = _PARAMS_DB_ROW_MIN_H
    grid.addWidget(_params_left_inset(_params_field_label("Host:"), c0, min_h=row_h), 0, _params_label_col(0), align)
    grid.addWidget(_params_left_inset(host_edit, c0_field, min_h=row_h), 0, _params_field_col(0), align)
    grid.addWidget(
        _params_left_inset(_params_db_pair1_labeled_field("Port:", port_spin, min_h=row_h), c1_field_inset, min_h=row_h),
        0,
        c1_field_col,
        align,
    )
    grid.addWidget(_params_left_inset(_params_field_label("DB:"), c0, min_h=row_h), 1, _params_label_col(0), align)
    grid.addWidget(_params_left_inset(db_edit, c0_field, min_h=row_h), 1, _params_field_col(0), align)
    grid.addWidget(
        _params_left_inset(_params_db_pair1_labeled_field("User:", user_edit, min_h=row_h), c1_field_inset, min_h=row_h),
        1,
        c1_field_col,
        align,
    )
    grid.addWidget(_params_left_inset(_params_field_label("Pass:"), c0, min_h=row_h), 2, _params_label_col(0), align)
    grid.addWidget(_params_left_inset(pass_edit, c0_field, min_h=row_h), 2, _params_field_col(0), 1, _PARAMS_PAIR_STRIDE, align)
    section.addLayout(grid, 0)
    section.addWidget(
        status_panel,
        0,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )
    section.addWidget(schema_panel, 1)
    parent_layout.addLayout(section)


def _params_make_field_grid() -> QGridLayout:
    grid = QGridLayout()
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(6)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setProperty("_params_field_grid", True)
    _params_apply_grid_columns(grid)
    return grid


class ParametersTab(QWidget):
    """Central place to vary tariffs, simulation defaults, Agile codes, and refresh timing."""

    def __init__(self, dashboard):
        super().__init__()
        self.dash = dashboard
        self.p = dashboard.app_params
        self._inv = Invoker(self)
        self._modbus_test_token = 0
        self.build_ui()

    def _set_growatt_local_status(self, connected, detail: str = ""):
        lbl = getattr(self, "lbl_growatt_local_status", None)
        if lbl is None:
            return
        if connected is None:
            colour = _UI_BLUE
            text = "Testing..."
            prefix = "..."
        elif connected:
            colour = "#a6e3a1"
            text = "Connected"
            prefix = "✓"
        else:
            colour = "#f38ba8"
            text = "Not Connected"
            prefix = "✗"
        lbl.setText(
            f"<span style='color:{colour}; font-weight:bold; font-size:12px;'>"
            f"{prefix} {text}</span>"
        )
        lbl.setToolTip(detail or text)

    def _set_growatt_modbus_status(self, connected, detail: str = ""):
        """Connected / Disconnected indicator for the Local Modbus section."""
        lbl = getattr(self, "lbl_growatt_modbus_status", None)
        if lbl is None:
            return
        if connected is None:
            colour = _UI_BLUE
            text = "Testing..."
            prefix = "..."
        elif connected:
            colour = "#a6e3a1"
            text = "Connected"
            prefix = "✓"
        else:
            colour = "#f38ba8"
            text = "Disconnected"
            prefix = "✗"
        lbl.setText(
            f"<span style='color:{colour}; font-weight:bold; font-size:12px;'>"
            f"{prefix} {text}</span>"
        )
        lbl.setToolTip(detail or text)

    def _update_grott_source_controls(self):
        source = self._growatt_form_source()
        selected = growatt_uses_grott(source)
        for widget in getattr(self, "_grott_source_widgets", []):
            widget.setEnabled(selected)
        if hasattr(self, "chk_grott_fill_missing"):
            self.chk_grott_fill_missing.setEnabled(selected)

    def _growatt_form_source(self) -> str:
        if getattr(self, "rb_growatt_hybrid", None) and self.rb_growatt_hybrid.isChecked():
            return GROWATT_TELEMETRY_HYBRID
        if getattr(self, "chk_grott_mqtt", None) and self.chk_grott_mqtt.isChecked():
            return GROWATT_TELEMETRY_GROTT
        return GROWATT_TELEMETRY_API

    def _make_db_action_row(self, backend: str) -> QHBoxLayout:
        labels = {
            "sqlite": "SQLite",
            "mysql": "MySQL",
            "pg": "PostgreSQL",
        }
        label = labels.get(backend, backend)
        row = QHBoxLayout()
        row.setContentsMargins(_PARAMS_DB_CHK_W + 8 + _PARAMS_DB_COL0_LEFT, 0, 0, 0)
        row.setSpacing(8)

        save_btn = QPushButton("Save DB Config")
        save_btn.setToolTip(f"Save {label} database settings and reconfigure logging")
        save_btn.clicked.connect(lambda _checked=False, b=backend: self._save_db_config(b))
        row.addWidget(save_btn)

        test_btn = QPushButton("Test Connection")
        test_btn.setToolTip(f"Test the {label} database connection using this row's settings")
        test_btn.clicked.connect(lambda _checked=False, b=backend: self._test_db_connections(b))
        row.addWidget(test_btn)

        setup_btn = QPushButton("Setup Database")
        if backend == "pg":
            setup_btn.setToolTip(
                "Does not create tables. Copy CREATE SQL and run it by hand "
                "as the database owner. This login is not allowed to create tables."
            )
        else:
            setup_btn.setToolTip(
                f"Create/upgrade the {label} database schema (CREATE IF NOT EXISTS). "
                "The SQL on the right is the script that runs."
            )
        setup_btn.clicked.connect(lambda _checked=False, b=backend: self._setup_database(b))
        row.addWidget(setup_btn)
        self._db_setup_buttons.append(setup_btn)

        copy_sql_btn = QPushButton("Copy CREATE SQL")
        copy_sql_btn.setToolTip(
            f"Copy the full {label} CREATE script (all logger tables) to the clipboard"
        )
        copy_sql_btn.clicked.connect(
            lambda _checked=False, b=backend: self._copy_db_schema_sql(b)
        )
        row.addWidget(copy_sql_btn)

        missing_btn = QPushButton("Show missing")
        missing_btn.setToolTip(
            f"List logger tables that are not on this {label} database yet, "
            "and show CREATE SQL for only those tables"
        )
        missing_btn.clicked.connect(
            lambda _checked=False, b=backend: self._show_missing_tables(b)
        )
        row.addWidget(missing_btn)

        ring_btn = QPushButton("Ring buffers…")
        ring_btn.setToolTip(f"Open ring-buffer limits for {label} logged data")
        ring_btn.clicked.connect(lambda _checked=False, b=backend: self._open_ring_buffers_dialog(b))
        row.addWidget(ring_btn)
        row.addStretch(1)
        return row

    def build_ui(self):
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        self._setup_scroll = scroll
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setSpacing(12)

        def add_group(title):
            gb = QGroupBox(title)
            gb.setStyleSheet(
                "QGroupBox { font-weight: bold; margin-top: 10px; }"
                "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
            )
            gl = QVBoxLayout(gb)
            lay.addWidget(gb)
            return gl

        # --- About / History row ---
        # Two pop-up buttons sit at the very top of Setup & Info so the
        # version copy and patch notes are reachable from a stable, easy
        # to find location regardless of which tab the user is on.
        info_row = QHBoxLayout()
        info_row.setContentsMargins(0, 0, 0, 0)
        about_btn = QPushButton("About")
        about_btn.setToolTip("Show app description and credits")
        about_btn.setMinimumWidth(110)
        about_btn.clicked.connect(self._show_about_dialog)
        history_btn = QPushButton("History")
        history_btn.setToolTip("Show per-patch change log (newest first)")
        history_btn.setMinimumWidth(110)
        history_btn.clicked.connect(self._show_history_dialog)
        ver_lbl = QLabel(f"<span style='color:#6c7086;'>v{APP_VERSION}</span>")
        ver_lbl.setTextFormat(Qt.RichText)
        info_row.addWidget(about_btn)
        info_row.addWidget(history_btn)
        info_row.addSpacing(12)
        info_row.addWidget(ver_lbl)
        info_row.addStretch(1)
        lay.addLayout(info_row)

        # --- Background collector system service ---
        g_svc = add_group("Background collector")
        svc_hint = QLabel(
            "The <b>energy-collector</b> boot service polls Tasmota and Growatt, writes to PostgreSQL, "
            "and serves <code>GET /snapshot</code> for the Tasmota tab. "
            "Install once with <code>sudo ./services/install-energy-collector.sh</code> "
            "(runs at boot; no need to keep this dashboard open). "
            "If the broker runs in a <b>container</b> or on another host, set <b>Broker URL</b> below "
            "(not <code>127.0.0.1</code> unless the dashboard shares that network namespace)."
        )
        svc_hint.setWordWrap(True)
        svc_hint.setTextFormat(Qt.RichText)
        svc_hint.setStyleSheet("color: #6c7086; font-size: 11px; font-weight: normal;")
        g_svc.addWidget(svc_hint)
        broker_cfg = QHBoxLayout()
        broker_cfg.setSpacing(8)
        broker_cfg.addWidget(QLabel("Broker URL:"))
        self.ed_broker_url = QLineEdit()
        self.ed_broker_url.setPlaceholderText("http://192.168.1.10:8765")
        self.ed_broker_url.setMinimumWidth(280)
        self.ed_broker_url.setMaximumWidth(440)
        # Preferred (not Expanding): the trailing stretch absorbs surplus width
        # so the field stays compact on the left instead of stretching.
        self.ed_broker_url.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.ed_broker_url.setToolTip(
            "Base URL for GET /health and GET /snapshot (powermon_broker / energy-collector). "
            "Use the container or remote host address reachable from this PC — e.g. "
            "http://192.168.1.10:8765. Shared with the Tasmota tab broker settings."
        )
        broker_cfg.addWidget(self.ed_broker_url)
        self.btn_broker_save = QPushButton("Save")
        self.btn_broker_save.setStyleSheet(_SUBTLE_BTN_QSS)
        # Fixed policy stops buttons ballooning to eat surplus row width.
        self.btn_broker_save.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_broker_save.setFixedWidth(88)
        self.btn_broker_save.setToolTip(
            "Save broker URL to disk and sync the Tasmota tab field"
        )
        self.btn_broker_save.clicked.connect(self._save_broker_url)
        broker_cfg.addWidget(self.btn_broker_save)
        self.btn_broker_test = QPushButton("Test")
        self.btn_broker_test.setStyleSheet(_SUBTLE_BTN_QSS)
        self.btn_broker_test.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_broker_test.setFixedWidth(88)
        self.btn_broker_test.setToolTip(
            "Probe GET /health on the URL above (uses the field value, even before Save)"
        )
        self.btn_broker_test.clicked.connect(self._test_broker_url)
        broker_cfg.addWidget(self.btn_broker_test)
        broker_cfg.addStretch(1)
        g_svc.addLayout(broker_cfg)
        self._load_broker_url_from_settings()
        svc_row = QGridLayout()
        svc_row.setContentsMargins(0, 0, 0, 0)
        svc_row.setHorizontalSpacing(8)
        svc_row.setVerticalSpacing(4)
        svc_row.setColumnStretch(1, 1)
        svc_row.addWidget(QLabel("Collector:"), 0, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.lbl_svc_system = QLabel("checking…")
        self.lbl_svc_system.setWordWrap(True)
        self.lbl_svc_system.setMinimumWidth(0)
        self.lbl_svc_system.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        svc_row.addWidget(self.lbl_svc_system, 0, 1)
        svc_row.addWidget(QLabel("HTTP broker:"), 1, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.lbl_svc_http = QLabel("checking…")
        self.lbl_svc_http.setWordWrap(True)
        self.lbl_svc_http.setMinimumWidth(0)
        self.lbl_svc_http.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        svc_row.addWidget(self.lbl_svc_http, 1, 1)
        self.btn_svc_refresh = QPushButton("Refresh")
        self.btn_svc_refresh.setStyleSheet(_SUBTLE_BTN_QSS)
        self.btn_svc_refresh.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_svc_refresh.setFixedWidth(96)
        self.btn_svc_refresh.clicked.connect(self._probe_service_async)
        g_svc.addLayout(svc_row)
        svc_ctrl = QHBoxLayout()
        svc_ctrl.setSpacing(8)
        self.btn_svc_start = QPushButton("Start/Restart")
        self.btn_svc_start.setStyleSheet(_SUBTLE_BTN_QSS)
        self.btn_svc_start.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_svc_start.setFixedWidth(120)
        self.btn_svc_start.setToolTip(
            "Start or restart the collector. Uses the user-session unit when "
            "installed (no sudo). The boot service needs a terminal sudo."
        )
        self.btn_svc_start.clicked.connect(self._svc_start_restart)
        svc_ctrl.addWidget(self.btn_svc_start)
        self.btn_svc_stop = QPushButton("Stop")
        self.btn_svc_stop.setStyleSheet(_SUBTLE_BTN_QSS)
        self.btn_svc_stop.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_svc_stop.setFixedWidth(96)
        self.btn_svc_stop.setToolTip("Stop the energy-collector service.")
        self.btn_svc_stop.clicked.connect(self._svc_stop)
        svc_ctrl.addWidget(self.btn_svc_stop)
        self.btn_svc_boot = QPushButton("Boot Start")
        self.btn_svc_boot.setProperty("tasmotaToggle", True)
        self.btn_svc_boot.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_svc_boot.setFixedWidth(120)
        self.btn_svc_boot.setToolTip(
            "Enable or disable starting energy-collector at boot. "
            "Green = enabled, red = disabled."
        )
        self.btn_svc_boot.clicked.connect(self._svc_toggle_boot)
        svc_ctrl.addWidget(self.btn_svc_boot)
        svc_ctrl.addWidget(self.btn_svc_refresh)
        svc_ctrl.addStretch(1)
        g_svc.addLayout(svc_ctrl)
        self._service_status = None
        self._service_control_busy = False
        self._update_svc_boot_button()
        self.lbl_svc_detail = QLabel("—")
        self.lbl_svc_detail.setWordWrap(True)
        self.lbl_svc_detail.setTextFormat(Qt.RichText)
        self.lbl_svc_detail.setMinimumWidth(0)
        self.lbl_svc_detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_svc_detail.setStyleSheet("color: #6c7086; font-size: 11px; font-weight: normal;")
        g_svc.addWidget(self.lbl_svc_detail)

        # --- Main window tab visibility ---
        g_tabs = add_group("Main window — tab bar")
        tab_hint = QLabel(
            "Uncheck tabs you rarely use to shorten the bar. "
            "Groups on the left of the tab bar are always visible. Within a "
            "group, <b>Octopus Energy Data</b>, <b>Growatt Live Status</b>, and "
            "<b>Setup && Info</b> always stay visible. "
            "Click <b>Apply tab bar</b> to save and refresh immediately."
        )
        tab_hint.setWordWrap(True)
        tab_hint.setTextFormat(Qt.RichText)
        tab_hint.setStyleSheet("color: #6c7086; font-size: 11px; font-weight: normal;")
        g_tabs.addWidget(tab_hint)
        self._tab_visibility_checks = {}
        s_vis = QSettings("PowerModel", "EnergyDashboard2")
        tab_grid = QGridLayout()
        tab_grid.setHorizontalSpacing(24)
        tab_grid.setVerticalSpacing(5)
        tab_grid.setContentsMargins(0, 0, 0, 0)
        _tab_cols = 4
        for c in range(_tab_cols):
            tab_grid.setColumnStretch(c, 1)
        _toggleable = [
            (k, t) for (k, _a, t, _g, _u) in _MAIN_TAB_BAR_REGISTRY if k is not None
        ]
        n = len(_toggleable)
        rows_per_col = (n + _tab_cols - 1) // _tab_cols
        for idx, (key, title) in enumerate(_toggleable):
            cb = QCheckBox(title.strip())
            cb.setChecked(s_vis.value(f"tabs/visible/{key}", True, type=bool))
            self._tab_visibility_checks[key] = cb
            row = idx % rows_per_col
            col = idx // rows_per_col
            tab_grid.addWidget(cb, row, col)
        g_tabs.addLayout(tab_grid)
        tab_btn_row = QHBoxLayout()
        apply_tabs_btn = QPushButton("Apply tab bar")
        apply_tabs_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        apply_tabs_btn.setToolTip(
            "Write tab visibility to QSettings and rebuild the main tab bar "
            "(hidden tabs stay loaded — Refresh All and data logging still work)."
        )
        apply_tabs_btn.clicked.connect(self._apply_main_tab_bar_visibility)
        tab_btn_row.addWidget(apply_tabs_btn)
        show_all_tabs_btn = QPushButton("Show all tabs")
        show_all_tabs_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        show_all_tabs_btn.clicked.connect(self._show_all_main_tabs)
        tab_btn_row.addWidget(show_all_tabs_btn)
        tab_btn_row.addStretch()
        g_tabs.addLayout(tab_btn_row)

        # --- Flat tariff (Octopus summary est. cost) ---
        g1 = add_group("Flat tariff (Octopus summary estimated net cost)")
        self.sp_import = QDoubleSpinBox()
        self.sp_import.setRange(0, 200)
        self.sp_import.setDecimals(2)
        self.sp_import.setValue(self.p.import_flat_pence)
        self.sp_import.valueChanged.connect(self._on_cost_spin_changed)
        self.sp_export = QDoubleSpinBox()
        self.sp_export.setRange(0, 200)
        self.sp_export.setDecimals(2)
        self.sp_export.setValue(self.p.export_flat_pence)
        self.sp_export.valueChanged.connect(self._on_cost_spin_changed)
        g1_grid = _params_make_field_grid()
        _params_grid_add_pairs(g1_grid, 0, [
            ("Import (p/kWh inc. VAT):", self.sp_import),
            ("Export (p/kWh):", self.sp_export),
        ])
        _params_add_field_grid(g1, g1_grid)

        # --- Analytics simulation defaults ---
        g2 = add_group("Analytics (battery expansion simulator)")
        self.sp_eff = QDoubleSpinBox()
        self.sp_eff.setRange(50, 100)
        self.sp_eff.setDecimals(1)
        self.sp_eff.setValue(self.p.analytics_efficiency_pct)
        self.sp_chg = QDoubleSpinBox()
        self.sp_chg.setRange(0.5, 50)
        self.sp_chg.setDecimals(2)
        self.sp_chg.setValue(self.p.analytics_max_charge_kw)
        self.sp_bat_cost = QDoubleSpinBox()
        self.sp_bat_cost.setRange(0, 50000)
        self.sp_bat_cost.setDecimals(0)
        self.sp_bat_cost.setValue(self.p.analytics_battery_cost_gbp)
        g2_grid = _params_make_field_grid()
        g2_grid.setProperty("_params_anchor_id", "analytics")
        _params_grid_add_pairs(g2_grid, 0, [
            ("Round-trip efficiency %:", self.sp_eff),
            ("Max charge kW:", self.sp_chg),
            ("Extra battery unit cost (£):", self.sp_bat_cost),
        ])
        _params_add_field_grid(g2, g2_grid)

        # --- Agile product/tariff (historical price fetch in Analytics + Forecasts tab defaults) ---
        g3 = add_group("Agile product / tariff (Analytics historical prices + Forecasts)")
        self.ed_agile_prod = QLineEdit(self.p.agile_product)
        self.ed_agile_tariff = QLineEdit(self.p.agile_tariff)
        self.ed_agile_export_tariff = QLineEdit(self.p.agile_export_tariff)
        self.ed_agile_export_tariff.setToolTip(
            "Octopus tariff code for half-hourly export (outgoing) rates — Forecasts chart"
        )
        for ed in (self.ed_agile_prod, self.ed_agile_tariff):
            ed.setProperty("_params_setup_line_field", True)
        self.ed_agile_export_tariff.setProperty("_params_setup_line_field", True)
        self.ed_agile_export_tariff.setProperty("_params_setup_line_wide", True)
        g3_grid = _params_make_field_grid()
        g3_grid.setProperty("_params_anchor_parent", "analytics")
        _params_grid_add_pairs(g3_grid, 0, [
            ("Product code:", self.ed_agile_prod),
            ("Tariff code:", self.ed_agile_tariff),
        ])
        _params_grid_add_pairs(g3_grid, 1, [
            ("Export Tariff:", self.ed_agile_export_tariff),
        ])
        _params_add_field_grid(g3, g3_grid)

        # --- Battery analysis tab defaults ---
        g4 = add_group("Battery Analysis tab defaults")
        self.sp_cap = QDoubleSpinBox()
        self.sp_cap.setRange(1, 200)
        self.sp_cap.setDecimals(1)
        self.sp_cap.setValue(self.p.battery_capacity_kwh)
        self.sp_soc_thr = QSpinBox()
        self.sp_soc_thr.setRange(0, 50)
        self.sp_soc_thr.setValue(int(self.p.battery_low_soc_threshold_pct))
        save_bat_btn = QPushButton("Save")
        save_bat_btn.setToolTip(
            "Save capacity and low-SOC threshold to disk and apply to Battery Analysis and Analytics"
        )
        save_bat_btn.clicked.connect(self._save_battery_defaults)
        g4_grid = _params_make_field_grid()
        g4_grid.setProperty("_params_anchor_id", "battery")
        _params_grid_add_pairs(g4_grid, 0, [
            ("Capacity (kWh):", self.sp_cap),
            ("Low SOC threshold %:", self.sp_soc_thr),
        ])
        bat_btn_row = QHBoxLayout()
        bat_btn_row.setContentsMargins(0, 0, 0, 0)
        bat_btn_row.addSpacing(_SETUP_INFO_SPIN_BTN_GAP)
        bat_btn_row.addWidget(save_bat_btn)
        bat_btn_row.addStretch()
        _save_btn_col = _params_field_col(1) + 1
        g4_grid.addLayout(
            bat_btn_row, 0, _save_btn_col, 1, _PARAMS_GRID_SPAN + 1 - _save_btn_col,
        )
        _params_add_field_grid(g4, g4_grid)

        # --- Live alarms (database, devices, battery) ---
        g_alarm = add_group("Live alarms (database, devices, battery)")
        s_al = self._settings()
        self.chk_alarms = QCheckBox("Enable live alarms")
        self.chk_alarms.setChecked(s_al.value("alarms/enabled", True, type=bool))
        self.chk_alarms.setToolTip(
            "Watch the logging database (connected + new Growatt/Tasmota rows), "
            "Grott feed, Tasmota plugs, inverter offline, live SOC, PV, and charge. "
            "Grott lost fires after ~20s; SOC/PV rules use the hold period below."
        )
        self.chk_alarm_desktop = QCheckBox("Desktop notifications")
        self.chk_alarm_desktop.setChecked(s_al.value("alarms/desktop", True, type=bool))
        self.chk_alarm_desktop.setToolTip(
            "System-tray notifications while an alarm is active: first notify "
            "immediately, then 4× every 5 min, 4× every 10 min, 4× every 30 min, "
            "then hourly. Backoff resets when the alarm clears."
        )
        self.sp_alarm_hold = QDoubleSpinBox()
        self.sp_alarm_hold.setRange(1, 180)
        self.sp_alarm_hold.setDecimals(0)
        self.sp_alarm_hold.setSuffix(" min")
        self.sp_alarm_hold.setValue(float(s_al.value("alarms/hold_minutes", 10)))
        self.sp_alarm_hold.setToolTip(
            "How long SOC/PV conditions must persist before they fire. "
            "Grott feed-lost is separate: ~20s if MQTT drops, or the Grott "
            "fresh window if payloads stop."
        )
        self.sp_alarm_pv_min = QDoubleSpinBox()
        self.sp_alarm_pv_min.setRange(0.2, 20)
        self.sp_alarm_pv_min.setDecimals(1)
        self.sp_alarm_pv_min.setSuffix(" kW")
        self.sp_alarm_pv_min.setValue(float(s_al.value("alarms/pv_min_kw", 1.0)))
        self.sp_alarm_pv_min.setToolTip(
            "Minimum PV for the “low SOC with unused sun” alarm."
        )
        save_alarm_btn = QPushButton("Save")
        save_alarm_btn.setToolTip("Save alarm settings and apply immediately")
        save_alarm_btn.clicked.connect(self._save_alarm_settings)
        alarm_chk_row = QHBoxLayout()
        alarm_chk_row.setContentsMargins(0, 0, 0, 0)
        alarm_chk_row.addWidget(self.chk_alarms)
        alarm_chk_row.addWidget(self.chk_alarm_desktop)
        alarm_chk_row.addStretch(1)
        g_alarm.addLayout(alarm_chk_row)
        alarm_grid = _params_make_field_grid()
        alarm_grid.setProperty("_params_anchor_parent", "battery")
        _params_grid_add_pairs(alarm_grid, 0, [
            ("Hold time:", self.sp_alarm_hold),
            ("Sun-waste PV min:", self.sp_alarm_pv_min),
        ])
        alarm_btn_row = QHBoxLayout()
        alarm_btn_row.setContentsMargins(0, 0, 0, 0)
        alarm_btn_row.addSpacing(_SETUP_INFO_SPIN_BTN_GAP)
        alarm_btn_row.addWidget(save_alarm_btn)
        alarm_btn_row.addStretch()
        alarm_grid.addLayout(
            alarm_btn_row, 0, _save_btn_col, 1, _PARAMS_GRID_SPAN + 1 - _save_btn_col,
        )
        _params_add_field_grid(g_alarm, alarm_grid)
        alarm_help = QLabel(
            "Alarms: (1) SOC below the low-SOC threshold for the hold time, "
            "(2) same, while PV ≥ min and charge ≈ 0 (sun not refilling the pack). "
            "Active alarms appear under the live banner — click for detail."
        )
        alarm_help.setWordWrap(True)
        alarm_help.setStyleSheet("color: #6c7086; font-size: 11px;")
        g_alarm.addWidget(alarm_help)

        # --- Load profile (base load + scheduled high-draw events) ---
        g_load = add_group("Load profile (base load + scheduled high-draw events)")
        self.sp_base_load = QDoubleSpinBox()
        self.sp_base_load.setRange(0, 20)
        self.sp_base_load.setDecimals(2)
        self.sp_base_load.setValue(self.p.base_load_kw)
        self.sp_base_load.setToolTip(
            "Constant background consumption (house + always-on devices). "
            "Used as the floor for every hour in the Smart Advisor simulation."
        )
        load_grid = _params_make_field_grid()
        _params_grid_add_pairs(load_grid, 0, [
            ("Base load (kW):", self.sp_base_load),
        ])
        sched_hdr = _params_field_label("Scheduled loads:", pair=True)
        load_grid.addWidget(
            sched_hdr,
            0,
            _params_label_col(1),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        _params_add_field_grid(g_load, load_grid)

        self.sched_table = QTreeWidget()
        self.sched_table.setHeaderLabels(['Hour', 'Power (kW)', 'Duration (min)', ''])
        self.sched_table.setColumnCount(4)
        self.sched_table.setColumnWidth(0, 60)
        self.sched_table.setColumnWidth(1, 90)
        self.sched_table.setColumnWidth(2, 100)
        self.sched_table.setColumnWidth(3, 50)
        self.sched_table.setRootIsDecorated(False)
        self.sched_table.setMaximumHeight(120)
        g_load.addWidget(self.sched_table)
        qtree_set_column_width_key(self.sched_table, "setup_heating_schedule")
        qtree_prepare_interactive_columns(self.sched_table)
        qtree_restore_column_widths(self.sched_table, "setup_heating_schedule", resize_if_no_saved=True)
        qtree_attach_column_width_persistence(self.sched_table)

        self.sp_sched_hour = QSpinBox()
        self.sp_sched_hour.setRange(0, 23)
        self.sp_sched_hour.setValue(4)
        self.sp_sched_kw = QDoubleSpinBox()
        self.sp_sched_kw.setRange(0.1, 50)
        self.sp_sched_kw.setDecimals(1)
        self.sp_sched_kw.setValue(3.0)
        self.sp_sched_dur = QSpinBox()
        self.sp_sched_dur.setRange(1, 120)
        self.sp_sched_dur.setValue(60)
        add_sched_btn = QPushButton("Add")
        add_sched_btn.clicked.connect(self._add_scheduled_load)
        remove_sched_btn = QPushButton("Remove Selected")
        remove_sched_btn.clicked.connect(self._remove_scheduled_load)
        save_load_btn = QPushButton("Save")
        save_load_btn.setToolTip("Save base load and scheduled loads to disk")
        save_load_btn.clicked.connect(self._save_load_profile)
        sched_grid = _params_make_field_grid()
        _params_grid_add_pairs(sched_grid, 0, [
            ("Add:  Hour (0-23):", self.sp_sched_hour),
            ("kW:", self.sp_sched_kw),
            ("Duration (min):", self.sp_sched_dur),
        ])
        sched_btn_row = QHBoxLayout()
        sched_btn_row.setContentsMargins(0, 0, 0, 0)
        sched_btn_row.setSpacing(8)
        sched_btn_row.addSpacing(_SETUP_INFO_SPIN_BTN_GAP)
        sched_btn_row.addWidget(add_sched_btn)
        sched_btn_row.addWidget(remove_sched_btn)
        sched_btn_row.addWidget(save_load_btn)
        sched_btn_row.addStretch()
        _sched_btn_col = _params_field_col(2) + 1
        sched_grid.addLayout(sched_btn_row, 0, _sched_btn_col, 1, _PARAMS_GRID_SPAN + 1 - _sched_btn_col)
        _params_add_field_grid(g_load, sched_grid)

        # --- Solar installation (location + PV system) ---
        g_solar = add_group("Solar installation (location, PV size, orientation)")
        self.ed_lat = QLineEdit(self._fmt_solar_coord(self.p.solar_lat))
        self.ed_lat.setFixedWidth(100)
        self.ed_lon = QLineEdit(self._fmt_solar_coord(self.p.solar_lon))
        self.ed_lon.setFixedWidth(100)
        from PySide6.QtGui import QDoubleValidator
        for edit, lo, hi, tip in (
            (self.ed_lat, -90.0, 90.0, "Decimal degrees latitude, 5 dp (~1.1 m). WGS84."),
            (self.ed_lon, -180.0, 180.0, "Decimal degrees longitude, 5 dp (~1.1 m). WGS84."),
        ):
            v = QDoubleValidator(lo, hi, 5, edit)
            v.setNotation(QDoubleValidator.Notation.StandardNotation)
            edit.setValidator(v)
            edit.setToolTip(tip)
            edit.editingFinished.connect(lambda e=edit: self._normalize_solar_coord_edit(e))
        self.ed_kwp = QLineEdit(self.p.solar_kwp)
        self.ed_kwp.setFixedWidth(60)
        self.ed_tilt = QLineEdit(self.p.solar_tilt)
        self.ed_tilt.setFixedWidth(60)
        self.ed_azimuth = QLineEdit(self.p.solar_azimuth)
        self.ed_azimuth.setFixedWidth(60)
        save_solar_btn = QPushButton("Save")
        save_solar_btn.setToolTip(
            "Save location and PV geometry to disk and sync the Forecasts tab solar fields"
        )
        save_solar_btn.clicked.connect(self._save_solar_installation)
        solar_grid = _params_make_field_grid()
        _params_grid_add_pairs(solar_grid, 0, [
            ("Latitude:", self.ed_lat),
            ("Longitude:", self.ed_lon),
            ("Total PV installed (kWp):", self.ed_kwp),
        ])
        _params_grid_add_pairs(solar_grid, 1, [
            ("Tilt / angle (°):", self.ed_tilt),
            ("Azimuth (°, 0=south):", self.ed_azimuth),
        ])
        solar_btn_row = QHBoxLayout()
        solar_btn_row.setContentsMargins(0, 0, 0, 0)
        solar_btn_row.addSpacing(_SETUP_INFO_SPIN_BTN_GAP)
        solar_btn_row.addWidget(save_solar_btn)
        solar_btn_row.addStretch()
        _solar_btn_col = _params_field_col(1) + 1
        solar_grid.addLayout(
            solar_btn_row, 1, _solar_btn_col, 1, _PARAMS_GRID_SPAN + 1 - _solar_btn_col
        )
        _params_add_field_grid(g_solar, solar_grid)

        # --- Growatt inverter (cloud credentials + local network + telemetry source) ---
        g_gw = add_group("Growatt inverter")
        self._growatt_group_box = g_gw.parentWidget()
        _cell_align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        _ip_field_w = (
            _SETUP_INFO_SPIN_W + 8 + _SETUP_INFO_PAIR_LABEL_WIDTH + 8 + _SETUP_INFO_SPIN_W
        )

        emqx_hint = QLabel(
            "Routing profile: <b>Tasmota</b>, <b>WiFi Direct</b>, and <b>LAN Direct</b> "
            "now route through <b>EMQX</b> at "
            f"<code>{_EMQX_ROUTE_DEFAULT_HOST}</code>."
        )
        emqx_hint.setWordWrap(True)
        emqx_hint.setTextFormat(Qt.RichText)
        emqx_hint.setStyleSheet("color: #6c7086; font-size: 11px; font-weight: normal;")
        emqx_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        gw_info_row = QHBoxLayout()
        gw_info_row.setContentsMargins(0, 0, 0, 0)
        gw_info_row.setSpacing(12)
        gw_info_row.addWidget(emqx_hint, 1)
        self.lbl_growatt_local_status = QLabel()
        self.lbl_growatt_local_status.setTextFormat(Qt.RichText)
        self.lbl_growatt_local_status.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.lbl_growatt_local_status.setMinimumWidth(145)
        self.lbl_growatt_local_status.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
        )
        gw_info_row.addWidget(self.lbl_growatt_local_status)
        g_gw.addLayout(gw_info_row)
        self._set_growatt_local_status(False)

        emqx_row = QHBoxLayout()
        emqx_row.setContentsMargins(0, 0, 0, 0)
        emqx_row.setSpacing(8)
        emqx_row.addWidget(QLabel("EMQX host:"))
        self.ed_emqx_host = QLineEdit()
        self.ed_emqx_host.setMinimumWidth(_ip_field_w)
        self.ed_emqx_host.setMaximumWidth(220)
        self.ed_emqx_host.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.ed_emqx_host.setPlaceholderText(_EMQX_ROUTE_DEFAULT_HOST)
        self.ed_emqx_host.setToolTip(
            "Shared MQTT broker host for local routes. "
            "Apply writes host/port/user/password into Growatt Grott MQTT and Tasmota MQTT settings."
        )
        emqx_row.addWidget(self.ed_emqx_host)
        emqx_row.addWidget(QLabel("Port:"))
        self.sp_emqx_port = QSpinBox()
        self.sp_emqx_port.setRange(1, 65535)
        self.sp_emqx_port.setValue(_EMQX_ROUTE_DEFAULT_PORT)
        self.sp_emqx_port.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.sp_emqx_port.setToolTip("EMQX MQTT port (usually 1883).")
        emqx_row.addWidget(self.sp_emqx_port)
        emqx_row.addWidget(QLabel("Username:"))
        self.ed_emqx_user = QLineEdit()
        self.ed_emqx_user.setMinimumWidth(100)
        self.ed_emqx_user.setMaximumWidth(140)
        self.ed_emqx_user.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.ed_emqx_user.setPlaceholderText("MQTT username")
        self.ed_emqx_user.setToolTip(
            "EMQX MQTT username. Applied to Grott MQTT and Tasmota MQTT when you click Apply."
        )
        emqx_row.addWidget(self.ed_emqx_user)
        emqx_row.addWidget(QLabel("Password:"))
        self.ed_emqx_pass = QLineEdit()
        self.ed_emqx_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_emqx_pass.setMinimumWidth(100)
        self.ed_emqx_pass.setMaximumWidth(140)
        self.ed_emqx_pass.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.ed_emqx_pass.setPlaceholderText("MQTT password")
        self.ed_emqx_pass.setToolTip(
            "EMQX MQTT password. Applied to Grott MQTT and Tasmota MQTT when you click Apply."
        )
        emqx_row.addWidget(self.ed_emqx_pass)
        self.btn_apply_emqx_route = QPushButton("Apply EMQX route")
        self.btn_apply_emqx_route.setStyleSheet(_SUBTLE_BTN_QSS)
        self.btn_apply_emqx_route.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_apply_emqx_route.setFixedWidth(150)
        self.btn_apply_emqx_route.setToolTip(
            "Copy EMQX host/port/username/password to Growatt Grott MQTT and Tasmota MQTT fields, "
            "persist to QSettings, and refresh connectivity status."
        )
        self.btn_apply_emqx_route.clicked.connect(self._apply_emqx_route)
        emqx_row.addWidget(self.btn_apply_emqx_route)
        self.btn_save_emqx = QPushButton("Save")
        self.btn_save_emqx.setStyleSheet(_SUBTLE_BTN_QSS)
        self.btn_save_emqx.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_save_emqx.setFixedWidth(72)
        self.btn_save_emqx.setToolTip(
            "Save EMQX host/port/username/password and apply the same broker "
            "to Grott MQTT and Tasmota MQTT (same effect as Apply EMQX route)."
        )
        self.btn_save_emqx.clicked.connect(self._save_emqx_credentials)
        emqx_row.addWidget(self.btn_save_emqx)
        self.btn_test_emqx = QPushButton("Test")
        self.btn_test_emqx.setStyleSheet(_SUBTLE_BTN_QSS)
        self.btn_test_emqx.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_test_emqx.setFixedWidth(72)
        self.btn_test_emqx.setToolTip(
            "Connect to the EMQX MQTT broker with the host/port/username/password shown above "
            "(auth check only; does not wait for Grott or Tasmota payloads)."
        )
        self.btn_test_emqx.clicked.connect(self._test_emqx_connection)
        emqx_row.addWidget(self.btn_test_emqx)
        emqx_row.addStretch(1)
        g_gw.addLayout(emqx_row)

        def _growatt_subsection(title: str) -> QLabel:
            lbl = QLabel(title)
            lbl.setStyleSheet(
                "font-weight: bold; color: #cdd6f4; margin-top: 4px; padding-bottom: 2px;"
            )
            return lbl

        g_gw.addWidget(_growatt_subsection("A) LAN connection"))
        self.ed_growatt_lan_ip = QLineEdit(self.p.growatt_lan_ip)
        self.ed_growatt_lan_ip.setMinimumWidth(_ip_field_w)
        self.ed_growatt_lan_ip.setPlaceholderText("e.g. 192.168.1.50")
        self.ed_growatt_lan_ip.setToolTip(
            "Ethernet / LAN address of the inverter or ShineLAN module "
            "(Modbus TCP and built‑in web UI when wired)."
        )
        self.ed_growatt_lan_user = QLineEdit(self.p.growatt_lan_user)
        self.ed_growatt_lan_user.setMinimumWidth(_SETUP_INFO_SPIN_W)
        self.ed_growatt_lan_user.setPlaceholderText("Web UI username")
        self.ed_growatt_lan_pass = QLineEdit(self.p.growatt_lan_password)
        self.ed_growatt_lan_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_growatt_lan_pass.setMinimumWidth(_SETUP_INFO_SPIN_W)
        self.ed_growatt_lan_pass.setPlaceholderText("Web UI password")
        lan_grid = _params_make_field_grid()
        lan_grid.setProperty("_params_growatt_grid", True)
        lan_grid.addWidget(
            _params_field_label("IP address / hostname:"), 0, _params_label_col(0), _cell_align
        )
        lan_grid.addWidget(
            self.ed_growatt_lan_ip, 0, _params_field_col(0), 1, _PARAMS_PAIR_STRIDE + 2, _cell_align
        )
        _params_grid_add_pairs(lan_grid, 1, [
            ("Username:", self.ed_growatt_lan_user),
            ("Password:", self.ed_growatt_lan_pass),
        ])
        _params_add_field_grid(g_gw, lan_grid)

        g_gw.addWidget(_growatt_subsection("B) WiFi connection"))
        self.ed_growatt_wifi_ip = QLineEdit(self.p.growatt_wifi_ip)
        self.ed_growatt_wifi_ip.setMinimumWidth(_ip_field_w)
        self.ed_growatt_wifi_ip.setPlaceholderText("e.g. 192.168.1.51")
        self.ed_growatt_wifi_ip.setToolTip(
            "Wi‑Fi address of the ShineWiFi‑X / dongle (built‑in web UI over wireless)."
        )
        self.ed_growatt_wifi_user = QLineEdit(self.p.growatt_wifi_user)
        self.ed_growatt_wifi_user.setMinimumWidth(_SETUP_INFO_SPIN_W)
        self.ed_growatt_wifi_user.setPlaceholderText("Web UI username")
        self.ed_growatt_wifi_pass = QLineEdit(self.p.growatt_wifi_password)
        self.ed_growatt_wifi_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_growatt_wifi_pass.setMinimumWidth(_SETUP_INFO_SPIN_W)
        self.ed_growatt_wifi_pass.setPlaceholderText("Web UI password")
        wifi_grid = _params_make_field_grid()
        wifi_grid.setProperty("_params_growatt_grid", True)
        wifi_grid.addWidget(
            _params_field_label("IP address / hostname:"), 0, _params_label_col(0), _cell_align
        )
        wifi_grid.addWidget(
            self.ed_growatt_wifi_ip, 0, _params_field_col(0), 1, _PARAMS_PAIR_STRIDE + 2, _cell_align
        )
        _params_grid_add_pairs(wifi_grid, 1, [
            ("Username:", self.ed_growatt_wifi_user),
            ("Password:", self.ed_growatt_wifi_pass),
        ])
        _params_add_field_grid(g_gw, wifi_grid)
        _params_add_db_section_rule(g_gw)

        self.sp_growatt_port = QSpinBox()
        self.sp_growatt_port.setRange(1, 65535)
        self.sp_growatt_port.setValue(int(self.p.growatt_local_port))
        self.sp_growatt_port.setToolTip("Port for the inverter web interface (often 80)")
        open_gw_btn = QPushButton("Open web UI")
        open_gw_btn.setToolTip(
            "Open http(s)://host:port/ in the default browser "
            "(LAN connection first, then Wi‑Fi if LAN is empty)"
        )
        open_gw_btn.clicked.connect(self._open_growatt_web_ui)
        save_gw_btn = QPushButton("Save")
        save_gw_btn.setToolTip(
            "Save LAN/Wi‑Fi addresses, web UI logins, and HTTP port to disk "
            "(Modbus has its own Save below)"
        )
        save_gw_btn.clicked.connect(self._save_growatt_lan)
        self._btn_test_growatt_http = QPushButton("Test web UI")
        self._btn_test_growatt_http.setToolTip(
            "Open a TCP connection to each configured IP/hostname and HTTP port "
            "(web UI only). Uses the values currently in this form; does not test Modbus."
        )
        self._btn_test_growatt_http.clicked.connect(self._test_growatt_http_connection)
        gw_grid = _params_make_field_grid()
        gw_grid.setProperty("_params_growatt_grid", True)
        _params_grid_add_pairs(gw_grid, 0, [("HTTP port:", self.sp_growatt_port)])
        gw_btn_row = QHBoxLayout()
        gw_btn_row.setContentsMargins(0, 0, 0, 0)
        gw_btn_row.setSpacing(8)
        gw_btn_row.addSpacing(_SETUP_INFO_SPIN_BTN_GAP)
        gw_btn_row.addWidget(open_gw_btn)
        gw_btn_row.addWidget(save_gw_btn)
        gw_btn_row.addWidget(self._btn_test_growatt_http)
        gw_btn_row.addStretch()
        _gw_btn_col = _params_field_col(0) + 1
        gw_grid.addLayout(gw_btn_row, 0, _gw_btn_col, 1, _PARAMS_GRID_SPAN + 1 - _gw_btn_col)
        _params_add_field_grid(g_gw, gw_grid)
        _params_add_db_section_rule(g_gw)

        self.cb_growatt_modbus = QComboBox()
        self.cb_growatt_modbus.addItem("Disabled", "off")
        self.cb_growatt_modbus.addItem("Modbus TCP (LAN / RS485 Ethernet)", "tcp")
        self.cb_growatt_modbus.addItem(
            "Modbus RTU over TCP (transparent gateway)", "tcp_rtu")
        self.cb_growatt_modbus.addItem("Modbus RTU (USB–RS485)", "serial")
        self.cb_growatt_modbus.setToolTip(
            "Optional health-check on Connectivity Status. "
            "Modbus TCP: native MBAP on the LAN IP (ShineWiFi or a gateway in "
            "Modbus TCP<=>RTU mode), usually port 502. "
            "RTU over TCP: USR/Waveshare Transparent Mode, typically port 8899. "
            "USB RTU is only for a serial adapter on this PC."
        )
        self.cb_growatt_modbus.currentIndexChanged.connect(
            self._on_growatt_modbus_mode_changed)
        self.sp_growatt_modbus_tcp = QSpinBox()
        self.sp_growatt_modbus_tcp.setRange(1, 65535)
        self.sp_growatt_modbus_tcp.setValue(int(self.p.growatt_modbus_tcp_port))
        self.sp_growatt_modbus_tcp.setToolTip(
            "Often 8899 on USR boxes (same as Home Assistant type: tcp). "
            "502 only if the box is in Modbus TCP<=>RTU mode and listens there."
        )
        self.ed_growatt_modbus_serial = QLineEdit(self.p.growatt_modbus_serial_path)
        self.ed_growatt_modbus_serial.setMinimumWidth(_SETUP_INFO_SPIN_W)
        self.ed_growatt_modbus_serial.setPlaceholderText("/dev/ttyUSB0")
        self.sp_growatt_modbus_baud = QSpinBox()
        self.sp_growatt_modbus_baud.setRange(1200, 921600)
        self.sp_growatt_modbus_baud.setSingleStep(300)
        self.sp_growatt_modbus_baud.setValue(int(self.p.growatt_modbus_baud))
        self.sp_growatt_modbus_unit = QSpinBox()
        self.sp_growatt_modbus_unit.setRange(1, 247)
        self.sp_growatt_modbus_unit.setValue(int(self.p.growatt_modbus_unit))
        mbus_grid = _params_make_field_grid()
        mbus_grid.setProperty("_params_growatt_grid", True)
        mbus_grid.addWidget(_params_field_label("Local Modbus check:"), 0, _params_label_col(0), _cell_align)
        mbus_grid.addWidget(self.cb_growatt_modbus, 0, _params_field_col(0), 1, _PARAMS_PAIR_STRIDE + 2, _cell_align)
        self.lbl_growatt_modbus_status = QLabel()
        self.lbl_growatt_modbus_status.setTextFormat(Qt.RichText)
        self.lbl_growatt_modbus_status.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.lbl_growatt_modbus_status.setMinimumWidth(130)
        self.lbl_growatt_modbus_status.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
        )
        # Place status on the mode row, right side of the grid.
        mbus_grid.addWidget(
            self.lbl_growatt_modbus_status,
            0,
            _params_field_col(2),
            1,
            2,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        self._set_growatt_modbus_status(False, "Not tested yet.")
        _params_grid_add_pairs(mbus_grid, 1, [
            ("TCP port:", self.sp_growatt_modbus_tcp),
            ("Serial device:", self.ed_growatt_modbus_serial),
        ])
        _params_grid_add_pairs(mbus_grid, 2, [
            ("Baud:", self.sp_growatt_modbus_baud),
            ("Unit ID:", self.sp_growatt_modbus_unit),
        ])
        self.chk_growatt_modbus_writes = QCheckBox(
            "Allow inverter writes via Modbus (opt-in)"
        )
        self.chk_growatt_modbus_writes.setChecked(
            bool(getattr(self.p, "growatt_modbus_writes_enabled", False))
        )
        self.chk_growatt_modbus_writes.setToolTip(
            "Safety opt-in: when Modbus is configured, allow this app to write "
            "inverter holding registers on the LAN (Command Sim and any future "
            "local schedule path). Default is off — schedule push still prefers "
            "Growatt cloud REST until a local write path is used. "
            "Wrong writes can drain the battery or miss cheap Agile windows."
        )
        mbus_grid.addWidget(
            self.chk_growatt_modbus_writes,
            3, _params_label_col(0), 1, _PARAMS_GRID_SPAN,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        self._btn_test_growatt_modbus = QPushButton("Test Modbus")
        self._btn_test_growatt_modbus.setToolTip(
            "Run the same Modbus read probe as Connectivity Status — "
            "TCP / RTU-over-TCP uses the LAN IP (or Wi‑Fi IP if LAN is empty); "
            "USB RTU uses the serial device. Uses the values currently in this form."
        )
        self._btn_test_growatt_modbus.clicked.connect(self._test_growatt_modbus_connection)
        save_mbus_btn = QPushButton("Save")
        save_mbus_btn.setToolTip(
            "Save Local Modbus mode, TCP port, serial device, baud, unit ID, "
            "and the inverter-write opt-in to disk"
        )
        save_mbus_btn.clicked.connect(self._save_growatt_modbus)
        mbus_btn_row = QHBoxLayout()
        mbus_btn_row.setContentsMargins(0, 0, 0, 0)
        mbus_btn_row.setSpacing(8)
        mbus_btn_row.addSpacing(_SETUP_INFO_SPIN_BTN_GAP)
        mbus_btn_row.addWidget(save_mbus_btn)
        mbus_btn_row.addWidget(self._btn_test_growatt_modbus)
        mbus_btn_row.addStretch()
        # Same column as HTTP-port Open/Save/Test so Save / Test Modbus line up.
        _mbus_btn_col = _params_field_col(0) + 1
        mbus_grid.addLayout(
            mbus_btn_row, 4, _mbus_btn_col, 1,
            _PARAMS_GRID_SPAN + 1 - _mbus_btn_col,
        )
        _params_add_field_grid(g_gw, mbus_grid)
        _mbus_hint = QLabel(
            "<b>RS485–Ethernet (USR / Waveshare):</b> match Home Assistant if it "
            "already works — typically <b>Modbus TCP</b>, converter LAN IP, port "
            "<b>8899</b>, unit <b>1</b> (HA <code>type: tcp</code> / <code>slave: 1</code>). "
            "Port <b>502</b> only if the box listens there in "
            "<b>Modbus TCP&lt;=&gt;Modbus RTU</b> mode. "
            "<b>RTU over TCP</b> is for raw Transparent serial framing only.<br>"
            "UART on the box: <b>9600 8N1</b>, 485 Enable, RFC2217 off. "
            "ShineWiFi dongles: port 80 does <i>not</i> mean TCP 502 exists."
        )
        _mbus_hint.setWordWrap(True)
        _mbus_hint.setTextFormat(Qt.RichText)
        _mbus_hint.setStyleSheet(
            "color: #6c7086; font-size: 10px; margin-top: 2px; padding: 4px 2px 6px 2px;"
        )
        g_gw.addWidget(_mbus_hint)

        _params_add_db_section_rule(g_gw)
        g_gw.addWidget(_growatt_subsection("C) Growatt telemetry source"))
        src_hint = QLabel(
            "Choose the live Growatt data path. <b>GROTT MQTT</b> is local only; "
            "<b>Hybrid</b> prefers Grott then falls back to the cloud API when "
            "Grott is stale. The checkbox below patches individual missing Grott "
            "registers from the cloud without switching the whole source."
        )
        src_hint.setWordWrap(True)
        src_hint.setTextFormat(Qt.RichText)
        src_hint.setStyleSheet("color: #6c7086; font-size: 10px; margin-bottom: 2px;")
        g_gw.addWidget(src_hint)

        self.rb_growatt_api = QRadioButton("Growatt Cloud API")
        self.rb_growatt_api.setToolTip("Use Growatt's cloud/API login as the live telemetry source.")
        self.chk_grott_mqtt = QRadioButton("GROTT MQTT")
        self.chk_grott_mqtt.setToolTip(
            "Use decoded local Growatt telemetry from GROTT over MQTT. "
            "When selected, this is the primary live source, not a fallback."
        )
        self.rb_growatt_hybrid = QRadioButton("Hybrid (Grott → API fallback)")
        self.rb_growatt_hybrid.setToolTip(
            "Prefer fresh GROTT MQTT telemetry; if Grott is stale or unavailable, "
            "fall back to the Growatt cloud API."
        )
        _src = read_growatt_telemetry_source(self._settings(), self.p)
        self.rb_growatt_api.setChecked(_src == GROWATT_TELEMETRY_API)
        self.chk_grott_mqtt.setChecked(_src == GROWATT_TELEMETRY_GROTT)
        self.rb_growatt_hybrid.setChecked(_src == GROWATT_TELEMETRY_HYBRID)
        self.growatt_source_group = QButtonGroup(self)
        self.growatt_source_group.setExclusive(True)
        self.growatt_source_group.addButton(self.rb_growatt_api)
        self.growatt_source_group.addButton(self.chk_grott_mqtt)
        self.growatt_source_group.addButton(self.rb_growatt_hybrid)
        self.chk_grott_mqtt.toggled.connect(self._update_grott_source_controls)
        self.rb_growatt_hybrid.toggled.connect(self._update_grott_source_controls)
        source_row = QHBoxLayout()
        source_row.setContentsMargins(0, 0, 0, 0)
        source_row.setSpacing(18)
        source_row.addWidget(self.rb_growatt_api)
        source_row.addWidget(self.chk_grott_mqtt)
        source_row.addWidget(self.rb_growatt_hybrid)
        source_row.addStretch(1)
        g_gw.addLayout(source_row)

        self.chk_grott_fill_missing = QCheckBox("Fill missing Grott data with API")
        self.chk_grott_fill_missing.setToolTip(
            "While GROTT or Hybrid is the live source, fetch Growatt cloud data "
            "in the background and patch only registers Grott did not publish. "
            "Patched fields are shown in amber on the Growatt tab."
        )
        self.chk_grott_fill_missing.setChecked(read_grott_fill_missing_api(self._settings(), self.p))
        fill_row = QHBoxLayout()
        fill_row.setContentsMargins(0, 0, 0, 0)
        fill_row.addWidget(self.chk_grott_fill_missing)
        fill_row.addStretch(1)
        g_gw.addLayout(fill_row)

        self.ed_grott_host = QLineEdit(self.p.grott_mqtt_host)
        self.ed_grott_host.setMinimumWidth(_ip_field_w)
        self.ed_grott_host.setPlaceholderText("e.g. 222.20.20.209")
        self.ed_grott_host.setToolTip("MQTT broker host reachable from this dashboard.")
        self.sp_grott_port = QSpinBox()
        self.sp_grott_port.setRange(1, 65535)
        self.sp_grott_port.setValue(int(self.p.grott_mqtt_port))
        self.sp_grott_port.setToolTip("MQTT broker port (usually 1883)")
        self.ed_grott_topic = QLineEdit(self.p.grott_mqtt_topic or "energy/growatt")
        self.ed_grott_topic.setMinimumWidth(_ip_field_w)
        self.ed_grott_topic.setPlaceholderText("energy/growatt")
        self.ed_grott_topic.setToolTip(
            "MQTT topic filter for Grott JSON payloads, usually energy/growatt. "
            "Multiple filters may be separated with commas."
        )
        self.ed_grott_user = QLineEdit(self.p.grott_mqtt_user)
        self.ed_grott_user.setMinimumWidth(_SETUP_INFO_SPIN_W)
        self.ed_grott_user.setPlaceholderText("MQTT user")
        self.ed_grott_pass = QLineEdit(self.p.grott_mqtt_password)
        self.ed_grott_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_grott_pass.setMinimumWidth(_SETUP_INFO_SPIN_W)
        self.ed_grott_pass.setPlaceholderText("MQTT password")
        self.sp_grott_fresh = QSpinBox()
        self.sp_grott_fresh.setRange(15, 99999)
        self.sp_grott_fresh.setValue(int(self.p.grott_mqtt_fresh_s))
        self.sp_grott_fresh.setToolTip(
            "How old a live Grott frame may be before it counts as stale. "
            "Shine often goes quiet ~11 min after reconnect (hourly handshake) "
            "— that is a real gap, not an MQTT drop."
        )

        self._grott_source_widgets = [
            self.ed_grott_host,
            self.sp_grott_port,
            self.ed_grott_topic,
            self.ed_grott_user,
            self.ed_grott_pass,
            self.sp_grott_fresh,
        ]

        grott_grid = _params_make_field_grid()
        grott_grid.setProperty("_params_growatt_grid", True)
        _params_grid_add_pairs(grott_grid, 0, [
            ("MQTT host:", self.ed_grott_host),
            ("Port:", self.sp_grott_port),
        ])
        _params_grid_add_pairs(grott_grid, 1, [
            ("Topic:", self.ed_grott_topic),
            ("Fresh max (s):", self.sp_grott_fresh),
        ])
        _params_grid_add_pairs(grott_grid, 2, [
            ("Username:", self.ed_grott_user),
            ("Password:", self.ed_grott_pass),
        ])
        grott_grid.setRowMinimumHeight(3, _SETUP_INFO_SPIN_H + 6)
        self._btn_test_grott_mqtt = QPushButton("Test Grott MQTT")
        self._btn_test_grott_mqtt.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._btn_test_grott_mqtt.setFixedWidth(130)
        self._btn_test_grott_mqtt.setToolTip(
            "Check MQTT host/auth/subscribe. A Grott payload within a few seconds "
            "is luck — Grott publishes ~every 1 min, not on demand."
        )
        self._btn_test_grott_mqtt.clicked.connect(self._test_grott_mqtt_connection)
        save_grott_btn = QPushButton("Save source")
        save_grott_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        save_grott_btn.setFixedWidth(105)
        save_grott_btn.setToolTip("Save Growatt source selection and GROTT MQTT settings")
        save_grott_btn.clicked.connect(self._save_growatt_lan)
        self._grott_source_widgets.append(self._btn_test_grott_mqtt)
        grott_btn_row = QHBoxLayout()
        grott_btn_row.setContentsMargins(0, 0, 0, 0)
        grott_btn_row.setSpacing(8)
        grott_btn_row.addSpacing(_SETUP_INFO_SPIN_BTN_GAP)
        grott_btn_row.addWidget(save_grott_btn)
        grott_btn_row.addWidget(self._btn_test_grott_mqtt)
        grott_btn_row.addStretch()
        grott_grid.addLayout(
            grott_btn_row, 3, _params_field_col(0), 1, _PARAMS_GRID_SPAN + 1 - _params_field_col(0)
        )
        _params_add_field_grid(g_gw, grott_grid)
        self._update_grott_source_controls()
        self._update_growatt_modbus_controls()

        # --- Growatt cloud login (used when source = Growatt Cloud API) ---
        _params_add_db_section_rule(g_gw)
        g_gw.addWidget(_growatt_subsection("D) Growatt cloud login (server.growatt.com)"))
        cloud_hint = QLabel(
            "Credentials for the Growatt cloud / Open API at "
            "<code>server.growatt.com</code>, used when the telemetry source above "
            "is <b>Growatt Cloud API</b>. An <b>API key</b> is recommended over "
            "username / password to avoid Growatt rate-limit lockouts."
        )
        cloud_hint.setWordWrap(True)
        cloud_hint.setTextFormat(Qt.RichText)
        cloud_hint.setStyleSheet("color: #6c7086; font-size: 10px; margin-bottom: 2px;")
        g_gw.addWidget(cloud_hint)

        _s_cloud = self._settings()
        self.ed_growatt_cloud_user = QLineEdit(
            str(_s_cloud.value("growatt/username", DEFAULT_GROWATT_USER) or "")
        )
        self.ed_growatt_cloud_user.setMinimumWidth(_SETUP_INFO_SPIN_W)
        self.ed_growatt_cloud_user.setPlaceholderText("server.growatt.com username")
        self.ed_growatt_cloud_pass = QLineEdit(
            str(_s_cloud.value("growatt/password", DEFAULT_GROWATT_PASS) or "")
        )
        self.ed_growatt_cloud_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_growatt_cloud_pass.setMinimumWidth(_SETUP_INFO_SPIN_W)
        self.ed_growatt_cloud_pass.setPlaceholderText("server.growatt.com password")
        self.ed_growatt_cloud_token = QLineEdit(str(_s_cloud.value("growatt/api_token", "") or ""))
        self.ed_growatt_cloud_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_growatt_cloud_token.setMinimumWidth(_SETUP_INFO_SPIN_W)
        self.ed_growatt_cloud_token.setPlaceholderText("API key (recommended)")
        self.ed_growatt_cloud_token.setToolTip(
            "Growatt Open API token. When set, Connect uses token auth instead of "
            "username / password and avoids Growatt 507 rate-limit lockouts."
        )
        self.ed_growatt_cloud_serial = QLineEdit(str(_s_cloud.value("growatt/serial", "") or ""))
        self.ed_growatt_cloud_serial.setMinimumWidth(_SETUP_INFO_SPIN_W)
        self.ed_growatt_cloud_serial.setPlaceholderText("Optional inverter SN")
        self.ed_growatt_cloud_serial.setToolTip(
            "Sticker serial on the inverter or WiFi module. Used when Growatt's "
            "device_list API returns nothing, or to pin a specific inverter."
        )
        cloud_grid = _params_make_field_grid()
        cloud_grid.setProperty("_params_growatt_grid", True)
        _params_grid_add_pairs(cloud_grid, 0, [
            ("Username:", self.ed_growatt_cloud_user),
            ("Password:", self.ed_growatt_cloud_pass),
        ])
        _params_grid_add_pairs(cloud_grid, 1, [
            ("API key:", self.ed_growatt_cloud_token),
            ("Serial:", self.ed_growatt_cloud_serial),
        ])
        save_cloud_btn = QPushButton("Save credentials")
        save_cloud_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        save_cloud_btn.setFixedWidth(130)
        save_cloud_btn.setToolTip(
            "Save Growatt cloud username, password, API key, and serial."
        )
        save_cloud_btn.clicked.connect(self._save_growatt_cloud_credentials)
        test_cloud_btn = QPushButton("Test connection")
        test_cloud_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        test_cloud_btn.setFixedWidth(130)
        test_cloud_btn.setToolTip(
            "Log in to server.growatt.com with these fields and probe live inverter data."
        )
        test_cloud_btn.clicked.connect(self._test_growatt_cloud_connection)
        cloud_btn_row = QHBoxLayout()
        cloud_btn_row.setContentsMargins(0, 0, 0, 0)
        cloud_btn_row.setSpacing(8)
        cloud_btn_row.addSpacing(_SETUP_INFO_SPIN_BTN_GAP)
        cloud_btn_row.addWidget(save_cloud_btn)
        cloud_btn_row.addWidget(test_cloud_btn)
        cloud_btn_row.addStretch()
        cloud_grid.addLayout(
            cloud_btn_row, 2, _params_field_col(0), 1,
            _PARAMS_GRID_SPAN + 1 - _params_field_col(0),
        )
        _params_add_field_grid(g_gw, cloud_grid)

        # --- PVOutput.org live upload ---
        g_pvo = add_group("PVOutput.org (live status upload)")
        g_pvo.addWidget(QLabel(
            "Pushes today’s PV generation (and optional house load) to "
            "<a href='https://pvoutput.org/'>pvoutput.org</a> via Add Status. "
            "Create an API key under PVOutput → Settings → API Access."
        ))
        g_pvo.itemAt(g_pvo.count() - 1).widget().setOpenExternalLinks(True)
        g_pvo.itemAt(g_pvo.count() - 1).widget().setWordWrap(True)
        g_pvo.itemAt(g_pvo.count() - 1).widget().setStyleSheet(
            "color: #a6adc8; font-size: 11px;"
        )
        from energy_dashboard.fetch.pvoutput import (
            DEFAULT_INTERVAL_S,
            MAX_INTERVAL_S,
            MIN_INTERVAL_S,
            load_pvoutput_config,
        )
        _pvo = load_pvoutput_config()
        self.chk_pvoutput = QCheckBox("Enable PVOutput uploads")
        self.chk_pvoutput.setChecked(bool(_pvo.enabled))
        pvo_en = QHBoxLayout()
        pvo_en.addWidget(self.chk_pvoutput)
        pvo_en.addStretch()
        g_pvo.addLayout(pvo_en)
        self.ed_pvoutput_key = QLineEdit(_pvo.api_key)
        self.ed_pvoutput_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_pvoutput_key.setMinimumWidth(_SETUP_INFO_SPIN_W)
        self.ed_pvoutput_key.setPlaceholderText("X-Pvoutput-Apikey")
        self.ed_pvoutput_sid = QLineEdit(_pvo.system_id)
        self.ed_pvoutput_sid.setMinimumWidth(_SETUP_INFO_SPIN_W)
        self.ed_pvoutput_sid.setPlaceholderText("System Id (number)")
        self.sp_pvoutput_interval = QSpinBox()
        self.sp_pvoutput_interval.setRange(MIN_INTERVAL_S, MAX_INTERVAL_S)
        self.sp_pvoutput_interval.setSingleStep(60)
        self.sp_pvoutput_interval.setValue(int(_pvo.interval_s or DEFAULT_INTERVAL_S))
        self.sp_pvoutput_interval.setSuffix(" s")
        self.sp_pvoutput_interval.setToolTip(
            "Minimum seconds between uploads (PVOutput rate limit is 60/hour)."
        )
        pvo_grid = _params_make_field_grid()
        _params_grid_add_pairs(pvo_grid, 0, [
            ("API key:", self.ed_pvoutput_key),
            ("System Id:", self.ed_pvoutput_sid),
        ])
        _params_grid_add_pairs(pvo_grid, 1, [
            ("Interval:", self.sp_pvoutput_interval),
        ])
        save_pvo_btn = QPushButton("Save")
        save_pvo_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        save_pvo_btn.setFixedWidth(130)
        save_pvo_btn.setToolTip("Save PVOutput API key, System Id, and interval.")
        save_pvo_btn.clicked.connect(self._save_pvoutput_settings)
        test_pvo_btn = QPushButton("Test upload")
        test_pvo_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        test_pvo_btn.setFixedWidth(130)
        test_pvo_btn.setToolTip("Force one Add Status upload from the latest Growatt snapshot.")
        test_pvo_btn.clicked.connect(self._test_pvoutput_upload)
        pvo_btn_row = QHBoxLayout()
        pvo_btn_row.setContentsMargins(0, 0, 0, 0)
        pvo_btn_row.setSpacing(8)
        # Start at the field column (same left edge as Interval spin); Test sits to the right.
        pvo_btn_row.addWidget(save_pvo_btn)
        pvo_btn_row.addWidget(test_pvo_btn)
        pvo_btn_row.addStretch()
        pvo_grid.addLayout(
            pvo_btn_row, 2, _params_field_col(0), 1,
            _PARAMS_GRID_SPAN + 1 - _params_field_col(0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        _params_add_field_grid(g_pvo, pvo_grid)

        # --- Wonderwatt.com (share / forecast — no public upload API) ---
        g_ww = add_group("Wonderwatt.com (share link · forecast compare)")
        g_ww.addWidget(QLabel(
            "<a href='https://www.wonderwatt.com/'>Wonderwatt</a> reads your "
            "plant from the <b>Growatt cloud</b> itself (not via this app). "
            "Paste an Advanced share link here so Potential Issues can compare "
            "their forecast with ours."
        ))
        g_ww.itemAt(g_ww.count() - 1).widget().setOpenExternalLinks(True)
        g_ww.itemAt(g_ww.count() - 1).widget().setWordWrap(True)
        g_ww.itemAt(g_ww.count() - 1).widget().setStyleSheet(
            "color: #a6adc8; font-size: 11px;"
        )
        from energy_dashboard.fetch.wonderwatt import load_wonderwatt_share_url
        self.ed_wonderwatt_share = QLineEdit(load_wonderwatt_share_url())
        self.ed_wonderwatt_share.setMinimumWidth(_SETUP_INFO_SPIN_W * 2)
        self.ed_wonderwatt_share.setPlaceholderText(
            "https://app.wonderwatt.com/?wattid=…&sig=…&time=…"
        )
        ww_grid = _params_make_field_grid()
        _params_grid_add_pairs(ww_grid, 0, [
            ("Share URL:", self.ed_wonderwatt_share),
        ])
        save_ww_btn = QPushButton("Save")
        save_ww_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        save_ww_btn.setFixedWidth(130)
        save_ww_btn.clicked.connect(self._save_wonderwatt_share)
        test_ww_btn = QPushButton("Test link")
        test_ww_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        test_ww_btn.setFixedWidth(130)
        test_ww_btn.clicked.connect(self._test_wonderwatt_share)
        ww_btn_row = QHBoxLayout()
        ww_btn_row.setContentsMargins(0, 0, 0, 0)
        ww_btn_row.setSpacing(8)
        # Left-align with the Share URL field; Test link sits to the right of Save.
        ww_btn_row.addWidget(save_ww_btn)
        ww_btn_row.addWidget(test_ww_btn)
        ww_btn_row.addStretch()
        ww_grid.addLayout(
            ww_btn_row, 1, _params_field_col(0), 1,
            _PARAMS_GRID_SPAN + 1 - _params_field_col(0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        _params_add_field_grid(g_ww, ww_grid)

        # --- Auto refresh (only place to enable / set interval) ---
        g5 = add_group("Auto-refresh (Growatt, Octopus Live, Tasmota)")
        r5a = QHBoxLayout()
        self.chk_auto_refresh = QCheckBox("Enable periodic auto-refresh")
        self.chk_auto_refresh.setChecked(bool(self.p.auto_refresh_enabled))
        r5a.addWidget(self.chk_auto_refresh)
        r5a.addStretch()
        g5.addLayout(r5a)
        self.sp_refresh = QSpinBox()
        self.sp_refresh.setRange(5, 600)
        self.sp_refresh.setValue(int(self.p.auto_refresh_seconds))
        save_ar_btn = QPushButton("Save")
        save_ar_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        save_ar_btn.setFixedWidth(130)
        save_ar_btn.setToolTip(
            "Save auto-refresh on/off and interval; applied immediately and restored when you open the dashboard"
        )
        save_ar_btn.clicked.connect(self._save_auto_refresh)
        ar_grid = _params_make_field_grid()
        _params_grid_add_pairs(ar_grid, 0, [
            ("Interval (seconds):", self.sp_refresh),
        ])
        ar_btn_row = QHBoxLayout()
        ar_btn_row.setContentsMargins(0, 0, 0, 0)
        ar_btn_row.setSpacing(8)
        # Own row under the interval spin, left-aligned with that spin.
        ar_btn_row.addWidget(save_ar_btn)
        ar_btn_row.addStretch()
        ar_grid.addLayout(
            ar_btn_row, 1, _params_field_col(0), 1,
            _PARAMS_GRID_SPAN + 1 - _params_field_col(0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        _params_add_field_grid(g5, ar_grid)

        # --- Hardware detection ---
        g_hw = add_group("Hardware Detection")
        r_coral = QHBoxLayout()
        self.coral_status_label = QLabel("Not checked")
        self.coral_status_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        detect_coral_btn = QPushButton("Detect Coral USB TPU")
        detect_coral_btn.setToolTip("Scan for a Google Coral Edge TPU USB accelerator")
        detect_coral_btn.clicked.connect(self._detect_coral_tpu)
        r_coral.addWidget(detect_coral_btn)
        r_coral.addWidget(self.coral_status_label)
        r_coral.addStretch()
        g_hw.addLayout(r_coral)

        # --- Database export ---
        g_db = add_group("Database Export (automatic logging on every refresh)")
        self._db_group = g_db.parentWidget()  # QGroupBox
        self._db_setup_buttons: list[QPushButton] = []

        # SQLite
        rd_sq = QHBoxLayout()
        rd_sq.setContentsMargins(0, 0, 0, 0)
        rd_sq.setSpacing(8)
        vcenter = Qt.AlignmentFlag.AlignVCenter
        self.chk_sqlite = QCheckBox("SQLite")
        self.chk_sqlite.setFixedWidth(_PARAMS_DB_CHK_W)
        self.chk_sqlite.setChecked(False)
        rd_sq.addWidget(self.chk_sqlite, 0, vcenter)

        sqlite_grid = _params_make_field_grid()
        sqlite_grid.setProperty("_params_db_backend_grid", True)
        sqlite_grid.setVerticalSpacing(_PARAMS_DB_GRID_VSPACE)
        sqlite_grid.setRowMinimumHeight(0, _PARAMS_DB_ROW_MIN_H)
        sqlite_c0 = _PARAMS_DB_COL0_LEFT
        sqlite_c0_field = max(0, sqlite_c0 - _PARAMS_DB_SPIN_LEFT)
        sqlite_c1_field_inset = _PARAMS_DB_PAIR1_FIELD_EXTRA_INSET - _PARAMS_DB_PAIR1_TITLE_LEFT
        sqlite_file_w = _params_db_pass_field_width(
            sqlite_c0_field,
            sqlite_c1_field_inset,
            grid_hspace=sqlite_grid.horizontalSpacing(),
        )
        self.ed_sqlite_path = QLineEdit(str(Path.home() / "energy_dashboard.db"))
        self.ed_sqlite_path.setFixedWidth(sqlite_file_w)
        self.ed_sqlite_path.setFixedHeight(_SETUP_INFO_SPIN_H)
        sqlite_grid.addWidget(
            _params_left_inset(
                _params_field_label("File:"),
                sqlite_c0,
                min_h=_PARAMS_DB_ROW_MIN_H,
            ),
            0,
            _params_label_col(0),
            vcenter | Qt.AlignmentFlag.AlignLeft,
        )
        sqlite_grid.addWidget(
            _params_left_inset(
                self.ed_sqlite_path,
                sqlite_c0_field,
                min_h=_PARAMS_DB_ROW_MIN_H,
            ),
            0,
            _params_field_col(0),
            1,
            _PARAMS_PAIR_STRIDE * 2,
            vcenter | Qt.AlignmentFlag.AlignLeft,
        )
        self.lbl_db_sqlite_found = self._make_db_status_line()
        self.lbl_db_sqlite_ok = self._make_db_status_line()
        self.lbl_db_sqlite_off = self._make_db_status_line()
        self._db_sqlite_status = self._make_db_status_panel(
            self.lbl_db_sqlite_found,
            self.lbl_db_sqlite_ok,
            self.lbl_db_sqlite_off,
        )
        rd_sq.addLayout(sqlite_grid, 0)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_sqlite)
        rd_sq.addWidget(browse_btn, 0, vcenter)
        rd_sq.addWidget(
            self._db_sqlite_status,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        rd_sq.addWidget(self._make_db_schema_panel("sqlite"), 1)
        g_db.addLayout(rd_sq)
        g_db.addLayout(self._make_db_action_row("sqlite"))

        _params_add_db_section_rule(g_db)

        # MySQL
        self.chk_mysql = QCheckBox("MySQL")
        self.chk_mysql.setFixedWidth(_PARAMS_DB_CHK_W)
        self.chk_mysql.setChecked(False)
        self.ed_mysql_host = QLineEdit("localhost")
        self.ed_mysql_port = QSpinBox()
        self.ed_mysql_port.setRange(1, 65535)
        self.ed_mysql_port.setValue(3306)
        self.ed_mysql_db = QLineEdit("energy")
        self.ed_mysql_user = QLineEdit()
        self.ed_mysql_pass = QLineEdit()
        self.ed_mysql_pass.setEchoMode(QLineEdit.Password)
        self.lbl_db_mysql_found = self._make_db_status_line()
        self.lbl_db_mysql_ok = self._make_db_status_line()
        self.lbl_db_mysql_off = self._make_db_status_line()
        self._db_mysql_status = self._make_db_status_panel(
            self.lbl_db_mysql_found,
            self.lbl_db_mysql_ok,
            self.lbl_db_mysql_off,
        )
        _params_add_db_backend_grid(
            g_db,
            self.chk_mysql,
            self.ed_mysql_host,
            self.ed_mysql_port,
            self.ed_mysql_db,
            self.ed_mysql_user,
            self.ed_mysql_pass,
            self._db_mysql_status,
            self._make_db_schema_panel("mysql"),
        )
        g_db.addLayout(self._make_db_action_row("mysql"))

        _params_add_db_section_rule(g_db)

        # PostgreSQL
        self.chk_pg = QCheckBox("PostgreSQL")
        self.chk_pg.setFixedWidth(_PARAMS_DB_CHK_W)
        self.chk_pg.setChecked(False)
        self.ed_pg_host = QLineEdit("localhost")
        self.ed_pg_port = QSpinBox()
        self.ed_pg_port.setRange(1, 65535)
        self.ed_pg_port.setValue(5432)
        self.ed_pg_db = QLineEdit("powermon")
        self.ed_pg_user = QLineEdit()
        self.ed_pg_pass = QLineEdit()
        self.ed_pg_pass.setEchoMode(QLineEdit.Password)
        self.lbl_db_pg_found = self._make_db_status_line()
        self.lbl_db_pg_ok = self._make_db_status_line()
        self.lbl_db_pg_off = self._make_db_status_line()
        self._db_pg_status = self._make_db_status_panel(
            self.lbl_db_pg_found,
            self.lbl_db_pg_ok,
            self.lbl_db_pg_off,
        )
        _params_add_db_backend_grid(
            g_db,
            self.chk_pg,
            self.ed_pg_host,
            self.ed_pg_port,
            self.ed_pg_db,
            self.ed_pg_user,
            self.ed_pg_pass,
            self._db_pg_status,
            self._make_db_schema_panel("pg"),
        )
        g_db.addLayout(self._make_db_action_row("pg"))
        self.ed_pg_user.textChanged.connect(lambda _t: self._refresh_db_schema_sql())

        for chk in (self.chk_sqlite, self.chk_mysql, self.chk_pg):
            chk.stateChanged.connect(self._on_db_enable_changed)

        # Shared DB operation summary.
        rd_btns = QHBoxLayout()
        self.db_status_label = QLabel("")
        self.db_status_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        self.db_status_label.setWordWrap(True)
        self.db_status_label.setMinimumWidth(280)
        rd_btns.addWidget(self.db_status_label)
        rd_btns.addStretch()
        g_db.addLayout(rd_btns)
        self._refresh_db_seen_off_rows()

        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply to all tabs")
        apply_btn.setToolTip("Writes these values into AppParameters and updates Analytics, Forecasts, Battery Analysis, and refresh timers.")
        apply_btn.clicked.connect(self._apply_all)
        btn_row.addWidget(apply_btn)
        sync_forecasts_btn = QPushButton("Copy Agile codes to Forecasts tab")
        sync_forecasts_btn.clicked.connect(self._sync_forecasts_only)
        btn_row.addWidget(sync_forecasts_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        hint = QLabel(
            "Changing import/export p/kWh updates the Octopus summary cost immediately.\n"
            "Use Apply to all tabs to push simulator settings, battery defaults, solar location, Agile codes, and auto-refresh.\n"
            "Growatt / Octopus Live / Tasmota no longer have their own auto-refresh toggles — control them here only.\n"
            "Use Save under Growatt inverter (local network) for LAN/Wi‑Fi IPs, "
            "web UI logins, and HTTP port; use Save next to Test Modbus for "
            "Local Modbus probe settings."
        )
        hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch()

        inner.setObjectName("parametersTabInner")
        # Spin chrome is app-wide (_spin_field_motif_qss); DB line edits stay local.
        inner.setStyleSheet(_setup_info_db_field_qss())
        self._align_setup_info_spins(inner)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def showEvent(self, event):
        super().showEvent(event)
        self._load_broker_url_from_settings()
        self._probe_db_seen_async()
        self._probe_service_async()

    def _align_setup_info_spins(self, root: QWidget):
        """Uniform spin size; title columns anchored to the widest title; gap before
        buttons in hbox rows."""
        field_grids = [
            g for g in root.findChildren(QGridLayout)
            if g.property("_params_field_grid")
        ]
        # Anchor each title column to the widest title that lands in it so every
        # field lines up vertically while the row stays condensed (30/40px gaps).
        label_needs: dict[int, int] = {}
        field_needs: dict[int, int] = {}
        for grid in field_grids:
            if grid.property("_params_db_backend_grid"):
                continue
            for i in range(grid.count()):
                w = grid.itemAt(i).widget()
                if not isinstance(w, QLabel):
                    continue
                _, col, _, _ = grid.getItemPosition(i)
                if col % _PARAMS_PAIR_STRIDE != 0:
                    continue
                pos = col // _PARAMS_PAIR_STRIDE
                need = _params_label_text_width(w.text(), w.font())
                label_needs[pos] = max(label_needs.get(pos, 0), need)
            for pos, need in _params_grid_field_width_needs(grid).items():
                field_needs[pos] = max(field_needs.get(pos, 0), need)
        label_widths = {
            p: max(56, need - _PARAMS_LABEL_COL_TRIM)
            for p, need in label_needs.items()
        }
        for grid in field_grids:
            if grid.property("_params_db_backend_grid"):
                _params_apply_grid_columns(grid)
                continue
            widths = dict(label_widths)
            _params_apply_grid_columns(grid, widths, field_needs)
            for i in range(grid.count()):
                w = grid.itemAt(i).widget()
                if not isinstance(w, QLabel):
                    continue
                _, col, _, _ = grid.getItemPosition(i)
                if col % _PARAMS_PAIR_STRIDE != 0:
                    continue
                pos = col // _PARAMS_PAIR_STRIDE
                w.setFixedWidth(widths.get(pos, label_needs.get(pos, _SETUP_INFO_LABEL_WIDTH)))

        anchor_by_id = {
            g.property("_params_anchor_id"): g
            for g in field_grids
            if g.property("_params_anchor_id")
        }
        for grid in field_grids:
            parent_id = grid.property("_params_anchor_parent")
            if not parent_id:
                continue
            src = anchor_by_id.get(str(parent_id))
            if src is None:
                continue
            for c in range(_PARAMS_GRID_SPAN + 1):
                cw = src.columnMinimumWidth(c)
                if cw > 0:
                    grid.setColumnMinimumWidth(c, cw)

        touched_layouts: set[int] = set()
        for spin in root.findChildren(QSpinBox) + root.findChildren(QDoubleSpinBox):
            field_w = (
                _PARAMS_DB_FIELD_W if spin.property("_params_db_field") else _SETUP_INFO_SPIN_W
            )
            apply_spin_field_motif(spin, width=field_w)
            parent = spin.parentWidget()
            if parent is None:
                continue
            lay = parent.layout()
            if isinstance(lay, QGridLayout):
                # Label widths and column stretch are handled when the grid is
                # built (see _params_field_label / _params_apply_grid_columns).
                continue
            if not isinstance(lay, QHBoxLayout):
                continue
            lid = id(lay)
            if lid not in touched_layouts:
                lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)
                lay.setSpacing(8)
                touched_layouts.add(lid)
            idx = lay.indexOf(spin)
            if idx > 0:
                prev = lay.itemAt(idx - 1).widget()
                if isinstance(prev, QLabel):
                    text = prev.text().strip()
                    if idx >= 2:
                        before = lay.itemAt(idx - 2).widget()
                        if isinstance(before, (QSpinBox, QDoubleSpinBox)):
                            pair_idx = 1
                        else:
                            pair_idx = 0
                    else:
                        pair_idx = 0
                    anchor = label_widths.get(
                        pair_idx,
                        _SETUP_INFO_PAIR_LABEL_WIDTH if pair_idx else _SETUP_INFO_LABEL_WIDTH,
                    )
                    if pair_idx == 0 and anchor:
                        prev.setFixedWidth(anchor)
                    elif len(text) <= 10:
                        prev.setFixedWidth(_SETUP_INFO_SHORT_LABEL_WIDTH)
                    else:
                        prev.setFixedWidth(
                            label_widths.get(pair_idx, _SETUP_INFO_PAIR_LABEL_WIDTH)
                        )
                    prev.setAlignment(
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    )
            if idx >= 0 and idx + 1 < lay.count():
                nxt = lay.itemAt(idx + 1).widget()
                if isinstance(nxt, QPushButton) and not spin.property("_pm_spin_btn_gap"):
                    lay.insertSpacing(idx + 1, _SETUP_INFO_SPIN_BTN_GAP)
                    spin.setProperty("_pm_spin_btn_gap", True)

        for edit in root.findChildren(QLineEdit):
            if not edit.property("_params_setup_line_field"):
                continue
            if edit.parent() is not None and isinstance(
                edit.parent(), (QSpinBox, QDoubleSpinBox),
            ):
                continue
            field_w = _SETUP_INFO_SPIN_W
            if edit.property("_params_setup_line_wide"):
                apply_setup_info_line_field_motif(
                    edit, width=_SETUP_INFO_SPIN_W * 3, expand=False,
                )
            else:
                apply_setup_info_line_field_motif(edit, width=_SETUP_INFO_SPIN_W)

    def _load_broker_url_from_settings(self):
        if not getattr(self, "ed_broker_url", None):
            return
        s = self._settings()
        url = (s.value("tasmota/powermon_broker_url") or "").strip()
        self.ed_broker_url.setText(url)

    def _broker_url_for_probe(self) -> str:
        raw = ""
        if getattr(self, "ed_broker_url", None) is not None:
            raw = self.ed_broker_url.text().strip()
        if not raw:
            s = self._settings()
            raw = (s.value("tasmota/powermon_broker_url") or "").strip()
        return resolve_broker_base(raw)

    def _save_broker_url(self):
        url = self.ed_broker_url.text().strip()
        s = self._settings()
        s.setValue("tasmota/powermon_broker_url", url)
        s.sync()
        tt = getattr(self.dash, "tasmota_tab", None)
        if tt is not None and getattr(tt, "ed_powermon_broker_url", None) is not None:
            tt.ed_powermon_broker_url.setText(url)
        self.dash.set_status(
            f"Broker URL saved ({resolve_broker_base(url) if url else 'cleared — will use env/default'})."
        )
        self._probe_service_async()

    def _postgres_host_setting_note(self, http: dict | None, field: str | None = None) -> str:
        """Where the collector's database host is set, and the values in use.

        The address is never written into the program. It is read from the
        collector environment and from the PostgreSQL Host field on this page.
        """
        http = http or {}
        db = http.get("database") if isinstance(http.get("database"), dict) else {}
        host = str(db.get("host") or "").strip()
        port = db.get("port")
        name = str(db.get("name") or "").strip()
        host_from = str(db.get("host_from") or "POWERMON_PG_HOST")
        if field is None:
            field = ""
            edit = getattr(self, "ed_pg_host", None)
            if edit is not None:
                field = edit.text().strip()
        lines = [
            "PostgreSQL host is not hard-coded.",
            "Setup & Info → Database → PostgreSQL → Host saves it as db/pg_host.",
            "sudo ./services/install-energy-collector.sh copies that into "
            f"{host_from} in /etc/default/energy-collector. "
            "The running collector uses that environment value.",
        ]
        if host:
            target = host
            if port not in (None, ""):
                target = f"{host}:{port}"
            if name:
                target = f"{target}/{name}"
            lines.append(f"Collector is using {host_from} = {target}.")
        else:
            lines.append(
                "This broker did not report its database host "
                "(restart energy-collector to include it)."
            )
        if field:
            lines.append(f"This screen's PostgreSQL Host is currently {field}.")
            if host and field != host:
                lines.append(
                    "Those two differ. Edit the Host field, Save the database "
                    "settings, then re-run the install script (or edit "
                    "/etc/default/energy-collector) and restart energy-collector."
                )
        else:
            lines.append("This screen's PostgreSQL Host field is empty.")
        return "\n".join(lines)

    def _test_broker_url(self):
        broker = self._broker_url_for_probe()
        pg_field = ""
        if getattr(self, "ed_pg_host", None) is not None:
            pg_field = self.ed_pg_host.text().strip()
        self.btn_broker_test.setEnabled(False)

        def _worker():
            try:
                status = collect_collector_service_status(broker)
                http = status.get("http") or {}
                url = http.get("url") or broker
                db_note = self._postgres_host_setting_note(http, field=pg_field)
                if http.get("reachable"):
                    if http.get("ok"):
                        msg = f"Broker healthy at {url}"
                        online = http.get("online_devices")
                        if online is not None:
                            msg += f"\n{online} Tasmota device(s) online in last snapshot."
                    else:
                        msg = (
                            f"Reachable but degraded at {url}\n"
                            f"{http.get('error') or http.get('growatt_error') or 'ok=false'}"
                        )
                else:
                    msg = (
                        f"Could not reach {url}\n"
                        f"{http.get('http_error') or 'connection failed'}"
                    )
                msg = f"{msg}\n\n{db_note}"
                self._inv.invoke(lambda m=msg: self._finish_broker_url_test(m))
            except Exception as e:
                self._inv.invoke(
                    lambda err=str(e): self._finish_broker_url_test(
                        f"Broker test failed unexpectedly:\n{err}", error=True
                    )
                )

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_broker_url_test(self, msg, error=False):
        self.btn_broker_test.setEnabled(True)
        if error:
            QMessageBox.warning(self, "Broker URL test", msg)
        else:
            QMessageBox.information(self, "Broker URL test", msg)

    def _broker_url_from_settings(self) -> str:
        return self._broker_url_for_probe()

    def _set_svc_controls_enabled(self, enabled: bool):
        for btn in (
            self.btn_svc_start,
            self.btn_svc_stop,
            self.btn_svc_boot,
            self.btn_svc_refresh,
        ):
            btn.setEnabled(enabled)

    def _update_svc_boot_button(self, status: dict | None = None):
        status = status or self._service_status or {}
        _, unit, _ = pick_control_scope(status, for_control=True)
        boot_on = is_boot_enabled(unit) if unit.get("installed") else False
        qss, hint = _tasmota_toggle_btn_qss(boot_on)
        self.btn_svc_boot.setStyleSheet(qss)
        if unit.get("installed"):
            state = "enabled at boot" if boot_on else "disabled at boot"
            self.btn_svc_boot.setText("Boot Start")
            self.btn_svc_boot.setToolTip(
                f"Click to toggle boot start ({state}). Green = enabled, red = disabled."
            )
        else:
            self.btn_svc_boot.setText("Boot Start")
            self.btn_svc_boot.setToolTip("Install the collector service first.")

    def _probe_service_async(self):
        self.lbl_svc_system.setText("checking…")
        self.lbl_svc_system.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        self.lbl_svc_http.setText("checking…")
        self.lbl_svc_http.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        self._set_svc_controls_enabled(False)
        broker = self._broker_url_for_probe()

        def _worker():
            status = collect_collector_service_status(broker)
            self._inv.invoke(lambda s=status: self._apply_service_status(s))

        threading.Thread(target=_worker, daemon=True).start()

    def _svc_run_control(self, action: str):
        if self._service_control_busy:
            return
        status = self._service_status
        if not status:
            self._probe_service_async()
            return
        _, unit, _ = pick_control_scope(status, for_control=True)
        if not unit.get("installed"):
            QMessageBox.information(
                self,
                "Energy collector",
                "Service is not installed. Run:\n"
                "sudo ./services/install-energy-collector.sh",
            )
            return
        self._service_control_busy = True
        self._set_svc_controls_enabled(False)
        self.lbl_svc_detail.setText(f"Running systemctl {action}…")

        def _worker():
            ok, msg = control_collector_service(action, status)
            self._inv.invoke(lambda o=ok, m=msg: self._svc_control_done(o, m))

        threading.Thread(target=_worker, daemon=True).start()

    def _svc_control_done(self, ok: bool, msg: str):
        self._service_control_busy = False
        self._set_svc_controls_enabled(True)
        if not ok:
            QMessageBox.warning(self, "Energy collector", msg)
        self._probe_service_async()

    def _svc_start_restart(self):
        self._svc_run_control("restart")

    def _svc_stop(self):
        self._svc_run_control("stop")

    def _svc_toggle_boot(self):
        status = self._service_status
        if not status:
            self._probe_service_async()
            return
        _, unit, _ = pick_control_scope(status, for_control=True)
        if not unit.get("installed"):
            QMessageBox.information(
                self,
                "Energy collector",
                "Service is not installed.",
            )
            return
        action = "disable" if is_boot_enabled(unit) else "enable"
        self._svc_run_control(action)

    @staticmethod
    def _service_scope_label(scope: str) -> str:
        if scope == "system":
            return "boot service"
        if scope == "user":
            return "user session copy"
        return scope

    @classmethod
    def _service_main_status_html(cls, system: dict, user: dict, primary: dict | None) -> str:
        """One-line collector status — avoid raw systemctl scope jargon."""
        sys_on = system.get("installed") and system.get("active_state") == "active"
        usr_on = user.get("installed") and user.get("active_state") == "active"
        if sys_on and usr_on:
            return (
                "<span style='color:#f38ba8; font-weight:bold;'>"
                "Two copies running</span>"
                "<span style='color:#6c7086;'> — stop the user session copy "
                "(<code>systemctl --user stop energy-collector</code>) so only the "
                "boot service runs.</span>"
            )
        if not system.get("installed") and not user.get("installed"):
            return (
                "<span style='color:#f38ba8; font-weight:bold;'>Not installed</span>"
                "<span style='color:#6c7086;'> — "
                "<code>sudo ./services/install-energy-collector.sh</code></span>"
            )
        unit = primary or system or user
        if not unit.get("installed"):
            unit = system if system.get("installed") else user
        active = unit.get("active_state", "unknown")
        scope = unit.get("scope", "system")
        scope_lbl = cls._service_scope_label(scope)
        enabled = (unit.get("enabled_state") or "").lower()
        boot_on = enabled in ("enabled", "enabled-runtime", "static")
        if active == "active":
            pid = unit.get("main_pid")
            pid_bit = (
                f" · <span style='color:#89b4fa;font-weight:bold;'>PID {pid}</span>"
                if pid
                else ""
            )
            boot_bit = (
                "starts at boot"
                if boot_on
                else "manual start only (not enabled at boot)"
            )
            since = unit.get("active_since") or ""
            since_bit = f" · since {since}" if since else ""
            return (
                "<span style='color:#a6e3a1; font-weight:bold;'>Running</span>"
                f"<span style='color:#6c7086;'> · {scope_lbl} · {boot_bit}"
                f"{pid_bit}{since_bit}</span>"
            )
        if active == "failed":
            state = "Failed"
            colour = "#f38ba8"
        else:
            state = "Stopped"
            colour = "#f38ba8"
        start_hint = (
            "<code>systemctl --user start energy-collector</code> (no sudo)"
            if user.get("installed")
            else (
                "<code>sudo systemctl start energy-collector</code>"
                if scope == "system"
                else "<code>systemctl --user start energy-collector</code>"
            )
        )
        return (
            f"<span style='color:{colour}; font-weight:bold;'>{state}</span>"
            f"<span style='color:#6c7086;'> · {scope_lbl} · {start_hint}</span>"
        )

    @staticmethod
    def _service_extra_notes(system: dict, user: dict) -> list[str]:
        """Grey footnotes only when they add information (not noise)."""
        notes = []
        sys_inst = system.get("installed")
        usr_inst = user.get("installed")
        sys_on = sys_inst and system.get("active_state") == "active"
        usr_on = usr_inst and user.get("active_state") == "active"
        if sys_on and usr_inst and not usr_on:
            notes.append(
                "A user-session install exists but is off — expected after "
                "<code>install-energy-collector.sh</code>. Only the boot service should run."
            )
        elif usr_on and not sys_on:
            notes.append(
                "Only the user-session copy is running — it stops when you log out. "
                "Prefer the boot service for 24/7 collection."
            )
        elif usr_inst and not sys_inst and not usr_on:
            notes.append(
                "User-session service is installed but stopped. "
                "For always-on collection use "
                "<code>sudo ./services/install-energy-collector.sh</code>."
            )
        elif sys_inst and usr_inst and not sys_on and not usr_on:
            notes.append(
                "Both boot and user-session units are installed. "
                "<b>Start/Restart</b> here uses the user-session copy (no sudo). "
                "Terminal: <code>sudo systemctl start energy-collector</code> for the boot unit."
            )
        return notes

    def _apply_service_status(self, status: dict):
        self._service_status = status
        system = status.get("system_unit") or {}
        user = status.get("user_unit") or {}
        http = status.get("http") or {}
        primary = status.get("primary")
        installed = bool(system.get("installed") or user.get("installed"))
        if not self._service_control_busy:
            self._set_svc_controls_enabled(True)
            self.btn_svc_start.setEnabled(installed)
            self.btn_svc_stop.setEnabled(installed)
            self.btn_svc_boot.setEnabled(installed)
        self._update_svc_boot_button(status)

        self.lbl_svc_system.setTextFormat(Qt.RichText)
        self.lbl_svc_system.setText(
            self._service_main_status_html(system, user, primary)
        )

        url = http.get("url") or self._broker_url_for_probe()
        url_html = _params_soft_wrap_html(url)
        if http.get("reachable"):
            if http.get("ok"):
                http_colour = "#a6e3a1"
                http_weight = "normal"
                http_state = "healthy"
            else:
                http_colour = "#fab387"
                http_weight = "bold"
                http_state = "degraded"
            updated = format_updated_at(http.get("updated_at"))
            online = http.get("online_devices")
            extra_parts = []
            if updated:
                extra_parts.append(f"last poll {updated}")
            if online is not None:
                extra_parts.append(f"{online} device(s) online")
            extra = (" · " + " · ".join(extra_parts)) if extra_parts else ""
            self.lbl_svc_http.setToolTip(f"{url}{extra}")
            self.lbl_svc_http.setTextFormat(Qt.RichText)
            self.lbl_svc_http.setText(
                f"<span style='color:{http_colour}; font-weight:{http_weight};'>"
                f"{http_state}</span>"
                f"<span style='color:#6c7086;'> · {url_html}{html.escape(extra)}</span>"
            )
        else:
            err = http.get("http_error") or "unreachable"
            err_html = _params_soft_wrap_html(err)
            self.lbl_svc_http.setToolTip(f"{url} — {err}")
            self.lbl_svc_http.setTextFormat(Qt.RichText)
            self.lbl_svc_http.setText(
                f"<span style='color:#f38ba8; font-weight:bold;'>"
                f"unreachable</span>"
                f"<span style='color:#6c7086;'> · {url_html} — {err_html}</span>"
            )

        detail_parts = []
        for note in self._service_extra_notes(system, user):
            detail_parts.append(f"<span style='color:#6c7086;'>{note}</span>")
        if not system.get("installed") and not user.get("installed"):
            detail_parts.append(
                "<span style='color:#f38ba8; font-weight:bold;'>"
                "Collector service is not installed.</span> "
                "Run <code>sudo ./services/install-energy-collector.sh</code> "
                "from the PowerModel directory."
            )
        growatt_err = http.get("growatt_error")
        poll_err = http.get("error")
        if growatt_err:
            detail_parts.append(f"Growatt poll error: {growatt_err}")
        if poll_err:
            detail_parts.append(f"Collector error: {html.escape(str(poll_err))}")
        detail_parts.append(
            "<span style='color:#cdd6f4;'>"
            + html.escape(self._postgres_host_setting_note(http)).replace("\n", "<br>")
            + "</span>"
        )
        if not http.get("reachable"):
            hint = broker_unreachable_hint(url, primary, http)
            if hint:
                detail_parts.append(
                    f"<span style='color:#fab387;font-weight:bold;'>{html.escape(hint)}</span>"
                )
        if http.get("reachable") and http.get("online_devices") == 0:
            detail_parts.append(
                "<span style='color:#fab387; font-weight:bold;'>"
                "Tasmota: 0 devices online</span> — HTTP is up but no device responded. "
                "Check <code>POWERMON_TASMOTA_IPS</code> or "
                "<code>POWERMON_IP_START</code>/<code>POWERMON_IP_END</code> in "
                "<code>/etc/default/energy-collector</code> (should match the Tasmota tab IP range), "
                "then <code>sudo systemctl restart energy-collector</code>."
            )
        if detail_parts:
            detail_parts.append(
                f"<span style='color:#45475a;'>Last checked {status.get('checked_at', '—')}</span>"
            )
        else:
            detail_parts.append(
                f"<span style='color:#6c7086;'>Last checked {status.get('checked_at', '—')}</span>"
            )
        self.lbl_svc_detail.setText("<br>".join(detail_parts))

    @staticmethod
    def _make_db_status_line():
        lbl = QLabel("—")
        lbl.setStyleSheet(f"color: {_DB_RAG_GREY}; font-size: 11px;")
        lbl.setMinimumWidth(_PARAMS_DB_STATUS_MIN_W)
        lbl.setWordWrap(True)
        lbl.setAlignment(
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter
        )
        lbl.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Preferred,
        )
        return lbl

    def _make_db_status_panel(
        self,
        lbl_found: QLabel,
        lbl_ok: QLabel,
        lbl_off: QLabel,
    ) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(2)
        lay.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        for lbl in (lbl_found, lbl_ok, lbl_off):
            lbl.setAlignment(left)
            lay.addWidget(lbl, 0, left)
        panel.setMinimumWidth(_PARAMS_DB_STATUS_MIN_W)
        panel.setMaximumWidth(_PARAMS_DB_STATUS_MAX_W)
        panel.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )
        return panel

    def _make_db_schema_panel(self, dialect: str) -> QWidget:
        """Right-hand create-all SQL + table list for one engine."""
        from energy_dashboard.db.full_schema import schema_info_html, schema_script

        box = QWidget()
        box.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        box.setMinimumWidth(_PARAMS_DB_SCHEMA_MIN_W)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 0, 0, 0)
        lay.setSpacing(4)
        info = QLabel(schema_info_html(dialect))
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setWordWrap(True)
        info.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        info.setStyleSheet(
            f"color: {_DARK_SUBTEXT}; font-size: 11px; font-weight: normal;"
        )
        sql = QTextEdit()
        sql.setReadOnly(True)
        sql.setPlainText(schema_script(dialect, grant_role=self._db_grant_role(dialect)))
        if dialect == "pg":
            self._db_schema_sql_view = sql
        sql.setMinimumHeight(110)
        sql.setMaximumHeight(150)
        sql.setFont(QFont("monospace", 9))
        sql.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        sql.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        _apply_dark_log_view(sql, object_name=f"dbSchemaSql_{dialect}")
        copy = QPushButton("Copy SQL")
        copy.setToolTip("Copy this engine's full CREATE script to the clipboard")
        copy.clicked.connect(
            lambda _checked=False, d=dialect: self._copy_db_schema_sql(d)
        )
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addWidget(copy, 0, Qt.AlignmentFlag.AlignLeft)
        btn_row.addStretch(1)
        lay.addWidget(info)
        lay.addWidget(sql, 1)
        lay.addLayout(btn_row)
        return box

    def _db_grant_role(self, dialect: str) -> str:
        """PostgreSQL login the GRANT lines should name (blank for other engines)."""
        if dialect != "pg":
            return ""
        ed = getattr(self, "ed_pg_user", None)
        if ed is not None:
            return ed.text().strip()
        s = QSettings("PowerModel", "EnergyDashboard2")
        return str(s.value("db/pg_user", "") or "").strip()

    def _refresh_db_schema_sql(self) -> None:
        """Keep the PostgreSQL GRANT lines in step with the user field."""
        from energy_dashboard.db.full_schema import schema_script

        view = getattr(self, "_db_schema_sql_view", None)
        if view is None:
            return
        view.setPlainText(schema_script("pg", grant_role=self._db_grant_role("pg")))

    def _copy_db_schema_sql(self, dialect: str) -> None:
        from energy_dashboard.db.full_schema import schema_script

        QApplication.clipboard().setText(
            schema_script(dialect, grant_role=self._db_grant_role(dialect))
        )
        engine = {"sqlite": "SQLite", "mysql": "MySQL", "pg": "PostgreSQL"}.get(
            dialect, dialect
        )
        self.dash.set_status(f"{engine} CREATE SQL copied to clipboard.")

    def _show_missing_tables(self, backend: str) -> None:
        """List missing logger tables for one engine and show CREATE SQL for them."""
        from energy_dashboard.db.connect_probe import probe_missing_logger_tables
        from energy_dashboard.dialogs.db_missing import DbMissingTablesDialog

        self._push_db_config_to_logger(backend)
        engine = self._db_backend_display_name(backend) or backend
        dialect = {"sqlite": "sqlite", "mysql": "mysql", "pg": "pg"}.get(
            backend, backend
        )
        grant_role = self._db_grant_role(dialect)
        self.dash.set_status(f"{engine}: checking for missing tables…")

        def _worker():
            dl = getattr(self.dash, "data_logger", None)
            if dl is None:
                result = {
                    "engine": engine,
                    "dialect": dialect,
                    "connected": False,
                    "missing": [],
                    "error": "Logger not initialised",
                }
            elif backend == "sqlite":
                result = probe_missing_logger_tables(
                    "SQLite", path=dl.sqlite_path,
                )
            elif backend == "mysql":
                result = probe_missing_logger_tables(
                    "MySQL",
                    host=dl.mysql_host,
                    port=dl.mysql_port,
                    user=dl.mysql_user,
                    password=dl.mysql_pass,
                    database=dl.mysql_db,
                )
            else:
                result = probe_missing_logger_tables(
                    "PostgreSQL",
                    host=dl.pg_host,
                    port=dl.pg_port,
                    user=dl.pg_user,
                    password=dl.pg_pass,
                    database=dl.pg_db,
                )
            self._inv.invoke(
                lambda r=result, g=grant_role, b=backend: self._finish_show_missing(
                    r, grant_role=g, backend=b,
                )
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_show_missing(self, result: dict, *, grant_role: str, backend: str) -> None:
        from energy_dashboard.dialogs.db_missing import DbMissingTablesDialog

        # Restore automatic-logging selection after a one-row probe.
        self._push_db_config_to_logger()
        engine = str(result.get("engine") or backend)
        dialect = str(result.get("dialect") or backend)
        missing = list(result.get("missing") or [])
        connected = bool(result.get("connected"))
        err = str(result.get("error") or "")
        if connected and not missing:
            self.dash.set_status(f"{engine}: no missing logger tables.")
        elif connected:
            self.dash.set_status(
                f"{engine}: {len(missing)} missing logger table"
                f"{'s' if len(missing) != 1 else ''}."
            )
        else:
            self.dash.set_status(
                f"{engine}: could not check tables — {err or 'not connected'}."
            )
        dlg = DbMissingTablesDialog(
            self,
            engine=engine,
            dialect=dialect,
            missing=missing,
            connected=connected,
            error=err,
            grant_role=grant_role,
        )
        dlg.exec()

    @staticmethod
    def _set_db_status_line(lbl: QLabel, text: str, color: str, *, bold=False, tooltip=""):
        weight = " font-weight: bold;" if bold else ""
        lbl.setText(text)
        lbl.setStyleSheet(f"color: {color}; font-size: 11px;{weight}")
        lbl.setToolTip(tooltip)

    def _db_status_rows(self):
        return (
            (
                "SQLite",
                self.chk_sqlite,
                self.lbl_db_sqlite_found,
                self.lbl_db_sqlite_ok,
                self.lbl_db_sqlite_off,
            ),
            (
                "MySQL",
                self.chk_mysql,
                self.lbl_db_mysql_found,
                self.lbl_db_mysql_ok,
                self.lbl_db_mysql_off,
            ),
            (
                "PostgreSQL",
                self.chk_pg,
                self.lbl_db_pg_found,
                self.lbl_db_pg_ok,
                self.lbl_db_pg_off,
            ),
        )

    def _refresh_db_seen_off_rows(self):
        for _name, chk, lbl_found, lbl_ok, lbl_off in self._db_status_rows():
            if not chk.isChecked():
                self._set_db_status_line(lbl_found, "", _DB_RAG_GREY)
                self._set_db_status_line(
                    lbl_ok,
                    "Disabled",
                    _DB_RAG_RED,
                    bold=True,
                    tooltip="Enable the checkbox to log to this backend.",
                )
                self._set_db_status_line(lbl_off, "", _DB_RAG_GREY)
            else:
                pass

    def _on_db_enable_changed(self, _state=0):
        self._refresh_db_seen_off_rows()
        if any(chk.isChecked() for chk in (self.chk_sqlite, self.chk_mysql, self.chk_pg)):
            self._probe_db_seen_async()

    def _apply_db_status_stage(self, lbl: QLabel, ok: bool, text: str, tip: str):
        self._set_db_status_line(
            lbl,
            text,
            _DB_RAG_GREEN if ok else _DB_RAG_RED,
            bold=not ok,
            tooltip=str(tip or ""),
        )

    @staticmethod
    def _db_backend_display_name(backend: str | None) -> str | None:
        return {
            "sqlite": "SQLite",
            "mysql": "MySQL",
            "pg": "PostgreSQL",
        }.get(backend or "")

    def _db_backend_checkbox(self, backend: str | None):
        return {
            "sqlite": self.chk_sqlite,
            "mysql": self.chk_mysql,
            "pg": self.chk_pg,
        }.get(backend or "")

    def _apply_db_seen_results(self, results, found_results=None, summary_prefix=None, backend=None):
        only_name = self._db_backend_display_name(backend)
        parts = []
        all_ok = True
        any_enabled = False
        for name, chk, lbl_found, lbl_ok, lbl_off in self._db_status_rows():
            if only_name is not None and name != only_name:
                continue
            if only_name is None and not chk.isChecked():
                continue
            any_enabled = True
            stage = results.get(name) if isinstance(results, dict) else None
            if not isinstance(stage, dict) or "seen_label" not in stage:
                self._set_db_status_line(lbl_found, "Checking DB seen…", _UI_BLUE)
                self._set_db_status_line(lbl_ok, "Checking connection…", _UI_BLUE)
                self._set_db_status_line(lbl_off, "Checking tables…", _UI_BLUE)
                continue
            self._apply_db_status_stage(
                lbl_found,
                stage.get("seen_ok"),
                stage.get("seen_label", ""),
                stage.get("seen_tip", ""),
            )
            self._apply_db_status_stage(
                lbl_ok,
                stage.get("conn_ok"),
                stage.get("conn_label", ""),
                stage.get("conn_tip", ""),
            )
            self._apply_db_status_stage(
                lbl_off,
                stage.get("tables_ok"),
                stage.get("tables_label", ""),
                stage.get("tables_tip", ""),
            )
            parts.append(stage.get("summary") or name)
            if not stage.get("ok"):
                all_ok = False
        if summary_prefix:
            prefix = f"{summary_prefix} — "
        else:
            prefix = ""
        if not any_enabled:
            self.db_status_label.setText(
                f"{prefix}No backends enabled — tick SQLite / MySQL / PostgreSQL to log data."
            )
            self.db_status_label.setStyleSheet(f"color: {_DB_RAG_AMBER}; font-size: 11px;")
        elif parts:
            self.db_status_label.setText(prefix + " | ".join(parts))
            self.db_status_label.setStyleSheet(
                f"color: {_DB_RAG_GREEN if all_ok else _DB_RAG_RED}; font-size: 11px;"
            )

    def _probe_db_seen_async(self, backend=None, user_test=None):
        only_name = self._db_backend_display_name(backend)
        self._push_db_config_to_logger(backend)
        self._refresh_db_seen_off_rows()
        for name, chk, lbl_found, lbl_ok, lbl_off in self._db_status_rows():
            if (only_name is not None and name == only_name) or (only_name is None and chk.isChecked()):
                self._set_db_status_line(lbl_found, "Checking DB seen…", _UI_BLUE)
                self._set_db_status_line(lbl_ok, "Checking connection…", _UI_BLUE)
                self._set_db_status_line(lbl_off, "Checking tables…", _UI_BLUE)
        if only_name is None and not any(chk.isChecked() for chk in (self.chk_sqlite, self.chk_mysql, self.chk_pg)):
            self._apply_db_seen_results({})
            return

        def _worker():
            dl = getattr(self.dash, 'data_logger', None)
            if dl is None:
                self._inv.invoke(
                    lambda u=user_test: self._set_db_seen_error(
                        "Logger not initialised", user_test=u,
                    )
                )
                return
            stages = {}
            if dl.sqlite_enabled:
                stages["SQLite"] = probe_engine_stages("SQLite", path=dl.sqlite_path)
            if dl.mysql_enabled:
                stages["MySQL"] = probe_engine_stages(
                    "MySQL",
                    host=dl.mysql_host,
                    port=dl.mysql_port,
                    user=dl.mysql_user,
                    password=dl.mysql_pass,
                    database=dl.mysql_db,
                )
            if dl.pg_enabled:
                stages["PostgreSQL"] = probe_engine_stages(
                    "PostgreSQL",
                    host=dl.pg_host,
                    port=dl.pg_port,
                    user=dl.pg_user,
                    password=dl.pg_pass,
                    database=dl.pg_db,
                )
            if "MySQL" in stages:
                dl.note_connect_result("mysql", bool(stages["MySQL"].get("conn_ok")))
            if "PostgreSQL" in stages:
                dl.note_connect_result("pg", bool(stages["PostgreSQL"].get("conn_ok")))
            self._inv.invoke(
                lambda r=stages, b=backend, u=user_test: self._finish_db_probe(
                    r, b, user_test=u,
                )
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_db_probe(self, results, backend=None, user_test=None):
        self._apply_db_seen_results(results, backend=backend)
        if backend is not None:
            # Restore the logger's real automatic-logging backend selection after
            # a one-row probe, because per-row tests operate even if the checkbox
            # is currently off.
            self._push_db_config_to_logger()
        if user_test is not None:
            self._complete_db_user_test(results, user_test)

    def _complete_db_user_test(self, results, user_test) -> None:
        backend, _on_done = user_test
        name = self._db_backend_display_name(backend) or "Database"
        stage = results.get(name) if isinstance(results, dict) else None
        if not isinstance(stage, dict):
            ok, detail = False, "No result from the database test."
        else:
            ok = bool(stage.get("conn_ok"))
            detail = str(stage.get("summary") or stage.get("conn_tip") or "")
        self._report_link_test(
            backend or "db",
            ok,
            detail,
            title=f"{name} test",
            status=f"{name}: {detail}" if detail else None,
        )

    def _set_db_seen_error(self, message, user_test=None):
        for name, chk, lbl_found, lbl_ok, lbl_off in self._db_status_rows():
            if chk.isChecked():
                self._set_db_status_line(
                    lbl_found, f"{name} DB not seen", _DB_RAG_RED, tooltip=message
                )
                self._set_db_status_line(
                    lbl_ok, "Database not connected", _DB_RAG_RED, tooltip=message
                )
                self._set_db_status_line(
                    lbl_off, "Tables not connected", _DB_RAG_RED, tooltip=message
                )
        self.db_status_label.setText(message)
        self.db_status_label.setStyleSheet(f"color: {_DB_RAG_RED}; font-size: 11px;")
        if user_test is not None:
            backend, _on_done = user_test
            name = self._db_backend_display_name(backend) or "Database"
            self._report_link_test(
                backend or "db", False, message, title=f"{name} test",
            )

    @staticmethod
    def _settings_str(s: QSettings, key: str, default: str = "") -> str:
        return str(s.value(key, default) or default).strip()

    def load_battery_solar_from_settings(self):
        s = self._settings()
        if s.contains("params/base_load_kw"):
            self.p.base_load_kw = float(s.value("params/base_load_kw", 0.4))
            self.sp_base_load.setValue(self.p.base_load_kw)
        if s.contains("params/scheduled_loads_count"):
            count = int(s.value("params/scheduled_loads_count", 0))
            loads = []
            for i in range(count):
                if s.contains(f"params/sched_{i}_hour"):
                    loads.append({
                        'hour': int(s.value(f"params/sched_{i}_hour", 0)),
                        'kw': float(s.value(f"params/sched_{i}_kw", 0)),
                        'duration_min': int(s.value(f"params/sched_{i}_dur", 60)),
                    })
            self.p.scheduled_loads = loads
            self._refresh_sched_table()
        if s.contains("params/battery_capacity_kwh"):
            self.sp_cap.setValue(float(s.value("params/battery_capacity_kwh", self.p.battery_capacity_kwh)))
        if s.contains("params/battery_low_soc_threshold_pct"):
            self.sp_soc_thr.setValue(int(s.value("params/battery_low_soc_threshold_pct", 10)))
        if s.contains("params/solar_lat"):
            self.ed_lat.setText(self._fmt_solar_coord(s.value("params/solar_lat", "")))
        if s.contains("params/solar_lon"):
            self.ed_lon.setText(self._fmt_solar_coord(s.value("params/solar_lon", "")))
        if s.contains("params/solar_tilt"):
            self.ed_tilt.setText(str(s.value("params/solar_tilt", "") or ""))
        if s.contains("params/solar_azimuth"):
            self.ed_azimuth.setText(str(s.value("params/solar_azimuth", "") or ""))
        if s.contains("params/solar_kwp"):
            self.ed_kwp.setText(str(s.value("params/solar_kwp", "") or ""))
        if s.contains("params/growatt_local_ip"):
            legacy_ip = self._settings_str(s, "params/growatt_local_ip")
        else:
            legacy_ip = ""
        if s.contains("params/growatt_lan_ip"):
            self.p.growatt_lan_ip = self._settings_str(s, "params/growatt_lan_ip")
        else:
            self.p.growatt_lan_ip = legacy_ip
        self.ed_growatt_lan_ip.setText(self.p.growatt_lan_ip)
        if s.contains("params/growatt_wifi_ip"):
            self.p.growatt_wifi_ip = self._settings_str(s, "params/growatt_wifi_ip")
        elif legacy_ip:
            self.p.growatt_wifi_ip = legacy_ip
        else:
            self.p.growatt_wifi_ip = ""
        self.ed_growatt_wifi_ip.setText(self.p.growatt_wifi_ip)
        if s.contains("params/growatt_lan_user"):
            self.p.growatt_lan_user = self._settings_str(s, "params/growatt_lan_user")
            self.ed_growatt_lan_user.setText(self.p.growatt_lan_user)
        if s.contains("params/growatt_lan_password"):
            self.p.growatt_lan_password = str(s.value("params/growatt_lan_password", "") or "")
            self.ed_growatt_lan_pass.setText(self.p.growatt_lan_password)
        if s.contains("params/growatt_wifi_user"):
            self.p.growatt_wifi_user = self._settings_str(s, "params/growatt_wifi_user")
            self.ed_growatt_wifi_user.setText(self.p.growatt_wifi_user)
        if s.contains("params/growatt_wifi_password"):
            self.p.growatt_wifi_password = str(s.value("params/growatt_wifi_password", "") or "")
            self.ed_growatt_wifi_pass.setText(self.p.growatt_wifi_password)
        if s.contains("params/growatt_telemetry_source") or s.contains("params/grott_mqtt_enabled"):
            self.p.growatt_telemetry_source = read_growatt_telemetry_source(s, self.p)
            self.p.grott_mqtt_enabled = growatt_uses_grott(self.p.growatt_telemetry_source)
            self.rb_growatt_api.setChecked(self.p.growatt_telemetry_source == GROWATT_TELEMETRY_API)
            self.chk_grott_mqtt.setChecked(self.p.growatt_telemetry_source == GROWATT_TELEMETRY_GROTT)
            if hasattr(self, "rb_growatt_hybrid"):
                self.rb_growatt_hybrid.setChecked(
                    self.p.growatt_telemetry_source == GROWATT_TELEMETRY_HYBRID
                )
        if s.contains("params/grott_fill_missing_api"):
            self.p.grott_fill_missing_api = s.value("params/grott_fill_missing_api", False, type=bool)
            if hasattr(self, "chk_grott_fill_missing"):
                self.chk_grott_fill_missing.setChecked(bool(self.p.grott_fill_missing_api))
        if s.contains("params/grott_mqtt_host"):
            self.p.grott_mqtt_host = self._settings_str(s, "params/grott_mqtt_host")
            self.ed_grott_host.setText(self.p.grott_mqtt_host)
        if s.contains("params/grott_mqtt_port"):
            self.p.grott_mqtt_port = int(s.value("params/grott_mqtt_port", 1883))
            self.sp_grott_port.setValue(self.p.grott_mqtt_port)
        emqx_host = str(
            s.value("params/emqx_host", self.p.grott_mqtt_host or _EMQX_ROUTE_DEFAULT_HOST)
            or _EMQX_ROUTE_DEFAULT_HOST
        ).strip()
        self.ed_emqx_host.setText(emqx_host)
        emqx_port = int(s.value("params/emqx_port", self.p.grott_mqtt_port or _EMQX_ROUTE_DEFAULT_PORT))
        self.sp_emqx_port.setValue(max(1, min(65535, emqx_port)))
        emqx_user = str(
            s.value("params/emqx_user", self.p.grott_mqtt_user or "") or ""
        ).strip()
        emqx_pass = str(
            s.value("params/emqx_password", self.p.grott_mqtt_password or "") or ""
        )
        # Prefer Tasmota MQTT auth when the EMQX row was never filled (common).
        if not emqx_user:
            emqx_user = str(s.value("tasmota/mqtt_user", "") or "").strip()
            if not emqx_pass:
                emqx_pass = str(s.value("tasmota/mqtt_pass", "") or "")
        self.ed_emqx_user.setText(emqx_user)
        self.ed_emqx_pass.setText(emqx_pass)
        if s.contains("params/grott_mqtt_user"):
            self.p.grott_mqtt_user = self._settings_str(s, "params/grott_mqtt_user")
            self.ed_grott_user.setText(self.p.grott_mqtt_user)
        if s.contains("params/grott_mqtt_password"):
            self.p.grott_mqtt_password = str(s.value("params/grott_mqtt_password", "") or "")
            self.ed_grott_pass.setText(self.p.grott_mqtt_password)
        # Persist empty Grott/EMQX broker from Tasmota/EMQX so Hybrid stays up.
        from energy_dashboard.config import heal_grott_mqtt_broker_settings
        healed = heal_grott_mqtt_broker_settings(s, self.p)
        if healed.get("host"):
            self.ed_grott_host.setText(healed["host"])
            self.sp_grott_port.setValue(int(healed["port"]))
            self.ed_emqx_host.setText(
                self.ed_emqx_host.text().strip() or healed["host"]
            )
            if healed.get("username"):
                if not self.ed_grott_user.text().strip():
                    self.ed_grott_user.setText(healed["username"])
                    self.ed_grott_pass.setText(healed.get("password") or "")
                if not self.ed_emqx_user.text().strip():
                    self.ed_emqx_user.setText(healed["username"])
                    self.ed_emqx_pass.setText(healed.get("password") or "")
        if s.contains("params/grott_mqtt_topic"):
            self.p.grott_mqtt_topic = self._settings_str(
                s, "params/grott_mqtt_topic", "energy/growatt"
            ) or "energy/growatt"
            self.ed_grott_topic.setText(self.p.grott_mqtt_topic)
        if s.contains("params/grott_mqtt_fresh_s"):
            self.p.grott_mqtt_fresh_s = int(s.value("params/grott_mqtt_fresh_s", 120))
            self.sp_grott_fresh.setValue(self.p.grott_mqtt_fresh_s)
        if s.contains("params/growatt_local_port"):
            self.p.growatt_local_port = int(s.value("params/growatt_local_port", 80))
            self.sp_growatt_port.setValue(self.p.growatt_local_port)
        if s.contains("params/growatt_modbus_mode"):
            self.p.growatt_modbus_mode = str(
                s.value("params/growatt_modbus_mode", "off") or "off"
            ).strip()
            idx = self.cb_growatt_modbus.findData(self.p.growatt_modbus_mode)
            if idx >= 0:
                self.cb_growatt_modbus.blockSignals(True)
                try:
                    self.cb_growatt_modbus.setCurrentIndex(idx)
                finally:
                    self.cb_growatt_modbus.blockSignals(False)
        if s.contains("params/growatt_modbus_tcp_port"):
            self.p.growatt_modbus_tcp_port = int(s.value("params/growatt_modbus_tcp_port", 502))
            self.sp_growatt_modbus_tcp.setValue(self.p.growatt_modbus_tcp_port)
        if s.contains("params/growatt_modbus_serial_path"):
            self.p.growatt_modbus_serial_path = self._settings_str(
                s, "params/growatt_modbus_serial_path", "/dev/ttyUSB0"
            )
            self.ed_growatt_modbus_serial.setText(self.p.growatt_modbus_serial_path)
        if s.contains("params/growatt_modbus_baud"):
            self.p.growatt_modbus_baud = int(s.value("params/growatt_modbus_baud", 9600))
            self.sp_growatt_modbus_baud.setValue(self.p.growatt_modbus_baud)
        if s.contains("params/growatt_modbus_unit"):
            self.p.growatt_modbus_unit = int(s.value("params/growatt_modbus_unit", 1))
            self.sp_growatt_modbus_unit.setValue(self.p.growatt_modbus_unit)
        self.p.growatt_modbus_writes_enabled = bool(
            s.value("params/growatt_modbus_writes_enabled", False, type=bool)
        )
        if hasattr(self, "chk_growatt_modbus_writes"):
            self.chk_growatt_modbus_writes.setChecked(self.p.growatt_modbus_writes_enabled)
        self._update_grott_source_controls()
        self._update_growatt_modbus_controls()
        self._read_growatt_form_into_params()
        self.p.battery_capacity_kwh = self.sp_cap.value()
        self.p.battery_low_soc_threshold_pct = float(self.sp_soc_thr.value())
        self._normalize_solar_coord_edit(self.ed_lat)
        self._normalize_solar_coord_edit(self.ed_lon)
        self.p.solar_lat = self.ed_lat.text().strip()
        self.p.solar_lon = self.ed_lon.text().strip()
        self.p.solar_tilt = self.ed_tilt.text().strip()
        self.p.solar_azimuth = self.ed_azimuth.text().strip()
        self.p.solar_kwp = self.ed_kwp.text().strip()
        self.dash.battery_tab.apply_from_app_params()
        self.dash.analytics_tab.apply_from_app_params()
        if hasattr(self.dash, "growatt_tab"):
            self.dash.growatt_tab.apply_grott_settings()
        ft = self.dash.forecasts_tab
        ft.solar_edits['lat'].setText(self.p.solar_lat)
        ft.solar_edits['lon'].setText(self.p.solar_lon)
        ft.solar_edits['tilt'].setText(self.p.solar_tilt)
        ft.solar_edits['azimuth'].setText(self.p.solar_azimuth)
        ft.solar_edits['kwp'].setText(self.p.solar_kwp)
        try:
            ft._refresh_locale_label(force=True)
        except Exception:
            pass
        # Populate Connected/Disconnected for Local Modbus without a dialog.
        mode = (getattr(self.p, "growatt_modbus_mode", "off") or "off").lower()
        if mode == "off":
            self._set_growatt_modbus_status(False, "Local Modbus check is disabled.")
        else:
            QTimer.singleShot(400, lambda: self._test_growatt_modbus_connection(quiet=True))

    # ── Main tab bar visibility ───────────────────────────────────────

    def _apply_main_tab_bar_visibility(self):
        s = QSettings("PowerModel", "EnergyDashboard2")
        for key, cb in self._tab_visibility_checks.items():
            s.setValue(f"tabs/visible/{key}", cb.isChecked())
        try:
            s.sync()
        except Exception:
            pass
        self.dash._rebuild_main_tab_bar()
        self.dash.set_status("Tab bar updated from Setup && Info.")

    def _show_all_main_tabs(self):
        for cb in self._tab_visibility_checks.values():
            cb.setChecked(True)
        self._apply_main_tab_bar_visibility()

    # ── About / History pop-ups ──────────────────────────────────────

    def _show_about_dialog(self):
        try:
            AboutDialog(self).exec()
        except Exception as e:
            try:
                _log.warn("Setup", f"AboutDialog failed: {e}")
            except Exception:
                pass
            QMessageBox.warning(self, "About", f"Couldn't open About dialog:\n{e}")

    def _show_history_dialog(self):
        try:
            HistoryDialog(self).exec()
        except Exception as e:
            try:
                _log.warn("Setup", f"HistoryDialog failed: {e}")
            except Exception:
                pass
            QMessageBox.warning(self, "History", f"Couldn't open History dialog:\n{e}")

    def _save_battery_defaults(self):
        self.p.battery_capacity_kwh = self.sp_cap.value()
        self.p.battery_low_soc_threshold_pct = float(self.sp_soc_thr.value())
        s = self._settings()
        s.setValue("params/battery_capacity_kwh", self.p.battery_capacity_kwh)
        s.setValue("params/battery_low_soc_threshold_pct", int(self.sp_soc_thr.value()))
        s.sync()
        self.dash.battery_tab.apply_from_app_params()
        self.dash.analytics_tab.apply_from_app_params()
        self.dash.set_status("Battery defaults saved.")

    def _save_alarm_settings(self):
        self.dash.apply_alarm_settings_from_ui(
            enabled=self.chk_alarms.isChecked(),
            desktop=self.chk_alarm_desktop.isChecked(),
            hold_minutes=float(self.sp_alarm_hold.value()),
            pv_min_kw=float(self.sp_alarm_pv_min.value()),
        )
        self.dash.set_status("Live alarm settings saved.")
        try:
            self.dash._evaluate_alarms()
        except Exception:
            pass

    @staticmethod
    def _fmt_solar_coord(val) -> str:
        """Format latitude/longitude to exactly 5 decimal places when numeric."""
        s = str(val or "").strip()
        if not s:
            return ""
        try:
            return f"{float(s):.5f}"
        except (TypeError, ValueError):
            return s

    def _normalize_solar_coord_edit(self, edit):
        """Snap a Setup Lat/Lon field to 5 decimal places on edit finish."""
        if edit is None:
            return
        edit.setText(self._fmt_solar_coord(edit.text()))

    def _save_solar_installation(self):
        self._normalize_solar_coord_edit(self.ed_lat)
        self._normalize_solar_coord_edit(self.ed_lon)
        self.p.solar_lat = self.ed_lat.text().strip()
        self.p.solar_lon = self.ed_lon.text().strip()
        self.p.solar_tilt = self.ed_tilt.text().strip()
        self.p.solar_azimuth = self.ed_azimuth.text().strip()
        self.p.solar_kwp = self.ed_kwp.text().strip()
        s = self._settings()
        s.setValue("params/solar_lat", self.p.solar_lat)
        s.setValue("params/solar_lon", self.p.solar_lon)
        s.setValue("params/solar_tilt", self.p.solar_tilt)
        s.setValue("params/solar_azimuth", self.p.solar_azimuth)
        s.setValue("params/solar_kwp", self.p.solar_kwp)
        s.sync()
        ft = self.dash.forecasts_tab
        ft.solar_edits['lat'].setText(self.p.solar_lat)
        ft.solar_edits['lon'].setText(self.p.solar_lon)
        ft.solar_edits['tilt'].setText(self.p.solar_tilt)
        ft.solar_edits['azimuth'].setText(self.p.solar_azimuth)
        ft.solar_edits['kwp'].setText(self.p.solar_kwp)
        ft._refresh_locale_label()
        try:
            _log.info(
                f"Setup & Info: saved solar installation lat={self.p.solar_lat} "
                f"lon={self.p.solar_lon} tilt={self.p.solar_tilt} "
                f"azimuth={self.p.solar_azimuth} kwp={self.p.solar_kwp}"
            )
        except Exception:
            pass
        self.dash.set_status(
            f"Solar installation saved: {self.p.solar_lat}, {self.p.solar_lon} "
            f"({self.p.solar_kwp} kWp, tilt {self.p.solar_tilt}°, az {self.p.solar_azimuth}°)"
        )

    def _refresh_sched_table(self):
        self.sched_table.clear()
        for entry in self.p.scheduled_loads:
            item = QTreeWidgetItem([
                f"{entry['hour']:02d}:00",
                f"{entry['kw']:.1f}",
                str(entry['duration_min']),
                '',
            ])
            self.sched_table.addTopLevelItem(item)

    def _add_scheduled_load(self):
        entry = {
            'hour': self.sp_sched_hour.value(),
            'kw': self.sp_sched_kw.value(),
            'duration_min': self.sp_sched_dur.value(),
        }
        self.p.scheduled_loads.append(entry)
        self.p.scheduled_loads.sort(key=lambda e: e['hour'])
        self._refresh_sched_table()

    def _remove_scheduled_load(self):
        idx = self.sched_table.indexOfTopLevelItem(self.sched_table.currentItem())
        if idx >= 0 and idx < len(self.p.scheduled_loads):
            self.p.scheduled_loads.pop(idx)
            self._refresh_sched_table()

    def _save_load_profile(self):
        self.p.base_load_kw = self.sp_base_load.value()
        s = self._settings()
        s.setValue("params/base_load_kw", self.p.base_load_kw)
        s.setValue("params/scheduled_loads_count", len(self.p.scheduled_loads))
        for i, entry in enumerate(self.p.scheduled_loads):
            s.setValue(f"params/sched_{i}_hour", entry['hour'])
            s.setValue(f"params/sched_{i}_kw", entry['kw'])
            s.setValue(f"params/sched_{i}_dur", entry['duration_min'])
        s.sync()
        self.dash.set_status("Load profile saved.")

    def _on_cost_spin_changed(self):
        self.p.import_flat_pence = self.sp_import.value()
        self.p.export_flat_pence = self.sp_export.value()
        self.dash.octopus_tab.recalc_estimated_cost()

    def _sync_forecasts_only(self):
        self.p.agile_product = self.ed_agile_prod.text().strip()
        self.p.agile_tariff = self.ed_agile_tariff.text().strip()
        self.p.agile_export_tariff = self.ed_agile_export_tariff.text().strip()
        self.dash.forecasts_tab.product_edit.setText(self.p.agile_product)
        self.dash.forecasts_tab.tariff_edit.setText(self.p.agile_tariff)
        self.dash.forecasts_tab.export_tariff_edit.setText(self.p.agile_export_tariff)
        self.dash.set_status("Agile product/tariff copied to Forecasts tab.")

    @staticmethod
    def _settings():
        return QSettings("PowerModel", "EnergyDashboard2")

    def _save_auto_refresh(self):
        sec = int(self.sp_refresh.value())
        enabled = self.chk_auto_refresh.isChecked()
        s = self._settings()
        s.setValue("auto_refresh/enabled", enabled)
        s.setValue("auto_refresh/seconds", sec)
        self.p.auto_refresh_seconds = sec
        self.p.auto_refresh_enabled = enabled
        self.dash.apply_auto_refresh_from_params(kick=True)
        self.dash.set_status("Auto-refresh saved.")

    def _save_growatt_cloud_credentials(self):
        s = self._settings()
        s.setValue("growatt/username", self.ed_growatt_cloud_user.text().strip())
        s.setValue("growatt/password", self.ed_growatt_cloud_pass.text())
        s.setValue("growatt/api_token", self.ed_growatt_cloud_token.text().strip())
        s.setValue("growatt/serial", self.ed_growatt_cloud_serial.text().strip())
        # A credential change should not inherit an old rate-limit pause timer.
        s.remove("growatt/rate_limit_until")
        s.remove("growatt/v1_rate_limit_until")
        s.sync()
        self.dash.set_status("Growatt cloud credentials saved.")
        gt = getattr(self.dash, "growatt_tab", None)
        if gt is not None and hasattr(gt, "_load_growatt_credentials"):
            try:
                gt._load_growatt_credentials()
            except Exception:
                pass

    def _test_growatt_cloud_connection(self):
        """Test Growatt cloud from Setup fields (always cloud, not Grott MQTT)."""
        self._save_growatt_cloud_credentials()
        gt = getattr(self.dash, "growatt_tab", None)
        if gt is None or not hasattr(gt, "_test_growatt_cloud_credentials"):
            self.dash.set_status("Growatt Live Status tab is not available.")
            return
        gt._test_growatt_cloud_credentials()

    def _save_pvoutput_settings(self):
        from energy_dashboard.fetch.pvoutput import save_pvoutput_config
        cfg = save_pvoutput_config(
            enabled=self.chk_pvoutput.isChecked(),
            api_key=self.ed_pvoutput_key.text(),
            system_id=self.ed_pvoutput_sid.text(),
            interval_s=int(self.sp_pvoutput_interval.value()),
        )
        state = "enabled" if cfg.ready else ("on but incomplete" if cfg.enabled else "disabled")
        self.dash.set_status(f"PVOutput settings saved ({state}).")

    def _test_pvoutput_upload(self, on_done=None):
        from energy_dashboard.fetch.pvoutput import save_pvoutput_config, upload_from_growatt
        self._arm_link_cb("pvoutput", on_done)
        save_pvoutput_config(
            enabled=True,
            api_key=self.ed_pvoutput_key.text(),
            system_id=self.ed_pvoutput_sid.text(),
            interval_s=int(self.sp_pvoutput_interval.value()),
        )
        self.chk_pvoutput.setChecked(True)
        gt = getattr(self.dash, "growatt_tab", None)
        status = getattr(gt, "mix_status_data", None) or {} if gt else {}
        totals = getattr(gt, "mix_totals_data", None) or {} if gt else {}
        if not status:
            self._report_link_test(
                "pvoutput",
                False,
                "No Growatt live snapshot yet — refresh Growatt first.",
                title="PVOutput",
                status="PVOutput test: no Growatt live snapshot yet — refresh Growatt first.",
            )
            return
        self.dash.set_status("PVOutput: uploading test status…")

        def _run():
            ok, msg = upload_from_growatt(status, totals, force=True)
            self._inv.invoke(
                lambda o=ok, m=msg: self._finish_pvoutput_test(o, m)
            )

        import threading
        threading.Thread(target=_run, daemon=True).start()

    def _finish_pvoutput_test(self, ok, msg):
        self._report_link_test(
            "pvoutput",
            bool(ok),
            msg,
            title="PVOutput test",
            status=f"PVOutput test: {'OK — ' if ok else 'failed — '}{msg}",
        )

    def _save_wonderwatt_share(self):
        from energy_dashboard.fetch.wonderwatt import save_wonderwatt_share_url
        parsed = save_wonderwatt_share_url(self.ed_wonderwatt_share.text())
        if parsed is None:
            self.ed_wonderwatt_share.clear()
            self.dash.set_status("Wonderwatt share URL cleared / invalid.")
            return
        self.ed_wonderwatt_share.setText(parsed["share_url"])
        pot = getattr(self.dash, "pot_issues_tab", None)
        if pot is not None and hasattr(pot, "ww_url"):
            pot.ww_url.setText(parsed["share_url"])
        self.dash.set_status(f"Wonderwatt share saved (wattid={parsed['wattid']}).")

    def _test_wonderwatt_share(self):
        from energy_dashboard.fetch.wonderwatt import (
            save_wonderwatt_share_url,
            test_wonderwatt_connection,
        )
        parsed = save_wonderwatt_share_url(self.ed_wonderwatt_share.text())
        if parsed is None:
            self.dash.set_status(
                "Wonderwatt test: need a valid share URL (wattid, sig, time)."
            )
            return
        self.ed_wonderwatt_share.setText(parsed["share_url"])
        self.dash.set_status("Wonderwatt: testing share link…")

        def _run():
            ok, msg = test_wonderwatt_connection(parsed["share_url"])
            self.dash.set_status(
                f"Wonderwatt: {'connected — ' if ok else 'failed — '}{msg}"
            )

        import threading
        threading.Thread(target=_run, daemon=True).start()

    def set_growatt_telemetry_source(self, source: str, fill_missing: bool | None = None):
        """Mirror the live-status source toggle onto the Setup radios."""
        if not hasattr(self, "chk_grott_mqtt"):
            return
        if source not in (GROWATT_TELEMETRY_API, GROWATT_TELEMETRY_GROTT, GROWATT_TELEMETRY_HYBRID):
            source = GROWATT_TELEMETRY_API
        self.p.growatt_telemetry_source = source
        self.p.grott_mqtt_enabled = growatt_uses_grott(source)
        if fill_missing is not None:
            self.p.grott_fill_missing_api = bool(fill_missing)
        for btn in (self.rb_growatt_api, self.chk_grott_mqtt, getattr(self, "rb_growatt_hybrid", None)):
            if btn is not None:
                btn.blockSignals(True)
        try:
            self.rb_growatt_api.setChecked(source == GROWATT_TELEMETRY_API)
            self.chk_grott_mqtt.setChecked(source == GROWATT_TELEMETRY_GROTT)
            if hasattr(self, "rb_growatt_hybrid"):
                self.rb_growatt_hybrid.setChecked(source == GROWATT_TELEMETRY_HYBRID)
            if fill_missing is not None and hasattr(self, "chk_grott_fill_missing"):
                self.chk_grott_fill_missing.blockSignals(True)
                try:
                    self.chk_grott_fill_missing.setChecked(bool(fill_missing))
                finally:
                    self.chk_grott_fill_missing.blockSignals(False)
        finally:
            for btn in (self.rb_growatt_api, self.chk_grott_mqtt, getattr(self, "rb_growatt_hybrid", None)):
                if btn is not None:
                    btn.blockSignals(False)
        self._update_grott_source_controls()

    def set_growatt_source(self, grott: bool):
        """Legacy bool mirror for older Growatt tab hooks."""
        self.set_growatt_telemetry_source(
            GROWATT_TELEMETRY_GROTT if grott else GROWATT_TELEMETRY_API,
        )

    def reveal_growatt_section(self):
        """Scroll the Setup page so the Growatt inverter section is visible."""
        box = getattr(self, "_growatt_group_box", None)
        scroll = getattr(self, "_setup_scroll", None)
        if box is None or scroll is None:
            return
        QTimer.singleShot(0, lambda: scroll.ensureWidgetVisible(box, 0, 0))

    def _read_growatt_form_into_params(self):
        self.p.growatt_lan_ip = self.ed_growatt_lan_ip.text().strip()
        self.p.growatt_wifi_ip = self.ed_growatt_wifi_ip.text().strip()
        self.p.growatt_lan_user = self.ed_growatt_lan_user.text().strip()
        self.p.growatt_lan_password = self.ed_growatt_lan_pass.text()
        self.p.growatt_wifi_user = self.ed_growatt_wifi_user.text().strip()
        self.p.growatt_wifi_password = self.ed_growatt_wifi_pass.text()
        source = self._growatt_form_source()
        self.p.growatt_telemetry_source = source
        self.p.grott_mqtt_enabled = growatt_uses_grott(source)
        self.p.grott_fill_missing_api = (
            bool(self.chk_grott_fill_missing.isChecked()) if growatt_uses_grott(source) else False
        )
        self.p.grott_mqtt_host = self.ed_grott_host.text().strip()
        self.p.grott_mqtt_port = int(self.sp_grott_port.value())
        self.p.grott_mqtt_user = self.ed_grott_user.text().strip()
        self.p.grott_mqtt_password = self.ed_grott_pass.text()
        self.p.grott_mqtt_topic = self.ed_grott_topic.text().strip() or "energy/growatt"
        self.p.grott_mqtt_fresh_s = int(self.sp_grott_fresh.value())
        self.p.growatt_local_ip = self.p.growatt_lan_ip
        self.p.growatt_local_port = int(self.sp_growatt_port.value())
        self.p.growatt_modbus_mode = self.cb_growatt_modbus.currentData() or "off"
        self.p.growatt_modbus_tcp_port = int(self.sp_growatt_modbus_tcp.value())
        self.p.growatt_modbus_serial_path = self.ed_growatt_modbus_serial.text().strip()
        self.p.growatt_modbus_baud = int(self.sp_growatt_modbus_baud.value())
        self.p.growatt_modbus_unit = int(self.sp_growatt_modbus_unit.value())
        self.p.growatt_modbus_writes_enabled = bool(
            hasattr(self, "chk_growatt_modbus_writes")
            and self.chk_growatt_modbus_writes.isChecked()
            and self.p.growatt_modbus_mode != "off"
        )

    def _write_growatt_params_to_settings(self, s):
        s.setValue("params/growatt_lan_ip", self.p.growatt_lan_ip)
        s.setValue("params/growatt_wifi_ip", self.p.growatt_wifi_ip)
        s.setValue("params/growatt_lan_user", self.p.growatt_lan_user)
        s.setValue("params/growatt_lan_password", self.p.growatt_lan_password)
        s.setValue("params/growatt_wifi_user", self.p.growatt_wifi_user)
        s.setValue("params/growatt_wifi_password", self.p.growatt_wifi_password)
        write_growatt_telemetry_settings(
            s,
            self.p.growatt_telemetry_source,
            fill_missing_api=self.p.grott_fill_missing_api,
        )
        s.setValue("params/grott_mqtt_host", self.p.grott_mqtt_host)
        s.setValue("params/grott_mqtt_port", int(self.p.grott_mqtt_port))
        s.setValue("params/grott_mqtt_user", self.p.grott_mqtt_user)
        s.setValue("params/grott_mqtt_password", self.p.grott_mqtt_password)
        s.setValue("params/grott_mqtt_topic", self.p.grott_mqtt_topic)
        s.setValue("params/grott_mqtt_fresh_s", int(self.p.grott_mqtt_fresh_s))
        s.setValue("params/growatt_local_ip", self.p.growatt_lan_ip)
        s.setValue("params/growatt_local_port", int(self.p.growatt_local_port))
        s.setValue("params/growatt_modbus_mode", self.p.growatt_modbus_mode)
        s.setValue("params/growatt_modbus_tcp_port", self.p.growatt_modbus_tcp_port)
        s.setValue("params/growatt_modbus_serial_path", self.p.growatt_modbus_serial_path)
        s.setValue("params/growatt_modbus_baud", self.p.growatt_modbus_baud)
        s.setValue("params/growatt_modbus_unit", self.p.growatt_modbus_unit)
        s.setValue(
            "params/growatt_modbus_writes_enabled",
            bool(getattr(self.p, "growatt_modbus_writes_enabled", False)),
        )

    @staticmethod
    def _growatt_web_url(host, port, username="", password=""):
        from urllib.parse import quote
        host = (host or "").strip()
        if not host:
            return ""
        port = int(port) if port else 80
        scheme = "https" if port == 443 else "http"
        user = (username or "").strip()
        pwd = password or ""
        if user:
            auth = f"{quote(user, safe='')}:{quote(pwd, safe='')}@"
        else:
            auth = ""
        return f"{scheme}://{auth}{host}:{port}/"

    def _growatt_web_targets(self):
        targets = []
        lan = self.ed_growatt_lan_ip.text().strip()
        if lan:
            targets.append((
                "LAN",
                lan,
                self.ed_growatt_lan_user.text(),
                self.ed_growatt_lan_pass.text(),
            ))
        wifi = self.ed_growatt_wifi_ip.text().strip()
        if wifi:
            targets.append((
                "WiFi",
                wifi,
                self.ed_growatt_wifi_user.text(),
                self.ed_growatt_wifi_pass.text(),
            ))
        return targets

    def _on_growatt_modbus_mode_changed(self):
        mode = self.cb_growatt_modbus.currentData()
        if mode is None:
            mode = "off"
        # Do not auto-rewrite TCP port: USR RS485 gateways often speak
        # Modbus TCP on 8899 (not 502). Clobbering 8899→502 on mode select
        # made Save appear to "lose" a working Modbus setup.
        self._update_growatt_modbus_controls()
        if (mode or "off").lower() == "off":
            self._set_growatt_modbus_status(False, "Local Modbus check is disabled.")
        else:
            self._set_growatt_modbus_status(False, "Not tested yet — click Test Modbus.")

    def _update_growatt_modbus_controls(self):
        mode = self.cb_growatt_modbus.currentData()
        if mode is None:
            mode = "off"
        tcp_on = mode in ("tcp", "tcp_rtu")
        ser_on = mode == "serial"
        self.sp_growatt_modbus_tcp.setEnabled(tcp_on)
        self.ed_growatt_modbus_serial.setEnabled(ser_on)
        self.sp_growatt_modbus_baud.setEnabled(ser_on)
        self.sp_growatt_modbus_unit.setEnabled(mode != "off")
        if hasattr(self, "chk_growatt_modbus_writes"):
            self.chk_growatt_modbus_writes.setEnabled(mode != "off")
            if mode == "off":
                self.chk_growatt_modbus_writes.setChecked(False)

    def _emqx_form_broker(self, *, fill_empty_creds=True):
        """Host/port/user/pass from the EMQX row, with sensible credential fallbacks.

        Empty username/password placeholders must not wipe working Tasmota/Grott
        MQTT auth when the user clicks Save without retyping ``mqadmin``.
        """
        host = self.ed_emqx_host.text().strip() or _EMQX_ROUTE_DEFAULT_HOST
        port = int(self.sp_emqx_port.value())
        user = self.ed_emqx_user.text().strip()
        password = self.ed_emqx_pass.text()
        if fill_empty_creds and not user:
            s = self._settings()
            user = str(
                s.value("tasmota/mqtt_user", "")
                or getattr(self.p, "grott_mqtt_user", "")
                or self.ed_grott_user.text()
                or ""
            ).strip()
            if not password:
                password = str(
                    s.value("tasmota/mqtt_pass", "")
                    or getattr(self.p, "grott_mqtt_password", "")
                    or self.ed_grott_pass.text()
                    or ""
                )
            if user:
                self.ed_emqx_user.setText(user)
                self.ed_emqx_pass.setText(password)
        self.ed_emqx_host.setText(host)
        return host, port, user, password

    def _push_broker_to_grott_tasmota(self, host, port, user, password, *, s=None):
        """Write broker into Grott + Tasmota form fields, app_params, and QSettings."""
        self.ed_grott_host.setText(host)
        self.sp_grott_port.setValue(port)
        self.ed_grott_user.setText(user)
        self.ed_grott_pass.setText(password)
        self.p.grott_mqtt_host = host
        self.p.grott_mqtt_port = port
        self.p.grott_mqtt_user = user
        self.p.grott_mqtt_password = password

        if s is None:
            s = self._settings()
        s.setValue("params/emqx_host", host)
        s.setValue("params/emqx_port", port)
        s.setValue("params/emqx_user", user)
        s.setValue("params/emqx_password", password)
        s.setValue("params/grott_mqtt_host", host)
        s.setValue("params/grott_mqtt_port", port)
        s.setValue("params/grott_mqtt_user", user)
        s.setValue("params/grott_mqtt_password", password)
        s.setValue("tasmota/mqtt_host", host)
        s.setValue("tasmota/mqtt_port", port)
        s.setValue("tasmota/mqtt_user", user)
        s.setValue("tasmota/mqtt_pass", password)

        tt = getattr(self.dash, "tasmota_tab", None)
        if tt is not None:
            if getattr(tt, "ed_mqtt_host", None) is not None:
                tt.ed_mqtt_host.setText(host)
            if getattr(tt, "sp_mqtt_port", None) is not None:
                tt.sp_mqtt_port.setValue(port)
            if getattr(tt, "ed_mqtt_user", None) is not None:
                tt.ed_mqtt_user.setText(user)
            if getattr(tt, "ed_mqtt_pass", None) is not None:
                tt.ed_mqtt_pass.setText(password)

    def _save_growatt_modbus(self):
        """Persist only Local Modbus probe settings."""
        self.p.growatt_modbus_mode = self.cb_growatt_modbus.currentData() or "off"
        self.p.growatt_modbus_tcp_port = int(self.sp_growatt_modbus_tcp.value())
        self.p.growatt_modbus_serial_path = self.ed_growatt_modbus_serial.text().strip()
        self.p.growatt_modbus_baud = int(self.sp_growatt_modbus_baud.value())
        self.p.growatt_modbus_unit = int(self.sp_growatt_modbus_unit.value())
        writes_on = bool(
            hasattr(self, "chk_growatt_modbus_writes")
            and self.chk_growatt_modbus_writes.isChecked()
            and self.p.growatt_modbus_mode != "off"
        )
        self.p.growatt_modbus_writes_enabled = writes_on
        if hasattr(self, "chk_growatt_modbus_writes"):
            self.chk_growatt_modbus_writes.setChecked(writes_on)
        s = self._settings()
        s.setValue("params/growatt_modbus_mode", self.p.growatt_modbus_mode)
        s.setValue("params/growatt_modbus_tcp_port", self.p.growatt_modbus_tcp_port)
        s.setValue("params/growatt_modbus_serial_path", self.p.growatt_modbus_serial_path)
        s.setValue("params/growatt_modbus_baud", self.p.growatt_modbus_baud)
        s.setValue("params/growatt_modbus_unit", self.p.growatt_modbus_unit)
        s.setValue("params/growatt_modbus_writes_enabled", writes_on)
        s.sync()
        mode = self.p.growatt_modbus_mode
        if mode in ("tcp", "tcp_rtu"):
            detail = f"{mode} port {self.p.growatt_modbus_tcp_port}, unit {self.p.growatt_modbus_unit}"
        elif mode == "serial":
            detail = (
                f"serial {self.p.growatt_modbus_serial_path or '—'} "
                f"@ {self.p.growatt_modbus_baud}, unit {self.p.growatt_modbus_unit}"
            )
        else:
            detail = "disabled"
        if writes_on:
            detail += "; inverter writes via Modbus: ON"
        elif mode != "off":
            detail += "; inverter writes via Modbus: off"
        self.dash.set_status(f"Growatt Modbus settings saved ({detail}).")
        if hasattr(self.dash, "connectivity_tab"):
            self.dash.connectivity_tab.refresh_status(test_db=False)
        # Refresh Connected/Disconnected after Save using the values just stored.
        if mode != "off":
            self._test_growatt_modbus_connection(quiet=True)
        else:
            self._set_growatt_modbus_status(False, "Local Modbus check is disabled.")

    def _save_growatt_lan(self):
        # EMQX row is the shared local broker — sync into Grott before persist so
        # Save never stores an empty grott_mqtt_host while EMQX host is set.
        host, port, user, password = self._emqx_form_broker()
        self._push_broker_to_grott_tasmota(host, port, user, password)
        self._read_growatt_form_into_params()
        s = self._settings()
        self._write_growatt_params_to_settings(s)
        s.setValue("params/emqx_host", host)
        s.setValue("params/emqx_port", port)
        s.setValue("params/emqx_user", user)
        s.setValue("params/emqx_password", password)
        s.sync()
        lan = self.p.growatt_lan_ip or "—"
        wifi = self.p.growatt_wifi_ip or "—"
        source = (
            f"Source GROTT MQTT {self.p.grott_mqtt_host}:{self.p.grott_mqtt_port}"
            if self.p.grott_mqtt_enabled and self.p.grott_mqtt_host
            else "Source Growatt API"
        )
        self.dash.set_status(
            f"Growatt local settings saved "
            f"(LAN {lan}, Wi‑Fi {wifi}, web port {self.p.growatt_local_port}, "
            f"EMQX {host}:{port}, {source})."
        )
        if hasattr(self.dash, "growatt_tab"):
            self.dash.growatt_tab.apply_grott_settings()
        if hasattr(self.dash, "connectivity_tab"):
            self.dash.connectivity_tab.refresh_status(test_db=False)

    def _save_grott_mqtt_login(self):
        """Persist Grott MQTT host, port, topic, and login.

        Does not copy the EMQX row over these fields — that overwrite belongs
        to Save / Apply on the EMQX row, not to a Grott-only login edit.
        """
        self.p.grott_mqtt_host = self.ed_grott_host.text().strip()
        self.p.grott_mqtt_port = int(self.sp_grott_port.value())
        self.p.grott_mqtt_user = self.ed_grott_user.text().strip()
        self.p.grott_mqtt_password = self.ed_grott_pass.text()
        topic = self.ed_grott_topic.text().strip() or "energy/growatt"
        self.p.grott_mqtt_topic = topic
        self.ed_grott_topic.setText(topic)
        s = self._settings()
        s.setValue("params/grott_mqtt_host", self.p.grott_mqtt_host)
        s.setValue("params/grott_mqtt_port", int(self.p.grott_mqtt_port))
        s.setValue("params/grott_mqtt_user", self.p.grott_mqtt_user)
        s.setValue("params/grott_mqtt_password", self.p.grott_mqtt_password)
        s.setValue("params/grott_mqtt_topic", self.p.grott_mqtt_topic)
        s.sync()
        if hasattr(self.dash, "growatt_tab"):
            self.dash.growatt_tab.apply_grott_settings()
        if hasattr(self.dash, "connectivity_tab"):
            self.dash.connectivity_tab.refresh_status(test_db=False)
        user = self.p.grott_mqtt_user
        cred = f", user {user}" if user else ""
        self.dash.set_status(
            f"Grott MQTT login saved "
            f"({self.p.grott_mqtt_host}:{self.p.grott_mqtt_port}{cred})."
        )

    def _save_emqx_credentials(self):
        """Persist EMQX and push the same broker into Grott + Tasmota MQTT."""
        host, port, user, password = self._emqx_form_broker()
        s = self._settings()
        self._push_broker_to_grott_tasmota(host, port, user, password, s=s)
        s.sync()
        if hasattr(self.dash, "growatt_tab"):
            self.dash.growatt_tab.apply_grott_settings()
        if hasattr(self.dash, "connectivity_tab"):
            self.dash.connectivity_tab.refresh_status(test_db=False)
        cred = f", user {user}" if user else ", anonymous"
        self.dash.set_status(
            f"EMQX saved and applied to Grott + Tasmota MQTT ({host}:{port}{cred})."
        )

    def _arm_link_cb(self, key: str, on_done) -> None:
        cbs = getattr(self, "_link_test_cbs", None)
        if cbs is None:
            self._link_test_cbs = cbs = {}
        if callable(on_done):
            cbs[key] = on_done
        else:
            cbs.pop(key, None)

    def _report_link_test(self, key, ok, msg, *, title, status=None) -> bool:
        """Store the last Test result and tell an open login panel, if any.

        Returns True when a panel callback handled the result (no message box).
        """
        from energy_dashboard.dialogs.component_login import record_link_test
        text = str(msg or "")
        record_link_test(key, bool(ok), text)
        cb = getattr(self, "_link_test_cbs", {}).pop(key, None)
        if status:
            self.dash.set_status(status)
        elif ok:
            self.dash.set_status(f"{title} OK — {text}")
        else:
            self.dash.set_status(f"{title} failed — {text}")
        if callable(cb):
            try:
                cb(bool(ok), text)
            except RuntimeError:
                pass
            return True
        return False

    def _test_emqx_connection(self, on_done=None):
        self._arm_link_cb("emqx", on_done)
        host, port, user, password = self._emqx_form_broker()
        if not host:
            handled = self._report_link_test(
                "emqx", False, "Enter the EMQX host first.", title="EMQX",
            )
            if not handled:
                QMessageBox.information(self, "EMQX", "Enter the EMQX host first.")
            return
        self.btn_test_emqx.setEnabled(False)
        self._set_growatt_local_status(None, f"Testing EMQX MQTT at {host}:{port}...")
        threading.Thread(
            target=self._test_emqx_thread,
            args=(host, port, user, password),
            daemon=True,
        ).start()

    def _test_emqx_thread(self, host, port, user, password):
        try:
            ok, msg = test_tasmota_mqtt_connection(
                host, port, username=user, password=password,
            )
            self._inv.invoke(lambda o=ok, m=msg: self._finish_emqx_test(o, m))
        except Exception as e:
            self._inv.invoke(
                lambda err=str(e): self._finish_emqx_test(
                    False, f"EMQX test failed unexpectedly:\n{err}",
                )
            )

    def _finish_emqx_test(self, ok, msg):
        self.btn_test_emqx.setEnabled(True)
        self._set_growatt_local_status(bool(ok), msg)
        title = "EMQX test"
        handled = self._report_link_test(
            "emqx",
            bool(ok),
            msg,
            title=title,
            status=(f"EMQX OK — {msg}" if ok else f"EMQX failed — {msg}"),
        )
        if handled:
            return
        if ok:
            QMessageBox.information(self, title, msg)
        else:
            QMessageBox.warning(self, title, msg)

    def _apply_emqx_route(self):
        host, port, user, password = self._emqx_form_broker()
        s = self._settings()
        self._push_broker_to_grott_tasmota(host, port, user, password, s=s)
        s.sync()

        if hasattr(self.dash, "growatt_tab"):
            self.dash.growatt_tab.apply_grott_settings()
        if hasattr(self.dash, "connectivity_tab"):
            self.dash.connectivity_tab.refresh_status(test_db=False)
        cred = f", user {user}" if user else ", anonymous"
        self.dash.set_status(
            f"EMQX routing applied ({host}:{port}{cred}) to Grott MQTT + Tasmota MQTT."
        )

    def _open_growatt_web_ui(self):
        targets = self._growatt_web_targets()
        if not targets:
            QMessageBox.information(
                self, "Growatt",
                "Enter a LAN or Wi‑Fi IP address / hostname first.",
            )
            return
        label, host, user, pwd = targets[0]
        port = int(self.sp_growatt_port.value())
        url = self._growatt_web_url(host, port, user, pwd)
        from energy_dashboard.dialogs.map_picker import _open_http_url
        _open_http_url(
            url,
            parent=self,
            title=f"Growatt web UI ({label})",
        )

    def _test_growatt_http_connection(self, on_done=None):
        self._arm_link_cb("webui", on_done)
        targets = self._growatt_web_targets()
        if not targets:
            self._set_growatt_local_status(False, "No LAN or WiFi address configured.")
            msg = "Enter a LAN or Wi‑Fi IP address / hostname first."
            handled = self._report_link_test("webui", False, msg, title="Growatt")
            if not handled:
                QMessageBox.information(self, "Growatt", msg)
            return
        http_port = int(self.sp_growatt_port.value())
        self._set_growatt_local_status(None, "Testing Growatt web UI TCP connectivity...")
        self._btn_test_growatt_http.setEnabled(False)
        threading.Thread(
            target=self._test_growatt_http_thread,
            args=(targets, http_port),
            daemon=True,
        ).start()

    def _test_growatt_http_thread(self, targets, http_port):
        try:
            import socket
            lines = []
            any_ok = False
            for label, host, _user, _pwd in targets:
                try:
                    with socket.create_connection((host, http_port), timeout=4.0):
                        pass
                    any_ok = True
                    lines.append(
                        f"{label}: reachable at {host}:{http_port} (TCP connection opened)."
                    )
                except OSError as e:
                    lines.append(
                        f"{label}: could not open TCP to {host}:{http_port} — {e}"
                    )
            msg = "\n".join(lines)
            self._inv.invoke(lambda ok=any_ok, m=msg: self._finish_growatt_http_test(m, ok=ok))
        except Exception as e:
            self._inv.invoke(
                lambda err=str(e): self._finish_growatt_http_test(
                    f"Web UI test failed unexpectedly:\n{err}", error=True
                )
            )

    def _finish_growatt_http_test(self, msg, error=False, ok=False):
        self._btn_test_growatt_http.setEnabled(True)
        connected = bool(ok) and not error
        self._set_growatt_local_status(connected, msg)
        title = "Growatt — web UI test"
        handled = self._report_link_test("webui", connected, msg, title=title)
        if handled:
            return
        if error:
            QMessageBox.warning(self, title, msg)
        else:
            QMessageBox.information(self, title, msg)

    def _test_grott_mqtt_connection(self, on_done=None):
        self._arm_link_cb("grott", on_done)
        self._read_growatt_form_into_params()
        if not self.p.grott_mqtt_host:
            msg = "Enter the MQTT broker host first."
            handled = self._report_link_test("grott", False, msg, title="Grott MQTT")
            if not handled:
                QMessageBox.information(self, "Grott MQTT", msg)
            return
        self._btn_test_grott_mqtt.setEnabled(False)
        threading.Thread(
            target=self._test_grott_mqtt_thread,
            args=(
                self.p.grott_mqtt_host,
                int(self.p.grott_mqtt_port),
                self.p.grott_mqtt_user,
                self.p.grott_mqtt_password,
                self.p.grott_mqtt_topic or "energy/growatt",
            ),
            daemon=True,
        ).start()

    def _test_grott_mqtt_thread(self, host, port, user, password, topic):
        try:
            ok, msg = test_grott_mqtt_connection(
                host,
                port,
                username=user,
                password=password,
                topic=topic,
            )
            self._inv.invoke(lambda o=ok, m=msg: self._finish_grott_mqtt_test(o, m))
        except Exception as e:
            self._inv.invoke(
                lambda err=str(e): self._finish_grott_mqtt_test(
                    False, f"Grott MQTT test failed unexpectedly:\n{err}",
                )
            )

    def _finish_grott_mqtt_test(self, ok, msg):
        self._btn_test_grott_mqtt.setEnabled(True)
        title = "Grott MQTT test"
        handled = self._report_link_test(
            "grott",
            bool(ok),
            msg,
            title=title,
            status=(f"Grott MQTT OK — {msg}" if ok else f"Grott MQTT failed — {msg}"),
        )
        if handled:
            return
        if ok:
            QMessageBox.information(self, title, msg)
        else:
            QMessageBox.warning(self, title, msg)

    def _test_growatt_modbus_connection(self, *, quiet: bool = False, on_done=None):
        mode = self.cb_growatt_modbus.currentData() or "off"
        host = (
            self.ed_growatt_lan_ip.text().strip()
            or self.ed_growatt_wifi_ip.text().strip()
        )
        tcp_port = int(self.sp_growatt_modbus_tcp.value())
        serial_path = self.ed_growatt_modbus_serial.text().strip()
        baud = int(self.sp_growatt_modbus_baud.value())
        unit = int(self.sp_growatt_modbus_unit.value())
        m = (mode or "off").lower()
        if not quiet:
            self._arm_link_cb("modbus", on_done)

        def _modbus_blocked(text: str) -> None:
            if quiet:
                return
            handled = self._report_link_test("modbus", False, text, title="Growatt")
            if not handled:
                QMessageBox.information(self, "Growatt", text)

        if m == "off":
            self._set_growatt_modbus_status(False, "Local Modbus check is disabled.")
            _modbus_blocked(
                "Choose Modbus TCP, RTU over TCP, or USB RTU under “Local Modbus check” first."
            )
            return
        if m in ("tcp", "tcp_rtu") and not host:
            self._set_growatt_modbus_status(
                False, "No LAN or WiFi address configured for Modbus TCP."
            )
            _modbus_blocked("Enter the RS485–Ethernet (or ShineWiFi) LAN IP above.")
            return
        if m == "serial" and not serial_path:
            self._set_growatt_modbus_status(
                False, "No serial device path configured for Modbus RTU."
            )
            _modbus_blocked(
                "Enter the serial device path (e.g. /dev/ttyUSB0) for Modbus RTU."
            )
            return
        self._set_growatt_modbus_status(None, "Testing Growatt Modbus connectivity...")
        self._btn_test_growatt_modbus.setEnabled(False)
        self._modbus_test_token += 1
        token = self._modbus_test_token
        QTimer.singleShot(
            18000, lambda t=token, q=quiet: self._modbus_test_watchdog(t, quiet=q),
        )
        threading.Thread(
            target=self._test_growatt_modbus_thread,
            args=(m, host, tcp_port, serial_path, baud, unit, token, quiet),
            daemon=True,
        ).start()

    def _modbus_test_watchdog(self, token: int, quiet: bool = True) -> None:
        if token != self._modbus_test_token:
            return
        if self._btn_test_growatt_modbus.isEnabled():
            return
        self._finish_growatt_modbus_test(
            "Modbus test timed out after 18s — no reply from the gateway/inverter. "
            "If the USR box is still in Transparent Mode, switch it to "
            "Modbus TCP<=>Modbus RTU and use port 502, or keep RTU over TCP on 8899 "
            "with UART 9600 8N1 and RFC2217 off.",
            error=True,
            token=token,
            quiet=quiet,
        )

    def _test_growatt_modbus_thread(
        self, mode, host, tcp_port, serial_path, baud, unit, token=0, quiet=False
    ):
        try:
            r = _growatt_modbus_probe_sync(mode, host, tcp_port, serial_path, baud, unit)
            st = r.get("state_text", "—")
            det = r.get("detail", "")
            msg = f"Local Modbus ({mode}): {st}\n\n{det}"
            ok = r.get("state_key") == "ok"
            self._inv.invoke(
                lambda o=ok, m=msg, t=token, q=quiet: self._finish_growatt_modbus_test(
                    m, ok=o, token=t, quiet=q
                )
            )
        except Exception as e:
            self._inv.invoke(
                lambda err=str(e), t=token, q=quiet: self._finish_growatt_modbus_test(
                    f"Modbus test failed unexpectedly:\n{err}",
                    error=True,
                    token=t,
                    quiet=q,
                )
            )

    def _finish_growatt_modbus_test(
        self, msg, error=False, ok=False, token=None, quiet=False
    ):
        if token is not None and token != self._modbus_test_token:
            return
        self._modbus_test_token += 1
        self._btn_test_growatt_modbus.setEnabled(True)
        connected = bool(ok) and not error
        self._set_growatt_modbus_status(connected, msg)
        title = "Growatt — Modbus test"
        status = "Modbus Connected" if connected else "Modbus Disconnected"
        if quiet:
            self.dash.set_status(status)
            return
        handled = self._report_link_test(
            "modbus", connected, msg, title=title, status=status,
        )
        if handled:
            return
        if error or not ok:
            QMessageBox.warning(self, title, msg)
        else:
            QMessageBox.information(self, title, msg)

    # ---- Database export helpers ----

    def _detect_coral_tpu(self):
        self.coral_status_label.setText("Scanning…")
        self.coral_status_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        threading.Thread(target=self._detect_coral_thread, daemon=True).start()

    def _detect_coral_thread(self):
        found = False
        detail = ""
        try:
            import subprocess
            result = subprocess.run(
                ["lsusb"], capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                lid = line.lower()
                if "1a6e:089a" in lid or "18d1:9302" in lid or "google" in lid and "coral" in lid:
                    found = True
                    detail = line.strip()
                    break
            if not found:
                try:
                    from pathlib import Path
                    apex = Path("/dev/apex_0")
                    if apex.exists():
                        found = True
                        detail = "/dev/apex_0 present (PCIe Coral)"
                except Exception:
                    pass
        except FileNotFoundError:
            detail = "lsusb not available"
        except Exception as e:
            detail = str(e)

        if found:
            self._inv.invoke(lambda: self._show_coral_result(True, detail))
        else:
            msg = detail or "No Coral TPU detected"
            self._inv.invoke(lambda m=msg: self._show_coral_result(False, m))

    def _show_coral_result(self, found, detail):
        if found:
            self.coral_status_label.setText(f"✓ Found: {detail}")
            self.coral_status_label.setStyleSheet("color: #a6e3a1; font-size: 11px;")
        else:
            self.coral_status_label.setText(f"✗ {detail}")
            self.coral_status_label.setStyleSheet("color: #f38ba8; font-size: 11px;")

    def _browse_sqlite(self):
        path, _ = QFileDialog.getSaveFileName(self, "SQLite database file",
                                              self.ed_sqlite_path.text(),
                                              "SQLite (*.db *.sqlite);;All (*)")
        if path:
            self.ed_sqlite_path.setText(path)

    def _push_db_config_to_logger(self, backend=None):
        dl = getattr(self.dash, 'data_logger', None)
        if dl is None:
            return
        scoped = backend in ("sqlite", "mysql", "pg")
        dl.sqlite_enabled = (backend == "sqlite") if scoped else self.chk_sqlite.isChecked()
        dl.sqlite_path = self.ed_sqlite_path.text().strip() or str(Path.home() / "energy_dashboard.db")
        dl.mysql_enabled = (backend == "mysql") if scoped else self.chk_mysql.isChecked()
        dl.mysql_host = self.ed_mysql_host.text().strip() or "localhost"
        dl.mysql_port = self.ed_mysql_port.value()
        dl.mysql_db = self.ed_mysql_db.text().strip() or "energy"
        dl.mysql_user = self.ed_mysql_user.text().strip()
        dl.mysql_pass = self.ed_mysql_pass.text()
        dl.pg_enabled = (backend == "pg") if scoped else self.chk_pg.isChecked()
        dl.pg_host = self.ed_pg_host.text().strip() or "localhost"
        dl.pg_port = self.ed_pg_port.value()
        dl.pg_db = self.ed_pg_db.text().strip() or "powermon"
        dl.pg_user = self.ed_pg_user.text().strip()
        dl.pg_pass = self.ed_pg_pass.text()
        dl.reconfigure()
        bar = getattr(self.dash, "system_status", None)
        if bar is not None:
            try:
                bar.refresh_db_now()
            except Exception:
                pass

    def _save_db_config(self, backend=None):
        s = self._settings()
        s.setValue("db/sqlite_enabled", self.chk_sqlite.isChecked())
        s.setValue("db/sqlite_path", self.ed_sqlite_path.text().strip())
        s.setValue("db/mysql_enabled", self.chk_mysql.isChecked())
        s.setValue("db/mysql_host", self.ed_mysql_host.text().strip())
        s.setValue("db/mysql_port", self.ed_mysql_port.value())
        s.setValue("db/mysql_db", self.ed_mysql_db.text().strip())
        s.setValue("db/mysql_user", self.ed_mysql_user.text().strip())
        s.setValue("db/mysql_pass", self.ed_mysql_pass.text())
        s.setValue("db/pg_enabled", self.chk_pg.isChecked())
        s.setValue("db/pg_host", self.ed_pg_host.text().strip())
        s.setValue("db/pg_port", self.ed_pg_port.value())
        s.setValue("db/pg_db", self.ed_pg_db.text().strip())
        s.setValue("db/pg_user", self.ed_pg_user.text().strip())
        s.setValue("db/pg_pass", self.ed_pg_pass.text())
        self._push_db_config_to_logger()
        self._probe_db_seen_async(backend)
        name = self._db_backend_display_name(backend)
        if name:
            self.dash.set_status(f"{name} database config saved and logger reconfigured.")
        else:
            self.dash.set_status("Database config saved and logger reconfigured.")

    def _test_db_connections(self, backend=None, on_done=None):
        if on_done is not None and backend:
            self._arm_link_cb(backend, on_done)
        self._probe_db_seen_async(backend, user_test=(backend, on_done))

    def _set_db_setup_buttons_enabled(self, enabled: bool):
        for btn in getattr(self, "_db_setup_buttons", []):
            btn.setEnabled(enabled)

    def _open_ring_buffers_dialog(self, backend=None):
        ct = getattr(self.dash, "connectivity_tab", None)
        if ct is None:
            QMessageBox.information(
                self,
                "Ring buffers",
                "Connectivity Status tab is not available.",
            )
            return
        ct.open_ring_buffers_dialog("database" if backend in ("sqlite", "mysql", "pg", None) else backend)

    def _setup_database(self, backend=None):
        if backend is None and not (self.chk_sqlite.isChecked() or self.chk_mysql.isChecked() or self.chk_pg.isChecked()):
            self.db_status_label.setText("Enable SQLite, MySQL, or PostgreSQL (checkbox), then Setup Database")
            self.db_status_label.setStyleSheet("color: #fab387; font-size: 11px;")
            return
        cap = {
            'sqlite': backend == "sqlite" if backend else self.chk_sqlite.isChecked(),
            'sqlite_path': self.ed_sqlite_path.text().strip(),
            'mysql': backend == "mysql" if backend else self.chk_mysql.isChecked(),
            'mysql_host': self.ed_mysql_host.text().strip(),
            'mysql_port': self.ed_mysql_port.value(),
            'mysql_user': self.ed_mysql_user.text().strip(),
            'mysql_pass': self.ed_mysql_pass.text(),
            'mysql_db': self.ed_mysql_db.text().strip(),
            'pg': backend == "pg" if backend else self.chk_pg.isChecked(),
            'pg_host': self.ed_pg_host.text().strip(),
            'pg_port': self.ed_pg_port.value(),
            'pg_user': self.ed_pg_user.text().strip(),
            'pg_pass': self.ed_pg_pass.text(),
            'pg_db': self.ed_pg_db.text().strip(),
            'backend': backend,
        }
        self._set_db_setup_buttons_enabled(False)
        self.db_status_label.setText("Setting up…")
        self.db_status_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        name = self._db_backend_display_name(backend)
        self.dash.set_status(f"Setting up {name} database..." if name else "Setting up database(s)...")
        threading.Thread(target=self._setup_database_thread, args=(cap,), daemon=True).start()

    def _setup_database_thread(self, cap):
        lines = []
        all_ok = True
        if cap['sqlite']:
            ok, msg = setup_sqlite_schema(cap['sqlite_path'])
            lines.append(msg)
            all_ok = all_ok and ok
        if cap['mysql']:
            ok, msg = setup_mysql_schema(
                cap['mysql_host'], cap['mysql_port'],
                cap['mysql_user'], cap['mysql_pass'],
                cap['mysql_db'] or 'energy',
            )
            lines.append(msg)
            all_ok = all_ok and ok
        if cap['pg']:
            lines.append(
                "PostgreSQL: this login does not create tables. "
                "Run the CREATE SQL on the right by hand as the database owner."
            )
        self._inv.invoke(lambda m=lines, a=all_ok: self._setup_database_done(m, a))

    def _setup_database_done(self, lines, all_ok):
        self._set_db_setup_buttons_enabled(True)
        self.db_status_label.setText(" | ".join(lines))
        self.db_status_label.setStyleSheet(
            f"color: {'#a6e3a1' if all_ok else '#f38ba8'}; font-size: 11px;"
        )
        dl = getattr(self.dash, 'data_logger', None)
        if dl:
            dl.reconfigure()
        bar = getattr(self.dash, "system_status", None)
        if bar is not None:
            try:
                bar.refresh_db_now()
            except Exception:
                pass
        self.dash.set_status(
            "Database setup complete." if all_ok else "Database setup finished with one or more errors."
        )
        self._probe_db_seen_async()

    def load_db_config_from_settings(self):
        s = self._settings()
        if s.contains("db/sqlite_enabled"):
            self.chk_sqlite.setChecked(s.value("db/sqlite_enabled", False, type=bool))
        if s.contains("db/sqlite_path"):
            self.ed_sqlite_path.setText(s.value("db/sqlite_path", ""))
        if s.contains("db/mysql_enabled"):
            self.chk_mysql.setChecked(s.value("db/mysql_enabled", False, type=bool))
        if s.contains("db/mysql_host"):
            self.ed_mysql_host.setText(s.value("db/mysql_host", "localhost"))
        if s.contains("db/mysql_port"):
            self.ed_mysql_port.setValue(int(s.value("db/mysql_port", 3306)))
        if s.contains("db/mysql_db"):
            self.ed_mysql_db.setText(s.value("db/mysql_db", "energy"))
        if s.contains("db/mysql_user"):
            self.ed_mysql_user.setText(s.value("db/mysql_user", ""))
        if s.contains("db/mysql_pass"):
            self.ed_mysql_pass.setText(s.value("db/mysql_pass", ""))
        if s.contains("db/pg_enabled"):
            self.chk_pg.setChecked(s.value("db/pg_enabled", False, type=bool))
        if s.contains("db/pg_host"):
            self.ed_pg_host.setText(s.value("db/pg_host", "localhost"))
        if s.contains("db/pg_port"):
            self.ed_pg_port.setValue(int(s.value("db/pg_port", 5432)))
        if s.contains("db/pg_db"):
            self.ed_pg_db.setText(s.value("db/pg_db", "powermon"))
        if s.contains("db/pg_user"):
            self.ed_pg_user.setText(s.value("db/pg_user", ""))
        if s.contains("db/pg_pass"):
            self.ed_pg_pass.setText(s.value("db/pg_pass", ""))
        self._push_db_config_to_logger()
        self._refresh_db_seen_off_rows()
        # Growatt LAN/Modbus/EMQX, battery, solar, etc. live in the same Setup
        # tab — always reload them with DB config so Save actually sticks across
        # restarts (previously only loaded on a DB-probe error path).
        self.load_battery_solar_from_settings()

    def _apply_all(self):
        self.p.import_flat_pence = self.sp_import.value()
        self.p.export_flat_pence = self.sp_export.value()
        self.p.analytics_efficiency_pct = self.sp_eff.value()
        self.p.analytics_max_charge_kw = self.sp_chg.value()
        self.p.analytics_battery_cost_gbp = self.sp_bat_cost.value()
        self.p.agile_product = self.ed_agile_prod.text().strip()
        self.p.agile_tariff = self.ed_agile_tariff.text().strip()
        self.p.agile_export_tariff = self.ed_agile_export_tariff.text().strip()
        self.p.battery_capacity_kwh = self.sp_cap.value()
        self.p.battery_low_soc_threshold_pct = float(self.sp_soc_thr.value())

        self._normalize_solar_coord_edit(self.ed_lat)
        self._normalize_solar_coord_edit(self.ed_lon)
        self.p.solar_lat = self.ed_lat.text().strip()
        self.p.solar_lon = self.ed_lon.text().strip()
        self.p.solar_tilt = self.ed_tilt.text().strip()
        self.p.solar_azimuth = self.ed_azimuth.text().strip()
        self.p.solar_kwp = self.ed_kwp.text().strip()

        self.dash.octopus_tab.recalc_estimated_cost()
        self.dash.analytics_tab.apply_from_app_params()
        self.dash.battery_tab.apply_from_app_params()
        self.dash.forecasts_tab.product_edit.setText(self.p.agile_product)
        self.dash.forecasts_tab.tariff_edit.setText(self.p.agile_tariff)
        self.dash.forecasts_tab.export_tariff_edit.setText(self.p.agile_export_tariff)
        ft = self.dash.forecasts_tab
        ft.solar_edits['lat'].setText(self.p.solar_lat)
        ft.solar_edits['lon'].setText(self.p.solar_lon)
        ft.solar_edits['tilt'].setText(self.p.solar_tilt)
        ft.solar_edits['azimuth'].setText(self.p.solar_azimuth)
        ft.solar_edits['kwp'].setText(self.p.solar_kwp)
        self.p.auto_refresh_seconds = int(self.sp_refresh.value())
        self.p.auto_refresh_enabled = self.chk_auto_refresh.isChecked()
        self._read_growatt_form_into_params()
        self.dash.apply_auto_refresh_from_params(kick=True)
        self.dash.set_status("Parameters applied to all tabs.")
        if hasattr(self.dash, "connectivity_tab"):
            self.dash.connectivity_tab.refresh_status(test_db=False)


# ==================== DATABASE VIEWER TAB ====================


__all__ = [n for n in globals() if not n.startswith('__')]
