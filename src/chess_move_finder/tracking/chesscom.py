"""Parse chess.com game-socket frames into structured game snapshots.

chess.com sends **binary** WebSocket frames; the DevTools Protocol delivers them
base64-encoded, with a short binary header in front of a JSON body. The frames we
care about describe the live game: a JSON object with an ``id`` and a ``moves``
list, where each entry is a ``[tcn, clock]`` pair (``tcn`` being one TCN
half-move). Other frames - heartbeats, matchmaking, latency echoes - carry no such
object.

:func:`parse_frame` turns one raw payload into a :class:`GameSnapshot`, or returns
``None`` if the frame isn't a game-state frame.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import Any

from .tcn import decode_tcn


@dataclass(frozen=True)
class GameSnapshot:
    """The state of a chess.com game as carried by one frame."""

    game_id: str
    moves: list[str]                                          # half-moves in UCI, from the start
    clocks: list[int] = field(default_factory=list)          # ms remaining, [white, black]
    actions: list[Any] = field(default_factory=list)         # per-side available actions


def parse_frame(payload: str) -> GameSnapshot | None:
    """Decode one frame payload into a :class:`GameSnapshot`, or ``None``."""
    data = _parse_payload(payload)
    if not isinstance(data, dict) or "id" not in data or "moves" not in data:
        return None
    game_id = data["id"]
    if not isinstance(game_id, str):
        return None
    moves = decode_tcn(_moves_to_tcn(data["moves"]))
    clocks = [c for c in data.get("clocks", []) if isinstance(c, int)]
    actions = data.get("actions")
    return GameSnapshot(
        game_id=game_id,
        moves=moves,
        clocks=clocks,
        actions=actions if isinstance(actions, list) else [],
    )


def _moves_to_tcn(value: Any) -> str:
    """Concatenate a ``moves`` value into one TCN string.

    Handles the live format (list of ``[tcn, clock]`` pairs) as well as a plain
    TCN string or a list of TCN strings.
    """
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for entry in value:
        if isinstance(entry, str):
            parts.append(entry)
        elif isinstance(entry, list) and entry and isinstance(entry[0], str):
            parts.append(entry[0])  # [tcn, clock] pair
    return "".join(parts)


def _parse_payload(payload: str) -> Any:
    """Decode a frame payload into a JSON value, or ``None`` if it carries none.

    Handles both text frames (plain JSON) and binary frames (base64, where a short
    binary header precedes the JSON body - we parse from the first ``{``).
    """
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None
    text = raw.decode("utf-8", errors="replace")
    start = text.find("{")
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, start)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj
