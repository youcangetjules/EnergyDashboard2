"""This-process CPU and resident memory for the status bar."""
from __future__ import annotations

import os
import time


def _clk_tck():
    try:
        n = os.sysconf("SC_CLK_TCK")
        if n and n > 0:
            return int(n)
    except (ValueError, OSError, AttributeError):
        pass
    return 100


def _read_self_cpu_ticks():
    """User + system jiffies for this PID (threads included; children not)."""
    with open("/proc/self/stat", encoding="utf-8") as fh:
        raw = fh.read()
    rest = raw[raw.rfind(")") + 2 :].split()
    # Fields 14–15 after pid+comm: utime, stime (1-based).
    return int(rest[11]) + int(rest[12])


def _read_self_rss_bytes():
    with open("/proc/self/status", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return None


def _fmt_bytes(n):
    if n is None or n < 0:
        return "—"
    mb = n / (1024.0 * 1024.0)
    if mb >= 1024.0:
        return f"{mb / 1024.0:.1f} GB"
    if mb >= 10.0:
        return f"{mb:.0f} MB"
    return f"{mb:.1f} MB"


class ProcessResourceSampler:
    """Delta CPU % (100% = one core busy) and current RSS."""

    def __init__(self):
        self._clk = _clk_tck()
        self._prev_ticks = None
        self._prev_mono = None
        try:
            self._prev_ticks = _read_self_cpu_ticks()
            self._prev_mono = time.monotonic()
        except (OSError, IndexError, ValueError):
            pass

    def sample(self):
        cpu_txt = "—"
        mem_txt = "—"
        try:
            ticks = _read_self_cpu_ticks()
            now = time.monotonic()
            if self._prev_ticks is not None and self._prev_mono is not None:
                dt = now - self._prev_mono
                if dt > 0.05:
                    d_ticks = max(0, ticks - self._prev_ticks)
                    pct = (d_ticks / self._clk) / dt * 100.0
                    cpu_txt = f"{pct:.0f}%" if pct >= 10.0 else f"{pct:.1f}%"
            self._prev_ticks = ticks
            self._prev_mono = now
        except (OSError, IndexError, ValueError):
            self._prev_ticks = None
            self._prev_mono = None
        try:
            mem_txt = _fmt_bytes(_read_self_rss_bytes())
        except (OSError, IndexError, ValueError):
            pass
        return cpu_txt, mem_txt
