"""Map a chess square to its centre point inside a board rectangle.

Square indices follow python-chess: ``0`` = a1, ``file = square % 8`` (0 = a) and
``rank = square // 8`` (0 = rank 1). The board is drawn with the player's pieces at
the bottom, so the orientation (``white_bottom``) flips the mapping.
"""

from __future__ import annotations

from .locator import BoardRect


def square_center(rect: BoardRect, square: int, white_bottom: bool) -> tuple[float, float]:
    """Return the screen-space centre ``(x, y)`` of ``square`` within ``rect``."""
    file = square % 8
    rank = square // 8
    if white_bottom:
        col = file  # a..h left to right
        row = 7 - rank  # rank 8 at the top
    else:
        col = 7 - file  # board flipped: a..h right to left
        row = rank  # rank 1 at the top
    cell_w = rect.w / 8
    cell_h = rect.h / 8
    cx = rect.x + (col + 0.5) * cell_w
    cy = rect.y + (row + 0.5) * cell_h
    return cx, cy
