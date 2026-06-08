"""Tests for mapping squares to centre points within the board rectangle."""

import chess

from chess_move_finder.overlay.geometry import square_center
from chess_move_finder.overlay.locator import BoardRect

# An 800x800 board at the screen origin -> 100px cells, centres at 50, 150, ... 750.
RECT = BoardRect(x=0.0, y=0.0, w=800.0, h=800.0)


def test_white_bottom_corners() -> None:
    assert square_center(RECT, chess.A1, white_bottom=True) == (50.0, 750.0)   # bottom-left
    assert square_center(RECT, chess.H1, white_bottom=True) == (750.0, 750.0)  # bottom-right
    assert square_center(RECT, chess.A8, white_bottom=True) == (50.0, 50.0)    # top-left
    assert square_center(RECT, chess.H8, white_bottom=True) == (750.0, 50.0)   # top-right


def test_black_bottom_is_flipped() -> None:
    # Board flipped: a1 sits top-right, h8 bottom-left.
    assert square_center(RECT, chess.A1, white_bottom=False) == (750.0, 50.0)
    assert square_center(RECT, chess.H8, white_bottom=False) == (50.0, 750.0)


def test_centres_account_for_board_offset() -> None:
    rect = BoardRect(x=200.0, y=100.0, w=400.0, h=400.0)  # 50px cells
    assert square_center(rect, chess.A1, white_bottom=True) == (225.0, 475.0)
