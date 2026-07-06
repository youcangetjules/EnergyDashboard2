"""
Energy Dashboard — `ui/cards.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.config import AppParameters
from energy_dashboard.core.logging import _log
def make_power_card(label_text, unit_text, color, return_unit_label=False):
    """Create a QGroupBox card with a big value label and unit label.

    The value label sits at 48 pt so the live SOC / Battery / PV / Grid /
    Load readings on the Growatt Live Status tab are readable from across
    the room — these are the headline numbers and deserve real estate.
    """
    box = QGroupBox(label_text)
    layout = QVBoxLayout(box)
    layout.setAlignment(Qt.AlignCenter)
    val_label = QLabel("--")
    val_label.setFont(QFont('Helvetica', 48, QFont.Bold))
    val_label.setStyleSheet(f"color: {color};")
    val_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(val_label)
    unit_label = QLabel(unit_text)
    unit_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(unit_label)
    if return_unit_label:
        return box, val_label, unit_label
    return box, val_label


# Live Status grid card: value matches make_power_card (48pt); (exporting)/(importing) is 30pt smaller.
_GRID_LIVE_MAIN_PT = 48
_GRID_LIVE_TAG_PT = 18

# "Device Information" box (Growatt live tab): field names + values.
INFO_DEVICE_SECTION_PT = 18


def _growatt_device_status_font_pt(text):
    """Smaller status font when a long message must wrap in the info column."""
    n = len(str(text or '').strip())
    if n <= 40:
        return INFO_DEVICE_SECTION_PT
    if n <= 80:
        return 14
    if n <= 140:
        return 11
    return 9


# Physical panel (under Device Information): row titles (px stylesheet), values (pt QFont), column headers.
INFO_PHYSICAL_TITLE_PX = 12
INFO_PHYSICAL_HDR_PX = 11
INFO_PHYSICAL_VALUE_PT = 13

# Where to obtain a Growatt Open API token (also valid via ShinePhone: Me → API Token).
_GROWATT_API_TOKEN_SOURCE = (
    'server.growatt.com → Settings → Account Management → API Key'
)
_GROWATT_API_TOKEN_SOURCE_ALT = 'ShinePhone: Me → API Token'
_GROWATT_TRANSIENT_ERROR_TOKENS = (
    'connection closed',
    'connection aborted',
    'connection reset',
    'remote disconnected',
    'temporarily unavailable',
    'timed out',
    'timeout',
    'max retries',
    'newconnectionerror',
    'ssl',
    'bad gateway',
    'service unavailable',
    'gateway timeout',
    '503',
    '504',
)


def _growatt_is_transient_error(exc_or_msg) -> bool:
    """True for Growatt/network failures where retrying is usually safe."""
    msg = str(exc_or_msg or '').lower()
    return any(tok in msg for tok in _GROWATT_TRANSIENT_ERROR_TOKENS)


def _growatt_retry_call(fn, *args, attempts=3, base_delay=0.7, **kwargs):
    """Retry transient Growatt/cloud calls with short backoff."""
    last = None
    for i in range(max(1, int(attempts))):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last = exc
            if i >= attempts - 1 or not _growatt_is_transient_error(exc):
                raise
            _time_mod.sleep(base_delay * (i + 1))
    raise last


def _growatt_first_nonempty(d, keys):
    """Return first present non-empty string value for keys in dict d."""
    if not isinstance(d, dict):
        return ''
    bad = {'null', 'none', '--', ''}
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() not in bad:
            return s
    return ''


_GROWATT_DEVICE_LIST_LOGGED = set()

_INV_MODEL_KEYS = (
    'deviceModule', 'moduleName', 'model', 'deviceTypeName', 'productName',
    'typeName', 'deviceModel', 'factoryName', 'module', 'invModel', 'typeStr',
    'deviceName', 'alias', 'deviceAilas', 'aliasName', 'productType',
    'firmwareVersion', 'softVersion', 'hardwareVersion', 'invType',
)
_BAT_MODEL_KEYS = (
    'batteryModel', 'batTypeName', 'batModel', 'bmsModel', 'deviceModule2',
    'storageModel', 'batteryMode', 'batType', 'storageName', 'packModel',
    'batteryName', 'batName',
)


def _growatt_unwrap_payload(raw):
    """Normalize Growatt JSON blobs (obj / data / nested lists)."""
    if not isinstance(raw, dict):
        return {}
    for key in ('obj', 'data', 'device', 'inverter', 'result'):
        v = raw.get(key)
        if isinstance(v, dict):
            return v
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v[0]
    return raw


def _growatt_walk_find(d, keys, max_depth=4, _depth=0):
    """Depth-first search for the first non-empty value among *keys*."""
    if _depth > max_depth:
        return ''
    if not isinstance(d, dict):
        return ''
    hit = _growatt_first_nonempty(d, keys)
    if hit:
        return hit
    for child in d.values():
        if isinstance(child, dict):
            hit = _growatt_walk_find(child, keys, max_depth, _depth + 1)
            if hit:
                return hit
        elif isinstance(child, list):
            for item in child[:12]:
                if isinstance(item, dict):
                    hit = _growatt_walk_find(item, keys, max_depth, _depth + 1)
                    if hit:
                        return hit
    return ''


_GROWATT_DEVICE_SN_KEYS = (
    'deviceSn', 'device_sn', 'serialNum', 'serial_num', 'sn', 'datalogSn',
)
_GROWATT_PLANT_DEVICE_LIST_KEYS = (
    ('deviceList', None),
    ('invList', 'inverter'),
    ('storageList', 'mix'),
    ('sphList', 'mix'),
    ('batList', 'battery'),
    ('datalogList', 'datalog'),
    ('witList', None),
)


def _growatt_normalize_device_entry(raw, default_type=None):
    """Normalize one Growatt plant_info / device_list record to {deviceSn, deviceType}."""
    if not isinstance(raw, dict):
        return None
    sn = _growatt_first_nonempty(raw, _GROWATT_DEVICE_SN_KEYS)
    if not sn:
        return None
    dt = raw.get('deviceType') or raw.get('type') or raw.get('device_type') or default_type
    out = dict(raw)
    out['deviceSn'] = str(sn)
    if dt is not None:
        out['deviceType'] = dt
    return out


def _growatt_flatten_device_list(devices):
    """device_list may return a list or a dict of category → list entries."""
    if isinstance(devices, list):
        return devices
    if isinstance(devices, dict):
        flat = []
        for value in devices.values():
            if isinstance(value, list):
                flat.extend(value)
            elif isinstance(value, dict):
                flat.append(value)
        return flat
    return []


def _growatt_plant_devices(api, plant_id):
    """Collect devices from device_list and plant_info sub-lists (API shape varies)."""
    try:
        devices = _growatt_flatten_device_list(
            _growatt_retry_call(api.device_list, plant_id, attempts=2)
        )
    except Exception:
        devices = []
    normalized = [
        d for d in (_growatt_normalize_device_entry(x) for x in devices) if d
    ]
    if normalized:
        return normalized
    try:
        raw = _growatt_retry_call(api.plant_info, plant_id, attempts=2)
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []
    merged = []
    for key, default_type in _GROWATT_PLANT_DEVICE_LIST_KEYS:
        chunk = raw.get(key)
        if isinstance(chunk, list):
            for item in chunk:
                nd = _growatt_normalize_device_entry(item, default_type)
                if nd:
                    merged.append(nd)
        elif isinstance(chunk, dict):
            nd = _growatt_normalize_device_entry(chunk, default_type)
            if nd:
                merged.append(nd)
    seen = set()
    out = []
    for item in merged:
        sn = item.get('deviceSn')
        if sn and sn not in seen:
            seen.add(sn)
            out.append(item)
    return out


def _growatt_pick_primary_device(devices):
    """Prefer MIX/SPH hybrid, else first normalized device."""
    for d in devices or []:
        if not isinstance(d, dict):
            continue
        dt = str(d.get('deviceType', '')).lower()
        if dt in ('mix', 'sph') or 'mix' in dt or 'sph' in dt:
            return d
    for d in devices or []:
        if isinstance(d, dict):
            return d
    return None


def _growatt_verify_plant_serial(api, plant_id, serial):
    """When cloud device_list is empty, check whether mix_* APIs accept this SN."""
    sn = (serial or '').strip()
    if not sn:
        return False, None
    for meth in ('mix_system_status', 'mix_info'):
        fn = getattr(api, meth, None)
        if fn is None:
            continue
        try:
            raw = fn(sn, plant_id)
        except Exception:
            continue
        if isinstance(raw, dict) and raw:
            return True, 'mix'
    return False, None


def _growatt_login_error_message(msg):
    """Map Growatt legacy login ``msg`` codes to actionable UI text."""
    code = str(msg or '').strip()
    if code == '507':
        return (
            'Growatt rate limit (507): password logins are temporarily blocked '
            '(often ~24 h after too many API attempts). Stop clicking Connect, wait, '
            'then paste an API token from '
            f'{_GROWATT_API_TOKEN_SOURCE} below. '
            'app.wonderwatt.com is a separate service and still works.'
        )
    if code == '502':
        return 'Invalid Growatt username or password (502).'
    if code.isdigit():
        return f'Growatt login rejected (code {code}). Wait and retry, or use an API token.'
    return f'Growatt login failed: {code or "unknown error"}'


def _growatt_v1_error_message(exc):
    """Turn Growatt Open API V1 failures into actionable dashboard text."""
    if isinstance(exc, AttributeError) and 'mix_system_status' in str(exc):
        return (
            'Growatt cloud session is not connected. '
            'Click Connect after checking your API token or username/password.'
        )
    try:
        from growattServer.exceptions import GrowattV1ApiError
    except ImportError:
        return str(exc)
    if not isinstance(exc, GrowattV1ApiError):
        return str(exc)

    code = exc.error_code
    detail = (exc.error_msg or '').strip()
    op = str(exc).removeprefix('Error during ').strip() or 'Open API call'

    if detail and code is not None:
        msg = f'Growatt {op} failed (code {code}): {detail}'
    elif code is not None:
        msg = f'Growatt {op} failed (code {code})'
    else:
        msg = str(exc)

    if code == 10011 or 'permission' in detail.lower():
        msg += (
            f' Regenerate the token at {_GROWATT_API_TOKEN_SOURCE} '
            f'(or {_GROWATT_API_TOKEN_SOURCE_ALT}) for the same account as your inverter.'
        )
    elif code == 10012 or 'frequently' in detail.lower():
        msg += (
            ' Growatt is rate-limiting API calls (error_frequently_access). '
            'Wait 30–60 minutes, avoid repeated Connect/Test clicks, and rely on '
            'Setup & Info auto-refresh interval rather than hammering the cloud.'
        )
    elif 'plant list' in op.lower():
        msg += (
            f' Check the token from {_GROWATT_API_TOKEN_SOURCE} matches the account '
            'that owns this plant.'
        )
    return msg


def _growatt_open_api_v1_session(token):
    """Return (api, plant_id, plant_name) for OpenApi V1 token auth."""
    from growattServer import OpenApiV1

    api = OpenApiV1(token=(token or '').strip())
    try:
        data = _growatt_retry_call(api.plant_list, attempts=3)
    except Exception as exc:
        raise ValueError(_growatt_v1_error_message(exc)) from exc
    if not isinstance(data, dict):
        raise ValueError(
            f'No plants returned for this API token — generate one at '
            f'{_GROWATT_API_TOKEN_SOURCE}.'
        )
    plants = data.get('plants') or []
    if not plants:
        raise ValueError(
            'API token accepted but no plants found — check the token account at '
            'server.growatt.com matches your inverter.'
        )
    plant = plants[0]
    plant_id = plant.get('plant_id') or plant.get('plantId') or plant.get('id')
    plant_name = (
        plant.get('name') or plant.get('plant_name') or plant.get('plantName') or str(plant_id)
    )
    if plant_id is None:
        raise ValueError('Could not read plant ID from Growatt Open API response.')
    return api, plant_id, plant_name


def _growatt_v1_plant_devices(api, plant_id):
    """Normalize OpenApi V1 device/list entries to legacy {deviceSn, deviceType}."""
    try:
        data = _growatt_retry_call(api.device_list, plant_id, attempts=3)
    except Exception:
        return []
    if isinstance(data, dict):
        devs = data.get('devices') or []
    elif isinstance(data, list):
        devs = data
    else:
        devs = []
    type_map = {5: 'mix', 2: 'storage', 7: 'min', 1: 'inverter', 6: 'spa'}
    out = []
    for raw in devs:
        if not isinstance(raw, dict):
            continue
        sn = raw.get('device_sn') or raw.get('deviceSn')
        if not sn:
            continue
        t = raw.get('type') or raw.get('device_type')
        try:
            dt = type_map.get(int(t), t)
        except (TypeError, ValueError):
            dt = t or 'inverter'
        out.append({'deviceSn': str(sn), 'deviceType': dt, **raw})
    return out


def _growatt_uses_open_api_v1(api) -> bool:
    """True when the session uses Growatt Open API V1 (token auth)."""
    return bool(getattr(api, 'api_url', None))


def _growatt_watts_to_kw(val, *, default=0.0):
    try:
        if val is None or str(val).strip() in ('', '--'):
            return default
        return float(val) / 1000.0
    except (TypeError, ValueError):
        return default


def _growatt_v1_resolve_load_kw(
    c,
    *,
    import_kw: float,
    export_kw: float,
    pv_kw: float,
    charge_kw: float,
    discharge_kw: float,
) -> float:
    """Resolve live house load (kW) from Open API V1 fields or power balance."""
    raw = _growatt_first_nonempty(
        c,
        (
            'pacToLocalLoad', 'pacToLocalLoadTotal', 'PLocalLoad_total',
            'pLocalLoad', 'PLocalLoad', 'plocalLoad',
            'sysOut', 'elocalLoad', 'loadPower', 'load_power',
        ),
    )
    if raw:
        # Open API V1 always reports watts (e.g. plocalLoadTotal=4080, ppvText
        # "1030.0 W"). Do not treat small watt readings as legacy kW — that
        # stored 10–49 W standby load as 10–49 kW in growatt_readings.
        load_kw = _growatt_watts_to_kw(raw)
        if load_kw > 0.001:
            return load_kw
    derived = import_kw - export_kw + pv_kw + discharge_kw - charge_kw
    return max(0.0, derived)


def _growatt_v1_map_mix_bundle(detail, energy):
    """Map Open API V1 sph_detail + sph_energy to legacy mix_* dict shapes."""
    d = detail if isinstance(detail, dict) else {}
    e = energy if isinstance(energy, dict) else {}
    c = {**d, **e}

    import_kw = _growatt_watts_to_kw(
        _growatt_first_nonempty(c, ('pacToUserR', 'pacToUserTotal', 'pactouser')),
    )
    export_kw = _growatt_watts_to_kw(
        _growatt_first_nonempty(c, ('pacToGridTotal', 'pactogrid')),
    )
    charge_kw = _growatt_watts_to_kw(
        _growatt_first_nonempty(c, ('pcharge1', 'bdc1ChargePower', 'chargePower')),
    )
    discharge_kw = _growatt_watts_to_kw(
        _growatt_first_nonempty(c, ('pdischarge1', 'bdc1DischargePower', 'pdisCharge1')),
    )
    pv_kw = _growatt_watts_to_kw(_growatt_first_nonempty(c, ('ppv',)))
    if pv_kw <= 0.001:
        pv_kw = (
            _growatt_watts_to_kw(_growatt_first_nonempty(c, ('ppv1', 'pPv1')))
            + _growatt_watts_to_kw(_growatt_first_nonempty(c, ('ppv2', 'pPv2')))
        )
    load_kw = _growatt_v1_resolve_load_kw(
        c,
        import_kw=import_kw,
        export_kw=export_kw,
        pv_kw=pv_kw,
        charge_kw=charge_kw,
        discharge_kw=discharge_kw,
    )

    status = {
        'SOC': _growatt_first_nonempty(c, ('bmsSOC', 'bdc1Soc', 'SOC')),
        'chargePower': charge_kw,
        'pdisCharge1': discharge_kw,
        'ppv': pv_kw,
        'pactogrid': export_kw,
        'pactouser': import_kw,
        'pLocalLoad': load_kw,
        'vAc1': _growatt_first_nonempty(c, ('vac1', 'vAc1')),
        'vac1': _growatt_first_nonempty(c, ('vac1', 'vAc1')),
        'fAc': _growatt_first_nonempty(c, ('fac', 'fAc')),
        'vBat': _growatt_first_nonempty(c, ('vbat', 'vBat')),
        'vPv1': _growatt_first_nonempty(c, ('vpv1', 'vPv1')),
        'vPv2': _growatt_first_nonempty(c, ('vpv2', 'vPv2')),
        'pPv1': _growatt_first_nonempty(c, ('ppv1', 'pPv1')),
        'pPv2': _growatt_first_nonempty(c, ('ppv2', 'pPv2')),
        'pmax': _growatt_first_nonempty(c, ('pmax',)),
        'lost': _growatt_first_nonempty(c, ('lost', 'statusText')),
        'status': _growatt_first_nonempty(c, ('status', 'lost')),
        'wBatteryType': _growatt_first_nonempty(c, ('wBatteryType', 'batteryType')),
    }
    totals = {
        'epvToday': _growatt_first_nonempty(c, ('epvtoday', 'epvToday')),
        'epvTotal': _growatt_first_nonempty(c, ('epvTotal',)),
        'echargetoday': _growatt_first_nonempty(
            c, ('echarge1Today', 'echargeToday', 'echargetoday'),
        ),
        'edischarge1Today': _growatt_first_nonempty(
            c, ('edischarge1Today', 'edischargeToday', 'edischargetoday'),
        ),
        'elocalLoadToday': _growatt_first_nonempty(c, ('elocalLoadToday',)),
        'etoGridToday': _growatt_first_nonempty(c, ('etoGridToday',)),
    }
    info = dict(c)
    info.setdefault('vbatdsp', _growatt_first_nonempty(c, ('vbatdsp', 'vBatDsp')))
    return status, info, totals


def _growatt_fetch_mix_live(api, device_sn, plant_id):
    """Fetch live MIX/SPH status, info, and today totals (legacy or Open API V1)."""
    if api is None:
        raise ValueError("Growatt cloud session is not connected.")
    if _growatt_uses_open_api_v1(api):
        detail = {}
        energy = {}
        try:
            raw = _growatt_retry_call(api.sph_detail, device_sn, attempts=2)
            if isinstance(raw, dict):
                detail = raw
        except Exception:
            pass
        energy = _growatt_retry_call(api.sph_energy, device_sn, attempts=3)
        if not isinstance(energy, dict):
            raise ValueError('Growatt Open API returned no live energy data for this inverter.')
        return _growatt_v1_map_mix_bundle(detail, energy)

    status = _growatt_retry_call(api.mix_system_status, device_sn, plant_id, attempts=3)
    if not isinstance(status, dict):
        status = {}
    info = {}
    try:
        raw = _growatt_retry_call(api.mix_info, device_sn, plant_id, attempts=2)
        if isinstance(raw, dict):
            info = raw
    except Exception:
        pass
    totals = {}
    try:
        raw = _growatt_retry_call(api.mix_totals, device_sn, plant_id, attempts=2)
        if isinstance(raw, dict):
            totals = raw
    except Exception:
        pass
    return status, info, totals


def _growatt_no_devices_message(plant_name, device_count=None):
    """User-facing text when login succeeds but Growatt cloud lists zero devices."""
    plant = (plant_name or 'your plant').strip() or 'your plant'
    count_hint = ''
    if device_count is not None:
        count_hint = f' Growatt reports deviceCount={device_count}.'
    return (
        f'Login OK — no devices on “{plant}”.{count_hint} '
        'Open the ShinePhone app or server.growatt.com, confirm the WiFi '
        'datalogger / inverter is added to this plant and online, then Connect '
        'again. Optional: enter the inverter serial below if the cloud list '
        'is empty but live reads work.'
    )


def _growatt_log_device_list_once(plant_id, devices, primary_sn):
    """Log raw device_list once per plant to Console (aids new field discovery)."""
    key = str(plant_id) if plant_id is not None else 'unknown'
    if key in _GROWATT_DEVICE_LIST_LOGGED:
        return
    _GROWATT_DEVICE_LIST_LOGGED.add(key)
    import json
    try:
        text = json.dumps(
            {'plant_id': plant_id, 'primary_sn': primary_sn, 'devices': devices},
            default=str,
            indent=2,
        )
        if len(text) > 14000:
            text = text[:14000] + '\n…(truncated — see Growatt cloud device_list)'
        _log.info('Growatt device_list (once per plant)', text)
    except Exception as e:
        _log.warn('Growatt device_list', f'Could not log device_list: {e}')


def _growatt_apply_setup_model_fallbacks(inv, bat, app_params, device_type):
    """When the cloud API is silent, use Setup / device type hints."""
    if inv == '—' and device_type:
        dt = str(device_type).strip()
        if dt and dt.lower() not in ('null', 'none', '--'):
            inv = dt.upper() if len(dt) <= 12 else dt
    if bat == '—' and app_params is not None:
        try:
            cap = float(app_params.battery_capacity_kwh)
            bat = f"{cap:g} kWh (Setup)"
        except (TypeError, ValueError):
            pass
    return inv, bat


def _growatt_inverter_battery_models(devices, primary_sn):
    """
    Best-effort inverter + battery product/model strings from Growatt device_list.
    Shape varies by firmware/server; several key names are tried.
    """
    if not devices:
        return '—', '—'
    primary = None
    for d in devices:
        if not isinstance(d, dict):
            continue
        sn = d.get('deviceSn') or d.get('device_sn')
        if sn is not None and primary_sn is not None and str(sn) == str(primary_sn):
            primary = d
            break
    if primary is None:
        primary = next((d for d in devices if isinstance(d, dict)), {})
    if not primary:
        return '—', '—'

    inv = _growatt_first_nonempty(primary, _INV_MODEL_KEYS)
    if not inv:
        inv = _growatt_walk_find(primary, _INV_MODEL_KEYS)
    bat = ''
    prim_sn = primary.get('deviceSn') or primary.get('device_sn')
    for d in devices:
        if not isinstance(d, dict):
            continue
        d_sn = d.get('deviceSn') or d.get('device_sn')
        if prim_sn is not None and d_sn == prim_sn:
            continue
        dt = d.get('deviceType') or d.get('type') or d.get('device_type')
        sdt = str(dt).lower()
        try:
            is_storage = int(dt) == 2
        except (TypeError, ValueError):
            is_storage = 'stor' in sdt or sdt in ('2', 'bat', 'battery')
        if is_storage:
            bat = _growatt_first_nonempty(d, _BAT_MODEL_KEYS + _INV_MODEL_KEYS)
            if not bat:
                bat = _growatt_walk_find(d, _BAT_MODEL_KEYS)
            if bat:
                break
    if not bat:
        bat = _growatt_first_nonempty(primary, _BAT_MODEL_KEYS)
        if not bat:
            bat = _growatt_walk_find(primary, _BAT_MODEL_KEYS)

    return (inv or '—'), (bat or '—')


def _growatt_enrich_models_inverter_detail(api, sn, inv, bat):
    """Fill missing model strings from inverter_detail when device_list was sparse."""
    if inv != '—' and bat != '—':
        return inv, bat
    try:
        raw = api.inverter_detail(sn)
    except Exception:
        return inv, bat
    if not isinstance(raw, dict):
        return inv, bat
    obj = _growatt_unwrap_payload(raw)
    if inv == '—':
        inv = (
            _growatt_first_nonempty(obj, _INV_MODEL_KEYS)
            or _growatt_walk_find(raw, _INV_MODEL_KEYS)
            or '—'
        )
    if bat == '—':
        bat = (
            _growatt_first_nonempty(obj, _BAT_MODEL_KEYS)
            or _growatt_walk_find(raw, _BAT_MODEL_KEYS)
            or '—'
        )
    return inv, bat


def _growatt_enrich_models_plant_info(api, plant_id, inv, bat):
    if inv != '—' and bat != '—':
        return inv, bat
    try:
        raw = api.plant_info(plant_id)
    except Exception:
        return inv, bat
    if not isinstance(raw, dict):
        return inv, bat
    if inv == '—':
        inv = (
            _growatt_first_nonempty(raw, _INV_MODEL_KEYS)
            or _growatt_walk_find(raw, _INV_MODEL_KEYS)
            or '—'
        )
    if bat == '—':
        bat = (
            _growatt_first_nonempty(raw, _BAT_MODEL_KEYS)
            or _growatt_walk_find(raw, _BAT_MODEL_KEYS)
            or '—'
        )
    devs = raw.get('deviceList') or raw.get('devices')
    if isinstance(devs, list) and (inv == '—' or bat == '—'):
        pi, pb = _growatt_inverter_battery_models(devs, None)
        if inv == '—' and pi != '—':
            inv = pi
        if bat == '—' and pb != '—':
            bat = pb
    return inv, bat


def _growatt_enrich_models_mix_info(mix_info, inv, bat):
    if inv != '—' and bat != '—':
        return inv, bat
    if not isinstance(mix_info, dict):
        return inv, bat
    obj = _growatt_unwrap_payload(mix_info)
    if inv == '—':
        inv = (
            _growatt_first_nonempty(obj, _INV_MODEL_KEYS)
            or _growatt_walk_find(mix_info, _INV_MODEL_KEYS)
            or '—'
        )
    if bat == '—':
        bat = (
            _growatt_first_nonempty(obj, _BAT_MODEL_KEYS)
            or _growatt_walk_find(mix_info, _BAT_MODEL_KEYS)
            or '—'
        )
    return inv, bat


def _growatt_resolve_models(
    api,
    plant_id,
    devices,
    primary_sn,
    app_params=None,
    device_type=None,
    *,
    mix_info=None,
    log_device_list=False,
):
    """Best-effort inverter + battery product strings (cloud + Setup fallbacks)."""
    if log_device_list:
        _growatt_log_device_list_once(plant_id, devices, primary_sn)
    inv, bat = _growatt_inverter_battery_models(devices or [], primary_sn)
    if primary_sn and api is not None:
        if inv == '—' or bat == '—':
            inv, bat = _growatt_enrich_models_inverter_detail(api, primary_sn, inv, bat)
    if plant_id is not None and api is not None and (inv == '—' or bat == '—'):
        inv, bat = _growatt_enrich_models_plant_info(api, plant_id, inv, bat)
    if mix_info is not None and (inv == '—' or bat == '—'):
        inv, bat = _growatt_enrich_models_mix_info(mix_info, inv, bat)
    inv, bat = _growatt_apply_setup_model_fallbacks(inv, bat, app_params, device_type)
    return inv, bat


def _html_grid_power_value(num_str, tag, color_hex):
    """Rich HTML for Grid Power: bold number + optional direction tag in smaller type."""
    fam = "Helvetica, Arial, sans-serif"
    head = (
        f'<span style="font-size: {_GRID_LIVE_MAIN_PT}pt; color: {color_hex}; '
        f"font-weight: 700; font-family: {fam};\">{num_str}</span>"
    )
    if not tag:
        return head
    return (
        head
        + f' <span style="font-size: {_GRID_LIVE_TAG_PT}pt; color: {color_hex}; '
        f"font-weight: 700; font-family: {fam};\">{tag}</span>"
    )


def make_small_card(label_text, unit_text, color, return_unit_label=False):
    """Compact metric card: value and unit share a single line.

    The bold coloured value is right-aligned, the muted unit is bottom-left
    aligned so its baseline tucks just under the value's baseline.  Halves
    the card's vertical footprint vs the previous stacked layout.

    If `return_unit_label=True`, returns (box, val_label, unit_label) so the
    caller can mutate the unit text at runtime (e.g. to add a staleness tag).
    """
    box = QGroupBox(label_text)
    layout = QHBoxLayout(box)
    layout.setContentsMargins(8, 2, 8, 4)
    layout.setSpacing(4)
    layout.setAlignment(Qt.AlignCenter)
    val_label = QLabel("--")
    val_label.setFont(QFont('Helvetica', 18, QFont.Bold))
    val_label.setStyleSheet(f"color: {color};")
    val_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
    layout.addWidget(val_label)
    unit_label = QLabel(unit_text)
    unit_label.setStyleSheet("color: #6c7086; font-size: 11px;")
    unit_label.setAlignment(Qt.AlignBottom | Qt.AlignLeft)
    unit_label.setContentsMargins(0, 0, 0, 4)
    layout.addWidget(unit_label)
    if return_unit_label:
        return box, val_label, unit_label
    return box, val_label


# ==================== GROWATT TAB ====================

def _growatt_physical_str(val):
    """Format a raw API field for the physical-info panel; never raises."""
    if val is None:
        return "—"
    s = str(val).strip()
    return s if s else "—"


def _growatt_inverter_comms_lost(status) -> tuple[bool, str]:
    """True when Growatt cloud reports the inverter is not talking (e.g. mix.status.lost)."""
    if not isinstance(status, dict):
        return False, ""
    raw = status.get("lost") or status.get("status") or ""
    reason = _growatt_physical_str(raw)
    if reason == "—":
        return False, ""
    low = reason.lower()
    if any(tok in low for tok in ("lost", "offline", "disconnect", "no signal", "fault")):
        return True, reason
    return False, reason


def _growatt_sanitize_api_label(val):
    """Strip control chars and odd whitespace from Growatt string fields."""
    if val is None:
        return ""
    if isinstance(val, (bytes, bytearray)):
        try:
            val = val.decode("utf-8", "replace")
        except Exception:
            val = str(val)
    s = str(val).strip()
    if not s:
        return ""
    out = []
    for ch in s:
        o = ord(ch)
        if ch in "\t\n\r":
            out.append(" ")
        elif o < 32 or o == 0x7F:
            continue
        else:
            out.append(ch)
    return " ".join("".join(out).split())


def _growatt_battery_chemistry_display(status, info):
    """Return (one_line_plain_text, tooltip) for MIX ``wBatteryType`` / labels.

    Some firmwares return non-numeric strings or strings with embedded
    control codes; concatenating a long legend on the same QLabel line
    caused cramped/overlapping glyphs in the physical panel.
    """
    raw = None
    if isinstance(status, dict):
        raw = status.get("wBatteryType")
    if (raw is None or (isinstance(raw, str) and not str(raw).strip())) and isinstance(info, dict):
        raw = info.get("wBatteryType")
    if raw is None:
        return "—", ""

    clean = _growatt_sanitize_api_label(raw)
    tip = f"Raw wBatteryType (from Growatt API): {raw!r}"
    if not clean:
        return "—", tip

    try:
        n = int(float(clean))
    except (TypeError, ValueError):
        disp = clean if len(clean) <= 48 else (clean[:47] + "…")
        tip = f"{tip}\n\nShown truncated in the cell; full string above."
        return disp, tip

    hints = {
        0: "lead-acid / generic (code 0)",
        1: "Li-ion or LFP pack (code 1, typical MIX)",
        2: "lithium variant (code 2)",
        3: "lithium variant (code 3)",
    }
    line = f"Code {n} - {hints.get(n, 'unknown code; ask installer')}"
    return line, tip


__all__ = [n for n in globals() if not n.startswith('__')]
