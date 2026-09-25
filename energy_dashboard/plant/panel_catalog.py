"""PV module catalogue the householder types in.

Datasheet fields only. Live string voltage is never copied into Vmp, and a
blank voltage stays blank. Roof layout reads this list for each face.
"""
from __future__ import annotations

import json
import uuid
from copy import deepcopy

from PySide6.QtCore import QSettings

_KEY = "plant/panel_database"

# Approximate overall sizes already used by Roof layout. No datasheet volts.
_SEED = (
    {"id": "gen_370", "maker": "", "model": "Generic 370 W", "wp": 370, "vmp": None, "voc": None, "imp": None, "w_m": 1.134, "h_m": 1.722},
    {"id": "gen_400", "maker": "", "model": "Generic 400 W", "wp": 400, "vmp": None, "voc": None, "imp": None, "w_m": 1.134, "h_m": 1.722},
    {"id": "gen_420", "maker": "", "model": "Generic 420 W", "wp": 420, "vmp": None, "voc": None, "imp": None, "w_m": 1.134, "h_m": 1.722},
    {"id": "gen_450", "maker": "", "model": "Generic 450 W", "wp": 450, "vmp": None, "voc": None, "imp": None, "w_m": 1.134, "h_m": 1.903},
    {"id": "gen_500", "maker": "", "model": "Generic 500 W", "wp": 500, "vmp": None, "voc": None, "imp": None, "w_m": 1.134, "h_m": 1.962},
    {"id": "gen_550", "maker": "", "model": "Generic 550 W", "wp": 550, "vmp": None, "voc": None, "imp": None, "w_m": 1.134, "h_m": 2.278},
)


def _settings() -> QSettings:
    return QSettings("PowerModel", "EnergyDashboard2")


def _num(val):
    if val is None or val in ("", "—", "--"):
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


def _norm(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    maker = str(raw.get("maker") or "").strip()
    model = str(raw.get("model") or raw.get("name") or "").strip()
    wp = _num(raw.get("wp"))
    vmp = _num(raw.get("vmp"))
    voc = _num(raw.get("voc"))
    imp = _num(raw.get("imp"))
    w_m = _num(raw.get("w_m"))
    h_m = _num(raw.get("h_m"))
    if not any(v is not None and v != "" for v in (maker, model, wp, vmp, voc, imp, w_m, h_m)):
        return None
    pid = str(raw.get("id") or "").strip() or str(uuid.uuid4())
    return {
        "id": pid,
        "maker": maker,
        "model": model,
        "wp": wp,
        "vmp": vmp,
        "voc": voc,
        "imp": imp,
        "w_m": w_m,
        "h_m": h_m,
    }


def _seed() -> list[dict]:
    return [deepcopy(row) for row in _SEED]


def list_panels() -> list[dict]:
    """Saved modules, or the generic wattage presets when nothing is saved yet."""
    raw = _settings().value(_KEY, "", type=str) or ""
    if not str(raw).strip():
        return _seed()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _seed()
    if not isinstance(data, list):
        return _seed()
    out = []
    seen = set()
    for row in data:
        item = _norm(row)
        if item is None:
            continue
        if item["id"] in seen:
            item["id"] = str(uuid.uuid4())
        seen.add(item["id"])
        out.append(item)
    return out


def save_panels(rows) -> list[dict]:
    """Persist the catalogue. An empty list is kept — it does not restore the presets."""
    clean = []
    seen = set()
    for row in rows or []:
        item = _norm(row)
        if item is None:
            continue
        if item["id"] in seen:
            item["id"] = str(uuid.uuid4())
        seen.add(item["id"])
        clean.append(item)
    s = _settings()
    s.setValue(_KEY, json.dumps(clean))
    s.sync()
    return clean


def panel_by_id(pid: str) -> dict:
    key = str(pid or "")
    for panel in list_panels():
        if panel["id"] == key:
            return panel
    return {
        "id": key,
        "maker": "",
        "model": "",
        "wp": 0,
        "vmp": None,
        "voc": None,
        "imp": None,
        "w_m": None,
        "h_m": None,
    }


def panel_label(panel: dict) -> str:
    maker = str(panel.get("maker") or "").strip()
    model = str(panel.get("model") or "").strip()
    name = " ".join(part for part in (maker, model) if part) or "Panel"
    wp = _num(panel.get("wp"))
    if wp is None:
        return name
    shown = int(wp) if float(wp).is_integer() else wp
    return f"{name} ({shown} W)"
