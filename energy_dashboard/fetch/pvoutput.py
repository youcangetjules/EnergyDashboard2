"""PVOutput.org Add Status upload (live generation → community site).

API: https://pvoutput.org/help/api_specification.html#add-status-service
Auth headers: X-Pvoutput-Apikey, X-Pvoutput-SystemId
Units: v1 energy Wh (cumulative today), v2 power W, v3/v4 consumption.
Rate limit: 60 requests/hour (donation 300) — we throttle to ≥5 minutes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

_QS_ORG = "PowerModel"
_QS_APP = "EnergyDashboard2"
_ADDSTATUS_URL = "https://pvoutput.org/service/r2/addstatus.jsp"
_GETSYSTEM_URL = "https://pvoutput.org/service/r2/getsystem.jsp"
_LONDON = ZoneInfo("Europe/London")

_QS_ENABLED = "pvoutput/enabled"
_QS_API_KEY = "pvoutput/api_key"
_QS_SYSTEM_ID = "pvoutput/system_id"
_QS_INTERVAL_S = "pvoutput/interval_s"
_QS_LAST_OK_TS = "pvoutput/last_ok_ts"
_QS_LAST_OK_MSG = "pvoutput/last_ok_msg"
_QS_LAST_ERR = "pvoutput/last_error"
_QS_LAST_ATTEMPT_TS = "pvoutput/last_attempt_ts"

DEFAULT_INTERVAL_S = 300  # 5 minutes — matches typical PVOutput status interval
MIN_INTERVAL_S = 300
MAX_INTERVAL_S = 900  # 15 minutes


def pvoutput_settings():
    from energy_dashboard.deps import QSettings
    return QSettings(_QS_ORG, _QS_APP)


@dataclass
class PvoutputConfig:
    enabled: bool = False
    api_key: str = ""
    system_id: str = ""
    interval_s: int = DEFAULT_INTERVAL_S

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.api_key.strip() and self.system_id.strip())


def load_pvoutput_config() -> PvoutputConfig:
    s = pvoutput_settings()
    try:
        interval = int(s.value(_QS_INTERVAL_S, DEFAULT_INTERVAL_S) or DEFAULT_INTERVAL_S)
    except (TypeError, ValueError):
        interval = DEFAULT_INTERVAL_S
    interval = max(MIN_INTERVAL_S, min(MAX_INTERVAL_S, interval))
    return PvoutputConfig(
        enabled=bool(s.value(_QS_ENABLED, False, type=bool)),
        api_key=str(s.value(_QS_API_KEY, "") or "").strip(),
        system_id=str(s.value(_QS_SYSTEM_ID, "") or "").strip(),
        interval_s=interval,
    )


def save_pvoutput_config(
    *,
    enabled: bool,
    api_key: str,
    system_id: str,
    interval_s: int = DEFAULT_INTERVAL_S,
) -> PvoutputConfig:
    s = pvoutput_settings()
    interval = max(MIN_INTERVAL_S, min(MAX_INTERVAL_S, int(interval_s or DEFAULT_INTERVAL_S)))
    s.setValue(_QS_ENABLED, bool(enabled))
    s.setValue(_QS_API_KEY, (api_key or "").strip())
    s.setValue(_QS_SYSTEM_ID, (system_id or "").strip())
    s.setValue(_QS_INTERVAL_S, interval)
    s.sync()
    return load_pvoutput_config()


def load_pvoutput_status() -> dict[str, Any]:
    s = pvoutput_settings()
    return {
        "last_ok_ts": str(s.value(_QS_LAST_OK_TS, "") or ""),
        "last_ok_msg": str(s.value(_QS_LAST_OK_MSG, "") or ""),
        "last_error": str(s.value(_QS_LAST_ERR, "") or ""),
        "last_attempt_ts": str(s.value(_QS_LAST_ATTEMPT_TS, "") or ""),
    }


def _write_status(*, ok: bool, message: str) -> None:
    s = pvoutput_settings()
    now = datetime.now(_LONDON).isoformat(timespec="seconds")
    s.setValue(_QS_LAST_ATTEMPT_TS, now)
    if ok:
        s.setValue(_QS_LAST_OK_TS, now)
        s.setValue(_QS_LAST_OK_MSG, message)
        s.setValue(_QS_LAST_ERR, "")
    else:
        s.setValue(_QS_LAST_ERR, message)
    s.sync()


def seconds_since_last_ok() -> float | None:
    st = load_pvoutput_status()
    raw = st.get("last_ok_ts") or ""
    if not raw:
        return None
    try:
        then = datetime.fromisoformat(raw)
        if then.tzinfo is None:
            then = then.replace(tzinfo=_LONDON)
        return (datetime.now(_LONDON) - then).total_seconds()
    except ValueError:
        return None


def should_upload_now(cfg: PvoutputConfig | None = None) -> bool:
    cfg = cfg or load_pvoutput_config()
    if not cfg.ready:
        return False
    age = seconds_since_last_ok()
    if age is None:
        return True
    return age >= float(cfg.interval_s)


def _kw_to_w(value) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value) * 1000.0))
    except (TypeError, ValueError):
        return None


def _kwh_to_wh(value) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value) * 1000.0))
    except (TypeError, ValueError):
        return None


def build_addstatus_payload(
    *,
    when: datetime | None = None,
    pv_power_kw=None,
    pv_today_kwh=None,
    load_power_kw=None,
    load_today_kwh=None,
) -> dict[str, str]:
    """Build addstatus form fields from Growatt-style kW / kWh readings."""
    now = when or datetime.now(_LONDON)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_LONDON)
    else:
        now = now.astimezone(_LONDON)
    payload: dict[str, str] = {
        "d": now.strftime("%Y%m%d"),
        "t": now.strftime("%H:%M"),
    }
    v1 = _kwh_to_wh(pv_today_kwh)
    v2 = _kw_to_w(pv_power_kw)
    v3 = _kwh_to_wh(load_today_kwh)
    v4 = _kw_to_w(load_power_kw)
    if v1 is not None:
        payload["v1"] = str(max(0, v1))
    if v2 is not None:
        payload["v2"] = str(max(0, v2))
    if v3 is not None:
        payload["v3"] = str(max(0, v3))
    if v4 is not None:
        payload["v4"] = str(max(0, v4))
    return payload


def test_pvoutput_connection(
    *,
    api_key: str | None = None,
    system_id: str | None = None,
    timeout: float = 15.0,
) -> tuple[bool, str]:
    """Lightweight credential check via getsystem.jsp (does not upload status)."""
    cfg = load_pvoutput_config()
    key = (api_key if api_key is not None else cfg.api_key).strip()
    sid = (system_id if system_id is not None else cfg.system_id).strip()
    if not key or not sid:
        return False, "Set API key + System Id under Setup & Info → PVOutput"
    headers = {
        "X-Pvoutput-Apikey": key,
        "X-Pvoutput-SystemId": sid,
    }
    try:
        resp = requests.get(_GETSYSTEM_URL, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        return False, f"PVOutput not reachable ({exc})"
    body = (resp.text or "").strip()
    if resp.status_code == 200 and body and not body.upper().startswith("UNAUTHORIZED"):
        # CSV: name,size,panel,inverter,... — first field is system name.
        name = body.split(",")[0].strip() if "," in body else body[:80]
        return True, f"Connected — system {sid}" + (f" ({name})" if name else "")
    detail = body[:200] if body else f"HTTP {resp.status_code}"
    return False, f"Auth/system check failed: {detail}"


def addstatus(
    payload: dict[str, str],
    *,
    api_key: str | None = None,
    system_id: str | None = None,
    timeout: float = 20.0,
) -> tuple[bool, str]:
    """POST live status to PVOutput. Returns (ok, message)."""
    cfg = load_pvoutput_config()
    key = (api_key if api_key is not None else cfg.api_key).strip()
    sid = (system_id if system_id is not None else cfg.system_id).strip()
    if not key or not sid:
        msg = "PVOutput API key or System Id missing"
        _write_status(ok=False, message=msg)
        return False, msg
    if not any(k in payload for k in ("v1", "v2", "v3", "v4")):
        msg = "Nothing to upload (need PV energy/power or consumption)"
        _write_status(ok=False, message=msg)
        return False, msg
    headers = {
        "X-Pvoutput-Apikey": key,
        "X-Pvoutput-SystemId": sid,
        "X-Rate-Limit": "1",
    }
    try:
        resp = requests.post(
            _ADDSTATUS_URL,
            data=payload,
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        msg = f"Network error: {exc}"
        _write_status(ok=False, message=msg)
        return False, msg
    body = (resp.text or "").strip()
    remaining = resp.headers.get("X-Rate-Limit-Remaining", "")
    if resp.status_code == 200 and body.upper().startswith("OK"):
        msg = body
        if remaining != "":
            msg = f"{body} (rate remaining {remaining})"
        _write_status(ok=True, message=msg)
        return True, msg
    # PVOutput returns plain text errors with non-200 or "Unauthorized" etc.
    detail = body[:240] if body else f"HTTP {resp.status_code}"
    msg = f"Upload failed: {detail}"
    _write_status(ok=False, message=msg)
    return False, msg


def upload_from_growatt(
    mix_status: dict | None,
    mix_totals: dict | None = None,
    *,
    force: bool = False,
) -> tuple[bool, str]:
    """Upload current Growatt live snapshot if enabled and due."""
    cfg = load_pvoutput_config()
    if not cfg.ready:
        return False, "PVOutput upload disabled or not configured"
    if not force and not should_upload_now(cfg):
        age = seconds_since_last_ok()
        left = cfg.interval_s - int(age or 0)
        return False, f"Skipped — next upload in ~{max(0, left)}s"
    status = mix_status or {}
    totals = mix_totals or {}
    payload = build_addstatus_payload(
        pv_power_kw=status.get("ppv"),
        pv_today_kwh=totals.get("epvToday"),
        load_power_kw=status.get("pLocalLoad"),
        load_today_kwh=totals.get("elocalLoadToday"),
    )
    return addstatus(payload, api_key=cfg.api_key, system_id=cfg.system_id)


def connectivity_row() -> tuple[str, str, str, str, str]:
    """Return (state_text, state_key, detail, freshness, size) for Connectivity."""
    cfg = load_pvoutput_config()
    st = load_pvoutput_status()
    fresh = "--"
    if st.get("last_ok_ts"):
        try:
            then = datetime.fromisoformat(st["last_ok_ts"])
            if then.tzinfo is None:
                then = then.replace(tzinfo=_LONDON)
            age_s = (datetime.now(_LONDON) - then).total_seconds()
            if age_s < 90:
                fresh = f"{int(age_s)}s ago"
            elif age_s < 3600:
                fresh = f"{int(age_s / 60)}m ago"
            else:
                fresh = then.strftime("%H:%M")
        except ValueError:
            fresh = st["last_ok_ts"][:16]
    if not cfg.enabled:
        return "Disabled", "off", "Enable under Setup & Info → PVOutput", fresh, "--"
    if not cfg.api_key or not cfg.system_id:
        return (
            "Not configured",
            "off",
            "Set API key + System Id (pvoutput.org → Settings → API)",
            fresh,
            "--",
        )
    if st.get("last_error") and not st.get("last_ok_ts"):
        return "Failed", "bad", st["last_error"][:200], fresh, "--"
    if st.get("last_error") and st.get("last_ok_ts"):
        # Had success before, last attempt may have failed
        age = seconds_since_last_ok()
        if age is not None and age > cfg.interval_s * 3:
            return "Stale", "warn", st["last_error"][:200], fresh, "--"
    if st.get("last_ok_ts"):
        detail = st.get("last_ok_msg") or f"System {cfg.system_id}"
        return "Uploading", "ok", detail[:200], fresh, "--"
    return (
        "Ready",
        "idle",
        f"System {cfg.system_id} · every {cfg.interval_s // 60} min",
        fresh,
        "--",
    )


__all__ = [
    "PvoutputConfig",
    "DEFAULT_INTERVAL_S",
    "MIN_INTERVAL_S",
    "MAX_INTERVAL_S",
    "load_pvoutput_config",
    "save_pvoutput_config",
    "load_pvoutput_status",
    "should_upload_now",
    "build_addstatus_payload",
    "addstatus",
    "upload_from_growatt",
    "connectivity_row",
    "test_pvoutput_connection",
]
