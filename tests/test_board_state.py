"""Tests for reading the live board state (FEN + orientation) from the page."""

import chess

from chess_move_finder.tracking.board_state import parse_live_game


def test_parse_live_game_reads_fen_and_white() -> None:
    state = {"path": "/game/live/123", "fen": chess.STARTING_FEN, "flipped": False}
    live = parse_live_game(state)
    assert live is not None
    assert live.board.fen() == chess.STARTING_FEN
    assert live.user_color == chess.WHITE


def test_parse_live_game_flipped_is_black() -> None:
    fen = "rnbqkbnr/pppppppp/8/8/8/2N5/PPPPPPPP/R1BQKBNR b KQkq - 1 1"
    live = parse_live_game({"fen": fen, "flipped": True})
    assert live is not None
    assert live.user_color == chess.BLACK
    assert live.board.turn == chess.BLACK


def test_parse_live_game_without_fen_is_none() -> None:
    assert parse_live_game({"path": "/home"}) is None
    assert parse_live_game({"fen": None}) is None
    assert parse_live_game({"fen": ""}) is None


def test_parse_live_game_rejects_bad_fen() -> None:
    assert parse_live_game({"fen": "not a fen", "flipped": False}) is None
