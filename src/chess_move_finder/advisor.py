"""Turn tracked game events into best-move suggestions.

Rebuilds the game on a :class:`chess.Board` from the move history reported by the
tracker (so the FEN is always available), and whenever it becomes the player's
turn asks for the best move. It resets on every game start, so it keeps working
across rematches and relaunched games.

It's engine-agnostic: it's handed a ``best_move`` callable, so it can be unit
tested without a real Stockfish.
"""

from __future__ import annotations

from collections.abc import Callable

import chess

from .tracking.chesscom import GameSnapshot

# Given the position to move in, return the best move (or None if none/over).
BestMoveFn = Callable[[chess.Board], "chess.Move | None"]
# Called with the position and the suggested move whenever it's the player's turn.
SuggestionCallback = Callable[[chess.Board, "chess.Move | None"], None]


def _parse_color(color: str | None) -> chess.Color | None:
    if color == "white":
        return chess.WHITE
    if color == "black":
        return chess.BLACK
    return None


class GameAdvisor:
    """Reconstructs the game and suggests a move whenever it's the player's turn."""

    def __init__(self, best_move: BestMoveFn, on_suggestion: SuggestionCallback) -> None:
        self._best_move = best_move
        self._on_suggestion = on_suggestion
        self._board = chess.Board()
        self._player: chess.Color | None = None

    def on_game_start(self, snapshot: GameSnapshot, color: str | None) -> None:
        """Start (or restart) tracking a game; suggest at once if we open as White."""
        self._board = chess.Board()
        self._player = _parse_color(color)
        # A fresh game where we have the move (we're White): suggest immediately.
        if not snapshot.moves and self._is_player_turn():
            self._suggest()

    def on_move(self, uci: str) -> None:
        """Apply a played move; suggest if it's now our turn."""
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return
        if move not in self._board.legal_moves:
            return  # desync guard; with the full move history this shouldn't happen
        self._board.push(move)
        if self._is_player_turn():
            self._suggest()

    def _is_player_turn(self) -> bool:
        return self._player is not None and self._board.turn == self._player

    def _suggest(self) -> None:
        self._on_suggestion(self._board, self._best_move(self._board))
