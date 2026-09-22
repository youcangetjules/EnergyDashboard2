"""Qt platform env — must run before any PySide6 / QApplication import."""
from __future__ import annotations

import os
import sys


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _append_logging_rule(rule: str) -> None:
    existing = os.environ.get("QT_LOGGING_RULES", "").strip()
    if rule in existing:
        return
    os.environ["QT_LOGGING_RULES"] = f"{existing};{rule}".strip(";")


def configure_qt_platform() -> None:
    """Apply process-wide Qt settings for this app."""
    # Matplotlib QtAgg backend defaults to PyQt6 when both bindings are installed.
    os.environ.setdefault("QT_API", "pyside6")

    if not sys.platform.startswith("linux"):
        return
    # Screen-reader users can set POWERMODEL_QT_A11Y=1 to keep AT-SPI logging.
    if os.environ.get("POWERMODEL_QT_A11Y", "").strip().lower() in ("1", "true", "yes"):
        return
    _append_logging_rule("qt.accessibility.atspi=false")
    if not _truthy("POWERMODEL_WEBENGINE_GPU"):
        _append_logging_rule("qt.qpa.gl=false")


def _linux_software_gl() -> None:
    """Software OpenGL for Qt widgets, without the probes that print noise.

    ``LIBGL_ALWAYS_SOFTWARE`` makes Chromium ask Mesa for a DRM render node
    and log “Failed to query DRM render node”. Chromium ``--disable-gpu`` /
    ``--use-gl=disabled`` then logs “GPUInfo not initialized”. Qt’s own
    software OpenGL path does not do either probe.
    """
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("QT_XCB_GL_INTEGRATION", "none")
    # These two make WebEngine print the DRM / GPUInfo lines. A parent shell
    # or an older launcher may still have exported them.
    os.environ.pop("LIBGL_ALWAYS_SOFTWARE", None)
    _strip_noisy_chromium_flags()


def _strip_noisy_chromium_flags() -> None:
    """Remove Chromium switches that log the DRM / GPUInfo lines."""
    raw = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    if not raw:
        return
    drop = {
        "--disable-gpu",
        "--disable-gpu-compositing",
        "--disable-gpu-sandbox",
        "--in-process-gpu",
        "--disable-dev-shm-usage",
        "--disable-gpu-early-init",
        "--use-gl=disabled",
        "--log-level=3",
        "--disable-features=Vulkan",
    }
    kept = [part for part in raw.split() if part not in drop]
    if kept:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(kept)
    else:
        os.environ.pop("QTWEBENGINE_CHROMIUM_FLAGS", None)


def configure_qt_webengine_chromium() -> None:
    """Chromium flags before QApplication / first QWebEngineView.

    Linux Qt WebEngine used to SEGV inside the GPU probe. Forcing Chromium
    ``--disable-gpu`` stopped the crash but printed “GPUInfo not initialized”
    and, with ``LIBGL_ALWAYS_SOFTWARE``, “Failed to query DRM render node”.
    Those flags are no longer set. Qt software OpenGL (see
    ``prepare_qapplication_attributes``) is the quiet default unless
    POWERMODEL_WEBENGINE_GPU=1.

    Must run before ``QApplication(...)`` (ideally before importing
    ``PySide6.QtWebEngineWidgets``). Safe to call more than once.
    """
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    extra: list[str] = []

    if "--no-sandbox" not in flags:
        try:
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                extra.append("--no-sandbox")
        except Exception:
            pass

    allow_gpu = _truthy("POWERMODEL_WEBENGINE_GPU")
    if sys.platform.startswith("linux") and not allow_gpu:
        _linux_software_gl()

    if extra:
        flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{flags} {' '.join(extra)}".strip()


def prepare_qapplication_attributes() -> None:
    """Call immediately before ``QApplication(...)``.

    Env vars alone do not stop Qt from creating an EGL context; this attribute
    forces software OpenGL for the widget stack (charts, WebEngine host).
    """
    if not sys.platform.startswith("linux") or _truthy("POWERMODEL_WEBENGINE_GPU"):
        return
    try:
        from PySide6.QtCore import QCoreApplication, Qt
        QCoreApplication.setAttribute(
            Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True,
        )
    except Exception:
        pass


# Apply as soon as this module is imported (EnergyDashboard2 / __main__ do that
# before constructing QApplication).
configure_qt_platform()
configure_qt_webengine_chromium()
