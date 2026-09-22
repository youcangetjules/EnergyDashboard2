"""
Energy Dashboard — `tabs/agile_prices.py`.

Grid view of Octopus Agile half-hourly slot prices for a three-day window
(yesterday / today / tomorrow by default), colour-coded like the Octopus
Energy app's own Agile schedule screen.

Live data comes from the Forecasts tab's already-fetched Agile DataFrames
(Refresh here triggers that same fetch). Historical days come from
``agile_price_snapshots`` in the DataLogger — written whenever Forecasts
persists a fetch — so Older / Newer can walk back through stored days.
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.tabs.forecasts import (
    _coerce_agile_frame,
    _merge_agile_forecast_frames,
)

# (upper bound exclusive, colour, legend label) — ascending, matches the
# banded legend on Octopus Energy's own Agile schedule view. The last
# entry's upper bound is None ("40p and over").
_AGILE_BANDS = (
    (0.0,  '#1565C0', 'Negative'),
    (5.0,  '#00897B', 'Under 5p'),
    (10.0, '#43A047', 'Under 10p'),
    (15.0, '#C0CA33', 'Over 10p'),
    (20.0, '#FDD835', 'Over 15p'),
    (25.0, '#FB8C00', 'Over 20p'),
    (30.0, '#F4511E', 'Over 25p'),
    (40.0, '#E53935', 'Over 30p'),
    (None, '#D81B60', 'Over 40p'),
)
_AGILE_NO_DATA_COLOR = '#3a3a4c'
_AGILE_GRID_COLS = 12
# How far Older may walk into DB history (calendar days behind today).
_AGILE_HISTORY_MAX_DAYS = 90


def _agile_band_for_price(price):
    """(colour_hex, legend_label) for a p/kWh value, per `_AGILE_BANDS`."""
    try:
        p = float(price)
    except (TypeError, ValueError):
        return _AGILE_NO_DATA_COLOR, 'No data'
    for upper, color, label in _AGILE_BANDS:
        if upper is None or p < upper:
            return color, label
    return _AGILE_BANDS[-1][1], _AGILE_BANDS[-1][2]


def _agile_readable_text_color(hex_color):
    """Dark or light text, whichever reads better on `hex_color`."""
    try:
        r, g, b = _hex_to_rgb(hex_color)
    except Exception:
        return '#ffffff'
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    return '#1e1e2e' if lum > 0.6 else '#ffffff'


class AgileSpotPricesTab(QWidget):
    """Colour-grid view of Octopus Agile import/export prices (3-day window)."""

    def __init__(self, forecasts_tab, status_callback):
        super().__init__()
        self.forecasts_tab = forecasts_tab
        self.set_status = status_callback
        self.on_data_updated = None
        self._view = 'import'
        # 0 = middle row is calendar today; negative = middle is older.
        self._anchor_offset = 0
        self.build_ui()

    # ── UI construction ─────────────────────────────────────────────────

    def _build_legend_bar(self):
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for _upper, color, label in _AGILE_BANDS:
            seg = QFrame()
            seg.setFixedHeight(28)
            seg.setStyleSheet(f"QFrame {{ background-color: {color}; border: none; }}")
            seg_lay = QHBoxLayout(seg)
            seg_lay.setContentsMargins(2, 0, 2, 0)
            text_color = _agile_readable_text_color(color)
            lbl = QLabel(label)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(
                f"color: {text_color}; font-size: 10px; font-weight: bold; "
                "border: none; background: transparent;"
            )
            seg_lay.addWidget(lbl)
            lay.addWidget(seg, 1)
        return bar

    def _make_day_section(self, days_layout, title: str):
        header = QLabel(title)
        header.setStyleSheet(
            f"color: {_DARK_TEXT}; font-weight: bold; font-size: 12px;"
        )
        days_layout.addWidget(header)
        host = QWidget()
        grid = QGridLayout(host)
        grid.setSpacing(6)
        grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        days_layout.addWidget(host)
        return header, grid

    def build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        legend_box = QGroupBox("Agile Tariff Colour Legend")
        legend_lay = QVBoxLayout(legend_box)
        legend_lay.setContentsMargins(8, 10, 8, 8)
        legend_lay.addWidget(self._build_legend_bar())
        main_layout.addWidget(legend_box)

        ctrl_box = QGroupBox("Agile Octopus Slots")
        ctrl_lay = QHBoxLayout(ctrl_box)
        ctrl_lay.setContentsMargins(10, 8, 10, 8)
        ctrl_lay.setSpacing(10)

        self.title_label = QLabel("Agile Octopus Slots")
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
        ctrl_lay.addSpacing(12)

        self.btn_older = QPushButton("◀ Older")
        self.btn_older.setToolTip(
            "Shift the three-day window one day into the past "
            "(uses prices stored in the database)."
        )
        self.btn_older.clicked.connect(self._on_older)
        _apply_primary_button_style(self.btn_older)
        ctrl_lay.addWidget(self.btn_older)

        self.btn_today = QPushButton("Today")
        self.btn_today.setToolTip("Jump back so the middle row is calendar today.")
        self.btn_today.clicked.connect(self._on_jump_today)
        _apply_primary_button_style(self.btn_today)
        ctrl_lay.addWidget(self.btn_today)

        self.btn_newer = QPushButton("Newer ▶")
        self.btn_newer.setToolTip("Shift the three-day window one day toward today.")
        self.btn_newer.clicked.connect(self._on_newer)
        _apply_primary_button_style(self.btn_newer)
        ctrl_lay.addWidget(self.btn_newer)

        ctrl_lay.addStretch(1)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip(
            "Re-fetch Agile prices (same fetch the Forecasts tab uses; this "
            "grid redraws once it completes). New slots are also saved to the DB."
        )
        self.refresh_btn.clicked.connect(self.refresh_now)
        _apply_primary_button_style(self.refresh_btn)
        ctrl_lay.addWidget(self.refresh_btn)
        main_layout.addWidget(ctrl_box)

        info_row = QHBoxLayout()
        self.hint_label = QLabel(
            "Prices include VAT. Default view: Yesterday · Today · Tomorrow. "
            "Use Older / Newer to walk stored history; Import/Export switches series."
        )
        self.hint_label.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px;")
        info_row.addWidget(self.hint_label, 1)
        self.updated_label = QLabel("Updated: --")
        self.updated_label.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 11px;")
        info_row.addWidget(self.updated_label, 0)
        main_layout.addLayout(info_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        days_host = QWidget()
        days_layout = QVBoxLayout(days_host)
        days_layout.setContentsMargins(0, 0, 0, 0)
        days_layout.setSpacing(4)
        days_layout.setAlignment(Qt.AlignTop)

        self.day_headers = []
        self.day_grids = []
        for i, title in enumerate(("Yesterday", "Today", "Tomorrow")):
            if i:
                days_layout.addSpacing(10)
            header, grid = self._make_day_section(days_layout, title)
            self.day_headers.append(header)
            self.day_grids.append(grid)

        scroll.setWidget(days_host)
        main_layout.addWidget(scroll, 1)

        summary_box = QGroupBox("Slot Summary")
        summary_lay = QVBoxLayout(summary_box)
        self.summary_label = QLabel("No data yet — click Refresh.")
        self.summary_label.setStyleSheet(f"color: {_DARK_TEXT}; font-size: 11px;")
        self.summary_label.setWordWrap(True)
        summary_lay.addWidget(self.summary_label)
        main_layout.addWidget(summary_box, 0)

        self._sync_nav_buttons()

    # ── Lifecycle / data plumbing ────────────────────────────────────────

    def auto_start(self):
        self.refresh_from_forecasts()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_from_forecasts()

    def _on_view_toggled(self, idx):
        self._view = 'import' if idx == 0 else 'export'
        self._render()

    def _on_older(self):
        if self._anchor_offset <= -_AGILE_HISTORY_MAX_DAYS:
            return
        self._anchor_offset -= 1
        self._sync_nav_buttons()
        self._render()

    def _on_newer(self):
        if self._anchor_offset >= 0:
            return
        self._anchor_offset += 1
        self._sync_nav_buttons()
        self._render()

    def _on_jump_today(self):
        if self._anchor_offset == 0:
            return
        self._anchor_offset = 0
        self._sync_nav_buttons()
        self._render()

    def _sync_nav_buttons(self):
        self.btn_newer.setEnabled(self._anchor_offset < 0)
        self.btn_today.setEnabled(self._anchor_offset != 0)
        self.btn_older.setEnabled(self._anchor_offset > -_AGILE_HISTORY_MAX_DAYS)

    def refresh_now(self):
        """Ask the Forecasts tab to fetch (Agile + solar); our grid redraws
        via `refresh_from_forecasts()` once that finishes."""
        ft = self.forecasts_tab
        if ft is None:
            return
        ft.fetch_forecasts()
        self.set_status("Agile Spot Prices: refreshing (via Forecasts fetch)…")

    def refresh_from_forecasts(self):
        """Re-read Forecasts / DB Agile data and redraw the three-day grid."""
        self._render()
        if self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception:
                pass

    def _current_mem_df(self):
        ft = self.forecasts_tab
        if ft is None:
            return None
        return ft.agile_df if self._view == 'import' else ft.agile_export_df

    def _tariff_code(self) -> str:
        ft = self.forecasts_tab
        if ft is None:
            return ""
        if self._view == 'import':
            return (ft.tariff_edit.text() or "").strip()
        return (ft.export_tariff_edit.text() or "").strip()

    def _day_label(self, day_date, today):
        """Relative name when the day is near today; otherwise weekday + date."""
        delta = (day_date - today).days
        if delta == -1:
            word = "Yesterday"
        elif delta == 0:
            word = "Today"
        elif delta == 1:
            word = "Tomorrow"
        else:
            word = day_date.strftime('%A')
        return f"{word} — {day_date.strftime('%a %d %b %Y')}"

    def _empty_frame_msg(self, day_date, today):
        if day_date > today:
            return (
                "Tomorrow's rates aren't published yet — usually available "
                "mid-afternoon."
                if (day_date - today).days == 1
                else "No published rates for this future day yet."
            )
        if day_date < today:
            return (
                "No stored prices for this day in the database yet. "
                "They appear after a Forecasts / Refresh fetch once that day "
                "has been seen."
            )
        return "No Agile data yet — click Refresh (fetches via the Forecasts tab)."

    def _prices_for_window(self, start_date, end_date):
        """Merge in-memory Forecasts Agile data with DB snapshots for the window.

        Live/memory wins on duplicate slots. Returns a Polars frame (may be empty).
        """
        mem = _coerce_agile_frame(self._current_mem_df())
        logger = getattr(self.forecasts_tab, "data_logger", None)
        tariff = self._tariff_code()
        db = pl.DataFrame()
        if (
            logger is not None
            and tariff
            and getattr(logger, "_primary_storage_backend", lambda: None)() is not None
        ):
            try:
                import pytz
                london = pytz.timezone("Europe/London")
                t0 = london.localize(
                    datetime.combine(start_date, datetime.min.time())
                ).astimezone(timezone.utc)
                t1 = london.localize(
                    datetime.combine(end_date + timedelta(days=1), datetime.min.time())
                ).astimezone(timezone.utc)
                db = logger.query_agile_prices(t0, t1, tariff, self._view)
            except Exception as e:
                try:
                    self.set_status(f"Agile Spot Prices: DB history read failed ({e})")
                except Exception:
                    pass
                db = pl.DataFrame()
        return _merge_agile_forecast_frames(mem, db)

    # ── Rendering ─────────────────────────────────────────────────────────

    def _render(self):
        import pytz
        london = pytz.timezone('Europe/London')
        now_l = datetime.now(london)
        today = now_l.date()
        middle = today + timedelta(days=self._anchor_offset)
        days = [
            middle - timedelta(days=1),
            middle,
            middle + timedelta(days=1),
        ]
        view_label = "Import" if self._view == 'import' else "Export (outgoing)"
        self.title_label.setText(f"Agile Octopus Slots — {view_label}")

        df = self._prices_for_window(days[0], days[2])

        for header, grid, day in zip(self.day_headers, self.day_grids, days):
            header.setText(self._day_label(day, today))
            self._build_day_grid(grid, df, day, now_l, today)

        self._update_summary(df, days, today, view_label)
        self.updated_label.setText(f"Updated: {datetime.now().strftime('%H:%M:%S')}")
        self._sync_nav_buttons()

    @staticmethod
    def _clear_grid(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _build_day_grid(self, layout, df, day_date, now_l, today):
        self._clear_grid(layout)
        if df is None or df.is_empty():
            lbl = QLabel(self._empty_frame_msg(day_date, today))
            lbl.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 12px; padding: 16px;")
            layout.addWidget(lbl, 0, 0)
            return
        try:
            day_df = df.filter(pl.col('valid_from').dt.date() == day_date).sort('valid_from')
        except Exception:
            day_df = pl.DataFrame()
        if day_df.is_empty():
            lbl = QLabel(self._empty_frame_msg(day_date, today))
            lbl.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 12px; padding: 16px;")
            layout.addWidget(lbl, 0, 0)
            return
        for i, row in enumerate(day_df.iter_rows(named=True)):
            r, c = divmod(i, _AGILE_GRID_COLS)
            t = row['valid_from']
            t_to = row.get('valid_to')
            price = row['price_pence']
            is_now = bool(t_to is not None and t <= now_l < t_to)
            layout.addWidget(self._make_slot_cell(t, price, is_now), r, c)

    def _make_slot_cell(self, t, price, is_now):
        color, band_label = _agile_band_for_price(price)
        text_color = _agile_readable_text_color(color)
        try:
            price_f = float(price)
            price_text = f"{price_f:.2f}p"
        except (TypeError, ValueError):
            price_f = None
            price_text = "—"
        frame = QFrame()
        frame.setMinimumSize(74, 52)
        tip = f"{t.strftime('%a %d %b, %H:%M')} — {band_label}"
        if price_f is not None:
            tip = f"{t.strftime('%a %d %b, %H:%M')} — {price_f:.2f} p/kWh ({band_label})"
        frame.setToolTip(tip)
        border = f"2px solid {_UI_BLUE}" if is_now else "1px solid rgba(0, 0, 0, 60)"
        frame.setStyleSheet(
            f"QFrame {{ background-color: {color}; border: {border}; border-radius: 5px; }}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(1)
        t_lbl = QLabel(t.strftime('%H:%M'))
        t_lbl.setAlignment(Qt.AlignCenter)
        t_lbl.setStyleSheet(
            f"color: {text_color}; font-weight: bold; font-size: 11px; "
            "border: none; background: transparent;"
        )
        p_lbl = QLabel(price_text)
        p_lbl.setAlignment(Qt.AlignCenter)
        p_lbl.setStyleSheet(
            f"color: {text_color}; font-size: 11px; border: none; background: transparent;"
        )
        lay.addWidget(t_lbl)
        lay.addWidget(p_lbl)
        if is_now:
            now_lbl = QLabel("● now")
            now_lbl.setAlignment(Qt.AlignCenter)
            now_lbl.setStyleSheet(
                f"color: {text_color}; font-size: 9px; font-weight: bold; "
                "border: none; background: transparent;"
            )
            lay.addWidget(now_lbl)
        return frame

    def _summary_line_for_day(self, df, day_date, today, view_label):
        word = self._day_label(day_date, today).split(" — ", 1)[0]
        if df is None or df.is_empty():
            return f"{view_label} ({word}): no data yet."
        try:
            day_df = df.filter(pl.col('valid_from').dt.date() == day_date)
        except Exception:
            day_df = pl.DataFrame()
        if day_df.is_empty():
            if day_date > today:
                suffix = "not published yet"
            elif day_date < today:
                suffix = "not in DB yet"
            else:
                suffix = "no data yet"
            return f"{view_label} ({word}, {day_date.strftime('%a %d %b')}): {suffix}."
        prices = day_df['price_pence']
        cheapest = day_df.sort('price_pence').row(0, named=True)
        priciest = day_df.sort('price_pence', descending=True).row(0, named=True)
        return (
            f"{view_label} ({word}, {day_date.strftime('%a %d %b')}): "
            f"min {prices.min():.2f}p @ {cheapest['valid_from'].strftime('%H:%M')}  |  "
            f"max {prices.max():.2f}p @ {priciest['valid_from'].strftime('%H:%M')}  |  "
            f"avg {prices.mean():.2f}p  |  {day_df.height} slots"
        )

    def _update_summary(self, df, days, today, view_label):
        lines = [
            self._summary_line_for_day(df, d, today, view_label) for d in days
        ]
        self.summary_label.setText('\n'.join(lines))


__all__ = ["AgileSpotPricesTab"]
