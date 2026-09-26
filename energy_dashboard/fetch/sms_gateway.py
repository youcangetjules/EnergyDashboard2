"""
Send a short text through an SMS gateway.

Two kinds of gateway:

* HTTP — POST JSON ``{"to", "message"}`` to a URL you provide. If a token
  is set it is sent as ``Authorization: Bearer …``.
* Twilio — the standard Messages API. Needs an account SID, a from number,
  and the auth token.

The token is ``SMS_GATEWAY_TOKEN`` in the environment or secrets file when
the SMS gateway page leaves the token box blank. The Twilio account SID falls back to
``SMS_TWILIO_SID`` the same way. Nothing here is written into git.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from energy_dashboard.secrets import secret

_MAX_CHARS = 320


@dataclass(frozen=True)
class SmsConfig:
    enabled: bool
    provider: str
    to_number: str
    url: str
    from_number: str
    account_sid: str
    token: str


def load_sms_config(settings=None) -> SmsConfig:
    """Read the gateway from the SMS gateway page, then fill a blank token or SID from secrets."""
    if settings is None:
        from PySide6.QtCore import QSettings
        settings = QSettings("PowerModel", "EnergyDashboard2")
    provider = str(settings.value("alarms/sms_provider", "http") or "http").strip().lower()
    if provider not in ("http", "twilio"):
        provider = "http"
    token = str(settings.value("alarms/sms_token", "") or "").strip()
    if not token:
        token = secret("SMS_GATEWAY_TOKEN", "").strip()
    sid = str(settings.value("alarms/sms_sid", "") or "").strip()
    if not sid:
        sid = secret("SMS_TWILIO_SID", "").strip()
    enabled = settings.value("alarms/sms_enabled", False, type=bool)
    return SmsConfig(
        enabled=bool(enabled),
        provider=provider,
        to_number=str(settings.value("alarms/sms_to", "") or "").strip(),
        url=str(settings.value("alarms/sms_url", "") or "").strip(),
        from_number=str(settings.value("alarms/sms_from", "") or "").strip(),
        account_sid=sid,
        token=token,
    )


def send_sms(config: SmsConfig, message: str, *, force: bool = False, timeout: float = 12.0) -> tuple[bool, str]:
    """Send one text. ``force`` is for Test SMS, which ignores the tick box."""
    if not force and not config.enabled:
        return False, "SMS is switched off"
    to = _clean_number(config.to_number)
    if not to:
        return False, "Enter the mobile number in international form, such as +447700900123"
    text = " ".join(str(message or "").split())
    if not text:
        return False, "Nothing to send"
    if len(text) > _MAX_CHARS:
        text = text[: _MAX_CHARS - 1].rstrip() + "…"
    if config.provider == "twilio":
        return _send_twilio(config, to, text, timeout)
    return _send_http(config, to, text, timeout)


def _clean_number(raw: str) -> str:
    number = "".join(str(raw or "").split())
    if number.startswith("00"):
        number = "+" + number[2:]
    if not number.startswith("+") or len(number) < 8:
        return ""
    digits = number[1:]
    if not digits.isdigit() or len(digits) > 15:
        return ""
    return number


def _send_http(config: SmsConfig, to: str, text: str, timeout: float) -> tuple[bool, str]:
    url = config.url.strip()
    if not url.startswith(("https://", "http://")):
        return False, "The HTTP gateway needs a full address, starting with https://"
    body = json.dumps({"to": to, "message": text}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"
    return _open(url, body, headers, timeout, auth=None)


def _send_twilio(config: SmsConfig, to: str, text: str, timeout: float) -> tuple[bool, str]:
    sid = config.account_sid.strip()
    token = config.token.strip()
    sender = _clean_number(config.from_number)
    if not sid or not token:
        return False, "Twilio needs an account SID and an auth token"
    if not sender:
        return False, "Twilio needs the From number in international form"
    url = (
        "https://api.twilio.com/2010-04-01/Accounts/"
        + urllib.parse.quote(sid, safe="")
        + "/Messages.json"
    )
    body = urllib.parse.urlencode({"To": to, "From": sender, "Body": text}).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    return _open(url, body, headers, timeout, auth=(sid, token))


def _open(url: str, body: bytes, headers: dict, timeout: float, auth: tuple[str, str] | None) -> tuple[bool, str]:
    if auth:
        import base64
        user, password = auth
        raw = f"{user}:{password}".encode("utf-8")
        headers = dict(headers)
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = int(getattr(response, "status", 0) or response.getcode() or 0)
            snippet = response.read(240).decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError as exc:
        snippet = ""
        try:
            snippet = exc.read(240).decode("utf-8", errors="replace").strip()
        except Exception:
            snippet = ""
        detail = f"the gateway answered {exc.code}"
        if snippet:
            detail += f": {snippet}"
        return False, detail
    except Exception as exc:
        return False, str(exc).splitlines()[0][:180] or exc.__class__.__name__
    if 200 <= code < 300:
        return True, "sent"
    detail = f"the gateway answered {code}"
    if snippet:
        detail += f": {snippet}"
    return False, detail


__all__ = ["SmsConfig", "load_sms_config", "send_sms"]
