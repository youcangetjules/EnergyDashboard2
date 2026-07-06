"""
Energy Dashboard — `dialogs/about_history.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
class AboutDialog(QDialog):
    """Modal pop-up shown when the user clicks the 'About' button on the
    Setup & Info tab. Renders `_APP_ABOUT_TEXT` (HTML) in a read-only
    QTextBrowser so links remain clickable when real copy is supplied."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About PowerModel")
        self.resize(640, 480)
        lay = QVBoxLayout(self)
        try:
            from PySide6.QtWidgets import QTextBrowser
            body = QTextBrowser(self)
            body.setOpenExternalLinks(True)
        except Exception:
            body = QTextEdit(self)
            body.setReadOnly(True)
        body.setHtml(_APP_ABOUT_TEXT)
        lay.addWidget(body, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        lay.addWidget(btns)
        _prepare_dialog_buttons(self)


class HistoryDialog(QDialog):
    """Modal pop-up that renders `_APP_CHANGELOG` as a scrollable HTML
    list. Each entry shows the version, date and a bullet-list of
    changes; the newest patch sits at the top."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Version history — patch notes")
        self.resize(720, 600)
        lay = QVBoxLayout(self)

        header = QLabel(
            f"<div style='font-size:14px;'><b>PowerModel patch history</b> "
            f"&nbsp;·&nbsp; current build "
            f"<span style='color:#a6e3a1;'>v{APP_VERSION}</span></div>"
        )
        header.setTextFormat(Qt.RichText)
        lay.addWidget(header)

        try:
            from PySide6.QtWidgets import QTextBrowser
            body = QTextBrowser(self)
            body.setOpenExternalLinks(True)
        except Exception:
            body = QTextEdit(self)
            body.setReadOnly(True)

        parts = ["<div style='font-family:Segoe UI,Helvetica,sans-serif;'>"]
        for version, date, bullets in _APP_CHANGELOG:
            ver_color = "#a6e3a1" if version == APP_VERSION else "#89b4fa"
            parts.append(
                "<div style='margin:14px 0 4px 0;'>"
                f"<span style='font-size:13px; font-weight:bold; color:{ver_color};'>"
                f"v{version}</span>"
                f"<span style='color:#6c7086; margin-left:10px;'>{date}</span>"
                "</div>"
            )
            parts.append("<ul style='margin:4px 0 0 18px; padding:0;'>")
            for b in bullets:
                parts.append(f"<li style='margin:2px 0;'>{b}</li>")
            parts.append("</ul>")
        parts.append("</div>")
        body.setHtml("".join(parts))
        lay.addWidget(body, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        lay.addWidget(btns)
        _prepare_dialog_buttons(self)


class HelpDialog(QDialog):
    """Modal pop-up shown when the user clicks the global 'Help' button in
    the status bar. Renders the page-specific help string from
    ``_HELP_TEXTS`` (falling back to ``_HELP_DEFAULT``) inside a scrollable
    QTextBrowser so any inline links remain clickable."""

    def __init__(self, tab_class_name: str, tab_title: str = "", parent=None):
        super().__init__(parent)
        title = tab_title.strip() if tab_title else tab_class_name
        self.setWindowTitle(f"Help — {title}")
        self.resize(640, 520)
        lay = QVBoxLayout(self)
        try:
            from PySide6.QtWidgets import QTextBrowser
            body = QTextBrowser(self)
            body.setOpenExternalLinks(True)
        except Exception:
            body = QTextEdit(self)
            body.setReadOnly(True)
        body.setHtml(help_text_for(tab_class_name))
        lay.addWidget(body, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        lay.addWidget(btns)
        _prepare_dialog_buttons(self)


__all__ = [n for n in globals() if not n.startswith('__')]
