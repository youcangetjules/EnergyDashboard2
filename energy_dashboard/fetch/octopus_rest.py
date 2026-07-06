"""
Energy Dashboard — `fetch/octopus_rest.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.core.logging import _log


def octopus_request_error_message(exc: BaseException) -> str:
    """Short, actionable text for Octopus HTTP failures."""
    if isinstance(exc, requests.exceptions.Timeout):
        return "Network: api.octopus.energy request timed out"
    if isinstance(exc, requests.exceptions.ConnectionError):
        text = str(getattr(exc, "__cause__", None) or exc)
        if "Failed to resolve" in text or "Name or service not known" in text:
            return (
                "Network/DNS: cannot resolve api.octopus.energy "
                "(check internet and DNS — not an API key problem)"
            )
        if "Network is unreachable" in text:
            return "Network: no route to api.octopus.energy"
        return f"Network: cannot reach api.octopus.energy ({text})"
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            body = resp.json()
            if isinstance(body, dict) and body.get("detail") is not None:
                return str(body["detail"])
        except Exception:
            raw = (resp.text or "").strip()
            if raw:
                return f"HTTP {resp.status_code}: {raw[:300]}"
    return str(exc)


def get_meter_data(api_key, mpan, serial, start_dt, end_dt):
    api_key = (api_key or "").strip()
    mpan = (mpan or "").strip()
    serial = (serial or "").strip()
    if not api_key or not mpan or not serial:
        return pd.DataFrame()
    url = f"https://api.octopus.energy/v1/electricity-meter-points/{mpan}/meters/{serial}/consumption/"
    auth_str = f"{api_key}:"
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {"Authorization": f"Basic {b64_auth}"}
    params = {
        "period_from": start_dt.strftime("%Y-%m-%dT00:00:00Z"),
        "period_to": end_dt.strftime("%Y-%m-%dT23:59:59Z"),
        "page_size": 25000, "order_by": "period"
    }
    all_results = []
    while url:
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            all_results.extend(data.get('results', []))
            url = data.get('next')
            params = None
        except requests.exceptions.RequestException as e:
            _log.warn("Octopus REST", octopus_request_error_message(e))
            return pd.DataFrame()
    if not all_results:
        return pd.DataFrame()
    df = pd.DataFrame(all_results)
    df['interval_start'] = pd.to_datetime(df['interval_start'], utc=True)
    df['consumption'] = pd.to_numeric(df['consumption'])
    return df[['interval_start', 'consumption']]


def fetch_agile_standard_unit_rates(product_code, tariff_code, days_back=1):
    """Half-hourly unit rates (p/kWh inc. VAT) for one Octopus electricity tariff code (import or outgoing)."""
    import pytz
    london = pytz.timezone('Europe/London')
    now_london = datetime.now(london)
    days_back = max(1, int(days_back))
    period_from = (now_london - timedelta(days=days_back)).replace(hour=0, minute=0, second=0)
    period_to = (now_london + timedelta(days=2)).replace(hour=0, minute=0, second=0)
    product_code = (product_code or "").strip()
    tariff_code = (tariff_code or "").strip()
    if not tariff_code:
        return pd.DataFrame()
    m = re.match(r"^[EG]-1R-(.+)-[A-Z]$", tariff_code)
    derived_product = m.group(1) if m else ""
    if derived_product and derived_product != product_code:
        _log.info("Agile", f"Using product {derived_product} derived from tariff {tariff_code}")
        product_code = derived_product
    if not product_code:
        _log.warn("Agile", f"Could not determine product code for tariff {tariff_code}")
        return pd.DataFrame()
    def _latest_outgoing_tariff_code(current_tariff):
        try:
            resp = requests.get("https://api.octopus.energy/v1/products/?page_size=1000", timeout=30)
            resp.raise_for_status()
            items = resp.json().get('results', [])
            outgoing = [x.get('code', '') for x in items if 'AGILE-OUTGOING' in x.get('code', '').upper()]
            if not outgoing:
                return None, None
            # Prefer the latest code lexically/date-wise; current API exposes one.
            latest_product = sorted(outgoing)[-1]
            region = current_tariff.rsplit('-', 1)[-1] if '-' in current_tariff else 'H'
            latest_tariff = f"E-1R-{latest_product}-{region}"
            return latest_product, latest_tariff
        except Exception as e:
            _log.warn("Agile", f"Could not resolve latest Agile outgoing tariff: {octopus_request_error_message(e)}")
            return None, None

    def _fetch_url(prod, tariff):
        url = f"https://api.octopus.energy/v1/products/{prod}/electricity-tariffs/{tariff}/standard-unit-rates/"
        params = {"period_from": period_from.isoformat(), "period_to": period_to.isoformat(), "page_size": 25000}
        rows = []
        max_pages = 80
        pages = 0
        while url and pages < max_pages:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            rows.extend(data.get('results', []))
            url = data.get('next')
            params = None
            pages += 1
        if url:
            _log.warn("Agile", f"standard-unit-rates pagination stopped at {max_pages} pages (still more 'next')")
        return rows

    all_results = []
    try:
        all_results = _fetch_url(product_code, tariff_code)
    except requests.exceptions.RequestException as e:
        retried = False
        if 'AGILE-OUTGOING' in tariff_code.upper():
            latest_product, latest_tariff = _latest_outgoing_tariff_code(tariff_code)
            if latest_product and latest_tariff and (latest_product != product_code or latest_tariff != tariff_code):
                _log.info("Agile", f"Retrying outgoing tariff with current code {latest_tariff}")
                try:
                    all_results = _fetch_url(latest_product, latest_tariff)
                    retried = True
                except requests.exceptions.RequestException as e2:
                    _log.warn("Agile", f"Error fetching tariff {latest_tariff}: {octopus_request_error_message(e2)}")
        if not retried and not all_results:
            _log.warn("Agile", f"Error fetching tariff {tariff_code}: {octopus_request_error_message(e)}")
    if not all_results:
        return pd.DataFrame()
    df = pd.DataFrame(all_results)
    df['valid_from'] = pd.to_datetime(df['valid_from'], utc=True).dt.tz_convert('Europe/London')
    df['valid_to'] = pd.to_datetime(df['valid_to'], utc=True).dt.tz_convert('Europe/London')
    df['price_pence'] = df['value_inc_vat']
    df = df[['valid_from', 'valid_to', 'price_pence']].sort_values('valid_from').reset_index(drop=True)
    return df


def fetch_agile_prices(product_code, tariff_code, days_back=1):
    """Import Agile rates (same product/tariff as household import)."""
    return fetch_agile_standard_unit_rates(product_code, tariff_code, days_back=days_back)


def fetch_agile_rates_series_utc(product_code, tariff_code, utc_start, utc_end):
    """Half-hourly standard unit rates for a UTC window (for historic cost vs meter data).

    Returns Series indexed by ``valid_from`` (UTC), values p/kWh inc. VAT.
    Empty series if the tariff request fails or returns no rows.
    """
    tariff_code = (tariff_code or "").strip()
    product_code = (product_code or "").strip()
    if not tariff_code:
        return pd.Series(dtype=float)
    m = re.match(r"^[EG]-1R-(.+)-[A-Z]$", tariff_code)
    derived = m.group(1) if m else ""
    if derived:
        if product_code and derived != product_code:
            _log.info("Agile", f"Using product {derived} derived from tariff {tariff_code}")
        product_code = derived
    if not product_code:
        _log.warn("Agile", f"Could not determine product code for tariff {tariff_code}")
        return pd.Series(dtype=float)
    ts0 = pd.Timestamp(utc_start)
    ts1 = pd.Timestamp(utc_end)
    if ts0.tz is None:
        ts0 = ts0.tz_localize("UTC")
    if ts1.tz is None:
        ts1 = ts1.tz_localize("UTC")
    pf = ts0.strftime("%Y-%m-%dT%H:%M:%SZ")
    pt = ts1.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _paginate(prod, tar):
        url = (
            f"https://api.octopus.energy/v1/products/{prod}/electricity-tariffs/"
            f"{tar}/standard-unit-rates/"
        )
        params = {"period_from": pf, "period_to": pt, "page_size": 25000}
        rows = []
        pages = 0
        while url and pages < 80:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            rows.extend(data.get("results", []))
            url = data.get("next")
            params = None
            pages += 1
        if url:
            _log.warn("Agile", "standard-unit-rates pagination cap (historic window)")
        return rows

    rows = []
    try:
        rows = _paginate(product_code, tariff_code)
    except requests.exceptions.RequestException as e:
        retried = False
        if "AGILE-OUTGOING" in tariff_code.upper():
            try:
                resp = requests.get(
                    "https://api.octopus.energy/v1/products/?page_size=1000", timeout=30
                )
                resp.raise_for_status()
                items = resp.json().get("results", [])
                outgoing = [
                    x.get("code", "")
                    for x in items
                    if "AGILE-OUTGOING" in x.get("code", "").upper()
                ]
                if outgoing:
                    latest_product = sorted(outgoing)[-1]
                    region = tariff_code.rsplit("-", 1)[-1] if "-" in tariff_code else "H"
                    latest_tariff = f"E-1R-{latest_product}-{region}"
                    if latest_product != product_code or latest_tariff != tariff_code:
                        _log.info("Agile", f"Retry outgoing with current code {latest_tariff}")
                        rows = _paginate(latest_product, latest_tariff)
                        retried = True
            except requests.exceptions.RequestException as e2:
                _log.warn("Agile", f"Outgoing retry failed: {e2}")
        if not retried and not rows:
            _log.warn("Agile", f"Error fetching {tariff_code}: {e}")
    if not rows:
        return pd.Series(dtype=float)
    ap = pd.DataFrame(rows)
    ap["valid_from"] = pd.to_datetime(ap["valid_from"], utc=True)
    ap = ap.sort_values("valid_from").drop_duplicates("valid_from", keep="first")
    return ap.set_index("valid_from")["value_inc_vat"].astype(float)


_OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Inverter + mismatch / wiring — keeps Open-Meteo backup in the same ballpark as nameplate kWp.
_OPEN_METEO_SOLAR_PR = 0.86


def _fetch_solar_forecast_forecast_solar(lat, lon, declination, azimuth, kwp):
    """Primary: Forecast.Solar published watt curve for the plant."""
    url = f"https://api.forecast.solar/estimate/{lat}/{lon}/{declination}/{azimuth}/{kwp}"
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 429:
            return pd.DataFrame(), "Rate limited — try again later"
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        return pd.DataFrame(), f"Error: {e}"
    watts = data.get('result', {}).get('watts', {})
    if not watts:
        return pd.DataFrame(), "No forecast data returned"
    records = [{'timestamp': pd.to_datetime(ts_str), 'watts': w} for ts_str, w in watts.items()]
    df = pd.DataFrame(records)
    df['kW'] = df['watts'] / 1000.0
    df = df.sort_values('timestamp').reset_index(drop=True)
    ratelimit = data.get('message', {}).get('ratelimit', {})
    remaining = ratelimit.get('remaining', '?')
    return df, f"Solar API: {remaining}/12 calls remaining this hour"


def _fetch_solar_forecast_open_meteo(lat, lon, declination, azimuth, kwp):
    """Backup: Open-Meteo hourly tilted-plane irradiance → kW via nameplate × PR.

    Azimuth convention matches Forecast.Solar / typical PV: 0° = south (NH),
    negative = east, positive = west — same as Open-Meteo's forecast API."""
    try:
        lat_f = float(str(lat).strip())
        lon_f = float(str(lon).strip())
        tilt = float(str(declination).strip())
        azim = float(str(azimuth).strip())
        kwp_f = float(str(kwp).strip())
    except (ValueError, TypeError, AttributeError):
        return pd.DataFrame(), "invalid lat/lon/tilt/azimuth/kWp"
    if kwp_f <= 0:
        return pd.DataFrame(), "kWp must be positive"

    params = {
        "latitude": lat_f,
        "longitude": lon_f,
        "hourly": "global_tilted_irradiance",
        "forecast_days": 16,
        "timezone": "GMT",
        "tilt": tilt,
        "azimuth": azim,
    }
    try:
        response = requests.get(_OPEN_METEO_FORECAST_URL, params=params, timeout=45)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        return pd.DataFrame(), str(e)

    if isinstance(data, dict) and data.get("error"):
        return pd.DataFrame(), str(data.get("reason") or data.get("error"))

    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    gti = hourly.get("global_tilted_irradiance")
    if not times or gti is None or len(gti) != len(times):
        return pd.DataFrame(), "no hourly global_tilted_irradiance"

    pr = _OPEN_METEO_SOLAR_PR
    records = []
    for t_str, g in zip(times, gti):
        try:
            gv = max(0.0, float(g)) if g is not None else 0.0
        except (TypeError, ValueError):
            gv = 0.0
        kw_ac = (gv / 1000.0) * kwp_f * pr
        w_ac = kw_ac * 1000.0
        ts = pd.to_datetime(t_str, utc=True)
        records.append({"timestamp": ts, "watts": w_ac, "kW": kw_ac})

    if not records:
        return pd.DataFrame(), "empty Open-Meteo series"

    df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
    msg = (
        f"Backup (Open-Meteo): tilted irradiance × {kwp_f:g} kWp "
        f"(PR {pr:g}); hourly — see open-meteo.com"
    )
    return df, msg


def fetch_solar_forecast(lat, lon, declination, azimuth, kwp):
    """Forecast.Solar first; on failure or empty data, Open-Meteo tilted irradiance backup."""
    df, primary_msg = _fetch_solar_forecast_forecast_solar(
        lat, lon, declination, azimuth, kwp)
    if df is not None and not df.empty:
        return df, primary_msg

    df_b, backup_msg = _fetch_solar_forecast_open_meteo(
        lat, lon, declination, azimuth, kwp)
    if df_b is not None and not df_b.empty:
        pri = (primary_msg or "").replace("\n", " ").strip()
        if len(pri) > 140:
            pri = pri[:137] + "…"
        suffix = f" — primary failed: {pri}" if pri else ""
        return df_b, backup_msg + suffix

    parts = []
    if primary_msg:
        parts.append(f"Forecast.Solar: {primary_msg}")
    if backup_msg:
        parts.append(f"Open-Meteo: {backup_msg}")
    return pd.DataFrame(), " | ".join(parts) if parts else "No solar forecast data"


def poll_tasmota_device(ip, timeout=3):
    url = f"http://{ip}/cm?cmnd=Status%208"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException:
        return None
    sns = data.get('StatusSNS', {})
    energy = sns.get('ENERGY', {})
    if not energy:
        return None
    relay_on = None
    try:
        r2 = requests.get(f"http://{ip}/cm?cmnd=Power", timeout=timeout)
        r2.raise_for_status()
        j2 = r2.json()
        pwr = j2.get('POWER')
        if isinstance(pwr, str):
            relay_on = pwr.strip().upper() in ('ON', 'TRUE', '1')
        elif isinstance(pwr, bool):
            relay_on = pwr
        elif isinstance(pwr, (int, float)):
            relay_on = pwr != 0
    except requests.exceptions.RequestException:
        pass
    return {
        'ip': ip, 'power_W': energy.get('Power', 0), 'voltage_V': energy.get('Voltage', 0),
        'current_A': energy.get('Current', 0), 'factor': energy.get('Factor', 0),
        'today_kWh': energy.get('Today', 0), 'yesterday_kWh': energy.get('Yesterday', 0),
        'total_kWh': energy.get('Total', 0),
        'relay_on': relay_on,
    }


def poll_tasmota_device_meta(ip, timeout=3):
    """Friendly name and firmware string from Tasmota ``Status 0`` (``StatusFWR``)."""
    url = f"http://{ip}/cm?cmnd=Status%200"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException:
        return ip, "—"
    status = data.get('Status', {}) or {}
    name = status.get('DeviceName', '') or status.get('FriendlyName', [''])[0]
    if not name:
        name = ip
    fw = ""
    statusfwr = data.get('StatusFWR') or {}
    if isinstance(statusfwr, dict):
        fw = (
            statusfwr.get('Version')
            or statusfwr.get('BuildVersion')
            or statusfwr.get('Core')
            or ""
        )
    if not fw:
        sts = data.get('StatusSTS') or {}
        if isinstance(sts, dict):
            fw = sts.get('BuildVersion') or sts.get('Version') or ""
    fw = str(fw).strip() if fw else "—"
    return name, fw


def poll_tasmota_device_name(ip, timeout=3):
    name, _fw = poll_tasmota_device_meta(ip, timeout=timeout)
    return name


def tasmota_send_cmnd(ip, cmnd, timeout=3):
    """GET ``http://ip/cm?cmnd=...`` for a Tasmota command string (e.g. ``Power Toggle``)."""
    from urllib.parse import quote
    url = f"http://{ip}/cm?cmnd={quote(str(cmnd))}"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException:
        return None


def ip_range(start, end):
    prefix = start.rsplit('.', 1)[0]
    s = int(start.rsplit('.', 1)[1])
    e = int(end.rsplit('.', 1)[1])
    return [f"{prefix}.{i}" for i in range(s, e + 1)]


def fetch_octopus_recent(api_key, mpan, serial, hours=24):
    """Half-hourly consumption for the last `hours` (UTC window). Returns (DataFrame, error_or_none).

    Octopus smart-meter data typically lags 24-48 h behind real time, so the
    actual request window is widened by 48 h to capture whatever is available.
    The returned DataFrame is then trimmed to the most recent `hours` of *data*.
    """
    api_key = (api_key or "").strip()
    mpan = (mpan or "").strip()
    serial = (serial or "").strip()
    if not api_key or not mpan or not serial:
        return pd.DataFrame(), "Missing API key, MPAN, or serial"
    try:
        h = int(hours)
    except (TypeError, ValueError):
        h = 24
    if h < 1:
        h = 24
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    period_to = now_utc
    period_from = period_to - timedelta(hours=h + 48)

    def _fmt_utc_z(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    url = f"https://api.octopus.energy/v1/electricity-meter-points/{mpan}/meters/{serial}/consumption/"
    auth_str = f"{api_key}:"
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {"Authorization": f"Basic {b64_auth}"}
    params = {
        "period_from": _fmt_utc_z(period_from),
        "period_to": _fmt_utc_z(period_to),
        "page_size": 25000,
        "order_by": "period",
    }
    all_results = []
    while url:
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            all_results.extend(data.get('results', []))
            url = data.get('next')
            params = None
        except requests.exceptions.RequestException as e:
            msg = octopus_request_error_message(e)
            resp = getattr(e, "response", None)
            if resp is not None:
                try:
                    body = resp.json()
                    if isinstance(body, dict) and body.get("detail") is not None:
                        msg = str(body["detail"])
                except Exception:
                    raw = (resp.text or "").strip()
                    if raw:
                        msg = f"HTTP {resp.status_code}: {raw[:300]}"
            _log.warn("Octopus REST", f"Error fetching recent data: {msg}")
            return pd.DataFrame(), msg
    if not all_results:
        return pd.DataFrame(), "No readings returned (meter data may lag 24-48 h)"
    df = pd.DataFrame(all_results)
    if "interval_start" not in df.columns or "consumption" not in df.columns:
        return pd.DataFrame(), "Unexpected API response (missing interval_start or consumption)"
    df["interval_start"] = pd.to_datetime(df["interval_start"], utc=True).dt.tz_convert("Europe/London")
    if "interval_end" in df.columns:
        df["interval_end"] = pd.to_datetime(df["interval_end"], utc=True).dt.tz_convert("Europe/London")
    df["consumption"] = pd.to_numeric(df["consumption"], errors="coerce")
    df = df.dropna(subset=["interval_start", "consumption"])
    cols = ["interval_start", "consumption"]
    if "interval_end" in df.columns:
        cols.insert(1, "interval_end")
    df = df[cols].sort_values("interval_start").reset_index(drop=True)
    if not df.empty:
        latest = df["interval_start"].max()
        cutoff = latest - pd.Timedelta(hours=h)
        df = df[df["interval_start"] >= cutoff].reset_index(drop=True)
    return df, None


__all__ = [n for n in globals() if not n.startswith('__')]
