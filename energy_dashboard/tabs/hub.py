"""
Energy Dashboard — `tabs/hub.py`.

Hub tab: a landing page with compact summary tiles that link to deeper tabs.
Tiles are added incrementally — this initial version contains Battery SOC.
"""
from __future__ import annotations

from energy_dashboard.common import *

_TILE_QSS = (
    f"QGroupBox {{ background: {_DARK_SURFACE_BG}; border: 1px solid #313244; "
    "border-radius: 8px; margin-top: 0; padding: 12px; "
    "color: #cdd6f4; font-weight: bold; }}"
)

_SOC_GREEN = "#a6e3a1"
_SOC_AMBER = "#fab387"
_SOC_PINK = "#f38ba8"


class _ClickableGroupBox(QGroupBox):
    """QGroupBox that navigates to a target tab on click."""

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self._target_attr: str | None = None
        self._dash = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_nav(self, dash, attr: str):
        self._dash = dash
        self._target_attr = attr

    def mousePressEvent(self, event):
        if self._dash and self._target_attr:
            widget = getattr(self._dash, self._target_attr, None)
            if widget is not None:
                self._dash.show_main_page(widget)
                return
        super().mousePressEvent(event)


class HubTab(QWidget):
    def __init__(self, status_callback, dashboard=None):
        super().__init__()
        self.set_status = status_callback
        self.dash = dashboard
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        ctrl = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        refresh_btn.clicked.connect(self.refresh)
        ctrl.addWidget(refresh_btn)
        title = QLabel("Hub — key metrics at a glance")
        title.setStyleSheet("color: #6c7086; font-style: italic;")
        ctrl.addWidget(title)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # Tile grid — wrapping flow via nested layouts.
        self._tile_area = QHBoxLayout()
        self._tile_area.setSpacing(12)
        self._tile_area.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self._soc_tile, self._soc_val, self._soc_detail = self._make_soc_tile()
        self._tile_area.addWidget(self._soc_tile)

        self._tile_area.addStretch()
        layout.addLayout(self._tile_area)
        layout.addStretch()

    def _make_soc_tile(self):
        tile = _ClickableGroupBox("Battery SOC")
        tile.setStyleSheet(_TILE_QSS)
        tile.setFixedSize(220, 140)
        if self.dash:
            tile.set_nav(self.dash, "battery_tab")

        inner = QVBoxLayout(tile)
        inner.setContentsMargins(8, 8, 8, 8)
        inner.setSpacing(4)

        val_label = QLabel("—")
        val_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val_label.setStyleSheet(
            f"font-size: 36pt; font-weight: bold; color: {_SOC_GREEN};"
        )
        inner.addWidget(val_label)

        detail_label = QLabel("No data")
        detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detail_label.setStyleSheet("font-size: 12pt; color: #6c7086;")
        inner.addWidget(detail_label)

        return tile, val_label, detail_label

    # ── Refresh ───────────────────────────────────────────────────────
    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        self._refresh_soc()
        self.set_status("Hub refreshed.")

    def _refresh_soc(self):
        gt = getattr(self.dash, "growatt_tab", None) if self.dash else None
        if gt is None:
            return
        data = gt.get_live_data_summary()
        if data is None:
            self._soc_val.setText("—")
            self._soc_val.setStyleSheet(
                f"font-size: 36pt; font-weight: bold; color: #6c7086;"
            )
            self._soc_detail.setText("No data")
            return

        # SOC value + colour
        try:
            soc = float(data.get("soc", 0))
        except (TypeError, ValueError):
            soc = 0.0
        if soc > 50:
            colour = _SOC_GREEN
        elif soc > 20:
            colour = _SOC_AMBER
        else:
            colour = _SOC_PINK
        self._soc_val.setText(f"{soc:.0f}%")
        self._soc_val.setStyleSheet(
            f"font-size: 36pt; font-weight: bold; color: {colour};"
        )

        # Battery power detail
        try:
            bp = float(data.get("bat_power", 0))
        except (TypeError, ValueError):
            bp = 0.0
        if bp > 0.01:
            detail = f"Charging {bp:.2f} kW"
        elif bp < -0.01:
            detail = f"Discharging {abs(bp):.2f} kW"
        else:
            detail = "Idle"
        self._soc_detail.setText(detail)
        self._soc_detail.setStyleSheet("font-size: 12pt; color: #a6adc8;")


__all__ = [n for n in globals() if not n.startswith('__')]
