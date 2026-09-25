"""
Energy Dashboard — `ui/tab_bar.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *

def _tab_bar_label_display(text):
    """Text for FreshnessTabBar paint — Qt ``&&`` in tab titles is not unescaped here."""
    return (text or "").replace("&&", "&")


class MainTabGroupStrip(QWidget):
    """Amber group selectors for the left of the main tab bar (same row, no extra height).

    Installed via ``QTabWidget.setCornerWidget(..., Qt.TopLeftCorner)``.
    """

    groupSelected = Signal(str)

    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self.setObjectName("mainTabGroupStrip")
        self.setStyleSheet(_MAIN_TAB_GROUP_STRIP_QSS)
        self._buttons = {}
        self._group_ids = [gid for gid, _ in groups]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        for gid, label in groups:
            btn = QPushButton(label)
            btn.setObjectName("mainTabGroupBtn")
            btn.setProperty(PRIMARY_BUTTON_EXEMPT, True)
            btn.setCheckable(True)
            btn.setAutoFillBackground(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            btn.setProperty("group_id", gid)
            btn.setStyleSheet(_MAIN_TAB_GROUP_BTN_QSS)
            self._btn_group.addButton(btn)
            self._buttons[gid] = btn
            lay.addWidget(btn)
            btn.clicked.connect(self._on_button_clicked)
        # Substantial separator between groups and page tabs (20px pad each side).
        lay.addSpacing(20)
        sep = QFrame()
        sep.setObjectName("mainTabGroupSep")
        sep.setFixedWidth(3)
        sep.setMinimumHeight(22)
        sep.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        sep.setStyleSheet(
            f"QFrame#mainTabGroupSep {{"
            f"  background: {_TAB_GROUP_AMBER};"
            f"  border: none;"
            f"  border-radius: 1px;"
            f"}}"
        )
        lay.addWidget(sep)
        lay.addSpacing(20)

    def _on_button_clicked(self):
        btn = self.sender()
        if btn is None:
            return
        gid = btn.property("group_id")
        if gid:
            self.groupSelected.emit(str(gid))

    def set_active_group(self, group_id):
        btn = self._buttons.get(group_id)
        if btn is None and self._group_ids:
            btn = self._buttons.get(self._group_ids[0])
            group_id = self._group_ids[0]
        if btn is not None:
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)
        return group_id

    def active_group(self):
        for gid, btn in self._buttons.items():
            if btn.isChecked():
                return gid
        return self._group_ids[0] if self._group_ids else None


class FreshnessTabBar(QTabBar):
    """Main page tab bar: solid green (updateable) / blue (static); selected has diagonal hatch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('freshMainTabBar')
        self.setStyleSheet(_FRESH_MAIN_TAB_BAR_QSS)
        self._fresh_bg = {}
        self._updateable = {}  # tab_index → bool
        self._label_font = QFont(self.font())
        self._label_font_bold = QFont(self.font())
        self._label_font_bold.setBold(True)

    @staticmethod
    def _tab_body_rect(rect):
        """Tab paint rect with rounded top corners and flat bottom (meets pane)."""
        return QRectF(rect).adjusted(1.0, 2.0, -1.0, -1.0)

    @classmethod
    def _tab_shape_path(cls, rect):
        """Rounded top corners only — standard tab silhouette."""
        return cls._shape_for_rect(cls._tab_body_rect(rect))

    @staticmethod
    def _shape_for_rect(r):
        """Rounded top corners on an explicit body rect."""
        rad = float(_TAB_CORNER_RADIUS)
        path = QPainterPath()
        path.moveTo(r.left(), r.bottom())
        path.lineTo(r.left(), r.top() + rad)
        path.arcTo(r.left(), r.top(), 2 * rad, 2 * rad, 180.0, -90.0)
        path.lineTo(r.right() - rad, r.top())
        path.arcTo(r.right() - 2 * rad, r.top(), 2 * rad, 2 * rad, 90.0, -90.0)
        path.lineTo(r.right(), r.bottom())
        path.closeSubpath()
        return path

    def set_freshness_backgrounds(self, mapping):
        """mapping: tab_index → '#rrggbb' or QColor (solid page colour)."""
        self._fresh_bg = {
            int(idx): QColor(c) if isinstance(c, str) else c
            for idx, c in mapping.items()
        }
        self.update()

    def set_updateable_flags(self, mapping):
        """mapping: tab_index → True (green / live) or False (blue / static)."""
        self._updateable = {int(idx): bool(v) for idx, v in mapping.items()}
        self.update()

    def _bg_for(self, tab_index):
        if tab_index in self._fresh_bg:
            return self._fresh_bg[tab_index]
        if self._updateable.get(tab_index, True):
            return QColor(_TAB_PAGE_UPDATEABLE)
        return QColor(_TAB_PAGE_STATIC)

    def _paint_selected_hatch(self, painter, shape, rect):
        """Diagonal stroke highlight clipped to the selected tab silhouette."""
        painter.save()
        painter.setClipPath(shape)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = QPen(_TAB_PAGE_HATCH)
        pen.setWidth(2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        body = self._tab_body_rect(rect)
        # Spacing between diagonal strokes
        step = 7.0
        x0 = body.left() - body.height()
        x1 = body.right() + body.height()
        y0 = body.top()
        y1 = body.bottom()
        x = x0
        while x < x1:
            painter.drawLine(QPointF(x, y1), QPointF(x + (y1 - y0), y0))
            x += step
        painter.restore()

    def paintEvent(self, event):
        """Paint solid green/blue page tabs; selected tab gets diagonal hatch."""
        painter = QPainter(self)
        if not painter.isActive():
            return
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setClipRegion(event.region())
            option = QStyleOptionTab()
            for i in range(self.count()):
                rect = self.tabRect(i)
                if not rect.isValid() or not rect.intersects(event.rect()):
                    continue
                self.initStyleOption(option, i)
                selected = bool(option.state & QStyle.StateFlag.State_Selected)
                shape = self._tab_shape_path(rect)
                bg = self._bg_for(i)
                stale = (
                    not selected
                    and bg.name(QColor.NameFormat.HexRgb).lower()
                    == _TAB_PAGE_NOT_UPDATED.lower()
                )
                if stale:
                    bg = QColor(_TAB_PAGE_NOT_UPDATED_IDLE)
                painter.fillPath(shape, bg)
                if selected:
                    self._paint_selected_hatch(painter, shape, rect)
                painter.setBrush(Qt.NoBrush)
                if stale:
                    # The outline is inset so it cannot form a halo outside
                    # the silhouette shared with the green and blue tabs.
                    inner = self._tab_body_rect(rect).adjusted(1.25, 1.25, -1.25, 0.0)
                    painter.setPen(QPen(_TAB_OUTLINE_STALE, 1.0))
                    painter.drawPath(self._shape_for_rect(inner))
                else:
                    outline, width = (
                        (_TAB_OUTLINE_SELECTED, 1.5)
                        if selected
                        else (_TAB_OUTLINE_FAINT, 1.0)
                    )
                    painter.setPen(QPen(outline, width))
                    painter.drawPath(shape)
                if selected:
                    body = self._tab_body_rect(rect)
                    painter.setPen(QColor(_DARK_BG))
                    painter.drawLine(
                        int(body.left()), int(body.bottom()),
                        int(body.right()), int(body.bottom()),
                    )
                bg_hex = bg.name(QColor.NameFormat.HexRgb)
                fg = QColor(_contrasting_tab_text(bg_hex))
                option.font = (
                    self._label_font_bold if selected else self._label_font
                )
                painter.setPen(fg)
                painter.setFont(option.font)
                text_rect = self.style().subElementRect(
                    QStyle.SubElement.SE_TabBarTabText, option, self,
                )
                if not text_rect.isValid():
                    text_rect = rect.adjusted(4, 0, -4, 0)
                painter.drawText(
                    text_rect,
                    int(Qt.AlignmentFlag.AlignCenter),
                    _tab_bar_label_display(self.tabText(i)),
                )
        finally:
            painter.end()


class BannerRefreshCyclePill(QFrame):
    """Clickable two-line auto-refresh status pill (banner right cluster)."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("bannerRefreshCyclePill")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(42)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet(_BANNER_REFRESH_CYCLE_QSS)
        self.setToolTip(
            "Click to cycle the shared auto-refresh interval:\n"
            "Auto 10s → 30s → 60s → 180s → 300s → 600s → Manual only.\n\n"
            "Line 1: mode · clock · age of the oldest live source.\n"
            "Line 2: time to next tick · live sources within their own "
            "cadence (Growatt / Octopus Live / Tasmota)."
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(0)
        self.line1 = QLabel("Mode --")
        self.line2 = QLabel("Next --")
        for lab in (self.line1, self.line2):
            lab.setObjectName("bannerRefreshCycleLine")
            lab.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lab.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lay.addWidget(lab)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        # Keep pressed look brief via stylesheet hover only.
        if event.button() == Qt.LeftButton:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def set_lines(self, line1, line2):
        a = line1 or ""
        b = line2 or ""
        # Avoid redundant QLabel updates (1 Hz banner ticks) that force layout.
        if self.line1.text() != a:
            self.line1.setText(a)
        if self.line2.text() != b:
            self.line2.setText(b)

    def set_detail_tooltip(self, text):
        t = text or ""
        if t and self.toolTip() != t:
            self.setToolTip(t)


class BannerTabScrollHold(QWidget):
    """Narrow control beside the auto-refresh banner: wheel = prev/next main tab;
    press-and-hold = advance tabs. Tab bodies already live in the QTabWidget."""

    _HOLD_MS = 420
    _REPEAT_MS = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("banner_tab_scroll_hold")
        self._tabs = None
        self._dash = None
        self._hold_armed = False
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._on_hold_deadline)
        self._repeat_timer = QTimer(self)
        self._repeat_timer.timeout.connect(self._tick_hold_repeat)
        self.setFixedWidth(38)
        self.setFixedHeight(42)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.WheelFocus)
        self.setToolTip(
            "<b>Mouse wheel</b> up/down: previous / next main tab (pages are already loaded). "
            "<b>Press and hold</b>: after a short pause, advance tab-by-tab until you release."
        )
        self.setToolTipDuration(10000)
        self.setStyleSheet(
            "#banner_tab_scroll_hold {"
            "  background: transparent;"
            "  border: 1px solid #45475a;"
            "  border-radius: 6px;"
            "}"
        )

    def bind_tabs(self, tabs_widget, dashboard):
        self._tabs = tabs_widget
        self._dash = dashboard

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor("#89b4fa"))
        f = QFont(self.font())
        f.setPointSize(16)
        f.setBold(True)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, "›")
        p.end()

    def wheelEvent(self, event):
        if not self._tabs or self._tabs.count() < 2:
            event.ignore()
            return
        dy = event.angleDelta().y()
        if dy < 0:
            self._apply_tab_delta(+1)
            event.accept()
        elif dy > 0:
            self._apply_tab_delta(-1)
            event.accept()
        else:
            event.ignore()

    def _apply_tab_delta(self, delta):
        if self._dash is None:
            return
        self._dash._banner_tab_step(delta)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._tabs is not None and self._tabs.count() > 1:
            self._hold_armed = True
            self._hold_timer.start(self._HOLD_MS)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._clear_hold()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        self._clear_hold()
        super().leaveEvent(event)

    def _clear_hold(self):
        self._hold_armed = False
        self._hold_timer.stop()
        self._repeat_timer.stop()

    def _on_hold_deadline(self):
        if not self._hold_armed or not self._tabs or self._tabs.count() < 2:
            return
        self._tick_hold_repeat()
        self._repeat_timer.start(self._REPEAT_MS)

    def _tick_hold_repeat(self):
        if not self._hold_armed or not self._tabs or self._tabs.count() < 2:
            self._repeat_timer.stop()
            return
        self._apply_tab_delta(+1)


__all__ = [n for n in globals() if not n.startswith('__')]
