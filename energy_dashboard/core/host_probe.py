"""Whether an IP address answers on a port.

Used by an Alarm defs signal whose source is an address. A short TCP
connection is the check. It is not a reading from the device, and it does
not send a command.
"""
from __future__ import annotations

import socket


def tcp_host_answers(ip: str, port: int, timeout: float = 1.2) -> bool:
    """True when something accepts a connection. False when it does not."""
    try:
        with socket.create_connection((str(ip), int(port)), timeout=float(timeout)):
            return True
    except OSError:
        return False
