"""Read a PV module datasheet and keep only the figures it prints.

A digital PDF is read as text. A scan is read as a picture, a few pages at
a time, and stops once the electrical table is in hand. A missing figure
stays missing. Live inverter volts are not used here.
"""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from energy_dashboard.plant.mcs_read import (
    _ocr_image,
    _pdf_page_count,
    _pdftotext,
    _render_page,
    _tesseract,
)

_SCAN_MAX_PAGES = 6
_FIELDS = ("maker", "model", "wp", "vmp", "voc", "imp", "w_m", "h_m")
_RANGES = {
    "wp": (50.0, 800.0),
    "vmp": (10.0, 90.0),
    "voc": (10.0, 100.0),
    "imp": (1.0, 25.0),
}
# More specific phrases first, so "maximum power voltage" is not the wattage.
_LABELS = (
    ("vmp", re.compile(
        r"voltage at max(?:imum)? power|\bvm(?:pp|p)\b",
        re.IGNORECASE,
    )),
    ("imp", re.compile(
        r"current at max(?:imum)? power|\bim(?:pp|p)\b",
        re.IGNORECASE,
    )),
    ("voc", re.compile(
        r"open[- ]circuit voltage|\bvoc\b",
        re.IGNORECASE,
    )),
    ("wp", re.compile(
        r"maximum power(?!\s+(?:voltage|current))|\bpmax\b|\brated power\b|\bnominal power\b",
        re.IGNORECASE,
    )),
)


def read_datasheet(path: Path, progress=None) -> dict:
    """Figures printed on this datasheet. ``ok`` is false when none were found."""
    path = Path(path)
    if progress:
        progress("Reading the spec sheet…")
    try:
        text, scanned = _read(path, progress)
    except OSError as exc:
        return _empty(f"The spec sheet could not be read.\n{exc}")
    if not text.strip():
        return _empty(
            "This file has no text the app could read. "
            "A digital PDF is read directly. A scan or a photo needs the tesseract program."
        )
    parsed = parse_datasheet(text)
    parsed["scanned"] = scanned
    parsed["ok"] = any(parsed.get(key) not in (None, "") for key in ("wp", "vmp", "voc", "imp"))
    parsed["note"] = _note(parsed)
    return parsed


def parse_datasheet(text: str) -> dict:
    """Pull maker, model, watts, volts, amps, and size out of datasheet text."""
    flat = re.sub(r"\s+", " ", text or "")
    found = {key: None for key in _FIELDS}
    found["maker"] = _maker(flat)
    found["model"] = _model(flat)
    for key, pattern in _LABELS:
        found[key] = _labelled_number(flat, pattern, key)
    width, height = _size_m(flat)
    found["w_m"] = width
    found["h_m"] = height
    found["scanned"] = False
    found["ok"] = False
    found["note"] = ""
    return found


def _read(path: Path, progress) -> tuple[str, bool]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _pdftotext(path)
        if sum(ch.isalpha() for ch in text) >= 80:
            return text, False
        if progress:
            progress("The PDF is a scan. Reading the first pages.")
        return _ocr_datasheet(path, progress), True
    if progress:
        progress("Reading the photo.")
    return _ocr_image(path), True


def _ocr_datasheet(path: Path, progress) -> str:
    if shutil.which("pdftoppm") is None or shutil.which("tesseract") is None:
        return ""
    page_count = min(_pdf_page_count(path), _SCAN_MAX_PAGES)
    chunks: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sheet-ocr-") as folder:
        for index in range(1, page_count + 1):
            if progress:
                progress(f"Reading scanned page {index}…")
            image = _render_page(path, index, Path(folder))
            if image is None:
                break
            chunks.append(_tesseract(image))
            parsed = parse_datasheet("\n".join(chunks))
            if parsed.get("vmp") and parsed.get("voc") and parsed.get("wp"):
                break
    return "\n".join(chunks)


def _labelled_number(text: str, pattern: re.Pattern, key: str) -> float | None:
    lo, hi = _RANGES[key]
    for match in pattern.finditer(text):
        window = text[match.end(): match.end() + 40]
        number = re.search(r"(\d+(?:\.\d+)?)\s*(kW|W|V|A|%)?", window, re.IGNORECASE)
        if number is None:
            continue
        if (number.group(2) or "").strip() == "%":
            continue
        before = window[:number.start()]
        if re.search(r"coeff|%/|°\s*C|temperature", before, re.IGNORECASE):
            continue
        try:
            value = float(number.group(1))
        except ValueError:
            continue
        unit = (number.group(2) or "").lower()
        if key == "wp" and unit == "kw" and value < 2:
            value *= 1000.0
        if lo <= value <= hi:
            return value
    return None


def _maker(text: str) -> str:
    match = re.search(
        r"\b([A-Z][A-Za-z.&]+(?:\s+[A-Z][A-Za-z.&]+){0,3})\s+Solar\b",
        text,
    )
    if not match:
        return ""
    return " ".join(match.group(1).split())


def _model(text: str) -> str:
    match = re.search(
        r"(?:module\s+type|model(?:\s+(?:no\.?|number|name))?)\s*[:\-]?\s*"
        r"([A-Z0-9][A-Z0-9./\-]{2,40})",
        text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    token = match.group(1).strip(" .,-")
    token = re.sub(r"[-/]?\d{3,4}\s*W$", "", token, flags=re.IGNORECASE).strip("-/")
    return token


def _size_m(text: str) -> tuple[float | None, float | None]:
    match = re.search(
        r"(\d{3,4}(?:\.\d+)?)\s*[×xX]\s*(\d{3,4}(?:\.\d+)?)"
        r"(?:\s*[×xX]\s*(\d{1,4}(?:\.\d+)?))?\s*mm",
        text,
    )
    if match is None:
        return None, None
    sides = []
    for group in match.groups():
        if not group:
            continue
        mm = float(group)
        if 200.0 <= mm <= 3000.0:
            sides.append(mm / 1000.0)
    if len(sides) < 2:
        return None, None
    sides.sort()
    return round(sides[0], 3), round(sides[1], 3)


def _note(parsed: dict) -> str:
    if not parsed.get("ok"):
        return (
            "The file was read, but it does not print a module wattage, "
            "working voltage, open-circuit voltage, or current. Nothing was added."
        )
    bits = []
    if parsed.get("maker") or parsed.get("model"):
        name = " ".join(part for part in (parsed.get("maker"), parsed.get("model")) if part)
        bits.append(name)
    if parsed.get("wp"):
        watts = parsed["wp"]
        bits.append(f"{int(watts) if float(watts).is_integer() else watts} W")
    if parsed.get("vmp"):
        bits.append(f"Vmp {_trim(parsed['vmp'])} V")
    if parsed.get("voc"):
        bits.append(f"Voc {_trim(parsed['voc'])} V")
    if parsed.get("imp"):
        bits.append(f"Imp {_trim(parsed['imp'])} A")
    if parsed.get("w_m") and parsed.get("h_m"):
        bits.append(f"{parsed['w_m']:.3f} m by {parsed['h_m']:.3f} m")
    sentence = "The sheet prints " + ", ".join(bits) + "."
    missing = []
    for key, label in (
        ("wp", "rated watts"),
        ("vmp", "working voltage"),
        ("voc", "open-circuit voltage"),
        ("imp", "current"),
    ):
        if not parsed.get(key):
            missing.append(label)
    if missing:
        sentence += " Not printed, so left blank: " + ", ".join(missing) + "."
    if parsed.get("scanned"):
        sentence += " The PDF was a scan."
    sentence += " Press Save to keep this module."
    return sentence


def _trim(value: float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _empty(note: str) -> dict:
    found = {key: None for key in _FIELDS}
    found.update({"maker": "", "model": "", "ok": False, "scanned": False, "note": note})
    return found
