"""
Energy Dashboard — `ui/tab_bar.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.common import *

def _tab_bar_label_display(text):
    """Text for FreshnessTabBar paint — Qt ``&&`` in tab titles is not unescaped here."""
    return (text or "").replace("&&", "&")


class FreshnessTabBar(QTabBar):
    """Main tab bar: per-tab background tint (fresh data fades green → app background)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('freshMainTabBar')
        self.setStyleSheet(_FRESH_MAIN_TAB_BAR_QSS)
        self._fresh_bg = {}
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
        r = cls._tab_body_rect(rect)
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
        """mapping: tab_index → '#rrggbb' or QColor."""
        self._fresh_bg = {
            int(idx): QColor(c) if isinstance(c, str) else c
            for idx, c in mapping.items()
        }
        self.update()

    def _bg_for(self, tab_index):
        return self._fresh_bg.get(tab_index, QColor(_DARK_BG))

    def paintEvent(self, event):
        """Paint each tab's freshness tint (QSS ::tab background overrides palette)."""
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
                painter.fillPath(shape, self._bg_for(i))
                painter.setBrush(Qt.NoBrush)
                painter.setPen(
                    QPen(
                        _TAB_OUTLINE_SELECTED if selected else _TAB_OUTLINE_FAINT,
                        1.0,
                    ),
                )
                painter.drawPath(shape)
                if selected:
                    body = self._tab_body_rect(rect)
                    painter.setPen(QColor(_DARK_BG))
                    painter.drawLine(
                        int(body.left()), int(body.bottom()),
                        int(body.right()), int(body.bottom()),
                    )
                bg_hex = self._bg_for(i).name(QColor.NameFormat.HexRgb)
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
