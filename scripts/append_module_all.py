#!/usr/bin/env python3
"""Append __all__ to split modules so `from module import *` includes _private names."""
from __future__ import annotations

from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "energy_dashboard"
SKIP = {"deps.py", "paths.py", "__init__.py", "__main__.py", "common.py"}


def main() -> None:
    for path in sorted(PKG.rglob("*.py")):
        if path.name in SKIP or path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "__all__" in text:
            continue
        text = text.rstrip() + "\n\n\n__all__ = [n for n in globals() if not n.startswith('__')]\n"
        path.write_text(text, encoding="utf-8")
        print("patched", path.relative_to(PKG.parent))
    print("done")


if __name__ == "__main__":
    main()
