"""
Align Octopus Agile half-hour rates to consumption timestamps.
"""
from __future__ import annotations

import pandas as pd


def _align_agile_rates_to_consumption_index(consumption_index, agile_series, flat_pence):
    """Map each half-hour consumption timestamp to the import Agile rate in force (backward as-of)."""
    if agile_series is None or len(agile_series) == 0:
        return pd.Series(float(flat_pence), index=consumption_index)
    ix = consumption_index.sort_values()
    left = pd.DataFrame({'t': ix})
    right = agile_series.sort_index().reset_index()
    if right.shape[1] != 2:
        return pd.Series(float(flat_pence), index=consumption_index)
    right.columns = ['t', 'price']
    merged = pd.merge_asof(left, right, on='t', direction='backward')
    vals = merged['price'].fillna(float(flat_pence))
    ser_sorted = pd.Series(vals.values, index=ix)
    return ser_sorted.reindex(consumption_index)


def _daily_cheap_mask(slot_prices, quantile=0.35):
    """Per local (Europe/London) calendar day, slots at or below this quantile count as 'cheap' for grid charging."""
    if slot_prices.empty:
        return pd.Series(False, index=slot_prices.index)
    idx = slot_prices.index
    if idx.tz is None:
        idx_l = idx.tz_localize('UTC', ambiguous='infer', nonexistent='shift_forward')
    else:
        idx_l = idx
    idx_l = idx_l.tz_convert('Europe/London')
    day = idx_l.normalize()
    df = pd.DataFrame({'p': slot_prices.values, 'day': day}, index=slot_prices.index)
    thr = df.groupby('day')['p'].transform(lambda x: x.quantile(quantile))
    return df['p'] <= thr
