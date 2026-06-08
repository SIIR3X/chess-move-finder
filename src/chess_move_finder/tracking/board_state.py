"""Read the live board state from the page in one Runtime.evaluate round-trip.

A single read feeds both kinds of assistance:

* **puzzles** - the piece placement (``pieces``), matched against the known
  solution (see :mod:`.puzzles`);
* **live games** - the board's own ``fen`` (full, with the side to move) plus the
  orientation (``flipped`` = you play Black), used to *bootstrap* a suggestion when
  the tool is activated mid-game.

The mid-game case can't be served by the move stream alone: the player's colour is
only announced before the game (the matchmaking ticket), and a game-state frame is
only pushed on the *next* move - so an already-running, idle-on-your-turn game
would otherwise go unhelped. Reading the board sidesteps both. The URL ``path``
lets the caller tell the puzzle and game contexts apart.

This only *reads* the page (it never injects), consistent with the rest of the app.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import chess

# Returns { path, pieces?, fen?, flipped? }. ``pieces`` are the piece elements'
# CSS classes (e.g. "piece br square-88"); ``fen`` is the board's own full FEN
# (null if this board exposes no game, e.g. some non-game pages).
READ_BOARD_JS = (
    "(() => {"
    " const path = location.pathname;"
    " const b = document.querySelector('wc-chess-board')"
    " || document.querySelector('chess-board');"
    " if (!b) return { path };"
    " const pieces = [...b.querySelectorAll('.piece')].map(p => p.className);"
    " let fen = null;"
    " try { if (b.game && b.game.getFEN) fen = b.game.getFEN(); } catch (e) {}"
    " return { path, pieces, fen, flipped: b.classList.contains('flipped') }; })()"
)


@dataclass(frozen=True)
class LiveGame:
    """The current live position and which colour the user is playing."""

    board: chess.Board
    user_color: chess.Color


def parse_live_game(state: dict[str, Any]) -> LiveGame | None:
    """Turn a board-state read into a :class:`LiveGame` (or None if not a game)."""
    fen = state.get("fen")
    if not isinstance(fen, str) or not fen:
        return None
    try:
        board = chess.Board(fen)
    except ValueError:
        return None
    # chess.com orients your own pieces at the bottom; a flipped board => you're Black.
    color = chess.BLACK if state.get("flipped") else chess.WHITE
    return LiveGame(board, color)
