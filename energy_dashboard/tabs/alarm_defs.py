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

from PySide6.QtCore import QMimeData, QSize
from PySide6.QtGui import QColor, QDrag, QFontMetrics, QPainter
from PySide6.QtWidgets import (
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
_QS_RULES = "alarms/defs_blocks"
_ROW_H = 28
_PALETTE_H = 118

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
        self.setFixedHeight(_PALETTE_H)
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
    """One drop target on a rule line. Right-click empties it."""

    changed = Signal()

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._text = ""
        self.setAcceptDrops(True)
        self.setFixedHeight(_ROW_H)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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
        if not self._text:
            return
        shown = QFontMetrics(self._body.font()).elidedText(
            self._text, Qt.TextElideMode.ElideRight, max(24, self._body.width()),
        )
        if shown != self._body.text():
            self._body.setText(shown)

    def text(self) -> str:
        return self._text

    def set_piece(self, text: str) -> None:
        self._text = (text or "").strip()
        colour = _KIND_COLOR[self.kind]
        if self._text:
            self._body.setText(self._text)
            self._body.setStyleSheet(
                "color: #1e1e2e; font-size: 11px; background: transparent;"
            )
            self.setStyleSheet(
                f"_Slot {{ background: {colour}; border-radius: 3px; }}"
            )
            self.setToolTip(f"{self._text}\nRight-click to empty this slot.")
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
            self.setToolTip(
                f"Drop a {_KIND_SHORT[self.kind].lower()} here."
                + (" Optional." if optional else "")
            )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self._text:
            self.set_piece("")
            self.changed.emit()
            return
        super().mousePressEvent(event)

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


class _RuleLine(QFrame):
    """One numbered alarm: a line of slots, and a halo when the sentence is whole."""

    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_ROW_H + 22)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 3, 4, 2)
        outer.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self._number = QLabel("1")
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
                lab.setStyleSheet("color: #6c7086; font-size: 10px; background: transparent;")
                lab.setFixedWidth(34 if kind != "signal" else 36)
                row.addWidget(lab)
            slot = _Slot(kind)
            slot.changed.connect(self._on_changed)
            self.slots[kind] = slot
            row.addWidget(slot, 3 if kind in ("signal", "context", "outcome") else 2)
        remove = QPushButton("×")
        remove.setFixedSize(24, _ROW_H)
        remove.setToolTip("Take this rule off the page")
        remove.setProperty("primary_button_exempt", True)
        remove.setStyleSheet(
            "QPushButton { background: transparent; color: #a6adc8; border: none; "
            "font-size: 14px; }"
            "QPushButton:hover { color: #f38ba8; }"
        )
        remove.clicked.connect(lambda: self.remove_requested.emit(self))
        row.addWidget(remove)
        outer.addLayout(row)
        self._syntax_note = QLabel("Syntax Correct")
        self._syntax_note.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._syntax_note.setStyleSheet(
            "color: #a6e3a1; font-size: 10px; background: transparent; padding-right: 28px;"
        )
        outer.addWidget(self._syntax_note)
        self._refresh()

    def set_number(self, number: int) -> None:
        self._number.setText(str(number))

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
        sentence = alarm_rule_syntax(pieces)
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
        self._syntax_note.setVisible(on)
        if on:
            self.setStyleSheet(
                "_RuleLine {"
                "  border: 1px solid #a6e3a1;"
                "  border-radius: 5px;"
                "  background-color: rgba(166, 227, 161, 16);"
                "}"
            )
            glow = QGraphicsDropShadowEffect(self)
            glow.setBlurRadius(16)
            glow.setOffset(0, 0)
            glow.setColor(QColor(166, 227, 161, 170))
            self.setGraphicsEffect(glow)
        else:
            self.setStyleSheet(
                "_RuleLine { border: 1px solid transparent; background: transparent; }"
            )
            self.setGraphicsEffect(None)


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
            "Drag a block from a list into a slot of the same colour. "
            "Right-click a slot to empty it. A complete sentence gets a green halo."
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

        pieces = QHBoxLayout()
        pieces.setSpacing(6)
        for kind in ALARM_PIECE_KINDS:
            pieces.addWidget(self._piece_column(kind), 1)
        layout.addLayout(pieces)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rules_host = QWidget()
        self._rules = QVBoxLayout(self._rules_host)
        # Room around each line so the green halo is not clipped.
        self._rules.setContentsMargins(8, 6, 8, 6)
        self._rules.setSpacing(10)
        self._rules.addStretch(1)
        scroll.setWidget(self._rules_host)
        layout.addWidget(scroll, 1)
        self._load()

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
        col.addWidget(_PaletteList(kind))
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
        self._rules.insertWidget(self._rules.count() - 1, card)
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
