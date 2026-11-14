"""
Energy Dashboard — `tabs/resources.py`.

Shows memory and CPU usage for every process associated with PowerModel:
the dashboard, the energy-collector daemon, and anything else whose
command line mentions powermon / energy_dashboard / EnergyDashboard.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from energy_dashboard.common import *
from energy_dashboard.core.single_instance import (
    DASHBOARD_NAME,
    COLLECTOR_NAME,
    _lock_path,
)

_KNOWN_SERVICES = (
    ("Dashboard", DASHBOARD_NAME),
    ("Collector daemon", COLLECTOR_NAME),
)

_CMDLINE_PATTERNS = re.compile(
    r"energy.?dashboard|energydashboard|energy.?collector|powermon",
    re.IGNORECASE,
)

_COL_HEADERS = ("PID", "Role", "RSS (MB)", "VMS (MB)", "CPU %", "Command")


def _read_proc_field(pid: int, field: str) -> str | None:
    """Read a single field from /proc/<pid>/status."""
    try:
        with open(f"/proc/{pid}/status") as fh:
            for line in fh:
                if line.startswith(field):
                    return line.split(":", 1)[1].strip()
    except (OSError, PermissionError):
        pass
    return None


def _read_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_text()
        return raw.replace("\x00", " ").strip()
    except (OSError, PermissionError):
        return ""


def _kb_to_mb(text: str | None) -> float:
    """Parse '123456 kB' → MB float."""
    if not text:
        return 0.0
    m = re.match(r"(\d+)", text)
    return int(m.group(1)) / 1024.0 if m else 0.0


def _cpu_percent(pid: int) -> str:
    """Rough instantaneous CPU % from /proc/<pid>/stat vs system uptime."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().split()
        utime = int(stat[13])
        stime = int(stat[14])
        starttime = int(stat[21])
        hz = os.sysconf("SC_CLK_TCK")
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        elapsed = uptime - (starttime / hz)
        if elapsed <= 0:
            return "—"
        total_cpu = (utime + stime) / hz
        return f"{100.0 * total_cpu / elapsed:.1f}"
    except (OSError, IndexError, ValueError, ZeroDivisionError):
        return "—"


def _pid_from_lock(name: str) -> int | None:
    try:
        text = Path(_lock_path(name)).read_text().strip()
        pid = int(text)
        # Check it's still alive.
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def _discover_processes() -> list[dict]:
    """Return a list of dicts for every PowerModel-related process."""
    seen: set[int] = set()
    results: list[dict] = []

    # 1) Known services via lock files.
    for role, lock_name in _KNOWN_SERVICES:
        pid = _pid_from_lock(lock_name)
        if pid is None:
            results.append({"pid": "—", "role": role, "rss": 0.0, "vms": 0.0,
                            "cpu": "—", "cmd": "(not running)"})
            continue
        seen.add(pid)
        rss = _kb_to_mb(_read_proc_field(pid, "VmRSS"))
        vms = _kb_to_mb(_read_proc_field(pid, "VmSize"))
        cpu = _cpu_percent(pid)
        cmd = _read_cmdline(pid)
        results.append({"pid": pid, "role": role, "rss": rss, "vms": vms,
                        "cpu": cpu, "cmd": cmd})

    # 2) Scan /proc for anything else matching PowerModel patterns.
    try:
        pids = [int(d) for d in os.listdir("/proc") if d.isdigit()]
    except OSError:
        pids = []
    for pid in pids:
        if pid in seen:
            continue
        cmd = _read_cmdline(pid)
        if not cmd or not _CMDLINE_PATTERNS.search(cmd):
            continue
        seen.add(pid)
        rss = _kb_to_mb(_read_proc_field(pid, "VmRSS"))
        vms = _kb_to_mb(_read_proc_field(pid, "VmSize"))
        cpu = _cpu_percent(pid)
        results.append({"pid": pid, "role": "Other", "rss": rss, "vms": vms,
                        "cpu": cpu, "cmd": cmd})

    return results


class ResourcesTab(QWidget):
    def __init__(self, dash=None):
        super().__init__()
        self.dash = dash
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        ctrl = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(_SUBTLE_BTN_QSS)
        refresh_btn.clicked.connect(self.refresh)
        ctrl.addWidget(refresh_btn)
        hint = QLabel("Memory and CPU for all PowerModel processes")
        hint.setStyleSheet("color: #6c7086; font-style: italic;")
        ctrl.addWidget(hint)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        self._table = QTableWidget(0, len(_COL_HEADERS))
        self._table.setHorizontalHeaderLabels(_COL_HEADERS)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget { alternate-background-color: #252536; }"
        )
        layout.addWidget(self._table, 1)

        self._summary = QLabel("")
        self._summary.setStyleSheet("color: #a6adc8; font-size: 11px; padding: 4px;")
        layout.addWidget(self._summary)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        procs = _discover_processes()
        self._table.setRowCount(len(procs))

        total_rss = 0.0
        for row, p in enumerate(procs):
            pid_str = str(p["pid"])
            rss_str = f"{p['rss']:.1f}" if p["rss"] else "—"
            vms_str = f"{p['vms']:.1f}" if p["vms"] else "—"
            total_rss += p["rss"]

            values = (pid_str, p["role"], rss_str, vms_str, p["cpu"], p["cmd"])
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    if col in (0, 2, 3, 4)
                    else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                self._table.setItem(row, col, item)

        self._table.resizeColumnsToContents()
        running = sum(1 for p in procs if p["pid"] != "—")
        self._summary.setText(
            f"{running} process{'es' if running != 1 else ''} running — "
            f"total RSS {total_rss:.1f} MB"
        )


__all__ = [n for n in globals() if not n.startswith('__')]
