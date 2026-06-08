"""Decode chess.com's TCN move encoding into UCI.

chess.com doesn't transmit moves as UCI or SAN over its game socket; it uses a
compact private encoding called **TCN** (Transcode Notation): two characters per
half-move. The first character encodes the origin square (0-63), the second the
destination - unless the move is a promotion or a piece drop, which are folded
into the second/first character respectively. This module turns a TCN string
into a list of UCI strings (e.g. ``"e2e4"``, ``"e7e8q"``), which python-chess
understands directly.

A square index ``k`` maps to file ``k % 8`` (0 = a) and rank ``k // 8 + 1``
(0 = rank 1), so index 0 is a1 and index 63 is h8.
"""

from __future__ import annotations

# chess.com's TCN alphabet: a character's position in this string *is* its value.
_TCN_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!?{~}(^)[_]@#$%^&*+-=."
# Pieces a pawn can promote to, in the order TCN indexes them.
_PROMOTION_PIECES = "qnrbkp"
# Index past which a destination character carries a promotion piece.
_PROMOTION_BASE = 64
# Index past which an origin character is a drop (Crazyhouse/Bughouse), not a square.
_DROP_BASE = 75


def _square_name(index: int) -> str:
    return "abcdefgh"[index % 8] + str(index // 8 + 1)


def decode_tcn(tcn: str) -> list[str]:
    """Decode a TCN string (any number of half-moves) into a list of UCI moves.

    Drops are skipped (they don't occur in standard chess), and a trailing odd
    character - should the stream ever be truncated mid-move - is ignored.
    """
    moves: list[str] = []
    for i in range(0, len(tcn) - 1, 2):
        origin = _TCN_CHARS.index(tcn[i])
        target = _TCN_CHARS.index(tcn[i + 1])
        promotion = ""
        if target > _PROMOTION_BASE - 1:
            # Promotion: the piece is folded into the target character, and the
            # real destination square is recovered relative to the origin.
            promotion = _PROMOTION_PIECES[(target - _PROMOTION_BASE) // 3]
            step = -8 if origin < 16 else 8
            target = origin + step + ((target - _PROMOTION_BASE) % 3 - 1)
        if origin > _DROP_BASE:
            continue  # piece drop - not a board-square move, ignore
        moves.append(_square_name(origin) + _square_name(target) + promotion)
    return moves
