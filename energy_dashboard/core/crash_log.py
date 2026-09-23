"""Log segmentation faults and other fatal signals.

A crash like this never reaches Python's exception hook — the process is
already dead — so the usual Console logger cannot see it. This module:

* arms ``faulthandler`` so the Python stacks of every thread are appended to
  ``~/.energy_dashboard_crash.log`` at the moment of the fault;
* lets ``run-dashboard.sh`` append the matching systemd core-dump stack
  after the process has died;
* on a later start, copies any dashboard core dumps the launcher did not
  already record (for example a start that did not go through the shell
  script) and writes a Crash line into the Console log.

The open file is kept on a small sentinel in ``sys.modules`` so the early
launcher load and the later package import share one handle.
"""
from __future__ import annotations

import atexit
import faulthandler
import json
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

# Same file the Console tab restores. Duplicated here so this module can load
# before ``energy_dashboard`` (that package import pulls in Qt).
_CONSOLE_LOG_PATH = Path.home() / ".energy_dashboard_console.jsonl"

_SENTINEL = "_powermodel_crash_log_state"
_MAX_CORES_PER_START = 8
_COREDUMP_TIMEOUT_S = 25

# Not crashes we want a core-dump essay for: hangup, Ctrl-C, kill -9, a
# broken pipe, or a normal terminate.
_QUIET_SIGNALS = frozenset({1, 2, 9, 13, 15})

_PLAIN_SIGNAL = {
    "SIGHUP": "hangup",
    "SIGINT": "interrupt",
    "SIGQUIT": "quit",
    "SIGILL": "illegal instruction",
    "SIGTRAP": "trace trap",
    "SIGABRT": "abort",
    "SIGBUS": "bus error",
    "SIGFPE": "arithmetic fault",
    "SIGKILL": "kill",
    "SIGSEGV": "segmentation fault",
    "SIGPIPE": "broken pipe",
    "SIGTERM": "terminate",
    "SIGSYS": "bad system call",
}


def crash_log_path() -> Path:
    override = os.environ.get("POWERMODEL_CRASH_LOG", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".energy_dashboard_crash.log"


def _seen_path() -> Path:
    path = crash_log_path()
    return path.with_name(path.name + ".seen")


def _state() -> SimpleNamespace:
    existing = sys.modules.get(_SENTINEL)
    if isinstance(existing, SimpleNamespace):
        return existing
    state = SimpleNamespace(fh=None, installed=False, clean_registered=False)
    sys.modules[_SENTINEL] = state
    return state


def _write(text: str) -> None:
    fh = _state().fh
    if fh is None:
        return
    try:
        fh.write(text.encode("utf-8", errors="replace"))
    except OSError:
        pass


def install_crash_logger() -> None:
    """Open the crash log and arm faulthandler. Safe to call more than once."""
    state = _state()
    if state.installed and state.fh is not None:
        rearm_crash_logger()
        return
    path = crash_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(path, "ab", buffering=0)
    except OSError:
        return
    state.fh = fh
    state.installed = True
    now = datetime.now().isoformat(timespec="seconds")
    cmd = " ".join(sys.argv)
    _write(
        f"\n===== session start pid={os.getpid()} {now}\n"
        f"argv: {cmd}\n"
    )
    rearm_crash_logger()
    if not state.clean_registered:
        atexit.register(_mark_clean_exit)
        state.clean_registered = True


def rearm_crash_logger() -> None:
    """Point faulthandler at the crash log again.

    Qt and Chromium install their own fatal-signal handlers after startup.
    Calling this again puts our logger back in front so a later fault is
    still written down.
    """
    fh = _state().fh
    if fh is None:
        return
    try:
        faulthandler.enable(file=fh, all_threads=True)
    except (AttributeError, OSError, RuntimeError, ValueError):
        return


def note_version(version: str) -> None:
    _write(f"version: {version}\n")


def _mark_clean_exit() -> None:
    now = datetime.now().isoformat(timespec="seconds")
    _write(f"===== clean exit pid={os.getpid()} {now}\n")


def signal_name(sig: int) -> str:
    try:
        return signal.Signals(sig).name
    except ValueError:
        return f"SIG{sig}"


def plain_signal(sig: int) -> str:
    name = signal_name(sig)
    return _PLAIN_SIGNAL.get(name, name)


def is_crash_status(status: int) -> bool:
    """True when a wait() status is a fatal signal worth logging."""
    if status < 128 or status > 255:
        return False
    return (status - 128) not in _QUIET_SIGNALS


def summarize_coredump_info(text: str) -> str:
    """Keep the identity lines and the crashing thread's stack."""
    head_keys = (
        "PID:",
        "Signal:",
        "Timestamp:",
        "Command Line:",
        "Executable:",
        "Storage:",
    )
    head: list[str] = []
    stack: list[str] = []
    in_stack = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Stack trace of thread"):
            if in_stack:
                break
            in_stack = True
        if in_stack:
            stack.append(line)
            if len(stack) > 45:
                stack.append("                …")
                break
            continue
        if any(key in line for key in head_keys):
            head.append(line.rstrip())
    parts = head
    if stack:
        parts = parts + [""] + stack
    return "\n".join(parts).rstrip() + "\n"


def _command_line(info: str) -> str:
    for line in info.splitlines():
        if "Command Line:" in line:
            return line.split("Command Line:", 1)[1].strip()
    return ""


def is_dashboard_command(command: str) -> bool:
    text = command.strip()
    if "EnergyDashboard2.py" in text:
        return True
    if "-m energy_dashboard" in text or text.endswith(" energy_dashboard"):
        return True
    return False


def _read_seen() -> set[str]:
    path = _seen_path()
    try:
        lines = path.read_text(encoding="utf-8").split()
    except OSError:
        return set()
    return {ln.strip() for ln in lines if ln.strip()}


def _mark_seen(pid: int) -> None:
    path = _seen_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{pid}\n")
    except OSError:
        return


def _append_text(text: str) -> None:
    path = crash_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(text)
            if not text.endswith("\n"):
                fh.write("\n")
    except OSError:
        return


def _coredump_info(pid: int) -> str:
    try:
        proc = subprocess.run(
            ["coredumpctl", "info", str(pid), "--no-pager"],
            capture_output=True,
            text=True,
            timeout=_COREDUMP_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (proc.stdout or "") + (proc.stderr or "")


def _append_console_line(message: str) -> None:
    now = datetime.now()
    entry = {
        "iso_ts": now.isoformat(timespec="milliseconds"),
        "ts": now.strftime("%H:%M:%S.%f")[:-3],
        "level": 3,
        "source": "Crash",
        "msg": message,
    }
    try:
        _CONSOLE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _CONSOLE_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except OSError:
        return


def record_launcher_death(pid: int, status: int) -> int:
    """Called by run-dashboard.sh after the dashboard process has died.

    Returns 0 always so the shell can still exit with the real status.
    """
    if not is_crash_status(status):
        return 0
    sig = status - 128
    name = signal_name(sig)
    plain = plain_signal(sig)
    now = datetime.now().isoformat(timespec="seconds")
    block = [
        "",
        f"===== launcher: pid {pid} died status={status} {name} ({plain}) {now}",
    ]
    info = _coredump_info(pid)
    command = _command_line(info)
    if info and (not command or is_dashboard_command(command)):
        block.append("----- core dump -----")
        block.append(summarize_coredump_info(info).rstrip())
        block.append("----- end core dump -----")
    elif not info:
        block.append("coredumpctl did not return a report for this pid.")
    text = "\n".join(block) + "\n"
    _append_text(text)
    _mark_seen(pid)
    where = crash_log_path()
    _append_console_line(
        f"The dashboard was killed by a {plain} ({name}). "
        f"Python stacks and the system core dump are in {where}."
    )
    print(f"Crash logged to {where}", file=sys.stderr)
    return 0


def _list_python_coredumps() -> list[dict]:
    try:
        proc = subprocess.run(
            ["coredumpctl", "list", "-q", "--json=short"],
            capture_output=True,
            text=True,
            timeout=_COREDUMP_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        rows = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []
    python_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        exe = str(row.get("exe") or "")
        base = Path(exe).name
        if base.startswith("python"):
            python_rows.append(row)
    python_rows.reverse()
    return python_rows


def import_new_coredumps(announce=None) -> list[dict]:
    """Copy recent dashboard core dumps that the launcher did not already log.

    ``announce`` is an optional ``callable(str)`` used to put one line on the
    Console. Returns the crashes that were newly written.
    """
    seen = _read_seen()
    found: list[dict] = []
    checked = 0
    for row in _list_python_coredumps():
        if checked >= _MAX_CORES_PER_START:
            break
        pid = row.get("pid")
        try:
            pid_i = int(pid)
        except (TypeError, ValueError):
            continue
        if str(pid_i) in seen:
            continue
        checked += 1
        info = _coredump_info(pid_i)
        if not info:
            continue
        command = _command_line(info)
        _mark_seen(pid_i)
        if not is_dashboard_command(command):
            continue
        sig = row.get("sig")
        try:
            sig_i = int(sig)
        except (TypeError, ValueError):
            sig_i = 0
        plain = plain_signal(sig_i) if sig_i else "crash"
        name = signal_name(sig_i) if sig_i else "signal"
        when = ""
        for line in info.splitlines():
            if "Timestamp:" in line:
                when = line.split("Timestamp:", 1)[1].strip()
                break
        header = (
            f"\n===== imported core dump pid {pid_i} {name} ({plain})"
            + (f" {when}" if when else "")
            + "\n"
        )
        body = "----- core dump -----\n" + summarize_coredump_info(info).rstrip()
        _append_text(header + body + "\n----- end core dump -----\n")
        found.append({"pid": pid_i, "sig": name, "plain": plain, "when": when})
    if found and announce is not None:
        newest = found[0]
        extra = f" ({len(found)} crashes)" if len(found) > 1 else ""
        when = f" at {newest['when']}" if newest["when"] else ""
        try:
            announce(
                f"Logged a {newest['plain']} from pid {newest['pid']}{when}{extra}. "
                f"Details are in {crash_log_path()}."
            )
        except Exception:
            pass
    return found


def schedule_import_coredumps(announce=None) -> None:
    """Look up recent core dumps without holding up the window opening."""
    threading.Thread(
        target=lambda: import_new_coredumps(announce),
        name="crash-log-import",
        daemon=True,
    ).start()
