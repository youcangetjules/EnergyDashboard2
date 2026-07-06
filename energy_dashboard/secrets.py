"""
Load credentials from environment variables and local .env files.

Search order for each key (first match wins):
  1. ``os.environ`` — already set (systemd, shell export, CI)
  2. Repo-root ``.env``
  3. ``~/.config/PowerModel/secrets.env``

Copy ``.env.example`` to ``.env`` and fill in your values. Never commit ``.env``.
"""
from __future__ import annotations

import os
from pathlib import Path

from energy_dashboard.paths import REPO_ROOT

_LOADED = False


def _dotenv_paths() -> list[Path]:
    xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return [
        REPO_ROOT / ".env",
        Path(xdg) / "PowerModel" / "secrets.env",
    ]


def _parse_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[7:].strip()
    if "=" not in line:
        return None
    key, _, val = line.partition("=")
    key = key.strip()
    if not key:
        return None
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        val = val[1:-1]
    return key, val


def load_secrets() -> None:
    """Parse local .env files into ``os.environ`` (without overriding existing keys)."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    for path in _dotenv_paths():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            parsed = _parse_line(line)
            if parsed is None:
                continue
            key, val = parsed
            os.environ.setdefault(key, val)


def secret(name: str, default: str = "") -> str:
    """Return a secret/config value from the environment or local .env files."""
    load_secrets()
    return os.environ.get(name, default)


__all__ = ["load_secrets", "secret"]
