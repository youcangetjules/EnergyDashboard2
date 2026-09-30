"""One dashboard process, and one collector process, on this machine.

The window and the energy collector are allowed to run together: the collector
keeps logging while the window is closed. A second window, or a second
collector, is not. The boot service and the user-session service are the same
program, so they share one lock. The lock is released when the process exits,
including a crash.

The lock file lives in /tmp so the user session and a root boot service can
see the same lock.
"""
from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass

DASHBOARD_NAME = "energy-dashboard"
COLLECTOR_NAME = "energy-collector"
_SHOW_SOCKET = "powermodel-energy-dashboard"

_held: dict[str, object] = {}


def _lock_path(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name)
    return f"/tmp/powermodel-{safe}.lock"


@dataclass
class InstanceClaim:
    """Result of trying to be the only process for one role."""

    name: str
    acquired: bool
    holder_pid: int | None = None
    _fh: object = None

    def release(self) -> None:
        fh = self._fh
        self._fh = None
        _held.pop(self.name, None)
        if fh is None:
            return
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            fh.close()
        except OSError:
            pass


def _read_pid(fd: int) -> int | None:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 64).decode("ascii", errors="ignore").strip()
    except OSError:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _open_lock(path: str):
    """Open the lock file for flock. Read-only is enough when we cannot write."""
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    except PermissionError:
        fd = os.open(path, os.O_RDONLY)
        return fd, False
    try:
        os.chmod(path, 0o666)
    except OSError:
        pass
    return fd, True


def claim(name: str) -> InstanceClaim:
    """Take the exclusive lock, or report the process that already holds it."""
    existing = _held.get(name)
    if isinstance(existing, InstanceClaim) and existing.acquired:
        return existing
    path = _lock_path(name)
    try:
        fd, writable = _open_lock(path)
    except OSError:
        return InstanceClaim(name=name, acquired=False, holder_pid=None)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        holder = _read_pid(fd)
        os.close(fd)
        return InstanceClaim(name=name, acquired=False, holder_pid=holder)
    except OSError:
        os.close(fd)
        return InstanceClaim(name=name, acquired=False, holder_pid=None)
    # Keep this open for the life of the process. Closing it drops the lock.
    fh = os.fdopen(fd, "r+" if writable else "r")
    if writable:
        try:
            fh.seek(0)
            fh.truncate()
            fh.write(f"{os.getpid()}\n")
            fh.flush()
        except OSError:
            pass
    result = InstanceClaim(name=name, acquired=True, holder_pid=os.getpid(), _fh=fh)
    _held[name] = result
    return result


def listen_for_show(callback) -> bool:
    """Ask this dashboard to come forward when another launch connects.

    ``callback`` runs on the window thread. Returns False if the socket could
    not be opened; the file lock still stops a second window.
    """
    try:
        from PySide6.QtNetwork import QLocalServer
    except Exception:
        return False
    try:
        QLocalServer.removeServer(_SHOW_SOCKET)
        server = QLocalServer()
        if not server.listen(_SHOW_SOCKET):
            return False
    except Exception:
        return False
    _held["show-socket"] = server

    def _on_connection() -> None:
        sock = server.nextPendingConnection()
        if sock is None:
            return
        try:
            callback()
        except Exception:
            pass
        sock.disconnectFromServer()

    server.newConnection.connect(_on_connection)
    return True


def ask_dashboard_to_show() -> bool:
    """Tell the dashboard that is already running to show its window."""
    try:
        from PySide6.QtNetwork import QLocalSocket
    except Exception:
        return False
    sock = QLocalSocket()
    try:
        sock.connectToServer(_SHOW_SOCKET)
        if not sock.waitForConnected(400):
            return False
        sock.write(b"show\n")
        sock.flush()
        if sock.state() == sock.LocalSocketState.ConnectedState:
            sock.waitForBytesWritten(200)
        sock.disconnectFromServer()
        return True
    except Exception:
        return False
    finally:
        sock.close()
