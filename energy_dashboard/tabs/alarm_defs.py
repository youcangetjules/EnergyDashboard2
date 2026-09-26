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

from PySide6.QtCore import QMimeData
from PySide6.QtGui import QDrag, QFontMetrics

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


class _PaletteChip(QLabel):
    """One palette row. Fixed height, so a long block scrolls instead of growing."""

    def __init__(self, kind: str, text: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._full = text
        self._press = None
        self.setFixedHeight(20)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            "QLabel {"
            f"  background: {_KIND_COLOR[kind]};"
            "  color: #1e1e2e;"
            "  border-radius: 3px;"
            "  padding: 0px 6px;"
            "  font-size: 11px;"
            "}"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        shown = QFontMetrics(self.font()).elidedText(
            self._full, Qt.TextElideMode.ElideRight, max(24, self.width() - 14),
        )
        if shown != self.text():
            self.setText(shown)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.position().toPoint() - self._press).manhattanLength() < 8:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_MIME, f"{self.kind}\n{self._full}".encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)
        self._press = None


def _palette_list(kind: str) -> QScrollArea:
    """Short scrolling list of one kind of block."""
    host = QWidget()
    col = QVBoxLayout(host)
    col.setContentsMargins(2, 2, 2, 2)
    col.setSpacing(2)
    for text in alarm_palette(kind):
        col.addWidget(_PaletteChip(kind, text))
    col.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setFixedHeight(_PALETTE_H)
    scroll.setWidget(host)
    scroll.setToolTip(f"Drag a {_KIND_SHORT[kind].lower()} into a slot of the same colour")
    scroll.setStyleSheet(
        "QScrollArea { background: #181825; border: 1px solid #313244; border-radius: 4px; }"
    )
    host.setStyleSheet("background: #181825;")
    return scroll


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
                "  background: #181825;"
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
            event.acceptProposedAction()
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
        event.acceptProposedAction()
        self.changed.emit()


class _RuleLine(QWidget):
    """One alarm on a single line of slots."""

    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_ROW_H + 4)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.slots: dict[str, _Slot] = {}
        for kind in ALARM_PIECE_KINDS:
            word = _BEFORE.get(kind)
            if word:
                lab = QLabel(word)
                lab.setStyleSheet("color: #6c7086; font-size: 10px;")
                lab.setFixedWidth(34 if kind != "signal" else 36)
                row.addWidget(lab)
            slot = _Slot(kind)
            slot.changed.connect(self._on_changed)
            self.slots[kind] = slot
            row.addWidget(slot, 3 if kind in ("signal", "context", "outcome") else 2)
        self.status = QLabel("")
        self.status.setFixedWidth(44)
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.status)
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
        self._refresh()

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
            self.status.setText("—")
            self.status.setStyleSheet("color: #6c7086; font-size: 11px;")
            self.setToolTip(_needs_text(
                [k for k in ALARM_PIECE_REQUIRED if not pieces.get(k)]
            ))
            return
        self.setToolTip(sentence)
        if alarm_blocks_key(pieces):
            self.status.setText("Live")
            self.status.setStyleSheet("color: #a6e3a1; font-size: 11px;")
        else:
            self.status.setText("Draft")
            self.status.setStyleSheet("color: #f9e2af; font-size: 11px;")
            self.setToolTip(sentence + "\nDraft — this does not fire.")


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
            "Right-click a slot to empty it. Live means it matches a built-in alarm."
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
        self._rules.setContentsMargins(0, 2, 0, 0)
        self._rules.setSpacing(2)
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
        col.addWidget(_palette_list(kind))
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
        if save:
            self._save()

    def _remove_card(self, card: _RuleLine) -> None:
        if card not in self._cards:
            return
        self._cards.remove(card)
        self._rules.removeWidget(card)
        card.deleteLater()
        self._save()

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
