"""Read the player's colour from chess.com's matchmaking frames.

When a game is found, chess.com sends a *matcher ticket* on its client socket - a
Socket.IO-style text frame like::

    47[20,"matcher/tickets/users/:me","<seq>","<gzip-base64>",1]

The last string element is a gzip-compressed JSON ticket that states, explicitly,
the colour the user was given, their user id, and the game it belongs to::

    {"userId": "...", "color": "white", "game": {"id": "...", "players": [...]}}

The game-state frames themselves carry no identity (only per-side connection
quality), so this ticket is *the* reliable source of the player's colour. It
arrives just before the game starts.

:func:`parse_ticket` turns one raw frame into a :class:`MatchTicket`, or returns
``None`` if the frame isn't a matcher ticket.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import json
from dataclasses import dataclass
from typing import Any

# Substring identifying the matcher-ticket channel within the frame.
_MATCHER_CHANNEL = "matcher/tickets"


@dataclass(frozen=True)
class MatchTicket:
    """The player's assignment for one game, from a matchmaking ticket."""

    game_id: str
    color: str       # "white" or "black"
    user_id: str


def parse_ticket(payload: str) -> MatchTicket | None:
    """Decode one frame into a :class:`MatchTicket`, or ``None`` if it isn't one."""
    array = _parse_socketio_array(payload)
    if array is None:
        return None
    if not any(isinstance(item, str) and _MATCHER_CHANNEL in item for item in array):
        return None
    ticket = _decompress_payload(array)
    if not isinstance(ticket, dict):
        return None
    color = ticket.get("color")
    user_id = ticket.get("userId")
    game = ticket.get("game")
    if not isinstance(color, str) or not isinstance(user_id, str) or not isinstance(game, dict):
        return None
    game_id = game.get("id")
    if not isinstance(game_id, str):
        return None
    return MatchTicket(game_id=game_id, color=color, user_id=user_id)


def _parse_socketio_array(payload: str) -> list[Any] | None:
    """Parse a ``<digits>[...]`` Socket.IO frame into its JSON array, or ``None``."""
    start = payload.find("[")
    if start < 0:
        return None
    prefix = payload[:start]
    if prefix and not prefix.isdigit():
        return None
    try:
        array = json.loads(payload[start:])
    except (json.JSONDecodeError, ValueError):
        return None
    return array if isinstance(array, list) else None


def _decompress_payload(array: list[Any]) -> Any:
    """Return the first array element that gunzips into a JSON object, or ``None``."""
    for item in array:
        if not isinstance(item, str):
            continue
        try:
            raw = gzip.decompress(base64.b64decode(item))
        except (binascii.Error, OSError, EOFError, ValueError):
            continue
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return None
