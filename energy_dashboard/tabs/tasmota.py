"""
Energy Dashboard — `tabs/tasmota.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.config import (
    TASMOTA_HIST_Y_PRESETS,
    TASMOTA_IP_END,
    TASMOTA_IP_START,
)
from energy_dashboard.core.logging import _log
from energy_dashboard.fetch.tasmota_health import (
    TasmotaDeviceHealth,
    _log_level_label,
    fetch_tasmota_device_health,
)
from energy_dashboard.fetch.tasmota_mqtt import (
    TasmotaMqttSubscriber,
    test_tasmota_mqtt_connection,
)
from energy_dashboard.db.connect_probe import (
    format_probe_summary,
    probe_mysql,
    probe_postgresql,
    probe_sqlite,
)
from functools import partial

# Control-row field widths — use spare horizontal space without stretching the whole bar.
_TASMOTA_IP_FIELD_W = 138
_TASMOTA_BROKER_URL_MIN_W = 280
_TASMOTA_MQTT_HOST_W = 142
_TASMOTA_MQTT_TEXT_W = 118
_TASMOTA_MQTT_PREFIX_W = 142
_TASMOTA_CTRL_SPIN_W = 94
_TASMOTA_HISTORY_SLIDER_W = 210
_TASMOTA_HISTORY_LABEL_W = 52
# Power History: break lines when samples are farther apart than this (seconds).
_HISTORY_MAX_GAP_S = 90.0
# MQTT mode: background DB refetch interval so DB+live merge stays current.
_DB_HIST_REFRESH_S = 60.0
# Direct MQTT (no powermon broker): GUI DB write interval aligned with collector.
_MQTT_DB_LOG_INTERVAL_S = 30.0
# Heavy MQTT UI (table + charts). Banner/status can update every emit.
_MQTT_HEAVY_UI_INTERVAL_S = 1.0
_TASMOTA_DEVICE_TABLE_FONT_PT = 8
_TASMOTA_DEVICE_ACTION_FONT_PT = 7
# Inner padding for in-table action buttons (outer width is fixed separately).
_TASMOTA_ACTION_BTN_HPAD = 2
_TASMOTA_ACTION_BTN_VPAD = 1
# Reference metrics for fixed outer width — do not shrink buttons when display
# font/padding is reduced to prevent label clipping.
_TASMOTA_ACTION_BTN_SIZING_FONT_PT = 8
_TASMOTA_ACTION_BTN_SIZING_HPAD = 7
_TASMOTA_ACTION_BTN_SIZING_MARGIN = 6
# Extra gap between Diagnose and Toggle (in addition to the 4 px inter-button spacing).
_TASMOTA_TOGGLE_LEADING_GAP = 10
# Total vertical inset so action buttons are row height minus this (1 px top + 1 px bottom).
_TASMOTA_ACTION_ROW_GAP = 2
# Devices are split across two trees, so each column must show this many rows
# without scrolling. The trees reserve height for exactly this count.
_TASMOTA_VISIBLE_ROWS = 8
_TASMOTA_DEVICE_COL_KEY = "tasmota_devices"
# Absolute floor for a legible action button; the real minimum comes from the
# button's own sizeHint (see _init_tasmota_device_trees).
_TASMOTA_ACTION_BTN_MIN_H = 20

# Compact padding for the in-table action buttons. Uses an attribute selector
# (QPushButton[tasmotaAction="true"]) so it has higher specificity than the
# shared primary-button rule (plain "QPushButton { padding: 4px 14px; }") and
# therefore actually wins — a plain duplicate selector was being ignored, which
# left the green primary padding clipping labels like "Diagnose".
# min/max-width are injected per-row so Probe / Web UI / Diagnose / Toggle stay
# the same fixed width (state-coloured Toggle styles used to let width drift).
def _tasmota_table_action_btn_qss(width_px: int) -> str:
    w = max(1, int(width_px))
    return (
        'QPushButton[tasmotaAction="true"],'
        'QPushButton[tasmotaAction="true"]:hover,'
        'QPushButton[tasmotaAction="true"]:pressed {'
        f"  padding: {_TASMOTA_ACTION_BTN_VPAD}px {_TASMOTA_ACTION_BTN_HPAD}px;"
        "  margin: 0px;"
        f"  min-width: {w}px;"
        f"  max-width: {w}px;"
        "  font-weight: normal;"
        "}"
    )


class _TasmotaDiagnoseDialog(QDialog):
    def __init__(self, health: TasmotaDeviceHealth, parent=None):
        super().__init__(parent)
        title_ip = health.device_name or health.ip
        self.setWindowTitle(f"Device health — {title_ip}")
        self.setMinimumWidth(880)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 10)
        lay.setSpacing(8)

        head = QLabel(self._header_html(health))
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setWordWrap(True)
        lay.addWidget(head)

        cols = QHBoxLayout()
        cols.setSpacing(14)
        left_col = QVBoxLayout()
        right_col = QVBoxLayout()
        left_col.setSpacing(8)
        right_col.setSpacing(8)

        left_col.addWidget(
            self._section_box(
                "Why the dashboard shows issues",
                self._findings_html(health.findings),
            )
        )
        if health.probe_checks:
            left_col.addWidget(
                self._section_box(
                    "Live HTTP checks",
                    self._probe_table(health.probe_checks),
                )
            )

        for section_title, section_html in self._sections(health):
            box = self._section_box(section_title, section_html)
            if section_title in ("Connectivity", "WiFi strength"):
                left_col.addWidget(box)
            else:
                right_col.addWidget(box)

        left_col.addStretch(1)
        right_col.addStretch(1)
        cols.addLayout(left_col, 1)
        cols.addLayout(right_col, 1)
        lay.addLayout(cols)

        if health.errors:
            warn = QLabel(
                "<span style='color:#f38ba8;'>"
                + "<br>".join(health.errors)
                + "</span>"
            )
            warn.setTextFormat(Qt.TextFormat.RichText)
            warn.setWordWrap(True)
            lay.addWidget(warn)

        foot = QLabel(
            f"<span style='color:#6c7086;font-size:10px;'>"
            f"Fetched in {health.fetch_ms:.0f} ms · HTTP Status 0 / 3 / 4 / 5 / 6 / 11"
            f" · LoadAvg idle read (1.5 s pause)</span>"
        )
        foot.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(foot)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)
        lay.addWidget(buttons)

    @classmethod
    def _section_box(cls, title: str, html: str) -> QGroupBox:
        box = QGroupBox(title)
        body = QLabel(html)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        inner = QVBoxLayout(box)
        inner.addWidget(body)
        return box

    @staticmethod
    def _ok(ok: bool | None) -> str:
        if ok is True:
            return "<span style='color:#a6e3a1;font-weight:bold;'>OK</span>"
        if ok is False:
            return "<span style='color:#f38ba8;font-weight:bold;'>Issue</span>"
        return "<span style='color:#6c7086;'>—</span>"

    @staticmethod
    def _row(label: str, value: str, *, state: bool | None = None) -> str:
        badge = ""
        if state is not None:
            badge = f" {_TasmotaDiagnoseDialog._ok(state)}"
        val = value if value else "—"
        return (
            f"<tr><td style='color:#a6adc8;padding:2px 12px 2px 0;'>"
            f"{label}</td><td style='color:#cdd6f4;'>{val}{badge}</td></tr>"
        )

    @classmethod
    def _table(cls, rows: list[str]) -> str:
        return "<table cellspacing='0' cellpadding='0'>" + "".join(rows) + "</table>"

    @staticmethod
    def _cell(label: str, value: str, *, header: bool = False) -> str:
        if header:
            lbl_style = "color:#89b4fa;font-weight:bold;"
            val_style = "color:#cdd6f4;font-weight:bold;"
        else:
            lbl_style = "color:#a6adc8;"
            val_style = "color:#cdd6f4;"
        return (
            f"<td style='{lbl_style}padding:2px 10px 2px 0;'>{label}</td>"
            f"<td style='{val_style}padding:2px 16px 2px 0;'>{value}</td>"
        )

    @classmethod
    def _table_two_col(cls, pairs: list[tuple[str, str]]) -> str:
        """Two label/value pairs per row (four columns)."""
        rows: list[str] = []
        for i in range(0, len(pairs), 2):
            left = pairs[i]
            right = pairs[i + 1] if i + 1 < len(pairs) else ("", "")
            row = "<tr>" + cls._cell(left[0], left[1] or "—")
            if right[0]:
                row += cls._cell(right[0], right[1] or "—")
            else:
                row += "<td colspan='2'></td>"
            rows.append(row + "</tr>")
        return "<table cellspacing='0' cellpadding='0'>" + "".join(rows) + "</table>"

    @classmethod
    def _loadavg_val(cls, val: int | None) -> str:
        """Tasmota LoadAvg — loop busy % during Sleep interval; ≤75 healthy."""
        if val is None:
            return "—"
        if val <= 75:
            col = "#a6e3a1"
        elif val <= 100:
            col = "#fab387"
        else:
            col = "#f38ba8"
        return f"<span style='color:{col};font-weight:bold;'>{val}</span>"

    @classmethod
    def _header_html(cls, h: TasmotaDeviceHealth) -> str:
        name = h.device_name or h.ip
        fw = f" · {h.firmware}" if h.firmware else ""
        reach = cls._ok(h.reachable)
        return (
            f"<span style='font-size:13px;font-weight:bold;color:#cdd6f4;'>{name}</span>"
            f"<span style='color:#6c7086;'>{fw}</span><br>"
            f"<span style='color:#6c7086;font-size:11px;'>{h.ip} · HTTP {reach}</span>"
        )

    @classmethod
    def _findings_html(cls, findings: list[str]) -> str:
        if not findings:
            return (
                "<span style='color:#a6e3a1;'>No issues detected.</span>"
            )
        items = "".join(
            f"<li style='margin:5px 0;'>{line}</li>" for line in findings
        )
        return f"<ul style='margin:0;padding-left:18px;color:#cdd6f4;'>{items}</ul>"

    @classmethod
    def _probe_table(cls, checks) -> str:
        rows = []
        for c in checks:
            ms = f" · {c.ms:.0f} ms" if c.ms else ""
            rows.append(
                cls._row(c.label, f"{c.detail}{ms}", state=c.ok)
            )
        return cls._table(rows)

    @classmethod
    def _wifi_dbm_html(cls, dbm: int | None) -> str:
        if dbm is None:
            return "—"
        if dbm >= -50:
            col = "#a6e3a1"
        elif dbm >= -67:
            col = "#a6e3a1"
        elif dbm >= -80:
            col = "#fab387"
        else:
            col = "#f38ba8"
        return f"<span style='color:{col};font-weight:bold;'>{dbm} dBm</span>"

    @classmethod
    def _log_level_html(cls, level: int | None) -> str:
        if level is None:
            return "—"
        if level >= 4:
            col = "#a6e3a1"
        elif level >= 2:
            col = "#cdd6f4"
        else:
            col = "#fab387"
        return (
            f"<span style='color:{col};font-weight:bold;'>"
            f"{_log_level_label(level)}</span>"
        )

    @classmethod
    def _mem_kb_html(cls, kb: int | None, *, warn_below: int = 15) -> str:
        if kb is None:
            return "—"
        col = "#a6e3a1" if kb >= warn_below else "#f38ba8"
        return f"<span style='color:{col};font-weight:bold;'>{kb} kB</span>"

    @classmethod
    def _wifi_quality_html(cls, pct: int | None) -> str:
        if pct is None:
            return "—"
        if pct >= 80:
            col = "#a6e3a1"
        elif pct >= 50:
            col = "#fab387"
        else:
            col = "#f38ba8"
        return f"<span style='color:{col};font-weight:bold;'>{pct}%</span>"

    @classmethod
    def _sections(cls, h: TasmotaDeviceHealth):
        conn_rows = [
            cls._row("HTTP reachable", "Yes" if h.reachable else "No", state=h.reachable),
            cls._row("Hostname", h.hostname),
            cls._row("IP address", h.ip_reported or h.ip),
            cls._row("Gateway", h.gateway),
            cls._row("Uptime", h.uptime),
            cls._row("Web UI", h.webserver),
        ]
        wifi_rows = [
            cls._row("SSID", h.wifi_ssid or "—"),
            cls._row(
                "RSSI (receiver)",
                cls._wifi_dbm_html(h.wifi_rssi_dbm),
            ),
            cls._row(
                "Link quality",
                cls._wifi_quality_html(h.wifi_signal_pct),
            ),
            cls._row(
                "WiFi reconnects",
                str(h.wifi_link_count) if h.wifi_link_count is not None else "—",
            ),
            cls._row("WiFi downtime", h.wifi_downtime),
        ]
        reboot_rows = [
            cls._row("Uptime (since last boot)", h.uptime),
            cls._row("Last restart reason", h.last_restart_reason),
            cls._row(
                "Restart count",
                str(h.restart_count)
                if h.restart_count is not None
                else "not reported by firmware",
            ),
            cls._row(
                "MQTT broker reconnects",
                str(h.mqtt_reconnect_count) if h.mqtt_reconnect_count is not None else "—",
            ),
        ]
        if h.mqtt_enabled:
            mqtt_rows = [
                cls._row(
                    "Broker",
                    f"{h.mqtt_host}:{h.mqtt_port}" if h.mqtt_port else h.mqtt_host,
                ),
                cls._row(
                    "Connected now",
                    "Yes" if h.mqtt_connected else "No",
                    state=h.mqtt_connected,
                ),
                cls._row("MQTT user", h.mqtt_user or "(none)"),
                cls._row("Topic", h.mqtt_topic),
                cls._row("FullTopic template", f"<code>{h.mqtt_full_topic}</code>"),
                cls._row("Client ID template", h.mqtt_client),
                cls._row("Publishes telemetry to", f"<code>{h.mqtt_tele_topic}</code>"),
                cls._row("Publishes state to", f"<code>{h.mqtt_stat_topic}</code>"),
            ]
        else:
            mqtt_rows = [
                cls._row("MQTT", "Not configured on device", state=False),
            ]
        sched_rows = [
            cls._row("LoadAvg", cls._loadavg_val(h.cpu_load_current)),
            cls._row(
                "Sleep interval",
                f"{h.sleep_interval_ms} ms" if h.sleep_interval_ms is not None else "—",
            ),
            cls._row("SleepMode", h.sleep_mode or "—"),
            cls._row(
                "Note",
                "<span style='color:#6c7086;font-size:10px;'>"
                "LoadAvg is loop busy % (not CPU). Read after diagnose HTTP "
                "finishes; can exceed 100 if Sleep is too low.</span>",
            ),
        ]
        weblog_note = ""
        if h.web_log_boosted:
            weblog_note = (
                " · <span style='color:#6c7086;'>level 4 during diagnose</span>"
            )
        log_rows = [
            cls._row(
                "WebLog",
                cls._log_level_html(h.web_log_level) + weblog_note,
            ),
            cls._row("MqttLog", cls._log_level_html(h.mqtt_log_level)),
            cls._row("SerialLog", cls._log_level_html(h.serial_log_level)),
            cls._row("SysLog", cls._log_level_html(h.sys_log_level)),
            cls._row(
                "TelePeriod",
                f"{h.tele_period_s} s" if h.tele_period_s is not None else "—",
            ),
        ]
        if h.log_host:
            host = h.log_host
            if h.log_port:
                host = f"{host}:{h.log_port}"
            log_rows.append(cls._row("Remote syslog", host))
        mem_rows = [
            cls._row("Heap free", cls._mem_kb_html(h.heap_kb)),
            cls._row("RAM free", cls._mem_kb_html(h.heap_free_kb, warn_below=50)),
            cls._row(
                "Program size",
                f"{h.program_size_kb} kB" if h.program_size_kb is not None else "—",
            ),
            cls._row(
                "Flash size",
                f"{h.flash_size_kb} kB" if h.flash_size_kb is not None else "—",
            ),
            cls._row(
                "Program flash",
                f"{h.program_flash_size_kb} kB"
                if h.program_flash_size_kb is not None
                else "—",
            ),
            cls._row("Flash mode", h.flash_mode or "—"),
            cls._row("Flash chip ID", h.flash_chip_id or "—"),
            cls._row(
                "Stack high-water",
                str(h.stack_high_water) if h.stack_high_water is not None else "—",
            ),
        ]
        if h.mem_drivers:
            mem_rows.append(cls._row("Drivers", f"<code>{h.mem_drivers[:120]}</code>"))
        if h.mem_sensors:
            mem_rows.append(cls._row("Sensors", f"<code>{h.mem_sensors[:120]}</code>"))
        return (
            ("Connectivity", cls._table(conn_rows)),
            ("WiFi strength", cls._table(wifi_rows)),
            ("Logging & telemetry (Status 3)", cls._table(log_rows)),
            ("Memory & flash (Status 4)", cls._table(mem_rows)),
            ("Reboots", cls._table(reboot_rows)),
            ("MQTT setup (push to server)", cls._table(mqtt_rows)),
            (
                "Scheduler load (LoadAvg · Status 11)",
                cls._table(sched_rows),
            ),
        )


class TasmotaTab(QWidget):
    def __init__(self, status_callback, dashboard=None):
        super().__init__()
        self.set_status = status_callback
        self.dash = dashboard
        self._inv = Invoker(self)
        self.device_ips = ip_range(TASMOTA_IP_START, TASMOTA_IP_END)
        self.device_names = {}
        self.device_firmware = {}
        self.device_data = {}
        self.history = {}
        self._db_history = {}
        self._db_hist_link = {
            "backend": None,
            "summary": "",
            "ok": False,
            "error": "not checked",
        }
        self.fetching = False
        self.on_data_updated = None
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(30000)
        self._auto_timer.timeout.connect(self.poll_all)
        self._auto_refresh_pending = False
        self._mqtt_last_notify = 0.0
        self._mqtt_last_db_log = 0.0
        self._mqtt_last_heavy_ui = 0.0
        self._last_db_hist_fetch = 0.0
        self._db_hist_fetch_inflight = False
        self._broker_snap_cache = None  # (monotonic_ts, snapshot dict)
        self._bootstrap_then_mqtt = False
        self._mqtt = TasmotaMqttSubscriber(
            on_update=lambda: self._inv.invoke(self._apply_mqtt_snapshot),
            on_status=lambda msg: self._inv.invoke(lambda m=msg: self._set_mqtt_status(m)),
        )
        self.build_ui()

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Row 1: controls
        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("IP Range:"))
        self.ip_start_edit = QLineEdit(TASMOTA_IP_START)
        self.ip_start_edit.setFixedWidth(_TASMOTA_IP_FIELD_W)
        ctrl_row.addWidget(self.ip_start_edit)
        ctrl_row.addWidget(QLabel("to"))
        self.ip_end_edit = QLineEdit(TASMOTA_IP_END)
        self.ip_end_edit.setFixedWidth(_TASMOTA_IP_FIELD_W)
        ctrl_row.addWidget(self.ip_end_edit)
        self.save_ip_btn = QPushButton("Save")
        self.save_ip_btn.setToolTip("Save IP range; restored next time you open the dashboard")
        self.save_ip_btn.clicked.connect(self._save_ip_range)
        _apply_primary_button_style(self.save_ip_btn)
        ctrl_row.addWidget(self.save_ip_btn)
        self.poll_btn = QPushButton("Poll Now")
        self.poll_btn.clicked.connect(self.poll_all)
        _apply_primary_button_style(self.poll_btn)
        ctrl_row.addWidget(self.poll_btn)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        ctrl_row.addWidget(self.status_label)
        ctrl_row.addSpacing(20)
        self._history_minutes_steps = [
            2, 5, 10, 15, 30, 60, 120, 240, 480, 720, 1440
        ]
        self._history_default_minutes = 120
        default_history_idx = self._history_minutes_steps.index(
            self._history_default_minutes
        )
        ctrl_row.addWidget(QLabel("History:"))
        self.history_slider = QSlider(Qt.Horizontal)
        self.history_slider.setMinimum(0)
        self.history_slider.setMaximum(len(self._history_minutes_steps) - 1)
        self.history_slider.setValue(default_history_idx)
        self.history_slider.setTickPosition(QSlider.TicksBelow)
        self.history_slider.setTickInterval(1)
        self.history_slider.setFixedWidth(_TASMOTA_HISTORY_SLIDER_W)
        self.history_slider.valueChanged.connect(self._on_history_slider_changed)
        ctrl_row.addWidget(self.history_slider)
        self.history_window_label = QLabel(
            self._format_window(self._history_default_minutes)
        )
        self.history_window_label.setFixedWidth(_TASMOTA_HISTORY_LABEL_W)
        ctrl_row.addWidget(self.history_window_label)
        ctrl_row.addSpacing(20)
        # Y-axis cap on the Power History chart. 0 means "auto" — let
        # matplotlib pick. Synced bidirectionally with click-and-drag on
        # the y-axis spine of the history chart (see _on_canvas_press /
        # _motion / _release).
        ctrl_row.addWidget(QLabel("Max W (Y-axis):"))
        self.sp_max_w = QSpinBox()
        self.sp_max_w.setRange(0, 100000)
        self.sp_max_w.setSingleStep(100)
        self.sp_max_w.setSpecialValueText("auto")  # shows "auto" when value == 0
        self.sp_max_w.setValue(0)
        apply_spin_field_motif(self.sp_max_w, width=_TASMOTA_CTRL_SPIN_W)
        self.sp_max_w.setToolTip(
            "Hard cap for the Power History y-axis (Watts). 0 = auto-fit "
            "around the data. You can also click-and-drag the y-axis "
            "labels on the chart to rescale interactively."
        )
        self.sp_max_w.valueChanged.connect(self._on_max_w_changed)
        ctrl_row.addWidget(self.sp_max_w)
        ctrl_row.addStretch()
        main_layout.addLayout(ctrl_row)

        broker_row = QHBoxLayout()
        self.cb_powermon_broker = QCheckBox(
            "Use power-monitor broker (HTTP /snapshot; PostgreSQL by background service)"
        )
        self.cb_powermon_broker.setToolTip(
            "When enabled, the app does not poll Tasmota devices on the LAN; it shows the latest "
            "snapshot from powermon_broker.py and skips duplicate tasmota_* DB inserts from this GUI."
        )
        self.cb_powermon_broker.toggled.connect(self._on_broker_mode_toggled)
        broker_row.addWidget(self.cb_powermon_broker)
        broker_row.addWidget(QLabel("Broker URL:"))
        self.ed_powermon_broker_url = QLineEdit()
        self.ed_powermon_broker_url.setPlaceholderText("http://192.168.1.10:8765")
        self.ed_powermon_broker_url.setToolTip(
            "Base URL for GET /snapshot from powermon_broker / energy-collector. "
            "Use the container or remote host IP — also editable under Setup & Info → Background collector."
        )
        self.ed_powermon_broker_url.setMinimumWidth(_TASMOTA_BROKER_URL_MIN_W)
        broker_row.addWidget(self.ed_powermon_broker_url, 1)
        broker_row.addSpacing(12)
        broker_row.addWidget(QLabel("Poll every (s):"))
        self.sp_poll_interval = QSpinBox()
        self.sp_poll_interval.setRange(5, 600)
        self.sp_poll_interval.setValue(30)
        self.sp_poll_interval.setToolTip(
            "Seconds between automatic polls (LAN devices or broker /snapshot)."
        )
        apply_spin_field_motif(self.sp_poll_interval, width=_TASMOTA_CTRL_SPIN_W)
        broker_row.addWidget(self.sp_poll_interval)
        self.cb_auto_poll = QCheckBox("Auto poll")
        self.cb_auto_poll.setToolTip(
            "Poll this tab on a timer. When the broker is enabled, fetches /snapshot; "
            "otherwise polls each device on the LAN."
        )
        broker_row.addWidget(self.cb_auto_poll)
        self.save_broker_btn = QPushButton("Save")
        self.save_broker_btn.setToolTip(
            "Save broker URL, poll interval, and auto-poll setting"
        )
        self.save_broker_btn.clicked.connect(self._save_broker_settings)
        _apply_primary_button_style(self.save_broker_btn)
        broker_row.addWidget(self.save_broker_btn)
        main_layout.addLayout(broker_row)

        mqtt_row = QHBoxLayout()
        mqtt_row.setSpacing(8)
        self.cb_use_mqtt = QCheckBox("Subscribe via MQTT (live telemetry, no HTTP polling)")
        self.cb_use_mqtt.setToolTip(
            "Listen on tele/+/SENSOR, tele/+/STATUS8, stat/+/POWER, and tele/+/STATE. "
            "Devices are matched by IP address from the payload when available."
        )
        self.cb_use_mqtt.toggled.connect(self._on_mqtt_mode_toggled)
        mqtt_row.addWidget(self.cb_use_mqtt)
        mqtt_row.addWidget(QLabel("Host:"))
        self.ed_mqtt_host = QLineEdit()
        self.ed_mqtt_host.setPlaceholderText("222.20.20.1")
        self.ed_mqtt_host.setFixedWidth(_TASMOTA_MQTT_HOST_W)
        mqtt_row.addWidget(self.ed_mqtt_host)
        mqtt_row.addWidget(QLabel("Port:"))
        self.sp_mqtt_port = QSpinBox()
        self.sp_mqtt_port.setRange(1, 65535)
        self.sp_mqtt_port.setValue(1883)
        apply_spin_field_motif(self.sp_mqtt_port, width=_SPIN_FIELD_MOTIF_DB_W)
        mqtt_row.addWidget(self.sp_mqtt_port)
        mqtt_row.addWidget(QLabel("User:"))
        self.ed_mqtt_user = QLineEdit()
        self.ed_mqtt_user.setFixedWidth(_TASMOTA_MQTT_TEXT_W)
        mqtt_row.addWidget(self.ed_mqtt_user)
        mqtt_row.addWidget(QLabel("Pass:"))
        self.ed_mqtt_pass = QLineEdit()
        self.ed_mqtt_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_mqtt_pass.setFixedWidth(_TASMOTA_MQTT_TEXT_W)
        mqtt_row.addWidget(self.ed_mqtt_pass)
        mqtt_row.addWidget(QLabel("Prefix:"))
        self.ed_mqtt_prefix = QLineEdit()
        self.ed_mqtt_prefix.setPlaceholderText("optional, e.g. home/")
        self.ed_mqtt_prefix.setFixedWidth(_TASMOTA_MQTT_PREFIX_W)
        self.ed_mqtt_prefix.setToolTip(
            "Optional topic prefix before tele/… and stat/… (for bridged or namespaced brokers)."
        )
        mqtt_row.addWidget(self.ed_mqtt_prefix)
        mqtt_row.addSpacing(12)
        self.save_mqtt_btn = QPushButton("Save MQTT")
        self.save_mqtt_btn.setToolTip(
            "Save MQTT broker settings and connect when Subscribe via MQTT is enabled"
        )
        self.save_mqtt_btn.clicked.connect(self._save_mqtt_settings)
        _apply_primary_button_style(self.save_mqtt_btn)
        mqtt_row.addWidget(self.save_mqtt_btn)
        self.test_mqtt_btn = QPushButton("Test connection")
        self.test_mqtt_btn.setToolTip(
            "Try connecting to the MQTT broker with the host, port, and credentials above"
        )
        self.test_mqtt_btn.clicked.connect(self._test_mqtt_connection)
        _apply_primary_button_style(self.test_mqtt_btn)
        mqtt_row.addWidget(self.test_mqtt_btn)
        self.lbl_mqtt_status = QLabel("")
        self.lbl_mqtt_status.setStyleSheet("color: #6c7086; font-size: 11px;")
        self.lbl_mqtt_status.setMinimumWidth(240)
        mqtt_row.addWidget(self.lbl_mqtt_status, 1)
        main_layout.addLayout(mqtt_row)

        # Row 2: power summary banner
        self._summary_frame = QFrame()
        self._summary_frame.setStyleSheet(
            "QFrame { background: transparent; border: 1px solid #45475a; border-radius: 6px; }"
        )
        ban_row = QHBoxLayout(self._summary_frame)
        ban_row.setContentsMargins(12, 6, 12, 6)
        ban_row.setSpacing(16)

        self.total_power_big = QLabel("--")
        self.total_power_big.setFont(QFont('Helvetica', 20, QFont.Bold))
        self.total_power_big.setStyleSheet("color: #a6e3a1;")
        ban_row.addWidget(self.total_power_big)

        def _stat_label(title):
            w = QWidget()
            vl = QVBoxLayout(w)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(0)
            t = QLabel(title)
            t.setStyleSheet("color: #6c7086; font-size: 9px;")
            t.setAlignment(Qt.AlignCenter)
            vl.addWidget(t)
            v = QLabel("--")
            v.setStyleSheet("color: #cdd6f4; font-size: 13px; font-weight: bold;")
            v.setAlignment(Qt.AlignCenter)
            vl.addWidget(v)
            return w, v

        def _add_stat(title):
            w, v = _stat_label(title)
            w.setMinimumWidth(88)
            ban_row.addWidget(w)
            return v

        self.total_power_big.setMinimumWidth(96)
        self.ban_kw = _add_stat("kW")
        self.ban_today = _add_stat("Today kWh")
        self.ban_total = _add_stat("All-time kWh")
        self.ban_devices = _add_stat("Devices")
        self.ban_top = _add_stat("Top Consumer")
        ban_row.addStretch()
        main_layout.addWidget(self._summary_frame)
        self._load_saved_ip_range()
        self._load_saved_broker_settings()
        self._update_connection_widgets()
        # MQTT / poll timers start in auto_start() after one HTTP bootstrap read.

        # Two device tables (first N IPs left, remainder right). Stretch with
        # the charts so the pane is filled instead of sitting in a top strip.
        tree_host = QWidget()
        tree_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding,
        )
        tree_pair = QHBoxLayout(tree_host)
        tree_pair.setContentsMargins(0, 0, 0, 0)
        tree_pair.setSpacing(10)
        self.tree_left = QTreeWidget()
        self.tree_right = QTreeWidget()
        self._init_tasmota_device_trees()
        tree_pair.addWidget(self.tree_left, 1)
        tree_pair.addWidget(self.tree_right, 1)
        main_layout.addWidget(tree_host, 1)

        # Charts — full width; layout finalized in _finalize_tasmota_charts_layout
        # (50/50 split at figure midpoint, room for full y-axis names on bar chart).
        self.fig = Figure(figsize=(15, 4), dpi=100)
        gs = self.fig.add_gridspec(1, 2, wspace=0.26, right=0.985,
                                   top=0.93, bottom=0.14)
        self.ax_bar = self.fig.add_subplot(gs[0, 0])
        self.ax_hist = self.fig.add_subplot(gs[0, 1])
        # Click-and-drag y-axis state for ax_hist. Set when a button-press
        # lands on the y-axis tick-label region; consumed in motion-notify.
        self._yaxis_drag = None
        _style_ax_dark(self.ax_bar, self.fig)
        _style_ax_dark(self.ax_hist, self.fig)
        self.fig.set_facecolor(_DARK_BG)
        self.canvas = FigureCanvas(self.fig)
        main_layout.addWidget(self.canvas, 3)
        toolbar_row = QHBoxLayout()
        toolbar_row.setContentsMargins(0, 0, 0, 0)
        toolbar_row.setSpacing(8)
        self._tasmota_toolbar = DarkNavigationToolbar(self.canvas, self)
        toolbar_row.addWidget(self._tasmota_toolbar, 1)
        self.lbl_hist_db_status = QLabel("Power History DB: checking…")
        self.lbl_hist_db_status.setTextFormat(Qt.RichText)
        self.lbl_hist_db_status.setWordWrap(True)
        self.lbl_hist_db_status.setStyleSheet("font-size: 10px; padding: 0 6px;")
        self.lbl_hist_db_status.hide()
        self.cb_pin_hist_500 = QCheckBox("Pin chart 2 max")
        self.sp_pin_hist_w = QSpinBox()
        self.sp_pin_hist_w.setRange(50, 100000)
        self.sp_pin_hist_w.setSingleStep(50)
        self.sp_pin_hist_w.setValue(500)
        self.sp_pin_hist_w.setSuffix(" W")
        self.sp_pin_hist_w.setToolTip(
            "Y-axis ceiling (watts) used while Pin is on. Change anytime — "
            "spikes above this are clipped from the scale so quieter devices stay readable."
        )
        _apply_pin_chart_checkbox_halo(self.cb_pin_hist_500, self.sp_pin_hist_w)
        self.cb_pin_hist_500.setToolTip(
            "Lock the Power History (right) chart Y-axis to 0…the watts box. "
            "Stops a brief spike from squashing the other traces. "
            "Right-click the chart for presets; drag the Y-axis to retune while pinned."
        )
        self.cb_pin_hist_500.toggled.connect(self._on_pin_hist_500_toggled)
        self.sp_pin_hist_w.valueChanged.connect(self._on_pin_hist_w_changed)
        toolbar_row.addWidget(self.cb_pin_hist_500, 0, Qt.AlignRight | Qt.AlignVCenter)
        toolbar_row.addWidget(self.sp_pin_hist_w, 0, Qt.AlignRight | Qt.AlignVCenter)
        toolbar_wrap = QWidget()
        toolbar_wrap.setLayout(toolbar_row)
        main_layout.addWidget(toolbar_wrap)
        self._tasmota_cursor_label = QLabel(
            "Power History: right-click for Y-axis zoom presets; hover a line for device + usage. "
            "Use “Pin chart 2 max” and set the watts to hide spikes."
        )
        self._tasmota_cursor_label.setStyleSheet(
            "color: #cdd6f4; padding: 6px 8px; background: transparent; "
            "border: 1px solid #45475a; border-radius: 4px; font-family: monospace; font-size: 10px;"
        )
        self._tasmota_cursor_label.setWordWrap(True)
        self._tasmota_cursor_label.setTextFormat(Qt.RichText)
        self._tasmota_cursor_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        main_layout.addWidget(self._tasmota_cursor_label, 0)
        self._tasmota_hist_series = []
        self._tasmota_bar_bars = []

        # Hook click-and-drag y-axis rescaling + right-click Y zoom on ax_hist.
        self.canvas.mpl_connect('button_press_event', self._on_tasmota_canvas_press)
        self.canvas.mpl_connect('motion_notify_event', self._on_yaxis_motion)
        self.canvas.mpl_connect('button_release_event', self._on_yaxis_release)
        self._tasmota_motion_cid = self.canvas.mpl_connect(
            'motion_notify_event', self._on_tasmota_chart_motion
        )
        self._tasmota_resize_cid = self.canvas.mpl_connect(
            'resize_event', self._on_tasmota_canvas_resize
        )
        self._chart_shimmer = ChartShimmerOverlay(self.canvas)

        # Restore last-saved Y-axis cap (0 = auto). Setting the spinbox
        # value does not trigger a replot here because charts haven't been
        # drawn yet — it just primes the value used by _plot_charts().
        try:
            saved_cap = int(self._tasmota_settings().value(
                "tasmota/history_max_w", 0
            ) or 0)
        except (TypeError, ValueError):
            saved_cap = 0
        if saved_cap > 0:
            self.sp_max_w.blockSignals(True)
            self.sp_max_w.setValue(saved_cap)
            self.sp_max_w.blockSignals(False)
        try:
            pin_w = int(self._tasmota_settings().value(
                "tasmota/pin_hist_max_w", 500
            ) or 500)
        except (TypeError, ValueError):
            pin_w = 500
        pin_w = max(50, min(100000, pin_w))
        self.sp_pin_hist_w.blockSignals(True)
        self.sp_pin_hist_w.setValue(pin_w)
        self.sp_pin_hist_w.blockSignals(False)
        try:
            pin = self._tasmota_settings().value(
                "tasmota/pin_hist_500", False, type=bool
            )
        except Exception:
            pin = False
        if pin:
            self.cb_pin_hist_500.blockSignals(True)
            self.cb_pin_hist_500.setChecked(True)
            self.cb_pin_hist_500.blockSignals(False)
            self._apply_pin_hist_500_state(True)

        self.device_ips = ip_range(self.ip_start_edit.text(), self.ip_end_edit.text())
        self._refresh_device_table_ui()
        self._probe_history_db_link_async(refetch_history=True)

    def showEvent(self, event):
        super().showEvent(event)
        self._probe_history_db_link_async(refetch_history=True)
        QTimer.singleShot(0, self._relayout_tasmota_device_trees)

    def hideEvent(self, event):
        super().hideEvent(event)
        try:
            self._save_tasmota_column_widths()
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_tasmota_device_trees()

    def _relayout_tasmota_device_trees(self):
        if not hasattr(self, "tree_left") or not hasattr(self, "tree_right"):
            return
        self._apply_tasmota_tree_heights()

    def _resolve_history_db_config(self):
        """First enabled backend from Setup & Info → Database Export (SQLite → MySQL → PG)."""
        if self.dash is None:
            return None
        pt = getattr(self.dash, "parameters_tab", None)
        if pt is None:
            return None
        if pt.chk_sqlite.isChecked():
            path = pt.ed_sqlite_path.text().strip() or str(Path.home() / "energy_dashboard.db")
            return {
                "backend": "SQLite",
                "summary": path,
                "fetch_backend": "sqlite",
                "fetch_params": {"path": path},
                "cap": {"sqlite_path": path},
            }
        if pt.chk_mysql.isChecked():
            host = pt.ed_mysql_host.text().strip() or "localhost"
            port = int(pt.ed_mysql_port.value())
            user = pt.ed_mysql_user.text().strip()
            password = pt.ed_mysql_pass.text()
            database = pt.ed_mysql_db.text().strip() or "energy"
            return {
                "backend": "MySQL",
                "summary": f"{host}:{port}/{database}",
                "fetch_backend": "mysql",
                "fetch_params": {
                    "host": host,
                    "port": port,
                    "user": user,
                    "password": password,
                    "database": database,
                },
                "cap": {
                    "mysql_host": host,
                    "mysql_port": port,
                    "mysql_user": user,
                    "mysql_pass": password,
                    "mysql_db": database,
                },
            }
        if pt.chk_pg.isChecked():
            host = pt.ed_pg_host.text().strip() or "localhost"
            port = int(pt.ed_pg_port.value())
            user = pt.ed_pg_user.text().strip()
            password = pt.ed_pg_pass.text()
            dbname = pt.ed_pg_db.text().strip() or "powermon"
            return {
                "backend": "PostgreSQL",
                "summary": f"{host}:{port}/{dbname}",
                "fetch_backend": "pg",
                "fetch_params": {
                    "host": host,
                    "port": port,
                    "user": user,
                    "password": password,
                    "dbname": dbname,
                },
                "cap": {
                    "pg_host": host,
                    "pg_port": port,
                    "pg_user": user,
                    "pg_pass": password,
                    "pg_db": dbname,
                },
            }
        return None

    def _probe_history_db_link(self):
        cfg = self._resolve_history_db_config()
        if cfg is None:
            return {
                "backend": None,
                "summary": "",
                "ok": False,
                "error": "no backend enabled in Setup & Info",
            }
        backend = cfg["backend"]
        cap = cfg["cap"]
        if backend == "SQLite":
            ok, detail = probe_sqlite(cap.get("sqlite_path", ""))
        elif backend == "MySQL":
            ok, detail = probe_mysql(
                cap.get("mysql_host"),
                cap.get("mysql_port"),
                cap.get("mysql_user"),
                cap.get("mysql_pass"),
                cap.get("mysql_db"),
            )
        else:
            ok, detail = probe_postgresql(
                cap.get("pg_host"),
                cap.get("pg_port"),
                cap.get("pg_user"),
                cap.get("pg_pass"),
                cap.get("pg_db"),
            )
        if ok and isinstance(detail, dict):
            summary = format_probe_summary(detail)
            return {"backend": backend, "summary": summary, "ok": True, "error": None}
        return {
            "backend": backend,
            "summary": cfg["summary"],
            "ok": False,
            "error": str(detail),
        }

    @staticmethod
    def _history_points_count(db_history):
        if not db_history:
            return 0
        return sum(len(info.get("points") or []) for info in db_history.values())

    def _db_history_window_minutes(self):
        """Minutes spanned by cached DB points (0 if none)."""
        pts = []
        for info in (self._db_history or {}).values():
            for t, _ in info.get("points") or []:
                try:
                    pts.append(TasmotaTab._history_ts_utc(t))
                except (TypeError, ValueError):
                    pass
        if len(pts) < 2:
            return 0
        span = (max(pts) - min(pts)).total_seconds() / 60.0
        return int(span) + 1

    def _probe_history_db_link_async(
        self, refetch_history=False, window_minutes=None, replot=False,
    ):
        def _worker():
            link = self._probe_history_db_link()
            display_win = (
                window_minutes
                if window_minutes is not None
                else self._history_window_minutes()
            )
            fetch_win = max(display_win, self._history_cache_minutes())
            db_rows = {}
            if link.get("ok"):
                db_rows = self._fetch_db_history(fetch_win)
            self._inv.invoke(
                lambda lk=link, rows=db_rows, rf=refetch_history, rp=replot: (
                    self._apply_db_hist_link(lk, rows, rf, rp)
                )
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_db_hist_link(
        self, link, db_history=None, refetch_history=False, replot=False,
    ):
        self._db_hist_fetch_inflight = False
        self._db_hist_link = link
        if link.get("ok"):
            if db_history is not None:
                self._db_history = db_history
        elif refetch_history:
            self._db_history = {}
        self._update_hist_db_status_label()
        if (refetch_history or replot) and hasattr(self, "ax_hist"):
            try:
                self._plot_charts()
            except Exception as e:
                _log.warn("Tasmota", f"History replot after DB probe: {e}")

    def _update_hist_db_status_label(self):
        link = getattr(self, "_db_hist_link", None) or {}
        backend = link.get("backend")
        if not backend:
            self.lbl_hist_db_status.setText(
                '<span style="color:#f38ba8;font-weight:bold;">'
                "Power History DB: not configured</span> "
                '<span style="color:#6c7086;">— tick SQLite, MySQL, or PostgreSQL under '
                "Setup &amp; Info → Database Export</span>"
            )
            return
        summary = link.get("summary") or "—"
        if link.get("ok"):
            self.lbl_hist_db_status.setText(
                f'<span style="color:#a6e3a1;font-weight:bold;">'
                f"Power History DB: {backend} · connected</span> "
                f'<span style="color:#6c7086;">({summary})</span>'
            )
        else:
            err = link.get("error") or "connection failed"
            self.lbl_hist_db_status.setText(
                f'<span style="color:#f38ba8;font-weight:bold;">'
                f"Power History DB: {backend} · down</span> "
                f'<span style="color:#6c7086;">({summary}) — {err}</span>'
            )

    def _refresh_device_table_ui(self):
        """Fill or refresh both device tables (safe to call before first poll)."""
        try:
            self._update_table()
            self._apply_tasmota_tree_heights()
        except Exception as e:
            _log.exception("Tasmota", f"Device table update failed: {e}")

    def _hist_y_cap_w(self):
        """Effective Power History Y max (W); 0 = matplotlib auto-scale."""
        if getattr(self, 'cb_pin_hist_500', None) and self.cb_pin_hist_500.isChecked():
            if hasattr(self, 'sp_pin_hist_w'):
                return max(50, int(self.sp_pin_hist_w.value()))
            return 500
        return int(self.sp_max_w.value()) if hasattr(self, 'sp_max_w') else 0

    def _pin_hist_max_w(self):
        if hasattr(self, 'sp_pin_hist_w'):
            return max(50, int(self.sp_pin_hist_w.value()))
        return 500

    def _persist_pin_hist_settings(self, *, pinned=None):
        try:
            s = self._tasmota_settings()
            if pinned is not None:
                s.setValue("tasmota/pin_hist_500", bool(pinned))
            if hasattr(self, 'sp_pin_hist_w'):
                s.setValue("tasmota/pin_hist_max_w", int(self.sp_pin_hist_w.value()))
            s.sync()
        except Exception:
            pass

    def _apply_pin_hist_500_state(self, pinned):
        if not hasattr(self, 'sp_max_w'):
            return
        if pinned:
            cap = self._pin_hist_max_w()
            self.sp_max_w.blockSignals(True)
            self.sp_max_w.setValue(cap)
            self.sp_max_w.blockSignals(False)
            try:
                s = self._tasmota_settings()
                s.setValue("tasmota/history_max_w", cap)
                s.sync()
            except Exception:
                pass

    def _on_pin_hist_500_toggled(self, checked):
        self._persist_pin_hist_settings(pinned=bool(checked))
        self._apply_pin_hist_500_state(checked)
        try:
            self._plot_charts()
        except Exception:
            pass

    def _on_pin_hist_w_changed(self, value):
        self._persist_pin_hist_settings()
        if not (getattr(self, 'cb_pin_hist_500', None) and self.cb_pin_hist_500.isChecked()):
            return
        cap = max(50, int(value))
        if hasattr(self, 'sp_max_w'):
            self.sp_max_w.blockSignals(True)
            self.sp_max_w.setValue(cap)
            self.sp_max_w.blockSignals(False)
        try:
            s = self._tasmota_settings()
            s.setValue("tasmota/history_max_w", cap)
            s.sync()
        except Exception:
            pass
        try:
            self._plot_charts()
        except Exception:
            pass

    def _set_hist_y_cap(self, cap_w, *, from_context_menu=False):
        """Apply Y-axis cap to Power History and sync controls."""
        cap = max(0, int(cap_w))
        pinned = getattr(self, 'cb_pin_hist_500', None) and self.cb_pin_hist_500.isChecked()
        if pinned and cap > 0:
            # Retune the pin ceiling instead of clearing the pin.
            if hasattr(self, 'sp_pin_hist_w'):
                self.sp_pin_hist_w.blockSignals(True)
                self.sp_pin_hist_w.setValue(max(50, cap))
                self.sp_pin_hist_w.blockSignals(False)
            self._persist_pin_hist_settings(pinned=True)
        elif from_context_menu and pinned and cap == 0:
            self.cb_pin_hist_500.blockSignals(True)
            self.cb_pin_hist_500.setChecked(False)
            self.cb_pin_hist_500.blockSignals(False)
            self._persist_pin_hist_settings(pinned=False)
        if hasattr(self, 'sp_max_w'):
            self.sp_max_w.blockSignals(True)
            self.sp_max_w.setValue(cap)
            self.sp_max_w.blockSignals(False)
        try:
            s = self._tasmota_settings()
            s.setValue("tasmota/history_max_w", cap)
            s.sync()
        except Exception:
            pass
        if cap > 0 and hasattr(self, 'ax_hist'):
            self.ax_hist.set_ylim(0, cap)
            self.canvas.draw_idle()
        else:
            try:
                self._plot_charts()
            except Exception:
                pass

    def _show_hist_y_context_menu(self, event):
        menu = QMenu(self)
        menu.setTitle("Power History — Y-axis")
        for cap in TASMOTA_HIST_Y_PRESETS:
            label = "Y max: auto (fit data)" if cap == 0 else f"Y max: {cap} W"
            act = menu.addAction(label)
            act.setData(cap)
        if event.ydata is not None and float(event.ydata) > 20:
            y_at = int(round(float(event.ydata) / 10.0) * 10)
            y_at = max(50, min(10000, y_at))
            act = menu.addAction(f"Y max: {y_at} W (at cursor)")
            act.setData(y_at)
        menu.addSeparator()
        pin_w = self._pin_hist_max_w()
        pin_act = menu.addAction(f"Pin chart 2 max at {pin_w} W")
        pin_act.setData("pin_y")
        pos = QCursor.pos()
        chosen = menu.exec(pos)
        if chosen is None:
            return
        data = chosen.data()
        if data == "pin_y":
            self.cb_pin_hist_500.setChecked(True)
            return
        self._set_hist_y_cap(int(data), from_context_menu=True)

    def _on_max_w_changed(self, _v):
        cap = int(self.sp_max_w.value()) if hasattr(self, 'sp_max_w') else 0
        if getattr(self, 'cb_pin_hist_500', None) and self.cb_pin_hist_500.isChecked():
            if cap <= 0:
                self.cb_pin_hist_500.blockSignals(True)
                self.cb_pin_hist_500.setChecked(False)
                self.cb_pin_hist_500.blockSignals(False)
                self._persist_pin_hist_settings(pinned=False)
            else:
                if hasattr(self, 'sp_pin_hist_w'):
                    self.sp_pin_hist_w.blockSignals(True)
                    self.sp_pin_hist_w.setValue(max(50, cap))
                    self.sp_pin_hist_w.blockSignals(False)
                self._persist_pin_hist_settings(pinned=True)
        try:
            s = self._tasmota_settings()
            s.setValue("tasmota/history_max_w", cap)
            s.sync()
        except Exception:
            pass
        try:
            self._plot_charts()
        except Exception:
            pass

    def _hist_axes_pixel_bbox(self):
        """Display-coord bbox of ax_hist, or None if not yet rendered."""
        try:
            return self.ax_hist.get_window_extent()
        except Exception:
            return None

    def _on_tasmota_canvas_press(self, event):
        if event.button == 3 and event.inaxes is self.ax_hist:
            self._show_hist_y_context_menu(event)
            return
        # Only left-button presses on the y-axis label/spine region of the
        # history chart start a drag. We intentionally ignore the toolbar's
        # pan/zoom modes — those manipulate xlim too, which the user does
        # not want here.
        if event.button != 1 or event.x is None or event.y is None:
            return
        bbox = self._hist_axes_pixel_bbox()
        if bbox is None:
            return
        # Y-axis tick-label region: 60 px to the left of the spine, plus
        # a 6 px tolerance on the inside.
        if not (bbox.x0 - 60 <= event.x <= bbox.x0 + 6):
            return
        if not (bbox.y0 <= event.y <= bbox.y1):
            return
        ymin, ymax = self.ax_hist.get_ylim()
        self._yaxis_drag = {
            'start_y_px': float(event.y),
            'start_ymin': float(ymin),
            'start_ymax': float(ymax),
            'height_px': max(1.0, float(bbox.height)),
            'keep_pin': bool(
                getattr(self, 'cb_pin_hist_500', None)
                and self.cb_pin_hist_500.isChecked()
            ),
        }
        # While we are dragging, suppress the default cursor change so the
        # user can see the rescale happening live.
        try:
            self.canvas.setCursor(Qt.SizeVerCursor)
        except Exception:
            pass

    def _on_yaxis_motion(self, event):
        drag = self._yaxis_drag
        if not drag or event.y is None:
            return
        # Drag UP increases ymax (zoom out vertically); drag DOWN decreases.
        # Scale linearly with fraction of axes height, biased so a full
        # axis-height drag changes the cap by ~2x in either direction.
        delta_px = float(event.y) - drag['start_y_px']
        scale = max(0.05, 1.0 - (delta_px / drag['height_px']))
        new_ymax = max(10.0, drag['start_ymax'] * scale)
        # Round to a "nice" Watt value for the spinbox.
        if new_ymax >= 1000:
            new_ymax = round(new_ymax / 100.0) * 100
        else:
            new_ymax = round(new_ymax / 10.0) * 10
        new_ymax = max(10, int(new_ymax))
        if drag.get('keep_pin'):
            new_ymax = max(50, new_ymax)
        self.ax_hist.set_ylim(drag['start_ymin'], new_ymax)
        # Mirror to spinbox (without re-triggering replot/persist).
        if hasattr(self, 'sp_max_w'):
            self.sp_max_w.blockSignals(True)
            self.sp_max_w.setValue(new_ymax)
            self.sp_max_w.blockSignals(False)
        if drag.get('keep_pin') and hasattr(self, 'sp_pin_hist_w'):
            self.sp_pin_hist_w.blockSignals(True)
            self.sp_pin_hist_w.setValue(new_ymax)
            self.sp_pin_hist_w.blockSignals(False)
        self.canvas.draw_idle()

    def _on_yaxis_release(self, _event):
        if not self._yaxis_drag:
            return
        keep_pin = bool(self._yaxis_drag.get('keep_pin'))
        self._yaxis_drag = None
        try:
            self.canvas.setCursor(Qt.ArrowCursor)
        except Exception:
            pass
        # Persist final value (drag updated the spinbox while signals were
        # blocked, so we save here explicitly).
        try:
            s = self._tasmota_settings()
            s.setValue("tasmota/history_max_w", int(self.sp_max_w.value()))
            if keep_pin and hasattr(self, 'sp_pin_hist_w'):
                s.setValue("tasmota/pin_hist_max_w", int(self.sp_pin_hist_w.value()))
                s.setValue("tasmota/pin_hist_500", True)
            s.sync()
        except Exception:
            pass

    def _init_tasmota_device_trees(self):
        table_font = self.tree_left.font()
        table_font.setPointSize(_TASMOTA_DEVICE_TABLE_FONT_PT)
        self._tasmota_table_font = table_font
        action_font = QFont(table_font)
        action_font.setPointSize(_TASMOTA_DEVICE_ACTION_FONT_PT)
        self._tasmota_action_font = action_font
        for tr in (self.tree_left, self.tree_right):
            tr.setFont(table_font)
            tr.header().setFont(table_font)

        _lbl_probe, _lbl_toggle, _lbl_web, _lbl_diag = (
            "Probe", "Toggle", "Web UI", "Diagnose",
        )
        sizing_font = QFont(table_font)
        sizing_font.setPointSize(_TASMOTA_ACTION_BTN_SIZING_FONT_PT)
        fm = QFontMetrics(sizing_font)
        # Fixed outer width from the original 8 pt / 7 px-hpad footprint — display
        # font is smaller so labels fit inside without changing button size.
        self._tasmota_btn_w = (
            max(
                fm.horizontalAdvance(_lbl_probe),
                fm.horizontalAdvance(_lbl_toggle),
                fm.horizontalAdvance(_lbl_web),
                fm.horizontalAdvance(_lbl_diag),
            )
            + (_TASMOTA_ACTION_BTN_SIZING_HPAD * 2)
            + _TASMOTA_ACTION_BTN_SIZING_MARGIN
        )
        self._tasmota_action_btn_h = self._measure_tasmota_action_btn_h()
        self._tasmota_tree_headers = [
            'State', 'Name', 'IP', 'Firmware', 'Power (W)', 'Voltage (V)',
            'Current (A)', 'Today (kWh)', 'Total (kWh)',
            'Actions',
        ]
        # 2 px top/bottom around row text; action buttons are row_h - 2 px tall.
        _qss = (
            "QTreeWidget { alternate-background-color: #252536; }\n"
            "QTreeWidget::item {\n"
            "  padding-top: 2px;\n"
            "  padding-bottom: 2px;\n"
            "}\n"
        )
        for tr in (self.tree_left, self.tree_right):
            tr.setHeaderLabels(self._tasmota_tree_headers)
            tr.setColumnCount(10)
            tr.setRootIsDecorated(False)
            tr.setAlternatingRowColors(True)
            tr.setUniformRowHeights(True)
            tr.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding,
            )
            tr.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            tr.setStyleSheet(_qss)
            tr.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            tr.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            tr.header().setStretchLastSection(False)
            tr.header().setMinimumSectionSize(36)
            tr.header().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            tr.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            tr.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._setup_tasmota_paired_columns()

    def _setup_tasmota_paired_columns(self) -> None:
        """Interactive column widths shared by both device tables."""
        for tr in (self.tree_left, self.tree_right):
            qtree_set_column_width_key(tr, _TASMOTA_DEVICE_COL_KEY)
            qtree_prepare_interactive_columns(tr)
        if not qtree_restore_column_widths(
            self.tree_left, _TASMOTA_DEVICE_COL_KEY, resize_if_no_saved=False,
        ):
            widths = self._tasmota_compute_column_widths(self.tree_left)
            if not widths:
                widths = self._tasmota_column_min_widths()
        else:
            widths = [
                self.tree_left.columnWidth(c)
                for c in range(self.tree_left.columnCount())
            ]
        self._apply_tasmota_widths_to_both(widths)
        self._tasmota_col_sync_guard = False
        if not getattr(self, "_tasmota_col_width_timer", None):
            self._tasmota_col_width_timer = QTimer(self)
            self._tasmota_col_width_timer.setSingleShot(True)
            self._tasmota_col_width_timer.setInterval(450)
            self._tasmota_col_width_timer.timeout.connect(
                self._save_tasmota_column_widths,
            )
        for tr in (self.tree_left, self.tree_right):
            tr.header().sectionResized.connect(self._on_tasmota_column_resized)
        app = QApplication.instance()
        if app is not None and not getattr(self, "_tasmota_col_quit_hooked", False):
            app.aboutToQuit.connect(self._save_tasmota_column_widths)
            self._tasmota_col_quit_hooked = True

    def _on_tasmota_column_resized(self, logical_index: int, _old_size: int, new_size: int):
        if getattr(self, "_tasmota_col_sync_guard", False):
            return
        hdr = self.sender()
        if hdr is self.tree_left.header():
            source, other = self.tree_left, self.tree_right
        elif hdr is self.tree_right.header():
            source, other = self.tree_right, self.tree_left
        else:
            return
        mins = self._tasmota_column_min_widths()
        col = int(logical_index)
        width = max(36, mins[col] if col < len(mins) else 36, int(new_size))
        self._tasmota_col_sync_guard = True
        try:
            if source.columnWidth(col) != width:
                source.header().blockSignals(True)
                source.setColumnWidth(col, width)
                source.header().blockSignals(False)
            other.header().blockSignals(True)
            other.setColumnWidth(col, width)
            other.header().blockSignals(False)
        finally:
            self._tasmota_col_sync_guard = False
        timer = getattr(self, "_tasmota_col_width_timer", None)
        if timer is not None:
            timer.start()

    def _apply_tasmota_widths_to_both(self, widths) -> None:
        if not widths:
            return
        self._tasmota_col_sync_guard = True
        try:
            for tr in (self.tree_left, self.tree_right):
                hdr = tr.header()
                hdr.blockSignals(True)
                for c, w in enumerate(widths):
                    if c < tr.columnCount():
                        tr.setColumnWidth(c, max(36, int(w)))
                hdr.blockSignals(False)
        finally:
            self._tasmota_col_sync_guard = False

    def _save_tasmota_column_widths(self) -> None:
        if hasattr(self, "tree_left"):
            qtree_save_column_widths(self.tree_left, _TASMOTA_DEVICE_COL_KEY)

    def _actions_column_width(self):
        """Fixed width for Probe + Web UI + Diagnose + Toggle.

        Four equal buttons, 4px gaps, extra gap before Toggle, plus end margin
        so the last button never clips.
        """
        w = self._tasmota_btn_w
        return w * 4 + (4 * 3) + _TASMOTA_TOGGLE_LEADING_GAP + 8

    def _tasmota_header_font_metrics(self):
        try:
            return QFontMetrics(self._tasmota_table_font)
        except Exception:
            return QFontMetrics(self.font())

    def _name_column_width(self):
        """Width that fits the longest device name actually displayed."""
        fm = self._tasmota_header_font_metrics()
        longest = fm.horizontalAdvance("Name")
        for ip in getattr(self, "device_ips", []) or []:
            text = str(self.device_names.get(ip, ip) or ip)
            longest = max(longest, fm.horizontalAdvance(text))
        return int(min(max(longest + 16, 90), 220))

    def _tasmota_column_min_widths(self):
        """Hard minima from header + typical cell text — never clip labels."""
        fm = self._tasmota_header_font_metrics()
        pad = 18
        headers = getattr(self, "_tasmota_tree_headers", []) or [""] * 10
        mins = [fm.horizontalAdvance(h) + pad for h in headers]
        samples = {
            0: "OFF",
            2: "255.255.255.255",
            3: "14.6.0",
            4: "9999",
            5: "240",
            6: "9.99",
            7: "99.99",
            8: "999.9",
        }
        for col, sample in samples.items():
            mins[col] = max(mins[col], fm.horizontalAdvance(sample) + pad)
        mins[1] = self._name_column_width()
        mins[9] = self._actions_column_width()
        return mins

    def _tasmota_compute_column_widths(self, tree):
        """Default column widths from viewport size (first run only)."""
        total_w = max(tree.width(), tree.viewport().width()) - 8
        if total_w < 80:
            return None
        mins = self._tasmota_column_min_widths()
        other_idx = [0, 2, 3, 4, 5, 6, 7, 8]
        weights = {0: 0.4, 2: 1.4, 3: 1.0, 4: 0.8, 5: 0.8, 6: 0.8, 7: 0.9, 8: 0.9}
        min_sum = sum(mins)
        widths = list(mins)
        if total_w > min_sum:
            extra = total_w - min_sum
            tw = sum(weights.values())
            for c in other_idx:
                widths[c] += int(extra * weights[c] / tw)
            widths[2] += total_w - sum(widths)
        return [max(36, w) for w in widths]

    def _apply_tasmota_column_widths(self, tree):
        """Legacy helper — apply computed defaults to one tree."""
        widths = self._tasmota_compute_column_widths(tree)
        if widths:
            for col, width in enumerate(widths):
                tree.setColumnWidth(col, width)

    @staticmethod
    def _tasmota_settings():
        return QSettings("PowerModel", "EnergyDashboard2")

    def _load_saved_ip_range(self):
        s = self._tasmota_settings()
        start = s.value("tasmota/ip_start")
        end = s.value("tasmota/ip_end")
        if start:
            self.ip_start_edit.setText(str(start).strip())
        if end:
            self.ip_end_edit.setText(str(end).strip())

    def _save_ip_range(self):
        a = self.ip_start_edit.text().strip()
        b = self.ip_end_edit.text().strip()
        try:
            ipaddress.ip_address(a)
            ipaddress.ip_address(b)
        except ValueError:
            QMessageBox.warning(self, "Invalid IP", "Enter two valid IPv4 (or IPv6) addresses.")
            return
        s = self._tasmota_settings()
        s.setValue("tasmota/ip_start", a)
        s.setValue("tasmota/ip_end", b)
        s.sync()
        self.set_status("Tasmota IP range saved.")

    def _default_poll_interval_seconds(self) -> int:
        if self.dash is not None:
            return max(5, min(600, int(self.dash.app_params.auto_refresh_seconds)))
        return 30

    def poll_interval_seconds(self) -> int:
        s = self._tasmota_settings()
        if s.contains("tasmota/poll_interval_seconds"):
            raw = int(s.value("tasmota/poll_interval_seconds", 30) or 30)
        else:
            raw = self._default_poll_interval_seconds()
        return max(5, min(600, raw))

    def poll_interval_ms(self) -> int:
        return self.poll_interval_seconds() * 1000

    def periodic_poll_enabled(self) -> bool:
        if self.use_mqtt_mode():
            return False
        s = self._tasmota_settings()
        if s.contains("tasmota/auto_poll"):
            return s.value("tasmota/auto_poll", False, type=bool)
        if self.dash is not None:
            return bool(self.dash.app_params.auto_refresh_enabled)
        return False

    def use_mqtt_mode(self) -> bool:
        return self._tasmota_settings().value("tasmota/use_mqtt", False, type=bool)

    def alarm_snapshot(self, stale_s: float = 480.0) -> dict:
        """Known Tasmota plugs/CTs that have gone quiet (not the whole IP range)."""
        mqtt_mode = self.use_mqtt_mode()
        mqtt_connected = False
        if mqtt_mode:
            try:
                mqtt_connected = bool(getattr(self._mqtt, "connected", False))
            except Exception:
                mqtt_connected = False
        known = set()
        for ip, name in (self.device_names or {}).items():
            if name:
                known.add(str(ip))
        for ip, data in (self.device_data or {}).items():
            if data:
                known.add(str(ip))
        for ip in (self.history or {}):
            known.add(str(ip))
        now = datetime.now(timezone.utc)
        offline = []
        for ip in sorted(known):
            last = None
            hist = (self.history or {}).get(ip)
            if hist:
                try:
                    last = self._history_ts_utc(hist[-1][0])
                except Exception:
                    last = None
            live = bool((self.device_data or {}).get(ip))
            if live and last is None:
                continue
            age_s = None
            if last is not None:
                try:
                    age_s = (self._history_ts_utc(now) - last).total_seconds()
                except Exception:
                    age_s = None
            silent = (not live) or (age_s is not None and age_s > float(stale_s))
            if silent:
                label = (self.device_names or {}).get(ip) or ip
                if label != ip:
                    offline.append(f"{label} ({ip})")
                else:
                    offline.append(str(ip))
        return {
            "mqtt_mode": mqtt_mode,
            "mqtt_connected": mqtt_connected,
            "known": len(known),
            "offline": offline,
        }

    def apply_poll_timer(self, *, kick: bool = False) -> None:
        """Start/stop the tab poll timer from saved or current UI settings.

        The interval always comes from this tab (``poll_interval_seconds``,
        which falls back to the shared cadence when nothing is saved here) so
        cycling the banner pill can no longer overwrite the device poll rate.
        """
        self._auto_timer.stop()
        if self.use_mqtt_mode():
            return
        self._auto_timer.setInterval(max(5000, self.poll_interval_ms()))
        if self.periodic_poll_enabled():
            self._auto_timer.start()
        if kick and self.periodic_poll_enabled():
            self.poll_all()

    def live_refresh_expectation(self):
        """(active, expected_seconds, detail) for the banner refresh pill."""
        if self.use_mqtt_mode():
            return True, 60.0, "Tasmota MQTT push"
        sec = self.poll_interval_seconds()
        if not self.periodic_poll_enabled():
            return False, float(sec), "periodic poll disabled on this tab"
        return True, float(sec), f"HTTP poll every {sec}s"

    def _on_broker_mode_toggled(self, checked: bool) -> None:
        if checked:
            self.cb_use_mqtt.blockSignals(True)
            self.cb_use_mqtt.setChecked(False)
            self.cb_use_mqtt.blockSignals(False)
        self._update_connection_widgets()

    def _on_mqtt_mode_toggled(self, checked: bool) -> None:
        if checked:
            self.cb_powermon_broker.blockSignals(True)
            self.cb_powermon_broker.setChecked(False)
            self.cb_powermon_broker.blockSignals(False)
        self._update_connection_widgets()

    def _update_connection_widgets(self) -> None:
        broker_on = self.cb_powermon_broker.isChecked()
        mqtt_on = self.cb_use_mqtt.isChecked()
        self.ed_powermon_broker_url.setEnabled(broker_on)
        self.sp_poll_interval.setEnabled(not mqtt_on)
        self.cb_auto_poll.setEnabled(not mqtt_on)
        self.cb_powermon_broker.setEnabled(not mqtt_on)
        self.cb_use_mqtt.setEnabled(not broker_on)
        mqtt_editable = not broker_on
        for w in (
            self.ed_mqtt_host,
            self.sp_mqtt_port,
            self.ed_mqtt_user,
            self.ed_mqtt_pass,
            self.ed_mqtt_prefix,
            self.save_mqtt_btn,
            self.test_mqtt_btn,
        ):
            w.setEnabled(mqtt_editable)
        self.sp_poll_interval.setEnabled(not mqtt_on)
        self.cb_auto_poll.setEnabled(not mqtt_on)
        if mqtt_on:
            self.poll_btn.setToolTip("Request one HTTP Status 8 read per device (MQTT stays active)")
        else:
            self.poll_btn.setToolTip("")

    def _mqtt_config_from_ui(self) -> dict:
        return {
            "host": self.ed_mqtt_host.text().strip(),
            "port": int(self.sp_mqtt_port.value()),
            "username": self.ed_mqtt_user.text().strip(),
            "password": self.ed_mqtt_pass.text(),
            "topic_prefix": self.ed_mqtt_prefix.text().strip(),
        }

    def _start_mqtt(self) -> None:
        cfg = self._mqtt_config_from_ui()
        self._set_mqtt_status(
            f"MQTT connecting to {cfg['host']}:{cfg['port']}…"
        )

        def _worker():
            ok, msg = self._mqtt.start(
                cfg["host"],
                cfg["port"],
                username=cfg["username"],
                password=cfg["password"],
                topic_prefix=cfg["topic_prefix"],
            )
            self._inv.invoke(lambda: self._mqtt_start_done(ok, msg))

        threading.Thread(target=_worker, daemon=True).start()

    def _mqtt_start_done(self, ok: bool, msg: str) -> None:
        self._set_mqtt_status(msg)
        if not ok:
            self.set_status(msg)

    def _stop_mqtt(self) -> None:
        def _worker():
            self._mqtt.stop()
        threading.Thread(target=_worker, daemon=True).start()

    def _set_mqtt_status(self, msg: str) -> None:
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(
            f"color: {_UI_BLUE}; font-size: 11px;"
            if "subscribed" in msg.lower() or "connecting" in msg.lower()
            else f"color: #f38ba8; font-size: 11px;"
            if "fail" in msg.lower() or "disconnect" in msg.lower()
            else f"color: #6c7086; font-size: 11px;"
        )

    def _apply_connection_mode(self) -> None:
        if self.use_mqtt_mode():
            self._auto_timer.stop()
            self._start_mqtt()
        else:
            self._stop_mqtt()
            self.apply_poll_timer()

    def _apply_mqtt_snapshot(self) -> None:
        if not self.use_mqtt_mode():
            return
        import time
        self.device_ips = ip_range(self.ip_start_edit.text(), self.ip_end_edit.text())
        allowed = set(self.device_ips)
        results, names, firmwares = self._mqtt.snapshot_for_ips(allowed)
        now = datetime.now(timezone.utc)
        for ip, data in results.items():
            self._record_history_point(
                ip, data.get("power_W", 0), when=now, min_interval_s=30,
            )
        self.device_names.update(names)
        self.device_firmware.update(firmwares)
        for ip, data in results.items():
            self.device_data[ip] = data
        online = sum(1 for ip in allowed if ip in self.device_data)
        total = len(self.device_ips)
        ts = datetime.now().strftime("%H:%M:%S")
        self.status_label.setText(f"MQTT · {online}/{total} devices · {ts}")
        self.status_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        self._update_total_power_banner()
        # Table + matplotlib are expensive — throttle and skip when tab hidden.
        mono = time.monotonic()
        tab_visible = self.isVisible()
        heavy_due = (mono - self._mqtt_last_heavy_ui) >= _MQTT_HEAVY_UI_INTERVAL_S
        if tab_visible and heavy_due:
            self._mqtt_last_heavy_ui = mono
            try:
                self._refresh_device_table_ui()
                self._plot_charts()
            except Exception as e:
                _log.exception("Tasmota", f"MQTT display update failed: {e}")
        self._maybe_log_mqtt_to_db()
        self._maybe_refresh_db_history()
        self._maybe_notify_data_updated()
        if self.dash is not None and hasattr(self.dash, "mark_tab_fresh"):
            self.dash.mark_tab_fresh(self)

    def _uses_powermon_broker(self) -> bool:
        return self._tasmota_settings().value(
            "tasmota/use_powermon_broker", False, type=bool,
        )

    def _broker_snapshot_cached(self, max_age_s: float = 30.0) -> dict | None:
        """Recent GET /snapshot from the energy-collector (cached briefly)."""
        if not self._uses_powermon_broker():
            return None
        import time
        cached = self._broker_snap_cache
        if cached and (time.monotonic() - cached[0]) < max_age_s:
            return cached[1]
        url = (
            self._tasmota_settings().value("tasmota/powermon_broker_url") or ""
        ).strip().rstrip("/")
        if not url:
            return None
        try:
            r = requests.get(f"{url}/snapshot", timeout=5)
            r.raise_for_status()
            snap = r.json()
            self._broker_snap_cache = (time.monotonic(), snap)
            return snap
        except Exception as e:
            _log.debug("Tasmota", f"Broker snapshot probe: {e}")
            return None

    def _broker_collector_logging_devices(self) -> bool:
        """True when the background collector is polling at least one dashboard IP."""
        snap = self._broker_snapshot_cached()
        if not snap:
            return False
        if int(snap.get("online") or 0) <= 0:
            return False
        scan = set(snap.get("scan_ips") or [])
        if not scan:
            return False
        wanted = set(self.device_ips or [])
        if not wanted:
            return True
        return bool(scan & wanted)

    def _maybe_log_mqtt_to_db(self) -> None:
        """Write MQTT samples to the DB on a fixed interval.

        Skipped when the power-monitor broker is enabled *and* the collector is
        successfully logging the dashboard IP range; otherwise the GUI writes so
        Power History stays filled when the service is misconfigured or offline.
        """
        if self._uses_powermon_broker() and self._broker_collector_logging_devices():
            return
        import time
        now = time.monotonic()
        if now - self._mqtt_last_db_log < _MQTT_DB_LOG_INTERVAL_S:
            return
        self._mqtt_last_db_log = now
        dash = self.dash
        if dash is None:
            return
        logger = getattr(dash, "data_logger", None)
        if logger is None:
            return
        records = []
        for ip, d in self.device_data.items():
            if d:
                records.append({
                    "ip": ip,
                    "name": d.get("name", ""),
                    "relay_on": d.get("relay_on"),
                    "power_W": d.get("power_W"),
                    "voltage_V": d.get("voltage_V"),
                    "current_A": d.get("current_A"),
                    "today_kWh": d.get("today_kWh"),
                    "total_kWh": d.get("total_kWh"),
                })
        if not records:
            return
        try:
            logger.log_tasmota(records)
        except Exception as e:
            _log.warn("Tasmota", f"MQTT DB log failed: {e}")

    def _maybe_refresh_db_history(self) -> None:
        """Periodically refetch DB history while MQTT is the live data source."""
        if not self.use_mqtt_mode():
            return
        import time
        now = time.monotonic()
        if now - self._last_db_hist_fetch < _DB_HIST_REFRESH_S:
            return
        if self._db_hist_fetch_inflight:
            return
        self._last_db_hist_fetch = now
        self._db_hist_fetch_inflight = True
        self._probe_history_db_link_async(refetch_history=True, replot=True)

    def _maybe_notify_data_updated(self) -> None:
        import time
        interval = float(self.poll_interval_seconds())
        now = time.monotonic()
        if now - self._mqtt_last_notify < interval:
            return
        self._mqtt_last_notify = now
        if self.on_data_updated:
            self.on_data_updated()

    def _load_saved_broker_settings(self):
        s = self._tasmota_settings()
        self.cb_use_mqtt.setChecked(s.value("tasmota/use_mqtt", False, type=bool))
        self.cb_powermon_broker.setChecked(
            s.value("tasmota/use_powermon_broker", False, type=bool)
        )
        url = s.value("tasmota/powermon_broker_url") or "http://127.0.0.1:8765"
        self.ed_powermon_broker_url.setText(str(url).strip())
        self.sp_poll_interval.setValue(self.poll_interval_seconds())
        self.cb_auto_poll.setChecked(
            s.value("tasmota/auto_poll", False, type=bool)
            if s.contains("tasmota/auto_poll")
            else bool(self.dash.app_params.auto_refresh_enabled)
            if self.dash is not None
            else False
        )
        self.ed_mqtt_host.setText(str(s.value("tasmota/mqtt_host") or "").strip())
        self.sp_mqtt_port.setValue(
            max(1, min(65535, int(s.value("tasmota/mqtt_port", 1883) or 1883)))
        )
        self.ed_mqtt_user.setText(str(s.value("tasmota/mqtt_user") or "").strip())
        self.ed_mqtt_pass.setText(str(s.value("tasmota/mqtt_pass") or ""))
        self.ed_mqtt_prefix.setText(str(s.value("tasmota/mqtt_prefix") or "").strip())
        if self.cb_use_mqtt.isChecked() and self.cb_powermon_broker.isChecked():
            self.cb_powermon_broker.setChecked(False)

    def _save_broker_settings(self):
        sec = int(self.sp_poll_interval.value())
        s = self._tasmota_settings()
        s.setValue("tasmota/use_powermon_broker", self.cb_powermon_broker.isChecked())
        s.setValue("tasmota/powermon_broker_url", self.ed_powermon_broker_url.text().strip())
        s.setValue("tasmota/poll_interval_seconds", sec)
        s.setValue("tasmota/auto_poll", self.cb_auto_poll.isChecked())
        s.sync()
        self._update_connection_widgets()
        if not self.use_mqtt_mode():
            self._apply_connection_mode()
        if self.dash is not None and hasattr(self.dash, "_update_refresh_cycle_button"):
            self.dash._update_refresh_cycle_button()
        self.set_status(f"Broker settings saved ({sec}s poll interval).")

    def _persist_mqtt_settings(self) -> None:
        s = self._tasmota_settings()
        s.setValue("tasmota/use_mqtt", self.cb_use_mqtt.isChecked())
        s.setValue("tasmota/mqtt_host", self.ed_mqtt_host.text().strip())
        s.setValue("tasmota/mqtt_port", int(self.sp_mqtt_port.value()))
        s.setValue("tasmota/mqtt_user", self.ed_mqtt_user.text().strip())
        s.setValue("tasmota/mqtt_pass", self.ed_mqtt_pass.text())
        s.setValue("tasmota/mqtt_prefix", self.ed_mqtt_prefix.text().strip())
        s.sync()

    def _save_mqtt_settings(self):
        self._persist_mqtt_settings()
        self._update_connection_widgets()
        if self.dash is not None and hasattr(self.dash, "_update_refresh_cycle_button"):
            self.dash._update_refresh_cycle_button()
        if self.use_mqtt_mode():
            self.lbl_mqtt_status.setText("Saved — bootstrap poll, then MQTT…")
            self.lbl_mqtt_status.setStyleSheet("color: #a6e3a1; font-size: 11px;")
            self.set_status("MQTT saved — polling devices for starting values…")
            self._bootstrap_then_mqtt = True
            self._stop_mqtt()
            self.poll_all()
        else:
            self._stop_mqtt()
            self.apply_poll_timer()
            self.lbl_mqtt_status.setText("MQTT settings saved")
            self.lbl_mqtt_status.setStyleSheet("color: #a6e3a1; font-size: 11px;")
            self.set_status("MQTT settings saved (enable Subscribe to connect).")

    def _test_mqtt_connection(self):
        cfg = self._mqtt_config_from_ui()
        if not cfg["host"]:
            self.lbl_mqtt_status.setText("Enter MQTT host first")
            self.lbl_mqtt_status.setStyleSheet("color: #f38ba8; font-size: 11px;")
            return
        self.test_mqtt_btn.setEnabled(False)
        self.lbl_mqtt_status.setText("Testing…")
        self.lbl_mqtt_status.setStyleSheet("color: #6c7086; font-size: 11px;")
        threading.Thread(
            target=self._test_mqtt_thread,
            args=(cfg,),
            daemon=True,
        ).start()

    def _test_mqtt_thread(self, cfg: dict):
        ok, msg = test_tasmota_mqtt_connection(
            cfg["host"],
            cfg["port"],
            username=cfg["username"],
            password=cfg["password"],
        )
        self._inv.invoke(lambda: self._finish_mqtt_test(ok, msg))

    def _finish_mqtt_test(self, ok: bool, msg: str):
        self.test_mqtt_btn.setEnabled(True)
        self.lbl_mqtt_status.setText(msg)
        color = "#a6e3a1" if ok else "#f38ba8"
        self.lbl_mqtt_status.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.set_status(msg)

    @staticmethod
    def _format_window(minutes):
        if minutes < 60:
            return f"{minutes} min"
        h = minutes / 60
        return f"{h:.0f} hr" if h == int(h) else f"{h:.1f} hr"

    def _on_history_slider_changed(self, idx):
        minutes = self._history_minutes_steps[idx]
        self.history_window_label.setText(self._format_window(minutes))
        self._plot_charts()
        # Re-query DB for the selected window when cache is empty or too short.
        win = self._history_window_minutes()
        cached = self._history_points_count(self._db_history)
        if cached == 0 or win > self._db_history_window_minutes():
            self._probe_history_db_link_async(refetch_history=True, window_minutes=win)

    def _history_window_minutes(self):
        return self._history_minutes_steps[self.history_slider.value()]

    def _history_cache_minutes(self):
        """DB + in-memory retention — always at least the longest slider step."""
        return self._history_minutes_steps[-1]

    def _history_time_cutoff(self):
        return datetime.now(timezone.utc) - timedelta(
            minutes=self._history_cache_minutes()
        )

    def _trim_device_history(self, ip: str) -> None:
        cutoff = pd.Timestamp(self._history_time_cutoff())
        pts = self.history.get(ip) or []
        kept = []
        for t, val in pts:
            try:
                if self._history_ts_utc(t) >= cutoff:
                    kept.append((t, val))
            except (TypeError, ValueError):
                continue
        self.history[ip] = kept

    def _record_history_point(
        self, ip: str, power_w, when=None, *, min_interval_s: float = 0,
    ) -> None:
        when = when or datetime.now(timezone.utc)
        if min_interval_s > 0 and self.history.get(ip):
            try:
                last_t, _ = self.history[ip][-1]
                gap = (
                    self._history_ts_utc(when) - self._history_ts_utc(last_t)
                ).total_seconds()
                if gap < min_interval_s:
                    return
            except (TypeError, ValueError):
                pass
        if ip not in self.history:
            self.history[ip] = []
        self.history[ip].append((when, float(power_w or 0)))
        self._trim_device_history(ip)

    @staticmethod
    def _history_ts_utc(t):
        """Normalise poll/DB timestamps to UTC for charting."""
        ts = pd.Timestamp(t)
        if ts.tzinfo is None:
            return ts.tz_localize('UTC')
        return ts.tz_convert('UTC')

    @staticmethod
    def _finalize_history_series(
        times, vals, *, online=False, max_gap_s=_HISTORY_MAX_GAP_S, current_val=None,
    ):
        """Break long gaps with NaN; hold last value to now for online devices."""
        if not times:
            return times, vals
        out_t = [times[0]]
        out_v = [vals[0]]
        for i in range(1, len(times)):
            gap = (times[i] - times[i - 1]).total_seconds()
            if gap > max_gap_s:
                out_t.append(times[i - 1])
                out_v.append(float("nan"))
            out_t.append(times[i])
            out_v.append(vals[i])
        if online and out_t:
            now = pd.Timestamp.now(tz="UTC")
            last_t = out_t[-1]
            last_v = out_v[-1]
            if not (isinstance(last_v, float) and math.isnan(last_v)):
                trail_v = current_val if current_val is not None else last_v
                gap_to_now = (now - last_t).total_seconds()
                if 0 < gap_to_now <= max_gap_s * 2:
                    out_t.append(now)
                    out_v.append(trail_v)
                elif gap_to_now > max_gap_s * 2 and current_val is not None:
                    # Stale history — jump to the live reading without a diagonal ramp.
                    out_t.append(last_t)
                    out_v.append(float("nan"))
                    out_t.append(now)
                    out_v.append(current_val)
        if len(out_t) == 1:
            out_t = [out_t[0], out_t[0]]
            out_v = [out_v[0], out_v[0]]
        return out_t, out_v

    def _merge_history_for_chart(self, window_min, chart_ips, online_ips=None):
        """Combine DB readings and in-memory poll history for one device timeline."""
        cutoff = pd.Timestamp.now(tz='UTC') - pd.Timedelta(minutes=window_min)
        merged = {}
        names = {}
        online_ips = online_ips or set()

        def _add(ip, t, val, name=None):
            try:
                ts = self._history_ts_utc(t)
            except (TypeError, ValueError):
                return
            if ts < cutoff:
                return
            if name:
                names[ip] = name
            merged.setdefault(ip, {})[ts.value] = float(val)

        for ip, info in (self._db_history or {}).items():
            for t, val in info.get('points') or []:
                _add(ip, t, val, info.get('name') or ip)

        for ip in chart_ips | set(self.history.keys()):
            for t, val in self.history.get(ip, []):
                _add(ip, t, val, self.device_names.get(ip))

        out = {}
        for ip, pts_map in merged.items():
            if not pts_map:
                continue
            ordered = sorted(pts_map.items())
            times = [pd.Timestamp(v, tz='UTC') for v, _ in ordered]
            vals = [p for _, p in ordered]
            current_val = None
            if ip in online_ips:
                live = (self.device_data or {}).get(ip)
                if live and live.get('power_W') is not None:
                    try:
                        current_val = float(live['power_W'])
                    except (TypeError, ValueError):
                        current_val = None
            times, vals = self._finalize_history_series(
                times, vals, online=(ip in online_ips), current_val=current_val,
            )
            out[ip] = {
                'name': self.device_names.get(ip, names.get(ip, ip)),
                'times': times,
                'vals': vals,
            }
        return out

    @staticmethod
    def _rows_to_tasmota_history(rows):
        history = {}
        for ts_str, ip, name, power in rows:
            if ip is None or power is None:
                continue
            if isinstance(ts_str, str):
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                except ValueError:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        else:
                            ts = ts.astimezone(timezone.utc)
                    except Exception:
                        continue
            else:
                ts = ts_str
                if isinstance(ts, datetime):
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    else:
                        ts = ts.astimezone(timezone.utc)
                else:
                    continue
            if ip not in history:
                history[ip] = {"name": name or ip, "points": []}
            history[ip]["points"].append((ts, float(power)))
        return history

    def _get_db_params(self):
        """Return (backend_key, params) for tasmota_readings queries, or None."""
        cfg = self._resolve_history_db_config()
        if cfg is None:
            return None
        return cfg["fetch_backend"], cfg["fetch_params"]

    def _fetch_db_history(self, window_minutes):
        """Query tasmota_readings from the configured database for the history chart."""
        logger = getattr(self.dash, "data_logger", None) if self.dash else None
        if logger is not None and (
            logger.sqlite_enabled or logger.mysql_enabled or logger.pg_enabled
        ):
            try:
                rows = logger.query_tasmota_power_history(window_minutes)
                hist = self._rows_to_tasmota_history(rows)
                if self._history_points_count(hist) > 0:
                    return hist
            except Exception as e:
                _log.warn("Tasmota", f"DataLogger history query: {e}")

        db = self._get_db_params()
        if db is None:
            return {}
        backend, params = db
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        q = (
            "SELECT timestamp, device_ip, device_name, power_w "
            "FROM tasmota_readings WHERE timestamp >= %s "
            "ORDER BY timestamp ASC"
        )
        try:
            if backend == "sqlite":
                conn = sqlite3.connect(params["path"])
                try:
                    cur = conn.cursor()
                    cur.execute(q.replace("%s", "?"), (cutoff_str,))
                    rows = cur.fetchall()
                finally:
                    conn.close()
            elif backend == "mysql":
                import pymysql
                conn = pymysql.connect(**params, charset="utf8mb4", connect_timeout=3)
                try:
                    with conn.cursor() as cur:
                        cur.execute(q, (cutoff_str,))
                        rows = cur.fetchall()
                finally:
                    conn.close()
            else:
                import psycopg2
                conn = psycopg2.connect(**params, connect_timeout=3)
                try:
                    with conn.cursor() as cur:
                        cur.execute(q, (cutoff_str,))
                        rows = cur.fetchall()
                finally:
                    conn.close()
        except Exception as e:
            _log.warn("Tasmota", f"DB history error: {e}")
            return {}
        return self._rows_to_tasmota_history(rows)

    def auto_start(self):
        """One HTTP/broker poll for starting values; MQTT connects after that completes."""
        if self.use_mqtt_mode():
            self._bootstrap_then_mqtt = True
            self._stop_mqtt()
        else:
            self._apply_connection_mode()
        self.poll_all()

    def poll_all(self):
        if self.use_mqtt_mode() and not self.fetching:
            self.device_ips = ip_range(self.ip_start_edit.text(), self.ip_end_edit.text())
            self.fetching = True
            self.poll_btn.setEnabled(False)
            self._chart_shimmer.start()
            self.set_status("HTTP probe (MQTT subscribe active)…")
            threading.Thread(target=self._mqtt_http_probe_thread, daemon=True).start()
            return
        if self.fetching:
            self._auto_refresh_pending = True
            return
        self.fetching = True
        self._auto_refresh_pending = False
        self.poll_btn.setEnabled(False)
        self._chart_shimmer.start()
        self.device_ips = ip_range(self.ip_start_edit.text(), self.ip_end_edit.text())
        self.set_status("Polling Tasmota devices...")
        threading.Thread(target=self._poll_thread, daemon=True).start()

    def _mqtt_http_probe_thread(self):
        """One-shot HTTP read per device while MQTT is the live data source."""
        try:
            from concurrent.futures import ThreadPoolExecutor
            ips = self.device_ips
            results = dict(self.device_data)
            names = dict(self.device_names)
            firmwares = dict(self.device_firmware)

            def poll_one(ip):
                data = poll_tasmota_device(ip)
                nm = fw = None
                if data:
                    nm, fw = poll_tasmota_device_meta(ip)
                return ip, data, nm, fw

            with ThreadPoolExecutor(max_workers=12) as pool:
                for f in [pool.submit(poll_one, ip) for ip in ips]:
                    ip, data, nm, fw = f.result()
                    if data:
                        results[ip] = data
                        if nm:
                            names[ip] = nm
                        if fw:
                            firmwares[ip] = fw
            now = datetime.now(timezone.utc)
            for ip, data in results.items():
                self._record_history_point(ip, data.get("power_W", 0), when=now)
            self.device_names.update(names)
            self.device_firmware.update(firmwares)
            self.device_data = results
            online = len(results)
            total = len(ips)
            self._inv.invoke(
                lambda: self._finish_mqtt_http_probe(online, total)
            )
        except Exception as e:
            _log.warn("Tasmota", f"MQTT-mode HTTP probe failed: {e}")
            self._inv.invoke(lambda err=str(e): self._poll_failed(err))

    def _finish_mqtt_http_probe(self, online: int, total: int) -> None:
        self._chart_shimmer.stop()
        self.fetching = False
        self.poll_btn.setEnabled(True)
        ts = datetime.now().strftime("%H:%M:%S")
        if getattr(self, "_bootstrap_then_mqtt", False):
            self._bootstrap_then_mqtt = False
            self._start_mqtt()
            self.lbl_mqtt_status.setText("Status OK: Listening for MQTT Telemetry")
            self.lbl_mqtt_status.setStyleSheet("color: #a6e3a1; font-size: 11px;")
            self.status_label.setText(
                f"MQTT · starting values from HTTP · {online}/{total} · {ts}"
            )
        else:
            self.status_label.setText(f"MQTT · HTTP probe {online}/{total} · {ts}")
        self.status_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        self._update_total_power_banner()
        try:
            self._refresh_device_table_ui()
            self._plot_charts()
        except Exception as e:
            _log.exception("Tasmota", f"Probe display update failed: {e}")
        self._mqtt_last_notify = 0.0
        self._maybe_notify_data_updated()
        if self.dash is not None and hasattr(self.dash, "mark_tab_fresh"):
            self.dash.mark_tab_fresh(self)

    def _poll_thread(self):
        try:
            from concurrent.futures import ThreadPoolExecutor
            now = datetime.now(timezone.utc)
            ips = self.device_ips
            s = self._tasmota_settings()
            if s.value("tasmota/use_mqtt", False, type=bool):
                return
            use_broker = s.value("tasmota/use_powermon_broker", False, type=bool)
            broker_url = (s.value("tasmota/powermon_broker_url") or "").strip().rstrip("/")

            if use_broker and broker_url:
                try:
                    r = requests.get(f"{broker_url}/snapshot", timeout=15)
                    r.raise_for_status()
                    payload = r.json()
                except Exception as e:
                    _log.warn("Tasmota", f"Power monitor broker: {e}")
                    self._inv.invoke(lambda err=str(e): self._broker_poll_failed(err))
                    return

                devices = payload.get("devices") or {}
                allowed = set(ips)
                results = {}
                names = {}
                firmwares = {}
                for ip, d in devices.items():
                    if ip not in allowed:
                        continue
                    if not isinstance(d, dict):
                        continue
                    d = dict(d)
                    nm = d.pop("name", None)
                    if nm:
                        names[ip] = nm
                    if d.get("power_W") is None:
                        continue
                    results[ip] = d
                    self._record_history_point(ip, d.get("power_W", 0), when=now)
                if results:
                    def _meta_one(addr):
                        return addr, *poll_tasmota_device_meta(addr)

                    with ThreadPoolExecutor(max_workers=8) as pool:
                        for f in [pool.submit(_meta_one, ip) for ip in results]:
                            addr, nm, fw = f.result()
                            if nm:
                                names[addr] = nm
                            if fw:
                                firmwares[addr] = fw
                self.device_names.update(names)
                self.device_firmware.update(firmwares)
                self.device_data = results
                online = len(results)
                total = len(ips)
                max_window = self._history_minutes_steps[-1]
                self._db_hist_link = self._probe_history_db_link()
                win = max(max_window, self._history_window_minutes())
                self._db_history = (
                    self._fetch_db_history(win)
                    if self._db_hist_link.get("ok")
                    else {}
                )
                self._inv.invoke(lambda: self._update_display(online, total))
                return

            results = {}
            names = {}
            firmwares = {}

            def poll_one(ip):
                data = poll_tasmota_device(ip)
                nm = fw = None
                if data:
                    nm, fw = poll_tasmota_device_meta(ip)
                return ip, data, nm, fw

            with ThreadPoolExecutor(max_workers=12) as pool:
                for f in [pool.submit(poll_one, ip) for ip in ips]:
                    ip, data, nm, fw = f.result()
                    if data:
                        results[ip] = data
                        if nm:
                            names[ip] = nm
                        if fw:
                            firmwares[ip] = fw
                        self._record_history_point(ip, data['power_W'], when=now)
            self.device_names.update(names)
            self.device_firmware.update(firmwares)
            self.device_data = results
            online = len(results)
            total = len(ips)
            # Pre-fetch DB history on the background thread so charts don't block
            max_window = self._history_minutes_steps[-1]
            self._db_hist_link = self._probe_history_db_link()
            win = max(max_window, self._history_window_minutes())
            self._db_history = (
                self._fetch_db_history(win)
                if self._db_hist_link.get("ok")
                else {}
            )
            self._inv.invoke(lambda: self._update_display(online, total))
        except Exception as e:
            _log.warn("Tasmota", f"Background poll failed: {e}")
            self._inv.invoke(lambda err=str(e): self._poll_failed(err))

    def _poll_failed(self, msg):
        self._chart_shimmer.stop()
        self.fetching = False
        self.poll_btn.setEnabled(True)
        pending = getattr(self, '_auto_refresh_pending', False)
        self._auto_refresh_pending = False
        short = (msg or "").replace("\n", " ").strip()
        if len(short) > 140:
            short = short[:137] + "..."
        self.status_label.setText(f"poll error: {short}")
        if pending:
            QTimer.singleShot(300, self.poll_all)

    def _broker_poll_failed(self, msg):
        self._chart_shimmer.stop()
        self.fetching = False
        self.poll_btn.setEnabled(True)
        pending = getattr(self, '_auto_refresh_pending', False)
        self._auto_refresh_pending = False
        short = (msg or "").replace("\n", " ").strip()
        if len(short) > 140:
            short = short[:137] + "..."
        self.status_label.setText(f"broker error: {short}")
        if pending:
            QTimer.singleShot(300, self.poll_all)

    def _update_display(self, online, total):
        self._chart_shimmer.stop()
        self.fetching = False
        self.poll_btn.setEnabled(True)
        pending = getattr(self, '_auto_refresh_pending', False)
        self._auto_refresh_pending = False
        ts = datetime.now().strftime('%H:%M:%S')
        self.status_label.setText(f"{online}/{total} online | {ts}")
        self._update_total_power_banner()
        try:
            self._refresh_device_table_ui()
            self._plot_charts()
        except Exception as e:
            _log.exception("Tasmota", f"Display update failed: {e}")
        if self.on_data_updated:
            self.on_data_updated()
        if pending:
            QTimer.singleShot(300, self.poll_all)

    def _update_total_power_banner(self):
        active = {ip: d for ip, d in self.device_data.items() if d}
        if not active:
            self.total_power_big.setText("--")
            self.total_power_big.setStyleSheet("color: #6c7086;")
            for lbl in (self.ban_kw, self.ban_today, self.ban_total,
                        self.ban_devices, self.ban_top):
                lbl.setText("--")
            return
        tp = sum(d.get('power_W', 0) or 0 for d in active.values())
        total_today = sum(d.get('today_kWh', 0) or 0 for d in active.values())
        total_all = sum(d.get('total_kWh', 0) or 0 for d in active.values())
        top_ip = max(active, key=lambda ip: active[ip].get('power_W', 0) or 0)
        top_name = self.device_names.get(top_ip, top_ip)
        top_w = active[top_ip].get('power_W', 0) or 0

        col = '#f38ba8' if tp > 2000 else '#fab387' if tp > 800 else '#a6e3a1'
        self.total_power_big.setText(f"{tp:.0f} W")
        self.total_power_big.setStyleSheet(f"color: {col};")
        self.ban_kw.setText(f"{tp / 1000:.2f}")
        self.ban_today.setText(f"{total_today:.2f}")
        self.ban_total.setText(f"{total_all:.1f}")
        self.ban_devices.setText(f"{len(active)} / {len(self.device_ips)}")
        self.ban_top.setText(f"{top_name}  {top_w:.0f}W")

    def _tasmota_lock_action_btn(self, btn, width_px):
        """Force a fixed outer width (code + QSS) so row refresh cannot stretch it."""
        w = max(1, int(width_px))
        btn.setFixedWidth(w)
        btn.setMinimumWidth(w)
        btn.setMaximumWidth(w)
        btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _measure_tasmota_action_btn_h(self) -> int:
        """Natural height of a fully-formed action button (no clipped labels).

        Uses the real button's sizeHint under the display font and compact
        padding, so shrinking rows can never squash the labels away.
        """
        probe = QPushButton("Diagnose")
        try:
            probe.setProperty("tasmotaAction", True)
            probe.setFont(self._tasmota_action_font)
            _apply_primary_button_style(probe)
            probe.setStyleSheet(
                probe.styleSheet()
                + _tasmota_table_action_btn_qss(self._tasmota_btn_w)
            )
            probe.ensurePolished()
            hint = int(probe.sizeHint().height())
        except Exception:
            hint = 0
        finally:
            probe.deleteLater()
        return max(_TASMOTA_ACTION_BTN_MIN_H, hint)

    def _tasmota_min_row_h(self) -> int:
        """Row height that still leaves the action buttons fully formed."""
        btn_h = int(
            getattr(self, "_tasmota_action_btn_h", 0) or _TASMOTA_ACTION_BTN_MIN_H
        )
        return btn_h + _TASMOTA_ACTION_ROW_GAP

    def _tasmota_sync_action_row_heights(self, wrap, row_h: int) -> None:
        """In-table buttons: row height minus 2 px (1 px gap above/below).

        Never goes below the button's natural height — a squashed button clips
        its label, which is worse than a slightly tighter row gap.
        """
        if wrap is None:
            return
        row_h = max(1, int(row_h))
        btn_min = int(
            getattr(self, "_tasmota_action_btn_h", 0) or _TASMOTA_ACTION_BTN_MIN_H
        )
        btn_h = max(btn_min, row_h - _TASMOTA_ACTION_ROW_GAP)
        lay = wrap.layout()
        if lay is not None:
            lay.setContentsMargins(0, 1, 0, 1)
            lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        # Pin the cell widget to the row — otherwise Qt sizes the row from the
        # widget's old height (~54 px) and only ~4 rows fit in the viewport.
        wrap.setFixedHeight(row_h)
        wrap.setMaximumHeight(row_h)
        wrap.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        for btn in wrap.findChildren(QPushButton):
            btn.setFixedHeight(btn_h)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _tasmota_style_toggle_btn(self, toggle, relay_on, ip, *, reachable=True):
        """State-coloured Toggle — not the shared primary green."""
        w = self._tasmota_btn_w
        toggle.setProperty(PRIMARY_BUTTON_EXEMPT, True)
        toggle.setProperty("tasmotaAction", True)
        toggle.setProperty("tasmotaToggle", True)
        toggle.style().unpolish(toggle)
        toggle.style().polish(toggle)
        self._tasmota_lock_action_btn(toggle, w)
        toggle.setFont(self._tasmota_action_font)
        toggle.setEnabled(bool(reachable))
        toggle_qss, hint = _tasmota_toggle_btn_qss(relay_on, reachable=reachable)
        toggle.setStyleSheet(toggle_qss + _tasmota_table_action_btn_qss(w))
        toggle.setToolTip(f"Send Power Toggle to {ip} ({hint})")

    def _tasmota_make_action_btn(self, label, object_name, ip, tooltip, on_click):
        """One of Probe / Web UI / Diagnose / Toggle — identical size and style."""
        w = self._tasmota_btn_w
        btn = QPushButton(label)
        btn.setObjectName(object_name)
        btn.setProperty("tasmotaAction", True)
        btn.setFont(self._tasmota_action_font)
        self._tasmota_lock_action_btn(btn, w)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _apply_primary_button_style(btn)
        btn.setStyleSheet(btn.styleSheet() + _tasmota_table_action_btn_qss(w))
        btn.setToolTip(tooltip)
        btn.clicked.connect(on_click)
        return btn

    def _tasmota_row_action_widget(self, ip, relay_on=None, *, reachable=True):
        """Probe, Web UI, Diagnose, Toggle — equal width; Toggle is state-coloured."""
        wrap = QWidget()
        wrap.setObjectName("tasmotaActionRow")
        # Minimum (not Expanding) so the cell does not stretch Toggle to fill.
        wrap.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        wrap.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 1, 0, 1)
        lay.setSpacing(4)

        b_probe = self._tasmota_make_action_btn(
            "Probe", "tasmotaProbeBtn", ip,
            f"Re-poll {ip} only (Status 8 + Power)",
            partial(self._tasmota_probe_one, ip),
        )
        b_web = self._tasmota_make_action_btn(
            "Web UI", "tasmotaWebBtn", ip,
            f"Open http://{ip}/ in Firefox/Chromium (or copy URL if launch fails)",
            partial(self._tasmota_open_web_ui, ip),
        )
        b_diag = self._tasmota_make_action_btn(
            "Diagnose", "tasmotaDiagnoseBtn", ip,
            f"Device health for {ip}: connectivity, WiFi, reboots, MQTT topics, CPU load",
            partial(self._tasmota_diagnose_one, ip),
        )
        b_toggle = QPushButton("Toggle")
        b_toggle.setObjectName("tasmotaToggleBtn")
        b_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        b_toggle.clicked.connect(partial(self._tasmota_toggle_one, ip))
        self._tasmota_style_toggle_btn(b_toggle, relay_on, ip, reachable=reachable)

        lay.addWidget(b_probe, 0)
        lay.addWidget(b_web, 0)
        lay.addWidget(b_diag, 0)
        lay.addSpacing(_TASMOTA_TOGGLE_LEADING_GAP)
        lay.addWidget(b_toggle, 0)
        lay.addStretch(1)
        # Size buttons for the current row immediately — waiting for the next
        # resize pass left fresh rows with buttons taller than the row.
        row_h = int(getattr(self, "_tasmota_last_row_h", 0) or 0)
        if row_h <= 0:
            row_h = self._tasmota_min_row_h()
        self._tasmota_sync_action_row_heights(wrap, row_h)
        return wrap

    def _tasmota_probe_one(self, ip):
        ip = (ip or "").strip()
        if not ip:
            return
        _log.debug("Tasmota", f"Probe clicked for {ip}")
        self.set_status(f"Tasmota: probing {ip}…")
        threading.Thread(target=self._tasmota_probe_one_thread, args=(ip,), daemon=True).start()

    def _tasmota_probe_one_thread(self, ip):
        data = poll_tasmota_device(ip, timeout=8)
        name = None
        firmware = None
        if data:
            name, firmware = poll_tasmota_device_meta(ip, timeout=8)

        def _merge():
            if data:
                self.device_data[ip] = data
                if name:
                    self.device_names[ip] = name
                if firmware:
                    self.device_firmware[ip] = firmware
                self.set_status(f"Tasmota: {ip} updated.")
            else:
                self.set_status(f"Tasmota: {ip} not reachable.")
            self._update_total_power_banner()
            try:
                self._refresh_device_table_ui()
                self._plot_charts()
            except Exception as e:
                _log.exception("Tasmota", f"Probe display update failed: {e}")
            if self.on_data_updated:
                self.on_data_updated()

        self._inv.invoke(_merge)

    def _tasmota_toggle_one(self, ip):
        ip = (ip or "").strip()
        if not ip:
            return
        _log.debug("Tasmota", f"Toggle clicked for {ip}")
        r = QMessageBox.question(
            self,
            "Toggle device",
            f"Send Power Toggle to {ip}?\n\n"
            "This flips the relay state on that Tasmota device.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if r != QMessageBox.Yes:
            return
        self.set_status(f"Tasmota: toggling {ip}…")
        threading.Thread(target=self._tasmota_toggle_one_thread, args=(ip,), daemon=True).start()

    def _tasmota_toggle_one_thread(self, ip):
        j = tasmota_send_cmnd(ip, "Power Toggle", timeout=8)
        data = poll_tasmota_device(ip, timeout=8)

        def _done():
            if j is not None:
                self.set_status(f"Tasmota: toggle sent to {ip}.")
                _log.info("Tasmota", f"Toggle OK for {ip}: {j!r}")
            else:
                self.set_status(f"Tasmota: toggle failed for {ip} (no response).")
                _log.warn("Tasmota", f"Toggle failed for {ip} (no JSON response)")
            if data:
                self.device_data[ip] = data
            self._update_total_power_banner()
            try:
                self._refresh_device_table_ui()
                self._plot_charts()
            except Exception as e:
                _log.exception("Tasmota", f"Toggle display update failed: {e}")
            if self.on_data_updated:
                self.on_data_updated()

        self._inv.invoke(_done)

    def _tasmota_open_web_ui(self, ip):
        from energy_dashboard.dialogs.map_picker import _open_http_url

        addr = (ip or '').strip()
        if not addr:
            return
        _log.debug("Tasmota", f"Web UI clicked for {addr}")
        parent = self.window() or self
        ok = _open_http_url(
            f'http://{addr}/', parent=parent, title=f'Tasmota {addr}', modal=False,
        )
        if not ok:
            self.set_status(f"Tasmota: invalid URL for {addr}")
        else:
            self.set_status(f"Tasmota: Web UI opened for {addr}")

    def _tasmota_diagnose_one(self, ip):
        ip = (ip or "").strip()
        if not ip:
            return
        _log.debug("Tasmota", f"Diagnose clicked for {ip}")
        self.set_status(f"Tasmota: diagnosing {ip}…")
        threading.Thread(
            target=self._tasmota_diagnose_one_thread,
            args=(ip,),
            daemon=True,
        ).start()

    def _tasmota_diagnose_one_thread(self, ip: str):
        try:
            health = fetch_tasmota_device_health(
                ip,
                timeout=8.0,
                cached_row=self.device_data.get(ip),
                app_uses_mqtt=self.use_mqtt_mode(),
            )
            self._inv.invoke(lambda: self._show_tasmota_diagnose_dialog(health))
        except Exception as exc:
            _log.error("Tasmota", f"Diagnose failed for {ip}: {exc}")
            self._inv.invoke(
                lambda: self.set_status(f"Tasmota: diagnose failed for {ip} — {exc}")
            )

    def _show_tasmota_diagnose_dialog(self, health: TasmotaDeviceHealth) -> None:
        ip = health.ip
        if health.reachable:
            self.set_status(f"Tasmota: health check OK for {ip}")
        else:
            self.set_status(f"Tasmota: {ip} unreachable")
        dlg = _TasmotaDiagnoseDialog(health, self.window() or self)
        dlg.exec()

    def _tasmota_device_tree_ips(self, ips):
        """Split scan-order IPs evenly across the left/right device tables."""
        mid = (len(ips) + 1) // 2
        return ips[:mid], ips[mid:]

    def _update_table(self):
        left_ips, right_ips = self._tasmota_device_tree_ips(self.device_ips)
        self._sync_tasmota_device_tree(self.tree_left, left_ips)
        self._sync_tasmota_device_tree(self.tree_right, right_ips)

    def _sync_tasmota_device_tree(self, tree, ips):
        """Update rows in place so action-button widgets are not recreated every poll."""
        while tree.topLevelItemCount() > len(ips):
            tree.takeTopLevelItem(tree.topLevelItemCount() - 1)

        for i, ip in enumerate(ips):
            if i >= tree.topLevelItemCount():
                item = QTreeWidgetItem([''] * 10)
                item.setData(0, Qt.ItemDataRole.UserRole, ip)
                tree.addTopLevelItem(item)
                data = self.device_data.get(ip)
                ro = data.get('relay_on') if data else None
                tree.setItemWidget(
                    item, 9,
                    self._tasmota_row_action_widget(ip, ro, reachable=data is not None),
                )
            else:
                item = tree.topLevelItem(i)
                prev_ip = item.data(0, Qt.ItemDataRole.UserRole)
                if prev_ip != ip:
                    item.setData(0, Qt.ItemDataRole.UserRole, ip)
                    data = self.device_data.get(ip)
                    ro = data.get('relay_on') if data else None
                    tree.setItemWidget(
                        item, 9,
                        self._tasmota_row_action_widget(ip, ro, reachable=data is not None),
                    )
                else:
                    self._refresh_tasmota_toggle_style(tree, item, ip)
            self._set_tasmota_item_cells(item, ip)

    def _refresh_tasmota_toggle_style(self, tree, item, ip):
        """Refresh Toggle colour, enabled state, and tooltip without rebuilding the row."""
        wrap = tree.itemWidget(item, 9)
        if wrap is None:
            return
        toggle = wrap.findChild(QPushButton, "tasmotaToggleBtn")
        if toggle is None:
            return
        data = self.device_data.get(ip)
        ro = data.get('relay_on') if data else None
        self._tasmota_style_toggle_btn(
            toggle, ro, ip, reachable=data is not None,
        )

    def _set_tasmota_item_cells(self, item, ip):
        off_grey = QColor('#6c7086')
        data = self.device_data.get(ip)
        name = self.device_names.get(ip, ip)
        fw = self.device_firmware.get(ip, '—')
        if data:
            ro = data.get('relay_on')
            if ro is True:
                state_txt, state_col = 'ON', QColor('#a6e3a1')
            elif ro is False:
                state_txt, state_col = 'OFF', QColor('#f38ba8')
            else:
                state_txt, state_col = '—', off_grey
            cols = [
                state_txt, name, ip, fw,
                f"{data.get('power_W', 0) or 0:.0f}",
                f"{data.get('voltage_V', 0) or 0:.0f}",
                f"{data.get('current_A', 0) or 0:.2f}",
                f"{data.get('today_kWh', 0) or 0:.2f}",
                f"{data.get('total_kWh', 0) or 0:.1f}",
                '',
            ]
            item.setForeground(0, QBrush(state_col))
        else:
            cols = ['—', name, ip, '—', '--', '--', '--', '--', '--', '']
            item.setForeground(0, QBrush(off_grey))
        for c, val in enumerate(cols):
            item.setText(c, val)

    def _fill_tasmota_device_tree(self, tree, ips):
        """Legacy full rebuild — prefer _sync_tasmota_device_tree (keeps action widgets)."""
        tree.clear()
        for ip in ips:
            item = QTreeWidgetItem([''] * 10)
            item.setData(0, Qt.ItemDataRole.UserRole, ip)
            tree.addTopLevelItem(item)
            data = self.device_data.get(ip)
            ro = data.get('relay_on') if data else None
            tree.setItemWidget(
                item, 9,
                self._tasmota_row_action_widget(ip, ro, reachable=data is not None),
            )
            self._set_tasmota_item_cells(item, ip)

    @staticmethod
    def _hist_step_value_at(xn, yn, x):
        """Step-hold power (W) at time *x* for a history trace."""
        xn = np.asarray(xn, dtype=float)
        yn = np.asarray(yn, dtype=float)
        if xn.size == 0 or yn.size == 0:
            return float('nan')
        mask = ~np.isnan(yn)
        if not mask.any():
            return float('nan')
        xn = xn[mask]
        yn = yn[mask]
        if x < float(xn[0]) or x > float(xn[-1]):
            return float('nan')
        idx = int(np.searchsorted(xn, x, side='right') - 1)
        idx = max(0, min(idx, len(yn) - 1))
        return float(yn[idx])

    @staticmethod
    def _tasmota_series_energy_kwh(times_utc, vals_w):
        """Trapezoidal ∫P dt over the series (W → kWh)."""
        if len(times_utc) < 2 or len(vals_w) < 2:
            return None
        trap = getattr(np, 'trapezoid', None) or np.trapz
        t_h = np.array([t.timestamp() / 3600.0 for t in times_utc], dtype=float)
        w = np.asarray(vals_w, dtype=float)
        mask = ~np.isnan(w)
        if mask.sum() < 2:
            return None
        t_h = t_h[mask]
        w = w[mask]
        if t_h[-1] <= t_h[0]:
            return None
        wh = float(trap(w, t_h))
        return wh / 1000.0

    def _pick_tasmota_hist_series(self, x, y):
        """Return the history trace nearest the cursor (within a y tolerance)."""
        series = getattr(self, '_tasmota_hist_series', None) or []
        if not series or x is None or y is None:
            return None
        ymin, ymax = self.ax_hist.get_ylim()
        y_tol = max(50.0, (ymax - ymin) * 0.1)
        best = None
        best_d = None
        for s in series:
            xn = s.get('xnum')
            yn = s.get('vals')
            if xn is None or len(xn) < 2:
                continue
            if x < float(xn[0]) or x > float(xn[-1]):
                continue
            yi = self._hist_step_value_at(xn, yn, x)
            if math.isnan(yi):
                continue
            d = abs(yi - y)
            if d <= y_tol and (best_d is None or d < best_d):
                best_d = d
                best = {**s, 'interp_w': yi}
        return best

    def _tasmota_hist_hover_text(self, s, x):
        """Rich hover string for one Power History trace."""
        import matplotlib.dates as mdates
        import pytz
        london = pytz.timezone('Europe/London')
        dt = mdates.num2date(x)
        ts = pd.Timestamp(dt)
        if ts.tzinfo is None:
            t_local = ts.tz_localize('UTC').tz_convert(london)
        else:
            t_local = ts.tz_convert(london)
        t_str = t_local.strftime('%a %d %b %H:%M:%S')

        name = s.get('name') or s.get('ip', '?')
        ip = s.get('ip', '')
        w_at = s.get('interp_w', float('nan'))
        times = s.get('times') or []
        vals = s.get('vals') or []

        parts = [f"<b>{name}</b>"]
        if ip and ip != name:
            parts.append(ip)
        parts.append(f"@ {t_str}: <b>{w_at:.0f} W</b>")

        kwh = self._tasmota_series_energy_kwh(times, vals)
        if kwh is not None and len(vals) >= 2:
            w_arr = np.asarray(vals, dtype=float)
            w_arr = w_arr[~np.isnan(w_arr)]
            if len(w_arr):
                parts.append(
                    f"Window: ~{kwh:.3f} kWh · avg {w_arr.mean():.0f} W · peak {w_arr.max():.0f} W"
                )
        n_pts = len(vals)
        if n_pts >= 2:
            span_min = (times[-1] - times[0]).total_seconds() / 60.0
            parts.append(f"({n_pts} samples, {span_min:.0f} min span)")

        live = self.device_data.get(ip) if ip else None
        if live:
            try:
                parts.append(f"Today {float(live.get('today_kWh', 0)):.2f} kWh")
            except (TypeError, ValueError):
                pass
            try:
                parts.append(f"Total {float(live.get('total_kWh', 0)):.1f} kWh")
            except (TypeError, ValueError):
                pass

        return "  |  ".join(parts)

    def _tasmota_default_cursor_hint(self):
        return (
            "Hover a <b>Power History</b> line: device name, power at cursor, "
            "and estimated kWh over the visible window. "
            "Hover a <b>Current Power Draw</b> bar for that device."
        )

    def _hide_tasmota_chart_cursor(self):
        if hasattr(self, '_tasmota_cursor_label'):
            self._tasmota_cursor_label.setText(self._tasmota_default_cursor_hint())

    def _on_tasmota_chart_motion(self, event):
        if getattr(self, '_yaxis_drag', None):
            return
        lbl = getattr(self, '_tasmota_cursor_label', None)
        if lbl is None:
            return

        if event.inaxes is self.ax_hist and event.xdata is not None and event.ydata is not None:
            s = self._pick_tasmota_hist_series(float(event.xdata), float(event.ydata))
            if s is not None:
                lbl.setText(self._tasmota_hist_hover_text(s, float(event.xdata)))
                return
            lbl.setText(
                "Power History: move closer to a coloured trace "
                "(device name and usage appear when a line is selected)."
            )
            return

        if event.inaxes is self.ax_bar and event.ydata is not None:
            bars = getattr(self, '_tasmota_bar_bars', None) or []
            y = float(event.ydata)
            for bar, meta in bars:
                y0 = bar.get_y()
                h = bar.get_height()
                if y0 <= y <= y0 + h:
                    p = meta.get('power', 0)
                    lbl.setText(
                        f"<b>{meta.get('name', meta.get('ip', '?'))}</b>"
                        f"  |  {meta.get('ip', '')}  |  "
                        f"Now: <b>{p:.0f} W</b>"
                    )
                    return
            lbl.setText("Current Power Draw: hover a bar to see the device.")
            return

        if event.inaxes not in (self.ax_hist, self.ax_bar):
            self._hide_tasmota_chart_cursor()

    def _plot_charts(self):
        import matplotlib.dates as mdates
        self._update_hist_db_status_label()
        self.ax_bar.clear()
        self.ax_hist.clear()
        self._tasmota_hist_series = []
        self._tasmota_bar_bars = []
        _style_ax_dark(self.ax_bar, self.fig)
        _style_ax_dark(self.ax_hist, self.fig)
        active = {ip: d for ip, d in self.device_data.items() if d}
        if not active:
            self.ax_bar.text(0.5, 0.5, 'No device data', transform=self.ax_bar.transAxes,
                             ha='center', va='center', fontsize=12, color='#6c7086')
            self.ax_hist.text(0.5, 0.5, 'No history yet', transform=self.ax_hist.transAxes,
                              ha='center', va='center', fontsize=12, color='#6c7086')
            self.ax_bar.format_coord = lambda xv, yv: "No devices — x would be watts, y would be device row"
            self.ax_hist.format_coord = lambda xv, yv: "No history — x would be time, y would be watts"
            self._finalize_tasmota_charts_layout()
            self.canvas.draw()
            return

        ordered_ips = [ip for ip in self.device_ips if ip in active]
        labels = [self.device_names.get(ip, ip) for ip in ordered_ips]
        powers = [active[ip].get('power_W', 0) or 0 for ip in ordered_ips]
        bar_meta = [
            {'ip': ip, 'name': self.device_names.get(ip, ip),
             'power': active[ip].get('power_W', 0) or 0}
            for ip in ordered_ips
        ]
        labels = list(reversed(labels))
        powers = list(reversed(powers))
        bar_meta = list(reversed(bar_meta))
        colors = ['#F44336' if p > 1000 else '#FF9800' if p > 200 else '#4CAF50' for p in powers]
        bars = self.ax_bar.barh(labels, powers, color=colors, edgecolor='none', alpha=0.85,
                                height=0.7)
        self._tasmota_bar_bars = list(zip(bars, bar_meta))
        self.ax_bar.set_xlabel('Power (W)', fontsize=10)
        self.ax_bar.set_title('Current Power Draw', fontsize=12, fontweight='bold', pad=8)
        self.ax_bar.grid(axis='x', color=_DARK_GRID, linewidth=0.4)
        self.ax_bar.tick_params(axis='y', labelsize=8)
        max_p = max(powers) if powers else 1
        for bar, val in zip(bars, powers):
            if val > 0:
                self.ax_bar.text(bar.get_width() + max_p * 0.02,
                                 bar.get_y() + bar.get_height() / 2,
                                 f'{val:.0f}W', va='center', fontsize=6,
                                 color=_DARK_TEXT)

        window_min = self._history_window_minutes()
        has_history = False
        import pytz
        _lon_fmt_tz = pytz.timezone('Europe/London')

        chart_ips = (
            set(ordered_ips)
            | set((self._db_history or {}).keys())
            | set(self.history.keys())
        )
        series = self._merge_history_for_chart(
            window_min, chart_ips, online_ips=set(active.keys()),
        )
        for ip, info in series.items():
            times = info['times']
            vals = info['vals']
            xnums = mdates.date2num(
                pd.DatetimeIndex(times).tz_convert('UTC').to_pydatetime(),
            )
            has_history = True
            name = info['name']
            self.ax_hist.plot(
                xnums, vals, label=name, linewidth=1.2, drawstyle='steps-post',
            )
            self._tasmota_hist_series.append({
                'ip': ip,
                'name': name,
                'times': times,
                'vals': vals,
                'xnum': np.asarray(xnums, dtype=float),
            })

        if has_history:
            self.ax_hist.set_ylabel('Power (W)', fontsize=10)
            has_db = bool(self._db_history)
            has_mem = any(len(self.history.get(ip, [])) > 0 for ip in active)
            if has_db and has_mem:
                src_tag = 'DB+live'
            elif has_db:
                src_tag = 'DB'
            else:
                src_tag = 'live'
            link = getattr(self, "_db_hist_link", None) or {}
            db_backend = link.get("backend")
            if db_backend:
                if link.get("ok"):
                    db_state = f" · {db_backend} ✓"
                else:
                    db_state = f" · {db_backend} ✗"
            else:
                db_state = ""
            # Apply the user's Y-axis cap (0 = auto). When capping, force
            # ymin to 0 so the visible range is unambiguous.
            cap_w = self._hist_y_cap_w()
            cap_tag = ''
            if cap_w > 0:
                self.ax_hist.set_ylim(0, cap_w)
                pin = getattr(self, 'cb_pin_hist_500', None) and self.cb_pin_hist_500.isChecked()
                cap_tag = f' · max {cap_w} W' + (' · pinned' if pin else '')
            end_u = pd.Timestamp.now(tz='UTC')
            start_u = end_u - pd.Timedelta(minutes=window_min)
            self.ax_hist.set_title(
                f'Power History ({self._format_window(window_min)}) '
                f'[{src_tag}{db_state}]{cap_tag}',
                fontsize=12, fontweight='bold', pad=8,
            )
            self.ax_hist.legend(
                loc='upper right', fontsize=6, ncol=2, framealpha=0.6,
                facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT)
            self.ax_hist.grid(axis='y', color=_DARK_GRID, linewidth=0.4)
            self.ax_hist.set_xlim(
                mdates.date2num(start_u.to_pydatetime()),
                mdates.date2num(end_u.to_pydatetime()),
            )
            if window_min <= 30:
                self.ax_hist.xaxis.set_major_formatter(
                    mdates.DateFormatter('%H:%M:%S', tz=_lon_fmt_tz))
            elif window_min <= 240:
                self.ax_hist.xaxis.set_major_formatter(
                    mdates.DateFormatter('%H:%M', tz=_lon_fmt_tz))
            else:
                self.ax_hist.xaxis.set_major_formatter(
                    mdates.DateFormatter('%d/%m %H:%M', tz=_lon_fmt_tz))
            self.ax_hist.tick_params(axis='x', rotation=20)
        else:
            self.ax_hist.text(0.5, 0.5, 'Poll again to build history',
                              transform=self.ax_hist.transAxes, ha='center', va='center',
                              fontsize=11, color='#6c7086')

        if has_history:
            _draw_6h_vertical_grid(self.ax_hist)
            _draw_day_date_labels(self.ax_hist)
        self.ax_bar.format_coord = lambda xv, yv: (
            f"Horizontal (x, W): {xv:.0f} — measured draw for the row at this height  |  "
            f"Vertical (y): {yv:.2f} — device band (labels on the left)"
        )
        self.ax_hist.format_coord = lambda xv, yv, tz=_lon_fmt_tz: _fmt_toolbar_time_y(
            xv, yv, tz, "W",
            "hover a trace for device name and window energy (see panel below chart)",
        )
        self._hide_tasmota_chart_cursor()
        self._finalize_tasmota_charts_layout()
        self.canvas.draw()

    def _on_tasmota_canvas_resize(self, _event):
        if not getattr(self, 'ax_hist', None) or not getattr(self, 'ax_bar', None):
            return
        if not self._tasmota_hist_series and not self._tasmota_bar_bars:
            return
        self._finalize_tasmota_charts_layout(redraw_only=True)

    def _finalize_tasmota_charts_layout(self, *, redraw_only=False):
        """Split charts at figure midpoint; bar chart uses left half with full y labels."""
        mid = 0.5
        gap = 0.022
        fig_r = 0.98
        label_pad = 0.01
        min_bar_w = 0.12
        bar_right = mid - gap / 2.0
        hist_left = mid + gap / 2.0
        bar_left = 0.02

        if redraw_only:
            pb = self.ax_bar.get_position()
            y0, h = pb.y0, pb.height
        else:
            # Fixed margins — do not use fig.tight_layout(). On a short chart
            # pane it cannot grow top/bottom enough for titles + rotated x
            # labels and emits UserWarning (often attributed to a later
            # processEvents when the canvas redraw runs).
            self.fig.subplots_adjust(left=0.02, right=0.98, top=0.90, bottom=0.16)
            pb = self.ax_bar.get_position()
            y0, h = pb.y0, pb.height

        self.ax_bar.set_position([bar_left, y0, max(min_bar_w, bar_right - bar_left), h])
        self.ax_hist.set_position([hist_left, y0, max(0.08, fig_r - hist_left), h])

        if redraw_only:
            self.canvas.draw_idle()
            return

        self.fig.canvas.draw()
        renderer = self.fig.canvas.get_renderer()
        tbb = self.ax_bar.get_tightbbox(renderer).transformed(
            self.fig.transFigure.inverted()
        )
        if tbb.x0 < label_pad:
            shift = label_pad - tbb.x0
            pos = self.ax_bar.get_position()
            new_w = pos.width - shift
            # Keep bar chart right edge at bar_right; only shrink if still usable
            if new_w >= 0.04:
                self.ax_bar.set_position([pos.x0 + shift, pos.y0, new_w, pos.height])

        # Shift bar chart 30px left (normalized: 30.0 / figure width in pixels).
        fw = self.fig.get_figwidth()
        dpi = self.fig.dpi
        dx_fig = 30.0 / max(fw * dpi, 1.0)
        pos = self.ax_bar.get_position()
        self.ax_bar.set_position([max(0.0, pos.x0 - dx_fig), pos.y0, pos.width, pos.height])

    def _apply_tasmota_tree_heights(self):
        """Fill the table pane and stretch rows so they share the assigned height."""
        if getattr(self, "_tasmota_row_fit_lock", False):
            return
        if not hasattr(self, "tree_left") or not hasattr(self, "tree_right"):
            return
        min_row = self._tasmota_min_row_h()
        self._tasmota_row_fit_lock = True
        try:
            QApplication.processEvents()
            for tr in (self.tree_left, self.tree_right):
                tr.setMaximumHeight(16777215)
                header_h = tr.header().height() if tr.header() is not None else 0
                frame = tr.frameWidth() * 2
                hsb = 0
                if tr.horizontalScrollBar().isVisible():
                    hsb = tr.horizontalScrollBar().sizeHint().height()
                body = tr.viewport().height()
                computed_body = max(0, tr.height() - header_h - frame - hsb)
                if computed_body > 0:
                    body = computed_body
                if body <= 0:
                    continue
                tree_rows = max(tr.topLevelItemCount(), 1)
                row_h = max(min_row, body // tree_rows)
                if row_h * tree_rows > body:
                    row_h = min_row
                    tr.setVerticalScrollBarPolicy(
                        Qt.ScrollBarPolicy.ScrollBarAsNeeded
                    )
                else:
                    tr.setVerticalScrollBarPolicy(
                        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                    )
                hint = QSize(0, row_h)
                self._tasmota_last_row_h = row_h
                for i in range(tr.topLevelItemCount()):
                    item = tr.topLevelItem(i)
                    for col in range(tr.columnCount()):
                        item.setSizeHint(col, hint)
                    wrap = tr.itemWidget(item, 9)
                    if wrap is not None:
                        self._tasmota_sync_action_row_heights(wrap, row_h)
                tr.doItemsLayout()
            floor = (
                self.tree_left.header().height()
                + min_row * _TASMOTA_VISIBLE_ROWS
                + 8
            )
            self.tree_left.setMinimumHeight(floor)
            self.tree_right.setMinimumHeight(floor)
        finally:
            self._tasmota_row_fit_lock = False


__all__ = [n for n in globals() if not n.startswith('__')]
