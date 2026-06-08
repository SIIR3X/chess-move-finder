"""Bridge best-move suggestions to the on-screen arrow overlay.

Runs on the worker thread (where suggestions are produced): it maps the move's
squares into the calibrated board rectangle (Qt screen coordinates) and emits the
two points to the overlay, which renders on the GUI thread. Without a calibration
it just logs the move. Clearing is emitting ``None``.
"""

from __future__ import annotations

import logging

import chess

from ..overlay.geometry import square_center
from ..overlay.locator import BoardRect
from .arrow_window import ArrowOverlay

logger = logging.getLogger("chess_move_finder")


class OverlayController:
    def __init__(self, overlay: ArrowOverlay) -> None:
        self._overlay = overlay
        self._board_rect: BoardRect | None = None
        self._white_bottom = True
        # No arrow until the startup calibration is resolved (calibrated or kept).
        self._ready = False

    def set_ready(self) -> None:
        """Allow arrows to be drawn (called once the calibration prompt closes)."""
        self._ready = True

    def is_calibrated(self) -> bool:
        """Whether the board is calibrated and arrows are allowed (for the GUI status)."""
        return self._ready and self._board_rect is not None

    def set_board_rect(self, rect: BoardRect | None) -> None:
        self._board_rect = rect

    def set_color(self, color: str | None) -> None:
        # Our pieces are at the bottom unless we play Black (default White if unknown).
        self._white_bottom = color != "black"

    def clear(self) -> None:
        self._overlay.arrow_changed.emit(None)

    def on_suggestion(self, board: chess.Board, move: chess.Move | None) -> None:
        if not self._ready:
            return  # calibration prompt still open: keep the overlay blank
        if move is None:
            self.clear()
            return
        logger.info("Best move: %s (%s)", board.san(move), move.uci())
        rect = self._board_rect
        if rect is None:
            logger.info("Board not calibrated; use the tray icon to calibrate")
            self.clear()
            return
        fx, fy = square_center(rect, move.from_square, self._white_bottom)
        tx, ty = square_center(rect, move.to_square, self._white_bottom)
        self._overlay.arrow_changed.emit((fx, fy, tx, ty))
