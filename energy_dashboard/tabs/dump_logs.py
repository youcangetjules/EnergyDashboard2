"""
Controls — dump logs.

Read-only view of ``~/.energy_dashboard_crash.log``: fatal-signal stacks
and the core-dump summaries copied in after a crash.
"""
from __future__ import annotations

import threading

from energy_dashboard.common import *
from energy_dashboard.core.crash_log import crash_log_path, import_new_coredumps

_TAIL_BYTES = 512_000


class DumpLogsTab(QWidget):
    """Standing crash and core-dump log. Does not clear the file."""

    def __init__(self, dash=None):
        super().__init__()
        self.dash = dash
        self._inv = Invoker(self)
        self._busy = False
        self.build_ui()
        self.reload()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("Dump logs")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #cdd6f4;")
        head.addWidget(title)
        head.addStretch(1)
        self.path_lbl = QLabel()
        self.path_lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
        self.path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        head.addWidget(self.path_lbl)
        self.fetch_btn = QPushButton("Look for new dumps")
        self.fetch_btn.setToolTip(
            "Ask the system for dashboard core dumps that are not in this "
            "log yet, then reload. This can take a few seconds."
        )
        self.fetch_btn.clicked.connect(self.look_for_new)
        head.addWidget(self.fetch_btn)
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.setFixedWidth(110)
        self.reload_btn.setToolTip("Re-read the crash log from disk")
        self.reload_btn.clicked.connect(self.reload)
        head.addWidget(self.reload_btn)
        layout.addLayout(head)

        self.hint = QLabel(
            "Fatal crashes (segmentation faults and the like) are written here "
            "because the Console cannot see a process that has already died. "
            "Newest text is at the bottom."
        )
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        layout.addWidget(self.hint)

        self.body = QTextEdit(self)
        self.body.setReadOnly(True)
        self.body.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        font = QFont("DejaVu Sans Mono")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        self.body.setFont(font)
        self.body.setStyleSheet(
            f"QTextEdit {{ background: {_DARK_BG}; color: #cdd6f4; "
            "border: 1px solid #313244; border-radius: 4px; }"
        )
        layout.addWidget(self.body, 1)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._busy:
            self.reload()

    def reload(self) -> None:
        path = crash_log_path()
        self.path_lbl.setText(str(path))
        try:
            size = path.stat().st_size
        except OSError:
            self.body.setPlainText(
                "No crash log yet.\n\n"
                f"When the dashboard dies with a fatal signal, the note is written to\n"
                f"{path}"
            )
            return
        try:
            with path.open("rb") as fh:
                if size > _TAIL_BYTES:
                    fh.seek(size - _TAIL_BYTES)
                    raw = fh.read()
                    # Drop a partial first line left by the seek.
                    nl = raw.find(b"\n")
                    if nl >= 0:
                        raw = raw[nl + 1 :]
                    note = (
                        f"Showing the newest {_TAIL_BYTES // 1000} KB "
                        f"of a {size // 1000} KB log.\n\n"
                    )
                else:
                    raw = fh.read()
                    note = ""
        except OSError as exc:
            self.body.setPlainText(f"Could not read the crash log.\n{exc}")
            return
        text = note + raw.decode("utf-8", errors="replace")
        self.body.setPlainText(text if text.strip() else "(crash log is empty)")
        cursor = self.body.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.body.setTextCursor(cursor)
        self.body.ensureCursorVisible()

    def look_for_new(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.fetch_btn.setEnabled(False)
        self.reload_btn.setEnabled(False)
        self.hint.setText("Looking for new core dumps…")

        def work():
            try:
                found = import_new_coredumps()
            except Exception as exc:
                found = exc
            self._inv.invoke(lambda: self._after_fetch(found))

        threading.Thread(target=work, name="dump-log-import", daemon=True).start()

    def _after_fetch(self, found) -> None:
        self._busy = False
        self.fetch_btn.setEnabled(True)
        self.reload_btn.setEnabled(True)
        self.hint.setText(
            "Fatal crashes (segmentation faults and the like) are written here "
            "because the Console cannot see a process that has already died. "
            "Newest text is at the bottom."
        )
        self.reload()
        if isinstance(found, Exception):
            self.set_status_line(f"Dump logs: could not check core dumps ({found}).")
            return
        n = len(found or [])
        if n:
            self.set_status_line(f"Dump logs: added {n} new core dump(s).")
        else:
            self.set_status_line("Dump logs: no new core dumps.")

    def set_status_line(self, text: str) -> None:
        dash = self.dash
        fn = getattr(dash, "set_status", None)
        if callable(fn):
            fn(text)


__all__ = ["DumpLogsTab"]
