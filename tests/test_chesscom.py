"""Tests for parsing chess.com game-socket frames into snapshots."""

import base64
import json
from typing import Any

from chess_move_finder.tracking.chesscom import parse_frame


def _binary_frame(obj: dict[str, Any]) -> str:
    """Build a frame like chess.com's: a binary header + JSON, base64-encoded."""
    body = json.dumps(obj).encode()
    return base64.b64encode(b"\x00\x00\x01\x28" + body).decode()


def test_parses_game_start_frame() -> None:
    frame = _binary_frame(
        {
            "id": "d5c6719e",
            "clocks": [600000, 600000],
            "moves": [],
            "actions": [["abort", "draw"], ["abort", "draw"]],
        }
    )
    snap = parse_frame(frame)
    assert snap is not None
    assert snap.game_id == "d5c6719e"
    assert snap.moves == []
    assert snap.clocks == [600000, 600000]
    assert snap.actions[0] == ["abort", "draw"]


def test_parses_moves_as_tcn_clock_pairs() -> None:
    frame = _binary_frame(
        {"id": "g1", "clocks": [597545, 598308], "moves": [["mC", 597545], ["0K", 598308]]}
    )
    snap = parse_frame(frame)
    assert snap is not None
    assert snap.moves == ["e2e4", "e7e5"]


def test_parses_plain_json_text_frame() -> None:
    snap = parse_frame('{"id": "g2", "moves": "mC0K"}')
    assert snap is not None
    assert snap.moves == ["e2e4", "e7e5"]


def test_ignores_heartbeat_frame() -> None:
    assert parse_frame("AAAAAAwAAAAAAAAAAAA=") is None


def test_ignores_non_game_frame() -> None:
    assert parse_frame('{"updatedAt": "2026-06-07T21:38:28.231Z"}') is None
    assert parse_frame("not base64 nor json !!") is None
