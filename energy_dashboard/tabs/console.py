"""
Energy Dashboard — `tabs/console.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.core.logging import LogManager, ensure_log_manager, get_log_manager, _log


class ConsoleTab(QWidget):
    """Live console log viewer with per-level filtering (checkboxes, all on by default)."""

    _LEVEL_COLORS = {
        LogManager.DEBUG: "#6c7086",
        LogManager.INFO:  "#89b4fa",
        LogManager.WARN:  "#fab387",
        LogManager.ERROR: "#f38ba8",
    }

    _LEVEL_OPTIONS = (
        ("Debug", LogManager.DEBUG),
        ("Info", LogManager.INFO),
        ("Warn", LogManager.WARN),
        ("Error", LogManager.ERROR),
    )

    _RS485_SOURCE = "RS485"

    def __init__(self, dashboard=None):
        super().__init__()
        ensure_log_manager()
        self.dash = dashboard
        self._level_checks = {}
        self._auto_scroll = True
        self._rendered_visible_count = 0
        self._hb_busy = False
        self.build_ui()
        get_log_manager()._new_entry.connect(self._on_new_entry)
        self._refresh()

    def build_ui(self):
        self.setStyleSheet(f"background-color: {_DARK_BG};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Show:"))
        for text, level in self._LEVEL_OPTIONS:
            cb = QCheckBox(text)
            cb.setChecked(True)
            cb.toggled.connect(self._on_filter_changed)
            self._level_checks[level] = cb
            toolbar.addWidget(cb)

        toolbar.addSpacing(12)
        self._rs485_only_chk = QCheckBox("RS485 only")
        self._rs485_only_chk.setChecked(False)
        self._rs485_only_chk.setToolTip(
            "Show only Modbus / RS485 probe lines (source RS485). "
            "Level filters still apply — keep Debug on for per-register tries."
        )
        self._rs485_only_chk.toggled.connect(self._on_filter_changed)
        toolbar.addWidget(self._rs485_only_chk)

        toolbar.addSpacing(12)
        self._rs485_hb_chk = QCheckBox("RS485 heartbeat")
        self._rs485_hb_chk.setToolTip(
            "Ping the RS485 gateway every N seconds (one TCP connect + one "
            "holding-register read). Logs under source RS485. Uses Setup Modbus "
            "mode / LAN IP / port / unit."
        )
        self._rs485_hb_chk.toggled.connect(self._on_rs485_heartbeat_toggled)
        toolbar.addWidget(self._rs485_hb_chk)
        self._rs485_hb_s = QSpinBox()
        self._rs485_hb_s.setRange(10, 120)
        self._rs485_hb_s.setValue(30)
        self._rs485_hb_s.setSuffix(" s")
        self._rs485_hb_s.setToolTip("Heartbeat interval")
        self._rs485_hb_s.setMaximumWidth(90)
        self._rs485_hb_s.valueChanged.connect(self._on_rs485_heartbeat_interval)
        toolbar.addWidget(self._rs485_hb_s)

        toolbar.addSpacing(20)
        self._auto_scroll_chk = QCheckBox("Auto-scroll")
        self._auto_scroll_chk.setChecked(True)
        self._auto_scroll_chk.setToolTip(
            "When on, keep the newest log lines in view. Turn off to freeze while reading."
        )
        self._auto_scroll_chk.toggled.connect(self._on_auto_scroll_toggled)
        toolbar.addWidget(self._auto_scroll_chk)

        toolbar.addSpacing(10)
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(60)
        clear_btn.setToolTip(
            f"Clear the in-memory log AND wipe the persisted on-disk log at:\n"
            f"{_CONSOLE_LOG_PATH}"
        )
        clear_btn.clicked.connect(self._clear)
        toolbar.addWidget(clear_btn)

        toolbar.addSpacing(10)
        self._count_label = QLabel("0 entries")
        self._count_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        toolbar.addWidget(self._count_label)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setAcceptRichText(True)
        self._text.setFont(QFont('Courier', 9))
        self._text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        _apply_dark_log_view(self._text, object_name='consoleLogView')
        layout.addWidget(self._text)

        self._hb_timer = QTimer(self)
        self._hb_timer.timeout.connect(self._rs485_heartbeat_tick)
        self._load_rs485_heartbeat_settings()

    def _active_levels(self):
        return [
            level for level, cb in self._level_checks.items()
            if cb.isChecked()
        ]

    def _rs485_only(self) -> bool:
        chk = getattr(self, "_rs485_only_chk", None)
        return bool(chk is not None and chk.isChecked())

    def _visible_entries(self):
        levels = self._active_levels()
        if not levels:
            return []
        entries = get_log_manager().get_entries(levels=levels)
        if self._rs485_only():
            want = self._RS485_SOURCE.upper()
            entries = [
                e for e in entries
                if str(e.get("source", "")).strip().upper() == want
            ]
        return entries

    def _on_filter_changed(self, _checked=False):
        self._refresh()

    def _console_settings(self):
        return QSettings("PowerModel", "EnergyDashboard2")

    def _save_rs485_heartbeat_settings(self):
        s = self._console_settings()
        s.setValue("console/rs485_heartbeat", bool(self._rs485_hb_chk.isChecked()))
        s.setValue("console/rs485_heartbeat_s", int(self._rs485_hb_s.value()))
        s.sync()

    def _load_rs485_heartbeat_settings(self):
        s = self._console_settings()
        on = bool(s.value("console/rs485_heartbeat", False, type=bool))
        try:
            interval = int(s.value("console/rs485_heartbeat_s", 30))
        except (TypeError, ValueError):
            interval = 30
        self._rs485_hb_s.blockSignals(True)
        self._rs485_hb_s.setValue(max(10, min(120, interval)))
        self._rs485_hb_s.blockSignals(False)
        self._rs485_hb_chk.blockSignals(True)
        self._rs485_hb_chk.setChecked(on)
        self._rs485_hb_chk.blockSignals(False)
        if on:
            self._start_rs485_heartbeat(immediate=True)

    def _on_rs485_heartbeat_toggled(self, checked: bool) -> None:
        self._save_rs485_heartbeat_settings()
        if checked:
            self._start_rs485_heartbeat(immediate=True)
        else:
            self._hb_timer.stop()
            _log.info("RS485", "Heartbeat stopped")

    def _on_rs485_heartbeat_interval(self, _value: int) -> None:
        self._save_rs485_heartbeat_settings()
        if self._rs485_hb_chk.isChecked():
            self._start_rs485_heartbeat(immediate=False)

    def _start_rs485_heartbeat(self, *, immediate: bool) -> None:
        ms = max(10, int(self._rs485_hb_s.value())) * 1000
        self._hb_timer.setInterval(ms)
        if not self._hb_timer.isActive():
            self._hb_timer.start()
            _log.info("RS485", f"Heartbeat every {ms // 1000}s (Setup Modbus target)")
        else:
            self._hb_timer.start()
        if immediate:
            QTimer.singleShot(0, self._rs485_heartbeat_tick)

    def _modbus_cfg(self) -> dict:
        dash = self.dash
        pt = getattr(dash, "parameters_tab", None) if dash else None
        if pt is not None and getattr(pt, "cb_growatt_modbus", None) is not None:
            host = (
                pt.ed_growatt_lan_ip.text().strip()
                or pt.ed_growatt_wifi_ip.text().strip()
            )
            return {
                "mode": pt.cb_growatt_modbus.currentData() or "off",
                "tcp_host": host,
                "tcp_port": int(pt.sp_growatt_modbus_tcp.value()),
                "serial_path": pt.ed_growatt_modbus_serial.text().strip(),
                "baud": int(pt.sp_growatt_modbus_baud.value()),
                "unit": int(pt.sp_growatt_modbus_unit.value()),
            }
        p = getattr(dash, "app_params", None) if dash else None
        from energy_dashboard.config import growatt_modbus_tcp_host
        return {
            "mode": getattr(p, "growatt_modbus_mode", "off") if p else "off",
            "tcp_host": growatt_modbus_tcp_host(p) if p else "",
            "tcp_port": getattr(p, "growatt_modbus_tcp_port", 502) if p else 502,
            "serial_path": getattr(p, "growatt_modbus_serial_path", "") if p else "",
            "baud": getattr(p, "growatt_modbus_baud", 9600) if p else 9600,
            "unit": getattr(p, "growatt_modbus_unit", 1) if p else 1,
        }

    def _rs485_heartbeat_tick(self):
        if not self._rs485_hb_chk.isChecked() or self._hb_busy:
            return
        cfg = self._modbus_cfg()
        if (cfg.get("mode") or "off").lower() not in ("tcp", "tcp_rtu", "serial"):
            _log.debug("RS485", "Heartbeat skipped — enable Modbus in Setup")
            return
        self._hb_busy = True
        threading.Thread(target=self._rs485_heartbeat_worker, args=(cfg,), daemon=True).start()

    def _rs485_heartbeat_worker(self, cfg: dict) -> None:
        try:
            from energy_dashboard.modbus.command_sim import _growatt_modbus_heartbeat_sync
            _growatt_modbus_heartbeat_sync(
                cfg.get("mode"),
                cfg.get("tcp_host"),
                cfg.get("tcp_port"),
                cfg.get("serial_path"),
                cfg.get("baud"),
                cfg.get("unit"),
            )
        except Exception as exc:
            _log.warn("RS485", f"Heartbeat worker: {exc}")
        finally:
            self._hb_busy = False

    @staticmethod
    def _format_ts(entry):
        iso = entry.get('iso_ts')
        if iso:
            try:
                dt = datetime.fromisoformat(iso)
                if dt.date() == datetime.now().date():
                    return dt.strftime('%H:%M:%S.%f')[:-3]
                return dt.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                pass
        return entry.get('ts', '--:--:--.---')

    def _format_line(self, e):
        lvl = LogManager._LEVEL_LABELS.get(e["level"], "?")
        color = self._LEVEL_COLORS.get(e["level"], _DARK_TEXT)
        ts = html.escape(self._format_ts(e))
        src = html.escape(str(e.get("source", "")))
        msg = html.escape(str(e.get("msg", "")))
        msg = msg.replace("\n", "<br>")
        return (
            f'<span style="color:#585b70">{ts}</span> '
            f'<span style="color:{color};font-weight:bold">[{lvl}]</span> '
            f'<span style="color:#a6adc8">{src}:</span> '
            f'<span style="color:{color}">{msg}</span>'
        )

    def _on_auto_scroll_toggled(self, checked: bool) -> None:
        self._auto_scroll = bool(checked)
        if self._auto_scroll:
            self._scroll_to_bottom()

    def _append_log_html(self, line_html):
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(line_html + "<br>")
        self._text.setTextCursor(cursor)

    def _scroll_to_bottom(self):
        if not self._auto_scroll:
            return
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._text.setTextCursor(cursor)
        self._text.ensureCursorVisible()
        # Document height (and scrollbar max) update after the next layout pass;
        # setting the bar immediately after insertHtml often leaves the view short.
        QTimer.singleShot(0, self._force_scroll_bottom)

    def _force_scroll_bottom(self):
        if not self._auto_scroll:
            return
        sb = self._text.verticalScrollBar()
        sb.setValue(sb.maximum())
        # One more pass for wrapped / large HTML batches (e.g. full rebuild).
        QTimer.singleShot(0, lambda: sb.setValue(sb.maximum()) if self._auto_scroll else None)

    def _count_caption(self, n: int) -> str:
        if self._rs485_only():
            return f"{n} entries (RS485 only)"
        return f"{n} entries"

    def _on_new_entry(self):
        levels = self._active_levels()
        if not levels:
            self._text.clear()
            self._rendered_visible_count = 0
            self._count_label.setText("0 entries (all filters off)")
            return
        entries = self._visible_entries()
        if len(entries) < self._rendered_visible_count:
            # Filter tightened or log trimmed — rebuild.
            self._refresh()
            return
        if len(entries) == self._rendered_visible_count:
            return
        for e in entries[self._rendered_visible_count:]:
            self._append_log_html(self._format_line(e))
        self._rendered_visible_count = len(entries)
        self._count_label.setText(self._count_caption(len(entries)))
        self._scroll_to_bottom()

    def _refresh(self):
        levels = self._active_levels()
        if not levels:
            self._text.clear()
            self._rendered_visible_count = 0
            self._count_label.setText("0 entries (all filters off)")
            return
        entries = self._visible_entries()
        self._text.clear()
        if entries:
            self._text.setHtml("<br>".join(self._format_line(e) for e in entries))
        self._rendered_visible_count = len(entries)
        self._count_label.setText(self._count_caption(len(entries)))
        self._scroll_to_bottom()

    def _clear(self):
        get_log_manager().clear_persisted()
        self._text.clear()
        self._rendered_visible_count = 0
        self._refresh()
        self._count_label.setText(self._count_caption(0))


__all__ = [n for n in globals() if not n.startswith('__')]
