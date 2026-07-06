"""
Energy Dashboard — `planner/core.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
_PLAN_SLOTS_DEFAULT = 48          # 24 h horizon (extends to 48 h once tomorrow's Agile is published)
_PLAN_BIN_PCT      = 2.5          # SOC discretisation for the DP (40 bins for a 100% range)
_PLAN_EXPORT_MIN_SOC = 30         # never discharge to grid below this SOC %
_PLAN_EXPORT_MARGIN_P = 5.0       # export must beat reachable cheap-charge slot by ≥ this p/kWh
_PLAN_THROUGHPUT_PENALTY_P = 0.3  # battery wear "tax" per kWh moved (in or out)
_PLAN_SOLAR_FORECAST_SCALE = 0.7  # multiply forecast.solar kWh/slot (conservative < 1)
# PV10 blend (Predbat-style probabilistic solar). The free Forecast.Solar
# /estimate endpoint only returns a single deterministic curve (≈ P50);
# Pro tier gives PV10/P90 but is paid. Instead of a flat 0.7 derate that
# treats peak midday and overcast morning identically, we synthesise PV10
# from PV50 with a *time-localised* ratio:
#   pv10[t] = pv50[t] × ( PV10_MIN_RATIO + (PV10_MAX_RATIO − PV10_MIN_RATIO)
#                          × √( pv50[t] / max(pv50) ) )
# i.e. peak slots get derated less (closer to PV10_MAX_RATIO) and shoulder
# slots get derated more (closer to PV10_MIN_RATIO), capturing the well-
# documented "cloudy days hit shoulders harder than peaks" behaviour.
# Effective per-slot energy used by the planner is then:
#   pv_used[t] = (1 − w10) × pv50[t] + w10 × pv10[t]
# with `w10 = _PLAN_PV10_WEIGHT`. Default 0.0 = pure PV50 = backwards
# compatible with every prior version. Predbat's typical setting is 0.3.
_PLAN_PV10_WEIGHT = 0.0
_PLAN_PV10_MIN_RATIO = 0.30  # PV10/PV50 ratio at zero irradiance
_PLAN_PV10_MAX_RATIO = 0.75  # PV10/PV50 ratio at peak irradiance

# Auto-replan cadence (Predbat re-plans every ~5 min). We don't time-step
# through actions ourselves — we just rebuild the plan when the inputs that
# fed the last plan are stale enough to matter. Default OFF: until the user
# has watched the auto-trigger fire a few times in their environment, the
# Optimiser stays push-to-run. Persisted in QSettings under
# ``optimiser/auto_replan``.
_PLAN_AUTO_REPLAN_DEFAULT = False
_PLAN_AUTO_REPLAN_TICK_S = 60                # how often the timer wakes up
_PLAN_AUTO_REPLAN_COOLDOWN_S = 5 * 60        # min wall-clock gap between auto fires
_PLAN_AUTO_REPLAN_PLAN_AGE_MIN = 30          # plan older than this → re-run
_PLAN_AUTO_REPLAN_SOC_DRIFT_PP = 15          # |actual − planned| SOC pp → re-run
_PLAN_AUTO_REPLAN_AGILE_PUBLISH_HOUR = 16    # Octopus typically publishes ~16:00 BST
_PLAN_HEATER_KW = 3.0             # immersion default
_PLAN_DAY_BLOCK_H = 4             # mandatory daytime hot-water duration
_PLAN_PRE_MORNING_END_H = 7       # heater MUST be off by this local hour
_PLAN_PRE_MORNING_SLOTS = 2       # slots (= 60 min) of mandatory pre-7am heat
_PLAN_DAY_WINDOW = (8, 18)        # local-hour window within which the 4 h block must sit
_PLAN_TERMINAL_VALUE_SCALE = 1.0  # multiplier on end-of-horizon SOC value (Predbat: metric_battery_value_scaling)
# Forced battery export (battery → grid). Defaults OFF: until the user has watched
# the new mix_ac_discharge_time_period writeback land safely a few times, the DP
# refuses any batt_to_grid > 0 action and the chart's green "export to grid" bars
# stay empty. Flip via the "Allow battery export" checkbox in the Optimiser tab.
_PLAN_ALLOW_BATTERY_EXPORT = False
_PLAN_INV_DISCHARGE_POWER_DEFAULT = 100  # % of rated power for forced-discharge schedule


def plan_horizon_slot_starts(now_london, n_slots=_PLAN_SLOTS_DEFAULT):
    """Return a tz-aware ``DatetimeIndex`` of London-time slot starts on 30-min boundaries
    starting at the next half-hour ≥ now."""
    n = pd.Timestamp(now_london)
    if n.tz is None:
        n = n.tz_localize('Europe/London')
    else:
        n = n.tz_convert('Europe/London')
    n = n.replace(second=0, microsecond=0)
    n = n.replace(minute=30) if n.minute >= 30 else n.replace(minute=0)
    return pd.DatetimeIndex([n + pd.Timedelta(minutes=30 * i) for i in range(n_slots)])


# Extra half-hours drawn before the DP horizon on the Optimiser charts only
# (London-local). Gives two hours of Agile + load + solar context left of NOW.
_OPTIMISER_CHART_PAST_HOURS = 2
_OPTIMISER_CHART_PAST_SLOTS = (_OPTIMISER_CHART_PAST_HOURS * 60) // 30


def build_optimiser_chart_past_extension(
    slot_starts, agile_in, agile_ex_series, solar_df, usage_profile,
    import_flat_p, export_flat_p, solar_forecast_scale, base_load_kw,
    pv10_weight=_PLAN_PV10_WEIGHT,
):
    """Build 30-min slot data for the ``_OPTIMISER_CHART_PAST_HOURS`` before ``slot_starts[0]``.

    Used only for rendering: Agile import/export, forecast solar, and rigid load
    for those slots; stacked bars use a no-battery solar/load split. The SOC
    polyline is extended separately (flat at the DP start SOC).
    """
    if slot_starts is None or len(slot_starts) == 0:
        return None
    first = pd.Timestamp(slot_starts[0])
    if first.tzinfo is None:
        first = first.tz_localize('Europe/London')
    else:
        first = first.tz_convert('Europe/London')
    past_starts = pd.date_range(
        start=first - pd.Timedelta(minutes=30 * _OPTIMISER_CHART_PAST_SLOTS),
        periods=_OPTIMISER_CHART_PAST_SLOTS,
        freq='30min',
        tz=first.tz,
    )
    past_p_in = plan_prices_per_slot(past_starts, agile_in, import_flat_p)
    past_p_ex = plan_export_prices_per_slot(past_starts, agile_ex_series, export_flat_p)
    past_solar = plan_solar_per_slot(
        past_starts, solar_df,
        forecast_scale=solar_forecast_scale,
        pv10_weight=pv10_weight,
    )
    past_load = plan_load_per_slot(past_starts, usage_profile, base_load_kw)
    past_heater = np.zeros(_OPTIMISER_CHART_PAST_SLOTS, dtype=float)
    naive_actions = []
    for i in range(_OPTIMISER_CHART_PAST_SLOTS):
        S = float(past_solar[i])
        L = float(past_load[i]) + float(past_heater[i])
        solar_to_load = min(S, L)
        grid_to_load = max(0.0, L - solar_to_load)
        solar_to_grid = max(0.0, S - solar_to_load)
        naive_actions.append({
            'batt_to_load': 0.0,
            'batt_to_grid': 0.0,
            'grid_to_batt': 0.0,
            'solar_to_load': solar_to_load,
            'solar_to_grid': solar_to_grid,
            'grid_in_kwh': grid_to_load,
        })
    return {
        'n_past': _OPTIMISER_CHART_PAST_SLOTS,
        'slot_starts': past_starts,
        'p_in': past_p_in,
        'p_ex': past_p_ex,
        'solar_kwh': past_solar,
        'load_kwh': past_load,
        'heater_kwh': past_heater,
        'actions': naive_actions,
    }


def plan_solar_per_slot(slot_starts, solar_df,
                        forecast_scale=_PLAN_SOLAR_FORECAST_SCALE,
                        pv10_weight=_PLAN_PV10_WEIGHT,
                        pv10_min_ratio=_PLAN_PV10_MIN_RATIO,
                        pv10_max_ratio=_PLAN_PV10_MAX_RATIO):
    """Average forecast.solar (kW) inside each 30-min slot, return kWh.

    Composition order:
      1. Per-slot PV50[t] = ∫ kW dt over the 30-min slot (Simpson's rule).
      2. If ``pv10_weight > 0``: blend with a time-localised PV10 curve
         (see :data:`_PLAN_PV10_WEIGHT` for the heuristic).
      3. Multiply by ``forecast_scale`` (the existing flat derate).

    Setting ``pv10_weight=0`` (default) reproduces the legacy behaviour
    bit-for-bit: pure PV50 × forecast_scale.
    """
    out = np.zeros(len(slot_starts), dtype=float)
    if solar_df is None or len(solar_df) == 0 or 'kW' not in solar_df.columns:
        return out
    sdf = solar_df.copy()
    ts = pd.to_datetime(sdf['timestamp'], utc=True).dt.tz_convert('Europe/London')
    sdf = sdf.assign(_t=ts).sort_values('_t').reset_index(drop=True)
    if sdf.empty:
        return out
    t_ns = sdf['_t'].astype('int64').to_numpy()
    kw = sdf['kW'].to_numpy(dtype=float)
    # Step 1: integrate PV50 per slot (kWh, no scale applied yet).
    pv50 = np.zeros(len(slot_starts), dtype=float)
    for i, t in enumerate(slot_starts):
        a = int(pd.Timestamp(t).value)
        b = a + 30 * 60 * 1_000_000_000
        m = (a + b) // 2
        kw_a = float(np.interp(a, t_ns, kw, left=0.0, right=0.0))
        kw_m = float(np.interp(m, t_ns, kw, left=0.0, right=0.0))
        kw_b = float(np.interp(b, t_ns, kw, left=0.0, right=0.0))
        avg = max(0.0, (kw_a + 4.0 * kw_m + kw_b) / 6.0)
        pv50[i] = avg * 0.5  # kWh in the 30-min slot
    # Step 2: optional PV10 blend.
    if pv10_weight and pv10_weight > 0.0:
        peak = float(pv50.max()) if pv50.size else 0.0
        if peak > 1e-9:
            i_norm = np.clip(pv50 / peak, 0.0, 1.0)
            ratio = pv10_min_ratio + (pv10_max_ratio - pv10_min_ratio) * np.sqrt(i_norm)
            pv10 = pv50 * ratio
            blended = (1.0 - pv10_weight) * pv50 + pv10_weight * pv10
        else:
            blended = pv50  # all-zero forecast, blend is a no-op
    else:
        blended = pv50
    # Step 3: apply the flat conservative derate.
    out[:] = blended * float(forecast_scale)
    return out


def plan_prices_per_slot(slot_starts, agile_df, fallback_p):
    """For each slot, return p/kWh by matching against agile_df['valid_from'/'valid_to'/'price_pence'].
    Falls back to flat ``fallback_p`` when no rate covers the slot."""
    out = np.full(len(slot_starts), float(fallback_p), dtype=float)
    if agile_df is None or len(agile_df) == 0:
        return out
    s = (agile_df.set_index('valid_from')['price_pence']
                 .astype(float).sort_index())
    if s.index.tz is None:
        s.index = s.index.tz_localize('UTC').tz_convert('Europe/London')
    else:
        s.index = s.index.tz_convert('Europe/London')
    aligned = s.reindex(slot_starts, method='pad')
    arr = aligned.to_numpy(dtype=float)
    mask = np.isfinite(arr)
    out[mask] = arr[mask]
    return out


def plan_export_prices_per_slot(slot_starts, agile_export_series, fallback_p):
    """``agile_export_series`` is the Series returned by ``fetch_agile_rates_series_utc``."""
    out = np.full(len(slot_starts), float(fallback_p), dtype=float)
    if agile_export_series is None or len(agile_export_series) == 0:
        return out
    s = agile_export_series.copy().astype(float).sort_index()
    if s.index.tz is None:
        s.index = s.index.tz_localize('UTC').tz_convert('Europe/London')
    else:
        s.index = s.index.tz_convert('Europe/London')
    aligned = s.reindex(slot_starts, method='pad')
    arr = aligned.to_numpy(dtype=float)
    mask = np.isfinite(arr)
    out[mask] = arr[mask]
    return out


def plan_load_per_slot(slot_starts, usage_profile_by_hour, base_load_kw=0.4):
    """Project the rigid-load profile across slots (kWh per 30 min). The usage profile
    coming from SmartAdvisor is a per-hour kWh-per-30-min figure; we just sample it.
    Heater/Tasmota carve-outs are handled separately by the caller."""
    out = np.zeros(len(slot_starts), dtype=float)
    floor = (base_load_kw or 0.4) * 0.5
    for i, t in enumerate(slot_starts):
        h = int(pd.Timestamp(t).hour)
        out[i] = max(floor, float(usage_profile_by_hour.get(h, floor)))
    return out


def pick_heater_windows(slot_starts, p_in, p_ex, solar_kwh,
                        heater_kw=_PLAN_HEATER_KW,
                        pre_morning_end_h=_PLAN_PRE_MORNING_END_H,
                        pre_morning_slots=_PLAN_PRE_MORNING_SLOTS,
                        day_block_h=_PLAN_DAY_BLOCK_H,
                        day_window=_PLAN_DAY_WINDOW):
    """Pick the heater schedule.

    Returns a dict with::
        morning_blocks : list of (start_idx, end_idx) — mandatory pre-7am, must run
        day_blocks     : list of (start_idx, end_idx) — chosen 4 h block (per day in horizon)
        alternates     : list of (net_cost_p, start_idx, end_idx) for the 4 h block (top 5)
        heater_kwh     : np.ndarray of length T, the per-slot kWh added by the heater
    """
    T = len(slot_starts)
    h_kwh = heater_kw * 0.5  # per-slot kWh
    morning_blocks = []
    used = np.zeros(T, dtype=bool)

    # Mandatory morning blocks: end at the next 07:00 boundary (and the day after).
    starts = pd.DatetimeIndex(slot_starts)
    for day_offset in range(2):
        target = starts[0].normalize() + pd.Timedelta(days=day_offset)
        target = target.replace(hour=pre_morning_end_h, minute=0)
        if target <= starts[0]:
            continue
        # Find the first slot whose start is >= target (= the first slot AFTER 07:00).
        end_idx = None
        for i in range(T):
            if starts[i] >= target:
                end_idx = i
                break
        if end_idx is None or end_idx < pre_morning_slots:
            continue
        a = end_idx - pre_morning_slots
        morning_blocks.append((a, end_idx))
        used[a:end_idx] = True

    # Daytime 4 h block: pick the cheapest contiguous window per day, scored by net cost
    # (cost of importing what solar can't cover) − (export sacrificed by self-consuming solar).
    block_n = day_block_h * 2
    cands_by_day = {}
    for i in range(T - block_n + 1):
        s_start = starts[i]
        s_end = starts[i + block_n - 1]
        if s_start.hour < day_window[0]:
            continue
        if s_end.hour >= day_window[1]:
            continue
        if s_start.day != s_end.day:
            continue
        if used[i:i + block_n].any():
            continue
        net = 0.0
        cov = 0.0
        for k in range(i, i + block_n):
            sk = solar_kwh[k]
            covered = min(h_kwh, sk)
            uncovered = h_kwh - covered
            sacrificed = covered  # solar that would otherwise have exported
            net += uncovered * p_in[k] - sacrificed * p_ex[k]
            cov += covered
        cands_by_day.setdefault(s_start.day, []).append((net, i, i + block_n, cov))

    day_blocks = []
    alternates = []
    for day, lst in cands_by_day.items():
        lst.sort(key=lambda x: x[0])
        best = lst[0]
        day_blocks.append((best[1], best[2]))
        for c in lst[:3]:
            alternates.append((c[0], c[1], c[2]))

    heater_kwh = np.zeros(T, dtype=float)
    for a, b in morning_blocks:
        heater_kwh[a:b] += h_kwh
    for a, b in day_blocks:
        heater_kwh[a:b] += h_kwh

    return {
        'morning_blocks': morning_blocks,
        'day_blocks': day_blocks,
        'alternates': sorted(alternates, key=lambda x: x[0])[:5],
        'heater_kwh': heater_kwh,
    }


def dp_battery_dispatch(load_kwh, solar_kwh, p_in, p_ex,
                        soc_now_kwh, capacity_kwh,
                        eta=0.90, max_kw=3.3,
                        soc_min_pct=10,
                        soc_export_min_pct=_PLAN_EXPORT_MIN_SOC,
                        export_margin_p=_PLAN_EXPORT_MARGIN_P,
                        throughput_penalty_p=_PLAN_THROUGHPUT_PENALTY_P,
                        bin_pct=_PLAN_BIN_PCT,
                        heater_kwh=None,
                        terminal_value_scale=1.0,
                        terminal_value_p_per_kwh=None,
                        allow_battery_export=True):
    """Dynamic programme over discretised battery SOC for a 30-min slot horizon.

    Returns ``{'actions': [...], 'total_cost_p': float, 'soc_pct_trace': [...]}``.

    Each action has::
        grid_in_kwh, grid_out_kwh, solar_to_load, solar_to_batt, solar_to_grid,
        batt_to_load, batt_to_grid, grid_to_batt, soc_after_kwh, slot_cost_p, d_soc_kwh

    ``terminal_value_p_per_kwh`` (optional) is the value (p/kWh) assigned to
    energy left in the battery at the end of the horizon. When ``None`` we use
    the mean import price across the horizon × ``sqrt(eta)`` (i.e. the value of
    that stored kWh once discharged through the inverter losses).
    ``terminal_value_scale`` then linearly scales that. Predbat's equivalent
    knob is ``metric_battery_value_scaling`` and defaults to 1.0.

    ``allow_battery_export`` (default True) is a hard kill switch on
    ``batt_to_grid``: when False, the DP refuses every transition that would
    force the battery to discharge into the grid, regardless of price. Solar
    export is unaffected. Pair with ``OptimiserTab.cb_allow_export`` so the
    planner only plans exports if the user has also enabled the discharge-
    schedule writeback path.
    """
    T = len(load_kwh)
    if heater_kwh is None:
        heater_kwh = np.zeros(T)
    # Round-trip efficiency η is split into sqrt(η) per direction, matching the rest of the codebase.
    eff = float(eta) ** 0.5
    max_hh = float(max_kw) * 0.5
    soc_min_kwh = capacity_kwh * (soc_min_pct / 100.0)
    soc_exp_min_kwh = capacity_kwh * (soc_export_min_pct / 100.0)

    n_bins = max(11, int(round(100.0 / bin_pct)) + 1)
    bin_kwh = capacity_kwh / (n_bins - 1)

    # Terminal value: without this, every SOC bin at t=T has cost 0 and the DP
    # prefers to empty the battery in the final slots even when tomorrow morning
    # is going to be just as expensive. Value 1 stored kWh at the average future
    # import price × discharge-side efficiency (so 1 kWh stored ≈ avoids buying
    # `eff` kWh later at mean price).
    if terminal_value_p_per_kwh is None:
        mean_p_in = float(np.mean(p_in)) if T > 0 else 0.0
        terminal_value_p_per_kwh = mean_p_in * eff
    terminal_value_p_per_kwh = float(terminal_value_p_per_kwh) * float(terminal_value_scale)

    INF = float('inf')
    cost = [[INF] * n_bins for _ in range(T + 1)]
    for b in range(n_bins):
        # Negative cost == positive value. SOC left at end-of-plan is worth
        # `b * bin_kwh * terminal_value_p_per_kwh` pence.
        cost[T][b] = -(b * bin_kwh) * terminal_value_p_per_kwh
    chosen = [[None] * n_bins for _ in range(T)]

    # Discretise the per-slot SOC delta into bin-multiples within the kW limit.
    max_bins_per_slot = int(np.floor(max_hh / bin_kwh + 1e-9))
    delta_bins = list(range(-max_bins_per_slot, max_bins_per_slot + 1))

    # Cheapest reachable (forward-looking) import price — used to gate exports.
    cheapest_future_in = np.full(T + 1, np.inf)
    for t in range(T - 1, -1, -1):
        cheapest_future_in[t] = min(cheapest_future_in[t + 1], p_in[t])

    for t in range(T - 1, -1, -1):
        L = float(load_kwh[t]) + float(heater_kwh[t])
        S = float(solar_kwh[t])
        pi = float(p_in[t])
        pe = float(p_ex[t])
        # Allow export only if it beats the cheapest reachable charge slot by ≥ margin
        # (so we don't sell now then have to buy back tomorrow at a higher price).
        export_allowed = (pe >= (cheapest_future_in[t + 1] if t + 1 < T else pi) + export_margin_p)
        for b in range(n_bins):
            soc = b * bin_kwh
            best = INF
            best_act = None
            best_nb = b
            for db in delta_bins:
                nb = b + db
                if nb < 0 or nb >= n_bins:
                    continue
                soc_next = nb * bin_kwh
                if soc_next < soc_min_kwh - 1e-9:
                    continue
                d = soc_next - soc                  # change in stored kWh
                solar_to_load = min(S, L)
                solar_surplus = S - solar_to_load
                load_residual = L - solar_to_load
                if d >= 0:
                    # Charging: solar fills first, grid tops up.
                    solar_to_batt = min(solar_surplus, d / eff)
                    grid_to_batt = (d - solar_to_batt * eff) / eff
                    grid_to_batt = max(0.0, grid_to_batt)
                    if grid_to_batt + load_residual > max_hh + 1e-6:
                        continue                   # grid-side AC limit
                    solar_to_grid = solar_surplus - solar_to_batt
                    if not export_allowed and solar_to_grid > 1e-9:
                        # Solar export is fine even if "export not allowed" gate is for battery,
                        # so leave solar_to_grid as-is. (Battery export is the part we gate.)
                        pass
                    grid_in = load_residual + grid_to_batt
                    grid_out = solar_to_grid
                    batt_to_load = 0.0
                    batt_to_grid = 0.0
                else:
                    out_kwh = -d * eff             # usable energy out of battery
                    if out_kwh > max_hh + 1e-6:
                        continue
                    batt_to_load = min(out_kwh, load_residual)
                    batt_to_grid = out_kwh - batt_to_load
                    if batt_to_grid > 1e-9:
                        if not allow_battery_export:
                            continue
                        if not export_allowed:
                            continue
                        if soc_next < soc_exp_min_kwh - 1e-9:
                            continue
                    grid_to_load = max(0.0, load_residual - batt_to_load)
                    grid_in = grid_to_load
                    grid_out = solar_surplus + batt_to_grid
                    grid_to_batt = 0.0
                    solar_to_batt = 0.0
                    solar_to_grid = solar_surplus
                throughput = abs(d) * throughput_penalty_p
                slot_cost = grid_in * pi - grid_out * pe + throughput
                total = slot_cost + cost[t + 1][nb]
                if total < best:
                    best = total
                    best_nb = nb
                    best_act = {
                        'grid_in_kwh': grid_in,
                        'grid_out_kwh': grid_out,
                        'solar_to_load': solar_to_load,
                        'solar_to_batt': solar_to_batt,
                        'solar_to_grid': solar_to_grid,
                        'batt_to_load': batt_to_load,
                        'batt_to_grid': batt_to_grid,
                        'grid_to_batt': grid_to_batt,
                        'soc_after_kwh': soc_next,
                        'slot_cost_p': slot_cost,
                        'd_soc_kwh': d,
                    }
            cost[t][b] = best
            chosen[t][b] = (best_nb, best_act)

    b0 = int(round(soc_now_kwh / bin_kwh))
    b0 = max(0, min(n_bins - 1, b0))
    actions = []
    soc_pct_trace = [b0 * bin_kwh / capacity_kwh * 100.0]
    b = b0
    for t in range(T):
        sel = chosen[t][b]
        if sel is None or sel[1] is None:
            actions.append({
                'grid_in_kwh': float(load_kwh[t] + heater_kwh[t]),
                'grid_out_kwh': 0.0,
                'solar_to_load': 0.0, 'solar_to_batt': 0.0, 'solar_to_grid': 0.0,
                'batt_to_load': 0.0, 'batt_to_grid': 0.0, 'grid_to_batt': 0.0,
                'soc_after_kwh': b * bin_kwh,
                'slot_cost_p': float((load_kwh[t] + heater_kwh[t]) * p_in[t]),
                'd_soc_kwh': 0.0,
            })
            soc_pct_trace.append(b * bin_kwh / capacity_kwh * 100.0)
            continue
        nb, act = sel
        actions.append(act)
        soc_pct_trace.append(act['soc_after_kwh'] / capacity_kwh * 100.0)
        b = nb

    # `cost[0][b0]` is the DP objective = raw spend − terminal value of leftover
    # SOC. Report the raw spend (sum of per-slot real costs) under the existing
    # `total_cost_p` key for backward-compat, and surface the two extra figures.
    raw_spend_p = float(sum(a.get('slot_cost_p', 0.0) for a in actions))
    final_soc_kwh = float(actions[-1]['soc_after_kwh']) if actions else float(soc_now_kwh)
    terminal_value_p = final_soc_kwh * terminal_value_p_per_kwh
    return {
        'actions': actions,
        'total_cost_p': raw_spend_p,
        'objective_p': cost[0][b0],
        'terminal_value_p': terminal_value_p,
        'terminal_value_p_per_kwh': terminal_value_p_per_kwh,
        'soc_pct_trace': soc_pct_trace,
        'eff': eff,
        'capacity_kwh': capacity_kwh,
    }


def collapse_grid_charge_to_periods(slot_starts, actions, max_periods=3, min_kwh_per_slot=0.05):
    """Group contiguous slots with ``grid_to_batt > min_kwh_per_slot`` into ≤ ``max_periods`` windows.
    Returns list of (start_time, end_time, total_kwh). The end_time is the END of the last slot."""
    runs = []
    cur = None
    for i, a in enumerate(actions):
        kwh = a.get('grid_to_batt', 0.0)
        if kwh > min_kwh_per_slot:
            if cur is None:
                cur = [i, i + 1, kwh]
            else:
                cur[1] = i + 1
                cur[2] += kwh
        else:
            if cur is not None:
                runs.append(tuple(cur))
                cur = None
    if cur is not None:
        runs.append(tuple(cur))

    if len(runs) > max_periods:
        runs.sort(key=lambda r: r[2], reverse=True)
        runs = runs[:max_periods]
        runs.sort(key=lambda r: r[0])

    out = []
    for a, b, kwh in runs:
        st = pd.Timestamp(slot_starts[a])
        en = pd.Timestamp(slot_starts[b - 1]) + pd.Timedelta(minutes=30)
        out.append((st, en, kwh))
    return out


def collapse_grid_export_runs(slot_starts, actions, min_kwh_per_slot=0.05):
    """Same idea but for slots where the battery is discharging to grid."""
    runs = []
    cur = None
    for i, a in enumerate(actions):
        kwh = a.get('batt_to_grid', 0.0)
        if kwh > min_kwh_per_slot:
            if cur is None:
                cur = [i, i + 1, kwh]
            else:
                cur[1] = i + 1
                cur[2] += kwh
        else:
            if cur is not None:
                runs.append(tuple(cur))
                cur = None
    if cur is not None:
        runs.append(tuple(cur))
    out = []
    for a, b, kwh in runs:
        st = pd.Timestamp(slot_starts[a])
        en = pd.Timestamp(slot_starts[b - 1]) + pd.Timedelta(minutes=30)
        out.append((st, en, kwh))
    return out


__all__ = [n for n in globals() if not n.startswith('__')]
