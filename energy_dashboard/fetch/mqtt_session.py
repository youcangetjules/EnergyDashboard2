"""One MQTT connection for the whole dashboard.

Grott and the Tasmota tab used to open their own clients. Grott also minted a
new client name on every start, so EMQX kept several sessions from this app
and a second window fought the first. This module owns a single paho client
named ``energy_dashboard``. A second dashboard process does not connect: it
leaves the existing session alone.
"""
from __future__ import annotations

import fcntl
import os
import threading
from pathlib import Path
from typing import Any, Callable

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None  # type: ignore


CLIENT_ID = "energy_dashboard"
_LOCK_PATH = Path.home() / ".energy_dashboard_mqtt.lock"

OnMessage = Callable[[str, bytes], None]
OnState = Callable[[bool, str, str], None]


def mqtt_topic_matches(topic: str, filt: str) -> bool:
    """True when *topic* matches an MQTT filter (``+`` and ``#``)."""
    topic = (topic or "").strip()
    filt = (filt or "").strip()
    if not topic or not filt:
        return False
    tparts = topic.split("/")
    fparts = filt.split("/")
    for i, fp in enumerate(fparts):
        if fp == "#":
            return i == len(fparts) - 1
        if i >= len(tparts):
            return False
        if fp != "+" and fp != tparts[i]:
            return False
    return len(fparts) == len(tparts)


class _Member:
    def __init__(
        self,
        member_id: str,
        filters: tuple[str, ...],
        on_message: OnMessage,
        on_state: OnState | None,
    ):
        self.member_id = member_id
        self.filters = filters
        self.on_message = on_message
        self.on_state = on_state


class MqttBrokerSession:
    """Process-wide broker socket. Grott and Tasmota subscribe through it."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._open_lock = threading.Lock()
        self._client: Any = None
        self._host = ""
        self._port = 0
        self._running = False
        self._connected = False
        self._loop_started = False
        self._members: dict[str, _Member] = {}
        self._lock_fh: Any = None
        self._watchdog_stop = threading.Event()
        self._watchdog: threading.Thread | None = None
        self._yielded = False

    @property
    def connected(self) -> bool:
        return self._connected

    def shares_broker(self, host: str, port: int) -> bool:
        host = (host or "").strip()
        with self._lock:
            return bool(
                self._connected
                and self._host == host
                and self._port == int(port)
            )

    def bind(
        self,
        member_id: str,
        host: str,
        port: int = 1883,
        *,
        username: str = "",
        password: str = "",
        filters: tuple[str, ...] | list[str] = (),
        on_message: OnMessage,
        on_state: OnState | None = None,
    ) -> tuple[bool, str]:
        """Subscribe *member_id* on the one broker socket.

        A second call for the same broker does not open another connection.
        """
        if mqtt is None:
            return False, "paho-mqtt not installed (pip install paho-mqtt)"
        host = (host or "").strip()
        if not host:
            return False, "MQTT broker host is required"
        port = int(port)
        filt = tuple(f.strip() for f in filters if (f or "").strip())
        member = _Member(member_id, filt, on_message, on_state)
        with self._lock:
            self._members[member_id] = member
            self._running = True
            self._yielded = False
            same_up = (
                self._client is not None
                and self._loop_started
                and self._connected
                and self._host == host
                and self._port == port
            )
            if same_up:
                client = self._client
            else:
                client = None
        if client is not None:
            self._subscribe_filters(client, filt)
            self._notify(member, True, "joined", f"{host}:{port}")
            return True, f"MQTT already connected to {host}:{port}"
        return self._open(host, port, username or "", password or "")

    def unbind(self, member_id: str) -> None:
        """Drop one subscriber. The socket stays up while anyone else needs it."""
        with self._lock:
            self._members.pop(member_id, None)
            if self._members:
                return
            client = self._client
            self._client = None
            self._running = False
            self._connected = False
            self._loop_started = False
            self._watchdog_stop.set()
        if client is not None:
            self._drop_client(client)
        self._release_process_lock()

    def resubscribe(self, member_id: str) -> tuple[bool, str]:
        with self._lock:
            member = self._members.get(member_id)
            client = self._client
            connected = self._connected
        if member is None or client is None:
            return False, "MQTT not running"
        if not connected:
            return False, "MQTT socket is down — the shared client will reconnect"
        try:
            self._subscribe_filters(client, member.filters)
        except Exception as exc:
            return False, f"MQTT re-subscribe failed: {exc}"
        return True, "MQTT topics re-subscribed on the shared connection"

    def publish(self, topic: str, payload: str | bytes = "") -> bool:
        with self._lock:
            client = self._client
            connected = self._connected
        if not connected or client is None:
            return False
        try:
            client.publish(topic, payload)
            return True
        except Exception:
            return False

    def _open(self, host: str, port: int, username: str, password: str) -> tuple[bool, str]:
        with self._open_lock:
            with self._lock:
                pending_same = (
                    self._client is not None
                    and self._loop_started
                    and self._host == host
                    and self._port == port
                )
                client = self._client
                connected = self._connected
                filters: list[str] = []
                if pending_same:
                    for member in self._members.values():
                        filters.extend(member.filters)
            if pending_same:
                if connected and client is not None:
                    self._subscribe_filters(client, filters)
                    return True, f"MQTT already connected to {host}:{port}"
                return True, f"MQTT connecting to {host}:{port}"
            if not self._acquire_process_lock():
                return (
                    False,
                    "Another Energy Dashboard already holds the MQTT connection. "
                    "Close that window — this one will not open a second session.",
                )
            with self._lock:
                old = self._client
                self._client = None
                self._connected = False
                self._loop_started = False
                self._host = host
                self._port = port
            if old is not None:
                self._drop_client(old)
            try:
                try:
                    client = mqtt.Client(
                        mqtt.CallbackAPIVersion.VERSION1,
                        client_id=CLIENT_ID,
                        clean_session=True,
                    )
                except (TypeError, AttributeError):
                    try:
                        client = mqtt.Client(client_id=CLIENT_ID, clean_session=True)
                    except TypeError:
                        client = mqtt.Client(client_id=CLIENT_ID)
            except Exception as exc:
                self._release_process_lock()
                return False, f"MQTT client: {exc}"
            if username:
                client.username_pw_set(username, password or None)
            try:
                client.reconnect_delay_set(min_delay=2, max_delay=30)
            except Exception:
                pass
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message
            # Reconnect ourselves. Paho's own loop plus an extra reconnect()
            # from the disconnect callback was opening a second socket.
            try:
                client.reconnect_on_failure = False
            except Exception:
                pass
            with self._lock:
                self._client = client
            try:
                client.connect(host, int(port), keepalive=60)
                client.loop_start()
            except Exception as exc:
                self._drop_client(client)
                with self._lock:
                    if self._client is client:
                        self._client = None
                self._release_process_lock()
                return False, str(exc)
            with self._lock:
                self._loop_started = True
            self._ensure_watchdog()
            return True, f"MQTT connecting to {host}:{port}"

    def _acquire_process_lock(self) -> bool:
        """One dashboard process may own the broker session."""
        if self._lock_fh is not None:
            return True
        try:
            fh = open(_LOCK_PATH, "a+", encoding="utf-8")
        except OSError:
            return True
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.close()
            return False
        try:
            fh.seek(0)
            fh.truncate()
            fh.write(str(os.getpid()))
            fh.flush()
        except OSError:
            pass
        self._lock_fh = fh
        return True

    def _release_process_lock(self) -> None:
        fh = self._lock_fh
        self._lock_fh = None
        if fh is None:
            return
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            fh.close()
        except OSError:
            pass

    def _ensure_watchdog(self) -> None:
        with self._lock:
            if self._watchdog is not None and self._watchdog.is_alive():
                return
            self._watchdog_stop = threading.Event()
            t = threading.Thread(
                target=self._watchdog_loop,
                name="mqtt-broker-watchdog",
                daemon=True,
            )
            self._watchdog = t
            t.start()

    def _watchdog_loop(self) -> None:
        """Reconnect the same client if the socket is down. Never opens another."""
        while not self._watchdog_stop.wait(15.0):
            with self._lock:
                if not self._running or not self._members or self._yielded:
                    continue
                client = self._client
                connected = self._connected
            if client is None or connected:
                continue
            try:
                if client.is_connected():
                    continue
            except Exception:
                pass
            try:
                client.reconnect()
                client.loop_start()
            except Exception:
                pass

    def _on_connect(self, client, userdata, flags, rc, *args) -> None:
        with self._lock:
            if client is not self._client:
                return
            ok = int(rc or 0) == 0
            self._connected = ok
            members = list(self._members.values())
            filters: list[str] = []
            if ok:
                for member in members:
                    filters.extend(member.filters)
        if not ok:
            for member in members:
                self._notify(member, False, "connect_fail", f"rc={rc}")
            return
        seen: set[str] = set()
        for filt in filters:
            if filt in seen:
                continue
            seen.add(filt)
            try:
                client.subscribe(filt)
            except Exception:
                pass
        for member in members:
            self._notify(member, True, "connect", "rc=0")

    def _on_disconnect(self, client, userdata, rc, *args) -> None:
        with self._lock:
            if client is not self._client:
                return
            self._connected = False
            if not self._running:
                return
            members = list(self._members.values())
            # Another dashboard took the client name. Stop retrying so the
            # broker is left with that one session instead of a kick loop.
            taken = int(rc or 0) in (7, 142)
            if taken:
                self._yielded = True
        detail = "clean disconnect" if int(rc or 0) == 0 else f"unexpected disconnect rc={rc}"
        if taken:
            detail = (
                "another Energy Dashboard took the broker session "
                f"(rc={rc}); this window will not open a second connection"
            )
        for member in members:
            self._notify(member, False, "disconnect", detail)
        # Reconnect from the watchdog, not from this callback. Calling
        # reconnect() here while the network thread is still inside the
        # disconnect handler is what opened a second socket.

    def _on_message(self, client, userdata, msg) -> None:
        with self._lock:
            members = list(self._members.values())
        topic = getattr(msg, "topic", "") or ""
        payload = getattr(msg, "payload", b"") or b""
        for member in members:
            if not any(mqtt_topic_matches(topic, filt) for filt in member.filters):
                continue
            try:
                member.on_message(topic, payload)
            except Exception:
                pass

    @staticmethod
    def _subscribe_filters(client, filters: tuple[str, ...] | list[str]) -> None:
        for filt in filters:
            if filt:
                client.subscribe(filt)

    @staticmethod
    def _notify(member: _Member, connected: bool, kind: str, detail: str) -> None:
        if member.on_state is None:
            return
        try:
            member.on_state(connected, kind, detail)
        except Exception:
            pass

    @staticmethod
    def _drop_client(client) -> None:
        try:
            client.loop_stop()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass


_SESSION: MqttBrokerSession | None = None
_SESSION_GUARD = threading.Lock()


def broker_session() -> MqttBrokerSession:
    global _SESSION
    with _SESSION_GUARD:
        if _SESSION is None:
            _SESSION = MqttBrokerSession()
        return _SESSION
