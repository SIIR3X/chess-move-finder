"""Tests for the calibration rectangle helpers (persistence + corner math)."""

from pathlib import Path

from chess_move_finder.overlay.calibration_store import (
    load_calibration,
    rect_from_corners,
    save_calibration,
)
from chess_move_finder.overlay.locator import BoardRect


def test_rect_from_corners_normalizes_any_order() -> None:
    rect = rect_from_corners(300, 200, 100, 50)  # bottom-right clicked first
    assert (rect.x, rect.y, rect.w, rect.h) == (100, 50, 200, 150)


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "cal.json"
    save_calibration(BoardRect(10, 20, 400, 400), path)
    assert load_calibration(path) == BoardRect(10.0, 20.0, 400.0, 400.0)


def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert load_calibration(tmp_path / "absent.json") is None
