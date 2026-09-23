"""
Energy Dashboard — Grott MQTT setup (Controls group).
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.config import (
    GROWATT_TELEMETRY_API,
    GROWATT_TELEMETRY_GROTT,
    GROWATT_TELEMETRY_HYBRID,
    growatt_uses_grott,
    read_grott_fill_missing_api,
    read_growatt_telemetry_source,
    write_growatt_telemetry_settings,
)
from energy_dashboard.fetch.grott_mqtt import test_grott_mqtt_connection

_QS_ORG, _QS_APP = "PowerModel", "EnergyDashboard2"


class GrottSetupTab(QWidget):
    """Configure Grott MQTT / Hybrid telemetry and show live feed health."""

    def __init__(self, dash):
        super().__init__()
        self.dash = dash
        self.set_status = dash.set_status
        self._inv = Invoker(self)
        self.on_data_updated = None
        self._build_ui()
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(5000)
        self._status_timer.timeout.connect(self.refresh_status)
        self.load_from_settings()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        intro = QLabel(
            "Configure how the dashboard receives live Growatt data from "
            "<b>Grott</b> over MQTT. The same settings are stored in "
            "<b>Setup &amp; Info → Growatt telemetry source</b>."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        root.addWidget(intro)

        live_box = QGroupBox("Live feed")
        live_lay = QVBoxLayout(live_box)
        self.lbl_live = QLabel("Loading…")
        self.lbl_live.setWordWrap(True)
        self.lbl_live.setTextFormat(Qt.TextFormat.RichText)
        # Do not set ``color`` here — a label stylesheet colour overrides HTML
        # ``<span style='color:…'>`` (so "connected · fresh" looked plain white).
        self.lbl_live.setStyleSheet(
            "padding: 8px; border: 1px solid #45475a; "
            "border-radius: 4px; background: transparent;"
        )
        live_lay.addWidget(self.lbl_live)
        root.addWidget(live_box)

        cfg_box = QGroupBox("Telemetry source")
        cfg_lay = QVBoxLayout(cfg_box)
        src_hint = QLabel(
            "<b>GROTT MQTT</b> is local only. <b>Hybrid</b> prefers Grott, then "
            "falls back to the Growatt cloud API when Grott is stale. "
            "<b>Fill missing</b> patches individual registers from the cloud "
            "without switching the whole source."
        )
        src_hint.setWordWrap(True)
        src_hint.setStyleSheet("color: #6c7086; font-size: 11px;")
        cfg_lay.addWidget(src_hint)

        self.rb_api = QRadioButton("Growatt Cloud API")
        self.rb_grott = QRadioButton("GROTT MQTT")
        self.rb_hybrid = QRadioButton("Hybrid (Grott → API fallback)")
        self._src_group = QButtonGroup(self)
        for rb in (self.rb_api, self.rb_grott, self.rb_hybrid):
            self._src_group.addButton(rb)
            rb.toggled.connect(self._on_source_toggled)
        src_row = QHBoxLayout()
        src_row.addWidget(self.rb_api)
        src_row.addWidget(self.rb_grott)
        src_row.addWidget(self.rb_hybrid)
        src_row.addStretch(1)
        cfg_lay.addLayout(src_row)

        self.chk_fill_missing = QCheckBox("Fill missing Grott data with API")
        self.chk_fill_missing.setToolTip(
            "While GROTT or Hybrid is selected, fetch Growatt cloud data in the "
            "background and patch only registers Grott did not publish."
        )
        cfg_lay.addWidget(self.chk_fill_missing)
        root.addWidget(cfg_box)

        mqtt_box = QGroupBox("MQTT broker")
        mqtt_grid = QGridLayout(mqtt_box)
        mqtt_grid.setHorizontalSpacing(12)
        mqtt_grid.setVerticalSpacing(8)

        self.ed_host = QLineEdit()
        self.ed_host.setPlaceholderText("e.g. 192.168.1.10")
        apply_setup_info_line_field_motif(self.ed_host, width=220, expand=True)
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1, 65535)
        self.sp_port.setValue(1883)
        apply_spin_field_motif(self.sp_port, width=_SPIN_FIELD_MOTIF_DB_W)
        self.ed_topic = QLineEdit()
        self.ed_topic.setPlaceholderText("energy/growatt")
        apply_setup_info_line_field_motif(self.ed_topic, width=220, expand=True)
        self.sp_fresh = QSpinBox()
        self.sp_fresh.setRange(15, 99999)
        self.sp_fresh.setSuffix(" s")
        self.sp_fresh.setToolTip(
            "Maximum age before Grott data is considered stale on Growatt Live."
        )
        apply_spin_field_motif(self.sp_fresh)
        self.ed_user = QLineEdit()
        apply_setup_info_line_field_motif(self.ed_user, width=160, expand=True)
        self.ed_pass = QLineEdit()
        self.ed_pass.setEchoMode(QLineEdit.EchoMode.Password)
        apply_setup_info_line_field_motif(self.ed_pass, width=160, expand=True)

        def _pair(row: int, label: str, w0, w1=None, label2: str = ""):
            mqtt_grid.addWidget(QLabel(label), row, 0)
            mqtt_grid.addWidget(w0, row, 1)
            if w1 is not None:
                mqtt_grid.addWidget(QLabel(label2), row, 2)
                mqtt_grid.addWidget(w1, row, 3)

        _pair(0, "Host:", self.ed_host, self.sp_port, "Port:")
        _pair(1, "Topic:", self.ed_topic, self.sp_fresh, "Fresh max:")
        _pair(2, "Username:", self.ed_user, self.ed_pass, "Password:")
        mqtt_grid.setColumnStretch(1, 1)
        mqtt_grid.setColumnStretch(3, 1)
        root.addWidget(mqtt_box)

        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("Save")
        self.btn_save.setToolTip("Save Grott settings and restart the MQTT subscriber")
        self.btn_save.clicked.connect(self.save_settings)
        _apply_primary_button_style(self.btn_save)
        self.btn_test = QPushButton("Test Grott MQTT")
        self.btn_test.setToolTip(
            "Check broker connect and subscribe. No JSON in ~6s is normal "
            "(Grott publishes on Shine packets, ~1 min heartbeat)."
        )
        self.btn_test.clicked.connect(self._test_mqtt)
        _apply_primary_button_style(self.btn_test)
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_test)
        btn_row.addStretch(1)
        self.lbl_saved = QLabel("")
        self.lbl_saved.setStyleSheet("color: #6c7086; font-size: 11px;")
        btn_row.addWidget(self.lbl_saved)
        root.addLayout(btn_row)
        root.addStretch(1)

        self._grott_fields = (
            self.ed_host, self.sp_port, self.ed_topic,
            self.ed_user, self.ed_pass, self.sp_fresh,
            self.chk_fill_missing,
        )

    def _on_source_toggled(self):
        uses = growatt_uses_grott(self._form_source())
        self.chk_fill_missing.setEnabled(uses)
        for w in self._grott_fields:
            if w is self.chk_fill_missing:
                continue
            w.setEnabled(uses)

    def _form_source(self) -> str:
        if self.rb_hybrid.isChecked():
            return GROWATT_TELEMETRY_HYBRID
        if self.rb_grott.isChecked():
            return GROWATT_TELEMETRY_GROTT
        return GROWATT_TELEMETRY_API

    def load_from_settings(self):
        p = self.dash.app_params
        s = QSettings(_QS_ORG, _QS_APP)
        src = read_growatt_telemetry_source(s, p)
        fill = read_grott_fill_missing_api(s, p)
        self.rb_api.setChecked(src == GROWATT_TELEMETRY_API)
        self.rb_grott.setChecked(src == GROWATT_TELEMETRY_GROTT)
        self.rb_hybrid.setChecked(src == GROWATT_TELEMETRY_HYBRID)
        self.chk_fill_missing.setChecked(bool(fill))
        self.ed_host.setText(str(s.value("params/grott_mqtt_host", p.grott_mqtt_host) or ""))
        self.sp_port.setValue(int(s.value("params/grott_mqtt_port", p.grott_mqtt_port) or 1883))
        self.ed_topic.setText(
            str(s.value("params/grott_mqtt_topic", p.grott_mqtt_topic) or "energy/growatt")
        )
        self.ed_user.setText(str(s.value("params/grott_mqtt_user", p.grott_mqtt_user) or ""))
        self.ed_pass.setText(str(s.value("params/grott_mqtt_password", p.grott_mqtt_password) or ""))
        self.sp_fresh.setValue(int(s.value("params/grott_mqtt_fresh_s", p.grott_mqtt_fresh_s) or 120))
        self._on_source_toggled()
        self.refresh_status()

    def _read_into_params(self):
        p = self.dash.app_params
        source = self._form_source()
        p.growatt_telemetry_source = source
        p.grott_mqtt_enabled = growatt_uses_grott(source)
        p.grott_fill_missing_api = (
            bool(self.chk_fill_missing.isChecked()) if growatt_uses_grott(source) else False
        )
        p.grott_mqtt_host = self.ed_host.text().strip()
        p.grott_mqtt_port = int(self.sp_port.value())
        p.grott_mqtt_user = self.ed_user.text().strip()
        p.grott_mqtt_password = self.ed_pass.text()
        p.grott_mqtt_topic = self.ed_topic.text().strip() or "energy/growatt"
        p.grott_mqtt_fresh_s = int(self.sp_fresh.value())

    def _write_settings(self):
        p = self.dash.app_params
        s = QSettings(_QS_ORG, _QS_APP)
        write_growatt_telemetry_settings(
            s, p.growatt_telemetry_source, fill_missing_api=p.grott_fill_missing_api,
        )
        s.setValue("params/grott_mqtt_host", p.grott_mqtt_host)
        s.setValue("params/grott_mqtt_port", int(p.grott_mqtt_port))
        s.setValue("params/grott_mqtt_user", p.grott_mqtt_user)
        s.setValue("params/grott_mqtt_password", p.grott_mqtt_password)
        s.setValue("params/grott_mqtt_topic", p.grott_mqtt_topic)
        s.setValue("params/grott_mqtt_fresh_s", int(p.grott_mqtt_fresh_s))
        s.sync()

    def _sync_parameters_tab(self):
        pt = getattr(self.dash, "parameters_tab", None)
        p = self.dash.app_params
        if pt is None:
            return
        try:
            pt.set_growatt_telemetry_source(
                p.growatt_telemetry_source,
                fill_missing=p.grott_fill_missing_api,
            )
        except Exception:
            pass
        for attr, widget in (
            ("grott_mqtt_host", "ed_grott_host"),
            ("grott_mqtt_port", "sp_grott_port"),
            ("grott_mqtt_topic", "ed_grott_topic"),
            ("grott_mqtt_user", "ed_grott_user"),
            ("grott_mqtt_password", "ed_grott_pass"),
            ("grott_mqtt_fresh_s", "sp_grott_fresh"),
        ):
            w = getattr(pt, widget, None)
            if w is None:
                continue
            val = getattr(p, attr)
            if hasattr(w, "setText"):
                w.setText(str(val or ""))
            elif hasattr(w, "setValue"):
                w.setValue(int(val))

    def save_settings(self):
        self._read_into_params()
        if growatt_uses_grott(self.dash.app_params.growatt_telemetry_source):
            if not self.dash.app_params.grott_mqtt_host:
                QMessageBox.information(
                    self, "Grott Setup", "Enter the MQTT broker host before saving.",
                )
                return
        self._write_settings()
        self._sync_parameters_tab()
        gt = getattr(self.dash, "growatt_tab", None)
        if gt is not None:
            try:
                gt.apply_grott_settings()
            except Exception:
                pass
        conn = getattr(self.dash, "connectivity_tab", None)
        if conn is not None:
            try:
                conn.refresh_status(test_db=False)
            except Exception:
                pass
        src = self.dash.app_params.growatt_telemetry_source
        self.lbl_saved.setText("Saved")
        self.set_status(f"Grott setup saved ({src}).")
        self.refresh_status()
        if self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception:
                pass

    def refresh_status(self):
        gt = getattr(self.dash, "growatt_tab", None)
        p = self.dash.app_params
        s = QSettings(_QS_ORG, _QS_APP)
        src = read_growatt_telemetry_source(s, p)
        if not growatt_uses_grott(src):
            self.lbl_live.setText(
                "<span style='color:#cdd6f4;'>"
                "<b>Source:</b> Growatt Cloud API — Grott MQTT is not selected."
                "</span>"
            )
            if self.on_data_updated:
                try:
                    self.on_data_updated()
                except Exception:
                    pass
            return
        gs = {}
        snap = None
        if gt is not None:
            try:
                gs = gt.grott_status() if hasattr(gt, "grott_status") else {}
            except Exception:
                gs = {}
            try:
                snap, _stale = gt._grott_display_snapshot(allow_stale=True)
            except Exception:
                snap = None
        connected = bool(gs.get("connected"))
        fresh = bool(gs.get("fresh"))
        age = gs.get("age_s")
        host = gs.get("host") or self.ed_host.text().strip() or "—"
        port = gs.get("port") or self.sp_port.value()
        topic = gs.get("topic") or self.ed_topic.text().strip() or "energy/growatt"
        serial = (snap or {}).get("serial") or gs.get("serial") or "—"
        if connected and fresh:
            state = (
                "<span style='color:#a6e3a1; font-weight:700;'>"
                "connected · fresh</span>"
            )
        elif connected:
            state = (
                "<span style='color:#fab387; font-weight:700;'>"
                "connected · stale</span>"
            )
        elif gs.get("enabled"):
            state = (
                "<span style='color:#f38ba8; font-weight:700;'>"
                "not connected</span>"
            )
        else:
            state = (
                "<span style='color:#6c7086; font-weight:700;'>"
                "subscriber stopped</span>"
            )
        age_bit = f"{float(age):.0f}s" if age is not None else "—"
        ignored_h = int(gs.get("ignored_historical") or 0)
        ignored_note = ""
        if ignored_h:
            ignored_note = (
                f"<br><b>Ignored:</b> {ignored_h} historical buffer dump(s) "
                "(not used as live)"
            )
        stale_note = ""
        if connected and not fresh:
            stale_note = (
                "<br><span style='color:#fab387;'>Shine often goes quiet for "
                "~11 minutes after it reconnects (commonly around the hour) "
                "while it handshakes with Growatt's servers. MQTT stays up; "
                "Hybrid uses the cloud until the next live Grott frame.</span>"
            )
        self.lbl_live.setText(
            f"<span style='color:#cdd6f4;'>"
            f"<b>Source:</b> {src} · {state}<br>"
            f"<b>Broker:</b> {host}:{port} · <b>Topic:</b> {topic}<br>"
            f"<b>Last live payload:</b> {age_bit} old · <b>Serial:</b> {serial}"
            f"{ignored_note}{stale_note}"
            f"</span>"
        )
        if self.on_data_updated:
            try:
                self.on_data_updated()
            except Exception:
                pass

    def showEvent(self, event):
        super().showEvent(event)
        self.load_from_settings()
        self._status_timer.start()

    def hideEvent(self, event):
        self._status_timer.stop()
        super().hideEvent(event)

    def _test_mqtt(self):
        self._read_into_params()
        host = self.dash.app_params.grott_mqtt_host
        if not host:
            QMessageBox.information(self, "Grott MQTT", "Enter the MQTT broker host first.")
            return
        self.btn_test.setEnabled(False)
        p = self.dash.app_params
        threading.Thread(
            target=self._test_mqtt_worker,
            args=(
                host,
                int(p.grott_mqtt_port),
                p.grott_mqtt_user,
                p.grott_mqtt_password,
                p.grott_mqtt_topic or "energy/growatt",
            ),
            daemon=True,
        ).start()

    def _test_mqtt_worker(self, host, port, user, password, topic):
        try:
            ok, msg = test_grott_mqtt_connection(
                host, port, username=user, password=password, topic=topic,
            )
        except Exception as exc:
            ok, msg = False, str(exc)
        self._inv.invoke(lambda o=ok, m=msg: self._finish_mqtt_test(o, m))

    def _finish_mqtt_test(self, ok: bool, msg: str):
        self.btn_test.setEnabled(True)
        title = "Grott MQTT test"
        if ok:
            QMessageBox.information(self, title, msg)
            self.set_status(f"Grott MQTT OK — {msg}")
        else:
            QMessageBox.warning(self, title, msg)
            self.set_status(f"Grott MQTT failed — {msg}")


__all__ = ["GrottSetupTab"]
