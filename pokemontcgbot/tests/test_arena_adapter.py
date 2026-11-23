"""Tests for the real-schema adapter. No network calls, no payment code."""
import pytest

from devfun_tcg_bot.arena_adapter import (
    STAKES, PLAYGROUND, ArenaContract, ContractError, action_body,
    busy_conflict, classify_competitions, error_code, join_body,
    legal_action, parse_pending, pending_identity, policy_state,
    retry_after_seconds,
)


INTROSPECTION = {
    "baseUrl": "https://arena.dev.fun",
    "auth": {"type": "header", "name": "x-arena-api-key"},
    "endpoints": [
        {"path": "/api/arena/tcg/join", "method": "POST"},
        {"path": "/api/arena/tcg/pending-actions", "method": "GET"},
        {"path": "/api/arena/tcg/action", "method": "POST"},
        {"path": "/api/arena/agent/wallet", "method": "GET"},
    ],
}


def test_contract_discovers_endpoints_from_list_not_semantic_keys():
    contract = ArenaContract(INTROSPECTION)
    assert contract.url("join") == "https://arena.dev.fun/api/arena/tcg/join"
    assert contract.url("pending") == "https://arena.dev.fun/api/arena/tcg/pending-actions"
    assert contract.url("action") == "https://arena.dev.fun/api/arena/tcg/action"
    assert contract.headers("SECRET")["x-arena-api-key"] == "SECRET"


def test_contract_rejects_missing_route():
    broken = dict(INTROSPECTION, endpoints=[{"path": "/api/arena/tcg/join", "method": "POST"}])
    with pytest.raises(ContractError):
        ArenaContract(broken)


def test_classify_by_gametype_and_name_not_entryfee():
    payload = [
        {"id": "pg", "gameType": "PokemonTcg", "name": "[TCG] Playground S7", "entryFee": None},
        {"id": "st", "gameType": "PokemonTcg", "name": "[TCG] Stakes S6", "entryFee": None},
        {"id": "pk", "gameType": "TexasHoldem", "name": "[Poker] Stakes S3"},
    ]
    got = classify_competitions(payload)
    assert got[PLAYGROUND]["id"] == "pg"
    assert got[STAKES]["id"] == "st"


def test_parse_pending_real_shape():
    payload = {"pending": [{"matchId": "m1", "seq": 4}], "activeMatches": []}
    pending, active = parse_pending(payload)
    assert len(pending) == 1 and active == []
    with pytest.raises(ContractError):
        parse_pending({"matches": []})


def test_join_body_uses_joinpayload_not_deck():
    body = join_body("comp1", [1] * 60)
    assert body["joinPayload"] == [1] * 60
    assert "deck" not in body
    with pytest.raises(ContractError):
        join_body("comp1", [1] * 59)


def test_action_body_echoes_seq_and_validates_legality():
    entry = {"matchId": "match-9", "seq": 7, "legalActions": ["[0]", "[1]"]}
    assert action_body(entry, "[1]") == {"matchId": "match-9", "seq": 7, "action": "[1]"}
    with pytest.raises(ContractError):
        legal_action(entry, "[9]")


def test_identity_and_conflict_parsing():
    assert pending_identity({"matchId": "m", "seq": 2}) == ("m", 2)
    assert error_code("action_conflict") == "action_conflict"
    assert error_code({"error": {"code": "arena_transaction_busy"}}) == "arena_transaction_busy"
    assert busy_conflict(409, {"error": {"code": "arena_transaction_busy"}})
    assert not busy_conflict(409, {"error": "action_conflict"})
    assert retry_after_seconds({"retryAfter": "abc"}) is None
    assert retry_after_seconds({"retryAfter": 3}) == 3.0


def test_policy_state_reads_yourindex_and_hides_hand():
    entry = {
        "matchId": "m", "seq": 1,
        "legalActions": ["[0]"],
        "obs": {"current": {
            "yourIndex": 1,
            "players": [
                {"active": {"id": 10}, "bench": [{"id": 11}], "prize": [1, 2, 3],
                 "deckCount": 20, "hand": None},
                {"active": {"id": 20}, "bench": [], "prize": [1, 2, 3, 4],
                 "deckCount": 25, "hand": None},
            ],
        }},
    }
    state = policy_state(entry)
    assert state["yourIndex"] == 1
    assert state["my_active"]["id"] == 20
    assert state["opp_active"]["id"] == 10
    assert state["my_prizes"] == 4
    assert state["my_hand"] == []
