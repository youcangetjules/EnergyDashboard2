"""
Energy Dashboard — `tabs/avg_spot_price.py`.

Vertical bar chart of the daily average Agile spot price (p/kWh inc. VAT).
Data comes from the pre-aggregated ``agile_year_daily`` table so no heavy
half-hour crunching is needed at view time.
"""
from __future__ import annotations

from datetime import date as date_cls, timedelta

from energy_dashboard.common import *
from energy_dashboard.tabs.agile_prices import _agile_band_for_price

_RANGE_OPTIONS = (
    ("Last 30 days", 30),
    ("Last 90 days", 90),
    ("Last 180 days", 180),
    ("Last 365 days", 365),
)


class AvgSpotPriceTab(QWidget):
    def __init__(self, status_callback, dashboard=None):
        super().__init__()
        self.set_status = status_callback
        self.dash = dashboard
        self._view = "import"
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        ctrl = QHBoxLayout()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        refresh_btn.clicked.connect(self.refresh)
        ctrl.addWidget(refresh_btn)

        ctrl.addSpacing(16)
        ctrl.addWidget(QLabel("Range:"))
        self._range_combo = QComboBox()
        for label, days in _RANGE_OPTIONS:
            self._range_combo.addItem(label, days)
        self._range_combo.setCurrentIndex(1)  # default 90 days
        apply_combo_field_motif(self._range_combo, width=140)
        self._range_combo.currentIndexChanged.connect(lambda _: self.refresh())
        ctrl.addWidget(self._range_combo)

        ctrl.addSpacing(16)
        self._import_btn = QPushButton("Import")
        self._export_btn = QPushButton("Export")
        for btn in (self._import_btn, self._export_btn):
            btn.setFixedWidth(80)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._import_btn.clicked.connect(lambda: self._set_view("import"))
        self._export_btn.clicked.connect(lambda: self._set_view("export"))
        ctrl.addWidget(self._import_btn)
        ctrl.addWidget(self._export_btn)
        self._style_toggle_buttons()

        ctrl.addStretch()
        layout.addLayout(ctrl)

        # Chart
        self._fig = Figure(figsize=(10, 5), dpi=100)
        self._ax = self._fig.add_subplot(111)
        self._canvas = FigureCanvas(self._fig)
        enable_bar_value_hover(self._canvas)
        layout.addWidget(self._canvas, 1)

    def _style_toggle_buttons(self):
        active_qss = (
            f"QPushButton {{ background: {_BTN_GREEN_BG}; color: #cdd6f4; "
            "border: 1px solid #a6e3a1; border-radius: 4px; padding: 4px; font-weight: bold; }"
        )
        inactive_qss = (
            f"QPushButton {{ background: {_DARK_SURFACE_BG}; color: #6c7086; "
            "border: 1px solid #313244; border-radius: 4px; padding: 4px; }"
        )
        self._import_btn.setStyleSheet(active_qss if self._view == "import" else inactive_qss)
        self._export_btn.setStyleSheet(active_qss if self._view == "export" else inactive_qss)

    def _set_view(self, view: str):
        if self._view == view:
            return
        self._view = view
        self._style_toggle_buttons()
        self.refresh()

    # ── Data ──────────────────────────────────────────────────────────
    def _tariff_code(self) -> str:
        ft = getattr(self.dash, "forecasts_tab", None) if self.dash else None
        if ft is None:
            return ""
        if self._view == "import":
            return (ft.tariff_edit.text() or "").strip()
        return (ft.export_tariff_edit.text() or "").strip()

    def _query(self) -> list[dict]:
        dl = getattr(self.dash, "data_logger", None) if self.dash else None
        if dl is None:
            return []
        tariff = self._tariff_code()
        if not tariff:
            return []
        return dl.query_agile_year_daily(tariff, self._view) or []

    # ── Chart ─────────────────────────────────────────────────────────
    def _draw(self, daily: list[dict]):
        ax = self._ax
        ax.clear()
        _style_ax_dark(ax, self._fig)

        days = self._range_combo.currentData() or 90
        cutoff = date_cls.today() - timedelta(days=days)
        filtered = [d for d in daily if d["day"] >= cutoff]
        filtered.sort(key=lambda d: d["day"])

        if not filtered:
            ax.text(
                0.5, 0.5,
                "No daily price data\nFetch prices in the Forecasts tab first",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=13, color="#6c7086",
            )
            self._fig.tight_layout()
            self._canvas.draw()
            return

        dates = [d["day"] for d in filtered]
        avgs = [d["avg"] for d in filtered]
        colors = [_agile_band_for_price(v)[0] for v in avgs]

        ax.bar(dates, avgs, color=colors, width=0.8, edgecolor="none", zorder=3)
        ax.axhline(y=0, color=_DARK_GRID, linewidth=0.6, zorder=2)

        ax.set_ylabel("p/kWh (inc. VAT)", fontsize=10)
        direction = "Import" if self._view == "import" else "Export"
        ax.set_title(
            f"Daily average Agile {direction} price — last {days} days",
            fontsize=12, fontweight="bold", pad=10,
        )
        ax.grid(axis="y", color=_DARK_GRID, linewidth=0.4, zorder=0)
        ax.tick_params(axis="x", rotation=45, labelsize=8)

        self._fig.tight_layout()
        self._canvas.draw()

    # ── Refresh ───────────────────────────────────────────────────────
    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        daily = self._query()
        self._draw(daily)
        days = self._range_combo.currentData() or 90
        cutoff = date_cls.today() - timedelta(days=days)
        n = sum(1 for d in daily if d["day"] >= cutoff)
        self.set_status(f"Avg. spot price: {n} days shown ({self._view}).")


__all__ = [n for n in globals() if not n.startswith('__')]
