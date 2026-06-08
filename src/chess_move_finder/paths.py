"""Resolve config/data and bundled-resource paths, from source or as a frozen exe.

When packaged with PyInstaller (``sys.frozen``), the editable ``config/`` lives next
to the .exe, and read-only resources (icons, the default config) are unpacked into
``sys._MEIPASS``. From source, the editable config is ``./config`` (the repo root)
and resources sit inside the package. This module hides that difference.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """Whether we're running from a PyInstaller-built executable."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """The directory holding the editable ``config/`` (next to the exe, or the CWD)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def config_dir() -> Path:
    return app_dir() / "config"


def bundled(*parts: str) -> Path:
    """A read-only resource shipped with the app (unpacked to _MEIPASS when frozen)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)
