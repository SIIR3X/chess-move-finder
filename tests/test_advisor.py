"""Tests for the engine-agnostic game advisor."""

import chess

from chess_move_finder.advisor import GameAdvisor
from chess_move_finder.tracking.chesscom import GameSnapshot

Suggestion = tuple[str, str | None]  # (fen of position to move, suggested move uci)


def _setup(
    color: str | None, moves_at_start: list[str] | None = None
) -> tuple[GameAdvisor, list[Suggestion]]:
    suggestions: list[Suggestion] = []
    advisor = GameAdvisor(
        best_move=lambda board: next(iter(board.legal_moves), None),
        on_suggestion=lambda board, move: suggestions.append(
            (board.fen(), move.uci() if move else None)
        ),
    )
    advisor.on_game_start(GameSnapshot(game_id="g", moves=moves_at_start or []), color)
    return advisor, suggestions


def test_suggests_immediately_when_player_is_white() -> None:
    _advisor, suggestions = _setup("white")
    assert len(suggestions) == 1
    assert suggestions[0][0] == chess.Board().fen()  # the starting position


def test_no_suggestion_at_start_when_player_is_black() -> None:
    _advisor, suggestions = _setup("black")
    assert suggestions == []


def test_suggests_only_when_it_becomes_our_turn() -> None:
    advisor, suggestions = _setup("black")  # we are Black
    advisor.on_move("e2e4")  # opponent (White) plays -> our turn -> suggest
    assert len(suggestions) == 1
    advisor.on_move("e7e5")  # our move -> opponent's turn -> no suggest
    assert len(suggestions) == 1


def test_unknown_color_yields_no_suggestions() -> None:
    advisor, suggestions = _setup(None)
    advisor.on_move("e2e4")
    advisor.on_move("e7e5")
    assert suggestions == []


def test_ignores_illegal_move() -> None:
    advisor, suggestions = _setup("black")
    advisor.on_move("e2e5")  # not a legal move
    assert suggestions == []


def test_restart_resets_board_and_works_again() -> None:
    advisor, suggestions = _setup("white")  # suggestion for the start position
    advisor.on_move("e2e4")  # our move -> Black to move, no suggestion

    # A new game where we're Black now; the old board must be forgotten.
    advisor.on_game_start(GameSnapshot(game_id="g2", moves=[]), "black")
    advisor.on_move("d2d4")  # opponent (White) -> our turn -> suggest
    board = chess.Board(suggestions[-1][0])
    assert board.turn == chess.BLACK
    assert board.fullmove_number == 1
    assert board.piece_at(chess.D4) is not None  # the new game's move
    assert board.piece_at(chess.E4) is None  # the old game's move is gone


def test_reconnect_midgame_suggests_when_it_is_our_turn() -> None:
    # Game start arrives with moves already played (we attached late); the moves
    # then stream in. We're White, so after Black's reply it's our turn.
    # Non-empty moves at start -> no immediate suggestion for the start position.
    advisor, suggestions = _setup("white", moves_at_start=["a", "b"])
    assert suggestions == []
    advisor.on_move("e2e4")  # our move
    advisor.on_move("e7e5")  # opponent -> our turn -> suggest
    assert len(suggestions) == 1
