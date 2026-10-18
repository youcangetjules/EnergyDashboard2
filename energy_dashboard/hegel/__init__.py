"""Hegel community energy inventory.

This package does not run on startup and does not talk to inverters.
Discovery clients are added later; they stay idle until a button asks.
"""
from __future__ import annotations

HEGEL_DBNAME = "hegel"

__all__ = ["HEGEL_DBNAME"]
