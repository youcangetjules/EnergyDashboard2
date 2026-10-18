"""
Physical Plant — design scenarios for string voltage.

Each scenario is a pair of series counts. The panel datasheet and the
inverter's voltage limits decide whether that design fits. Measured volts
are not used and are not changed.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from energy_dashboard.common import *
from energy_dashboard.plant.mcs_certificate import load_record as load_mcs
from energy_dashboard.plant.panel_catalog import list_panels, panel_label
from energy_dashboard.plant.string_design import (
    Bounds,
    evaluate_string,
    load_design,
    save_design,
    scenario_state,
)

_LABEL_W = 168
_STATE_COLOR = {
    "inside": "#a6e3a1",
    "provisional": "#f9e2af",
    "outside": "#f38ba8",
    "unchecked": "#6c7086",
}


def _opt_spin(maximum: float, *, decimals: int = 0, width: int = 90) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(0.0, maximum)
    spin.setDecimals(decimals)
    spin.setSpecialValueText("—")
    apply_spin_field_motif(spin, width=width)
    return spin


class StringDesignTab(QWidget):
    """Compare string lengths with the panel datasheet and the inverter window."""

    def __init__(self, status_callback=None, dash=None):
        super().__init__()
        self.set_status = status_callback
        self.dash = dash
        self.on_data_updated = None
        self._rows: list[dict] = []
        self._loading = False
        self.build_ui()
        self.reload()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        intro = QLabel(
            "A design scenario is how many panels are in series on each string. "
            "The check uses that count and the panel datasheet. "
            "It does not read live volts and it does not multiply them. "
            "Inverter limits stay blank until you type them from the inverter datasheet."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        root.addWidget(intro)

        self.cmb_panel = QComboBox()
        apply_combo_field_motif(self.cmb_panel, width=280)
        self.cmb_panel.setToolTip("Module from Panel database. Vmp and Voc must be filled in.")
        self.cmb_panel.currentIndexChanged.connect(self._recalc)
        root.addLayout(self._pair("Panel", self.cmb_panel))

        self.lbl_spec = QLabel("")
        self.lbl_spec.setWordWrap(True)
        self.lbl_spec.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 12px;")
        root.addWidget(self.lbl_spec)

        self.spin_mppt_min = _opt_spin(1500)
        self.spin_mppt_min.setToolTip("Lowest voltage at which the MPPT will run, from the inverter datasheet.")
        self.spin_mppt_max = _opt_spin(1500)
        self.spin_mppt_max.setToolTip("Highest operating voltage of the MPPT, from the inverter datasheet.")
        self.spin_voc_max = _opt_spin(1500)
        self.spin_voc_max.setToolTip(
            "Absolute maximum PV voltage. Cold open-circuit voltage must stay under this."
        )
        for spin in (self.spin_mppt_min, self.spin_mppt_max, self.spin_voc_max):
            spin.valueChanged.connect(self._recalc)
        limits = QHBoxLayout()
        limits.setSpacing(12)
        limits.addWidget(self._field("MPPT lowest V", self.spin_mppt_min))
        limits.addWidget(self._field("MPPT highest V", self.spin_mppt_max))
        limits.addWidget(self._field("Maximum Voc", self.spin_voc_max))
        limits.addStretch(1)
        root.addLayout(limits)

        self.ed_voc_coeff = QLineEdit()
        self.ed_voc_coeff.setPlaceholderText("blank")
        apply_setup_info_line_field_motif(self.ed_voc_coeff, width=90)
        self.ed_voc_coeff.setToolTip(
            "Voc temperature coefficient from the panel datasheet, in percent per degree. "
            "It is a small negative number. Leave blank if the sheet does not give it."
        )
        self.chk_cold = QCheckBox("Cold morning")
        self.chk_cold.setToolTip("Check open-circuit voltage at a cell temperature you choose.")
        self.spin_cold = QSpinBox()
        self.spin_cold.setRange(-40, 40)
        self.spin_cold.setSuffix(" °C")
        apply_spin_field_motif(self.spin_cold, width=90)
        self.spin_cold.setToolTip("Cell temperature for the cold check, not the air temperature unless you mean that.")
        self.ed_vmp_coeff = QLineEdit()
        self.ed_vmp_coeff.setPlaceholderText("blank")
        apply_setup_info_line_field_motif(self.ed_vmp_coeff, width=90)
        self.ed_vmp_coeff.setToolTip(
            "Vmp temperature coefficient, percent per degree. Leave blank if you do not have it."
        )
        self.chk_hot = QCheckBox("Hot cells")
        self.spin_hot = QSpinBox()
        self.spin_hot.setRange(25, 85)
        self.spin_hot.setSuffix(" °C")
        apply_spin_field_motif(self.spin_hot, width=90)
        self.spin_hot.setToolTip("Cell temperature for the hot working-voltage check.")
        for widget in (self.ed_voc_coeff, self.chk_cold, self.spin_cold, self.ed_vmp_coeff, self.chk_hot, self.spin_hot):
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(self._recalc)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._recalc)
            else:
                widget.valueChanged.connect(self._recalc)
        temp = QHBoxLayout()
        temp.setSpacing(12)
        temp.addWidget(self._field("Voc coeff %/°C", self.ed_voc_coeff))
        temp.addWidget(self.chk_cold)
        temp.addWidget(self.spin_cold)
        temp.addSpacing(16)
        temp.addWidget(self._field("Vmp coeff %/°C", self.ed_vmp_coeff))
        temp.addWidget(self.chk_hot)
        temp.addWidget(self.spin_hot)
        temp.addStretch(1)
        root.addLayout(temp)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_add = QPushButton("Add scenario")
        self.btn_add.setFixedWidth(140)
        self.btn_add.setToolTip("Add another pair of string lengths.")
        self.btn_add.clicked.connect(self._add_scenario)
        self.btn_save = QPushButton("Save design")
        self.btn_save.setFixedWidth(130)
        self.btn_save.setToolTip("Keep these scenarios and the inverter limits.")
        self.btn_save.clicked.connect(self._save)
        for btn in (self.btn_add, self.btn_save):
            _apply_primary_button_style(btn)
            bar.addWidget(btn)
        bar.addStretch(1)
        root.addLayout(bar)

        self.scenario_host = QVBoxLayout()
        self.scenario_host.setSpacing(8)
        holder = QWidget()
        holder.setLayout(self.scenario_host)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll, 1)

    def _pair(self, title: str, field: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        lab = QLabel(title)
        lab.setFixedWidth(_LABEL_W)
        lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lab.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        row.addWidget(lab)
        row.addWidget(field, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        return row

    def _field(self, title: str, field: QWidget) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab = QLabel(title)
        lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lab.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        row.addWidget(lab)
        row.addWidget(field)
        return wrap

    def showEvent(self, event):
        super().showEvent(event)
        self._fill_panels(keep=self._panel_id())
        self._recalc()

    def hideEvent(self, event):
        self._save(quiet=True)
        super().hideEvent(event)

    def reload(self):
        record = load_design()
        self._loading = True
        self._fill_panels(keep=record.get("panel_id") or "")
        self._set_opt(self.spin_mppt_min, record.get("mppt_min"))
        self._set_opt(self.spin_mppt_max, record.get("mppt_max"))
        self._set_opt(self.spin_voc_max, record.get("voc_max"))
        self.ed_voc_coeff.setText(self._coeff_text(record.get("voc_coeff")))
        self.ed_vmp_coeff.setText(self._coeff_text(record.get("vmp_coeff")))
        cold = record.get("cold_c")
        self.chk_cold.setChecked(cold is not None)
        self.spin_cold.setValue(int(cold) if cold is not None else 0)
        hot = record.get("hot_c")
        self.chk_hot.setChecked(hot is not None)
        self.spin_hot.setValue(int(hot) if hot is not None else 25)
        self._build_rows(record.get("scenarios") or [])
        self._loading = False
        self._recalc()

    def _fill_panels(self, keep: str):
        self.cmb_panel.blockSignals(True)
        self.cmb_panel.clear()
        chosen = 0
        for panel in list_panels():
            if panel.get("vmp") is None or panel.get("voc") is None:
                continue
            self.cmb_panel.addItem(panel_label(panel), panel.get("id"))
            if str(panel.get("id") or "") == str(keep):
                chosen = self.cmb_panel.count() - 1
        self.cmb_panel.setCurrentIndex(chosen if self.cmb_panel.count() else -1)
        self.cmb_panel.blockSignals(False)

    def _build_rows(self, scenarios: list[dict]):
        while self.scenario_host.count():
            item = self.scenario_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = []
        for scenario in scenarios:
            self._append_row(scenario)
        if not self._rows:
            self._append_row({"name": "6 and 6", "n1": 6, "n2": 6})

    def _append_row(self, scenario: dict):
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #181825; border: 1px solid #313244; border-radius: 6px; }"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        name = QLineEdit(str(scenario.get("name") or ""))
        apply_setup_info_line_field_motif(name, width=140)
        name.setToolTip("Name for this arrangement.")
        n1 = QSpinBox()
        n2 = QSpinBox()
        for spin, count, tip in (
            (n1, scenario.get("n1") or 0, "Panels in series on string 1."),
            (n2, scenario.get("n2") or 0, "Panels in series on string 2. 0 means that string is unused."),
        ):
            spin.setRange(0, 40)
            spin.setSpecialValueText("—")
            spin.setValue(int(count or 0))
            spin.setToolTip(tip)
            apply_spin_field_motif(spin, width=70)
        remove = QPushButton("Remove")
        remove.setFixedWidth(90)
        _apply_primary_button_style(remove)
        remove.setToolTip("Remove this scenario.")
        top.addWidget(name)
        top.addWidget(QLabel("String 1"))
        top.addWidget(n1)
        top.addWidget(QLabel("String 2"))
        top.addWidget(n2)
        top.addWidget(remove)
        top.addStretch(1)
        result = QLabel("")
        result.setWordWrap(True)
        result.setStyleSheet("color: #cdd6f4; font-size: 12px; border: none; background: transparent;")
        lay.addLayout(top)
        lay.addWidget(result)
        self.scenario_host.addWidget(frame)
        row = {"frame": frame, "name": name, "n1": n1, "n2": n2, "result": result}
        self._rows.append(row)
        name.textChanged.connect(self._recalc)
        n1.valueChanged.connect(self._recalc)
        n2.valueChanged.connect(self._recalc)
        remove.clicked.connect(lambda _checked=False, item=row: self._remove_row(item))

    def _add_scenario(self):
        self._append_row({"name": "New arrangement", "n1": 6, "n2": 6})
        self._recalc()

    def _remove_row(self, row: dict):
        if row not in self._rows:
            return
        self._rows.remove(row)
        self.scenario_host.removeWidget(row["frame"])
        row["frame"].deleteLater()
        if not self._rows:
            self._append_row({"name": "6 and 6", "n1": 6, "n2": 6})
        self._recalc()

    def _panel(self) -> dict | None:
        pid = self._panel_id()
        for panel in list_panels():
            if str(panel.get("id") or "") == pid:
                return panel
        return None

    def _panel_id(self) -> str:
        data = self.cmb_panel.currentData()
        return "" if data is None else str(data)

    def _bounds(self) -> Bounds:
        return Bounds(
            self._spin_opt(self.spin_mppt_min),
            self._spin_opt(self.spin_mppt_max),
            self._spin_opt(self.spin_voc_max),
        )

    @staticmethod
    def _spin_opt(spin: QDoubleSpinBox):
        value = float(spin.value())
        if value <= 0:
            return None
        return value

    @staticmethod
    def _set_opt(spin: QDoubleSpinBox, value):
        spin.setValue(0.0 if value is None else float(value))

    @staticmethod
    def _coeff_text(value) -> str:
        if value is None:
            return ""
        return f"{float(value):.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _parse_coeff(text: str):
        raw = (text or "").strip().replace("−", "-")
        if not raw or raw in ("—", "-", ".", "-."):
            return None
        try:
            value = float(raw)
        except ValueError:
            return None
        if value != value or value == 0:
            return None
        return value

    def _recalc(self, *_args):
        if self._loading:
            return
        panel = self._panel()
        mcs = load_mcs()
        mcs_n = mcs.get("panels")
        if panel is None:
            self.lbl_spec.setText(
                "Panel database has no module with both Vmp and Voc. "
                "Fill those in before a scenario can be checked."
            )
        else:
            wp = panel.get("wp")
            imp = panel.get("imp")
            spec = (
                f"{panel_label(panel)}: Vmp {panel['vmp']:.1f} V, "
                f"Voc {panel['voc']:.1f} V"
            )
            if wp:
                spec += f", {float(wp):.0f} W"
            if imp:
                spec += f", Imp {float(imp):.2f} A"
            spec += ". Panels in series add the voltages. The current stays Imp."
            if mcs_n:
                spec += f" The MCS certificate records {int(mcs_n)} panels."
            self.lbl_spec.setText(spec)
        bounds = self._bounds()
        voc_coeff = self._parse_coeff(self.ed_voc_coeff.text())
        vmp_coeff = self._parse_coeff(self.ed_vmp_coeff.text())
        cold_c = float(self.spin_cold.value()) if self.chk_cold.isChecked() else None
        hot_c = float(self.spin_hot.value()) if self.chk_hot.isChecked() else None
        vmp = None if panel is None else panel.get("vmp")
        voc = None if panel is None else panel.get("voc")
        for row in self._rows:
            n1 = int(row["n1"].value())
            n2 = int(row["n2"].value())
            left = evaluate_string(
                n1, vmp=vmp, voc=voc, bounds=bounds,
                voc_coeff=voc_coeff, cold_c=cold_c,
                vmp_coeff=vmp_coeff, hot_c=hot_c,
            ) if n1 else None
            right = evaluate_string(
                n2, vmp=vmp, voc=voc, bounds=bounds,
                voc_coeff=voc_coeff, cold_c=cold_c,
                vmp_coeff=vmp_coeff, hot_c=hot_c,
            ) if n2 else None
            parts = []
            if left is not None:
                parts.append("String 1: " + left.detail)
            if right is not None:
                parts.append("String 2: " + right.detail)
            total = n1 + n2
            if total:
                parts.append(f"Together that is {total} panels.")
                if mcs_n and int(mcs_n) != total:
                    parts.append(f"The certificate records {int(mcs_n)}.")
            state = "unchecked"
            if left is not None and right is not None:
                state = scenario_state(left, right)
            elif left is not None:
                state = left.state
            elif right is not None:
                state = right.state
            color = _STATE_COLOR.get(state, _STATE_COLOR["unchecked"])
            row["result"].setText(" ".join(parts) if parts else "Set a string length.")
            row["result"].setStyleSheet(
                f"color: {color}; font-size: 12px; border: none; background: transparent;"
            )
            row["frame"].setStyleSheet(
                "QFrame { background: #181825; border: 1px solid #313244; "
                f"border-left: 3px solid {color}; border-radius: 6px; }}"
            )

    def _collect(self) -> dict:
        return {
            "panel_id": self._panel_id(),
            "mppt_min": self._spin_opt(self.spin_mppt_min),
            "mppt_max": self._spin_opt(self.spin_mppt_max),
            "voc_max": self._spin_opt(self.spin_voc_max),
            "voc_coeff": self._parse_coeff(self.ed_voc_coeff.text()),
            "cold_c": float(self.spin_cold.value()) if self.chk_cold.isChecked() else None,
            "vmp_coeff": self._parse_coeff(self.ed_vmp_coeff.text()),
            "hot_c": float(self.spin_hot.value()) if self.chk_hot.isChecked() else None,
            "scenarios": [
                {
                    "name": row["name"].text().strip(),
                    "n1": int(row["n1"].value()),
                    "n2": int(row["n2"].value()),
                }
                for row in self._rows
            ],
        }

    def _save(self, quiet: bool = False):
        if self._loading:
            return
        save_design(self._collect())
        if not quiet and self.set_status:
            self.set_status("String design saved.")
        if not quiet and self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception:
                pass


__all__ = ["StringDesignTab"]
