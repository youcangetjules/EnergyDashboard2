"""
Login fields for Connectivity architecture popups.

Each panel is the Setup & Info credential block for that one component.
Save and Test copy the values back onto Setup & Info and call the same
handlers, so the popup and the Setup tab stay one login.
"""
from __future__ import annotations

import json
from time import time as _now
from zoneinfo import ZoneInfo

from energy_dashboard.common import *

from datetime import datetime as _datetime
from energy_dashboard.ui.buttons import _apply_primary_button_style
from energy_dashboard.ui.styles import (
    apply_setup_info_line_field_motif,
    apply_spin_field_motif,
)

_FIELD_W = 200
_CLOUD_FIELD_W = 420
_PORT_W = 98
_BTN_W = 120

# Diagram box → which login block to show. Boxes with no Setup login are absent.
_BOX_LOGIN = {
    "growatt_cloud": "cloud",
    "grott": "grott",
    "emqx": "emqx",
    "tasmota": "tasmota",
    "inverter": "inverter",
    "modbus": "modbus",
    "modbus_lan": "modbus",
    "pvoutput": "pvoutput",
    "octopus": "octopus",
    "database": "database",
    "export": "database",
    "storage": "database",
}


def build_component_login(box_key: str, dash) -> QWidget | None:
    """Return the login panel for this diagram box, or None if it has no login."""
    kind = _BOX_LOGIN.get(str(box_key or ""))
    if not kind or dash is None:
        return None
    params = getattr(dash, "parameters_tab", None)
    if params is None and kind != "octopus":
        return None
    builders = {
        "cloud": _CloudLogin,
        "grott": _GrottLogin,
        "emqx": _EmqxLogin,
        "tasmota": _TasmotaLogin,
        "inverter": _InverterLogin,
        "modbus": _ModbusLogin,
        "pvoutput": _PvOutputLogin,
        "octopus": _OctopusLogin,
        "database": _DatabaseLogin,
    }
    cls = builders.get(kind)
    if cls is None:
        return None
    return cls(dash, params)


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setStyleSheet("color: #6c7086; font-size: 10px;")
    return lbl


def _status_label() -> QLabel:
    lbl = QLabel("")
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
    return lbl


_TEST_STALE_S = 3600
_TEST_KEY_PREFIX = "connectivity/last_test/"
_TEST_OK = "#a6e3a1"
_TEST_FAIL = "#f38ba8"
_TEST_STALE = "#fab387"
_TEST_BUSY = "#89b4fa"
_STALE_TEXT = "Connectivity - last OK (Stale >1hr since last test)"


def record_link_test(key: str, ok: bool, detail: str = "") -> None:
    """Remember the last Test result for a login panel (survives closing it)."""
    s = QSettings("PowerModel", "EnergyDashboard2")
    s.setValue(
        _TEST_KEY_PREFIX + str(key),
        json.dumps({
            "ok": bool(ok),
            "at": _now(),
            "detail": (detail or "")[:500],
        }),
    )


def _load_link_test(key: str) -> dict | None:
    s = QSettings("PowerModel", "EnergyDashboard2")
    raw = s.value(_TEST_KEY_PREFIX + str(key), "", type=str) or ""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "at" not in data:
        return None
    return data


def _test_when(ts: float) -> str:
    try:
        dt = _datetime.fromtimestamp(float(ts), ZoneInfo("Europe/London"))
    except (TypeError, ValueError, OSError):
        return ""
    return dt.strftime("%H:%M on %d %b")


class _TestStatement(QLabel):
    """Connectivity line on the same row as Test, at the right.

    A pass stays green until it is an hour old, then amber.
    """

    def __init__(self, key: str, parent=None):
        super().__init__("", parent)
        self._key = str(key)
        self._busy = False
        self.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.setWordWrap(False)
        self.setStyleSheet("color: #6c7086; font-size: 11px;")
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self.refresh)
        self.refresh()
        self._timer.start()

    def begin(self) -> None:
        self._busy = True
        self.setText("Connectivity — testing…")
        self.setToolTip("Test in progress")
        self.setStyleSheet(f"color: {_TEST_BUSY}; font-size: 11px;")

    def finish(self, ok: bool, detail: str = "") -> None:
        record_link_test(self._key, bool(ok), detail)
        self._busy = False
        self.refresh()

    def refresh(self) -> None:
        if self._busy:
            return
        data = _load_link_test(self._key)
        if not data:
            self.setText("")
            self.setToolTip("")
            return
        try:
            age = _now() - float(data.get("at") or 0)
        except (TypeError, ValueError):
            age = 0.0
        ok = bool(data.get("ok"))
        detail = str(data.get("detail") or "").strip()
        when = _test_when(float(data.get("at") or 0))
        tip = detail
        if when:
            tip = (f"{when}. {detail}" if detail else when).strip()
        if ok and age > _TEST_STALE_S:
            self.setText(_STALE_TEXT)
            self.setStyleSheet(f"color: {_TEST_STALE}; font-size: 11px;")
            self.setToolTip(tip or "Last successful test was more than an hour ago")
            return
        if ok:
            self.setText("Connectivity — OK")
            self.setStyleSheet(f"color: {_TEST_OK}; font-size: 11px;")
        else:
            self.setText("Connectivity — failed")
            self.setStyleSheet(f"color: {_TEST_FAIL}; font-size: 11px;")
        self.setToolTip(tip)


def _line(
    text: str,
    placeholder: str = "",
    *,
    secret: bool = False,
    width: int = _FIELD_W,
    expand: bool = False,
) -> QLineEdit:
    edit = QLineEdit(text or "")
    edit.setPlaceholderText(placeholder)
    if secret:
        edit.setEchoMode(QLineEdit.EchoMode.Password)
    apply_setup_info_line_field_motif(edit, width=width, expand=expand)
    return edit


def _port(value: int, lo: int = 1, hi: int = 65535) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(lo, hi)
    spin.setValue(int(value))
    apply_spin_field_motif(spin, width=_PORT_W)
    return spin


def _btn(text: str, slot, width: int = _BTN_W) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedWidth(width)
    btn.clicked.connect(slot)
    _apply_primary_button_style(btn)
    return btn


class _LoginPanel(QGroupBox):
    """Two-column credential grid: label | field | label | field, Save under the fields."""

    def __init__(self, title: str, hint: str, parent=None, *, test_key: str = ""):
        super().__init__(title, parent)
        self._lay = QVBoxLayout(self)
        self._lay.setSpacing(8)
        self._lay.addWidget(_hint(hint))
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(6)
        self._grid.setColumnMinimumWidth(0, 108)
        self._grid.setColumnMinimumWidth(2, 96)
        self._grid.setColumnStretch(1, 1)
        self._grid.setColumnStretch(3, 1)
        self._row = 0
        self._lay.addLayout(self._grid)
        self._note = _status_label()
        self._note.setVisible(False)
        self._lay.addWidget(self._note)
        self.statement = _TestStatement(test_key) if test_key else None
        # Older callers still write self.status; that is the left note, not the test line.
        self.status = self._note

    def add_pair(self, left: tuple[str, QWidget], right: tuple[str, QWidget] | None = None) -> None:
        r = self._row
        self._grid.addWidget(QLabel(left[0]), r, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._grid.addWidget(left[1], r, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if right is not None:
            self._grid.addWidget(QLabel(right[0]), r, 2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._grid.addWidget(right[1], r, 3, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._row += 1

    def add_wide(self, label: str, widget: QWidget) -> None:
        r = self._row
        self._grid.addWidget(QLabel(label), r, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._grid.addWidget(widget, r, 1, 1, 3, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._row += 1

    def add_buttons(self, *buttons: QPushButton) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for btn in buttons:
            row.addWidget(btn)
        row.addStretch(1)
        if self.statement is not None:
            row.addWidget(
                self.statement,
                0,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )
        self._grid.addLayout(row, self._row, 1, 1, 3)
        self._row += 1

    def note(self, text: str) -> None:
        self._note.setText(text)
        self._note.setVisible(bool(text))

    def begin_test(self) -> None:
        if self.statement is not None:
            self.statement.begin()

    def finish_test(self, ok: bool, detail: str = "") -> None:
        if self.statement is not None:
            try:
                self.statement.finish(ok, detail)
            except RuntimeError:
                record_link_test(self.statement._key, bool(ok), detail)


class _CloudLogin(_LoginPanel):
    def __init__(self, dash, params):
        super().__init__(
            "Growatt cloud login",
            "Same fields as Setup &amp; Info → <b>Growatt cloud login</b> "
            "(server.growatt.com). An API key avoids password rate-limit lockouts. "
            "<b>Test connection</b> checks login and a live inverter read.",
            test_key="cloud",
        )
        self._dash = dash
        self._params = params
        self.user = _line(
            params.ed_growatt_cloud_user.text(),
            "server.growatt.com username",
            width=_CLOUD_FIELD_W,
            expand=True,
        )
        self.password = _line(
            params.ed_growatt_cloud_pass.text(),
            "password",
            secret=True,
            width=_CLOUD_FIELD_W,
            expand=True,
        )
        self.token = _line(
            params.ed_growatt_cloud_token.text(),
            "API key (recommended)",
            secret=True,
            width=_CLOUD_FIELD_W,
            expand=True,
        )
        self.serial = _line(
            params.ed_growatt_cloud_serial.text(),
            "Optional inverter serial",
            width=_CLOUD_FIELD_W,
            expand=True,
        )
        self.add_pair(("Username:", self.user), ("Password:", self.password))
        self.add_pair(("API key:", self.token), ("Serial:", self.serial))
        self._test_btn = _btn("Test connection", self._test, 150)
        self.add_buttons(
            _btn("Save credentials", self._save, 150),
            self._test_btn,
        )

    def _push(self) -> None:
        p = self._params
        p.ed_growatt_cloud_user.setText(self.user.text())
        p.ed_growatt_cloud_pass.setText(self.password.text())
        p.ed_growatt_cloud_token.setText(self.token.text())
        p.ed_growatt_cloud_serial.setText(self.serial.text())

    def _save(self) -> None:
        self._push()
        self._params._save_growatt_cloud_credentials()
        self.note("Saved — same cloud login as Setup & Info.")

    def _test(self) -> None:
        self._push()
        gt = getattr(self._dash, "growatt_tab", None)
        if gt is None:
            self.note("Growatt Live Status tab is not available.")
            return
        # Drive the hidden Growatt credential holders used by authenticate().
        gt.username_edit.setText(self.user.text().strip())
        gt.password_edit.setText(self.password.text())
        gt.token_edit.setText(self.token.text().strip())
        gt.serial_edit.setText(self.serial.text().strip())
        self._test_btn.setEnabled(False)
        self.begin_test()

        def _done(ok: bool, detail: str) -> None:
            self._test_btn.setEnabled(True)
            self.finish_test(ok, detail or ("connected" if ok else "test failed"))

        gt._test_growatt_cloud_credentials(on_done=_done)


class _GrottLogin(_LoginPanel):
    def __init__(self, dash, params):
        super().__init__(
            "Grott MQTT login",
            "Same broker login as Setup &amp; Info → <b>GROTT MQTT</b>. "
            "Saving here keeps this Grott login; it does not copy the EMQX row over it.",
            test_key="grott",
        )
        self._params = params
        self.host = _line(params.ed_grott_host.text(), "MQTT host")
        self.port = _port(params.sp_grott_port.value())
        self.topic = _line(params.ed_grott_topic.text(), "energy/growatt")
        self.user = _line(params.ed_grott_user.text(), "MQTT user")
        self.password = _line(params.ed_grott_pass.text(), "MQTT password", secret=True)
        self.add_pair(("MQTT host:", self.host), ("Port:", self.port))
        self.add_wide("Topic:", self.topic)
        self.add_pair(("Username:", self.user), ("Password:", self.password))
        self.add_buttons(
            _btn("Save", self._save),
            _btn("Test Grott MQTT", self._test, 150),
        )

    def _push(self) -> None:
        p = self._params
        p.ed_grott_host.setText(self.host.text())
        p.sp_grott_port.setValue(int(self.port.value()))
        p.ed_grott_topic.setText(self.topic.text())
        p.ed_grott_user.setText(self.user.text())
        p.ed_grott_pass.setText(self.password.text())

    def _save(self) -> None:
        self._push()
        self._params._save_grott_mqtt_login()
        self.topic.setText(self._params.ed_grott_topic.text())
        self.note("Saved — Grott MQTT login on Setup & Info updated.")

    def _test(self) -> None:
        self._push()
        self.begin_test()
        self._params._test_grott_mqtt_connection(on_done=self.finish_test)


class _EmqxFields(_LoginPanel):
    """Shared EMQX host / port / username / password (Setup EMQX row)."""

    def __init__(self, title: str, hint: str, dash, params):
        super().__init__(title, hint, test_key="emqx")
        self._params = params
        self.host = _line(params.ed_emqx_host.text(), "EMQX host")
        self.port = _port(params.sp_emqx_port.value())
        self.user = _line(params.ed_emqx_user.text(), "MQTT username")
        self.password = _line(params.ed_emqx_pass.text(), "MQTT password", secret=True)
        self.add_pair(("Host:", self.host), ("Port:", self.port))
        self.add_pair(("Username:", self.user), ("Password:", self.password))

    def _push(self) -> None:
        p = self._params
        p.ed_emqx_host.setText(self.host.text())
        p.sp_emqx_port.setValue(int(self.port.value()))
        p.ed_emqx_user.setText(self.user.text())
        p.ed_emqx_pass.setText(self.password.text())

    def _pull(self) -> None:
        p = self._params
        self.host.setText(p.ed_emqx_host.text())
        self.port.setValue(int(p.sp_emqx_port.value()))
        self.user.setText(p.ed_emqx_user.text())
        self.password.setText(p.ed_emqx_pass.text())

    def _save(self) -> None:
        self._push()
        self._params._save_emqx_credentials()
        self._pull()
        self.note("Saved — EMQX login applied to Grott and Tasmota as well.")

    def _test(self) -> None:
        self._push()
        self.begin_test()
        self._params._test_emqx_connection(on_done=self.finish_test)


class _EmqxLogin(_EmqxFields):
    def __init__(self, dash, params):
        super().__init__(
            "EMQX login",
            "Same host, port, username, and password as Setup &amp; Info → <b>EMQX</b>. "
            "Save also applies this broker to Grott MQTT and Tasmota MQTT.",
            dash,
            params,
        )
        self.add_buttons(_btn("Save", self._save), _btn("Test", self._test))


class _TasmotaLogin(_EmqxFields):
    def __init__(self, dash, params):
        super().__init__(
            "Tasmota MQTT login",
            "Tasmota signs in to the <b>EMQX</b> broker. These are the same username "
            "and password as Setup &amp; Info → EMQX. Save applies them to Tasmota "
            "(and to Grott, which shares that broker).",
            dash,
            params,
        )
        self.add_buttons(_btn("Save", self._save), _btn("Test", self._test))


class _InverterLogin(_LoginPanel):
    def __init__(self, dash, params):
        super().__init__(
            "Inverter web UI login",
            "LAN and Wi‑Fi logins from Setup &amp; Info (the stick’s local browser page). "
            "This is not the Growatt cloud login and not Modbus.",
            test_key="webui",
        )
        self._params = params
        self.lan_ip = _line(params.ed_growatt_lan_ip.text(), "e.g. 192.168.1.50")
        self.lan_user = _line(params.ed_growatt_lan_user.text(), "Web UI username")
        self.lan_pass = _line(params.ed_growatt_lan_pass.text(), "Web UI password", secret=True)
        self.wifi_ip = _line(params.ed_growatt_wifi_ip.text(), "e.g. 192.168.1.51")
        self.wifi_user = _line(params.ed_growatt_wifi_user.text(), "Web UI username")
        self.wifi_pass = _line(params.ed_growatt_wifi_pass.text(), "Web UI password", secret=True)
        self.http_port = _port(params.sp_growatt_port.value())
        self.add_wide("LAN address:", self.lan_ip)
        self.add_pair(("LAN user:", self.lan_user), ("LAN password:", self.lan_pass))
        self.add_wide("Wi‑Fi address:", self.wifi_ip)
        self.add_pair(("Wi‑Fi user:", self.wifi_user), ("Wi‑Fi password:", self.wifi_pass))
        self.add_pair(("HTTP port:", self.http_port))
        self.add_buttons(
            _btn("Save", self._save),
            _btn("Test web UI", self._test, 130),
            _btn("Open web UI", self._open, 130),
        )

    def _push(self) -> None:
        p = self._params
        p.ed_growatt_lan_ip.setText(self.lan_ip.text())
        p.ed_growatt_lan_user.setText(self.lan_user.text())
        p.ed_growatt_lan_pass.setText(self.lan_pass.text())
        p.ed_growatt_wifi_ip.setText(self.wifi_ip.text())
        p.ed_growatt_wifi_user.setText(self.wifi_user.text())
        p.ed_growatt_wifi_pass.setText(self.wifi_pass.text())
        p.sp_growatt_port.setValue(int(self.http_port.value()))

    def _save(self) -> None:
        self._push()
        self._params._save_growatt_lan()
        self.note("Saved — LAN / Wi‑Fi web UI login on Setup & Info updated.")

    def _test(self) -> None:
        self._push()
        self.begin_test()
        self._params._test_growatt_http_connection(on_done=self.finish_test)

    def _open(self) -> None:
        self._push()
        self._params._open_growatt_web_ui()


class _ModbusLogin(_LoginPanel):
    def __init__(self, dash, params):
        super().__init__(
            "Modbus access",
            "Modbus has no username. It uses the <b>LAN address</b> and the port / unit "
            "from Setup &amp; Info. Inverter writes stay off unless you tick the box.",
            test_key="modbus",
        )
        self._params = params
        self.lan_ip = _line(params.ed_growatt_lan_ip.text(), "LAN address Modbus TCP uses")
        self.mode = QComboBox()
        self.mode.addItem("Disabled", "off")
        self.mode.addItem("Modbus TCP (LAN / RS485 Ethernet)", "tcp")
        self.mode.addItem("Modbus RTU over TCP (transparent gateway)", "tcp_rtu")
        self.mode.addItem("Modbus RTU (USB–RS485)", "serial")
        self.mode.setMinimumWidth(360)
        current = params.cb_growatt_modbus.currentData() or "off"
        idx = self.mode.findData(current)
        if idx >= 0:
            self.mode.setCurrentIndex(idx)
        self.tcp_port = _port(params.sp_growatt_modbus_tcp.value())
        self.serial = _line(params.ed_growatt_modbus_serial.text(), "/dev/ttyUSB0")
        self.baud = _port(params.sp_growatt_modbus_baud.value(), 1200, 921600)
        self.baud.setSingleStep(300)
        self.unit = _port(params.sp_growatt_modbus_unit.value(), 1, 247)
        self.writes = QCheckBox("Allow inverter writes via Modbus (opt-in)")
        self.writes.setChecked(bool(params.chk_growatt_modbus_writes.isChecked()))
        self.add_wide("LAN address:", self.lan_ip)
        self.add_wide("Mode:", self.mode)
        self.add_pair(("TCP port:", self.tcp_port), ("Unit ID:", self.unit))
        self.add_pair(("Serial device:", self.serial), ("Baud:", self.baud))
        r = self._row
        self._grid.addWidget(self.writes, r, 1, 1, 3)
        self._row += 1
        self.add_buttons(
            _btn("Save", self._save),
            _btn("Test Modbus", self._test, 130),
        )

    def _push(self, *, persist_ip: bool = False) -> None:
        p = self._params
        ip = self.lan_ip.text().strip()
        p.ed_growatt_lan_ip.setText(ip)
        if persist_ip:
            p.p.growatt_lan_ip = ip
            p.p.growatt_local_ip = ip
            s = p._settings()
            s.setValue("params/growatt_lan_ip", ip)
            s.setValue("params/growatt_local_ip", ip)
            s.sync()
        mode = self.mode.currentData() or "off"
        idx = p.cb_growatt_modbus.findData(mode)
        if idx >= 0:
            p.cb_growatt_modbus.setCurrentIndex(idx)
        p.sp_growatt_modbus_tcp.setValue(int(self.tcp_port.value()))
        p.ed_growatt_modbus_serial.setText(self.serial.text())
        p.sp_growatt_modbus_baud.setValue(int(self.baud.value()))
        p.sp_growatt_modbus_unit.setValue(int(self.unit.value()))
        p.chk_growatt_modbus_writes.setChecked(bool(self.writes.isChecked()) and mode != "off")

    def _save(self) -> None:
        self._push(persist_ip=True)
        self._params._save_growatt_modbus()
        self.note("Saved — Modbus access on Setup & Info updated.")

    def _test(self) -> None:
        self._push()
        self.begin_test()
        self._params._test_growatt_modbus_connection(on_done=self.finish_test)


class _PvOutputLogin(_LoginPanel):
    def __init__(self, dash, params):
        super().__init__(
            "PVOutput login",
            "Same API key and System Id as Setup &amp; Info → <b>PVOutput.org</b>.",
            test_key="pvoutput",
        )
        self._params = params
        self.enabled = QCheckBox("Enable PVOutput uploads")
        self.enabled.setChecked(bool(params.chk_pvoutput.isChecked()))
        self.key = _line(params.ed_pvoutput_key.text(), "X-Pvoutput-Apikey", secret=True)
        self.sid = _line(params.ed_pvoutput_sid.text(), "System Id")
        self.interval = _port(params.sp_pvoutput_interval.value(), 300, 900)
        self.interval.setSingleStep(60)
        r = self._row
        self._grid.addWidget(self.enabled, r, 1, 1, 3)
        self._row += 1
        self.add_pair(("API key:", self.key), ("System Id:", self.sid))
        self.add_pair(("Interval (s):", self.interval))
        self.add_buttons(
            _btn("Save", self._save),
            _btn("Test upload", self._test, 130),
        )

    def _push(self) -> None:
        p = self._params
        p.chk_pvoutput.setChecked(self.enabled.isChecked())
        p.ed_pvoutput_key.setText(self.key.text())
        p.ed_pvoutput_sid.setText(self.sid.text())
        p.sp_pvoutput_interval.setValue(int(self.interval.value()))

    def _save(self) -> None:
        self._push()
        self._params._save_pvoutput_settings()
        self.note("Saved — PVOutput login on Setup & Info updated.")

    def _test(self) -> None:
        self._push()
        self.begin_test()
        self._params._test_pvoutput_upload(on_done=self.finish_test)


class _OctopusLogin(_LoginPanel):
    def __init__(self, dash, params):
        super().__init__(
            "Octopus login",
            "API key and meter numbers from the Octopus tabs (Setup &amp; Info does not "
            "store this login). Save writes them for Octopus Live and copies them onto "
            "the historic Octopus tab.",
        )
        self._dash = dash
        live = getattr(dash, "octopus_live_tab", None)
        hist = getattr(dash, "octopus_tab", None)
        src = live or hist
        self._live = live
        self._hist = hist
        self.key = _line(
            src.api_key_edit.text() if src is not None else "",
            "Octopus API key",
            secret=True,
            width=280,
        )
        self.account = _line(
            live.account_edit.text() if live is not None and hasattr(live, "account_edit") else "",
            "A-XXXXXX",
        )
        self.imp_mpan = _line(
            src.import_mpan_edit.text() if src is not None else "",
            "Import MPAN",
        )
        self.imp_serial = _line(
            src.import_serial_edit.text() if src is not None else "",
            "Import serial",
        )
        self.exp_mpan = _line(
            src.export_mpan_edit.text() if src is not None else "",
            "Export MPAN",
        )
        self.exp_serial = _line(
            src.export_serial_edit.text() if src is not None else "",
            "Export serial",
        )
        self.add_wide("API key:", self.key)
        self.add_wide("Account:", self.account)
        self.add_pair(("Import MPAN:", self.imp_mpan), ("Import serial:", self.imp_serial))
        self.add_pair(("Export MPAN:", self.exp_mpan), ("Export serial:", self.exp_serial))
        self.add_buttons(_btn("Save", self._save))

    def _set(self, widget_owner, name: str, value: str) -> None:
        if widget_owner is None:
            return
        edit = getattr(widget_owner, name, None)
        if edit is not None:
            edit.setText(value)

    def _save(self) -> None:
        key = self.key.text().strip()
        account = self.account.text().strip()
        imp_m = self.imp_mpan.text().strip()
        imp_s = self.imp_serial.text().strip()
        exp_m = self.exp_mpan.text().strip()
        exp_s = self.exp_serial.text().strip()
        for owner in (self._live, self._hist):
            self._set(owner, "api_key_edit", key)
            self._set(owner, "account_edit", account)
            self._set(owner, "import_mpan_edit", imp_m)
            self._set(owner, "import_serial_edit", imp_s)
            self._set(owner, "export_mpan_edit", exp_m)
            self._set(owner, "export_serial_edit", exp_s)
        if self._live is not None and hasattr(self._live, "_save_octopus_live"):
            self._live._save_octopus_live()
        if self._dash is not None:
            self._dash.set_status("Octopus login saved (Live settings, copied to historic).")
        self.note("Saved — Octopus API key and meter numbers updated.")


class _DatabaseLogin(QWidget):
    """SQLite file plus MySQL and PostgreSQL logins — the Setup database rows."""

    def __init__(self, dash, params):
        super().__init__()
        self._params = params
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(_hint(
            "Database logins from Setup &amp; Info. "
            "<b>Save</b> and <b>Test Connection</b> use that same row."
        ))
        self._sqlite = self._sqlite_box(params)
        self._mysql = self._server_box(
            "MySQL login",
            params.chk_mysql,
            params.ed_mysql_host,
            params.ed_mysql_port,
            params.ed_mysql_db,
            params.ed_mysql_user,
            params.ed_mysql_pass,
            "mysql",
            "energy",
        )
        self._pg = self._server_box(
            "PostgreSQL login",
            params.chk_pg,
            params.ed_pg_host,
            params.ed_pg_port,
            params.ed_pg_db,
            params.ed_pg_user,
            params.ed_pg_pass,
            "pg",
            "powermon",
        )
        lay.addWidget(self._sqlite)
        lay.addWidget(self._mysql)
        lay.addWidget(self._pg)
        self.status = _status_label()
        lay.addWidget(self.status)

    def _sqlite_box(self, params) -> QGroupBox:
        box = QGroupBox("SQLite")
        lay = QVBoxLayout(box)
        enabled = QCheckBox("Use SQLite")
        enabled.setChecked(bool(params.chk_sqlite.isChecked()))
        path = _line(params.ed_sqlite_path.text(), "Database file", width=360)
        lay.addWidget(enabled)
        row = QHBoxLayout()
        row.addWidget(QLabel("File:"))
        row.addWidget(path)
        browse = _btn("Browse…", lambda: self._browse(path), 100)
        row.addWidget(browse)
        row.addStretch(1)
        lay.addLayout(row)
        actions = QHBoxLayout()
        actions.addWidget(_btn("Save", lambda: self._save_sqlite(enabled, path)))
        actions.addWidget(_btn(
            "Test Connection",
            lambda: self._test_sqlite(enabled, path),
            150,
        ))
        actions.addStretch(1)
        stmt = _TestStatement("sqlite")
        actions.addWidget(
            stmt, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        lay.addLayout(actions)
        box.statement = stmt
        box._enabled = enabled
        box._path = path
        return box

    def _browse(self, path_edit: QLineEdit) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "SQLite database file",
            path_edit.text(),
            "SQLite (*.db *.sqlite);;All (*)",
        )
        if path:
            path_edit.setText(path)

    def _apply_sqlite(self, enabled, path_edit) -> None:
        p = self._params
        p.chk_sqlite.setChecked(enabled.isChecked())
        p.ed_sqlite_path.setText(path_edit.text())

    def _save_sqlite(self, enabled, path_edit) -> None:
        self._apply_sqlite(enabled, path_edit)
        self._params._save_db_config("sqlite")
        self.status.setText("SQLite settings saved.")

    def _test_sqlite(self, enabled, path_edit) -> None:
        self._apply_sqlite(enabled, path_edit)
        self._sqlite.statement.begin()
        self._params._test_db_connections(
            "sqlite", on_done=self._sqlite.statement.finish,
        )

    def _server_box(self, title, chk, host_e, port_e, db_e, user_e, pass_e, backend, db_placeholder):
        box = QGroupBox(title)
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        enabled = QCheckBox("Enable MySQL" if backend == "mysql" else "Enable PostgreSQL")
        enabled.setChecked(bool(chk.isChecked()))
        host = _line(host_e.text(), "localhost")
        port = _port(port_e.value())
        database = _line(db_e.text(), db_placeholder)
        user = _line(user_e.text(), "Username")
        password = _line(pass_e.text(), "Password", secret=True)
        grid.addWidget(enabled, 0, 1, 1, 3)
        grid.addWidget(QLabel("Host:"), 1, 0)
        grid.addWidget(host, 1, 1)
        grid.addWidget(QLabel("Port:"), 1, 2)
        grid.addWidget(port, 1, 3)
        grid.addWidget(QLabel("Database:"), 2, 0)
        grid.addWidget(database, 2, 1)
        grid.addWidget(QLabel("Username:"), 3, 0)
        grid.addWidget(user, 3, 1)
        grid.addWidget(QLabel("Password:"), 3, 2)
        grid.addWidget(password, 3, 3)
        actions = QHBoxLayout()
        actions.addWidget(_btn(
            "Save",
            lambda b=backend, en=enabled, h=host, po=port, d=database, u=user, pw=password: self._save_server(
                b, en, h, po, d, u, pw,
            ),
        ))
        actions.addWidget(_btn(
            "Test Connection",
            lambda b=backend, en=enabled, h=host, po=port, d=database, u=user, pw=password: self._test_server(
                b, en, h, po, d, u, pw,
            ),
            150,
        ))
        actions.addStretch(1)
        stmt = _TestStatement(backend)
        actions.addWidget(
            stmt, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        grid.addLayout(actions, 4, 1, 1, 3)
        box.statement = stmt
        return box

    def _apply_server(self, backend, enabled, host, port, database, user, password) -> None:
        p = self._params
        if backend == "mysql":
            p.chk_mysql.setChecked(enabled.isChecked())
            p.ed_mysql_host.setText(host.text())
            p.ed_mysql_port.setValue(int(port.value()))
            p.ed_mysql_db.setText(database.text())
            p.ed_mysql_user.setText(user.text())
            p.ed_mysql_pass.setText(password.text())
        else:
            p.chk_pg.setChecked(enabled.isChecked())
            p.ed_pg_host.setText(host.text())
            p.ed_pg_port.setValue(int(port.value()))
            p.ed_pg_db.setText(database.text())
            p.ed_pg_user.setText(user.text())
            p.ed_pg_pass.setText(password.text())

    def _save_server(self, backend, enabled, host, port, database, user, password) -> None:
        self._apply_server(backend, enabled, host, port, database, user, password)
        self._params._save_db_config(backend)
        name = "MySQL" if backend == "mysql" else "PostgreSQL"
        self.status.setText(f"{name} login saved.")

    def _test_server(self, backend, enabled, host, port, database, user, password) -> None:
        self._apply_server(backend, enabled, host, port, database, user, password)
        box = self._mysql if backend == "mysql" else self._pg
        box.statement.begin()
        self._params._test_db_connections(backend, on_done=box.statement.finish)
