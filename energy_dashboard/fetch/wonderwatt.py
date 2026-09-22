"""Wonder Watt share-link helpers (forecast comparison for Potential Issues).

app.wonderwatt.com is a Blazor Server app. A share URL of the form
``?wattid=…&sig=…&time=…`` sets session cookies; there is no public JSON
forecast API. This module:

* parses and persists the share URL in QSettings
* tests that the share cookies are accepted
* exposes optional daily kWh overrides (paste / manual) until a live
  forecast endpoint can be reverse-engineered
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

_QS_ORG = "PowerModel"
_QS_APP = "EnergyDashboard2"
_QS_SHARE = "wonderwatt/share_url"
_QS_DAILY = "wonderwatt/daily_kwh_json"
_WW_ORIGIN = "https://app.wonderwatt.com"
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def wonderwatt_settings():
    from energy_dashboard.deps import QSettings
    return QSettings(_QS_ORG, _QS_APP)


def parse_wonderwatt_share_url(url: str) -> dict[str, str] | None:
    """Return ``{wattid, sig, time, share_url}`` or None if incomplete."""
    text = (url or "").strip()
    if not text:
        return None
    if "://" not in text and text.startswith("?"):
        text = _WW_ORIGIN + "/" + text
    elif "://" not in text and "wattid=" in text:
        text = _WW_ORIGIN + "/?" + text.lstrip("?&")
    try:
        parsed = urlparse(text)
    except Exception:
        return None
    qs = parse_qs(parsed.query)
    wattid = (qs.get("wattid") or [""])[0].strip()
    sig = unquote((qs.get("sig") or [""])[0].strip())
    time_s = (qs.get("time") or [""])[0].strip()
    if not wattid or not sig or not time_s:
        return None
    # Rebuild a canonical share URL for storage / requests.
    from urllib.parse import quote, urlencode
    share = (
        f"{_WW_ORIGIN}/?"
        + urlencode({"wattid": wattid, "sig": sig, "time": time_s}, quote_via=quote)
    )
    return {"wattid": wattid, "sig": sig, "time": time_s, "share_url": share}


def load_wonderwatt_share_url() -> str:
    return str(wonderwatt_settings().value(_QS_SHARE, "") or "").strip()


def save_wonderwatt_share_url(url: str) -> dict[str, str] | None:
    """Validate, persist, and return parsed parts (or None)."""
    parsed = parse_wonderwatt_share_url(url)
    s = wonderwatt_settings()
    if parsed is None:
        s.remove(_QS_SHARE)
        s.sync()
        return None
    s.setValue(_QS_SHARE, parsed["share_url"])
    s.sync()
    return parsed


def load_wonderwatt_daily_kwh() -> dict[str, float]:
    """Map ``YYYY-MM-DD`` → forecast kWh from manual paste / prior saves."""
    raw = wonderwatt_settings().value(_QS_DAILY, "")
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    out: dict[str, float] = {}
    if not isinstance(data, dict):
        return out
    for k, v in data.items():
        try:
            out[str(k)[:10]] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def save_wonderwatt_daily_kwh(mapping: dict[str, float]) -> None:
    clean = {}
    for k, v in (mapping or {}).items():
        try:
            clean[str(k)[:10]] = float(v)
        except (TypeError, ValueError):
            continue
    s = wonderwatt_settings()
    s.setValue(_QS_DAILY, json.dumps(clean, sort_keys=True))
    s.sync()


def merge_wonderwatt_daily_paste(text: str) -> dict[str, float]:
    """Parse paste lines into daily kWh and merge with saved map.

    Accepted forms (one entry per line or JSON object):
    * ``2026-09-08 12.5``
    * ``2026-09-08,12.5``
    * ``08/09/2026: 12.5`` (D/M/Y)
    * JSON ``{"2026-09-08": 12.5, ...}``
    """
    existing = load_wonderwatt_daily_kwh()
    text = (text or "").strip()
    if not text:
        return existing
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            for k, v in data.items():
                try:
                    existing[str(k)[:10]] = float(v)
                except (TypeError, ValueError):
                    continue
            save_wonderwatt_daily_kwh(existing)
            return existing

    line_re = re.compile(
        r"(?P<d>\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})"
        r"\s*[,:=\s]\s*"
        r"(?P<kwh>[-+]?\d+(?:\.\d+)?)"
    )
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = line_re.search(line)
        if not m:
            continue
        d_raw = m.group("d")
        try:
            kwh = float(m.group("kwh"))
        except ValueError:
            continue
        key = _normalize_day_key(d_raw)
        if key:
            existing[key] = kwh
    save_wonderwatt_daily_kwh(existing)
    return existing


def _normalize_day_key(raw: str) -> str | None:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def test_wonderwatt_connection(share_url: str | None = None) -> tuple[bool, str]:
    """Hit the share URL and report whether cookies / HTML look accepted."""
    url = (share_url or load_wonderwatt_share_url() or "").strip()
    parsed = parse_wonderwatt_share_url(url)
    if parsed is None:
        return False, "No valid Wonderwatt share URL (need wattid, sig, time)."
    sess = requests.Session()
    sess.headers.update({"User-Agent": _UA, "Accept": "text/html,application/json"})
    try:
        resp = sess.get(parsed["share_url"], timeout=20, allow_redirects=True)
    except requests.RequestException as exc:
        return False, f"Wonderwatt not reachable ({exc})"
    cookies = {c.name: c.value for c in sess.cookies}
    has_watt = cookies.get("wattid") == parsed["wattid"] or "wattid" in cookies
    has_sig = "sig" in cookies
    if resp.status_code >= 400:
        return False, f"HTTP {resp.status_code} from Wonderwatt"
    if not (has_watt and has_sig):
        return (
            False,
            f"HTTP {resp.status_code} but share cookies missing "
            "(link may be expired — regenerate in Wonderwatt Advanced).",
        )
    # Blazor SPA always returns HTML; note that live forecast JSON is not public.
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "json" in ctype:
        return True, f"Connected as wattid={parsed['wattid']} (JSON response)."
    return (
        True,
        f"Share link accepted for wattid={parsed['wattid']} "
        "(Blazor app — use daily paste for forecast kWh until live API is available).",
    )


def fetch_wonderwatt_daily_forecast(
    start_day: date,
    end_day: date,
    *,
    share_url: str | None = None,
) -> dict[str, Any]:
    """Return daily WW forecast kWh for [start_day, end_day].

    Tries a live fetch first (currently unavailable as public JSON); falls back
    to saved/pasted daily map. Result::

        {
          "ok": bool,
          "source": "paste" | "live" | "none",
          "message": str,
          "days": { "YYYY-MM-DD": float_kwh, ... },
        }
    """
    parsed = parse_wonderwatt_share_url(share_url or load_wonderwatt_share_url())
    days: dict[str, float] = {}
    # Future: reverse-engineer Blazor hub and fill `days` from live forecast.
    live_msg = ""
    if parsed is not None:
        ok, live_msg = test_wonderwatt_connection(parsed["share_url"])
        if not ok:
            live_msg = live_msg
        else:
            live_msg = live_msg  # cookies OK; still no JSON curve yet

    pasted = load_wonderwatt_daily_kwh()
    cur = start_day
    while cur <= end_day:
        key = cur.isoformat()
        if key in pasted:
            days[key] = float(pasted[key])
        cur += timedelta(days=1)

    if days:
        return {
            "ok": True,
            "source": "paste",
            "message": (
                f"Using {len(days)} pasted Wonderwatt day(s). {live_msg}"
            ).strip(),
            "days": days,
        }
    if parsed is None:
        return {
            "ok": False,
            "source": "none",
            "message": "No Wonderwatt share URL and no pasted daily kWh.",
            "days": {},
        }
    return {
        "ok": False,
        "source": "none",
        "message": (
            live_msg
            or "Share link OK but no live forecast JSON yet — paste daily kWh below."
        ),
        "days": {},
    }


def connectivity_row() -> tuple[str, str, str, str, str]:
    """Return (state_text, state_key, detail, freshness, size) for Connectivity.

    Wonderwatt has no public upload API — plant live data is pulled by
    Wonderwatt from Growatt cloud. This app uses the share link for forecast
    comparison (Potential Issues) and shows that link's health here.
    """
    url = load_wonderwatt_share_url()
    parsed = parse_wonderwatt_share_url(url)
    pasted = load_wonderwatt_daily_kwh()
    if parsed is None:
        return (
            "Not configured",
            "off",
            "Paste a Wonderwatt Advanced share link under Potential Issues "
            "(or Setup). Live plant data goes Growatt cloud → Wonderwatt.",
            "--",
            "--",
        )
    detail = f"wattid={parsed['wattid']}"
    if pasted:
        detail += f" · {len(pasted)} pasted day(s)"
    # Soft probe would be too slow on every Connectivity refresh — report config only.
    return "Share link set", "ok", detail, "--", "--"


__all__ = [
    "parse_wonderwatt_share_url",
    "load_wonderwatt_share_url",
    "save_wonderwatt_share_url",
    "load_wonderwatt_daily_kwh",
    "save_wonderwatt_daily_kwh",
    "merge_wonderwatt_daily_paste",
    "test_wonderwatt_connection",
    "fetch_wonderwatt_daily_forecast",
    "connectivity_row",
]
