"""
Energy Dashboard — Alarms page (Dashboards group).

What is sounding right now, what has been shelved, and what has happened
since the app started. This page only reads `AlarmMonitor`; conditions are
still judged in one place (`core/alarms.py`) so the page and the tray can
never disagree.
"""
from __future__ import annotations

import json

from energy_dashboard.common import *

# After the star import: `common` re-exports datetime.time as `time`.
import time as _clock

# Rank chips. Critical red, major amber, minor yellow, warning blue.
_RANK = {
    "critical": ("Critical", "#c23b4a", "#ffe8ea"),
    "major": ("Major", "#fab387", "#1e1e2e"),
    "minor": ("Minor", "#f9e2af", "#1e1e2e"),
    "warn": ("Warning", "#89b4fa", "#1e1e2e"),
    "warning": ("Warning", "#89b4fa", "#1e1e2e"),
}
_CLEAR = "#a6e3a1"
_MUTED = "#a6adc8"
_FAINT = "#6c7086"
_QS_SUPPRESSED = "alarms/suppressed"
_ROW_BTN_QSS = (
    "QPushButton { background: #313244; color: #cdd6f4; "
    "border: 1px solid #45475a; border-radius: 3px; padding: 0 8px; font-size: 11px; }"
    "QPushButton:hover { background: #45475a; }"
    "QPushButton:disabled { color: #6c7086; background: #1e1e2e; }"
)


def _rank(severity: str) -> tuple[str, str, str]:
    return _RANK.get(str(severity).strip().lower(), _RANK["warn"])


def _severity_colour(severity: str) -> str:
    return _rank(severity)[1]


def _severity_word(severity: str) -> str:
    return _rank(severity)[0]


def alarm_age_text(since_wall: float, now_wall: float | None = None) -> str:
    """Plain-English 'how long has this been going on'."""
    try:
        since = float(since_wall)
    except (TypeError, ValueError):
        return ""
    now = float(now_wall if now_wall is not None else _clock.time())
    mins = max(0.0, (now - since) / 60.0)
    started = _clock.strftime("%H:%M", _clock.localtime(since))
    if mins < 1.0:
        return f"since {started} (just now)"
    if mins < 60.0:
        return f"since {started} ({mins:.0f} min)"
    return f"since {started} ({mins / 60.0:.1f} hours)"


def _clock_text(wall: float) -> str:
    try:
        return _clock.strftime("%H:%M:%S", _clock.localtime(float(wall)))
    except (TypeError, ValueError, OSError, OverflowError):
        return "—"


def _span_text(since_wall: float, now_wall: float) -> str:
    try:
        mins = max(0.0, (float(now_wall) - float(since_wall)) / 60.0)
    except (TypeError, ValueError):
        return "—"
    if mins < 1.0:
        return "just now"
    if mins < 60.0:
        return f"{mins:.0f} min"
    return f"{mins / 60.0:.1f} h"


class _FitText(QLabel):
    """One column. Long text is cut with an ellipsis; the full words are on the hover."""

    def __init__(self, text: str, *, colour: str = "#cdd6f4", bold: bool = False, parent=None):
        super().__init__(parent)
        self._full = text or ""
        self.setToolTip(self._full)
        self.setWordWrap(False)
        weight = "bold" if bold else "normal"
        self.setStyleSheet(
            f"color: {colour}; font-size: 12px; font-weight: {weight}; background: transparent;"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        shown = self.fontMetrics().elidedText(
            self._full, Qt.TextElideMode.ElideRight, max(24, self.width() - 2),
        )
        if self.text() != shown:
            self.setText(shown)


def _column_row() -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(8, 4, 8, 4)
    row.setSpacing(8)
    return row


def _add_fixed(row: QHBoxLayout, widget: QWidget, width: int) -> None:
    widget.setFixedWidth(width)
    row.addWidget(widget, 0)


class AlarmCard(QFrame):
    """One alarm as a row. The words inside sit in columns."""

    def __init__(
        self,
        *,
        severity: str,
        state: str,
        state_colour: str,
        when: str,
        span: str,
        title: str,
        detail: str,
        actions: list[tuple[str, str, object]] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        _word, colour, _ink = _rank(severity)
        self.setObjectName("AlarmCard")
        self.setStyleSheet(
            "QFrame#AlarmCard {"
            "  background: #181825;"
            f"  border-left: 4px solid {colour};"
            "  border-top: 1px solid #313244;"
            "  border-right: 1px solid #313244;"
            "  border-bottom: 1px solid #313244;"
            "  border-radius: 4px;"
            "}"
        )
        row = _column_row()
        self.setLayout(row)
        rank = QLabel(_word)
        rank.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rank.setFixedHeight(22)
        rank.setStyleSheet(
            f"background: {colour}; color: {_ink}; font-size: 11px; font-weight: bold; "
            "border-radius: 3px; padding: 0 4px;"
        )
        _add_fixed(row, rank, 88)
        state_lbl = _FitText(state, colour=state_colour, bold=True)
        _add_fixed(row, state_lbl, 110)
        _add_fixed(row, _FitText(when, colour=_MUTED), 78)
        _add_fixed(row, _FitText(span, colour=_MUTED), 72)
        row.addWidget(_FitText(title, colour="#cdd6f4", bold=True), 2)
        row.addWidget(_FitText(detail, colour="#a6adc8"), 3)
        actions_host = QWidget()
        actions_host.setFixedWidth(196)
        actions_row = QHBoxLayout(actions_host)
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(4)
        for label, tip, handler in actions or []:
            button = QPushButton(label)
            button.setFixedHeight(22)
            button.setToolTip(tip)
            button.setStyleSheet(_ROW_BTN_QSS)
            button.setProperty(PRIMARY_BUTTON_EXEMPT, True)
            if handler is None:
                button.setEnabled(False)
            else:
                button.clicked.connect(handler)
            actions_row.addWidget(button)
        actions_row.addStretch(1)
        row.addWidget(actions_host, 0)


class AlarmsTab(QWidget):
    """Dashboards page: sounding alarms, shelved alarms, and the session history."""

    def __init__(self, dash=None):
        super().__init__()
        self.dash = dash
        self._view = "sounding"
        self._shelves_loaded = False
        self._view_buttons: dict[str, QPushButton] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("Alarms")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #cdd6f4;")
        head.addWidget(title)
        self.state = QLabel("")
        self.state.setStyleSheet(
            f"color: {_CLEAR}; font-size: 12px; padding-left: 8px;"
        )
        head.addWidget(self.state)
        head.addStretch(1)
        for key, label, tip in (
            ("sounding", "Sounding", "Alarms that are true now and not shelved."),
            ("suppressed", "Suppressed", "Alarms you have shelved. They do not notify."),
            ("history", "History", "Raised, acknowledged, suppressed, and cleared since the app started."),
        ):
            button = QPushButton(label)
            button.setFixedHeight(26)
            button.setToolTip(tip)
            button.setProperty(PRIMARY_BUTTON_EXEMPT, True)
            button.clicked.connect(lambda _checked=False, name=key: self._set_view(name))
            self._view_buttons[key] = button
            head.addWidget(button)
        defs_btn = QPushButton("Alarm defs")
        defs_btn.setFixedWidth(120)
        defs_btn.setToolTip("Open the Alarm defs page in Controls to see the rules.")
        defs_btn.clicked.connect(self._show_defs)
        head.addWidget(defs_btn)
        layout.addLayout(head)
        self._paint_view_buttons()

        self._columns = QWidget()
        col = _column_row()
        self._columns.setLayout(col)
        for text, width, stretch in (
            ("Rank", 88, 0),
            ("State", 110, 0),
            ("Time", 78, 0),
            ("For", 72, 0),
            ("Alarm", 0, 2),
            ("Detail", 0, 3),
            ("", 196, 0),
        ):
            label = QLabel(text)
            label.setStyleSheet(
                "color: #6c7086; font-size: 10px; font-weight: bold; background: transparent;"
            )
            if width:
                label.setFixedWidth(width)
                col.addWidget(label, 0)
            else:
                col.addWidget(label, stretch)
        layout.addWidget(self._columns)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self._body = QVBoxLayout(host)
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(8)
        self._body.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

        self.rules = QLabel("")
        self.rules.setWordWrap(True)
        self.rules.setStyleSheet(f"color: {_FAINT}; font-size: 11px;")
        layout.addWidget(self.rules)

        self._tick = QTimer(self)
        self._tick.setInterval(10_000)
        self._tick.timeout.connect(self._tick_refresh)
        self._tick.start()
        self.refresh_now()

    # ── wiring ───────────────────────────────────────────────────────────
    def set_hits(self, _hits=None) -> None:
        """Called by the main window after each alarm evaluation."""
        self.refresh_now()

    def _tick_refresh(self) -> None:
        # Only redraw the page the user can actually see.
        if self.isVisible():
            self.refresh_now()

    def _monitor(self):
        return getattr(self.dash, "alarm_monitor", None)

    def _show_defs(self) -> None:
        dash = self.dash
        page = getattr(dash, "alarm_defs_tab", None)
        if dash is not None and page is not None:
            dash.show_main_page(page)

    # ── drawing ──────────────────────────────────────────────────────────
    def refresh_now(self) -> None:
        mon = self._monitor()
        self._clear_body()
        if mon is None:
            self.state.setText("Alarm monitor not started")
            self.state.setStyleSheet(f"color: {_MUTED}; font-size: 12px; padding-left: 8px;")
            self.rules.setText("")
            return
        self._ensure_shelves(mon)

        now = _clock.time()
        order = {"critical": 0, "major": 1, "minor": 2, "warn": 3, "warning": 3}
        active = [
            hit for hit in getattr(mon, "_active", {}).values()
            if not getattr(hit, "suppressed", False)
        ]
        active.sort(key=lambda h: (
            0 if not getattr(h, "acknowledged", False) else 1,
            order.get(str(h.severity).lower(), 9),
            h.since_wall,
        ))
        if not getattr(mon, "enabled", True):
            self.state.setText("Alarms are switched off in Setup & Info")
            self.state.setStyleSheet(f"color: #f9e2af; font-size: 12px; padding-left: 8px;")
        elif active:
            unacked = sum(1 for hit in active if not getattr(hit, "acknowledged", False))
            worst = _severity_colour(active[0].severity)
            self.state.setText(
                f"{len(active)} sounding, {unacked} unacknowledged"
            )
            self.state.setStyleSheet(f"color: {worst}; font-size: 12px; padding-left: 8px;")
        else:
            self.state.setText("All clear")
            self.state.setStyleSheet(f"color: {_CLEAR}; font-size: 12px; padding-left: 8px;")

        if self._view == "history":
            self._show_history(mon, now)
        elif self._view == "suppressed":
            self._show_suppressed(mon, now)
        else:
            self._show_sounding(active, now)

        self.rules.setText(
            f"An alarm needs the condition to hold for {float(mon.hold_minutes):.0f} "
            f"minutes before it sounds, and spare solar counts from "
            f"{float(mon.pv_min_kw):.1f} kW. Desktop pop-ups repeat immediately, "
            "then four times every 5 minutes, four times every 10, four times "
            "every 30, then hourly. Thresholds live in Setup & Info; the rules "
            "themselves are on Alarm defs in Controls."
        )

    def _clear_body(self) -> None:
        while self._body.count() > 1:
            item = self._body.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _insert(self, widget) -> None:
        self._body.insertWidget(self._body.count() - 1, widget)

    def _set_view(self, name: str) -> None:
        self._view = name
        self._paint_view_buttons()
        self.refresh_now()

    def _paint_view_buttons(self) -> None:
        for key, button in self._view_buttons.items():
            if key == self._view:
                button.setStyleSheet(
                    "QPushButton { background: #313244; color: #f5a524; "
                    "border: 1px solid #f5a524; border-radius: 3px; padding: 2px 12px; "
                    "font-size: 12px; font-weight: bold; }"
                )
            else:
                button.setStyleSheet(
                    "QPushButton { background: #1e1e2e; color: #a6adc8; "
                    "border: 1px solid #313244; border-radius: 3px; padding: 2px 12px; "
                    "font-size: 12px; }"
                    "QPushButton:hover { color: #cdd6f4; }"
                )

    def _ensure_shelves(self, mon) -> None:
        if self._shelves_loaded or mon is None or not hasattr(mon, "restore_suppressed"):
            return
        self._shelves_loaded = True
        raw = QSettings("PowerModel", "EnergyDashboard2").value(_QS_SUPPRESSED, "")
        keys: list[str] = []
        if raw:
            try:
                parsed = json.loads(str(raw))
                if isinstance(parsed, list):
                    keys = [str(key) for key in parsed]
            except (TypeError, ValueError, json.JSONDecodeError):
                keys = []
        mon.restore_suppressed(keys)

    def _save_shelves(self, mon) -> None:
        keys = sorted(mon.suppressed_keys()) if hasattr(mon, "suppressed_keys") else []
        QSettings("PowerModel", "EnergyDashboard2").setValue(
            _QS_SUPPRESSED, json.dumps(keys),
        )

    def _show_sounding(self, active, now: float) -> None:
        if not active:
            self._add_note(
                "Nothing is sounding. Solar, battery, inverter, the Grott feed, "
                "the logging database, and the Tasmota monitors all look healthy."
            )
            return
        for hit in active:
            state = "ACK" if getattr(hit, "acknowledged", False) else "UNACK"
            state_colour = _CLEAR if state == "ACK" else _severity_colour(hit.severity)
            actions: list[tuple[str, str, object]] = []
            if state == "UNACK":
                actions.append((
                    "Acknowledge",
                    "You have seen this alarm. It stays on the list and stops repeating.",
                    lambda _checked=False, key=hit.key: self._acknowledge(key),
                ))
            else:
                actions.append(("Acknowledged", "Already acknowledged.", None))
            actions.append((
                "Suppress",
                "Shelf this alarm. It will not notify until you unsuppress it.",
                lambda _checked=False, key=hit.key: self._suppress(key),
            ))
            self._insert(AlarmCard(
                severity=hit.severity,
                state=state,
                state_colour=state_colour,
                when=_clock_text(hit.since_wall),
                span=_span_text(hit.since_wall, now),
                title=hit.title,
                detail=hit.detail,
                actions=actions,
            ))

    def _show_suppressed(self, mon, now: float) -> None:
        rows = mon.shelved_rows() if hasattr(mon, "shelved_rows") else []
        if not rows:
            self._add_note("Nothing is suppressed.")
            return
        for row in rows:
            sounding = bool(row.get("sounding"))
            since = float(row.get("since_wall") or 0.0)
            self._insert(AlarmCard(
                severity=str(row.get("severity") or "warn"),
                state="SUPPRESSED",
                state_colour=_FAINT,
                when=_clock_text(since) if since else "—",
                span=_span_text(since, now) if sounding and since else "not sounding",
                title=str(row.get("title") or ""),
                detail=str(row.get("detail") or ""),
                actions=[(
                    "Unsuppress",
                    "Put this alarm back on the sounding list.",
                    lambda _checked=False, key=str(row.get("key") or ""): self._unsuppress(key),
                )],
            ))

    def _show_history(self, mon, now: float) -> None:
        history = list(getattr(mon, "history", []) or [])
        if not history:
            self._add_note("No alarm has fired since the app was started.")
            return
        words = {
            "raised": "RAISED",
            "acknowledged": "ACK",
            "suppressed": "SUPPRESSED",
            "unsuppressed": "UNSUPPRESSED",
            "cleared": "CLEARED",
        }
        for row in history:
            event = str(row.get("event") or "raised")
            wall = float(row.get("wall") or now)
            self._insert(AlarmCard(
                severity=str(row.get("severity") or "warn"),
                state=words.get(event, event.upper()),
                state_colour=_MUTED if event == "cleared" else _severity_colour(str(row.get("severity") or "warn")),
                when=_clock_text(wall),
                span=_clock.strftime("%a", _clock.localtime(wall)),
                title=str(row.get("title") or ""),
                detail=str(row.get("detail") or ""),
                actions=[],
            ))

    def _acknowledge(self, key: str) -> None:
        mon = self._monitor()
        if mon is not None and hasattr(mon, "acknowledge"):
            mon.acknowledge(key)
        self._repaint_horn()
        self.refresh_now()

    def _repaint_horn(self) -> None:
        """Banner, count, and tray follow a shelf change without waiting for the next check."""
        dash = self.dash
        mon = self._monitor()
        if dash is None or mon is None:
            return
        hits = list(getattr(mon, "_active", {}).values())
        if hasattr(dash, "_apply_alarm_banner"):
            dash._apply_alarm_banner(hits)
        if hasattr(dash, "_tray_refresh_alarm_bands"):
            dash._tray_refresh_alarm_bands()

    def _suppress(self, key: str) -> None:
        mon = self._monitor()
        if mon is not None and hasattr(mon, "suppress"):
            mon.suppress(key)
            self._save_shelves(mon)
        self._repaint_horn()
        self.refresh_now()

    def _unsuppress(self, key: str) -> None:
        mon = self._monitor()
        if mon is not None and hasattr(mon, "unsuppress"):
            mon.unsuppress(key)
            self._save_shelves(mon)
        self._repaint_horn()
        self.refresh_now()

    def _add_note(self, text: str) -> None:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")
        self._insert(label)


__all__ = ["AlarmsTab", "AlarmCard", "alarm_age_text"]
