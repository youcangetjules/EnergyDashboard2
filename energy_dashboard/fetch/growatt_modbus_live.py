"""Live Growatt snapshot over the Local Modbus check path.

The bus is the inverter's RS485 port. Setup → Local Modbus check chooses how
this PC reaches it: Modbus TCP, RTU framed over TCP, or a USB–RS485 adapter.
Nothing here is published through EMQX.

Register addresses are the SPH input map (Growatt protocol V1.39) this app
already probes for a heartbeat (input 5 and input 1014). Power pairs are
high-word then low-word, scale 0.1 W. Energy pairs are the same layout,
scale 0.1 kWh. Values that did not read are omitted — never filled in.
"""
from __future__ import annotations

from energy_dashboard.config import (
    growatt_modbus_mode_label,
    growatt_modbus_tcp_host,
)


def _u16(regs, index, scale=1.0):
    if regs is None or index < 0 or index >= len(regs):
        return None
    return (int(regs[index]) & 0xFFFF) * float(scale)


def _u32(regs, index, scale=1.0):
    """Unsigned 32-bit pair: register at *index* is the high word."""
    if regs is None or index < 0 or index + 1 >= len(regs):
        return None
    raw = ((int(regs[index]) & 0xFFFF) << 16) | (int(regs[index + 1]) & 0xFFFF)
    return raw * float(scale)


def _kw_from_w(watts):
    if watts is None:
        return None
    return float(watts) / 1000.0


def decode_sph_live(pv_regs, store_regs, lifetime_regs) -> tuple[dict, dict]:
    """Map three input-register blocks into the live-card status and totals.

    ``pv_regs`` starts at input address 1 (count through at least 66).
    ``lifetime_regs`` starts at input address 91 (PV energy total, 2 regs).
    ``store_regs`` starts at input address 1009 (count through at least 55).
    """
    status: dict = {}
    totals: dict = {}

    def put_status(key, val):
        if val is not None:
            status[key] = val

    def put_total(key, val):
        if val is not None:
            totals[key] = val

    # Input 1–2 total PV, 3 Vpv1, 5–6 Ppv1, 7 Vpv2, 9–10 Ppv2. Scale 0.1.
    ppv_w = _u32(pv_regs, 0, 0.1)
    p1_w = _u32(pv_regs, 4, 0.1)
    p2_w = _u32(pv_regs, 8, 0.1)
    if ppv_w is None and (p1_w is not None or p2_w is not None):
        ppv_w = (p1_w or 0.0) + (p2_w or 0.0)
    put_status("ppv", _kw_from_w(ppv_w))
    put_status("pPv1", _kw_from_w(p1_w))
    put_status("pPv2", _kw_from_w(p2_w))
    put_status("vPv1", _u16(pv_regs, 2, 0.1))
    put_status("vPv2", _u16(pv_regs, 6, 0.1))
    # Input 37 grid frequency (0.01 Hz), 38 grid voltage (0.1 V).
    put_status("fAc", _u16(pv_regs, 36, 0.01))
    put_status("vAc1", _u16(pv_regs, 37, 0.1))

    # Per-string DC energy today (input 59 and 63), 0.1 kWh. Sum is today's solar.
    e1 = _u32(pv_regs, 58, 0.1)
    e2 = _u32(pv_regs, 62, 0.1)
    if e1 is not None or e2 is not None:
        put_total("epvToday", (e1 or 0.0) + (e2 or 0.0))
    put_total("epvTotal", _u32(lifetime_regs, 0, 0.1))

    # Storage block at 1009: discharge, charge, Vbat, SOC, then totals.
    put_status("pdisCharge1", _kw_from_w(_u32(store_regs, 0, 0.1)))
    put_status("chargePower", _kw_from_w(_u32(store_regs, 2, 0.1)))
    put_status("vBat", _u16(store_regs, 4, 0.1))
    soc = _u16(store_regs, 5, 1.0)
    if soc is not None:
        put_status("SOC", int(round(soc)))
    # 1021 import total, 1029 export total, 1037 house load — all 0.1 W.
    put_status("pactouser", _kw_from_w(_u32(store_regs, 12, 0.1)))
    put_status("pactogrid", _kw_from_w(_u32(store_regs, 20, 0.1)))
    put_status("pLocalLoad", _kw_from_w(_u32(store_regs, 28, 0.1)))
    status["gridPowerEstimated"] = False
    status["loadPowerEstimated"] = False

    put_total("etouser", _u32(store_regs, 35, 0.1))
    put_total("etoGridToday", _u32(store_regs, 39, 0.1))
    put_total("edischarge1Today", _u32(store_regs, 43, 0.1))
    put_total("echargetoday", _u32(store_regs, 47, 0.1))
    put_total("elocalLoadToday", _u32(store_regs, 51, 0.1))
    return status, totals


def _call(fn, unit, **kw):
    for arg in ("device_id", "slave"):
        try:
            return fn(**{arg: unit, **kw})
        except TypeError:
            continue
    return fn(**kw)


def _read_input(client, unit, address, count):
    rr = _call(client.read_input_registers, unit, address=int(address), count=int(count))
    if hasattr(rr, "isError") and rr.isError():
        es = getattr(rr, "exception_code", None) or getattr(rr, "message", None) or rr
        raise RuntimeError(f"input@{address} ×{count}: {es}")
    regs = list(getattr(rr, "registers", []) or [])
    if len(regs) < count:
        raise RuntimeError(f"input@{address} returned {len(regs)} of {count}")
    return regs


def _open_client(params):
    mode = str(getattr(params, "growatt_modbus_mode", "off") or "off").lower()
    unit = max(1, min(247, int(getattr(params, "growatt_modbus_unit", 1) or 1)))
    label = growatt_modbus_mode_label(mode)
    if mode in ("tcp", "tcp_rtu"):
        from energy_dashboard.modbus.command_sim import _pymodbus_tcp_client

        host = growatt_modbus_tcp_host(params)
        port = int(getattr(params, "growatt_modbus_tcp_port", 502) or 502)
        if not host:
            raise RuntimeError(
                "Local Modbus check has no LAN address. Set it under Setup & Info."
            )
        client = _pymodbus_tcp_client(
            host, port, rtu=(mode == "tcp_rtu"), timeout=3.0, retries=0,
        )
        where = f"{label} {host}:{port} unit {unit}"
        return client, unit, where
    if mode == "serial":
        from pymodbus.client import ModbusSerialClient

        path = str(getattr(params, "growatt_modbus_serial_path", "") or "").strip()
        baud = int(getattr(params, "growatt_modbus_baud", 9600) or 9600)
        if not path:
            raise RuntimeError(
                "Local Modbus check has no serial device. Set it under Setup & Info."
            )
        client = ModbusSerialClient(
            port=path, baudrate=baud, bytesize=8, parity="N", stopbits=1, timeout=3.0,
        )
        where = f"{label} {path} @ {baud} unit {unit}"
        return client, unit, where
    raise RuntimeError(
        "Local Modbus check is disabled. Choose Modbus TCP, RTU over TCP, "
        "or USB–RS485 under Setup & Info."
    )


def read_growatt_modbus_live(params) -> tuple[bool, str, dict, dict]:
    """One connect, three input reads, then close. Returns (ok, detail, status, totals)."""
    mode = str(getattr(params, "growatt_modbus_mode", "off") or "off").lower()
    if mode == "off" or params is None:
        return False, (
            "Local Modbus check is disabled. Choose a mode under Setup & Info "
            "before using Modbus RS485 as the live source."
        ), {}, {}

    from energy_dashboard.modbus.command_sim import _RS485_IO_LOCK, _SuppressPymodbusConsoleNoise
    from energy_dashboard.ui.cards import (
        _GROWATT_MODBUS_TCP_LOCK,
        _GROWATT_MODBUS_TCP_LOCK_TIMEOUT_S,
    )

    if not _RS485_IO_LOCK.acquire(timeout=8.0):
        return False, "RS485 bus is busy (another Modbus probe is running).", {}, {}
    got_tcp = False
    client = None
    try:
        got_tcp = _GROWATT_MODBUS_TCP_LOCK.acquire(
            timeout=_GROWATT_MODBUS_TCP_LOCK_TIMEOUT_S
        )
        if not got_tcp:
            return False, "Modbus is busy (another probe is running).", {}, {}
        with _SuppressPymodbusConsoleNoise():
            client, unit, where = _open_client(params)
            if not client.connect():
                return False, f"Could not open {where}.", {}, {}
            pv = _read_input(client, unit, 1, 66)
            life = _read_input(client, unit, 91, 2)
            store = _read_input(client, unit, 1009, 55)
        status, totals = decode_sph_live(pv, store, life)
        soc = status.get("SOC")
        soc_bit = f" · SOC {soc}%" if soc is not None else ""
        return True, f"Live registers from {where}{soc_bit}.", status, totals
    except Exception as exc:
        return False, str(exc), {}, {}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        if got_tcp:
            try:
                _GROWATT_MODBUS_TCP_LOCK.release()
            except Exception:
                pass
        try:
            _RS485_IO_LOCK.release()
        except Exception:
            pass
