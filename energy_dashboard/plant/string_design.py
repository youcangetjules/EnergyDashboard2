"""Design check: series string voltage against the inverter window.

Inputs are the panel datasheet and how many panels are in series.
The inverter limits are whatever was typed from its datasheet. A blank
limit is not guessed. This does not change measured string volts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from PySide6.QtCore import QSettings

_KEY = "plant/string_design"
_STC_C = 25.0


@dataclass(frozen=True)
class Bounds:
    mppt_min: float | None
    mppt_max: float | None
    voc_max: float | None

    def any_set(self) -> bool:
        return any(v is not None for v in (self.mppt_min, self.mppt_max, self.voc_max))


@dataclass(frozen=True)
class StringDesign:
    count: int
    vmp: float | None
    voc: float | None
    voc_cold: float | None
    vmp_hot: float | None
    state: str
    detail: str


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


def at_temperature(volts: float, coeff_pct_per_c: float | None, cell_c: float | None) -> float | None:
    """Datasheet volts shifted by a percent-per-degree coefficient from 25°C."""
    if coeff_pct_per_c is None or cell_c is None:
        return None
    return volts * (1.0 + (coeff_pct_per_c / 100.0) * (cell_c - _STC_C))


def _fmt(val: float) -> str:
    return f"{val:.0f} V"


def evaluate_string(
    count: int,
    *,
    vmp: float | None,
    voc: float | None,
    bounds: Bounds,
    voc_coeff: float | None = None,
    cold_c: float | None = None,
    vmp_coeff: float | None = None,
    hot_c: float | None = None,
) -> StringDesign:
    """Say whether one series string stays inside the typed voltage limits."""
    n = int(count or 0)
    if n < 1 or vmp is None or voc is None or vmp <= 0 or voc <= 0:
        return StringDesign(
            n, None, None, None, None, "unchecked",
            "This string needs a panel count and a datasheet Vmp and Voc.",
        )
    working = n * vmp
    open_circuit = n * voc
    voc_cold = None
    if voc_coeff is not None and cold_c is not None:
        voc_cold = at_temperature(open_circuit, voc_coeff, cold_c)
    vmp_hot = None
    if vmp_coeff is not None and hot_c is not None:
        vmp_hot = at_temperature(working, vmp_coeff, hot_c)

    bits = [
        f"{n} panels work near {_fmt(working)} "
        f"and are open-circuit at {_fmt(open_circuit)} on the 25°C test."
    ]
    if voc_cold is not None and cold_c is not None:
        bits.append(f"At {cold_c:.0f}°C the open-circuit voltage is about {_fmt(voc_cold)}.")
    if vmp_hot is not None and hot_c is not None:
        bits.append(f"At {hot_c:.0f}°C the working voltage is about {_fmt(vmp_hot)}.")

    if not bounds.any_set():
        bits.append("Type the inverter's voltage limits to see if this design fits.")
        return StringDesign(n, working, open_circuit, voc_cold, vmp_hot, "unchecked", " ".join(bits))

    problems = []
    provisional = []
    low_end = vmp_hot if vmp_hot is not None else working
    high_end = voc_cold if voc_cold is not None else open_circuit
    if bounds.mppt_min is not None and low_end < bounds.mppt_min:
        problems.append(
            f"The working voltage {_fmt(low_end)} is below the MPPT's lowest "
            f"{_fmt(bounds.mppt_min)}."
        )
    elif bounds.mppt_min is not None and vmp_hot is None:
        provisional.append(
            "Hot cells are not checked, so the working voltage may fall "
            f"below the MPPT's lowest {_fmt(bounds.mppt_min)}."
        )
    if bounds.mppt_max is not None and working > bounds.mppt_max:
        problems.append(
            f"The working voltage {_fmt(working)} is above the MPPT's highest "
            f"{_fmt(bounds.mppt_max)}."
        )
    if bounds.voc_max is not None and high_end > bounds.voc_max:
        problems.append(
            f"The open-circuit voltage {_fmt(high_end)} is above the inverter's "
            f"maximum {_fmt(bounds.voc_max)}."
        )
    elif bounds.voc_max is not None and voc_cold is None:
        provisional.append(
            "A cold morning is not checked. Open-circuit voltage rises when the "
            "cells are colder than 25°C, and that is the figure that must stay "
            f"under {_fmt(bounds.voc_max)}."
        )

    if problems:
        state = "outside"
        bits.extend(problems)
    elif provisional:
        state = "provisional"
        bits.extend(provisional)
    else:
        state = "inside"
        bits.append("This string stays inside the voltage limits that are filled in.")
    return StringDesign(n, working, open_circuit, voc_cold, vmp_hot, state, " ".join(bits))


def scenario_state(left: StringDesign, right: StringDesign | None = None) -> str:
    order = ("outside", "provisional", "unchecked", "inside")
    states = [left.state]
    if right is not None:
        states.append(right.state)
    for state in order:
        if state in states:
            return state
    return "unchecked"


def default_scenarios() -> list[dict]:
    return [
        {"name": "6 and 6", "n1": 6, "n2": 6},
        {"name": "7 and 5", "n1": 7, "n2": 5},
    ]


def _settings() -> QSettings:
    return QSettings("PowerModel", "EnergyDashboard2")


def load_design() -> dict:
    raw = _settings().value(_KEY, "", type=str) or ""
    data = {}
    if str(raw).strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            data = parsed
    scenarios = []
    for row in data.get("scenarios") or []:
        if not isinstance(row, dict):
            continue
        try:
            n1 = int(row.get("n1") or 0)
            n2 = int(row.get("n2") or 0)
        except (TypeError, ValueError):
            continue
        if n1 < 1 and n2 < 1:
            continue
        scenarios.append({
            "name": str(row.get("name") or "").strip() or f"{n1} and {n2}",
            "n1": max(0, n1),
            "n2": max(0, n2),
        })
    if not scenarios:
        scenarios = default_scenarios()
    return {
        "panel_id": str(data.get("panel_id") or ""),
        "mppt_min": _num(data.get("mppt_min")),
        "mppt_max": _num(data.get("mppt_max")),
        "voc_max": _num(data.get("voc_max")),
        "voc_coeff": _num(data.get("voc_coeff")),
        "cold_c": _num(data.get("cold_c")),
        "vmp_coeff": _num(data.get("vmp_coeff")),
        "hot_c": _num(data.get("hot_c")),
        "scenarios": scenarios,
    }


def save_design(record: dict) -> dict:
    clean = load_design()
    clean["panel_id"] = str(record.get("panel_id") or "")
    for key in ("mppt_min", "mppt_max", "voc_max", "voc_coeff", "cold_c", "vmp_coeff", "hot_c"):
        clean[key] = _num(record.get(key))
    scenarios = []
    for row in record.get("scenarios") or []:
        if not isinstance(row, dict):
            continue
        try:
            n1 = int(row.get("n1") or 0)
            n2 = int(row.get("n2") or 0)
        except (TypeError, ValueError):
            continue
        if n1 < 1 and n2 < 1:
            continue
        scenarios.append({
            "name": str(row.get("name") or "").strip() or f"{n1} and {n2}",
            "n1": max(0, min(n1, 40)),
            "n2": max(0, min(n2, 40)),
        })
    clean["scenarios"] = scenarios or default_scenarios()
    _settings().setValue(_KEY, json.dumps(clean))
    _settings().sync()
    return clean
