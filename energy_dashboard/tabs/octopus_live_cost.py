"""Cost for the Octopus Live tab: spot price × energy, tuned from settled days.

The live stream is close to real time. Octopus's half-hour meter — the
readings a bill is built from — usually arrives later and does not match
that stream exactly. For each completed day where both exist, this module
takes (Octopus meter cost) / (live cost). The median of those ratios scales
today's live estimate. Days Octopus has already metered stay as stated.
The scaled figure is an estimate. Standing charge is not included.
"""
from __future__ import annotations

from statistics import median

import pandas as pd

from energy_dashboard.utils.agile_rates import _align_agile_rates_to_consumption_index

# A settled day needs this many hours of slots before it may teach the scale.
COMPLETE_HOURS = 18.0
# Ignore a side of the bill below this when forming a ratio (noise).
MIN_RATIO_PENCE = 30.0
SCALE_MIN = 0.50
SCALE_MAX = 1.50
HISTORY_DAYS = 14
# How long a fetched price + meter bundle may be reused.
COST_REFRESH_S = 20 * 60

_LONDON = "Europe/London"


def to_london(timestamps):
    """Timezone-aware Europe/London timestamps. Naive values are London wall time."""
    ts = pd.to_datetime(timestamps)
    if isinstance(ts, pd.Series):
        if ts.dt.tz is None:
            return ts.dt.tz_localize(
                _LONDON, ambiguous="infer", nonexistent="shift_forward",
            )
        return ts.dt.tz_convert(_LONDON)
    if getattr(ts, "tz", None) is None:
        return ts.tz_localize(_LONDON, ambiguous="infer", nonexistent="shift_forward")
    return ts.tz_convert(_LONDON)


def _as_utc_index(timestamps) -> pd.DatetimeIndex:
    london = to_london(pd.Series(pd.to_datetime(timestamps)))
    return pd.DatetimeIndex(london.dt.tz_convert("UTC"))


def _floor_sum(df, slot_minutes: int, value_col: str) -> pd.DataFrame:
    cols = ["interval_start", value_col]
    if df is None or getattr(df, "empty", True) or value_col not in df.columns:
        return pd.DataFrame(columns=cols)
    out = df[["interval_start", value_col]].copy()
    out["interval_start"] = to_london(out["interval_start"])
    out[value_col] = pd.to_numeric(out[value_col], errors="coerce").fillna(0.0)
    slot = out["interval_start"].dt.floor(f"{int(slot_minutes)}min")
    grouped = (
        out.assign(interval_start=slot)
        .groupby("interval_start", as_index=False)[value_col]
        .sum()
        .sort_values("interval_start")
        .reset_index(drop=True)
    )
    return grouped


def energy_slots_from_frames(imp_df, exp_df, slot_minutes: int) -> tuple[pd.DataFrame, str]:
    """Import and export kWh per slot.

    Prefers each meter's interval energy. If that is missing, falls back to
    signed live power × slot length (an estimate — the caller must say so).
    Returns (frame, source) where source is ``meter``, ``demand``, or
    ``meter+demand-export``.
    """
    cols = ["interval_start", "import_kwh", "export_kwh", "slot_hours"]
    slot_minutes = max(1, int(slot_minutes))
    hours = slot_minutes / 60.0
    imp = _floor_sum(imp_df, slot_minutes, "consumption").rename(
        columns={"consumption": "import_kwh"},
    )
    exp = _floor_sum(exp_df, slot_minutes, "consumption").rename(
        columns={"consumption": "export_kwh"},
    )
    imp_total = float(imp["import_kwh"].sum()) if not imp.empty else 0.0
    exp_total = float(exp["export_kwh"].sum()) if not exp.empty else 0.0
    demand = _demand_kwh_slots(imp_df, slot_minutes)

    source = "meter"
    if imp_total < 1e-9 and exp_total < 1e-9 and not demand.empty:
        merged = demand.copy()
        source = "demand"
    elif exp_total < 1e-9 and not demand.empty and float(demand["export_kwh"].sum()) > 1e-9:
        # Import meter has energy; export meter does not. Estimate export
        # from negative live power so the credit is not silently missing.
        if imp.empty:
            merged = demand.copy()
            source = "demand"
        else:
            merged = imp.merge(demand[["interval_start", "export_kwh"]], on="interval_start", how="outer")
            source = "meter+demand-export"
    elif imp.empty and exp.empty:
        return pd.DataFrame(columns=cols), source
    elif imp.empty:
        merged = exp.copy()
        merged["import_kwh"] = 0.0
    elif exp.empty:
        merged = imp.copy()
        merged["export_kwh"] = 0.0
    else:
        merged = imp.merge(exp, on="interval_start", how="outer")

    merged["import_kwh"] = pd.to_numeric(merged["import_kwh"], errors="coerce").fillna(0.0)
    merged["export_kwh"] = pd.to_numeric(merged["export_kwh"], errors="coerce").fillna(0.0)
    merged["slot_hours"] = hours
    merged = merged.sort_values("interval_start").reset_index(drop=True)
    return merged[cols], source


def _demand_kwh_slots(imp_df, slot_minutes: int) -> pd.DataFrame:
    cols = ["interval_start", "import_kwh", "export_kwh"]
    if imp_df is None or getattr(imp_df, "empty", True) or "demand_w" not in imp_df.columns:
        return pd.DataFrame(columns=cols)
    out = imp_df[["interval_start", "demand_w"]].copy()
    out["interval_start"] = to_london(out["interval_start"])
    out["demand_w"] = pd.to_numeric(out["demand_w"], errors="coerce")
    out = out.dropna(subset=["demand_w"])
    if out.empty:
        return pd.DataFrame(columns=cols)
    slot = out["interval_start"].dt.floor(f"{int(slot_minutes)}min")
    grouped = (
        out.assign(interval_start=slot)
        .groupby("interval_start", as_index=False)["demand_w"]
        .mean()
    )
    hours = slot_minutes / 60.0
    w = grouped["demand_w"]
    grouped["import_kwh"] = w.clip(lower=0) * hours / 1000.0
    grouped["export_kwh"] = (-w.clip(upper=0)) * hours / 1000.0
    return grouped[cols]


def rest_half_hour_slots(imp_df, exp_df) -> pd.DataFrame:
    """Octopus half-hour meter kWh (what the bill uses), London timestamps."""
    imp = _floor_sum(imp_df, 30, "consumption").rename(columns={"consumption": "import_kwh"})
    exp = _floor_sum(exp_df, 30, "consumption").rename(columns={"consumption": "export_kwh"})
    cols = ["interval_start", "import_kwh", "export_kwh", "slot_hours"]
    if imp.empty and exp.empty:
        return pd.DataFrame(columns=cols)
    if imp.empty:
        merged = exp.copy()
        merged["import_kwh"] = 0.0
    elif exp.empty:
        merged = imp.copy()
        merged["export_kwh"] = 0.0
    else:
        merged = imp.merge(exp, on="interval_start", how="outer")
    merged["import_kwh"] = pd.to_numeric(merged["import_kwh"], errors="coerce").fillna(0.0)
    merged["export_kwh"] = pd.to_numeric(merged["export_kwh"], errors="coerce").fillna(0.0)
    merged["slot_hours"] = 0.5
    return merged.sort_values("interval_start").reset_index(drop=True)[cols]


def _rates_utc(rates: pd.Series | None) -> pd.Series:
    if rates is None or len(rates) == 0:
        return pd.Series(dtype=float)
    ser = pd.Series(rates).astype(float).sort_index()
    idx = pd.DatetimeIndex(pd.to_datetime(ser.index))
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    ser.index = idx
    return ser[~ser.index.duplicated(keep="last")]


def price_slots(slots, imp_rates, exp_rates, flat_import: float, flat_export: float) -> pd.DataFrame:
    """Add import_pence, export_pence, net_pence. Flat p/kWh fills any gap."""
    if slots is None or slots.empty:
        return pd.DataFrame(columns=[
            "interval_start", "import_kwh", "export_kwh", "slot_hours",
            "import_pence", "export_pence", "net_pence",
        ])
    out = slots.copy()
    utc = _as_utc_index(out["interval_start"])
    p_imp = _align_agile_rates_to_consumption_index(utc, _rates_utc(imp_rates), float(flat_import))
    p_exp = _align_agile_rates_to_consumption_index(utc, _rates_utc(exp_rates), float(flat_export))
    out["import_pence"] = out["import_kwh"].to_numpy(dtype=float) * p_imp.to_numpy(dtype=float)
    out["export_pence"] = out["export_kwh"].to_numpy(dtype=float) * p_exp.to_numpy(dtype=float)
    out["net_pence"] = out["import_pence"] - out["export_pence"]
    return out


def _day_key(timestamps) -> pd.Series:
    ts = to_london(timestamps)
    return ts.dt.normalize()


def summarise_days(priced, today, *, export_known: bool = True) -> list[dict]:
    """Per London day totals. ``complete`` is a finished day with enough hours."""
    if priced is None or priced.empty:
        return []
    df = priced.copy()
    df["_day"] = _day_key(df["interval_start"])
    today_ts = pd.Timestamp(today)
    if today_ts.tzinfo is None:
        today_ts = today_ts.tz_localize(_LONDON)
    else:
        today_ts = today_ts.tz_convert(_LONDON)
    today_ts = today_ts.normalize()
    rows = []
    for day, part in df.groupby("_day", sort=True):
        hours = float(pd.to_numeric(part["slot_hours"], errors="coerce").fillna(0).sum())
        day_ts = pd.Timestamp(day)
        if day_ts.tzinfo is None:
            day_ts = day_ts.tz_localize(_LONDON)
        complete = bool(day_ts.normalize() < today_ts and hours + 1e-9 >= COMPLETE_HOURS)
        rows.append({
            "date": day_ts.strftime("%Y-%m-%d"),
            "import_pence": float(part["import_pence"].sum()),
            "export_pence": float(part["export_pence"].sum()) if export_known else None,
            "import_kwh": float(part["import_kwh"].sum()),
            "export_kwh": float(part["export_kwh"].sum()) if export_known else None,
            "hours_covered": hours,
            "complete": complete,
            "export_known": bool(export_known),
        })
    return rows


def update_history(history: dict | None, live_days: list[dict], stated_days: list[dict], today) -> dict:
    """Fold completed days into the small remembered table. Partials do not wipe a full day."""
    out = {str(k): dict(v) for k, v in (history or {}).items() if isinstance(v, dict)}
    for day in live_days:
        if not day.get("complete"):
            continue
        rec = out.setdefault(day["date"], {})
        rec["live_import_pence"] = round(float(day["import_pence"]), 4)
        if day.get("export_known", True) and day.get("export_pence") is not None:
            rec["live_export_pence"] = round(float(day["export_pence"]), 4)
            rec["live_export_known"] = True
        rec["live_complete"] = True
    for day in stated_days:
        if not day.get("complete"):
            continue
        rec = out.setdefault(day["date"], {})
        rec["stated_import_pence"] = round(float(day["import_pence"]), 4)
        rec["stated_complete"] = True
        if day.get("export_known", True) and day.get("export_pence") is not None:
            rec["stated_export_pence"] = round(float(day["export_pence"]), 4)
            rec["stated_export_known"] = True
    today_ts = pd.Timestamp(today)
    if today_ts.tzinfo is None:
        today_ts = today_ts.tz_localize(_LONDON)
    cutoff = (today_ts.normalize() - pd.Timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
    return {k: v for k, v in out.items() if k >= cutoff}


def _clamp_scale(raw: float) -> tuple[float, bool]:
    clamped = min(SCALE_MAX, max(SCALE_MIN, float(raw)))
    return clamped, abs(clamped - float(raw)) > 1e-9


def scales_from_history(history: dict | None) -> dict:
    """Median stated/live ratio. Missing side stays ×1 (not tuned)."""
    imp_ratios = []
    exp_ratios = []
    days = []
    for date in sorted((history or {}).keys()):
        rec = history[date] or {}
        if not rec.get("live_complete") or not rec.get("stated_complete"):
            continue
        row = {"date": date}
        li = rec.get("live_import_pence")
        si = rec.get("stated_import_pence")
        if li is not None and si is not None and float(li) >= MIN_RATIO_PENCE:
            row["import_ratio"] = float(si) / float(li)
            row["stated_import_pence"] = float(si)
            row["live_import_pence"] = float(li)
            imp_ratios.append(row["import_ratio"])
        if rec.get("live_export_known") and rec.get("stated_export_known"):
            le = rec.get("live_export_pence")
            se = rec.get("stated_export_pence")
            if le is not None and se is not None and float(le) >= MIN_RATIO_PENCE:
                row["export_ratio"] = float(se) / float(le)
                row["stated_export_pence"] = float(se)
                row["live_export_pence"] = float(le)
                exp_ratios.append(row["export_ratio"])
        if "import_ratio" in row or "export_ratio" in row:
            days.append(row)

    def _side(ratios):
        if not ratios:
            return 1.0, None, False, False
        raw = float(median(ratios))
        scale, was_clamped = _clamp_scale(raw)
        return scale, raw, True, was_clamped

    si, ri, ti, ci = _side(imp_ratios)
    se, re, te, ce = _side(exp_ratios)
    return {
        "scale_import": si,
        "scale_export": se,
        "raw_import": ri,
        "raw_export": re,
        "tuned_import": ti,
        "tuned_export": te,
        "import_clamped": ci,
        "export_clamped": ce,
        "days": days,
    }


def compose_cost_view(
    live_slots,
    stated_slots,
    imp_rates,
    exp_rates,
    flat_import: float,
    flat_export: float,
    scales: dict,
    now,
    view_start,
    view_end,
    *,
    export_known: bool = True,
) -> dict:
    """Window of money slots.

    Completed time that Octopus has metered uses that meter × the spot price.
    Today uses the live energy × the same price, multiplied by the learned
    scales. ``gbp_per_h`` is the slot's net money spread over the slot length
    (positive = paying for import, negative = export credit).
    """
    empty = {
        "slots": pd.DataFrame(),
        "today": None,
        "window": None,
        "days": [],
    }
    live_p = price_slots(live_slots, imp_rates, exp_rates, flat_import, flat_export)
    stated_p = price_slots(stated_slots, imp_rates, exp_rates, flat_import, flat_export)
    now_ts = pd.Timestamp(now)
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize(_LONDON)
    else:
        now_ts = now_ts.tz_convert(_LONDON)
    today = now_ts.normalize()

    tuned = bool(scales.get("tuned_import") or scales.get("tuned_export"))
    parts = []
    stated_keep = pd.DataFrame()
    if not stated_p.empty:
        stated_p = stated_p.copy()
        stated_p["_day"] = _day_key(stated_p["interval_start"])
        stated_p["_bucket"] = stated_p["interval_start"].dt.floor("30min")
        stated_keep = stated_p[stated_p["_day"] < today].copy()

    if not live_p.empty:
        live_p = live_p.copy()
        live_p["_day"] = _day_key(live_p["interval_start"])
        live_p["_bucket"] = live_p["interval_start"].dt.floor("30min")
        if not stated_keep.empty and export_known:
            keys = stated_keep[["_day", "_bucket"]].drop_duplicates()
            keys["_settled"] = True
            live_p = live_p.merge(keys, on=["_day", "_bucket"], how="left")
            live_p = live_p[live_p["_settled"].isna()].drop(columns=["_settled"])
        elif not stated_keep.empty:
            # Import meter answered; export meter did not. One settled row per
            # half hour: Octopus import cost, plus the live export credit summed
            # across the live slots in that half hour (not copied onto each one).
            imp_only = (
                stated_keep.groupby(["_day", "_bucket"], as_index=False)
                .agg(import_pence=("import_pence", "sum"), import_kwh=("import_kwh", "sum"))
            )
            live_p = live_p.merge(imp_only, on=["_day", "_bucket"], how="left", suffixes=("", "_stated"))
            hit = live_p["import_pence_stated"].notna() & (live_p["_day"] < today)
            settled_live = live_p.loc[hit]
            if not settled_live.empty:
                folded = (
                    settled_live.groupby(["_day", "_bucket"], as_index=False)
                    .agg(
                        export_pence=("export_pence", "sum"),
                        export_kwh=("export_kwh", "sum"),
                        interval_start=("_bucket", "min"),
                        slot_hours=("slot_hours", "sum"),
                    )
                )
                folded = folded.merge(imp_only, on=["_day", "_bucket"], how="left")
                folded["slot_hours"] = 0.5
                folded["basis_overlay"] = "settled"
                live_p = live_p.loc[~hit].drop(
                    columns=["import_pence_stated", "import_kwh_stated"], errors="ignore",
                )
                live_p = pd.concat([live_p, folded], ignore_index=True)
            else:
                live_p = live_p.drop(
                    columns=["import_pence_stated", "import_kwh_stated"], errors="ignore",
                )
        today_mask = live_p["_day"] == today
        if bool(today_mask.any()):
            live_p.loc[today_mask, "import_pence"] = (
                live_p.loc[today_mask, "import_pence"] * float(scales.get("scale_import", 1.0))
            )
            live_p.loc[today_mask, "export_pence"] = (
                live_p.loc[today_mask, "export_pence"] * float(scales.get("scale_export", 1.0))
            )
        live_p["net_pence"] = live_p["import_pence"] - live_p["export_pence"]
        if "basis_overlay" not in live_p.columns:
            live_p["basis_overlay"] = pd.NA
        settled_row = live_p["basis_overlay"] == "settled"
        live_p["basis"] = "estimated"
        live_p.loc[today_mask, "basis"] = "tuned" if tuned else "estimated"
        live_p.loc[settled_row, "basis"] = "settled"
        parts.append(live_p.drop(columns=["_day", "_bucket", "basis_overlay"], errors="ignore"))

    if export_known and not stated_keep.empty:
        stated_keep = stated_keep.drop(columns=["_day", "_bucket"])
        stated_keep["basis"] = "settled"
        parts.append(stated_keep)

    if not parts:
        return empty
    out = pd.concat(parts, ignore_index=True)
    out["interval_start"] = to_london(out["interval_start"])
    start = pd.Timestamp(view_start)
    end = pd.Timestamp(view_end)
    if start.tzinfo is None:
        start = start.tz_localize(_LONDON)
    else:
        start = start.tz_convert(_LONDON)
    if end.tzinfo is None:
        end = end.tz_localize(_LONDON)
    else:
        end = end.tz_convert(_LONDON)
    out = out[(out["interval_start"] >= start) & (out["interval_start"] <= end)]
    if out.empty:
        return empty
    out = out.sort_values("interval_start").reset_index(drop=True)
    hours = pd.to_numeric(out["slot_hours"], errors="coerce").replace(0, pd.NA)
    out["gbp_per_h"] = (out["net_pence"] / 100.0) / hours
    out["cum_import_gbp"] = _cumsum_gbp(out["import_pence"], out["interval_start"])
    out["cum_export_gbp"] = _cumsum_gbp(out["export_pence"], out["interval_start"])
    out["cum_net_gbp"] = out["cum_import_gbp"] - out["cum_export_gbp"]

    def _pack(part, basis: str):
        if part is None or part.empty:
            return None
        return {
            "import_pence": float(part["import_pence"].sum()),
            "export_pence": float(part["export_pence"].sum()),
            "net_pence": float(part["net_pence"].sum()),
            "basis": basis,
        }

    out["_day"] = _day_key(out["interval_start"])
    day_rows = []
    for day, part in out.groupby("_day", sort=True):
        bases = set(part["basis"].astype(str))
        if bases == {"settled"}:
            basis = "settled"
        elif "tuned" in bases:
            basis = "tuned"
        elif "settled" in bases:
            basis = "mixed"
        else:
            basis = "estimated"
        packed = _pack(part, basis)
        packed["date"] = pd.Timestamp(day).strftime("%Y-%m-%d")
        day_rows.append(packed)
    today_part = out[out["_day"] == today]
    window_basis = "settled" if set(out["basis"]) == {"settled"} else "mixed"
    return {
        "slots": out.drop(columns=["_day"]),
        "today": _pack(today_part, "tuned" if (not today_part.empty and (today_part["basis"] == "tuned").any()) else "estimated"),
        "window": _pack(out, window_basis),
        "days": day_rows,
        "export_known": export_known,
    }


def _cumsum_gbp(pence, timestamps) -> pd.Series:
    s = pd.to_numeric(pd.Series(pence), errors="coerce").fillna(0.0) / 100.0
    day = _day_key(timestamps)
    return s.groupby(day.values, sort=False).cumsum()


def summary_lines(
    *,
    rates_source: str,
    scales: dict,
    model: dict,
    energy_source: str,
) -> list[str]:
    """Plain-English notes for the live summary box."""
    lines = []
    if rates_source == "agile":
        lines.append(
            "Prices: Agile spot rate for each half hour, including VAT "
            "(import and export tariffs from Forecasts / Setup)."
        )
    elif rates_source == "database":
        lines.append(
            "Prices: Agile spot rates already stored in the database. "
            "The live tariff request did not answer."
        )
    else:
        lines.append(
            "Prices: flat p/kWh from Setup. Agile spot rates were not available, "
            "so this is not a spot-price cost."
        )
    lines.append("Standing charge is not included — this is the unit energy only.")
    if energy_source == "demand":
        lines.append(
            "Interval energy was missing, so kWh is power × time from the live "
            "demand reading. That is an estimate, labelled as such."
        )
    elif energy_source == "meter+demand-export":
        lines.append(
            "Import energy is the live meter. Export energy is estimated from "
            "negative live power because the export stream had no interval energy."
        )
    else:
        lines.append(
            "Energy is the live meter's interval reading, priced at the spot rate. "
            "It is not yet the half-hour total Octopus will bill."
        )

    today = (model or {}).get("today")
    if today:
        if today["basis"] == "tuned":
            how = "estimated, tuned from settled Octopus days"
        else:
            how = "estimated, not tuned yet"
        lines.append(
            f"Today so far ({how}): import £{today['import_pence'] / 100:.2f}, "
            f"export credit £{today['export_pence'] / 100:.2f}, "
            f"net £{today['net_pence'] / 100:.2f}."
        )
    window = (model or {}).get("window")
    if window:
        lines.append(
            f"This window: import £{window['import_pence'] / 100:.2f}, "
            f"export credit £{window['export_pence'] / 100:.2f}, "
            f"net £{window['net_pence'] / 100:.2f}."
        )

    if scales.get("tuned_import") or scales.get("tuned_export"):
        lines.append(
            f"Tuning ×{scales['scale_import']:.3f} on import and "
            f"×{scales['scale_export']:.3f} on export. "
            "Each is the median of (Octopus half-hour meter × spot price) "
            "÷ (live energy × the same price) on settled days."
        )
        if scales.get("import_clamped") or scales.get("export_clamped"):
            lines.append(
                "A raw ratio sat outside 0.50–1.50, so the scale was held "
                "at that limit rather than stretching today's estimate."
            )
        for row in scales.get("days") or []:
            bits = [row["date"]]
            if "import_ratio" in row:
                bits.append(
                    f"import Octopus £{row['stated_import_pence'] / 100:.2f} "
                    f"vs live £{row['live_import_pence'] / 100:.2f} "
                    f"(×{row['import_ratio']:.3f})"
                )
            if "export_ratio" in row:
                bits.append(
                    f"export Octopus £{row['stated_export_pence'] / 100:.2f} "
                    f"vs live £{row['live_export_pence'] / 100:.2f} "
                    f"(×{row['export_ratio']:.3f})"
                )
            lines.append("  " + " — ".join(bits))
    else:
        lines.append(
            "No settled day yet where the live stream and Octopus's half-hour "
            "meter can both be priced, so today is not scaled."
        )
    lines.append(
        "On the chart, a settled day is Octopus's meter × the spot price. "
        "Today is the live estimate. Neither line is a final bill."
    )
    return lines
