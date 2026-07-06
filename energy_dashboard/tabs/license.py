"""
Energy Dashboard — `tabs/license.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
class LicenseTab(QWidget):
    """Static MIT license and terms-of-use notice."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        title = QLabel("License and terms of use")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #cdd6f4;")
        layout.addWidget(title)
        body = QTextBrowser(self)
        body.setOpenExternalLinks(True)
        body.setHtml(_LICENSE_TAB_HTML)
        body.setStyleSheet(
            f"QTextBrowser {{ background: {_DARK_SURFACE_BG}; color: #cdd6f4; "
            "border: 1px solid #313244; border-radius: 4px; }"
        )
        layout.addWidget(body, 1)


__all__ = [n for n in globals() if not n.startswith('__')]
