"""Smoke tests: the package imports and exposes a version."""

import chess_move_finder


def test_version() -> None:
    assert chess_move_finder.__version__
