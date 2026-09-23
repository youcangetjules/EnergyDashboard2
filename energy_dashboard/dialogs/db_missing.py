"""Dialog: missing logger tables + dialect CREATE SQL for Setup & Info."""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.db.full_schema import TABLE_SUMMARIES, schema_script_for_tables
from energy_dashboard.ui.buttons import _apply_primary_button_style, _prepare_dialog_buttons


class DbMissingTablesDialog(QDialog):
    """Lists missing logger tables and shows CREATE SQL for those tables only."""

    def __init__(
        self,
        parent,
        *,
        engine: str,
        dialect: str,
        missing: list[str],
        connected: bool,
        error: str = "",
        grant_role: str = "",
    ):
        super().__init__(parent)
        self._sql = schema_script_for_tables(
            dialect, missing, grant_role=grant_role or None,
        )
        self.setWindowTitle(f"Missing tables — {engine}")
        self.setModal(True)
        self.resize(780, 560)
        self.setMinimumSize(560, 400)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        blurb = dict(TABLE_SUMMARIES)
        if error and not connected:
            head = (
                f"<p style='color:#fab387;'>Could not check which tables are "
                f"missing ({html.escape(error)}).</p>"
                f"<p>Showing CREATE SQL for <b>every</b> logger table so you "
                f"can still run the script by hand.</p>"
            )
        elif not missing:
            head = (
                "<p style='color:#a6e3a1; font-weight:700;'>"
                "No missing logger tables.</p>"
                "<p>Every expected table is already present.</p>"
            )
        else:
            n = len(missing)
            head = (
                f"<p><b>{n} missing table"
                f"{'s' if n != 1 else ''}</b> "
                f"(not created yet on {html.escape(engine)}):</p>"
            )
        self.header = QLabel(head)
        self.header.setWordWrap(True)
        self.header.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(self.header)

        if missing:
            lines = []
            for name in missing:
                tip = blurb.get(name) or ""
                if tip:
                    lines.append(f"• <code>{html.escape(name)}</code> — {html.escape(tip)}")
                else:
                    lines.append(f"• <code>{html.escape(name)}</code>")
            lst = QLabel("<br/>".join(lines))
            lst.setWordWrap(True)
            lst.setTextFormat(Qt.TextFormat.RichText)
            lst.setStyleSheet("color: #cdd6f4;")
            outer.addWidget(lst)

        sql_lbl = QLabel(
            f"<b>{html.escape(engine)} SQL</b> for the tables above "
            "(CREATE IF NOT EXISTS — existing tables keep their rows):"
        )
        sql_lbl.setWordWrap(True)
        sql_lbl.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(sql_lbl)

        self.sql_view = QTextEdit()
        self.sql_view.setReadOnly(True)
        self.sql_view.setPlainText(self._sql)
        self.sql_view.setStyleSheet(
            f"QTextEdit {{ background: {_DARK_BG}; color: {_DARK_TEXT}; "
            f"border: 1px solid {_DARK_GRID}; font-family: monospace; font-size: 11px; }}"
        )
        outer.addWidget(self.sql_view, 1)

        btns = QHBoxLayout()
        copy_btn = QPushButton("Copy SQL")
        copy_btn.setToolTip("Copy this CREATE script to the clipboard")
        copy_btn.clicked.connect(self._copy_sql)
        _apply_primary_button_style(copy_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        _apply_primary_button_style(close_btn)
        btns.addWidget(copy_btn)
        btns.addStretch(1)
        btns.addWidget(close_btn)
        outer.addLayout(btns)
        _prepare_dialog_buttons(self)

    def _copy_sql(self):
        QApplication.clipboard().setText(self._sql)
        self.header.setText(
            (self.header.text() or "")
            + "<p style='color:#a6e3a1;'>SQL copied to the clipboard.</p>"
        )
