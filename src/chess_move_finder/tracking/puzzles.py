"""Read chess.com puzzles (Rated Puzzles) from your own Chrome.

Unlike live games - which stream moves over a WebSocket (see :mod:`.chesscom`) -
puzzles arrive as a single HTTP RPC response (``GetNextRated``) that carries the
*whole* solution up front, and there is **no per-move signal** while you solve
(validation is client-side until the solution is submitted).

So helping step-by-step needs two pieces:

* :func:`parse_puzzle` turns the ``GetNextRated`` JSON body into a :class:`Puzzle`
  (start FEN, the solution as UCI moves, and which colour you play);
* :class:`PuzzleSolver` replays that solution and, given the *live* board position
  (read from the page DOM, see :data:`READ_PIECES_JS` / :func:`placement_fen`),
  works out how far you've got and which move to show next.

The first move of a puzzle's solution is the opponent's auto-played setup move;
your moves alternate after it. No engine is needed - the solution is given.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass

import chess

# Substring identifying the puzzle-loading RPC, used to filter HTTP responses.
NEXT_PUZZLE_URL = "GetNextRated"

# chess.com promotion enum (e.g. "PIECE_TYPE_QUEEN") -> python-chess piece letter.
_PROMOTION = {"QUEEN": "q", "ROOK": "r", "BISHOP": "b", "KNIGHT": "n"}
_FEN_TAG = re.compile(r'\[FEN\s+"([^"]+)"\]')
_SQUARE_CLASS = re.compile(r"^square-([1-8])([1-8])$")
_PIECE_CLASS = re.compile(r"^([wb])([pnbrqk])$")


@dataclass(frozen=True)
class Puzzle:
    """A puzzle: where to start, the full solution, and the side you play."""

    puzzle_id: str
    start_fen: str
    solution: list[str]  # UCI moves, starting with the opponent's setup move
    user_color: str  # "white" or "black"


def _square(raw: str) -> str:
    # "SQUARE_G8" -> "g8".
    return raw.rsplit("_", 1)[-1].lower()


def _uci(move: dict) -> str | None:
    src, dst = move.get("from"), move.get("to")
    if not isinstance(src, str) or not isinstance(dst, str):
        return None
    promo = move.get("promotion")
    suffix = _PROMOTION.get(promo.rsplit("_", 1)[-1], "") if isinstance(promo, str) else ""
    return _square(src) + _square(dst) + suffix


def parse_puzzle(body: str) -> Puzzle | None:
    """Parse a ``GetNextRated`` JSON body into a :class:`Puzzle` (or None if bad)."""
    try:
        puzzle = json.loads(body)["userPuzzle"]["puzzle"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

    fen = _start_fen(puzzle)
    if fen is None:
        return None

    raw_moves = puzzle.get("moves")
    if not isinstance(raw_moves, list):
        return None
    solution: list[str] = []
    for item in raw_moves:
        move = item.get("move") if isinstance(item, dict) else None
        uci = _uci(move) if isinstance(move, dict) else None
        if uci is None:
            return None
        solution.append(uci)

    position = puzzle.get("userPosition", "")
    user_color = "black" if "BLACK" in position else "white"
    puzzle_id = str(puzzle.get("legacyPuzzleId", ""))
    return Puzzle(puzzle_id, fen, solution, user_color)


def _start_fen(puzzle: dict) -> str | None:
    pgn = puzzle.get("pgn")
    if isinstance(pgn, str):
        match = _FEN_TAG.search(pgn)
        if match:
            return match.group(1)
    fen4 = puzzle.get("fen4")  # placement/side/castling/ep, without move counters
    if isinstance(fen4, str) and fen4:
        return f"{fen4} 0 1"
    return None


def placement_fen(class_names: list[str]) -> str | None:
    """Build a board-placement FEN (the part before the first space) from the DOM.

    ``class_names`` is each piece element's class string, e.g. ``"piece br
    square-88"``. Returns None if nothing parseable is found.
    """
    grid = [["" for _ in range(8)] for _ in range(8)]  # grid[rank-1][file-1]
    found = False
    for classes in class_names:
        square = piece = None
        for token in classes.split():
            sq = _SQUARE_CLASS.match(token)
            if sq:
                square = (int(sq.group(2)) - 1, int(sq.group(1)) - 1)  # (rank, file)
                continue
            pc = _PIECE_CLASS.match(token)
            if pc:
                letter = pc.group(2)
                piece = letter.upper() if pc.group(1) == "w" else letter
        if square is not None and piece is not None:
            grid[square[0]][square[1]] = piece
            found = True
    if not found:
        return None

    rows = []
    for rank in range(7, -1, -1):  # FEN lists rank 8 first
        row, empty = "", 0
        for file in range(8):
            cell = grid[rank][file]
            if cell:
                if empty:
                    row += str(empty)
                    empty = 0
                row += cell
            else:
                empty += 1
        if empty:
            row += str(empty)
        rows.append(row)
    return "/".join(rows)


class PuzzleSolver:
    """Tracks progress through a puzzle and yields the next move to show.

    Thread-safe: :meth:`load` (called from the CDP thread when a puzzle arrives)
    and :meth:`suggestion_for` (called from the poller thread) can run concurrently.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Snapshot of the loaded puzzle: boards[k]/placements[k] = position after k
        # plies; solution[k] = the UCI move played from position k.
        self._boards: list[chess.Board] = []
        self._placements: list[str] = []
        self._solution: list[str] = []
        self._user_color: chess.Color = chess.WHITE
        self._puzzle_id = ""

    def load(self, puzzle: Puzzle) -> bool:
        """Replay a puzzle's solution; return False if its data is inconsistent."""
        try:
            board = chess.Board(puzzle.start_fen)
        except ValueError:
            return False
        boards = [board.copy()]
        for uci in puzzle.solution:
            try:
                move = chess.Move.from_uci(uci)
            except ValueError:
                return False
            if move not in board.legal_moves:
                return False
            board.push(move)
            boards.append(board.copy())
        with self._lock:
            self._boards = boards
            self._placements = [b.board_fen() for b in boards]
            self._solution = list(puzzle.solution)
            self._user_color = chess.BLACK if puzzle.user_color == "black" else chess.WHITE
            self._puzzle_id = puzzle.puzzle_id
        return True

    def clear(self) -> None:
        with self._lock:
            self._boards = []
            self._placements = []
            self._solution = []

    def is_loaded(self) -> bool:
        """Whether a puzzle is currently being tracked."""
        with self._lock:
            return bool(self._placements)

    def suggestion_for(
        self, live_placement: str
    ) -> tuple[chess.Board, chess.Move | None] | None:
        """Map the live board to the solution and return the move to display.

        * ``None`` - the position matches no known ply (transient/mid-animation, or
          no puzzle loaded): leave the overlay unchanged.
        * ``(board, move)`` - it's your turn: show ``move``.
        * ``(board, None)`` - it's the opponent's turn or the puzzle is solved: clear.
        """
        with self._lock:
            placements = self._placements
            boards = self._boards
            solution = self._solution
            user_color = self._user_color
        matches = [i for i, p in enumerate(placements) if p == live_placement]
        if not matches:
            return None
        ply = max(matches)  # if a position repeats, prefer the most-progressed one
        board = boards[ply]
        if ply < len(solution) and board.turn == user_color:
            return board, chess.Move.from_uci(solution[ply])
        return board, None
