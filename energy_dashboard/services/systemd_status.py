"""
Probe energy-collector systemd unit and HTTP broker health.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

SERVICE_NAME = "energy-collector.service"
DEFAULT_LISTEN = "127.0.0.1:8765"


def _run_systemctl(args: list[str], user: bool = False, timeout: float = 5.0):
    cmd = ["systemctl"]
    if user:
        cmd.append("--user")
    cmd.extend(args)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        return proc.returncode, out, err
    except FileNotFoundError:
        return -1, "", "systemctl not found"
    except subprocess.TimeoutExpired:
        return -1, "", "systemctl timed out"


def _read_listen_from_env_files() -> str | None:
    paths = (
        Path("/etc/default/energy-collector"),
        Path.home() / ".config" / "energy-collector.env",
    )
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if line.startswith("POWERMON_LISTEN="):
                val = line.split("=", 1)[1].strip().strip("'\"")
                if val:
                    return val
    return None


def resolve_broker_base(settings_value: str | None = None) -> str:
    if settings_value:
        val = settings_value.strip().rstrip("/")
        if val:
            return val
    listen = _read_listen_from_env_files() or DEFAULT_LISTEN
    if "://" not in listen:
        listen = f"http://{listen}"
    return listen.rstrip("/")


def _probe_unit(user: bool) -> dict:
    scope = "user" if user else "system"
    info = {
        "scope": scope,
        "installed": False,
        "active_state": "not-installed",
        "enabled_state": "not-installed",
        "active_since": None,
        "main_pid": None,
        "load_state": None,
        "sub_state": None,
        "error": None,
    }
    rc_active, active, err = _run_systemctl(["is-active", SERVICE_NAME], user=user)
    if rc_active == 4 or active == "not-found":
        return info
    info["installed"] = True
    info["active_state"] = active or "unknown"
    if err and rc_active not in (0, 3):
        info["error"] = err

    rc_enabled, enabled, _ = _run_systemctl(["is-enabled", SERVICE_NAME], user=user)
    if rc_enabled == 4:
        info["enabled_state"] = "not-installed"
    else:
        info["enabled_state"] = enabled or "unknown"

    if info["active_state"] == "active":
        rc_show, props, _ = _run_systemctl(
            [
                "show",
                SERVICE_NAME,
                "--property=ActiveEnterTimestamp,MainPID,LoadState,SubState",
            ],
            user=user,
        )
        if rc_show == 0 and props:
            for line in props.splitlines():
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                val = val.strip()
                if key == "ActiveEnterTimestamp":
                    info["active_since"] = val or None
                elif key == "MainPID":
                    try:
                        pid = int(val)
                        info["main_pid"] = pid if pid > 0 else None
                    except ValueError:
                        info["main_pid"] = None
                elif key == "LoadState":
                    info["load_state"] = val or None
                elif key == "SubState":
                    info["sub_state"] = val or None
    return info


def _probe_http(base_url: str) -> dict:
    out = {
        "url": base_url,
        "reachable": False,
        "ok": False,
        "error": None,
        "growatt_error": None,
        "updated_at": None,
        "online_devices": None,
        "http_error": None,
    }
    health_url = urljoin(base_url + "/", "health")
    try:
        r = requests.get(health_url, timeout=3)
        out["reachable"] = True
        if r.status_code != 200:
            out["http_error"] = f"HTTP {r.status_code}"
            return out
        data = r.json()
        out["ok"] = bool(data.get("ok"))
        out["error"] = data.get("error")
        out["growatt_error"] = data.get("growatt_error")
    except requests.RequestException as exc:
        out["http_error"] = str(exc)
        return out
    except (ValueError, json.JSONDecodeError) as exc:
        out["http_error"] = f"invalid JSON: {exc}"
        return out

    snap_url = urljoin(base_url + "/", "snapshot")
    try:
        r = requests.get(snap_url, timeout=5)
        if r.status_code == 200:
            snap = r.json()
            out["updated_at"] = snap.get("updated_at")
            online = snap.get("online")
            if online is not None:
                out["online_devices"] = int(online)
    except (requests.RequestException, ValueError, TypeError):
        pass
    return out


def _pick_primary(system_unit: dict, user_unit: dict) -> dict | None:
    for unit in (system_unit, user_unit):
        if unit.get("active_state") == "active":
            return unit
    for unit in (system_unit, user_unit):
        if unit.get("installed"):
            return unit
    return None


def format_updated_at(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return s


def format_service_summary(status: dict) -> str:
    """Plain-text one-liner for status bar / compact label."""
    primary = status.get("primary")
    http = status.get("http") or {}
    parts = []
    if primary and primary.get("installed"):
        scope = primary.get("scope", "?")
        active = primary.get("active_state", "?")
        parts.append(f"{scope} service {active}")
        pid = primary.get("main_pid")
        if pid:
            parts.append(f"PID {pid}")
        if primary.get("enabled_state"):
            parts.append(f"boot {primary['enabled_state']}")
    elif not (status.get("system_unit", {}).get("installed") or status.get("user_unit", {}).get("installed")):
        parts.append("not installed")
    else:
        parts.append("stopped")

    if http.get("reachable"):
        parts.append("HTTP OK" if http.get("ok") else "HTTP degraded")
    else:
        parts.append("HTTP unreachable")
    return " · ".join(parts)


def collect_collector_service_status(broker_url: str | None = None) -> dict:
    system_unit = _probe_unit(user=False)
    user_unit = _probe_unit(user=True)
    base = resolve_broker_base(broker_url)
    http = _probe_http(base)
    return {
        "service_name": SERVICE_NAME,
        "system_unit": system_unit,
        "user_unit": user_unit,
        "primary": _pick_primary(system_unit, user_unit),
        "http": http,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


def broker_unreachable_hint(broker_url: str, primary: dict | None, http: dict) -> str | None:
    """Actionable note when systemd is up but the configured broker URL fails."""
    if not http or http.get("reachable"):
        return None
    if not primary or primary.get("active_state") != "active":
        return None
    from urllib.parse import urlparse

    host = (urlparse(broker_url).hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        local = _probe_http("http://127.0.0.1:8765")
        if local.get("reachable"):
            return (
                "Collector responds on this PC at http://127.0.0.1:8765 but Broker URL "
                f"points to {host} — update Broker URL unless the collector runs on that host."
            )
    listen = _read_listen_from_env_files()
    if listen:
        listen_host = listen.split(":", 1)[0].strip().lower()
        if listen_host in ("127.0.0.1", "localhost", "::1") and host not in (
            "127.0.0.1",
            "localhost",
            "::1",
        ):
            return (
                f"Collector is configured to listen on {listen} (local only). "
                f"Broker URL {broker_url} will not work from this PC — use "
                "http://127.0.0.1:8765 or change POWERMON_LISTEN in "
                "/etc/default/energy-collector."
            )
    err = (http.get("http_error") or "").lower()
    if "connection refused" in err or "errno 111" in err:
        return (
            "Service is running but nothing is accepting HTTP on that URL — "
            "try Start/Restart, then: journalctl -u energy-collector -n 40 --no-pager"
        )
    return None


def pick_control_scope(status: dict) -> tuple[bool, dict, str]:
    """Return ``(user_scope, unit_dict, label)`` for systemd control commands."""
    system = status.get("system_unit") or {}
    user = status.get("user_unit") or {}
    if system.get("installed"):
        return False, system, "system"
    if user.get("installed"):
        return True, user, "user"
    return False, {}, "none"


def is_boot_enabled(unit: dict) -> bool:
    en = (unit.get("enabled_state") or "").lower()
    return en in ("enabled", "enabled-runtime", "static")


def _run_systemctl_privileged(args: list[str], *, user: bool, timeout: float = 15.0):
    """Run systemctl; use sudo/pkexec for system scope when not root."""
    import os

    if user:
        return _run_systemctl(args, user=True, timeout=timeout)
    if os.geteuid() == 0:
        return _run_systemctl(args, user=False, timeout=timeout)

    for prefix in (["sudo", "-n"], ["pkexec"]):
        cmd = [*prefix, "systemctl", *args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            if proc.returncode == 0:
                return proc.returncode, out, err
            last_err = err or out or f"exit {proc.returncode}"
        except FileNotFoundError:
            last_err = f"{' '.join(prefix)} not found"
        except subprocess.TimeoutExpired:
            last_err = "command timed out"
    return -1, "", last_err or "permission denied (try sudo)"


def control_collector_service(action: str, status: dict) -> tuple[bool, str]:
    """Start/stop/restart/enable/disable the installed collector unit.

    ``action`` is one of ``start``, ``stop``, ``restart``, ``enable``, ``disable``.
    """
    user_scope, unit, label = pick_control_scope(status)
    if not unit.get("installed"):
        return False, "Collector service is not installed."
    action = action.strip().lower()
    if action not in ("start", "stop", "restart", "enable", "disable"):
        return False, f"Unknown action: {action}"

    rc, out, err = _run_systemctl_privileged([action, SERVICE_NAME], user=user_scope)
    if rc == 0:
        verb = {
            "start": "started",
            "stop": "stopped",
            "restart": "restarted",
            "enable": "enabled at boot",
            "disable": "disabled at boot",
        }.get(action, action)
        return True, f"{label} unit {verb}."
    msg = err or out or f"systemctl {action} failed (exit {rc})"
    if not user_scope and rc != 0:
        msg += (
            " — system units need root: "
            f"sudo systemctl {action} energy-collector"
        )
    return False, msg
