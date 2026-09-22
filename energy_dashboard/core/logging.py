"""
Energy Dashboard — `core/logging.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.core.console_paths import *
from energy_dashboard.version import APP_VERSION


class LogManager(QObject):
    """Thread-safe log manager that collects messages for display in a Console tab."""

    DEBUG, INFO, WARN, ERROR = 0, 1, 2, 3
    _LEVEL_LABELS = {0: "DEBUG", 1: "INFO", 2: "WARN", 3: "ERROR"}

    _new_entry = Signal()

    def __init__(self):
        super().__init__()
        self._entries = []
        self._lock = threading.Lock()
        self._persist_path = _CONSOLE_LOG_PATH
        self._persist_fh = None
        self._load_from_disk()
        self._open_persist_file_and_mark_session()

    def _load_from_disk(self):
        try:
            if not self._persist_path.is_file():
                return
            self._maybe_trim_file()
            with self._persist_path.open('r', encoding='utf-8') as fh:
                lines = fh.readlines()
        except OSError:
            return
        for ln in lines[-_CONSOLE_LOG_MAX_ENTRIES:]:
            ln = ln.strip()
            if not ln:
                continue
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if not all(k in e for k in ("level", "source", "msg")):
                continue
            if 'ts' not in e:
                iso = e.get('iso_ts')
                if iso:
                    try:
                        dt = datetime.fromisoformat(iso)
                        e['ts'] = dt.strftime('%H:%M:%S.%f')[:-3]
                    except ValueError:
                        e['ts'] = '--:--:--.---'
                else:
                    e['ts'] = '--:--:--.---'
            self._entries.append(e)

    def _maybe_trim_file(self):
        try:
            with self._persist_path.open('r', encoding='utf-8') as fh:
                lines = fh.readlines()
            if len(lines) <= _CONSOLE_LOG_FILE_TRIM_AT:
                return
            tail = lines[-_CONSOLE_LOG_MAX_ENTRIES:]
            tmp = self._persist_path.with_suffix(self._persist_path.suffix + '.tmp')
            with tmp.open('w', encoding='utf-8') as fh:
                fh.writelines(tail)
            tmp.replace(self._persist_path)
        except OSError:
            pass

    def _open_persist_file_and_mark_session(self):
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._persist_fh = self._persist_path.open(
                'a', encoding='utf-8', buffering=1
            )
        except OSError:
            self._persist_fh = None
        self.info("App", f"========== Session start v{APP_VERSION} ==========")

    def log(self, level, source, message):
        now = datetime.now()
        entry = {
            "iso_ts": now.isoformat(timespec='milliseconds'),
            "ts": now.strftime("%H:%M:%S.%f")[:-3],
            "level": level,
            "source": source,
            "msg": str(message),
        }
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > _CONSOLE_LOG_MAX_ENTRIES:
                self._entries = self._entries[-3000:]
            if self._persist_fh is not None:
                try:
                    self._persist_fh.write(
                        json.dumps(entry, ensure_ascii=True) + '\n'
                    )
                except OSError:
                    self._persist_fh = None
        self._emit_new_entry()

    def _emit_new_entry(self) -> None:
        """Notify Console of a new line — never raise into worker threads.

        Background fetch threads (Octopus Live, etc.) keep logging after the
        GUI/QApplication tears down LogManager's C++ QObject on exit/restart.
        Emitting then raises ``RuntimeError: Signal source has been deleted``
        and can cascade through nested except handlers.
        """
        try:
            from shiboken6 import isValid as _qt_alive
        except Exception:
            _qt_alive = None
        try:
            if _qt_alive is not None and not _qt_alive(self):
                return
            if QApplication.instance() is None:
                return
            self._new_entry.emit()
        except RuntimeError:
            return

    def debug(self, source, msg):
        self.log(self.DEBUG, source, msg)

    def info(self, source, msg):
        self.log(self.INFO, source, msg)

    def warn(self, source, msg):
        self.log(self.WARN, source, msg)

    def err(self, source, msg):
        self.log(self.ERROR, source, msg)

    def exception(self, source, msg):
        """Log ERROR with full traceback appended."""
        tb = traceback.format_exc()
        if tb and tb.strip() != "NoneType: None":
            self.err(source, f"{msg}\n{tb}")
        else:
            self.err(source, str(msg))

    def get_entries(self, min_level=0, levels=None):
        with self._lock:
            if levels is not None:
                allowed = set(levels)
                return [e for e in self._entries if e["level"] in allowed]
            return [e for e in self._entries if e["level"] >= min_level]

    def clear_persisted(self):
        with self._lock:
            self._entries.clear()
            try:
                if self._persist_fh is not None:
                    self._persist_fh.close()
            except OSError:
                pass
            self._persist_fh = None
            try:
                if self._persist_path.is_file():
                    self._persist_path.unlink()
            except OSError:
                pass
        self._open_persist_file_and_mark_session()


_log_instance: LogManager | None = None


def get_log_manager() -> LogManager:
    """Return the app-wide log manager (created after QApplication exists)."""
    global _log_instance
    if _log_instance is None:
        _log_instance = LogManager()
    return _log_instance


def ensure_log_manager() -> LogManager:
    """Create the log manager if needed — call once QApplication exists."""
    return get_log_manager()


class _LogFacade:
    """Deferred binding so LogManager is not constructed before QApplication."""

    DEBUG = LogManager.DEBUG
    INFO = LogManager.INFO
    WARN = LogManager.WARN
    ERROR = LogManager.ERROR

    def __getattr__(self, name):
        return getattr(get_log_manager(), name)


_log = _LogFacade()


__all__ = [
    "LogManager",
    "get_log_manager",
    "ensure_log_manager",
    "_log",
]
