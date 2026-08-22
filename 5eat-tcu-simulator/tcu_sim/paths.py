"""Filesystem paths that work both as a plain script and as a PyInstaller
one-folder build. When frozen, the executable lives in dist/<app>/ and its
`_internal/` holds the bundled package + data; logs go next to the .exe so a
portable copy stays self-contained and writable.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_base() -> str:
    """Writable base dir for runtime artifacts (logs)."""
    if is_frozen():
        return os.path.dirname(sys.executable)          # the portable app folder
    return os.path.dirname(os.path.dirname(__file__))    # project root in dev


def web_dir() -> Path:
    """The bundled web assets (packaged under tcu_sim/web in both modes)."""
    return Path(__file__).parent / "web"


LOG_DIR = os.path.join(app_base(), "logs")
