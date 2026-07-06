# Growatt API Guide (project-local reference)

A consolidated reference for talking to Growatt MIX/SPH inverters from this
project. Combines:

- the upstream [`growattServer`](https://github.com/indykoning/PyPi_GrowattServer)
  Python library (v2.0.1, bundled in `octopus-ui/`) — both the legacy
  password-based `GrowattApi` and the token-based `OpenApiV1`,
- the on-the-wire `paramN` layouts for the two write paths we actually use
  (`mix_ac_charge_time_period`, `mix_ac_discharge_time_period`),
- the read-back JSON shape returned by `getMixSetParams` (so you can decode
  what the inverter currently has scheduled),
- this project's wrapper helpers (`_mix_ac_charge_api_params`,
  `_parse_ac_charge_from_settings`, …) and where they live,
- the snapshot → write → verify → rollback workflow used by the Optimiser tab.

> ⚠️ **Safety.** Settings calls modify your inverter's behaviour. The upstream
> library's disclaimer applies in full:
> *"To the best of our knowledge only the `settings` functions perform
> modifications to your system and all other operations are read only.
> Regardless of the operation: the library is used entirely at your own risk."*
> Anything that calls `update_mix_inverter_setting` should go through the
> snapshot-and-verify workflow described at the end of this document.

---

## 1. Three ways to talk to Growatt

| Path | Auth | Status in this repo | When to use |
|------|------|---------------------|-------------|
| **Legacy `GrowattApi`** (`server.growatt.com` / `openapi.growatt.com`) | username + MD5-with-`c`-substitution password (cookies) | **Used by `EnergyDashboard2.py`, `GreatOverlord.py`, `growattServer2.py`, `Diagnose.py`** | Default for MIX/SPH; only path that exposes `update_mix_inverter_setting` |
| **OpenApi V1** (`/v1/...`) | bearer token (`token` header) | Bundled (`growattServer.OpenApiV1`) but **not currently used** | Officially supported by Growatt for MIN (TLX) and SPH (MIX); better security + relaxed rate limiting |
| **ShinePhone web scraper** (`server.growatt.com/login`) | username + MD5 password (no `c` substitution) | **Used by `GetGrowatt.py`** | Reverse-engineered HTML/JSON web API; useful when the legacy app API is blocked or rate-limited |

Endpoints in the legacy and V1 paths overlap heavily. **Prefer V1 if you can
get a token from your installer** — see §10.

---

## 2. Authentication

### 2.1 Legacy password API

```python
import growattServer

api = growattServer.GrowattApi(
    add_random_user_id=False,
    agent_identifier="https://server.growatt.com/",
)
login = api.login(USERNAME, PASSWORD)  # MD5+c hash done internally
# login['data'] -> [{plantName, plantId}, ...]
# login['user']['id']  -> userId
```

`GrowattApi.__init__` defaults to `https://openapi.growatt.com/`. This project
overrides the URL to `https://server.growatt.com/` (see
`EnergyDashboard2.py:2981`, `growattServer2.py:15`, `Diagnose.py:12`).

The password hash is computed by `growattServer.hash_password`:

```
md5_hex = md5(password)         # 32 hex chars
for i in 0,2,4,...,30:          # at every even index
    if md5_hex[i] == '0':
        md5_hex[i] = 'c'
```

### 2.2 OpenApi V1 (token)

```python
from growattServer import OpenApiV1, DeviceType

api = OpenApiV1(token="…issued by Growatt to your installer…")
plants = api.plant_list()              # 'count', 'plants'
detail = api.plant_details(plant_id)
sph    = api.get_device(device_sn, DeviceType.SPH.value)
sph.write_ac_charge_times(charge_power=100, charge_stop_soc=80,
                          mains_enabled=True, periods=[…])
```

V1 is documented at <https://www.showdoc.com.cn/262556420217021/0>.

### 2.3 ShinePhone scraper (`GetGrowatt.py`)

The `GrowattShinePhone` class hits the web frontend. Uses raw MD5 (no `c`
substitution) and a Chrome user-agent. Login flow:

1. `GET https://server.growatt.com/login` (collect cookies)
2. `POST https://server.growatt.com/login` with `{account, password (md5),
   validateCode='', isReadPact=1}`
3. JSON response on success contains `result=1` and `user.id`.

---

## 3. Read endpoints we use (legacy `GrowattApi`)

All return `dict` (or `list` for `plant_list`). All call sites are in
`EnergyDashboard2.py` unless noted.

| Method | Purpose | Used at |
|--------|---------|---------|
| `api.login(user, pwd)` | Auth + plant list | `2982`, `growattServer2.py:20`, `Diagnose.py:17` |
| `api.plant_list(user_id)` | List plants for a user | `Diagnose.py:51` |
| `api.plant_list_two()` | Detailed plant list (paginated) | available |
| `api.plant_info(plant_id)` | Plant info | `growattServer2.py:129`, `Diagnose.py:65` |
| `api.device_list(plant_id)` | All devices on a plant | `growattServer2.py:46` |
| `api.inverter_detail(device_sn)` | PV-only inverter detail | `growattServer2.py:105` |
| `api.mix_info(device_sn[, plant_id])` | MIX high-level (SOC, capacity, pCharge1, pDischarge1, vbat, vpv1/2) | `growattServer2.py:113` |
| `api.mix_totals(device_sn, plant_id)` | MIX daily/all-time totals (`echargetoday`, `etoGridToday`, `elocalLoadToday`, `epvToday`) | `3040`, `growattServer2.py:121` |
| `api.mix_system_status(device_sn, plant_id)` | MIX live status (SOC, chargePower, pLocalLoad, pactogrid, pactouser, pdisCharge1, pPv1/2, vAc1) | `3026`, `3115` |
| `api.mix_detail(device_sn, plant_id, timespan, date)` | 5-min `chartData` (pacToGrid, pacToUser, pdischarge, ppv, sysOut) for hour/day/month | `4204` |
| `api.dashboard_data(plant_id, timespan, date)` | Plant-level chartData (note: **not** accurate for MIX systems on most fields) | available |
| `api.get_mix_inverter_settings(device_sn)` | Read current AC-charge / AC-discharge schedule (raw `getMixSetParams` response) | `10148`, `12098`, `12169`, `12349`, `12483`, `12637`, `12803` |
| `api.tlx_*` | TLX/MIN equivalents | available |
| `api.noah_system_status(sn)` / `noah_info(sn)` | Noah battery system | available |

The most important read keys for MIX systems (mapped to inverter behaviour) are
documented inline in `growattServer/base_api.py:551..738`.

---

## 4. Write endpoints we use

| Method | Setting type used | Purpose |
|--------|-------------------|---------|
| `api.update_mix_inverter_setting(sn, "mix_ac_charge_time_period", params)` | AC charge schedule | `EnergyDashboard2.py:10235`, `12154`, `12339` |
| `api.update_mix_inverter_setting(sn, "mix_ac_discharge_time_period", params)` | AC discharge / forced-export schedule | `EnergyDashboard2.py:12627`, `12792` |

Under the hood (`growattServer/base_api.py:1094`) `update_mix_inverter_setting`
POSTs to `newTcpsetAPI.do` with `op=mixSetApiNew, serialNum=<sn>, type=<setting_type>` and merges in the `paramN` dict you pass.

There are sibling endpoints we do **not** use:

- `update_ac_inverter_setting` — for AC-coupled SPA-class inverters (`op=spaSetApi`)
- `update_tlx_inverter_setting` / `update_tlx_inverter_time_segment` — for TLX/MIN
- `update_noah_settings` — for Noah portable batteries
- `update_classic_inverter_setting` / `update_plant_settings`

---

## 5. AC-charge schedule wire format (`mix_ac_charge_time_period`)

### 5.1 paramN layout sent to the cloud (param1..param18)

| param  | Meaning                                            | Type / values    |
|--------|----------------------------------------------------|------------------|
| param1 | Charge power (% of rated AC charge rate)           | `"0".."100"`     |
| param2 | Stop SOC (%) — charging stops when battery hits this | `"0".."100"`   |
| param3 | **Master enable** for AC charging                  | `"0"` / `"1"`    |
| param4 | Period 1 start hour                                | `"0".."23"`      |
| param5 | Period 1 start minute                              | `"0".."59"`      |
| param6 | Period 1 end hour                                  | `"0".."23"`      |
| param7 | Period 1 end minute                                | `"0".."59"`      |
| param8 | Period 1 per-period enable                         | `"0"` / `"1"`    |
| param9..param13  | Period 2 (same 5-tuple)                  | as above         |
| param14..param18 | Period 3 (same 5-tuple)                  | as above         |

> All values are **strings** on the wire. A period only fires when `param3`
> (master enable) **AND** the per-period enable bit are both `"1"`.

Generator: `EnergyDashboard2.py:9089` `_mix_ac_charge_api_params(charge_power,
charge_stop_soc, mains_enabled, periods)`. `periods` must be a list of
exactly 3 dicts: `{'start_time': datetime.time, 'end_time': datetime.time,
'enabled': bool}`. Disabled periods should still be present (just with
`enabled=False`); the inverter expects all 3 slots every time.

Reference implementation in upstream library:
`growattServer/open_api_v1/devices/sph.py:218..289`
(`Sph.write_ac_charge_times`).

### 5.2 Read-back JSON fields (response from `get_mix_inverter_settings`)

The response wraps the schedule in `{"obj": {...}}`. Inside `obj`:

| JSON key                       | Decoded as                                |
|--------------------------------|-------------------------------------------|
| `chargePowerCommand`           | `charge_power` (int %)                    |
| `wchargeSOCLowLimit`           | `stop_soc` (int %)                        |
| `acChargeEnable`               | `mains_enabled` (bool, `1` = on)          |
| `forcedChargeTimeStart{i}`     | period `i` start `"H:M"` (i = 1, 2, 3)    |
| `forcedChargeTimeStop{i}`      | period `i` end `"H:M"`                    |
| `forcedChargeStopSwitch{i}`    | period `i` enabled (bool, `1` = on)       |

Decoder: `OptimiserTab._parse_ac_charge_from_settings` at
`EnergyDashboard2.py:11363`. Returns `None` if the response shape isn't
recognised (so callers can fall back to safe-disable behaviour without
exceptions).

---

## 6. AC-discharge / forced-export schedule (`mix_ac_discharge_time_period`)

Same idea but **shifted by one** because there is no master enable bit.

### 6.1 paramN layout (param1..param17)

| param  | Meaning                                                             |
|--------|---------------------------------------------------------------------|
| param1 | Discharge power (% of rated)                                        |
| param2 | Discharge **stop SOC %** — battery floor (set 100 to disable safely)|
| param3..param7   | Period 1: (start_h, start_m, end_h, end_m, enabled)       |
| param8..param12  | Period 2                                                  |
| param13..param17 | Period 3                                                  |

> Note `stop_soc` here is a **floor** (discharge stops at this %),
> the opposite of the charge schedule's ceiling. There is **no global
> master switch** — each period's enable bit alone gates whether it fires.

Generator: `EnergyDashboard2.py:9115` `_mix_ac_discharge_api_params(...)`.
Reference: `growattServer/open_api_v1/devices/sph.py:291..359`
(`Sph.write_ac_discharge_times`).

### 6.2 Read-back JSON fields

Inside `obj`:

| JSON key                          | Decoded as                                     |
|-----------------------------------|------------------------------------------------|
| `disChargePowerCommand`           | `discharge_power` (int %)                      |
| `wdisChargeSOCLowLimit`           | `discharge_stop_soc` (int %, **floor**)        |
| `forcedDischargeTimeStart{i}`     | period `i` start `"H:M"`                       |
| `forcedDischargeTimeStop{i}`      | period `i` end `"H:M"`                         |
| `forcedDischargeStopSwitch{i}`    | period `i` enabled                             |

Decoder: `OptimiserTab._parse_ac_discharge_from_settings` at
`EnergyDashboard2.py:11542`.

---

## 7. Project-local helper inventory

Everything we use to talk to the inverter, with line numbers in
`EnergyDashboard2.py`:

| Helper | Line | Purpose |
|--------|------|---------|
| `_mix_ac_charge_api_params(power, stop_soc, mains_en, periods)` | 9089 | Build paramN dict for AC charge writes |
| `_mix_ac_discharge_api_params(power, stop_soc, periods)` | 9115 | Build paramN dict for forced-discharge writes |
| `OptimiserTab._build_inverter_payload_from_plan(plan)` | ~11166 | Translate optimiser plan → AC-charge payload tuple |
| `OptimiserTab._build_inverter_discharge_payload_from_plan(plan)` | ~11264 | Translate optimiser plan → forced-discharge payload tuple |
| `OptimiserTab._parse_ac_charge_from_settings(raw)` | 11363 | Decode read-back into structured charge state |
| `OptimiserTab._ac_state_to_params(ac)` | 11435 | Round-trip back to paramN dict |
| `OptimiserTab._safe_disable_params(power=100, stop_soc=10)` | 11446 | Panic-stop AC-charge payload (3 disabled periods, master OFF) |
| `OptimiserTab._format_ac_state(ac)` | 11455 | Render charge state for the confirmation dialog |
| `OptimiserTab._ac_state_matches_params(ac, params, tol=2)` | 11474 | Verify a write by comparing read-back vs sent params |
| `OptimiserTab._parse_ac_discharge_from_settings(raw)` | 11542 | Decode read-back into structured discharge state |
| `OptimiserTab._ac_discharge_state_to_params(ac)` | 11598 | Round-trip back to paramN dict |
| `OptimiserTab._safe_disable_discharge_params()` | 11606 | Panic-stop discharge payload (3 disabled periods, floor=100 %) |
| `OptimiserTab._format_ac_discharge_state(ac)` | 11615 | Render discharge state for the confirmation dialog |
| `OptimiserTab._ac_discharge_state_matches_params(...)` | 11632 | Verify discharge write |
| `OptimiserTab._param_explainer_rows(params, kind)` | (v2.9.84) | Per-paramN English explainer for the confirmation dialog tree view |
| `OptimiserTab._show_writeback_confirmation(...)` | (v2.9.84) | Resizable QDialog used by both write flows (replaces QMessageBox) |
| `OptimiserTab._build_confirm_dialog_html(...)` | 11748 | HTML body for the AC-charge confirmation |
| `OptimiserTab._build_discharge_confirm_dialog_html(...)` | 12365 | HTML body for the discharge confirmation |
| `_qtime_to_time(qt)` | 9150 | Convert `QTime` from spinbox → `datetime.time` |

Other modules:

- `GetGrowatt.py` — `GrowattShinePhone` class (web scraper API)
- `growattServer2.py` — introspection/exploration of the legacy API
- `Diagnose.py` — connection sanity checker

---

## 8. Snapshot → write → verify → rollback workflow

This is the safety contract we follow for **every** settings write. Both the
AC-charge and forced-discharge flows in the Optimiser tab implement this
identically.

```
┌─ SNAPSHOT ──────────────────────────────────────────────────────────┐
│ raw_snap = api.get_mix_inverter_settings(sn)                       │
│ pre = _parse_ac_charge_from_settings(raw_snap)   # may be None      │
│ pre_params = _ac_state_to_params(pre) if pre else None              │
│ pre_ts = datetime.now()                                             │
└────────────────────────────────────────────────────────────────────┘
            │  Refuse to write if snapshot fetch raised
            ▼
┌─ CONFIRM ──────────────────────────────────────────────────────────┐
│ Show resizable dialog with:                                        │
│   • plan summary (decoded paramN → human-readable)                 │
│   • prior schedule (from snapshot, _format_ac_state)               │
│   • risks & caveats                                                │
│   • Parameter explainer tree (each paramN annotated)               │
│   • Raw JSON tab (json.dumps(params, indent=2))                    │
└────────────────────────────────────────────────────────────────────┘
            │  user presses Yes
            ▼
┌─ WRITE  (background thread) ───────────────────────────────────────┐
│ resp = api.update_mix_inverter_setting(sn, type, params)           │
│ time.sleep(3.0)   # let the cloud propagate to the device          │
└────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─ VERIFY ───────────────────────────────────────────────────────────┐
│ verify_raw = api.get_mix_inverter_settings(sn)                     │
│ verify_ac  = _parse_ac_charge_from_settings(verify_raw)            │
│ ok, mismatches = _ac_state_matches_params(verify_ac, params,       │
│                                            tolerance_min=2)        │
└────────────────────────────────────────────────────────────────────┘
            │
       ┌────┴────┐
   ok? │         │ mismatch / verify failed
       ▼         ▼
   GREEN      ┌─ AUTO-ROLLBACK ─────────────────────────────────────┐
              │ if pre_params: api.update_mix_inverter_setting(...) │
              │              else: api.update_mix_inverter_setting( │
              │                       sn, type, _safe_disable_*())  │
              └─────────────────────────────────────────────────────┘
                              │
                              ▼ verify rollback the same way → AMBER/RED status
```

A few invariants the workflow guarantees:

- **No write without a snapshot.** If `api.get_mix_inverter_settings` raises,
  the write is aborted before any state change.
- **Tolerance on times.** The cloud sometimes rounds `H:M`; `_..._matches_params`
  accepts up to 2 minutes of drift before flagging a mismatch.
- **Safe-disable fallback.** If the snapshot can't be parsed, rollback writes
  `_safe_disable_params()` (charge) or `_safe_disable_discharge_params()`
  (discharge) instead of trying to restore unparsable state. This guarantees
  the inverter ends in a known-good "do nothing" state on any failure.
- **Manual rollback button** stays active so the user can panic-stop at any
  time.
- **AMBER / RED status.** Cloud unreachable on read-back → AMBER (no auto
  action). Verify failed → auto-rollback then RED.

---

## 9. Common pitfalls

- **`paramN` values are strings, not ints.** `param1=100` will work because
  `requests` will str() it, but the reference helpers all emit strings to
  match the upstream library.
- **AC-charge has `mains_enabled` at `param3`; AC-discharge does not.** This
  shifts every period's params by 1 between the two schedules. Don't reuse
  one's helper for the other.
- **Discharge `stop_soc` is a floor, charge `stop_soc` is a ceiling.** Setting
  discharge `stop_soc=100` is a safe-disable (battery never allowed to
  discharge below 100 % SOC, i.e. never).
- **All 3 periods must always be sent.** The inverter doesn't have a "1
  period" mode; pass the unused slots as `enabled=False` (any times will do).
- **Daily recurrence.** The schedule has no concept of "tomorrow only" — it
  replays every day at those times until you write again. Re-arm or rollback
  daily if your plan is single-day.
- **Schedule overwrite.** Only ONE AC-charge and ONE AC-discharge schedule
  exist per inverter. A write replaces anything ShinePhone or your installer
  set previously.
- **Cloud latency.** Writes propagate via the Growatt cloud. We sleep 3 s
  before verifying; this catches most cases but not all (10–90 s delays do
  happen). If verify fails immediately, a manual re-verify a minute later
  often succeeds.
- **Rate limiting.** The legacy API will start returning HTML login pages if
  hammered. Stay under ~1 read/s per device. The V1 API is more permissive.
- **Password hashing differs between paths.** `growattServer.hash_password`
  uses MD5+`c`-substitution; `GrowattShinePhone._make_password_hash` uses
  raw MD5. Don't share hashed passwords between the two.
- **Server URL.** `GrowattApi` defaults to `openapi.growatt.com` but this
  project targets `server.growatt.com`. Always pass it as the second
  positional arg to the constructor.
- **MIX vs TLX.** `mix_*` endpoints are SPH/MIX only. TLX (newer single-phase
  hybrid, e.g. MIN-3000TL-XH-EP) needs `tlx_*` endpoints and a different
  schedule API (`update_tlx_inverter_time_segment`). The V1 API generalises
  this with `Sph` / `Min` device classes.

---

## 10. Switching to OpenApi V1 (future work)

The bundled `growattServer.OpenApiV1` is the officially-supported replacement
for the legacy API. Migration sketch:

```python
from growattServer import OpenApiV1, DeviceType
from datetime import time as _time

api = OpenApiV1(token=GROWATT_V1_TOKEN)
plants = api.plant_list()
sph = api.get_device(device_sn, DeviceType.SPH.value)  # returns Sph instance

# Read the current AC-charge schedule
charge_state = sph.read_ac_charge_times()
# Write a new one
sph.write_ac_charge_times(
    charge_power=100,
    charge_stop_soc=80,
    mains_enabled=True,
    periods=[
        {"start_time": _time(1, 0), "end_time": _time(5, 0), "enabled": True},
        {"start_time": _time(0, 0), "end_time": _time(0, 0), "enabled": False},
        {"start_time": _time(0, 0), "end_time": _time(0, 0), "enabled": False},
    ],
)
```

The wire-level `paramN` layout is **identical** to the legacy API (the V1
methods just wrap the same `mixSet` / `mixSetApiNew` endpoint), so all the
parsers and helpers in §7 still apply.

To migrate this project we'd need to:

1. Get a V1 token from your Growatt account / installer (free for SPH/MIN).
2. Add a token field to the Growatt tab credentials UI.
3. In `EnergyDashboard2.py`, branch on token-present → use `OpenApiV1`,
   otherwise fall back to the legacy `GrowattApi`.
4. Replace `mix_system_status` → `sph.detail()`, `mix_totals` → `sph.energy()`,
   `mix_detail` → `sph.energy_history()`, `get_mix_inverter_settings` →
   `sph.read_ac_charge_times()` / `sph.read_ac_discharge_times()`, etc.
5. Keep the snapshot → write → verify → rollback workflow unchanged — both
   APIs return parseable state, and `_ac_state_matches_params` only cares
   about the structured form.

---

## 11. Reference URLs

- `growattServer` library — <https://github.com/indykoning/PyPi_GrowattServer>
- Local copy of the README — `octopus-ui/lib/python3.13/site-packages/growattserver-2.0.1.dist-info/METADATA` (lines 26+)
- OpenApi V1 docs — <https://www.showdoc.com.cn/262556420217021/0>
- Original Sjoerd Langkemper client (archived) — <https://github.com/Sjord/growatt_api_client>
