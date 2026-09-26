"""
Energy Dashboard — Alarm defs tab (Dashboards group).

Drag a What, a Condition, and an Outcome into a row. The line underneath
is the alarm syntax. A sentence that matches a built-in rule is live.
Any other sentence is a draft and does not fire.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QMimeData
from PySide6.QtGui import QDrag

from energy_dashboard.common import *
from energy_dashboard.core.alarms import (
    ALARM_PHRASES,
    alarm_phrase_key,
    alarm_piece_accepted,
    alarm_rule_syntax,
)

_MIME = "application/x-powermon-alarm-piece"
_QS_RULES = "alarms/defs_syntax"
_KIND_COLOR = {
    "what": "#89b4fa",
    "condition": "#f9e2af",
    "outcome": "#f38ba8",
}
_KIND_LABEL = {
    "what": "What",
    "condition": "Condition",
    "outcome": "Outcome",
}


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
    """A draggable What, Condition, or Outcome piece."""

    def __init__(self, kind: str, text: str, parent=None):
        super().__init__(text, parent)
        self.kind = kind
        self._press = None
        self.setWordWrap(True)
        self.setMaximumWidth(320)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        colour = _KIND_COLOR[kind]
        self.setStyleSheet(
            "QLabel {"
            f"  background: {colour};"
            "  color: #1e1e2e;"
            "  border-radius: 4px;"
            "  padding: 4px 8px;"
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
    """Drop target for one kind of piece."""

    changed = Signal()

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._text = ""
        self.setAcceptDrops(True)
        self.setMinimumHeight(72)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self._title = QLabel(_KIND_LABEL[kind])
        self._title.setStyleSheet("color: #a6adc8; font-size: 10px; background: transparent;")
        self._body = QLabel(f"Drop a {kind}")
        self._body.setWordWrap(True)
        self._body.setStyleSheet("color: #6c7086; font-size: 12px; background: transparent;")
        layout.addWidget(self._title)
        layout.addWidget(self._body, 1)
        self._paint()

    def text(self) -> str:
        return self._text

    def set_piece(self, text: str) -> None:
        self._text = (text or "").strip()
        if self._text:
            self._body.setText(self._text)
            self._body.setStyleSheet("color: #1e1e2e; font-size: 12px; background: transparent;")
        else:
            self._body.setText(f"Drop a {self.kind}")
            self._body.setStyleSheet("color: #6c7086; font-size: 12px; background: transparent;")
        self._paint()

    def _paint(self) -> None:
        colour = _KIND_COLOR[self.kind]
        if self._text:
            self.setStyleSheet(
                "AlarmWell {"
                f"  background: {colour};"
                "  border-radius: 6px;"
                "}"
            )
        else:
            self.setStyleSheet(
                "AlarmWell {"
                "  background: #181825;"
                f"  border: 1px dashed {colour};"
                "  border-radius: 6px;"
                "}"
            )

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
    """One What / Condition / Outcome row, plus the sentence it makes."""

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

        wells = QHBoxLayout()
        wells.setSpacing(8)
        self.what = AlarmWell("what")
        self.condition = AlarmWell("condition")
        self.outcome = AlarmWell("outcome")
        for well in (self.what, self.condition, self.outcome):
            well.changed.connect(self._on_changed)
            wells.addWidget(well, 1)
        outer.addLayout(wells)

        foot = QHBoxLayout()
        self.syntax = QLabel("Drop a what, a condition, and an outcome.")
        self.syntax.setWordWrap(True)
        self.syntax.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.syntax.setStyleSheet("color: #cdd6f4; font-size: 12px; background: transparent;")
        foot.addWidget(self.syntax, 1)
        self.status = QLabel("")
        self.status.setStyleSheet("color: #a6adc8; font-size: 11px; background: transparent;")
        foot.addWidget(self.status)
        remove = QPushButton("Remove")
        remove.setFixedWidth(88)
        remove.setToolTip("Take this sentence off the page")
        remove.clicked.connect(lambda: self.remove_requested.emit(self))
        foot.addWidget(remove)
        outer.addLayout(foot)
        self._refresh_syntax()

    def values(self) -> tuple[str, str, str]:
        return self.what.text(), self.condition.text(), self.outcome.text()

    def set_values(self, what: str, condition: str, outcome: str) -> None:
        self.what.set_piece(what)
        self.condition.set_piece(condition)
        self.outcome.set_piece(outcome)
        self._refresh_syntax()

    def _on_changed(self) -> None:
        self._refresh_syntax()
        self.changed.emit()

    def _refresh_syntax(self) -> None:
        what, condition, outcome = self.values()
        sentence = alarm_rule_syntax(what, condition, outcome)
        if not sentence:
            self.syntax.setText("Drop a what, a condition, and an outcome.")
            self.status.setText("")
            return
        self.syntax.setText(sentence)
        if alarm_phrase_key(what, condition, outcome):
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
    """Dashboards page: drag pieces to build an alarm sentence."""

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
        add_btn = QPushButton("Add rule")
        add_btn.setFixedWidth(110)
        add_btn.setToolTip("Add an empty What / Condition / Outcome row")
        add_btn.clicked.connect(lambda: self._add_card("", "", ""))
        head.addWidget(add_btn)
        reset_btn = QPushButton("Reset")
        reset_btn.setFixedWidth(110)
        reset_btn.setToolTip("Put the built-in sentences back")
        reset_btn.clicked.connect(self._reset)
        head.addWidget(reset_btn)
        layout.addLayout(head)

        hint = QLabel(
            "Drag a blue What, an amber Condition, and a red Outcome into a row. "
            "The line under the row is the syntax. A sentence that matches a "
            "built-in rule is live. Any other mix is a draft and does not fire."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        layout.addWidget(hint)

        pieces = QHBoxLayout()
        pieces.setSpacing(10)
        for kind in ("what", "condition", "outcome"):
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
        label = QLabel(_KIND_LABEL[kind])
        label.setStyleSheet(
            f"color: {_KIND_COLOR[kind]}; font-size: 12px; font-weight: bold;"
        )
        col.addWidget(label)
        seen: list[str] = []
        for phrase in ALARM_PHRASES:
            text = getattr(phrase, kind)
            if text not in seen:
                seen.append(text)
                col.addWidget(AlarmChip(kind, text))
        col.addStretch(1)
        return box

    def _add_card(self, what: str, condition: str, outcome: str, *, save: bool = True) -> None:
        card = AlarmRuleCard()
        card.set_values(what, condition, outcome)
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

    def _builtin_rows(self) -> list[tuple[str, str, str]]:
        return [(p.what, p.condition, p.outcome) for p in ALARM_PHRASES]

    def _load(self) -> None:
        rows = self._read_saved()
        if not rows:
            rows = self._builtin_rows()
        for what, condition, outcome in rows:
            self._add_card(what, condition, outcome, save=False)

    def _read_saved(self) -> list[tuple[str, str, str]]:
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
            rows.append((
                str(item.get("what") or ""),
                str(item.get("condition") or ""),
                str(item.get("outcome") or ""),
            ))
        return rows

    def _save(self) -> None:
        payload = [
            {"what": w, "condition": c, "outcome": o}
            for w, c, o in (card.values() for card in self._cards)
        ]
        QSettings("PowerModel", "EnergyDashboard2").setValue(
            _QS_RULES, json.dumps(payload),
        )

    def _reset(self) -> None:
        QSettings("PowerModel", "EnergyDashboard2").remove(_QS_RULES)
        for card in list(self._cards):
            self._rules.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        for what, condition, outcome in self._builtin_rows():
            self._add_card(what, condition, outcome, save=False)
        self._save()


__all__ = ["AlarmDefsTab"]
