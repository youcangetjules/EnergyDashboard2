"""
Energy Dashboard — `planner/shadow.py`.

Pure logic for the Shadow Trial: replaying a frozen optimiser plan against
the day that actually happened, plus the self-consumption baseline and the
capture-ratio scoring used to compare controllers fairly across days.

Nothing in this module talks to the network, the database, or Qt.
"""
from __future__ import annotations

from energy_dashboard.deps import *


def day_slot_starts_london(day_date) -> pd.DatetimeIndex:
    """All 30-min slot starts of one London calendar day (46/48/50 on DST days)."""
    d = pd.Timestamp(day_date)
    nd = d + pd.Timedelta(days=1)
    # Localise each midnight separately: adding 1 day to a tz-aware stamp
    # adds 24 absolute hours, which is wrong on the 23/25-hour DST days.
    start = pd.Timestamp(year=d.year, month=d.month, day=d.day, tz='Europe/London')
    end = pd.Timestamp(year=nd.year, month=nd.month, day=nd.day, tz='Europe/London')
    return pd.date_range(start, end, freq='30min', inclusive='left')


def slot_key_utc(ts) -> str:
    """Canonical UTC 'YYYY-MM-DD HH:MM' key for a slot start (JSON/DB safe)."""
    return pd.Timestamp(ts).tz_convert('UTC').strftime('%Y-%m-%d %H:%M')


def bucket_power_to_slot_kwh(df: "pl.DataFrame", slot_starts,
                             value_col: str) -> tuple[np.ndarray, np.ndarray]:
    """Average sampled power (kW) into per-slot energy (kWh per 30 min).

    ``df`` needs a UTC ``timestamp`` column plus ``value_col``. Returns
    ``(kwh, has_data)`` arrays aligned with ``slot_starts``; slots with no
    samples get 0.0 kWh and ``has_data=False`` so the caller can decide how
    to fill them.
    """
    n = len(slot_starts)
    if df is None or df.is_empty() or value_col not in df.columns:
        return np.zeros(n), np.zeros(n, dtype=bool)
    pdf = df.select('timestamp', value_col).to_pandas().dropna()
    if pdf.empty:
        return np.zeros(n), np.zeros(n, dtype=bool)
    ts = pd.to_datetime(pdf['timestamp'], utc=True)
    starts_utc = pd.DatetimeIndex(
        [pd.Timestamp(t).tz_convert('UTC') for t in slot_starts])
    end_utc = starts_utc[-1] + pd.Timedelta(minutes=30)
    keep = (ts >= starts_utc[0]) & (ts < end_utc)
    ts = ts[keep]
    vals = pdf[value_col].to_numpy(dtype=float)[np.asarray(keep)]
    idx = starts_utc.searchsorted(ts, side='right') - 1
    sums = np.zeros(n)
    counts = np.zeros(n)
    for i, v in zip(idx, vals):
        if 0 <= i < n:
            sums[i] += v
            counts[i] += 1
    mean_kw = np.divide(sums, counts, out=np.zeros(n), where=counts > 0)
    return mean_kw * 0.5, counts > 0


def simulate_day_execution(load_kwh, solar_kwh, p_in, p_ex,
                           charge_kwh, export_kwh,
                           soc_start_kwh, capacity_kwh,
                           eta=0.90, max_kw=3.3, soc_min_pct=10,
                           soc_export_min_pct=30):
    """Execute a schedule against realised data; return cash cost + trace.

    Models how a MIX inverter runs a written schedule:

    - Slots with ``charge_kwh > 0`` are AC-charge windows: the battery
      charges from the grid at the planned energy (capped by power/room),
      load is served PV-first then grid, and the battery does not discharge.
    - Slots with ``export_kwh > 0`` are forced-discharge windows: the
      battery serves residual load then exports the planned energy, down to
      the export SOC floor.
    - All other slots are load-first self-consumption: PV to load, surplus
      to battery then grid, deficit from battery (above floor) then grid.

    ``charge_kwh``/``export_kwh`` are AC-side kWh per slot (the DP action
    fields ``grid_to_batt`` / ``batt_to_grid``). Pass all-zeros for the
    self-consumption baseline. Costs are pure cash (p): import minus export
    revenue, no wear tax — comparable with a metered bill.
    """
    T = len(load_kwh)
    eff = float(eta) ** 0.5
    max_hh = float(max_kw) * 0.5
    soc_min = float(capacity_kwh) * float(soc_min_pct) / 100.0
    soc_exp_min = float(capacity_kwh) * float(soc_export_min_pct) / 100.0
    soc = min(max(float(soc_start_kwh), 0.0), float(capacity_kwh))
    cost = 0.0
    grid_in_total = 0.0
    grid_out_total = 0.0
    soc_trace = [soc]
    for i in range(T):
        L = max(0.0, float(load_kwh[i]))
        S = max(0.0, float(solar_kwh[i]))
        grid_in = 0.0
        grid_out = 0.0
        solar_to_load = min(S, L)
        surplus = S - solar_to_load
        residual = L - solar_to_load
        want_charge = max(0.0, float(charge_kwh[i]))
        want_export = max(0.0, float(export_kwh[i]))
        if want_charge > 1e-9:
            room = max(0.0, capacity_kwh - soc) / eff
            ch = min(want_charge, max_hh, room)
            soc += ch * eff
            grid_in += ch + residual
            room2 = max(0.0, capacity_kwh - soc) / eff
            ch_solar = min(surplus, max(0.0, max_hh - ch), room2)
            soc += ch_solar * eff
            grid_out += surplus - ch_solar
        elif want_export > 1e-9:
            avail_ac = max(0.0, soc - soc_min) * eff
            to_load = min(residual, max_hh, avail_ac)
            soc -= to_load / eff
            grid_in += residual - to_load
            exp_avail_ac = max(0.0, soc - soc_exp_min) * eff
            out = min(want_export, max(0.0, max_hh - to_load), exp_avail_ac)
            soc -= out / eff
            grid_out += surplus + out
        else:
            room = max(0.0, capacity_kwh - soc) / eff
            ch_solar = min(surplus, max_hh, room)
            soc += ch_solar * eff
            grid_out += surplus - ch_solar
            avail_ac = max(0.0, soc - soc_min) * eff
            dis = min(residual, max_hh, avail_ac)
            soc -= dis / eff
            grid_in += residual - dis
        cost += grid_in * float(p_in[i]) - grid_out * float(p_ex[i])
        grid_in_total += grid_in
        grid_out_total += grid_out
        soc_trace.append(soc)
    return {
        'total_cost_p': cost,
        'grid_in_kwh': grid_in_total,
        'grid_out_kwh': grid_out_total,
        'soc_end_kwh': soc,
        'soc_trace_kwh': soc_trace,
    }


def capture_ratio(baseline_p, controller_p, perfect_p):
    """Fraction of the theoretically available savings a controller captured.

    Returns None when the denominator is degenerate (perfect ~= baseline:
    nothing to be saved that day, so the ratio is meaningless).
    """
    try:
        denom = float(baseline_p) - float(perfect_p)
        if abs(denom) < 1.0:  # < 1p of available savings
            return None
        return (float(baseline_p) - float(controller_p)) / denom
    except (TypeError, ValueError):
        return None


__all__ = [n for n in globals() if not n.startswith('__')]
