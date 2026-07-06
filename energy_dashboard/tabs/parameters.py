"""
Energy Dashboard — `tabs/parameters.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.dialogs.about_history import AboutDialog, HistoryDialog
from energy_dashboard.db.connect_probe import (
    check_mysql_database_exists,
    check_postgresql_database_exists,
    check_sqlite_file_exists,
    format_probe_summary,
    format_probe_tooltip,
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
_PARAMS_DB_STATUS_MIN_W = 300
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
    status_align_lbl: QLabel,
    seen_alignments: list | None = None,
) -> None:
    """Checkbox vertically centred beside host/port/db/user/pass grid."""
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
    seen_wrap = QWidget()
    seen_row = QHBoxLayout(seen_wrap)
    seen_row.setContentsMargins(0, 0, 0, 0)
    seen_row.setSpacing(0)
    seen_spacer = QWidget()
    seen_spacer.setFixedWidth(0)
    seen_spacer.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
    seen_row.addWidget(seen_spacer)
    seen_row.addWidget(status_panel)
    section.addWidget(
        seen_wrap,
        0,
        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
    )
    section.addStretch()
    if seen_alignments is not None:
        seen_alignments.append((seen_spacer, status_align_lbl, section))
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
        setup_btn.setToolTip(
            f"Create/upgrade the {label} database schema (CREATE IF NOT EXISTS)"
        )
        setup_btn.clicked.connect(lambda _checked=False, b=backend: self._setup_database(b))
        row.addWidget(setup_btn)
        self._db_setup_buttons.append(setup_btn)

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
            "Start or restart the boot service (energy-collector). "
            "Needs sudo/pkexec when installed system-wide."
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
            "<b>Growatt Live Status</b>, <b>Octopus Energy Data</b>, and "
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
        _toggleable = [(k, t) for (k, _a, t) in _MAIN_TAB_BAR_REGISTRY if k is not None]
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
        _params_grid_add_pairs(g2_grid, 0, [
            ("Round-trip efficiency %:", self.sp_eff),
            ("Max charge kW:", self.sp_chg),
            ("Extra battery unit cost (£):", self.sp_bat_cost),
        ])
        _params_add_field_grid(g2, g2_grid)

        # --- Agile product/tariff (historical price fetch in Analytics + Forecasts tab defaults) ---
        g3 = add_group("Agile product / tariff (Analytics historical prices + Forecasts)")
        self.ed_agile_prod = QLineEdit(self.p.agile_product)
        self.ed_agile_prod.setMinimumWidth(200)
        self.ed_agile_tariff = QLineEdit(self.p.agile_tariff)
        self.ed_agile_tariff.setMinimumWidth(260)
        self.ed_agile_export_tariff = QLineEdit(self.p.agile_export_tariff)
        self.ed_agile_export_tariff.setMinimumWidth(280)
        self.ed_agile_export_tariff.setToolTip(
            "Octopus tariff code for half-hourly export (outgoing) rates — Forecasts chart"
        )
        g3_grid = _params_make_field_grid()
        _params_grid_add_pairs(g3_grid, 0, [
            ("Product code:", self.ed_agile_prod),
            ("Tariff code:", self.ed_agile_tariff),
        ])
        _agile_align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        g3_grid.addWidget(
            _params_field_label("Export Tariff:"),
            1,
            _params_label_col(0),
            _agile_align,
        )
        g3_grid.addWidget(
            self.ed_agile_export_tariff,
            1,
            _params_field_col(0),
            1,
            _PARAMS_GRID_SPAN - _params_field_col(0),
            _agile_align,
        )
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
        _params_grid_add_pairs(g4_grid, 0, [
            ("Capacity (kWh):", self.sp_cap),
            ("Low SOC threshold %:", self.sp_soc_thr),
        ])
        bat_btn_row = QHBoxLayout()
        bat_btn_row.setContentsMargins(0, 0, 0, 0)
        bat_btn_row.addSpacing(_SETUP_INFO_SPIN_BTN_GAP)
        bat_btn_row.addWidget(save_bat_btn)
        bat_btn_row.addStretch()
        _bat_btn_col = _params_field_col(1) + 1
        g4_grid.addLayout(bat_btn_row, 0, _bat_btn_col, 1, _PARAMS_GRID_SPAN + 1 - _bat_btn_col)
        _params_add_field_grid(g4, g4_grid)

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
        self.ed_lat = QLineEdit(self.p.solar_lat)
        self.ed_lat.setFixedWidth(80)
        self.ed_lon = QLineEdit(self.p.solar_lon)
        self.ed_lon.setFixedWidth(80)
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
            "Apply writes this host/port into Growatt Grott MQTT and Tasmota MQTT settings."
        )
        emqx_row.addWidget(self.ed_emqx_host)
        emqx_row.addWidget(QLabel("Port:"))
        self.sp_emqx_port = QSpinBox()
        self.sp_emqx_port.setRange(1, 65535)
        self.sp_emqx_port.setValue(_EMQX_ROUTE_DEFAULT_PORT)
        self.sp_emqx_port.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.sp_emqx_port.setToolTip("EMQX MQTT port (usually 1883).")
        emqx_row.addWidget(self.sp_emqx_port)
        self.btn_apply_emqx_route = QPushButton("Apply EMQX route")
        self.btn_apply_emqx_route.setStyleSheet(_SUBTLE_BTN_QSS)
        self.btn_apply_emqx_route.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_apply_emqx_route.setFixedWidth(150)
        self.btn_apply_emqx_route.setToolTip(
            "Copy EMQX host/port to Growatt Grott MQTT and Tasmota MQTT fields, "
            "persist to QSettings, and refresh connectivity status."
        )
        self.btn_apply_emqx_route.clicked.connect(self._apply_emqx_route)
        emqx_row.addWidget(self.btn_apply_emqx_route)
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
            "Save LAN/Wi‑Fi addresses, web UI logins, HTTP port, and Modbus probe settings to disk"
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
        self.cb_growatt_modbus.addItem("Modbus TCP (LAN)", "tcp")
        self.cb_growatt_modbus.addItem("Modbus RTU (RS485 serial)", "serial")
        self.cb_growatt_modbus.setToolTip(
            "Optional health-check on Connectivity Status. TCP uses the LAN IP "
            "(or Wi‑Fi IP if LAN is empty) + Modbus port (often 502). "
            "RTU uses a USB–RS485 adapter device path. Requires: pip install pymodbus"
        )
        self.cb_growatt_modbus.currentIndexChanged.connect(self._update_growatt_modbus_controls)
        self.sp_growatt_modbus_tcp = QSpinBox()
        self.sp_growatt_modbus_tcp.setRange(1, 65535)
        self.sp_growatt_modbus_tcp.setValue(int(self.p.growatt_modbus_tcp_port))
        self.sp_growatt_modbus_tcp.setToolTip("Modbus TCP port (default 502)")
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
        _params_grid_add_pairs(mbus_grid, 1, [
            ("TCP port:", self.sp_growatt_modbus_tcp),
            ("Serial device:", self.ed_growatt_modbus_serial),
        ])
        _params_grid_add_pairs(mbus_grid, 2, [
            ("Baud:", self.sp_growatt_modbus_baud),
            ("Unit ID:", self.sp_growatt_modbus_unit),
        ])
        self._btn_test_growatt_modbus = QPushButton("Test Modbus")
        self._btn_test_growatt_modbus.setToolTip(
            "Run the same Modbus read probe as Connectivity Status — "
            "TCP uses the LAN IP (or Wi‑Fi IP if LAN is empty); RTU uses the serial device. "
            "Uses the values currently in this form."
        )
        self._btn_test_growatt_modbus.clicked.connect(self._test_growatt_modbus_connection)
        mbus_btn_row = QHBoxLayout()
        mbus_btn_row.setContentsMargins(0, 0, 0, 0)
        mbus_btn_row.setSpacing(8)
        mbus_btn_row.addSpacing(_SETUP_INFO_SPIN_BTN_GAP)
        mbus_btn_row.addWidget(self._btn_test_growatt_modbus)
        mbus_btn_row.addStretch()
        _mbus_btn_col = _params_field_col(0) + 1
        mbus_grid.addLayout(
            mbus_btn_row, 1, _mbus_btn_col, 1, _PARAMS_GRID_SPAN + 1 - _mbus_btn_col
        )
        _params_add_field_grid(g_gw, mbus_grid)
        _mbus_hint = QLabel(
            "<b>Modbus TCP (Growatt):</b> aim at the <b>ShineWiFi‑X / LAN module IP</b> "
            "(fixed IP on your LAN, same subnet as this PC). That unit bridges "
            "<b>TCP port 502</b> to the inverter over USB/RS485. "
            "Port <b>80</b> (web UI) working does <i>not</i> guarantee TCP&nbsp;502 — many "
            "dongles have no Modbus server; use <b>Modbus RTU</b> on RS485 instead."
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
        self.sp_grott_fresh.setToolTip("Maximum age in seconds before Grott data is considered stale")

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
            "Connect to the MQTT broker, subscribe to the topic, and wait briefly for a Grott JSON payload."
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
        cloud_btn_row = QHBoxLayout()
        cloud_btn_row.setContentsMargins(0, 0, 0, 0)
        cloud_btn_row.setSpacing(8)
        cloud_btn_row.addSpacing(_SETUP_INFO_SPIN_BTN_GAP)
        cloud_btn_row.addWidget(save_cloud_btn)
        cloud_btn_row.addStretch()
        cloud_grid.addLayout(
            cloud_btn_row, 2, _params_field_col(0), 1,
            _PARAMS_GRID_SPAN + 1 - _params_field_col(0),
        )
        _params_add_field_grid(g_gw, cloud_grid)

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
        ar_btn_row.addSpacing(_SETUP_INFO_SPIN_BTN_GAP)
        ar_btn_row.addWidget(save_ar_btn)
        ar_btn_row.addStretch()
        _ar_btn_col = _params_field_col(0) + 1
        ar_grid.addLayout(ar_btn_row, 0, _ar_btn_col, 1, _PARAMS_GRID_SPAN + 1 - _ar_btn_col)
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
        self._db_seen_alignments: list = []
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
        rd_sq.addLayout(sqlite_grid, 0)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_sqlite)
        rd_sq.addWidget(browse_btn, 0, vcenter)
        self.lbl_db_sqlite_found = self._make_db_status_line()
        self.lbl_db_sqlite_ok = self._make_db_status_line()
        self.lbl_db_sqlite_off = self._make_db_status_line()
        self._db_sqlite_status = self._make_db_status_panel(
            self.lbl_db_sqlite_found,
            self.lbl_db_sqlite_ok,
            self.lbl_db_sqlite_off,
        )
        rd_sq.addWidget(self._db_sqlite_status, 0, vcenter)
        rd_sq.addStretch()
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
            self.lbl_db_mysql_ok,
            self._db_seen_alignments,
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
            self.lbl_db_pg_ok,
            self._db_seen_alignments,
        )
        g_db.addLayout(self._make_db_action_row("pg"))

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
            "Use Save under Growatt inverter (local network) to persist LAN/Wi‑Fi IPs, web UI logins, HTTP port, and optional Modbus probe settings."
        )
        hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch()

        inner.setObjectName("parametersTabInner")
        # Spin chrome is app-wide (_spin_field_motif_qss); DB line edits stay local.
        inner.setStyleSheet(_setup_info_db_field_qss())
        self._align_setup_info_spins(inner)
        QTimer.singleShot(0, self._align_db_seen_labels)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def showEvent(self, event):
        super().showEvent(event)
        self._load_broker_url_from_settings()
        self._align_db_seen_labels()
        self._probe_db_seen_async()
        self._probe_service_async()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._align_db_seen_labels()

    def _align_db_seen_labels(self) -> None:
        """Line up MySQL/PostgreSQL seen/disabled labels with the SQLite one."""
        g_db = getattr(self, "_db_group", None)
        alignments = getattr(self, "_db_seen_alignments", None)
        lbl_ref = getattr(self, "lbl_db_sqlite_ok", None)
        if g_db is None or not alignments or lbl_ref is None:
            return
        g_db.ensurePolished()
        lbl_ref.ensurePolished()
        target = lbl_ref.mapTo(g_db, QPointF(0, 0)).x()
        for seen_spacer, status_lbl, _section in alignments:
            status_lbl.ensurePolished()
            current = status_lbl.mapTo(g_db, QPointF(0, 0)).x()
            seen_spacer.setFixedWidth(max(0, round(target - current)))

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

        self._align_db_seen_labels()

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

    def _test_broker_url(self):
        broker = self._broker_url_for_probe()
        self.btn_broker_test.setEnabled(False)

        def _worker():
            try:
                status = collect_collector_service_status(broker)
                http = status.get("http") or {}
                url = http.get("url") or broker
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
        _, unit, _ = pick_control_scope(status)
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
        _, unit, _ = pick_control_scope(status)
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
        _, unit, _ = pick_control_scope(status)
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
            "<code>sudo systemctl start energy-collector</code>"
            if scope == "system"
            else "<code>systemctl --user start energy-collector</code>"
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
            detail_parts.append(f"Collector error: {poll_err}")
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
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(lbl_found)
        lay.addWidget(lbl_ok)
        lay.addWidget(lbl_off)
        panel.setMinimumWidth(_PARAMS_DB_STATUS_MIN_W)
        return panel

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
                lbl_off.setText("")
                lbl_off.setToolTip("")

    def _on_db_enable_changed(self, _state=0):
        self._refresh_db_seen_off_rows()
        if any(chk.isChecked() for chk in (self.chk_sqlite, self.chk_mysql, self.chk_pg)):
            self._probe_db_seen_async()

    def _apply_db_status_found(self, name, lbl_found, found_ok, found_detail):
        if found_ok:
            self._set_db_status_line(
                lbl_found,
                "Database found",
                _DB_RAG_GREEN,
                tooltip=str(found_detail),
            )
        else:
            self._set_db_status_line(
                lbl_found,
                "Database not found",
                _DB_RAG_RED,
                tooltip=str(found_detail),
            )

    def _apply_db_status_ok(self, name, lbl_ok, conn_ok, conn_detail):
        if conn_ok and isinstance(conn_detail, dict):
            access = str(conn_detail.get("access", ""))
            summary = format_probe_summary(conn_detail)
            tooltip = format_probe_tooltip(conn_detail)
            if access.startswith("read+write"):
                self._set_db_status_line(
                    lbl_ok,
                    "Database OK",
                    _DB_RAG_GREEN,
                    tooltip=tooltip,
                )
                return True, f"{name}: OK — {summary}"
            self._set_db_status_line(
                lbl_ok,
                "Database OK (read-only)",
                _DB_RAG_AMBER,
                tooltip=tooltip,
            )
            return True, f"{name}: read-only — {summary}"
        if conn_ok:
            self._set_db_status_line(
                lbl_ok,
                "Database OK",
                _DB_RAG_GREEN,
                tooltip=str(conn_detail),
            )
            return True, f"{name}: OK ({conn_detail})"
        self._set_db_status_line(
            lbl_ok,
            "Database not OK",
            _DB_RAG_RED,
            tooltip=str(conn_detail),
        )
        return False, f"{name}: FAIL — {conn_detail}"

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
        found_results = found_results or {}
        for name, chk, lbl_found, lbl_ok, lbl_off in self._db_status_rows():
            if only_name is not None and name != only_name:
                continue
            if only_name is None and not chk.isChecked():
                continue
            any_enabled = True
            lbl_off.setText("")
            lbl_off.setToolTip("")
            if name in found_results:
                self._apply_db_status_found(
                    name, lbl_found, *found_results[name]
                )
            elif name not in results:
                self._set_db_status_line(lbl_found, "Checking…", _UI_BLUE)
            if name not in results:
                self._set_db_status_line(lbl_ok, "Checking…", _UI_BLUE)
                lbl_ok.setToolTip("")
                continue
            conn_ok, conn_detail = results[name]
            ok_part, part = self._apply_db_status_ok(name, lbl_ok, conn_ok, conn_detail)
            parts.append(part)
            if not ok_part:
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

    def _probe_db_seen_async(self, backend=None):
        only_name = self._db_backend_display_name(backend)
        self._push_db_config_to_logger(backend)
        self._refresh_db_seen_off_rows()
        for name, chk, lbl_found, lbl_ok, _lbl_off in self._db_status_rows():
            if (only_name is not None and name == only_name) or (only_name is None and chk.isChecked()):
                self._set_db_status_line(lbl_found, "Checking…", _UI_BLUE)
                self._set_db_status_line(lbl_ok, "Checking…", _UI_BLUE)
        if only_name is None and not any(chk.isChecked() for chk in (self.chk_sqlite, self.chk_mysql, self.chk_pg)):
            self._apply_db_seen_results({})
            return

        def _worker():
            dl = getattr(self.dash, 'data_logger', None)
            if dl is None:
                self._inv.invoke(lambda: self._set_db_seen_error("Logger not initialised"))
                return
            found_results = {}
            if dl.sqlite_enabled:
                found_results["SQLite"] = check_sqlite_file_exists(dl.sqlite_path)
            if dl.mysql_enabled:
                found_results["MySQL"] = check_mysql_database_exists(
                    dl.mysql_host,
                    dl.mysql_port,
                    dl.mysql_user,
                    dl.mysql_pass,
                    dl.mysql_db,
                )
            if dl.pg_enabled:
                found_results["PostgreSQL"] = check_postgresql_database_exists(
                    dl.pg_host,
                    dl.pg_port,
                    dl.pg_user,
                    dl.pg_pass,
                    dl.pg_db,
                )
            results = dl.test_connections()
            self._inv.invoke(
                lambda r=results, f=found_results, b=backend: self._finish_db_probe(r, f, b)
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_db_probe(self, results, found_results, backend=None):
        self._apply_db_seen_results(results, found_results, backend=backend)
        if backend is not None:
            # Restore the logger's real automatic-logging backend selection after
            # a one-row probe, because per-row tests operate even if the checkbox
            # is currently off.
            self._push_db_config_to_logger()

    def _set_db_seen_error(self, message):
        for _name, chk, lbl_found, lbl_ok, _lbl_off in self._db_status_rows():
            if chk.isChecked():
                self._set_db_status_line(lbl_found, "Database not found", _DB_RAG_RED, tooltip=message)
                self._set_db_status_line(lbl_ok, "Database not OK", _DB_RAG_RED, tooltip=message)
        self.db_status_label.setText(message)
        self.db_status_label.setStyleSheet(f"color: {_DB_RAG_RED}; font-size: 11px;")
        self.load_battery_solar_from_settings()

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
            self.ed_lat.setText(s.value("params/solar_lat", ""))
        if s.contains("params/solar_lon"):
            self.ed_lon.setText(s.value("params/solar_lon", ""))
        if s.contains("params/solar_tilt"):
            self.ed_tilt.setText(s.value("params/solar_tilt", ""))
        if s.contains("params/solar_azimuth"):
            self.ed_azimuth.setText(s.value("params/solar_azimuth", ""))
        if s.contains("params/solar_kwp"):
            self.ed_kwp.setText(s.value("params/solar_kwp", ""))
        if s.contains("params/growatt_local_ip"):
            legacy_ip = s.value("params/growatt_local_ip", "")
        else:
            legacy_ip = ""
        if s.contains("params/growatt_lan_ip"):
            self.p.growatt_lan_ip = s.value("params/growatt_lan_ip", "")
        else:
            self.p.growatt_lan_ip = legacy_ip
        self.ed_growatt_lan_ip.setText(self.p.growatt_lan_ip)
        if s.contains("params/growatt_wifi_ip"):
            self.p.growatt_wifi_ip = s.value("params/growatt_wifi_ip", "")
        elif legacy_ip:
            self.p.growatt_wifi_ip = legacy_ip
        else:
            self.p.growatt_wifi_ip = ""
        self.ed_growatt_wifi_ip.setText(self.p.growatt_wifi_ip)
        if s.contains("params/growatt_lan_user"):
            self.p.growatt_lan_user = s.value("params/growatt_lan_user", "")
            self.ed_growatt_lan_user.setText(self.p.growatt_lan_user)
        if s.contains("params/growatt_lan_password"):
            self.p.growatt_lan_password = s.value("params/growatt_lan_password", "")
            self.ed_growatt_lan_pass.setText(self.p.growatt_lan_password)
        if s.contains("params/growatt_wifi_user"):
            self.p.growatt_wifi_user = s.value("params/growatt_wifi_user", "")
            self.ed_growatt_wifi_user.setText(self.p.growatt_wifi_user)
        if s.contains("params/growatt_wifi_password"):
            self.p.growatt_wifi_password = s.value("params/growatt_wifi_password", "")
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
            self.p.grott_mqtt_host = s.value("params/grott_mqtt_host", "")
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
        if s.contains("params/grott_mqtt_user"):
            self.p.grott_mqtt_user = s.value("params/grott_mqtt_user", "")
            self.ed_grott_user.setText(self.p.grott_mqtt_user)
        if s.contains("params/grott_mqtt_password"):
            self.p.grott_mqtt_password = s.value("params/grott_mqtt_password", "")
            self.ed_grott_pass.setText(self.p.grott_mqtt_password)
        if s.contains("params/grott_mqtt_topic"):
            self.p.grott_mqtt_topic = s.value("params/grott_mqtt_topic", "energy/growatt")
            self.ed_grott_topic.setText(self.p.grott_mqtt_topic)
        if s.contains("params/grott_mqtt_fresh_s"):
            self.p.grott_mqtt_fresh_s = int(s.value("params/grott_mqtt_fresh_s", 120))
            self.sp_grott_fresh.setValue(self.p.grott_mqtt_fresh_s)
        if s.contains("params/growatt_local_port"):
            self.p.growatt_local_port = int(s.value("params/growatt_local_port", 80))
            self.sp_growatt_port.setValue(self.p.growatt_local_port)
        if s.contains("params/growatt_modbus_mode"):
            self.p.growatt_modbus_mode = s.value("params/growatt_modbus_mode", "off")
            idx = self.cb_growatt_modbus.findData(self.p.growatt_modbus_mode)
            if idx >= 0:
                self.cb_growatt_modbus.setCurrentIndex(idx)
        if s.contains("params/growatt_modbus_tcp_port"):
            self.p.growatt_modbus_tcp_port = int(s.value("params/growatt_modbus_tcp_port", 502))
            self.sp_growatt_modbus_tcp.setValue(self.p.growatt_modbus_tcp_port)
        if s.contains("params/growatt_modbus_serial_path"):
            self.p.growatt_modbus_serial_path = s.value("params/growatt_modbus_serial_path", "")
            self.ed_growatt_modbus_serial.setText(self.p.growatt_modbus_serial_path)
        if s.contains("params/growatt_modbus_baud"):
            self.p.growatt_modbus_baud = int(s.value("params/growatt_modbus_baud", 9600))
            self.sp_growatt_modbus_baud.setValue(self.p.growatt_modbus_baud)
        if s.contains("params/growatt_modbus_unit"):
            self.p.growatt_modbus_unit = int(s.value("params/growatt_modbus_unit", 1))
            self.sp_growatt_modbus_unit.setValue(self.p.growatt_modbus_unit)
        self._update_grott_source_controls()
        self._update_growatt_modbus_controls()
        self._read_growatt_form_into_params()
        self.p.battery_capacity_kwh = self.sp_cap.value()
        self.p.battery_low_soc_threshold_pct = float(self.sp_soc_thr.value())
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
                _log.warn(f"ParametersTab: AboutDialog failed: {e}")
            except Exception:
                pass
            QMessageBox.warning(self, "About", f"Couldn't open About dialog:\n{e}")

    def _show_history_dialog(self):
        try:
            HistoryDialog(self).exec()
        except Exception as e:
            try:
                _log.warn(f"ParametersTab: HistoryDialog failed: {e}")
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

    def _save_solar_installation(self):
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

    def _update_growatt_modbus_controls(self):
        mode = self.cb_growatt_modbus.currentData()
        if mode is None:
            mode = "off"
        tcp_on = mode == "tcp"
        ser_on = mode == "serial"
        self.sp_growatt_modbus_tcp.setEnabled(tcp_on)
        self.ed_growatt_modbus_serial.setEnabled(ser_on)
        self.sp_growatt_modbus_baud.setEnabled(ser_on)
        self.sp_growatt_modbus_unit.setEnabled(mode != "off")

    def _save_growatt_lan(self):
        self._read_growatt_form_into_params()
        s = self._settings()
        self._write_growatt_params_to_settings(s)
        s.setValue("params/emqx_host", self.ed_emqx_host.text().strip() or _EMQX_ROUTE_DEFAULT_HOST)
        s.setValue("params/emqx_port", int(self.sp_emqx_port.value()))
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
            f"(LAN {lan}, Wi‑Fi {wifi}, web port {self.p.growatt_local_port}, {source})."
        )
        if hasattr(self.dash, "growatt_tab"):
            self.dash.growatt_tab.apply_grott_settings()
        if hasattr(self.dash, "connectivity_tab"):
            self.dash.connectivity_tab.refresh_status(test_db=False)

    def _apply_emqx_route(self):
        host = self.ed_emqx_host.text().strip() or _EMQX_ROUTE_DEFAULT_HOST
        port = int(self.sp_emqx_port.value())
        self.ed_emqx_host.setText(host)

        # Setup tab (Growatt GROTT source)
        self.ed_grott_host.setText(host)
        self.sp_grott_port.setValue(port)
        self.p.grott_mqtt_host = host
        self.p.grott_mqtt_port = port

        s = self._settings()
        s.setValue("params/emqx_host", host)
        s.setValue("params/emqx_port", port)
        s.setValue("params/grott_mqtt_host", host)
        s.setValue("params/grott_mqtt_port", port)
        s.setValue("tasmota/mqtt_host", host)
        s.setValue("tasmota/mqtt_port", port)
        s.sync()

        # Keep Tasmota tab in sync immediately (if it is already constructed).
        tt = getattr(self.dash, "tasmota_tab", None)
        if tt is not None:
            if getattr(tt, "ed_mqtt_host", None) is not None:
                tt.ed_mqtt_host.setText(host)
            if getattr(tt, "sp_mqtt_port", None) is not None:
                tt.sp_mqtt_port.setValue(port)

        if hasattr(self.dash, "growatt_tab"):
            self.dash.growatt_tab.apply_grott_settings()
        if hasattr(self.dash, "connectivity_tab"):
            self.dash.connectivity_tab.refresh_status(test_db=False)
        self.dash.set_status(
            f"EMQX routing applied ({host}:{port}) to Grott MQTT + Tasmota MQTT."
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
        _open_http_url(
            url,
            parent=self,
            title=f"Growatt web UI ({label})",
        )

    def _test_growatt_http_connection(self):
        targets = self._growatt_web_targets()
        if not targets:
            self._set_growatt_local_status(False, "No LAN or WiFi address configured.")
            QMessageBox.information(
                self, "Growatt",
                "Enter a LAN or Wi‑Fi IP address / hostname first.",
            )
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
        self._set_growatt_local_status(bool(ok) and not error, msg)
        title = "Growatt — web UI test"
        if error:
            QMessageBox.warning(self, title, msg)
        else:
            QMessageBox.information(self, title, msg)

    def _test_grott_mqtt_connection(self):
        self._read_growatt_form_into_params()
        if not self.p.grott_mqtt_host:
            QMessageBox.information(
                self, "Grott MQTT",
                "Enter the MQTT broker host first.",
            )
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
        if ok:
            QMessageBox.information(self, title, msg)
            self.dash.set_status(f"Grott MQTT OK — {msg}")
        else:
            QMessageBox.warning(self, title, msg)
            self.dash.set_status(f"Grott MQTT failed — {msg}")

    def _test_growatt_modbus_connection(self):
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
        if m == "off":
            self._set_growatt_local_status(False, "Modbus probe is disabled.")
            QMessageBox.information(
                self, "Growatt",
                "Choose Modbus TCP or RTU under “Local Modbus check” first.",
            )
            return
        if m == "tcp" and not host:
            self._set_growatt_local_status(False, "No LAN or WiFi address configured for Modbus TCP.")
            QMessageBox.information(
                self, "Growatt",
                "Enter a LAN or Wi‑Fi IP address / hostname above (used for Modbus TCP).",
            )
            return
        if m == "serial" and not serial_path:
            self._set_growatt_local_status(False, "No serial device path configured for Modbus RTU.")
            QMessageBox.information(
                self, "Growatt",
                "Enter the serial device path (e.g. /dev/ttyUSB0) for Modbus RTU.",
            )
            return
        self._set_growatt_local_status(None, "Testing Growatt Modbus connectivity...")
        self._btn_test_growatt_modbus.setEnabled(False)
        threading.Thread(
            target=self._test_growatt_modbus_thread,
            args=(m, host, tcp_port, serial_path, baud, unit),
            daemon=True,
        ).start()

    def _test_growatt_modbus_thread(self, mode, host, tcp_port, serial_path, baud, unit):
        try:
            r = _growatt_modbus_probe_sync(mode, host, tcp_port, serial_path, baud, unit)
            st = r.get("state_text", "—")
            det = r.get("detail", "")
            msg = f"Local Modbus ({mode}): {st}\n\n{det}"
            ok = r.get("state_key") == "ok"
            self._inv.invoke(lambda o=ok, m=msg: self._finish_growatt_modbus_test(m, ok=o))
        except Exception as e:
            self._inv.invoke(
                lambda err=str(e): self._finish_growatt_modbus_test(
                    f"Modbus test failed unexpectedly:\n{err}", error=True
                )
            )

    def _finish_growatt_modbus_test(self, msg, error=False, ok=False):
        self._btn_test_growatt_modbus.setEnabled(True)
        self._set_growatt_local_status(bool(ok) and not error, msg)
        title = "Growatt — Modbus test"
        if error:
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

    def _test_db_connections(self, backend=None):
        self._probe_db_seen_async(backend)

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
            ok, msg = setup_postgresql_schema(
                cap['pg_host'], cap['pg_port'],
                cap['pg_user'], cap['pg_pass'],
                cap['pg_db'] or 'powermon',
            )
            lines.append(msg)
            all_ok = all_ok and ok
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
