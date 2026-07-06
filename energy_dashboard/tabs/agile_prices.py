"""
Energy Dashboard — `tabs/agile_prices.py`.

Grid view of Octopus Agile half-hourly slot prices for today / tomorrow,
colour-coded like the Octopus Energy app's own Agile schedule screen.
Reuses the Agile DataFrames the Forecasts tab already fetches (and merges
with DB history) so this tab never issues its own extra API calls — the
Refresh button here simply asks the Forecasts tab to fetch, and this tab
redraws once that completes.
"""
from __future__ import annotations

from energy_dashboard.common import *

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
    """Read-only colour-grid view of Octopus Agile import/export prices."""

    def __init__(self, forecasts_tab, status_callback):
        super().__init__()
        self.forecasts_tab = forecasts_tab
        self.set_status = status_callback
        self.on_data_updated = None
        self._view = 'import'
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
        ctrl_lay.addStretch(1)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip(
            "Re-fetch Agile prices (same fetch the Forecasts tab uses; this "
            "grid redraws once it completes)."
        )
        self.refresh_btn.clicked.connect(self.refresh_now)
        ctrl_lay.addWidget(self.refresh_btn)
        main_layout.addWidget(ctrl_box)

        info_row = QHBoxLayout()
        self.hint_label = QLabel(
            "Prices include VAT. Today's slots are shown above tomorrow's; "
            "use Import/Export to change which price series fills the grids."
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

        self.today_header = QLabel("Today")
        self.today_header.setStyleSheet(
            f"color: {_DARK_TEXT}; font-weight: bold; font-size: 12px;"
        )
        days_layout.addWidget(self.today_header)
        today_grid_host = QWidget()
        self.grid_layout_today = QGridLayout(today_grid_host)
        self.grid_layout_today.setSpacing(6)
        self.grid_layout_today.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        days_layout.addWidget(today_grid_host)

        days_layout.addSpacing(10)

        self.tomorrow_header = QLabel("Tomorrow")
        self.tomorrow_header.setStyleSheet(
            f"color: {_DARK_TEXT}; font-weight: bold; font-size: 12px;"
        )
        days_layout.addWidget(self.tomorrow_header)
        tomorrow_grid_host = QWidget()
        self.grid_layout_tomorrow = QGridLayout(tomorrow_grid_host)
        self.grid_layout_tomorrow.setSpacing(6)
        self.grid_layout_tomorrow.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        days_layout.addWidget(tomorrow_grid_host)

        scroll.setWidget(days_host)
        main_layout.addWidget(scroll, 1)

        summary_box = QGroupBox("Slot Summary")
        summary_lay = QVBoxLayout(summary_box)
        self.summary_label = QLabel("No data yet — click Refresh.")
        self.summary_label.setStyleSheet(f"color: {_DARK_TEXT}; font-size: 11px;")
        self.summary_label.setWordWrap(True)
        summary_lay.addWidget(self.summary_label)
        main_layout.addWidget(summary_box, 0)

    # ── Lifecycle / data plumbing ────────────────────────────────────────

    def auto_start(self):
        self.refresh_from_forecasts()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_from_forecasts()

    def _on_view_toggled(self, idx):
        self._view = 'import' if idx == 0 else 'export'
        self._render()

    def refresh_now(self):
        """Ask the Forecasts tab to fetch (Agile + solar); our grid redraws
        via `refresh_from_forecasts()` once that finishes."""
        ft = self.forecasts_tab
        if ft is None:
            return
        ft.fetch_forecasts()
        self.set_status("Agile Spot Prices: refreshing (via Forecasts fetch)…")

    def refresh_from_forecasts(self):
        """Re-read the Forecasts tab's already-fetched Agile DataFrames
        (no extra Octopus API calls) and redraw the grid."""
        self._render()
        if self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception:
                pass

    def _current_df(self):
        ft = self.forecasts_tab
        if ft is None:
            return None
        return ft.agile_df if self._view == 'import' else ft.agile_export_df

    # ── Rendering ─────────────────────────────────────────────────────────

    def _render(self):
        import pytz
        london = pytz.timezone('Europe/London')
        now_l = datetime.now(london)
        today = now_l.date()
        tomorrow = today + timedelta(days=1)
        df = self._current_df()
        view_label = "Import" if self._view == 'import' else "Export (outgoing)"

        self.title_label.setText(f"Agile Octopus Slots — {view_label}")
        self.today_header.setText(f"Today — {today.strftime('%a %d %b %Y')}")
        self.tomorrow_header.setText(f"Tomorrow — {tomorrow.strftime('%a %d %b %Y')}")

        self._build_day_grid(self.grid_layout_today, df, today, now_l)
        self._build_day_grid(self.grid_layout_tomorrow, df, tomorrow, now_l)
        self._update_summary(df, today, tomorrow, view_label)
        self.updated_label.setText(f"Updated: {datetime.now().strftime('%H:%M:%S')}")

    @staticmethod
    def _clear_grid(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _build_day_grid(self, layout, df, day_date, now_l):
        self._clear_grid(layout)
        if df is None or df.is_empty():
            lbl = QLabel("No Agile data yet — click Refresh (fetches via the Forecasts tab).")
            lbl.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 12px; padding: 16px;")
            layout.addWidget(lbl, 0, 0)
            return
        try:
            day_df = df.filter(pl.col('valid_from').dt.date() == day_date).sort('valid_from')
        except Exception:
            day_df = pl.DataFrame()
        if day_df.is_empty():
            msg = (
                "No data for this day yet."
                if day_date <= now_l.date()
                else "Tomorrow's rates aren't published yet — usually available mid-afternoon."
            )
            lbl = QLabel(msg)
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

    def _summary_line_for_day(self, df, day_date, day_word, view_label):
        if df is None or df.is_empty():
            return f"{view_label} ({day_word}): no data yet."
        try:
            day_df = df.filter(pl.col('valid_from').dt.date() == day_date)
        except Exception:
            day_df = pl.DataFrame()
        if day_df.is_empty():
            suffix = "not published yet" if day_word == "tomorrow" else "no data yet"
            return f"{view_label} ({day_word}, {day_date.strftime('%a %d %b')}): {suffix}."
        prices = day_df['price_pence']
        cheapest = day_df.sort('price_pence').row(0, named=True)
        priciest = day_df.sort('price_pence', descending=True).row(0, named=True)
        return (
            f"{view_label} ({day_word}, {day_date.strftime('%a %d %b')}): "
            f"min {prices.min():.2f}p @ {cheapest['valid_from'].strftime('%H:%M')}  |  "
            f"max {prices.max():.2f}p @ {priciest['valid_from'].strftime('%H:%M')}  |  "
            f"avg {prices.mean():.2f}p  |  {day_df.height} slots"
        )

    def _update_summary(self, df, today, tomorrow, view_label):
        lines = [
            self._summary_line_for_day(df, today, "today", view_label),
            self._summary_line_for_day(df, tomorrow, "tomorrow", view_label),
        ]
        self.summary_label.setText('\n'.join(lines))


__all__ = [n for n in globals() if not n.startswith('__')]
