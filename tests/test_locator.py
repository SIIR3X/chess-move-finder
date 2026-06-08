"""Tests for mapping a page measurement to the board's screen rectangle."""

from chess_move_finder.overlay.locator import screen_board_rect


def _measurement() -> dict[str, float]:
    # Board at (100,50) sized 400x400 in a window at screen (10,20) with 80px chrome.
    return {"x": 100, "y": 50, "w": 400, "h": 400, "sx": 10, "sy": 20, "ch": 80, "dpr": 1}


def test_maps_board_into_screen_space() -> None:
    rect = screen_board_rect(_measurement())
    assert rect is not None
    assert (rect.x, rect.y, rect.w, rect.h) == (110, 150, 400, 400)


def test_applies_offset_and_scale() -> None:
    rect = screen_board_rect(_measurement(), offset_x=5, offset_y=-3, scale=2.0)
    assert rect is not None
    assert (rect.x, rect.y, rect.w, rect.h) == (115, 147, 800, 800)


def test_returns_none_when_no_board() -> None:
    assert screen_board_rect(None) is None
    assert screen_board_rect({"x": 0}) is None  # missing keys
    assert screen_board_rect({**_measurement(), "w": 0}) is None  # degenerate
