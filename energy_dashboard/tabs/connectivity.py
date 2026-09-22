"""
Energy Dashboard — `tabs/connectivity.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.db.health_stats import (
    KNOWN_TABLES,
    _fmt_size,
    _open_db,
    _relation_size_bytes,
    collect_health_stats,
)
from energy_dashboard.db.retention import format_policy_block, targets_for_box
from energy_dashboard.dialogs.component_login import build_component_login
from energy_dashboard.dialogs.data_retention import ConnectivityRetentionDialog
from energy_dashboard.ui.buttons import _prepare_dialog_buttons
from energy_dashboard.dialogs.pipeline_probe import PipelineProbeDialog
from energy_dashboard.connectivity.pipeline_probe import run_growatt_pipeline_probe
from energy_dashboard.config import (
    GROWATT_TELEMETRY_API,
    GROWATT_TELEMETRY_GROTT,
    GROWATT_TELEMETRY_HYBRID,
    growatt_uses_grott,
    read_growatt_telemetry_source,
    read_grott_fill_missing_api,
)


def _growatt_telemetry_info(gt, params):
    """Summarise Growatt source mode for Connectivity rows and diagram labels."""
    settings = QSettings("PowerModel", "EnergyDashboard2")
    source = read_growatt_telemetry_source(settings, params)
    if gt is not None and hasattr(gt, "_telemetry_source"):
        try:
            source = gt._telemetry_source()
        except Exception:
            pass
    fill_missing = read_grott_fill_missing_api(settings, params)
    if gt is not None and hasattr(gt, "_fill_missing_api_enabled"):
        try:
            fill_missing = gt._fill_missing_api_enabled()
        except Exception:
            pass
    gs = gt.grott_status() if gt is not None and hasattr(gt, "grott_status") else {}
    api_filled = getattr(gt, "_api_filled_fields", None) if gt is not None else None
    api_filled_fields = sorted(str(x) for x in (api_filled or ()))
    batteries = _growatt_battery_diagram_packs(gt, params)
    grott_fresh = bool(gs.get("fresh"))
    grott_running = bool(gs.get("enabled"))
    hybrid = source == GROWATT_TELEMETRY_HYBRID
    age_s = gs.get("age_s")
    try:
        age_s = float(age_s) if age_s is not None else None
    except (TypeError, ValueError):
        age_s = None
    fresh_s = 120.0
    if gt is not None and hasattr(gt, "_grott_config"):
        try:
            fresh_s = float(gt._grott_config().get("fresh_s", 120) or 120)
        except Exception:
            fresh_s = 120.0
    return {
        "source": source,
        "uses_grott": growatt_uses_grott(source),
        "hybrid": hybrid,
        "fill_missing": bool(fill_missing),
        "api_filled_count": len(api_filled_fields),
        "api_filled_fields": api_filled_fields,
        "grott_fresh": grott_fresh,
        "grott_connected": bool(gs.get("connected")),
        "grott_running": grott_running,
        "grott_age_s": age_s,
        "grott_fresh_s": fresh_s,
        "grott_disconnects": int(gs.get("disconnect_count") or 0),
        "grott_reconnects": int(gs.get("reconnect_count") or 0),
        "grott_last_event": str(gs.get("last_event") or ""),
        # Hybrid is degraded when Grott is selected but not delivering fresh data
        # — cloud API is carrying (or should be carrying) the live numbers.
        "hybrid_fallback": bool(
            hybrid and growatt_uses_grott(source) and (not grott_fresh)
        ),
        "batteries": batteries,
        "battery_count": len(batteries),
    }


def _growatt_battery_diagram_packs(gt, params) -> list[dict]:
    """Pack slots for the architecture diagram (count + SN + alert hint)."""
    try:
        status = getattr(gt, "mix_status_data", None) if gt is not None else None
        info = getattr(gt, "mix_info_data", None) if gt is not None else None
        devices = getattr(gt, "_plant_devices", None) if gt is not None else None
        modbus_sns = list(getattr(gt, "_modbus_pack_serials", None) or []) if gt is not None else []
        modbus_detail = (
            getattr(gt, "_modbus_pack_serials_detail", "") or ""
        ) if gt is not None else ""

        collected = _growatt_collect_battery_serials(
            devices=devices,
            status=status if isinstance(status, dict) else None,
            info=info if isinstance(info, dict) else None,
            modbus_sns=modbus_sns,
            modbus_detail=modbus_detail,
        )
        sns = list(collected.get("serials") or [])

        override = _growatt_battery_modules_override()
        equip = getattr(gt, "_battery_equipage", None) if gt is not None else None
        if not isinstance(equip, dict) or not equip:
            equip = _growatt_detect_battery_equipage(
                devices=devices,
                status=status if isinstance(status, dict) else None,
                info=info if isinstance(info, dict) else None,
                app_params=params,
                modbus_modules=getattr(gt, "_modbus_modules", None) if gt is not None else None,
                modbus_detail=getattr(gt, "_modbus_modules_detail", "") or "",
                modbus_serials=modbus_sns,
            )

        n = None
        if override is not None:
            n = int(override)
        elif equip.get("modules") is not None:
            n = int(equip["modules"])
        elif sns:
            n = len(sns)
        elif equip.get("setup_modules"):
            n = int(equip["setup_modules"])
        else:
            n = 1
        n = max(1, min(int(n), 8))

        alerts = _growatt_decode_inverter_alerts(
            status if isinstance(status, dict) else None,
            info if isinstance(info, dict) else None,
        )
        bus_ok = int(equip.get("bus_count") or 0) >= 1
        packs = []
        for i in range(n):
            sn = sns[i] if i < len(sns) else ""
            if alerts.get("has_fault"):
                alert = "fault"
            elif alerts.get("has_warning"):
                alert = "warn"
            elif not sn:
                alert = "warn" if bus_ok or n > 1 else "off"
            else:
                alert = "ok"
            packs.append({
                "index": i + 1,
                "sn": sn,
                "alert": alert,
                "alerts_summary": alerts.get("summary") or "",
                "alerts_detail": alerts.get("detail") or "",
            })
        return packs
    except Exception:
        return [{"index": 1, "sn": "", "alert": "off"}]


def _growatt_source_label(source: str) -> str:
    if source == GROWATT_TELEMETRY_HYBRID:
        return "Hybrid (Grott → API fallback)"
    if source == GROWATT_TELEMETRY_GROTT:
        return "GROTT MQTT"
    return "Growatt Cloud API"


# Logged import tables → diagram box keys that should show their DB volumes.
_IMPORT_TABLE_META = (
    ("growatt_readings", "Growatt readings", ("growatt_cloud", "grott", "emqx", "modbus")),
    ("growatt_mix_chart", "Growatt MIX chart", ("growatt_cloud", "grott")),
    ("octopus_readings", "Octopus half-hour readings", ("octopus",)),
    ("tasmota_readings", "Tasmota readings", ("tasmota", "emqx")),
    ("tasmota_devices", "Tasmota devices", ("tasmota",)),
    ("solar_forecast_snapshots", "Solar forecast snapshots", ("forecast",)),
    ("agile_price_snapshots", "Agile price snapshots", ("forecast",)),
    ("agile_year_daily", "Agile Year daily stats", ("forecast",)),
    ("pv_string_charge", "PV string charge estimates", ("growatt_cloud", "grott")),
)

_CONNECTIVITY_BOX_SERVICES = {
    "growatt_cloud": ("Growatt API", ("Growatt server", "Inverter write (this app)")),
    "grott": ("GROTT / Hybrid", ("Growatt local (Grott MQTT)",)),
    "octopus": ("Octopus", ("Octopus historic", "Octopus live")),
    "forecast": ("PV forecast", ("Forecast.solar",)),
    "modbus": ("Modbus", ("Growatt local (Modbus)",)),
    "modbus_lan": ("Modbus", ("Growatt local (Modbus)",)),
    "tasmota": ("Tasmota", ("Tasmota devices",)),
    "emqx": ("EMQX", ("Growatt local (Grott MQTT)", "Growatt local (Modbus)", "Tasmota devices")),
    "database": ("Databases", ("Databases",)),
    "export": ("Exported data", ("Databases",)),
    "storage": ("Databases & Exports", ("Databases",)),
    "pvoutput": ("PVOutput.org", ()),
    "wonderwatt": ("Wonderwatt.com", ()),
    "dashboard": ("Energy Dashboard", ()),
    "battery": ("Battery pack", ()),
    "inverter": ("Growatt Inverter", ()),
}

# Status-table row label → diagram health key (also defined in command_sim for
# shared tooling; keep a local copy so Connectivity never depends on Modbus).
_CONNECTIVITY_ROW_TO_HEALTH = {
    "Growatt server": "growatt_cloud",
    "Growatt local (Grott MQTT)": "grott",
    "Growatt local (ShineLan)": "wifi_direct",
    "Growatt local (Modbus)": "modbus",
    "Octopus historic": "octopus_hist",
    "Octopus live": "octopus_live",
    "Tasmota devices": "tasmota",
    "Forecast.solar": "forecast",
    "PVOutput.org": "pvoutput",
    "Wonderwatt.com": "wonderwatt",
    "Databases": "database",
}

# Stable keys for State-column context menu (disable / highlight / history).
# highlight_edges: exact (from, to) pairs on the architecture diagram — never
# "any link that touches dashboard", or selecting one row lights the whole graph.
def _edges(*pairs: tuple[str, str]) -> frozenset[tuple[str, str]]:
    return frozenset(pairs)


# Live AlarmMonitor keys → diagram boxes / edges (so alarms are visible on the
# architecture view, not only the top banner / tray).
_ALARM_DIAGRAM_MAP: dict[str, dict] = {
    "grott_lost": {
        "boxes": ("grott", "emqx", "inverter"),
        "edges": (
            ("inverter", "grott"),
            ("grott", "inverter"),
            ("grott", "emqx"),
            ("emqx", "grott"),
            ("emqx", "dashboard"),
            ("dashboard", "emqx"),
        ),
        "batteries": False,
    },
    "low_soc": {
        "boxes": ("inverter",),
        "edges": (),
        "batteries": True,
    },
    "sun_wasted": {
        "boxes": ("inverter", "growatt_cloud", "grott"),
        "edges": (
            ("inverter", "growatt_cloud"),
            ("growatt_cloud", "inverter"),
            ("inverter", "grott"),
            ("grott", "inverter"),
        ),
        "batteries": True,
    },
    "load_eats_pv": {
        "boxes": ("inverter",),
        "edges": (("inverter", "growatt_cloud"), ("inverter", "grott")),
        "batteries": False,
    },
    "db_disconnected": {
        "boxes": ("storage",),
        "edges": (
            ("dashboard", "storage"),
            ("storage", "dashboard"),
        ),
        "batteries": False,
    },
    "db_ingest_stale": {
        "boxes": ("storage", "dashboard"),
        "edges": (
            ("dashboard", "storage"),
            ("storage", "dashboard"),
        ),
        "batteries": False,
    },
    "inverter_comms_lost": {
        "boxes": ("inverter", "growatt_cloud"),
        "edges": (
            ("inverter", "growatt_cloud"),
            ("growatt_cloud", "inverter"),
            ("inverter", "grott"),
        ),
        "batteries": False,
    },
    "tasmota_mqtt_lost": {
        "boxes": ("tasmota", "emqx"),
        "edges": (
            ("tasmota", "emqx"),
            ("emqx", "tasmota"),
            ("emqx", "dashboard"),
        ),
        "batteries": False,
    },
    "tasmota_offline": {
        "boxes": ("tasmota",),
        "edges": (("tasmota", "emqx"), ("emqx", "tasmota")),
        "batteries": False,
    },
}


def _alarm_severity_to_sk(severity: str) -> str:
    return "bad" if str(severity).lower() in ("critical", "bad", "fault") else "warn"


_SERVICE_ROW_META = {
    "Growatt server": {
        "key": "growatt_server",
        "can_disable": True,
        "can_show_alarms": True,
        "can_downtime": True,
        "highlight_edges": _edges(
            ("inverter", "growatt_cloud"),
            ("growatt_cloud", "dashboard"),
            ("dashboard", "growatt_cloud"),
            ("growatt_cloud", "inverter"),
        ),
    },
    "Growatt local (Grott MQTT)": {
        "key": "grott_mqtt",
        "can_disable": True,
        "can_show_alarms": True,
        "can_downtime": True,
        "highlight_edges": _edges(
            ("inverter", "grott"),
            ("grott", "emqx"),
            ("emqx", "dashboard"),
            ("dashboard", "emqx"),
            ("emqx", "grott"),
            ("grott", "inverter"),
        ),
    },
    "Growatt local (ShineLan)": {
        "key": "shinelan",
        "can_disable": True,
        "can_show_alarms": False,
        "can_downtime": False,
        "highlight_edges": frozenset(),
        "highlight_note": "ShineLan is Setup diagnostics only — not drawn on the architecture diagram.",
    },
    "Growatt local (Modbus)": {
        "key": "modbus",
        "can_disable": True,
        "can_show_alarms": True,
        "can_downtime": True,
        "highlight_edges": _edges(
            ("inverter", "modbus"),
            ("modbus", "emqx"),
            ("modbus", "dashboard"),
            ("dashboard", "modbus"),
            ("modbus", "inverter"),
        ),
    },
    "Inverter write (this app)": {
        "key": "inverter_write",
        # Dedicated Enable/Disable Modbus writes — not a mute toggle.
        "can_disable": False,
        "can_show_alarms": False,
        "can_downtime": False,
        "highlight_edges": _edges(
            ("dashboard", "growatt_cloud"),
            ("growatt_cloud", "inverter"),
            ("dashboard", "modbus"),
            ("modbus", "inverter"),
        ),
    },
    "Octopus historic": {
        "key": "octopus_historic",
        "can_disable": True,
        "can_test": True,
        "can_downtime": True,
        "can_show_alarms": True,
        "highlight_edges": _edges(("octopus", "dashboard")),
    },
    "Octopus live": {
        "key": "octopus_live",
        "can_disable": True,
        "can_test": True,
        "can_downtime": True,
        "can_show_alarms": True,
        "highlight_edges": _edges(("octopus", "dashboard")),
    },
    "Tasmota devices": {
        "key": "tasmota",
        "can_disable": True,
        "can_show_alarms": True,
        "can_downtime": True,
        "goto_tab_attr": "tasmota_tab",
        "goto_tab_label": "Go to Tasmota Tab",
        "highlight_edges": _edges(
            ("tasmota", "emqx"),
            ("emqx", "tasmota"),
            ("emqx", "dashboard"),
            ("dashboard", "emqx"),
        ),
    },
    "Forecast.solar": {
        "key": "forecast",
        "can_disable": True,
        "can_test": True,
        "can_downtime": True,
        "can_show_alarms": True,
        "highlight_edges": _edges(("forecast", "dashboard")),
    },
    "PVOutput.org": {
        "key": "pvoutput",
        "can_disable": True,
        "can_test": True,
        "can_downtime": True,
        "can_show_alarms": True,
        "highlight_edges": _edges(("dashboard", "pvoutput")),
    },
    "Wonderwatt.com": {
        "key": "wonderwatt",
        "can_disable": True,
        "can_test": True,
        "can_downtime": True,
        "can_show_alarms": True,
        "highlight_edges": _edges(("dashboard", "wonderwatt")),
    },
    "Databases": {
        "key": "databases",
        # Backends are configured in Setup — muting the row is not appropriate.
        "can_disable": False,
        "can_test": True,
        "can_downtime": True,
        "can_show_alarms": True,
        "highlight_edges": _edges(
            ("dashboard", "storage"),
            ("storage", "dashboard"),
            ("ai", "storage"),
            ("storage", "ai"),
        ),
    },
}

_DISABLED_QS_PREFIX = "connectivity/row_disabled/"


class _ConnectivityDetailDialog(QDialog):
    _CONTENT_WIDTH = 440
    _CONTENT_PAD = 24
    # Login popups (Growatt API, Grott, EMQX, …) need room for wide credential fields.
    _LOGIN_DIALOG_W = 1200
    _LOGIN_TEXT_W = 1160

    def __init__(self, title, body, parent=None, *, login=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        wide = login is not None
        self.setMinimumWidth(self._LOGIN_DIALOG_W if wide else 480)
        if wide:
            self.resize(self._LOGIN_DIALOG_W, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setFont(QFont("Helvetica", 10))
        te.setFrameShape(QFrame.Shape.NoFrame)
        te.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        te.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Body may include light HTML (<b>, &amp;); render as rich text.
        te.setHtml(self._body_to_html(body))
        doc = te.document()
        doc.setTextWidth(float(self._CONTENT_WIDTH))
        doc_h = int(doc.size().height())
        te_h = max(120, doc_h + self._CONTENT_PAD)
        screen = QApplication.primaryScreen()
        if screen is not None:
            max_h = int(screen.availableGeometry().height() * 0.88) - 90
            if wide:
                # Leave room for the login block under the status text.
                max_h = min(max_h, 220)
            if te_h > max_h:
                te_h = max_h
                te.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            else:
                te.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        else:
            te.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        text_w = self._LOGIN_TEXT_W if wide else self._CONTENT_WIDTH
        if wide:
            doc.setTextWidth(float(text_w))
        te.setMinimumWidth(text_w + 8)
        te.setFixedHeight(te_h)
        te.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if login is None:
            layout.addWidget(te, 0, Qt.AlignmentFlag.AlignLeft)
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            inner = QWidget()
            inner_lay = QVBoxLayout(inner)
            inner_lay.setContentsMargins(0, 0, 0, 0)
            inner_lay.setSpacing(10)
            inner_lay.addWidget(te)
            inner_lay.addWidget(login)
            inner_lay.addStretch(1)
            scroll.setWidget(inner)
            screen_h = 640
            if screen is not None:
                screen_h = int(screen.availableGeometry().height() * 0.72)
            scroll.setMinimumHeight(min(360, screen_h))
            scroll.setMaximumHeight(screen_h)
            layout.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)
        layout.addWidget(buttons)
        _prepare_dialog_buttons(self)
        self.adjustSize()
        if wide:
            # adjustSize can shrink below the credential layout; keep the floor.
            self.setMinimumWidth(self._LOGIN_DIALOG_W)
            if self.width() < self._LOGIN_DIALOG_W:
                self.resize(self._LOGIN_DIALOG_W, max(self.height(), 560))

    @staticmethod
    def _body_to_html(body: str) -> str:
        """Turn detail text (plain paragraphs + optional HTML tags) into HTML."""
        text = (body or "").strip()
        if not text:
            return ""
        paras = []
        for part in text.split("\n\n"):
            part = part.replace("\n", "<br>")
            paras.append(f"<p style='margin:0 0 10px 0;'>{part}</p>")
        return (
            "<div style='font-family: Helvetica, Arial, sans-serif; "
            "font-size: 10pt; color: #cdd6f4;'>"
            + "".join(paras)
            + "</div>"
        )


class _WonderwattShareDialog(QDialog):
    """Connectivity click-through: status + editable Advanced share link."""

    def __init__(self, title: str, body: str, parent=None, *, dash=None):
        super().__init__(parent)
        self._dash = dash
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        te = QTextEdit()
        te.setReadOnly(True)
        te.setFont(QFont("Helvetica", 10))
        te.setFrameShape(QFrame.Shape.NoFrame)
        te.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        te.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        te.setHtml(_ConnectivityDetailDialog._body_to_html(body))
        doc = te.document()
        doc.setTextWidth(440.0)
        te.setFixedHeight(max(110, int(doc.size().height()) + 20))
        te.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(te)

        from energy_dashboard.fetch.wonderwatt import load_wonderwatt_share_url

        link_lbl = QLabel("Advanced share link")
        link_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
        layout.addWidget(link_lbl)

        self.ed_share = QLineEdit(load_wonderwatt_share_url())
        self.ed_share.setPlaceholderText(
            "https://app.wonderwatt.com/?wattid=…&sig=…&time=…"
        )
        self.ed_share.setClearButtonEnabled(True)
        layout.addWidget(self.ed_share)

        hint = QLabel(
            "Paste the full share URL from Wonderwatt Advanced "
            "(needs <code>wattid</code>, <code>sig</code>, and <code>time</code>). "
            "Saved locally — same field as Setup &amp; Info / Potential Issues."
        )
        hint.setWordWrap(True)
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setStyleSheet("color: #6c7086; font-size: 10px;")
        layout.addWidget(hint)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color: #a6adc8; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        save_btn = QPushButton("Save")
        save_btn.setFixedWidth(110)
        save_btn.clicked.connect(self._save)
        test_btn = QPushButton("Test link")
        test_btn.setFixedWidth(110)
        test_btn.clicked.connect(self._test)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(test_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(110)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        self.adjustSize()

    def _sync_other_fields(self, url: str) -> None:
        dash = self._dash
        if dash is None:
            return
        pot = getattr(dash, "pot_issues_tab", None)
        if pot is not None and hasattr(pot, "ww_url"):
            pot.ww_url.setText(url)
        params = getattr(dash, "parameters_tab", None)
        if params is not None and hasattr(params, "ed_wonderwatt_share"):
            params.ed_wonderwatt_share.setText(url)

    def _save(self) -> None:
        from energy_dashboard.fetch.wonderwatt import save_wonderwatt_share_url

        parsed = save_wonderwatt_share_url(self.ed_share.text())
        if parsed is None:
            self.ed_share.clear()
            self._sync_other_fields("")
            self.lbl_status.setText("Share link cleared / invalid.")
            if self._dash is not None:
                self._dash.set_status("Wonderwatt share URL cleared / invalid.")
            return
        self.ed_share.setText(parsed["share_url"])
        self._sync_other_fields(parsed["share_url"])
        self.lbl_status.setText(f"Saved — wattid={parsed['wattid']}")
        if self._dash is not None:
            self._dash.set_status(
                f"Wonderwatt share saved (wattid={parsed['wattid']})."
            )

    def _test(self) -> None:
        from energy_dashboard.fetch.wonderwatt import (
            save_wonderwatt_share_url,
            test_wonderwatt_connection,
        )

        parsed = save_wonderwatt_share_url(self.ed_share.text())
        if parsed is None:
            self.lbl_status.setText(
                "Need a valid share URL (wattid, sig, time)."
            )
            return
        self.ed_share.setText(parsed["share_url"])
        self._sync_other_fields(parsed["share_url"])
        self.lbl_status.setText("Testing share link…")

        def _run():
            ok, msg = test_wonderwatt_connection(parsed["share_url"])
            line = f"{'Connected — ' if ok else 'Failed — '}{msg}"

            def _ui():
                self.lbl_status.setText(line)
                if self._dash is not None:
                    self._dash.set_status(f"Wonderwatt: {line}")

            QTimer.singleShot(0, _ui)

        import threading
        threading.Thread(target=_run, daemon=True).start()


class _ConnectivityHistoryDialog(QDialog):
    """Alarms / faults / enable-disable history for one Connectivity service row."""

    def __init__(
        self,
        service_label: str,
        rows: list[dict],
        parent=None,
        *,
        title: str | None = None,
        hint: str | None = None,
        empty_message: str | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title or f"History — {service_label}")
        self.setMinimumSize(640, 360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(8)
        hint_lbl = QLabel(
            hint
            or (
                "Alarms, faults, recoveries, and enable/disable actions for this service. "
                "Newest first."
            )
        )
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
        layout.addWidget(hint_lbl)
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["When", "Type", "State", "Detail"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            "QTableWidget { alternate-background-color: #252536; }"
        )
        table.setRowCount(len(rows))
        type_colors = {
            "alarm": "#f38ba8",
            "fault": "#f38ba8",
            "warn": "#fab387",
            "recover": "#a6e3a1",
            "disable": "#6c7086",
            "enable": "#89b4fa",
            "info": "#cdd6f4",
            "downtime": "#fab387",
            "test": "#89b4fa",
        }
        for i, ev in enumerate(rows):
            vals = [
                str(ev.get("timestamp") or ""),
                str(ev.get("event_type") or ""),
                str(ev.get("state_text") or ev.get("state_key") or ""),
                str(ev.get("detail") or ""),
            ]
            for c, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if c == 1:
                    item.setForeground(
                        QBrush(QColor(type_colors.get(vals[1].lower(), "#cdd6f4")))
                    )
                table.setItem(i, c, item)
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        if not rows:
            table.setRowCount(1)
            empty = QTableWidgetItem(
                empty_message
                or "No alarms or faults recorded yet for this service."
            )
            empty.setForeground(QBrush(QColor("#6c7086")))
            table.setItem(0, 0, empty)
            table.setSpan(0, 0, 1, 4)
        layout.addWidget(table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)
        layout.addWidget(buttons)


class _ConnectivityFlowDiagram(QWidget):
    """Animated architecture view: internet APIs + LAN → house (app) → DB → export."""

    def __init__(self, tab: "ConnectivityStatusTab"):
        super().__init__(tab)
        self._tab = tab
        self._phase = 0.0
        self._health = {}
        self._service_rows = {}
        self._box_volumes = {}
        self._telemetry = {}
        self._pipeline_probe = None
        self._hit_regions = []
        self._hover_key = None
        self._highlight_boxes: set[str] = set()
        self._highlight_edges: set[tuple[str, str]] = set()
        self._highlight_blink_on = False
        self._highlight_clear_at = 0.0
        # Active AlarmMonitor hits: list of {key, severity, title, detail}
        self._alarms: list[dict] = []
        self.setMinimumHeight(400)
        self.setMinimumWidth(360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._anim = QTimer(self)
        # 10 Hz is enough for the flow animation; pause when the tab is hidden
        # so the rest of the app stays responsive.
        self._anim.setInterval(100)
        self._anim.timeout.connect(self._tick)
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setInterval(220)
        self._highlight_timer.timeout.connect(self._highlight_tick)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._anim.isActive():
            self._anim.start()

    def hideEvent(self, event):
        if self._anim.isActive():
            self._anim.stop()
        super().hideEvent(event)

    def _tick(self):
        if not self.isVisible():
            return
        self._phase = (self._phase + 0.036) % 1.0
        self.update()

    def _highlight_tick(self):
        import time as _time
        if not self._highlight_edges and not self._highlight_boxes:
            self._highlight_timer.stop()
            return
        if _time.monotonic() >= self._highlight_clear_at:
            self.clear_link_highlight()
            return
        self._highlight_blink_on = not self._highlight_blink_on
        self.update()

    def highlight_links(self, box_keys=None, *, edges=None, duration_s: float = 4.0) -> None:
        """Blink only the named architecture edges (exact from→to pairs)."""
        import time as _time
        edge_set: set[tuple[str, str]] = set()
        for e in edges or ():
            if not e or len(e) != 2:
                continue
            a, b = str(e[0]), str(e[1])
            if a and b:
                edge_set.add((a, b))
        # Legacy box list is ignored for matching — keep empty so we never
        # re-light “anything touching dashboard”.
        self._highlight_boxes = set()
        self._highlight_edges = edge_set
        self._highlight_blink_on = True
        self._highlight_clear_at = _time.monotonic() + max(1.0, float(duration_s))
        if edge_set and not self._highlight_timer.isActive():
            self._highlight_timer.start()
        self.update()

    def clear_link_highlight(self) -> None:
        self._highlight_boxes = set()
        self._highlight_edges = set()
        self._highlight_blink_on = False
        self._highlight_clear_at = 0.0
        if self._highlight_timer.isActive():
            self._highlight_timer.stop()
        self.update()

    def _link_highlighted(self, fr=None, to=None, health_key=None) -> bool:
        """True only when this exact connector is in the highlight edge set."""
        edges = self._highlight_edges
        if not edges or not fr or not to:
            return False
        return (str(fr), str(to)) in edges

    @staticmethod
    def _worst_state(*keys):
        """Pick the worst connectivity among keys (bad is worst, then warn, idle, ok, off)."""
        rank = {"bad": 0, "warn": 1, "idle": 2, "ok": 3, "off": 4}
        worst = None
        worst_r = 99
        for k in keys:
            if k is None:
                continue
            r = rank.get(k, 99)
            if r < worst_r:
                worst_r = r
                worst = k
        return worst

    @staticmethod
    def _norm_diagram_sk(state_key, state_text):
        """Diagram states: only ``ok`` implies live data; empty/disabled → ``off``."""
        st = (state_text or "").strip().lower()
        no_data_phrases = (
            "no data", "disabled", "no targets", "not probed", "no live data",
            "not loaded", "disconnected", "partial session", "failed",
            "offline", "empty", "need growatt",
        )
        if state_key == "ok":
            return "ok"
        if state_key == "idle":
            return "idle"
        if state_key == "bad":
            return "bad"
        if state_key == "off" or any(p in st for p in no_data_phrases):
            return "off"
        if state_key == "warn":
            return "warn"
        return "off"

    def set_growatt_telemetry(self, info):
        self._telemetry = dict(info or {})
        self.update()

    def set_alarms(self, hits) -> None:
        """Push live AlarmMonitor hits onto the architecture diagram."""
        out: list[dict] = []
        for h in hits or ():
            if isinstance(h, dict):
                key = str(h.get("key") or "")
                if not key:
                    continue
                out.append({
                    "key": key,
                    "severity": str(h.get("severity") or "warn"),
                    "title": str(h.get("title") or key),
                    "detail": str(h.get("detail") or ""),
                })
                continue
            key = str(getattr(h, "key", "") or "")
            if not key:
                continue
            out.append({
                "key": key,
                "severity": str(getattr(h, "severity", "warn") or "warn"),
                "title": str(getattr(h, "title", key) or key),
                "detail": str(getattr(h, "detail", "") or ""),
            })
        self._alarms = out
        self.update()

    def _alarms_touching_box(self, box_key: str) -> list[dict]:
        key = str(box_key or "")
        if key.startswith("battery_"):
            key = "battery"
        hits = []
        for alarm in self._alarms:
            meta = _ALARM_DIAGRAM_MAP.get(alarm["key"]) or {}
            boxes = meta.get("boxes") or ()
            if key in boxes or (key == "battery" and meta.get("batteries")):
                hits.append(alarm)
            elif key.startswith("battery") and meta.get("batteries"):
                hits.append(alarm)
        return hits

    def _alarm_state_for_box(self, box_key: str) -> str | None:
        worst = None
        for alarm in self._alarms_touching_box(box_key):
            sk = _alarm_severity_to_sk(alarm.get("severity", "warn"))
            worst = self._worst_state(worst, sk)
        return worst

    def _alarm_state_for_edge(self, fr: str | None, to: str | None) -> str | None:
        if not fr or not to:
            return None
        pair = (str(fr), str(to))
        # Battery pack → inverter inherits battery alarms.
        if str(fr).startswith("battery_") and to == "inverter":
            return self._alarm_state_for_box("battery")
        worst = None
        for alarm in self._alarms:
            meta = _ALARM_DIAGRAM_MAP.get(alarm["key"]) or {}
            edges = meta.get("edges") or ()
            if pair in edges:
                sk = _alarm_severity_to_sk(alarm.get("severity", "warn"))
                worst = self._worst_state(worst, sk)
        return worst

    def _box_display_state(self, box_key: str, health_key: str | None = None) -> str:
        """Worst of connectivity health and live alarms for a diagram card."""
        hk = health_key or box_key
        health = "ok" if box_key == "dashboard" else self._health.get(hk, "off")
        if box_key == "inverter":
            health = self._worst_state(
                self._health.get("grott", "off"),
                self._health.get("growatt_cloud", "off"),
                self._health.get("modbus", "off"),
            ) or "off"
        t = self._telemetry or {}
        # Hybrid fallback: make Grott / EMQX / cloud show as degraded even if
        # the status row has not flipped yet.
        if t.get("hybrid_fallback"):
            if box_key in ("grott", "emqx"):
                health = self._worst_state(
                    health,
                    "bad" if not t.get("grott_connected") else "warn",
                ) or health
            elif box_key == "growatt_cloud":
                # Cloud is carrying live — warn tint so the fallback is visible.
                health = self._worst_state(health, "warn") or health
            elif box_key == "inverter":
                health = self._worst_state(health, "warn") or health
        alarm = self._alarm_state_for_box(box_key)
        return self._worst_state(health, alarm) or health or "off"

    def _alarm_badge_label(self, box_key: str) -> str:
        hits = self._alarms_touching_box(box_key)
        if not hits:
            return ""
        if len(hits) == 1:
            title = hits[0].get("title") or hits[0].get("key") or "Alarm"
            return title if len(title) <= 28 else title[:25] + "…"
        return f"{len(hits)} alarms"

    @staticmethod
    def _fmt_age_s(age_s) -> str:
        try:
            s = float(age_s)
        except (TypeError, ValueError):
            return "unknown age"
        if s < 60:
            return f"{s:.0f}s"
        if s < 3600:
            return f"{int(s // 60)}m {int(s % 60):02d}s"
        return f"{int(s // 3600)}h {int((s % 3600) // 60):02d}m"

    def _degradation_findings(self) -> list[dict]:
        """Plain-English findings when the architecture is degraded.

        Each item: severity ('warn'|'bad'), headline, detail (optional).
        Used by the diagram banner and click-through details.
        """
        findings: list[dict] = []
        t = self._telemetry or {}

        for alarm in self._alarms:
            findings.append({
                "severity": _alarm_severity_to_sk(alarm.get("severity", "warn")),
                "headline": alarm.get("title") or alarm.get("key") or "Alarm",
                "detail": alarm.get("detail") or "",
                "box": ( _ALARM_DIAGRAM_MAP.get(alarm.get("key") or "", {}).get("boxes") or (None,) )[0],
            })

        if t.get("hybrid_fallback") or (
            t.get("uses_grott") and not t.get("grott_fresh") and t.get("hybrid")
        ):
            age = self._fmt_age_s(t.get("grott_age_s"))
            connected = bool(t.get("grott_connected"))
            if not connected and t.get("grott_running"):
                headline = "GROTT MQTT disconnected — Hybrid using Growatt cloud API"
                detail = (
                    f"Last Grott payload {age}. Broker session is down "
                    f"(disconnects={t.get('grott_disconnects', 0)}, "
                    f"reconnects={t.get('grott_reconnects', 0)}). "
                    "Live SOC/power should be coming from Growatt cloud until Grott recovers."
                )
                sev = "bad"
            elif not t.get("grott_running"):
                headline = "GROTT not running — Hybrid expecting MQTT"
                detail = (
                    "Hybrid mode is selected but the Grott MQTT subscriber is not "
                    "enabled/running. Check Grott Setup / EMQX, or switch source to API."
                )
                sev = "bad"
            else:
                limit = t.get("grott_fresh_s") or 120
                headline = f"GROTT stale ({age}) — Hybrid live path is Growatt cloud API"
                detail = (
                    f"MQTT is connected but no fresh inverter payload within "
                    f"{float(limit):.0f}s. Shine/Grott often wait 1–5 min; if this "
                    "persists, check Grott, EMQX, and the Shine datalogger. "
                    f"Disconnects={t.get('grott_disconnects', 0)}, "
                    f"reconnects={t.get('grott_reconnects', 0)}."
                )
                sev = "warn"
            last_ev = (t.get("grott_last_event") or "").strip()
            if last_ev:
                detail = f"{detail} Last link event: {last_ev}."
            findings.append({
                "severity": sev,
                "headline": headline,
                "detail": detail,
                "box": "grott",
            })

        if t.get("api_filled_count"):
            n = int(t.get("api_filled_count") or 0)
            names = list(t.get("api_filled_fields") or ())
            detail = (
                "Live path is still Grott/Hybrid, but empty fields were filled "
                "from the cloud API. Amber labels on Growatt Live mark those values."
            )
            if names:
                shown = ", ".join(names[:8])
                if len(names) > 8:
                    shown += f", +{len(names) - 8} more"
                detail = f"{detail} Currently: {shown}."
            findings.append({
                "severity": "warn",
                "headline": f"Grott missing {n} register(s) — patched from Growatt cloud (amber)",
                "detail": detail,
                "box": "growatt_cloud",
            })

        # Connectivity table warn/bad (skip ones already covered by Grott fallback).
        covered = {f.get("headline") for f in findings}
        for label, row in (self._service_rows or {}).items():
            if not row or len(row) < 3:
                continue
            sk = self._norm_diagram_sk(row[2], row[1])
            if sk not in ("warn", "bad"):
                continue
            if "Grott" in label and any("GROTT" in (f.get("headline") or "") for f in findings):
                continue
            headline = f"{label}: {row[1]}"
            if headline in covered:
                continue
            detail = str(row[3] or "").strip()
            fresh = str(row[4] or "").strip()
            if fresh and fresh not in ("--", ""):
                detail = f"{detail}  ·  Last/fresh: {fresh}".strip(" ·")
            findings.append({
                "severity": sk,
                "headline": headline,
                "detail": detail,
                "box": _CONNECTIVITY_ROW_TO_HEALTH.get(label),
            })

        # Worst-first.
        rank = {"bad": 0, "warn": 1}
        findings.sort(key=lambda f: rank.get(f.get("severity"), 9))
        return findings

    def _degradation_banner_lines(self, *, max_lines: int = 3) -> tuple[str, list[str]]:
        """Return (severity, lines) for the diagram header strip."""
        findings = self._degradation_findings()
        if not findings:
            return "", []
        sev = "bad" if any(f.get("severity") == "bad" for f in findings) else "warn"
        lines = []
        for f in findings[:max_lines]:
            h = str(f.get("headline") or "").strip()
            if not h:
                continue
            lines.append(h)
        more = len(findings) - len(lines)
        if more > 0 and lines:
            lines[-1] = f"{lines[-1]}  (+{more} more — click a highlighted box)"
        return sev, lines

    def set_health_from_rows(self, rows, direct=None):
        self._service_rows = {r[0]: r for r in rows if r}
        raw = {}
        for r in rows:
            if len(r) < 3:
                continue
            key = _CONNECTIVITY_ROW_TO_HEALTH.get(r[0])
            if key:
                raw[key] = self._norm_diagram_sk(r[2], r[1])
        hist = raw.get("octopus_hist", "off")
        live = raw.get("octopus_live", "off")
        if hist == "ok" or live == "ok":
            oc = "ok"
        elif hist == "idle" or live == "idle":
            oc = "idle"
        else:
            oc = self._worst_state(hist, live) or "off"
        db = raw.get("database", "off")
        if db == "ok":
            ex = "ok"
        elif db == "idle":
            ex = "idle"
        elif db in ("warn", "bad"):
            ex = "warn"
        else:
            ex = "off"
        direct = direct or {}
        modbus = direct.get(
            "modbus",
            direct.get("lan_direct", raw.get("modbus_lan", "off")),
        )
        self._health = {
            "growatt_cloud": raw.get("growatt_cloud", "off"),
            "grott": raw.get("grott", "off"),
            "octopus": oc or "off",
            "forecast": raw.get("forecast", "off"),
            "modbus": modbus,
            "modbus_lan": raw.get("modbus_lan", modbus),
            "tasmota": raw.get("tasmota", "off"),
            "database": db,
            "export": ex,
            "storage": db if db != "off" else ex,
            "pvoutput": direct.get("pvoutput", "off"),
            "wonderwatt": direct.get("wonderwatt", "off"),
        }
        # EMQX carries Grott, Tasmota, and bridged Modbus MQTT — not cloud REST.
        emqx = self._worst_state(
            self._health.get("grott", "off"),
            self._health.get("tasmota", "off"),
            self._health.get("modbus", "off"),
        )
        if (
            self._health.get("grott") == "ok"
            or self._health.get("tasmota") == "ok"
            or self._health.get("modbus") == "ok"
        ):
            emqx = "ok"
        self._health["emqx"] = emqx or "off"
        self.update()

    def _link_flow_state(self, health_key, fr=None, to=None):
        if health_key is None:
            return "ok"
        src = self._telemetry.get("source", GROWATT_TELEMETRY_API)
        if fr == "grott" and to == "emqx":
            # Always show Grott→broker flow from Grott health (and EMQX if known).
            grott = self._health.get("grott", "off")
            emqx = self._health.get("emqx", "off")
            if self._telemetry.get("uses_grott"):
                return self._worst_state(grott, emqx) or "off"
            return grott if grott != "off" else emqx
        if fr == "modbus" and to == "emqx":
            return self._health.get("modbus", "off")
        if fr == "inverter" and to == "grott" and self._telemetry.get("uses_grott"):
            return self._health.get("grott", "off")
        if fr == "growatt_cloud" and to == "dashboard" and src == GROWATT_TELEMETRY_HYBRID:
            return self._worst_state(
                self._health.get("growatt_cloud", "off"),
                self._health.get("grott", "off"),
            ) or "off"
        if fr == "grott" and to == "growatt_cloud" and src == GROWATT_TELEMETRY_HYBRID:
            cloud = self._health.get("growatt_cloud", "off")
            grott = self._health.get("grott", "off")
            if grott == "ok":
                return "idle" if cloud in ("ok", "warn") else grott
            if cloud == "ok":
                return "warn"
            return self._worst_state(grott, cloud) or "off"
        return self._health.get(health_key, "off")

    def _diagram_card_copy(self, key, title, sub):
        t = self._telemetry
        src = t.get("source", GROWATT_TELEMETRY_API)
        age = self._fmt_age_s(t.get("grott_age_s")) if t.get("grott_age_s") is not None else None
        if key == "grott":
            if src == GROWATT_TELEMETRY_HYBRID:
                title = "GROTT / Hybrid"
                if t.get("hybrid_fallback"):
                    if not t.get("grott_connected"):
                        sub = f"DISCONNECTED — cloud API carrying live"
                    else:
                        sub = f"STALE {age or '?'} — cloud API carrying live"
                else:
                    sub = "MQTT primary · API on standby"
            elif src == GROWATT_TELEMETRY_GROTT:
                title = "GROTT"
                if t.get("grott_fresh"):
                    sub = "MQTT primary"
                elif t.get("grott_connected"):
                    sub = f"STALE {age or '?'} — waiting for payload"
                else:
                    sub = "DISCONNECTED — no live MQTT"
            else:
                title, sub = "GROTT", "not selected"
            if t.get("fill_missing") and src in (GROWATT_TELEMETRY_GROTT, GROWATT_TELEMETRY_HYBRID):
                n = int(t.get("api_filled_count") or 0)
                sub += f" · API patch gaps" + (f" ({n})" if n else "")
            return title, sub
        if key == "growatt_cloud":
            if src == GROWATT_TELEMETRY_HYBRID:
                if t.get("grott_fresh"):
                    sub = "cloud REST · standby (Grott live)"
                elif t.get("hybrid_fallback"):
                    sub = f"LIVE FALLBACK — Grott {age or 'stale'}"
                elif t.get("grott_running"):
                    sub = "cloud REST · fallback (Grott stale)"
                else:
                    sub = "cloud REST · fallback"
            elif src == GROWATT_TELEMETRY_GROTT:
                sub = "cloud REST · patch only" if t.get("fill_missing") else "cloud REST · standby"
            else:
                sub = "cloud REST"
            return title, sub
        if key == "emqx" and t.get("uses_grott"):
            if t.get("hybrid_fallback"):
                if not t.get("grott_connected"):
                    sub = "MQTT broker · Grott path DOWN"
                else:
                    sub = f"MQTT broker · Grott stale ({age or '?'})"
            else:
                sub = "MQTT broker · Grott path"
        return title, sub

    def set_volumes(self, volumes):
        self._box_volumes = dict(volumes or {})
        self.update()

    def set_pipeline_probe(self, report):
        """Overlay hop/link states from a pipeline probe onto the diagram."""
        self._pipeline_probe = report
        self.update()

    def clear_pipeline_probe(self):
        self._pipeline_probe = None
        self.update()

    def _probe_hop_state(self, hop_id: str):
        report = self._pipeline_probe
        if not report:
            return None
        hop = report.hop(hop_id)
        return hop.state if hop else None

    def _probe_link_state(self, link_id: str):
        report = self._pipeline_probe
        if not report:
            return None
        for ln in report.links:
            if ln.link_id == link_id:
                return ln.state
        return None

    def _sk_color(self, sk):
        c = {
            "ok": "#a6e3a1",
            "warn": "#fab387",
            "bad": "#f38ba8",
            "idle": _UI_BLUE,
            "off": "#6c7086",
        }.get(sk, "#a6adc8")
        return QColor(c)

    def _draw_label_card(self, p, rect, title, state_key, subtitle=None, *, hover=False):
        border = self._sk_color(state_key)
        if hover:
            border = border.lighter(125)
        bg = QColor("#2a2a3c")
        if hover:
            bg = bg.lighter(108)
        p.setPen(QPen(border, 2))
        p.setBrush(bg)
        p.drawRoundedRect(rect, 6, 6)
        p.setPen(QColor("#cdd6f4"))
        f = QFont("Helvetica", 9)
        f.setBold(True)
        p.setFont(f)
        title_rect = QRectF(rect.left() + 8, rect.top() + 7, rect.width() - 16, 18)
        p.drawText(title_rect, Qt.AlignLeft | Qt.AlignTop, title)
        if subtitle:
            f2 = QFont("Helvetica", 8)
            p.setFont(f2)
            p.setPen(QColor("#6c7086"))
            sub_rect = QRectF(
                rect.left() + 8, rect.top() + 26,
                rect.width() - 16, rect.height() - 32,
            )
            p.drawText(
                sub_rect,
                int(Qt.AlignLeft | Qt.AlignTop | Qt.TextFlag.TextWordWrap),
                subtitle,
            )

    def _draw_arch_card(
        self,
        p,
        rect,
        title,
        subtitle,
        *,
        accent="#89b4fa",
        hover=False,
        main=False,
        vertical=False,
        state_key: str | None = None,
        alarm_label: str = "",
        show_badge: bool = False,
    ):
        # Prefer alarm / connectivity colour over the group accent when degraded.
        edge = QColor(accent)
        if state_key in ("warn", "bad"):
            edge = self._sk_color(state_key)
        if hover:
            edge = edge.lighter(120)
        pen_w = 2.6 if state_key in ("warn", "bad") else (2.0 if main else 1.8)
        if main:
            base = QColor("#2563eb")
            base2 = QColor("#4338ca")
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, base)
            grad.setColorAt(1.0, base2)
            p.setBrush(grad)
            p.setPen(QPen(edge.lighter(130), pen_w))
        else:
            fill = QColor("#1f2937")
            if state_key == "bad":
                fill = QColor("#3f1d2e")
            elif state_key == "warn":
                fill = QColor("#3a2e1d")
            if hover:
                fill = fill.lighter(110)
            p.setBrush(fill)
            p.setPen(QPen(edge, pen_w))
        p.drawRoundedRect(rect, 10, 10)

        if vertical:
            p.save()
            p.translate(rect.center())
            p.rotate(-90)
            p.setPen(QColor("#e2e8f0"))
            ft = QFont("Helvetica", 8 if rect.width() < 50 else 9, QFont.Bold)
            p.setFont(ft)
            tw = int(rect.height() - 12)
            th = int(rect.width() - 10)
            p.drawText(
                QRectF(-tw * 0.5, -th * 0.5, tw, th),
                int(Qt.AlignCenter | Qt.TextFlag.TextWordWrap),
                title,
            )
            p.restore()
            if show_badge:
                self._draw_alarm_badge(p, rect, state_key or "warn", alarm_label)
            return

        p.setPen(QColor("#f8fafc") if main else QColor("#e2e8f0"))
        f1 = QFont("Helvetica", 9 if not main else 10, QFont.Bold)
        p.setFont(f1)
        p.drawText(
            QRectF(rect.left() + 10, rect.top() + 8, rect.width() - 20, 18),
            Qt.AlignLeft | Qt.AlignTop,
            title,
        )
        sub = subtitle or ""
        if show_badge and alarm_label:
            sub = alarm_label if not sub else f"{alarm_label}\n{sub}"
        if sub:
            p.setPen(
                self._sk_color(state_key) if show_badge and state_key in ("warn", "bad")
                else (QColor("#cbd5e1") if main else QColor("#94a3b8"))
            )
            f2 = QFont("Helvetica", 8)
            p.setFont(f2)
            # Leave a few px under the title and above the bottom radius so
            # wrapped / ALARM+detail lines are not clipped (BUG-20260922-01).
            p.drawText(
                QRectF(
                    rect.left() + 10, rect.top() + 28,
                    rect.width() - 20, max(14.0, rect.height() - 36),
                ),
                int(Qt.AlignLeft | Qt.AlignTop | Qt.TextFlag.TextWordWrap),
                sub,
            )
        if show_badge:
            self._draw_alarm_badge(p, rect, state_key or "warn", alarm_label)

    def _draw_battery_arch_card(self, p, rect, pack, *, hover=False):
        """Compact horizontal battery pack card (SN + alert tint)."""
        alert = str((pack or {}).get("alert") or "off")
        accent = {
            "ok": "#34d399",
            "warn": "#fab387",
            "fault": "#f38ba8",
            "bad": "#f38ba8",
            "off": "#64748b",
        }.get(alert, "#64748b")
        edge = QColor(accent)
        if hover:
            edge = edge.lighter(120)
        fill = QColor("#1f2937")
        if hover:
            fill = fill.lighter(110)
        p.setBrush(fill)
        p.setPen(QPen(edge, 1.6))
        p.drawRoundedRect(rect, 8, 8)

        idx = int((pack or {}).get("index") or 1)
        sn = str((pack or {}).get("sn") or "").strip()
        title = f"Battery {idx}"
        # Show the full serial — cards are sized for typical Growatt pack SNs.
        sub = sn if sn else "SN unknown"

        p.setPen(QColor("#e2e8f0"))
        p.setFont(QFont("Helvetica", 7, QFont.Bold))
        pad_x = 7.0
        pad_y = 6.0
        title_h = 15.0 if rect.height() >= 38 else 12.0
        p.drawText(
            QRectF(rect.left() + pad_x, rect.top() + pad_y, rect.width() - 2 * pad_x, title_h),
            Qt.AlignLeft | Qt.AlignVCenter,
            title,
        )
        p.setPen(QColor(accent) if alert in ("fault", "warn") else QColor("#94a3b8"))
        # Slightly smaller font only if the SN is unusually long for the box.
        sn_pt = 7 if len(sub) <= 16 else 6
        p.setFont(QFont("Helvetica", sn_pt))
        sn_top = rect.top() + pad_y + title_h + 1.0
        sn_h = max(14.0, rect.bottom() - pad_y - sn_top)
        p.drawText(
            QRectF(rect.left() + pad_x, sn_top, rect.width() - 2 * pad_x, sn_h),
            Qt.AlignLeft | Qt.AlignVCenter,
            sub,
        )

    def _draw_house(self, p, cx, cy, w, h, *, hover=False):
        path = QPainterPath()
        hw = w * 0.5
        roof_h = h * 0.38
        body_h = h - roof_h
        top_y = cy - h * 0.5
        peak_x, peak_y = cx, top_y
        left_roof_x, left_roof_y = cx - hw, top_y + roof_h
        right_roof_x, right_roof_y = cx + hw, top_y + roof_h
        path.moveTo(left_roof_x, left_roof_y)
        path.lineTo(peak_x, peak_y)
        path.lineTo(right_roof_x, right_roof_y)
        path.lineTo(right_roof_x, left_roof_y + body_h)
        path.lineTo(left_roof_x, left_roof_y + body_h)
        path.closeSubpath()
        p.setPen(QPen(QColor("#b4d0ff" if hover else "#89b4fa"), 2))
        p.setBrush(QColor("#3a3a52" if hover else "#313244"))
        p.drawPath(path)
        p.setPen(QColor("#cdd6f4"))
        p.setFont(QFont("Helvetica", 10, QFont.Bold))
        p.drawText(
            QRectF(cx - hw, left_roof_y + body_h * 0.25, w, 40),
            Qt.AlignHCenter | Qt.AlignTop,
            "Energy\nDashboard",
        )

    def _pulse_line(self, p, x1, y1, x2, y2, color, strength=1.0):
        col = QColor(color)
        pen = QPen(col)
        pen.setWidthF(1.3 * strength)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([6, 5])
        pen.setDashOffset(-self._phase * 22)
        p.setPen(pen)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        dx, dy = x2 - x1, y2 - y1
        for k in range(3):
            t = (self._phase + k * 0.34) % 1.0
            px = x1 + dx * t
            py = y1 + dy * t
            p.setPen(Qt.PenStyle.NoPen)
            dot = QColor(col)
            dot.setAlpha(210 - k * 50)
            p.setBrush(dot.lighter(112 - k * 6))
            p.drawEllipse(QPointF(px, py), 3.2, 3.2)

    @staticmethod
    def _curve_path(x1, y1, x2, y2, bend=0.0):
        """Cubic path between two points with optional vertical bend.
        Positive bend bows downward; negative bows upward."""
        dx = (x2 - x1)
        path = QPainterPath(QPointF(x1, y1))
        dy = (y2 - y1)
        # Horizontal-ish links: bias control points on x.
        if abs(dx) >= abs(dy):
            c = max(28.0, min(abs(dx) * 0.45, 120.0))
            path.cubicTo(
                QPointF(x1 + c, y1 + bend),
                QPointF(x2 - c, y2 + bend),
                QPointF(x2, y2),
            )
        else:
            # Vertical-ish links: bias control points on y, and let `bend`
            # act as horizontal bowing so purely vertical links are still curved.
            c = max(28.0, min(abs(dy) * 0.38, 120.0))
            path.cubicTo(
                QPointF(x1 + bend, y1 + c),
                QPointF(x2 + bend, y2 - c),
                QPointF(x2, y2),
            )
        return path

    def _draw_flow_curve_link(
        self,
        p,
        x1,
        y1,
        x2,
        y2,
        flow_state,
        *,
        color="#89b4fa",
        bend=0.0,
        strength=1.0,
        idle_color="#566483",
    ):
        path = self._curve_path(x1, y1, x2, y2, bend=bend)
        if flow_state == "ok":
            # Soft base lane.
            base = QPen(QColor("#1e293b"))
            base.setWidthF(2.8)
            base.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(base)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            # Color halo lane.
            col = QPen(QColor(color))
            col.setWidthF(1.4 * strength)
            col.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(col)
            p.drawPath(path)
            # Animated dashed flow.
            anim = QPen(QColor(color))
            anim.setWidthF(2.1 * strength)
            anim.setCapStyle(Qt.PenCapStyle.RoundCap)
            anim.setStyle(Qt.PenStyle.DashLine)
            anim.setDashPattern([2, 22])
            anim.setDashOffset(-self._phase * 22.0)
            p.setPen(anim)
            p.drawPath(path)
        elif flow_state == "idle":
            pen = QPen(QColor(idle_color))
            pen.setWidthF(1.0)
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern([3, 7])
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        else:
            # warn / bad / off: keep the topology visible with a faint static
            # line so missing data does not make the diagram look broken.
            faint = QColor(color)
            faint.setAlpha(70 if flow_state in ("warn", "bad") else 38)
            pen = QPen(faint)
            pen.setWidthF(1.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

    def _static_link_line(self, p, x1, y1, x2, y2, *, pending=False, color="#566483"):
        """Faint connector — pending only; no animation (does not imply data flow)."""
        if not pending:
            return
        pen = QPen(QColor(color))
        pen.setWidthF(1.0)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([3, 7])
        p.setPen(pen)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def _draw_flow_link(
        self,
        p,
        x1,
        y1,
        x2,
        y2,
        flow_state,
        *,
        color="#89b4fa",
        idle_color="#566483",
        strength=1.0,
    ):
        if flow_state == "ok":
            self._pulse_line(p, x1, y1, x2, y2, color, strength)
        elif flow_state == "idle":
            self._static_link_line(p, x1, y1, x2, y2, pending=True, color=idle_color)

    @staticmethod
    def _even_vertical_tops(count, pane_top, pane_bottom, item_h):
        """Top-y for each item with equal spacing above, below, and between."""
        span = max(item_h, pane_bottom - pane_top)
        gap = max(6.0, (span - count * item_h) / (count + 1))
        return [pane_top + gap + i * (item_h + gap) for i in range(count)]

    @staticmethod
    def _even_edge_fractions(count: int, height: float, pad_px: float = 12.0) -> list[float]:
        """Attach fractions along a box edge: equal spacing, ``pad_px`` from both ends."""
        n = int(count)
        if n <= 0:
            return []
        h = max(1.0, float(height))
        pad = max(0.0, min(float(pad_px), h * 0.45))
        if n == 1:
            return [0.5]
        span = max(0.0, h - 2.0 * pad)
        return [(pad + i * span / (n - 1)) / h for i in range(n)]

    # Planar layout: no data line crosses another data line or passes under
    # a box. The middle column stacks the local sources top-to-bottom in the
    # same order their lines enter EMQX / the dashboard, so every route nests
    # inside the one above it:
    #   Growatt API ↔ inverter (parallel data + return) → dashboard
    #   GROTT ↔ inverter; GROTT → EMQX (dedicated lane) → dashboard
    #   Tasmota ↔ EMQX mid (two-way MQTT: tele/stat in, cmnd out)
    #   Modbus ↔ inverter; Modbus → EMQX (one-way) and → dashboard direct
    # Octopus / PV forecast run in the lower lanes straight to the dashboard.
    # Bottom row (evenly spaced left→right): Octopus · PV forecast ·
    # PVOutput.org · Wonderwatt.com.
    # AI Controller + Databases sit on one row above the dashboard (half width
    # each) with a link between them; dashboard is 50 px wider than before.
    # Inverter is vertically centred on the four local-source boxes
    # (Growatt API → GROTT → Tasmota → Modbus). Standard cards are 52 px tall
    # so title + ALARM/WARN + subtitle fit without clipping (was 40).
    _ARCH_VBW = 1100.0
    _ARCH_VBH = 560.0
    # Four-box stack: top of Growatt API (cy 50 − 26) … bottom of Modbus (cy 260 + 26)
    # → group centre y = 155. EMQX centred between GROTT and Tasmota.
    _ARCH_SPEC = {
        "inverter": (168, 155, 42, 190.0),
        "growatt_cloud": (400, 50, 150, 52),
        "grott": (400, 120, 150, 52),
        "tasmota": (400, 190, 150, 52),
        "modbus": (400, 260, 150, 52),
        "emqx": (640, 155, 150, 52),
        "ai": (880, 45, 100, 52),
        "storage": (1030, 45, 100, 52),
        "dashboard": (955, 165, 250, 118),
        # Bottom strip — four equal slots across the canvas.
        "octopus": (137.5, 505, 200, 52),
        "forecast": (412.5, 505, 200, 52),
        "pvoutput": (687.5, 505, 200, 52),
        "wonderwatt": (962.5, 505, 200, 52),
    }

    def _battery_packs(self) -> list[dict]:
        packs = self._telemetry.get("batteries")
        if isinstance(packs, list) and packs:
            return packs
        n = int(self._telemetry.get("battery_count") or 1)
        n = max(1, min(n, 8))
        return [{"index": i + 1, "sn": "", "alert": "off"} for i in range(n)]

    def _compute_layout(self, W, H, *, header_h: float = 46.0):
        """Faithful port of the React blueprint: nodes live in a 1100x500 virtual
        canvas and are mapped into the widget with a non-uniform scale (matching
        the React SVG `preserveAspectRatio='none'` + percentage layout). The
        header occupies the top strip; the diagram fills the rest.

        Battery pack boxes are injected dynamically to the left of the inverter.
        """
        bp = {
            key: QRectF(cx - w * 0.5, cy - h * 0.5, w, h)
            for key, (cx, cy, w, h) in self._ARCH_SPEC.items()
        }
        packs = self._battery_packs()
        inv = bp["inverter"]
        n = len(packs)
        # Wide enough for a full Growatt pack serial (typically ≤16 chars) plus padding.
        bat_w = 132.0
        # Fit packs into the inverter's vertical span (inverter is centred on the
        # four source boxes, so the battery stack moves with it). Prefer taller
        # cards so title + full SN both fit without clipping.
        inv_h = max(1.0, float(inv.height()))
        if n <= 1:
            bat_h = min(54.0, inv_h)
        else:
            # Leave a small gap between packs; keep each tall enough for two text lines.
            gap = 8.0
            usable = inv_h - gap * (n - 1)
            bat_h = min(54.0, max(38.0, usable / n))
            bat_h = min(bat_h, usable / n)
        bat_right = inv.left() - 10.0
        bat_left = max(4.0, bat_right - bat_w)
        bat_w = bat_right - bat_left
        bat_keys = []
        if n <= 1:
            ys = [inv.center().y() - bat_h * 0.5]
        else:
            y_first = inv.top()
            y_last = inv.bottom() - bat_h
            step = (y_last - y_first) / (n - 1)
            ys = [y_first + i * step for i in range(n)]
        for i, pack in enumerate(packs):
            key = f"battery_{int(pack.get('index') or (i + 1))}"
            bp[key] = QRectF(bat_left, ys[i], bat_w, bat_h)
            bat_keys.append(key)
        ax = 10.0
        ay = float(max(46.0, header_h))
        aw = max(60.0, W - 20.0)
        ah = max(60.0, H - ay - 10.0)
        sx = aw / self._ARCH_VBW
        sy = ah / self._ARCH_VBH
        return {
            "bp": bp,
            "ax": ax,
            "ay": ay,
            "sx": sx,
            "sy": sy,
            "battery_keys": bat_keys,
            "battery_packs": packs,
        }

    def _hit_key_at(self, pos):
        pt = QPointF(pos)
        for key, _title, rect in reversed(self._hit_regions):
            if rect.contains(pt):
                return key
        return None

    def _state_label(self, state_key):
        return {
            "ok": "Active — data flowing",
            "idle": "In progress",
            "warn": "Degraded / partial",
            "bad": "Error / unavailable",
            "off": "No data / not configured",
        }.get(state_key, state_key)

    def _format_row_block(self, row):
        service, state_text, state_key, details, fresh = row[:5]
        lines = [
            service,
            f"  Status: {state_text} ({self._state_label(state_key)})",
            f"  Details: {details}",
            f"  Last / freshness: {fresh}",
        ]
        if len(row) > 5 and row[5] not in (None, "", "--"):
            lines.append(f"  Table size: {row[5]}")
        return "\n".join(lines)

    def _volume_block(self, box_key):
        lines = self._box_volumes.get(box_key) or []
        if not lines:
            # Fall back to live inventory from the size/health cache when async
            # DB volume enrichment has not finished yet.
            tab = self._tab
            if tab is not None and hasattr(tab, "import_inventory_lines_for_box"):
                lines = tab.import_inventory_lines_for_box(box_key)
        if not lines:
            return ""
        return "Data volumes:\n" + "\n".join(f"  · {ln}" for ln in lines)

    def _append_volumes(self, blocks, box_key):
        vol = self._volume_block(box_key)
        if vol:
            blocks.append(vol)

    def _append_alarms(self, blocks, box_key):
        hits = self._alarms_touching_box(box_key)
        if not hits:
            return
        lines = ["Active alarms / alerts:"]
        for h in hits:
            sev = str(h.get("severity") or "warn").upper()
            lines.append(f"  · [{sev}] {h.get('title') or h.get('key')}")
            detail = (h.get("detail") or "").strip()
            if detail:
                lines.append(f"      {detail}")
        blocks.append("\n".join(lines))

    def _append_whats_happening(self, blocks, box_key=None):
        """Fuller degradation narrative for click-through details."""
        findings = self._degradation_findings()
        if not findings:
            return
        relevant = findings
        if box_key:
            bk = "battery" if str(box_key).startswith("battery_") else str(box_key)
            scoped = []
            for f in findings:
                fb = f.get("box")
                if fb is None or fb == bk or (
                    bk == "emqx" and fb in ("grott", "tasmota", "modbus")
                ) or (
                    bk == "inverter" and fb in ("grott", "growatt_cloud", "modbus")
                ):
                    scoped.append(f)
            # Always include global hybrid/alarm headlines when viewing a Growatt box.
            if bk in ("grott", "growatt_cloud", "emqx", "inverter", "dashboard"):
                relevant = findings
            elif scoped:
                relevant = scoped
            else:
                relevant = findings[:3]
        lines = ["What's happening right now:"]
        for f in relevant[:6]:
            sev = str(f.get("severity") or "warn").upper()
            lines.append(f"  · [{sev}] {f.get('headline')}")
            detail = (f.get("detail") or "").strip()
            if detail:
                lines.append(f"      {detail}")
        blocks.append("\n".join(lines))

    def _format_box_details(self, box_key):
        title, services = _CONNECTIVITY_BOX_SERVICES.get(box_key, (box_key, ()))
        blocks = []
        flow = self._health.get(box_key, "off")
        self._append_alarms(blocks, box_key)
        self._append_whats_happening(blocks, box_key)
        if box_key == "battery" or str(box_key).startswith("battery_"):
            packs = self._battery_packs()
            n = len(packs)
            focus = None
            if str(box_key).startswith("battery_"):
                try:
                    focus = int(str(box_key).split("_", 1)[1])
                except (TypeError, ValueError):
                    focus = None
            lines = [
                f"{n} parallel battery pack slot(s) on the architecture diagram.",
                "",
                "Count comes from (in order): manual override on Growatt Live, "
                "detected/Modbus module count, known pack serials, then Setup "
                "capacity ÷ 6.5 kWh.",
                "",
            ]
            for pack in packs:
                sn = (pack.get("sn") or "").strip() or "—"
                alert = pack.get("alert") or "off"
                mark = " ←" if focus and int(pack.get("index") or 0) == focus else ""
                lines.append(
                    f"Battery {pack.get('index')}: SN {sn} · status {alert}{mark}"
                )
            detail = (packs[0].get("alerts_detail") if packs else "") or ""
            if detail:
                lines.extend(["", "Inverter fault/warning words:", detail])
            lines.extend([
                "",
                "Pack serials: Growatt Live → Physical → Probe packs (Modbus), "
                "or plant device_list storage devices when Growatt lists them.",
            ])
            title = f"Battery {focus}" if focus else "Battery packs"
            body = "\n".join(lines)
            if blocks:
                return title, "\n\n".join(blocks + [body])
            return title, body
        if box_key == "inverter":
            blocks.append(
                "Growatt hybrid inverter — three independent pipes leave this box: "
                "cloud REST, GROTT (cloud-report decode → MQTT), and Modbus.\n\n"
                f"Diagram status: {self._state_label(self._box_display_state('inverter'))}"
            )
            return title, "\n\n".join(blocks)
        if box_key == "dashboard":
            blocks.append(
                "Central application that ingests live and historic energy data, "
                "runs forecasts and optimisation, and writes snapshots to configured "
                "database backends.\n\n"
                f"Diagram status: {self._state_label('ok')} (always running while open)\n\n"
                "Click other boxes for upstream source and backend details."
            )
            self._append_volumes(blocks, box_key)
            return title, "\n\n".join(blocks)
        if box_key == "export":
            blocks.append(
                "CSV / Excel exports, saved reports, and log files written from "
                "this app when database backends are available.\n\n"
                f"Diagram status: {self._state_label(flow)}"
            )
            db_row = self._service_rows.get("Databases")
            if db_row:
                blocks.append(self._format_row_block(db_row))
            self._append_volumes(blocks, box_key)
            return title, "\n\n".join(blocks)
        if box_key == "storage":
            blocks.append(
                "All imported telemetry and forecast data written by the dashboard "
                "and collectors into configured database backends, plus export/"
                "log sinks.\n\n"
                f"Diagram status: {self._state_label(flow)}"
            )
            db_row = self._service_rows.get("Databases")
            if db_row:
                blocks.append(self._format_row_block(db_row))
            tab = self._tab
            inv = []
            if tab is not None and hasattr(tab, "import_inventory_lines"):
                inv = tab.import_inventory_lines()
            if not inv:
                inv = self._box_volumes.get("storage") or []
            if inv:
                blocks.append(
                    "Imports (volume · size · freshness):\n"
                    + "\n".join(f"  · {ln}" for ln in inv)
                )
            else:
                blocks.append(
                    "Imports: no logged rows found yet (enable a backend in "
                    "Setup & Info and wait for collectors to write)."
                )
            self._append_volumes(blocks, "database")
            self._append_volumes(blocks, "export")
            if tab is not None:
                stats = tab._retention_table_stats()
                blocks.append(
                    "Ring buffer (per table / store) — current policy "
                    "(use controls below to activate and set limits):"
                )
                for target in targets_for_box("storage"):
                    blocks.append(format_policy_block(target, stats.get(target.key)))
            return title, "\n\n".join(blocks)
        if box_key == "emqx":
            blocks.append(
                "MQTT broker. Feeds in: Grott’s decoded Growatt JSON, Tasmota "
                "tele/stat topics, and Modbus readings bridged onto MQTT. "
                "<b>Tasmota is two-way</b> on this broker — the dashboard also "
                "publishes <code>cmnd/…</code> (and can HTTP-poll devices). "
                "Modbus is still one-way into the broker — EMQX never drives "
                "Modbus registers itself.\n\n"
                f"Diagram status: {self._state_label(flow)}"
            )
            t = self._telemetry
            if t.get("uses_grott"):
                blocks.append(
                    f"Growatt telemetry source: {_growatt_source_label(t.get('source', GROWATT_TELEMETRY_API))}"
                )
                if t.get("fill_missing"):
                    n = int(t.get("api_filled_count") or 0)
                    blocks.append(
                        f"Fill missing Grott with API: on"
                        + (f" ({n} amber field(s) now)" if n else "")
                    )
            # Prefer stored Growatt/Tasmota volumes from the DB over "Not configured".
            self._append_volumes(blocks, "emqx")
            self._append_volumes(blocks, "grott")
            return title, "\n\n".join(blocks)
        if box_key == "grott":
            t = self._telemetry
            blocks.append(
                "Local GROTT proxy decodes the inverter’s Growatt cloud "
                "reporting stream into MQTT JSON. It is independent of "
                "Modbus (register path) and of the Growatt cloud REST API.\n\n"
                "In <b>Hybrid</b> mode Grott is the preferred live path; the "
                "Growatt API box is fallback when Grott is stale. "
                "Fill-missing patches individual registers from the cloud "
                "without switching the whole source.\n\n"
                "If the link flaps: Connectivity Details show disconnect / "
                "reconnect counts; right-click State → Show history lists "
                "each edge. The dashboard no longer tears down MQTT just "
                "because a payload is late (Shine often waits 1–5&nbsp;min).\n\n"
                f"Diagram status: {self._state_label(flow)}"
            )
            if t:
                blocks.append(
                    f"Configured source: {_growatt_source_label(t.get('source', GROWATT_TELEMETRY_API))}"
                )
            row = self._service_rows.get("Growatt local (Grott MQTT)")
            if row:
                blocks.append(self._format_row_block(row))
            self._append_volumes(blocks, "grott")
            return title, "\n\n".join(blocks)
        if box_key == "tasmota":
            blocks.append(
                "Tasmota plugs / CT monitors talk <b>both ways</b> on EMQX: "
                "devices publish <code>tele/</code> and <code>stat/</code> "
                "(watts, relay state); the dashboard publishes "
                "<code>cmnd/</code> (Power on/off, Status queries). "
                "HTTP poll (<code>/cm?cmnd=…</code>) is the same idea without MQTT.\n\n"
                f"Diagram status: {self._state_label(flow)}"
            )
            row = self._service_rows.get("Tasmota devices")
            if row:
                blocks.append(self._format_row_block(row))
            self._append_volumes(blocks, "tasmota")
            return title, "\n\n".join(blocks)
        blocks.append(f"Diagram status: {self._state_label(flow)}")
        for svc in services:
            row = self._service_rows.get(svc)
            if row:
                blocks.append(self._format_row_block(row))
            else:
                blocks.append(f"{svc}\n  No status row available.")
        if box_key == "modbus":
            blocks.append(
                "Modbus TCP/RTU on the LAN — one of the three Growatt connection "
                "methods (alongside Growatt API and GROTT). The dashboard talks "
                "to Modbus <b>directly</b> (reads and control writes). Readings "
                "can also be bridged onto EMQX (Modbus feeds the broker, never "
                "the reverse). Independent of Grott MQTT."
            )
        if box_key == "pvoutput":
            blocks.append(
                "Community output: this dashboard uploads live PV generation "
                "(and optional house load) to <b>pvoutput.org</b> via the Add "
                "Status API when enabled under Setup &amp; Info. "
                "Units are Wh / W; interval defaults to 5 minutes."
            )
            from energy_dashboard.fetch.pvoutput import load_pvoutput_config, load_pvoutput_status
            cfg = load_pvoutput_config()
            st = load_pvoutput_status()
            blocks.append(
                f"Enabled: {'yes' if cfg.enabled else 'no'} · "
                f"System Id: {cfg.system_id or '—'} · "
                f"Interval: {cfg.interval_s}s"
            )
            if st.get("last_ok_msg"):
                blocks.append(f"Last OK: {st.get('last_ok_ts', '—')} — {st['last_ok_msg']}")
            if st.get("last_error"):
                blocks.append(f"Last error: {st['last_error']}")
        if box_key == "wonderwatt":
            blocks.append(
                "<b>Wonderwatt</b> is a hosted optimiser that reads your plant "
                "from the <b>Growatt cloud</b> itself (parallel to this app — "
                "there is no public Wonderwatt upload API). "
                "Use the share link field below for forecast comparison on "
                "Potential Issues."
            )
            from energy_dashboard.fetch.wonderwatt import (
                load_wonderwatt_daily_kwh,
                load_wonderwatt_share_url,
                parse_wonderwatt_share_url,
            )
            parsed = parse_wonderwatt_share_url(load_wonderwatt_share_url())
            if parsed:
                blocks.append(f"Current wattid: <b>{parsed['wattid']}</b>")
            else:
                blocks.append("No share link saved yet.")
            n = len(load_wonderwatt_daily_kwh())
            if n:
                blocks.append(f"Pasted daily forecast days stored: {n}")
        self._append_volumes(blocks, box_key)
        if box_key in ("database", "export"):
            tab = self._tab
            stats = tab._retention_table_stats() if tab is not None else {}
            blocks.append(
                "Ring buffer (per table / store) — current policy "
                "(use controls below to activate and set limits):"
            )
            for target in targets_for_box(box_key):
                blocks.append(format_policy_block(target, stats.get(target.key)))
        return title, "\n\n".join(blocks)

    def _show_box_details(self, box_key):
        tab = self._tab
        if box_key in ("database", "export", "storage") and tab is not None:
            tab.open_ring_buffers_dialog(box_key)
            return
        title, body = self._format_box_details(box_key)
        dash = getattr(tab, "dash", None) if tab is not None else None
        if box_key == "wonderwatt":
            dlg = _WonderwattShareDialog(title, body, self, dash=dash)
            _prepare_dialog_buttons(dlg)
            dlg.exec()
            return
        login = build_component_login(box_key, dash)
        dlg = _ConnectivityDetailDialog(title, body, self, login=login)
        dlg.exec()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            key = self._hit_key_at(event.pos())
            if key:
                self._show_box_details(key)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        key = self._hit_key_at(event.pos())
        if key != self._hover_key:
            self._hover_key = key
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if key else Qt.CursorShape.ArrowCursor,
            )
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover_key is not None:
            self._hover_key = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()
        super().leaveEvent(event)

    def _draw_arch_link(self, p, path, state, *, color="#89b4fa",
                        idle_color="#566483", strength=1.0,
                        fr=None, to=None, health_key=None):
        """Draw a prebuilt connector path in the reference React style.
        ok = animated flow, idle = faint dashed, warn/bad = steady tint
        (no flashing). Highlighted links blink at double thickness only while
        the user has chosen Highlight on diagram."""
        hi = self._link_highlighted(fr=fr, to=to, health_key=health_key)
        blink = hi and self._highlight_blink_on
        thick = 2.0 if blink else (1.35 if hi else 1.0)
        strength = float(strength) * thick
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Degraded / alarm links: solid colour, no marching dashes — those
        # looked like the whole pipe was flashing red.
        if state in ("warn", "bad") and not blink:
            col = QColor("#f38ba8" if state == "bad" else "#fab387")
            if color and color not in ("#89b4fa", "#38bdf8", "#34d399", "#a78bfa", "#fbbf24"):
                col = QColor(color)
            base = QPen(QColor("#1e293b"))
            base.setWidthF(2.8 * thick)
            base.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(base)
            p.drawPath(path)
            halo = QPen(col)
            halo.setWidthF(2.2 * strength)
            halo.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(halo)
            p.drawPath(path)
            return
        if state == "ok" or blink:
            base = QPen(QColor("#1e293b"))
            base.setWidthF(2.8 * thick)
            base.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(base)
            p.drawPath(path)
            halo = QPen(QColor("#fbbf24" if blink else color))
            halo.setWidthF(1.4 * strength)
            halo.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(halo)
            p.drawPath(path)
            anim = QPen(QColor("#fde68a" if blink else color))
            anim.setWidthF(2.2 * strength)
            anim.setCapStyle(Qt.PenCapStyle.RoundCap)
            anim.setStyle(Qt.PenStyle.DashLine)
            anim.setDashPattern([2, 22])
            anim.setDashOffset(-self._phase * 22.0)
            p.setPen(anim)
            p.drawPath(path)
        elif state == "idle":
            base = QPen(QColor("#0f172a"))
            base.setWidthF(2.6 * thick)
            base.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(base)
            p.drawPath(path)
            pen = QPen(QColor("#fbbf24" if hi else idle_color))
            pen.setWidthF(1.3 * thick)
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern([5, 7])
            p.setPen(pen)
            p.drawPath(path)
        else:
            faint = QColor("#fbbf24" if hi else color)
            faint.setAlpha(200 if blink else (80 if state in ("warn", "bad") else 40))
            pen = QPen(faint)
            pen.setWidthF(1.3 * thick)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawPath(path)

    def _draw_probe_badge(self, p, rect, state_key):
        """Small status dot when a pipeline probe overlay is active."""
        c = self._sk_color(state_key)
        cx = rect.right() - 10.0
        cy = rect.top() + 10.0
        p.setPen(QPen(c.darker(120), 1.2))
        p.setBrush(c)
        p.drawEllipse(QPointF(cx, cy), 5.0, 5.0)

    def _draw_alarm_badge(self, p, rect, state_key, label: str = ""):
        """Corner alarm pip (+ optional short label) on a diagram card."""
        c = self._sk_color(state_key if state_key in ("warn", "bad") else "warn")
        cx = rect.right() - 11.0
        cy = rect.top() + 11.0
        # Soft halo so the pip reads on dark cards.
        halo = QColor(c)
        halo.setAlpha(90)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(cx, cy), 9.0, 9.0)
        p.setPen(QPen(QColor("#0f172a"), 1.2))
        p.setBrush(c)
        p.drawEllipse(QPointF(cx, cy), 5.5, 5.5)
        p.setPen(QColor("#0f172a"))
        p.setFont(QFont("Helvetica", 8, QFont.Bold))
        p.drawText(
            QRectF(cx - 5.0, cy - 5.0, 10.0, 10.0),
            Qt.AlignCenter,
            "!" if state_key != "bad" else "!!",
        )
        if label and rect.width() >= 90:
            p.setPen(c)
            p.setFont(QFont("Helvetica", 7, QFont.Bold))
            # Keep label inside the card, left of the pip.
            p.drawText(
                QRectF(rect.left() + 8.0, rect.top() + 2.0, rect.width() - 28.0, 12.0),
                Qt.AlignRight | Qt.AlignVCenter,
                "ALARM" if state_key == "bad" else "WARN",
            )

    def _draw_degradation_banner(self, p, rect: QRectF, severity: str, lines: list[str]) -> None:
        """Full-width strip explaining what is degraded and what is carrying live."""
        if not lines:
            return
        bg = QColor("#3f1d2e" if severity == "bad" else "#3a2e1d")
        edge = self._sk_color(severity if severity in ("warn", "bad") else "warn")
        p.setBrush(bg)
        p.setPen(QPen(edge, 1.6))
        p.drawRoundedRect(rect, 8, 8)
        tag = "DEGRADED" if severity != "bad" else "FAULT / DEGRADED"
        p.setPen(edge)
        p.setFont(QFont("Helvetica", 8, QFont.Bold))
        y = rect.top() + 4.0
        p.drawText(
            QRectF(rect.left() + 10, y, rect.width() - 20, 14),
            Qt.AlignLeft | Qt.AlignVCenter,
            tag,
        )
        y += 15.0
        p.setFont(QFont("Helvetica", 8))
        p.setPen(QColor("#fde68a" if severity != "bad" else "#fecdd3"))
        for line in lines:
            p.drawText(
                QRectF(rect.left() + 10, y, rect.width() - 20, 14),
                Qt.AlignLeft | Qt.AlignVCenter,
                line,
            )
            y += 15.0

    def paintEvent(self, event):
        # Uncaught Python exceptions inside paintEvent are a known PySide6
        # segfault vector (Shiboken + QWidget::paint). Swallow and log.
        try:
            self._paint_architecture(event)
        except Exception as exc:  # noqa: BLE001
            try:
                _log.exception("Connectivity", f"Architecture paint failed: {exc}")
            except Exception:
                pass

    def _paint_architecture(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        W = float(max(self.width(), 360))
        H = float(max(self.height(), 360))
        # Background gradient + subtle frame + grid (React-like style).
        grad = QLinearGradient(QPointF(0, 0), QPointF(W, H))
        grad.setColorAt(0.0, QColor("#020617"))
        grad.setColorAt(0.55, QColor("#0f172a"))
        grad.setColorAt(1.0, QColor("#020617"))
        p.fillRect(self.rect(), grad)
        frame = self.rect().adjusted(6, 4, -6, -4)
        p.setPen(QPen(QColor("#1e293b"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(frame, 10, 10)

        # Header (top strip, above the diagram canvas).
        deg_sev, deg_lines = self._degradation_banner_lines(max_lines=3)
        banner_h = 0.0
        if deg_lines:
            # Title + subtitle + padded finding lines.
            banner_h = 18.0 + 14.0 + 6.0 + len(deg_lines) * 15.0 + 8.0
        else:
            banner_h = 40.0

        p.setPen(QColor("#f8fafc"))
        p.setFont(QFont("Helvetica", 10, QFont.Bold))
        p.drawText(QRectF(16, 8, W - 32, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   "Energy Data Architecture")
        p.setPen(QColor("#94a3b8"))
        p.setFont(QFont("Helvetica", 8))
        p.drawText(QRectF(16, 26, W - 32, 14), Qt.AlignLeft | Qt.AlignVCenter,
                   "Producers -> brokers -> dashboard <-> AI / Databases")

        # Legend (right-aligned in the header strip).
        legend = [
            ("Internet", "#38bdf8"),
            ("Home LAN", "#34d399"),
            ("Storage", "#a78bfa"),
            ("Control", "#fbbf24"),
            ("Warn", "#fab387"),
            ("Alarm", "#f38ba8"),
        ]
        p.setFont(QFont("Helvetica", 7))
        fm = p.fontMetrics()
        gap = 14.0
        seg = [(txt, col, float(fm.horizontalAdvance(txt))) for txt, col in legend]
        total = sum(11.0 + wd for _, _, wd in seg) + gap * (len(seg) - 1)
        lx = max(16.0, W - 16.0 - total)
        lyc = 18.0
        for txt, col, wd in seg:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(col))
            p.drawEllipse(QPointF(lx + 3.0, lyc), 3.0, 3.0)
            p.setPen(QColor("#cbd5e1"))
            p.drawText(QRectF(lx + 9.0, lyc - 6.0, wd + 4.0, 12.0),
                       Qt.AlignLeft | Qt.AlignVCenter, txt)
            lx += 11.0 + wd + gap

        if deg_lines:
            self._draw_degradation_banner(
                p, QRectF(12, 42, W - 24, banner_h - 40.0), deg_sev, deg_lines,
            )

        # Blueprint -> widget transform (non-uniform, like React preserveAspectRatio='none').
        layout = self._compute_layout(W, H, header_h=max(46.0, banner_h + 6.0))
        bp = layout["bp"]
        ax, ay, sx, sy = layout["ax"], layout["ay"], layout["sx"], layout["sy"]
        xform = QTransform()
        xform.translate(ax, ay)
        xform.scale(sx, sy)
        nodes = {k: xform.mapRect(r) for k, r in bp.items()}
        self._hit_regions = []

        # Subtle grid confined to the diagram canvas.
        p.setPen(QPen(QColor("#16213a"), 1))
        cx0, cy0 = ax, ay
        cx1 = ax + self._ARCH_VBW * sx
        cy1 = ay + self._ARCH_VBH * sy
        gx = cx0
        while gx <= cx1:
            p.drawLine(QPointF(gx, cy0), QPointF(gx, cy1))
            gx += 40.0
        gy = cy0
        while gy <= cy1:
            p.drawLine(QPointF(cx0, gy), QPointF(cx1, gy))
            gy += 40.0

        # ---- Connector geometry: built in blueprint space, then scaled. ----
        DIR = {"left": (-1.0, 0.0), "right": (1.0, 0.0),
               "top": (0.0, -1.0), "bottom": (0.0, 1.0)}

        def bp_edge(key, edge, t):
            r = bp[key]
            if edge == "left":
                return (r.left(), r.top() + t * r.height())
            if edge == "right":
                return (r.right(), r.top() + t * r.height())
            if edge == "top":
                return (r.left() + t * r.width(), r.top())
            return (r.left() + t * r.width(), r.bottom())

        def build(fr, fe, ft, to, te, tt, straight=False, curveK=None):
            p0 = bp_edge(fr, fe, ft)
            p1 = bp_edge(to, te, tt)
            path = QPainterPath(QPointF(p0[0], p0[1]))
            if straight:
                path.lineTo(QPointF(p1[0], p1[1]))
            else:
                d0 = DIR[fe]
                d1 = DIR[te]
                dist = float(np.hypot(p1[0] - p0[0], p1[1] - p0[1]))
                k = curveK if curveK is not None else max(35.0, min(dist * 0.42, 110.0))
                c0 = QPointF(p0[0] + d0[0] * k, p0[1] + d0[1] * k)
                c1 = QPointF(p1[0] + d1[0] * k, p1[1] + d1[1] * k)
                path.cubicTo(c0, c1, QPointF(p1[0], p1[1]))
            return xform.map(path)

        sky, emerald, violet, amber = "#38bdf8", "#34d399", "#a78bfa", "#fbbf24"

        # Dashboard left-edge ports: equal vertical spacing with 12 px inset
        # from the top and bottom of the box (blueprint space). Top→bottom
        # matches the left-side stack so lanes nest and never cross:
        #   Growatt API data / Growatt API control
        #   EMQX data / EMQX control
        #   Modbus data (direct) / Modbus control
        # Two-way peers use parallel lanes (upper↔upper, lower↔lower).
        # Modbus also feeds EMQX (separate short link); that does not replace
        # the direct Modbus → Dashboard data lane.
        _dash_left = self._even_edge_fractions(
            6, bp["dashboard"].height(), pad_px=12.0,
        )
        (
            _dl_growatt_data,
            _dl_growatt_ctrl,
            _dl_emqx_data,
            _dl_emqx_ctrl,
            _dl_modbus_data,
            _dl_modbus_ctrl,
        ) = _dash_left

        # Inverter right-edge ports: three Growatt pipes × (data out + return).
        # Upper of each pair = telemetry away from the inverter; lower = return
        # (cloud schedule push, Modbus writes, Grott tap topology). Parallel so
        # reverse lines do not sit on top of the forward lanes.
        _inv_right = self._even_edge_fractions(
            6, bp["inverter"].height(), pad_px=10.0,
        )
        (
            _ir_cloud_data,
            _ir_cloud_ret,
            _ir_grott_data,
            _ir_grott_ret,
            _ir_modbus_data,
            _ir_modbus_ret,
        ) = _inv_right

        # Forward data connections — three Growatt methods only:
        #   inverter → Growatt API (cloud REST) → dashboard (top lane)
        #   inverter → Grott → EMQX → dashboard
        #   inverter → Modbus (TCP/RTU) → dashboard (direct)
        #                    ↘ EMQX (bridge; broker never drives Modbus)
        # Planar routing: sources are stacked in the same top-to-bottom order
        # as their entry points, so no data line crosses another data line.
        # (fr, fe, ft, to, te, tt, color, straight, curveK, health_key)
        data_conns = [
            # Inverter → Cloud / Grott / Modbus (upper port of each pair).
            ("inverter", "right", _ir_cloud_data, "growatt_cloud", "left", 0.30, sky, False, 50.0, "growatt_cloud"),
            ("inverter", "right", _ir_grott_data, "grott", "left", 0.30, emerald, False, 50.0, "grott"),
            ("inverter", "right", _ir_modbus_data, "modbus", "left", 0.30, emerald, False, 60.0, "modbus"),
            # Growatt API → dashboard: upper parallel lane (stays above EMQX).
            ("growatt_cloud", "right", 0.30, "dashboard", "left", _dl_growatt_data, sky, False, None, "growatt_cloud"),
            # GROTT → EMQX: dedicated upper lane (must not share endpoints with
            # any amber return — that used to hide this telemetry flow).
            ("grott", "right", 0.30, "emqx", "left", 0.18, emerald, False, 30.0, "grott"),
            # Tasmota ↔ EMQX is two-way MQTT on the same LAN broker:
            #   tele/ + stat/  device → broker (upper lane)
            #   cmnd/         broker → device (lower lane)
            ("tasmota", "right", 0.3, "emqx", "left", 0.5, emerald, False, 30.0, "tasmota"),
            ("emqx", "left", 0.75, "tasmota", "right", 0.7, emerald, False, 30.0, "tasmota"),
            # Modbus → EMQX bridge (one-way into the broker) — kept in addition
            # to the direct Modbus → Dashboard lane below.
            ("modbus", "right", 0.35, "emqx", "left", 0.9, emerald, False, 40.0, "modbus"),
            # EMQX → dashboard: upper of the EMQX pair (below Growatt lanes).
            ("emqx", "right", 0.30, "dashboard", "left", _dl_emqx_data, emerald, False, None, "emqx"),
            # Modbus → dashboard direct (does not go through EMQX).
            ("modbus", "right", 0.70, "dashboard", "left", _dl_modbus_data, emerald, False, 70.0, "modbus"),
            # AI ↔ Dashboard is two-way: live/state feed up, optimise/schedule down.
            ("dashboard", "top", 0.15, "ai", "bottom", 0.25, violet, False, 20.0, None),
            ("ai", "bottom", 0.75, "dashboard", "top", 0.35, amber, False, 20.0, None),
            # Databases ↔ Dashboard is two-way: writes/logs down, reads/query up.
            ("dashboard", "top", 0.65, "storage", "bottom", 0.25, violet, False, 20.0, None),
            ("storage", "bottom", 0.75, "dashboard", "top", 0.85, violet, False, 20.0, None),
            # AI Controller ↔ Databases (same top row).
            ("ai", "right", 0.5, "storage", "left", 0.5, violet, False, 25.0, None),
            # Bottom-row peers → dashboard (left→right attach order matches box order).
            ("octopus", "top", 0.5, "dashboard", "bottom", 0.12, sky, False, 70.0, "octopus"),
            ("forecast", "top", 0.5, "dashboard", "bottom", 0.32, sky, False, 70.0, "forecast"),
            ("dashboard", "bottom", 0.68, "pvoutput", "top", 0.5, sky, False, 70.0, "pvoutput"),
            ("dashboard", "bottom", 0.88, "wonderwatt", "top", 0.5, sky, False, 70.0, "wonderwatt"),
        ]
        bat_keys = layout.get("battery_keys") or []
        bat_packs = layout.get("battery_packs") or []
        inv_box = bp.get("inverter")
        for i, key in enumerate(bat_keys):
            if key not in bp:
                continue
            # Attach at each pack's vertical mid-point along the inverter edge.
            t = (i + 0.5) / max(1, len(bat_keys))
            if inv_box is not None and inv_box.height() > 0:
                mid_y = bp[key].center().y()
                t = (mid_y - inv_box.top()) / inv_box.height()
                t = max(0.05, min(0.95, float(t)))
            data_conns.append(
                (key, "right", 0.5, "inverter", "left", t, emerald, True, None, "modbus")
            )
        probe_link_map = {
            ("inverter", "grott"): "inv_grott",
            ("grott", "emqx"): "grott_emqx",
            ("emqx", "dashboard"): "emqx_dashboard",
        }
        for fr, fe, ft, to, te, tt, color, straight, ck, hk in data_conns:
            path = build(fr, fe, ft, to, te, tt, straight=straight, curveK=ck)
            plink = probe_link_map.get((fr, to))
            probe_st = self._probe_link_state(plink) if plink else None
            state = probe_st if probe_st is not None else self._link_flow_state(hk, fr=fr, to=to)
            link_color = color
            if probe_st == "bad":
                link_color = "#f38ba8"
            elif probe_st == "warn":
                link_color = "#fab387"
            elif probe_st == "ok":
                link_color = "#34d399"
            # Battery → inverter: colour by pack alert when known.
            if fr.startswith("battery_") and probe_st is None:
                pack = next(
                    (p for p in bat_packs if f"battery_{p.get('index')}" == fr),
                    None,
                )
                alert = (pack or {}).get("alert") or "off"
                # Live battery alarms (low SOC / sun wasted) escalate the pack link.
                a_sk = self._alarm_state_for_edge(fr, to)
                if a_sk == "bad" or alert == "fault":
                    state, link_color = "bad", "#f38ba8"
                elif a_sk == "warn" or alert == "warn":
                    state, link_color = "warn", "#fab387"
                elif alert == "ok":
                    state, link_color = "ok", emerald
                else:
                    state, link_color = "off", "#64748b"
            else:
                a_sk = self._alarm_state_for_edge(fr, to)
                # Hybrid fallback: Grott path looks degraded; cloud→dashboard is the
                # live carrier (keep flowing, but amber so the switch is obvious).
                t = self._telemetry or {}
                if t.get("hybrid_fallback"):
                    if (fr, to) in (
                        ("inverter", "grott"),
                        ("grott", "emqx"),
                        ("emqx", "dashboard"),
                        ("grott", "inverter"),
                        ("emqx", "grott"),
                    ):
                        a_sk = self._worst_state(
                            a_sk,
                            "bad" if not t.get("grott_connected") else "warn",
                        )
                    elif (fr, to) == ("growatt_cloud", "dashboard"):
                        # Carrying live — show as warn (amber flow), not healthy emerald.
                        a_sk = self._worst_state(a_sk, "warn")
                if a_sk in ("warn", "bad"):
                    state = self._worst_state(state, a_sk) or a_sk
                    if a_sk == "bad" or state == "bad":
                        link_color = "#f38ba8"
                    elif a_sk == "warn":
                        link_color = "#fab387"
            self._draw_arch_link(
                p, path, state, color=link_color, fr=fr, to=to, health_key=hk,
            )

        # Hybrid fallback path (Grott ↔ cloud API) — dashed amber when configured.
        if self._telemetry.get("source") == GROWATT_TELEMETRY_HYBRID:
            path = build("grott", "top", 0.5, "growatt_cloud", "bottom", 0.5, straight=False, curveK=45.0)
            state = self._link_flow_state("grott", fr="grott", to="growatt_cloud")
            self._draw_arch_link(
                p, path, state, color="#fbbf24", idle_color="#a16207", strength=0.65,
                fr="grott", to="growatt_cloud", health_key="grott",
            )

        # Reverse / control — parallel lower lane of each pair so amber returns
        # do not sit on the emerald/sky data lines (same endpoints used to hide
        # Grott→EMQX and inverter→Cloud/Grott/Modbus).
        #   Cloud / Grott / Modbus → inverter (lower inverter ports)
        #   Dashboard → Cloud / EMQX / Modbus (lower dashboard left ports)
        #   EMQX → Grott topology return (lower Grott↔EMQX lane; broker never
        #   drives Modbus — Modbus→EMQX stays one-way).
        # (fr, fe, ft, to, te, tt, active, straight, curveK)
        ctrl_conns = [
            ("dashboard", "left", _dl_growatt_ctrl, "growatt_cloud", "right", 0.70, False, False, None),
            # Cloud → inverter (schedule / mode push path).
            ("growatt_cloud", "left", 0.70, "inverter", "right", _ir_cloud_ret, False, False, 50.0),
            ("dashboard", "left", _dl_emqx_ctrl, "emqx", "right", 0.70, True, False, None),
            # EMQX → Grott return on a *lower* lane — keeps Grott→EMQX data clear.
            ("emqx", "left", 0.32, "grott", "right", 0.70, True, False, 30.0),
            (
                "dashboard", "left", _dl_modbus_ctrl, "modbus", "right", 0.85,
                # Amber only when the user has opted in to Modbus inverter writes.
                bool(getattr(self._tab, "_modbus_writes_active", False)),
                False, 70.0,
            ),
            ("modbus", "left", 0.70, "inverter", "right", _ir_modbus_ret, True, False, 60.0),
            ("grott", "left", 0.70, "inverter", "right", _ir_grott_ret, True, False, 50.0),
        ]
        for fr, fe, ft, to, te, tt, active, straight, ck in ctrl_conns:
            path = build(fr, fe, ft, to, te, tt, straight=straight, curveK=ck)
            state = "ok" if active else "idle"
            color = amber
            a_sk = self._alarm_state_for_edge(fr, to)
            if a_sk in ("warn", "bad"):
                state = a_sk
                color = "#f38ba8" if a_sk == "bad" else "#fab387"
            self._draw_arch_link(
                p, path, state,
                color=color, idle_color="#a16207",
                fr=fr, to=to, health_key=to if to != "inverter" else fr,
            )

        # ---- Node cards ----
        cards = [
            ("inverter", "Growatt Inverter", "", "lan", "modbus", True, False),
            ("tasmota", "Tasmota", "MQTT tele ↔ cmnd", "lan", "tasmota", False, False),
            ("octopus", "Octopus", "REST / GraphQL", "internet", "octopus", False, False),
            ("forecast", "PV forecast", "Forecast.Solar · Open-Meteo", "internet", "forecast", False, False),
            ("growatt_cloud", "Growatt API", "cloud REST", "internet", "growatt_cloud", False, False),
            ("grott", "GROTT", "MQTT primary path", "lan", "grott", False, False),
            ("modbus", "Modbus", "↔ Dashboard · → EMQX", "lan", "modbus", False, False),
            ("emqx", "EMQX", "MQTT broker", "lan", "emqx", False, False),
            ("ai", "AI Controller", "↔ optimise", "ai", "ai", False, False),
            ("storage", "Databases", "↔ read / write", "data", "storage", False, False),
            ("dashboard", "Energy Dashboard", "publish / subscribe", "internet", "dashboard", False, True),
            ("pvoutput", "PVOutput.org", "live Add Status upload", "internet", "pvoutput", False, False),
            ("wonderwatt", "Wonderwatt.com", "share · Growatt cloud peer", "internet", "wonderwatt", False, False),
        ]
        group_color = {
            "internet": "#38bdf8",
            "lan": "#34d399",
            "data": "#a78bfa",
            "ai": "#fbbf24",
        }
        probe_card_keys = {
            "modbus": "modbus",
            "grott": "grott",
            "emqx": "emqx",
            "dashboard": "dashboard",
        }
        # Batteries first (left column), then the rest of the graph.
        try:
            bat_alarm = self._alarm_state_for_box("battery")
            for i, pack in enumerate(bat_packs):
                key = bat_keys[i] if i < len(bat_keys) else f"battery_{pack.get('index', i + 1)}"
                if key not in nodes:
                    continue
                rect = nodes[key]
                self._hit_regions.append((key, f"Battery {pack.get('index', i + 1)}", rect))
                draw_pack = dict(pack)
                if bat_alarm == "bad" and draw_pack.get("alert") not in ("fault", "bad"):
                    draw_pack["alert"] = "fault"
                elif bat_alarm == "warn" and draw_pack.get("alert") in ("ok", "off", "", None):
                    draw_pack["alert"] = "warn"
                self._draw_battery_arch_card(
                    p,
                    rect,
                    draw_pack,
                    hover=(self._hover_key == key),
                )
                if bat_alarm in ("warn", "bad"):
                    self._draw_alarm_badge(
                        p, rect, bat_alarm, self._alarm_badge_label("battery"),
                    )
        except Exception:
            pass
        for key, title, sub, grp, health_key, vertical, main in cards:
            rect = nodes[key]
            title, sub = self._diagram_card_copy(key, title, sub)
            click_key = health_key if health_key in _CONNECTIVITY_BOX_SERVICES else None
            if key == "inverter":
                click_key = "inverter"
            if click_key is not None:
                self._hit_regions.append((click_key, title, rect))
            display_sk = self._box_display_state(key, health_key if key != "inverter" else None)
            # Live alarms get the ALARM badge. Hybrid fallback / connectivity
            # degradation also get a WARN badge so the diagram explains itself.
            alarm_sk = self._alarm_state_for_box(key)
            t = self._telemetry or {}
            fallback_box = t.get("hybrid_fallback") and key in (
                "grott", "emqx", "growatt_cloud", "inverter",
            )
            show_badge = alarm_sk in ("warn", "bad") or bool(fallback_box and display_sk in ("warn", "bad"))
            if alarm_sk in ("warn", "bad"):
                border_sk = alarm_sk
            elif display_sk in ("warn", "bad"):
                border_sk = display_sk
            else:
                border_sk = None
            if show_badge and alarm_sk:
                alarm_label = self._alarm_badge_label(key)
            elif show_badge and fallback_box:
                if key == "growatt_cloud":
                    alarm_label = "Live via cloud fallback"
                elif key == "grott":
                    alarm_label = "Stale / down — not primary"
                elif key == "emqx":
                    alarm_label = "Grott path degraded"
                else:
                    alarm_label = "Hybrid degraded"
            else:
                alarm_label = ""
            self._draw_arch_card(
                p,
                rect,
                title,
                sub,
                accent=group_color.get(grp, "#94a3b8"),
                hover=(
                    (click_key is not None and self._hover_key == click_key)
                    or (key == "inverter" and self._hover_key == "inverter")
                ),
                main=main,
                vertical=vertical,
                state_key=border_sk,
                alarm_label=alarm_label,
                show_badge=show_badge,
            )
            ph = probe_card_keys.get(key)
            if ph:
                pst = self._probe_hop_state(ph)
                if pst:
                    self._draw_probe_badge(p, rect, pst)

class ConnectivityStatusTab(QWidget):
    """Live connectivity overview for upstream services and local backends."""

    _STATE_COLORS = {
        'ok': '#a6e3a1',
        'warn': '#fab387',
        'bad': '#f38ba8',
        'idle': _UI_BLUE,
        'off': '#6c7086',
    }

    def __init__(self, dash):
        super().__init__()
        self.dash = dash
        self._inv = Invoker(self)
        self._db_results = None
        self._db_test_time = "--"
        self._growatt_modbus_probe_running = False
        self._suppress_modbus_probe = False
        self._growatt_modbus_cache = {
            'state_key': 'idle',
            'state_text': '—',
            'detail': 'Not probed yet',
            'fresh': '--',
        }
        self._growatt_http_probe_running = False
        self._suppress_http_probe = False
        self._growatt_http_cache = {
            'state_key': 'idle',
            'state_text': '—',
            'detail': 'Not probed yet',
            'fresh': '--',
        }
        self._pipeline_probe_running = False
        self._pipeline_probe_status = ""
        self._size_cache = {}
        self._size_cache_at = 0.0
        self._size_cache_building = False
        self._table_info = {}
        self._last_db_test_mono = 0.0
        self._db_test_building = False
        self._last_http_probe_mono = 0.0
        self._last_modbus_probe_mono = 0.0
        self._volumes_busy = False
        self._last_volumes_mono = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(15000)
        self._timer.timeout.connect(self._on_status_timer)
        self.build_ui()
        self.refresh_status(test_db=False)
        self._schedule_size_cache_rebuild()
        self._timer.start()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        ctrl = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Status")
        self.refresh_btn.clicked.connect(
            lambda: self.refresh_status(test_db=False, allow_local_probes=True)
        )
        ctrl.addWidget(self.refresh_btn)
        self.test_db_btn = QPushButton("Test Databases")
        self.test_db_btn.clicked.connect(
            lambda: self.refresh_status(test_db=True, allow_local_probes=False)
        )
        ctrl.addWidget(self.test_db_btn)
        self.ring_buffers_btn = QPushButton("Ring buffers…")
        self.ring_buffers_btn.setToolTip(
            "Per-table ring-buffer limits (max rows, age, size) for logged data"
        )
        self.ring_buffers_btn.clicked.connect(lambda: self.open_ring_buffers_dialog("database"))
        ctrl.addWidget(self.ring_buffers_btn)
        self.probe_pipeline_btn = QPushButton("Probe pipeline…")
        self.probe_pipeline_btn.setToolTip(
            "Trace the three Growatt paths (cloud API, Grott→EMQX, Modbus) "
            "plus EMQX / dashboard ingest and highlight breaks"
        )
        self.probe_pipeline_btn.clicked.connect(self._start_pipeline_probe)
        ctrl.addWidget(self.probe_pipeline_btn)
        self.probe_status_label = QLabel("")
        self.probe_status_label.setStyleSheet("color: #89b4fa; font-size: 11px;")
        ctrl.addWidget(self.probe_status_label)
        self.updated_label = QLabel("Updated: --")
        self.updated_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        ctrl.addWidget(self.updated_label)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "Service", "State", "Details", "Last / freshness", "Table size",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget { alternate-background-color: #252536; }"
        )
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_state_context_menu)
        self.table.itemSelectionChanged.connect(self._on_row_selection_changed)
        qtable_set_column_width_key(self.table, "connectivity_status")
        qtable_prepare_interactive_columns(self.table)
        qtable_restore_column_widths(self.table, "connectivity_status", resize_if_no_saved=True)
        qtable_attach_column_width_persistence(self.table)

        self._prev_row_states: dict[str, str] = {}
        self._flow_diagram = _ConnectivityFlowDiagram(self)
        self.table.setMinimumHeight(96)
        self._flow_diagram.setMinimumHeight(320)

        self._table_diagram_split = QSplitter(Qt.Vertical)
        self._table_diagram_split.setChildrenCollapsible(False)
        self._table_diagram_split.setStyleSheet(
            "QSplitter::handle { background: #313244; }"
            "QSplitter::handle:hover { background: #45475a; }"
            "QSplitter::handle:vertical { height: 6px; }"
        )
        self._table_diagram_split.addWidget(self.table)
        self._table_diagram_split.addWidget(self._flow_diagram)
        self._table_diagram_split.setStretchFactor(0, 2)
        self._table_diagram_split.setStretchFactor(1, 3)
        try:
            _ss = QSettings("PowerModel", "EnergyDashboard2")
            _saved = _ss.value("ui/connectivity_table_diagram_split")
            if _saved and self._table_diagram_split.restoreState(_saved):
                pass
            else:
                self._table_diagram_split.setSizes([260, 480])
        except Exception:
            self._table_diagram_split.setSizes([260, 480])
        self._table_diagram_split.splitterMoved.connect(self._persist_table_diagram_split)
        layout.addWidget(self._table_diagram_split, 1)

        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setFrameShape(QFrame.Shape.NoFrame)
        self.summary.setMaximumHeight(74)
        self.summary.setMinimumHeight(58)
        self.summary.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.summary.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.summary.setStyleSheet(
            "QTextEdit { background: #181825; color: #cdd6f4; font-size: 10px; }"
        )
        layout.addWidget(self.summary, 0)

    def _persist_table_diagram_split(self, *_):
        try:
            _ss = QSettings("PowerModel", "EnergyDashboard2")
            _ss.setValue(
                "ui/connectivity_table_diagram_split",
                self._table_diagram_split.saveState(),
            )
            _ss.sync()
        except Exception:
            pass

    def open_ring_buffers_dialog(self, box_key: str = "database") -> None:
        """Open per-table ring-buffer controls (also used when clicking Databases pill)."""
        if box_key not in ("database", "export", "storage"):
            box_key = "database"
        # Ensure size/freshness cache is warm so the summary lists real volumes.
        if not getattr(self, "_table_info", None):
            self._schedule_size_cache_rebuild()
        _, body = self._flow_diagram._format_box_details(box_key)
        dlg = ConnectivityRetentionDialog(
            box_key,
            body,
            table_stats=self._retention_table_stats(),
            data_logger=self.dash.data_logger,
            dash=self.dash,
            parent=self,
        )
        dlg.exec()

    @staticmethod
    def _fmt_activity_freshness(raw_ts) -> str:
        """Human age from a DB MAX(timestamp) / last_activity string."""
        if not raw_ts or raw_ts == "file on disk":
            return "--" if not raw_ts else str(raw_ts)
        from energy_dashboard.db.health_stats import _parse_ts

        parsed = _parse_ts(raw_ts)
        if parsed is None:
            return str(raw_ts)
        now = datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age_s = max(0.0, (now - parsed).total_seconds())
        if age_s < 60:
            return f"{age_s:.0f}s ago"
        if age_s < 3600:
            return f"{age_s / 60.0:.1f}m ago"
        if age_s < 86400:
            return f"{age_s / 3600.0:.1f}h ago"
        return f"{age_s / 86400.0:.1f}d ago"

    def _format_table_volume_line(self, label: str, info: dict | None, *, backend: str | None = None) -> str:
        """One inventory line: Label: N rows · size · freshness."""
        if not info:
            return f"{label}: no data"
        bits = []
        if backend:
            bits.append(str(backend))
        rows_n = info.get("row_count")
        if rows_n is not None:
            bits.append(f"{self._fmt_num(rows_n)} rows")
        sz = info.get("size_human")
        if sz:
            bits.append(str(sz))
        fresh = self._fmt_activity_freshness(info.get("last_activity"))
        if fresh and fresh != "--":
            bits.append(f"fresh {fresh}")
        elif info.get("last_activity"):
            bits.append(f"last {info['last_activity']}")
        return f"{label}: " + " · ".join(bits) if bits else f"{label}: empty"

    def import_inventory_lines(self) -> list[str]:
        """All logged imports from the size/health cache (volume · size · freshness)."""
        info_map = getattr(self, "_table_info", None) or {}
        lines = []
        for table, label, _boxes in _IMPORT_TABLE_META:
            info = info_map.get(table)
            if info and int(info.get("row_count") or 0) == 0 and not info.get("last_activity"):
                lines.append(f"{label}: empty (0 rows)")
            elif info:
                lines.append(self._format_table_volume_line(label, info))
            else:
                lines.append(f"{label}: not found in configured backends")
        # Console export sink
        log_path = Path.home() / ".energy_dashboard_console.jsonl"
        if log_path.is_file():
            try:
                n = sum(1 for _ in log_path.open(encoding="utf-8"))
                sz = _fmt_size(log_path.stat().st_size)
                lines.append(f"Console log: {self._fmt_num(n)} lines · {sz}")
            except OSError:
                pass
        return lines

    def import_inventory_lines_for_box(self, box_key: str) -> list[str]:
        """Subset of import inventory lines that belong to a diagram box."""
        if box_key in ("storage", "database", "export"):
            return self.import_inventory_lines()
        info_map = getattr(self, "_table_info", None) or {}
        lines = []
        for table, label, boxes in _IMPORT_TABLE_META:
            if box_key not in boxes:
                continue
            info = info_map.get(table)
            if info:
                lines.append(self._format_table_volume_line(label, info))
        return lines

    def _latest_age_text(self, *dfs):
        latest = None
        for df in dfs:
            if df is not None and not df.empty and 'interval_start' in df.columns:
                ts = df['interval_start'].max()
                if latest is None or ts > latest:
                    latest = ts
        if latest is None:
            return "--"
        now = datetime.now(latest.tzinfo) if getattr(latest, 'tzinfo', None) else datetime.now()
        age_min = max(0.0, (now - latest).total_seconds() / 60.0)
        if age_min < 60:
            return f"{age_min:.0f}m ago"
        return f"{age_min/60:.1f}h ago"

    def _set_row(
        self,
        row,
        service,
        state_text,
        state_key,
        details,
        freshness,
        table_size="--",
    ):
        color = self._STATE_COLORS.get(state_key, '#cdd6f4')
        vals = [service, state_text, details, freshness, table_size]
        meta = _SERVICE_ROW_META.get(str(service)) or {}
        service_key = meta.get("key", "")
        for col, val in enumerate(vals):
            item = QTableWidgetItem(str(val))
            if col == 0 and service_key:
                item.setData(Qt.ItemDataRole.UserRole, service_key)
            if col == 1:
                item.setForeground(QBrush(QColor(color)))
                f = item.font()
                f.setBold(True)
                item.setFont(f)
                item.setToolTip(
                    "Right-click for context actions "
                    "(Test / Downtime / Alarms / Highlight / History…)"
                )
                if service_key:
                    item.setData(Qt.ItemDataRole.UserRole, service_key)
            elif col == 4:
                item.setForeground(QBrush(QColor("#a6adc8")))
            self.table.setItem(row, col, item)

    @staticmethod
    def _service_key_for_label(label: str) -> str:
        meta = _SERVICE_ROW_META.get(label) or {}
        return str(meta.get("key") or "")

    def _row_is_disabled(self, service_key: str) -> bool:
        if not service_key:
            return False
        s = QSettings("PowerModel", "EnergyDashboard2")
        return bool(s.value(f"{_DISABLED_QS_PREFIX}{service_key}", False, type=bool))

    def _set_row_disabled(self, service_key: str, disabled: bool) -> None:
        s = QSettings("PowerModel", "EnergyDashboard2")
        key = f"{_DISABLED_QS_PREFIX}{service_key}"
        if disabled:
            s.setValue(key, True)
        else:
            s.remove(key)
        s.sync()

    def _on_row_selection_changed(self):
        """Selecting a service row blinks only that row’s architecture edges."""
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            self._flow_diagram.clear_link_highlight()
            return
        svc_item = self.table.item(rows[0].row(), 0)
        if svc_item is None:
            return
        label = svc_item.text()
        meta = _SERVICE_ROW_META.get(label)
        if meta is None:
            self._flow_diagram.clear_link_highlight()
            return
        self._highlight_service_on_diagram(label, meta)

    def _on_state_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid() or index.column() != 1:
            return
        row = index.row()
        svc_item = self.table.item(row, 0)
        if svc_item is None:
            return
        label = svc_item.text()
        meta = _SERVICE_ROW_META.get(label)
        if meta is None:
            return
        service_key = meta["key"]
        can_disable = bool(meta.get("can_disable", True))
        can_test = bool(meta.get("can_test", False))
        can_downtime = bool(meta.get("can_downtime", False))
        can_alarms = bool(meta.get("can_show_alarms", True))
        goto_attr = str(meta.get("goto_tab_attr") or "")
        goto_label = str(meta.get("goto_tab_label") or "")

        menu = QMenu(self)
        act_toggle = None
        if service_key == "inverter_write":
            from energy_dashboard.config import growatt_modbus_writes_allowed

            s = QSettings("PowerModel", "EnergyDashboard2")
            mb_on = growatt_modbus_writes_allowed(self.dash.app_params, s)
            act_toggle = menu.addAction(
                "Disable Modbus inverter writes"
                if mb_on
                else "Enable Modbus inverter writes"
            )
        elif can_disable:
            disabled = self._row_is_disabled(service_key)
            act_toggle = menu.addAction("Enable" if disabled else "Disable")

        act_goto = None
        if goto_attr and goto_label:
            act_goto = menu.addAction(goto_label)
        act_test = menu.addAction("Test Connection") if can_test else None
        act_downtime = menu.addAction("Show Downtime") if can_downtime else None
        act_alarms = menu.addAction("Show Alarms") if can_alarms else None
        if act_goto or act_test or act_downtime or act_alarms:
            menu.addSeparator()
        act_highlight = menu.addAction("Highlight on diagram below")
        act_history = menu.addAction("Show history")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if act_toggle is not None and chosen is act_toggle:
            if service_key == "inverter_write":
                self._toggle_modbus_inverter_writes(label)
            else:
                self._toggle_service_disabled(
                    label,
                    service_key,
                    currently_disabled=self._row_is_disabled(service_key),
                )
        elif act_goto is not None and chosen is act_goto:
            self._goto_service_tab(label, goto_attr)
        elif act_test is not None and chosen is act_test:
            self._test_service_connection(label, service_key)
        elif act_downtime is not None and chosen is act_downtime:
            self._show_service_downtime(label, service_key)
        elif act_alarms is not None and chosen is act_alarms:
            self._show_service_alarms(label, service_key)
        elif chosen is act_highlight:
            self._highlight_service_on_diagram(label, meta)
        elif chosen is act_history:
            self._show_service_history(label, service_key)

    def _goto_service_tab(self, label: str, tab_attr: str) -> None:
        """Jump to the related main window page (e.g. Tasmota Devices)."""
        dash = self.dash
        page = getattr(dash, tab_attr, None) if dash is not None else None
        if page is None or not hasattr(dash, "show_main_page"):
            self.dash.set_status(f"{label}: related page is not available.")
            return
        ok = dash.show_main_page(page)
        if ok:
            self.dash.set_status(f"Opened {label.replace(' devices', '')} page.")
        else:
            self.dash.set_status(
                f"{label}: page is hidden — enable it under Setup tab visibility."
            )

    def _toggle_modbus_inverter_writes(self, label: str) -> None:
        """Opt-in / opt-out local Modbus inverter writes (safety-gated)."""
        from energy_dashboard.config import (
            growatt_modbus_path_configured,
            growatt_modbus_writes_allowed,
            write_growatt_modbus_writes_enabled,
        )
        from energy_dashboard.db.connectivity_events import log_connectivity_event

        p = self.dash.app_params
        s = QSettings("PowerModel", "EnergyDashboard2")
        if not growatt_modbus_path_configured(p):
            self.dash.set_status(
                "Enable a Modbus mode under Setup & Info first, then Enable writes here."
            )
            return
        currently = growatt_modbus_writes_allowed(p, s)
        new_on = not currently
        p.growatt_modbus_writes_enabled = new_on
        write_growatt_modbus_writes_enabled(s, new_on)
        pt = getattr(self.dash, "parameters_tab", None)
        if pt is not None and hasattr(pt, "chk_growatt_modbus_writes"):
            pt.chk_growatt_modbus_writes.blockSignals(True)
            try:
                pt.chk_growatt_modbus_writes.setChecked(new_on)
            finally:
                pt.chk_growatt_modbus_writes.blockSignals(False)
        log_connectivity_event(
            getattr(self.dash, "data_logger", None),
            service_key="inverter_write",
            service_label=label,
            event_type="enable" if new_on else "disable",
            state_key="ok" if new_on else "off",
            state_text="Modbus writes ON" if new_on else "Modbus writes off",
            detail=(
                "Local Modbus inverter writes enabled from Connectivity Status."
                if new_on
                else "Local Modbus inverter writes disabled from Connectivity Status."
            ),
        )
        self.dash.set_status(
            f"Modbus inverter writes: {'ENABLED' if new_on else 'disabled'}."
        )
        self.refresh_status(test_db=False, allow_local_probes=False)

    def _toggle_service_disabled(self, label, service_key, *, currently_disabled: bool):
        from energy_dashboard.db.connectivity_events import log_connectivity_event

        new_disabled = not currently_disabled
        self._set_row_disabled(service_key, new_disabled)
        log_connectivity_event(
            getattr(self.dash, "data_logger", None),
            service_key=service_key,
            service_label=label,
            event_type="disable" if new_disabled else "enable",
            state_key="off" if new_disabled else "info",
            state_text="Disabled" if new_disabled else "Enabled",
            detail=(
                "Monitoring muted from Connectivity Status."
                if new_disabled
                else "Monitoring re-enabled from Connectivity Status."
            ),
        )
        self.dash.set_status(
            f"{label}: {'disabled' if new_disabled else 'enabled'}."
        )
        self.refresh_status(test_db=False, allow_local_probes=False)

    def _highlight_service_on_diagram(self, label, meta):
        edges = set(meta.get("highlight_edges") or ())
        note = meta.get("highlight_note")
        if not edges:
            self.dash.set_status(note or f"{label}: nothing to highlight on the diagram.")
            return
        self._flow_diagram.highlight_links(edges=edges, duration_s=4.5)
        self.dash.set_status(f"Highlighting {label} on the architecture diagram…")

    def _collect_service_events(self, label: str, service_key: str) -> list[dict]:
        """DB connectivity_events plus live AlarmMonitor history where relevant."""
        from energy_dashboard.db.connectivity_events import query_connectivity_events

        rows = query_connectivity_events(
            getattr(self.dash, "data_logger", None),
            service_key,
            limit=250,
        )
        if service_key in ("grott_mqtt", "growatt_server", "modbus", "databases", "tasmota"):
            mon = getattr(self.dash, "alarm_monitor", None)
            hist = list(getattr(mon, "history", None) or [])
            _svc_keys = {
                "grott_mqtt": {"grott_lost"},
                "growatt_server": {"low_soc", "sun_wasted", "load_eats_pv", "inverter_comms_lost"},
                "modbus": {"low_soc", "sun_wasted", "load_eats_pv"},
                "databases": {"db_disconnected", "db_ingest_stale"},
                "tasmota": {"tasmota_mqtt_lost", "tasmota_offline"},
            }
            allowed = _svc_keys.get(service_key) or set()
            for ev in hist:
                akey = str(ev.get("key") or "")
                if akey not in allowed:
                    continue
                wall = ev.get("wall")
                try:
                    ts = datetime.fromtimestamp(float(wall), tz=timezone.utc).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ) if wall else ""
                except (TypeError, ValueError, OSError):
                    ts = ""
                rows.append({
                    "timestamp": ts,
                    "event_type": "alarm",
                    "state_key": ev.get("severity") or "warn",
                    "state_text": ev.get("title") or "",
                    "detail": ev.get("detail") or "",
                })
            rows.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
        return rows

    def _show_service_history(self, label, service_key):
        rows = self._collect_service_events(label, service_key)
        dlg = _ConnectivityHistoryDialog(label, rows, self)
        dlg.exec()

    def _show_service_alarms(self, label, service_key):
        """State menu → Show Alarms: alarm / fault / warn only (+ live AlarmMonitor)."""
        rows = self._collect_service_events(label, service_key)
        # Also surface *active* AlarmMonitor hits that map to this row.
        mon = getattr(self.dash, "alarm_monitor", None)
        active = list(getattr(mon, "_active", {}) or {}).values() if mon else []
        for hit in active:
            akey = str(getattr(hit, "key", "") or "")
            # Map live alarms onto the row that owns them.
            if akey == "grott_lost" and service_key != "grott_mqtt":
                continue
            if akey in ("db_disconnected", "db_ingest_stale") and service_key != "databases":
                continue
            if akey in ("tasmota_mqtt_lost", "tasmota_offline") and service_key != "tasmota":
                continue
            if akey == "inverter_comms_lost" and service_key not in (
                "growatt_server", "grott_mqtt",
            ):
                continue
            if akey in ("low_soc", "sun_wasted", "load_eats_pv") and service_key not in (
                "growatt_server", "grott_mqtt", "modbus",
            ):
                continue
            if akey and akey not in (
                "grott_lost", "low_soc", "sun_wasted", "load_eats_pv",
                "db_disconnected", "db_ingest_stale",
                "inverter_comms_lost", "tasmota_mqtt_lost", "tasmota_offline",
            ):
                continue
            if not akey:
                continue
            try:
                ts = datetime.fromtimestamp(
                    float(getattr(hit, "since_wall", 0) or 0), tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError, OSError):
                ts = ""
            rows.insert(0, {
                "timestamp": ts or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "event_type": "alarm",
                "state_key": getattr(hit, "severity", "warn"),
                "state_text": f"ACTIVE · {getattr(hit, 'title', akey)}",
                "detail": getattr(hit, "detail", "") or "",
            })
        alarm_types = {"alarm", "fault", "warn"}
        filtered = [
            r for r in rows
            if str(r.get("event_type") or "").lower() in alarm_types
            or str(r.get("state_text") or "").upper().startswith("ACTIVE")
        ]
        # Deduplicate consecutive identical titles.
        seen = set()
        uniq = []
        for r in filtered:
            key = (
                str(r.get("timestamp") or ""),
                str(r.get("state_text") or ""),
                str(r.get("detail") or "")[:80],
            )
            if key in seen:
                continue
            seen.add(key)
            uniq.append(r)
        dlg = _ConnectivityHistoryDialog(
            label,
            uniq,
            self,
            title=f"Alarms — {label}",
            hint=(
                "Live and recent alarms / faults / warnings for this service. "
                "ACTIVE rows are firing right now. Newest first."
            ),
            empty_message="No alarms recorded yet for this service.",
        )
        dlg.exec()

    @staticmethod
    def _parse_event_ts(raw: str):
        text = str(raw or "").strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(text[:19], fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    def _downtime_periods(self, events: list[dict]) -> list[dict]:
        """Build degraded windows from warn/fault → recover transitions."""
        chrono = sorted(
            events,
            key=lambda r: str(r.get("timestamp") or ""),
        )
        periods = []
        open_start = None
        open_text = ""
        open_detail = ""
        for ev in chrono:
            et = str(ev.get("event_type") or "").lower()
            ts = self._parse_event_ts(ev.get("timestamp"))
            if et in ("warn", "fault", "alarm") and open_start is None:
                open_start = ts
                open_text = str(ev.get("state_text") or et)
                open_detail = str(ev.get("detail") or "")
            elif et == "recover" and open_start is not None:
                end = ts
                dur = None
                if open_start is not None and end is not None:
                    dur = max(0.0, (end - open_start).total_seconds())
                periods.append({
                    "start": open_start,
                    "end": end,
                    "ongoing": False,
                    "duration_s": dur,
                    "state_text": open_text,
                    "detail": open_detail,
                })
                open_start = None
                open_text = ""
                open_detail = ""
        if open_start is not None:
            now = datetime.utcnow()
            dur = max(0.0, (now - open_start).total_seconds()) if open_start else None
            periods.append({
                "start": open_start,
                "end": None,
                "ongoing": True,
                "duration_s": dur,
                "state_text": open_text,
                "detail": open_detail,
            })
        periods.reverse()  # newest first
        return periods

    def _show_service_downtime(self, label, service_key):
        events = self._collect_service_events(label, service_key)
        periods = self._downtime_periods(events)
        live = self._prev_row_states.get(service_key)
        if live in ("warn", "bad") and not any(p.get("ongoing") for p in periods):
            periods.insert(0, {
                "start": datetime.utcnow(),
                "end": None,
                "ongoing": True,
                "duration_s": None,
                "state_text": f"Currently {live}",
                "detail": "Open degraded state (no start edge logged yet).",
            })

        def _fmt_ts(dt):
            if dt is None:
                return "—"
            return dt.strftime("%Y-%m-%d %H:%M:%S")

        def _fmt_dur(seconds):
            if seconds is None:
                return "?"
            s = int(seconds)
            if s < 60:
                return f"{s}s"
            if s < 3600:
                return f"{s // 60}m {s % 60:02d}s"
            return f"{s // 3600}h {(s % 3600) // 60:02d}m"

        total = sum(float(p["duration_s"] or 0) for p in periods)
        rows = []
        for p in periods:
            end_txt = "ongoing" if p.get("ongoing") else _fmt_ts(p.get("end"))
            rows.append({
                "timestamp": _fmt_ts(p.get("start")),
                "event_type": "downtime",
                "state_text": f"{_fmt_dur(p.get('duration_s'))} · {end_txt}",
                "detail": (
                    f"{p.get('state_text') or ''} — {p.get('detail') or ''}"
                ).strip(" —"),
            })
        hint = (
            f"Degraded / down periods for {label}. "
            f"Logged total ≈ {_fmt_dur(total)} across {len(periods)} period(s). "
            "Built from warn/fault/alarm → recover edges (and live AlarmMonitor)."
        )
        dlg = _ConnectivityHistoryDialog(
            label,
            rows,
            self,
            title=f"Downtime — {label}",
            hint=hint,
            empty_message=(
                "No downtime periods recorded yet. "
                "They appear when this row goes warn/bad and later recovers."
            ),
        )
        dlg.exec()

    def _test_service_connection(self, label: str, service_key: str) -> None:
        """State menu → Test Connection for external / DB peers."""
        from energy_dashboard.db.connectivity_events import log_connectivity_event

        self.dash.set_status(f"{label}: testing connection…")

        def _done(ok: bool, msg: str):
            line = f"{label}: {'OK — ' if ok else 'FAILED — '}{msg}"
            self.dash.set_status(line)
            log_connectivity_event(
                getattr(self.dash, "data_logger", None),
                service_key=service_key,
                service_label=label,
                event_type="test",
                state_key="ok" if ok else "bad",
                state_text="Test OK" if ok else "Test failed",
                detail=str(msg)[:2000],
            )
            # Refresh so the State cell picks up the latest probe where applicable.
            try:
                self.refresh_status(
                    test_db=(service_key == "databases"),
                    allow_local_probes=False,
                )
            except Exception:
                pass

        if service_key == "databases":
            self.refresh_status(test_db=True, allow_local_probes=False)
            # refresh_status already probes; summarise from cache.
            results = getattr(self, "_db_results", None)
            if results is None:
                _done(False, "Database probe did not return results yet — try again in a moment.")
                return
            ok_n = sum(1 for ok, _ in results.values() if ok)
            detail = " | ".join(
                f"{name}: {'OK' if ok else info}" for name, (ok, info) in results.items()
            )
            _done(ok_n == len(results) and ok_n > 0, detail or "No backends enabled")
            return

        if service_key == "forecast":
            ft = getattr(self.dash, "forecasts_tab", None)
            if ft is None or not hasattr(ft, "fetch_forecasts"):
                _done(False, "Forecasts tab not available")
                return
            try:
                ft.fetch_forecasts()
                _done(True, "Forecast fetch started — watch the Forecasts tab / this row for result")
            except Exception as exc:
                _done(False, str(exc))
            return

        if service_key == "octopus_historic":
            ot = getattr(self.dash, "octopus_tab", None)
            if ot is None or not hasattr(ot, "fetch_data"):
                _done(False, "Octopus historic tab not available")
                return
            try:
                ot.fetch_data()
                _done(True, "Historic fetch started — watch Octopus / this row for result")
            except Exception as exc:
                _done(False, str(exc))
            return

        if service_key == "octopus_live":
            olt = getattr(self.dash, "octopus_live_tab", None)
            if olt is None or not hasattr(olt, "fetch_data"):
                _done(False, "Octopus Live tab not available")
                return
            try:
                olt.fetch_data()
                _done(True, "Live fetch started — watch Octopus Live / this row for result")
            except Exception as exc:
                _done(False, str(exc))
            return

        if service_key == "pvoutput":
            def _run():
                from energy_dashboard.fetch.pvoutput import test_pvoutput_connection
                ok, msg = test_pvoutput_connection()
                QTimer.singleShot(0, lambda: _done(ok, msg))
            import threading
            threading.Thread(target=_run, daemon=True).start()
            return

        if service_key == "wonderwatt":
            def _run():
                from energy_dashboard.fetch.wonderwatt import test_wonderwatt_connection
                ok, msg = test_wonderwatt_connection()
                QTimer.singleShot(0, lambda: _done(ok, msg))
            import threading
            threading.Thread(target=_run, daemon=True).start()
            return

        _done(False, f"No test action wired for {service_key}")

    def _apply_disabled_and_log_transitions(self, rows: list) -> list:
        """Mute disabled rows and persist state transitions as connectivity_events."""
        from energy_dashboard.db.connectivity_events import log_connectivity_event

        out = []
        for row in rows:
            if len(row) < 5:
                out.append(row)
                continue
            label, state_text, state_key, details, fresh = row[:5]
            rest = row[5:]
            service_key = self._service_key_for_label(label)
            live_key = str(state_key)
            live_text = str(state_text)
            meta = _SERVICE_ROW_META.get(label) or {}
            if (
                service_key
                and service_key != "inverter_write"
                and bool(meta.get("can_disable", True))
                and self._row_is_disabled(service_key)
            ):
                state_text = "Disabled"
                state_key = "off"
                details = f"Muted in Connectivity Status. Underlying: {live_text}. {details}"
            out.append((label, state_text, state_key, details, fresh, *rest))

            if not service_key:
                continue
            prev = self._prev_row_states.get(service_key)
            # Track underlying (pre-mute) health for alarms/faults history.
            self._prev_row_states[service_key] = live_key
            if prev is None or prev == live_key:
                continue
            if live_key in ("bad", "warn") and prev not in ("bad", "warn"):
                et = "fault" if live_key == "bad" else "warn"
                log_connectivity_event(
                    getattr(self.dash, "data_logger", None),
                    service_key=service_key,
                    service_label=label,
                    event_type=et,
                    state_key=live_key,
                    state_text=live_text,
                    detail=str(details)[:2000],
                )
            elif prev in ("bad", "warn") and live_key in ("ok", "idle"):
                log_connectivity_event(
                    getattr(self.dash, "data_logger", None),
                    service_key=service_key,
                    service_label=label,
                    event_type="recover",
                    state_key=live_key,
                    state_text=live_text,
                    detail=str(details)[:2000],
                )
        return out

    def _fmt_db_tables_cell(self, *table_names: str) -> str:
        """Format row counts / relation size for one or more logged tables."""
        parts = []
        info_map = getattr(self, "_table_info", {}) or {}
        for name in table_names:
            info = info_map.get(name)
            if not info:
                continue
            bit = []
            rc = info.get("row_count")
            if rc is not None:
                bit.append(f"{int(rc):,} rows")
            if info.get("size_human"):
                bit.append(info["size_human"])
            if bit:
                parts.append(
                    f"{name}: {' · '.join(bit)}" if len(table_names) > 1 else " · ".join(bit)
                )
        return " · ".join(parts) if parts else "--"

    def _on_status_timer(self):
        """Periodic light refresh; full DB connect test only when tab is visible."""
        import time as _time
        visible = self.isVisible()
        now = _time.monotonic()
        test_db = visible and (now - self._last_db_test_mono) >= 120.0
        # Local ShineLan / Modbus probes are expensive; at most once per 90s.
        allow_probes = visible and (
            (now - self._last_http_probe_mono) >= 90.0
            or (now - self._last_modbus_probe_mono) >= 90.0
        )
        self.refresh_status(test_db=test_db, allow_local_probes=allow_probes)
        if visible and (now - self._size_cache_at) >= 120.0:
            self._schedule_size_cache_rebuild()

    def _schedule_db_connect_test(self):
        """Run DataLogger.test_connections() off the UI thread."""
        if self._db_test_building:
            return
        self._db_test_building = True

        def work():
            import time as _time
            try:
                results = self.dash.data_logger.test_connections()
            except Exception as e:
                results = {"Error": (False, str(e))}

            def apply():
                self._db_results = results
                self._db_test_time = datetime.now().strftime("%H:%M:%S")
                self._last_db_test_mono = _time.monotonic()
                self._db_test_building = False
                # Light UI refresh only — do not kick local probes again.
                self.refresh_status(test_db=False, allow_local_probes=False)

            self._inv.invoke(apply)

        threading.Thread(target=work, daemon=True).start()

    def _schedule_size_cache_rebuild(self):
        """Rebuild table-size cache off the UI thread."""
        if self._size_cache_building:
            return
        dl = self.dash.data_logger
        db_enabled = []
        if dl.sqlite_enabled:
            db_enabled.append("SQLite")
        if dl.mysql_enabled:
            db_enabled.append("MySQL")
        if dl.pg_enabled:
            db_enabled.append("PostgreSQL")
        if not db_enabled:
            self._size_cache = {}
            return
        self._size_cache_building = True

        def work():
            import time as _time
            try:
                cache = self._build_table_size_cache(db_enabled)
            except Exception:
                cache = dict(self._size_cache or {})
            def apply():
                table_info = {}
                if isinstance(cache, dict):
                    table_info = cache.pop("_table_info", {}) or {}
                    self._size_cache = cache
                else:
                    self._size_cache = {}
                if table_info:
                    self._table_info = table_info
                self._size_cache_at = _time.monotonic()
                self._size_cache_building = False
            self._inv.invoke(apply)

        threading.Thread(target=work, daemon=True).start()

    def _build_table_size_cache(self, enabled_backends: list[str]) -> dict[str, str]:
        """Service name → Table size column (from health stats + PG relation sizes).

        Safe to call from a worker thread: builds a local table_info map and only
        returns the formatted size-cache dict (UI applies it on the main thread).
        """
        table_info: dict = {}
        db_parts = []
        cap = self._db_cap()
        for backend in enabled_backends:
            stats = collect_health_stats(backend, cap)
            if not stats.get("ok"):
                db_parts.append(f"{backend}: —")
                continue
            db_parts.append(f"{backend}: {stats.get('db_size', '—')}")
            for table, info in (stats.get("tables") or {}).items():
                if not info.get("exists"):
                    continue
                prev = table_info.get(table, {})
                rows_n = int(info.get("row_count") or 0)
                if rows_n >= int(prev.get("row_count") or 0):
                    table_info[table] = {
                        "row_count": rows_n,
                        "last_activity": info.get("last_activity"),
                        "size_human": info.get("size_human") or prev.get("size_human"),
                        "size_bytes": info.get("size_bytes")
                        if info.get("size_bytes") is not None
                        else prev.get("size_bytes"),
                    }
                elif info.get("size_human") and not prev.get("size_human"):
                    prev = dict(prev)
                    prev["size_human"] = info.get("size_human")
                    prev["size_bytes"] = info.get("size_bytes")
                    table_info[table] = prev
            # Fill any missing sizes with a direct relation-size probe.
            try:
                with _open_db(backend, cap) as (conn, dialect, _):
                    cur = conn.cursor()
                    for table, _ts in KNOWN_TABLES:
                        if table not in table_info:
                            continue
                        if table_info[table].get("size_human"):
                            continue
                        sz = _relation_size_bytes(cur, dialect, table)
                        if sz:
                            table_info[table]["size_bytes"] = int(sz)
                            table_info[table]["size_human"] = _fmt_size(sz)
            except Exception:
                pass

        def _fmt(*table_names: str) -> str:
            parts = []
            for name in table_names:
                info = table_info.get(name) or {}
                bit = []
                rows_n = info.get("row_count")
                if rows_n is not None:
                    bit.append(f"{int(rows_n):,} rows")
                sz = info.get("size_human")
                if sz:
                    bit.append(str(sz))
                fresh = ConnectivityStatusTab._fmt_activity_freshness(
                    info.get("last_activity")
                )
                if fresh and fresh != "--":
                    bit.append(fresh)
                if bit:
                    parts.append(
                        f"{name}: {' · '.join(bit)}" if len(table_names) > 1 else " · ".join(bit)
                    )
            return " · ".join(parts) if parts else "--"

        return {
            "Growatt server": _fmt("growatt_readings", "growatt_mix_chart"),
            "Octopus historic": _fmt("octopus_readings"),
            "Tasmota devices": _fmt("tasmota_readings", "tasmota_devices"),
            "Forecast.solar": _fmt(
                "solar_forecast_snapshots", "agile_price_snapshots", "agile_year_daily",
            ),
            "Databases": " | ".join(db_parts) if db_parts else "--",
            "_table_info": table_info,
        }

    def _size_for(self, service: str, *, override: str | None = None) -> str:
        if override is not None:
            return override
        return (getattr(self, "_size_cache", None) or {}).get(service, "--")

    def _inverter_write_row(self, gt, md_mode, mc, growatt_last):
        """
        One table row: whether schedule writeback from this app is available,
        and by which transport (Growatt cloud REST vs local Modbus).
        """
        from energy_dashboard.config import growatt_modbus_writes_allowed

        s = QSettings("PowerModel", "EnergyDashboard2")
        mb_writes = growatt_modbus_writes_allowed(self.dash.app_params, s)
        md_ok = (mc or {}).get("state_key") == "ok"

        if not gt.connect_btn.isEnabled():
            return (
                "Inverter write (this app)",
                "Starting…",
                "idle",
                "Growatt cloud session not ready yet. When connected, schedule push "
                "uses the Growatt server REST API. Local Modbus writes are a separate "
                "opt-in under Setup (or right-click Enable here).",
                "--",
            )
        cloud_ok = bool(gt.api and gt.device_sn)

        def _modbus_write_clause() -> str:
            if md_mode == "off":
                return (
                    " Local Modbus writes: unavailable — set a Modbus mode in Setup first, "
                    "then Enable here or tick “Allow inverter writes via Modbus”."
                )
            if mb_writes:
                if md_ok:
                    return (
                        " Local Modbus writes: ENABLED (opt-in). Command Sim and any "
                        "local register write path may use the LAN gateway. "
                        "Wrong writes are safety-sensitive."
                    )
                if self._growatt_modbus_probe_running:
                    return (
                        " Local Modbus writes: ENABLED in Setup — probe running "
                        "(path not confirmed yet)."
                    )
                mt = (mc or {}).get("state_text", "—")
                return (
                    f" Local Modbus writes: ENABLED in Setup, but probe is {mt} — "
                    "fix the link before relying on local writes."
                )
            return (
                " Local Modbus writes: off (default). Right-click this State → "
                "Enable Modbus inverter writes, or tick the opt-in under Setup & Info."
            )

        if cloud_ok:
            det = (
                "Optimiser / AC charge / forced-discharge schedule push uses the "
                "logged-in Growatt cloud REST API"
            )
            if mb_writes and md_ok:
                state_text = "Yes — cloud + Modbus"
                state_key = "ok"
                det += "; local Modbus register writes are also enabled."
            elif mb_writes:
                state_text = "Yes — cloud (Modbus writes armed)"
                state_key = "warn"
                det += "; Modbus write opt-in is on but the local probe is not OK yet."
            else:
                state_text = "Yes — Growatt cloud (REST)"
                state_key = "ok"
                det += "."
            det += _modbus_write_clause()
            return (
                "Inverter write (this app)",
                state_text,
                state_key,
                det,
                growatt_last or "--",
            )
        # Grott MQTT often fills device_sn without a cloud API handle — that is
        # telemetry only, not a write session.
        if gt.device_sn and not gt.api:
            sn = str(gt.device_sn)
            if mb_writes and md_ok:
                return (
                    "Inverter write (this app)",
                    "Yes — Modbus only",
                    "ok",
                    f"SN {sn} is from Grott MQTT (no cloud API session). "
                    "Cloud schedule writeback needs Growatt Live → Connect. "
                    "Local Modbus register writes are ENABLED."
                    + _modbus_write_clause(),
                    growatt_last or "--",
                )
            if mb_writes:
                return (
                    "Inverter write (this app)",
                    "Modbus writes armed — probe not OK",
                    "warn",
                    f"SN {sn} from Grott only (no cloud login). "
                    "Modbus write opt-in is on but the local probe is not healthy."
                    + _modbus_write_clause(),
                    growatt_last or "--",
                )
            return (
                "Inverter write (this app)",
                "No — cloud login or enable Modbus writes",
                "warn",
                f"SN {sn} is from Grott MQTT / Hybrid telemetry only. "
                "Schedule writeback via cloud needs Growatt Live → Connect. "
                "Or enable local Modbus inverter writes (right-click Enable / Setup)."
                + _modbus_write_clause(),
                growatt_last or "--",
            )
        if gt.api and not gt.device_sn:
            return (
                "Inverter write (this app)",
                "Partial session",
                "warn",
                "Growatt API login succeeded but no device serial is selected yet. "
                "Finish connecting on the Live tab (pick plant / inverter) to "
                "enable cloud schedule writeback."
                + _modbus_write_clause(),
                growatt_last or "--",
            )
        if mb_writes and md_ok:
            return (
                "Inverter write (this app)",
                "Yes — Modbus only",
                "ok",
                "No Growatt cloud session. Local Modbus register writes are ENABLED."
                + _modbus_write_clause(),
                "--",
            )
        return (
            "Inverter write (this app)",
            "No — need cloud login or enable Modbus writes",
            "bad",
            "No Growatt API session. Connect on the Live tab for cloud schedule push, "
            "or enable local Modbus inverter writes once Modbus is configured."
            + _modbus_write_clause(),
            "--",
        )

    def _start_growatt_modbus_probe(self, app_params):
        """Background Modbus read to verify local TCP/RTU path (non-blocking)."""
        if self._growatt_modbus_probe_running:
            return
        import time as _time
        self._growatt_modbus_probe_running = True
        self._last_modbus_probe_mono = _time.monotonic()
        p = app_params

        def work():
            try:
                r = _growatt_modbus_probe_sync(
                    getattr(p, "growatt_modbus_mode", "off"),
                    growatt_modbus_tcp_host(p),
                    getattr(p, "growatt_modbus_tcp_port", 502),
                    getattr(p, "growatt_modbus_serial_path", ""),
                    getattr(p, "growatt_modbus_baud", 9600),
                    getattr(p, "growatt_modbus_unit", 1),
                )
            except Exception as e:
                r = {
                    "state_key": "bad",
                    "state_text": "Error",
                    "detail": str(e),
                    "fresh": datetime.now().strftime("%H:%M:%S"),
                }

            def done():
                self._growatt_modbus_probe_running = False
                self._growatt_modbus_cache = r
                # Apply cache without restarting the other local probe.
                self.refresh_status(test_db=False, allow_local_probes=False)

            self._inv.invoke(done)

        threading.Thread(target=work, daemon=True).start()

    def _start_growatt_http_probe(self, app_params):
        """Background ShineLan web UI settings read (non-blocking)."""
        if self._growatt_http_probe_running:
            return
        host = growatt_http_host(app_params)
        if not host:
            return
        import time as _time
        self._growatt_http_probe_running = True
        self._last_http_probe_mono = _time.monotonic()
        p = app_params
        if host == growatt_wifi_host(p):
            username = getattr(p, "growatt_wifi_user", "")
            password = getattr(p, "growatt_wifi_password", "")
        else:
            username = getattr(p, "growatt_lan_user", "")
            password = getattr(p, "growatt_lan_password", "")

        def work():
            try:
                r = _growatt_http_probe_sync(
                    host,
                    getattr(p, "growatt_local_port", 80),
                    username,
                    password,
                )
            except Exception as e:
                r = {
                    "state_key": "bad",
                    "state_text": "Error",
                    "detail": str(e),
                    "fresh": datetime.now().strftime("%H:%M:%S"),
                }

            def done():
                self._growatt_http_probe_running = False
                self._growatt_http_cache = r
                self.refresh_status(test_db=False, allow_local_probes=False)

            self._inv.invoke(done)

        threading.Thread(target=work, daemon=True).start()

    def _start_pipeline_probe(self):
        """Background Growatt pipeline probe (Modbus, GROTT, EMQX, dashboard)."""
        if self._pipeline_probe_running:
            return
        self._pipeline_probe_running = True
        self.probe_pipeline_btn.setEnabled(False)
        self.probe_status_label.setText("Probing pipeline…")

        def progress(msg: str):
            def ui():
                self.probe_status_label.setText(msg)
            self._inv.invoke(ui)

        def work():
            try:
                report = run_growatt_pipeline_probe(
                    self.dash.app_params,
                    dash=self.dash,
                    progress=progress,
                )
            except Exception as exc:
                report = None
                err = str(exc)

            def done():
                self._pipeline_probe_running = False
                self.probe_pipeline_btn.setEnabled(True)
                if report is None:
                    self.probe_status_label.setText(f"Probe failed: {err[:120]}")
                    QMessageBox.warning(
                        self,
                        "Pipeline probe",
                        f"Probe failed:\n{err}",
                    )
                    return
                self.probe_status_label.setText(
                    "Breaks found" if report.breaks else "Pipeline OK"
                )
                self._flow_diagram.set_pipeline_probe(report)
                dlg = PipelineProbeDialog(report, self)
                dlg.exec()

            self._inv.invoke(done)

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _fmt_num(n):
        try:
            return f"{int(n):,}"
        except (TypeError, ValueError):
            return str(n)

    @staticmethod
    def _fmt_age_s(age_s):
        if age_s is None:
            return "--"
        try:
            age = float(age_s)
        except (TypeError, ValueError):
            return "--"
        if age < 60:
            return f"{age:.0f}s ago"
        if age < 3600:
            return f"{age / 60.0:.1f}m ago"
        return f"{age / 3600.0:.1f}h ago"

    def _retention_table_stats(self) -> dict:
        """Row counts / last activity / size per table for retention dialog."""
        # Prefer the warm size cache (already includes freshness + size).
        info_map = getattr(self, "_table_info", None) or {}
        if info_map:
            merged = {
                k: {
                    "row_count": v.get("row_count"),
                    "last_activity": v.get("last_activity"),
                    "size_human": v.get("size_human"),
                }
                for k, v in info_map.items()
            }
        else:
            merged = {}
            dl = self.dash.data_logger
            enabled = []
            if dl.sqlite_enabled:
                enabled.append("SQLite")
            if dl.mysql_enabled:
                enabled.append("MySQL")
            if dl.pg_enabled:
                enabled.append("PostgreSQL")
            cap = self._db_cap()
            for backend in enabled:
                stats = collect_health_stats(backend, cap)
                if not stats.get("ok"):
                    continue
                for table, info in (stats.get("tables") or {}).items():
                    if not info.get("exists"):
                        continue
                    prev = merged.get(table, {})
                    rows = int(info.get("row_count") or 0)
                    if rows >= int(prev.get("row_count") or 0):
                        merged[table] = {
                            "row_count": rows,
                            "last_activity": info.get("last_activity"),
                            "size_human": info.get("size_human"),
                        }
        log_path = Path.home() / ".energy_dashboard_console.jsonl"
        if log_path.is_file():
            try:
                st = log_path.stat()
                # Avoid reading the whole file just to count lines (can be multi-MB).
                merged["console_log"] = {
                    "row_count": max(1, int(st.st_size // 160)),
                    "last_activity": "file on disk",
                    "size_human": _fmt_size(st.st_size),
                }
            except OSError:
                pass
        return merged

    def _refresh_db_volumes_async(self, enabled, base_volumes, *, force=False):
        import time as _time
        now = _time.monotonic()
        if self._volumes_busy:
            return
        # Full COUNT(*) / growth stats are heavy — at most every 60s unless forced.
        if not force and (now - self._last_volumes_mono) < 60.0:
            return
        self._volumes_busy = True
        self._last_volumes_mono = now
        cap = self._db_cap()

        def work():
            try:
                vol = {k: list(v) for k, v in (base_volumes or {}).items()}
                for key in (
                    "growatt_cloud", "grott", "octopus", "forecast", "modbus",
                    "modbus_lan", "tasmota", "emqx", "database",
                    "export", "dashboard", "storage", "pvoutput", "wonderwatt",
                ):
                    vol.setdefault(key, [])
                db_lines = list(vol.get("database", []))
                # Drop soft placeholders so calculated DB lines replace them.
                for soft_key in ("modbus", "modbus_lan"):
                    vol[soft_key] = [
                        ln for ln in vol[soft_key]
                        if ln != "Not configured"
                    ]
                extra = {k: [] for k in vol}
                export_rows = 0
                table_info_merged: dict = {}
                for backend in enabled:
                    stats = collect_health_stats(backend, cap)
                    if not stats.get("ok"):
                        db_lines.append(
                            f"{backend}: unavailable ({stats.get('error') or 'probe failed'})"
                        )
                        continue
                    db_lines.append(f"{backend}: {stats.get('db_size', '—')} total size")
                    overall = stats.get("last_activity_overall")
                    if overall:
                        db_lines.append(
                            f"  Last write: {overall} "
                            f"({self._fmt_activity_freshness(overall)})"
                        )
                    week_total = sum(w.get("total", 0) for w in stats.get("weekly_growth", []))
                    if week_total:
                        db_lines.append(
                            f"  Rows logged (last 4 weeks): {self._fmt_num(week_total)}"
                        )
                    for table, label, boxes in _IMPORT_TABLE_META:
                        info = (stats.get("tables") or {}).get(table) or {}
                        if not info.get("exists"):
                            continue
                        rows_n = int(info.get("row_count") or 0)
                        export_rows += rows_n
                        line = self._format_table_volume_line(label, info, backend=backend)
                        db_lines.append(f"  {line}")
                        prev = table_info_merged.get(table, {})
                        if rows_n >= int(prev.get("row_count") or 0):
                            table_info_merged[table] = {
                                "row_count": rows_n,
                                "last_activity": info.get("last_activity"),
                                "size_human": info.get("size_human"),
                                "size_bytes": info.get("size_bytes"),
                            }
                        for box in boxes:
                            extra[box].append(line)
                        extra["storage"].append(line)
                        extra["export"].append(line)

                vol["database"] = db_lines
                if export_rows:
                    vol["export"].append(
                        f"Stored rows (all backends / imports): {self._fmt_num(export_rows)}"
                    )
                # Prefer calculated inventory over empty / "Not configured" stubs.
                for box, lines in extra.items():
                    if not lines:
                        continue
                    existing = [
                        ln for ln in (vol.get(box) or [])
                        if ln != "Not configured"
                    ]
                    vol[box] = list(dict.fromkeys(existing + lines))
                if not vol.get("storage"):
                    vol["storage"] = list(dict.fromkeys(extra.get("storage") or []))
            except Exception:
                vol = base_volumes or {}
                table_info_merged = {}

            def done():
                self._volumes_busy = False
                try:
                    if table_info_merged:
                        prev = dict(getattr(self, "_table_info", None) or {})
                        prev.update(table_info_merged)
                        self._table_info = prev
                    self._flow_diagram.set_volumes(vol)
                except Exception:
                    pass

            self._inv.invoke(done)

        threading.Thread(target=work, daemon=True).start()

    def _db_cap(self):
        pt = self.dash.parameters_tab
        return {
            'sqlite_path': pt.ed_sqlite_path.text().strip(),
            'mysql_host': pt.ed_mysql_host.text().strip(),
            'mysql_port': pt.ed_mysql_port.value(),
            'mysql_user': pt.ed_mysql_user.text().strip(),
            'mysql_pass': pt.ed_mysql_pass.text(),
            'mysql_db': pt.ed_mysql_db.text().strip(),
            'pg_host': pt.ed_pg_host.text().strip(),
            'pg_port': pt.ed_pg_port.value(),
            'pg_user': pt.ed_pg_user.text().strip(),
            'pg_pass': pt.ed_pg_pass.text(),
            'pg_db': pt.ed_pg_db.text().strip(),
        }

    def _collect_box_volumes(self, d):
        vol = {
            "growatt_cloud": [],
            "grott": [],
            "octopus": [],
            "forecast": [],
            "modbus": [],
            "modbus_lan": [],
            "tasmota": [],
            "emqx": [],
            "database": [],
            "export": [],
            "dashboard": [],
            "storage": [],
            "pvoutput": [],
            "wonderwatt": [],
        }
        gt = d.growatt_tab
        tel = _growatt_telemetry_info(gt, d.app_params)
        mt = getattr(gt, 'mix_totals_data', None) or {}
        status = getattr(gt, 'mix_status_data', None) or {}

        def _f(k):
            try:
                return float(mt.get(k) or 0)
            except (TypeError, ValueError):
                return None

        if _f('epvToday') is not None:
            vol["growatt_cloud"].append(f"PV generated today: {_f('epvToday'):.2f} kWh")
        if _f('elocalLoadToday') is not None:
            vol["growatt_cloud"].append(f"Load today: {_f('elocalLoadToday'):.2f} kWh")
        if _f('etoGridToday') is not None:
            vol["growatt_cloud"].append(f"Grid export today: {_f('etoGridToday'):.2f} kWh")
        try:
            pv = float(status.get('ppv') or 0)
            load = float(status.get('pLocalLoad') or 0)
            if pv > 0:
                vol["growatt_cloud"].append(f"Live PV: {pv:.2f} kW")
            if load > 0:
                vol["growatt_cloud"].append(f"Live load: {load:.2f} kW")
        except (TypeError, ValueError):
            pass

        ot = d.octopus_tab
        hh = getattr(ot, 'hh_data', None)
        if hh is not None and not hh.empty:
            summary = getattr(ot, '_last_summary', None) or (0, 0, 0, 0)
            imp_kwh, exp_kwh, _, num_days = summary
            vol["octopus"].append(
                f"Historic: {imp_kwh:.1f} kWh import, {exp_kwh:.1f} kWh export "
                f"({num_days} days loaded)"
            )
            vol["octopus"].append(f"Historic half-hour slots: {self._fmt_num(len(hh))}")

        olt = d.octopus_live_tab
        imp_df = getattr(olt, 'import_df', None)
        exp_df = getattr(olt, 'export_df', None)
        n_imp = 0 if imp_df is None else len(imp_df)
        n_exp = 0 if exp_df is None else len(exp_df)
        if n_imp or n_exp:
            imp_kwh = float(imp_df['consumption'].sum()) if n_imp and 'consumption' in imp_df.columns else 0.0
            exp_kwh = float(exp_df['consumption'].sum()) if n_exp and 'consumption' in exp_df.columns else 0.0
            vol["octopus"].append(
                f"Live window: {n_imp} import + {n_exp} export slots "
                f"({imp_kwh:.2f} + {exp_kwh:.2f} kWh in view)"
            )

        ft = d.forecasts_tab
        sdf = getattr(ft, 'solar_df', None)
        if sdf is not None and not sdf.empty:
            vol["forecast"].append(f"Solar forecast samples: {self._fmt_num(len(sdf))}")
        agile = getattr(ft, 'agile_df', None)
        if agile is not None and not agile.is_empty():
            vol["forecast"].append(f"Agile import price slots: {self._fmt_num(len(agile))}")
        agile_ex = getattr(ft, 'agile_export_df', None)
        if agile_ex is not None and not agile_ex.is_empty():
            vol["forecast"].append(f"Agile export price slots: {self._fmt_num(len(agile_ex))}")

        tt = d.tasmota_tab
        total = len(getattr(tt, 'device_ips', []) or [])
        online = len(getattr(tt, 'device_data', {}) or {})
        vol["tasmota"].append(f"Devices online: {online}/{total}")
        hist = getattr(tt, '_db_history', {}) or {}
        if hist:
            pts = sum(len(v) for v in hist.values() if v)
            vol["tasmota"].append(f"In-memory power history points: {self._fmt_num(pts)}")

        # Seed each component with any already-cached DB inventory (rows · size · fresh).
        for box_key in (
            "growatt_cloud", "grott", "octopus", "forecast", "tasmota",
            "emqx", "modbus", "storage",
        ):
            for ln in self.import_inventory_lines_for_box(box_key):
                if ln not in vol[box_key]:
                    vol[box_key].append(ln)

        md_mode = (getattr(d.app_params, "growatt_modbus_mode", "off") or "off").lower()
        if md_mode == "off":
            if not vol["modbus"]:
                vol["modbus"].append("Modbus mode: off")
            if not vol["modbus_lan"]:
                vol["modbus_lan"].append("Modbus mode: off")
        else:
            vol["modbus"].append(f"Mode: {md_mode}")
            vol["modbus_lan"].append(f"Mode: {md_mode}")
            tcp_host = growatt_modbus_tcp_host(d.app_params)
            if tcp_host:
                vol["modbus"].append(
                    f"Target: {tcp_host}:{getattr(d.app_params, 'growatt_modbus_tcp_port', 502)}"
                )
            else:
                vol["modbus"].append("Modbus TCP host not configured")
        gs = gt.grott_status() if hasattr(gt, "grott_status") else {}
        vol["growatt_cloud"].append(
            f"Telemetry source: {_growatt_source_label(tel.get('source', GROWATT_TELEMETRY_API))}"
        )
        if tel.get("fill_missing"):
            n = int(tel.get("api_filled_count") or 0)
            vol["growatt_cloud"].append(
                f"Fill missing Grott with API: on"
                + (f" ({n} patched field(s))" if n else "")
            )
        if gs.get("enabled") or tel.get("uses_grott"):
            target = f"{gs.get('host') or '—'}:{gs.get('port') or '—'}"
            topic = gs.get("topic") or "energy/growatt"
            state = (
                "fresh" if gs.get("fresh")
                else ("connected" if gs.get("connected") else "not connected")
            )
            vol["grott"].append(f"Broker: {target} · {topic} ({state})")
            vol["emqx"].append(f"Broker: {target} · {topic} ({state})")
            if tel.get("hybrid"):
                if gs.get("fresh"):
                    vol["grott"].append("Hybrid: Grott primary (cloud on standby)")
                else:
                    vol["grott"].append("Hybrid: Grott stale — cloud fallback may apply")
            elif gs.get("fresh"):
                vol["grott"].append("Grott MQTT: fresh telemetry available")
            if tel.get("fill_missing") and int(tel.get("api_filled_count") or 0) > 0:
                vol["grott"].append(
                    f"API patched {tel['api_filled_count']} missing register(s)"
                )
            if gs.get("fresh") and tel.get("source") == GROWATT_TELEMETRY_GROTT:
                vol["growatt_cloud"].append("Live path: Grott MQTT (cloud standby)")

        dl = d.data_logger
        enabled = []
        if dl.sqlite_enabled:
            enabled.append("SQLite")
        if dl.mysql_enabled:
            enabled.append("MySQL")
        if dl.pg_enabled:
            enabled.append("PostgreSQL")
        if enabled:
            vol["database"].append(f"Backends enabled: {', '.join(enabled)}")
        else:
            vol["database"].append("No database backends enabled")

        # Always include full import inventory on storage / export / database boxes.
        inv = self.import_inventory_lines()
        if inv:
            vol["storage"] = list(dict.fromkeys((vol.get("storage") or []) + inv))
            for ln in inv:
                if ln not in vol["database"]:
                    vol["database"].append(ln)
                if ln not in vol["export"]:
                    vol["export"].append(ln)
        else:
            vol["export"].append("Manual CSV / Excel exports from dashboard tabs")
            vol["export"].append("Automatic logging when database backends are connected")

        dash_lines = []
        if vol["growatt_cloud"]:
            dash_lines.append(f"Growatt live/today: {vol['growatt_cloud'][0]}")
        if vol["octopus"]:
            dash_lines.append(vol["octopus"][0])
        if vol["tasmota"]:
            dash_lines.append(vol["tasmota"][0])
        if vol["forecast"]:
            dash_lines.append(vol["forecast"][0])
        vol["dashboard"] = dash_lines or ["Open source boxes for per-feed volumes"]
        return vol, enabled

    def set_diagram_alarms(self, hits) -> None:
        """Update architecture diagram alarm badges (called from AlarmMonitor)."""
        try:
            self._flow_diagram.set_alarms(hits)
        except Exception:
            pass

    def _push_diagram_alarms(self) -> None:
        mon = getattr(self.dash, "alarm_monitor", None)
        hits = []
        if mon is not None:
            try:
                hits = list(getattr(mon, "_active", {}) or {}).values()
            except Exception:
                hits = []
        self.set_diagram_alarms(hits)

    def refresh_status(self, test_db=False, allow_local_probes=None):
        import time as _time
        d = self.dash
        rows = []
        dl = d.data_logger
        db_enabled = []
        if dl.sqlite_enabled:
            db_enabled.append("SQLite")
        if dl.mysql_enabled:
            db_enabled.append("MySQL")
        if dl.pg_enabled:
            db_enabled.append("PostgreSQL")
        # Never rebuild size cache on the UI thread — use last async result.
        if not getattr(self, "_size_cache", None) and db_enabled:
            self._schedule_size_cache_rebuild()
        if test_db:
            self._last_db_test_mono = _time.monotonic()
            self._schedule_size_cache_rebuild()
            self._schedule_db_connect_test()
        elif self._db_results is None and db_enabled:
            # First paint: kick an async probe; do not block the UI thread.
            self._schedule_db_connect_test()

        gt = d.growatt_tab
        tel = _growatt_telemetry_info(gt, d.app_params)
        growatt_state = gt.info_labels['status'].text() if 'status' in gt.info_labels else "--"
        inverter_lost = getattr(gt, "_inverter_comms_lost", False)
        lost_reason = ""
        if isinstance(getattr(gt, "mix_status_data", None), dict):
            inverter_lost, lost_reason = _growatt_inverter_comms_lost(
                gt.mix_status_data,
            )
        if gt.connect_btn.isEnabled() and gt.api and gt.device_sn:
            if inverter_lost:
                state_key = "bad"
                state_text = (
                    growatt_state
                    if "offline" in growatt_state.lower()
                    else "Inverter offline"
                )
            else:
                state_key = "ok"
                state_text = "Connected"
        elif not gt.connect_btn.isEnabled():
            state_key = 'idle'
            state_text = "Connecting"
        elif gt.api or gt.device_sn:
            state_key = 'warn'
            state_text = growatt_state or "Partial"
        else:
            state_key = 'bad'
            state_text = growatt_state or "Disconnected"
        growatt_detail = f"{gt.plant_name or '--'} | SN {gt.device_sn or '--'}"
        growatt_detail += f" | {_growatt_source_label(tel.get('source', GROWATT_TELEMETRY_API))}"
        if tel.get("hybrid") and not tel.get("grott_fresh") and gt.api and gt.device_sn:
            growatt_detail += " | Hybrid cloud fallback active"
        if inverter_lost and lost_reason and lost_reason != "—":
            growatt_detail += f" | {lost_reason}"
        growatt_last = gt.last_refresh_label.text().replace("Last refresh: ", "")
        rows.append((
            "Growatt server", state_text, state_key, growatt_detail, growatt_last,
            self._size_for("Growatt server"),
        ))

        gs = gt.grott_status() if hasattr(gt, "grott_status") else {}
        if tel.get("uses_grott"):
            if gs.get("fresh"):
                g_state_text, g_state_key = "Fresh telemetry", "ok"
            elif gs.get("connected"):
                g_state_text, g_state_key = "Connected", "warn"
            else:
                g_state_text, g_state_key = "Disconnected", "bad"
            if tel.get("hybrid") and not gs.get("fresh") and gt.api and gt.device_sn:
                g_state_text = "Stale — cloud fallback"
                g_state_key = "warn"
            g_detail = (
                f"{_growatt_source_label(tel.get('source', GROWATT_TELEMETRY_GROTT))} | "
                f"{gs.get('host') or '—'}:{gs.get('port') or '—'} | "
                f"{gs.get('topic') or 'energy/growatt'}"
            )
            if tel.get("fill_missing"):
                g_detail += " | fill missing: on"
                n = int(tel.get("api_filled_count") or 0)
                if n:
                    g_detail += f" ({n} amber)"
            if gs.get("serial"):
                g_detail += f" | SN {gs.get('serial')}"
            disc = int(gs.get("disconnect_count") or 0)
            rec = int(gs.get("reconnect_count") or 0)
            if disc or rec:
                g_detail += f" | link: {disc} disconnect(s), {rec} reconnect(s)"
            last_ev = gs.get("last_event") or ""
            if last_ev:
                g_detail += f" | last: {last_ev}"
            msg = gs.get("message")
            if msg:
                g_detail += f" | {msg}"
            rows.append((
                "Growatt local (Grott MQTT)",
                g_state_text,
                g_state_key,
                g_detail,
                self._fmt_age_s(gs.get("age_s")),
                "--",
            ))
        else:
            rows.append((
                "Growatt local (Grott MQTT)",
                "Disabled",
                "off",
                "Select GROTT MQTT or Hybrid as the Growatt telemetry source under Setup & Info.",
                "--",
                "--",
            ))

        p = d.app_params
        http_host = growatt_http_host(p)
        if not http_host:
            hc = self._growatt_http_cache
            rows.append((
                "Growatt local (ShineLan)",
                "Not configured",
                "off",
                "Set ShineLan / Wi‑Fi logger IP and web credentials under Setup & Info.",
                "--",
                "--",
            ))
        else:
            if self._growatt_http_probe_running:
                hc = {
                    "state_key": "idle",
                    "state_text": "Checking…",
                    "detail": "Reading ShineLan web UI network settings…",
                    "fresh": "--",
                }
            else:
                hc = self._growatt_http_cache
            rows.append((
                "Growatt local (ShineLan)",
                hc["state_text"],
                hc["state_key"],
                hc["detail"],
                hc["fresh"],
                "--",
            ))

        md_mode = (getattr(p, "growatt_modbus_mode", "off") or "off").lower()
        if md_mode == "off":
            mc = self._growatt_modbus_cache
            rows.append((
                "Growatt local (Modbus)",
                "Disabled",
                "off",
                "Set Modbus TCP or RTU under Setup & Info to verify local RS485 / gateway (separate from cloud).",
                "--",
                "--",
            ))
        else:
            if self._growatt_modbus_probe_running:
                mc = {
                    "state_key": "idle",
                    "state_text": "Checking…",
                    "detail": "Probing Modbus…",
                    "fresh": "--",
                }
            else:
                mc = self._growatt_modbus_cache
            rows.append((
                "Growatt local (Modbus)",
                mc["state_text"],
                mc["state_key"],
                mc["detail"],
                mc["fresh"],
                "--",
            ))
        inv_row = self._inverter_write_row(gt, md_mode, mc, growatt_last)
        rows.append((*inv_row, "--"))

        ot = d.octopus_tab
        hh = getattr(ot, 'hh_data', None)
        if hh is not None and not hh.empty:
            total_import, total_export, _, num_days = ot._last_summary or (0, 0, 0, 0)
            state_text, state_key = "Loaded", 'ok'
            detail = f"{num_days} days | {total_import:.1f} kWh import | {total_export:.1f} kWh export"
            fresh = self._latest_age_text(hh.reset_index().rename(columns={hh.index.name or 'index': 'interval_start'}))
        else:
            state_text, state_key = "No data", 'warn'
            detail = "Historic half-hourly data not loaded yet"
            fresh = "--"
        oct_hist_size = self._size_for("Octopus historic")
        if oct_hist_size == "--" and hh is not None and not hh.empty:
            oct_hist_size = f"{num_days}d in memory"
        rows.append((
            "Octopus historic", state_text, state_key, detail, fresh, oct_hist_size,
        ))

        olt = d.octopus_live_tab
        src = getattr(olt, '_data_source', 'REST')
        imp_df = getattr(olt, 'import_df', None)
        exp_df = getattr(olt, 'export_df', None)
        gql_msg = getattr(olt, '_gql_msg', '')
        if olt.fetching:
            state_text, state_key = "Fetching", 'idle'
        elif ((imp_df is not None and not imp_df.empty) or (exp_df is not None and not exp_df.empty)):
            if src == 'GraphQL':
                state_text, state_key = "Live GraphQL", 'ok'
            else:
                state_text, state_key = "REST fallback", 'warn'
        else:
            state_text = "No live data"
            state_key = 'bad'
        n_imp = 0 if imp_df is None else len(imp_df)
        n_exp = 0 if exp_df is None else len(exp_df)
        detail = f"{src} | {n_imp} import + {n_exp} export"
        if gql_msg:
            detail += f" | {gql_msg}"
        fresh = self._latest_age_text(imp_df, exp_df)
        rows.append((
            "Octopus live", state_text, state_key, detail, fresh,
            self._size_for("Octopus live", override=f"{n_imp + n_exp:,} live slots"),
        ))

        tt = d.tasmota_tab
        total = len(getattr(tt, 'device_ips', []) or [])
        online = len(getattr(tt, 'device_data', {}) or {})
        if tt.fetching:
            state_text, state_key = "Polling", 'idle'
        elif total == 0:
            state_text, state_key = "No targets", 'warn'
        elif online > 0:
            state_text, state_key = "Online", 'ok'
        else:
            state_text, state_key = "Offline", 'bad'
        db_tag = "DB history" if getattr(tt, '_db_history', {}) else "live history"
        detail = f"{online}/{total} devices online | {db_tag}"
        fresh = tt.status_label.text() if hasattr(tt, 'status_label') else "--"
        rows.append((
            "Tasmota devices", state_text, state_key, detail, fresh,
            self._size_for("Tasmota devices"),
        ))

        ft = d.forecasts_tab
        solar_msg = (getattr(ft, '_solar_last_msg', None) or "").strip()
        solar_fresh = getattr(ft, '_solar_last_refresh_local', None) or "--"
        sdf = getattr(ft, 'solar_df', None)
        fc_size = self._size_for("Forecast.solar")
        if ft.fetching:
            rows.append((
                "Forecast.solar",
                "Fetching",
                "idle",
                "PV curve + Agile refresh in progress",
                solar_fresh,
                fc_size,
            ))
        elif sdf is not None and not sdf.empty:
            low = solar_msg.lower()
            if low.startswith("solar error") or low.startswith("error:"):
                rows.append((
                    "Forecast.solar",
                    "Error",
                    "bad",
                    solar_msg[:200] if solar_msg else "Solar request failed",
                    solar_fresh,
                    fc_size,
                ))
            elif "rate limited" in low:
                rows.append((
                    "Forecast.solar",
                    "Rate limited",
                    "warn",
                    solar_msg[:200] if solar_msg else "429 — try later",
                    solar_fresh,
                    fc_size,
                ))
            else:
                kwp_e = ft.solar_edits.get('kwp')
                kwp_t = kwp_e.text().strip() if kwp_e else "?"
                det = f"{len(sdf)} samples | {kwp_t} kWp"
                if solar_msg and "calls remaining" in solar_msg:
                    det = f"{det} | {solar_msg.strip()}"
                elif solar_msg:
                    det = f"{det} | {solar_msg.strip()[:80]}"
                rows.append((
                    "Forecast.solar", "Loaded", "ok", det, solar_fresh, fc_size,
                ))
        else:
            low = solar_msg.lower()
            if "rate limited" in low:
                rows.append((
                    "Forecast.solar",
                    "Rate limited",
                    "warn",
                    solar_msg[:200] if solar_msg else "429 — try later",
                    solar_fresh,
                    fc_size,
                ))
            elif (
                low.startswith("error:")
                or low.startswith("solar error")
                or "no forecast" in low
                or ("forecast.solar:" in low and "open-meteo:" in low)
            ):
                rows.append((
                    "Forecast.solar",
                    "Failed",
                    "bad",
                    solar_msg[:200] if solar_msg else "No PV curve",
                    solar_fresh,
                    fc_size,
                ))
            else:
                rows.append((
                    "Forecast.solar",
                    "No data",
                    "warn",
                    "Forecast curve empty — open Forecasts tab or wait for startup fetch",
                    solar_fresh,
                    fc_size,
                ))

        try:
            from energy_dashboard.fetch.pvoutput import connectivity_row as _pvo_row
            pvo_st, pvo_sk, pvo_det, pvo_fr, pvo_sz = _pvo_row()
            rows.append(("PVOutput.org", pvo_st, pvo_sk, pvo_det, pvo_fr, pvo_sz))
        except Exception as exc:
            rows.append(("PVOutput.org", "Error", "warn", str(exc)[:160], "--", "--"))
        try:
            from energy_dashboard.fetch.wonderwatt import connectivity_row as _ww_row
            ww_st, ww_sk, ww_det, ww_fr, ww_sz = _ww_row()
            rows.append(("Wonderwatt.com", ww_st, ww_sk, ww_det, ww_fr, ww_sz))
        except Exception as exc:
            rows.append(("Wonderwatt.com", "Error", "warn", str(exc)[:160], "--", "--"))

        if not db_enabled:
            rows.append((
                "Databases", "Disabled", "off",
                "No database backends enabled", "--", "--",
            ))
        else:
            if self._db_test_building and self._db_results is None:
                state_text, state_key = "Checking…", "idle"
                detail = "Probing database backends…"
                db_fresh = "--"
            elif self._db_results is None:
                state_text, state_key = "Pending", "idle"
                detail = "Database probe not finished yet"
                db_fresh = "--"
            else:
                ok_count = sum(1 for ok, _ in self._db_results.values() if ok)
                if ok_count == len(self._db_results):
                    state_text, state_key = "Connected", 'ok'
                elif ok_count > 0:
                    state_text, state_key = "Partial", 'warn'
                else:
                    state_text, state_key = "Failed", 'bad'
                detail = " | ".join(
                    f"{name}: {'OK' if ok else info}" for name, (ok, info) in self._db_results.items()
                )
                db_fresh = self._db_test_time
            rows.append((
                "Databases", state_text, state_key, detail, db_fresh,
                self._size_for("Databases"),
            ))

        rows = self._apply_disabled_and_log_transitions(rows)

        try:
            from energy_dashboard.config import growatt_modbus_writes_allowed
            self._modbus_writes_active = growatt_modbus_writes_allowed(
                d.app_params, QSettings("PowerModel", "EnergyDashboard2"),
            )
        except Exception:
            self._modbus_writes_active = False

        self.table.setRowCount(len(rows))
        for idx, row in enumerate(rows):
            self._set_row(idx, *row)
        try:
            volumes, db_enabled = self._collect_box_volumes(d)
            if md_mode == "off":
                modbus = "off"
            elif self._growatt_modbus_probe_running:
                modbus = "idle"
            else:
                modbus = self._growatt_modbus_cache.get("state_key", "off")
            try:
                from energy_dashboard.fetch.pvoutput import connectivity_row as _pvo_row
                _pvo_direct = _pvo_row()[1]
            except Exception:
                _pvo_direct = "off"
            try:
                from energy_dashboard.fetch.wonderwatt import connectivity_row as _ww_row
                _ww_direct = _ww_row()[1]
            except Exception:
                _ww_direct = "off"
            self._flow_diagram.set_health_from_rows(
                rows,
                direct={
                    "modbus": modbus,
                    "pvoutput": _pvo_direct,
                    "wonderwatt": _ww_direct,
                },
            )
            self._flow_diagram.set_growatt_telemetry(tel)
            self._flow_diagram.set_volumes(volumes)
            self._push_diagram_alarms()
            if db_enabled:
                self._refresh_db_volumes_async(
                    db_enabled, volumes, force=bool(test_db),
                )
        except Exception:
            pass
        self.updated_label.setText(f"Updated: {datetime.now().strftime('%H:%M:%S')}")

        ok = sum(1 for _, _, state_key, *_ in rows if state_key == "ok")
        warn = sum(1 for _, _, state_key, *_ in rows if state_key == "warn")
        bad = sum(1 for _, _, state_key, *_ in rows if state_key == "bad")
        idle = sum(1 for _, _, state_key, *_ in rows if state_key == "idle")
        solar_ok = (
            sdf is not None and not sdf.empty and not ft.fetching
            and not (solar_msg.lower().startswith(("solar error", "error:"))
                     or "rate limited" in solar_msg.lower())
        )
        _mdm = (getattr(d.app_params, "growatt_modbus_mode", "off") or "off").lower()
        if _mdm == "off":
            modbus_line = "Growatt local Modbus: not enabled (off)"
        else:
            _cm = self._growatt_modbus_cache
            modbus_line = (
                f"Growatt local Modbus: {_cm.get('state_text', '—')} | "
                f"{( _cm.get('detail') or '')[:160]}"
            )
        _hc = self._growatt_http_cache
        if growatt_http_host(d.app_params):
            shinelan_line = (
                f"ShineLan logger: {_hc.get('state_text', '—')} | "
                f"{(_hc.get('detail') or '')[:160]}"
            )
        else:
            shinelan_line = "ShineLan logger: not configured"
        from energy_dashboard.config import growatt_modbus_writes_allowed
        _mb_wr = growatt_modbus_writes_allowed(
            d.app_params, QSettings("PowerModel", "EnergyDashboard2"),
        )
        _wr_ok = gt.connect_btn.isEnabled() and gt.api and gt.device_sn
        if _wr_ok and _mb_wr:
            _wr_line = "Inverter write: cloud REST + Modbus writes ENABLED"
        elif _wr_ok:
            _wr_line = "Inverter write (schedules): yes — via Growatt cloud REST"
        elif _mb_wr:
            _wr_line = (
                "Inverter write: Modbus writes ENABLED "
                "(cloud schedule push still needs Growatt Live Connect)"
            )
        elif gt.device_sn and not gt.api:
            _wr_line = (
                "Inverter write (schedules): no — Grott SN only; "
                "Connect cloud or Enable Modbus writes"
            )
        else:
            _wr_line = (
                "Inverter write: no until Growatt Live cloud session "
                "or Enable Modbus inverter writes"
            )
        if gt.api and gt.device_sn:
            if inverter_lost:
                growatt_summary = (
                    "Growatt cloud: yes · inverter live data: no (comms lost)"
                )
            else:
                growatt_summary = "Growatt cloud: yes · inverter live data: yes"
        else:
            growatt_summary = "Growatt cloud: no"
        src_line = f"Growatt source: {_growatt_source_label(tel.get('source', GROWATT_TELEMETRY_API))}"
        if tel.get("hybrid") and tel.get("grott_fresh"):
            src_line += " · Grott primary"
        elif tel.get("hybrid") and gt.api and gt.device_sn:
            src_line += " · cloud fallback"
        elif tel.get("fill_missing") and tel.get("uses_grott"):
            src_line += " · API patch gaps on"
        def _summary_cell(title, lines):
            body = "<br>".join(html.escape(str(x)) for x in lines if x)
            return (
                "<td width='33%' valign='top' style='padding:0 12px 0 0;'>"
                f"<span style='color:#89b4fa;font-weight:bold;'>{html.escape(title)}</span><br>"
                f"<span style='color:#cdd6f4;'>{body}</span>"
                "</td>"
            )

        self.summary.setHtml(
            "<div style='font-family:Courier New, monospace; font-size:10px; line-height:1.15;'>"
            "<table width='100%' cellspacing='0' cellpadding='0'><tr>"
            + _summary_cell(
                "Connectivity",
                [
                    f"OK {ok} | Warn {warn} | Bad {bad} | Progress {idle}",
                    growatt_summary,
                    src_line,
                    _wr_line,
                ],
            )
            + _summary_cell(
                "Feeds",
                [
                    f"Octopus historic: {'yes' if hh is not None and not hh.empty else 'no'}",
                    f"Octopus live: {src}",
                    f"Tasmota: {online}/{total}",
                    f"Forecast PV: {'yes' if solar_ok else 'no'} ({solar_fresh})",
                ],
            )
            + _summary_cell(
                "Local / Store",
                [
                    f"DB test: {self._db_test_time}",
                    shinelan_line,
                    modbus_line,
                ],
            )
            + "</tr></table></div>"
        )

        # Local ShineLan / Modbus probes: only when explicitly allowed (timer /
        # manual Refresh) or still "Not probed yet". Never chain-restart from
        # probe completion callbacks (those pass allow_local_probes=False).
        if allow_local_probes is None:
            allow_local_probes = (
                self._growatt_modbus_cache.get("detail") == "Not probed yet"
                or self._growatt_http_cache.get("detail") == "Not probed yet"
            )
        now_m = _time.monotonic()
        if (
            allow_local_probes
            and not self._suppress_modbus_probe
            and not self._growatt_modbus_probe_running
            and (getattr(d.app_params, "growatt_modbus_mode", "off") or "off").lower() != "off"
            and (
                (now_m - self._last_modbus_probe_mono) >= 90.0
                or self._growatt_modbus_cache.get("detail") == "Not probed yet"
            )
        ):
            self._start_growatt_modbus_probe(d.app_params)
        if (
            allow_local_probes
            and not self._suppress_http_probe
            and not self._growatt_http_probe_running
            and growatt_http_host(d.app_params)
            and (
                (now_m - self._last_http_probe_mono) >= 90.0
                or self._growatt_http_cache.get("detail") == "Not probed yet"
            )
        ):
            self._start_growatt_http_probe(d.app_params)


__all__ = [n for n in globals() if not n.startswith('__')]
