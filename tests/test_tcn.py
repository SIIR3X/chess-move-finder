"""Tests for the chess.com TCN move decoder."""

import chess

from chess_move_finder.tracking.tcn import decode_tcn


def test_decodes_single_move() -> None:
    assert decode_tcn("mC") == ["e2e4"]


def test_decodes_move_sequence() -> None:
    # 1. e4 e5 2. Nf3
    assert decode_tcn("mC0Kgv") == ["e2e4", "e7e5", "g1f3"]


def test_decodes_queen_promotion() -> None:
    assert decode_tcn("0~") == ["e7e8q"]


def test_ignores_trailing_odd_character() -> None:
    assert decode_tcn("mC0") == ["e2e4"]


def test_decoded_moves_are_legal_in_sequence() -> None:
    board = chess.Board()
    for uci in decode_tcn("mC0Kgv"):
        move = chess.Move.from_uci(uci)
        assert move in board.legal_moves
        board.push(move)
