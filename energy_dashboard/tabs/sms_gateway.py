"""
Energy Dashboard — SMS gateway tab (Controls group).

Where live alarms send a text. The same settings used to sit under
Setup & Info → Live alarms. The keys in QSettings are unchanged, so a
number already saved there still works.
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.ui.styles import (
    apply_combo_field_motif,
    apply_setup_info_line_field_motif,
)

_QS_ORG, _QS_APP = "PowerModel", "EnergyDashboard2"


class SmsGatewayTab(QWidget):
    """Phone number and gateway used when an alarm sends an SMS."""

    def __init__(self, dash):
        super().__init__()
        self.dash = dash
        self._build_ui()
        self._load()

    def _settings(self) -> QSettings:
        return QSettings(_QS_ORG, _QS_APP)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        intro = QLabel(
            "This is where an alarm sends a text. It uses the same timing as "
            "the desktop pop-up, so it does not text on every refresh. "
            "A rule on <b>Alarm defs</b> can ask for a text, a desktop alert, "
            "or both. If the rule says nothing about that, the tick below and "
            "the desktop tick in Setup &amp; Info decide."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        root.addWidget(intro)

        self.chk_enabled = QCheckBox("Text alarms to this phone")
        self.chk_enabled.setToolTip(
            "When this is off, alarms do not send a text. "
            "Test SMS still sends one message, so you can check the gateway."
        )
        root.addWidget(self.chk_enabled)

        box = QGroupBox("Gateway")
        lay = QVBoxLayout(box)
        lay.setSpacing(6)

        self.ed_to = QLineEdit()
        self.ed_to.setPlaceholderText("+447700900123")
        self.ed_to.setToolTip("Mobile number in international form, starting with +")
        apply_setup_info_line_field_motif(self.ed_to, width=200)

        self.cb_provider = QComboBox()
        self.cb_provider.addItem("HTTP", "http")
        self.cb_provider.addItem("Twilio", "twilio")
        self.cb_provider.setToolTip(
            "HTTP posts JSON to your gateway address. Twilio uses Twilio's Messages API."
        )
        apply_combo_field_motif(self.cb_provider, width=120)
        self.cb_provider.currentIndexChanged.connect(self._show_provider_fields)

        self.ed_url = QLineEdit()
        self.ed_url.setPlaceholderText("https://…")
        self.ed_url.setToolTip(
            "HTTP only. We POST {\"to\", \"message\"} here. "
            "A token, if set, goes in Authorization: Bearer."
        )
        apply_setup_info_line_field_motif(self.ed_url, width=360, expand=True)

        self.ed_from = QLineEdit()
        self.ed_from.setPlaceholderText("+44…")
        self.ed_from.setToolTip("Twilio only: the number Twilio sends from")
        apply_setup_info_line_field_motif(self.ed_from, width=180)

        self.ed_sid = QLineEdit()
        self.ed_sid.setToolTip(
            "Twilio account SID. Leave blank to use SMS_TWILIO_SID from secrets.env."
        )
        apply_setup_info_line_field_motif(self.ed_sid, width=280, expand=True)

        self.ed_token = QLineEdit()
        self.ed_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_token.setToolTip(
            "Gateway token, or the Twilio auth token. "
            "Leave blank to use SMS_GATEWAY_TOKEN from secrets.env."
        )
        apply_setup_info_line_field_motif(self.ed_token, width=220)

        self._row_to = self._field_row("To:", self.ed_to)
        self._row_provider = self._field_row("Gateway:", self.cb_provider)
        self._row_url = self._field_row("URL:", self.ed_url)
        self._row_from = self._field_row("From:", self.ed_from)
        self._row_sid = self._field_row("Account SID:", self.ed_sid)
        self._row_token = self._field_row("Token:", self.ed_token)
        for row in (
            self._row_to, self._row_provider, self._row_url,
            self._row_from, self._row_sid, self._row_token,
        ):
            lay.addWidget(row)

        hint = QLabel(
            "HTTP posts <code>{\"to\", \"message\"}</code> to the URL. "
            "Twilio needs the From number and the account SID. "
            "The token can stay in secrets.env — leave the box blank and it is read from there."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        lay.addWidget(hint)
        root.addWidget(box)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        save_btn = QPushButton("Save")
        save_btn.setToolTip("Save the gateway and apply it to the next alarm text")
        save_btn.clicked.connect(self._save)
        test_btn = QPushButton("Test SMS")
        test_btn.setToolTip("Save these settings and send one test text")
        test_btn.clicked.connect(self._test)
        buttons.addWidget(save_btn)
        buttons.addWidget(test_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)
        root.addStretch(1)

    def _field_row(self, label: str, widget: QWidget) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lab = QLabel(label)
        lab.setFixedWidth(110)
        lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lab.setStyleSheet("color: #a6adc8; background: transparent;")
        row.addWidget(lab)
        row.addWidget(widget)
        row.addStretch(1)
        return host

    def _load(self) -> None:
        s = self._settings()
        self.chk_enabled.setChecked(s.value("alarms/sms_enabled", False, type=bool))
        self.ed_to.setText(str(s.value("alarms/sms_to", "") or ""))
        provider = str(s.value("alarms/sms_provider", "http") or "http")
        index = self.cb_provider.findData(provider)
        self.cb_provider.setCurrentIndex(index if index >= 0 else 0)
        self.ed_from.setText(str(s.value("alarms/sms_from", "") or ""))
        self.ed_url.setText(str(s.value("alarms/sms_url", "") or ""))
        self.ed_sid.setText(str(s.value("alarms/sms_sid", "") or ""))
        self.ed_token.setText(str(s.value("alarms/sms_token", "") or ""))
        self._show_provider_fields()

    def _show_provider_fields(self) -> None:
        http = (self.cb_provider.currentData() or "http") == "http"
        self._row_url.setVisible(http)
        self._row_from.setVisible(not http)
        self._row_sid.setVisible(not http)

    def _save(self) -> None:
        provider = self.cb_provider.currentData() or "http"
        s = self._settings()
        s.setValue("alarms/sms_enabled", self.chk_enabled.isChecked())
        s.setValue("alarms/sms_to", self.ed_to.text().strip())
        s.setValue("alarms/sms_provider", str(provider))
        s.setValue("alarms/sms_from", self.ed_from.text().strip())
        s.setValue("alarms/sms_url", self.ed_url.text().strip())
        s.setValue("alarms/sms_sid", self.ed_sid.text().strip())
        s.setValue("alarms/sms_token", self.ed_token.text())
        s.sync()
        if self.dash is not None:
            self.dash.set_status("SMS gateway saved.")

    def _test(self) -> None:
        import threading
        self._save()
        if self.dash is not None:
            self.dash.set_status("Sending a test SMS…")

        def work() -> None:
            from energy_dashboard.fetch.sms_gateway import load_sms_config, send_sms
            ok, detail = send_sms(
                load_sms_config(),
                "Energy Dashboard test. The SMS gateway is working.",
                force=True,
            )
            msg = "Test SMS sent." if ok else f"Test SMS failed: {detail}"
            if self.dash is not None:
                QTimer.singleShot(0, lambda m=msg: self.dash.set_status(m))

        threading.Thread(target=work, daemon=True).start()
