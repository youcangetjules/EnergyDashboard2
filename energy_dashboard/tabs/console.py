"""
Energy Dashboard — `tabs/console.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.core.logging import LogManager, ensure_log_manager, get_log_manager


class ConsoleTab(QWidget):
    """Live console log viewer with per-level filtering (checkboxes, all on by default)."""

    _LEVEL_COLORS = {
        LogManager.DEBUG: "#6c7086",
        LogManager.INFO:  "#89b4fa",
        LogManager.WARN:  "#fab387",
        LogManager.ERROR: "#f38ba8",
    }

    _LEVEL_OPTIONS = (
        ("Debug", LogManager.DEBUG),
        ("Info", LogManager.INFO),
        ("Warn", LogManager.WARN),
        ("Error", LogManager.ERROR),
    )

    def __init__(self):
        super().__init__()
        ensure_log_manager()
        self._level_checks = {}
        self._auto_scroll = True
        self._rendered_visible_count = 0
        self.build_ui()
        get_log_manager()._new_entry.connect(self._on_new_entry)
        self._refresh()

    def build_ui(self):
        self.setStyleSheet(f"background-color: {_DARK_BG};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Show:"))
        for text, level in self._LEVEL_OPTIONS:
            cb = QCheckBox(text)
            cb.setChecked(True)
            cb.toggled.connect(self._on_filter_changed)
            self._level_checks[level] = cb
            toolbar.addWidget(cb)

        toolbar.addSpacing(20)
        self._auto_scroll_chk = QCheckBox("Auto-scroll")
        self._auto_scroll_chk.setChecked(True)
        self._auto_scroll_chk.toggled.connect(lambda v: setattr(self, '_auto_scroll', v))
        toolbar.addWidget(self._auto_scroll_chk)

        toolbar.addSpacing(10)
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(60)
        clear_btn.setToolTip(
            f"Clear the in-memory log AND wipe the persisted on-disk log at:\n"
            f"{_CONSOLE_LOG_PATH}"
        )
        clear_btn.clicked.connect(self._clear)
        toolbar.addWidget(clear_btn)

        toolbar.addSpacing(10)
        self._count_label = QLabel("0 entries")
        self._count_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        toolbar.addWidget(self._count_label)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setAcceptRichText(True)
        self._text.setFont(QFont('Courier', 9))
        self._text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        _apply_dark_log_view(self._text, object_name='consoleLogView')
        layout.addWidget(self._text)

    def _active_levels(self):
        return [
            level for level, cb in self._level_checks.items()
            if cb.isChecked()
        ]

    def _on_filter_changed(self, _checked=False):
        self._refresh()

    @staticmethod
    def _format_ts(entry):
        iso = entry.get('iso_ts')
        if iso:
            try:
                dt = datetime.fromisoformat(iso)
                if dt.date() == datetime.now().date():
                    return dt.strftime('%H:%M:%S.%f')[:-3]
                return dt.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                pass
        return entry.get('ts', '--:--:--.---')

    def _format_line(self, e):
        lvl = LogManager._LEVEL_LABELS.get(e["level"], "?")
        color = self._LEVEL_COLORS.get(e["level"], _DARK_TEXT)
        ts = html.escape(self._format_ts(e))
        src = html.escape(str(e.get("source", "")))
        msg = html.escape(str(e.get("msg", "")))
        msg = msg.replace("\n", "<br>")
        return (
            f'<span style="color:#585b70">{ts}</span> '
            f'<span style="color:{color};font-weight:bold">[{lvl}]</span> '
            f'<span style="color:#a6adc8">{src}:</span> '
            f'<span style="color:{color}">{msg}</span>'
        )

    def _append_log_html(self, line_html):
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(line_html + "<br>")
        self._text.setTextCursor(cursor)

    def _scroll_to_bottom(self):
        if self._auto_scroll:
            sb = self._text.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_new_entry(self):
        levels = self._active_levels()
        if not levels:
            self._text.clear()
            self._rendered_visible_count = 0
            self._count_label.setText("0 entries (all filters off)")
            return
        entries = get_log_manager().get_entries(levels=levels)
        if len(entries) <= self._rendered_visible_count:
            return
        for e in entries[self._rendered_visible_count:]:
            self._append_log_html(self._format_line(e))
        self._rendered_visible_count = len(entries)
        self._count_label.setText(f"{len(entries)} entries")
        self._scroll_to_bottom()

    def _refresh(self):
        levels = self._active_levels()
        if not levels:
            self._text.clear()
            self._rendered_visible_count = 0
            self._count_label.setText("0 entries (all filters off)")
            return
        entries = get_log_manager().get_entries(levels=levels)
        self._text.clear()
        if entries:
            self._text.setHtml("<br>".join(self._format_line(e) for e in entries))
        self._rendered_visible_count = len(entries)
        self._count_label.setText(f"{len(entries)} entries")
        self._scroll_to_bottom()

    def _clear(self):
        get_log_manager().clear_persisted()
        self._text.clear()
        self._rendered_visible_count = 0
        self._refresh()
        self._count_label.setText("0 entries")


__all__ = [n for n in globals() if not n.startswith('__')]
