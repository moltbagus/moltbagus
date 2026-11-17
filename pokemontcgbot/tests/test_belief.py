import math

import pytest

from belief import BeliefTracker, build_tracker_from_obs


def make_obs(hand=7, deck=53, prizes=None, discard=None, active=None, bench=None, yi=0):
    you = {
        "handCount": 7,
        "deckCount": 53,
        "prize": [],
        "discard": [],
        "active": [],
        "bench": [],
    }
    opponent = {
        "handCount": hand,
        "deckCount": deck,
        "prize": prizes if prizes is not None else [],
        "discard": discard or [],
        "active": active or [],
        "bench": bench or [],
    }
    players = [you, opponent] if yi == 0 else [opponent, you]
    return {"current": {"yourIndex": yi, "players": players}, "select": {"option": []}}


def test_hypergeometric_matches_formula():
    tracker = BeliefTracker({328: 4})
    assert tracker.sync_from_obs(make_obs(hand=7, deck=53)) is True

    expected = 1.0 - math.comb(56, 7) / math.comb(60, 7)
    assert tracker.total_remaining_pool() == 60
    assert tracker.hand_probabilities()[328] == pytest.approx(expected)


def test_sync_is_idempotent_and_reads_opponent_side():
    obs = make_obs(
        hand=6,
        deck=44,
        prizes=[None] * 6,
        discard=[{"id": 1086}, {"id": 1086}, {"id": 1}],
        active=[{"id": 96, "hp": 210, "maxHp": 210, "energyCards": [{"id": 1}]}],
        bench=[{"id": 709, "hp": 160, "maxHp": 160}],
        yi=1,
    )
    tracker = BeliefTracker({})

    tracker.sync_from_obs(obs)
    first = (
        dict(tracker.discard),
        dict(tracker.board),
        tracker.hand_size,
        tracker.deck_size,
        tracker.prizes_remaining,
        tracker.hand_probabilities(),
    )

    tracker.sync_from_obs(obs)
    second = (
        dict(tracker.discard),
        dict(tracker.board),
        tracker.hand_size,
        tracker.deck_size,
        tracker.prizes_remaining,
        tracker.hand_probabilities(),
    )

    assert first == second
    assert tracker.hand_size == 6  # players[0] when yourIndex is 1
    assert tracker.prizes_remaining == 6
    assert tracker.discard[1086] == 2
    assert tracker.board[96] == 1
    assert tracker.board[1] == 1  # attached energy is public, not in hand
    assert tracker.board[709] == 1


def test_reset_for_match_keeps_archetype_but_clears_state():
    tracker = BeliefTracker({328: 4})
    tracker.sync_from_obs(
        make_obs(
            hand=6,
            deck=44,
            prizes=[None] * 6,
            discard=[{"id": 328}],
            active=[{"id": 96, "hp": 100, "maxHp": 210}],
        )
    )
    tracker.reset_for_match()

    assert tracker.hand_size == 0
    assert tracker.deck_size == 60
    assert dict(tracker.discard) == {}
    assert dict(tracker.board) == {}
    assert tracker.archetype[328] == 4


def test_energy_is_excluded_from_threats():
    tracker = BeliefTracker({1: 40, 328: 4})
    tracker.sync_from_obs(make_obs(hand=7, deck=53))

    probs = tracker.hand_probabilities()
    threats = dict(tracker.top_threats(5))

    assert probs[1] > 0.99  # raw probability is still tracked
    assert 1 not in threats
    assert 328 in threats


def test_build_tracker_from_obs_uses_arena_schema():
    tracker = build_tracker_from_obs(make_obs(hand=5, deck=48), {328: 4})
    assert tracker.hand_size == 5
    assert tracker.deck_size == 48
    assert tracker.total_remaining_pool() == 53
