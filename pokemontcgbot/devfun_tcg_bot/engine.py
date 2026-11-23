from __future__ import annotations

import copy
import math
import random
import time
from typing import Dict, List, Optional

from .tracker import CardTracker

NESTED_PROMPTS = {
    "DISCARD_FROM_HAND",
    "SEARCH_DECK",
    "SELECT_BENCH_TARGET",
    "PROMOTE_ACTIVE",
    "RECOVER_FROM_DISCARD",
}


def compute_net_damage(attacker: dict, defender: dict, move: dict) -> int:
    dmg = move.get("base_damage", 0)
    if dmg <= 0:
        return 0
    atk_type = attacker.get("type")
    if atk_type and atk_type == defender.get("weakness"):
        dmg *= defender.get("weakness_mult", 2)
    if atk_type and atk_type == defender.get("resistance"):
        dmg = max(0, dmg - defender.get("resistance_val", 30))
    return int(dmg)


def get_prize_value(pokemon: dict) -> int:
    tags = set(pokemon.get("tags", []))
    if "MEGA_EX" in tags or "VMAX" in tags:
        return 3
    if "EX" in tags or "V" in tags or "VSTAR" in tags:
        return 2
    return 1


def resolve_sub_prompt(state: dict, legal_actions: List[dict], tracker: CardTracker) -> str:
    """Deterministically resolves nested card-selection prompts in <1ms."""
    if not legal_actions:
        raise ValueError("resolve_sub_prompt requires at least one legal action")
    prompt = state.get("prompt_type")
    my_prizes = state.get("my_prizes", 6)

    if prompt == "PROMOTE_ACTIVE":
        opp_active = state.get("opp_active", {})
        best_action, best_score = legal_actions[0], -1e9
        for act in legal_actions:
            cand = act.get("target_card", {})
            ready = cand.get("energy_count", 0) >= cand.get("min_attack_cost", 1)
            can_ko = any(
                compute_net_damage(cand, opp_active, m) >= opp_active.get("hp", 999)
                for m in cand.get("moves", [])
            )
            score = (500 if (ready and can_ko) else 0) - (cand.get("retreat_cost", 1) * 20)
            score -= get_prize_value(cand) * 40
            if score > best_score:
                best_score, best_action = score, act
        return best_action["id"]

    if prompt == "DISCARD_FROM_HAND":
        def discard_keep_value(act: dict) -> float:
            card = act.get("target_card", {})
            name = card.get("name", "")
            ctype = card.get("card_type", "")
            rem = tracker.remaining_copies(name) + 1
            if rem == 1 and ctype in ("POKEMON", "SUPPORTER"):
                return 999.0
            if ctype == "ENERGY":
                return 15.0
            if ctype == "ITEM" and "TURN1" in card.get("tags", []):
                return 5.0
            return 40.0 + (10.0 if ctype == "SUPPORTER" else 0.0)

        return min(legal_actions, key=discard_keep_value)["id"]

    if prompt == "SEARCH_DECK":
        my_bench = state.get("my_bench", [])

        def search_priority(act: dict) -> float:
            card = act.get("target_card", {})
            name = card.get("name", "")
            if tracker.is_definitely_prized(name):
                return -999.0
            tags = set(card.get("tags", []))
            if len(my_bench) == 0 and card.get("stage") == "BASIC":
                return 500.0
            if "EVOLUTION" in tags:
                return 300.0
            if "DRAW_ENGINE" in tags:
                return 220.0
            return 100.0

        return max(legal_actions, key=search_priority)["id"]

    if prompt == "SELECT_BENCH_TARGET":
        best_act, best_val = legal_actions[0], -1e9
        for act in legal_actions:
            target = act.get("target_card", {})
            prizes = get_prize_value(target)
            hp = target.get("hp", 100)
            val = (prizes * 120) - (hp * 0.5) + (target.get("energy_count", 0) * 25)
            if prizes >= my_prizes and hp <= 180:
                val += 1000
            if val > best_val:
                best_val, best_act = val, act
        return best_act["id"]

    return legal_actions[0]["id"]


def check_mandatory_guardrails(
    state: dict, legal_actions: List[dict], tracker: CardTracker
) -> Optional[dict]:
    """Phase 0 survival, self-deck-out, and Turn-1 donk overrides."""
    my_bench = state.get("my_bench", [])
    my_deck_count = state.get("my_deck_count", 30)
    opp_bench = state.get("opp_bench", [])
    opp_active = state.get("opp_active", {})

    if len(my_bench) == 0:
        bench_basics = [a for a in legal_actions if a.get("type") == "PLAY_BASIC_BENCH"]
        if bench_basics:
            return bench_basics[0]

    safe_actions = [
        act for act in legal_actions
        if not (act.get("type") == "PLAY_SUPPORTER" and act.get("draw_count", 0) >= my_deck_count)
    ]

    if len(opp_bench) == 0 and opp_active:
        for act in safe_actions:
            if act.get("type") == "ATTACK":
                dmg = compute_net_damage(state.get("my_active", {}) or {}, opp_active, act)
                if dmg >= opp_active.get("hp", 999):
                    return act

    return None


def evaluate_board_state(state: dict, opp_profile: dict) -> float:
    """Evaluates board with Prize-parity math and deck-out pressure."""
    my_prizes = state.get("my_prizes", 6)
    opp_prizes = state.get("opp_prizes", 6)

    if my_prizes <= 0:
        return 10000.0
    if opp_prizes <= 0:
        return -10000.0

    my_active = state.get("my_active") or {}
    opp_active = state.get("opp_active") or {}
    opp_bench = state.get("opp_bench", [])
    opp_deck = state.get("opp_deck_count", 30)

    score = 100.0 * (6 - my_prizes) - 115.0 * (6 - opp_prizes)
    if opp_prizes in (5, 3, 1):
        score += 28.0

    active_prizes = get_prize_value(my_active)
    if active_prizes == 3 and opp_prizes <= 3:
        score -= 140.0

    for b_mon in opp_bench:
        dmg_counters = b_mon.get("damage", 0)
        rem_hp = b_mon.get("hp", 100) - dmg_counters
        if dmg_counters > 0 and rem_hp <= 60:
            score += 35.0 * get_prize_value(b_mon)

    if opp_deck <= 3:
        score += (4 - opp_deck) * 180.0

    projected_opp_dmg = opp_profile.get("expected_active_damage", 110)
    if len(state.get("my_bench", [])) == 0 and my_active.get("hp", 100) <= projected_opp_dmg:
        score -= 5000.0

    hand_len = len(state.get("my_hand", []))
    if hand_len > 7:
        score -= (hand_len - 7) * 6.0

    return score


def simulate_action_lightweight(state: dict, action: dict) -> dict:
    """Fast forward-model step for 2-turn Expectimax rollouts."""
    next_s = copy.deepcopy(state)
    atype = action.get("type")

    if atype == "PLAY_BASIC_BENCH":
        card = action.get("target_card", {"name": "Basic", "hp": 70})
        next_s.setdefault("my_bench", []).append(card)
    elif atype == "ATTACH_ENERGY":
        target_id = action.get("target_id")
        for mon in [next_s.get("my_active")] + next_s.get("my_bench", []):
            if mon and mon.get("id") == target_id:
                mon["energy_count"] = mon.get("energy_count", 0) + 1
    elif atype == "ATTACK":
        my_act = next_s.get("my_active") or {}
        opp_act = next_s.get("opp_active") or {}
        dmg = compute_net_damage(my_act, opp_act, action)
        opp_act["hp"] = opp_act.get("hp", 100) - dmg
        if opp_act["hp"] <= 0:
            next_s["my_prizes"] = max(0, next_s.get("my_prizes", 6) - get_prize_value(opp_act))
        spread = action.get("bench_spread_damage", 0)
        if spread > 0 and next_s.get("opp_bench"):
            target_b = min(next_s["opp_bench"], key=lambda m: m.get("hp", 100))
            target_b["damage"] = target_b.get("damage", 0) + spread

    return next_s


def simulate_opponent_counter(state: dict, opp_profile: dict) -> float:
    my_act = state.get("my_active") or {}
    opp_dmg = opp_profile.get("expected_active_damage", 110)
    counter_penalty = 0.0
    if my_act and my_act.get("hp", 100) <= opp_dmg:
        counter_penalty += 125.0 * get_prize_value(my_act)
        if len(state.get("my_bench", [])) == 0:
            counter_penalty += 5000.0
    return evaluate_board_state(state, opp_profile) - counter_penalty


def run_expectimax_search(
    state: dict,
    legal_actions: List[dict],
    opp_profile: dict,
    budget_ms: int = 240,
    temperature: float = 0.15,
) -> dict:
    """2-ply Expectimax with Softmax tie-breaking against counter-scouting."""
    if not legal_actions:
        raise ValueError("run_expectimax_search requires at least one legal action")
    deadline = time.perf_counter() + (budget_ms / 1000.0)
    scored: List[tuple] = []

    for act in legal_actions:
        if time.perf_counter() > deadline and scored:
            break
        s1 = simulate_action_lightweight(state, act)
        ev = simulate_opponent_counter(s1, opp_profile)
        priority_bonus = {
            "PLAY_BASIC_BENCH": 18.0,
            "USE_ABILITY": 14.0,
            "PLAY_ITEM_SEARCH": 12.0,
            "PLAY_SUPPORTER": 10.0,
            "EVOLVE": 8.0,
            "ATTACH_ENERGY": 6.0,
        }.get(act.get("type", ""), 0.0)
        scored.append((ev + priority_bonus, act))

    scored.sort(key=lambda x: x[0], reverse=True)
    if len(scored) == 1 or temperature <= 0:
        return scored[0][1]

    best = scored[0][0]
    pool = [(s, a) for s, a in scored if s >= best - 2.0]
    if len(pool) == 1:
        return pool[0][1]
    weights = [math.exp((s - best) / temperature) for s, _ in pool]
    total = sum(weights)
    r = random.random() * total
    acc = 0.0
    for weight, (_, act) in zip(weights, pool):
        acc += weight
        if r <= acc:
            return act
    return pool[0][1]
