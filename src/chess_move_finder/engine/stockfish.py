"""Thin synchronous wrapper around a UCI engine (Stockfish), via python-chess.

Holds one long-lived engine subprocess and answers "best move for this position"
with a fixed think time. Kept deliberately simple: the caller owns when to ask
(only on the player's turn) and the lifecycle (:meth:`close` on shutdown).
"""

from __future__ import annotations

import contextlib
import subprocess

import chess
import chess.engine

# Stockfish is a console program; on Windows this stops it opening a console window.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class StockfishEngine:
    """A running UCI engine that returns the best move for a board."""

    def __init__(
        self, path: str, movetime_ms: int = 200, threads: int = 1, hash_mb: int = 16
    ) -> None:
        self._engine = chess.engine.SimpleEngine.popen_uci(path, creationflags=_NO_WINDOW)
        self._limit = chess.engine.Limit(time=movetime_ms / 1000.0)
        # Apply only the options the engine actually exposes, so a non-Stockfish
        # or stripped build doesn't raise on an unknown option.
        wanted = {"Threads": threads, "Hash": hash_mb}
        supported = {k: v for k, v in wanted.items() if k in self._engine.options}
        if supported:
            self._engine.configure(supported)

    def best_move(self, board: chess.Board) -> chess.Move | None:
        """The engine's chosen move for ``board`` (``None`` if the game is over)."""
        return self._engine.play(board, self._limit).move

    def close(self) -> None:
        with contextlib.suppress(chess.engine.EngineError):
            self._engine.quit()
