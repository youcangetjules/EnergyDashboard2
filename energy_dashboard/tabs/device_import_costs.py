"""
Energy Dashboard — `tabs/device_import_costs.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
class DeviceImportCostsTab(QWidget):
    """Daily stacked import cost (£): Tasmota-attributed vs the rest, using half-hour Agile rates."""

    def __init__(self, octopus_tab, tasmota_tab, app_params, status_callback):
        super().__init__()
        self.octopus_tab = octopus_tab
        self.tasmota_tab = tasmota_tab
        self.app_params = app_params
        self.set_status = status_callback
        self._inv = Invoker(self)
        self._refreshing = False
        # Set by EnergyDashboard.build_ui — fired after a successful refresh
        # so the global tab-bar freshness colouring updates.
        self.on_data_updated = None
        self.build_ui()

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh chart")
        self.refresh_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        self.refresh_btn.clicked.connect(self.refresh_chart)
        row.addWidget(self.refresh_btn)
        hint = QLabel(
            "Uses half-hour import from the Octopus tab and Agile import rates (Parameters). "
            "Tasmota power samples come from the database between those timestamps — enable DB logging and poll devices."
        )
        hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        hint.setWordWrap(True)
        row.addWidget(hint, 1)
        main_layout.addLayout(row)
        self.note_label = QLabel("")
        self.note_label.setStyleSheet(f"color: {_UI_BLUE}; font-size: 11px;")
        main_layout.addWidget(self.note_label)

        self.fig = Figure(figsize=(12, 6), dpi=100)
        self.ax = self.fig.add_subplot(111)
        _style_ax_dark(self.ax, self.fig)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_layout.addWidget(self.canvas, 1)
        main_layout.addWidget(DarkNavigationToolbar(self.canvas, self))
        self._chart_shimmer = ChartShimmerOverlay(self.canvas)

    def refresh_chart(self):
        if self._refreshing:
            return
        self._refreshing = True
        self.refresh_btn.setEnabled(False)
        self._chart_shimmer.start()
        self.set_status("Computing device vs rest import costs…")
        threading.Thread(target=self._refresh_thread, daemon=True).start()

    def _fetch_tasmota_power_between(self, utc_start, utc_end):
        rows_out = []
        db = self.tasmota_tab._get_db_params()
        if db is None:
            return rows_out
        backend, params = db
        a = pd.Timestamp(utc_start)
        b = pd.Timestamp(utc_end)
        if a.tz is None:
            a = a.tz_localize("UTC")
        if b.tz is None:
            b = b.tz_localize("UTC")
        a_s = a.strftime("%Y-%m-%d %H:%M:%S")
        b_s = b.strftime("%Y-%m-%d %H:%M:%S")
        q = (
            "SELECT timestamp, device_ip, power_w FROM tasmota_readings "
            "WHERE timestamp >= %s AND timestamp <= %s ORDER BY timestamp ASC"
        )
        try:
            if backend == "sqlite":
                conn = sqlite3.connect(params["path"])
                try:
                    cur = conn.cursor()
                    cur.execute(q.replace("%s", "?"), (a_s, b_s))
                    db_rows = cur.fetchall()
                finally:
                    conn.close()
            elif backend == "mysql":
                import pymysql
                conn = pymysql.connect(**params, charset="utf8mb4")
                try:
                    with conn.cursor() as cur:
                        cur.execute(q, (a_s, b_s))
                        db_rows = cur.fetchall()
                finally:
                    conn.close()
            else:
                import psycopg2
                conn = psycopg2.connect(**params)
                try:
                    with conn.cursor() as cur:
                        cur.execute(q, (a_s, b_s))
                        db_rows = cur.fetchall()
                finally:
                    conn.close()
        except Exception as e:
            _log.warn("DeviceCosts", f"Tasmota DB query: {e}")
            return rows_out

        for ts_str, ip, power in db_rows:
            if power is None:
                continue
            if isinstance(ts_str, str):
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                    except Exception:
                        continue
            else:
                ts = ts_str
            ts = pd.Timestamp(ts)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            rows_out.append((ts, str(ip), float(power)))
        return rows_out

    def _refresh_thread(self):
        note = ""
        try:
            hh = self.octopus_tab.hh_data
            if hh is None or hh.empty:
                self._inv.invoke(
                    lambda: self._apply_plot(None, None, None, "Fetch Octopus Energy Data first (half-hourly import).")
                )
                return
            idx = hh.index
            if idx.tz is None:
                idx = idx.tz_localize("UTC")
            else:
                idx = idx.tz_convert("UTC")
            hh = hh.copy()
            hh.index = idx
            t0, t1 = idx.min(), idx.max()
            pow_rows = self._fetch_tasmota_power_between(
                t0.to_pydatetime(), (t1 + pd.Timedelta(minutes=30)).to_pydatetime()
            )
            pow_df = pd.DataFrame(pow_rows, columns=["ts", "ip", "pw"]) if pow_rows else pd.DataFrame(
                columns=["ts", "ip", "pw"]
            )
            ap = self.app_params
            prod = (ap.agile_product if ap else None) or DEFAULT_AGILE_PRODUCT
            tar = (ap.agile_tariff if ap else None) or DEFAULT_AGILE_TARIFF
            fi = float(ap.import_flat_pence) if ap else 24.5
            agile_ser = fetch_agile_rates_series_utc(
                prod, tar, t0, t1 + pd.Timedelta(hours=1)
            )
            if agile_ser is None or len(agile_ser) == 0:
                agile_ser = None
                note = "Agile rates not returned for this window — using flat import p/kWh from Parameters."
            else:
                note = "Half-hour costs use Agile import unit rates (Parameters tariff) matched to each slot."
            if pow_df.empty:
                note = (
                    (note + " ") if note else ""
                ) + "No Tasmota DB rows in range; all cost shown as “the rest”."

            p_per_slot = _align_agile_rates_to_consumption_index(hh.index, agile_ser, fi)
            daily_t = {}
            daily_r = {}
            import pytz
            london = pytz.timezone("Europe/London")

            for t, row in hh.iterrows():
                imp = float(row["Import (kWh)"])
                p = float(p_per_slot.loc[t])
                te = t + pd.Timedelta(minutes=30)
                if pow_df.empty:
                    t_kwh = 0.0
                else:
                    sub = pow_df[(pow_df["ts"] >= t) & (pow_df["ts"] < te)]
                    if sub.empty:
                        t_kwh = 0.0
                    else:
                        t_kwh = sub.groupby("ip")["pw"].mean().sum() / 1000.0 * 0.5
                t_alloc = min(imp, max(0.0, t_kwh))
                r_alloc = max(0.0, imp - t_alloc)
                pt = t_alloc * p
                pr = r_alloc * p
                day = t.tz_convert(london).normalize()
                daily_t[day] = daily_t.get(day, 0.0) + pt
                daily_r[day] = daily_r.get(day, 0.0) + pr

            days_sorted = sorted(daily_t.keys())
            tasmota_gbp = [daily_t[d] / 100.0 for d in days_sorted]
            rest_gbp = [daily_r[d] / 100.0 for d in days_sorted]
            labels = [d.strftime("%a %d/%m") for d in days_sorted]
            self._inv.invoke(lambda: self._apply_plot(labels, tasmota_gbp, rest_gbp, note))
        except Exception as e:
            _log.warn("DeviceCosts", str(e))
            self._inv.invoke(lambda msg=str(e): self._apply_plot(None, None, None, f"Error: {msg}"))
        finally:
            self._inv.invoke(self._refresh_done)

    def _refresh_done(self):
        self._chart_shimmer.stop()
        self._refreshing = False
        self.refresh_btn.setEnabled(True)

    def _apply_plot(self, labels, tasmota_gbp, rest_gbp, note):
        self.note_label.setText(note or "")
        self.ax.clear()
        _style_ax_dark(self.ax, self.fig)
        if not labels or tasmota_gbp is None:
            self.ax.text(
                0.5,
                0.5,
                note or "No data",
                transform=self.ax.transAxes,
                ha="center",
                va="center",
                fontsize=12,
                color="#6c7086",
            )
            self.fig.tight_layout(pad=2.0)
            self.canvas.draw()
            self.set_status("Device costs: no chart")
            return
        x = np.arange(len(labels))
        w = 0.65
        self.ax.bar(
            x,
            tasmota_gbp,
            w,
            label="Tasmota devices (attributed)",
            color="#cba6f7",
            alpha=0.9,
            zorder=2,
        )
        self.ax.bar(
            x,
            rest_gbp,
            w,
            bottom=tasmota_gbp,
            label="The rest",
            color=_UI_BLUE,
            alpha=0.88,
            zorder=2,
        )
        _min_lbl = 0.02
        for i, xi in enumerate(x):
            ta = float(tasmota_gbp[i])
            rb = float(rest_gbp[i])
            if abs(ta) >= _min_lbl:
                self.ax.text(
                    xi,
                    ta * 0.5,
                    f"£{ta:.2f}",
                    rotation=90,
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="black",
                    fontweight="bold",
                    zorder=4,
                    clip_on=False,
                )
            if abs(rb) >= _min_lbl:
                self.ax.text(
                    xi,
                    ta + rb * 0.5,
                    f"£{rb:.2f}",
                    rotation=90,
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="black",
                    fontweight="bold",
                    zorder=4,
                    clip_on=False,
                )
        totals = [float(tasmota_gbp[i]) + float(rest_gbp[i]) for i in range(len(x))]
        ymax = max(totals) if totals else 0.0
        if ymax > 0:
            self.ax.set_ylim(0, ymax * 1.14)
        pad = max(ymax * 0.018, 0.06) if ymax > 0 else 0.06
        for i, xi in enumerate(x):
            tot = totals[i]
            if tot >= _min_lbl:
                self.ax.text(
                    xi,
                    tot + pad,
                    f"£{tot:.2f}",
                    ha="center",
                    va="bottom",
                    fontsize=9,
                    color="white",
                    fontweight="bold",
                    zorder=6,
                    clip_on=False,
                )
        self.ax.set_xticks(x)
        self.ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
        self.ax.set_ylabel("Import cost (£ / day)")
        self.ax.set_title(
            "Daily import cost split (Agile unit rate × half-hour import kWh)",
            fontsize=12,
            fontweight="bold",
            pad=10,
        )
        self.ax.legend(loc="upper right", fontsize=9, framealpha=0.6,
                       facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT)
        self.ax.grid(axis="y", color=_DARK_GRID, linewidth=0.4)
        self.ax.axhline(0, color=_DARK_GRID, linewidth=0.6)
        self.ax.format_coord = lambda xv, yv: (
            f"Horizontal (x): day column ~{xv:.1f} — matches date under ticks  |  "
            f"{_fmt_toolbar_y(yv, '£/day', 'daily Agile-priced import cost (Tasmota slice + remainder)')}"
        )
        self.fig.tight_layout(pad=2.0)
        self.canvas.draw()
        self.set_status("Device costs chart updated.")
        if self.on_data_updated:
            self.on_data_updated()


__all__ = [n for n in globals() if not n.startswith('__')]
