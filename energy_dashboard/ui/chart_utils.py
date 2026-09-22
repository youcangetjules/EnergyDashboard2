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


def _octopus_live_draw_demand_zone_labels(ax, fig):
    """Faint Import / output zone labels on the Live Demand (watts) chart."""
    import math

    ymin, ymax = ax.get_ylim()
    if not math.isfinite(ymin) or not math.isfinite(ymax):
        return

    x_lo, x_hi = ax.get_xlim()
    span = float(x_hi - x_lo)
    if not math.isfinite(span) or span <= 0:
        return
    try:
        w_px = float(ax.bbox.width)
        x_pad = span * (50.0 / w_px) if w_px > 0 else span * 0.005
    except Exception:
        x_pad = span * 0.005
    x_pos = x_lo + x_pad

    label_kw = dict(
        fontsize=40,
        color=_DARK_TEXT,
        alpha=0.20,
        va='center',
        ha='left',
        zorder=12,
        clip_on=True,
    )

    for y_val, text in ((2000.0, 'Import'), (-2000.0, 'Export')):
        if ymin <= y_val <= ymax:
            ax.text(x_pos, y_val, text, **label_kw)


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


def _octopus_live_draw_cumulative_day_labels(ax, london, cum_df, *, now=None):
    """Annotate daily finals and today's running tallies on the cumulative chart.

    For each completed London calendar day in ``cum_df``, place Imp / PV / Cons
    totals just below that day's last sample (left of the midnight reset).
    For the current day, place the same three values at the latest sample
    (running tally). When Cons and Imp (or PV) sit at nearly the same kWh,
    labels are stacked so they do not overlap: today stacks upward
    (Cons above Imp above PV); completed days stack downward under the lines.
    """
    import math
    import matplotlib.dates as mdates

    if cum_df is None or cum_df.empty or 'interval_start' not in cum_df.columns:
        return
    if 'cum_import_kwh' not in cum_df.columns:
        return

    df = cum_df.copy()
    ts = pd.to_datetime(df['interval_start'])
    if getattr(ts.dt, 'tz', None) is None:
        ts = ts.dt.tz_localize(london, ambiguous='infer', nonexistent='shift_forward')
    else:
        ts = ts.dt.tz_convert(london)
    df = df.assign(_ts=ts, _day=ts.dt.normalize())
    df = df.sort_values('_ts').reset_index(drop=True)

    if now is None:
        now_ts = pd.Timestamp(datetime.now(london))
    else:
        now_ts = pd.Timestamp(now)
        if now_ts.tzinfo is None:
            now_ts = now_ts.tz_localize(london)
        else:
            now_ts = now_ts.tz_convert(london)
    today = now_ts.normalize()

    x_lo, x_hi = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    if not math.isfinite(ymin) or not math.isfinite(ymax) or ymax <= ymin:
        return
    y_span = ymax - ymin
    # Minimum vertical gap between stacked labels (data units ≈ one label height).
    min_gap = max(0.9, 0.05 * y_span)
    # Drop completed-day labels this far below their series endpoint.
    below_gap = max(0.45, 0.025 * y_span)
    # Preferred bottom→top order when values collide: PV, Imp, Cons.
    stack_rank = {"PV": 0, "Imp": 1, "Cons": 2}

    series = (
        ('Imp', 'cum_import_kwh', '#F44336'),
        ('PV', 'cum_pv_kwh', '#fab387'),
        ('Cons', 'cum_consumption_kwh', '#cba6f7'),
    )

    for day_ts, day_df in df.groupby('_day', sort=True):
        if day_df.empty:
            continue
        last = day_df.iloc[-1]
        x_num = float(mdates.date2num(last['_ts'].to_pydatetime()))
        if x_num < x_lo - 1e-6 or x_num > x_hi + 1e-6:
            continue
        is_today = bool(pd.Timestamp(day_ts).normalize() == today)
        ha = 'left' if is_today else 'right'
        x_off = 6 if is_today else -6

        items = []
        for name, col, color in series:
            if col not in day_df.columns:
                continue
            try:
                val = float(last[col])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(val):
                continue
            text = f"{name} {val:.1f}"
            if is_today:
                text = f"{name} {val:.1f} (now)"
            items.append({
                "name": name,
                "val": val,
                "color": color,
                "text": text,
            })
        if not items:
            continue

        if is_today:
            # Running tally: sort by value, Cons above Imp above PV on near-ties;
            # stack label baselines upward so close values do not overlap.
            items.sort(
                key=lambda it: (it["val"], stack_rank.get(it["name"], 0)),
            )
            y_text = None
            for it in items:
                y = float(it["val"])
                if y_text is None:
                    y_text = y
                else:
                    y_text = max(y, y_text + min_gap)
                it["y_text"] = y_text
        else:
            # End-of-day: sit below the lines. Highest series closest to its
            # endpoint; lower labels stack further down on collisions.
            items.sort(
                key=lambda it: (-it["val"], -stack_rank.get(it["name"], 0)),
            )
            y_text = None
            for it in items:
                y = float(it["val"]) - below_gap
                if y_text is None:
                    y_text = y
                else:
                    y_text = min(y, y_text - min_gap)
                it["y_text"] = y_text
            # Restore ascending order for top/bottom clamp below.
            items.sort(key=lambda it: it["y_text"])

        # Keep the stack inside the axes (shift as a column if needed).
        top_lim = ymax - 0.02 * y_span
        overflow = items[-1]["y_text"] - top_lim
        if overflow > 0:
            for it in items:
                it["y_text"] -= overflow
        bot_lim = ymin + 0.02 * y_span
        if items[0]["y_text"] < bot_lim:
            shift = bot_lim - items[0]["y_text"]
            for it in items:
                it["y_text"] += shift

        # Map data-y delta → offset points so each label sits at y_text while
        # still anchoring to the series endpoint.
        for it in items:
            y0 = float(ax.transData.transform((0.0, it["val"]))[1])
            y1 = float(ax.transData.transform((0.0, it["y_text"]))[1])
            dy_pts = y1 - y0
            ax.annotate(
                it["text"],
                xy=(x_num, it["val"]),
                xytext=(x_off, dy_pts),
                textcoords='offset points',
                ha=ha, va='center',
                fontsize=7.5, color=it["color"], fontweight='bold',
                annotation_clip=False,
                zorder=8, clip_on=False,
            )


def _battery_power_draw_daily_totals(ax, df, london=None):
    """Annotate the previous two days and today's running energy totals.

    Values are shown beneath each London day-date label on Battery Analysis
    Power Flows. Today's values are explicitly marked as a running tally.
    """
    import matplotlib.dates as mdates
    import pytz
    if london is None:
        london = pytz.timezone('Europe/London')
    if df is None or df.empty or 'timestamp' not in df.columns:
        return
    ts = pd.to_datetime(df['timestamp'])
    x_lo, x_hi = ax.get_xlim()
    span_days = max(1e-9, x_hi - x_lo)
    try:
        day_px = float(ax.bbox.width) / span_days
    except Exception:
        day_px = 200.0
    if day_px < 50.0:
        return

    today = datetime.now(london).date()
    wanted_days = [today - timedelta(days=2), today - timedelta(days=1), today]
    interval_h = 5.0 / 60.0
    # `_draw_day_date_labels` uses top_offset_px=10 and ~11px text; stack below it.
    base_y = 10 + 11 + 2
    line_gap = 12
    # Readings are stored as UTC-naive wall strings; day totals must use London
    # calendar days or "today" annotations land on the wrong pillar.
    if getattr(ts.dt, 'tz', None) is None:
        ts_london = ts.dt.tz_localize('UTC').dt.tz_convert(london)
    else:
        ts_london = ts.dt.tz_convert(london)
    day_keys = ts_london.dt.date
    for day in wanted_days:
        day_df = df[day_keys == day]
        if day_df.empty:
            continue
        if len(day_df) >= 2:
            dt_h = pd.to_datetime(day_df['timestamp']).diff().dt.total_seconds() / 3600.0
            med = float(dt_h.dropna().median()) if dt_h.notna().any() else interval_h
            if not np.isfinite(med) or med <= 0:
                med = interval_h
            sample_h = float(np.clip(med, 1.0 / 60.0, 0.5))
        else:
            sample_h = interval_h
        midnight = pd.Timestamp(
            year=day.year, month=day.month, day=day.day,
            hour=0, minute=0, second=0, tz=london,
        )
        xn = mdates.date2num(midnight.to_pydatetime())
        if xn < x_lo or xn > x_hi:
            continue

        tot_import = float((day_df['grid_import_kW'] * sample_h).sum())
        tot_gen = float((day_df['pv_kW'] * sample_h).sum())
        if 'load_kW' in day_df.columns:
            tot_consumed = float((day_df['load_kW'] * sample_h).sum())
        else:
            tot_export = float((day_df['grid_export_kW'] * sample_h).sum())
            tot_charge = float((day_df['charge_kW'] * sample_h).sum())
            tot_discharge = float((day_df['discharge_kW'] * sample_h).sum())
            tot_consumed = (
                tot_gen + tot_import + tot_discharge - tot_export - tot_charge
            )
        running = " (running)" if day == today else ""
        for i, (txt, color) in enumerate([
            (f"Tot kWh consumed{running}: {tot_consumed:.2f}", '#89b4fa'),
            (f"Tot kWh imported{running}: {tot_import:.2f}", '#f38ba8'),
            (f"Tot kWh generated{running}: {tot_gen:.2f}", '#fab387'),
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


# Compatibility for callers outside the active dashboard package.
_battery_power_draw_prev_day_totals = _battery_power_draw_daily_totals


def _bar_hover_series_label(art, ax) -> str:
    """Best-effort legend/series name for a bar Rectangle."""
    lab = art.get_label()
    if lab and not str(lab).startswith("_"):
        return str(lab)
    for container in getattr(ax, "containers", []) or []:
        try:
            patches = list(container)
        except Exception:
            continue
        if art not in patches:
            continue
        cl = container.get_label()
        if cl and not str(cl).startswith("_"):
            return str(cl)
    return ""


def _bar_hover_unit(ax) -> str:
    ylab = (ax.get_ylabel() or "").strip()
    if not ylab:
        return ""
    # Common dashboard axis titles already include the unit.
    low = ylab.lower()
    for token in ("kwh", "kw", "£", "gbp", "%", "w"):
        if token in low:
            return ylab
    return ylab


def _bar_hover_format_value(height: float, unit: str) -> str:
    try:
        h = float(height)
    except (TypeError, ValueError):
        return str(height)
    if abs(h) >= 100:
        body = f"{h:.1f}"
    elif abs(h) >= 10:
        body = f"{h:.2f}"
    else:
        body = f"{h:.3g}"
    if unit:
        # Avoid "12.3 kWh (kWh)" duplication when ylabel is just the unit.
        if unit.lower() in ("kwh", "kw", "w", "%", "£"):
            return f"{body} {unit}"
        if any(tok in unit.lower() for tok in ("kwh", "kw", "£", "%")):
            return f"{body} ({unit})"
        return f"{body} {unit}"
    return body


def enable_bar_value_hover(canvas) -> None:
    """Show the bar value in a tooltip annotation when the mouse is over a bar.

    Safe to call more than once per canvas. Works for vertical ``ax.bar`` /
    stacked bars (matplotlib ``Rectangle`` patches). Line charts are ignored.
    """
    if canvas is None:
        return
    if getattr(canvas, "_pm_bar_hover_cid", None) is not None:
        return

    from matplotlib.patches import Rectangle

    def _annot_for(ax):
        annot = getattr(ax, "_pm_bar_hover_annot", None)
        # Recreate after ax.clear() — old artist is detached from the axes.
        if annot is None or getattr(annot, "axes", None) is not ax:
            annot = ax.annotate(
                "",
                xy=(0, 0),
                xytext=(0, 14),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=9,
                fontweight="bold",
                color="#cdd6f4",
                bbox={
                    "boxstyle": "round,pad=0.35",
                    "facecolor": "#11111b",
                    "edgecolor": "#89b4fa",
                    "linewidth": 1.0,
                    "alpha": 0.92,
                },
                zorder=30,
                annotation_clip=False,
            )
            annot.set_visible(False)
            ax._pm_bar_hover_annot = annot
        return annot

    def _hide_all(*, draw=True):
        dirty = False
        fig = getattr(canvas, "figure", None)
        if fig is None:
            return
        for ax in fig.axes:
            annot = getattr(ax, "_pm_bar_hover_annot", None)
            if annot is not None and annot.get_visible():
                annot.set_visible(False)
                dirty = True
        if draw and dirty:
            canvas.draw_idle()

    def _on_move(event):
        if event.inaxes is None or event.xdata is None or event.ydata is None:
            _hide_all()
            return
        ax = event.inaxes
        x, y = float(event.xdata), float(event.ydata)
        hit = None
        hit_area = None
        for art in ax.patches:
            if not isinstance(art, Rectangle) or not art.get_visible():
                continue
            try:
                x0 = float(art.get_x())
                w = float(art.get_width())
                y0 = float(art.get_y())
                h = float(art.get_height())
            except (TypeError, ValueError):
                continue
            if abs(w) < 1e-15 and abs(h) < 1e-15:
                continue
            xa, xb = (x0, x0 + w) if w >= 0 else (x0 + w, x0)
            ya, yb = (y0, y0 + h) if h >= 0 else (y0 + h, y0)
            if xa <= x <= xb and ya <= y <= yb:
                area = abs(w) * abs(h)
                if hit is None or area < hit_area:
                    hit = art
                    hit_area = area
        if hit is None:
            _hide_all()
            return

        # Hide annotations on other axes in the same figure.
        for other in canvas.figure.axes:
            if other is ax:
                continue
            annot = getattr(other, "_pm_bar_hover_annot", None)
            if annot is not None and annot.get_visible():
                annot.set_visible(False)

        h = float(hit.get_height())
        y0 = float(hit.get_y())
        x0 = float(hit.get_x())
        w = float(hit.get_width())
        # Vertical bars encode the value in height; horizontal (barh) in width.
        horizontal = abs(w) > abs(h)
        value_num = w if horizontal else h
        if horizontal:
            tip_x = x0 + w if w >= 0 else x0
            tip_y = y0 + h * 0.5
        else:
            tip_x = x0 + w * 0.5
            tip_y = y0 + h if h >= 0 else y0
        series = _bar_hover_series_label(hit, ax)
        unit = _bar_hover_unit(ax)
        value = _bar_hover_format_value(value_num, unit)
        text = f"{series}: {value}" if series else value

        annot = _annot_for(ax)
        annot.xy = (tip_x, tip_y)
        annot.set_text(text)
        if horizontal:
            if value_num < 0:
                annot.set_ha("right")
                annot.set_va("center")
                annot.xyann = (-10, 0)
            else:
                annot.set_ha("left")
                annot.set_va("center")
                annot.xyann = (10, 0)
        elif value_num < 0:
            annot.set_ha("center")
            annot.set_va("top")
            annot.xyann = (0, -14)
        else:
            annot.set_ha("center")
            annot.set_va("bottom")
            annot.xyann = (0, 14)
        annot.set_visible(True)
        canvas.draw_idle()

    canvas._pm_bar_hover_cid = canvas.mpl_connect("motion_notify_event", _on_move)
    # Leave axes also clears the tip when the pointer exits the canvas.
    canvas._pm_bar_hover_leave_cid = canvas.mpl_connect(
        "axes_leave_event", lambda _e: _hide_all()
    )


__all__ = [n for n in globals() if not n.startswith('__')]
