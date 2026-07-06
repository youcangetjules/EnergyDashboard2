"""
Energy Dashboard — `tabs/connectivity.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *
from energy_dashboard.db.health_stats import KNOWN_TABLES, _fmt_size, _open_db, collect_health_stats
from energy_dashboard.db.retention import _relation_size_bytes
from energy_dashboard.db.retention import format_policy_block, targets_for_box
from energy_dashboard.dialogs.data_retention import ConnectivityRetentionDialog
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
    return {
        "source": source,
        "uses_grott": growatt_uses_grott(source),
        "hybrid": source == GROWATT_TELEMETRY_HYBRID,
        "fill_missing": bool(fill_missing),
        "api_filled_count": len(api_filled or ()),
        "grott_fresh": bool(gs.get("fresh")),
        "grott_connected": bool(gs.get("connected")),
        "grott_running": bool(gs.get("enabled")),
    }


def _growatt_source_label(source: str) -> str:
    if source == GROWATT_TELEMETRY_HYBRID:
        return "Hybrid (Grott → API fallback)"
    if source == GROWATT_TELEMETRY_GROTT:
        return "GROTT MQTT"
    return "Growatt Cloud API"

_CONNECTIVITY_BOX_SERVICES = {
    "growatt_cloud": ("Growatt API", ("Growatt server", "Inverter write (this app)")),
    "grott": ("GROTT / Hybrid", ("Growatt local (Grott MQTT)",)),
    "octopus": ("Octopus", ("Octopus historic", "Octopus live")),
    "forecast": ("PV forecast", ("Forecast.solar",)),
    "modbus_lan": ("Modbus", ("Growatt local (Modbus)",)),
    "tasmota": ("Tasmota", ("Tasmota devices",)),
    "lan_direct": ("LAN Direct", ("Growatt local (Modbus)",)),
    "wifi_direct": ("WiFi Direct", ()),
    "emqx": ("EMQX", ("Growatt local (Modbus)", "Growatt local (ShineLan)", "Growatt local (Grott MQTT)")),
    "database": ("Databases", ("Databases",)),
    "export": ("Exported data", ("Databases",)),
    "storage": ("Databases & Exports", ("Databases",)),
    "dashboard": ("Energy Dashboard", ()),
}


class _ConnectivityDetailDialog(QDialog):
    _CONTENT_WIDTH = 440
    _CONTENT_PAD = 24

    def __init__(self, title, body, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setFont(QFont("Helvetica", 10))
        te.setFrameShape(QFrame.Shape.NoFrame)
        te.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        te.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        te.setPlainText(body)
        doc = te.document()
        doc.setTextWidth(float(self._CONTENT_WIDTH))
        doc_h = int(doc.size().height())
        te_h = max(120, doc_h + self._CONTENT_PAD)
        screen = QApplication.primaryScreen()
        if screen is not None:
            max_h = int(screen.availableGeometry().height() * 0.88) - 90
            if te_h > max_h:
                te_h = max_h
                te.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            else:
                te.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        else:
            te.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        te.setFixedSize(self._CONTENT_WIDTH + 8, te_h)
        te.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(te, 0, Qt.AlignmentFlag.AlignLeft)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)
        layout.addWidget(buttons)
        self.adjustSize()


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
        self.setMinimumHeight(400)
        self.setMinimumWidth(360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._anim = QTimer(self)
        self._anim.setInterval(50)
        self._anim.timeout.connect(self._tick)
        self._anim.start()

    def _tick(self):
        self._phase = (self._phase + 0.018) % 1.0
        self.update()

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
        self._health = {
            "growatt_cloud": raw.get("growatt_cloud", "off"),
            "grott": raw.get("grott", "off"),
            "octopus": oc or "off",
            "forecast": raw.get("forecast", "off"),
            "modbus_lan": raw.get("modbus_lan", "off"),
            "tasmota": raw.get("tasmota", "off"),
            "lan_direct": direct.get("lan_direct", raw.get("modbus_lan", "off")),
            "wifi_direct": direct.get("wifi_direct", "off"),
            "database": db,
            "export": ex,
        }
        emqx = self._worst_state(
            self._health.get("lan_direct", "off"),
            self._health.get("wifi_direct", "off"),
            self._health.get("grott", "off"),
        )
        if (
            self._health.get("lan_direct") == "ok"
            or self._health.get("wifi_direct") == "ok"
            or self._health.get("grott") == "ok"
        ):
            emqx = "ok"
        self._health["emqx"] = emqx or "off"
        self.update()

    def _link_flow_state(self, health_key, fr=None, to=None):
        if health_key is None:
            return "ok"
        src = self._telemetry.get("source", GROWATT_TELEMETRY_API)
        if fr == "lan_direct" and to == "grott" and self._telemetry.get("uses_grott"):
            return self._health.get("grott", self._health.get("lan_direct", "off"))
        if fr == "grott" and to == "emqx" and self._telemetry.get("uses_grott"):
            grott = self._health.get("grott", "off")
            emqx = self._health.get("emqx", "off")
            return self._worst_state(grott, emqx) or "off"
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
        if key == "grott":
            if src == GROWATT_TELEMETRY_HYBRID:
                title, sub = "GROTT / Hybrid", "MQTT primary · API fallback"
            elif src == GROWATT_TELEMETRY_GROTT:
                title, sub = "GROTT", "MQTT primary"
            else:
                title, sub = "GROTT", "not selected"
            if t.get("fill_missing") and src in (GROWATT_TELEMETRY_GROTT, GROWATT_TELEMETRY_HYBRID):
                sub += " · API patch gaps"
            return title, sub
        if key == "growatt_cloud":
            if src == GROWATT_TELEMETRY_HYBRID:
                if t.get("grott_fresh"):
                    sub = "cloud REST · standby fallback"
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
    ):
        edge = QColor(accent)
        if hover:
            edge = edge.lighter(120)
        if main:
            base = QColor("#2563eb")
            base2 = QColor("#4338ca")
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            grad.setColorAt(0.0, base)
            grad.setColorAt(1.0, base2)
            p.setBrush(grad)
            p.setPen(QPen(edge.lighter(130), 2))
        else:
            fill = QColor("#1f2937")
            if hover:
                fill = fill.lighter(110)
            p.setBrush(fill)
            p.setPen(QPen(edge, 1.8))
        p.drawRoundedRect(rect, 10, 10)

        if vertical:
            p.save()
            p.translate(rect.center())
            p.rotate(-90)
            p.setPen(QColor("#e2e8f0"))
            ft = QFont("Helvetica", 9, QFont.Bold)
            p.setFont(ft)
            tw = int(rect.height() - 16)
            th = int(rect.width() - 16)
            p.drawText(
                QRectF(-tw * 0.5, -th * 0.5, tw, th),
                int(Qt.AlignCenter | Qt.TextFlag.TextWordWrap),
                title,
            )
            p.restore()
            return

        p.setPen(QColor("#f8fafc") if main else QColor("#e2e8f0"))
        f1 = QFont("Helvetica", 9 if not main else 10, QFont.Bold)
        p.setFont(f1)
        p.drawText(
            QRectF(rect.left() + 10, rect.top() + 8, rect.width() - 20, 18),
            Qt.AlignLeft | Qt.AlignTop,
            title,
        )
        if subtitle:
            p.setPen(QColor("#cbd5e1") if main else QColor("#94a3b8"))
            f2 = QFont("Helvetica", 8)
            p.setFont(f2)
            p.drawText(
                QRectF(rect.left() + 10, rect.top() + 26, rect.width() - 20, rect.height() - 30),
                int(Qt.AlignLeft | Qt.AlignTop | Qt.TextFlag.TextWordWrap),
                subtitle,
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

    # Exact blueprint from the reference React diagram. (cx, cy, w, h) where
    # (cx, cy) is the node centre in a 1100 x 500 virtual canvas.
    _ARCH_VBW = 1100.0
    _ARCH_VBH = 500.0
    _ARCH_SPEC = {
        "inverter": (45, 96.5, 56, 113),
        "wifi_direct": (240, 60, 210, 40),
        "lan_direct": (240, 133, 210, 40),
        "tasmota": (122, 206, 210, 40),
        "octopus": (122, 279, 210, 40),
        "forecast": (122, 352, 210, 40),
        "growatt_cloud": (460, 60, 150, 40),
        "grott": (460, 133, 150, 40),
        "emqx": (640, 200, 150, 40),
        "ai": (955, 55, 230, 44),
        "dashboard": (955, 200, 200, 140),
        "storage": (955, 350, 240, 44),
    }

    def _compute_layout(self, W, H):
        """Faithful port of the React blueprint: nodes live in a 1100x500 virtual
        canvas and are mapped into the widget with a non-uniform scale (matching
        the React SVG `preserveAspectRatio='none'` + percentage layout). The
        header occupies the top strip; the diagram fills the rest."""
        bp = {
            key: QRectF(cx - w * 0.5, cy - h * 0.5, w, h)
            for key, (cx, cy, w, h) in self._ARCH_SPEC.items()
        }
        ax = 10.0
        ay = 46.0
        aw = max(60.0, W - 20.0)
        ah = max(60.0, H - ay - 10.0)
        sx = aw / self._ARCH_VBW
        sy = ah / self._ARCH_VBH
        return {"bp": bp, "ax": ax, "ay": ay, "sx": sx, "sy": sy}

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
        return "\n".join(lines)

    def _volume_block(self, box_key):
        lines = self._box_volumes.get(box_key) or []
        if not lines:
            return ""
        return "Data volumes:\n" + "\n".join(f"  · {ln}" for ln in lines)

    def _append_volumes(self, blocks, box_key):
        vol = self._volume_block(box_key)
        if vol:
            blocks.append(vol)

    def _format_box_details(self, box_key):
        title, services = _CONNECTIVITY_BOX_SERVICES.get(box_key, (box_key, ()))
        blocks = []
        flow = self._health.get(box_key, "off")
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
        if box_key == "emqx":
            blocks.append(
                "MQTT broker path for local Growatt / LAN telemetry. LAN Direct "
                "and WiFi Direct publish through EMQX; GROTT / Hybrid consumes "
                "decoded Growatt JSON from here.\n\n"
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
            self._append_volumes(blocks, "lan_direct")
            self._append_volumes(blocks, "wifi_direct")
            self._append_volumes(blocks, "grott")
            return title, "\n\n".join(blocks)
        if box_key == "grott":
            t = self._telemetry
            blocks.append(
                "Local GROTT proxy decodes inverter traffic into MQTT JSON. "
                "In <b>Hybrid</b> mode this is the preferred live path; the "
                "Growatt API box becomes fallback when Grott is stale. "
                "The fill-missing checkbox patches individual registers from "
                "the cloud without switching the whole source.\n\n"
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
        blocks.append(f"Diagram status: {self._state_label(flow)}")
        for svc in services:
            row = self._service_rows.get(svc)
            if row:
                blocks.append(self._format_row_block(row))
            else:
                blocks.append(f"{svc}\n  No status row available.")
        if box_key == "wifi_direct":
            tab = self._tab
            if tab is not None:
                hc = tab._growatt_http_cache
                blocks.append(
                    "WiFi Direct (inverter web UI port)\n"
                    f"  Status: {hc.get('state_text', '—')} ({self._state_label(hc.get('state_key', 'off'))})\n"
                    f"  Details: {hc.get('detail', '—')}\n"
                    f"  Last / freshness: {hc.get('fresh', '--')}"
                )
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
            tab.open_ring_buffers_dialog("database" if box_key == "storage" else box_key)
            return
        title, body = self._format_box_details(box_key)
        dlg = _ConnectivityDetailDialog(title, body, self)
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
                        idle_color="#566483", strength=1.0):
        """Draw a prebuilt connector path in the reference React style.
        ok = animated flow, idle = faint dashed, warn/bad/off = faint static."""
        p.setBrush(Qt.BrushStyle.NoBrush)
        if state == "ok":
            base = QPen(QColor("#1e293b"))
            base.setWidthF(2.8)
            base.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(base)
            p.drawPath(path)
            halo = QPen(QColor(color))
            halo.setWidthF(1.4 * strength)
            halo.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(halo)
            p.drawPath(path)
            anim = QPen(QColor(color))
            anim.setWidthF(2.2 * strength)
            anim.setCapStyle(Qt.PenCapStyle.RoundCap)
            anim.setStyle(Qt.PenStyle.DashLine)
            anim.setDashPattern([2, 22])
            anim.setDashOffset(-self._phase * 22.0)
            p.setPen(anim)
            p.drawPath(path)
        elif state == "idle":
            base = QPen(QColor("#0f172a"))
            base.setWidthF(2.6)
            base.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(base)
            p.drawPath(path)
            pen = QPen(QColor(idle_color))
            pen.setWidthF(1.3)
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern([5, 7])
            p.setPen(pen)
            p.drawPath(path)
        else:
            faint = QColor(color)
            faint.setAlpha(80 if state in ("warn", "bad") else 40)
            pen = QPen(faint)
            pen.setWidthF(1.3)
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

    def paintEvent(self, event):
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
        p.setPen(QColor("#f8fafc"))
        p.setFont(QFont("Helvetica", 10, QFont.Bold))
        p.drawText(QRectF(16, 8, W - 32, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   "Energy Data Architecture")
        p.setPen(QColor("#94a3b8"))
        p.setFont(QFont("Helvetica", 8))
        p.drawText(QRectF(16, 26, W - 32, 14), Qt.AlignLeft | Qt.AlignVCenter,
                   "Producers -> brokers -> dashboard -> storage")

        # Blueprint -> widget transform (non-uniform, like React preserveAspectRatio='none').
        layout = self._compute_layout(W, H)
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

        # Legend (right-aligned in the header strip).
        legend = [
            ("Internet", "#38bdf8"),
            ("Home LAN", "#34d399"),
            ("Storage", "#a78bfa"),
            ("Control", "#fbbf24"),
            ("Idle", "#a16207"),
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

        # Forward data connections (faithful to the React blueprint):
        # (fr, fe, ft, to, te, tt, color, straight, curveK, health_key)
        data_conns = [
            ("inverter", "right", 0.236, "wifi_direct", "left", 2 / 3, sky, True, None, "wifi_direct"),
            ("inverter", "right", 0.882, "lan_direct", "left", 2 / 3, emerald, True, None, "lan_direct"),
            ("wifi_direct", "right", 0.67, "growatt_cloud", "left", 0.67, sky, False, None, "growatt_cloud"),
            ("lan_direct", "right", 0.67, "grott", "left", 0.67, emerald, False, None, "lan_direct"),
            ("growatt_cloud", "right", 0.67, "dashboard", "left", 0.286, sky, False, None, "growatt_cloud"),
            ("grott", "right", 0.6, "emqx", "top", 0.4, emerald, False, 30.0, "emqx"),
            ("tasmota", "right", 0.67, "emqx", "left", 0.67, emerald, False, None, "tasmota"),
            ("emqx", "right", 0.67, "dashboard", "left", 0.571, emerald, False, None, "emqx"),
            ("octopus", "right", 0.5, "dashboard", "left", 0.714, sky, False, None, "octopus"),
            ("forecast", "right", 0.5, "dashboard", "left", 0.857, sky, False, None, "forecast"),
            ("dashboard", "top", 0.33, "ai", "bottom", 0.33, violet, False, None, None),
            ("dashboard", "bottom", 0.5, "storage", "top", 0.5, violet, False, None, None),
        ]
        probe_link_map = {
            ("lan_direct", "grott"): "inv_grott",
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
            self._draw_arch_link(p, path, state, color=link_color)

        # Hybrid fallback path (Grott ↔ cloud API) — dashed amber when configured.
        if self._telemetry.get("source") == GROWATT_TELEMETRY_HYBRID:
            path = build("grott", "top", 0.5, "growatt_cloud", "bottom", 0.5, straight=False, curveK=45.0)
            state = self._link_flow_state("grott", fr="grott", to="growatt_cloud")
            self._draw_arch_link(
                p, path, state, color="#fbbf24", idle_color="#a16207", strength=0.65,
            )

        # Reverse control connections (amber):
        # (fr, fe, ft, to, te, tt, active, straight, curveK)
        ctrl_conns = [
            ("ai", "bottom", 0.67, "dashboard", "top", 0.67, True, False, None),
            ("dashboard", "left", 0.429, "emqx", "right", 0.33, True, False, None),
            ("emqx", "top", 0.6, "grott", "right", 0.4, True, False, 30.0),
            ("emqx", "left", 0.33, "tasmota", "right", 0.33, True, False, None),
            ("grott", "left", 0.33, "lan_direct", "right", 0.33, True, False, None),
            ("lan_direct", "left", 1 / 3, "inverter", "right", 0.764, True, True, None),
            ("dashboard", "left", 0.143, "growatt_cloud", "right", 0.33, False, False, None),
            ("growatt_cloud", "left", 0.33, "wifi_direct", "right", 0.33, False, False, None),
            ("wifi_direct", "left", 1 / 3, "inverter", "right", 0.118, False, True, None),
        ]
        for fr, fe, ft, to, te, tt, active, straight, ck in ctrl_conns:
            path = build(fr, fe, ft, to, te, tt, straight=straight, curveK=ck)
            self._draw_arch_link(p, path, "ok" if active else "idle",
                                 color=amber, idle_color="#a16207")

        # ---- Node cards ----
        cards = [
            ("inverter", "Growatt Inverter", "", "lan", "modbus_lan", True, False),
            ("wifi_direct", "Growatt WiFi Direct", "inverter web UI", "internet", "wifi_direct", False, False),
            ("lan_direct", "Growatt LAN Direct", "Modbus TCP / RTU", "lan", "lan_direct", False, False),
            ("tasmota", "Tasmota", "Wi-Fi devices", "lan", "tasmota", False, False),
            ("octopus", "Octopus", "REST / GraphQL", "internet", "octopus", False, False),
            ("forecast", "PV forecast", "Forecast.Solar · Open-Meteo", "internet", "forecast", False, False),
            ("growatt_cloud", "Growatt API", "cloud REST", "internet", "growatt_cloud", False, False),
            ("grott", "GROTT", "Growatt proxy", "lan", "grott", False, False),
            ("emqx", "EMQX", "MQTT broker", "lan", "emqx", False, False),
            ("ai", "AI Controller", "optimise · schedule", "ai", "ai", False, False),
            ("dashboard", "Energy Dashboard", "publish / subscribe", "internet", "dashboard", False, True),
            ("storage", "Databases & Exports", "SQLite · MySQL · .xlsx · logs", "data", "storage", False, False),
        ]
        group_color = {
            "internet": "#38bdf8",
            "lan": "#34d399",
            "data": "#a78bfa",
            "ai": "#fbbf24",
        }
        probe_card_keys = {
            "wifi_direct": "wifi_direct",
            "lan_direct": "lan_direct",
            "grott": "grott",
            "emqx": "emqx",
            "dashboard": "dashboard",
        }
        for key, title, sub, grp, health_key, vertical, main in cards:
            rect = nodes[key]
            title, sub = self._diagram_card_copy(key, title, sub)
            click_key = health_key if health_key in _CONNECTIVITY_BOX_SERVICES else None
            if click_key is not None:
                self._hit_regions.append((click_key, title, rect))
            self._draw_arch_card(
                p,
                rect,
                title,
                sub,
                accent=group_color.get(grp, "#94a3b8"),
                hover=(click_key is not None and self._hover_key == click_key),
                main=main,
                vertical=vertical,
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
        self._timer = QTimer()
        self._timer.setInterval(15000)
        self._timer.timeout.connect(lambda: self.refresh_status(test_db=True))
        self.build_ui()
        self.refresh_status(test_db=True)
        self._timer.start()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        ctrl = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Status")
        self.refresh_btn.clicked.connect(lambda: self.refresh_status(test_db=False))
        ctrl.addWidget(self.refresh_btn)
        self.test_db_btn = QPushButton("Test Databases")
        self.test_db_btn.clicked.connect(lambda: self.refresh_status(test_db=True))
        ctrl.addWidget(self.test_db_btn)
        self.ring_buffers_btn = QPushButton("Ring buffers…")
        self.ring_buffers_btn.setToolTip(
            "Per-table ring-buffer limits (max rows, age, size) for logged data"
        )
        self.ring_buffers_btn.clicked.connect(lambda: self.open_ring_buffers_dialog("database"))
        ctrl.addWidget(self.ring_buffers_btn)
        self.probe_pipeline_btn = QPushButton("Probe pipeline…")
        self.probe_pipeline_btn.setToolTip(
            "Trace Growatt WiFi → GROTT → EMQX → dashboard and highlight breaks"
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
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget { alternate-background-color: #252536; }"
        )
        qtable_set_column_width_key(self.table, "connectivity_status")
        qtable_prepare_interactive_columns(self.table)
        qtable_restore_column_widths(self.table, "connectivity_status", resize_if_no_saved=True)
        qtable_attach_column_width_persistence(self.table)

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
        if box_key not in ("database", "export"):
            box_key = "database"
        _, body = self._flow_diagram._format_box_details(box_key)
        dlg = ConnectivityRetentionDialog(
            box_key,
            body,
            table_stats=self._retention_table_stats(),
            data_logger=self.dash.data_logger,
            parent=self,
        )
        dlg.exec()

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
        for col, val in enumerate(vals):
            item = QTableWidgetItem(str(val))
            if col == 1:
                item.setForeground(QBrush(QColor(color)))
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            elif col == 4:
                item.setForeground(QBrush(QColor("#a6adc8")))
            self.table.setItem(row, col, item)

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

    def _build_table_size_cache(self, enabled_backends: list[str]) -> dict[str, str]:
        """Service name → Table size column (from health stats + PG relation sizes)."""
        self._table_info = {}
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
                prev = self._table_info.get(table, {})
                rows_n = int(info.get("row_count") or 0)
                if rows_n >= int(prev.get("row_count") or 0):
                    self._table_info[table] = {
                        "row_count": rows_n,
                        "last_activity": info.get("last_activity"),
                        "size_human": prev.get("size_human"),
                    }
            if backend == "PostgreSQL":
                try:
                    with _open_db(backend, cap) as (conn, dialect, _):
                        cur = conn.cursor()
                        for table, _ts in KNOWN_TABLES:
                            if table not in self._table_info:
                                continue
                            sz = _relation_size_bytes(cur, dialect, table)
                            if sz:
                                self._table_info[table]["size_human"] = _fmt_size(sz)
                except Exception:
                    pass
        return {
            "Growatt server": self._fmt_db_tables_cell("growatt_readings"),
            "Octopus historic": self._fmt_db_tables_cell("octopus_readings"),
            "Tasmota devices": self._fmt_db_tables_cell(
                "tasmota_readings", "tasmota_devices"
            ),
            "Forecast.solar": self._fmt_db_tables_cell(
                "solar_forecast_snapshots", "agile_price_snapshots"
            ),
            "Databases": " | ".join(db_parts) if db_parts else "--",
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
        if not gt.connect_btn.isEnabled():
            return (
                "Inverter write (this app)",
                "Starting…",
                "idle",
                "Growatt cloud session not ready yet. When connected, schedule push "
                "uses the Growatt server REST API — not local Modbus from this app.",
                "--",
            )
        cloud_ok = bool(gt.api and gt.device_sn)
        if cloud_ok:
            det = (
                "Optimiser and AC charge / forced-discharge actions POST "
                "mix_ac_charge_time_period and mix_ac_discharge_time_period "
                "through the logged-in Growatt API. This app does not write "
                "inverter holding registers over local Modbus."
            )
            if md_mode == "off":
                det += (
                    " Local Modbus: disabled in Setup (optional read-only probe only)."
                )
            elif self._growatt_modbus_probe_running:
                det += " Local Modbus: probe running — read test only; not used for writes."
            else:
                mk = (mc or {}).get("state_key", "")
                if mk == "ok":
                    det += (
                        " Local Modbus read path OK — external tools could "
                        "Modbus-write; PowerModel does not."
                    )
                else:
                    mt = (mc or {}).get("state_text", "—")
                    det += (
                        f" Local Modbus: {mt} — does not block cloud schedule "
                        "writeback when Growatt server shows Connected."
                    )
            return (
                "Inverter write (this app)",
                "Yes — Growatt cloud (REST)",
                "ok",
                det,
                growatt_last or "--",
            )
        if gt.api or gt.device_sn:
            return (
                "Inverter write (this app)",
                "Partial session",
                "warn",
                "Growatt login looks incomplete. Finish connecting on the Live tab "
                "to enable schedule writeback via cloud.",
                growatt_last or "--",
            )
        return (
            "Inverter write (this app)",
            "No — need Growatt cloud login",
            "bad",
            "No Growatt API session. Connect on the Live tab first. A working "
            "local Modbus read probe does not enable schedule push from this app.",
            "--",
        )

    def _start_growatt_modbus_probe(self, app_params):
        """Background Modbus read to verify local TCP/RTU path (non-blocking)."""
        if self._growatt_modbus_probe_running:
            return
        self._growatt_modbus_probe_running = True
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
                self._suppress_modbus_probe = True
                try:
                    self.refresh_status(test_db=False)
                finally:
                    self._suppress_modbus_probe = False

            self._inv.invoke(done)

        threading.Thread(target=work, daemon=True).start()

    def _start_growatt_http_probe(self, app_params):
        """Background ShineLan web UI settings read (non-blocking)."""
        if self._growatt_http_probe_running:
            return
        host = growatt_http_host(app_params)
        if not host:
            return
        self._growatt_http_probe_running = True
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
                self._suppress_http_probe = True
                try:
                    self.refresh_status(test_db=False)
                finally:
                    self._suppress_http_probe = False

            self._inv.invoke(done)

        threading.Thread(target=work, daemon=True).start()

    def _start_pipeline_probe(self):
        """Background Growatt pipeline probe (WiFi, GROTT, EMQX, dashboard)."""
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
        """Row counts / last activity per table for retention dialog (first OK backend)."""
        dl = self.dash.data_logger
        enabled = []
        if dl.sqlite_enabled:
            enabled.append("SQLite")
        if dl.mysql_enabled:
            enabled.append("MySQL")
        if dl.pg_enabled:
            enabled.append("PostgreSQL")
        merged: dict = {}
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
                    }
        log_path = Path.home() / ".energy_dashboard_console.jsonl"
        if log_path.is_file():
            try:
                merged["console_log"] = {
                    "row_count": sum(1 for _ in log_path.open(encoding="utf-8")),
                    "last_activity": "file on disk",
                }
            except OSError:
                pass
        return merged

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
            "modbus_lan": [],
            "tasmota": [],
            "lan_direct": [],
            "wifi_direct": [],
            "database": [],
            "export": [],
            "dashboard": [],
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

        md_mode = (getattr(d.app_params, "growatt_modbus_mode", "off") or "off").lower()
        if md_mode == "off":
            vol["modbus_lan"].append("Not configured")
            vol["lan_direct"].append("Not configured")
        else:
            vol["modbus_lan"].append(f"Mode: {md_mode}")
            vol["lan_direct"].append(f"Mode: {md_mode}")
            tcp_host = growatt_modbus_tcp_host(d.app_params)
            if tcp_host:
                vol["lan_direct"].append(
                    f"Target: {tcp_host}:{getattr(d.app_params, 'growatt_modbus_tcp_port', 502)}"
                )
            else:
                vol["lan_direct"].append("LAN/Wi‑Fi IP not configured")
        http_host = growatt_http_host(d.app_params)
        if http_host:
            hc = self._growatt_http_cache or {}
            vol["wifi_direct"].append(
                f"Wi‑Fi: {http_host}:{getattr(d.app_params, 'growatt_local_port', 80)}"
            )
            if hc.get("server_ip"):
                target = f"{hc.get('server_ip')}:{hc.get('server_port') or '—'}"
                vol["wifi_direct"].append(f"ShineLan cloud target: {target}")
        else:
            vol["wifi_direct"].append("Not configured")
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
            vol["wifi_direct"].append(f"Grott MQTT: {target} {topic} ({state})")
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

    def _refresh_db_volumes_async(self, enabled, base_volumes):
        cap = self._db_cap()

        def work():
            vol = dict(base_volumes)
            db_lines = list(vol.get("database", []))
            table_map = {
                "growatt_readings": "growatt_cloud",
                "octopus_readings": "octopus",
                "tasmota_readings": "tasmota",
            }
            extra = {k: [] for k in vol}
            export_rows = 0
            for backend in enabled:
                stats = collect_health_stats(backend, cap)
                if not stats.get("ok"):
                    db_lines.append(f"{backend}: unavailable ({stats.get('error') or 'probe failed'})")
                    continue
                db_lines.append(f"{backend}: {stats.get('db_size', '—')} total size")
                week_total = sum(w.get("total", 0) for w in stats.get("weekly_growth", []))
                if week_total:
                    db_lines.append(
                        f"  Rows logged (last 4 weeks): {self._fmt_num(week_total)}"
                    )
                for table, info in (stats.get("tables") or {}).items():
                    if not info.get("exists"):
                        continue
                    rows_n = int(info.get("row_count") or 0)
                    line = f"  {table}: {self._fmt_num(rows_n)} rows"
                    db_lines.append(line)
                    export_rows += rows_n
                    box = table_map.get(table)
                    if box:
                        extra[box].append(f"{backend} {table}: {self._fmt_num(rows_n)} rows")
                for snap_table in ("solar_forecast_snapshots", "agile_price_snapshots"):
                    info = (stats.get("tables") or {}).get(snap_table)
                    if info and info.get("exists"):
                        rows_n = int(info.get("row_count") or 0)
                        db_lines.append(f"  {snap_table}: {self._fmt_num(rows_n)} rows")
                        extra["forecast"].append(
                            f"{backend} {snap_table}: {self._fmt_num(rows_n)} rows"
                        )
                        export_rows += rows_n
            vol["database"] = db_lines
            if export_rows:
                vol["export"].append(f"Stored rows (all backends): {self._fmt_num(export_rows)}")
            for box, lines in extra.items():
                if lines:
                    vol[box] = list(dict.fromkeys((vol.get(box) or []) + lines))

            def done():
                try:
                    self._flow_diagram.set_volumes(vol)
                except Exception:
                    pass

            self._inv.invoke(done)

        threading.Thread(target=work, daemon=True).start()

    def refresh_status(self, test_db=False):
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
        self._size_cache = (
            self._build_table_size_cache(db_enabled) if db_enabled else {}
        )

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

        if not db_enabled:
            rows.append((
                "Databases", "Disabled", "off",
                "No database backends enabled", "--", "--",
            ))
        else:
            if test_db or self._db_results is None:
                self._db_results = dl.test_connections()
                self._db_test_time = datetime.now().strftime('%H:%M:%S')
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
            rows.append((
                "Databases", state_text, state_key, detail, self._db_test_time,
                self._size_for("Databases"),
            ))

        self.table.setRowCount(len(rows))
        for idx, row in enumerate(rows):
            self._set_row(idx, *row)
        try:
            volumes, db_enabled = self._collect_box_volumes(d)
            if md_mode == "off":
                lan_direct = "off"
            elif self._growatt_modbus_probe_running:
                lan_direct = "idle"
            else:
                lan_direct = self._growatt_modbus_cache.get("state_key", "off")
            if not http_host:
                wifi_direct = "off"
            elif self._growatt_http_probe_running:
                wifi_direct = "idle"
            else:
                wifi_direct = self._growatt_http_cache.get("state_key", "off")
            self._flow_diagram.set_health_from_rows(
                rows,
                direct={"lan_direct": lan_direct, "wifi_direct": wifi_direct},
            )
            self._flow_diagram.set_growatt_telemetry(tel)
            self._flow_diagram.set_volumes(volumes)
            if db_enabled:
                self._refresh_db_volumes_async(db_enabled, volumes)
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
        _wr_ok = gt.connect_btn.isEnabled() and gt.api and gt.device_sn
        _wr_line = (
            "Inverter write (schedules): yes — via Growatt cloud REST"
            if _wr_ok else
            "Inverter write (schedules): no until Growatt Live tab is connected"
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

        if not self._suppress_modbus_probe and not self._growatt_modbus_probe_running:
            if (getattr(d.app_params, "growatt_modbus_mode", "off") or "off").lower() != "off":
                self._start_growatt_modbus_probe(d.app_params)
        if not self._suppress_http_probe and not self._growatt_http_probe_running:
            if growatt_http_host(d.app_params):
                self._start_growatt_http_probe(d.app_params)


__all__ = [n for n in globals() if not n.startswith('__')]
