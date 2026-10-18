"""
Physical Plant — the MCS installation certificate for this house.

The file is kept on this computer. The panel count typed from it is the
installed plant. It is not used to scale live volts.
"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QDoubleSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from energy_dashboard.common import *
from energy_dashboard.core.invoker import Invoker
from energy_dashboard.ui.file_dialog import choose_open_file
from energy_dashboard.plant.mcs_certificate import (
    clear_certificate,
    load_record,
    save_record,
    store_upload,
    stored_path,
)
from energy_dashboard.plant.mcs_read import add_catalog_note, fill_record, interpret
from energy_dashboard.plant.panel_catalog import list_panels

_LABEL_W = 160


class McsCertificateTab(QWidget):
    """Upload and read the MCS certificate for this installation."""

    def __init__(self, status_callback=None, dash=None):
        super().__init__()
        self.set_status = status_callback
        self.dash = dash
        self.on_data_updated = None
        self._inv = Invoker(self)
        self._reading = False
        self._auto_read = False
        self._pdf = QPdfDocument(self)
        self.build_ui()
        self.reload()

    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        intro = QLabel(
            "The MCS certificate is the record of what was installed: "
            "the panels, the total power, and the installer. "
            "Upload the PDF or a photo. The app reads it and fills in the figures it prints. "
            "The copy stays on this computer. "
            "It is not a live reading, and it is not a multiplier on string voltage."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        root.addWidget(intro)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_upload = QPushButton("Upload certificate")
        self.btn_upload.setFixedWidth(160)
        self.btn_upload.setToolTip("Copy a PDF or a picture of the MCS certificate into this app.")
        self.btn_upload.clicked.connect(self._upload)
        self.btn_read = QPushButton("Read certificate")
        self.btn_read.setFixedWidth(160)
        self.btn_read.setToolTip(
            "Read the saved certificate and fill in the number, the panels, the kilowatts, the date, and the installer."
        )
        self.btn_read.clicked.connect(self._begin_read)
        self.btn_open = QPushButton("Open")
        self.btn_open.setFixedWidth(110)
        self.btn_open.setToolTip("Open the saved certificate in the usual viewer.")
        self.btn_open.clicked.connect(self._open_external)
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setFixedWidth(110)
        self.btn_remove.setToolTip("Remove the saved certificate file from this app.")
        self.btn_remove.clicked.connect(self._remove)
        for btn in (self.btn_upload, self.btn_read, self.btn_open, self.btn_remove):
            _apply_primary_button_style(btn)
            bar.addWidget(btn)
        bar.addStretch(1)
        root.addLayout(bar)

        self.lbl_file = QLabel("No certificate uploaded.")
        self.lbl_file.setWordWrap(True)
        self.lbl_file.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 12px;")
        root.addWidget(self.lbl_file)

        self.lbl_reading = QLabel("")
        self.lbl_reading.setWordWrap(True)
        self.lbl_reading.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_reading.setStyleSheet(
            "color: #cdd6f4; font-size: 12px; "
            "background: #181825; border: 1px solid #313244; border-radius: 6px; padding: 8px;"
        )
        self.lbl_reading.hide()
        root.addWidget(self.lbl_reading)

        form = QVBoxLayout()
        form.setSpacing(6)
        self.ed_number = QLineEdit()
        self.ed_number.setPlaceholderText("Certificate number")
        self.spin_panels = QSpinBox()
        self.spin_panels.setRange(0, 64)
        self.spin_panels.setSpecialValueText("—")
        self.spin_panels.setToolTip("Total panels printed on the certificate. 0 means not typed in yet.")
        apply_spin_field_motif(self.spin_panels, width=90)
        self.spin_kwp = QDoubleSpinBox()
        self.spin_kwp.setRange(0.0, 100.0)
        self.spin_kwp.setDecimals(2)
        self.spin_kwp.setSingleStep(0.01)
        self.spin_kwp.setSpecialValueText("—")
        self.spin_kwp.setToolTip("Installed kilowatts peak on the certificate.")
        apply_spin_field_motif(self.spin_kwp, width=110)
        self.ed_date = QLineEdit()
        self.ed_date.setPlaceholderText("YYYY-MM-DD")
        self.ed_installer = QLineEdit()
        self.ed_installer.setPlaceholderText("Installer")
        for edit in (self.ed_number, self.ed_date, self.ed_installer):
            edit.setMinimumWidth(280)
        rows = (
            ("Certificate number", self.ed_number),
            ("Total panels", self.spin_panels),
            ("Installed kWp", self.spin_kwp),
            ("Commissioned", self.ed_date),
            ("Installer", self.ed_installer),
        )
        for title, field in rows:
            form.addLayout(self._pair(title, field))
        save_row = QHBoxLayout()
        save_row.setContentsMargins(_LABEL_W + 12, 0, 0, 0)
        self.btn_save = QPushButton("Save details")
        self.btn_save.setFixedWidth(130)
        self.btn_save.setToolTip("Keep the figures. A read fills these from the certificate; you can still change them.")
        self.btn_save.clicked.connect(self._save_details)
        _apply_primary_button_style(self.btn_save)
        save_row.addWidget(self.btn_save)
        save_row.addStretch(1)
        form.addLayout(save_row)
        root.addLayout(form)

        self.stack = QStackedWidget()
        self.lbl_empty = QLabel("The certificate will show here after you upload it.")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setStyleSheet(f"color: {_DARK_SUBTEXT}; font-size: 13px;")
        self.stack.addWidget(self.lbl_empty)

        self.pic = QLabel()
        self.pic.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setWidget(self.pic)
        self.stack.addWidget(self.preview_scroll)

        self.pdf_view = QPdfView()
        self.pdf_view.setDocument(self._pdf)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.stack.addWidget(self.pdf_view)
        root.addWidget(self.stack, 1)

    def _pair(self, title: str, field: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        lab = QLabel(title)
        lab.setFixedWidth(_LABEL_W)
        lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lab.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        row.addWidget(lab)
        row.addWidget(field, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        return row

    def reload(self):
        rec = load_record()
        self.ed_number.setText(rec.get("number") or "")
        self.spin_panels.setValue(int(rec["panels"] or 0))
        self.spin_kwp.setValue(float(rec["kwp"] or 0.0))
        self.ed_date.setText(rec.get("commissioned") or "")
        self.ed_installer.setText(rec.get("installer") or "")
        reading = (rec.get("reading") or "").strip()
        self.lbl_reading.setVisible(bool(reading) or self._reading)
        if reading:
            self.lbl_reading.setText(reading)
        path = stored_path(rec)
        self.btn_read.setEnabled(path is not None and not self._reading)
        self.btn_open.setEnabled(path is not None)
        self.btn_remove.setEnabled(path is not None)
        if path is None:
            self.lbl_file.setText("No certificate uploaded.")
            self._pdf.close()
            self.stack.setCurrentWidget(self.lbl_empty)
            return
        self.lbl_file.setText(f"Saved copy of {rec.get('filename') or path.name}")
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            self._pdf.load(str(path))
            self.stack.setCurrentWidget(self.pdf_view)
        else:
            pix = QPixmap(str(path))
            if pix.isNull():
                self.lbl_file.setText(f"Saved {path.name}, but it could not be shown. Use Open.")
                self.stack.setCurrentWidget(self.lbl_empty)
            else:
                self.pic.setPixmap(pix)
                self.stack.setCurrentWidget(self.preview_scroll)

    def _details_from_form(self, rec: dict) -> dict:
        rec = dict(rec)
        rec["number"] = self.ed_number.text().strip()
        rec["panels"] = int(self.spin_panels.value()) or None
        rec["kwp"] = float(self.spin_kwp.value()) or None
        rec["commissioned"] = self.ed_date.text().strip()
        rec["installer"] = self.ed_installer.text().strip()
        return rec

    def _save_details(self):
        rec = self._details_from_form(load_record())
        save_record(rec)
        if self.set_status:
            self.set_status("MCS certificate details saved.")
        self._touch()

    def _upload(self):
        path = choose_open_file(
            self,
            "MCS certificate",
            str(Path.home()),
            "Certificate (*.pdf *.png *.jpg *.jpeg *.webp *.tif *.tiff)",
        )
        if not path:
            return
        try:
            rec = store_upload(Path(path))
        except ValueError as exc:
            QMessageBox.warning(self, "MCS certificate", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "MCS certificate", f"Could not keep that file.\n{exc}")
            return
        save_record(rec)
        self.reload()
        if self.set_status:
            self.set_status(f"MCS certificate kept: {Path(path).name}")
        self._touch()
        self._begin_read()

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_read or self._reading:
            return
        rec = load_record()
        if stored_path(rec) is None or (rec.get("reading") or "").strip():
            return
        self._auto_read = True
        self._begin_read()

    def _begin_read(self):
        path = stored_path()
        if path is None or self._reading:
            return
        self._reading = True
        self.btn_read.setEnabled(False)
        self.btn_upload.setEnabled(False)
        self.lbl_reading.setText("Reading the certificate…")
        self.lbl_reading.show()
        if self.set_status:
            self.set_status("Reading the MCS certificate…")

        def work():
            try:
                result = interpret(path, progress=self._progress)
            except Exception as exc:
                result = {
                    "ok": False,
                    "text": f"The certificate could not be read.\n{exc}",
                }
            self._inv.invoke(lambda found=result: self._finish_read(found))

        threading.Thread(target=work, daemon=True).start()

    def _progress(self, message: str):
        self._inv.invoke(lambda text=message: self._show_progress(text))

    def _show_progress(self, message: str):
        if self._reading:
            self.lbl_reading.setText(message)
            self.lbl_reading.show()

    def _finish_read(self, result: dict):
        self._reading = False
        self.btn_upload.setEnabled(True)
        result = add_catalog_note(result, list_panels())
        if result.get("ok"):
            rec = fill_record(load_record(), result)
            save_record(rec)
        else:
            rec = load_record()
            rec["reading"] = result.get("text") or "The certificate could not be read."
            save_record(rec)
        self.reload()
        if self.set_status:
            if result.get("ok"):
                self.set_status("MCS certificate read.")
            else:
                self.set_status("The certificate could not be interpreted.")
        self._touch()

    def _open_external(self):
        path = stored_path()
        if path is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _remove(self):
        if stored_path() is None:
            return
        answer = QMessageBox.question(
            self,
            "Remove certificate",
            "Remove the saved MCS certificate from this app? The original file you uploaded is left where it was.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        clear_certificate()
        self.reload()
        if self.set_status:
            self.set_status("MCS certificate removed from this app.")
        self._touch()

    def _touch(self):
        if self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception:
                pass


__all__ = ["McsCertificateTab"]
