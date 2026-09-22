"""
Energy Dashboard — `tabs/agile_year.py`.

Year-long daily stats for Octopus Agile spot prices: highest, lowest and
average p/kWh (inc. VAT) per Europe/London calendar day, plus how many
hours that day the rate was below 0p.

Rates come from the public Octopus unit-rates API for the import/export
tariff on Forecasts (not a cosmetic rescale). Missing days are omitted,
not invented. Daily rows are stored in ``agile_year_daily`` when logging
is on, so the tab can reload from the database and a since-start trend
can grow beyond one API window.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as date_cls

from energy_dashboard.common import *
from energy_dashboard.db.agile_year_daily import _MIN_SLOTS as _MIN_COMPLETE_SLOTS
from energy_dashboard.tabs.agile_prices import (
    _agile_band_for_price,
    _agile_readable_text_color,
)
from energy_dashboard.tabs.forecasts import (
    _coerce_agile_frame,
    _merge_agile_forecast_frames,
)

# A shade over a calendar year, plus tomorrow if Octopus has published it.
_AGILE_YEAR_DAYS = 370
_QS_TREND_MONTHLY = "agile_year/trend_monthly"
_QS_TREND_YTD = "agile_year/trend_ytd"
_QS_TREND_YEARLY = "agile_year/trend_yearly"
_QS_TREND_START = "agile_year/trend_since_start"
_COL_KEY = "agile_year_daily"
_COL_HEADERS = (
    "Day",
    "Highest p/kWh",
    "Lowest p/kWh",
    "Average p/kWh",
    "Hours below 0p",
    "Slots",
    "% Above/Below LT trend",
    "Std. deviation from trend",
)
_COL_WIDTHS = (168, 108, 108, 112, 110, 58, 168, 168)
_TREND_MONTHLY_COLOUR = "#f9e2af"
_TREND_YTD_COLOUR = "#89dceb"
_TREND_YEARLY_COLOUR = "#cba6f7"
_TREND_START_COLOUR = "#fab387"
_LT_PCT_FLOOR_P = 1.0


class _SortNumItem(QTableWidgetItem):
    """Numeric sort via Qt.UserRole (float); display text stays formatted."""

    def __lt__(self, other):
        try:
            a = self.data(Qt.UserRole)
            b = other.data(Qt.UserRole) if other is not None else None
            if a is None:
                return True
            if b is None:
                return False
            return float(a) < float(b)
        except (TypeError, ValueError):
            return super().__lt__(other)


def _london_today():
    try:
        import pytz
        return datetime.now(pytz.timezone("Europe/London")).date()
    except Exception:
        return datetime.now().date()


def _london_day(t0):
    """Europe/London calendar date for a slot start (never a UTC-date guess)."""
    if t0 is None:
        return None
    if isinstance(t0, datetime):
        dt = t0
        if dt.tzinfo is not None:
            try:
                import pytz
                dt = dt.astimezone(pytz.timezone("Europe/London"))
            except Exception:
                pass
        return dt.date()
    if isinstance(t0, date_cls):
        return t0
    if hasattr(t0, "to_pydatetime"):
        try:
            return _london_day(t0.to_pydatetime())
        except Exception:
            return None
    return None


def _slot_hours(valid_from, valid_to) -> float:
    """Length of one Agile slot in hours (half-hour unless valid_to says otherwise)."""
    try:
        if valid_from is not None and valid_to is not None:
            sec = (valid_to - valid_from).total_seconds()
            if 0.0 < sec <= 2 * 3600:
                return sec / 3600.0
    except Exception:
        pass
    return 0.5


def _is_half_hour_slot(valid_from, valid_to) -> bool:
    """Skip open-ended / standing unit rates that are not a 30-minute Agile slot."""
    if valid_from is None:
        return False
    if valid_to is None:
        return True
    try:
        sec = (valid_to - valid_from).total_seconds()
    except Exception:
        return True
    if sec <= 0:
        return False
    # Longer than two hours is a standing/open-ended rate, not a half-hour slot.
    return sec <= 2 * 3600


def daily_agile_stats(slots_df, *, min_slots=_MIN_COMPLETE_SLOTS):
    """List of per-London-day dicts from half-hour slots (newest day first).

    Each dict: day (date), high, low, avg, neg_hours, slots.
    Days with no slots are skipped — never invented. Sparse days (fewer than
    ``min_slots`` half-hours) are omitted so a 1–2 slot timezone spill cannot
    draw a spike that is not a real day of prices.
    """
    df = _coerce_agile_frame(slots_df)
    if df is None or df.is_empty():
        return []
    if "valid_from" not in df.columns or "price_pence" not in df.columns:
        return []
    buckets = {}
    has_to = "valid_to" in df.columns
    for row in df.iter_rows(named=True):
        t0 = row.get("valid_from")
        t1 = row.get("valid_to") if has_to else None
        if not _is_half_hour_slot(t0, t1):
            continue
        day = _london_day(t0)
        if day is None:
            continue
        try:
            price = float(row.get("price_pence"))
        except (TypeError, ValueError):
            continue
        hours = _slot_hours(t0, t1)
        rec = buckets.get(day)
        if rec is None:
            rec = {
                "day": day,
                "high": price,
                "low": price,
                "wsum": price * hours,
                "hours": hours,
                "neg_hours": 0.0,
                "slots": 0,
            }
            buckets[day] = rec
        else:
            if price > rec["high"]:
                rec["high"] = price
            if price < rec["low"]:
                rec["low"] = price
            rec["wsum"] += price * hours
            rec["hours"] += hours
        rec["slots"] += 1
        if price < 0:
            rec["neg_hours"] += hours
    out = []
    for day in sorted(buckets.keys(), reverse=True):
        rec = buckets[day]
        n = rec["slots"]
        if n < min_slots:
            continue
        hours = rec["hours"] if rec["hours"] > 0 else float(n)
        out.append(
            {
                "day": rec["day"],
                "high": rec["high"],
                "low": rec["low"],
                "avg": rec["wsum"] / hours,
                "neg_hours": rec["neg_hours"],
                "slots": rec["slots"],
            }
        )
    return out


def merge_daily_stats(*groups):
    """Later groups win on the same London day (live fetch beats stored rows)."""
    by_day = {}
    for group in groups:
        for rec in group or ():
            day = rec.get("day")
            if day is None:
                continue
            by_day[day] = rec
    return [by_day[d] for d in sorted(by_day.keys(), reverse=True)]


def _fit_linear(days, values):
    """Ordinary least-squares line vs ordinal day. ``(pred, slope, intercept)`` or Nones."""
    if not days or not values or len(days) != len(values):
        return None, None, None
    y = np.asarray(values, dtype=float)
    mask = np.isfinite(y)
    if int(mask.sum()) < 3:
        return None, None, None
    x = np.array([d.toordinal() for d in days], dtype=float)
    xs = x[mask]
    ys = y[mask]
    try:
        slope, intercept = np.polyfit(xs, ys, 1)
    except (np.linalg.LinAlgError, ValueError, TypeError):
        return None, None, None
    return slope * x + intercept, float(slope), float(intercept)


def annotate_lt_stats(rows):
    """Copy of rows with ``lt_pct`` / ``lt_z`` vs the since-start average trend."""
    chrono = sorted(rows or [], key=lambda rec: rec["day"])
    if not chrono:
        return []
    days = [rec["day"] for rec in chrono]
    avgs = [rec["avg"] for rec in chrono]
    pred, _slope, _intercept = _fit_linear(days, avgs)
    by_day = {}
    if pred is None:
        for rec in chrono:
            item = dict(rec)
            item["lt_pct"] = None
            item["lt_z"] = None
            by_day[rec["day"]] = item
        return [by_day[r["day"]] for r in rows]
    resid = np.asarray(avgs, dtype=float) - pred
    sigma = float(np.std(resid, ddof=1)) if len(resid) > 2 else float(np.std(resid))
    if not np.isfinite(sigma) or sigma < 1e-9:
        sigma = None
    for rec, yhat, r in zip(chrono, pred, resid):
        item = dict(rec)
        if abs(float(yhat)) >= _LT_PCT_FLOOR_P:
            item["lt_pct"] = 100.0 * float(r) / abs(float(yhat))
        else:
            item["lt_pct"] = None
        item["lt_z"] = (float(r) / sigma) if sigma else None
        by_day[rec["day"]] = item
    return [by_day[r["day"]] for r in rows]


def _monthly_segments(chrono):
    groups = defaultdict(list)
    for rec in chrono:
        day = rec["day"]
        groups[(day.year, day.month)].append(rec)
    segs = []
    for key in sorted(groups):
        chunk = groups[key]
        if len(chunk) < 3:
            continue
        days = [r["day"] for r in chunk]
        avgs = [r["avg"] for r in chunk]
        pred, slope, intercept = _fit_linear(days, avgs)
        if pred is None:
            continue
        xs = [datetime.combine(d, time.min) for d in days]
        segs.append((xs, list(pred), slope, intercept))
    return segs


class AgileYearTab(QWidget):
    """Daily high / low / average Agile prices over ~a year, plus hours below 0p."""

    def __init__(self, forecasts_tab, status_callback):
        super().__init__()
        self.forecasts_tab = forecasts_tab
        self.set_status = status_callback
        self.on_data_updated = None
        self._view = "import"
        self._inv = Invoker(self)
        self._fetching = False
        self._loaded_key = None
        self._user_opened = False
        self._daily = []
        self._source_note = ""
        self._ax2 = None
        self.build_ui()

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        ctrl_box = QGroupBox("Agile year — daily stats")
        ctrl_lay = QHBoxLayout(ctrl_box)
        ctrl_lay.setContentsMargins(10, 8, 10, 8)
        ctrl_lay.setSpacing(10)

        self.title_label = QLabel("Agile year")
        self.title_label.setStyleSheet(
            f"color: {_DARK_TEXT}; font-weight: bold; font-size: 13px;"
        )
        ctrl_lay.addWidget(self.title_label)
        ctrl_lay.addSpacing(16)

        self.rb_import = QRadioButton("Import (household)")
        self.rb_export = QRadioButton("Export (outgoing)")
        self.rb_import.setChecked(True)
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        self._view_group.addButton(self.rb_import, 0)
        self._view_group.addButton(self.rb_export, 1)
        self._view_group.idClicked.connect(self._on_view_toggled)
        ctrl_lay.addWidget(self.rb_import)
        ctrl_lay.addWidget(self.rb_export)
        ctrl_lay.addSpacing(16)

        trend_lbl = QLabel("Trend:")
        trend_lbl.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px;")
        ctrl_lay.addWidget(trend_lbl)
        self.chk_trend_monthly = QCheckBox("Monthly")
        self.chk_trend_ytd = QCheckBox("YTD")
        self.chk_trend_yearly = QCheckBox("Yearly")
        self.chk_trend_start = QCheckBox("Since start")
        self.chk_trend_monthly.setToolTip(
            "Linear fit of the daily average inside each calendar month "
            "(drawn as short segments)."
        )
        self.chk_trend_ytd.setToolTip(
            "Linear fit of the daily average from 1 January of the latest "
            "year in this series through the last day."
        )
        self.chk_trend_yearly.setToolTip(
            "Linear fit of the daily average over the last 365 London days."
        )
        self.chk_trend_start.setToolTip(
            "Long-term linear fit of every stored day (grows as the database "
            "keeps history beyond one API fetch). This is the LT trend used "
            "by the table’s % and standard-deviation columns."
        )
        s = QSettings("PowerModel", "EnergyDashboard2")
        self.chk_trend_monthly.setChecked(
            bool(s.value(_QS_TREND_MONTHLY, True, type=bool))
        )
        self.chk_trend_ytd.setChecked(bool(s.value(_QS_TREND_YTD, True, type=bool)))
        self.chk_trend_yearly.setChecked(
            bool(s.value(_QS_TREND_YEARLY, True, type=bool))
        )
        self.chk_trend_start.setChecked(
            bool(s.value(_QS_TREND_START, True, type=bool))
        )
        for chk in (
            self.chk_trend_monthly,
            self.chk_trend_ytd,
            self.chk_trend_yearly,
            self.chk_trend_start,
        ):
            chk.toggled.connect(self._on_trend_toggled)
            ctrl_lay.addWidget(chk)
        ctrl_lay.addStretch(1)

        self.refresh_btn = QPushButton("Fetch year")
        self.refresh_btn.setToolTip(
            "Download about a year of half-hourly Agile rates from Octopus "
            "(the tariff on Forecasts) and rebuild daily high / low / average. "
            "Rates and daily stats are stored in the database when logging is on."
        )
        self.refresh_btn.clicked.connect(self.refresh_now)
        _apply_primary_button_style(self.refresh_btn)
        ctrl_lay.addWidget(self.refresh_btn)
        main_layout.addWidget(ctrl_box)

        info_row = QHBoxLayout()
        self.hint_label = QLabel(
            "Prices include VAT. Each London calendar day shows the highest, "
            "lowest and average half-hour rate. Hours below 0p count every "
            "slot whose price is negative (normally 0.5 h each). Missing or "
            "sparse days are left out — not filled in. Trend lines are fits "
            "of the daily average; the table’s LT columns use Since start."
        )
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px;")
        info_row.addWidget(self.hint_label, 1)
        self.updated_label = QLabel("Updated: --")
        self.updated_label.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px;")
        info_row.addWidget(self.updated_label, 0)
        main_layout.addLayout(info_row)

        self.summary_label = QLabel("No year data yet — click Fetch year.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(f"color: {_DARK_TEXT}; font-size: 12px;")
        main_layout.addWidget(self.summary_label)

        splitter = QSplitter(Qt.Vertical)

        chart_host = QWidget()
        chart_lay = QVBoxLayout(chart_host)
        chart_lay.setContentsMargins(0, 0, 0, 0)
        chart_lay.setSpacing(2)
        self.fig = Figure(figsize=(10, 3.2), dpi=100)
        self.ax = self.fig.add_subplot(111)
        _style_ax_dark(self.ax, self.fig)
        self.fig.subplots_adjust(left=0.07, right=0.93, top=0.88, bottom=0.22)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setMinimumHeight(180)
        chart_lay.addWidget(self.canvas, 1)
        chart_lay.addWidget(DarkNavigationToolbar(self.canvas, self), 0)
        self._chart_shimmer = ChartShimmerOverlay(self.canvas)
        splitter.addWidget(chart_host)

        self.table = QTableWidget(0, len(_COL_HEADERS))
        self.table.setHorizontalHeaderLabels(list(_COL_HEADERS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._apply_table_columns()
        splitter.addWidget(self.table)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([260, 420])
        main_layout.addWidget(splitter, 1)

        self._draw_empty_chart("Click Fetch year for about 12 months of Agile rates.")

    def _apply_table_columns(self):
        hdr = self.table.horizontalHeader()
        hdr.setMinimumSectionSize(48)
        qtable_set_column_width_key(self.table, _COL_KEY)
        qtable_prepare_interactive_columns(self.table)
        restored = qtable_restore_column_widths(self.table, _COL_KEY)
        if not restored:
            for col, width in enumerate(_COL_WIDTHS):
                self.table.setColumnWidth(col, width)
        qtable_attach_column_width_persistence(self.table)

    # ── Lifecycle ────────────────────────────────────────────────────────

    def auto_start(self):
        # Heavy Octopus pull — wait until this tab is shown.
        pass

    def showEvent(self, event):
        super().showEvent(event)
        self._user_opened = True
        if self._loaded_key is None and not self._fetching:
            QTimer.singleShot(0, self.refresh_now)

    def _on_view_toggled(self, idx):
        self._view = "import" if idx == 0 else "export"
        self._loaded_key = None
        self._daily = []
        if self._user_opened and not self._fetching:
            self.refresh_now()

    def _on_trend_toggled(self, _checked=False):
        s = QSettings("PowerModel", "EnergyDashboard2")
        s.setValue(_QS_TREND_MONTHLY, self.chk_trend_monthly.isChecked())
        s.setValue(_QS_TREND_YTD, self.chk_trend_ytd.isChecked())
        s.setValue(_QS_TREND_YEARLY, self.chk_trend_yearly.isChecked())
        s.setValue(_QS_TREND_START, self.chk_trend_start.isChecked())
        if self._daily:
            view_label = "Import" if self._view == "import" else "Export (outgoing)"
            self._draw_chart(self._daily, view_label)

    def _tariff_code(self) -> str:
        ft = self.forecasts_tab
        if ft is None:
            return ""
        if self._view == "import":
            return (ft.tariff_edit.text() or "").strip()
        return (ft.export_tariff_edit.text() or "").strip()

    def _product_code(self) -> str:
        ft = self.forecasts_tab
        if ft is None:
            return ""
        return (ft.product_edit.text() or "").strip()

    def _logger(self):
        return getattr(self.forecasts_tab, "data_logger", None)

    def refresh_now(self):
        if self._fetching:
            return
        # Don't pull a year of rates until the user actually opens this tab
        # (Refresh All would otherwise hammer Octopus on every click).
        if not self._user_opened and not self.isVisible():
            return
        tariff = self._tariff_code()
        product = self._product_code()
        if not tariff:
            self.set_status(
                "Agile Year: set the Agile tariff on Forecasts first."
            )
            self.summary_label.setText(
                "No tariff code — enter it on the Forecasts tab, then Fetch year."
            )
            return
        self._fetching = True
        self.refresh_btn.setEnabled(False)
        try:
            self._chart_shimmer.start()
        except Exception:
            pass
        view = self._view
        self.set_status(
            f"Agile Year: fetching ~{_AGILE_YEAR_DAYS} days of "
            f"{'import' if view == 'import' else 'export'} rates…"
        )
        threading.Thread(
            target=self._fetch_thread,
            args=(product, tariff, view),
            daemon=True,
        ).start()

    def _fetch_thread(self, product, tariff, view):
        err = ""
        live = pl.DataFrame()
        db_slots = pl.DataFrame()
        logger = self._logger()
        db_daily = []
        if logger is not None and tariff:
            try:
                db_daily = logger.query_agile_year_daily(tariff, view) or []
            except Exception as e:
                _log.warn("AgileYear", f"DB daily read failed: {e}")
                db_daily = []
        if db_daily:
            self._inv.invoke(
                lambda d=list(db_daily), v=view, t=tariff: self._on_db_preview(d, v, t)
            )
        try:
            pdf = fetch_agile_standard_unit_rates(
                product, tariff, days_back=_AGILE_YEAR_DAYS,
            )
            live = _coerce_agile_frame(pdf)
        except Exception as e:
            err = str(e)
            _log.warn("AgileYear", f"Octopus year fetch failed: {e}")
        if (
            logger is not None
            and tariff
            and getattr(logger, "_primary_storage_backend", lambda: None)() is not None
        ):
            try:
                import pytz
                london = pytz.timezone("Europe/London")
                now_l = datetime.now(london)
                start = (now_l - timedelta(days=_AGILE_YEAR_DAYS)).replace(
                    hour=0, minute=0, second=0, microsecond=0,
                )
                end = (now_l + timedelta(days=2)).replace(
                    hour=0, minute=0, second=0, microsecond=0,
                )
                t0 = start.astimezone(timezone.utc)
                t1 = end.astimezone(timezone.utc)
                db_slots = logger.query_agile_prices(t0, t1, tariff, view)
            except Exception as e:
                _log.warn("AgileYear", f"DB year read failed: {e}")
                db_slots = pl.DataFrame()
        merged = _merge_agile_forecast_frames(live, db_slots)
        if logger is not None and not live.is_empty():
            try:
                logger.log_agile_forecast(live, tariff, view)
            except Exception as e:
                _log.warn("AgileYear", f"Could not persist year rates: {e}")
        daily_live = daily_agile_stats(merged)
        if logger is not None and daily_live:
            try:
                logger.log_agile_year_daily(daily_live, tariff, view)
            except Exception as e:
                _log.warn("AgileYear", f"Could not persist daily stats: {e}")
        daily = merge_daily_stats(db_daily, daily_live)
        source_bits = []
        if not live.is_empty():
            source_bits.append("Octopus API")
        if db_daily or (db_slots is not None and not db_slots.is_empty()):
            source_bits.append("database")
        source = " + ".join(source_bits) if source_bits else "none"
        self._inv.invoke(
            lambda: self._on_fetched(daily, view, tariff, source, err)
        )

    def _on_db_preview(self, daily, view, tariff):
        if view != self._view:
            return
        if self._daily:
            return
        self._daily = daily or []
        self._source_note = "database"
        self._render()
        self.set_status(
            f"Agile Year: {len(self._daily)} stored days — fetching Octopus…"
        )

    def _on_fetched(self, daily, view, tariff, source, err):
        self._fetching = False
        self.refresh_btn.setEnabled(True)
        try:
            self._chart_shimmer.stop()
        except Exception:
            pass
        if view != self._view:
            self.refresh_now()
            return
        self._daily = daily or []
        self._source_note = source
        self._loaded_key = f"{view}:{tariff}"
        self._render()
        if err and not self._daily:
            self.set_status(f"Agile Year: fetch failed ({err})")
        elif not self._daily:
            self.set_status(
                "Agile Year: no rates returned for this tariff over the year."
            )
        else:
            self.set_status(
                f"Agile Year: {len(self._daily)} days from {source}."
            )
        if self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception:
                pass

    # ── Render ───────────────────────────────────────────────────────────

    def _render(self):
        import pytz

        view_label = "Import" if self._view == "import" else "Export (outgoing)"
        self.title_label.setText(f"Agile year — {view_label}")
        rows = annotate_lt_stats(self._daily)
        self._fill_table(rows)
        self._draw_chart(rows, view_label)
        self._update_summary(rows, view_label)
        london = pytz.timezone("Europe/London")
        self.updated_label.setText(
            f"Updated: {datetime.now(london).strftime('%H:%M:%S')}"
        )

    def _price_item(self, value, *, user=None):
        item = _SortNumItem(f"{value:.2f}")
        item.setData(Qt.UserRole, float(value) if user is None else user)
        item.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
        color, _band = _agile_band_for_price(value)
        item.setBackground(QBrush(QColor(color)))
        item.setForeground(QBrush(QColor(_agile_readable_text_color(color))))
        item.setToolTip(f"{value:.2f} p/kWh inc. VAT")
        return item

    def _signed_item(self, value, *, text, tooltip, plus_bad=True):
        item = _SortNumItem(text)
        if value is None:
            item.setData(Qt.UserRole, None)
        else:
            item.setData(Qt.UserRole, float(value))
        item.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
        item.setToolTip(tooltip)
        if value is None:
            return item
        if plus_bad:
            if value > 5:
                item.setForeground(QBrush(QColor("#f38ba8")))
            elif value < -5:
                item.setForeground(QBrush(QColor("#a6e3a1")))
        return item

    def _fill_table(self, rows):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        today = _london_today()
        for r, rec in enumerate(rows):
            day = rec["day"]
            day_item = _SortNumItem(day.strftime("%a %d %b %Y"))
            try:
                day_item.setData(Qt.UserRole, int(day.strftime("%Y%m%d")))
            except Exception:
                day_item.setData(Qt.UserRole, 0)
            if day == today:
                font = day_item.font()
                font.setBold(True)
                day_item.setFont(font)
                day_item.setText(f"Today — {day.strftime('%a %d %b %Y')}")
            self.table.setItem(r, 0, day_item)
            self.table.setItem(r, 1, self._price_item(rec["high"]))
            self.table.setItem(r, 2, self._price_item(rec["low"]))
            self.table.setItem(r, 3, self._price_item(rec["avg"]))
            neg = rec["neg_hours"]
            if neg > 0.001:
                neg_item = _SortNumItem(f"{neg:.1f}")
                neg_item.setBackground(QBrush(QColor("#1565C0")))
                neg_item.setForeground(QBrush(QColor("#ffffff")))
                slots_neg = int(round(neg / 0.5))
                neg_item.setToolTip(
                    f"{neg:.1f} hours with price below 0p "
                    f"(about {slots_neg} half-hour slots)."
                )
            else:
                neg_item = _SortNumItem("—")
                neg_item.setToolTip("No half-hour slots below 0p this day.")
            neg_item.setData(Qt.UserRole, float(neg))
            neg_item.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
            self.table.setItem(r, 4, neg_item)
            slot_item = _SortNumItem(str(rec["slots"]))
            slot_item.setData(Qt.UserRole, float(rec["slots"]))
            slot_item.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
            slot_item.setToolTip(
                f"{rec['slots']} half-hour slots (46 or 50 on UK clock-change days)."
            )
            self.table.setItem(r, 5, slot_item)

            pct = rec.get("lt_pct")
            if pct is None:
                pct_item = self._signed_item(
                    None, text="—",
                    tooltip=(
                        "No long-term trend value that day (need at least three "
                        "stored days, or the trend was too close to 0p)."
                    ),
                )
            else:
                sign = "+" if pct > 0 else ""
                pct_item = self._signed_item(
                    pct,
                    text=f"{sign}{pct:.1f}%",
                    tooltip=(
                        f"{sign}{pct:.1f}% versus the long-term (since start) "
                        "linear trend of the daily average. Positive = more "
                        "expensive than that trend."
                    ),
                )
            self.table.setItem(r, 6, pct_item)

            z = rec.get("lt_z")
            if z is None:
                z_item = self._signed_item(
                    None, text="—",
                    tooltip="Need a long-term trend with a usable spread of residuals.",
                )
            else:
                sign = "+" if z > 0 else ""
                z_item = self._signed_item(
                    z,
                    text=f"{sign}{z:.2f} σ",
                    tooltip=(
                        f"{sign}{z:.2f} standard deviations from the long-term "
                        "trend residual. Positive = above the since-start line."
                    ),
                )
            self.table.setItem(r, 7, z_item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.SortOrder.DescendingOrder)

    def _discard_twin_axes(self):
        ax2 = getattr(self, "_ax2", None)
        if ax2 is not None:
            try:
                ax2.remove()
            except Exception:
                pass
            self._ax2 = None
        try:
            for extra in list(self.fig.axes):
                if extra is not self.ax:
                    extra.remove()
        except Exception:
            pass

    def _draw_empty_chart(self, message):
        self._discard_twin_axes()
        self.ax.clear()
        _style_ax_dark(self.ax, self.fig)
        self.ax.text(
            0.5, 0.5, message,
            ha="center", va="center", color=_DARK_SUBTEXT, fontsize=11,
            transform=self.ax.transAxes,
        )
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.canvas.draw_idle()

    def _plot_trend(self, days, avgs, *, colour, label, linestyle="--"):
        pred, _slope, _intercept = _fit_linear(days, avgs)
        if pred is None:
            return
        xs = [datetime.combine(d, time.min) for d in days]
        self.ax.plot(
            xs, pred, color=colour, linewidth=1.35, linestyle=linestyle,
            label=label, zorder=5,
        )

    def _draw_chart(self, rows, view_label):
        import matplotlib.dates as mdates

        if not rows:
            self._draw_empty_chart("No daily rates to plot.")
            return
        chrono = sorted(rows, key=lambda rec: rec["day"])
        xs = [datetime.combine(rec["day"], time.min) for rec in chrono]
        highs = [rec["high"] for rec in chrono]
        lows = [rec["low"] for rec in chrono]
        avgs = [rec["avg"] for rec in chrono]
        negs = [rec["neg_hours"] for rec in chrono]
        days = [rec["day"] for rec in chrono]

        self._discard_twin_axes()
        self.ax.clear()
        _style_ax_dark(self.ax, self.fig)
        self.ax.fill_between(
            xs, lows, highs, color="#89b4fa", alpha=0.22, linewidth=0,
            label="High–low range",
        )
        self.ax.plot(
            xs, avgs, color="#cdd6f4", linewidth=1.4, label="Daily average",
        )
        self.ax.plot(
            xs, highs, color="#f38ba8", linewidth=0.8, alpha=0.85, label="Highest",
        )
        self.ax.plot(
            xs, lows, color="#a6e3a1", linewidth=0.8, alpha=0.85, label="Lowest",
        )
        self.ax.axhline(0.0, color="#89b4fa", linewidth=0.7, linestyle="--", alpha=0.7)

        if self.chk_trend_monthly.isChecked():
            first = True
            for mxs, mys, _slope, _intercept in _monthly_segments(chrono):
                self.ax.plot(
                    mxs, mys, color=_TREND_MONTHLY_COLOUR, linewidth=1.3,
                    linestyle=":", zorder=5,
                    label="Monthly trend" if first else None,
                )
                first = False
        if self.chk_trend_ytd.isChecked():
            last_year = days[-1].year
            ytd = [(d, a) for d, a in zip(days, avgs) if d.year == last_year]
            if ytd:
                self._plot_trend(
                    [p[0] for p in ytd], [p[1] for p in ytd],
                    colour=_TREND_YTD_COLOUR, label="YTD trend", linestyle="-.",
                )
        if self.chk_trend_yearly.isChecked():
            end = days[-1]
            start = end - timedelta(days=365)
            window = [(d, a) for d, a in zip(days, avgs) if d >= start]
            if window:
                self._plot_trend(
                    [p[0] for p in window], [p[1] for p in window],
                    colour=_TREND_YEARLY_COLOUR, label="Yearly trend",
                )
        if self.chk_trend_start.isChecked():
            self._plot_trend(
                days, avgs, colour=_TREND_START_COLOUR, label="Since start (LT)",
                linestyle="-",
            )

        self.ax.set_ylabel("p/kWh inc. VAT")
        self.ax.set_title(
            f"{view_label} Agile — daily high / low / average (~year)"
        )
        ax2 = self.ax.twinx()
        self._ax2 = ax2
        ax2.set_facecolor("none")
        ax2.patch.set_visible(False)
        ax2.spines["left"].set_visible(False)
        ax2.spines["top"].set_visible(False)
        ax2.spines["bottom"].set_color(_DARK_GRID)
        ax2.spines["right"].set_color(_DARK_GRID)
        ax2.tick_params(axis="x", which="both", bottom=False, labelbottom=False)
        ax2.bar(
            xs, negs, width=0.8, color="#1565C0", alpha=0.45,
            label="Hours below 0p", zorder=1,
        )
        ax2.set_ylabel("Hours below 0p")
        ax2.yaxis.label.set_color("#89b4fa")
        ax2.tick_params(axis="y", colors="#89b4fa", labelsize=9)
        max_neg = max(negs) if negs else 0.0
        ax2.set_ylim(0, max(4.0, max_neg * 1.4) if max_neg else 4.0)

        loc = mdates.MonthLocator()
        self.ax.xaxis.set_major_locator(loc)
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        self.ax.figure.autofmt_xdate(rotation=30, ha="right")
        h1, l1 = self.ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        self.ax.legend(
            h1 + h2, l1 + l2,
            loc="upper left", fontsize=8, framealpha=0.35,
            facecolor=_DARK_FACE, edgecolor=_DARK_GRID, labelcolor=_DARK_TEXT,
            ncol=2,
        )
        self.fig.subplots_adjust(left=0.07, right=0.93, top=0.88, bottom=0.22)
        self.canvas.draw_idle()

    def _update_summary(self, rows, view_label):
        if not rows:
            extra = ""
            if self._source_note and self._source_note != "none":
                extra = f" Source tried: {self._source_note}."
            self.summary_label.setText(
                f"{view_label}: no daily stats yet.{extra}"
            )
            return
        days = [rec["day"] for rec in rows]
        d0, d1 = min(days), max(days)
        highs = [rec["high"] for rec in rows]
        lows = [rec["low"] for rec in rows]
        avg_of_avgs = sum(rec["avg"] for rec in rows) / len(rows)
        neg_hours = sum(rec["neg_hours"] for rec in rows)
        neg_days = sum(1 for rec in rows if rec["neg_hours"] > 0.001)
        src = f" Source: {self._source_note}." if self._source_note else ""
        self.summary_label.setText(
            f"{view_label}: {d0.strftime('%d %b %Y')} – {d1.strftime('%d %b %Y')} "
            f"({len(rows)} days). "
            f"Highest day {max(highs):.2f}p · lowest day {min(lows):.2f}p · "
            f"mean of daily averages {avg_of_avgs:.2f}p. "
            f"Below 0p: {neg_hours:.1f} hours across {neg_days} day"
            f"{'' if neg_days == 1 else 's'}.{src}"
        )


__all__ = [
    "AgileYearTab",
    "annotate_lt_stats",
    "daily_agile_stats",
    "merge_daily_stats",
]
