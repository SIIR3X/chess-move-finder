"""Locate the chess.com board on screen, from a measurement read in the page.

The measurement is produced by :data:`BOARD_RECT_JS` (run via CDP), which returns
the board element's rectangle in the page plus the window's screen position and the
height of the browser chrome. :func:`screen_board_rect` turns that into the board's
rectangle in screen coordinates, so an overlay can be drawn over it.

Coordinates are in the browser's logical (CSS) pixels; with the browser at 100%
zoom and a DPI-aware overlay, those line up with the desktop. A residual offset or
scale can be corrected with the ``offset``/``scale`` arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Read-only JS: the board rectangle + the info needed to map it to the screen.
BOARD_RECT_JS = (
    "(function(){"
    "var b=document.querySelector('wc-chess-board,.board,cg-board,.cg-wrap');"
    "if(!b)return null;"
    "var r=b.getBoundingClientRect();"
    "return {x:r.x,y:r.y,w:r.width,h:r.height,"
    "sx:window.screenX,sy:window.screenY,"
    "ch:window.outerHeight-window.innerHeight,dpr:window.devicePixelRatio};"
    "})()"
)


@dataclass(frozen=True)
class BoardRect:
    """The board's bounding box in screen coordinates."""

    x: float
    y: float
    w: float
    h: float


def screen_board_rect(
    value: Any, offset_x: float = 0.0, offset_y: float = 0.0, scale: float = 1.0
) -> BoardRect | None:
    """Map a :data:`BOARD_RECT_JS` result to a screen-space :class:`BoardRect`.

    Returns ``None`` if the measurement is missing or degenerate (no board found).
    """
    if not isinstance(value, dict):
        return None
    try:
        x = float(value["x"])
        y = float(value["y"])
        w = float(value["w"])
        h = float(value["h"])
        sx = float(value["sx"])
        sy = float(value["sy"])
        ch = float(value["ch"])
    except (KeyError, TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    left = sx + x + offset_x
    top = sy + ch + y + offset_y
    return BoardRect(x=left, y=top, w=w * scale, h=h * scale)
