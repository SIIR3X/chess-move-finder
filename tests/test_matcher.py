"""Tests for reading the player's colour from matchmaking frames."""

import base64
import gzip
import json
from typing import Any

from chess_move_finder.tracking.matcher import parse_ticket


def _matcher_frame(ticket: dict[str, Any]) -> str:
    blob = base64.b64encode(gzip.compress(json.dumps(ticket).encode())).decode()
    return f'47[20,"matcher/tickets/users/:me","1780869994994-0","{blob}",1]'


def test_parses_color_and_ids_from_ticket() -> None:
    frame = _matcher_frame(
        {
            "userId": "user-uuid",
            "color": "black",
            "game": {"id": "game-uuid", "players": ["white-uuid", "user-uuid"]},
        }
    )
    ticket = parse_ticket(frame)
    assert ticket is not None
    assert ticket.game_id == "game-uuid"
    assert ticket.color == "black"
    assert ticket.user_id == "user-uuid"


def test_ignores_non_matcher_socketio_frame() -> None:
    other = _matcher_frame({"userId": "u", "color": "white", "game": {"id": "g"}})
    other = other.replace("matcher/tickets", "some/other/channel")
    assert parse_ticket(other) is None


def test_ignores_game_and_heartbeat_frames() -> None:
    assert parse_ticket("AAAAAAwAAAAAAAAAAAA=") is None  # heartbeat
    assert parse_ticket('{"id": "g", "moves": []}') is None  # plain JSON, no array


def test_parses_real_captured_frame() -> None:
    # A real matcher frame captured from chess.com (gzipped ticket, "color": white).
    blob = (
        "H4sIAAAAAAAA/+1WTW/bOBD9LzxbFklJ1Met6AK7e1hg0aZA0aJYUNTIIqIvkJSNIPB/74xct8kmRey2x/o"
        "iiX7zyDdvOOQ9sw2rmMwaqTVXkZJ1EwnRiqhoDER5XtbAeWtSmbENWzy4vwnPmzZLFDdRo5VBPLRRCbyJai"
        "GEKppSQFYgPtgBXk9jcFPPqntWaw8Y/O+N4P/gv3Y0DgYYwzrG37LjhvmgA2G0MTAHaIjkbqYRD3CLX2bqJ"
        "4efh84icMN2egDiPstIjWn1QxlZmUVc5YVsueAoBWN62GlzR0KEKguV5SKRSm3YXjur1+WYDrz/IsD0Gt8r"
        "5vRsmx8S5TQpqVrde9iwudd34JDx46VpVFmTZ3WqEYaenGAJ5FFaKwVNIhMja/bpK/MfELTtaYJ7mtqOO1Z"
        "JzjenHF0459nqVMo0S0slTkPjmm725wI+8CRLMl6kXCFe73XQ7p3DnLAuhNlXcXw4HLZrJrdmGuJ6GZsefH"
        "yAOraD3uHrOJ3C/uu3RapLmSZqu7NkUWd33Rvwr34tq5kW9O0Oyd6/x88Bhhrz1dkZR3YkCQfbXlv3empI5"
        "jiFjtK3YTDquicTg1vQQ/SYPH1FLksuscJEJNMbkVVZUcnyAyVwbl6CGKwirJS/bNPAeKbeg7Ot/Vovx81z"
        "Jl5UEQ9NTNKkLHn21MQiESJPeC5/m7g6lN3wBPNVyfy7Jj6GXGTipyezKWxKEc9vpKy4qpJ0W/KC6DoHLSJ"
        "itGlvDcS0p6PFRzJK4jVhMXU8H1/Y6kynxxEo8w+JrqKYl9ov9aM1rSMrGfVDp0c/Ty54aodkMD2X1e5fI+"
        "P4bRFPiR+t5aflUrf2k7mF8IKIMwrx0xJg1X7QwXRUhTTf9pL5trDH2qGTZpj2cF0oRVCkNsFO43Wxp5hT9"
        "O04HXBX7M6n1lU05+Dhi4x5bVTXcFCEZ0f8YSlN7843jAs7nJ8WZyhxzozsuRP88dn7/901kGPgYrpcrBVy"
        "yS3opZ1cCP5M73i64cvkAzt+Bl9O0S2BCQAA"
    )
    frame = f'47[20,"matcher/tickets/users/:me","1780869994994-0","{blob}",1]'
    ticket = parse_ticket(frame)
    assert ticket is not None
    assert ticket.color == "white"
    assert ticket.game_id == "25d4ccfa-62bd-11f1-8595-06782f01000f"
    assert ticket.user_id == "0df5360c-da6c-11ef-9e0d-b11168d91e58"
