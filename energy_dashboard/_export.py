"""Import helper: merge a module's public and ``_`` names into a namespace."""
from __future__ import annotations

import importlib


def load(ns: dict, module_name: str) -> None:
    mod = importlib.import_module(module_name)
    for name in getattr(mod, "__all__", [n for n in dir(mod) if not n.startswith("__")]):
        ns[name] = getattr(mod, name)
