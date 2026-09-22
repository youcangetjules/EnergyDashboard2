"""
Energy Dashboard — `ui/cards.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.config import AppParameters
from energy_dashboard.core.logging import _log

# Serialise Growatt Modbus TCP probes — USR/Waveshare gateways often drop or
# hang when Setup Test, Connectivity, and Probe packs open sockets together.
_GROWATT_MODBUS_TCP_LOCK = threading.Lock()
_GROWATT_MODBUS_TCP_LOCK_TIMEOUT_S = 12.0


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


_GROWATT_GRID_IMPORT_TODAY_KEYS = (
    "etouser",
    "eToUser",
    "eToUserToday",
    "Etouser_today",
    "efromGridToday",
    "eFromGridToday",
    "import_from_grid_energy_today",
    "import_from_grid_today",
    "importFromGridToday",
    "etousertoday",
    "efromgridtoday",
)


def _growatt_grid_import_today_kwh(totals):
    """Daily grid import energy (kWh) from mix_totals / Grott / Open API V1."""
    if not isinstance(totals, dict):
        return None
    raw = _growatt_first_nonempty(totals, _GROWATT_GRID_IMPORT_TODAY_KEYS)
    if not raw:
        return None
    try:
        return float(str(raw).replace("kWh", "").strip())
    except (TypeError, ValueError):
        return None


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
        'pPv1': _growatt_watts_to_kw(_growatt_first_nonempty(c, ('ppv1', 'pPv1'))),
        'pPv2': _growatt_watts_to_kw(_growatt_first_nonempty(c, ('ppv2', 'pPv2'))),
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
        'etouser': _growatt_first_nonempty(c, _GROWATT_GRID_IMPORT_TODAY_KEYS),
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


# Growatt GBLI6532-class module energy (nominal); Analytics uses the same unit.
_GROWATT_BATTERY_UNIT_KWH = 6.5
_GROWATT_BATTERY_UNIT_AH = 128.0  # GBLI6532 nominal Ah (usable ~118)
_QS_BAT_MODULES_OVERRIDE = "growatt/battery_modules_override"


def _kwh_from_rated_bat_capacity(val) -> float | None:
    """Interpret Grott/cloud RatedBatCapacity as nominal kWh, or None.

    Growatt publishes this as kWh, 0.1 kWh ticks, or amp-hours depending on
    firmware. Match whole GBLI-class modules (6.5 kWh / 128 Ah) first.
    """
    v = _growatt_as_float(val)
    if v is None or v <= 0:
        return None
    unit = _GROWATT_BATTERY_UNIT_KWH
    ah = _GROWATT_BATTERY_UNIT_AH
    for n in range(1, 9):
        if abs(v - n * unit) < 0.35:
            return float(n * unit)
        if abs(v - n * unit * 10.0) < 2.0:
            return float(n * unit)
        if abs(v - n * ah) < 4.0:
            return float(n * unit)
    if 1.0 <= v <= 50.0:
        return float(v)
    return None


def _growatt_as_float(val):
    if val is None:
        return None
    try:
        text = str(val).strip().rstrip('%')
        if not text or text.lower() in ('--', '—', 'none', 'null', ''):
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _growatt_battery_modules_override() -> int | None:
    """Manual module count from QSettings (None = auto)."""
    try:
        from energy_dashboard.deps import QSettings
        s = QSettings("PowerModel", "EnergyDashboard2")
        if not s.contains(_QS_BAT_MODULES_OVERRIDE):
            return None
        n = int(float(s.value(_QS_BAT_MODULES_OVERRIDE, 0)))
        return n if 1 <= n <= 25 else None
    except Exception:
        return None


def _growatt_set_battery_modules_override(n: int | None) -> None:
    from energy_dashboard.deps import QSettings
    s = QSettings("PowerModel", "EnergyDashboard2")
    if n is None or int(n) <= 0:
        s.remove(_QS_BAT_MODULES_OVERRIDE)
    else:
        s.setValue(_QS_BAT_MODULES_OVERRIDE, int(n))
    s.sync()


def _growatt_count_storage_devices(devices) -> int:
    """Distinct battery/storage SNs in a plant device_list (excludes the MIX itself)."""
    seen = set()
    for d in devices or []:
        if not isinstance(d, dict):
            continue
        dt = d.get('deviceType') or d.get('type') or d.get('device_type')
        sdt = str(dt).lower() if dt is not None else ''
        try:
            is_storage = int(dt) == 2
        except (TypeError, ValueError):
            is_storage = (
                'stor' in sdt or 'bat' in sdt
                or sdt in ('2', 'battery', 'storage')
            )
        if not is_storage:
            continue
        sn = d.get('deviceSn') or d.get('device_sn') or d.get('sn')
        if sn:
            seen.add(str(sn))
    return len(seen)


def _growatt_count_live_pack_voltages(status, info) -> int:
    """Count pack/cluster voltages that look like a connected 48 V bus."""
    blobs = []
    if isinstance(status, dict):
        blobs.append(status)
    if isinstance(info, dict):
        blobs.append(info)
    keys = (
        'vBat', 'vbat',
        'vBat2', 'vbat2', 'vBat3', 'vbat3', 'vBat4', 'vbat4',
        'bdc1Vbat', 'bdc2Vbat', 'bdc3Vbat', 'bdc4Vbat',
        'BMS2_Vbat', 'BMS3_Vbat', 'BMS4_Vbat',
        'batteryVoltage', 'batteryVoltage2', 'batteryVoltage3',
        'bat_Volt',
    )
    found = 0
    seen_vals = []
    for blob in blobs:
        for key in keys:
            if key not in blob:
                continue
            v = _growatt_as_float(blob.get(key))
            if v is None:
                continue
            # Connected LFP pack bus is typically ~45–58 V.
            if 40.0 <= v <= 62.0:
                if any(abs(v - x) < 0.8 for x in seen_vals):
                    continue
                seen_vals.append(v)
                found += 1
    return found


def _growatt_battery_keys_present(status, info) -> list[str]:
    """List bat/bms/pack-related keys present in live dicts (for diagnostics)."""
    out = []
    for blob in (status, info):
        if not isinstance(blob, dict):
            continue
        for k, v in blob.items():
            kl = str(k).lower()
            if not any(t in kl for t in ('bat', 'bms', 'pack', 'soc', 'fcc')):
                continue
            if v is None or str(v).strip() == '':
                continue
            out.append(f"{k}={v}")
    # Stable unique order
    seen = set()
    uniq = []
    for item in out:
        if item in seen:
            continue
        seen.add(item)
        uniq.append(item)
    return uniq


def _growatt_explicit_battery_count(status, info) -> tuple[int | None, str]:
    """Return (count, source) from explicit BMS / API fields when present."""
    keys = (
        'batteryNum', 'battery_num', 'batNum', 'bat_num', 'bmsBatNum',
        'bmsBatteryNum', 'parallelBatNum', 'BatNumber', 'batNumber',
        'batteryModules', 'batModules', 'packNum', 'pack_num', 'BatPackNum',
        'bdcBatNum', 'BDCNumAndBatNum',
    )
    want = {k.lower() for k in keys}
    for blob in (status, info):
        if not isinstance(blob, dict):
            continue
        for k, raw in blob.items():
            if str(k).lower() not in want:
                continue
            if raw is None:
                continue
            n = _growatt_as_float(raw)
            if n is None:
                continue
            if 'bdcnum' in str(k).lower().replace('_', '') and n > 25:
                n = int(n) & 0xFF
            n_i = int(round(n))
            if 1 <= n_i <= 25:
                return n_i, str(k)
    return None, ''


def _growatt_anomalous_vdsp_note(status, info) -> str:
    """Note when vbatdsp is not a plausible pack voltage (diagnostic only)."""
    vbat = None
    if isinstance(status, dict):
        vbat = _growatt_as_float(status.get('vBat') or status.get('vbat'))
    if vbat is None and isinstance(info, dict):
        vbat = _growatt_as_float(info.get('vBat') or info.get('vbat'))
    vdsp = None
    if isinstance(info, dict):
        vdsp = _growatt_as_float(
            info.get('vbatdsp') or info.get('vBatDsp') or info.get('bat_dsp')
        )
    if vdsp is None and isinstance(status, dict):
        vdsp = _growatt_as_float(
            status.get('vbatdsp') or status.get('vBatDsp') or status.get('bat_dsp')
        )
    if vbat is None or vdsp is None:
        return ''
    if 40.0 <= vbat <= 62.0 and 1.0 <= vdsp <= 30.0:
        return (
            f"vbatdsp={vdsp:g} V is not a pack bus voltage (vBat={vbat:g} V); "
            "Grott maps bat_dsp as voltage — not a parallel-pack counter."
        )
    return ''


def _growatt_modbus_tcp_ready(app_params) -> tuple[str | None, int, int, str]:
    """Return (host, port, unit, err). err set when LAN Modbus is not usable."""
    if app_params is None:
        return None, 0, 0, "No app params"
    mode = str(getattr(app_params, "growatt_modbus_mode", "off") or "off").lower()
    if mode == "serial":
        return None, 0, 0, "USB RTU selected — use Modbus TCP or RTU over TCP for the Ethernet gateway"
    if mode not in ("tcp", "tcp_rtu"):
        return None, 0, 0, "Modbus disabled in Setup (enable Modbus TCP or RTU over TCP)"
    try:
        from energy_dashboard.config import growatt_modbus_tcp_host
    except Exception as exc:
        return None, 0, 0, f"Modbus helper unavailable ({exc})"
    host = growatt_modbus_tcp_host(app_params)
    port = int(getattr(app_params, "growatt_modbus_tcp_port", 502) or 502)
    unit = int(getattr(app_params, "growatt_modbus_unit", 1) or 1)
    if not host:
        return None, 0, 0, "Modbus TCP host empty (set Growatt LAN IP to the RS485–Ethernet box)"
    return host, port, unit, ""


def _growatt_modbus_txn(host, port, unit, op, addr, count=1, *, rtu=False):
    from energy_dashboard.modbus.command_sim import _command_sim_tcp_transaction
    got = _GROWATT_MODBUS_TCP_LOCK.acquire(timeout=_GROWATT_MODBUS_TCP_LOCK_TIMEOUT_S)
    if not got:
        return False, "Modbus busy (another probe in progress)", None
    try:
        return _command_sim_tcp_transaction(
            host, port, unit, op, addr, count, 0, rtu=rtu
        )
    finally:
        _GROWATT_MODBUS_TCP_LOCK.release()


def _growatt_modbus_read_battery_modules(
    app_params,
    *,
    serials: list[str] | None = None,
    serials_detail: str = "",
) -> tuple[int | None, str]:
    """Try Modbus for parallel module count (Grott MQTT cannot see packs 2/3).

    Probes common Growatt maps:
      holding 185  — module count (HA growatt-modbus)
      holding 3120 — BDCNumAndBatNum (low 8 bits = parallel modules)
      input 3262   — BatPackNum (TL-XH BDC2 block)

    On SPH via USR Modbus TCP those count regs are often 0 even when packs are
    present. Fall back to counting non-empty pack serials at holding 1125+
    (8 regs ASCII per pack) — that is the reliable signal for pack 2/3.

    Pass ``serials`` when the caller already read pack SNs to avoid a second
    round-trip on the same gateway.
    """
    host, port, unit, err = _growatt_modbus_tcp_ready(app_params)
    if err:
        return None, err
    rtu = str(getattr(app_params, "growatt_modbus_mode", "")).lower() == "tcp_rtu"

    probes = (
        ("rh", 185, 1, "holding:185"),
        ("rh", 3120, 1, "holding:3120"),
        ("ri", 3262, 1, "input:3262"),
    )
    notes = []
    for op, addr, count, tag in probes:
        ok, msg, regs = _growatt_modbus_txn(
            host, port, unit, op, addr, count, rtu=rtu)
        if not ok or not regs:
            notes.append(f"{tag} fail ({msg})")
            continue
        raw = int(regs[0]) & 0xFFFF
        if tag.endswith("3120"):
            n = raw & 0xFF
        else:
            n = raw
        if 1 <= n <= 25:
            return n, f"Modbus {tag}={raw} → {n} module(s)"
        notes.append(f"{tag}={raw} (out of range)")

    # Count registers empty/zero — derive from pack SN block (SPH).
    if serials is None:
        sns, sn_detail = _growatt_modbus_read_battery_serials(app_params)
    else:
        sns, sn_detail = list(serials or []), serials_detail
    if sns:
        n = len(sns)
        return n, (
            f"Modbus pack SNs ({sn_detail}) → {n} module(s); "
            f"count regs unused ({'; '.join(notes) or 'none'})"
        )
    notes.append(sn_detail or "no pack SNs")
    return None, "; ".join(notes) or "No Modbus pack-count register responded"


def _growatt_regs_to_ascii(regs) -> str:
    """Decode Growatt Modbus ASCII (two chars per register, big-endian)."""
    chars = []
    for raw in regs or []:
        r = int(raw) & 0xFFFF
        for b in ((r >> 8) & 0xFF, r & 0xFF):
            if b == 0:
                break
            if 32 <= b < 127:
                chars.append(chr(b))
    return "".join(chars).strip().strip("\x00")


def _growatt_modbus_read_battery_serials(app_params) -> tuple[list[str], str]:
    """Read per-pack battery serials from Modbus when the map exposes them.

    SPH/SPA-style: holding 1125–1204 (8 regs ASCII × up to 10 packs).
    TL-XH BDC2-style: input 3263–3270 (one pack SN block).
    MIX maps often omit these — same gap as the Growatt website.
    """
    host, port, unit, err = _growatt_modbus_tcp_ready(app_params)
    if err:
        return [], err
    rtu = str(getattr(app_params, "growatt_modbus_mode", "")).lower() == "tcp_rtu"

    notes = []
    # Prefer multi-pack block (3 packs × 8 = 24; then 10 × 8 = 80).
    for count, tag in ((24, "holding:1125×24"), (80, "holding:1125×80"), (8, "holding:1125×8")):
        ok, msg, regs = _growatt_modbus_txn(
            host, port, unit, "rh", 1125, count, rtu=rtu)
        if not ok or not regs:
            notes.append(f"{tag} fail ({msg})")
            continue
        sns = []
        for i in range(0, len(regs), 8):
            sn = _growatt_regs_to_ascii(regs[i:i + 8])
            if sn and len(sn) >= 4:
                sns.append(sn)
        if sns:
            return sns, f"Modbus {tag} → {len(sns)} pack SN(s)"
        notes.append(f"{tag} empty/non-ASCII")

    ok, msg, regs = _growatt_modbus_txn(
        host, port, unit, "ri", 3263, 8, rtu=rtu)
    if ok and regs:
        sn = _growatt_regs_to_ascii(regs)
        if sn and len(sn) >= 4:
            return [sn], f"Modbus input:3263 → 1 pack SN"
        notes.append(f"input:3263 empty ({sn!r})")
    else:
        notes.append(f"input:3263 fail ({msg})")
    return [], "; ".join(notes) or "No Modbus pack-serial block responded"


def _growatt_storage_serials_from_devices(devices) -> list[str]:
    """Storage/battery deviceSn entries from plant device_list."""
    out = []
    seen = set()
    for d in devices or []:
        if not isinstance(d, dict):
            continue
        dt = d.get("deviceType") or d.get("type") or d.get("device_type")
        sdt = str(dt).lower() if dt is not None else ""
        try:
            is_storage = int(dt) == 2
        except (TypeError, ValueError):
            is_storage = (
                "stor" in sdt or "bat" in sdt
                or sdt in ("2", "battery", "storage")
            )
        if not is_storage:
            continue
        sn = d.get("deviceSn") or d.get("device_sn") or d.get("sn")
        if not sn:
            continue
        s = str(sn).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _growatt_serials_from_live(status, info) -> list[str]:
    """Any pack/BMS serial-like fields published in live status/info."""
    keys = (
        "batterySn", "batterySN", "batSn", "batSN", "bmsSn", "bmsSN",
        "BatSerialNO", "batSerial", "packSn", "packSN",
        "batterySn1", "batterySn2", "batterySn3", "batterySn4",
        "batSn1", "batSn2", "batSn3", "batSn4",
        "BMS1_SN", "BMS2_SN", "BMS3_SN", "BMS4_SN",
    )
    out = []
    seen = set()
    for blob in (status, info):
        if not isinstance(blob, dict):
            continue
        for k in keys:
            if k not in blob:
                continue
            s = str(blob.get(k) or "").strip()
            if s and s.lower() not in ("--", "none", "null") and s not in seen:
                seen.add(s)
                out.append(s)
        # Also catch batSnN / batterySnN wildcards.
        for k, v in blob.items():
            kl = str(k).lower()
            if not any(t in kl for t in ("batsn", "batterysn", "packsn", "bmssn", "serial")):
                continue
            if "datalog" in kl or "pvserial" in kl or "inverter" in kl:
                continue
            s = str(v or "").strip()
            if len(s) < 4 or s in seen:
                continue
            # Skip pure numbers that look like voltages/counts.
            try:
                float(s)
                continue
            except (TypeError, ValueError):
                pass
            seen.add(s)
            out.append(s)
    return out


def _growatt_collect_battery_serials(
    devices=None,
    status=None,
    info=None,
    *,
    modbus_sns: list[str] | None = None,
    modbus_detail: str = "",
) -> dict:
    """Merge battery pack serials from device_list, live fields, and Modbus."""
    sns: list[str] = []
    seen = set()
    sources = []

    def _add(items, src):
        nonlocal sns, sources
        added = 0
        for s in items or []:
            t = str(s).strip()
            if not t or t in seen:
                continue
            seen.add(t)
            sns.append(t)
            added += 1
        if added:
            sources.append(f"{src}:{added}")

    if modbus_sns:
        _add(modbus_sns, "modbus")
    _add(_growatt_storage_serials_from_devices(devices), "device_list")
    _add(_growatt_serials_from_live(status, info), "live")

    detail_bits = []
    if sources:
        detail_bits.append(", ".join(sources))
    if modbus_detail:
        detail_bits.append(modbus_detail)
    if not sns:
        detail_bits.append(
            "No pack serials in Growatt cloud device_list / Grott MQTT. "
            "Enable Modbus TCP and Probe — holding 1125+ (SPH) or input 3263 "
            "(TL-XH) when the map exposes them."
        )
    label = ", ".join(sns) if sns else "—"
    return {
        "serials": sns,
        "label": label,
        "count": len(sns),
        "detail": " ".join(detail_bits).strip(),
        "sources": sources,
    }


def _growatt_as_u16(val) -> int | None:
    n = _growatt_as_float(val)
    if n is None:
        return None
    try:
        return int(n) & 0xFFFF
    except (TypeError, ValueError):
        return None


def _growatt_decode_inverter_alerts(status=None, info=None) -> dict:
    """Summarise Growatt/Grott fault & warning words from live telemetry."""
    blobs = [b for b in (status, info) if isinstance(b, dict)]
    faults = []
    warns = []
    raw_bits = []

    def _pick(*keys):
        for blob in blobs:
            for k in keys:
                if k in blob and blob.get(k) not in (None, ""):
                    return k, blob.get(k)
        return None, None

    for label, keys, bucket in (
        ("faultBit", ("faultBit", "faultbit", "FaultBit"), faults),
        ("faultValue", ("faultValue", "faultvalue", "FaultValue", "faultcode", "faultCode"), faults),
        ("warningBit", ("warningBit", "warningbit", "WarningBit"), warns),
        ("warningValue", ("warningValue", "warningvalue", "WarningValue"), warns),
    ):
        k, v = _pick(*keys)
        if k is None:
            continue
        n = _growatt_as_u16(v)
        if n is None:
            continue
        raw_bits.append(f"{k}={n}")
        if n:
            bucket.append(f"{label}={n} (0x{n:04X})")

    for i in range(8):
        for name in (f"systemfaultword{i}", f"systemFaultWord{i}", f"SystemFaultWord{i}"):
            k, v = _pick(name)
            if k is None:
                continue
            n = _growatt_as_u16(v)
            if n is None:
                continue
            raw_bits.append(f"{k}={n}")
            if n:
                faults.append(f"systemfaultword{i}={n} (0x{n:04X})")
            break

    for name in ("facfault", "vacfault", "vpvfault", "tmpfault"):
        k, v = _pick(name, name.lower(), name.upper())
        if k is None:
            continue
        n = _growatt_as_u16(v)
        if n is None:
            continue
        raw_bits.append(f"{k}={n}")
        if n:
            faults.append(f"{k}={n}")

    has_fault = bool(faults)
    has_warn = bool(warns)
    if not has_fault and not has_warn:
        if raw_bits:
            summary = "None (fault/warning words present, all zero)"
        else:
            summary = "—"
        detail = (
            "No non-zero fault/warning fields in this snapshot. "
            "Grott MIX layouts publish systemfaultword0–7; some maps use "
            "faultBit/warningBit."
            if not raw_bits
            else "Raw: " + ", ".join(raw_bits[:16])
        )
    else:
        parts = []
        if has_fault:
            parts.append("FAULT: " + "; ".join(faults))
        if has_warn:
            parts.append("WARN: " + "; ".join(warns))
        summary = " | ".join(parts)
        detail = summary
        if raw_bits:
            detail = detail + "\nRaw: " + ", ".join(raw_bits[:24])

    lines = []
    if has_fault:
        lines.extend(faults)
    if has_warn:
        lines.extend(warns)
    if not lines:
        lines = [summary]

    return {
        "summary": summary,
        "lines": lines,
        "detail": detail,
        "has_fault": has_fault,
        "has_warning": has_warn,
        "healthy": not has_fault and not has_warn and bool(raw_bits),
        "raw": raw_bits,
    }


def _growatt_detect_battery_equipage(
    devices=None,
    status=None,
    info=None,
    app_params=None,
    *,
    modbus_modules: int | None = None,
    modbus_detail: str = "",
    modbus_serials: list[str] | None = None,
) -> dict:
    """Detect how many battery modules are connected and their nominal kWh.

    Parallel GBLI packs share one DC bus. Grott's MIX/SPH layout only publishes
    aggregate ``vbat`` / ``SOC`` — there are no vBat2/vBat3 fields — so packs 2+
    are invisible unless Modbus (or an explicit API count / manual override)
    supplies the module count.

    Returns keys: modules, unit_kwh, capacity_kwh, source, label, detail,
    confidence (certain|configured|partial|unknown), evidence, mismatch, …
    """
    unit = _GROWATT_BATTERY_UNIT_KWH
    setup_cap = None
    setup_modules = None
    if app_params is not None:
        try:
            setup_cap = float(app_params.battery_capacity_kwh)
            if setup_cap > 0:
                setup_modules = max(1, int(round(setup_cap / unit)))
        except (TypeError, ValueError):
            setup_cap = None

    evidence = _growatt_battery_keys_present(status, info)
    vdsp_note = _growatt_anomalous_vdsp_note(status, info)
    n_bus = _growatt_count_live_pack_voltages(status, info)
    n_dev = _growatt_count_storage_devices(devices)
    n_exp, exp_key = _growatt_explicit_battery_count(status, info)
    override = _growatt_battery_modules_override()
    n_modbus_sns = len([
        s for s in (modbus_serials or [])
        if str(s or "").strip()
    ])
    # Prefer explicit count register; else pack-SN count (SPH holding 1125+).
    if modbus_modules is None and n_modbus_sns >= 1:
        modbus_modules = n_modbus_sns
        if not modbus_detail:
            modbus_detail = f"Modbus pack SNs → {n_modbus_sns} module(s)"

    modules = None
    source = ''
    detail = ''
    confidence = 'unknown'

    if override is not None:
        modules = override
        source = 'manual_override'
        detail = (
            f'Manual override = {override} module(s) '
            f'(telemetry cannot count parallel packs)'
        )
        confidence = 'configured'
    elif n_exp is not None:
        modules = n_exp
        source = f'field:{exp_key}'
        detail = f'Explicit {exp_key}={n_exp}'
        confidence = 'certain'
    elif modbus_modules is not None:
        modules = int(modbus_modules)
        source = 'modbus'
        detail = modbus_detail or f'Modbus count = {modules}'
        confidence = 'certain'
    elif n_dev >= 1:
        modules = n_dev
        source = 'device_list'
        detail = f'{n_dev} storage device(s) in plant device_list'
        confidence = 'certain' if n_dev >= 2 else 'partial'
    elif n_bus >= 2:
        modules = n_bus
        source = 'pack_voltages'
        detail = f'{n_bus} distinct pack voltages online'
        confidence = 'certain'
    elif n_bus == 1:
        # Shared 48 V bus — proves ≥1 pack, NOT the parallel count.
        modules = None
        source = 'live_bus_only'
        detail = (
            "Live ~48 V battery bus present. Growatt cloud, the Growatt website, "
            "and Grott MQTT all expose only one shared vBat/SOC for parallel "
            "GBLI packs — packs 2+ are not countable from that feed. "
            "Set a manual module count, or Probe packs over Modbus TCP "
            "(SPH holding 1125+ serials — pack-count regs are often 0)."
        )
        confidence = 'partial'
    else:
        detail = "No live battery bus voltage and no pack-count field."
        confidence = 'unknown'

    if vdsp_note:
        detail = f"{detail} {vdsp_note}".strip()

    # Prefer Setup module count only as a *label hint* when live proof of a bus
    # exists but exact parallel count is unknown — never claim it as detected.
    capacity = (modules * unit) if modules else None
    if modules and source == 'manual_override':
        label = f'{modules} × {unit:g} kWh (manual)'
    elif modules and source == 'modbus':
        label = f'{modules} × {unit:g} kWh (Modbus)'
    elif modules and confidence == 'certain':
        label = f'{modules} × {unit:g} kWh (detected)'
    elif modules and confidence == 'partial' and source == 'device_list':
        label = f'{modules} × {unit:g} kWh (device_list)'
    elif n_bus >= 1 and setup_modules:
        label = (
            f'≥1 connected · Setup implies {setup_modules} × {unit:g} kWh '
            f'(parallel count not in telemetry)'
        )
        if modules is None:
            # Expose Setup as configured suggestion without calling it detected.
            capacity = None
    elif n_bus >= 1:
        label = '≥1 connected (parallel count unknown)'
    else:
        label = ''

    mismatch = ''
    if (
        modules is not None and setup_cap is not None
        and abs(setup_cap - (modules * unit)) > 0.6
    ):
        mismatch = (
            f'Setup still has {setup_cap:g} kWh — update Setup if packs changed '
            f'(e.g. 3 × {unit:g} = {3 * unit:g} kWh)'
        )
    elif modules is None and setup_modules and n_bus >= 1:
        mismatch = (
            f'Setup implies {setup_modules} × {unit:g} kWh but Growatt '
            f'cloud/website/Grott cannot confirm packs 2+'
        )

    why_missing = ''
    if modules is None or (
        source not in ('manual_override', 'modbus')
        and modules is not None and modules < 2 and n_bus == 1
    ):
        why_missing = (
            "Packs 2/3 are not visible anywhere Growatt publishes: parallel "
            "GBLI modules share one DC bus, and the Growatt website, cloud API, "
            "and Grott MIX layout all expose only aggregate vbat/SOC "
            "(no vBat2, BatPackNum, or batteryNum). Set a manual module count "
            "and update Setup capacity; Modbus may help only if your map has "
            "a pack-count register."
        )

    return {
        'modules': modules,
        'unit_kwh': unit,
        'capacity_kwh': capacity,
        'source': source,
        'label': label,
        'detail': detail,
        'confidence': confidence,
        'evidence': evidence,
        'ah_hint': None,
        'mismatch': mismatch,
        'setup_kwh': setup_cap,
        'setup_modules': setup_modules,
        'bus_count': n_bus,
        'why_missing': why_missing,
        'modbus_detail': modbus_detail or '',
    }


def _growatt_strip_equipage_from_model(bat: str) -> str:
    """Remove prior equipage suffixes so label composition stays idempotent."""
    s = (bat or "").strip()
    if not s or s == "—":
        return s or "—"
    parts = [p.strip() for p in s.split(" · ") if p.strip()]
    kept = []
    for p in parts:
        pl = p.lower()
        if (
            p.startswith("≥1 connected")
            or "parallel count" in pl
            or pl.endswith("(detected)")
            or pl.endswith("(manual)")
            or pl.endswith("(modbus)")
            or pl.endswith("(device_list)")
            or "setup implies" in pl
        ):
            continue
        if p not in kept:
            kept.append(p)
    return " · ".join(kept) if kept else "—"


def _growatt_prefer_detected_battery_label(bat: str, equip: dict) -> str:
    """Compose battery model text with a known equipage label (idempotent).

    Partial/unknown equipage notes belong on the Physical equipage row — do not
    append them to the Battery model line (that used to stack on every refresh).
    """
    label = (equip or {}).get("label") or ""
    bat_s = _growatt_strip_equipage_from_model(bat)
    if not label:
        return bat_s
    conf = (equip or {}).get("confidence") or ""
    mods = equip.get("modules")

    # Uncertainty / Setup-implied text → model stays product/Setup only.
    if conf in ("partial", "unknown") or mods is None:
        if bat_s in ("", "—"):
            # Prefer a short Setup hint over the long ≥1 telemetry essay.
            setup_m = equip.get("setup_modules")
            unit = equip.get("unit_kwh") or _GROWATT_BATTERY_UNIT_KWH
            if setup_m:
                return f"{setup_m} × {float(unit):g} kWh (Setup)"
            return "—"
        return bat_s

    if bat_s in ("", "—") or "(Setup)" in bat_s:
        return label
    if conf in ("certain", "configured") and mods:
        if label in bat_s or f"{mods} ×" in bat_s:
            # Already composed (or product string already names the count).
            if label in bat_s:
                return bat_s
            return f"{bat_s} · {label}"
        return f"{bat_s} · {label}"
    return bat_s


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
    status=None,
    log_device_list=False,
):
    """Best-effort inverter + battery product strings (cloud + Setup + live equipage)."""
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
    equip = _growatt_detect_battery_equipage(
        devices=devices, status=status, info=mix_info, app_params=app_params,
    )
    bat = _growatt_prefer_detected_battery_label(bat, equip)
    return inv, bat, equip


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


# Growatt SPH / MIX hybrid “system status” / ``pvstatus`` work-mode codes
# (Modbus / Grott / cloud). Indicative — firmwares can vary slightly.
_GROWATT_SYSTEM_STATUS_HINTS = {
    0: "Standby / waiting",
    1: "PV + battery bypass (or self-check on some firmwares)",
    2: "Bypass / grid-pass",
    3: "Fault",
    4: "Flash / firmware update",
    5: "PV charging the battery",
    6: "AC (grid) charging the battery",
    7: "Battery discharging to the house",
    8: "Combined charge (PV + grid)",
    9: "Combined charge + bypass",
    10: "PV charge + bypass",
}


def _growatt_system_status_display(status) -> tuple[str, str]:
    """Return (one_line_plain_text, tooltip) for mix ``lost`` / ``status`` / ``pvstatus``.

    Growatt publishes this as a small integer work-mode on hybrids (SPH/MIX),
    or sometimes as a string such as ``lost`` when the stick is offline.
    """
    if not isinstance(status, dict):
        return "—", ""
    raw = status.get("lost")
    if raw in (None, ""):
        raw = status.get("status")
    if raw in (None, ""):
        raw = status.get("pvstatus")
    if raw in (None, ""):
        return "—", (
            "No system-status field in this snapshot "
            "(Grott/cloud keys: lost, status, pvstatus)."
        )

    clean = _growatt_sanitize_api_label(raw)
    tip_bits = [
        f"Raw value from inverter telemetry: {raw!r}",
        "Source keys (first present): lost → status → pvstatus.",
        "On Growatt hybrid (SPH/MIX) this is usually the work mode, not a fault code.",
        "Faults/warnings are listed separately above when the inverter sets them.",
    ]
    if not clean:
        return "—", "\n".join(tip_bits)

    low = clean.lower()
    if any(tok in low for tok in ("lost", "offline", "disconnect", "no signal")):
        tip_bits.append("Growatt is reporting the inverter/stick as not talking.")
        return f"{clean} — inverter/comms offline", "\n".join(tip_bits)

    try:
        n = int(float(clean))
    except (TypeError, ValueError):
        tip_bits.append("Non-numeric status string (shown as published).")
        disp = clean if len(clean) <= 56 else (clean[:55] + "…")
        return disp, "\n".join(tip_bits)

    hint = _GROWATT_SYSTEM_STATUS_HINTS.get(n)
    if hint:
        tip_bits.append(f"Decoded work mode {n}: {hint}.")
        tip_bits.append(
            "Legend is indicative for Growatt hybrid family; "
            "confirm against your inverter manual if unsure."
        )
        return f"{n} — {hint}", "\n".join(tip_bits)

    tip_bits.append(f"Code {n} is not in the built-in hybrid legend.")
    return f"{n} — unknown work mode (see tooltip)", "\n".join(tip_bits)


__all__ = [n for n in globals() if not n.startswith('__')]
