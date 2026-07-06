"""
Subscribe to Tasmota MQTT telemetry (tele/SENSOR, tele/STATUS8, stat/POWER, tele/STATE).

Devices are keyed by IP when the payload includes ``IPAddress``; otherwise the
Tasmota topic segment is used until an IP is learned from a STATE message.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None  # type: ignore


def _topic_parts(topic: str) -> tuple[str, str, str] | None:
    parts = topic.split("/")
    if len(parts) < 3:
        return None
    return parts[0], parts[1], "/".join(parts[2:])


def _energy_block(data: dict) -> dict | None:
    if not isinstance(data, dict):
        return None
    energy = data.get("ENERGY")
    if isinstance(energy, dict):
        return energy
    sns = data.get("StatusSNS")
    if isinstance(sns, dict):
        energy = sns.get("ENERGY")
        if isinstance(energy, dict):
            return energy
    return None


def _blank_reading(ip: str) -> dict:
    """A complete reading row with zeroed energy fields.

    Used when we learn a device's relay state before (or without) any energy
    telemetry, so every row always carries the full set of keys the UI reads.
    """
    return {
        "ip": ip,
        "power_W": 0.0,
        "voltage_V": 0.0,
        "current_A": 0.0,
        "factor": 0.0,
        "today_kWh": 0.0,
        "yesterday_kWh": 0.0,
        "total_kWh": 0.0,
        "relay_on": None,
    }


def _reading_from_energy(ip: str, energy: dict) -> dict:
    return {
        "ip": ip,
        "power_W": float(energy.get("Power", 0) or 0),
        "voltage_V": float(energy.get("Voltage", 0) or 0),
        "current_A": float(energy.get("Current", 0) or 0),
        "factor": float(energy.get("Factor", 0) or 0),
        "today_kWh": float(energy.get("Today", 0) or 0),
        "yesterday_kWh": float(energy.get("Yesterday", 0) or 0),
        "total_kWh": float(energy.get("Total", 0) or 0),
        "relay_on": None,
    }


def _parse_power_payload(raw: bytes) -> bool | None:
    text = raw.decode("utf-8", errors="replace").strip().upper()
    if text in ("ON", "TRUE", "1"):
        return True
    if text in ("OFF", "FALSE", "0"):
        return False
    return None


def _parse_state_power(data: dict) -> bool | None:
    """Extract relay state from a STATE/RESULT JSON payload.

    Tasmota reports the current relay as ``POWER`` (single relay) or
    ``POWER1``/``POWER2``/… (multi-relay). We treat the first relay as the
    device's switch state.
    """
    if not isinstance(data, dict):
        return None
    for key in ("POWER", "POWER1"):
        if key in data:
            val = data[key]
            if isinstance(val, bool):
                return val
            if isinstance(val, (int, float)):
                return val != 0
            if isinstance(val, str):
                u = val.strip().upper()
                if u in ("ON", "TRUE", "1"):
                    return True
                if u in ("OFF", "FALSE", "0"):
                    return False
    return None


def _friendly_name(data: dict) -> str:
    fn = data.get("FriendlyName")
    if isinstance(fn, list) and fn:
        return str(fn[0]).strip()
    if isinstance(fn, str) and fn.strip():
        return fn.strip()
    host = data.get("Hostname") or data.get("Host")
    if host:
        return str(host).strip()
    return ""


class TasmotaMqttSubscriber:
    """Background MQTT client; thread-safe snapshot for the Tasmota tab."""

    _SUB_TOPICS = (
        "tele/+/SENSOR",
        "tele/+/STATUS8",
        "stat/+/POWER",
        "stat/+/RESULT",
        "tele/+/STATE",
    )

    def __init__(
        self,
        on_update: Callable[[], None],
        on_status: Callable[[str], None],
    ):
        self._on_update = on_update
        self._on_status = on_status
        self._lock = threading.Lock()
        self._client: Any = None
        self._running = False
        self._connected = False
        self._by_ip: dict[str, dict] = {}
        self._names: dict[str, str] = {}
        self._firmware: dict[str, str] = {}
        self._topic_to_ip: dict[str, str] = {}
        self._topic_to_key: dict[str, str] = {}
        self._prefix = ""
        self._state_queried: set[str] = set()
        self._last_emit = 0.0
        self._emit_interval = 0.25

    @property
    def connected(self) -> bool:
        return self._connected

    def snapshot_for_ips(self, allowed_ips: set[str] | list[str] | None = None):
        """Return (readings, names, firmware) filtered to *allowed_ips* when set."""
        allowed = set(allowed_ips) if allowed_ips else None
        with self._lock:
            readings = {}
            names = dict(self._names)
            firmware = dict(self._firmware)
            for key, row in self._by_ip.items():
                ip = row.get("ip") or key
                if allowed is not None and ip not in allowed:
                    continue
                readings[ip] = dict(row)
            if allowed is not None:
                names = {k: v for k, v in names.items() if k in allowed}
                firmware = {k: v for k, v in firmware.items() if k in allowed}
        return readings, names, firmware

    def stop(self) -> None:
        self._running = False
        self._connected = False
        client = self._client
        self._client = None
        if client is not None:
            try:
                client.loop_stop()
            except Exception:
                pass
            try:
                client.disconnect()
            except Exception:
                pass
        self._on_status("MQTT stopped")

    def start(
        self,
        host: str,
        port: int = 1883,
        *,
        username: str = "",
        password: str = "",
        topic_prefix: str = "",
        client_id: str = "energy_dashboard_tasmota",
    ) -> tuple[bool, str]:
        if mqtt is None:
            return False, "paho-mqtt not installed (pip install paho-mqtt)"
        host = (host or "").strip()
        if not host:
            return False, "MQTT broker host is required"
        self.stop()
        prefix = (topic_prefix or "").strip()
        if prefix and not prefix.endswith("/"):
            prefix += "/"

        try:
            try:
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION1,
                    client_id=client_id,
                )
            except (TypeError, AttributeError):
                client = mqtt.Client(client_id=client_id)
        except Exception as e:
            return False, f"MQTT client: {e}"

        if username:
            client.username_pw_set(username, password or None)

        client.on_connect = self._mk_on_connect(prefix)
        client.on_disconnect = self._mk_on_disconnect()
        client.on_message = self._mk_on_message()
        self._client = client
        self._running = True
        self._on_status(f"MQTT connecting to {host}:{port}…")

        try:
            client.connect(host, int(port), keepalive=60)
            client.loop_start()
        except Exception as e:
            self.stop()
            return False, str(e)
        return True, f"MQTT connecting to {host}:{port}"

    def _mk_on_connect(self, prefix: str):
        def _on_connect(client, userdata, flags, rc, *args):
            ok = rc == 0
            self._connected = ok
            if not ok:
                self._on_status(f"MQTT connect failed (rc={rc})")
                return
            self._prefix = prefix
            self._state_queried.clear()
            for tpl in self._SUB_TOPICS:
                topic = f"{prefix}{tpl}"
                client.subscribe(topic)
            self._on_status(f"MQTT subscribed ({prefix or ''}tele/+, stat/+)")
        return _on_connect

    def _query_relay_state(self, device_topic: str) -> None:
        """Ask a device for its current relay state (one-shot per topic).

        Tasmota answers an empty ``cmnd/<topic>/POWER`` with the current
        state on ``stat/<topic>/RESULT`` (or ``.../POWER``), so the switch
        renders correctly without waiting for the next periodic STATE.
        """
        if not device_topic or device_topic in self._state_queried:
            return
        client = self._client
        if client is None or not self._connected:
            return
        self._state_queried.add(device_topic)
        try:
            client.publish(f"{self._prefix}cmnd/{device_topic}/POWER", "")
        except Exception:
            pass

    def _mk_on_disconnect(self):
        def _on_disconnect(client, userdata, rc, *args):
            self._connected = False
            if self._running:
                self._on_status(
                    "MQTT disconnected"
                    if rc == 0
                    else f"MQTT disconnected (rc={rc})"
                )
        return _on_disconnect

    def _mk_on_message(self):
        def _on_message(client, userdata, msg):
            self._handle_message(msg.topic, msg.payload)
        return _on_message

    def _set_relay(self, key: str, relay: bool, *, ip: str | None = None) -> None:
        """Store relay state on the row for *key* (and mirror to *ip*).

        Must be called with ``self._lock`` held.
        """
        row = self._by_ip.get(key)
        if row is None:
            row = _blank_reading(ip or key)
            row["relay_on"] = relay
            self._by_ip[key] = row
        else:
            row["relay_on"] = relay
            if ip and not row.get("ip"):
                row["ip"] = ip
        if ip and ip != key:
            self._by_ip[ip] = row

    def _resolve_key(self, device_topic: str, ip: str | None) -> str:
        if ip:
            self._topic_to_ip[device_topic] = ip
            self._topic_to_key[device_topic] = ip
            return ip
        return self._topic_to_ip.get(device_topic) or device_topic

    def _handle_message(self, topic: str, payload: bytes) -> None:
        parsed = _topic_parts(topic)
        if not parsed:
            return
        root, device_topic, suffix = parsed
        changed = False

        self._query_relay_state(device_topic)

        try:
            if suffix == "POWER" and root == "stat":
                relay = _parse_power_payload(payload)
                if relay is None:
                    return
                with self._lock:
                    self._set_relay(self._resolve_key(device_topic, None), relay)
                changed = True
            else:
                try:
                    data = json.loads(payload.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    return
                if not isinstance(data, dict):
                    return

                if suffix == "RESULT" and root == "stat":
                    relay = _parse_state_power(data)
                    if relay is not None:
                        with self._lock:
                            self._set_relay(
                                self._resolve_key(device_topic, None), relay
                            )
                        changed = True

                if suffix == "STATE" and root == "tele":
                    ip = str(data.get("IPAddress") or "").strip()
                    name = _friendly_name(data)
                    fw = str(
                        data.get("Version")
                        or data.get("BuildVersion")
                        or data.get("Module")
                        or ""
                    ).strip()
                    relay = _parse_state_power(data)
                    with self._lock:
                        key = self._resolve_key(device_topic, ip or None)
                        if name:
                            self._names[key] = name
                        if fw:
                            self._firmware[key] = fw
                        if ip:
                            self._names[ip] = name or self._names.get(key, ip)
                            if fw:
                                self._firmware[ip] = fw
                        if relay is not None:
                            self._set_relay(key, relay, ip=ip or None)
                    changed = True

                energy = _energy_block(data)
                if energy:
                    ip_hint = str(data.get("IPAddress") or "").strip()
                    with self._lock:
                        key = self._resolve_key(device_topic, ip_hint or None)
                        row = _reading_from_energy(key, energy)
                        prev = self._by_ip.get(key)
                        if prev and prev.get("relay_on") is not None:
                            row["relay_on"] = prev["relay_on"]
                        self._by_ip[key] = row
                        if ip_hint:
                            self._by_ip[ip_hint] = row
                    changed = True
        except Exception:
            return

        if changed:
            now = time.monotonic()
            if now - self._last_emit >= self._emit_interval:
                self._last_emit = now
                self._on_update()


def test_tasmota_mqtt_connection(
    host: str,
    port: int = 1883,
    *,
    username: str = "",
    password: str = "",
    timeout: float = 8.0,
) -> tuple[bool, str]:
    """One-shot TCP/MQTT connect test (does not subscribe)."""
    if mqtt is None:
        return False, "paho-mqtt not installed (pip install paho-mqtt)"
    host = (host or "").strip()
    if not host:
        return False, "MQTT host is required"
    port = int(port)
    done = threading.Event()
    outcome: dict[str, Any] = {"ok": False, "msg": "timeout"}

    def _on_connect(client, userdata, flags, rc, *args):
        if rc == 0:
            outcome["ok"] = True
            auth = f" as {username}" if username else ""
            outcome["msg"] = f"OK — connected to {host}:{port}{auth}"
        else:
            outcome["msg"] = f"Broker refused connection (rc={rc})"
        done.set()

    try:
        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id="energy_dashboard_mqtt_test",
            )
        except (TypeError, AttributeError):
            client = mqtt.Client(client_id="energy_dashboard_mqtt_test")
    except Exception as e:
        return False, str(e)

    if username:
        client.username_pw_set(username, password or None)
    client.on_connect = _on_connect

    try:
        client.connect(host, port, keepalive=15)
        client.loop_start()
        if not done.wait(timeout=max(1.0, float(timeout))):
            outcome["msg"] = (
                f"Timeout after {timeout:.0f}s — no response from {host}:{port}"
            )
    except Exception as e:
        outcome["msg"] = str(e)
    finally:
        try:
            client.loop_stop()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass

    return bool(outcome["ok"]), str(outcome["msg"])
