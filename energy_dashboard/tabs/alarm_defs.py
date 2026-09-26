"""
Energy Dashboard — Alarm defs tab (Controls group).

Lists the standing alarm rules from ``ALARM_CATALOGUE``. Thresholds that
can be changed (hold time, spare-solar minimum, low-battery line) are read
from the same settings Setup & Info saves. This tab does not invent rules.
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.core.alarms import (
    ALARM_CATALOGUE,
    DEFAULT_HOLD_MINUTES,
    DEFAULT_PV_MIN_KW,
)


class AlarmDefsTab(QWidget):
    """Read-only list of the alarms the tray and the Alarms button can raise."""

    def __init__(self, dash=None):
        super().__init__()
        self.dash = dash
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("Alarm defs")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #cdd6f4;")
        head.addWidget(title)
        head.addStretch(1)
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.setFixedWidth(110)
        self.reload_btn.setToolTip(
            "Re-read the hold time, spare-solar minimum, and low-battery line"
        )
        self.reload_btn.clicked.connect(self.reload)
        head.addWidget(self.reload_btn)
        layout.addLayout(head)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(self.summary)

        hint = QLabel(
            "These are the rules behind the Alarms button and the tray menu. "
            "Change the hold time, the spare-solar minimum, and the low-battery "
            "line under Setup &amp; Info → Live alarms."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Alarm", "Level", "Fires after", "What it means"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self.table, 1)
        self._fill_catalogue()
        self.reload()

    def showEvent(self, event):
        super().showEvent(event)
        self.reload()

    def _settings_line(self) -> str:
        s = QSettings("PowerModel", "EnergyDashboard2")
        enabled = s.value("alarms/enabled", True, type=bool)
        hold = float(s.value("alarms/hold_minutes", DEFAULT_HOLD_MINUTES) or DEFAULT_HOLD_MINUTES)
        pv_min = float(s.value("alarms/pv_min_kw", DEFAULT_PV_MIN_KW) or DEFAULT_PV_MIN_KW)
        try:
            soc = int(s.value("params/battery_low_soc_threshold_pct", 10))
        except (TypeError, ValueError):
            soc = 10
        if enabled:
            state = "Live alarms are on."
        else:
            state = "Live alarms are off. The rules below are what would fire if you turn them on."
        return (
            f"{state} A low battery or unused solar must last {hold:.0f} minutes "
            f"before it fires. Spare solar counts from {pv_min:.1f} kW. "
            f"The low-battery line is {soc}%. "
            "Tray notices start straight away, then four times every 5 minutes, "
            "four times every 10, four times every 30, then once an hour."
        )

    def _fill_catalogue(self) -> None:
        self.table.setRowCount(len(ALARM_CATALOGUE))
        for row, spec in enumerate(ALARM_CATALOGUE):
            cells = (spec.name, spec.level, spec.fires_after, spec.meaning)
            level = (spec.level or "").lower()
            if "critical" in level and "warning" not in level:
                colour = QColor("#f38ba8")
            elif level.startswith("warning"):
                colour = QColor("#f9e2af")
            else:
                colour = QColor("#cdd6f4")
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                item.setForeground(colour if col < 2 else QColor("#cdd6f4"))
                self.table.setItem(row, col, item)
        self.table.resizeRowsToContents()

    def reload(self) -> None:
        self.summary.setText(self._settings_line())


__all__ = ["AlarmDefsTab"]
