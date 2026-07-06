"""
Grott MQTT source for Growatt live telemetry.

Grott deployments vary in topic and JSON shape.  This module keeps the MQTT
transport small and normalizes common Growatt/Grott field names into the
legacy-style dicts used by the Growatt tab.
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


_BAD = {"", "--", "none", "null", "unknown"}
_DEFAULT_GROTT_TOPIC = "energy/growatt"
_GROTT_TELEMETRY_KEYS = {
    # Standard Grott status fields.
    "pvpowerin", "pvpowerout", "pvgridpower", "pvgridpowerin",
    "pvgridpowerout", "pv1watt", "pv2watt", "pvloadpower",
    "loadpower", "pvgridvoltage", "pvfrequentie", "vbat", "vbatdsp",
    "soc", "batpower", "pcharge1", "pdischarge1",
    # Pre-normalised / OpenAPI-ish names that some MQTT bridges emit.
    "ppv", "ppv1", "ppv2", "ppv1", "ppv2", "pPv1", "pPv2",
    "chargePower", "pdisCharge1", "pactouser", "pactogrid",
    "pLocalLoad", "loadPower", "gridPower", "vAc1", "fAc", "vBat",
    # Daily / cumulative energy fields.
    "pvenergytoday", "pvenergytotal", "epvtoday", "epvtotal",
    "echarge1today", "echargetoday", "edischarge1today",
    "edischargetoday", "elocalloadtoday", "eactoday", "etogridtoday",
    # Device identity/model frames are useful partial telemetry frames too.
    "pvmodel", "invertermodel", "invertertype", "devicetype", "batterytype",
    "batttype", "bmsmodel", "batterymodel",
}


def _first_nonempty(d: dict, keys: tuple[str, ...]):
    if not isinstance(d, dict):
        return ""
    for key in keys:
        if key not in d:
            continue
        val = d.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text.lower() not in _BAD:
            return val
    return ""


def _has_meaningful_telemetry(flat: dict) -> bool:
    """Return True only for payloads that can update live Growatt telemetry.

    MQTT brokers often carry health/config/status JSON on nearby topics.  Before
    this guard, such sparse payloads could be normalised into a fresh snapshot
    with every missing numeric field defaulted to 0, making the dashboard look
    connected but empty.  Require at least one real power/energy/electrical field.
    """
    for key in _GROTT_TELEMETRY_KEYS:
        if _first_nonempty(flat, (key, str(key).lower())) != "":
            return True
    return False


def _has_any(flat: dict, keys: tuple[str, ...]) -> bool:
    return _first_nonempty(flat, keys) != ""


def _set_if_present(target: dict, key: str, value: Any, flat: dict, keys: tuple[str, ...]) -> None:
    if _has_any(flat, keys):
        target[key] = value


def _as_float(val, default=0.0):
    if val is None:
        return default
    try:
        text = str(val).strip()
        if not text or text.lower() in _BAD:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def _maybe_w_to_kw(val):
    """Convert Grott power registers from watts to kW.

    Layout scaling leaves values in watts (see ``_inject_grott_standard``).
    A previous ``abs(n) > 50`` heuristic kept 10–50 W readings unchanged,
    which wrote dawn/dusk PV and standby load into ``growatt_readings`` as
    10–50 kW and blew up the Forecasts measured-history chart.
    """
    return _as_float(val, 0.0) / 1000.0


def _topic_filters(topic: str) -> tuple[str, ...]:
    """MQTT topic filters to subscribe to.

    Grott's default MQTT topic is commonly ``energy/growatt``.  Older dashboard
    builds used ``grott/#`` as their placeholder, so if that default is still in
    settings subscribe to both rather than silently missing the real Grott JSON.
    Multiple filters can be entered separated by commas, semicolons, or spaces.
    """
    raw = (topic or _DEFAULT_GROTT_TOPIC).strip() or _DEFAULT_GROTT_TOPIC
    parts = []
    for chunk in raw.replace(";", ",").replace(" ", ",").split(","):
        chunk = chunk.strip()
        if chunk and chunk not in parts:
            parts.append(chunk)
    if not parts:
        parts = [_DEFAULT_GROTT_TOPIC]
    if parts == ["grott/#"]:
        parts.append(_DEFAULT_GROTT_TOPIC)
    return tuple(parts)


def _grott_topic_matches(topic: str, filters: tuple[str, ...]) -> bool:
    """Return True when *topic* matches any Grott MQTT filter we subscribed to."""
    topic = (topic or "").strip()
    if not topic:
        return False
    for filt in filters:
        filt = (filt or "").strip()
        if not filt:
            continue
        if filt == topic:
            return True
        if filt.endswith("/#"):
            prefix = filt[:-2]
            if topic == prefix or topic.startswith(prefix + "/"):
                return True
    return False


def _kw_from_watts(val):
    """Convert an explicit watts field to kW."""
    return _as_float(val, 0.0) / 1000.0


def _flatten_json(data: Any, *, prefix: str = "", out: dict | None = None) -> dict:
    out = out if out is not None else {}
    if isinstance(data, dict):
        for key, val in data.items():
            k = str(key)
            out[k] = val
            low = k.lower()
            out.setdefault(low, val)
            if prefix:
                out.setdefault(f"{prefix}_{k}", val)
                out.setdefault(f"{prefix}_{low}", val)
            if isinstance(val, dict):
                _flatten_json(val, prefix=low, out=out)
    return out


def _inject_grott_standard(flat: dict) -> None:
    """Map standard grott layout field names onto the canonical names below.

    Grott's default layout emits *raw, unscaled* integers in its MQTT JSON
    (e.g. ``pvpowerin: 51300`` = 5130 W, ``pvfrequentie: 5019`` = 50.19 Hz,
    ``pvenergytotal: 193991`` = 19399.1 kWh).  The rest of the normalizer was
    written for pre-scaled camelCase names (ppv, vAc1, fAc, epvToday...), so we
    apply grott's divisors here and expose the results under those canonical
    keys.  Values are only added with ``setdefault`` so an explicit camelCase
    field already in the payload always wins; if no grott-standard fields are
    present this is a no-op.
    """
    if not any(
        key in flat
        for key in (
            "pvpowerin",
            "pvpowerout",
            "pvgridpower",
            "pv1watt",
            "pvloadpower",
            "loadpower",
            "pvgridvoltage",
            "pvfrequentie",
            "soc",
            "vbat",
            "batpower",
            "pcharge1",
            "pdischarge1",
            "pvenergytoday",
            "pvenergytotal",
            "epvtoday",
            "epvtotal",
            "echarge1today",
            "echargetoday",
            "edischarge1today",
            "edischargetoday",
            "elocalloadtoday",
            "eactoday",
            "etogridtoday",
        )
    ):
        return  # not a standard-grott payload — leave existing logic untouched

    def num(key: str, div: float):
        v = _as_float(flat.get(key), None)
        return None if v is None else v / div

    # Power -> watts (downstream _maybe_w_to_kw converts W to kW).
    ppv = num("pvpowerin", 10)
    p1 = num("pv1watt", 10)
    p2 = num("pv2watt", 10)
    if ppv is None and (p1 or p2):
        ppv = (p1 or 0.0) + (p2 or 0.0)
    for key, val in (("ppv", ppv), ("pPv1", p1), ("pPv2", p2)):
        if val is not None:
            flat.setdefault(key, val)

    # AC output / grid / load powers in standard Grott layouts.
    # ``pvpowerout`` is inverter AC output, not whole-house local load. Keep it
    # under its own name so missing local load can be estimated from PV + battery
    # + grid below instead of under-reading whenever the battery is discharging.
    # ``pvgridpower`` is grid-side instantaneous power; Grott layouts/signs vary,
    # so expose it under a neutral name and let the normalizer below pick it up.
    for canon, key, div in (
        ("inverterOutputPower", "pvpowerout", 10),
        ("pLocalLoad", "pvloadpower", 10),
        ("pLocalLoad", "loadpower", 10),
        ("gridPower", "pvgridpower", 10),
        ("pactouser", "pvgridpowerin", 10),
        ("pactogrid", "pvgridpowerout", 10),
    ):
        val = num(key, div)
        if val is not None:
            flat.setdefault(canon, val)

    # Voltage / frequency in physical units (no further scaling downstream).
    for canon, key, div in (
        ("vPv1", "pv1voltage", 10),
        ("vPv2", "pv2voltage", 10),
        ("vAc1", "pvgridvoltage", 10),
        ("fAc", "pvfrequentie", 100),
    ):
        val = num(key, div)
        if val is not None:
            flat.setdefault(canon, val)

    # Battery (hybrid inverters): grott emits raw values; scale to canonical.
    vbat = num("vbat", 10)
    if vbat is not None:
        flat.setdefault("vBat", vbat)
    vbat_dsp = num("vbatdsp", 10)
    if vbat_dsp is not None:
        flat.setdefault("vBatDsp", vbat_dsp)
    pchg = num("pcharge1", 10)  # -> watts; downstream _maybe_w_to_kw makes kW
    if pchg is not None:
        flat.setdefault("chargePower", pchg)
    pdis = num("pdischarge1", 10)
    if pdis is not None:
        flat.setdefault("pdisCharge1", pdis)
    for canon, key in (
        ("wBatteryType", "batterytype"),
        ("wBatteryType", "batttype"),
        ("batteryType", "batterytype"),
        ("batteryType", "batttype"),
        ("status", "pvstatus"),
        ("lost", "pvstatus"),
        ("pmax", "pvpowermax"),
        ("pmax", "pmax"),
    ):
        if key in flat:
            flat.setdefault(canon, flat.get(key))
    # SOC is already 0-100; the normalizer reads "soc" directly, expose SOC too.
    if "soc" in flat:
        flat.setdefault("SOC", flat.get("soc"))

    # 0x36 status record: a single *signed* battery power (raw unsigned from grott
    # since the layout can't express signed). Decode 32-bit two's complement,
    # then split: negative = discharging, positive = charging.
    bp = _as_float(flat.get("batpower"), None)
    if bp is not None:
        bp = int(bp)
        if bp >= 2 ** 31:
            bp -= 2 ** 32
        bp_w = bp / 10.0  # watts
        if bp_w < 0:
            flat.setdefault("pdisCharge1", -bp_w)
        elif bp_w > 0:
            flat.setdefault("chargePower", bp_w)

    # Energy counters in kWh.
    for canon, key, div in (
        ("epvToday", "pvenergytoday", 10),
        ("epvTotal", "pvenergytotal", 10),
        ("epvToday", "epvtoday", 10),
        ("epvTotal", "epvtotal", 10),
        ("echargetoday", "echarge1today", 10),
        ("echargetoday", "echargetoday", 10),
        ("edischarge1Today", "edischarge1today", 10),
        ("edischarge1Today", "edischargetoday", 10),
        ("elocalLoadToday", "elocalloadtoday", 10),
        ("elocalLoadToday", "eactoday", 10),
        ("etoGridToday", "etogridtoday", 10),
        ("etoGridToday", "eto_grid_today", 1),
    ):
        val = num(key, div)
        if val is not None:
            flat.setdefault(canon, val)


def _normalize_grott_payload(payload: dict, *, topic: str = "") -> dict | None:
    flat = _flatten_json(payload)
    if not flat:
        return None
    _inject_grott_standard(flat)
    if not _has_meaningful_telemetry(flat):
        return None

    serial = _first_nonempty(
        flat,
        (
            "device", "device_sn", "devicesn", "deviceSn", "serial", "serialNum",
            "inverterserial", "pvserial", "pvSerial", "datalogserial",
            "dataloggerserial", "datalogSerial", "dataloggerSerial",
        ),
    )
    plant = _first_nonempty(
        flat,
        ("plant", "plantname", "plantName", "plant_name", "pvplant", "plantid"),
    )

    soc_keys = ("SOC", "soc", "battery_soc", "batterySOC", "bmsSOC", "bdc1Soc", "batsoc")
    pv_keys = ("ppv", "pvpower", "pv_power", "pvw", "pv_w", "pPv", "pv", "pvpowerin")
    pv1_power_keys = ("pPv1", "ppv1", "pv1power", "pv1_w", "pv1watt")
    pv2_power_keys = ("pPv2", "ppv2", "pv2power", "pv2_w", "pv2watt")
    charge_keys = (
        "chargePower", "pcharge1", "pCharge1", "battery_charge",
        "bat_charge", "batteryChargePower",
    )
    discharge_keys = (
        "pdisCharge1", "pdischarge1", "pDisCharge1", "dischargePower",
        "battery_discharge", "bat_discharge", "batteryDischargePower",
    )
    import_keys = (
        "pactouser", "pacToUser", "pacToUserR", "grid_import",
        "importPower", "gridImportPower", "pvgridpowerin",
    )
    export_keys = (
        "pactogrid", "pacToGrid", "pacToGridTotal", "grid_export",
        "exportPower", "gridExportPower", "pvgridpowerout",
    )
    signed_grid_keys = ("gridPower", "pvgridpower", "grid_power")
    load_keys = (
        "pLocalLoad", "plocalLoad", "loadPower", "load_power",
        "houseLoad", "sysOut", "pvloadpower", "loadpower",
    )

    pv_kw = _maybe_w_to_kw(
        _first_nonempty(flat, pv_keys)
    )
    if not _has_any(flat, pv_keys) and (_has_any(flat, pv1_power_keys) or _has_any(flat, pv2_power_keys)):
        pv_kw = (
            _maybe_w_to_kw(_first_nonempty(flat, pv1_power_keys))
            + _maybe_w_to_kw(_first_nonempty(flat, pv2_power_keys))
        )

    charge_kw = _maybe_w_to_kw(
        _first_nonempty(flat, charge_keys)
    )
    discharge_kw = _maybe_w_to_kw(
        _first_nonempty(flat, discharge_keys)
    )
    import_kw = _maybe_w_to_kw(
        _first_nonempty(flat, import_keys)
    )
    export_kw = _maybe_w_to_kw(
        _first_nonempty(flat, export_keys)
    )
    # Some standard Grott layouts provide only a signed grid power field.  Treat
    # positive as import and negative as export; explicit import/export fields
    # above still win when present.
    explicit_grid_split = _has_any(flat, import_keys) or _has_any(flat, export_keys)
    if not explicit_grid_split and _has_any(flat, signed_grid_keys):
        signed_grid_kw = _maybe_w_to_kw(
            _first_nonempty(flat, signed_grid_keys)
        )
        if signed_grid_kw >= 0:
            import_kw = signed_grid_kw
        else:
            export_kw = abs(signed_grid_kw)
    grid_data_present = (
        _has_any(flat, import_keys) or _has_any(flat, export_keys) or _has_any(flat, signed_grid_keys)
    )
    # Some MIX layouts publish pvgridpower (or similar) stuck at 0 even while
    # battery charge / load clearly need grid import. Treat an all-zero signed
    # field as "not really reporting" unless explicit import/export keys exist,
    # so `_backfill_estimated_grid` can still run on the merged snapshot.
    if (grid_data_present and not explicit_grid_split
            and _has_any(flat, signed_grid_keys) and not _has_any(flat, import_keys)
            and not _has_any(flat, export_keys)):
        try:
            if abs(float(_first_nonempty(flat, signed_grid_keys) or 0)) < 1e-6:
                grid_data_present = False
        except (TypeError, ValueError):
            pass
    load_data_present = _has_any(flat, load_keys)
    load_kw = _maybe_w_to_kw(
        _first_nonempty(flat, load_keys)
    )
    # Only back-solve load from the balance when *this* payload actually has
    # grid data plus PV and/or battery — i.e. it looks like a genuine
    # full-status frame that simply omits a load register. Grott layouts
    # that split telemetry across several cyclical messages (PV in one,
    # battery in another, ...) would otherwise have each partial message
    # silently default its missing legs to zero and fabricate a bogus load
    # figure (e.g. a PV-only frame "computing" load == PV).
    load_can_estimate = not load_data_present and grid_data_present and (
        _has_any(flat, pv_keys) or _has_any(flat, pv1_power_keys) or _has_any(flat, pv2_power_keys)
        or _has_any(flat, charge_keys) or _has_any(flat, discharge_keys)
    )
    if load_can_estimate:
        load_kw = max(0.0, import_kw - export_kw + pv_kw + discharge_kw - charge_kw)
    # Many Grott layouts publish pvpowerout (inverter AC output) but omit pvloadpower /
    # grid registers entirely.  Use AC output as an approximate house load so merge
    # can back-solve grid from PV + battery instead of leaving both as "--".
    load_from_inverter_out = (
        not load_data_present
        and not load_can_estimate
        and _as_float(flat.get("inverterOutputPower"), None) is not None
    )
    load_from_pv_balance = False
    if load_from_inverter_out:
        load_kw = _maybe_w_to_kw(flat.get("inverterOutputPower"))
        load_data_present = True
        load_can_estimate = True
        load_is_inverter_out = True
    elif (
        not load_data_present
        and not load_can_estimate
        and (_has_any(flat, pv_keys) or _has_any(flat, pv1_power_keys) or _has_any(flat, pv2_power_keys))
        and (_has_any(flat, charge_keys) or _has_any(flat, discharge_keys))
    ):
        load_kw = max(0.0, pv_kw + discharge_kw - charge_kw)
        load_data_present = True
        load_can_estimate = True
        load_is_inverter_out = False
        load_from_pv_balance = True
    else:
        load_is_inverter_out = False

    status = {}
    _set_if_present(status, "SOC", _first_nonempty(flat, soc_keys), flat, soc_keys)
    if _has_any(flat, pv_keys) or _has_any(flat, pv1_power_keys) or _has_any(flat, pv2_power_keys):
        status["ppv"] = pv_kw
    _set_if_present(status, "chargePower", charge_kw, flat, charge_keys)
    _set_if_present(status, "pdisCharge1", discharge_kw, flat, discharge_keys)
    if grid_data_present:
        # A real grid-power reading is in *this* payload — report it and
        # flag it as real so `_merge_grott_snapshots` never papers over it
        # with a balance-derived estimate (see `_backfill_estimated_grid`).
        status["pactouser"] = import_kw
        status["pactogrid"] = export_kw
        status["gridPowerEstimated"] = False
    if load_data_present or load_can_estimate:
        status["pLocalLoad"] = load_kw
        status["loadPowerEstimated"] = (
            load_is_inverter_out or load_from_pv_balance or not load_data_present
        )
        if load_is_inverter_out:
            status["loadSource"] = "inverter_output"
        elif load_from_pv_balance:
            status["loadSource"] = "pv_balance"
    for key, keys in (
        ("vAc1", ("vAc1", "vac1", "gridVoltage", "grid_voltage", "pvgridvoltage")),
        ("vac1", ("vac1", "vAc1", "gridVoltage", "grid_voltage", "pvgridvoltage")),
        ("fAc", ("fAc", "fac", "gridFrequency", "grid_frequency", "pvfrequentie")),
        ("vBat", ("vBat", "vbat", "batteryVoltage", "battery_voltage")),
        ("vPv1", ("vPv1", "vpv1", "pv1Voltage", "pv1_voltage", "pv1voltage")),
        ("vPv2", ("vPv2", "vpv2", "pv2Voltage", "pv2_voltage", "pv2voltage")),
        ("pmax", ("pmax", "nominalPower", "ratedPower", "pvpowermax")),
        ("lost", ("lost", "statusText", "status", "pvstatus")),
        ("status", ("status", "lost", "pvstatus")),
        ("wBatteryType", ("wBatteryType", "batteryType", "battery_type", "batterytype", "batttype")),
    ):
        _set_if_present(status, key, _first_nonempty(flat, keys), flat, keys)
    if _has_any(flat, pv1_power_keys):
        status["pPv1"] = _as_float(_first_nonempty(flat, pv1_power_keys), "")
    if _has_any(flat, pv2_power_keys):
        status["pPv2"] = _as_float(_first_nonempty(flat, pv2_power_keys), "")

    totals = {}
    for key, keys in (
        ("epvToday", ("epvToday", "epvtoday", "pvToday", "pv_today", "pvenergytoday")),
        ("epvTotal", ("epvTotal", "pvTotal", "pv_total", "pvenergytotal")),
        ("echargetoday", ("echargetoday", "echargeToday", "echarge1Today", "echarge1today")),
        ("edischarge1Today", ("edischarge1Today", "edischargeToday", "edischargetoday", "edischarge1today")),
        ("elocalLoadToday", ("elocalLoadToday", "loadToday", "load_today", "eactoday", "elocalloadtoday")),
        ("etoGridToday", ("etoGridToday", "exportToday", "export_today", "etogridtoday")),
    ):
        _set_if_present(totals, key, _first_nonempty(flat, keys), flat, keys)
    info = dict(flat)
    info.setdefault("vbatdsp", _first_nonempty(flat, ("vbatdsp", "vBatDsp", "batteryDisplayVoltage")))
    info.setdefault(
        "inverterModel",
        _first_nonempty(
            flat,
            (
                "inverterModel", "invertermodel", "inv_model", "inverter_model",
                "pvmodel", "pvModel", "inverterType", "invertertype",
                "deviceType", "devicetype", "plantData_deviceType",
                "datalogger_deviceType", "model", "alias",
            ),
        ),
    )
    info.setdefault(
        "batteryModel",
        _first_nonempty(
            flat,
            (
                "batteryModel", "batterymodel", "bat_model", "battery_model",
                "bmsmodel", "bmsModel", "batteryType", "batterytype", "batttype",
            ),
        ),
    )
    return {
        "topic": topic,
        "serial": str(serial).strip() if serial else "",
        "plant": str(plant).strip() if plant else "",
        "status": status,
        "info": info,
        "totals": totals,
        "received_at": time.time(),
        "raw": payload,
    }


def grott_snapshot_fresh(snapshot: dict | None, max_age_s: float = 120.0) -> bool:
    if not snapshot:
        return False
    ts = snapshot.get("received_at")
    try:
        return (time.time() - float(ts)) <= float(max_age_s)
    except (TypeError, ValueError):
        return False


def _merge_nonempty_dict(old: dict | None, new: dict | None) -> dict:
    merged = dict(old or {})
    for key, val in dict(new or {}).items():
        if val is None:
            continue
        if str(val).strip().lower() in _BAD:
            continue
        merged[key] = val
    return merged


def _status_has_load_reading(status: dict) -> bool:
    if not isinstance(status, dict) or "pLocalLoad" not in status:
        return False
    val = status.get("pLocalLoad")
    if val is None:
        return False
    return str(val).strip().lower() not in _BAD


def grott_derive_load_kw(status: dict) -> float | None:
    """House load (kW) from grid import/export + PV + battery when explicit load is absent."""
    if not isinstance(status, dict):
        return None
    # Do not derive load from an estimated grid value.  When both Grott load and
    # real grid are absent, load and grid are two unknowns in one balance equation.
    if status.get("gridPowerEstimated") is not False:
        return None
    has_grid = "pactouser" in status or "pactogrid" in status
    has_other = (
        "ppv" in status or "chargePower" in status or "pdisCharge1" in status
    )
    if not has_grid or not has_other:
        return None
    try:
        import_kw = float(status.get("pactouser", 0) or 0)
        export_kw = float(status.get("pactogrid", 0) or 0)
        pv = float(status.get("ppv", 0) or 0)
        charge = float(status.get("chargePower", 0) or 0)
        discharge = float(status.get("pdisCharge1", 0) or 0)
    except (TypeError, ValueError):
        return None
    return max(0.0, import_kw - export_kw + pv + discharge - charge)


def _backfill_merged_load_from_info(status: dict, info: dict | None) -> None:
    """Fill house load on the merged snapshot when partial frames omit it."""
    if _status_has_load_reading(status):
        return
    info = info or {}
    inv = _as_float(info.get("inverterOutputPower"), None)
    if inv is not None:
        status["pLocalLoad"] = _maybe_w_to_kw(inv)
        status["loadPowerEstimated"] = True
        status["loadSource"] = "inverter_output"
        return
    if "ppv" not in status:
        return
    try:
        pv = float(status.get("ppv") or 0)
        charge = float(status.get("chargePower") or 0)
        discharge = float(status.get("pdisCharge1") or 0)
    except (TypeError, ValueError):
        return
    if pv <= 0 and charge <= 0 and discharge <= 0:
        return
    status["pLocalLoad"] = max(0.0, pv + discharge - charge)
    status["loadPowerEstimated"] = True
    status["loadSource"] = "pv_balance"


def _backfill_estimated_load(status: dict, info: dict | None = None) -> None:
    """Back-solve house load on the merged Grott snapshot (symmetric to grid backfill)."""
    if status.get("loadPowerEstimated") is False:
        return
    if _status_has_load_reading(status) and not status.get("loadPowerEstimated"):
        return
    derived = grott_derive_load_kw(status)
    if derived is not None:
        status["pLocalLoad"] = derived
        status["loadPowerEstimated"] = True
        return
    if status.get("loadPowerEstimated") and not _status_has_load_reading(status):
        status.pop("pLocalLoad", None)
        status.pop("loadPowerEstimated", None)
        status.pop("loadSource", None)


def _backfill_estimated_grid(status: dict) -> None:
    """Back-solve Grid Power from the power balance when no Grott message
    has ever reported a real grid-power register, but PV, battery, and load
    are all now known in the *merged* snapshot.

    Some Grott layouts (seen on certain MIX/hybrid inverters) never publish
    a grid-power field at all — and worse, PV / battery / load can each
    arrive on separate cyclical records rather than all together in one
    payload, so a purely per-message estimate never has enough info to fire.
    Operating on the merged snapshot instead means it fires as soon as the
    three pieces have each arrived at least once, however many messages that
    took. Runs on every merge so the estimate stays fresh as PV/battery/load
    change; a message with a genuine reading (`gridPowerEstimated: False`)
    always wins and this function leaves it alone.
    """
    if status.get("gridPowerEstimated") is False:
        return  # a real reading is already in place — don't paper over it
    if status.get("loadPowerEstimated") and status.get("loadSource") not in (
        "inverter_output", "pv_balance",
    ):
        return  # don't build an estimated grid from a load that was back-solved from grid
    if not ("ppv" in status and "pLocalLoad" in status
            and ("chargePower" in status or "pdisCharge1" in status)):
        return
    try:
        pv = float(status.get("ppv", 0) or 0)
        load = float(status.get("pLocalLoad", 0) or 0)
        charge = float(status.get("chargePower", 0) or 0)
        discharge = float(status.get("pdisCharge1", 0) or 0)
    except (TypeError, ValueError):
        return
    net_kw = load + charge - pv - discharge
    if net_kw >= 0:
        status["pactouser"], status["pactogrid"] = net_kw, 0.0
    else:
        status["pactouser"], status["pactogrid"] = 0.0, -net_kw
    status["gridPowerEstimated"] = True


def _merge_grott_snapshots(old: dict | None, new: dict) -> dict:
    """Merge partial Grott frames into one API-shaped live bundle.

    Grott/MQTT installations commonly publish multiple records: one may carry
    live power, another totals, another model/info.  The dashboard wants the
    latest *bundle*, so keep previous fields until a later payload explicitly
    replaces them.
    """
    if not old:
        merged = dict(new)
        merged["status"] = dict(new.get("status") or {})
        _backfill_merged_load_from_info(merged["status"], merged.get("info"))
        _backfill_estimated_grid(merged["status"])
        _backfill_estimated_load(merged["status"], merged.get("info"))
    else:
        merged = dict(old)
        merged["topic"] = new.get("topic") or old.get("topic", "")
        merged["serial"] = new.get("serial") or old.get("serial", "")
        merged["plant"] = new.get("plant") or old.get("plant", "")
        merged["status"] = _merge_nonempty_dict(old.get("status"), new.get("status"))
        merged["info"] = _merge_nonempty_dict(old.get("info"), new.get("info"))
        merged["totals"] = _merge_nonempty_dict(old.get("totals"), new.get("totals"))
        merged["received_at"] = new.get("received_at", time.time())
        merged["raw"] = new.get("raw", {})
        _backfill_merged_load_from_info(merged["status"], merged.get("info"))
        _backfill_estimated_grid(merged["status"])
        _backfill_estimated_load(merged["status"], merged.get("info"))
    # #region agent log
    try:
        from energy_dashboard.core.debug_trace import debug_trace
        st = merged.get("status") or {}
        debug_trace(
            "grott_mqtt.py:_merge_grott_snapshots",
            "merge complete",
            data={
                "had_old": bool(old),
                "pLocalLoad": st.get("pLocalLoad"),
                "pactouser": st.get("pactouser"),
                "pactogrid": st.get("pactogrid"),
                "ppv": st.get("ppv"),
                "chargePower": st.get("chargePower"),
                "pdisCharge1": st.get("pdisCharge1"),
                "gridPowerEstimated": st.get("gridPowerEstimated"),
                "loadPowerEstimated": st.get("loadPowerEstimated"),
                "status_keys": sorted(st.keys()),
            },
            hypothesis_id="H2",
        )
    except Exception:
        pass
    # #endregion
    return merged


class GrottMqttSubscriber:
    """Background MQTT client; thread-safe latest Grott snapshot."""

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
        self._snapshot: dict | None = None
        self._last_emit = 0.0
        self._last_payload_status = 0.0
        self._emit_interval = 0.25
        self._topic = _DEFAULT_GROTT_TOPIC
        self._topic_filters: tuple[str, ...] = (_DEFAULT_GROTT_TOPIC,)
        self._host = ""
        self._port = 1883

    @property
    def connected(self) -> bool:
        return self._connected

    def snapshot(self) -> dict | None:
        with self._lock:
            return dict(self._snapshot) if self._snapshot else None

    def status(self) -> dict:
        snap = self.snapshot()
        age = None
        if snap:
            try:
                age = max(0.0, time.time() - float(snap.get("received_at")))
            except (TypeError, ValueError):
                age = None
        return {
            "enabled": self._running,
            "connected": self._connected,
            "host": self._host,
            "port": self._port,
            "topic": self._topic,
            "age_s": age,
            "fresh": grott_snapshot_fresh(snap),
            "serial": (snap or {}).get("serial", ""),
        }

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
        self._on_status("Grott MQTT stopped")

    def start(
        self,
        host: str,
        port: int = 1883,
        *,
        username: str = "",
        password: str = "",
        topic: str = _DEFAULT_GROTT_TOPIC,
        client_id: str = "",
    ) -> tuple[bool, str]:
        if mqtt is None:
            return False, "paho-mqtt not installed (pip install paho-mqtt)"
        host = (host or "").strip()
        if not host:
            return False, "Grott MQTT host is required"
        topic = (topic or _DEFAULT_GROTT_TOPIC).strip() or _DEFAULT_GROTT_TOPIC
        if not (client_id or "").strip():
            client_id = f"energy_dashboard_grott_{int(time.time())}"
        self._topic_filters = _topic_filters(topic)
        self.stop()

        try:
            try:
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION1,
                    client_id=client_id,
                    clean_session=True,
                )
            except (TypeError, AttributeError):
                try:
                    client = mqtt.Client(client_id=client_id, clean_session=True)
                except TypeError:
                    client = mqtt.Client(client_id=client_id)
        except Exception as e:
            return False, f"MQTT client: {e}"

        if username:
            client.username_pw_set(username, password or None)

        self._host = host
        self._port = int(port)
        self._topic = topic
        client.on_connect = self._mk_on_connect(topic)
        client.on_disconnect = self._mk_on_disconnect()
        client.on_message = self._mk_on_message()
        self._client = client
        self._running = True
        self._on_status(f"Grott MQTT connecting to {host}:{port}…")

        try:
            client.connect(host, int(port), keepalive=60)
            client.loop_start()
        except Exception as e:
            self.stop()
            return False, str(e)
        return True, f"Grott MQTT connecting to {host}:{port}"

    def _mk_on_connect(self, topic: str):
        def _on_connect(client, userdata, flags, rc, *args):
            ok = rc == 0
            self._connected = ok
            if not ok:
                self._on_status(f"Grott MQTT connect failed (rc={rc})")
                return
            filters = _topic_filters(topic)
            for filt in filters:
                client.subscribe(filt)
            self._on_status(f"Grott MQTT subscribed ({', '.join(filters)})")
        return _on_connect

    def _mk_on_disconnect(self):
        def _on_disconnect(client, userdata, rc, *args):
            self._connected = False
            if self._running:
                self._on_status(
                    "Grott MQTT disconnected"
                    if rc == 0
                    else f"Grott MQTT disconnected (rc={rc})"
                )
        return _on_disconnect

    def _mk_on_message(self):
        def _on_message(client, userdata, msg):
            self._handle_message(msg.topic, msg.payload)
        return _on_message

    def _handle_message(self, topic: str, payload: bytes) -> None:
        if not _grott_topic_matches(topic, self._topic_filters):
            return
        try:
            data = json.loads(payload.decode("utf-8", errors="replace"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        # #region agent log
        try:
            from energy_dashboard.core.debug_trace import debug_trace
            vals = data.get("values") if isinstance(data, dict) else None
            debug_trace(
                "grott_mqtt.py:_handle_message",
                "mqtt payload received",
                data={
                    "topic": topic,
                    "device": (data.get("device") if isinstance(data, dict) else None),
                    "value_keys": sorted(vals.keys()) if isinstance(vals, dict) else [],
                },
                hypothesis_id="H1",
            )
        except Exception:
            pass
        # #endregion
        snap = _normalize_grott_payload(data, topic=topic)
        if snap is None:
            now = time.monotonic()
            if now - self._last_payload_status >= 10.0:
                self._last_payload_status = now
                self._on_status(f"Grott MQTT ignored non-telemetry payload on {topic}")
            return
        with self._lock:
            self._snapshot = _merge_grott_snapshots(self._snapshot, snap)
        # #region agent log
        try:
            from energy_dashboard.core.debug_trace import debug_trace
            st = (self._snapshot or {}).get("status") or {}
            debug_trace(
                "grott_mqtt.py:_handle_message",
                "snapshot after merge",
                data={
                    "topic": topic,
                    "ppv": st.get("ppv"),
                    "pLocalLoad": st.get("pLocalLoad"),
                    "pactouser": st.get("pactouser"),
                    "pactogrid": st.get("pactogrid"),
                    "chargePower": st.get("chargePower"),
                    "loadPowerEstimated": st.get("loadPowerEstimated"),
                    "gridPowerEstimated": st.get("gridPowerEstimated"),
                },
                hypothesis_id="H2",
            )
        except Exception:
            pass
        # #endregion
        now = time.monotonic()
        if now - self._last_payload_status >= 10.0:
            self._last_payload_status = now
            self._on_status(f"Grott MQTT received inverter telemetry on {topic}")
        if now - self._last_emit >= self._emit_interval:
            self._last_emit = now
            self._on_update()


def test_grott_mqtt_connection(
    host: str,
    port: int,
    *,
    username: str = "",
    password: str = "",
    topic: str = _DEFAULT_GROTT_TOPIC,
    timeout_s: float = 6.0,
) -> tuple[bool, str]:
    """Connect, subscribe, and wait briefly for one Grott JSON payload."""
    if mqtt is None:
        return False, "paho-mqtt not installed (pip install paho-mqtt)"
    got = threading.Event()
    status = {"msg": "No message received"}

    try:
        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id=f"energy_dashboard_grott_test_{int(time.time())}",
            )
        except (TypeError, AttributeError):
            client = mqtt.Client(client_id=f"energy_dashboard_grott_test_{int(time.time())}")
    except Exception as e:
        return False, f"MQTT client: {e}"

    if username:
        client.username_pw_set(username, password or None)

    def on_connect(client, userdata, flags, rc, *args):
        if rc != 0:
            status["msg"] = f"connect failed rc={rc}"
            got.set()
            return
        for filt in _topic_filters(topic):
            client.subscribe(filt)
        status["msg"] = "connected; waiting for Grott payload"

    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        snap = _normalize_grott_payload(data, topic=msg.topic)
        if snap is None:
            return
        status["msg"] = f"received {msg.topic}"
        got.set()

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect((host or "").strip(), int(port), keepalive=30)
        client.loop_start()
        ok = got.wait(timeout_s)
    except Exception as e:
        return False, str(e)
    finally:
        try:
            client.loop_stop()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass
    return ok, status["msg"] if ok else f"Connected but no Grott payload within {timeout_s:.0f}s"
