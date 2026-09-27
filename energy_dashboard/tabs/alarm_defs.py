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
    alarm_logic_note,
    alarm_palette,
    duration_seconds,
    format_duration,
    parse_flap,
    FLAP_CHOICE,
    FlapSpec,
    signal_alarm_type,
    alarm_unit_problem,
    split_joined_pieces,
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
    "context": "With additional Conditions (optional)",
    "outcome": "Outcome",
}
_KIND_SHORT = dict(
    _KIND_LABEL, duration="How long", context="With additional Conditions",
)
# One or two words for hover text: "Drop a condition here."
_KIND_WORD = {
    "signal": "signal",
    "comparison": "comparison",
    "threshold": "threshold",
    "duration": "how long",
    "context": "condition",
    "outcome": "outcome",
}
# Faint grey for the alarm type under each signal on the palette.
_ALARM_TYPE_INK = "#e6e6e6"
# Little words between the slots, so the line still reads as a sentence.
_BEFORE = {
    "signal": "when",
    "duration": "for",
    "context": "with",
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


def _decode_slot(mime: QMimeData) -> tuple[str, str, int | None]:
    raw = _decode_token(mime, _MIME_SLOT)
    if not raw:
        return "", "", None
    lines = raw.split("\n")
    token = lines[0].strip()
    kind = lines[1].strip() if len(lines) > 1 else ""
    index = None
    if len(lines) > 2 and lines[2].strip().isdigit():
        index = int(lines[2].strip())
    return token, kind, index


# A signal slot can watch more than one thing, and an outcome slot can pair a
# severity with how it tells you. The rest hold one block.
_MULTI_KINDS = ("signal", "outcome")


def _split_parts(kind: str, text: str) -> tuple[list[str], str]:
    """Blocks on one slot, and whether they are joined by and or or."""
    return split_joined_pieces(text, set(alarm_palette(kind)))


def _opens_editor(text: str) -> bool:
    """Click opens a box: a limit, a typed time, or Is flapping."""
    return (
        text in _PARAM_FOR
        or text == _TASMOTA_SIGNAL
        or text == "custom value"
        or text == FLAP_CHOICE
        or parse_flap(text) is not None
    )


def _piece_caption(text: str) -> str:
    if text == _TASMOTA_SIGNAL:
        return _tasmota_caption(text)
    spec = _PARAM_FOR.get(text)
    if spec is None:
        return text
    return spec.chip(_read_param(spec))


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


_TASMOTA_SIGNAL = "Tasmota device"
_QS_TASMOTA_IP = "alarms/tasmota_device_ip"


def _valid_ipv4(raw: str) -> str:
    parts = str(raw or "").strip().split(".")
    if len(parts) != 4:
        return ""
    nums = []
    for part in parts:
        if not part.isdigit():
            return ""
        number = int(part)
        if number > 255 or (len(part) > 1 and part.startswith("0")):
            return ""
        nums.append(str(number))
    return ".".join(nums)


def _tasmota_device_ip() -> str:
    return _valid_ipv4(str(_alarm_settings().value(_QS_TASMOTA_IP, "") or ""))


def _tasmota_caption(text: str) -> str:
    if text != _TASMOTA_SIGNAL:
        return text
    ip = _tasmota_device_ip()
    if not ip:
        return text
    return f"{text} ({ip})"


def _dialog_hint(text: str) -> QLabel:
    """Explanation that keeps its full height when the sentence wraps."""
    hint = QLabel(text)
    hint.setWordWrap(True)
    hint.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    hint.setStyleSheet("color: #cdd6f4; font-size: 12px; background: transparent;")
    return hint


def _fit_dialog_to_hint(dlg: QDialog, hint: QLabel) -> None:
    """Grow the dialog so a wrapped explanation is not clipped by the field below."""
    margins = dlg.layout().contentsMargins()
    width = max(380, dlg.minimumWidth() - margins.left() - margins.right())
    needed = hint.fontMetrics().boundingRect(
        0, 0, width, 2000,
        int(Qt.TextFlag.TextWordWrap),
        hint.text(),
    ).height() + 12
    hint.setMinimumHeight(needed)
    dlg.adjustSize()
    dlg.setMinimumHeight(dlg.sizeHint().height())


def _edit_tasmota_ip(parent) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Tasmota device")
    dlg.setMinimumWidth(420)
    lay = QVBoxLayout(dlg)
    hint = _dialog_hint(
        "IP address of the plug or current clamp. "
        "Once this is set, the Tasmota-device alarm watches this address only."
    )
    lay.addWidget(hint)
    edit = QLineEdit(_tasmota_device_ip())
    edit.setPlaceholderText("192.168.1.50")
    apply_setup_info_line_field_motif(edit, width=160)
    row = QHBoxLayout()
    row.addWidget(edit)
    row.addStretch(1)
    lay.addLayout(row)
    error = QLabel("")
    error.setStyleSheet("color: #f38ba8; font-size: 11px;")
    lay.addWidget(error)
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
    _fit_dialog_to_hint(dlg, hint)
    while True:
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        typed = edit.text().strip()
        ip = _valid_ipv4(typed)
        if typed and not ip:
            error.setText("Enter an IP address such as 192.168.1.50, or leave it blank.")
            continue
        settings = _alarm_settings()
        settings.setValue(_QS_TASMOTA_IP, ip)
        settings.sync()
        return True


def _edit_custom_duration(parent) -> str | None:
    """Ask for a length of time. Returns the chip phrase, or None if cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Custom value")
    dlg.setMinimumWidth(420)
    lay = QVBoxLayout(dlg)
    hint = _dialog_hint(
        "How long the condition must stay true before the alarm fires. "
        "Zero means it fires as soon as it is seen."
    )
    lay.addWidget(hint)
    spin = QSpinBox()
    spin.setRange(0, 1440)
    spin.setValue(1)
    apply_spin_field_motif(spin, width=120)
    unit = QComboBox()
    unit.addItem("minutes", 60)
    unit.addItem("seconds", 1)

    def _limit_custom_spin():
        if int(unit.currentData() or 1) == 60:
            spin.setRange(0, 1440)
        else:
            spin.setRange(0, 86400)

    unit.currentIndexChanged.connect(lambda _i: _limit_custom_spin())
    apply_combo_field_motif(unit, width=120)
    _limit_custom_spin()
    row = QHBoxLayout()
    row.addWidget(spin)
    row.addWidget(unit)
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
    _fit_dialog_to_hint(dlg, hint)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    scale = int(unit.currentData() or 1)
    return format_duration(float(spin.value()) * scale)


def _sentence_word(text: str) -> QLabel:
    word = QLabel(text)
    word.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    word.setStyleSheet("color: #cdd6f4; font-size: 13px; background: transparent;")
    return word


def _edit_flap(parent, current: FlapSpec | None = None) -> str | None:
    """Ask how often the line must be crossed. Returns the chip sentence."""
    spec = current or FlapSpec(times=3, window_min=10, dwell_s=5)
    dlg = QDialog(parent)
    dlg.setWindowTitle("Is flapping")
    dlg.setMinimumWidth(640)
    lay = QVBoxLayout(dlg)
    hint = _dialog_hint(
        "The alarm sounds when the line is crossed this often, "
        "instead of once and then staying there. A crossing only counts "
        "after it has stayed over the line for the seconds you set, "
        "and those crossings have to fall inside the minutes window."
    )
    lay.addWidget(hint)
    times = QSpinBox()
    times.setRange(1, 99)
    times.setValue(spec.times)
    apply_spin_field_motif(times, width=72)
    minutes = QSpinBox()
    minutes.setRange(1, 1440)
    minutes.setValue(spec.window_min)
    apply_spin_field_motif(minutes, width=72)
    seconds = QSpinBox()
    seconds.setRange(1, 3600)
    seconds.setValue(max(1, spec.dwell_s))
    apply_spin_field_motif(seconds, width=72)
    times_word = _sentence_word("times")
    minutes_word = _sentence_word("minutes")
    seconds_word = _sentence_word("seconds")

    def _plurals() -> None:
        times_word.setText("time" if times.value() == 1 else "times")
        minutes_word.setText("minute" if minutes.value() == 1 else "minutes")
        seconds_word.setText("second" if seconds.value() == 1 else "seconds")

    times.valueChanged.connect(lambda _v: _plurals())
    minutes.valueChanged.connect(lambda _v: _plurals())
    seconds.valueChanged.connect(lambda _v: _plurals())
    _plurals()
    seen = QHBoxLayout()
    seen.setSpacing(6)
    seen.addWidget(_sentence_word("Seen"))
    seen.addWidget(times)
    seen.addWidget(times_word)
    seen.addWidget(_sentence_word("in"))
    seen.addWidget(minutes)
    seen.addWidget(minutes_word)
    seen.addStretch(1)
    lay.addLayout(seen)
    crossed = QHBoxLayout()
    crossed.setSpacing(6)
    crossed.addWidget(_sentence_word("where the trigger threshold is exceeded for"))
    crossed.addWidget(seconds)
    crossed.addWidget(seconds_word)
    crossed.addStretch(1)
    lay.addLayout(crossed)
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
    _fit_dialog_to_hint(dlg, hint)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return FlapSpec(
        times=int(times.value()),
        window_min=int(minutes.value()),
        dwell_s=int(seconds.value()),
    ).phrase()


def _edit_param(parent, spec: _Param, dash) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle(spec.title)
    dlg.setMinimumWidth(420)
    lay = QVBoxLayout(dlg)
    hint = _dialog_hint(spec.hint)
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
    _fit_dialog_to_hint(dlg, hint)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False
    _write_param(spec, float(spin.value()), dash)
    return True


class _PaletteDelegate(QStyledItemDelegate):
    """Paints each palette row itself. A list stylesheet was hiding the colour."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._fill = QColor(_KIND_COLOR[kind])
        self._ink = QColor("#1e1e2e")
        self._type_ink = QColor(_ALARM_TYPE_INK)

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
        alarm_type = signal_alarm_type(text) if self._kind == "signal" else ""
        painter.setPen(self._ink)
        if alarm_type:
            name_rect = rect.adjusted(6, 1, -4, -(rect.height() // 2) + 1)
            painter.drawText(
                name_rect,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                shown,
            )
            small = QFont(option.font)
            small.setPointSizeF(max(6.0, option.font.pointSizeF() - 2.0))
            painter.setFont(small)
            painter.setPen(self._type_ink)
            painter.drawText(
                rect.adjusted(6, rect.height() // 2 - 1, -4, -1),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                alarm_type,
            )
        else:
            painter.drawText(
                rect.adjusted(6, 0, -4, 0),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                shown,
            )
        painter.restore()

    def sizeHint(self, _option, _index):
        return QSize(80, 32 if self._kind == "signal" else 20)


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
            f"Drag a {_KIND_WORD[kind]} into a slot of the same colour"
        )
        for text in alarm_palette(kind):
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, text)
            if kind == "signal" and signal_alarm_type(text):
                tip = f"{text}\nAlarm type: {signal_alarm_type(text)}"
            elif kind == "duration" and text == "is seen":
                tip = "As soon as it is seen. No wait."
            elif kind == "duration" and text == "custom value":
                tip = "Type your own length of time."
            elif kind == "duration" and text == FLAP_CHOICE:
                tip = (
                    "The line is crossed several times, instead of staying true. "
                    "Drop it to say how many times, in how many minutes, "
                    "and for how many seconds."
                )
            elif kind == "duration":
                tip = f"The condition must stay true for {text}."
            else:
                tip = text
            item.setToolTip(tip)
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


class _JoinChip(QFrame):
    """The AND / OR between two signals. Click it to swap.

    AND means both signals have to be true at once. OR means either one is
    enough.
    """

    def __init__(self, slot: "_Slot", word: str):
        super().__init__(slot)
        self._slot = slot
        self.setFixedHeight(_ROW_H - 8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(5, 0, 5, 0)
        label = QLabel(word.upper())
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        label.setStyleSheet(
            "color: #f5a524; font-size: 9px; font-weight: bold; background: transparent;"
        )
        lay.addWidget(label)
        self.setStyleSheet(
            "_JoinChip {"
            "  background: #2a2b3c;"
            "  border: 1px solid #f5a524;"
            "  border-radius: 3px;"
            "}"
        )
        other = "OR" if word == "and" else "AND"
        both = (
            "Both signals have to be true."
            if word == "and"
            else "Either signal is enough."
        )
        self.setToolTip(f"{both}\nClick to change it to {other}.")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            slot = self._slot
            QTimer.singleShot(0, slot.toggle_join)
            return
        super().mouseReleaseEvent(event)


class _SignalChip(QFrame):
    """One signal inside a rule that holds more than one."""

    def __init__(self, slot: "_Slot", index: int, text: str, colour: str = "#89b4fa"):
        super().__init__(slot)
        self._slot = slot
        self._index = index
        self._text = text
        self._colour = colour
        self._armed = False
        self.setAcceptDrops(True)
        self.setFixedHeight(_ROW_H - 4)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        label = QLabel(_piece_caption(text))
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        label.setStyleSheet("color: #1e1e2e; font-size: 11px; background: transparent;")
        lay.addWidget(label)
        self.setStyleSheet(
            f"_SignalChip {{ background: {colour}; border-radius: 3px; }}"
        )
        self.setToolTip("Double-click to remove this one.")
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._open_editor)

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
        self._click_timer.stop()
        rule = self._slot._rule()
        if rule is None:
            return
        mime = QMimeData()
        mime.setData(
            _MIME_SLOT,
            f"{rule.token}\n{self._slot.kind}\n{self._index}".encode("utf-8"),
        )
        drag = QDrag(self)
        drag.setMimeData(mime)
        chip = QLabel(_piece_caption(self._text))
        chip.setStyleSheet(
            f"QLabel {{ background: {self._colour}; color: #1e1e2e; border-radius: 3px; "
            "padding: 2px 8px; font-size: 11px; }}"
        )
        chip.adjustSize()
        drag.setPixmap(chip.grab())
        drag.setHotSpot(chip.rect().center())
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event):
        if self._armed and event.button() == Qt.MouseButton.LeftButton:
            self._armed = False
            if self._text == _TASMOTA_SIGNAL:
                self._click_timer.start(QApplication.doubleClickInterval())
            return
        self._armed = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._click_timer.stop()
        self._armed = False
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._index
            slot = self._slot
            QTimer.singleShot(0, lambda: slot.remove_at(index))
            return
        super().mouseDoubleClickEvent(event)

    def dragEnterEvent(self, event):
        self._slot.dragEnterEvent(event)

    def dragMoveEvent(self, event):
        self._slot.dragMoveEvent(event)

    def dropEvent(self, event):
        self._slot.dropEvent(event)

    def _open_editor(self) -> None:
        if self._text != _TASMOTA_SIGNAL:
            return
        tab = self._slot._tab()
        if tab is not None and _edit_tasmota_ip(tab):
            tab.refresh_param_chips()


class _Slot(QFrame):
    """One drop target on a rule line. Drag it to the bin, or click a number."""

    changed = Signal()

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._text = ""
        self._parts: list[str] = []
        self._join = "and"
        self._armed = False
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._open_editor)
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
        self._chip_host = QWidget()
        self._chip_row = QHBoxLayout(self._chip_host)
        self._chip_row.setContentsMargins(0, 0, 0, 0)
        self._chip_row.setSpacing(3)
        self._chip_host.hide()
        lay.addWidget(self._chip_host)
        self.set_piece("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._paint_caption()

    def text(self) -> str:
        return self._text

    @property
    def _multi(self) -> bool:
        return self.kind in _MULTI_KINDS

    def caption(self) -> str:
        if self._multi and self._parts:
            joiner = f" {self._join} "
            return joiner.join(_piece_caption(part) for part in self._parts)
        if not self._text:
            return ""
        return _piece_caption(self._text)

    def set_piece(self, text: str) -> None:
        raw = (text or "").strip()
        if self._multi:
            self._parts, self._join = _split_parts(self.kind, raw)
            self._text = f" {self._join} ".join(self._parts)
        else:
            self._parts = []
            self._text = raw
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
            if _opens_editor(self._text):
                lines.append("Click to change this.")
            lines.append("Double-click to remove it.")
            lines.append("Drag onto the bin to remove it.")
            lines.append("Right-click to empty this slot.")
            if self._multi:
                lines.append(
                    f"Drop another {_KIND_WORD[self.kind]} here to add it."
                )
                if self.kind == "signal" and len(self._parts) > 1:
                    lines.append("Click the joining word to swap and for or.")
            self.setToolTip("\n".join(lines))
        else:
            optional = self.kind not in ALARM_PIECE_REQUIRED
            self._body.setText("—" if optional else _KIND_WORD[self.kind])
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
                f"Drop a {_KIND_WORD[self.kind]} here."
                + (" Drop more than one." if self.kind == "signal" else "")
                + (" Optional." if optional else "")
            )
        self._show_signal_chips()

    def remove_at(self, index: int) -> None:
        if not self._multi or not (0 <= index < len(self._parts)):
            self.set_piece("")
        else:
            parts = list(self._parts)
            del parts[index]
            self.set_piece(f" {self._join} ".join(parts))
        self.changed.emit()

    def toggle_join(self) -> None:
        """Swap AND for OR between the signals on this slot."""
        if self.kind != "signal" or len(self._parts) < 2:
            return
        word = "or" if self._join == "and" else "and"
        self.set_piece(f" {word} ".join(self._parts))
        self.changed.emit()

    def _show_signal_chips(self) -> None:
        while self._chip_row.count():
            item = self._chip_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not self._multi or len(self._parts) < 2:
            self._chip_host.hide()
            self._body.show()
            return
        colour = _KIND_COLOR[self.kind]
        for index, part in enumerate(self._parts):
            if index:
                if self.kind == "signal":
                    self._chip_row.addWidget(_JoinChip(self, self._join))
                else:
                    word = QLabel("and")
                    word.setAttribute(
                        Qt.WidgetAttribute.WA_TransparentForMouseEvents, True,
                    )
                    word.setStyleSheet(
                        "color: #6c7086; font-size: 10px; background: transparent;"
                    )
                    self._chip_row.addWidget(word)
            self._chip_row.addWidget(_SignalChip(self, index, part, colour))
        self._chip_row.addStretch(1)
        self._body.hide()
        self._chip_host.show()
        self.setStyleSheet(
            "_Slot {"
            "  background: transparent;"
            f"  border: 1px dashed {colour};"
            "  border-radius: 3px;"
            "}"
        )
        short = _KIND_WORD[self.kind]
        lines = []
        if self.kind == "signal":
            lines.append(
                f"Joined by {self._join.upper()} — click that word to change it."
            )
        lines.append(f"Drop another {short} to add it.")
        lines.append("Double-click one to remove it.")
        lines.append("Drag one onto the bin to remove it.")
        self.setToolTip("\n".join(lines))

    def _paint_caption(self) -> None:
        if not self._text:
            return
        shown = QFontMetrics(self._body.font()).elidedText(
            self.caption(), Qt.TextElideMode.ElideRight, max(24, self._body.width()),
        )
        if shown != self._body.text():
            self._body.setText(shown)

    def mouseDoubleClickEvent(self, event):
        self._click_timer.stop()
        self._armed = False
        if event.button() != Qt.MouseButton.LeftButton or not self._text:
            return
        if self._multi and len(self._parts) > 1:
            return
        self.set_piece("")
        self.changed.emit()

    def _open_editor(self) -> None:
        if not self._text:
            return
        spec = _PARAM_FOR.get(self._text)
        tab = self._tab()
        edited = False
        if self._text == _TASMOTA_SIGNAL and tab is not None:
            edited = _edit_tasmota_ip(tab)
        elif spec is not None and tab is not None:
            edited = _edit_param(tab, spec, tab.dash)
        elif self._text == "custom value" and tab is not None:
            phrase = _edit_custom_duration(tab)
            if phrase:
                self.set_piece(phrase)
                self.changed.emit()
            return
        elif tab is not None and (
            self._text == FLAP_CHOICE or parse_flap(self._text) is not None
        ):
            phrase = _edit_flap(tab, parse_flap(self._text))
            if phrase:
                self.set_piece(phrase)
                self.changed.emit()
            return
        if edited and tab is not None:
            tab.refresh_param_chips()

    def _apply_flap_drop(self) -> None:
        """Dropping Is flapping asks for the three numbers before the chip changes."""
        tab = self._tab()
        if tab is None:
            return
        phrase = _edit_flap(tab, None)
        if not phrase:
            return
        self.set_piece(phrase)
        self.changed.emit()

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
            if _opens_editor(self._text):
                self._click_timer.start(QApplication.doubleClickInterval())
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
        if self._multi and self._parts:
            if text not in self._parts:
                joiner = f" {self._join} "
                self.set_piece(joiner.join(self._parts + [text]))
                self.changed.emit()
        else:
            if text == FLAP_CHOICE:
                QTimer.singleShot(0, self._apply_flap_drop)
            else:
                self.set_piece(text)
                self.changed.emit()
                if text == "custom value":
                    QTimer.singleShot(0, self._open_editor)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()


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
        token, kind, index = _decode_slot(event.mimeData())
        if token and kind:
            self._tab.clear_slot(token, kind, index)
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


def _inspect_chip(text: str, fill: str, ink: str = "#1e1e2e") -> QLabel:
    chip = QLabel(text)
    chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
    chip.setFixedWidth(118)
    chip.setStyleSheet(
        "QLabel {"
        f"  background-color: {fill};"
        f"  color: {ink};"
        "  font-size: 11px;"
        "  font-weight: bold;"
        "  padding: 2px 6px;"
        "  border-radius: 3px;"
        "}"
    )
    return chip


def _show_rule_inspection(parent, number: int, pieces: dict, captions: dict, monitor) -> None:
    """Which clauses of this rule are true on the last live check."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"Inspect rule {number}")
    dlg.setMinimumWidth(520)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(16, 14, 16, 12)
    lay.setSpacing(8)
    heading = QLabel(f"Rule {number}")
    heading.setStyleSheet("font-size: 15px; font-weight: bold; color: #cdd6f4;")
    lay.addWidget(heading)
    sentence = alarm_rule_syntax(captions or pieces)
    if sentence:
        line = QLabel(sentence)
        line.setWordWrap(True)
        line.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        lay.addWidget(line)

    missing = [k for k in ALARM_PIECE_REQUIRED if not str((pieces or {}).get(k) or "").strip()]
    key = None if missing else alarm_blocks_key(pieces)
    enabled = True if monitor is None else bool(getattr(monitor, "enabled", True))
    checked = None
    parts = None
    if key and monitor is not None and enabled and hasattr(monitor, "rule_inspection"):
        parts = monitor.rule_inspection(key)
        checked = monitor.inspection_at() if hasattr(monitor, "inspection_at") else None

    note = QLabel("")
    note.setWordWrap(True)
    note.setStyleSheet("color: #a6adc8; font-size: 12px;")
    lay.addWidget(note)

    rows = QVBoxLayout()
    rows.setSpacing(8)
    lay.addLayout(rows)

    def add_row(chip: QLabel, label: str, detail: str) -> None:
        block = QVBoxLayout()
        block.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
        name = QLabel(label)
        name.setWordWrap(True)
        name.setStyleSheet("color: #cdd6f4; font-size: 12px; font-weight: bold;")
        top.addWidget(name, 1)
        block.addLayout(top)
        if detail:
            body = QLabel(detail)
            body.setWordWrap(True)
            body.setStyleSheet("color: #a6adc8; font-size: 11px;")
            body.setContentsMargins(126, 0, 0, 0)
            block.addWidget(body)
        rows.addLayout(block)

    if missing:
        note.setText(_needs_text(missing) + " Nothing is being checked until the sentence is complete.")
    elif monitor is not None and not enabled:
        note.setText("Alarms are switched off, so nothing is being checked.")
    elif key and parts:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        when = ""
        if checked:
            clock = datetime.fromtimestamp(float(checked), ZoneInfo("Europe/London"))
            when = f" Last check at {clock.strftime('%H:%M:%S')}."
        note.setText("Triggering means that part is true right now." + when)
        for part in parts:
            if part.result:
                chip = _inspect_chip(
                    "Sounding" if part.on else "Not sounding",
                    "#f38ba8" if part.on else "#a6e3a1",
                )
            elif part.on:
                chip = _inspect_chip("Triggering", "#f38ba8")
            else:
                chip = _inspect_chip("Not triggering", "#313244", "#cdd6f4")
            add_row(chip, part.label, part.detail)
    elif key:
        note.setText(
            "This is one of the built-in alarms, but it has not been checked yet. "
            "A check runs when a live reading arrives, and about every 15 seconds."
        )
    else:
        note.setText(
            "This sentence is not one of the built-in alarms, so none of these "
            "parts is watched and the rule does not fire."
        )
        for kind in ("signal", "comparison", "threshold", "duration", "context"):
            text = str((captions or pieces or {}).get(kind) or "").strip()
            if not text:
                continue
            add_row(
                _inspect_chip("Not watched", "#45475a", "#cdd6f4"),
                f"{_KIND_SHORT[kind]}: {text}",
                "",
            )

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dlg.reject)
    close = buttons.button(QDialogButtonBox.StandardButton.Close)
    if close is not None:
        close.clicked.connect(dlg.accept)
    lay.addWidget(buttons)
    _prepare_dialog_buttons(dlg)
    dlg.exec()


class _RuleLine(QFrame):
    """One numbered alarm: a line of slots, and a halo when the sentence is whole."""

    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.token = f"r{id(self)}"
        self._complete = False
        self._unit_bad = False
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
        inspect = QPushButton("Inspect")
        inspect.setFixedSize(100, 26)
        inspect.setToolTip(
            "Show which parts of this rule are true on the last check, and which are not."
        )
        inspect.clicked.connect(self._inspect)
        row.addWidget(inspect)
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

    def _inspect(self) -> None:
        tab = self._tab()
        monitor = None
        if tab is not None:
            monitor = getattr(getattr(tab, "dash", None), "alarm_monitor", None)
        captions = {kind: slot.caption() for kind, slot in self.slots.items()}
        _show_rule_inspection(
            self.window(),
            int(self._number.text() or 0),
            self.values(),
            captions,
            monitor,
        )

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
        elif self._unit_bad:
            border = "1px solid #f38ba8"
            background = "#2a1a1e"
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
        problem = alarm_unit_problem(pieces)
        if problem:
            self._set_halo(False, bad=problem)
            self.setToolTip("Syntax incorrect. " + problem)
            return
        note = alarm_logic_note(pieces)
        self._set_halo(True, note=note)
        if alarm_blocks_key(pieces):
            self.setToolTip(sentence)
        else:
            tip = (
                sentence + "\nThe sentence is complete, but it is not one of the "
                "built-in alarms, so it does not fire."
            )
            if note:
                tip += "\nNon-standard logic: " + note
            self.setToolTip(tip)

    def _set_halo(self, on: bool, *, bad: str = "", note: str = "") -> None:
        self._unit_bad = bool(bad)
        self._complete = bool(on) and not bad
        self._syntax_note.setVisible(bool(on) or bool(bad))
        if bad:
            text, fill = "Syntax incorrect", "#f38ba8"
            self.setGraphicsEffect(None)
        elif note:
            text, fill = "Syntax Correct/Non-Standard Logic - please check", "#f9e2af"
        else:
            text, fill = "Syntax Correct", "#a6e3a1"
        self._syntax_note.setText(text)
        self._syntax_note.setToolTip(note)
        self._syntax_note.setStyleSheet(
            "QLabel {"
            "  color: #1e1e2e;"
            f"  background-color: {fill};"
            "  font-size: 10px;"
            "  font-weight: bold;"
            "  padding: 1px 8px;"
            "  border-radius: 3px;"
            "}"
        )
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

    def clear_slot(self, token: str, kind: str, index: int | None = None) -> None:
        card = self._card(token)
        if card is None:
            return
        slot = card.slots.get(kind)
        if slot is None or not slot.text():
            return
        if index is not None:
            QTimer.singleShot(0, lambda s=slot, i=index: s.remove_at(i))
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
        self._apply_rule_holds()

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
        self._apply_rule_holds()

    def _apply_rule_holds(self) -> None:
        """A How long choice on a built-in rule is how long that alarm waits."""
        dash = getattr(self, "dash", None)
        monitor = getattr(dash, "alarm_monitor", None) if dash is not None else None
        if monitor is None or not hasattr(monitor, "set_rule_holds"):
            return
        holds: dict[str, float] = {}
        flaps: dict[str, FlapSpec] = {}
        for card in self._cards:
            pieces = card.values()
            key = alarm_blocks_key(pieces)
            if not key:
                continue
            flap = parse_flap(pieces.get("duration", ""))
            if flap is not None:
                flaps[key] = flap
                continue
            seconds = duration_seconds(pieces.get("duration", ""))
            if seconds is not None:
                holds[key] = seconds
        monitor.set_rule_holds(holds)
        if hasattr(monitor, "set_rule_flaps"):
            monitor.set_rule_flaps(flaps)

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
