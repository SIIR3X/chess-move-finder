"""Tests for chess.com puzzle parsing, board reading, and step-by-step solving."""

import json

import chess

from chess_move_finder.tracking.puzzles import (
    PuzzleSolver,
    parse_puzzle,
    placement_fen,
)

# A trimmed but faithful GetNextRated body: a real mate-in-3 puzzle. The first
# move (g8h7) is the opponent's auto-played setup; the user (Black) plays the rest.
_START_FEN = "r2qkbQ1/ppp4p/8/8/4n3/1P6/P1P1PPPP/RN2KBNR w KQq - 0 1"
_SOLUTION = ["g8h7", "f8b4", "c2c3", "b4c3", "b1c3", "d8d2"]


def _move(uci: str) -> dict:
    return {"move": {"from": f"SQUARE_{uci[:2].upper()}", "to": f"SQUARE_{uci[2:4].upper()}"}}


def _body() -> str:
    return json.dumps(
        {
            "userPuzzle": {
                "puzzle": {
                    "legacyPuzzleId": "1361282",
                    "pgn": f'[FEN "{_START_FEN}"]\n[PuzzleGoals "Checkmate"]\n\n1. Qxh7',
                    "moves": [_move(u) for u in _SOLUTION],
                    "userPosition": "COLOR_BLACK",
                    "fen4": "r2qkbQ1/ppp4p/8/8/4n3/1P6/P1P1PPPP/RN2KBNR w KQq -",
                }
            }
        }
    )


def _classes_for(board: chess.Board) -> list[str]:
    """Build the page's piece CSS classes from a board (inverse of placement_fen)."""
    out = []
    for square, piece in board.piece_map().items():
        file = chess.square_file(square) + 1
        rank = chess.square_rank(square) + 1
        color = "w" if piece.color == chess.WHITE else "b"
        out.append(f"piece {color}{piece.symbol().lower()} square-{file}{rank}")
    return out


def _placement_after(plies: int) -> str:
    board = chess.Board(_START_FEN)
    for uci in _SOLUTION[:plies]:
        board.push(chess.Move.from_uci(uci))
    return board.board_fen()


def test_parse_puzzle_extracts_fen_solution_and_color() -> None:
    puzzle = parse_puzzle(_body())
    assert puzzle is not None
    assert puzzle.start_fen == _START_FEN
    assert puzzle.solution == _SOLUTION
    assert puzzle.user_color == "black"
    assert puzzle.puzzle_id == "1361282"


def test_parse_puzzle_handles_promotion() -> None:
    body = json.dumps(
        {
            "userPuzzle": {
                "puzzle": {
                    "fen4": "8/P7/8/8/8/8/8/k6K w - -",
                    "moves": [
                        {
                            "move": {
                                "from": "SQUARE_A7",
                                "to": "SQUARE_A8",
                                "promotion": "PIECE_QUEEN",
                            }
                        }
                    ],
                    "userPosition": "COLOR_WHITE",
                }
            }
        }
    )
    puzzle = parse_puzzle(body)
    assert puzzle is not None
    assert puzzle.solution == ["a7a8q"]


def test_parse_puzzle_rejects_garbage() -> None:
    assert parse_puzzle("not json") is None
    assert parse_puzzle('{"unexpected": true}') is None


def test_placement_fen_matches_board_fen() -> None:
    board = chess.Board(_START_FEN)
    assert placement_fen(_classes_for(board)) == board.board_fen()


def test_placement_fen_empty_is_none() -> None:
    assert placement_fen([]) is None
    assert placement_fen(["piece", "highlight square-11"]) is None


def test_solver_shows_each_user_move_in_turn() -> None:
    solver = PuzzleSolver()
    assert solver.load(parse_puzzle(_body()))

    # The user is Black; their moves are the odd plies (after the opponent's reply).
    for ply, expected in [(1, "f8b4"), (3, "b4c3"), (5, "d8d2")]:
        result = solver.suggestion_for(_placement_after(ply))
        assert result is not None
        _board, move = result
        assert move is not None and move.uci() == expected


def test_solver_clears_on_opponent_turn_and_when_solved() -> None:
    solver = PuzzleSolver()
    solver.load(parse_puzzle(_body()))

    # Opponent's turn (start, before the setup move): nothing to suggest.
    board, move = solver.suggestion_for(_placement_after(0))
    assert move is None
    # Whole solution played: puzzle solved, clear.
    board, move = solver.suggestion_for(_placement_after(6))
    assert move is None


def test_solver_ignores_unknown_position() -> None:
    solver = PuzzleSolver()
    solver.load(parse_puzzle(_body()))
    assert solver.suggestion_for(chess.Board().board_fen()) is None


def test_solver_without_puzzle_ignores() -> None:
    assert PuzzleSolver().suggestion_for(chess.Board().board_fen()) is None
