"""
Energy Dashboard — Alarm defs tab (Controls group).

Describes the alarms. What is sounding right now is the Alarms page in
Dashboards (`tabs/alarms.py`).

An alarm is one line of small blocks: signal, comparison, threshold, how
long, an optional extra condition, and the outcome. The palette above is a
short scrolling list per kind — drag a row from a list into the matching
slot. A line that matches a built-in alarm is live; anything else is a
draft and does not fire.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from PySide6.QtCore import QMimeData, QSize
from PySide6.QtGui import QColor, QDrag, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QGraphicsDropShadowEffect,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
)

from energy_dashboard.common import *
from energy_dashboard.core.alarms import (
    ALARM_BLOCKS,
    ALARM_PIECE_KINDS,
    ALARM_PIECE_REQUIRED,
    alarm_blocks_key,
    alarm_palette,
    alarm_piece_accepted,
    alarm_rule_syntax,
)

_MIME = "application/x-powermon-alarm-piece"
_MIME_SLOT = "application/x-powermon-alarm-slot"
_MIME_RULE = "application/x-powermon-alarm-rule"
_QS_RULES = "alarms/defs_blocks"
_ROW_H = 28
_QS_SPLIT = "alarms/defs_split"

# One colour per kind of block, so a line reads as a sentence of parts.
_KIND_COLOR = {
    "signal": "#89b4fa",
    "comparison": "#94e2d5",
    "threshold": "#f9e2af",
    "duration": "#cba6f7",
    "context": "#fab387",
    "outcome": "#f38ba8",
}
_KIND_LABEL = {
    "signal": "Signal",
    "comparison": "Comparison",
    "threshold": "Threshold",
    "duration": "For how long",
    "context": "While (optional)",
    "outcome": "Outcome",
}
_KIND_SHORT = dict(_KIND_LABEL, duration="How long", context="While")
# Little words between the slots, so the line still reads as a sentence.
_BEFORE = {
    "signal": "when",
    "duration": "for",
    "context": "while",
    "outcome": "then",
}
# Reads properly in "Still needs a signal and an outcome."
_KIND_NOUN = dict(
    signal="a signal",
    comparison="a comparison",
    threshold="a threshold",
    duration="a length of time",
    context="an extra condition",
    outcome="an outcome",
)


def _needs_text(missing: list[str]) -> str:
    nouns = [_KIND_NOUN[k] for k in missing]
    if len(nouns) == 1:
        joined = nouns[0]
    else:
        joined = ", ".join(nouns[:-1]) + " and " + nouns[-1]
    return f"Still needs {joined}."


def _decode_piece(mime: QMimeData) -> tuple[str, str]:
    if mime is None or not mime.hasFormat(_MIME):
        return "", ""
    try:
        raw = bytes(mime.data(_MIME)).decode("utf-8")
    except Exception:
        return "", ""
    kind, _, text = raw.partition("\n")
    return kind.strip(), text.strip()


def _decode_token(mime: QMimeData, fmt: str) -> str:
    if mime is None or not mime.hasFormat(fmt):
        return ""
    try:
        return bytes(mime.data(fmt)).decode("utf-8").strip()
    except Exception:
        return ""


def _decode_slot(mime: QMimeData) -> tuple[str, str]:
    raw = _decode_token(mime, _MIME_SLOT)
    if not raw:
        return "", ""
    token, _, kind = raw.partition("\n")
    return token.strip(), kind.strip()


def _event_pos(event):
    pos = getattr(event, "position", None)
    if callable(pos):
        return pos().toPoint()
    return event.pos()


@dataclass(frozen=True)
class _Param:
    """A block whose number is a real alarm setting, not just words."""

    piece: str
    title: str
    hint: str
    key: str
    minimum: float
    maximum: float
    decimals: int
    default: float
    suffix: str
    scale: float
    monitor: str
    keep_words: bool = False

    def spin_value(self, stored: float) -> float:
        return float(stored) / self.scale

    def stored_value(self, spin: float) -> float:
        return float(spin) * self.scale

    def format_stored(self, stored: float) -> str:
        if self.suffix.strip() == "%":
            return f"{int(round(stored))}%"
        if self.suffix.strip() == "kW":
            return f"{float(stored):.1f} kW"
        if self.suffix.strip() == "V":
            return f"{int(round(float(stored)))} V"
        if self.scale != 1.0:
            n = int(round(float(stored) / self.scale))
            return "1 minute" if n == 1 else f"{n} minutes"
        n = int(round(float(stored)))
        if self.suffix.strip() == "min":
            return "1 minute" if n == 1 else f"{n} minutes"
        if n >= 60 and n % 60 == 0:
            minutes = n // 60
            return "1 minute" if minutes == 1 else f"{minutes} minutes"
        return "1 second" if n == 1 else f"{n} seconds"

    def chip(self, stored: float) -> str:
        pretty = self.format_stored(stored)
        if self.keep_words:
            return f"{self.piece} ({pretty})"
        if abs(float(stored) - self.default) < 0.05:
            return self.piece
        if self.monitor == "db_ingest_hold_s":
            return f"15 minutes, then {pretty}"
        return pretty


_PARAMS = (
    _Param(
        "the hold time",
        "Hold time",
        "How long a low battery, spare solar, or a house load that uses "
        "almost all the solar must stay that way before the alarm fires. "
        "This is the same figure as Setup → Live alarms.",
        "alarms/hold_minutes",
        1, 180, 0, 10.0, " min", 1.0, "hold_minutes",
        keep_words=True,
    ),
    _Param(
        "the low-battery line",
        "Low-battery line",
        "State of charge at or below this counts as a low battery. "
        "This is the same figure as Setup → Low SOC threshold.",
        "params/battery_low_soc_threshold_pct",
        0, 50, 0, 10.0, " %", 1.0, "low_soc",
        keep_words=True,
    ),
    _Param(
        "the spare-solar minimum",
        "Spare-solar minimum",
        "How much spare solar — panels minus what the house is using — "
        "counts as wasted when the battery is low and barely charging.",
        "alarms/pv_min_kw",
        0.2, 20, 1, 1.0, " kW", 1.0, "pv_min_kw",
        keep_words=True,
    ),
    _Param(
        "Volts",
        "Volts",
        "How many volts this block stands for. With “has a differential of”, "
        "that is the gap between the two string voltages.",
        "alarms/diff_volts",
        1, 600, 0, 20.0, " V", 1.0, "volts",
        keep_words=True,
    ),
    _Param(
        "about 20 seconds",
        "Grott feed lost",
        "How long Grott can be missing before that alarm fires. If MQTT "
        "is up but no frame has arrived yet, the Grott fresh window still applies.",
        "alarms/grott_lost_hold_s",
        5, 600, 0, 20.0, " s", 1.0, "grott_lost_hold_s",
    ),
    _Param(
        "about 60 seconds",
        "Database unreachable",
        "How long the logging database must be unreachable before that alarm fires.",
        "alarms/db_disconnect_hold_s",
        10, 600, 0, 60.0, " s", 1.0, "db_disconnect_hold_s",
    ),
    _Param(
        "15 minutes",
        "No new rows",
        "The logger counts rows over the last 15 minutes. This is how long "
        "that count must stay at zero before the alarm fires.",
        "alarms/db_ingest_hold_s",
        30, 1800, 0, 90.0, " s", 1.0, "db_ingest_hold_s",
    ),
    _Param(
        "about 2 minutes",
        "Inverter offline",
        "How long Growatt must keep reporting the inverter offline before that alarm fires.",
        "alarms/inverter_lost_hold_s",
        60, 1800, 0, 120.0, " min", 60.0, "inverter_lost_hold_s",
    ),
    _Param(
        "about 30 seconds",
        "Tasmota MQTT lost",
        "How long the Tasmota MQTT connection must be down before that alarm fires.",
        "alarms/tasmota_mqtt_hold_s",
        5, 600, 0, 30.0, " s", 1.0, "tasmota_mqtt_hold_s",
    ),
    _Param(
        "about 8 minutes",
        "Tasmota device silent",
        "How long a named plug or current clamp must be quiet before it counts as silent.",
        "alarms/tasmota_stale_s",
        60, 3600, 0, 480.0, " min", 60.0, "tasmota_stale_s",
    ),
)
_PARAM_FOR = {row.piece: row for row in _PARAMS}


def _alarm_settings() -> QSettings:
    return QSettings("PowerModel", "EnergyDashboard2")


def _read_param(spec: _Param) -> float:
    raw = _alarm_settings().value(spec.key, spec.default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = float(spec.default)
    return min(spec.maximum, max(spec.minimum, value))


def _write_param(spec: _Param, spin_value: float, dash) -> None:
    stored = min(spec.maximum, max(spec.minimum, spec.stored_value(spin_value)))
    settings = _alarm_settings()
    if spec.monitor == "low_soc":
        pct = int(round(stored))
        settings.setValue(spec.key, pct)
        settings.sync()
        if dash is None:
            return
        try:
            dash.app_params.battery_low_soc_threshold_pct = float(pct)
        except Exception:
            pass
        params = getattr(dash, "parameters_tab", None)
        if params is not None:
            try:
                params.p.battery_low_soc_threshold_pct = float(pct)
            except Exception:
                pass
            soc = getattr(params, "sp_soc_thr", None)
            if soc is not None:
                soc.blockSignals(True)
                soc.setValue(pct)
                soc.blockSignals(False)
        battery = getattr(dash, "battery_tab", None)
        if battery is not None:
            spin = getattr(battery, "threshold_spin", None)
            if spin is not None:
                spin.blockSignals(True)
                spin.setValue(pct)
                spin.blockSignals(False)
            if hasattr(battery, "soc_threshold"):
                battery.soc_threshold = pct
        return
    settings.setValue(spec.key, stored)
    settings.sync()
    if spec.monitor == "volts" or dash is None:
        return
    monitor = getattr(dash, "alarm_monitor", None)
    if monitor is not None:
        monitor.configure(**{spec.monitor: stored})
    params = getattr(dash, "parameters_tab", None)
    if params is None:
        return
    if spec.monitor == "hold_minutes":
        params.sp_alarm_hold.blockSignals(True)
        params.sp_alarm_hold.setValue(float(stored))
        params.sp_alarm_hold.blockSignals(False)
    elif spec.monitor == "pv_min_kw":
        params.sp_alarm_pv_min.blockSignals(True)
        params.sp_alarm_pv_min.setValue(float(stored))
        params.sp_alarm_pv_min.blockSignals(False)


def _edit_param(parent, spec: _Param, dash) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle(spec.title)
    dlg.setMinimumWidth(420)
    lay = QVBoxLayout(dlg)
    hint = QLabel(spec.hint)
    hint.setWordWrap(True)
    hint.setStyleSheet("color: #cdd6f4; font-size: 12px;")
    lay.addWidget(hint)
    if spec.decimals:
        spin = QDoubleSpinBox()
        spin.setDecimals(spec.decimals)
    else:
        spin = QSpinBox()
    lo = spec.minimum / spec.scale
    hi = spec.maximum / spec.scale
    if spec.decimals:
        spin.setRange(lo, hi)
    else:
        spin.setRange(int(round(lo)), int(round(hi)))
    spin.setSuffix(spec.suffix)
    current = spec.spin_value(_read_param(spec))
    spin.setValue(current if spec.decimals else int(round(current)))
    apply_spin_field_motif(spin, width=120)
    row = QHBoxLayout()
    row.addWidget(spin)
    row.addStretch(1)
    lay.addLayout(row)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
    if ok is not None:
        ok.setText("Save")
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)
    _prepare_dialog_buttons(dlg)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False
    _write_param(spec, float(spin.value()), dash)
    return True


class _PaletteDelegate(QStyledItemDelegate):
    """Paints each palette row itself. A list stylesheet was hiding the colour."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._fill = QColor(_KIND_COLOR[kind])
        self._ink = QColor("#1e1e2e")

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect.adjusted(2, 1, -2, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._fill)
        painter.drawRoundedRect(rect, 3, 3)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        shown = option.fontMetrics.elidedText(
            text, Qt.TextElideMode.ElideRight, max(24, rect.width() - 12),
        )
        painter.setPen(self._ink)
        painter.drawText(
            rect.adjusted(6, 0, -4, 0),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            shown,
        )
        painter.restore()

    def sizeHint(self, _option, _index):
        return QSize(80, 20)


class _PaletteList(QListWidget):
    """One kind of block, as a short scrolling list. Drag uses Qt's own drag."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setItemDelegate(_PaletteDelegate(kind, self))
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSpacing(1)
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setToolTip(
            f"Drag a {_KIND_SHORT[kind].lower()} into a slot of the same colour"
        )
        for text in alarm_palette(kind):
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, text)
            item.setToolTip(text)
            self.addItem(item)
        # No QListWidget::item rule. That replaces the delegate and the
        # rows vanish on this desktop.
        self.setStyleSheet(
            "QListWidget {"
            "  background: #181825;"
            "  border: 1px solid #313244;"
            "  border-radius: 4px;"
            "  outline: none;"
            "  font-size: 11px;"
            "}"
        )

    def mimeTypes(self):
        return [_MIME]

    def mimeData(self, items):
        mime = QMimeData()
        if items:
            text = items[0].data(Qt.ItemDataRole.UserRole) or items[0].text()
            mime.setData(_MIME, f"{self.kind}\n{text}".encode("utf-8"))
        return mime

    def startDrag(self, _supported):
        item = self.currentItem()
        text = item.data(Qt.ItemDataRole.UserRole) if item is not None else ""
        if not text:
            return
        mime = QMimeData()
        mime.setData(_MIME, f"{self.kind}\n{text}".encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        # Without a pixmap the drag is invisible, so it looks like nothing moved.
        chip = QLabel(str(text))
        chip.setStyleSheet(
            "QLabel {"
            f"  background: {_KIND_COLOR[self.kind]};"
            "  color: #1e1e2e; border-radius: 3px; padding: 2px 8px; font-size: 11px;"
            "}"
        )
        chip.adjustSize()
        drag.setPixmap(chip.grab())
        drag.setHotSpot(chip.rect().center())
        drag.exec(Qt.DropAction.CopyAction)


class _Slot(QFrame):
    """One drop target on a rule line. Drag it to the bin, or click a number."""

    changed = Signal()

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._text = ""
        self._armed = False
        self.setAcceptDrops(True)
        self.setFixedHeight(_ROW_H)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        self._body = QLabel("")
        self._body.setWordWrap(False)
        self._body.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        # The label was the widget under the cursor, so the drop never reached
        # this frame. Mouse events (including the drop) now hit the frame.
        self._body.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self._body)
        self.set_piece("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._paint_caption()

    def text(self) -> str:
        return self._text

    def caption(self) -> str:
        if not self._text:
            return ""
        spec = _PARAM_FOR.get(self._text)
        if spec is None:
            return self._text
        return spec.chip(_read_param(spec))

    def set_piece(self, text: str) -> None:
        self._text = (text or "").strip()
        colour = _KIND_COLOR[self.kind]
        if self._text:
            self._body.setStyleSheet(
                "color: #1e1e2e; font-size: 11px; background: transparent;"
            )
            self.setStyleSheet(
                f"_Slot {{ background: {colour}; border-radius: 3px; }}"
            )
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self._paint_caption()
            lines = [self.caption()]
            if self._text in _PARAM_FOR:
                lines.append("Click to change this.")
            lines.append("Drag onto the bin to remove it.")
            lines.append("Right-click to empty this slot.")
            self.setToolTip("\n".join(lines))
        else:
            optional = self.kind not in ALARM_PIECE_REQUIRED
            self._body.setText("—" if optional else _KIND_SHORT[self.kind].lower())
            self._body.setStyleSheet(
                "color: #6c7086; font-size: 11px; background: transparent;"
            )
            self.setStyleSheet(
                "_Slot {"
                "  background: transparent;"
                f"  border: 1px dashed {colour};"
                "  border-radius: 3px;"
                "}"
            )
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setToolTip(
                f"Drop a {_KIND_SHORT[self.kind].lower()} here."
                + (" Optional." if optional else "")
            )

    def _paint_caption(self) -> None:
        if not self._text:
            return
        shown = QFontMetrics(self._body.font()).elidedText(
            self.caption(), Qt.TextElideMode.ElideRight, max(24, self._body.width()),
        )
        if shown != self._body.text():
            self._body.setText(shown)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self._text:
            self.set_piece("")
            self.changed.emit()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._text:
            self._armed = True
            self._press = _event_pos(event)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._armed or not self._text:
            super().mouseMoveEvent(event)
            return
        if (_event_pos(event) - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._armed = False
        rule = self._rule()
        if rule is None:
            return
        mime = QMimeData()
        mime.setData(_MIME_SLOT, f"{rule.token}\n{self.kind}".encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        chip = QLabel(self.caption())
        chip.setStyleSheet(
            "QLabel {"
            f"  background: {_KIND_COLOR[self.kind]};"
            "  color: #1e1e2e; border-radius: 3px; padding: 2px 8px; font-size: 11px;"
            "}"
        )
        chip.adjustSize()
        drag.setPixmap(chip.grab())
        drag.setHotSpot(chip.rect().center())
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event):
        if self._armed and event.button() == Qt.MouseButton.LeftButton and self._text:
            self._armed = False
            spec = _PARAM_FOR.get(self._text)
            tab = self._tab()
            if spec is not None and tab is not None and _edit_param(tab, spec, tab.dash):
                tab.refresh_param_chips()
            return
        self._armed = False
        super().mouseReleaseEvent(event)

    def _rule(self):
        widget = self.parent()
        while widget is not None and not isinstance(widget, _RuleLine):
            widget = widget.parent()
        return widget

    def _tab(self):
        widget = self.parent()
        while widget is not None and not isinstance(widget, AlarmDefsTab):
            widget = widget.parent()
        return widget

    def dragEnterEvent(self, event):
        kind, text = _decode_piece(event.mimeData())
        if text and alarm_piece_accepted(self.kind, kind):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        kind, text = _decode_piece(event.mimeData())
        if not text or not alarm_piece_accepted(self.kind, kind):
            event.ignore()
            return
        self.set_piece(text)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.changed.emit()


class _RuleHandle(QWidget):
    """Three bars. Drag to reorder, or drop on the bin to remove the rule."""

    def __init__(self, rule: "_RuleLine"):
        super().__init__(rule)
        self._rule = rule
        self._armed = False
        self.setFixedSize(16, _ROW_H)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to change the order.\nDrag into the bin to remove this rule.")

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#a6adc8"))
        top = (self.height() - 10) // 2
        for index in range(3):
            painter.drawRoundedRect(3, top + index * 4, 10, 2, 1, 1)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._armed = True
            self._press = _event_pos(event)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._armed:
            return
        if (_event_pos(event) - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._armed = False
        mime = QMimeData()
        mime.setData(_MIME_RULE, self._rule.token.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        chip = QLabel(f"Rule {self._rule._number.text()}")
        chip.setStyleSheet(
            "QLabel { background: #313244; color: #f5a524; border-radius: 3px; "
            "padding: 2px 8px; font-size: 11px; font-weight: bold; }"
        )
        chip.adjustSize()
        drag.setPixmap(chip.grab())
        drag.setHotSpot(chip.rect().center())
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event):
        self._armed = False
        super().mouseReleaseEvent(event)


class _Bin(QWidget):
    """Drop a block here to clear it, or a rule handle to remove the rule."""

    def __init__(self, tab: "AlarmDefsTab"):
        super().__init__()
        self._tab = tab
        self._hot = False
        self.setFixedSize(40, 40)
        self.setAcceptDrops(True)
        self.setToolTip(
            "Drop a block here to take it off its rule.\n"
            "Drop a rule’s handle here to remove the whole rule."
        )

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        ink = QColor("#f38ba8" if self._hot else "#a6adc8")
        if self._hot:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(243, 139, 168, 48))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)
        painter.setPen(QPen(ink, 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(10, 13, 30, 13)
        painter.drawLine(16, 13, 16, 10)
        painter.drawLine(24, 13, 24, 10)
        painter.drawLine(16, 10, 24, 10)
        painter.drawRoundedRect(12, 15, 16, 15, 2, 2)
        painter.drawLine(17, 18, 17, 26)
        painter.drawLine(20, 18, 20, 26)
        painter.drawLine(23, 18, 23, 26)
        painter.end()

    def dragEnterEvent(self, event):
        if _decode_slot(event.mimeData())[0] or _decode_token(event.mimeData(), _MIME_RULE):
            self._hot = True
            self.update()
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self._hot = False
        self.update()
        event.accept()

    def dropEvent(self, event):
        self._hot = False
        self.update()
        token, kind = _decode_slot(event.mimeData())
        if token and kind:
            self._tab.clear_slot(token, kind)
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        rule = _decode_token(event.mimeData(), _MIME_RULE)
        if rule:
            self._tab.remove_rule_token(rule)
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        event.ignore()


class _RuleLine(QFrame):
    """One numbered alarm: a line of slots, and a halo when the sentence is whole."""

    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.token = f"r{id(self)}"
        self._complete = False
        self._reorder_edge = ""
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setFixedHeight(_ROW_H + 22)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 3, 4, 2)
        outer.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(_RuleHandle(self))
        self._number = QLabel("1")
        self._number.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._number.setFixedWidth(18)
        self._number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._number.setStyleSheet(
            "color: #f5a524; font-size: 12px; font-weight: bold; background: transparent;"
        )
        row.addWidget(self._number)
        self.slots: dict[str, _Slot] = {}
        for kind in ALARM_PIECE_KINDS:
            word = _BEFORE.get(kind)
            if word:
                lab = QLabel(word)
                lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                lab.setStyleSheet("color: #6c7086; font-size: 10px; background: transparent;")
                lab.setFixedWidth(34 if kind != "signal" else 36)
                row.addWidget(lab)
            slot = _Slot(kind)
            slot.changed.connect(self._on_changed)
            self.slots[kind] = slot
            row.addWidget(slot, 3 if kind in ("signal", "context", "outcome") else 2)
        outer.addLayout(row)
        note_row = QHBoxLayout()
        note_row.setContentsMargins(20, 0, 4, 0)
        note_row.addStretch(1)
        self._syntax_note = QLabel("Syntax Correct")
        self._syntax_note.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._syntax_note.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._syntax_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._syntax_note.setStyleSheet(
            "QLabel {"
            "  color: #1e1e2e;"
            "  background-color: #a6e3a1;"
            "  font-size: 10px;"
            "  font-weight: bold;"
            "  padding: 1px 8px;"
            "  border-radius: 3px;"
            "}"
        )
        note_row.addWidget(self._syntax_note)
        outer.addLayout(note_row)
        self._refresh()

    def set_number(self, number: int) -> None:
        self._number.setText(str(number))

    def refresh_chips(self) -> None:
        for slot in self.slots.values():
            slot.set_piece(slot.text())
        self._refresh()

    def dragEnterEvent(self, event):
        token = _decode_token(event.mimeData(), _MIME_RULE)
        if not token or token == self.token:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        self._mark_edge(_event_pos(event).y())

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self._reorder_edge = ""
        self._chrome()
        event.accept()

    def dropEvent(self, event):
        token = _decode_token(event.mimeData(), _MIME_RULE)
        after = self._reorder_edge == "after"
        self._reorder_edge = ""
        self._chrome()
        tab = self._tab()
        if not token or tab is None:
            event.ignore()
            return
        tab.reorder_rule(token, self.token, after=after)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()

    def _mark_edge(self, y: int) -> None:
        edge = "after" if y >= self.height() / 2 else "before"
        if edge == self._reorder_edge:
            return
        self._reorder_edge = edge
        self._chrome()

    def _tab(self):
        widget = self.parent()
        while widget is not None and not isinstance(widget, AlarmDefsTab):
            widget = widget.parent()
        return widget

    def _chrome(self) -> None:
        if self._complete:
            border = "1px solid #a6e3a1"
            background = "#1c3324"
        else:
            border = "1px solid transparent"
            background = "transparent"
        edge = ""
        if self._reorder_edge == "before":
            edge = "border-top: 2px solid #f5a524;"
        elif self._reorder_edge == "after":
            edge = "border-bottom: 2px solid #f5a524;"
        self.setStyleSheet(
            "_RuleLine {"
            f"  border: {border};"
            "  border-radius: 5px;"
            f"  background-color: {background};"
            f"  {edge}"
            "}"
        )

    def values(self) -> dict[str, str]:
        return {kind: slot.text() for kind, slot in self.slots.items()}

    def set_values(self, pieces: dict[str, str]) -> None:
        for kind, slot in self.slots.items():
            slot.set_piece(str((pieces or {}).get(kind) or ""))
        self._refresh()

    def _on_changed(self) -> None:
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        pieces = self.values()
        sentence = alarm_rule_syntax(
            {kind: slot.caption() for kind, slot in self.slots.items()}
        )
        if not sentence:
            self._set_halo(False)
            self.setToolTip(_needs_text(
                [k for k in ALARM_PIECE_REQUIRED if not pieces.get(k)]
            ))
            return
        self._set_halo(True)
        if alarm_blocks_key(pieces):
            self.setToolTip(sentence)
        else:
            self.setToolTip(
                sentence + "\nThe sentence is complete, but it is not one of the "
                "built-in alarms, so it does not fire."
            )

    def _set_halo(self, on: bool) -> None:
        self._complete = on
        self._syntax_note.setVisible(on)
        if on:
            glow = QGraphicsDropShadowEffect(self)
            glow.setBlurRadius(16)
            glow.setOffset(0, 0)
            glow.setColor(QColor(166, 227, 161, 170))
            self.setGraphicsEffect(glow)
        else:
            self.setGraphicsEffect(None)
        self._chrome()


class AlarmDefsTab(QWidget):
    """Controls page: drag blocks from short lists onto one line per rule."""

    def __init__(self, dash=None):
        super().__init__()
        self.dash = dash
        self._cards: list[_RuleLine] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        head = QHBoxLayout()
        title = QLabel("Alarm defs")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #cdd6f4;")
        head.addWidget(title)
        hint = QLabel(
            "Click a time or a limit to change it. Drag a block to the bin to "
            "remove it. The handle on the left reorders a rule, or drops the whole rule in the bin."
        )
        hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        head.addWidget(hint, 1)
        live_btn = QPushButton("Alarms page")
        live_btn.setFixedWidth(110)
        live_btn.setToolTip("Open the Alarms page in Dashboards to see what is sounding.")
        live_btn.clicked.connect(self._show_live)
        head.addWidget(live_btn)
        add_btn = QPushButton("Add rule")
        add_btn.setFixedWidth(90)
        add_btn.setToolTip("Add an empty line")
        add_btn.clicked.connect(lambda: self._add_card({}))
        head.addWidget(add_btn)
        reset_btn = QPushButton("Reset")
        reset_btn.setFixedWidth(80)
        reset_btn.setToolTip("Put the built-in rules back")
        reset_btn.clicked.connect(self._reset)
        head.addWidget(reset_btn)
        layout.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rules_host = QWidget()
        self._rules = QVBoxLayout(self._rules_host)
        # Room around each line so the green halo is not clipped.
        self._rules.setContentsMargins(8, 6, 8, 6)
        self._rules.setSpacing(10)
        scroll.setWidget(self._rules_host)
        rules_pane = QWidget()
        rules_lay = QVBoxLayout(rules_pane)
        rules_lay.setContentsMargins(0, 0, 0, 0)
        rules_lay.setSpacing(4)
        rules_lay.addWidget(scroll, 1)
        bin_row = QHBoxLayout()
        bin_row.setContentsMargins(0, 0, 4, 0)
        bin_row.addStretch(1)
        self._bin = _Bin(self)
        bin_row.addWidget(self._bin)
        rules_lay.addLayout(bin_row)

        pieces_host = QWidget()
        pieces = QHBoxLayout(pieces_host)
        pieces.setContentsMargins(0, 0, 0, 0)
        pieces.setSpacing(6)
        for kind in ALARM_PIECE_KINDS:
            pieces.addWidget(self._piece_column(kind), 1)
        pieces_host.setMinimumHeight(100)
        rules_pane.setMinimumHeight(140)

        self._split = QSplitter(Qt.Orientation.Vertical)
        self._split.setChildrenCollapsible(False)
        self._split.setHandleWidth(8)
        self._split.setStyleSheet(
            "QSplitter::handle { background: #45475a; }"
            "QSplitter::handle:hover { background: #89b4fa; }"
            "QSplitter::handle:vertical { height: 8px; }"
        )
        self._split.addWidget(pieces_host)
        self._split.addWidget(rules_pane)
        self._split.setStretchFactor(0, 1)
        self._split.setStretchFactor(1, 0)
        self._split.splitterMoved.connect(self._save_split)
        self._split_ready = False
        layout.addWidget(self._split, 1)
        self._load()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_param_chips()
        if not self._split_ready:
            self._split_ready = True
            QTimer.singleShot(0, self._restore_split)

    def _preferred_rules_height(self) -> int:
        count = max(1, len(self._cards))
        cards = count * (_ROW_H + 22) + max(0, count - 1) * 10 + 20
        return cards + 48

    def _restore_split(self) -> None:
        raw = QSettings("PowerModel", "EnergyDashboard2").value(_QS_SPLIT)
        sizes = []
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            try:
                sizes = [int(x) for x in raw]
            except (TypeError, ValueError):
                sizes = []
        if len(sizes) == 2 and all(n > 40 for n in sizes):
            self._split.setSizes(sizes)
            return
        total = max(self._split.height(), self.height() - 48, 480)
        rules_h = min(self._preferred_rules_height(), int(total * 0.62))
        rules_h = max(rules_h, 160)
        self._split.setSizes([max(120, total - rules_h), rules_h])

    def _save_split(self, *_args) -> None:
        if not self._split_ready:
            return
        QSettings("PowerModel", "EnergyDashboard2").setValue(
            _QS_SPLIT, self._split.sizes(),
        )

    def refresh_param_chips(self) -> None:
        for card in self._cards:
            card.refresh_chips()

    def _card(self, token: str) -> _RuleLine | None:
        for card in self._cards:
            if card.token == token:
                return card
        return None

    def clear_slot(self, token: str, kind: str) -> None:
        card = self._card(token)
        if card is None:
            return
        slot = card.slots.get(kind)
        if slot is None or not slot.text():
            return
        slot.set_piece("")
        card._on_changed()

    def remove_rule_token(self, token: str) -> None:
        card = self._card(token)
        if card is not None:
            self._remove_card(card)

    def reorder_rule(self, src_token: str, dst_token: str, *, after: bool) -> None:
        src = self._card(src_token)
        dst = self._card(dst_token)
        if src is None or dst is None or src is dst:
            return
        self._cards.remove(src)
        index = self._cards.index(dst)
        if after:
            index += 1
        self._cards.insert(index, src)
        for card in self._cards:
            self._rules.removeWidget(card)
        for card in self._cards:
            self._rules.addWidget(card)
        self._renumber()
        self._save()

    def _piece_column(self, kind: str) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        label = QLabel(_KIND_SHORT[kind])
        label.setStyleSheet(
            f"color: {_KIND_COLOR[kind]}; font-size: 11px; font-weight: bold;"
        )
        col.addWidget(label)
        col.addWidget(_PaletteList(kind), 1)
        return box

    def _show_live(self) -> None:
        dash = self.dash
        page = getattr(dash, "alarms_tab", None)
        if dash is not None and page is not None:
            dash.show_main_page(page)

    def _add_card(self, pieces: dict[str, str], *, save: bool = True) -> None:
        card = _RuleLine()
        card.set_values(pieces)
        card.changed.connect(self._save)
        card.remove_requested.connect(self._remove_card)
        self._cards.append(card)
        self._rules.addWidget(card)
        self._renumber()
        if save:
            self._save()

    def _remove_card(self, card: _RuleLine) -> None:
        if card not in self._cards:
            return
        self._cards.remove(card)
        self._rules.removeWidget(card)
        card.deleteLater()
        self._renumber()
        self._save()

    def _renumber(self) -> None:
        for index, card in enumerate(self._cards, start=1):
            card.set_number(index)

    def _builtin_rows(self) -> list[dict[str, str]]:
        return [row.pieces() for row in ALARM_BLOCKS]

    def _load(self) -> None:
        # Rows saved before the sentence was split into blocks cannot be read.
        QSettings("PowerModel", "EnergyDashboard2").remove("alarms/defs_syntax")
        rows = self._read_saved() or self._builtin_rows()
        for pieces in rows:
            self._add_card(pieces, save=False)

    def _read_saved(self) -> list[dict[str, str]]:
        raw = QSettings("PowerModel", "EnergyDashboard2").value(_QS_RULES, "")
        if not raw:
            return []
        try:
            data = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []
        rows = []
        for item in data:
            if not isinstance(item, dict):
                continue
            rows.append({
                kind: str(item.get(kind) or "") for kind in ALARM_PIECE_KINDS
            })
        return rows

    def _save(self) -> None:
        payload = [card.values() for card in self._cards]
        QSettings("PowerModel", "EnergyDashboard2").setValue(
            _QS_RULES, json.dumps(payload),
        )

    def _reset(self) -> None:
        QSettings("PowerModel", "EnergyDashboard2").remove(_QS_RULES)
        for card in list(self._cards):
            self._rules.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        for pieces in self._builtin_rows():
            self._add_card(pieces, save=False)
        self._save()


__all__ = ["AlarmDefsTab"]
