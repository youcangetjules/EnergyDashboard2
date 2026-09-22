"""
Energy Dashboard — `ui/styles.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

import base64

from energy_dashboard.deps import *
from energy_dashboard.ui.palette import *
from energy_dashboard.ui.buttons import _APP_GLOBAL_WIDGET_QSS
from energy_dashboard.ui.theme_constants import _REFRESH_ALL_BTN_QSS

_CHEVRON_W = 10
_CHEVRON_H = 6


def _chevron_svg_uri(direction: str, color: str) -> str:
    """Inline SVG stroke chevron for Qt stylesheets (no external files)."""
    stroke = color if color.startswith("#") else f"#{color}"
    path = "M1 5 L5 1 L9 5" if direction == "up" else "M1 1 L5 5 L9 1"
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 6" '
        f'width="{_CHEVRON_W}" height="{_CHEVRON_H}">'
        f'<path fill="none" stroke="{stroke}" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round" d="{path}"/></svg>'
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"url(data:image/svg+xml;base64,{encoded})"


def _stepper_chevron_qss(
    color: str,
    disabled_color: str,
    widgets: tuple[str, ...] = ("QSpinBox", "QDoubleSpinBox", "QTimeEdit"),
) -> str:
    """Up/down chevrons for spin/time steppers."""
    up = _chevron_svg_uri("up", color)
    down = _chevron_svg_uri("down", color)
    up_off = _chevron_svg_uri("up", disabled_color)
    down_off = _chevron_svg_uri("down", disabled_color)
    w, h = _CHEVRON_W, _CHEVRON_H
    up_sel = ", ".join(f"{wt}::up-arrow" for wt in widgets)
    down_sel = ", ".join(f"{wt}::down-arrow" for wt in widgets)
    up_off_sel = ", ".join(f"{wt}::up-arrow:disabled, {wt}::up-arrow:off" for wt in widgets)
    down_off_sel = ", ".join(f"{wt}::down-arrow:disabled, {wt}::down-arrow:off" for wt in widgets)
    return (
        f"{up_sel} {{ image: {up}; width: {w}px; height: {h}px; border: none; }}"
        f"{down_sel} {{ image: {down}; width: {w}px; height: {h}px; border: none; }}"
        f"{up_off_sel} {{ image: {up_off}; width: {w}px; height: {h}px; border: none; }}"
        f"{down_off_sel} {{ image: {down_off}; width: {w}px; height: {h}px; border: none; }}"
    )


def _combo_chevron_qss(color: str, disabled_color: str) -> str:
    down = _chevron_svg_uri("down", color)
    down_off = _chevron_svg_uri("down", disabled_color)
    w, h = _CHEVRON_W, _CHEVRON_H
    return (
        f"QComboBox::down-arrow {{"
        f"  image: {down}; width: {w}px; height: {h}px; border: none;"
        f"}}"
        f"QComboBox::down-arrow:disabled {{"
        f"  image: {down_off}; width: {w}px; height: {h}px; border: none;"
        f"}}"
    )


def _spin_field_motif_field_qss(widget: str) -> str:
    """Canonical QSpinBox / QDoubleSpinBox chrome (Setup & Info Export p/kWh reference)."""
    return (
        f"{widget} {{"
        f"  background: {_FLAT_TARIFF_INPUT_BG};"
        f"  background-color: {_FLAT_TARIFF_INPUT_BG};"
        f"  color: {_DARK_TEXT};"
        f"  font-weight: {_FLAT_TARIFF_FONT_WEIGHT};"
        f"  border: 1px solid {_FLAT_TARIFF_INPUT_BORDER};"
        f"  border-radius: {_INPUT_FIELD_RADIUS}px;"
        f"  padding: {_INPUT_FIELD_PADDING};"
        f"  padding-right: {_INPUT_STEP_W + 2}px;"
        f"  min-height: {_SPIN_FIELD_MOTIF_H}px;"
        f"  max-height: {_SPIN_FIELD_MOTIF_H}px;"
        f"}}"
        f"{widget} QLineEdit {{"
        f"  background: {_FLAT_TARIFF_INPUT_BG};"
        f"  background-color: {_FLAT_TARIFF_INPUT_BG};"
        f"  color: {_DARK_TEXT};"
        f"  border: none;"
        f"  font-weight: {_FLAT_TARIFF_FONT_WEIGHT};"
        f"  padding: 0 2px 0 0;"
        f"}}"
        f"{widget}:focus {{ border: 1px solid {_FLAT_TARIFF_FOCUS_BORDER}; }}"
        f"{widget}:disabled {{ color: {_DARK_OVERLAY}; }}"
        f"{widget}::up-button, {widget}::down-button {{"
        f"  subcontrol-origin: padding;"
        f"  width: {_INPUT_STEP_W}px;"
        f"  border: none;"
        f"  background: transparent;"
        f"}}"
        f"{widget}::up-button {{ subcontrol-position: top right; border-top-right-radius: 2px; }}"
        f"{widget}::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 2px; }}"
        f"{widget}::up-button:hover, {widget}::down-button:hover {{"
        f"  background-color: {_FLAT_TARIFF_STEP_HOVER}; border-radius: 2px;"
        f"}}"
        f"{widget}::up-button:pressed, {widget}::down-button:pressed {{"
        f"  background-color: {_FLAT_TARIFF_STEP_PRESSED}; border-radius: 2px;"
        f"}}"
    )


def _spin_widget_stylesheet(widget: str) -> str:
    """Per-widget stylesheet (wins over app-wide rules on some Qt/Linux builds)."""
    return (
        _spin_field_motif_field_qss(widget)
        + _stepper_chevron_qss(_DARK_TEXT, _DARK_OVERLAY, (widget,))
    )


def _spin_field_motif_qss() -> str:
    """App-wide spin/stepper fields — electric-blue motif."""
    return (
        _spin_field_motif_field_qss("QSpinBox")
        + _spin_field_motif_field_qss("QDoubleSpinBox")
        + _stepper_chevron_qss(_DARK_TEXT, _DARK_OVERLAY, ("QSpinBox", "QDoubleSpinBox"))
    )


def apply_spin_field_motif(
    spin,
    *,
    width: int | None = None,
) -> None:
    """Apply motif footprint (90×20 by default) and inner-field palette to one spin box."""
    w = int(width if width is not None else _SPIN_FIELD_MOTIF_W)
    spin.setFixedSize(w, _SPIN_FIELD_MOTIF_H)
    spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    spin.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    spin.setFrame(False)
    spin.setAttribute(Qt.WA_StyledBackground, True)
    spin.setAutoFillBackground(True)
    cls = spin.metaObject().className()
    spin.setStyleSheet(_spin_widget_stylesheet(cls))
    pal = spin.palette()
    pal.setColor(QPalette.ColorRole.Base, QColor(_SPIN_FIELD_BG))
    pal.setColor(QPalette.ColorRole.Window, QColor(_SPIN_FIELD_BG))
    pal.setColor(QPalette.ColorRole.Text, QColor(_DARK_TEXT))
    spin.setPalette(pal)
    for line_edit in spin.findChildren(QLineEdit):
        line_edit.setAutoFillBackground(True)
        line_edit.setAttribute(Qt.WA_StyledBackground, True)
        le_pal = line_edit.palette()
        le_pal.setColor(QPalette.ColorRole.Base, QColor(_SPIN_FIELD_BG))
        le_pal.setColor(QPalette.ColorRole.Window, QColor(_SPIN_FIELD_BG))
        le_pal.setColor(QPalette.ColorRole.Text, QColor(_DARK_TEXT))
        line_edit.setPalette(le_pal)


def apply_setup_info_line_field_motif(
    edit: QLineEdit,
    *,
    width: int | None = None,
    expand: bool = False,
) -> None:
    """Setup & Info line edits — same electric-blue field as spin boxes."""
    w = int(width if width is not None else _SPIN_FIELD_MOTIF_W)
    edit.setObjectName("paramsDbField")
    edit.setFixedHeight(_SPIN_FIELD_MOTIF_H)
    edit.setAttribute(Qt.WA_StyledBackground, True)
    edit.setAutoFillBackground(True)
    edit.setStyleSheet(_setup_info_db_field_qss())
    pal = edit.palette()
    pal.setColor(QPalette.ColorRole.Base, QColor(_SPIN_FIELD_BG))
    pal.setColor(QPalette.ColorRole.Window, QColor(_SPIN_FIELD_BG))
    pal.setColor(QPalette.ColorRole.Text, QColor(_DARK_TEXT))
    edit.setPalette(pal)
    if expand:
        edit.setMinimumWidth(w)
        edit.setMaximumWidth(16777215)
        edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    else:
        edit.setFixedWidth(w)
        edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


def apply_spin_field_motif_tree(root) -> None:
    """Size every spin box under *root* and apply the spin-field motif."""
    for spin in root.findChildren(QSpinBox) + root.findChildren(QDoubleSpinBox):
        custom_w = spin.property("_pm_spin_motif_w")
        if custom_w is not None:
            try:
                apply_spin_field_motif(spin, width=int(custom_w))
                continue
            except (TypeError, ValueError):
                pass
        if spin.property("_params_db_field"):
            apply_spin_field_motif(spin, width=_SPIN_FIELD_MOTIF_DB_W)
        else:
            apply_spin_field_motif(spin)


def _input_widgets_qss():
    """Line edits and combos use neutral chrome; spins use the electric-blue motif."""
    return (
        f"QLineEdit, QComboBox, QTimeEdit {{"
        f"  background-color: {_DARK_INPUT_BG};"
        f"  color: {_DARK_TEXT};"
        f"  border: 1px solid {_DARK_INPUT_BORDER};"
        f"  border-radius: {_INPUT_FIELD_RADIUS}px;"
        f"  padding: {_INPUT_FIELD_PADDING};"
        f"  min-height: {_INPUT_FIELD_MIN_H}px;"
        f"  selection-background-color: #45475a;"
        f"  selection-color: {_DARK_TEXT};"
        f"}}"
        f"QComboBox QLineEdit {{"
        f"  background-color: {_DARK_INPUT_BG};"
        f"  color: {_DARK_TEXT};"
        f"  border: none;"
        f"  padding: 0 4px;"
        f"}}"
        f"QLineEdit:focus, QComboBox:focus, QTimeEdit:focus {{"
        f"  border: 1px solid #6c7086;"
        f"}}"
        f"QLineEdit:disabled, QComboBox:disabled, QTimeEdit:disabled {{"
        f"  background-color: {_DARK_INPUT_BG};"
        f"  color: {_DARK_OVERLAY};"
        f"}}"
        f"QComboBox {{ padding-right: {_COMBO_DROP_W + 4}px; }}"
        f"QComboBox::drop-down {{"
        f"  subcontrol-origin: padding;"
        f"  subcontrol-position: center right;"
        f"  width: {_COMBO_DROP_W}px;"
        f"  border: none;"
        f"  background: transparent;"
        f"}}"
        + _combo_chevron_qss(_DARK_TEXT, _DARK_OVERLAY)
        + f"QComboBox::drop-down:hover {{ background: transparent; }}"
        f"QTimeEdit {{ padding-right: {_INPUT_STEP_W + 4}px; }}"
        f"QTimeEdit::up-button, QTimeEdit::down-button {{"
        f"  subcontrol-origin: padding;"
        f"  width: {_INPUT_STEP_W}px;"
        f"  border: none;"
        f"  background: transparent;"
        f"}}"
        f"QTimeEdit::up-button {{ subcontrol-position: top right; border-top-right-radius: 2px; }}"
        f"QTimeEdit::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 2px; }}"
        f"QTimeEdit::up-button:hover, QTimeEdit::down-button:hover {{"
        f"  background-color: {_SPIN_STEP_BTN_HOVER}; border-radius: 2px;"
        f"}}"
        f"QTimeEdit::up-button:pressed, QTimeEdit::down-button:pressed {{"
        f"  background-color: {_SPIN_STEP_BTN_PRESSED}; border-radius: 2px;"
        f"}}"
        + _stepper_chevron_qss(_DARK_TEXT, _DARK_OVERLAY, ("QTimeEdit",))
        + _spin_field_motif_qss()
        + f"QComboBox QAbstractItemView {{"
        f"  background-color: {_DARK_INPUT_BG};"
        f"  color: {_DARK_TEXT};"
        f"  border: 1px solid {_DARK_INPUT_BORDER};"
        f"  selection-background-color: #45475a;"
        f"}}"
    )


def _setup_info_spin_qss() -> str:
    """Alias — Setup & Info spins use the global spin-field motif."""
    return _spin_field_motif_qss()


def _setup_info_db_field_qss() -> str:
    """Database Export line edits — same electric-blue field as Setup & Info spins."""
    w = "QLineEdit#paramsDbField"
    return (
        f"{w} {{"
        f"  background-color: {_FLAT_TARIFF_INPUT_BG};"
        f"  color: {_DARK_TEXT};"
        f"  font-weight: {_FLAT_TARIFF_FONT_WEIGHT};"
        f"  border: 1px solid {_FLAT_TARIFF_INPUT_BORDER};"
        f"  border-radius: {_INPUT_FIELD_RADIUS}px;"
        f"  padding: {_INPUT_FIELD_PADDING};"
        f"}}"
        f"{w}:focus {{ border: 1px solid {_FLAT_TARIFF_FOCUS_BORDER}; }}"
        f"{w}:disabled {{ color: {_DARK_OVERLAY}; }}"
    )


def _flat_tariff_spin_qss():
    """Alias — flat tariff fields use the spin-field motif."""
    return _spin_field_motif_qss()


def _checkbox_indicator_qss(selector: str = "QCheckBox") -> str:
    """Square indicator — white halo, solid green when checked (no tick mark)."""
    return (
        f"{selector}::indicator {{"
        f"  width: 15px;"
        f"  height: 15px;"
        f"  border-radius: 3px;"
        f"  background: #313244;"
        f"  border: 1px solid #ffffff;"
        f"  image: none;"
        f"}}"
        f"{selector}::indicator:unchecked:hover {{"
        f"  background: #3b3d52;"
        f"  border: 1px solid #ffffff;"
        f"}}"
        f"{selector}::indicator:checked {{"
        f"  background: #a6e3a1;"
        f"  border: 1px solid #ffffff;"
        f"  image: none;"
        f"}}"
        f"{selector}::indicator:checked:hover {{"
        f"  background: #b8f0b3;"
        f"  border: 1px solid #ffffff;"
        f"}}"
        f"{selector}::indicator:disabled {{"
        f"  background: #313244;"
        f"  border: 1px solid #6c7086;"
        f"}}"
        f"{selector}::indicator:checked:disabled {{"
        f"  background: #585b70;"
        f"  border: 1px solid #6c7086;"
        f"}}"
    )


def _checkbox_qss() -> str:
    """App-wide QCheckBox chrome (all tabs inherit via application stylesheet)."""
    return (
        f"QCheckBox {{"
        f"  background-color: transparent;"
        f"  color: {_DARK_TEXT};"
        f"  spacing: 8px;"
        f"}}"
        f"QCheckBox:disabled {{ color: {_DARK_OVERLAY}; }}"
        + _checkbox_indicator_qss("QCheckBox")
    )


def _radio_indicator_qss(selector: str = "QRadioButton") -> str:
    """Round indicator — white 1px halo; filled when selected."""
    return (
        f"{selector}::indicator {{"
        f"  width: 15px;"
        f"  height: 15px;"
        f"  border-radius: 8px;"
        f"  background: #313244;"
        f"  border: 1px solid #ffffff;"
        f"  image: none;"
        f"}}"
        f"{selector}::indicator:unchecked:hover {{"
        f"  background: #3b3d52;"
        f"  border: 1px solid #ffffff;"
        f"}}"
        f"{selector}::indicator:checked {{"
        f"  background: #cdd6f4;"
        f"  border: 1px solid #ffffff;"
        f"  image: none;"
        f"}}"
        f"{selector}::indicator:checked:hover {{"
        f"  background: #e6e9f5;"
        f"  border: 1px solid #ffffff;"
        f"}}"
        f"{selector}::indicator:disabled {{"
        f"  background: #313244;"
        f"  border: 1px solid #6c7086;"
        f"}}"
        f"{selector}::indicator:checked:disabled {{"
        f"  background: #585b70;"
        f"  border: 1px solid #6c7086;"
        f"}}"
    )


def _radio_qss() -> str:
    """App-wide QRadioButton chrome (all tabs inherit via application stylesheet)."""
    return (
        f"QRadioButton {{"
        f"  background-color: transparent;"
        f"  color: {_DARK_TEXT};"
        f"  spacing: 8px;"
        f"}}"
        f"QRadioButton:disabled {{ color: {_DARK_OVERLAY}; }}"
        + _radio_indicator_qss("QRadioButton")
    )


def _text_panel_qss():
    """Read-only / editable multiline panels (summary boxes, client log, etc.)."""
    return (
        f"QTextEdit, QTextBrowser, QPlainTextEdit {{"
        f"  background-color: {_DARK_INPUT_BG};"
        f"  color: {_DARK_TEXT};"
        f"  border: 1px solid {_DARK_INPUT_BORDER};"
        f"  border-radius: {_INPUT_FIELD_RADIUS}px;"
        f"  padding: {_INPUT_FIELD_PADDING};"
        f"  selection-background-color: #45475a;"
        f"  selection-color: {_DARK_TEXT};"
        f"}}"
        f"QTextEdit#appLogView, QTextEdit#consoleLogView,"
        f"QPlainTextEdit#appLogView, QPlainTextEdit#consoleLogView {{"
        f"  background-color: {_DARK_BG};"
        f"  border: 1px solid {_DARK_GRID};"
        f"}}"
        f"QTextEdit#appLogView QAbstractScrollArea::viewport,"
        f"QPlainTextEdit#appLogView QAbstractScrollArea::viewport,"
        f"QTextEdit#consoleLogView QAbstractScrollArea::viewport,"
        f"QPlainTextEdit#consoleLogView QAbstractScrollArea::viewport {{"
        f"  background-color: {_DARK_BG};"
        f"}}"
    )


def _apply_dark_log_view(widget, object_name='appLogView', extra_qss=''):
    """Read-only log / preview QTextEdit: match app background (not input-panel grey)."""
    widget.setObjectName(object_name)
    widget.setAttribute(Qt.WA_StyledBackground, True)
    widget.setAutoFillBackground(True)
    widget.setStyleSheet(
        f"QTextEdit#{object_name} {{ background-color: {_DARK_BG}; color: {_DARK_TEXT}; "
        f"border: 1px solid {_DARK_GRID}; {extra_qss} }}"
    )
    vp = widget.viewport()
    vp.setAutoFillBackground(True)
    vp.setStyleSheet(f"background-color: {_DARK_BG};")
    pal = widget.palette()
    pal.setColor(QPalette.ColorRole.Base, QColor(_DARK_BG))
    pal.setColor(QPalette.ColorRole.Window, QColor(_DARK_BG))
    widget.setPalette(pal)
    vp.setPalette(pal)
    widget.document().setDefaultStyleSheet(
        f"body {{ background-color: {_DARK_BG}; color: {_DARK_TEXT}; }}"
    )


def _configure_app_input_palette(app):
    """Palette Base/Window for line edits and spin inner fields (QSS + native)."""
    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Base, QColor(_DARK_INPUT_BG))
    pal.setColor(QPalette.ColorRole.Window, QColor(_DARK_INPUT_BG))
    pal.setColor(QPalette.ColorRole.Text, QColor(_DARK_TEXT))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(_DARK_OVERLAY))
    pal.setColor(QPalette.ColorRole.Highlight, QColor('#45475a'))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(_DARK_TEXT))
    app.setPalette(pal)


def _tab_freshness_background(last_update, now=None):
    """Updateable page tab: solid green when fresh → black over 20 min; never updated = black."""
    if last_update is None:
        return _TAB_PAGE_NOT_UPDATED
    if now is None:
        now = datetime.now()
    age = (now - last_update).total_seconds()
    if age >= _TAB_FRESH_MAX_AGE_SEC:
        return _TAB_PAGE_NOT_UPDATED
    return _lerp_hex(_TAB_FRESH_TINT, _TAB_PAGE_NOT_UPDATED, age / _TAB_FRESH_MAX_AGE_SEC)


def _relative_luminance(hex_color):
    """WCAG relative luminance for sRGB hex."""
    def _lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_rgb(hex_color)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast_ratio(bg_hex, fg_hex):
    l1 = _relative_luminance(bg_hex)
    l2 = _relative_luminance(fg_hex)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def _contrasting_tab_text(bg_hex):
    """Pick black or white label — whichever has higher contrast on this tab tint."""
    if _contrast_ratio(bg_hex, _TAB_TEXT_ON_LIGHT_BG) >= _contrast_ratio(
        bg_hex, _TAB_PAGE_NOT_UPDATED_TEXT
    ):
        return _TAB_TEXT_ON_LIGHT_BG
    return _TAB_PAGE_NOT_UPDATED_TEXT


def _tab_freshness_text_color(last_update, now, selected=False):
    """Label colour for updateable pages (white on black when not updated)."""
    bg = _tab_freshness_background(last_update, now)
    if last_update is None:
        return _TAB_PAGE_NOT_UPDATED_TEXT
    if now is None:
        now = datetime.now()
    age = (now - last_update).total_seconds()
    if age >= _TAB_FRESH_MAX_AGE_SEC:
        return _TAB_PAGE_NOT_UPDATED_TEXT
    return _contrasting_tab_text(bg)


# Window chrome (Catppuccin Mocha). Nested QWidget is transparent so read-only
# labels (Device Information, Physical panel, etc.) do not sit on black/grey tiles.
_APP_DARK_THEME_QSS = (
    f"""
QMainWindow {{
    background-color: {_DARK_BG};
    color: {_DARK_TEXT};
}}
QDialog, QMessageBox {{
    background-color: {_DARK_SURFACE_BG};
    color: {_DARK_TEXT};
}}
QWidget {{
    background-color: transparent;
    color: {_DARK_TEXT};
}}
QFrame {{
    background-color: transparent;
    border: none;
}}
QFrame#liveBannerCard {{
    background-color: {_DARK_BG};
    border: 1px solid #45475a;
    border-radius: 6px;
}}
QLabel {{
    background-color: transparent;
    border: none;
    color: {_DARK_TEXT};
}}
QStatusBar {{
    background-color: {_DARK_BG};
    color: {_DARK_TEXT};
    border-top: 1px solid {_DARK_GRID};
}}
QFrame#systemStatusBar {{
    background-color: {_DARK_MANTLE};
    border: none;
    border-top: 1px solid {_DARK_GRID};
}}
QFrame#systemStatusBar QLabel {{
    color: {_DARK_SUBTEXT};
    font-size: 11px;
    background: transparent;
    border: none;
    padding: 0px;
}}
QFrame#systemStatusBar QLabel#dbStatus {{
    font-weight: 600;
    color: {_DARK_TEXT};
}}
QFrame#systemStatusBar QLabel#dbStatus[dbHealth="ok"] {{
    color: #a6e3a1;
}}
QFrame#systemStatusBar QLabel#dbStatus[dbHealth="bad"] {{
    color: #f38ba8;
}}
QFrame#systemStatusBar QLabel#octopusStatus {{
    font-weight: 600;
}}
QFrame#systemStatusBar QLabel#octopusStatus[octopusHealth="ok"] {{
    color: #a6e3a1;
}}
QFrame#systemStatusBar QLabel#octopusStatus[octopusHealth="warn"] {{
    color: #fab387;
}}
QFrame#systemStatusBar QLabel#octopusStatus[octopusHealth="bad"] {{
    color: #f38ba8;
}}
QFrame#systemStatusBar QLabel#octopusStatus[octopusHealth="busy"] {{
    color: #b8dcff;
}}
QFrame#systemStatusBar QLabel#octopusStatus[octopusHealth="idle"] {{
    color: #6c7086;
}}
QFrame#systemStatusBar QLabel[ingestHealth="dry"] {{
    color: #fab387;
}}
QFrame#systemStatusBar QLabel[ingestHealth="bad"] {{
    color: #f38ba8;
}}
QStatusBar QLabel#procStatsLabel {{
    color: {_DARK_SUBTEXT};
    font-size: 11px;
    padding: 0 12px;
    background: transparent;
    border: none;
}}
QGroupBox {{
    background-color: {_DARK_SURFACE_BG};
    border: 1px solid {_DARK_GRID};
    border-radius: 6px;
    margin-top: 10px;
    padding: 8px 10px 10px 10px;
    color: {_DARK_TEXT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {_DARK_SUBTEXT};
    background-color: {_DARK_SURFACE_BG};
}}
"""
    + _input_widgets_qss()
    + f"""
QTabWidget::pane {{
    border: 1px solid {_DARK_GRID};
    background: {_DARK_BG};
    border-radius: 4px;
    top: -1px;
}}
QTabWidget::tab-bar {{
    background: {_DARK_BG};
}}
QTabBar {{
    background: {_DARK_BG};
}}
QTabBar::tab {{
    background: transparent;
    color: {_DARK_OVERLAY};
    padding: 6px 14px;
    border: 1px solid transparent;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: transparent;
    color: {_DARK_TEXT};
    font-weight: bold;
    border: 1px solid {_DARK_GRID};
    border-bottom: 1px solid {_DARK_BG};
}}
QTabBar::tab:hover {{
    color: {_DARK_SUBTEXT};
}}
QTreeWidget, QTableWidget {{
    background-color: {_DARK_BG};
    alternate-background-color: {_DARK_BG};
    color: {_DARK_TEXT};
    border: 1px solid {_DARK_GRID};
    gridline-color: {_DARK_GRID};
}}
QTreeWidget::item:selected, QTableWidget::item:selected {{
    background-color: #45475a;
    color: {_DARK_TEXT};
}}
QHeaderView::section {{
    background-color: {_DARK_BG};
    color: {_DARK_TEXT};
    border: none;
    border-bottom: 1px solid {_DARK_GRID};
    border-right: 1px solid {_DARK_GRID};
    padding: 4px;
}}
QScrollArea, QScrollArea > QWidget > QWidget {{
    background-color: transparent;
    border: none;
}}
"""
    + _text_panel_qss()
    + _checkbox_qss()
    + _radio_qss()
    + f"""
QSplitter::handle {{
    background-color: #585b70;
}}
QSlider::groove:horizontal {{
    background: #45475a;
    height: 6px;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: #89b4fa;
    width: 14px;
    margin: -4px 0;
    border-radius: 7px;
}}
"""
)


def application_stylesheet():
    """Global dark surfaces plus button / toolbar interaction styles."""
    return _APP_DARK_THEME_QSS + _APP_GLOBAL_WIDGET_QSS


# Tab & dialog action buttons: same Catppuccin-green tint as Growatt Connect /
# Alias for tabs that set a stylesheet explicitly (same as app-wide default).
_SUBTLE_BTN_QSS = _REFRESH_ALL_BTN_QSS
_TASMOTA_ACTION_BTN_QSS = _REFRESH_ALL_BTN_QSS


def _tasmota_toggle_btn_qss(relay_on, *, reachable=True):
    """Toggle colours: green ON, red OFF, slate unknown, muted grey when unreachable."""
    fg = "#ffffff"
    if not reachable:
        bg, border = "rgba(69, 71, 90, 140)", "rgba(108, 112, 134, 90)"
        hover_bg, hover_border = bg, border
        press_bg, press_border = bg, border
        hint = "device unreachable — toggle unavailable"
    elif relay_on is True:
        bg, border = "rgba(166, 227, 161, 105)", "rgba(166, 227, 161, 185)"
        hover_bg, hover_border = "rgba(166, 227, 161, 145)", "rgba(166, 227, 161, 210)"
        press_bg, press_border = "rgba(166, 227, 161, 175)", "rgba(166, 227, 161, 220)"
        hint = "relay ON — click to turn off"
    elif relay_on is False:
        bg, border = "rgba(243, 139, 168, 105)", "rgba(243, 139, 168, 185)"
        hover_bg, hover_border = "rgba(243, 139, 168, 145)", "rgba(243, 139, 168, 210)"
        press_bg, press_border = "rgba(243, 139, 168, 175)", "rgba(243, 139, 168, 220)"
        hint = "relay OFF — click to turn on"
    else:
        bg, border = "rgba(108, 112, 134, 95)", "rgba(137, 180, 250, 140)"
        hover_bg, hover_border = "rgba(108, 112, 134, 130)", "rgba(137, 180, 250, 175)"
        press_bg, press_border = "rgba(108, 112, 134, 155)", "rgba(137, 180, 250, 195)"
        hint = "relay state unknown"
    qss = (
        f"QPushButton[tasmotaToggle=\"true\"] {{"
        f"  background: {bg};"
        f"  color: {fg};"
        f"  border: 1px solid {border};"
        f"  border-radius: 3px;"
        f"  font-weight: bold;"
        f"}}"
        f"QPushButton[tasmotaToggle=\"true\"]:hover {{"
        f"  background: {hover_bg};"
        f"  border: 1px solid {hover_border};"
        f"  color: {fg};"
        f"  font-weight: bold;"
        f"}}"
        f"QPushButton[tasmotaToggle=\"true\"]:pressed {{"
        f"  background: {press_bg};"
        f"  border: 1px solid {press_border};"
        f"  color: {fg};"
        f"  font-weight: bold;"
        f"}}"
    )
    if not reachable:
        qss += (
            'QPushButton[tasmotaToggle="true"]:disabled {'
            f"  background: {bg};"
            f"  color: rgba(205, 214, 244, 140);"
            f"  border: 1px solid {border};"
            "  font-weight: bold;"
            "}"
        )
    return qss, hint

def _retention_activate_btn_qss(*, active: bool) -> str:
    """Per-table ring-buffer toggle — electric blue when active."""
    if active:
        bg, border = "rgba(0, 168, 255, 0.28)", _ELECTRIC_BLUE
        hover_bg = "rgba(0, 168, 255, 0.38)"
    else:
        bg, border = "rgba(108, 112, 134, 0.35)", "#45475a"
        hover_bg = "rgba(108, 112, 134, 0.55)"
    return (
        f"QPushButton {{"
        f"  background: {bg};"
        f"  color: {_DARK_TEXT};"
        f"  border: 1px solid {border};"
        f"  border-radius: 4px;"
        f"  padding: 4px 12px;"
        f"  font-weight: bold;"
        f"  min-width: 88px;"
        f"}}"
        f"QPushButton:hover {{"
        f"  background: {hover_bg};"
        f"  border: 1px solid {border};"
        f"}}"
    )


def _retention_row_action_btn_qss() -> str:
    """Save / Prune on one retention row — muted green like other action buttons."""
    return _REFRESH_ALL_BTN_QSS


def _style_ax_dark(ax, fig):
    fig.set_facecolor(_DARK_BG)
    ax.set_facecolor(_DARK_FACE)
    ax.tick_params(colors=_DARK_TEXT, labelsize=9)
    ax.xaxis.label.set_color(_DARK_TEXT)
    ax.yaxis.label.set_color(_DARK_TEXT)
    # Chart titles stay pure white for contrast on the dark face.
    ax.title.set_color('#ffffff')
    for spine in ax.spines.values():
        spine.set_color(_DARK_GRID)


__all__ = [n for n in globals() if not n.startswith('__')]
