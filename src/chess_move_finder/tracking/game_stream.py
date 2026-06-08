"""Derive game-start and move events from a stream of chess.com frames.

Two frame kinds are interleaved on the socket:

* **matchmaking tickets**, which state the player's colour for an upcoming game
  (see :mod:`.matcher`) - these arrive just before the game does;
* **game-state frames**, which carry the full move list (see :mod:`.chesscom`).

Each game-state frame holds the *whole* move list, so following a game is just a
matter of diffing successive snapshots: a change of ``game_id`` is a new game, and
a longer ``moves`` list (with the previous one as its prefix) means moves were
played. Tickets are remembered by game id so that, when a game starts, its colour
is already known.
"""

from __future__ import annotations

from collections.abc import Callable

from .chesscom import GameSnapshot, parse_frame
from .matcher import parse_ticket

# (snapshot, player colour as "white"/"black"/None if not seen).
GameStartCallback = Callable[[GameSnapshot, str | None], None]
MoveCallback = Callable[[str], None]


class GameStream:
    """Feed raw frames in; get :func:`on_game_start` / :func:`on_move` callbacks out."""

    def __init__(self, on_game_start: GameStartCallback, on_move: MoveCallback) -> None:
        self._on_game_start = on_game_start
        self._on_move = on_move
        self._game_id: str | None = None
        self._moves: list[str] = []
        self._colors: dict[str, str] = {}  # game_id -> the player's colour

    def feed(self, payload: str) -> None:
        """Process one raw frame, firing events for anything new."""
        ticket = parse_ticket(payload)
        if ticket is not None:
            self._colors[ticket.game_id] = ticket.color
            return
        snapshot = parse_frame(payload)
        if snapshot is None:
            return
        if snapshot.game_id != self._game_id:
            self._game_id = snapshot.game_id
            self._moves = []
            self._on_game_start(snapshot, self._colors.get(snapshot.game_id))
        self._emit_new_moves(snapshot.moves)

    def _emit_new_moves(self, moves: list[str]) -> None:
        # Only trust a list that extends what we already have (guards against a
        # stray out-of-order frame); otherwise wait for the next consistent one.
        if len(moves) <= len(self._moves) or moves[: len(self._moves)] != self._moves:
            return
        for uci in moves[len(self._moves) :]:
            self._on_move(uci)
        self._moves = moves
