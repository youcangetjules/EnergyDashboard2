"""
Energy Dashboard — Alarms page (Dashboards group).

What is sounding right now, and what has fired since the app started. This
page only reads `AlarmMonitor`; conditions are still judged in one place
(`core/alarms.py`) so the page and the tray can never disagree.
"""
from __future__ import annotations

from energy_dashboard.common import *

# After the star import: `common` re-exports datetime.time as `time`.
import time as _clock

_CRITICAL = "#f38ba8"
_WARN = "#f9e2af"
_CLEAR = "#a6e3a1"
_MUTED = "#a6adc8"
_FAINT = "#6c7086"


def _severity_colour(severity: str) -> str:
    return _CRITICAL if str(severity).strip() == "critical" else _WARN


def _severity_word(severity: str) -> str:
    return "Critical" if str(severity).strip() == "critical" else "Warning"


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


class AlarmCard(QFrame):
    """One alarm, live or historic, in words rather than a table row."""

    def __init__(self, *, severity: str, title: str, detail: str, when: str, parent=None):
        super().__init__(parent)
        colour = _severity_colour(severity)
        self.setStyleSheet(
            "AlarmCard {"
            "  background: #181825;"
            f"  border-left: 4px solid {colour};"
            "  border-top: 1px solid #313244;"
            "  border-right: 1px solid #313244;"
            "  border-bottom: 1px solid #313244;"
            "  border-radius: 4px;"
            "}"
        )
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(8)
        name = QLabel(title)
        name.setWordWrap(True)
        name.setStyleSheet(
            f"color: {colour}; font-size: 13px; font-weight: bold; background: transparent;"
        )
        head.addWidget(name, 1)
        level = QLabel(_severity_word(severity))
        level.setStyleSheet(
            f"color: {colour}; font-size: 11px; background: transparent;"
        )
        head.addWidget(level, 0, Qt.AlignmentFlag.AlignTop)
        box.addLayout(head)

        if when:
            stamp = QLabel(when)
            stamp.setStyleSheet(
                f"color: {_MUTED}; font-size: 11px; background: transparent;"
            )
            box.addWidget(stamp)

        body = QLabel(detail or "")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setStyleSheet(
            "color: #cdd6f4; font-size: 12px; background: transparent;"
        )
        box.addWidget(body)


class AlarmsTab(QWidget):
    """Dashboards page: active alarms and this session's alarm history."""

    _HISTORY_SHOWN = 20

    def __init__(self, dash=None):
        super().__init__()
        self.dash = dash
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
        defs_btn = QPushButton("Alarm defs")
        defs_btn.setFixedWidth(120)
        defs_btn.setToolTip("Open the Alarm defs page in Controls to see the rules.")
        defs_btn.clicked.connect(self._show_defs)
        head.addWidget(defs_btn)
        layout.addLayout(head)

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

        now = _clock.time()
        active = sorted(
            list(getattr(mon, "_active", {}).values()),
            key=lambda h: (0 if h.severity == "critical" else 1, h.since_wall),
        )
        if not getattr(mon, "enabled", True):
            self.state.setText("Alarms are switched off in Setup & Info")
            self.state.setStyleSheet(f"color: {_WARN}; font-size: 12px; padding-left: 8px;")
        elif active:
            worst = _severity_colour(active[0].severity)
            self.state.setText(
                f"{len(active)} sounding now"
                if len(active) != 1
                else "1 sounding now"
            )
            self.state.setStyleSheet(f"color: {worst}; font-size: 12px; padding-left: 8px;")
        else:
            self.state.setText("All clear")
            self.state.setStyleSheet(f"color: {_CLEAR}; font-size: 12px; padding-left: 8px;")

        self._add_heading("Sounding now")
        if active:
            for hit in active:
                self._add_card(
                    severity=hit.severity,
                    title=hit.title,
                    detail=hit.detail,
                    when=alarm_age_text(hit.since_wall, now),
                )
        else:
            self._add_note(
                "Nothing is sounding. Solar, battery, inverter, the Grott feed, "
                "the logging database, and the Tasmota monitors all look healthy."
            )

        history = list(getattr(mon, "history", []) or [])
        self._add_heading("Since the app started")
        if history:
            for row in history[: self._HISTORY_SHOWN]:
                stamp = _clock.strftime("%a %H:%M", _clock.localtime(row.get("wall", now)))
                self._add_card(
                    severity=str(row.get("severity", "warn")),
                    title=str(row.get("title", "")),
                    detail=str(row.get("detail", "")),
                    when=f"first raised {stamp}",
                )
            if len(history) > self._HISTORY_SHOWN:
                self._add_note(
                    f"{len(history) - self._HISTORY_SHOWN} older entries are not "
                    "shown. The list is kept for this session only."
                )
        else:
            self._add_note("No alarm has fired since the app was started.")

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

    def _add_heading(self, text: str) -> None:
        label = QLabel(text)
        label.setStyleSheet(
            "color: #f5a524; font-size: 12px; font-weight: bold; "
            "border-bottom: 1px solid #313244; padding-bottom: 3px;"
        )
        self._insert(label)

    def _add_note(self, text: str) -> None:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {_MUTED}; font-size: 12px;")
        self._insert(label)

    def _add_card(self, *, severity: str, title: str, detail: str, when: str) -> None:
        self._insert(AlarmCard(severity=severity, title=title, detail=detail, when=when))


__all__ = ["AlarmsTab", "AlarmCard", "alarm_age_text"]
