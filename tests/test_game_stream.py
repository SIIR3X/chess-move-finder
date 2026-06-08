"""Tests for turning a frame stream into game-start / move events."""

import base64
import gzip
import json

from chess_move_finder.tracking.chesscom import GameSnapshot
from chess_move_finder.tracking.game_stream import GameStream


def _frame(game_id: str, moves: list[str]) -> str:
    pairs = [[m, 0] for m in moves]  # [tcn, clock] like the live format
    body = json.dumps({"id": game_id, "moves": pairs, "clocks": [600000, 600000]}).encode()
    return base64.b64encode(b"\x00\x00\x01\x28" + body).decode()


def _matcher_frame(game_id: str, color: str) -> str:
    ticket = {"userId": "u", "color": color, "game": {"id": game_id}}
    blob = base64.b64encode(gzip.compress(json.dumps(ticket).encode())).decode()
    return f'47[20,"matcher/tickets/users/:me","seq","{blob}",1]'


def _collect() -> tuple[GameStream, list[tuple[str, str]]]:
    events: list[tuple[str, str]] = []
    stream = GameStream(
        on_game_start=lambda s, _color: events.append(("start", s.game_id)),
        on_move=lambda uci: events.append(("move", uci)),
    )
    return stream, events


def test_fires_game_start_once_per_game() -> None:
    stream, events = _collect()
    stream.feed(_frame("g1", []))
    stream.feed(_frame("g1", []))  # resend, no new event
    assert events == [("start", "g1")]


def test_emits_only_newly_played_moves() -> None:
    stream, events = _collect()
    stream.feed(_frame("g1", []))
    stream.feed(_frame("g1", ["mC"]))        # e2e4
    stream.feed(_frame("g1", ["mC"]))        # resend
    stream.feed(_frame("g1", ["mC", "0K"]))  # e7e5 added
    assert events == [("start", "g1"), ("move", "e2e4"), ("move", "e7e5")]


def test_a_new_game_id_restarts_tracking() -> None:
    stream, events = _collect()
    stream.feed(_frame("g1", ["mC", "0K"]))
    stream.feed(_frame("g2", []))            # new game
    stream.feed(_frame("g2", ["lB"]))        # d2d4
    assert events == [
        ("start", "g1"),
        ("move", "e2e4"),
        ("move", "e7e5"),
        ("start", "g2"),
        ("move", "d2d4"),
    ]


def test_game_start_reports_color_from_preceding_ticket() -> None:
    starts: list[tuple[str, str | None]] = []
    stream = GameStream(
        on_game_start=lambda s, color: starts.append((s.game_id, color)),
        on_move=lambda _uci: None,
    )
    stream.feed(_matcher_frame("g1", "black"))  # ticket arrives first
    stream.feed(_frame("g1", []))               # then the game starts
    assert starts == [("g1", "black")]


def test_game_start_color_is_none_without_ticket() -> None:
    starts: list[tuple[str, str | None]] = []
    stream = GameStream(
        on_game_start=lambda s, color: starts.append((s.game_id, color)),
        on_move=lambda _uci: None,
    )
    stream.feed(_frame("g1", []))
    assert starts == [("g1", None)]


def test_snapshot_dataclass_defaults() -> None:
    snap = GameSnapshot(game_id="x", moves=[])
    assert snap.clocks == []
    assert snap.actions == []
