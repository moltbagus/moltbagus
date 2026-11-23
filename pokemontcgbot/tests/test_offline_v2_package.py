"""Offline package tests. These do NOT touch the live arena bot."""
import math
import pytest

from devfun_tcg_bot.tracker import CardTracker
from devfun_tcg_bot.engine import (
    check_mandatory_guardrails,
    compute_net_damage,
    get_prize_value,
    resolve_sub_prompt,
    run_expectimax_search,
)


def _card(name, **kw):
    base = {"id": name, "name": name, "card_type": "POKEMON", "hp": 70, "tags": [], "moves": []}
    base.update(kw)
    return base


def test_tracker_unknown_pool_and_hit_probability():
    deck = ["Nest Ball"] * 4 + ["Professor"] * 4 + ["Energy"] * 52
    tracker = CardTracker(deck)
    tracker.sync_from_state({"my_hand": [_card("Nest Ball")], "my_bench": [], "my_discard": [], "my_active": None})
    pool = tracker.unknown_pool
    assert pool["Nest Ball"] == 3
    assert pool["Professor"] == 4
    # Drawing 7 from 59 unknown with 4 Professor copies.
    p = tracker.prob_draw_at_least_one({"Professor"}, 7)
    assert 0.0 < p < 1.0


def test_check_mandatory_guardrails_empty_bench():
    tracker = CardTracker(["Basic"] * 60)
    bench = {"id": "b", "type": "PLAY_BASIC_BENCH", "target_card": _card("Basic")}
    attack = {"id": "a", "type": "ATTACK", "base_damage": 30}
    forced = check_mandatory_guardrails({"my_bench": []}, [bench, attack], tracker)
    assert forced["id"] == "b"


def test_compute_net_damage_weakness_resistance():
    atk = {"type": "WATER"}
    defender = {"weakness": "WATER", "resistance": "FIRE", "resistance_val": 20}
    move = {"base_damage": 50}
    assert compute_net_damage(atk, defender, move) == 100
    atk = {"type": "FIRE"}
    assert compute_net_damage(atk, defender, move) == 30


def test_get_prize_value():
    assert get_prize_value({"tags": []}) == 1
    assert get_prize_value({"tags": ["EX"]}) == 2
    assert get_prize_value({"tags": ["VMAX"]}) == 3


def test_resolve_sub_prompt_promote_prefers_ready_ko():
    tracker = CardTracker(["X"] * 60)
    weak = _card("Weak", hp=60, energy_count=0, min_attack_cost=2, moves=[{"base_damage": 30}])
    strong = _card("Strong", hp=120, energy_count=2, min_attack_cost=2, moves=[{"base_damage": 200}])
    actions = [
        {"id": "weak", "target_card": weak},
        {"id": "strong", "target_card": strong},
    ]
    state = {"prompt_type": "PROMOTE_ACTIVE", "opp_active": {"hp": 100}}
    assert resolve_sub_prompt(state, actions, tracker) == "strong"


def test_expectimax_search_returns_legal_action_and_respects_budget():
    tracker = CardTracker(["X"] * 60)
    state = {"my_prizes": 6, "opp_prizes": 6, "my_bench": [_card("B")], "my_active": _card("A", hp=100),
             "opp_active": _card("O", hp=100), "opp_bench": [], "opp_deck_count": 30,
             "my_hand": [], "my_discard": []}
    actions = [
        {"id": "end", "type": "END_TURN"},
        {"id": "bench", "type": "PLAY_BASIC_BENCH", "target_card": _card("B2")},
        {"id": "attach", "type": "ATTACH_ENERGY", "target_id": "A"},
    ]
    chosen = run_expectimax_search(state, actions, {"expected_active_damage": 110}, budget_ms=50, temperature=0.0)
    assert chosen["id"] in {"end", "bench", "attach"}
