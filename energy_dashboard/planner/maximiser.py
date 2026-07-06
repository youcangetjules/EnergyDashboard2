"""
Energy Dashboard — `planner/maximiser.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.utils.agile_rates import (
    _align_agile_rates_to_consumption_index,
    _daily_cheap_mask,
)
def maximiser_yesterday_merged_from_growatt(dashboard):
    """Slice Growatt DB half-hours for **previous London calendar day**.

    Returns ``(merged_df, date_label, error_or_none)``. ``merged_df`` columns:
    ``load_kWh``, ``solar_kWh``; index timezone-aware (UTC).
    """
    import pytz
    london = pytz.timezone("Europe/London")
    yday = (datetime.now(london) - timedelta(days=1)).date()
    at = getattr(dashboard, "analytics_tab", None)
    if at is None:
        return None, None, "Internal: Analytics tab not ready."
    hh = at._fetch_growatt_history(14)
    if hh is None or hh.empty:
        return None, None, (
            "No Growatt history in the database. Enable SQLite/MySQL/PostgreSQL logging "
            "and let the Live tab run long enough to populate growatt_readings."
        )
    idx_l = hh.index.tz_convert("Europe/London")
    mask = np.array([ts.date() == yday for ts in idx_l], dtype=bool)
    sub = hh.loc[mask].copy()
    if sub.empty or len(sub) < 36:
        return None, None, (
            f"Insufficient Growatt data for {yday} ({len(sub)} half-hour samples). "
            "Need most of the previous day logged."
        )
    return sub, str(yday), None


def maximiser_net_no_battery_variable_tariffs(merged, slot_imp, slot_exp):
    """Per-slot Agile import/export (no storage): net import cost minus export revenue."""
    tot_imp_p = tot_exp_p = 0.0
    gi = ge = 0.0
    for ts, row in merged.iterrows():
        L = float(row["load_kWh"])
        S = float(row["solar_kWh"])
        try:
            pi = float(slot_imp.loc[ts])
        except Exception:
            pi = float(slot_imp.iloc[0]) if len(slot_imp) else 24.5
        try:
            pe = float(slot_exp.loc[ts])
        except Exception:
            pe = float(slot_exp.iloc[0]) if len(slot_exp) else 5.0
        solar_to_load = min(L, S)
        grid_import = max(0.0, L - solar_to_load)
        grid_export = max(0.0, S - solar_to_load)
        tot_imp_p += grid_import * pi
        tot_exp_p += grid_export * pe
        gi += grid_import
        ge += grid_export
    return {
        "import_kwh": gi,
        "export_kwh": ge,
        "import_cost_pence": tot_imp_p,
        "export_revenue_pence": tot_exp_p,
        "net_pence": tot_imp_p - tot_exp_p,
    }


def maximiser_net_no_battery_no_export(merged, slot_imp):
    """Same as self-consumption import cost but surplus PV cannot be sold (curtailed)."""
    tot_imp_p = 0.0
    gi = 0.0
    wasted_surplus = 0.0
    for ts, row in merged.iterrows():
        L = float(row["load_kWh"])
        S = float(row["solar_kWh"])
        try:
            pi = float(slot_imp.loc[ts])
        except Exception:
            pi = float(slot_imp.iloc[0]) if len(slot_imp) else 24.5
        solar_to_load = min(L, S)
        grid_import = max(0.0, L - solar_to_load)
        surplus = max(0.0, S - solar_to_load)
        tot_imp_p += grid_import * pi
        gi += grid_import
        wasted_surplus += surplus
    return {
        "import_kwh": gi,
        "export_kwh": 0.0,
        "import_cost_pence": tot_imp_p,
        "export_revenue_pence": 0.0,
        "net_pence": tot_imp_p,
        "wasted_surplus_kwh": wasted_surplus,
    }


def maximiser_overnight_cheapest_fill(loads, solars, p_imp, idx_london, max_kwh_per_slot, dawn_hour=7):
    """Greedy lower bound: buy ``need`` kWh from cheapest overnight slots (same calendar day).

    ``need`` = sum max(0, load−solar) from midnight until **dawn_idx** (first slot at or
    after ``dawn_hour`` London where PV exceeds a small fraction of the day's peak).
    """
    n = len(loads)
    peak_s = max(max(solars), 1e-6)
    dawn_idx = n
    for i in range(n):
        ts = idx_london[i]
        h = int(ts.hour)
        if h >= int(dawn_hour) and solars[i] >= 0.12 * peak_s:
            dawn_idx = i
            break
    need = sum(max(0.0, loads[i] - solars[i]) for i in range(dawn_idx))
    pairs = [(float(p_imp[i]), i) for i in range(dawn_idx)]
    pairs.sort(key=lambda x: x[0])
    rem = need
    cost_p = 0.0
    breakdown = []
    for price, ti in pairs:
        if rem <= 1e-9:
            break
        take = min(rem, max_kwh_per_slot)
        cost_p += take * price
        breakdown.append((ti, take, price))
        rem -= take
    return {
        "dawn_idx": dawn_idx,
        "need_kwh": need,
        "min_cost_pence": cost_p,
        "unmet_kwh": rem,
        "breakdown": breakdown,
    }


def maximiser_net_per_slot_scenarios_pence(merged, slot_imp, slot_exp):
    """Per half-hour net spend (pence) for Scenario A (export ok) vs B (no export)."""
    ts_list = list(merged.index)
    n = len(ts_list)
    net_a = np.zeros(n)
    net_b = np.zeros(n)
    for i, ts in enumerate(ts_list):
        row = merged.loc[ts]
        L = float(row["load_kWh"])
        S = float(row["solar_kWh"])
        try:
            pi = float(slot_imp.loc[ts])
        except Exception:
            pi = float(slot_imp.iloc[0]) if len(slot_imp) else 24.5
        try:
            pe = float(slot_exp.loc[ts])
        except Exception:
            pe = float(slot_exp.iloc[0]) if len(slot_exp) else 5.0
        solar_to_load = min(L, S)
        grid_import = max(0.0, L - solar_to_load)
        grid_export = max(0.0, S - solar_to_load)
        net_a[i] = grid_import * pi - grid_export * pe
        net_b[i] = grid_import * pi
    return net_a, net_b


def maximiser_cumulative_gbp_10m(timestamps_utc, net_pence_per_half_hour):
    """Cumulative net £ at 10-minute marks (London wall time on x-axis).

    Each half-hour increment is split evenly across three 10-minute steps.
    Returns ``(x_mpl_nums, cum_gbp)``.
    """
    import matplotlib.dates as mdates
    import pytz
    london = pytz.timezone("Europe/London")
    x_nums = []
    cum_gbp = []
    cum = 0.0
    steps = np.asarray(net_pence_per_half_hour, dtype=float) / 3.0
    for i, ts in enumerate(timestamps_utc):
        ts_pd = pd.Timestamp(ts)
        if ts_pd.tz is None:
            ts_pd = ts_pd.tz_localize("UTC")
        else:
            ts_pd = ts_pd.tz_convert("UTC")
        for k in (1, 2, 3):
            cum += steps[i]
            t_end = ts_pd + pd.Timedelta(minutes=10 * k)
            x_nums.append(mdates.date2num(t_end.tz_convert(london).to_pydatetime()))
            cum_gbp.append(cum / 100.0)
    return x_nums, cum_gbp


def maximiser_battery_soc_pct_10m(timestamps_utc, soc_history, initial_pct=50.0):
    """Battery SOC % linearly interpolated within each half-hour (``soc_history`` slot-end values)."""
    import matplotlib.dates as mdates
    import pytz
    london = pytz.timezone("Europe/London")
    x_nums = []
    soc_vals = []
    prev_pct = float(initial_pct)
    for i, ts in enumerate(timestamps_utc):
        ts_pd = pd.Timestamp(ts)
        if ts_pd.tz is None:
            ts_pd = ts_pd.tz_localize("UTC")
        else:
            ts_pd = ts_pd.tz_convert("UTC")
        end_pct = float(soc_history[i][1]) if i < len(soc_history) else prev_pct
        for k in (1, 2, 3):
            alpha = k / 3.0
            pct = prev_pct + (end_pct - prev_pct) * alpha
            t_end = ts_pd + pd.Timedelta(minutes=10 * k)
            x_nums.append(mdates.date2num(t_end.tz_convert(london).to_pydatetime()))
            soc_vals.append(pct)
        prev_pct = end_pct
    return x_nums, soc_vals


class MaximiserTab(QWidget):
    """Retrospective 'minimum spend' scenarios for the previous day using logged load/PV."""

    def __init__(self, dashboard):
        super().__init__()
        self.dash = dashboard
        self.p = dashboard.app_params
        self._inv = Invoker(self)
        self._busy = False
        self.build_ui()

    def build_ui(self):
        lay = QVBoxLayout(self)
        hint = QLabel(
            "<p style='line-height:1.45;'><b>Maximiser</b> estimates <i>theoretical minimum</i> "
            "electricity money for <b>yesterday</b> using half-hour <b>Growatt</b> load + PV from "
            "the database and <b>Agile</b> import/export unit rates (Setup && Info codes).</p>"
            "<p style='line-height:1.45;'><b>Scenario A</b> — export allowed: grid can buy/sell at "
            "each slot's Agile prices with no battery (ideal export credit).</p>"
            "<p style='line-height:1.45;'><b>Scenario B</b> — export forbidden: surplus PV is "
            "wasted (no FiT/export); you still pay only for grid imports.</p>"
            "<p style='line-height:1.45;'><b>Overnight</b> — energy required before PV ramps (cheap-slot "
            "greedy fill): if you had to import only during the cheapest overnight half-hours, "
            "what would it cost to cover the cumulative deficit until sunlight?</p>"
            "<p style='line-height:1.45;'>The text summary is laid out in <b>three columns</b> so the "
            "charts below get more vertical space. Those charts plot <b>battery SOC %</b> for two "
            "heuristic cases (export allowed vs surplus not exported) and <b>cumulative net £</b> for "
            "<b>no-battery</b> scenarios A/B — all at <b>10-minute</b> resolution within each "
            "half-hour slot.</p>"
            "<p style='color:#a6adc8;font-size:11px;'>Battery scheduling optimum is NP-hard; "
            "run <b>Battery Simulation</b> / <b>Optimiser</b> for detailed dispatch. "
            "Here we also show a <b>heuristic smart-charge</b> simulation using your battery "
            "defaults.</p>"
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(hint)

        row = QHBoxLayout()
        self.run_btn = QPushButton("Analyse yesterday")
        self.run_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self.run_btn.clicked.connect(self.run_analysis)
        row.addWidget(self.run_btn)
        row.addStretch()
        lay.addLayout(row)

        summary_panel = QWidget()
        s_lay = QHBoxLayout(summary_panel)
        s_lay.setContentsMargins(0, 0, 0, 0)
        s_lay.setSpacing(8)
        self.summary_col1 = QTextEdit()
        self.summary_col2 = QTextEdit()
        self.summary_col3 = QTextEdit()
        _sum_placeholders = (
            "Overview & Scenario A — click Analyse yesterday…",
            "Scenario B & overnight — …",
            "Battery heuristic — …",
        )
        for te, ph in zip(
            (self.summary_col1, self.summary_col2, self.summary_col3),
            _sum_placeholders,
        ):
            te.setReadOnly(True)
            te.setFont(QFont("Helvetica", 10))
            te.setPlaceholderText(ph)

        s_lay.addWidget(self.summary_col1, 1)
        s_lay.addWidget(self.summary_col2, 1)
        s_lay.addWidget(self.summary_col3, 1)

        self.chart_fig = Figure(figsize=(10, 5.5), dpi=100)
        _MAX_CHART_HSPACE = 0.28
        self.chart_fig.subplots_adjust(
            top=0.94, bottom=0.14, left=0.08, right=0.97, hspace=_MAX_CHART_HSPACE,
        )
        gs = self.chart_fig.add_gridspec(
            2, 1, height_ratios=[1, 1], hspace=_MAX_CHART_HSPACE,
        )
        self._max_ax_soc = self.chart_fig.add_subplot(gs[0])
        self._max_ax_cost = self.chart_fig.add_subplot(gs[1], sharex=self._max_ax_soc)
        self.chart_canvas = FigureCanvas(self.chart_fig)
        chart_wrap = QWidget()
        cw_lay = QVBoxLayout(chart_wrap)
        cw_lay.setContentsMargins(0, 0, 0, 0)
        cw_lay.addWidget(DarkNavigationToolbar(self.chart_canvas, chart_wrap))
        cw_lay.addWidget(self.chart_canvas, 1)
        self._chart_shimmer = ChartShimmerOverlay(self.chart_canvas)

        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.addWidget(summary_panel)
        split.addWidget(chart_wrap)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 4)
        split.setSizes([200, 520])
        lay.addWidget(split, 1)

        self._render_maximiser_chart(None)

    def _render_maximiser_chart(self, plot_data):
        import matplotlib.dates as mdates
        self._max_ax_soc.clear()
        self._max_ax_cost.clear()
        _style_ax_dark(self._max_ax_soc, self.chart_fig)
        _style_ax_dark(self._max_ax_cost, self.chart_fig)
        if not plot_data:
            self._max_ax_soc.set_title(
                "Battery SOC % — run analysis", fontsize=10, color=_DARK_TEXT
            )
            self._max_ax_cost.set_title(
                "Cumulative net £ (no-battery A vs B) — run analysis", fontsize=10, color=_DARK_TEXT
            )
            self._max_ax_soc.set_ylabel("SOC %")
            self._max_ax_cost.set_ylabel("£")
            self.chart_canvas.draw_idle()
            return

        x = plot_data["x"]
        dl = plot_data.get("date_lbl", "")
        sfx = f" ({dl})" if dl else ""

        soc_ok = plot_data.get("soc_exp") is not None and plot_data.get("soc_ne") is not None
        if soc_ok:
            self._max_ax_soc.plot(
                x, plot_data["soc_exp"], color="#89b4fa", linewidth=1.2,
                label="Battery — export allowed",
            )
            self._max_ax_soc.plot(
                x, plot_data["soc_ne"], color="#fab387", linewidth=1.2,
                label="Battery — surplus not exported",
            )
            self._max_ax_soc.legend(fontsize=8, loc="upper right", facecolor=_DARK_FACE, edgecolor=_DARK_GRID)
        else:
            self._max_ax_soc.text(
                0.5, 0.5, "Battery SOC unavailable\n(heuristic simulation failed)",
                transform=self._max_ax_soc.transAxes, ha="center", va="center",
                color="#fab387", fontsize=10,
            )
        self._max_ax_soc.set_ylabel("SOC %")
        self._max_ax_soc.set_ylim(0, 105)
        self._max_ax_soc.set_title(f"Heuristic battery SOC % — 10-minute steps{sfx}", fontsize=10)
        self._max_ax_soc.grid(True, alpha=0.3)

        self._max_ax_cost.plot(
            x, plot_data["cum_a"], color="#a6e3a1", linewidth=1.2,
            label="Scenario A — export allowed (no battery)",
        )
        self._max_ax_cost.plot(
            x, plot_data["cum_b"], color="#f38ba8", linewidth=1.2,
            label="Scenario B — no export (no battery)",
        )
        self._max_ax_cost.legend(fontsize=8, loc="upper left", facecolor=_DARK_FACE, edgecolor=_DARK_GRID)
        self._max_ax_cost.set_ylabel("Cumulative net £")
        self._max_ax_cost.set_title(f"Cumulative net £ — no-battery scenarios — 10-minute steps{sfx}", fontsize=10)
        self._max_ax_cost.grid(True, alpha=0.3)
        self._max_ax_cost.axhline(y=0, color="#6c7086", linewidth=0.8, alpha=0.6)

        loc = mdates.AutoDateLocator(maxticks=14)
        fmt = mdates.ConciseDateFormatter(loc)
        self._max_ax_cost.xaxis.set_major_locator(loc)
        self._max_ax_cost.xaxis.set_major_formatter(fmt)
        self._max_ax_soc.tick_params(axis="x", labelbottom=False)
        self._max_ax_cost.tick_params(axis="x", rotation=22)

        self.chart_canvas.draw_idle()

    def run_analysis(self):
        if self._busy:
            return
        self._busy = True
        self.run_btn.setEnabled(False)
        self._chart_shimmer.start()
        self.dash.set_status("Maximiser: loading yesterday…")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            merged, date_lbl, err = maximiser_yesterday_merged_from_growatt(self.dash)
            if err:
                self._inv.invoke(lambda: self._done_err(err))
                return
            p = self.p
            prod = (p.agile_product if p else None) or DEFAULT_AGILE_PRODUCT
            tar_i = (p.agile_tariff if p else None) or DEFAULT_AGILE_TARIFF
            tar_e = (p.agile_export_tariff if p else None) or DEFAULT_AGILE_EXPORT_TARIFF
            flat_i = float(p.import_flat_pence) if p else 24.5
            flat_e = float(p.export_flat_pence) if p else 5.0

            start_utc = merged.index.min()
            if getattr(start_utc, "tz", None) is None:
                start_utc = pd.Timestamp(start_utc).tz_localize("UTC")
            else:
                start_utc = start_utc.tz_convert("UTC")
            end_utc = merged.index.max().tz_convert("UTC") + pd.Timedelta(minutes=30)

            s_imp = fetch_agile_rates_series_utc(prod, tar_i, start_utc, end_utc)
            s_exp = fetch_agile_rates_series_utc(prod, tar_e, start_utc, end_utc)
            slot_imp = _align_agile_rates_to_consumption_index(merged.index, s_imp, flat_i)
            slot_exp = _align_agile_rates_to_consumption_index(merged.index, s_exp, flat_e)

            base_exp = maximiser_net_no_battery_variable_tariffs(merged, slot_imp, slot_exp)
            no_ex = maximiser_net_no_battery_no_export(merged, slot_imp)

            import pytz
            london = pytz.timezone("Europe/London")
            idx_lo = [ts.tz_convert(london) for ts in merged.index]
            loads = merged["load_kWh"].to_numpy(dtype=float)
            solars = merged["solar_kWh"].to_numpy(dtype=float)
            p_arr = np.array([float(slot_imp.loc[ts]) for ts in merged.index], dtype=float)
            max_slot = float(p.analytics_max_charge_kw) * 0.5
            if hasattr(self.dash, "analytics_tab"):
                try:
                    mx = float(self.dash.analytics_tab.charge_rate_edit.text())
                    max_slot = mx * 0.5
                except Exception:
                    pass
            ov = maximiser_overnight_cheapest_fill(loads, solars, p_arr, idx_lo, max_slot)

            cheap_mask = _daily_cheap_mask(slot_imp)
            cap = float(p.battery_capacity_kwh)
            eff = float(p.analytics_efficiency_pct) / 100.0
            max_kw = float(p.analytics_max_charge_kw)
            flat_e_mean = float(slot_exp.mean()) if len(slot_exp) else flat_e

            ts_list = list(merged.index)
            net_a, net_b = maximiser_net_per_slot_scenarios_pence(merged, slot_imp, slot_exp)
            x10, cum_a = maximiser_cumulative_gbp_10m(ts_list, net_a)
            _, cum_b = maximiser_cumulative_gbp_10m(ts_list, net_b)

            soc_exp = soc_ne = None
            bat_line = ""
            try:
                at = self.dash.analytics_tab
                bat_sim = at._simulate_battery(
                    merged, cap, eff, max_kw,
                    slot_imp, flat_e_mean, cheap_mask, True, True,
                )
                bat_net = (
                    bat_sim["total_cost_pence"] - bat_sim["total_export_revenue_pence"]
                )
                bat_line = (
                    f"Heuristic smart grid-charge (Battery Simulation physics, TOU on):\n"
                    f"  Net £          : £{bat_net/100.0:.2f}\n"
                    f"  Grid import    : {bat_sim['total_grid_import_kwh']:.2f} kWh\n"
                    f"  Export revenue : £{bat_sim['total_export_revenue_pence']/100.0:.2f}\n"
                )
                _, soc_exp = maximiser_battery_soc_pct_10m(ts_list, bat_sim["soc_history"])
                try:
                    bat_ne = at._simulate_battery(
                        merged, cap, eff, max_kw,
                        slot_imp, flat_e_mean, cheap_mask, True, False,
                    )
                    _, soc_ne = maximiser_battery_soc_pct_10m(ts_list, bat_ne["soc_history"])
                except Exception:
                    pass
            except Exception as e:
                bat_line = f"Battery heuristic skipped: {e}\n"

            plot_data = {
                "x": x10,
                "cum_a": cum_a,
                "cum_b": cum_b,
                "soc_exp": soc_exp,
                "soc_ne": soc_ne,
                "date_lbl": date_lbl,
            }

            col1_lines = [
                f"London date analysed : {date_lbl}",
                f"Half-hour slots      : {len(merged)}",
                f"Total load           : {merged['load_kWh'].sum():.2f} kWh",
                f"Total solar (PV est.): {merged['solar_kWh'].sum():.2f} kWh",
                "",
                "── Scenario A: export allowed (no battery) ──",
                f"  Import cost      : £{base_exp['import_cost_pence']/100.0:.2f}",
                f"  Export revenue   : £{base_exp['export_revenue_pence']/100.0:.2f}",
                f"  Net £            : £{base_exp['net_pence']/100.0:.2f}",
                f"  (Grid import {base_exp['import_kwh']:.2f} kWh, export {base_exp['export_kwh']:.2f} kWh)",
            ]
            col2_lines = [
                "── Scenario B: export NOT allowed (surplus PV curtailed) ──",
                f"  Import cost      : £{no_ex['import_cost_pence']/100.0:.2f}",
                f"  Export revenue   : £0.00",
                f"  Net £            : £{no_ex['net_pence']/100.0:.2f}",
                f"  Surplus wasted   : {no_ex['wasted_surplus_kwh']:.2f} kWh (not sold)",
                "",
                "── Overnight (until PV picks up): cheapest-slot lower bound ──",
                f"  Dawn window ends at slot index {ov['dawn_idx']} (London ≥07:00 & PV ≥12% of peak)",
                f"  Cumulative deficit before then : {ov['need_kwh']:.2f} kWh",
                f"  Min £ if buying only cheapest slots (≤{max_slot:.2f} kWh/slot): "
                f"£{ov['min_cost_pence']/100.0:.2f}",
            ]
            if ov["unmet_kwh"] > 0.01:
                col2_lines.append(
                    f"  (Could not fit all energy in window at {max_slot:.2f} kWh/slot — "
                    f"{ov['unmet_kwh']:.2f} kWh unmet — raise charge rate or relax limit.)"
                )
            col3_lines = ["", "── Battery (same defaults as Battery Simulation) ──", bat_line.rstrip("\n")]

            triple = (
                "\n".join(col1_lines),
                "\n".join(col2_lines),
                "\n".join(col3_lines),
            )
            self._inv.invoke(lambda t=triple, pd=plot_data: self._done_ok(t, pd))
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self._inv.invoke(lambda msg=f"{e}\n\n{tb}": self._done_err(msg))

    def _done_ok(self, summary_cols, plot_data=None):
        self._chart_shimmer.stop()
        self._busy = False
        self.run_btn.setEnabled(True)
        s1, s2, s3 = summary_cols
        self.summary_col1.setPlainText(s1)
        self.summary_col2.setPlainText(s2)
        self.summary_col3.setPlainText(s3)
        self._render_maximiser_chart(plot_data)
        self.dash.set_status("Maximiser: analysis ready.")
        if hasattr(self.dash, "mark_tab_fresh"):
            self.dash.mark_tab_fresh(self)

    def _done_err(self, msg):
        self._chart_shimmer.stop()
        self._busy = False
        self.run_btn.setEnabled(True)
        self.summary_col1.setPlainText(f"Error:\n{msg}")
        self.summary_col2.clear()
        self.summary_col3.clear()
        self._render_maximiser_chart(None)
        self.dash.set_status("Maximiser: failed.")


__all__ = [n for n in globals() if not n.startswith('__')]
