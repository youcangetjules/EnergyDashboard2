"""Pipeline probe results dialog for the Connectivity tab."""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.connectivity.pipeline_probe import PipelineProbeReport


_STATE_LABEL = {
    "ok": "OK",
    "warn": "Degraded",
    "bad": "Break",
    "idle": "In progress",
    "off": "Not configured",
}


class PipelineProbeDialog(QDialog):
    """Show hop-by-hop Growatt pipeline probe results."""

    def __init__(self, report: PipelineProbeReport, parent=None):
        super().__init__(parent)
        self._report = report
        self.setWindowTitle("Growatt pipeline probe")
        self.setModal(True)
        self.resize(780, 520)
        self.setMinimumSize(640, 420)
        self.setStyleSheet(
            f"QDialog {{ background: {_DARK_SURFACE_BG}; }}"
            "QLabel, QTableWidget { color: #cdd6f4; }"
            "QGroupBox { color: #cdd6f4; border: 1px solid #313244; "
            "border-radius: 6px; margin-top: 8px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        summary_color = "#a6e3a1" if not report.breaks else "#f38ba8"
        if report.breaks and all(b.startswith("(degraded)") for b in report.breaks):
            summary_color = "#fab387"
        if not report.breaks:
            summary_head = "Pipeline continuity OK"
            summary_body = (
                f"All probed hops responded within {report.duration_s:.1f}s "
                f"(source: {html.escape(report.telemetry_source)})."
            )
        else:
            summary_head = "Breaks detected"
            summary_body = "<br>".join(
                f"• {html.escape(b)}" for b in report.breaks[:6]
            )
            if len(report.breaks) > 6:
                summary_body += f"<br>• … and {len(report.breaks) - 6} more"

        self.header_lbl = QLabel(
            f"<h3 style='margin:0;color:{summary_color};'>{html.escape(summary_head)}</h3>"
            f"<p style='margin:6px 0 0 0;color:#cdd6f4;'>{summary_body}</p>"
        )
        self.header_lbl.setTextFormat(Qt.RichText)
        self.header_lbl.setWordWrap(True)
        outer.addWidget(self.header_lbl)

        hops_box = QGroupBox("Hops (data producers & consumers)")
        hops_lay = QVBoxLayout(hops_box)
        self.hops_table = QTableWidget(len(report.hops), 3)
        self.hops_table.setHorizontalHeaderLabels(["Hop", "Status", "Details"])
        self.hops_table.verticalHeader().setVisible(False)
        self.hops_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hops_table.setAlternatingRowColors(True)
        self.hops_table.setSelectionMode(QAbstractItemView.NoSelection)
        for row, hop in enumerate(report.hops):
            self._set_row(self.hops_table, row, hop.label, hop.state, hop.detail)
        self.hops_table.horizontalHeader().setStretchLastSection(True)
        self.hops_table.resizeColumnsToContents()
        hops_lay.addWidget(self.hops_table)
        outer.addWidget(hops_box)

        links_box = QGroupBox("Links (continuity between hops)")
        links_lay = QVBoxLayout(links_box)
        self.links_table = QTableWidget(len(report.links), 3)
        self.links_table.setHorizontalHeaderLabels(["Link", "Status", "Details"])
        self.links_table.verticalHeader().setVisible(False)
        self.links_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.links_table.setAlternatingRowColors(True)
        self.links_table.setSelectionMode(QAbstractItemView.NoSelection)
        for row, link in enumerate(report.links):
            self._set_row(self.links_table, row, link.label, link.state, link.detail)
        self.links_table.horizontalHeader().setStretchLastSection(True)
        self.links_table.resizeColumnsToContents()
        links_lay.addWidget(self.links_table)
        outer.addWidget(links_box)

        footer = QLabel(
            f"Started {report.started_at.strftime('%H:%M:%S')} · "
            f"finished {report.finished_at.strftime('%H:%M:%S')} · "
            f"{report.duration_s:.1f}s total"
        )
        footer.setStyleSheet("color: #6c7086; font-size: 11px;")
        outer.addWidget(footer)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        close_btn = btns.button(QDialogButtonBox.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)
        outer.addWidget(btns)
        _prepare_dialog_buttons(self)

    def _set_row(self, table: QTableWidget, row: int, label: str, state: str, detail: str):
        colors = {
            "ok": "#a6e3a1",
            "warn": "#fab387",
            "bad": "#f38ba8",
            "idle": _UI_BLUE,
            "off": "#6c7086",
        }
        table.setItem(row, 0, QTableWidgetItem(label))
        st_item = QTableWidgetItem(_STATE_LABEL.get(state, state))
        st_item.setForeground(QBrush(QColor(colors.get(state, "#cdd6f4"))))
        table.setItem(row, 1, st_item)
        table.setItem(row, 2, QTableWidgetItem(detail))


__all__ = ["PipelineProbeDialog"]
