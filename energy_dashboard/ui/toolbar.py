"""
Energy Dashboard — `ui/toolbar.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.ui.buttons import _TASMOTA_PIN_CHART_CB_QSS
from energy_dashboard.ui.styles import _checkbox_indicator_qss


def _apply_pin_chart_checkbox_halo(checkbox):
    """Pill chrome on the chart toolbar; indicator matches app-wide checkbox style."""
    checkbox.setObjectName('tasmotaPinHist500')
    checkbox.setStyleSheet(
        _TASMOTA_PIN_CHART_CB_QSS
        + _checkbox_indicator_qss("QCheckBox#tasmotaPinHist500")
    )
    halo = QGraphicsDropShadowEffect(checkbox)
    halo.setBlurRadius(16)
    halo.setColor(QColor(255, 255, 255, 160))
    halo.setOffset(0, 0)
    checkbox.setGraphicsEffect(halo)


class DarkNavigationToolbar(_MplNavigationToolbar):
    """Matplotlib NavigationToolbar with white tool icons on the dark dashboard."""

    def _icon(self, name):
        from matplotlib import cbook

        path_regular = cbook._get_data_path('images', name)
        path_large = path_regular.with_name(
            path_regular.name.replace('.png', '_large.png'))
        filename = str(path_large if path_large.exists() else path_regular)
        pm = QPixmap(filename)
        pm.setDevicePixelRatio(self.devicePixelRatioF() or 1)
        icon_color = QColor('#ffffff')
        mask = pm.createMaskFromColor(
            QColor('black'),
            Qt.MaskMode.MaskOutColor,
        )
        pm.fill(icon_color)
        pm.setMask(mask)
        return QIcon(pm)

    def __init__(self, canvas, parent=None, coordinates=True):
        super().__init__(canvas, parent, coordinates)
        self.setStyleSheet(
            "QToolBar { background: transparent; border: none; spacing: 3px; }"
            "QToolBar QLabel { color: #ffffff; background: transparent; }"
        )
        if self.coordinates and getattr(self, 'locLabel', None) is not None:
            self.locLabel.setStyleSheet(
                'color: #ffffff; background: transparent; padding: 0 4px;'
            )


class ChartShimmerOverlay(QWidget):
    """Translucent animated sweep over a FigureCanvas while data is loading."""

    def __init__(self, canvas: "FigureCanvas"):
        super().__init__(canvas)
        self._canvas = canvas
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self._timer = QTimer(self)
        self._timer.setInterval(36)
        self._timer.timeout.connect(self._on_tick)
        self._phase = 0.0
        self._active = False
        canvas.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self._canvas and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._canvas.rect())
        return False

    def start(self):
        self._active = True
        self._phase = 0.0
        self.setGeometry(self._canvas.rect())
        self.raise_()
        self.show()
        self._timer.start()

    def stop(self):
        self._active = False
        self._timer.stop()
        self.hide()

    def _on_tick(self):
        self._phase = (self._phase + 0.022) % 1.0
        self.update()

    def paintEvent(self, event):
        if not self._active:
            return
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        sweep = max(w * 0.36, 72.0)
        # Sweep travels across full width plus band width so the highlight enters/exits smoothly.
        cx = -sweep + self._phase * (w + 2 * sweep)
        grad = QLinearGradient(cx, 0, cx + sweep, 0)
        grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        grad.setColorAt(0.45, QColor(198, 208, 245, 52))
        grad.setColorAt(0.5, QColor(240, 242, 255, 105))
        grad.setColorAt(0.55, QColor(198, 208, 245, 52))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(0, 0, w, h, grad)


__all__ = [n for n in globals() if not n.startswith('__')]
