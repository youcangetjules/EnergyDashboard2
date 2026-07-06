"""
Energy Dashboard — `ui/chart_utils.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.ui.palette import *
# --- NavigationToolbar cursor line: explain x and y (all dashboard charts) ---
def _fmt_toolbar_time(xv, tz=None):
    """Format matplotlib date number as local wall time for the status line."""
    import matplotlib.dates as mdates
    import pytz
    if tz is None:
        tz = pytz.timezone("Europe/London")
    try:
        return mdates.num2date(xv, tz=tz).strftime("%a %d %b %Y %H:%M")
    except Exception:
        return f"(invalid time; raw x={xv})"


def _fmt_toolbar_y(yv, unit, explanation):
    """Format y value with unit and a plain-language meaning."""
    import math
    if yv is None:
        y_s = "—"
    else:
        try:
            yf = float(yv)
            if math.isnan(yf) or math.isinf(yf):
                y_s = "—"
            else:
                y_s = f"{yf:.4g}"
        except (TypeError, ValueError):
            y_s = str(yv)
    return f"Vertical axis ({unit}): {y_s} — {explanation}"


def _fmt_toolbar_time_y(xv, yv, tz, y_unit, y_explain):
    return (
        f"Horizontal axis (time, local): {_fmt_toolbar_time(xv, tz)}  |  "
        f"{_fmt_toolbar_y(yv, y_unit, y_explain)}"
    )


def _resolve_axis_day_range(ax, london):
    """Return (d_lo, d_hi, n_days) for the London-time day span currently
    visible on `ax`'s x-axis, or None if the axis isn't a usable datetime
    axis.  Centralises the sanity checks shared by `_draw_day_date_labels`
    and `_draw_6h_vertical_grid`."""
    import matplotlib.dates as mdates
    x_lo, x_hi = ax.get_xlim()
    span = x_hi - x_lo
    # Matplotlib's default axes start at (0, 1); bail if no time data has
    # been plotted yet so we don't try to "label" the year 1.
    if span <= 0 or span > 365 * 5 or x_lo < 1.0:
        return None
    try:
        d_lo = mdates.num2date(x_lo, tz=london).date()
        d_hi = mdates.num2date(x_hi, tz=london).date()
    except (ValueError, OverflowError):
        return None
    n_days = (d_hi - d_lo).days + 2
    if n_days <= 0:
        return None
    return d_lo, d_hi, n_days


def _draw_6h_vertical_grid(ax, london=None, *, max_days=120,
                           primary_hours=(0, 6, 12, 18),
                           secondary_hours=(3, 9, 15, 21),
                           force_intraday_secondary=False):
    """Draw vertical reference grids on a datetime x-axis.

    By default London midnight (00:00) is a solid day-boundary line; 06:00 /
    12:00 / 18:00 are dotted primaries; 03:00 / 09:00 / 15:00 / 21:00 are
    lighter half-step guides.  Pass `primary_hours` / `secondary_hours` to
    override — e.g. `primary_hours=(0,)`, `secondary_hours=()` for a
    midnight-only grid on multi-day charts where intra-day lines just add
    visual noise.

    The grid auto-thins for wide axes: when each day occupies less than
    ~100 px, secondary hours are dropped; below ~40 px, intra-day primary
    hours are dropped too, leaving only the midnight (00:00) marker. This
    keeps multi-week charts (e.g. Daily Energy Trends) from drowning in
    vertical noise without any per-call configuration.
    Pass ``force_intraday_secondary=True`` (e.g. Optimiser / short horizons)
    to keep the 03 / 09 / 15 / 21 guides even when each day column is narrow.

    Pair this with `_draw_day_date_labels` for a consistent look across all
    time-series charts.
    """
    import matplotlib.dates as mdates
    import pytz
    if london is None:
        london = pytz.timezone('Europe/London')
    rng = _resolve_axis_day_range(ax, london)
    if rng is None:
        return
    d_lo, _d_hi, n_days = rng
    if n_days > max_days:
        return
    x_lo, x_hi = ax.get_xlim()
    span_days = max(1.0, x_hi - x_lo)
    try:
        day_px = float(ax.bbox.width) / span_days
    except Exception:
        day_px = 200.0  # if the bbox isn't ready, assume "plenty of room"
    PRIMARY_HOURS = tuple(primary_hours)
    SECONDARY_HOURS = tuple(secondary_hours)
    if day_px < 40.0:
        PRIMARY_HOURS = tuple(h for h in PRIMARY_HOURS if h == 0)
        SECONDARY_HOURS = ()
    elif day_px < 100.0 and not force_intraday_secondary:
        SECONDARY_HOURS = ()
    if not PRIMARY_HOURS and not SECONDARY_HOURS:
        return
    for i in range(n_days):
        d = d_lo + timedelta(days=i)
        for hh in PRIMARY_HOURS + SECONDARY_HOURS:
            tick = pd.Timestamp(
                year=d.year, month=d.month, day=d.day,
                hour=hh, minute=0, second=0, tz=london,
            )
            xn = mdates.date2num(tick.to_pydatetime())
            if xn < x_lo or xn > x_hi:
                continue
            if hh == 0:
                # Solid day boundary at London midnight — stronger than the
                # dotted 06/12/18 guides so multi-day charts read clearly.
                ax.axvline(
                    xn, color='#9aa8c7', linewidth=2.0, linestyle='-',
                    alpha=0.9, zorder=0,
                )
            elif hh in PRIMARY_HOURS:
                ax.axvline(
                    xn, color='#7a8aab', linewidth=1.4, linestyle=':',
                    alpha=0.75, zorder=0,
                )
            else:
                # Fainter than primary 00/06/12/18 — still visible on dark axes.
                ax.axvline(
                    xn, color='#566483', linewidth=1.0, linestyle=(0, (1, 5)),
                    alpha=0.45, zorder=0,
                )


def _draw_day_date_labels(ax, london=None, *, anchor='top', top_offset_px=10,
                          bottom_offset_px=6, left_offset_px=10, max_days=120,
                          stagger_row_height_px=22, label_color=None):
    """Annotate `ax` with 'Day DD Mon' labels at every London-time midnight
    crossing visible on its x-axis.

    Designed to be a drop-in for any matplotlib datetime-like x-axis (mdates
    floats, pandas Timestamps, etc.).  Call AFTER the data is plotted and
    after any `set_xlim` adjustments — this method reads the final xlim to
    decide which midnights are in view.

    With ``anchor='top'`` (default), labels sit just inside the top of each
    day's column.  With ``anchor='bottom'``, they sit just below the axis
    (for charts that stack kWh totals under the day headers).

    Returns the pixel depth of the label band (for stacking further lines).

    Auto-stagger: if successive day pillars would sit closer together than
    a label is wide (~75 px for "Sat 18 Apr"), labels alternate between row
    1 and row 2 so they stop colliding. When days are crammed in even
    tighter, the helper additionally thins the labels (every 2nd, 3rd, …)
    so the staggered rows themselves stay legible.

    `max_days` guards against very wide axes (e.g. months of daily totals)
    that would clutter the chart with hundreds of midnight labels.

    NOTE: this function no longer draws the midnight gridline itself —
    pair it with `_draw_6h_vertical_grid` if you want the line as well.
    """
    import matplotlib.dates as mdates
    import pytz
    if london is None:
        london = pytz.timezone('Europe/London')
    _lbl_col = label_color if label_color is not None else _DARK_TEXT
    rng = _resolve_axis_day_range(ax, london)
    if rng is None:
        return 0
    d_lo, _d_hi, n_days = rng
    if n_days > max_days:
        return 0
    anchor = (anchor or 'top').lower()
    if anchor not in ('top', 'bottom'):
        anchor = 'top'
    x_lo, x_hi = ax.get_xlim()
    span_days = max(1.0, x_hi - x_lo)
    try:
        day_px = float(ax.bbox.width) / span_days
    except Exception:
        day_px = 200.0  # safe assumption if bbox isn't ready

    # Approximate footprint of "Sat 18 Apr" at fontsize 9 (no bbox).
    LABEL_PX = 72.0
    if day_px >= LABEL_PX:
        stagger = False
        skip_n = 1
    elif day_px >= (LABEL_PX / 2.0):
        # Two-row alternating layout doubles the effective horizontal space.
        stagger = True
        skip_n = 1
    else:
        # Even staggered they would still overlap — also drop every Nth
        # day so the survivors fit. Each retained label still alternates
        # between row 1 and row 2.
        stagger = True
        skip_n = max(1, int((LABEL_PX / 2.0) / max(day_px, 1.0)) + 1)

    drawn = 0
    for i in range(n_days):
        if (i % skip_n) != 0:
            continue
        d = d_lo + timedelta(days=i)
        midnight = pd.Timestamp(
            year=d.year, month=d.month, day=d.day,
            hour=0, minute=0, second=0, tz=london,
        )
        xn = mdates.date2num(midnight.to_pydatetime())
        if xn < x_lo or xn > x_hi:
            continue
        # Alternate between two stacked rows: even drawn-index → top row,
        # odd → second row 22 px below.  When stagger is False both rows
        # collapse to a single line so existing single-day charts look
        # identical to before.
        row = (drawn % 2) if stagger else 0
        if anchor == 'bottom':
            y_frac = 0.0
            edge_px = bottom_offset_px
            offset_y = -(edge_px + row * stagger_row_height_px)
            va = 'top'
        else:
            y_frac = 1.0
            edge_px = top_offset_px
            offset_y = -(edge_px + row * stagger_row_height_px)
            va = 'top'
        ax.annotate(
            midnight.strftime('%a %d %b'),
            xy=(xn, y_frac), xycoords=('data', 'axes fraction'),
            xytext=(left_offset_px, offset_y),
            textcoords='offset pixels',
            ha='left', va=va,
            fontsize=9, fontweight='normal', color=_lbl_col,
            annotation_clip=False,
            zorder=6,
        )
        drawn += 1
    if drawn == 0:
        return 0
    edge_px = bottom_offset_px if anchor == 'bottom' else top_offset_px
    label_rows = 2 if stagger and drawn > 1 else 1
    return edge_px + (label_rows - 1) * stagger_row_height_px + 11


def _draw_history_future_shading(ax, now, *, history_color='#181825',
                                 future_color='#313244', history_alpha=0.42,
                                 future_alpha=0.28, zorder=-1):
    """Tint the axis background differently for past vs future around ``now``."""
    import matplotlib.dates as mdates
    x_lo, x_hi = ax.get_xlim()
    now_num = float(mdates.date2num(now))
    if now_num > x_lo:
        ax.axvspan(
            x_lo, min(now_num, x_hi),
            facecolor=history_color, alpha=history_alpha,
            edgecolor='none', zorder=zorder,
        )
    if now_num < x_hi:
        ax.axvspan(
            max(now_num, x_lo), x_hi,
            facecolor=future_color, alpha=future_alpha,
            edgecolor='none', zorder=zorder,
        )


def _draw_historical_day_energy_totals(ax, day_entries, *, anchor='top',
                                       min_day_px=50, top_offset_px=10,
                                       bottom_offset_px=6,
                                       label_row_height_px=11,
                                       label_band_px=0,
                                       stagger_row_height_px=22):
    """Under each day-date label, show used / generated / imported / forecast kWh.

    ``day_entries`` is a list of ``(midnight_mdates_num, dict)`` where the dict
    holds optional ``used``, ``generated``, ``imported``, and ``forecast`` keys
    (kWh).  All lines for a day share the same left edge (midnight + pad).
    ``label_band_px`` should be the value returned by ``_draw_day_date_labels``
    on the same axis (0 if day labels were not drawn).
    """
    if not day_entries:
        return 0
    anchor = (anchor or 'top').lower()
    if anchor not in ('top', 'bottom'):
        anchor = 'top'
    x_lo, x_hi = ax.get_xlim()
    span_days = max(1e-9, x_hi - x_lo)
    try:
        day_px = float(ax.bbox.width) / span_days
    except Exception:
        day_px = 200.0
    if day_px < min_day_px:
        return 0
    stagger = day_px < 72.0
    if anchor == 'bottom':
        y_frac = 0.0
        base_y = bottom_offset_px + label_band_px + 2
    else:
        y_frac = 1.0
        base_y = top_offset_px + label_row_height_px + 2
        if stagger:
            base_y += stagger_row_height_px
    # Roomier stack; extra gap before F'cast.
    line_gap = 15
    forecast_extra_gap = 6
    x_pad_px = 8
    lines_spec = (
        ('used', 'Used', '#89b4fa'),
        ('generated', 'Gen', '#fab387'),
        ('imported', 'Imp', '#f38ba8'),
        ('forecast', "F'cast", '#cba6f7'),
    )
    max_depth = 0
    # Include midnights on the left edge (window_start is usually 00:00).
    x_lo_ok = x_lo - 1e-6
    x_hi_ok = x_hi + 1e-6
    for xn, totals in day_entries:
        if xn < x_lo_ok or xn > x_hi_ok:
            continue
        y_off = float(base_y)
        drew = False
        for key, label, color in lines_spec:
            val = totals.get(key)
            if val is None or not np.isfinite(val):
                continue
            if key == 'forecast':
                if val < 0.0:
                    continue
                y_off += forecast_extra_gap
            elif val <= 0.005:
                continue
            # annotate (not offset_copy): reliable before the canvas has a
            # renderer, and keeps every line on the same left edge.
            ax.annotate(
                f"{label} {val:.1f} kWh",
                xy=(xn, y_frac),
                xycoords=('data', 'axes fraction'),
                xytext=(x_pad_px, -y_off),
                textcoords='offset points',
                ha='left', va='top',
                fontsize=7.5, color=color,
                annotation_clip=False,
                zorder=6,
                clip_on=False,
            )
            y_off += line_gap
            drew = True
        if drew:
            max_depth = max(max_depth, y_off - base_y)
    return base_y + max_depth + (8 if max_depth else 0)


def _octopus_live_draw_per_day_totals(ax, london, imp_view, exp_view,
                                      view_start, view_end):
    """On the Live Demand (or import/export) axis, label each London day with
    cumulative kWh for that day within the plot window: top-right = total
    imported, bottom-left = total exported (partial days use only visible intervals)."""
    import math
    import matplotlib.dates as mdates

    rng = _resolve_axis_day_range(ax, london)
    if rng is None:
        return
    d_lo, d_hi, n_days = rng
    if n_days > 120:
        return
    x_lo, x_hi = ax.get_xlim()
    span_days = max(1e-9, x_hi - x_lo)
    try:
        day_px = float(ax.bbox.width) / span_days
    except Exception:
        day_px = 200.0
    if day_px < 50.0:
        return

    def _sum_kwh(df, t0, t1):
        if df is None or df.empty or 'interval_start' not in df.columns:
            return 0.0
        ts = df['interval_start']
        m = (ts >= t0) & (ts < t1)
        if 'consumption' not in df.columns:
            return 0.0
        try:
            return float(df.loc[m, 'consumption'].sum())
        except Exception:
            return 0.0

    ymin, ymax = ax.get_ylim()
    if not math.isfinite(ymin) or not math.isfinite(ymax) or ymax <= ymin:
        return
    y_top = ymax - 0.06 * (ymax - ymin)
    y_bot = ymin + 0.06 * (ymax - ymin)
    x_pad = max(1e-5, span_days * 0.004)

    for i in range(n_days):
        d = d_lo + timedelta(days=i)
        midnight = pd.Timestamp(
            year=d.year, month=d.month, day=d.day,
            hour=0, minute=0, second=0, tz=london,
        )
        next_mid = midnight + timedelta(days=1)
        x_day_l = mdates.date2num(midnight.to_pydatetime())
        x_day_r = mdates.date2num(next_mid.to_pydatetime())
        x_clip_l = max(x_day_l, x_lo, mdates.date2num(view_start))
        x_clip_r = min(x_day_r, x_hi, mdates.date2num(view_end))
        if x_clip_r - x_clip_l < span_days * 0.02:
            continue
        t0 = pd.Timestamp(mdates.num2date(x_clip_l, tz=london))
        t1 = pd.Timestamp(mdates.num2date(x_clip_r, tz=london))
        tot_imp = _sum_kwh(imp_view, t0, t1)
        tot_exp = _sum_kwh(exp_view, t0, t1)
        txt_imp = f"Total imported\n{tot_imp:.2f} kWh"
        txt_exp = f"Total exported\n{tot_exp:.2f} kWh"
        ax.text(
            x_clip_r - x_pad, y_top, txt_imp,
            ha='right', va='top', fontsize=8, color='#f38ba8',
            zorder=7, clip_on=True,
        )
        ax.text(
            x_clip_l + x_pad, y_bot, txt_exp,
            ha='left', va='bottom', fontsize=8, color='#a6e3a1',
            zorder=7, clip_on=True,
        )


def _battery_power_draw_prev_day_totals(ax, df, london=None):
    """Under yesterday's day-date label on Battery Analysis Power Flows, show
    total consumption, grid import, and PV generation (kWh) for that calendar day."""
    import matplotlib.dates as mdates
    import pytz
    if london is None:
        london = pytz.timezone('Europe/London')
    if df is None or df.empty or 'timestamp' not in df.columns:
        return
    yesterday = (datetime.now(london) - timedelta(days=1)).date()
    ts = pd.to_datetime(df['timestamp'])
    day_df = df[ts.dt.date == yesterday]
    if day_df.empty:
        return
    interval_h = 5.0 / 60.0
    tot_import = float((day_df['grid_import_kW'] * interval_h).sum())
    tot_gen = float((day_df['pv_kW'] * interval_h).sum())
    if 'load_kW' in day_df.columns:
        tot_consumed = float((day_df['load_kW'] * interval_h).sum())
    else:
        tot_export = float((day_df['grid_export_kW'] * interval_h).sum())
        tot_charge = float((day_df['charge_kW'] * interval_h).sum())
        tot_discharge = float((day_df['discharge_kW'] * interval_h).sum())
        tot_consumed = tot_gen + tot_import + tot_discharge - tot_export - tot_charge
    midnight = pd.Timestamp(
        year=yesterday.year, month=yesterday.month, day=yesterday.day,
        hour=0, minute=0, second=0, tz=london,
    )
    xn = mdates.date2num(midnight.to_pydatetime())
    x_lo, x_hi = ax.get_xlim()
    if xn < x_lo or xn > x_hi:
        return
    span_days = max(1e-9, x_hi - x_lo)
    try:
        day_px = float(ax.bbox.width) / span_days
    except Exception:
        day_px = 200.0
    if day_px < 50.0:
        return
    # `_draw_day_date_labels` uses top_offset_px=10 and ~11px text; stack below that.
    base_y = 10 + 11 + 2
    line_gap = 12
    for i, (txt, color) in enumerate([
        (f"Tot kWh consumed: {tot_consumed:.2f}", '#89b4fa'),
        (f"Tot kWh imported: {tot_import:.2f}", '#f38ba8'),
        (f"Tot kWh generated: {tot_gen:.2f}", '#fab387'),
    ]):
        ax.annotate(
            txt,
            xy=(xn, 1.0), xycoords=('data', 'axes fraction'),
            xytext=(10, -(base_y + i * line_gap)),
            textcoords='offset pixels',
            ha='left', va='top',
            fontsize=8, color=color,
            annotation_clip=True,
            zorder=6,
        )


__all__ = [n for n in globals() if not n.startswith('__')]
