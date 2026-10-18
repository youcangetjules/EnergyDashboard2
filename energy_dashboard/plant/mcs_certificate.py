"""The house MCS certificate, kept on this machine.

The file itself is not a setting and is not committed. A short record of
what the certificate says (number, panel count, kWp) lives in app settings.
Those figures are what was installed. They are not a scale on measured volts.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from PySide6.QtCore import QSettings

_KEY = "plant/mcs_certificate"
_ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def certificate_dir() -> Path:
    folder = Path.home() / ".config" / "PowerModel" / "mcs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _settings() -> QSettings:
    return QSettings("PowerModel", "EnergyDashboard2")


def _blank() -> dict:
    return {
        "filename": "",
        "stored_name": "",
        "number": "",
        "panels": None,
        "kwp": None,
        "commissioned": "",
        "installer": "",
    }


def _num(val):
    if val is None or val in ("", "—", "--"):
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f or f <= 0:
        return None
    return f


def load_record() -> dict:
    raw = _settings().value(_KEY, "", type=str) or ""
    rec = _blank()
    if str(raw).strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            rec["filename"] = str(data.get("filename") or "")
            rec["stored_name"] = str(data.get("stored_name") or "")
            rec["number"] = str(data.get("number") or "")
            panels = _num(data.get("panels"))
            rec["panels"] = int(panels) if panels is not None else None
            rec["kwp"] = _num(data.get("kwp"))
            rec["commissioned"] = str(data.get("commissioned") or "")
            rec["installer"] = str(data.get("installer") or "")
    path = stored_path(rec)
    if path is None:
        rec["filename"] = ""
        rec["stored_name"] = ""
    return rec


def save_record(rec: dict) -> dict:
    clean = _blank()
    clean["filename"] = str(rec.get("filename") or "").strip()
    clean["stored_name"] = str(rec.get("stored_name") or "").strip()
    clean["number"] = str(rec.get("number") or "").strip()
    panels = _num(rec.get("panels"))
    clean["panels"] = int(panels) if panels is not None else None
    clean["kwp"] = _num(rec.get("kwp"))
    clean["commissioned"] = str(rec.get("commissioned") or "").strip()
    clean["installer"] = str(rec.get("installer") or "").strip()
    if stored_path(clean) is None:
        clean["filename"] = ""
        clean["stored_name"] = ""
    s = _settings()
    s.setValue(_KEY, json.dumps(clean))
    s.sync()
    return clean


def stored_path(rec: dict | None = None) -> Path | None:
    rec = load_record() if rec is None else rec
    name = str(rec.get("stored_name") or "")
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    path = certificate_dir() / name
    if not path.is_file():
        return None
    return path


def store_upload(src: Path) -> dict:
    """Copy the chosen certificate into the app folder and remember its name."""
    src = Path(src)
    suffix = src.suffix.lower()
    if suffix not in _ALLOWED or not src.is_file():
        raise ValueError("Choose a PDF or a picture of the certificate.")
    folder = certificate_dir()
    for old in folder.glob("certificate.*"):
        try:
            old.unlink()
        except OSError:
            pass
    stored_name = "certificate" + suffix
    dest = folder / stored_name
    shutil.copy2(src, dest)
    rec = load_record()
    rec["filename"] = src.name
    rec["stored_name"] = stored_name
    return save_record(rec)


def clear_certificate() -> dict:
    folder = certificate_dir()
    for old in folder.glob("certificate.*"):
        try:
            old.unlink()
        except OSError:
            pass
    rec = load_record()
    rec["filename"] = ""
    rec["stored_name"] = ""
    return save_record(rec)


def certificate_note() -> str:
    """One sentence for other pages. Empty when nothing has been saved."""
    rec = load_record()
    has_file = stored_path(rec) is not None
    panels = rec.get("panels")
    if not has_file and panels is None:
        return ""
    if has_file and panels:
        word = "panel" if int(panels) == 1 else "panels"
        return f"The MCS certificate on file records {int(panels)} {word}."
    if has_file:
        return "The MCS certificate is on file. Its panel count has not been typed in yet."
    word = "panel" if int(panels) == 1 else "panels"
    return f"The MCS certificate record says {int(panels)} {word}. The file itself has not been uploaded."
