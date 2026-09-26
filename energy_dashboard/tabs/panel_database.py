"""
Physical Plant — the modules installed on this roof.

The householder types maker, model, rated watts, and datasheet volts.
Blank voltage cells stay blank. Roof layout’s panel list reads this table.
"""
from __future__ import annotations

import uuid

from energy_dashboard.common import *
from energy_dashboard.plant.panel_catalog import list_panels, save_panels

_COLS = ("Maker", "Model", "Wp", "Vmp", "Voc", "Imp", "Width m", "Height m")
_KEYS = ("maker", "model", "wp", "vmp", "voc", "imp", "w_m", "h_m")
_VOLT_KEYS = {"vmp", "voc", "imp"}


def _cell_text(value, key: str) -> str:
    if value is None or value == "":
        return ""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if key == "wp":
        return str(int(num)) if num.is_integer() else f"{num:.1f}"
    if key in _VOLT_KEYS:
        return f"{num:.2f}".rstrip("0").rstrip(".")
    if key in ("w_m", "h_m"):
        return f"{num:.3f}".rstrip("0").rstrip(".")
    return str(value)


class PanelDatabaseTab(QWidget):
    """Catalogue of PV modules for this house. Not a live measurement."""

    def __init__(self, status_callback=None, dash=None):
        super().__init__()
        self.set_status = status_callback
        self.dash = dash
        self.on_data_updated = None
        self._rows: list[dict] = []
        self._suppress = False
        self.build_ui()
        self.reload()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        intro = QLabel(
            "The modules on this roof. Roof layout uses this list for each face. "
            "<b>Vmp</b> is the datasheet voltage at maximum power — leave it "
            "blank if you do not have the sheet. Live string voltage is not "
            "copied in here."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        root.addWidget(intro)

        bar = QHBoxLayout()
        self.btn_add = QPushButton("Add panel")
        self.btn_add.setToolTip("Add a blank module row.")
        self.btn_add.clicked.connect(self._add_row)
        bar.addWidget(self.btn_add)
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setToolTip("Remove the selected module.")
        self.btn_remove.clicked.connect(self._remove_row)
        bar.addWidget(self.btn_remove)
        bar.addStretch(1)
        self.btn_save = QPushButton("Save")
        self.btn_save.setToolTip("Keep this list. Roof layout picks panels from it.")
        self.btn_save.clicked.connect(self.save)
        bar.addWidget(self.btn_save)
        for btn in (self.btn_add, self.btn_remove, self.btn_save):
            _apply_primary_button_style(btn)
        root.addLayout(bar)

        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(list(_COLS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in range(2, len(_COLS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        tips = {
            2: "Rated power of one module, in watts.",
            3: "Datasheet volts at maximum power. Leave blank if unknown. Not the live string reading.",
            4: "Datasheet open-circuit volts. Leave blank if unknown.",
            5: "Datasheet current at maximum power, in amps. Leave blank if unknown.",
            6: "Module width in metres, for roof layout.",
            7: "Module height in metres, for roof layout.",
        }
        for col, tip in tips.items():
            item = self.table.horizontalHeaderItem(col)
            if item is not None:
                item.setToolTip(tip)
        root.addWidget(self.table, 1)

        self.lbl_detail = QLabel("")
        self.lbl_detail.setWordWrap(True)
        self.lbl_detail.setStyleSheet("color: #6c7086; font-size: 11px;")
        root.addWidget(self.lbl_detail)

    def reload(self):
        self._rows = list_panels()
        self._fill()

    def _fill(self):
        self._suppress = True
        self.table.setRowCount(len(self._rows))
        for row, panel in enumerate(self._rows):
            for col, key in enumerate(_KEYS):
                self.table.setItem(row, col, QTableWidgetItem(_cell_text(panel.get(key), key)))
        self._suppress = False
        n = len(self._rows)
        self.lbl_detail.setText(
            f"{n} module type(s). A blank voltage is left blank — it is not stored as 0 V."
        )

    def _read_table(self) -> list[dict]:
        rows = []
        for row in range(self.table.rowCount()):
            src = self._rows[row] if row < len(self._rows) else {}
            item = {"id": src.get("id") or str(uuid.uuid4())}
            for col, key in enumerate(_KEYS):
                cell = self.table.item(row, col)
                item[key] = cell.text().strip() if cell is not None else ""
            rows.append(item)
        return rows

    def _add_row(self):
        self._rows = self._read_table()
        self._rows.append({
            "id": str(uuid.uuid4()),
            "maker": "",
            "model": "",
            "wp": None,
            "vmp": None,
            "voc": None,
            "imp": None,
            "w_m": None,
            "h_m": None,
        })
        self._fill()
        last = self.table.rowCount() - 1
        if last >= 0:
            self.table.selectRow(last)
            self.table.setCurrentCell(last, 0)
            self.table.editItem(self.table.item(last, 0))

    def _remove_row(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return
        row = selected[0].row()
        self._rows = self._read_table()
        if 0 <= row < len(self._rows):
            del self._rows[row]
        self._fill()

    def save(self):
        self._rows = save_panels(self._read_table())
        self._fill()
        n = len(self._rows)
        if self.set_status:
            self.set_status(f"Panel database: {n} module type(s) saved.")
        roof = getattr(self.dash, "roof_layout_tab", None) if self.dash else None
        refresh = getattr(roof, "reload_panel_choices", None)
        if callable(refresh):
            refresh()
        if self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception:
                pass


__all__ = ["PanelDatabaseTab"]
