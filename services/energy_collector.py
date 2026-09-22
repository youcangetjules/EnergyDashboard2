#!/usr/bin/env python3
"""
Background energy collector: polls Tasmota device(s) and Growatt cloud,
writes readings to PostgreSQL (same schema as EnergyDashboard DataLogger),
and exposes GET /snapshot for the GUI.

Run via systemd — see energy-collector.service and install-energy-collector.sh.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import growattServer
import requests

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from energy_dashboard.db.mix_chart import (  # noqa: E402
    fetch_mix_chart_for_date,
    upsert_mix_chart_rows,
)
from energy_dashboard.db.logger import _sanitize_power_kw  # noqa: E402
from energy_dashboard.ui.cards import (  # noqa: E402
    _growatt_fetch_mix_live,
    _growatt_open_api_v1_session,
    _growatt_v1_plant_devices,
)

# --- PostgreSQL DML (tables are created by the hand-run CREATE script) ---
_GROWATT_INSERT_PG = """
INSERT INTO growatt_readings
    (timestamp, soc_pct, battery_power_kw, pv_power_kw, grid_power_kw,
     load_power_kw, charge_today_kwh, discharge_today_kwh, pv_today_kwh)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""

_TASMOTA_INSERT_PG = """
INSERT INTO tasmota_readings
    (timestamp, device_ip, device_name, power_w, voltage_v, current_a,
     today_kwh, total_kwh)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""

_TASMOTA_DEVICE_UPSERT_PG = """
INSERT INTO tasmota_devices (device_ip, device_name, relay_on, first_seen, last_seen)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (device_ip) DO UPDATE SET
    device_name = EXCLUDED.device_name,
    relay_on = EXCLUDED.relay_on,
    last_seen = EXCLUDED.last_seen
"""


def _relay_to_db_int(relay_on):
    if relay_on is True:
        return 1
    if relay_on is False:
        return 0
    return None


def _to_float(v):
    if v is None or v == "--":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ip_range(start: str, end: str) -> list[str]:
    prefix = start.rsplit(".", 1)[0]
    s = int(start.rsplit(".", 1)[1])
    e = int(end.rsplit(".", 1)[1])
    return [f"{prefix}.{i}" for i in range(s, e + 1)]


def resolve_tasmota_ips(tasmota_ips: str, ip_start: str, ip_end: str) -> list[str]:
    if tasmota_ips.strip():
        return [ip.strip() for ip in tasmota_ips.split(",") if ip.strip()]
    return ip_range(ip_start, ip_end)


def poll_tasmota_device(ip: str, timeout: float = 3.0):
    url = f"http://{ip}/cm?cmnd=Status%208"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException:
        return None
    sns = data.get("StatusSNS", {})
    energy = sns.get("ENERGY", {})
    if not energy:
        return None
    relay_on = None
    try:
        r2 = requests.get(f"http://{ip}/cm?cmnd=Power", timeout=timeout)
        r2.raise_for_status()
        j2 = r2.json()
        pwr = j2.get("POWER")
        if isinstance(pwr, str):
            relay_on = pwr.strip().upper() in ("ON", "TRUE", "1")
        elif isinstance(pwr, bool):
            relay_on = pwr
        elif isinstance(pwr, (int, float)):
            relay_on = pwr != 0
    except requests.exceptions.RequestException:
        pass
    return {
        "ip": ip,
        "power_W": energy.get("Power", 0),
        "voltage_V": energy.get("Voltage", 0),
        "current_A": energy.get("Current", 0),
        "factor": energy.get("Factor", 0),
        "today_kWh": energy.get("Today", 0),
        "yesterday_kWh": energy.get("Yesterday", 0),
        "total_kWh": energy.get("Total", 0),
        "relay_on": relay_on,
    }


def poll_tasmota_device_name(ip: str, timeout: float = 3.0) -> str:
    url = f"http://{ip}/cm?cmnd=Status%200"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException:
        return ip
    status = data.get("Status", {})
    name = status.get("DeviceName", "") or status.get("FriendlyName", [""])[0]
    return name if name else ip


def poll_tasmota_once(
    ips: list[str],
    max_workers: int,
    timeout: float,
) -> tuple[dict[str, dict], dict[str, str]]:
    results: dict[str, dict] = {}
    names: dict[str, str] = {}

    def poll_one(ip: str):
        data = poll_tasmota_device(ip, timeout=timeout)
        if data:
            nm = poll_tasmota_device_name(ip, timeout=timeout)
            return ip, data, nm
        return ip, None, ""

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(poll_one, ip): ip for ip in ips}
        for fut in as_completed(futures):
            ip, data, nm = fut.result()
            if data:
                results[ip] = data
                if nm:
                    names[ip] = nm
    return results, names


def _write_tasmota_pg(cur, records: list[dict]) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    dev_rows = []
    for r in records:
        rows.append(
            (
                ts,
                r.get("ip"),
                r.get("name"),
                _to_float(r.get("power_W")),
                _to_float(r.get("voltage_V")),
                _to_float(r.get("current_A")),
                _to_float(r.get("today_kWh")),
                _to_float(r.get("total_kWh")),
            )
        )
        ip = r.get("ip")
        if ip:
            dev_rows.append(
                (
                    ip,
                    (r.get("name") or "") or "",
                    _relay_to_db_int(r.get("relay_on")),
                    ts,
                    ts,
                )
            )
    if not rows:
        return
    cur.executemany(_TASMOTA_INSERT_PG, rows)
    if dev_rows:
        cur.executemany(_TASMOTA_DEVICE_UPSERT_PG, dev_rows)


def _write_growatt_pg(cur, data: dict) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    row = (
        ts,
        _to_float(data.get("soc")),
        _sanitize_power_kw(_to_float(data.get("bat_power"))),
        _sanitize_power_kw(_to_float(data.get("pv_power"))),
        _sanitize_power_kw(_to_float(data.get("grid_power"))),
        _sanitize_power_kw(_to_float(data.get("load_power"))),
        _to_float(data.get("charge_today")),
        _to_float(data.get("discharge_today")),
        _to_float(data.get("pv_today")),
    )
    cur.execute(_GROWATT_INSERT_PG, row)


class GrowattSession:
    """Reusable Growatt cloud session (password or Open API token)."""

    def __init__(self, user: str, password: str, server: str, token: str = ""):
        self.user = user
        self.password = password
        self.server = server.rstrip("/") + "/"
        self.token = (token or "").strip()
        self.api = None
        self.plant_id = None
        self.device_sn = None
        self.device_type = None
        self.last_error = None

    def connect(self) -> bool:
        if self.token:
            try:
                self.api, self.plant_id, _plant_name = _growatt_open_api_v1_session(self.token)
            except Exception as e:
                self.last_error = str(e)
                return False
            devices = _growatt_v1_plant_devices(self.api, self.plant_id)
            device = None
            for d in devices:
                if str(d.get("deviceType", "")).lower() == "mix":
                    device = d
                    break
            if device is None and devices:
                device = devices[0]
            if device is None:
                self.last_error = "No devices found for token"
                return False
            self.device_sn = device.get("deviceSn") or device.get("device_sn")
            self.device_type = device.get("deviceType") or "mix"
            self.last_error = None
            return bool(self.device_sn and self.plant_id)

        self.api = growattServer.GrowattApi(False, self.server)
        login_response = self.api.login(self.user, self.password)
        plants = login_response.get("data", [])
        if not plants:
            self.last_error = "No plants found"
            return False
        self.plant_id = plants[0]["plantId"]
        devices = self.api.device_list(self.plant_id)
        if not devices:
            self.last_error = "No devices found"
            return False
        device = None
        for d in devices:
            if not isinstance(d, dict):
                continue
            if str(d.get("deviceType", "")).lower() == "mix":
                device = d
                break
        if device is None:
            device = devices[0]
        self.device_sn = device.get("deviceSn")
        self.device_type = device.get("deviceType")
        self.last_error = None
        return bool(self.device_sn and self.plant_id)

    def poll(self) -> dict | None:
        if not self.token and (not self.user or not self.password):
            self.last_error = "Growatt credentials not configured"
            return None
        if self.api is None or not self.device_sn:
            if not self.connect():
                return None
        try:
            if str(self.device_type or "").lower() != "mix":
                self.last_error = f"Unsupported device type: {self.device_type}"
                return None
            status, _info, totals = _growatt_fetch_mix_live(
                self.api, self.device_sn, self.plant_id,
            )
            if not isinstance(status, dict):
                self.last_error = "Invalid Growatt live status response"
                return None
            discharge = float(status.get("pdisCharge1", 0) or 0)
            charge = float(status.get("chargePower", 0) or 0)
            grid_import = float(status.get("pactouser", 0) or 0)
            grid_export = float(status.get("pactogrid", 0) or 0)
            return {
                "plant_id": self.plant_id,
                "device_sn": self.device_sn,
                "soc": status.get("SOC"),
                "bat_power": charge - discharge,
                "pv_power": status.get("ppv"),
                "grid_power": grid_export - grid_import,
                "load_power": status.get("pLocalLoad"),
                "charge_today": totals.get("echargetoday") if isinstance(totals, dict) else None,
                "discharge_today": totals.get("edischarge1Today") if isinstance(totals, dict) else None,
                "pv_today": totals.get("epvToday") if isinstance(totals, dict) else None,
                "status": status,
            }
        except Exception as e:
            self.last_error = str(e)
            self.api = None
            self.device_sn = None
            return None

    def poll_chart(self) -> list[dict]:
        if self.api is None or not self.device_sn:
            if not self.connect():
                return []
        records: list[dict] = []
        for day_offset in (0, 1):
            day = date.today() - timedelta(days=day_offset)
            try:
                records.extend(
                    fetch_mix_chart_for_date(self.api, self.device_sn, self.plant_id, day)
                )
            except Exception:
                continue
        return records


class CollectorState:
    def __init__(self):
        self.lock = threading.Lock()
        self.snapshot: dict[str, Any] = {
            "devices": {},
            "growatt": None,
            "updated_at": None,
            "scan_ips": [],
            "online": 0,
            "error": None,
        }
        # PostgreSQL target this process was started with. No password.
        self.database: dict[str, Any] | None = None


def make_handler(state: CollectorState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send_json(self, code: int, obj: dict):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/health":
                with state.lock:
                    err = state.snapshot.get("error")
                    growatt_err = state.snapshot.get("growatt_error")
                    database = state.database
                self._send_json(
                    200,
                    {
                        "ok": err is None,
                        "error": err,
                        "growatt_error": growatt_err,
                        "database": database,
                    },
                )
                return
            if path == "/snapshot":
                with state.lock:
                    snap = dict(state.snapshot)
                self._send_json(200, snap)
                return
            self._send_json(404, {"error": "not found"})

    return Handler


def run_poll_loop(
    args: argparse.Namespace,
    state: CollectorState,
    pg_conn_holder: list,
):
    import psycopg2

    ips = resolve_tasmota_ips(args.tasmota_ips, args.ip_start, args.ip_end)
    growatt = GrowattSession(
        args.growatt_user,
        args.growatt_pass,
        args.growatt_server,
        token=args.growatt_token,
    )
    last_tasmota = 0.0
    last_growatt = 0.0
    last_chart = 0.0

    def ensure_pg():
        if pg_conn_holder[0] is None:
            pg_conn_holder[0] = psycopg2.connect(
                host=args.pg_host,
                port=int(args.pg_port),
                dbname=args.pg_db,
                user=args.pg_user,
                password=args.pg_pass or None,
            )
            pg_conn_holder[0].autocommit = True
        return pg_conn_holder[0]

    while True:
        t0 = time.monotonic()
        err_msg = None
        growatt_err = None
        devices_out: dict[str, dict] = {}
        growatt_out = None
        online = 0

        try:
            now = time.monotonic()
            conn = ensure_pg()
            with state.lock:
                prev = dict(state.snapshot)

            if not args.no_growatt and (now - last_growatt) >= args.growatt_interval:
                g = growatt.poll()
                last_growatt = now
                if g is None:
                    growatt_err = growatt.last_error
                else:
                    growatt_out = {k: v for k, v in g.items() if k != "status"}
                    with conn.cursor() as cur:
                        _write_growatt_pg(cur, g)
            elif prev.get("growatt") is not None:
                growatt_out = prev.get("growatt")
                growatt_err = prev.get("growatt_error")

            if (
                not args.no_growatt
                and (now - last_chart) >= args.growatt_chart_interval
            ):
                if growatt.api is None or not growatt.device_sn:
                    growatt.connect()
                if growatt.device_sn:
                    chart_rows = growatt.poll_chart()
                    last_chart = now
                    if chart_rows:
                        with conn.cursor() as cur:
                            upsert_mix_chart_rows(cur, "pg", growatt.device_sn, chart_rows)

            if (now - last_tasmota) >= args.tasmota_interval:
                results, names = poll_tasmota_once(ips, args.workers, args.timeout)
                last_tasmota = now
                records = []
                for ip, data in results.items():
                    nm = names.get(ip, ip)
                    rec = {
                        "ip": ip,
                        "name": nm,
                        "relay_on": data.get("relay_on"),
                        "power_W": data.get("power_W"),
                        "voltage_V": data.get("voltage_V"),
                        "current_A": data.get("current_A"),
                        "today_kWh": data.get("today_kWh"),
                        "total_kWh": data.get("total_kWh"),
                    }
                    records.append(rec)
                    row = dict(data)
                    row["name"] = nm
                    devices_out[ip] = row
                online = len(results)
                if records:
                    with conn.cursor() as cur:
                        _write_tasmota_pg(cur, records)
            else:
                devices_out = dict(prev.get("devices") or {})
                online = int(prev.get("online") or 0)

            updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            with state.lock:
                state.snapshot = {
                    "devices": devices_out,
                    "growatt": growatt_out,
                    "updated_at": updated,
                    "scan_ips": ips,
                    "online": online,
                    "error": None,
                    "growatt_error": growatt_err,
                }
        except Exception as e:
            err_msg = str(e)
            pg_conn_holder[0] = None
            with state.lock:
                state.snapshot["error"] = err_msg
                state.snapshot["growatt_error"] = growatt_err

        sleep_s = max(0.5, args.loop_interval - (time.monotonic() - t0))
        time.sleep(sleep_s)


def parse_listen(s: str) -> tuple[str, int]:
    if ":" not in s:
        return s, 8765
    host, _, port_s = s.rpartition(":")
    host = host or "127.0.0.1"
    return host.strip("[]"), int(port_s)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Tasmota + Growatt → PostgreSQL collector with /snapshot HTTP API.",
    )
    p.add_argument(
        "--tasmota-ips",
        default=os.environ.get("POWERMON_TASMOTA_IPS", ""),
        help="Comma-separated Tasmota IPs (overrides --ip-start/--ip-end when non-empty).",
    )
    p.add_argument(
        "--ip-start",
        default=os.environ.get("POWERMON_IP_START", "222.20.20.101"),
    )
    p.add_argument(
        "--ip-end",
        default=os.environ.get("POWERMON_IP_END", "222.20.20.116"),
    )
    p.add_argument(
        "--tasmota-interval",
        type=float,
        default=float(os.environ.get("POWERMON_TASMOTA_INTERVAL", "30")),
        help="Minimum seconds between Tasmota scans.",
    )
    p.add_argument(
        "--growatt-interval",
        type=float,
        default=float(os.environ.get("POWERMON_GROWATT_INTERVAL", "60")),
        help="Minimum seconds between Growatt cloud polls.",
    )
    p.add_argument(
        "--loop-interval",
        type=float,
        default=float(os.environ.get("POWERMON_LOOP_INTERVAL", "5")),
        help="Main loop sleep cadence (seconds).",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("POWERMON_WORKERS", "4")),
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("POWERMON_HTTP_TIMEOUT", "3")),
    )
    p.add_argument("--pg-host", default=os.environ.get("POWERMON_PG_HOST", "localhost"))
    p.add_argument("--pg-port", type=int, default=int(os.environ.get("POWERMON_PG_PORT", "5432")))
    p.add_argument("--pg-db", default=os.environ.get("POWERMON_PG_DB", "powermon"))
    p.add_argument("--pg-user", default=os.environ.get("POWERMON_PG_USER", ""))
    p.add_argument("--pg-pass", default=os.environ.get("POWERMON_PG_PASSWORD", ""))
    p.add_argument(
        "--growatt-user",
        default=os.environ.get("POWERMON_GROWATT_USER", ""),
    )
    p.add_argument(
        "--growatt-pass",
        default=os.environ.get("POWERMON_GROWATT_PASSWORD", ""),
    )
    p.add_argument(
        "--growatt-server",
        default=os.environ.get("POWERMON_GROWATT_SERVER", "https://server.growatt.com"),
    )
    p.add_argument(
        "--growatt-chart-interval",
        type=float,
        default=float(os.environ.get("POWERMON_GROWATT_CHART_INTERVAL", "900")),
        help="Minimum seconds between Growatt 5-minute chart upserts (today+yesterday).",
    )
    p.add_argument(
        "--growatt-token",
        default=os.environ.get("POWERMON_GROWATT_TOKEN", ""),
        help="Growatt Open API token (preferred over password when set).",
    )
    p.add_argument(
        "--no-growatt",
        action="store_true",
        default=os.environ.get("POWERMON_NO_GROWATT", "").lower() in ("1", "true", "yes"),
    )
    p.add_argument(
        "--listen",
        default=os.environ.get("POWERMON_LISTEN", "127.0.0.1:8765"),
    )
    p.add_argument(
        "--no-http",
        action="store_true",
        default=os.environ.get("POWERMON_NO_HTTP", "").lower() in ("1", "true", "yes"),
        help="Skip HTTP /snapshot server (PostgreSQL collection only).",
    )
    return p


def main() -> int:
    args = build_arg_parser().parse_args()
    host, port = parse_listen(args.listen)
    ips = resolve_tasmota_ips(args.tasmota_ips, args.ip_start, args.ip_end)

    state = CollectorState()
    state.database = {
        "engine": "postgresql",
        "host": args.pg_host,
        "port": int(args.pg_port),
        "name": args.pg_db,
        "host_from": "POWERMON_PG_HOST",
        "port_from": "POWERMON_PG_PORT",
        "name_from": "POWERMON_PG_DB",
    }
    pg_conn_holder: list = [None]

    poll_thread = threading.Thread(
        target=run_poll_loop,
        args=(args, state, pg_conn_holder),
        daemon=True,
        name="energy-collector",
    )
    poll_thread.start()

    growatt_note = "off" if args.no_growatt else f"every {args.growatt_interval}s"
    base_msg = (
        f"energy_collector: Tasmota {','.join(ips)} every {args.tasmota_interval}s; "
        f"Growatt {growatt_note} → PostgreSQL {args.pg_host}:{args.pg_port}/{args.pg_db}"
    )

    if args.no_http:
        print(f"{base_msg}; HTTP disabled", flush=True)
        try:
            while poll_thread.is_alive():
                time.sleep(3600)
        except KeyboardInterrupt:
            print("energy_collector: shutting down", flush=True)
        return 0

    Handler = make_handler(state)
    try:
        httpd = ThreadingHTTPServer((host, port), Handler)
    except OSError as e:
        if e.errno != 98:  # EADDRINUSE
            raise
        print(
            f"{base_msg}; HTTP disabled — port {host}:{port} in use ({e}). "
            "Collection continues; stop the other listener or set POWERMON_LISTEN.",
            flush=True,
        )
        try:
            while poll_thread.is_alive():
                time.sleep(3600)
        except KeyboardInterrupt:
            print("energy_collector: shutting down", flush=True)
        return 0

    print(
        f"{base_msg}; http://{host}:{port} (/snapshot /health)",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("energy_collector: shutting down", flush=True)
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
