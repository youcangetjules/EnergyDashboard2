"""
Energy Dashboard — Alarm defs tab (Controls group).

Describes the alarms. What is sounding right now is the Alarms page in
Dashboards (`tabs/alarms.py`).

An alarm is built from its smallest pieces: a signal, a comparison, a
threshold, how long it has to hold, an optional extra condition, and the
outcome. Drag those blocks into a row and the line underneath is the
syntax. A row that matches a built-in alarm is live; anything else is a
draft and does not fire.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QMimeData
from PySide6.QtGui import QDrag

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

# One colour per kind of block, so a row reads as a sentence of parts.
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
# Short palette-column captions.
_KIND_SHORT = dict(_KIND_LABEL, duration="How long", context="While")
_ROW_1 = ("signal", "comparison", "threshold")
_ROW_2 = ("duration", "context", "outcome")
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


class AlarmChip(QLabel):
    """One draggable block."""

    def __init__(self, kind: str, text: str, parent=None):
        super().__init__(text, parent)
        self.kind = kind
        self._press = None
        self.setWordWrap(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(f"Drag into a {_KIND_LABEL[kind]} box")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setStyleSheet(
            "QLabel {"
            f"  background: {_KIND_COLOR[kind]};"
            "  color: #1e1e2e;"
            "  border-radius: 4px;"
            "  padding: 3px 7px;"
            "  font-size: 11px;"
            "}"
        )

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
        mime.setData(_MIME, f"{self.kind}\n{self.text()}".encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)
        self._press = None


class AlarmWell(QFrame):
    """Drop target for one kind of block. Right-click empties it."""

    changed = Signal()

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._text = ""
        self.setAcceptDrops(True)
        self.setMinimumHeight(54)
        self.setToolTip(
            f"{_KIND_LABEL[kind]} — drop a {_KIND_SHORT[kind].lower()} block here. "
            "Right-click to empty it."
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 4, 7, 5)
        layout.setSpacing(1)
        self._title = QLabel(_KIND_LABEL[kind])
        self._title.setStyleSheet(
            "color: #a6adc8; font-size: 10px; background: transparent;"
        )
        self._body = QLabel("")
        self._body.setWordWrap(True)
        layout.addWidget(self._title)
        layout.addWidget(self._body, 1)
        self.set_piece("")

    def text(self) -> str:
        return self._text

    def set_piece(self, text: str) -> None:
        self._text = (text or "").strip()
        optional = self.kind not in ALARM_PIECE_REQUIRED
        if self._text:
            self._body.setText(self._text)
            self._body.setStyleSheet(
                "color: #1e1e2e; font-size: 12px; background: transparent;"
            )
            self._title.setStyleSheet(
                "color: #45475a; font-size: 10px; background: transparent;"
            )
        else:
            self._body.setText("not used" if optional else f"drop a {_KIND_SHORT[self.kind].lower()}")
            self._body.setStyleSheet(
                "color: #6c7086; font-size: 12px; background: transparent;"
            )
            self._title.setStyleSheet(
                "color: #a6adc8; font-size: 10px; background: transparent;"
            )
        self._paint()

    def _paint(self) -> None:
        colour = _KIND_COLOR[self.kind]
        if self._text:
            self.setStyleSheet(
                "AlarmWell {" f"  background: {colour};" "  border-radius: 6px; }"
            )
        else:
            self.setStyleSheet(
                "AlarmWell {"
                "  background: #181825;"
                f"  border: 1px dashed {colour};"
                "  border-radius: 6px; }"
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


class AlarmRuleCard(QFrame):
    """One row of blocks, plus the sentence they make."""

    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "AlarmRuleCard { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)

        self.wells: dict[str, AlarmWell] = {}
        for kinds in (_ROW_1, _ROW_2):
            row = QHBoxLayout()
            row.setSpacing(8)
            for kind in kinds:
                well = AlarmWell(kind)
                well.changed.connect(self._on_changed)
                self.wells[kind] = well
                row.addWidget(well, 1)
            outer.addLayout(row)

        foot = QHBoxLayout()
        self.syntax = QLabel("")
        self.syntax.setWordWrap(True)
        self.syntax.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.syntax.setStyleSheet(
            "color: #cdd6f4; font-size: 12px; background: transparent;"
        )
        foot.addWidget(self.syntax, 1)
        self.status = QLabel("")
        self.status.setStyleSheet(
            "color: #a6adc8; font-size: 11px; background: transparent;"
        )
        foot.addWidget(self.status)
        remove = QPushButton("Remove")
        remove.setFixedWidth(88)
        remove.setToolTip("Take this row off the page")
        remove.clicked.connect(lambda: self.remove_requested.emit(self))
        foot.addWidget(remove)
        outer.addLayout(foot)
        self._refresh_syntax()

    def values(self) -> dict[str, str]:
        return {kind: well.text() for kind, well in self.wells.items()}

    def set_values(self, pieces: dict[str, str]) -> None:
        for kind, well in self.wells.items():
            well.set_piece(str((pieces or {}).get(kind) or ""))
        self._refresh_syntax()

    def _on_changed(self) -> None:
        self._refresh_syntax()
        self.changed.emit()

    def _refresh_syntax(self) -> None:
        pieces = self.values()
        sentence = alarm_rule_syntax(pieces)
        if not sentence:
            missing = [k for k in ALARM_PIECE_REQUIRED if not pieces.get(k)]
            self.syntax.setText(_needs_text(missing))
            self.status.setText("")
            return
        self.syntax.setText(sentence)
        if alarm_blocks_key(pieces):
            self.status.setText("Live rule")
            self.status.setStyleSheet(
                "color: #a6e3a1; font-size: 11px; background: transparent;"
            )
        else:
            self.status.setText("Draft — this does not fire")
            self.status.setStyleSheet(
                "color: #f9e2af; font-size: 11px; background: transparent;"
            )


class AlarmDefsTab(QWidget):
    """Controls page: drag blocks to build an alarm sentence."""

    def __init__(self, dash=None):
        super().__init__()
        self.dash = dash
        self._cards: list[AlarmRuleCard] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("Alarm defs")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #cdd6f4;")
        head.addWidget(title)
        head.addStretch(1)
        live_btn = QPushButton("Alarms page")
        live_btn.setFixedWidth(120)
        live_btn.setToolTip("Open the Alarms page in Dashboards to see what is sounding.")
        live_btn.clicked.connect(self._show_live)
        head.addWidget(live_btn)
        add_btn = QPushButton("Add rule")
        add_btn.setFixedWidth(110)
        add_btn.setToolTip("Add an empty row")
        add_btn.clicked.connect(lambda: self._add_card({}))
        head.addWidget(add_btn)
        reset_btn = QPushButton("Reset")
        reset_btn.setFixedWidth(110)
        reset_btn.setToolTip("Put the built-in rules back")
        reset_btn.clicked.connect(self._reset)
        head.addWidget(reset_btn)
        layout.addLayout(head)

        hint = QLabel(
            "Every alarm is made of blocks: a signal, a comparison, the "
            "threshold it is compared against, how long it has to hold, an "
            "optional extra condition, and the outcome. Drag a block into the "
            "matching box; right-click a box to empty it. A row that matches a "
            "built-in alarm is marked live — any other mix is a draft and does "
            "not fire."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        layout.addWidget(hint)

        pieces = QHBoxLayout()
        pieces.setSpacing(8)
        for kind in ALARM_PIECE_KINDS:
            pieces.addWidget(self._piece_column(kind), 1)
        layout.addLayout(pieces)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rules_host = QWidget()
        self._rules = QVBoxLayout(self._rules_host)
        self._rules.setContentsMargins(0, 0, 0, 0)
        self._rules.setSpacing(8)
        self._rules.addStretch(1)
        scroll.setWidget(self._rules_host)
        layout.addWidget(scroll, 1)
        self._load()

    def _piece_column(self, kind: str) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        label = QLabel(_KIND_SHORT[kind])
        label.setStyleSheet(
            f"color: {_KIND_COLOR[kind]}; font-size: 12px; font-weight: bold;"
        )
        col.addWidget(label)
        for text in alarm_palette(kind):
            col.addWidget(AlarmChip(kind, text))
        col.addStretch(1)
        return box

    def _show_live(self) -> None:
        dash = self.dash
        page = getattr(dash, "alarms_tab", None)
        if dash is not None and page is not None:
            dash.show_main_page(page)

    def _add_card(self, pieces: dict[str, str], *, save: bool = True) -> None:
        card = AlarmRuleCard()
        card.set_values(pieces)
        card.changed.connect(self._save)
        card.remove_requested.connect(self._remove_card)
        self._cards.append(card)
        self._rules.insertWidget(self._rules.count() - 1, card)
        if save:
            self._save()

    def _remove_card(self, card: AlarmRuleCard) -> None:
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
