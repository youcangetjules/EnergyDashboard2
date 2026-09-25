"""
Energy Dashboard — `fetch/octopus_gql.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.core.logging import _log
from energy_dashboard.fetch.octopus_rest import octopus_request_error_message
_OCTOPUS_GQL_URL = "https://api.octopus.energy/v1/graphql/"

_GQL_TOKEN_MUTATION = '''mutation {
  obtainKrakenToken(input: { APIKey: "%s" }) {
    token
  }
}'''

_GQL_ACCOUNT_QUERY = '''query {
  account(accountNumber: "%s") {
    electricityAgreements(active: true) {
      meterPoint {
        mpan
        direction
        meters(includeInactive: false) {
          serialNumber
          smartImportElectricityMeter { deviceId }
          smartExportElectricityMeter { deviceId }
        }
      }
    }
  }
}'''

_GQL_TELEMETRY_QUERY = '''query {
  smartMeterTelemetry(
    deviceId: "%s"
    grouping: %s
    start: "%s"
    end: "%s"
  ) {
    readAt
    consumption
    consumptionDelta
    demand
    export
  }
}'''


def _gql_telemetry_interval_kwh(reading, is_export_register):
    """Per-interval kWh for one GraphQL ``smartMeterTelemetry`` row.

    Interval energy is carried in ``consumptionDelta`` (watt-hours → divide by
    1000). The ``consumption`` and ``export`` fields are often **cumulative**
    meter registers; using them as interval kWh produces nonsense totals (billions
    of kWh). We only fall back to absolutes when the value is plausibly a single
    interval (see cap below).
    """
    _ = is_export_register  # delta semantics match on import vs export CAD devices
    try:
        cd = reading.get("consumptionDelta")
        if cd is not None and str(cd).strip() != "":
            return max(0.0, float(cd) / 1000.0)
        # No delta: some payloads omit it — reject obvious cumulative totals.
        _MAX_INTERVAL_KWH = 80.0  # domestic half-hour cap ~40 kWh @ 80 kW; safety margin
        for key in ("consumption", "export"):
            v = reading.get(key)
            if v is None or str(v).strip() == "":
                continue
            fv = float(v)
            if 0.0 <= fv <= _MAX_INTERVAL_KWH:
                return fv
        return 0.0
    except (TypeError, ValueError):
        return 0.0


def _gql_post(query, token=None):
    """POST a GraphQL query to the Octopus Kraken API. Returns parsed JSON body."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"JWT {token}"
    resp = requests.post(_OCTOPUS_GQL_URL, json={"query": query}, headers=headers, timeout=30)
    body = None
    try:
        body = resp.json()
    except ValueError:
        body = None
    if resp.status_code >= 400:
        if isinstance(body, dict) and body.get("errors"):
            raise RuntimeError(body["errors"][0].get("message", str(body["errors"])))
        resp.raise_for_status()
    if not isinstance(body, dict):
        resp.raise_for_status()
        body = resp.json()
    if "errors" in body and body["errors"]:
        raise RuntimeError(body["errors"][0].get("message", str(body["errors"])))
    return body


def octopus_gql_authenticate(api_key):
    """Exchange an Octopus API key for a short-lived JWT token."""
    body = _gql_post(_GQL_TOKEN_MUTATION % api_key)
    data = body.get("data") or {}
    token_data = data.get("obtainKrakenToken")
    if not token_data or not token_data.get("token"):
        raise RuntimeError("API returned no token — check your API key")
    return token_data["token"]


def octopus_gql_discover_devices(token, account_number):
    """Return list of dicts: {mpan, serial, device_id, is_export}."""
    body = _gql_post(_GQL_ACCOUNT_QUERY % account_number, token=token)
    data = body.get("data") or {}
    account = data.get("account")
    if not account:
        raise RuntimeError(f"No account data returned for '{account_number}' — check account number")
    agreements = account.get("electricityAgreements") or []
    if not agreements:
        raise RuntimeError(f"No active electricity agreements on account '{account_number}'")
    devices = []
    for agreement in agreements:
        mp = agreement.get("meterPoint") or {}
        is_export = mp.get("direction") == "EXPORT"
        for m in mp.get("meters") or []:
            smart_imp = m.get("smartImportElectricityMeter")
            smart_exp = m.get("smartExportElectricityMeter")
            smart = smart_imp or smart_exp
            if smart and smart.get("deviceId"):
                devices.append({
                    "mpan": mp.get("mpan", ""),
                    "serial": m.get("serialNumber", ""),
                    "device_id": smart["deviceId"],
                    "is_export": is_export,
                })
    return devices


def fetch_octopus_telemetry(api_key, account_number, hours=24, grouping="HALF_HOURLY"):
    """Fetch granular smart meter telemetry via Octopus GraphQL.

    grouping: HALF_HOURLY | QUARTER_HOURLY | FIVE_MINUTES
    Returns (import_df, export_df, error_or_none).
    Each DataFrame has columns: timestamp, consumption_kwh, demand_w
    """
    import pytz
    london = pytz.timezone("Europe/London")
    api_key = (api_key or "").strip()
    account_number = (account_number or "").strip()
    if not api_key or not account_number:
        return pd.DataFrame(), pd.DataFrame(), "Missing API key or account number"

    try:
        _log.debug("Octopus GQL", f"Authenticating with API key ...{api_key[-6:]}")
        token = octopus_gql_authenticate(api_key)
        _log.info("Octopus GQL", "Authentication successful")
    except requests.exceptions.RequestException as e:
        msg = octopus_request_error_message(e)
        _log.warn("Octopus GQL", msg)
        return pd.DataFrame(), pd.DataFrame(), msg
    except Exception as e:
        _log.warn("Octopus GQL", f"Auth failed: {e}")
        return pd.DataFrame(), pd.DataFrame(), f"Auth failed: {e}"

    try:
        _log.debug("Octopus GQL", f"Discovering devices for account {account_number}")
        devices = octopus_gql_discover_devices(token, account_number)
    except Exception as e:
        _log.warn("Octopus GQL", f"Account query failed: {e}")
        return pd.DataFrame(), pd.DataFrame(), f"Account query failed: {e}"

    if not devices:
        return pd.DataFrame(), pd.DataFrame(), (
            "No smart meter devices found on account — check account number"
        )
    _log.info("Octopus GQL", f"Found {len(devices)} device(s): "
              + ", ".join(f"{d['device_id']} ({'export' if d['is_export'] else 'import'})" for d in devices))

    now_utc = datetime.now(timezone.utc)
    period_from = now_utc - timedelta(hours=hours + 48)
    period_to = now_utc

    import_frames = []
    export_frames = []
    telemetry_errors = []
    for dev in devices:
        query = _GQL_TELEMETRY_QUERY % (
            dev["device_id"], grouping,
            period_from.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            period_to.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        )
        try:
            body = _gql_post(query, token=token)
        except RuntimeError as e:
            err_str = str(e)
            _log.warn("Octopus GQL", f"Telemetry error for {dev['device_id']}: {err_str}")
            telemetry_errors.append(err_str)
            continue
        except Exception as e:
            _log.warn("Octopus GQL", f"Telemetry error for {dev['device_id']}: {e}")
            telemetry_errors.append(str(e))
            continue

        readings = body.get("data", {}).get("smartMeterTelemetry") or []
        _log.debug("Octopus GQL", f"Device {dev['device_id']}: {len(readings)} readings")
        if not readings:
            continue

        rows = []
        for r in readings:
            ts = pd.to_datetime(r["readAt"], utc=True).tz_convert(london)
            cons_kwh = _gql_telemetry_interval_kwh(r, dev["is_export"])
            try:
                demand_raw = r.get("demand")
                demand_w = float(demand_raw) if demand_raw is not None else None
            except (ValueError, TypeError):
                demand_w = None
            rows.append({"interval_start": ts, "consumption": cons_kwh, "demand_w": demand_w})

        df = pd.DataFrame(rows).sort_values("interval_start").reset_index(drop=True)
        if dev["is_export"]:
            export_frames.append(df)
        else:
            import_frames.append(df)

    def _merge_gql_telemetry_frames(frames):
        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, ignore_index=True)
        if out.empty:
            return out
        out = out.sort_values("interval_start").reset_index(drop=True)
        out = (
            out.groupby("interval_start", as_index=False)
            .agg({"consumption": "sum", "demand_w": "last"})
        )
        latest = out["interval_start"].max()
        cutoff = latest - pd.Timedelta(hours=hours)
        out = out[out["interval_start"] >= cutoff].reset_index(drop=True)
        return out

    import_df = _merge_gql_telemetry_frames(import_frames)
    export_df = _merge_gql_telemetry_frames(export_frames)

    if import_df.empty and export_df.empty:
        # No telemetry data — most likely the user has no CAD device
        if telemetry_errors:
            detail = telemetry_errors[0]
            if "HAN" in detail or "4056" in detail:
                return pd.DataFrame(), pd.DataFrame(), (
                    "No CAD/Home Mini paired with your smart meter. "
                    "The smartMeterTelemetry API requires an Octopus Home Mini "
                    "or compatible Consumer Access Device (CAD) for real-time data."
                )
            return pd.DataFrame(), pd.DataFrame(), f"Telemetry query failed: {detail}"
        return pd.DataFrame(), pd.DataFrame(), (
            "No telemetry readings returned. This usually means you don't have "
            "an Octopus Home Mini or CAD device paired with your smart meter. "
            "Real-time demand data requires this hardware."
        )

    return import_df, export_df, None


__all__ = [n for n in globals() if not n.startswith('__')]
