"""Compare a Grott MQTT snapshot with a Growatt cloud live bundle.

Both sides are already normalised to MIX-style dicts (``status`` / ``info`` /
``totals``). This module does not talk to MQTT or the cloud.
"""
from __future__ import annotations

from typing import Any

# (id, label, section, key, unit, abs_tolerance)
# section: status | info | totals
_ALIGN_FIELDS: tuple[tuple[str, str, str, str, str, float], ...] = (
    ("soc", "Battery SOC", "status", "SOC", "%", 1.0),
    ("pv", "PV power", "status", "ppv", "kW", 0.05),
    ("pv1", "PV string 1", "status", "pPv1", "kW", 0.05),
    ("pv2", "PV string 2", "status", "pPv2", "kW", 0.05),
    ("charge", "Battery charge", "status", "chargePower", "kW", 0.05),
    ("discharge", "Battery discharge", "status", "pdisCharge1", "kW", 0.05),
    ("load", "House load", "status", "pLocalLoad", "kW", 0.08),
    ("grid_in", "Grid import", "status", "pactouser", "kW", 0.08),
    ("grid_out", "Grid export", "status", "pactogrid", "kW", 0.08),
    ("vac", "Grid voltage", "status", "vAc1", "V", 2.0),
    ("fac", "Grid frequency", "status", "fAc", "Hz", 0.08),
    ("vbat", "Battery voltage", "status", "vBat", "V", 0.4),
    ("pv_today", "PV today", "totals", "epvToday", "kWh", 0.15),
    ("chg_today", "Charge today", "totals", "echargetoday", "kWh", 0.15),
    ("dch_today", "Discharge today", "totals", "edischarge1Today", "kWh", 0.15),
    ("load_today", "Load today", "totals", "elocalLoadToday", "kWh", 0.2),
    ("imp_today", "Import today", "totals", "etouser", "kWh", 0.2),
    ("exp_today", "Export today", "totals", "etoGridToday", "kWh", 0.2),
)


def _as_float(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        if val != val:  # NaN
            return None
        return float(val)
    text = str(val).strip().replace(",", "")
    if text.lower() in ("", "--", "—", "none", "null", "nan"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _section(bundle: dict | None, name: str) -> dict:
    if not isinstance(bundle, dict):
        return {}
    if name in bundle and isinstance(bundle.get(name), dict):
        return bundle[name]
    # Cloud fetch returns a 3-tuple unpacked by callers; a flat MIX status
    # dict is also accepted.
    if name == "status":
        return bundle
    return bundle.get(name) or {}


def _notes_for(field_id: str, grott_status: dict) -> str:
    bits = []
    if field_id == "load" and grott_status.get("loadPowerEstimated"):
        bits.append("Grott load estimated")
    if field_id in ("grid_in", "grid_out") and grott_status.get("gridPowerEstimated"):
        bits.append("Grott grid estimated")
    return "; ".join(bits)


def compare_grott_to_api(
    grott_bundle: dict | None,
    api_status: dict | None,
    api_info: dict | None,
    api_totals: dict | None,
) -> dict:
    """Return ``{rows, aligned, mismatch, grott_only, api_only, both_missing}``.

    Each row: field, label, unit, grott, api, delta, result, notes, tolerance.
    """
    g_st = _section(grott_bundle, "status")
    g_info = _section(grott_bundle, "info")
    g_tot = _section(grott_bundle, "totals")
    api_bundle = {
        "status": api_status if isinstance(api_status, dict) else {},
        "info": api_info if isinstance(api_info, dict) else {},
        "totals": api_totals if isinstance(api_totals, dict) else {},
    }
    rows = []
    counts = {
        "aligned": 0,
        "mismatch": 0,
        "grott_only": 0,
        "api_only": 0,
        "both_missing": 0,
    }
    for fid, label, section, key, unit, tol in _ALIGN_FIELDS:
        src_g = {"status": g_st, "info": g_info, "totals": g_tot}[section]
        src_a = api_bundle[section]
        gv = _as_float(src_g.get(key)) if isinstance(src_g, dict) else None
        av = _as_float(src_a.get(key)) if isinstance(src_a, dict) else None
        notes = _notes_for(fid, g_st)
        if gv is None and av is None:
            result = "both_missing"
            delta = None
        elif gv is None:
            result = "api_only"
            delta = None
        elif av is None:
            result = "grott_only"
            delta = None
        else:
            delta = gv - av
            result = "aligned" if abs(delta) <= tol else "mismatch"
        counts[result] += 1
        rows.append({
            "field": fid,
            "label": label,
            "unit": unit,
            "key": key,
            "grott": gv,
            "api": av,
            "delta": delta,
            "result": result,
            "notes": notes,
            "tolerance": tol,
        })
    return {"rows": rows, **counts}


__all__ = ["compare_grott_to_api", "_ALIGN_FIELDS"]
