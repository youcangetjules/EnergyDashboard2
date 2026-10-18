"""Read an MCS installation certificate and say what it actually prints.

A digital PDF is read as text. A scan or a photo has no text layer, so the
pages are read with the tesseract program when it is installed. Figures that
are not on the page stay blank. Nothing here changes measured volts, and a
string split is not invented from the panel total.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_PV_CODE = re.compile(r"\bMCS\s+P[V1]\s*\d{3,}", re.IGNORECASE)
_IK_CODE = re.compile(r"\bMCS\s+[I1l]\s*K\s*\d{3,}", re.IGNORECASE)
_MODEL = re.compile(
    r"\b([A-Z]{2,}(?:-[A-Z0-9]+){1,8})\s*[-–]?\s*(\d{3,4})\s*W\b",
    re.IGNORECASE,
)
_WATTS = re.compile(r"\b(\d{3,4})\s*W\b", re.IGNORECASE)


def interpret(path: Path, progress=None) -> dict:
    """Read *path* and return the figures the certificate prints, plus a paragraph."""
    path = Path(path)
    if progress:
        progress("Reading the certificate…")
    try:
        text, scanned = extract_text(path, progress=progress)
    except OSError as exc:
        return _empty(f"The certificate could not be read.\n{exc}")
    if not text.strip():
        return _empty(
            "This file has no text the app could read. "
            "A digital PDF is read directly. A scan or a photo needs the tesseract program."
        )
    parsed = parse_certificate(text)
    parsed["scanned"] = scanned
    if scanned:
        _reject_scan_count_if_it_disagrees(parsed)
        _imply_panels_from_capacity(parsed)
    parsed["text"] = describe(parsed)
    parsed["ok"] = bool(
        parsed.get("number") or parsed.get("panels") or parsed.get("kwp")
    )
    if not parsed["ok"]:
        parsed["text"] = (
            "The file was read, but it does not look like an MCS installation certificate. "
            "The details were left as they are."
        )
    return parsed


def extract_text(path: Path, progress=None) -> tuple[str, bool]:
    """Return (text, scanned). *scanned* is true when the words came from a picture."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _pdftotext(path)
        if _usable(text):
            return text, False
        if progress:
            progress("The PDF is a scan. Reading the pages. This can take a minute or two.")
        return _ocr_pdf(path, progress=progress), True
    if progress:
        progress("Reading the photo. This can take a minute or two.")
    return _ocr_image(path), True


def parse_certificate(text: str) -> dict:
    """Pull the labelled figures and the product rows out of certificate text."""
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    flat = re.sub(r"\s+", " ", text)
    number = _certificate_number(flat)
    version = _first(r"CERTIFICATE VERSION\s+(\d+)", flat)
    issued = _iso_date(_value_after(lines, r"CERTIFICATE VERSION\s+\d+"))
    if not issued:
        # The issue date sits on the line under the version.
        issued = _date_near(lines, r"CERTIFICATE VERSION")
    installer = _installer(lines)
    kwp = _float_value(_value_after(lines, r"Total Installed Capacity\s*\(kW\)"))
    annual = _float_value(_value_after(lines, r"Estimated Annual Generation\s*\(kWh\)"))
    commissioned = _iso_date(_value_after(lines, r"Commissioning Date"))
    declared = _float_value(_value_after(lines, r"Declared Net Capacity\s*\(kW\)"))
    technology = _value_after(lines, r"TECHNOLOGY TYPE")
    address = _value_after(lines, r"Address")
    modules, mounts = _products(lines)
    panels = sum(item["count"] for item in modules) or None
    return {
        "ok": False,
        "scanned": False,
        "number": number,
        "version": version,
        "issued": issued,
        "installer": installer,
        "kwp": kwp,
        "annual_kwh": annual,
        "commissioned": commissioned,
        "declared_kw": declared,
        "technology": _title_tech(technology),
        "address": address,
        "panels": panels,
        "modules": modules,
        "mounts": mounts,
        "text": "",
    }


def describe(parsed: dict, panels: list | None = None) -> str:
    """Plain-English reading. *panels* is the panel database, used only to name a match."""
    parts: list[str] = []
    number = parsed.get("number") or ""
    if number:
        line = f"This is MCS installation certificate {number}"
        if parsed.get("version"):
            line += f", version {parsed['version']}"
        if parsed.get("issued"):
            line += f", issued {_spoken(parsed['issued'])}"
        parts.append(line + ".")
    elif parsed.get("technology"):
        parts.append(f"This certificate is for {parsed['technology']}.")

    if parsed.get("installer") or parsed.get("commissioned"):
        if parsed.get("installer") and parsed.get("commissioned"):
            parts.append(
                f"{parsed['installer']} installed it. "
                f"It was commissioned on {_spoken(parsed['commissioned'])}."
            )
        elif parsed.get("installer"):
            parts.append(f"{parsed['installer']} installed it.")
        else:
            parts.append(f"It was commissioned on {_spoken(parsed['commissioned'])}.")
    if parsed.get("technology"):
        parts.append(f"The technology is {parsed['technology']}.")

    modules = parsed.get("modules") or []
    mounts = parsed.get("mounts") or []
    if modules and parsed.get("panels_implied"):
        item = next((row for row in modules if row.get("model")), modules[0])
        name = " ".join(p for p in (item.get("maker"), item.get("model")) if p) or "the module"
        if item.get("watts"):
            parts.append(f"The product table names the module as {name}, {item['watts']:g} W.")
        else:
            parts.append(f"The product table names the module as {name}.")
    elif modules:
        bits = []
        for item in modules:
            watts = item.get("watts")
            name = " ".join(
                part for part in (item.get("maker"), item.get("model")) if part
            ) or "modules"
            if watts:
                bits.append(f"{item['count']} {name} modules, {watts:g} W each")
            else:
                word = "module" if item["count"] == 1 else "modules"
                bits.append(f"{item['count']} {name} {word}")
        parts.append("The product list has " + ", and ".join(bits) + ".")
        watts = next((item.get("watts") for item in modules if item.get("watts")), None)
        count = parsed.get("panels")
        kwp = parsed.get("kwp")
        if count and watts and kwp is not None:
            expect = count * watts / 1000.0
            if abs(expect - kwp) <= 0.05:
                parts.append(
                    f"{count} × {watts:g} W is {_kw(expect)}, "
                    f"which matches the total installed capacity of {_kw(kwp)} on the certificate."
                )
            else:
                parts.append(
                    f"The product rows add up to {count} modules. "
                    f"{count} × {watts:g} W is {_kw(expect)}, "
                    f"while the certificate prints a total installed capacity of {_kw(kwp)}."
                )
        elif kwp is not None:
            parts.append(
                f"The total installed capacity printed on the certificate is {_kw(kwp)}."
            )
    if parsed.get("panels_implied"):
        item = next((row for row in modules if row.get("watts")), None)
        watts = item.get("watts") if item else None
        kwp = parsed.get("kwp")
        count = parsed.get("panels")
        if watts and kwp is not None and count:
            parts.append(
                f"{_kw(kwp)} divided by {watts:g} W is {count} modules. "
                "The scanned product table was only partly readable, so this total is that division, "
                "not a count of every row."
            )
    elif parsed.get("count_rejected"):
        parts.append(
            f"The scan's product table showed {parsed['count_rejected']} module rows, "
            "which does not match that capacity, so the panel total was left as it was."
        )
    elif not modules and parsed.get("kwp") is not None:
        parts.append(
            f"The total installed capacity printed on the certificate is {_kw(parsed['kwp'])}. "
            "The product table did not yield a module count."
        )

    if mounts:
        if parsed.get("scanned"):
            name = mounts[0].get("name") or "the mounting rails"
            parts.append(
                f"The table also names {name}. Those are the fixings, not extra panels."
            )
        else:
            bits = []
            for item in mounts:
                name = item.get("name") or "mounting kit"
                if "kit" not in name.lower() and "rail" not in name.lower():
                    name = name + (" mounting kit" if item["count"] == 1 else " mounting kits")
                elif "rail" in name.lower():
                    name = name + ("" if name.lower().endswith("s") else "")
                    word = "kit" if item["count"] == 1 else "kits"
                    name = f"{name} mounting {word}"
                bits.append(f"{item['count']} {name}")
            parts.append(
                "It also lists " + ", and ".join(bits) + ". Those are the fixings, not extra panels."
            )

    extras = []
    if parsed.get("annual_kwh") is not None:
        extras.append(
            f"the certificate's own estimate of annual generation is {_kwh(parsed['annual_kwh'])}"
        )
    if parsed.get("declared_kw") is not None:
        extras.append(
            f"declared net capacity is {_kw(parsed['declared_kw'])}, "
            "which is the grid-connection figure, not the size of the array"
        )
    if extras:
        sentence = extras[0][0].upper() + extras[0][1:]
        if len(extras) == 2:
            sentence += ". " + extras[1][0].upper() + extras[1][1:]
        parts.append(sentence + ".")

    count = parsed.get("panels")
    if count:
        parts.append(
            f"The certificate does not say how the {count} modules are split between the two strings. "
            "It does not print the working voltage (Vmp), the open-circuit voltage (Voc), or the current (Imp)."
        )
    match = _catalog_match(modules, panels or [])
    if match:
        parts.append(match)
    if parsed.get("address") and not parsed.get("scanned"):
        parts.append(f"The site printed on the certificate is {parsed['address']}.")
    if parsed.get("scanned"):
        parts.append("This was read from a scan, so a faint line in the product table can be missed.")
    return "\n\n".join(parts)


def _reject_scan_count_if_it_disagrees(parsed: dict) -> None:
    """A scan can miss a row. Do not store a module count that fights the printed kilowatts."""
    modules = parsed.get("modules") or []
    watts = next((item.get("watts") for item in modules if item.get("watts")), None)
    count = parsed.get("panels")
    kwp = parsed.get("kwp")
    if not count or not watts or kwp is None:
        return
    if abs(count * watts / 1000.0 - float(kwp)) > 0.05:
        parsed["count_rejected"] = count
        parsed["panels"] = None


def _imply_panels_from_capacity(parsed: dict) -> None:
    """When a scan misses rows,  kW divided by the module wattage is the total, and it is labelled as such."""
    if parsed.get("panels"):
        return
    modules = parsed.get("modules") or []
    watts = next((item.get("watts") for item in modules if item.get("watts")), None)
    kwp = parsed.get("kwp")
    if not watts or kwp is None:
        return
    implied = float(kwp) * 1000.0 / float(watts)
    nearest = int(round(implied))
    if nearest < 1 or abs(implied - nearest) > 0.02:
        return
    parsed["panels"] = nearest
    parsed["panels_implied"] = True


def _merge_modules(modules: dict) -> list[dict]:
    merged: dict[str, dict] = {}
    for row in modules.values():
        key = _fold(row.get("model") or "") or _fold(row.get("maker") or "module")
        got = merged.get(key)
        if got is None:
            maker = row.get("maker") or ""
            if "dah" in maker.lower():
                maker = "DAH Solar"
            merged[key] = {
                "count": row["count"],
                "maker": maker,
                "model": row.get("model") or "",
                "watts": row.get("watts"),
            }
            continue
        got["count"] += row["count"]
        if row.get("watts") and not got.get("watts"):
            got["watts"] = row["watts"]
        if row.get("model") and not got.get("model"):
            got["model"] = row["model"]
    return list(merged.values())


def _merge_mounts(mounts: list[dict]) -> list[dict]:
    if not mounts:
        return []
    if any("solidrail" in (item.get("name") or "").lower() for item in mounts):
        total = sum(int(item.get("count") or 0) for item in mounts)
        return [{"count": total, "name": "K2 Solidrail"}]
    return mounts


def add_catalog_note(parsed: dict, panels: list | None) -> dict:
    """Mention a panel-database row that is the same module. Does not change its volts."""
    parsed = dict(parsed)
    note = _catalog_match(parsed.get("modules") or [], panels or [])
    if not note:
        return parsed
    text = (parsed.get("text") or "").rstrip()
    parsed["text"] = (text + "\n\n" + note).strip() if text else note
    return parsed


def fill_record(rec: dict, parsed: dict) -> dict:
    """Copy figures the certificate actually printed. A blank stay blank."""
    rec = dict(rec)
    if parsed.get("number"):
        rec["number"] = parsed["number"]
    if parsed.get("panels"):
        rec["panels"] = int(parsed["panels"])
    if parsed.get("kwp"):
        rec["kwp"] = float(parsed["kwp"])
    if parsed.get("commissioned"):
        rec["commissioned"] = parsed["commissioned"]
    if parsed.get("installer"):
        rec["installer"] = parsed["installer"]
    if parsed.get("text"):
        rec["reading"] = parsed["text"]
    return rec


def _empty(message: str) -> dict:
    parsed = parse_certificate("")
    parsed["text"] = message
    parsed["ok"] = False
    return parsed


def _products(lines: list[str]) -> tuple[list[dict], list[dict]]:
    modules: dict[tuple, dict] = {}
    mounts: dict[str, dict] = {}
    pending_without_model = False
    for line in lines:
        if not line or line.startswith("MCS PRODUCT") or line.startswith("PRODUCT "):
            continue
        has_pv = _PV_CODE.search(line) is not None
        has_ik = _IK_CODE.search(line) is not None
        model = _model_on(line)
        if has_ik and not has_pv:
            name = _mount_name(line)
            row = mounts.setdefault(name, {"count": 0, "name": name})
            row["count"] += 1
            pending_without_model = False
            continue
        if has_pv and model:
            _add_module(modules, model, line)
            pending_without_model = False
        elif has_pv:
            _add_module(modules, {"maker": _maker_on(line), "model": "", "watts": None}, line)
            pending_without_model = True
        elif model and pending_without_model:
            # The model fell onto the next line of a row already counted.
            _attach_model(modules, model)
            pending_without_model = False
        elif model:
            _add_module(modules, model, line)
            pending_without_model = False
        elif "solidrail" in line.lower() or "mounting solution" in line.lower():
            name = _mount_name(line)
            row = mounts.setdefault(name, {"count": 0, "name": name})
            row["count"] += 1
            pending_without_model = False
    return _merge_modules(modules), _merge_mounts(list(mounts.values()))


def _add_module(modules: dict, model: dict, line: str) -> None:
    maker = model.get("maker") or _maker_on(line)
    key = (
        _fold(maker),
        _fold(model.get("model") or ""),
        model.get("watts"),
    )
    row = modules.setdefault(
        key,
        {"count": 0, "maker": maker, "model": model.get("model") or "", "watts": model.get("watts")},
    )
    if maker and not row["maker"]:
        row["maker"] = maker
    if model.get("model") and not row["model"]:
        row["model"] = model["model"]
    if model.get("watts") and not row["watts"]:
        row["watts"] = model["watts"]
    row["count"] += 1


def _attach_model(modules: dict, model: dict) -> None:
    """Fill the model onto the most recent module row that does not have one yet."""
    for row in reversed(list(modules.values())):
        if not row.get("model"):
            row["model"] = model.get("model") or ""
            row["watts"] = model.get("watts")
            if model.get("maker") and not row.get("maker"):
                row["maker"] = model["maker"]
            return


def _model_on(line: str) -> dict | None:
    match = _MODEL.search(line)
    watts = int(match.group(2)) if match else _fuzzy_watts(line)
    if not watts:
        return None
    if match:
        model = f"{match.group(1)}-{watts}W"
    else:
        model = f"DHM-72X10-{watts}W"
    model = re.sub(r"[\s-]+", "-", model).upper().strip("-")
    model = re.sub(r"-{2,}", "-", model)
    return {"maker": _maker_on(line), "model": model, "watts": watts}


def _fuzzy_watts(line: str) -> int | None:
    """A scan often reads 550 as 5S0 or S50 on the DAH module name."""
    match = re.search(r"DHM[\s-]*72\s*X\s*10[^\dA-Z]{0,8}([0-9SO]{3})\s*W", line, re.IGNORECASE)
    if not match:
        return None
    token = match.group(1).upper().replace("S", "5").replace("O", "0")
    if not token.isdigit():
        return None
    watts = int(token)
    if not 200 <= watts <= 800:
        return None
    return watts


def _maker_on(line: str) -> str:
    if re.search(r"DAH\s*Solar", line, re.IGNORECASE):
        return "DAH Solar"
    match = re.search(
        r"(K2 Solar[^,]*(?:,\s*Ltd\.?)?|[A-Z][\w&.''-]+(?:\s+[A-Z][\w&.''-]+){0,4}\s+Ltd\.?)",
        line,
    )
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip(" ,")


def _mount_name(line: str) -> str:
    if "solidrail" in line.lower():
        return "K2 Solidrail"
    if "k2" in line.lower():
        return "K2 mounting"
    return "mounting kit"


def _catalog_match(modules: list[dict], panels: list) -> str:
    if not modules or not panels:
        return ""
    item = modules[0]
    token = _fold(item.get("model") or "")
    # DHM-72X10-550W → dhm72x10, enough to meet DHM72x10 in the database.
    token = re.sub(r"\d{3,4}w$", "", token)
    if len(token) < 4:
        return ""
    for panel in panels:
        blob = _fold(f"{panel.get('maker') or ''} {panel.get('model') or ''}")
        if token and token in blob:
            from energy_dashboard.plant.panel_catalog import panel_label
            return (
                f"The panel database already has this module as {panel_label(panel)}. "
                "The certificate does not print Vmp, Voc, or Imp, so those stay as they are there."
            )
    return ""


def _certificate_number(flat: str) -> str:
    match = re.search(r"\bMCS\s*-?\s*(\d{7,10})\s*-?\s*([A-Z])\b", flat, re.IGNORECASE)
    if not match:
        return ""
    return f"MCS-{match.group(1)}-{match.group(2).upper()}"


def _installer(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if not re.search(r"Installer Company Name and MCS Number", line, re.IGNORECASE):
            continue
        for nxt in lines[index + 1:index + 4]:
            cleaned = _clean_installer(nxt)
            if cleaned:
                return cleaned
    for line in lines:
        cleaned = _clean_installer(line)
        if cleaned and "ltd" in cleaned.lower():
            return cleaned
    return ""


def _clean_installer(line: str) -> str:
    line = line.strip(" `'\"“”‘’")
    match = re.search(r"^(.+?\bLtd\.?)\s*\(([A-Z]{2,6})(\d+)\)\s*$", line)
    if not match:
        return ""
    # A scan often drops a digit. Keep the scheme number only when it is a full one.
    if len(match.group(3)) < 6:
        return match.group(1).strip()
    return f"{match.group(1).strip()} ({match.group(2)}{match.group(3)})"


def _value_after(lines: list[str], label: str) -> str:
    pattern = re.compile(label, re.IGNORECASE)
    for index, line in enumerate(lines):
        match = pattern.search(line)
        if not match:
            continue
        rest = line[match.end():].strip(" :\t-")
        rest = re.split(r"\s{2,}", rest)[0].strip()
        if rest and ":" not in rest and not rest.lower().startswith("ibg"):
            return rest
        for nxt in lines[index + 1:index + 4]:
            nxt = nxt.strip()
            if not nxt or nxt.lower().startswith("ibg"):
                continue
            return re.split(r"\s{2,}", nxt)[0].strip()
    return ""


def _date_near(lines: list[str], label: str) -> str:
    pattern = re.compile(label, re.IGNORECASE)
    for index, line in enumerate(lines):
        if not pattern.search(line):
            continue
        for nxt in lines[index:index + 4]:
            iso = _iso_date(nxt)
            if iso:
                return iso
    return ""


def _iso_date(raw: str) -> str:
    """MCS dates are day/month/year."""
    match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", raw or "")
    if not match:
        return ""
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if year < 100:
        year += 2000
    if not (1 <= day <= 31 and 1 <= month <= 12 and 2000 <= year <= 2100):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def _spoken(iso: str) -> str:
    year, month, day = (int(part) for part in iso.split("-"))
    return f"{day} {_MONTHS[month - 1]} {year}"


def _float_value(raw: str) -> float | None:
    match = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)", raw or "")
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def _first(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _title_tech(raw: str) -> str:
    words = (raw or "").strip(" :.")
    if not words:
        return ""
    return words.lower()


def _kw(value: float) -> str:
    return f"{value:.2f} kW"


def _kwh(value: float) -> str:
    if float(value).is_integer():
        return f"{int(value):,} kWh".replace(",", ",")
    return f"{value:,.1f} kWh"


def _fold(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _usable(text: str) -> bool:
    letters = sum(ch.isalpha() for ch in text)
    return letters >= 80 and ("MCS" in text or "certificate" in text.lower())


def _pdftotext(path: Path) -> str:
    if shutil.which("pdftotext") is None:
        return ""
    try:
        done = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout or ""


def _ocr_pdf(path: Path, progress=None) -> str:
    if shutil.which("pdftoppm") is None or shutil.which("tesseract") is None:
        return ""
    chunks: list[str] = []
    with tempfile.TemporaryDirectory(prefix="mcs-ocr-") as folder:
        try:
            subprocess.run(
                ["pdftoppm", "-gray", "-r", "140", "-png", str(path), str(Path(folder) / "p")],
                check=False,
                capture_output=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        pages = sorted(Path(folder).glob("p*.png"))
        for index, image in enumerate(pages[:4], start=1):
            if progress:
                progress(f"Reading scanned page {index}…")
            chunks.append(_tesseract(image))
            so_far = "\n".join(chunks)
            if index >= 2 and re.search(
                r"Declared Net Capacity|Generation Meter|Consumer Information",
                so_far,
                re.IGNORECASE,
            ):
                break
    return "\n".join(chunks)


def _ocr_image(path: Path) -> str:
    return _tesseract(path)


def _tesseract(image: Path) -> str:
    if shutil.which("tesseract") is None:
        return ""
    out_base = Path(tempfile.gettempdir()) / f"mcs-ocr-{image.stem}"
    try:
        subprocess.run(
            ["tesseract", str(image), str(out_base), "--psm", "6", "--oem", "1", "-l", "eng"],
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    text_path = Path(str(out_base) + ".txt")
    try:
        return text_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    finally:
        try:
            text_path.unlink()
        except OSError:
            pass
