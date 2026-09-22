"""
Growatt pipeline probe — trace Modbus / GROTT / EMQX / dashboard hops.

Runs synchronously (call from a worker thread).  Each hop returns ok / warn /
bad / off / idle.  Links between hops are evaluated to surface the first break
in the chain.  Growatt cloud API is a separate peer (not probed as a TCP hop
here); Modbus is independent of GROTT.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from PySide6.QtCore import QSettings

from energy_dashboard.config import (
    GROWATT_TELEMETRY_API,
    GROWATT_TELEMETRY_GROTT,
    GROWATT_TELEMETRY_HYBRID,
    growatt_modbus_tcp_host,
    growatt_modbus_uses_lan_tcp,
    growatt_uses_grott,
    read_growatt_telemetry_source,
)
from energy_dashboard.fetch.grott_mqtt import (
    _DEFAULT_GROTT_TOPIC,
    _normalize_grott_payload,
    _topic_filters,
    grott_snapshot_fresh,
)

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None  # type: ignore


_STATE_RANK = {"bad": 0, "warn": 1, "idle": 2, "ok": 3, "off": 4}


def _worst(*states: str) -> str:
    best = "off"
    for st in states:
        if _STATE_RANK.get(st, 99) < _STATE_RANK.get(best, 99):
            best = st
    return best


def _tcp_open(host: str, port: int, timeout: float = 4.0) -> tuple[bool, str, float | None]:
    host = (host or "").strip()
    if not host:
        return False, "host not configured", None
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            ms = (time.monotonic() - t0) * 1000.0
            return True, f"TCP {host}:{port} open ({ms:.0f} ms)", ms
    except OSError as exc:
        return False, f"TCP {host}:{port} failed — {exc}", None


@dataclass
class PipelineHopResult:
    hop_id: str
    label: str
    state: str
    detail: str
    latency_ms: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineLinkResult:
    link_id: str
    from_hop: str
    to_hop: str
    label: str
    state: str
    detail: str


@dataclass
class PipelineProbeReport:
    started_at: datetime
    finished_at: datetime
    telemetry_source: str
    hops: list[PipelineHopResult]
    links: list[PipelineLinkResult]
    breaks: list[str]

    @property
    def duration_s(self) -> float:
        return max(0.0, (self.finished_at - self.started_at).total_seconds())

    def hop(self, hop_id: str) -> PipelineHopResult | None:
        for h in self.hops:
            if h.hop_id == hop_id:
                return h
        return None


def _probe_modbus(params) -> PipelineHopResult:
    mode = (getattr(params, "growatt_modbus_mode", "off") or "off").lower()
    if mode == "off":
        return PipelineHopResult(
            "modbus",
            "Modbus",
            "off",
            "Modbus disabled in Setup (optional for this pipeline)",
        )
    host = growatt_modbus_tcp_host(params) if growatt_modbus_uses_lan_tcp(mode) else ""
    if growatt_modbus_uses_lan_tcp(mode):
        if not host:
            return PipelineHopResult(
                "modbus",
                "Modbus",
                "off",
                "Modbus TCP enabled but host IP is empty",
            )
        port = int(getattr(params, "growatt_modbus_tcp_port", 502) or 502)
        ok, detail, ms = _tcp_open(host, port)
        return PipelineHopResult(
            "modbus",
            "Modbus",
            "ok" if ok else "bad",
            detail,
            latency_ms=ms,
            extra={"host": host, "port": port, "mode": mode},
        )
    path = (getattr(params, "growatt_modbus_serial_path", "") or "").strip()
    if not path:
        return PipelineHopResult(
            "modbus",
            "Modbus",
            "warn",
            "Modbus RTU configured but serial path is empty",
            extra={"mode": mode},
        )
    return PipelineHopResult(
        "modbus",
        "Modbus",
        "idle",
        f"RTU path {path} — serial probe not run (TCP-only check in pipeline probe)",
        extra={"mode": mode, "path": path},
    )


def _read_mqtt_settings(params, settings: QSettings | None) -> dict[str, Any]:
    settings = settings or QSettings("PowerModel", "EnergyDashboard2")

    def _val(attr: str, key: str, default: Any = "") -> Any:
        if settings.contains(key):
            return settings.value(key, default)
        return getattr(params, attr, default) if params is not None else default

    emqx_host = str(_val("grott_mqtt_host", "params/emqx_host", "") or "").strip()
    if not emqx_host:
        emqx_host = str(_val("grott_mqtt_host", "params/grott_mqtt_host", "") or "").strip()
    emqx_port = int(_val("grott_mqtt_port", "params/emqx_port", 1883) or 1883)
    if settings.contains("params/grott_mqtt_port") and not settings.contains("params/emqx_port"):
        emqx_port = int(_val("grott_mqtt_port", "params/grott_mqtt_port", 1883) or 1883)

    topic_raw = str(
        _val("grott_mqtt_topic", "params/grott_mqtt_topic", _DEFAULT_GROTT_TOPIC)
        or _DEFAULT_GROTT_TOPIC
    ).strip()
    if topic_raw in ("grott/#", "#"):
        topic_raw = _DEFAULT_GROTT_TOPIC

    user = str(_val("grott_mqtt_user", "params/emqx_user", "") or "").strip()
    if not user:
        user = str(_val("grott_mqtt_user", "params/grott_mqtt_user", "") or "").strip()
    password = str(_val("grott_mqtt_password", "params/emqx_password", "") or "")
    if password == "" and settings.contains("params/grott_mqtt_password"):
        password = str(_val("grott_mqtt_password", "params/grott_mqtt_password", "") or "")

    return {
        "host": emqx_host,
        "port": max(1, min(65535, emqx_port)),
        "user": user,
        "password": password,
        "topic": topic_raw,
        "fresh_s": int(_val("grott_mqtt_fresh_s", "params/grott_mqtt_fresh_s", 150) or 150),
    }


def _probe_emqx_broker(mqtt_cfg: dict[str, Any]) -> PipelineHopResult:
    host = mqtt_cfg.get("host") or ""
    port = int(mqtt_cfg.get("port") or 1883)
    if not host:
        return PipelineHopResult(
            "emqx",
            "EMQX MQTT broker",
            "off",
            "MQTT broker host not configured (Setup → EMQX / Grott MQTT)",
        )
    ok, detail, ms = _tcp_open(host, port)
    if not ok:
        return PipelineHopResult("emqx", "EMQX MQTT broker", "bad", detail, extra={"host": host, "port": port})

    from energy_dashboard.fetch.mqtt_session import broker_session

    if broker_session().shares_broker(host, port):
        return PipelineHopResult(
            "emqx",
            "EMQX MQTT broker",
            "ok",
            f"MQTT already connected on the shared session {host}:{port} ({ms:.0f} ms TCP)",
            latency_ms=ms,
            extra={"host": host, "port": port},
        )

    if mqtt is None:
        return PipelineHopResult(
            "emqx",
            "EMQX MQTT broker",
            "warn",
            f"{detail}; paho-mqtt not installed — auth not verified",
            latency_ms=ms,
            extra={"host": host, "port": port},
        )

    auth_ok = {"rc": -1}

    def on_connect(client, userdata, flags, rc, *args):
        auth_ok["rc"] = rc

    try:
        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id=f"pipeline_emqx_{int(time.time())}",
                clean_session=True,
            )
        except (TypeError, AttributeError):
            client = mqtt.Client(client_id=f"pipeline_emqx_{int(time.time())}", clean_session=True)
    except Exception as exc:
        return PipelineHopResult(
            "emqx",
            "EMQX MQTT broker",
            "bad",
            f"TCP open but MQTT client failed: {exc}",
            latency_ms=ms,
            extra={"host": host, "port": port},
        )

    user = mqtt_cfg.get("user") or ""
    if user:
        client.username_pw_set(user, mqtt_cfg.get("password") or None)
    client.on_connect = on_connect
    try:
        client.connect(host, port, keepalive=30)
        client.loop_start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and auth_ok["rc"] == -1:
            time.sleep(0.05)
        client.loop_stop()
        client.disconnect()
    except Exception as exc:
        try:
            client.loop_stop()
        except Exception:
            pass
        return PipelineHopResult(
            "emqx",
            "EMQX MQTT broker",
            "bad",
            f"TCP open but MQTT connect failed: {exc}",
            latency_ms=ms,
            extra={"host": host, "port": port},
        )

    rc = auth_ok["rc"]
    if rc != 0:
        return PipelineHopResult(
            "emqx",
            "EMQX MQTT broker",
            "bad",
            f"MQTT connect rejected (rc={rc}) on {host}:{port}",
            latency_ms=ms,
            extra={"host": host, "port": port, "rc": rc},
        )
    return PipelineHopResult(
        "emqx",
        "EMQX MQTT broker",
        "ok",
        f"MQTT auth OK on {host}:{port} ({ms:.0f} ms TCP)",
        latency_ms=ms,
        extra={"host": host, "port": port},
    )


def _probe_grott_publish(
    mqtt_cfg: dict[str, Any],
    *,
    wait_s: float = 20.0,
    progress: Callable[[str], None] | None = None,
) -> PipelineHopResult:
    host = mqtt_cfg.get("host") or ""
    port = int(mqtt_cfg.get("port") or 1883)
    topic_filter = mqtt_cfg.get("topic") or _DEFAULT_GROTT_TOPIC
    filters = _topic_filters(topic_filter)
    listen_topic = _DEFAULT_GROTT_TOPIC

    if not host:
        return PipelineHopResult(
            "grott",
            "GROTT publish",
            "off",
            "MQTT broker not configured",
        )
    from energy_dashboard.fetch.mqtt_session import broker_session

    if broker_session().shares_broker(host, port):
        return PipelineHopResult(
            "grott",
            "GROTT publish",
            "ok",
            f"Shared MQTT session already connected to {host}:{port} — not opening a second listener",
            extra={"host": host, "port": port, "topic": listen_topic},
        )
    if mqtt is None:
        return PipelineHopResult(
            "grott",
            "GROTT publish",
            "warn",
            "paho-mqtt not installed — cannot listen for Grott JSON",
        )

    result: dict[str, Any] = {"topic": "", "keys": [], "device": ""}
    done = threading.Event()

    def on_connect(client, userdata, flags, rc, *args):
        if rc != 0:
            result["error"] = f"connect rc={rc}"
            done.set()
            return
        client.subscribe(listen_topic)

    def on_message(client, userdata, msg):
        if msg.topic != listen_topic:
            return
        try:
            data = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        snap = _normalize_grott_payload(data, topic=msg.topic)
        if snap is None:
            return
        result["topic"] = msg.topic
        result["device"] = snap.get("serial") or data.get("device") or ""
        result["keys"] = sorted((snap.get("status") or {}).keys())
        done.set()

    if progress:
        progress(f"Listening on {host}:{port} · {listen_topic} (up to {wait_s:.0f}s)…")

    t0 = time.monotonic()
    try:
        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id=f"pipeline_grott_{int(time.time())}",
                clean_session=True,
            )
        except (TypeError, AttributeError):
            client = mqtt.Client(client_id=f"pipeline_grott_{int(time.time())}", clean_session=True)
    except Exception as exc:
        return PipelineHopResult("grott", "GROTT publish", "bad", str(exc))

    user = mqtt_cfg.get("user") or ""
    if user:
        client.username_pw_set(user, mqtt_cfg.get("password") or None)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(host, port, keepalive=30)
        client.loop_start()
        done.wait(timeout=wait_s)
        client.loop_stop()
        client.disconnect()
    except Exception as exc:
        try:
            client.loop_stop()
        except Exception:
            pass
        return PipelineHopResult(
            "grott",
            "GROTT publish",
            "bad",
            f"MQTT listen failed: {exc}",
            extra={"host": host, "port": port, "topic": listen_topic},
        )

    elapsed_ms = (time.monotonic() - t0) * 1000.0
    if result.get("error"):
        return PipelineHopResult(
            "grott",
            "GROTT publish",
            "bad",
            str(result["error"]),
            extra={"host": host, "port": port},
        )
    if not result.get("topic"):
        return PipelineHopResult(
            "grott",
            "GROTT publish",
            "bad",
            (
                f"No Growatt JSON on {listen_topic} within {wait_s:.0f}s — "
                "GROTT proxy may be stopped or not publishing"
            ),
            latency_ms=elapsed_ms,
            extra={"host": host, "port": port, "topic": listen_topic, "filters": filters},
        )
    keys = result.get("keys") or []
    detail = (
        f"Received {result['topic']} from {result.get('device') or 'inverter'}"
        f" ({elapsed_ms:.0f} ms) — fields: {', '.join(keys[:8])}"
        + ("…" if len(keys) > 8 else "")
    )
    return PipelineHopResult(
        "grott",
        "GROTT publish",
        "ok",
        detail,
        latency_ms=elapsed_ms,
        extra={"host": host, "port": port, "topic": result["topic"], "device": result.get("device")},
    )


def _probe_dashboard(
    dash,
    mqtt_cfg: dict[str, Any],
    *,
    telemetry_source: str,
) -> PipelineHopResult:
    gt = getattr(dash, "growatt_tab", None) if dash is not None else None
    if gt is None:
        return PipelineHopResult(
            "dashboard",
            "Energy Dashboard",
            "idle",
            "Growatt tab not available in this session",
        )

    st = getattr(gt, "mix_status_data", None) or {}
    has_live = bool(st) and any(
        st.get(k) not in (None, "", "--")
        for k in ("ppv", "SOC", "chargePower", "pdisCharge1", "pactouser", "pLocalLoad")
    )
    api_ok = gt.api is not None and bool(getattr(gt, "device_sn", None))

    if not growatt_uses_grott(telemetry_source):
        if has_live and api_ok:
            return PipelineHopResult(
                "dashboard",
                "Energy Dashboard",
                "ok",
                "Cloud API session active; live Growatt fields present in this app",
                extra={"source": telemetry_source, "api": True},
            )
        if api_ok:
            return PipelineHopResult(
                "dashboard",
                "Energy Dashboard",
                "warn",
                "Growatt API connected but live fields not loaded in the UI yet",
                extra={"source": telemetry_source, "api": True},
            )
        return PipelineHopResult(
            "dashboard",
            "Energy Dashboard",
            "bad",
            "No Growatt cloud session — connect on the Live tab (Grott pipeline not selected)",
            extra={"source": telemetry_source},
        )

    gs = gt.grott_status() if hasattr(gt, "grott_status") else {}
    snap = gt._grott.snapshot() if hasattr(gt, "_grott") else None
    fresh_s = max(15, int(mqtt_cfg.get("fresh_s") or 150))
    fresh = grott_snapshot_fresh(snap, fresh_s)
    connected = bool(gs.get("connected"))

    if fresh and has_live:
        age = gs.get("age_s")
        age_txt = f"{age:.0f}s old" if age is not None else "fresh"
        return PipelineHopResult(
            "dashboard",
            "Energy Dashboard",
            "ok",
            f"Grott subscriber connected; live bundle present ({age_txt})",
            extra={"connected": connected, "fresh": True, "serial": gs.get("serial")},
        )
    if telemetry_source == GROWATT_TELEMETRY_HYBRID and has_live and api_ok:
        return PipelineHopResult(
            "dashboard",
            "Energy Dashboard",
            "warn",
            "Grott path degraded — dashboard showing live data via cloud API fallback",
            extra={"connected": connected, "fresh": fresh, "hybrid_fallback": True},
        )
    if connected and snap and has_live:
        return PipelineHopResult(
            "dashboard",
            "Energy Dashboard",
            "warn",
            f"Subscriber connected but snapshot stale (>{fresh_s}s) — showing last reading",
            extra={"connected": connected, "fresh": False},
        )
    if connected and not has_live:
        return PipelineHopResult(
            "dashboard",
            "Energy Dashboard",
            "warn",
            "MQTT connected but no live Growatt fields in the UI yet — waiting for a full frame",
            extra={"connected": connected, "message": gs.get("message")},
        )
    if not connected:
        return PipelineHopResult(
            "dashboard",
            "Energy Dashboard",
            "bad",
            gs.get("message") or "Grott MQTT subscriber not connected",
            extra={"connected": False},
        )
    return PipelineHopResult(
        "dashboard",
        "Energy Dashboard",
        "bad",
        "No Grott snapshot in this app — pipeline break at dashboard ingest",
        extra={"connected": connected, "fresh": fresh},
    )


def _eval_link(
    link_id: str,
    from_hop: str,
    to_hop: str,
    label: str,
    upstream: PipelineHopResult,
    downstream: PipelineHopResult,
) -> PipelineLinkResult:
    up, down = upstream.state, downstream.state
    if up == "off" and down == "off":
        return PipelineLinkResult(link_id, from_hop, to_hop, label, "off", "Both hops inactive / not configured")
    if up in ("bad", "warn") and down in ("bad", "warn", "idle"):
        return PipelineLinkResult(
            link_id,
            from_hop,
            to_hop,
            label,
            "bad",
            f"Break near {upstream.label}: {upstream.detail}",
        )
    if up == "ok" and down == "bad":
        return PipelineLinkResult(
            link_id,
            from_hop,
            to_hop,
            label,
            "bad",
            f"Break between {upstream.label} and {downstream.label}: {downstream.detail}",
        )
    if up == "ok" and down == "warn":
        return PipelineLinkResult(
            link_id,
            from_hop,
            to_hop,
            label,
            "warn",
            f"Degraded: {downstream.detail}",
        )
    if up == "ok" and down == "ok":
        return PipelineLinkResult(link_id, from_hop, to_hop, label, "ok", "Path continuity OK")
    return PipelineLinkResult(
        link_id,
        from_hop,
        to_hop,
        label,
        _worst(up, down),
        f"{upstream.label} → {downstream.label}: {_worst(up, down)}",
    )


def _collect_breaks(hops: list[PipelineHopResult], links: list[PipelineLinkResult]) -> list[str]:
    breaks: list[str] = []
    for h in hops:
        if h.state == "bad":
            breaks.append(f"{h.label}: {h.detail}")
    for ln in links:
        if ln.state == "bad":
            breaks.append(f"{ln.label}: {ln.detail}")
    if not breaks:
        warn_hops = [h for h in hops if h.state == "warn"]
        for h in warn_hops:
            breaks.append(f"(degraded) {h.label}: {h.detail}")
    return breaks


def run_growatt_pipeline_probe(
    params,
    *,
    dash=None,
    settings: QSettings | None = None,
    grott_wait_s: float = 20.0,
    progress: Callable[[str], None] | None = None,
) -> PipelineProbeReport:
    """Probe Growatt API / GROTT / Modbus peers → EMQX → dashboard and return structured results."""
    started = datetime.now()
    settings = settings or QSettings("PowerModel", "EnergyDashboard2")
    source = read_growatt_telemetry_source(settings, params)
    mqtt_cfg = _read_mqtt_settings(params, settings)

    hops: list[PipelineHopResult] = []

    if progress:
        progress("Probing Modbus…")
    hops.append(_probe_modbus(params))

    if progress:
        progress("Probing EMQX MQTT broker…")
    hops.append(_probe_emqx_broker(mqtt_cfg))

    if growatt_uses_grott(source):
        if progress:
            progress("Waiting for GROTT publish on energy/growatt…")
        hops.append(_probe_grott_publish(mqtt_cfg, wait_s=grott_wait_s, progress=progress))
    else:
        hops.append(PipelineHopResult(
            "grott",
            "GROTT publish",
            "off",
            f"Telemetry source is {_source_label(source)} — GROTT hop skipped",
        ))

    if progress:
        progress("Checking Energy Dashboard ingest…")
    hops.append(_probe_dashboard(dash, mqtt_cfg, telemetry_source=source))

    by_id = {h.hop_id: h for h in hops}
    grott = by_id["grott"]
    emqx = by_id["emqx"]
    dash_hop = by_id["dashboard"]

    # Three Growatt methods: cloud API (separate), Grott→EMQX, Modbus (separate).
    # Do not treat Modbus as Grott's upstream.
    links = [
        _eval_link(
            "inv_grott",
            "grott",
            "grott",
            "Inverter report → GROTT",
            grott,
            grott,
        ),
        _eval_link(
            "grott_emqx",
            "grott",
            "emqx",
            "GROTT → EMQX",
            grott,
            emqx,
        ),
        _eval_link(
            "emqx_dashboard",
            "emqx",
            "dashboard",
            "EMQX → Dashboard",
            emqx,
            dash_hop,
        ),
    ]

    breaks = _collect_breaks(hops, links)
    return PipelineProbeReport(
        started_at=started,
        finished_at=datetime.now(),
        telemetry_source=source,
        hops=hops,
        links=links,
        breaks=breaks,
    )


def _source_label(source: str) -> str:
    if source == GROWATT_TELEMETRY_HYBRID:
        return "Hybrid (Grott → API)"
    if source == GROWATT_TELEMETRY_GROTT:
        return "GROTT MQTT"
    return "Growatt Cloud API"


__all__ = [
    "PipelineHopResult",
    "PipelineLinkResult",
    "PipelineProbeReport",
    "run_growatt_pipeline_probe",
]
