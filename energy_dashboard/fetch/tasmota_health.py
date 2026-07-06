"""
Parse Tasmota HTTP Status responses into a compact device health summary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from energy_dashboard.fetch.octopus_rest import (
    poll_tasmota_device,
    poll_tasmota_device_meta,
    tasmota_send_cmnd,
)


@dataclass
class TasmotaDeviceHealth:
    ip: str
    reachable: bool = False
    device_name: str = ""
    firmware: str = ""
    fetch_ms: float = 0.0
    errors: list[str] = field(default_factory=list)

    # Connectivity
    hostname: str = ""
    ip_reported: str = ""
    gateway: str = ""
    uptime: str = ""
    webserver: str = ""

    # WiFi — Tasmota names are historical: RSSI=0–100% quality, Signal=dBm at receiver
    wifi_ssid: str = ""
    wifi_signal_pct: int | None = None  # link quality %
    wifi_rssi_dbm: int | None = None  # receiver strength (dBm)
    wifi_link_count: int | None = None
    wifi_downtime: str = ""

    # Reboots / stability
    last_restart_reason: str = ""
    restart_count: int | None = None
    mqtt_reconnect_count: int | None = None

    # MQTT publish setup (on device)
    mqtt_enabled: bool = False
    mqtt_host: str = ""
    mqtt_port: int | None = None
    mqtt_user: str = ""
    mqtt_topic: str = ""
    mqtt_full_topic: str = ""
    mqtt_client: str = ""
    mqtt_connected: bool | None = None
    mqtt_tele_topic: str = ""
    mqtt_stat_topic: str = ""

    # CPU — Tasmota 15+ uses StatusSTS.LoadAvg (Status 11); older builds use Load
    cpu_metric: str = ""
    cpu_load_samples: list[int] = field(default_factory=list)
    cpu_load_current: int | None = None
    cpu_load_avg: int | None = None
    cpu_load_peak: int | None = None
    sleep_interval_ms: int | None = None
    sleep_mode: str = ""

    # Logging / telemetry (Status 3 — StatusLOG)
    web_log_level: int | None = None
    web_log_original: int | None = None
    web_log_boosted: bool = False
    mqtt_log_level: int | None = None
    serial_log_level: int | None = None
    sys_log_level: int | None = None
    tele_period_s: int | None = None
    log_host: str = ""
    log_port: int | None = None

    # Memory / flash (Status 4 — StatusMEM)
    heap_kb: int | None = None
    heap_free_kb: int | None = None
    program_size_kb: int | None = None
    flash_size_kb: int | None = None
    program_flash_size_kb: int | None = None
    flash_mode: str = ""
    flash_chip_id: str = ""
    stack_high_water: int | None = None
    mem_features: str = ""
    mem_drivers: str = ""
    mem_sensors: str = ""

    # Troubleshooting (why the dashboard row may be blank or wrong)
    probe_checks: list["TasmotaProbeCheck"] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    dashboard_has_row: bool = False
    status8_has_energy: bool = False
    power_cmd_ok: bool = False
    poll_row_ok: bool = False
    status3_ok: bool = False
    status4_ok: bool = False


@dataclass
class TasmotaProbeCheck:
    label: str
    ok: bool
    detail: str = ""
    ms: float = 0.0


def _dig(data: dict | None, *keys, default=None):
    cur = data
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


def _as_int(val) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


_LOG_LEVEL_LABELS = {
    0: "off",
    1: "errors only",
    2: "error + info",
    3: "debug",
    4: "verbose (HW / socket)",
}


def _log_level_label(level: int | None) -> str:
    if level is None:
        return "—"
    return _LOG_LEVEL_LABELS.get(level, str(level))


def _parse_size_kb(val) -> int | None:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip().lower().replace("kb", "").strip()
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _apply_status_log(health: TasmotaDeviceHealth, payload: dict | None) -> None:
    log = _dig(payload, "StatusLOG") or {}
    if not log:
        return
    health.status3_ok = True
    health.web_log_level = _as_int(log.get("WebLog"))
    health.mqtt_log_level = _as_int(log.get("MqttLog"))
    health.serial_log_level = _as_int(log.get("SerialLog"))
    health.sys_log_level = _as_int(log.get("SysLog"))
    health.tele_period_s = _as_int(log.get("TelePeriod"))
    health.log_host = str(log.get("LogHost") or "").strip()
    health.log_port = _as_int(log.get("LogPort"))


def _apply_status_mem(health: TasmotaDeviceHealth, payload: dict | None) -> None:
    mem = _dig(payload, "StatusMEM") or {}
    if not mem:
        return
    health.status4_ok = True
    health.heap_kb = _parse_size_kb(mem.get("Heap"))
    health.heap_free_kb = _parse_size_kb(mem.get("Free"))
    health.program_size_kb = _parse_size_kb(mem.get("ProgramSize"))
    health.flash_size_kb = _parse_size_kb(mem.get("FlashSize"))
    health.program_flash_size_kb = _parse_size_kb(mem.get("ProgramFlashSize"))
    fm = mem.get("FlashMode")
    health.flash_mode = str(fm) if fm is not None else ""
    health.flash_chip_id = str(mem.get("FlashChipId") or mem.get("FlashChipID") or "").strip()
    health.stack_high_water = _as_int(mem.get("StackHighWaterMark"))
    health.mem_features = str(mem.get("Features") or "").strip()
    health.mem_drivers = str(mem.get("Drivers") or "").strip()
    health.mem_sensors = str(mem.get("Sensors") or "").strip()


def _boost_weblog_for_diagnose(
    ip: str,
    health: TasmotaDeviceHealth,
    *,
    timeout: float,
) -> None:
    """Temporarily set WebLog 4 for verbose HW/socket errors; restore after diagnose."""
    original = health.web_log_level
    if original is None:
        return
    health.web_log_original = original
    if original == 4:
        return
    tasmota_send_cmnd(ip, "WebLog 4", timeout=timeout)
    health.web_log_level = 4
    health.web_log_boosted = True


def _restore_weblog_after_diagnose(
    ip: str,
    health: TasmotaDeviceHealth,
    *,
    timeout: float,
) -> None:
    if not health.web_log_boosted or health.web_log_original is None:
        return
    tasmota_send_cmnd(ip, f"WebLog {health.web_log_original}", timeout=timeout)
    health.web_log_level = health.web_log_original


def _tasmota_wifi_metrics(wifi: dict) -> tuple[int | None, int | None]:
    """Parse Tasmota Wifi block into (quality_pct, rssi_dbm).

    Tasmota reports link quality as ``RSSI`` (0–100) and receiver strength in
    dBm as ``Signal``. Some builds only expose one field; derive the other.
    """
    raw_rssi = _as_int(wifi.get("RSSI"))
    raw_signal = _as_int(wifi.get("Signal"))

    quality_pct: int | None = None
    rssi_dbm: int | None = None

    for val in (raw_rssi, raw_signal):
        if val is None:
            continue
        if -120 <= val <= 0:
            rssi_dbm = val
        elif 0 <= val <= 100:
            quality_pct = val

    # Prefer official field names when both are present and unambiguous.
    if raw_rssi is not None and 0 <= raw_rssi <= 100:
        quality_pct = raw_rssi
    if raw_signal is not None and -120 <= raw_signal <= 0:
        rssi_dbm = raw_signal

    if quality_pct is None and rssi_dbm is not None:
        quality_pct = max(0, min(100, 2 * (rssi_dbm + 100)))
    if rssi_dbm is None and quality_pct is not None:
        rssi_dbm = max(-120, min(0, (quality_pct // 2) - 100))

    return quality_pct, rssi_dbm


def _restart_count_from(*payloads: dict | None) -> int | None:
    """Boot/restart count from StatusSTS / StatusRST only (avoid false positives)."""
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for block_key in ("StatusSTS", "StatusRST"):
            block = payload.get(block_key)
            if not isinstance(block, dict):
                continue
            for key in ("RestartCount", "Restarts", "BootCount"):
                n = _as_int(block.get(key))
                if n is not None and 0 <= n < 50_000:
                    return n
    return None


def _status_sts(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}
    sts = payload.get("StatusSTS")
    return sts if isinstance(sts, dict) else {}


def _loadavg_from_payload(payload: dict | None) -> int | None:
    """LoadAvg from Status 11 StatusSTS — loop busy %, not CPU % (can exceed 100)."""
    return _as_int(_status_sts(payload).get("LoadAvg"))


def _example_mqtt_topics(full_topic: str, topic: str) -> tuple[str, str]:
    """Derive example tele/stat publish paths from Tasmota FullTopic template."""
    t = (topic or "tasmota").strip() or "tasmota"
    ft = (full_topic or "%prefix%/%topic%/").strip()
    tele = ft.replace("%prefix%", "tele").replace("%topic%", t)
    stat = ft.replace("%prefix%", "stat").replace("%topic%", t)
    if not tele.endswith("/"):
        tele += "/"
    if not stat.endswith("/"):
        stat += "/"
    return f"{tele}SENSOR", f"{stat}POWER"


def _probe_http(
    ip: str,
    *,
    path: str = "",
    cmnd: str | None = None,
    timeout: float = 5.0,
) -> tuple[bool, str, float, dict | None]:
    """GET /cm?cmnd=… or / — returns (ok, detail, ms, json_or_none)."""
    import time
    from urllib.parse import quote

    import requests

    if cmnd is not None:
        url = f"http://{ip}/cm?cmnd={quote(str(cmnd))}"
    else:
        url = f"http://{ip}/{path.lstrip('/')}"
    t0 = time.monotonic()
    try:
        resp = requests.get(url, timeout=timeout)
        ms = (time.monotonic() - t0) * 1000.0
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}", ms, None
        if cmnd is None:
            return True, f"HTTP {resp.status_code}", ms, None
        try:
            return True, "OK", ms, resp.json()
        except ValueError:
            return False, "non-JSON body", ms, None
    except requests.exceptions.Timeout:
        ms = (time.monotonic() - t0) * 1000.0
        return False, f"timeout ({timeout:.0f}s)", ms, None
    except requests.exceptions.ConnectionError:
        ms = (time.monotonic() - t0) * 1000.0
        return False, "connection refused / host unreachable", ms, None
    except requests.RequestException as exc:
        ms = (time.monotonic() - t0) * 1000.0
        return False, str(exc).strip() or "request failed", ms, None


def _has_energy_block(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    sns = payload.get("StatusSNS") or {}
    if isinstance(sns, dict) and sns.get("ENERGY"):
        return True
    return bool(_dig(payload, "StatusSNS", "ENERGY"))


def _build_findings(
    health: TasmotaDeviceHealth,
    *,
    cached: dict | None,
    app_uses_mqtt: bool,
) -> list[str]:
    findings: list[str] = []
    checks = {c.label: c for c in health.probe_checks}

    if not health.reachable:
        root = checks.get("Web root /")
        if root and not root.ok:
            findings.append(
                f"<b>Offline or wrong IP</b> — {root.detail}. "
                "Check device power, VLAN, and that this address is a Tasmota HTTP API."
            )
        else:
            findings.append(
                "<b>No Tasmota HTTP response</b> — nothing answered on Status 0/8/11. "
                "Device may be powered off, on a different IP, or not running Tasmota."
            )
        if app_uses_mqtt:
            findings.append(
                "This tab is in <b>MQTT subscribe</b> mode — rows only fill when tele/ "
                "messages arrive. Offline devices stay blank even if other IPs work."
            )
        if cached:
            findings.append(
                "<b>Stale dashboard row</b> — cached readings exist but live HTTP failed now."
            )
        return findings

    s8 = checks.get("Status 8 (energy meter)")
    s0 = checks.get("Status 0 (identity)")
    pwr = checks.get("Power (relay)")
    poll = checks.get("Dashboard poll (Status 8 + Power)")

    if s0 and s0.ok and not health.firmware:
        findings.append(
            "<b>Firmware unknown</b> — Status 0 responded but Version was missing "
            "(unusual template or very old build)."
        )

    if s8 and s8.ok and not health.status8_has_energy:
        findings.append(
            "<b>No power meter</b> — Status 8 has no ENERGY block. "
            "Relay-only device or wrong module (PZEM / Shelly PM template not enabled). "
            "The table needs ENERGY for W, V, A, and kWh."
        )
    elif s8 and not s8.ok:
        findings.append(
            f"<b>Energy read failed</b> — Status 8: {s8.detail}. "
            "Dashboard cannot show power columns without this."
        )

    if pwr and not pwr.ok:
        findings.append(
            f"<b>Relay state unknown</b> — Power command failed ({pwr.detail}); "
            "State column stays blank."
        )

    if health.reachable and not health.dashboard_has_row and poll and not poll.ok:
        findings.append(
            "<b>Full poll failed</b> — same check the table uses (Status 8 + ENERGY). "
            "Probe button will behave the same until ENERGY is available."
        )

    if cached:
        pw = float(cached.get("power_W") or 0)
        cur = float(cached.get("current_A") or 0)
        if cur > 50 and pw < 100:
            findings.append(
                f"<b>Implausible readings</b> — cached {pw:.0f} W with {cur:.1f} A "
                "(likely bad calibration, wrong driver, or corrupt tele snapshot)."
            )
        if cached.get("relay_on") is None:
            findings.append(
                "<b>State column empty</b> — relay on/off was never read (Power command failed)."
            )
    elif health.reachable and health.poll_row_ok:
        findings.append(
            "<b>Live poll OK</b> — device answers now; click <b>Probe</b> to refresh the row."
        )

    if app_uses_mqtt and health.reachable and not health.dashboard_has_row:
        findings.append(
            "MQTT mode: HTTP works but the row is empty — no tele/SENSOR for this IP on the "
            f"broker yet (expect <code>{health.mqtt_tele_topic}</code>)."
        )

    if health.mqtt_enabled and health.mqtt_connected is False:
        findings.append(
            "<b>Device MQTT disconnected</b> — it may not publish telemetry until the "
            f"broker at {health.mqtt_host} is reachable from the device."
        )

    if health.ip_reported and health.ip_reported != health.ip:
        findings.append(
            f"<b>IP mismatch</b> — device reports {health.ip_reported} "
            f"but you polled {health.ip}."
        )

    if health.heap_kb is not None and health.heap_kb < 12:
        findings.append(
            f"<b>Low heap</b> — only {health.heap_kb} kB free (Status 4); "
            "device may drop HTTP/MQTT under load."
        )

    if health.mqtt_enabled and health.mqtt_log_level == 0:
        findings.append(
            "<b>MQTT logging off</b> — MqttLog is 0; enable MqttLog 2+ on the device "
            "to see broker/socket errors in tele/RESULT."
        )

    if health.web_log_boosted:
        findings.append(
            "<b>WebLog 4 enabled briefly</b> — verbose HW/socket logging was turned on "
            f"for this diagnose (was {_log_level_label(health.web_log_original)}), "
            "then restored."
        )

    if health.cpu_load_current is not None and health.cpu_load_current > 100:
        sleep_ms = health.sleep_interval_ms
        findings.append(
            f"<b>High LoadAvg</b> — {health.cpu_load_current} "
            "(Tasmota loop busy %; ideal ≤75). "
            f"Sleep interval is {sleep_ms if sleep_ms is not None else '?'} ms — "
            "raise <code>Sleep</code> if the device struggles with WiFi/MQTT."
        )

    if not findings:
        findings.append(
            "No problems found — HTTP, energy meter, and relay checks passed."
        )
    return findings


def _run_probe_suite(ip: str, *, timeout: float) -> list[TasmotaProbeCheck]:
    suite = (
        ("Web root /", None, "/"),
        ("Status 0 (identity)", "Status 0", None),
        ("Status 8 (energy meter)", "Status 8", None),
        ("Power (relay)", "Power", None),
        ("Status 11 (LoadAvg)", "Status 11", None),
        ("Status 3 (logging)", "Status 3", None),
        ("Status 4 (memory)", "Status 4", None),
        ("Status 5 (network)", "Status 5", None),
    )
    checks: list[TasmotaProbeCheck] = []
    for label, cmnd, path in suite:
        if cmnd is not None:
            ok, detail, ms, _payload = _probe_http(ip, cmnd=cmnd, timeout=timeout)
        else:
            ok, detail, ms, _payload = _probe_http(ip, path=path or "", timeout=timeout)
        checks.append(TasmotaProbeCheck(label=label, ok=ok, detail=detail, ms=ms))
    return checks


def _read_idle_scheduler_load(
    ip: str,
    *,
    timeout: float,
    quiet_s: float = 1.5,
) -> dict | None:
    """Status 11 after a pause so diagnose HTTP traffic does not inflate LoadAvg."""
    import time

    time.sleep(quiet_s)
    return tasmota_send_cmnd(ip, "Status 11", timeout=timeout)


def fetch_tasmota_device_health(
    ip: str,
    *,
    timeout: float = 8.0,
    cached_row: dict | None = None,
    app_uses_mqtt: bool = False,
) -> TasmotaDeviceHealth:
    import time

    ip = (ip or "").strip()
    health = TasmotaDeviceHealth(ip=ip)
    t0 = time.monotonic()
    probe_timeout = min(timeout, 5.0)

    health.probe_checks = _run_probe_suite(ip, timeout=probe_timeout)
    health.dashboard_has_row = bool(cached_row)
    health.reachable = any(c.ok for c in health.probe_checks if c.label != "Web root /") or any(
        c.ok for c in health.probe_checks
    )

    poll_row = poll_tasmota_device(ip, timeout=probe_timeout)
    health.poll_row_ok = poll_row is not None
    health.probe_checks.append(
        TasmotaProbeCheck(
            label="Dashboard poll (Status 8 + Power)",
            ok=health.poll_row_ok,
            detail="ENERGY + relay" if health.poll_row_ok else "no ENERGY / unreachable",
            ms=0.0,
        )
    )

    s0 = tasmota_send_cmnd(ip, "Status 0", timeout=timeout) if health.reachable else None
    s3 = tasmota_send_cmnd(ip, "Status 3", timeout=timeout) if health.reachable else None
    s4 = tasmota_send_cmnd(ip, "Status 4", timeout=timeout) if health.reachable else None
    s5 = tasmota_send_cmnd(ip, "Status 5", timeout=timeout) if health.reachable else None
    s6 = tasmota_send_cmnd(ip, "Status 6", timeout=timeout) if health.reachable else None
    s11 = tasmota_send_cmnd(ip, "Status 11", timeout=timeout) if health.reachable else None
    if health.reachable:
        _apply_status_log(health, s3)
        _boost_weblog_for_diagnose(ip, health, timeout=min(timeout, 3.0))
        _apply_status_mem(health, s4)
    s8_payload = tasmota_send_cmnd(ip, "Status 8", timeout=timeout) if health.reachable else None
    health.status8_has_energy = _has_energy_block(s8_payload)
    pwr_payload = tasmota_send_cmnd(ip, "Power", timeout=timeout) if health.reachable else None
    health.power_cmd_ok = isinstance(pwr_payload, dict)

    if not health.reachable:
        health.fetch_ms = (time.monotonic() - t0) * 1000.0
        health.findings = _build_findings(
            health, cached=cached_row, app_uses_mqtt=app_uses_mqtt,
        )
        return health
    name, fw = poll_tasmota_device_meta(ip, timeout=timeout)
    health.device_name = name if name and name != ip else ""
    health.firmware = fw if fw and fw != "—" else ""

    sts = _status_sts(s11) or _status_sts(s0)
    net = _dig(s5, "StatusNET") or _dig(s0, "StatusNET") or {}
    wifi = _dig(net, "Wifi") or _dig(sts, "Wifi") or {}
    mqtt = _dig(s6, "StatusMQT") or {}

    health.hostname = str(net.get("Hostname") or sts.get("Hostname") or "").strip()
    health.ip_reported = str(net.get("IPAddress") or "").strip()
    health.gateway = str(net.get("Gateway") or "").strip()
    health.uptime = str(sts.get("Uptime") or "").strip()
    ws = net.get("Webserver")
    health.webserver = (
        "enabled" if ws in (1, 2, "1", "2") else "off" if ws in (0, "0") else str(ws or "—")
    )

    health.wifi_ssid = str(wifi.get("SSId") or wifi.get("SSID") or "").strip()
    health.wifi_signal_pct, health.wifi_rssi_dbm = _tasmota_wifi_metrics(wifi)
    health.wifi_link_count = _as_int(wifi.get("LinkCount"))
    health.wifi_downtime = str(wifi.get("Downtime") or "").strip()

    health.last_restart_reason = str(sts.get("RestartReason") or "").strip()
    health.restart_count = _restart_count_from(s0, s11)

    health.mqtt_host = str(mqtt.get("MqttHost") or "").strip()
    health.mqtt_port = _as_int(mqtt.get("MqttPort"))
    health.mqtt_user = str(mqtt.get("MqttUser") or "").strip()
    health.mqtt_topic = str(mqtt.get("Topic") or "").strip()
    health.mqtt_full_topic = str(mqtt.get("FullTopic") or "").strip()
    health.mqtt_client = str(mqtt.get("MqttClient") or "").strip()
    health.mqtt_reconnect_count = _as_int(mqtt.get("MqttCount"))
    health.mqtt_enabled = bool(health.mqtt_host)
    if health.mqtt_host:
        mc = health.mqtt_reconnect_count
        health.mqtt_connected = mc is not None and mc > 0
    health.mqtt_tele_topic, health.mqtt_stat_topic = _example_mqtt_topics(
        health.mqtt_full_topic, health.mqtt_topic or ip.replace(".", "_"),
    )

    if health.mqtt_enabled and not health.mqtt_host:
        health.errors.append("MQTT is configured but broker host is empty.")

    if health.reachable:
        _restore_weblog_after_diagnose(ip, health, timeout=min(timeout, 3.0))
        s11_idle = _read_idle_scheduler_load(
            ip, timeout=timeout, quiet_s=1.5,
        )
        sts_idle = _status_sts(s11_idle)
        load = _loadavg_from_payload(s11_idle)
        health.cpu_metric = "LoadAvg"
        health.sleep_interval_ms = _as_int(sts_idle.get("Sleep"))
        health.sleep_mode = str(sts_idle.get("SleepMode") or "").strip()
        if load is not None:
            health.cpu_load_current = load
            health.cpu_load_peak = load
            health.cpu_load_avg = load
            health.cpu_load_samples = [load]
        else:
            health.errors.append(
                "LoadAvg not found in Status 11 — check tele/STATE on this firmware."
            )

    health.findings = _build_findings(
        health, cached=cached_row, app_uses_mqtt=app_uses_mqtt,
    )
    health.fetch_ms = (time.monotonic() - t0) * 1000.0
    return health
