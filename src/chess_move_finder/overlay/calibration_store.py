"""Persist the calibrated board rectangle (in Qt screen coordinates).

Browser coordinates don't line up with Qt's across multi-monitor / DPI-scaled
setups, so the board rectangle is obtained by clicking its corners and stored
here, in Qt's own coordinate space - no DPI conversion, robust to any layout.
Pure (no Qt) so it can be unit tested.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..paths import config_dir
from .locator import BoardRect

logger = logging.getLogger("chess_move_finder")

CALIBRATION_PATH = config_dir() / "calibration.json"


def rect_from_corners(x1: float, y1: float, x2: float, y2: float) -> BoardRect:
    """Board rectangle from two opposite corners, in any order."""
    return BoardRect(min(x1, x2), min(y1, y2), float(abs(x2 - x1)), float(abs(y2 - y1)))


def load_calibration(path: Path = CALIBRATION_PATH) -> BoardRect | None:
    """Load a saved board rectangle, or ``None`` if absent/unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return BoardRect(float(data["x"]), float(data["y"]), float(data["w"]), float(data["h"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_calibration(rect: BoardRect, path: Path = CALIBRATION_PATH) -> None:
    """Persist a board rectangle (best-effort; warns on failure)."""
    payload = {"x": rect.x, "y": rect.y, "w": rect.w, "h": rect.h}
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        logger.warning("Could not save calibration to %s", path)
