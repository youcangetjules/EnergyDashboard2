"""
Energy Dashboard — `modbus/command_sim.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

import time as _time_mod

from energy_dashboard.common import *
# Appended to probe detail when Modbus TCP socket cannot connect (Growatt-specific).
GROWATT_MODBUS_TCP_UNREACHABLE_HINT = (
    "Nothing accepted TCP on this host:port. On Growatt, Modbus TCP is normally served "
    "by a ShineWiFi‑X-class module with a fixed LAN IP (same subnet as this PC). "
    "Many sticks only expose a web UI on :80 and do not listen on :502 — use Modbus RTU "
    "(RS485) to the inverter in that case."
)
GROWATT_SHINELAN_DEFAULT_CREDENTIALS = (("admin", "admin"), ("admin", "admion"))


def _host_ping_ok(host: str, timeout_s: float = 2.0) -> bool:
    """True when the host responds to a single ICMP ping (best-effort)."""
    host = (host or "").strip()
    if not host:
        return False
    try:
        proc = subprocess.run(
            ["ping", "-c", "1", "-W", str(max(1, int(timeout_s))), host],
            capture_output=True,
            timeout=timeout_s + 2.0,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


GROWATT_WIFI_PING_OK_PORT_CLOSED_HINT = (
    "Inverter is on the network (ping OK) but the ShineLan web UI port is closed. "
    "This is normal on many Growatt WiFi sticks when GROTT or cloud forwarding is "
    "enabled — live telemetry via GROTT MQTT does not require HTTP access from this PC."
)


def _strip_tags_to_text(fragment: str) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", fragment or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _html_attr(tag: str, attr: str) -> str:
    m = re.search(rf"""\b{re.escape(attr)}\s*=\s*(['"])(.*?)\1""", tag or "", re.I | re.S)
    return html.unescape(m.group(2)).strip() if m else ""


def _cell_form_value(cell_html: str) -> str:
    values = []
    for tag in re.findall(r"(?is)<input\b[^>]*>", cell_html or ""):
        typ = (_html_attr(tag, "type") or "text").lower()
        checked = bool(re.search(r"\bchecked\b", tag, re.I))
        val = _html_attr(tag, "value")
        if typ in ("radio", "checkbox"):
            if checked and val:
                values.append(val)
        elif val:
            values.append(val)
    for sel in re.findall(r"(?is)<option\b[^>]*\bselected\b[^>]*>(.*?)</option>", cell_html or ""):
        txt = _strip_tags_to_text(sel)
        if txt:
            values.append(txt)
    txt = _strip_tags_to_text(cell_html)
    if txt:
        for val in values:
            txt = txt.replace(val, " ")
        txt = re.sub(r"\s+", " ", txt).strip()
        if txt:
            values.append(txt)
    return " ".join(dict.fromkeys(v for v in values if v)).strip()


def _shinelan_key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (label or "").lower())


def _parse_shinelan_network_settings(body: str) -> dict:
    """Parse the simple ShineLan network table without requiring BeautifulSoup."""
    out = {}
    for row in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr>", body or ""):
        cells = re.findall(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>", row)
        if len(cells) < 2:
            continue
        key = _shinelan_key(_strip_tags_to_text(cells[0]))
        val = " ".join(_cell_form_value(c) for c in cells[1:])
        val = re.sub(r"\s+", " ", val).strip()
        if key and val:
            out[key] = val
    # Some firmware emits bare labels with adjacent inputs rather than a clean table.
    for label, key in (
        ("Server IP", "serverip"),
        ("Server Port", "serverport"),
        ("Data Transfer Interval", "datatransferinterval"),
        ("DNS", "dns"),
        ("NetGate", "netgate"),
        ("NetMask", "netmask"),
    ):
        if key in out:
            continue
        m = re.search(
            rf"(?is){re.escape(label)}.*?<input\b[^>]*\bvalue\s*=\s*(['\"])(.*?)\1",
            body or "",
        )
        if m:
            out[key] = html.unescape(m.group(2)).strip()
    return out


def _shinelan_settings_summary(settings: dict) -> str:
    server_ip = settings.get("serverip") or settings.get("serverdomain") or ""
    server_port = settings.get("serverport") or ""
    bits = []
    if server_ip:
        bits.append(f"logger target {server_ip}{(':' + server_port) if server_port else ''}")
    dns = settings.get("dns")
    if dns:
        bits.append(f"DNS {dns}")
    interval = settings.get("datatransferinterval")
    if interval:
        bits.append(f"interval {interval} min")
    if not bits:
        return "ShineLan web UI reachable, but network settings were not found"
    return "ShineLan " + " | ".join(bits)


def _shinelan_candidate_paths() -> tuple[str, ...]:
    return (
        "/",
        "/index.html",
        "/index.htm",
        "/config.html",
        "/config.htm",
        "/network.html",
        "/network.htm",
        "/net.html",
        "/net.htm",
        "/setting.html",
        "/setting.htm",
    )


def _shinelan_try_form_login(session, base_url: str, login_html: str, username: str, password: str) -> bool:
    forms = re.findall(r"(?is)<form\b[^>]*>(.*?)</form>", login_html or "")
    actions = re.findall(r"(?is)<form\b[^>]*\baction\s*=\s*(['\"])(.*?)\1", login_html or "")
    action_by_index = [a[1] for a in actions]
    for idx, form in enumerate(forms or [login_html or ""]):
        inputs = re.findall(r"(?is)<input\b[^>]*>", form)
        payload = {}
        user_key = None
        pass_key = None
        for tag in inputs:
            name = _html_attr(tag, "name")
            if not name:
                continue
            typ = (_html_attr(tag, "type") or "text").lower()
            val = _html_attr(tag, "value")
            lname = name.lower()
            if typ == "password" or "pass" in lname or "pwd" in lname:
                pass_key = pass_key or name
            elif "user" in lname or "account" in lname or "name" in lname or "admin" in lname:
                user_key = user_key or name
            payload[name] = val
        if not payload:
            continue
        payload[user_key or "username"] = username
        payload[pass_key or "password"] = password
        action = action_by_index[idx] if idx < len(action_by_index) else ""
        url = requests.compat.urljoin(base_url + "/", action or "/")
        try:
            resp = session.post(url, data=payload, timeout=5, allow_redirects=True)
            if resp.status_code < 400:
                return True
        except requests.RequestException:
            continue
    return False


def _shinelan_credentials(username: str = "", password: str = "") -> list[tuple[str, str]]:
    username = (username or "").strip()
    if username or password:
        return [(username or "admin", password or "")]
    return list(GROWATT_SHINELAN_DEFAULT_CREDENTIALS)


def _command_sim_tcp_client_host(bind_address: str) -> str:
    """Host for ModbusTcpClient when talking to a server bound on bind_address."""
    b = (bind_address or "").strip()
    if b in ("0.0.0.0", "::"):
        return "127.0.0.1"
    return b if b else "127.0.0.1"


def _command_sim_tcp_transaction(host, port, unit, op, addr, count, write_val):
    """
    Run one Modbus TCP client transaction against the simulator (or any slave).
    op: 'rh' holding read, 'ri' input read, 'wh' single holding write.
    Returns (ok: bool, message: str, registers: list|None).
    """
    try:
        from pymodbus.client import ModbusTcpClient
    except ImportError:
        return False, "pymodbus not installed", None

    unit = int(unit)
    addr = int(addr)
    count = max(1, int(count))
    port = int(port)

    def _call(fn, **kw):
        for arg in ("slave", "device_id"):
            try:
                return fn(**{arg: unit, **kw})
            except TypeError:
                continue
        return fn(**kw)

    with _SuppressPymodbusConsoleNoise():
        client = ModbusTcpClient(host, port=port, timeout=5.0, retries=1)
        if not client.connect():
            return False, f"TCP connect failed ({host}:{port})", None
        try:
            if op == "rh":
                rr = _call(client.read_holding_registers, address=addr, count=count)
            elif op == "ri":
                rr = _call(client.read_input_registers, address=addr, count=count)
            elif op == "wh":
                rr = _call(
                    client.write_register,
                    address=addr,
                    value=int(write_val) & 0xFFFF,
                )
            else:
                return False, f"unknown op {op!r}", None

            if hasattr(rr, "isError") and rr.isError():
                es = getattr(rr, "exception_code", None) or getattr(rr, "message", None)
                return False, f"Modbus error response ({es or rr})", None
            if op == "wh":
                return True, f"write_register addr={addr} value={int(write_val) & 0xFFFF} OK", None
            regs = list(getattr(rr, "registers", []) or [])
            return True, f"{len(regs)} register(s)", regs
        finally:
            try:
                client.close()
            except Exception:
                pass


class _SuppressPymodbusConsoleNoise:
    """pymodbus logs ERROR on every failed TCP connect() — floods terminal during probes."""

    def __enter__(self):
        import logging
        self._saved = []
        for name in ("pymodbus", "pymodbus.logging", "pymodbus.client"):
            lg = logging.getLogger(name)
            self._saved.append((lg, lg.level))
            lg.setLevel(logging.CRITICAL)
        return self

    def __exit__(self, *args):
        import logging
        for lg, lvl in self._saved:
            lg.setLevel(lvl)
        return False


def _growatt_try_modbus_read(client, unit):
    """Attempt one successful Modbus read; works across common map offsets and pymodbus versions."""
    unit = int(unit)

    def _call(read_fn, addr, count):
        try:
            return read_fn(address=addr, count=count, slave=unit)
        except TypeError:
            return read_fn(address=addr, count=count, device_id=unit)

    # Growatt inverter protocol PDFs use holding blocks e.g. 0–124 / 125–249 — try short blocks first.
    for read_fn in (client.read_holding_registers, client.read_input_registers):
        for addr, count in ((0, 20), (0, 10), (125, 10), (0, 5)):
            try:
                rr = _call(read_fn, addr, count)
                if hasattr(rr, "isError") and not rr.isError():
                    return True, f"read OK ({read_fn.__name__} @{addr}×{count})"
            except Exception:
                continue

    for read_fn in (client.read_holding_registers, client.read_input_registers):
        for addr in (0, 1, 3, 4, 5, 6):
            for count in (1, 2):
                rr = _call(read_fn, addr, count)
                if hasattr(rr, "isError") and not rr.isError():
                    return True, f"read OK ({read_fn.__name__} addr={addr} n={count})"
    return False, "no register read succeeded (check unit ID or model map)"


def _growatt_http_probe_sync(host, port, username="", password=""):
    """Read ShineLan network settings from the Growatt local web UI when possible."""
    fresh = datetime.now().strftime("%H:%M:%S")
    host = (host or "").strip()
    if not host:
        return {
            "state_key": "off",
            "state_text": "Not configured",
            "detail": "Set inverter IP/hostname under Setup & Info for WiFi Direct",
            "fresh": fresh,
        }
    port = int(port) if port else 80
    scheme = "https" if port == 443 else "http"
    base_url = f"{scheme}://{host}:{port}"
    import socket
    try:
        with socket.create_connection((host, port), timeout=4.0):
            pass
    except OSError as e:
        if _host_ping_ok(host):
            return {
                "state_key": "warn",
                "state_text": "Web UI port closed",
                "detail": (
                    f"{host} is online (ping OK) but TCP port {port} is closed — {e}. "
                    f"{GROWATT_WIFI_PING_OK_PORT_CLOSED_HINT}"
                ),
                "fresh": fresh,
                "host": host,
                "port": port,
            }
        return {
            "state_key": "bad",
            "state_text": "Unreachable",
            "detail": f"Could not open TCP to {host}:{port} — {e}",
            "fresh": fresh,
        }
    session = requests.Session()
    session.headers.update({"User-Agent": "PowerModel-ShineLan-Probe/1.0"})
    errors = []
    for user, pwd in _shinelan_credentials(username, password):
        auth_modes = [("basic", requests.auth.HTTPBasicAuth(user, pwd))]
        auth_modes.append(("digest", requests.auth.HTTPDigestAuth(user, pwd)))
        for _auth_name, auth in auth_modes:
            session.auth = auth
            first_html = ""
            try:
                first = session.get(base_url + "/", timeout=5, allow_redirects=True)
                first_html = first.text or ""
                if first.status_code in (401, 403):
                    errors.append(f"auth rejected for {user!r}")
                    continue
                if "login" in first.url.lower() or "password" in first_html.lower():
                    _shinelan_try_form_login(session, base_url, first_html, user, pwd)
            except requests.RequestException as exc:
                errors.append(str(exc))
                continue
            for path in _shinelan_candidate_paths():
                try:
                    resp = session.get(base_url + path, timeout=5, allow_redirects=True)
                except requests.RequestException as exc:
                    errors.append(str(exc))
                    continue
                if resp.status_code in (401, 403):
                    errors.append(f"auth rejected for {user!r}")
                    break
                if resp.status_code >= 400:
                    continue
                body = resp.text or ""
                settings = _parse_shinelan_network_settings(body)
                if settings.get("serverip") or settings.get("serverport"):
                    detail = _shinelan_settings_summary(settings)
                    return {
                        "state_key": "ok",
                        "state_text": "Settings read",
                        "detail": detail,
                        "fresh": fresh,
                        "host": host,
                        "port": port,
                        "server_ip": settings.get("serverip", ""),
                        "server_port": settings.get("serverport", ""),
                        "dns": settings.get("dns", ""),
                        "interval_min": settings.get("datatransferinterval", ""),
                        "raw_settings": settings,
                    }
                if "server ip" in body.lower() or "data transfer interval" in body.lower():
                    settings = _parse_shinelan_network_settings(body)
                    return {
                        "state_key": "warn",
                        "state_text": "Partial read",
                        "detail": _shinelan_settings_summary(settings),
                        "fresh": fresh,
                        "host": host,
                        "port": port,
                        "raw_settings": settings,
                    }
    err = "; ".join(dict.fromkeys(e for e in errors if e))[:180]
    return {
        "state_key": "warn",
        "state_text": "Web UI only",
        "detail": (
            f"TCP open on {host}:{port}, but ShineLan network settings could not be read"
            + (f" ({err})" if err else "")
        ),
        "fresh": fresh,
        "host": host,
        "port": port,
    }


def _growatt_modbus_probe_sync(mode, tcp_host, tcp_port, serial_path, baud, unit):
    """Run a short Modbus transport test. Returns dict: state_key, state_text, detail."""
    fresh = datetime.now().strftime("%H:%M:%S")
    try:
        from pymodbus.client import ModbusSerialClient, ModbusTcpClient
    except ImportError:
        return {
            "state_key": "warn",
            "state_text": "No pymodbus",
            "detail": "pip install pymodbus (see requirements.txt)",
            "fresh": fresh,
        }

    mode = (mode or "off").lower()
    if mode not in ("tcp", "serial"):
        return {
            "state_key": "off",
            "state_text": "Disabled",
            "detail": "Enable Modbus TCP or RTU in Setup & Info to monitor the inverter locally",
            "fresh": fresh,
        }

    with _SuppressPymodbusConsoleNoise():
        return _growatt_modbus_probe_core(
            mode, tcp_host, tcp_port, serial_path, baud, unit, fresh,
            ModbusSerialClient, ModbusTcpClient,
        )


def _growatt_modbus_probe_core(mode, tcp_host, tcp_port, serial_path, baud, unit, fresh,
                               ModbusSerialClient, ModbusTcpClient):
    unit = max(1, min(247, int(unit)))
    timeout = 5.0
    if mode == "tcp":
        host = (tcp_host or "").strip()
        if not host:
            return {
                "state_key": "warn",
                "state_text": "Not configured",
                "detail": "Set inverter IP/hostname (Growatt local network) for Modbus TCP",
                "fresh": fresh,
            }
        port = int(tcp_port) if tcp_port else 502
        client = None
        connected = False
        for attempt in range(2):
            c = ModbusTcpClient(host, port=port, timeout=timeout, retries=1)
            if c.connect():
                client = c
                connected = True
                break
            try:
                c.close()
            except Exception:
                pass
            _time_mod.sleep(0.35)
        if not connected:
            return {
                "state_key": "bad",
                "state_text": "Unreachable",
                "detail": (
                    f"TCP connect failed ({host}:{port}). "
                    f"{GROWATT_MODBUS_TCP_UNREACHABLE_HINT}"
                ),
                "fresh": fresh,
            }
        try:
            ok, msg = _growatt_try_modbus_read(client, unit)
            if ok:
                return {
                    "state_key": "ok",
                    "state_text": "OK",
                    "detail": f"{host}:{port} unit {unit} | {msg}",
                    "fresh": fresh,
                }
            return {
                "state_key": "bad",
                "state_text": "Modbus error",
                "detail": f"{host}:{port} unit {unit} — {msg}",
                "fresh": fresh,
            }
        except Exception as e:
            return {
                "state_key": "bad",
                "state_text": "Error",
                "detail": f"{host}:{port}: {e}",
                "fresh": fresh,
            }
        finally:
            try:
                client.close()
            except Exception:
                pass

    # serial
    path = (serial_path or "").strip()
    if not path:
        return {
            "state_key": "warn",
            "state_text": "Not configured",
            "detail": "Set the serial device path (e.g. /dev/ttyUSB0) for Modbus RTU",
            "fresh": fresh,
        }
    try:
        client = ModbusSerialClient(
            port=path,
            baudrate=int(baud),
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=timeout,
        )
    except Exception as e:
        return {
            "state_key": "bad",
            "state_text": "Bad config",
            "detail": str(e),
            "fresh": fresh,
        }
    if not client.connect():
        try:
            client.close()
        except Exception:
            pass
        return {
            "state_key": "bad",
            "state_text": "Unreachable",
            "detail": f"Could not open {path} @ {baud} baud",
            "fresh": fresh,
        }
    try:
        ok, msg = _growatt_try_modbus_read(client, unit)
        if ok:
            return {
                "state_key": "ok",
                "state_text": "OK",
                "detail": f"{path} @ {baud} baud unit {unit} | {msg}",
                "fresh": fresh,
            }
        return {
            "state_key": "bad",
            "state_text": "Modbus error",
            "detail": f"{path} unit {unit} — {msg}",
            "fresh": fresh,
        }
    except Exception as e:
        return {
            "state_key": "bad",
            "state_text": "Error",
            "detail": f"{path}: {e}",
            "fresh": fresh,
        }
    finally:
        try:
            client.close()
        except Exception:
            pass


def _command_sim_build_sim_device(unit_id: int, profile: str):
    """Build pymodbus SimDevice (non-shared blocks) for local Modbus TCP lab."""
    from pymodbus.simulator import SimData, SimDevice, DataType

    co = [SimData(address=0, count=16, values=False, datatype=DataType.BITS)]
    di = [SimData(address=0, count=16, values=False, datatype=DataType.BITS)]
    n = 256
    if profile == "mic":
        # Sparse-ish values reminiscent of growatt_simulator Mic600Profile (×0.1 scaling elsewhere).
        hrv = [0] * n
        irv = [0] * n
        irv[0] = 1
        irv[35] = 6000
        irv[37] = 2300
        irv[53] = 50
        irv[55] = 12000
        irv[93] = 350
        hrv[0] = 1
        hrv[3] = 100
    else:
        # "probe" — dense blocks so Connectivity’s Modbus read patterns succeed.
        hrv = [(0x0100 + (i & 0xFF)) for i in range(n)]
        irv = [(0x0200 + (i & 0xFF)) for i in range(n)]
        for a in range(125, min(135, n)):
            hrv[a] = 0x1357
            irv[a] = 0x2468
    hr = [SimData(address=0, count=n, values=hrv, datatype=DataType.REGISTERS)]
    ir = [SimData(address=0, count=n, values=irv, datatype=DataType.REGISTERS)]
    return SimDevice(id=max(1, min(247, int(unit_id))), simdata=(co, di, hr, ir))


class CommandSimTab(QWidget):
    """Local Modbus TCP slave (pymodbus SimDevice) — lab substitute for growatt2mqtt’s RTU simulator."""

    def __init__(self, set_status):
        super().__init__()
        self.set_status = set_status
        self._inv = Invoker(self)
        self._thread = None
        self._stop_ev = threading.Event()
        self._pymodbus_ok = False
        self._client_busy = False
        self._server_running = False
        self._sim_bind = None
        self._sim_port = None
        self._sim_unit = None
        try:
            import pymodbus  # noqa: F401
            from pymodbus.server import ModbusTcpServer  # noqa: F401
            self._pymodbus_ok = True
        except ImportError:
            pass
        self.build_ui()

    def build_ui(self):
        lay = QVBoxLayout(self)
        hint = QLabel(
            "<p style='line-height:1.45;'>This tab runs a <b>Modbus TCP slave</b> (server) "
            "on this PC. <b>Listening</b> only opens the socket — a <b>Modbus round-trip</b> "
            "needs a <b>client</b> (Connectivity probe, or the <i>Test read / manual</i> "
            "section below).</p>"
            "<p style='line-height:1.45;'>Point <b>Setup → Growatt local Modbus</b> and "
            "<b>Connectivity</b> at the bind address and port "
            "(e.g. <code>TCP 127.0.0.1:5502</code>, unit ID 1).</p>"
            "<p style='line-height:1.45;color:#a6adc8;'>Not a Grott proxy — standard "
            "Modbus only. Stop the server before changing port.</p>"
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(hint)

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        r = 0
        form.addWidget(QLabel("Bind address:"), r, 0)
        self.bind_edit = QLineEdit("127.0.0.1")
        self.bind_edit.setToolTip("0.0.0.0 = all interfaces; 127.0.0.1 = localhost only")
        form.addWidget(self.bind_edit, r, 1)
        r += 1
        form.addWidget(QLabel("TCP port:"), r, 0)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(5502)
        self.port_spin.setToolTip("Default 5502 avoids needing root for port 502")
        form.addWidget(self.port_spin, r, 1)
        r += 1
        form.addWidget(QLabel("Unit ID:"), r, 0)
        self.unit_spin = QSpinBox()
        self.unit_spin.setRange(1, 247)
        self.unit_spin.setValue(1)
        form.addWidget(self.unit_spin, r, 1)
        r += 1
        form.addWidget(QLabel("Profile:"), r, 0)
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("Probe-shaped (dense HR/IR)", "probe")
        self.profile_combo.addItem("MIC-style sparse (input regs)", "mic")
        self.profile_combo.setToolTip(
            "Probe-shaped: answers Connectivity read patterns. "
            "MIC-style: a few registers like growatt_simulator Mic600Profile."
        )
        form.addWidget(self.profile_combo, r, 1)
        lay.addLayout(form)

        row = QHBoxLayout()
        self.start_btn = QPushButton("Start server")
        self.stop_btn = QPushButton("Stop server")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        row.addStretch(1)
        lay.addLayout(row)

        self.status_lbl = QLabel("Idle — server not running.")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.status_lbl.setStyleSheet("color: #a6adc8;")
        lay.addWidget(self.status_lbl)

        client_box = QGroupBox("Modbus client — prove a round-trip (same PC)")
        client_lay = QVBoxLayout(client_box)
        c_hint = QLabel(
            "<p style='line-height:1.4;color:#a6adc8;font-size:11px;'>Opens a short-lived "
            "<b>Modbus TCP client</b> to the same bind/port/unit so you can confirm reads "
            "/ writes reach this simulator without switching tabs.</p>"
        )
        c_hint.setWordWrap(True)
        c_hint.setTextFormat(Qt.TextFormat.RichText)
        client_lay.addWidget(c_hint)

        quick_row = QHBoxLayout()
        self.client_test_btn = QPushButton("Test read (holding reg 0, count 1)")
        self.client_test_btn.setToolTip(
            "Confirms a Modbus TCP read succeeds against the server started above."
        )
        self.client_test_btn.setEnabled(False)
        self.client_test_btn.clicked.connect(self._on_client_test_read)
        quick_row.addWidget(self.client_test_btn)
        quick_row.addStretch(1)
        client_lay.addLayout(quick_row)

        self.roundtrip_lbl = QLabel(
            "No Modbus client exchange yet — start the server, wait for “Listening…”, "
            "then press Test read."
        )
        self.roundtrip_lbl.setWordWrap(True)
        self.roundtrip_lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
        self.roundtrip_lbl.setTextFormat(Qt.TextFormat.RichText)
        client_lay.addWidget(self.roundtrip_lbl)

        man = QGridLayout()
        man.setHorizontalSpacing(8)
        man.setVerticalSpacing(6)
        mr = 0
        man.addWidget(QLabel("Operation:"), mr, 0)
        self.client_op_combo = QComboBox()
        self.client_op_combo.addItem("Read holding registers", "rh")
        self.client_op_combo.addItem("Read input registers", "ri")
        self.client_op_combo.addItem("Write single holding register", "wh")
        self.client_op_combo.currentIndexChanged.connect(self._on_client_op_changed)
        man.addWidget(self.client_op_combo, mr, 1)
        mr += 1
        man.addWidget(QLabel("Address:"), mr, 0)
        self.client_addr_spin = QSpinBox()
        self.client_addr_spin.setRange(0, 65535)
        self.client_addr_spin.setValue(0)
        man.addWidget(self.client_addr_spin, mr, 1)
        mr += 1
        self.client_count_label = QLabel("Count:")
        man.addWidget(self.client_count_label, mr, 0)
        self.client_count_spin = QSpinBox()
        self.client_count_spin.setRange(1, 125)
        self.client_count_spin.setValue(1)
        man.addWidget(self.client_count_spin, mr, 1)
        mr += 1
        self.client_val_label = QLabel("Value (write):")
        man.addWidget(self.client_val_label, mr, 0)
        self.client_val_spin = QSpinBox()
        self.client_val_spin.setRange(0, 65535)
        self.client_val_spin.setValue(0)
        man.addWidget(self.client_val_spin, mr, 1)
        client_lay.addLayout(man)

        self.client_exec_btn = QPushButton("Run manual command")
        self.client_exec_btn.setEnabled(False)
        self.client_exec_btn.clicked.connect(self._on_client_manual_exec)
        client_lay.addWidget(self.client_exec_btn)

        self.client_log = QTextEdit()
        self.client_log.setReadOnly(True)
        self.client_log.setMaximumHeight(120)
        self.client_log.setPlaceholderText("Client results appear here…")
        client_lay.addWidget(self.client_log)

        lay.addWidget(client_box)
        self._on_client_op_changed()

        if not self._pymodbus_ok:
            self.start_btn.setEnabled(False)
            self.status_lbl.setText(
                "pymodbus is not installed — pip install pymodbus (see requirements.txt)."
            )

        lay.addStretch(1)

    def _on_client_op_changed(self):
        op = self.client_op_combo.currentData()
        is_write = op == "wh"
        self.client_count_label.setVisible(not is_write)
        self.client_count_spin.setVisible(not is_write)
        self.client_val_label.setVisible(is_write)
        self.client_val_spin.setVisible(is_write)

    def _refresh_client_buttons(self):
        base = self._server_running and self._pymodbus_ok and not self._client_busy
        self.client_test_btn.setEnabled(base)
        self.client_exec_btn.setEnabled(base)
        self.client_op_combo.setEnabled(base)
        self.client_addr_spin.setEnabled(base)
        self.client_count_spin.setEnabled(base)
        self.client_val_spin.setEnabled(base)

    def _append_client_log(self, html_line):
        self.client_log.append(html_line)
        sb = self.client_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_client_test_read(self):
        if self._client_busy or not self._server_running:
            return
        self._client_busy = True
        self._refresh_client_buttons()
        threading.Thread(target=self._client_test_read_thread, daemon=True).start()

    def _client_test_read_thread(self):
        host = _command_sim_tcp_client_host(self._sim_bind or "")
        port = self._sim_port
        unit = self._sim_unit
        ok_final = False
        detail = ""
        regs_out = None
        for _ in range(6):
            ok, msg, regs = _command_sim_tcp_transaction(
                host, port, unit, "rh", 0, 1, 0)
            if ok:
                ok_final = True
                detail = msg
                regs_out = regs
                break
            detail = msg
            _time_mod.sleep(0.15)

        def done():
            self._client_busy = False
            self._refresh_client_buttons()
            ts = datetime.now().strftime("%H:%M:%S")
            if ok_final:
                r0 = regs_out[0] if regs_out else None
                self._append_client_log(
                    f"<span style='color:#a6e3a1'><b>✓ {ts}</b> Round-trip OK — "
                    f"read HR[0]={r0}</span>"
                )
                self.roundtrip_lbl.setText(
                    f"<b>Last Modbus exchange OK</b> @ {ts} — client read HR[0]={r0} "
                    f"via {host}:{port} unit {unit}. Simulator responded."
                )
                self.roundtrip_lbl.setStyleSheet("color: #a6e3a1; font-size: 12px;")
            else:
                self._append_client_log(
                    f"<span style='color:#f38ba8'><b>✗ {ts}</b> {detail}</span> "
                    "<span style='color:#a6adc8'>— wait for “Listening” or check bind/port.</span>"
                )
                self.roundtrip_lbl.setText(
                    "No successful client read — see log. If the server just started, "
                    "try Test read again."
                )
                self.roundtrip_lbl.setStyleSheet("color: #fab387; font-size: 11px;")

        self._inv.invoke(done)

    def _on_client_manual_exec(self):
        if self._client_busy or not self._server_running:
            return
        self._client_busy = True
        self._refresh_client_buttons()
        op = self.client_op_combo.currentData()
        addr = int(self.client_addr_spin.value())
        cnt = int(self.client_count_spin.value())
        val = int(self.client_val_spin.value())
        threading.Thread(
            target=self._client_manual_thread,
            args=(op, addr, cnt, val),
            daemon=True,
        ).start()

    def _client_manual_thread(self, op, addr, cnt, val):
        host = _command_sim_tcp_client_host(self._sim_bind or "")
        ok, msg, regs = _command_sim_tcp_transaction(
            host, self._sim_port, self._sim_unit, op, addr, cnt, val)

        def done():
            self._client_busy = False
            self._refresh_client_buttons()
            ts = datetime.now().strftime("%H:%M:%S")
            if ok:
                if op == "wh":
                    self._append_client_log(
                        f"<span style='color:#a6e3a1'><b>✓ {ts}</b> {msg}</span>"
                    )
                else:
                    reg_str = ", ".join(str(x) for x in (regs or []))
                    self._append_client_log(
                        f"<span style='color:#a6e3a1'><b>✓ {ts}</b> {msg}: [{reg_str}]</span>"
                    )
                self.roundtrip_lbl.setText(
                    f"<b>Last Modbus exchange OK</b> @ {ts} — manual {op} @ addr {addr}."
                )
                self.roundtrip_lbl.setStyleSheet("color: #a6e3a1; font-size: 12px;")
            else:
                self._append_client_log(
                    f"<span style='color:#f38ba8'><b>✗ {ts}</b> {msg}</span>"
                )

        self._inv.invoke(done)

    def _on_start(self):
        if not self._pymodbus_ok:
            return
        if self._thread is not None and self._thread.is_alive():
            self.set_status("Command Sim: server already running.")
            return
        self._stop_ev.clear()
        bind = (self.bind_edit.text() or "127.0.0.1").strip() or "127.0.0.1"
        port = int(self.port_spin.value())
        unit = int(self.unit_spin.value())
        self._sim_bind = bind
        self._sim_port = port
        self._sim_unit = unit
        self._server_running = False
        self._refresh_client_buttons()
        profile = self.profile_combo.currentData()
        self._thread = threading.Thread(
            target=self._server_thread_main,
            args=(bind, port, unit, profile),
            name="CommandSimModbusTcp",
            daemon=True,
        )
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.bind_edit.setEnabled(False)
        self.port_spin.setEnabled(False)
        self.unit_spin.setEnabled(False)
        self.profile_combo.setEnabled(False)
        self._thread.start()
        self.set_status(f"Command Sim: starting Modbus TCP on {bind}:{port} unit {unit}…")

    def _on_stop(self):
        self._stop_ev.set()
        self.set_status("Command Sim: stop requested…")

    def _server_thread_main(self, bind: str, port: int, unit: int, profile: str):
        import asyncio
        from pymodbus.server import ModbusTcpServer

        dev = _command_sim_build_sim_device(unit, profile)

        async def runner():
            srv = ModbusTcpServer(dev, address=(bind, port))
            serve_task = None
            try:
                serve_task = asyncio.create_task(srv.serve_forever())
                self._inv.invoke(
                    lambda b=bind, p=port, u=unit: self.status_lbl.setText(
                        f"<b>Listening</b> on {b}:{p} (unit {u}). "
                        "Use <b>Test read</b> below for a local round-trip, or "
                        "Connectivity → Growatt local Modbus."
                    ))
                self._inv.invoke(lambda: self.status_lbl.setStyleSheet("color: #a6e3a1;"))
                self._inv.invoke(lambda: self._command_sim_server_ready())
                while not self._stop_ev.is_set():
                    await asyncio.sleep(0.06)
            finally:
                try:
                    await srv.shutdown()
                except Exception:
                    pass
                if serve_task is not None:
                    try:
                        await serve_task
                    except Exception:
                        pass

        try:
            asyncio.run(runner())
        except OSError as e:
            self._inv.invoke(
                lambda msg=str(e): self.status_lbl.setText(
                    f"<b>Failed:</b> {msg} (port in use or bind address invalid?)"
                ))
            self._inv.invoke(lambda: self.status_lbl.setStyleSheet("color: #f38ba8;"))
        except Exception as e:
            self._inv.invoke(
                lambda msg=str(e): self.status_lbl.setText(f"<b>Error:</b> {msg}"))
            self._inv.invoke(lambda: self.status_lbl.setStyleSheet("color: #f38ba8;"))
        finally:
            self._inv.invoke(self._reset_ui_after_thread)

    def _command_sim_server_ready(self):
        self._server_running = True
        self._refresh_client_buttons()

    def _reset_ui_after_thread(self):
        self._thread = None
        self._server_running = False
        self._sim_bind = None
        self._sim_port = None
        self._sim_unit = None
        self._refresh_client_buttons()
        self.start_btn.setEnabled(self._pymodbus_ok)
        self.stop_btn.setEnabled(False)
        self.bind_edit.setEnabled(True)
        self.port_spin.setEnabled(True)
        self.unit_spin.setEnabled(True)
        self.profile_combo.setEnabled(True)
        if self._pymodbus_ok:
            self.status_lbl.setText("Idle — server not running.")
            self.status_lbl.setStyleSheet("color: #a6adc8;")
        self.set_status("Command Sim: server stopped.")


_CONNECTIVITY_ROW_TO_HEALTH = {
    "Growatt server": "growatt_cloud",
    "Growatt local (Grott MQTT)": "grott",
    "Growatt local (ShineLan)": "wifi_direct",
    "Growatt local (Modbus)": "modbus_lan",
    "Octopus historic": "octopus_hist",
    "Octopus live": "octopus_live",
    "Tasmota devices": "tasmota",
    "Forecast.solar": "forecast",
    "Databases": "database",
}


__all__ = [n for n in globals() if not n.startswith('__')]
