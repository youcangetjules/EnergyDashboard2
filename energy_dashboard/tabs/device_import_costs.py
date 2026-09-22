"""
Energy Dashboard — `tabs/device_import_costs.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *


class _TasmotaDayBreakdownDialog(QDialog):
    """Per-device Tasmota cost / energy for one day (from Daily import costs chart)."""

    def __init__(self, day_label: str, rows: list, *, total_gbp: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Tasmota breakdown — {day_label}")
        self.setMinimumWidth(520)
        self.setMinimumHeight(360)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 12)
        lay.setSpacing(10)

        intro = QLabel(
            f"<b>{day_label}</b> — attributed import cost by Tasmota device "
            f"(Agile-priced; capped by half-hour Octopus import). "
            f"Total Tasmota: <b>£{total_gbp:.2f}</b>."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        lay.addWidget(intro)

        table = QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels(
            ["Device", "IP", "Attributed kWh", "Cost (£)", "% of Tasmota"]
        )
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for r, (name, ip, kwh, gbp, pct) in enumerate(rows):
            vals = [
                str(name or ip),
                str(ip),
                f"{kwh:.3f}",
                f"{gbp:.2f}",
                f"{pct:.1f}%",
            ]
            for c, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if c >= 2:
                    item.setTextAlignment(
                        int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    )
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        lay.addWidget(table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)
        lay.addWidget(buttons)


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
        self.on_data_updated = None
        # Drill-down state filled by _apply_plot
        self._day_labels = []
        self._tasmota_gbp = []
        self._day_keys = []
        self._device_day_rows = {}  # day_key → [(name, ip, kwh, gbp), ...]
        self._click_cid = None
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
            "Tasmota power samples come from the database between those timestamps — enable DB logging and poll devices. "
            "Click the purple (Tasmota) part of a bar for a per-device breakdown that day."
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
        self._click_cid = self.canvas.mpl_connect(
            "button_press_event", self._on_canvas_click
        )

    def refresh_chart(self):
        if self._refreshing:
            return
        self._refreshing = True
        self.refresh_btn.setEnabled(False)
        self._chart_shimmer.start()
        self.set_status("Computing device vs rest import costs…")
        threading.Thread(target=self._refresh_thread, daemon=True).start()

    def _device_label(self, ip: str) -> str:
        tt = self.tasmota_tab
        name = None
        if hasattr(tt, "device_names"):
            name = (tt.device_names or {}).get(ip)
        if not name and hasattr(tt, "device_data"):
            d = (tt.device_data or {}).get(ip) or {}
            name = d.get("name")
        return str(name or ip)

    def _known_device_ips(self) -> list[str]:
        tt = self.tasmota_tab
        ips = list(getattr(tt, "device_ips", None) or [])
        if ips:
            return [str(ip) for ip in ips]
        names = getattr(tt, "device_names", None) or {}
        return [str(ip) for ip in names.keys()]

    def _fetch_tasmota_slot_device_kwh(self, utc_start, utc_end):
        """Return {(slot_ts, device_ip): kWh} aggregated in SQL (mean W × 0.5 h)."""
        out = {}
        db = self.tasmota_tab._get_db_params()
        if db is None:
            return out
        backend, params = db
        a = pd.Timestamp(utc_start)
        b = pd.Timestamp(utc_end)
        if a.tz is None:
            a = a.tz_localize("UTC")
        if b.tz is None:
            b = b.tz_localize("UTC")
        a_s = a.strftime("%Y-%m-%d %H:%M:%S")
        b_s = b.strftime("%Y-%m-%d %H:%M:%S")
        try:
            if backend == "sqlite":
                q = (
                    "SELECT "
                    "  substr(timestamp, 1, 14) || "
                    "  CASE WHEN CAST(substr(timestamp, 15, 2) AS INTEGER) < 30 "
                    "       THEN '00:00' ELSE '30:00' END AS slot, "
                    "  device_ip, AVG(power_w) AS avg_w "
                    "FROM tasmota_readings "
                    "WHERE timestamp >= ? AND timestamp <= ? AND power_w IS NOT NULL "
                    "GROUP BY slot, device_ip"
                )
                conn = sqlite3.connect(params["path"])
                try:
                    cur = conn.cursor()
                    cur.execute(q, (a_s, b_s))
                    db_rows = cur.fetchall()
                finally:
                    conn.close()
            elif backend == "mysql":
                import pymysql
                q = (
                    "SELECT "
                    "  DATE_FORMAT("
                    "    DATE_SUB(timestamp, INTERVAL MINUTE(timestamp) %% 30 MINUTE),"
                    "    '%%Y-%%m-%%d %%H:%%i:00') AS slot, "
                    "  device_ip, AVG(power_w) AS avg_w "
                    "FROM tasmota_readings "
                    "WHERE timestamp >= %s AND timestamp <= %s AND power_w IS NOT NULL "
                    "GROUP BY slot, device_ip"
                )
                conn = pymysql.connect(**params, charset="utf8mb4", connect_timeout=3)
                try:
                    with conn.cursor() as cur:
                        cur.execute(q, (a_s, b_s))
                        db_rows = cur.fetchall()
                finally:
                    conn.close()
            else:
                import psycopg2
                q = (
                    "SELECT "
                    "  to_char(date_trunc('hour', timestamp::timestamp) + "
                    "    INTERVAL '30 min' * FLOOR(EXTRACT(MINUTE FROM timestamp::timestamp) / 30),"
                    "    'YYYY-MM-DD HH24:MI:SS') AS slot, "
                    "  device_ip, AVG(power_w) AS avg_w "
                    "FROM tasmota_readings "
                    "WHERE timestamp >= %s AND timestamp <= %s AND power_w IS NOT NULL "
                    "GROUP BY slot, device_ip"
                )
                conn = psycopg2.connect(**params, connect_timeout=3)
                try:
                    with conn.cursor() as cur:
                        cur.execute(q, (a_s, b_s))
                        db_rows = cur.fetchall()
                finally:
                    conn.close()
        except Exception as e:
            _log.warn("DeviceCosts", f"Tasmota DB query: {e}")
            return out

        for slot_raw, ip, avg_w in db_rows:
            if avg_w is None or not ip:
                continue
            if isinstance(slot_raw, str):
                try:
                    ts = datetime.strptime(str(slot_raw)[:19], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try:
                        ts = datetime.fromisoformat(str(slot_raw))
                    except Exception:
                        continue
            else:
                ts = slot_raw
            ts = pd.Timestamp(ts)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            out[(ts, str(ip))] = float(avg_w) / 1000.0 * 0.5
        return out

    def _refresh_thread(self):
        note = ""
        try:
            hh = self.octopus_tab.hh_data
            if hh is None or hh.empty:
                self._inv.invoke(
                    lambda: self._apply_plot(
                        None, None, None, None, None,
                        "Fetch Octopus Energy Data first (half-hourly import).",
                    )
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
            slot_dev_kwh = self._fetch_tasmota_slot_device_kwh(
                t0.to_pydatetime(), (t1 + pd.Timedelta(minutes=30)).to_pydatetime()
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
            if not slot_dev_kwh:
                note = (
                    (note + " ") if note else ""
                ) + "No Tasmota DB rows in range; all cost shown as “the rest”."

            p_per_slot = _align_agile_rates_to_consumption_index(hh.index, agile_ser, fi)
            rates = p_per_slot.reindex(hh.index)
            if rates is None or rates.empty:
                rates = pd.Series(fi, index=hh.index, dtype=float)
            else:
                rates = rates.fillna(fi)

            # Total Tasmota kWh per slot (sum of devices).
            slot_totals = {}
            for (slot, _ip), kwh in slot_dev_kwh.items():
                slot_totals[slot] = slot_totals.get(slot, 0.0) + float(kwh)
            slot_tasmota_kwh = pd.Series(slot_totals, dtype=float)
            if slot_tasmota_kwh.empty:
                slot_tasmota_kwh = pd.Series(0.0, index=hh.index, dtype=float)
            else:
                slot_tasmota_kwh = slot_tasmota_kwh.reindex(hh.index).fillna(0.0)

            imp = hh["Import (kWh)"].astype(float).clip(lower=0.0)
            imp_a = imp.to_numpy(dtype=float)
            tot_a = np.maximum(0.0, slot_tasmota_kwh.to_numpy(dtype=float))
            t_alloc = np.minimum(imp_a, tot_a)
            r_alloc = np.maximum(0.0, imp_a - t_alloc)
            rate_a = rates.to_numpy(dtype=float)
            t_pence = t_alloc * rate_a
            r_pence = r_alloc * rate_a

            # Scale factor per slot so device shares match import-capped Tasmota total.
            scale_a = np.divide(
                t_alloc, tot_a, out=np.zeros_like(t_alloc), where=tot_a > 1e-12
            )
            scale_by_slot = {ts: float(scale_a[i]) for i, ts in enumerate(hh.index)}

            import pytz
            london = pytz.timezone("Europe/London")
            day_index = pd.Index([ts.tz_convert(london).normalize() for ts in hh.index])
            daily_t = pd.Series(t_pence, index=day_index).groupby(level=0).sum()
            daily_r = pd.Series(r_pence, index=day_index).groupby(level=0).sum()
            days_sorted = list(daily_t.index.sort_values())
            tasmota_gbp = [float(daily_t.loc[d]) / 100.0 for d in days_sorted]
            rest_gbp = [float(daily_r.loc[d]) / 100.0 for d in days_sorted]
            labels = [d.strftime("%a %d/%m") for d in days_sorted]

            # Per-device daily attributed kWh + £ (pence/100).
            day_dev_kwh = {}
            day_dev_gbp = {}
            for (slot, ip), kwh in slot_dev_kwh.items():
                if slot not in scale_by_slot:
                    continue
                scale = scale_by_slot[slot]
                if scale <= 0:
                    continue
                rate = float(rates.loc[slot]) if slot in rates.index else fi
                alloc_kwh = float(kwh) * scale
                alloc_gbp = alloc_kwh * rate / 100.0
                day = slot.tz_convert(london).normalize()
                day_dev_kwh.setdefault(day, {})
                day_dev_gbp.setdefault(day, {})
                day_dev_kwh[day][ip] = day_dev_kwh[day].get(ip, 0.0) + alloc_kwh
                day_dev_gbp[day][ip] = day_dev_gbp[day].get(ip, 0.0) + alloc_gbp

            known_ips = self._known_device_ips()
            device_day_rows = {}
            for day in days_sorted:
                ips = set(known_ips) | set((day_dev_kwh.get(day) or {}).keys())
                rows = []
                for ip in ips:
                    kwh = float((day_dev_kwh.get(day) or {}).get(ip, 0.0))
                    gbp = float((day_dev_gbp.get(day) or {}).get(ip, 0.0))
                    rows.append((self._device_label(ip), ip, kwh, gbp))
                rows.sort(key=lambda r: (-r[3], r[0].lower()))
                device_day_rows[day] = rows

            self._inv.invoke(
                lambda: self._apply_plot(
                    labels, tasmota_gbp, rest_gbp, days_sorted, device_day_rows, note
                )
            )
        except Exception as e:
            _log.warn("DeviceCosts", str(e))
            self._inv.invoke(
                lambda msg=str(e): self._apply_plot(
                    None, None, None, None, None, f"Error: {msg}"
                )
            )
        finally:
            self._inv.invoke(self._refresh_done)

    def _refresh_done(self):
        self._chart_shimmer.stop()
        self._refreshing = False
        self.refresh_btn.setEnabled(True)

    def _on_canvas_click(self, event):
        if event.inaxes is not self.ax or event.button != 1:
            return
        if event.xdata is None or event.ydata is None:
            return
        tb = getattr(self.canvas, "toolbar", None)
        if tb is not None and getattr(tb, "mode", ""):
            return  # pan / zoom active
        if not self._tasmota_gbp or not self._day_keys:
            return
        idx = int(round(event.xdata))
        if idx < 0 or idx >= len(self._tasmota_gbp):
            return
        # Only the purple (Tasmota) segment: y from 0 → tasmota height.
        ta = float(self._tasmota_gbp[idx])
        if ta <= 0.005:
            self.set_status("No Tasmota-attributed cost on this day to break down.")
            return
        if event.ydata < 0 or event.ydata > ta:
            return
        self._show_device_breakdown(idx)

    def _show_device_breakdown(self, idx: int):
        day = self._day_keys[idx]
        label = self._day_labels[idx] if idx < len(self._day_labels) else str(day)
        raw_rows = self._device_day_rows.get(day) or []
        total_gbp = float(self._tasmota_gbp[idx]) if idx < len(self._tasmota_gbp) else 0.0
        if not raw_rows:
            # Still show known devices at £0 so the 16-device list is visible.
            raw_rows = [
                (self._device_label(ip), ip, 0.0, 0.0)
                for ip in self._known_device_ips()
            ]
        rows = []
        for name, ip, kwh, gbp in raw_rows:
            pct = (100.0 * gbp / total_gbp) if total_gbp > 1e-9 else 0.0
            rows.append((name, ip, kwh, gbp, pct))
        dlg = _TasmotaDayBreakdownDialog(
            label, rows, total_gbp=total_gbp, parent=self
        )
        dlg.exec()

    def _apply_plot(self, labels, tasmota_gbp, rest_gbp, day_keys, device_day_rows, note):
        self.note_label.setText(note or "")
        self._day_labels = list(labels or [])
        self._tasmota_gbp = list(tasmota_gbp or [])
        self._day_keys = list(day_keys or [])
        self._device_day_rows = dict(device_day_rows or {})
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
            label="Tasmota devices (attributed) — click for breakdown",
            color="#cba6f7",
            alpha=0.9,
            zorder=2,
            picker=True,
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
        self.set_status("Device costs chart updated. Click purple bars for per-device breakdown.")
        if self.on_data_updated:
            self.on_data_updated()


__all__ = [n for n in globals() if not n.startswith('__')]
