"""Keep top-level windows inside the usable screen, above panels.

On X11, Qt's available geometry already stops at the taskbar. On KDE Wayland
it often does not: a floating panel reserves no strut, so available geometry
equals the full monitor and a maximised window slides underneath the bar.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

# Plasma's own fallback floating margin is 8px (Panel.qml). This theme's
# floating hint is 9px. A little more keeps the frame clear of the bar,
# including while the panel is still floating and sitting off the screen edge.
_FLOATING_EDGE_PAD = 12
_BORDER_CUSHION_PX = 6

_CACHE_TTL_S = 5.0
_panel_cache: tuple[float, tuple] | None = None
_panel_logged = False

_PANEL_SCRIPT = r"""
var lines = [];
var ps = panels();
for (var i = 0; i < ps.length; i++) {
  var p = ps[i];
  if (p.hiding === "autohide")
    continue;
  var g = screenGeometry(p.screen);
  var vertical = (p.location === "left" || p.location === "right");
  var thick = vertical ? p.width : p.height;
  if (!thick || thick < 1)
    continue;
  var floating = p.floating ? 1 : 0;
  lines.push("PANEL " + g.x + " " + g.y + " " + g.width + " " + g.height
    + " " + p.location + " " + thick + " " + floating);
}
print(lines.join("\n"));
"""


def parse_panel_lines(text: str) -> tuple[dict, ...]:
    """Parse plasmashell script output into panel records."""
    found = []
    for raw in (text or "").splitlines():
        parts = raw.split()
        if len(parts) != 8 or parts[0] != "PANEL":
            continue
        try:
            found.append({
                "x": int(parts[1]),
                "y": int(parts[2]),
                "w": int(parts[3]),
                "h": int(parts[4]),
                "edge": parts[5],
                "thick": int(parts[6]),
                "floating": parts[7] == "1",
            })
        except ValueError:
            continue
    return tuple(found)


def insets_for_screen(panels, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
    """Left, top, right, bottom pixels a window must stay clear of on this screen."""
    left = top = right = bottom = 0
    for panel in panels:
        if (
            abs(panel["x"] - x) > 2
            or abs(panel["y"] - y) > 2
            or abs(panel["w"] - w) > 2
            or abs(panel["h"] - h) > 2
        ):
            continue
        reserve = int(panel["thick"])
        if reserve < 1:
            continue
        if panel.get("floating"):
            reserve += _FLOATING_EDGE_PAD
        edge = panel.get("edge")
        if edge == "left":
            left = max(left, reserve)
        elif edge == "top":
            top = max(top, reserve)
        elif edge == "right":
            right = max(right, reserve)
        elif edge == "bottom":
            bottom = max(bottom, reserve)
    return left, top, right, bottom


def _query_plasma_panels() -> tuple[dict, ...]:
    global _panel_cache
    now = time.monotonic()
    if _panel_cache is not None and now - _panel_cache[0] < _CACHE_TTL_S:
        return _panel_cache[1]
    text = ""
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

        bus = QDBusConnection.sessionBus()
        iface = QDBusInterface(
            "org.kde.plasmashell",
            "/PlasmaShell",
            "org.kde.PlasmaShell",
            bus,
        )
        iface.setTimeout(700)
        if iface.isValid():
            reply = iface.call("evaluateScript", _PANEL_SCRIPT)
            if reply.type() != QDBusMessage.MessageType.ErrorMessage:
                args = reply.arguments()
                if args:
                    text = str(args[0])
    except Exception:
        text = ""
    panels = parse_panel_lines(text)
    _panel_cache = (now, panels)
    return panels


def usable_screen_geometry(screen) -> QRect:
    """Rectangle the window frame must stay inside (excludes the taskbar)."""
    if screen is None:
        return QRect()
    geo = screen.geometry()
    avail = screen.availableGeometry()
    insets = insets_for_screen(
        _query_plasma_panels(), geo.x(), geo.y(), geo.width(), geo.height(),
    )
    shrunk = QRect(
        geo.x() + insets[0],
        geo.y() + insets[1],
        max(1, geo.width() - insets[0] - insets[2]),
        max(1, geo.height() - insets[1] - insets[3]),
    )
    both = avail.intersected(shrunk)
    if both.isValid() and both.width() >= 320 and both.height() >= 240:
        return both
    if shrunk.isValid():
        return shrunk
    return avail


def _measured_frame_extras(window: QWidget) -> tuple[int, int, int, int]:
    handle = window.windowHandle()
    if handle is not None:
        margins = handle.frameMargins()
        extras = (
            int(margins.left()),
            int(margins.top()),
            int(margins.right()),
            int(margins.bottom()),
        )
        if any(extras):
            return extras
    frame = window.frameGeometry()
    geo = window.geometry()
    return (
        max(0, geo.left() - frame.left()),
        max(0, geo.top() - frame.top()),
        max(0, frame.right() - geo.right()),
        max(0, frame.bottom() - geo.bottom()),
    )


def client_cap(window: QWidget) -> tuple[int, int]:
    """Largest client width and height that stay on this monitor.

    The frame must not extend past ``window.screen()``. A layout minimum
    that is wider than that monitor does not raise this cap.
    """
    cap_w, cap_h, _area, _left, _top = _client_cap(window)
    return cap_w, cap_h


def _client_cap(window: QWidget) -> tuple[int, int, QRect, int, int]:
    screen = window.screen() or QApplication.primaryScreen() or QGuiApplication.primaryScreen()
    area = usable_screen_geometry(screen)
    if screen is not None:
        monitor = screen.geometry()
        bounded = area.intersected(monitor)
        if not bounded.isValid() or bounded.width() < 320 or bounded.height() < 240:
            bounded = monitor
        # Hard ceiling: one monitor, never the joined desktop.
        area = QRect(
            bounded.x(),
            bounded.y(),
            min(bounded.width(), monitor.width()),
            min(bounded.height(), monitor.height()),
        )
    if area.isNull():
        return 1, 1, area, 0, 0
    measured = _measured_frame_extras(window)
    if any(measured):
        left, top, right, bottom = measured
    else:
        # A couple of pixels for a border we have not measured yet.
        # Do not guess a title bar — that left a gap under the window.
        left, top, right, bottom = (_BORDER_CUSHION_PX, 0, _BORDER_CUSHION_PX, 0)
    # Width stays inside this monitor. Height is the usable screen
    # above the taskbar, so the panel buttons stay visible.
    cap_w = max(1, area.width() - left - right)
    cap_h = max(1, area.height() - top - bottom)
    return cap_w, cap_h, area, left, top


def _pull_minimum_inside_cap(window: QWidget, cap_w: int, cap_h: int) -> None:
    """Stop the layout minimum from inflating the window past the monitor."""
    min_w = int(window.minimumWidth())
    min_h = int(window.minimumHeight())
    if min_w > cap_w or min_h > cap_h:
        window.setMinimumSize(min(max(min_w, 1), cap_w), min(max(min_h, 1), cap_h))


def fit_window_to_work_area(window: QWidget, *, fill: bool = False) -> QRect:
    """Keep *window* on its monitor, above the taskbar.

    *fill* snaps it to that monitor's usable resolution (startup and
    maximise). Otherwise the window is only moved or shrunk when its frame
    currently crosses the screen edge or a panel.
    """
    from PySide6.QtCore import Qt

    state = window.windowState()
    if state & Qt.WindowState.WindowMinimized:
        screen = window.screen() or QApplication.primaryScreen()
        return usable_screen_geometry(screen)

    cap_w, cap_h, area, left, top = _client_cap(window)
    if area.isNull():
        return area

    maximized = bool(state & Qt.WindowState.WindowMaximized)

    _pull_minimum_inside_cap(window, cap_w, cap_h)
    if window.maximumWidth() != cap_w or window.maximumHeight() != cap_h:
        window.setMaximumSize(cap_w, cap_h)

    if fill or maximized:
        # The compositor's maximise uses the full monitor and covers a
        # floating taskbar. Drop that state so this size sticks, then
        # place the window in the usable rectangle above the panel.
        if maximized:
            window.setWindowState(state & ~Qt.WindowState.WindowMaximized)
        window.setGeometry(QRect(area.x() + left, area.y() + top, cap_w, cap_h))
        _note_insets(window.screen(), area)
        return area

    frame = window.frameGeometry()
    if area.contains(frame) and frame.width() <= area.width() and frame.height() <= area.height():
        return area

    fw = min(frame.width(), area.width())
    fh = min(frame.height(), area.height())
    fx = min(max(frame.x(), area.x()), area.x() + area.width() - fw)
    fy = min(max(frame.y(), area.y()), area.y() + area.height() - fh)
    right = area.width() - cap_w - left
    bottom = area.height() - cap_h - top
    window.setGeometry(QRect(
        fx + left,
        fy + top,
        max(1, min(fw - left - right, cap_w)),
        max(1, min(fh - top - bottom, cap_h)),
    ))
    _note_insets(window.screen(), area)
    return area


def _note_insets(screen, area: QRect) -> None:
    global _panel_logged
    if _panel_logged or screen is None:
        return
    geo = screen.geometry()
    if area.width() >= geo.width() and area.height() >= geo.height() and area.topLeft() == geo.topLeft():
        return
    _panel_logged = True
    try:
        from energy_dashboard.core.logging import get_log_manager
        get_log_manager().info(
            "App",
            "Main window stays above the taskbar "
            f"({area.width()}×{area.height()} usable on {geo.width()}×{geo.height()}).",
        )
    except Exception:
        pass
