"""Hegel pod page. Hidden until Setup shows it. Reads the database only on the button."""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.hegel.models import chinnor_pod


class HegelTab(QWidget):
    """Community inventory. Does not search external sites."""

    def __init__(self, parent=None):
        super().__init__(parent)
        pod = chinnor_pod()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        title = QLabel("Hegel — Chinnor")
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #cdd6f4;")
        layout.addWidget(title)

        intro = QLabel(
            "This is the community inventory for a Hegel pod. "
            "It lives in a PostgreSQL database named hegel, "
            "separate from this house’s plant log. "
            "Nothing is searched, and the database is not opened, "
            "until you press Check inventory."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #cdd6f4;")
        layout.addWidget(intro)

        self.summary = QLabel(
            f"{pod.name}: a {pod.radius_km:g} km circle around "
            f"{pod.centre_lat:.3f}, {pod.centre_lon:.3f}. "
            f"{pod.locality_label} is the postcode district name, not a rooftop pin. "
            "Installed solar, storage, and what would still run in a power cut "
            "are not filled in until a source says so."
        )
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary.setStyleSheet("color: #a6adc8;")
        layout.addWidget(self.summary)

        self.status = QLabel("Inventory not checked.")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status.setStyleSheet("color: #cdd6f4;")
        layout.addWidget(self.status)

        row = QHBoxLayout()
        self.check_btn = QPushButton("Check inventory")
        self.check_btn.setToolTip(
            "Open the hegel database and count rows. Does not contact PVOutput or other sites."
        )
        self.check_btn.clicked.connect(self.check_inventory)
        row.addWidget(self.check_btn)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)

    def check_inventory(self):
        from energy_dashboard.hegel.repository import HegelDbError, inventory_snapshot

        self.status.setText("Checking the hegel database…")
        try:
            snap = inventory_snapshot()
        except HegelDbError as exc:
            self.status.setText(str(exc))
            return
        except Exception:
            self.status.setText("The hegel database could not be read.")
            return
        self.status.setText(snap.detail)


__all__ = [n for n in globals() if not n.startswith("__")]
