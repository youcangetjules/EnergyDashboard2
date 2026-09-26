"""PowerMon tray mark: a sun and a battery, readable at tray size.

The old icon was the standard warning triangle, which belonged to the
alarm-only tray. The window now lives in the tray, so the mark should
say solar and storage.
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.ui.palette import (
    _DARK_BG,
    _DARK_SURFACE0,
    _DARK_SURFACE_BG,
    _DARK_TEXT,
    _TAB_GROUP_AMBER,
)

_BATTERY = "#a6e3a1"
_RING = "#cdd6f4"


def powermon_tray_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 22, 24, 32, 48, 64):
        icon.addPixmap(_pixmap(size))
    return icon


def style_tray_info(menu, _labels=None) -> None:
    """Paint the tray menu like the rest of the app.

    Every row, including the database lines, is a plain menu entry. A widget
    embedded in this menu rendered as a blank strip on KDE (BUG-074), so the
    figures are ordinary items and take this item colour.
    """
    menu.setStyleSheet(
        f"""
        QMenu {{
            background-color: {_DARK_SURFACE_BG};
            color: #ffffff;
            border: 1px solid #45475a;
            padding: 4px 0px;
        }}
        QMenu::item {{
            color: #ffffff;
            background-color: transparent;
            padding: 6px 28px 6px 16px;
        }}
        QMenu::item:selected {{
            background-color: {_DARK_SURFACE0};
            color: #ffffff;
        }}
        QMenu::item:disabled {{
            color: {_DARK_TEXT};
        }}
        QMenu::separator {{
            height: 1px;
            background: #45475a;
            margin: 4px 10px;
        }}
        """
    )


def _pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    span = float(size)
    inset = max(0.5, span * 0.04)
    ring = max(1.0, span * 0.055)
    badge = QRectF(inset, inset, span - 2 * inset, span - 2 * inset)
    badge.adjust(ring / 2, ring / 2, -ring / 2, -ring / 2)
    painter.setPen(QPen(QColor(_RING), ring))
    painter.setBrush(QColor(_DARK_BG))
    painter.drawEllipse(badge)

    cx = span * 0.50
    cy = span * 0.40
    radius = span * 0.15
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(_TAB_GROUP_AMBER))
    painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
    ray = QPen(
        QColor(_TAB_GROUP_AMBER),
        max(1.0, span * 0.065),
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
    )
    painter.setPen(ray)
    gap = radius + span * 0.045
    length = span * 0.07
    for dx, dy in ((0, -1), (-1, 0), (1, 0)):
        painter.drawLine(
            QPointF(cx + dx * gap, cy + dy * gap),
            QPointF(cx + dx * (gap + length), cy + dy * (gap + length)),
        )

    body_w = span * 0.40
    body_h = span * 0.15
    body_x = (span - body_w) / 2
    body_y = span * 0.69
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(_BATTERY))
    painter.drawRoundedRect(
        QRectF(body_x, body_y, body_w, body_h), span * 0.03, span * 0.03,
    )
    nub_h = body_h * 0.46
    painter.drawRoundedRect(
        QRectF(
            body_x + body_w - span * 0.01,
            body_y + (body_h - nub_h) / 2,
            span * 0.055,
            nub_h,
        ),
        1,
        1,
    )
    painter.end()
    return pm
