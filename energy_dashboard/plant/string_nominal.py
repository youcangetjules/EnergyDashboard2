"""Nominal string voltage from the panel datasheet and the roof counts.

A series string adds the panel voltages. N panels work near N times Vmp
(the voltage at rated power) and sit near N times Voc (open circuit, sun
on the panels but almost no current). Measured inverter volts are never
rewritten from these figures. A blank Vmp or Voc stays blank.

The fit allows real cell temperature. Hot cells pull the working voltage
down to about 85% of Vmp. The middle of a working day should stay at or
under the datasheet open-circuit voltage (2% of slack). The high end may
sit about 6% above that, which is a cold bright morning: open-circuit
voltage rises by roughly a quarter of a percent per degree below the 25°C test.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from PySide6.QtCore import QSettings

from energy_dashboard.plant.mcs_certificate import certificate_note

_ROOF_KEY = "forecasts/roof_layout"
_DARK_BELOW = 50.0
_MIN_SAMPLES = 30
_HOT = 0.85
_COLD = 1.06
_MEDIAN_SLACK = 1.02
_MAX_COUNT = 16
_LAYOUTS = (
    ("6 and 6", (6, 6)),
    ("7 and 5", (7, 5)),
)


@dataclass(frozen=True)
class PanelSpec:
    label: str
    wp: float | None
    vmp: float | None
    voc: float | None
    imp: float | None

    def usable(self) -> bool:
        return (
            self.vmp is not None and self.vmp > 0
            and self.voc is not None and self.voc > 0
        )


@dataclass(frozen=True)
class StringNominal:
    number: int
    count: int
    faces: tuple[int, ...]
    panel: PanelSpec | None


@dataclass(frozen=True)
class StringVerdict:
    nominal: StringNominal
    samples: int
    median: float | None
    high: float | None
    saved_in_line: bool | None
    closest_count: int | None


def series_vmp(count: int, panel: PanelSpec) -> float:
    return count * float(panel.vmp)


def series_voc(count: int, panel: PanelSpec) -> float:
    return count * float(panel.voc)


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


def _pct(values: list[float], p: float) -> float:
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    frac = k - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac


def _in_band(count: int, panel: PanelSpec, median: float, high: float) -> bool:
    lo = series_vmp(count, panel) * _HOT
    voc = series_voc(count, panel)
    return lo <= median <= voc * _MEDIAN_SLACK and lo <= high <= voc * _COLD


def _center(count: int, panel: PanelSpec) -> float:
    return 0.5 * (series_vmp(count, panel) + series_voc(count, panel))


def _closest(panel: PanelSpec, median: float, high: float) -> int | None:
    hits = [
        n for n in range(1, _MAX_COUNT + 1)
        if _in_band(n, panel, median, high)
    ]
    if not hits:
        return None
    return min(hits, key=lambda n: (abs(median - _center(n, panel)), n))


def _panel_spec(raw: dict) -> PanelSpec:
    maker = str(raw.get("maker") or "").strip()
    model = str(raw.get("model") or "").strip()
    label = " ".join(part for part in (maker, model) if part) or "Panel"
    return PanelSpec(
        label=label,
        wp=_num(raw.get("wp")),
        vmp=_num(raw.get("vmp")),
        voc=_num(raw.get("voc")),
        imp=_num(raw.get("imp")),
    )


def _roof_planes() -> list[dict]:
    raw = QSettings("PowerModel", "EnergyDashboard2").value(_ROOF_KEY, "", type=str) or ""
    if not str(raw).strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    planes = data.get("planes") if isinstance(data, dict) else data
    return [p for p in (planes or []) if isinstance(p, dict)]


def load_string_nominals() -> list[StringNominal]:
    """Enabled roof faces, summed onto each inverter string."""
    from energy_dashboard.plant.panel_catalog import list_panels

    by_id = {str(p.get("id") or ""): p for p in list_panels()}
    grouped: dict[int, list[dict]] = {}
    for plane in _roof_planes():
        if not plane.get("enabled", True):
            continue
        try:
            count = int(plane.get("panel_count") or 0)
            number = int(plane.get("pv_string") or 0)
        except (TypeError, ValueError):
            continue
        if count <= 0 or number <= 0:
            continue
        grouped.setdefault(number, []).append(plane)
    out = []
    for number in sorted(grouped):
        faces = grouped[number]
        counts = tuple(int(face.get("panel_count") or 0) for face in faces)
        ids = {str(face.get("panel_type") or "") for face in faces}
        ids.discard("")
        panel = None
        if len(ids) == 1:
            raw = by_id.get(next(iter(ids)))
            if raw is not None:
                panel = _panel_spec(raw)
        out.append(StringNominal(number, sum(counts), counts, panel))
    return out


def judge_string(nominal: StringNominal, volts) -> StringVerdict:
    """Compare one string's measured volts with its roof count.

    Samples under 50 V are the inverter reporting a dark string. They are
    not a working voltage, so they stay out of the comparison.
    """
    producing = []
    for val in volts or []:
        v = _num(val)
        if v is not None and v >= _DARK_BELOW:
            producing.append(v)
    samples = len(producing)
    median = high = None
    saved_in = closest = None
    panel = nominal.panel
    if samples >= _MIN_SAMPLES:
        median = _pct(producing, 0.5)
        high = _pct(producing, 0.95)
        if panel is not None and panel.usable():
            saved_in = _in_band(nominal.count, panel, median, high)
            closest = _closest(panel, median, high)
    return StringVerdict(nominal, samples, median, high, saved_in, closest)


def _fmt_v(val: float) -> str:
    return f"{val:.0f} V"


def _face_phrase(nominal: StringNominal) -> str:
    n = nominal.count
    faces = nominal.faces
    panels = "panel" if n == 1 else "panels"
    if len(faces) <= 1:
        return f"string {nominal.number} is {n} {panels} on one face"
    parts = " and ".join(str(c) for c in sorted(faces, reverse=True))
    return f"string {nominal.number} is {n} {panels} across {len(faces)} faces ({parts})"


def _layout_sentence(verdicts: list[StringVerdict]) -> str:
    usable = [
        v for v in verdicts
        if v.median is not None and v.nominal.panel is not None and v.nominal.panel.usable()
        and v.nominal.number in (1, 2)
    ]
    if len(usable) < 2:
        return ""
    by_num = {v.nominal.number: v for v in usable}
    if 1 not in by_num or 2 not in by_num:
        return ""
    results = {}
    for name, counts in _LAYOUTS:
        ok = True
        for number, count in ((1, counts[0]), (2, counts[1])):
            verdict = by_num[number]
            if not _in_band(count, verdict.nominal.panel, verdict.median, verdict.high):
                ok = False
                break
        results[name] = ok
    six = results.get("6 and 6")
    seven = results.get("7 and 5")
    if six is None or seven is None:
        return ""

    def word(ok):
        return "fits the measured volts" if ok else "does not fit the measured volts"

    return (
        f"Against the measured volts, a 6-and-6 pair {word(six)}. "
        f"A 7-and-5 pair {word(seven)}. "
        "That check does not change how many panels are installed, "
        "and it does not multiply the measured volts."
    )


def verdict_paragraph(verdicts: list[StringVerdict], *, recent: bool = True) -> str:
    """Plain-English comparison for the string voltage page."""
    if not verdicts:
        return (
            "Roof layout has no panel counts, so there is no nominal "
            "string voltage to set beside the measured line."
        )
    panel = next(
        (v.nominal.panel for v in verdicts if v.nominal.panel is not None and v.nominal.panel.usable()),
        None,
    )
    lines = []
    if panel is None:
        lines.append(
            "The roof faces do not share one panel with Vmp and Voc filled in, "
            "so the nominal string voltage cannot be calculated."
        )
    else:
        spec = (
            f"{panel.label} is rated {panel.wp:.0f} W. "
            if panel.wp else f"{panel.label}. "
        )
        spec += (
            f"Vmp {panel.vmp:.1f} V is the voltage at that rated power, "
            f"Voc {panel.voc:.1f} V is the open-circuit voltage in the same test, "
            f"and Imp {panel.imp:.2f} A is the current at that power."
            if panel.imp else
            f"Vmp {panel.vmp:.1f} V is the voltage at rated power, and "
            f"Voc {panel.voc:.1f} V is the open-circuit voltage in the same test."
        )
        if panel.wp and panel.imp:
            product = panel.vmp * panel.imp
            if abs(product - panel.wp) / panel.wp <= 0.05:
                spec += f" {panel.vmp:.1f} V times {panel.imp:.2f} A comes back to {product:.0f} W, which matches the rated power."
            else:
                spec += (
                    f" {panel.vmp:.1f} V times {panel.imp:.2f} A is {product:.0f} W, "
                    f"which does not match the rated {panel.wp:.0f} W, so this band is less sure."
                )
        lines.append(spec)
        span = "Over recent days, while it is up" if recent else "While it is up in this window"
        face_bits = [_face_phrase(v.nominal) for v in verdicts]
        lines.append(
            "Roof layout says " + ", and ".join(face_bits) + ". "
            "Panels in series add their voltages. "
            "That count is the installation. It is not worked out by dividing the measured volts."
        )
        note = certificate_note()
        if note:
            lines.append(note)
    for verdict in verdicts:
        nom = verdict.nominal
        panel = nom.panel
        if panel is None or not panel.usable():
            continue
        expect = (
            f"String {nom.number} as {nom.count} panels should work near "
            f"{_fmt_v(series_vmp(nom.count, panel))} and stay under about "
            f"{_fmt_v(series_voc(nom.count, panel) * _COLD)} on a cold morning "
            f"(datasheet open-circuit is {_fmt_v(series_voc(nom.count, panel))})."
        )
        if verdict.median is None:
            lines.append(
                expect + " This window does not have half an hour above 50 V, "
                "so it cannot say whether the measured volts match."
            )
            continue
        measured = (
            f"{span}, the middle of the measured volts is {_fmt_v(verdict.median)} "
            f"and the high end is {_fmt_v(verdict.high)}."
        )
        if verdict.saved_in_line:
            lines.append(f"{expect} {measured} That is in line with the {nom.count} panels on that string.")
        else:
            lines.append(
                f"{expect} {measured} Those measured volts sit off the datasheet for the "
                f"{nom.count} panels on that string. The chart still shows the inverter's volts, "
                "with no extra multiplier."
            )
    layout = _layout_sentence(verdicts)
    if layout:
        lines.append(layout)
    lines.append(
        "Amber dashed lines are the roof datasheet for the panels that are installed. "
        "They are not a measurement. Volts under 50 V are the dark string and are left out of this check."
    )
    return " ".join(lines)
