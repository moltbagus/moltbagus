from __future__ import annotations

import math
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .engine import (
    NESTED_PROMPTS,
    check_mandatory_guardrails,
    compute_net_damage,
    get_prize_value,
    resolve_sub_prompt,
    run_expectimax_search,
)
from .tracker import CardTracker


@dataclass
class AgentPolicy:
    name: str
    deck_list: List[str]
    budget_ms: int = 120
    temperature: float = 0.15
    opp_profile: dict = field(default_factory=lambda: {"expected_active_damage": 110})
    custom_selector: Optional[Callable[[dict, List[dict], CardTracker], str]] = None

    def choose_action(self, state: dict, legal_actions: List[dict], tracker: CardTracker) -> str:
        if self.custom_selector is not None:
            return self.custom_selector(state, legal_actions, tracker)
        if state.get("prompt_type") in NESTED_PROMPTS:
            return resolve_sub_prompt(state, legal_actions, tracker)
        forced = check_mandatory_guardrails(state, legal_actions, tracker)
        if forced:
            return forced["id"]
        chosen = run_expectimax_search(
            state, legal_actions, self.opp_profile,
            budget_ms=self.budget_ms, temperature=self.temperature,
        )
        return chosen["id"]


def _build_card_object(name: str, idx: int) -> dict:
    if "Energy" in name:
        return {"id": f"c_{idx}", "name": name, "card_type": "ENERGY", "tags": []}
    if "Supporter" in name or "Professor" in name or "Boss" in name:
        tags = ["GUST"] if "Boss" in name else ["DRAW"]
        return {
            "id": f"c_{idx}", "name": name, "card_type": "SUPPORTER",
            "draw_count": 7 if "Professor" in name else 0, "tags": tags,
        }
    if "Ball" in name or "Switch" in name or "Hammer" in name:
        tags = ["TURN1"] if "Ball" in name else []
        return {"id": f"c_{idx}", "name": name, "card_type": "ITEM", "tags": tags}
    if "Stage2" in name or "Dragapult" in name:
        return {
            "id": f"c_{idx}", "name": name, "card_type": "POKEMON",
            "stage": "STAGE2", "hp": 320, "type": "DRAGON", "retreat_cost": 1,
            "energy_count": 0, "min_attack_cost": 2, "tags": ["EX", "EVOLUTION"],
            "moves": [{
                "id": "atk_phantom_dive", "type": "ATTACK", "base_damage": 200,
                "bench_spread_damage": 60, "cost": 2,
            }],
        }
    if "Pivot" in name or "Cleffa" in name:
        return {
            "id": f"c_{idx}", "name": name, "card_type": "POKEMON",
            "stage": "BASIC", "hp": 60, "type": "COLORLESS", "retreat_cost": 0,
            "energy_count": 0, "min_attack_cost": 0, "tags": ["DRAW_ENGINE"],
            "moves": [{"id": "atk_draw", "type": "ATTACK", "base_damage": 0, "cost": 0}],
        }
    return {
        "id": f"c_{idx}", "name": name, "card_type": "POKEMON",
        "stage": "BASIC", "hp": 70, "type": "DRAGON", "retreat_cost": 1,
        "energy_count": 0, "min_attack_cost": 1, "tags": [],
        "moves": [{"id": "atk_bite", "type": "ATTACK", "base_damage": 30, "cost": 1}],
    }


@dataclass
class MatchOutcome:
    winner: str
    turns: int
    reason: str
    red_prizes_taken: int
    blue_prizes_taken: int
    red_avg_latency_ms: float
    blue_avg_latency_ms: float


class LocalTCGSimulator:
    """Fast self-play simulator with deterministic RNG seeding for paired AB tests."""

    def __init__(self, max_turns: int = 40):
        self.max_turns = max_turns

    def _init_side(self, deck_list: List[str], rng: random.Random) -> dict:
        cards = [_build_card_object(name, i) for i, name in enumerate(deck_list)]
        while True:
            rng.shuffle(cards)
            hand = cards[:7]
            if any(c["card_type"] == "POKEMON" and c.get("stage") == "BASIC" for c in hand):
                break
        prizes = cards[7:13]
        deck = cards[13:]
        basics = [c for c in hand if c["card_type"] == "POKEMON" and c.get("stage") == "BASIC"]
        basics.sort(key=lambda c: c.get("retreat_cost", 1))
        active = basics[0]
        hand.remove(active)
        bench = []
        for b in basics[1:4]:
            hand.remove(b)
            bench.append(b)
        return {
            "deck": deck, "hand": hand, "prizes": prizes, "discard": [],
            "active": active, "bench": bench,
            "energy_attached_turn": False, "supporter_played_turn": False,
        }

    def _legal_actions(self, me: dict, opp: dict, turn: int) -> List[dict]:
        actions: List[dict] = []
        if len(me["bench"]) < 5:
            for c in me["hand"]:
                if c["card_type"] == "POKEMON" and c.get("stage") == "BASIC":
                    actions.append({"id": f"bench_{c['id']}", "type": "PLAY_BASIC_BENCH", "target_card": c})
        if turn >= 2:
            for c in me["hand"]:
                if c["card_type"] == "POKEMON" and c.get("stage") in ("STAGE1", "STAGE2"):
                    if me["active"] and me["active"].get("stage") == "BASIC":
                        actions.append({"id": f"evolve_act_{c['id']}", "type": "EVOLVE", "target_card": c})
        if not me["energy_attached_turn"]:
            energies = [c for c in me["hand"] if c["card_type"] == "ENERGY"]
            if energies:
                e_card = energies[0]
                if me["active"]:
                    actions.append({
                        "id": f"attach_act_{e_card['id']}", "type": "ATTACH_ENERGY",
                        "target_id": me["active"]["id"], "card": e_card,
                    })
                for b in me["bench"]:
                    actions.append({
                        "id": f"attach_bench_{b['id']}", "type": "ATTACH_ENERGY",
                        "target_id": b["id"], "card": e_card,
                    })
        if turn > 1 and not me["supporter_played_turn"]:
            for c in me["hand"]:
                if c["card_type"] == "SUPPORTER":
                    actions.append({
                        "id": f"supp_{c['id']}", "type": "PLAY_SUPPORTER",
                        "draw_count": c.get("draw_count", 0), "card": c,
                    })
        for c in me["hand"]:
            if c["card_type"] == "ITEM":
                actions.append({"id": f"item_{c['id']}", "type": "PLAY_ITEM_SEARCH", "card": c})
        if turn > 1 and me["active"] and opp["active"]:
            for move in me["active"].get("moves", []):
                if me["active"].get("energy_count", 0) >= move.get("cost", 0):
                    actions.append(dict(move))
        actions.append({"id": "END_TURN", "type": "END_TURN"})
        return actions

    def _view_state(self, me: dict, opp: dict, turn: int, step: int) -> dict:
        return {
            "turn": turn, "step_index": step, "prompt_type": None,
            "my_hand": me["hand"], "my_discard": me["discard"],
            "my_active": me["active"], "my_bench": me["bench"],
            "my_prizes": len(me["prizes"]), "my_deck_count": len(me["deck"]),
            "opp_active": opp["active"], "opp_bench": opp["bench"],
            "opp_prizes": len(opp["prizes"]), "opp_deck_count": len(opp["deck"]),
        }

    def play_game(self, red: AgentPolicy, blue: AgentPolicy, seed: int) -> MatchOutcome:
        # The policy's softmax tie-break draws from the module-level RNG. Seed it
        # per match so paired (seed, seat-swap) games are reproducible run to run.
        random.seed(seed)
        rng = random.Random(seed)
        sides = {"RED": self._init_side(red.deck_list, rng), "BLUE": self._init_side(blue.deck_list, rng)}
        policies = {"RED": red, "BLUE": blue}
        trackers = {"RED": CardTracker(red.deck_list), "BLUE": CardTracker(blue.deck_list)}
        latencies: Dict[str, List[float]] = {"RED": [], "BLUE": []}
        order = ["RED", "BLUE"]

        def outcome(winner: str, reason: str, turn: int) -> MatchOutcome:
            return MatchOutcome(
                winner=winner, turns=turn, reason=reason,
                red_prizes_taken=6 - len(sides["RED"]["prizes"]),
                blue_prizes_taken=6 - len(sides["BLUE"]["prizes"]),
                red_avg_latency_ms=statistics.mean(latencies["RED"] or [0.0]),
                blue_avg_latency_ms=statistics.mean(latencies["BLUE"] or [0.0]),
            )

        for turn in range(1, self.max_turns + 1):
            active_tag = order[(turn - 1) % 2]
            opp_tag = "BLUE" if active_tag == "RED" else "RED"
            me, opp = sides[active_tag], sides[opp_tag]

            if not me["deck"]:
                return outcome(opp_tag, "DECK_OUT", turn)
            me["hand"].append(me["deck"].pop(0))
            me["energy_attached_turn"] = False
            me["supporter_played_turn"] = False

            for step in range(25):
                state = self._view_state(me, opp, turn, step)
                trackers[active_tag].sync_from_state(state)
                legal = self._legal_actions(me, opp, turn)
                t0 = time.perf_counter()
                act_id = policies[active_tag].choose_action(state, legal, trackers[active_tag])
                latencies[active_tag].append((time.perf_counter() - t0) * 1000.0)
                chosen = next((a for a in legal if a["id"] == act_id), legal[-1])
                atype = chosen["type"]

                if atype == "END_TURN":
                    break
                if atype == "PLAY_BASIC_BENCH":
                    card = chosen["target_card"]
                    if card in me["hand"]:
                        me["hand"].remove(card)
                        me["bench"].append(card)
                elif atype == "EVOLVE":
                    evo = chosen["target_card"]
                    if evo in me["hand"] and me["active"]:
                        me["hand"].remove(evo)
                        evo["energy_count"] = me["active"].get("energy_count", 0)
                        me["discard"].append(me["active"])
                        me["active"] = evo
                elif atype == "ATTACH_ENERGY":
                    e_card = chosen["card"]
                    if e_card in me["hand"]:
                        me["hand"].remove(e_card)
                        me["energy_attached_turn"] = True
                        for mon in [me["active"]] + me["bench"]:
                            if mon and mon["id"] == chosen["target_id"]:
                                mon["energy_count"] = mon.get("energy_count", 0) + 1
                elif atype == "PLAY_SUPPORTER":
                    s_card = chosen["card"]
                    if s_card in me["hand"]:
                        me["hand"].remove(s_card)
                        me["discard"].append(s_card)
                        me["supporter_played_turn"] = True
                        draw_n = min(chosen.get("draw_count", 0), len(me["deck"]))
                        for _ in range(draw_n):
                            me["hand"].append(me["deck"].pop(0))
                elif atype == "PLAY_ITEM_SEARCH":
                    i_card = chosen["card"]
                    if i_card in me["hand"]:
                        me["hand"].remove(i_card)
                        me["discard"].append(i_card)
                        if "Ball" in i_card["name"] and len(me["bench"]) < 5:
                            deck_basics = [
                                c for c in me["deck"]
                                if c["card_type"] == "POKEMON" and c.get("stage") == "BASIC"
                            ]
                            if deck_basics:
                                fetched = deck_basics[0]
                                me["deck"].remove(fetched)
                                me["bench"].append(fetched)
                        elif "Switch" in i_card["name"] and me["bench"]:
                            me["bench"].sort(key=lambda m: m.get("energy_count", 0), reverse=True)
                            old_act = me["active"]
                            me["active"] = me["bench"].pop(0)
                            if old_act:
                                me["bench"].append(old_act)
                elif atype == "ATTACK":
                    dmg = compute_net_damage(me["active"], opp["active"], chosen)
                    opp["active"]["hp"] -= dmg
                    spread = chosen.get("bench_spread_damage", 0)
                    if spread > 0 and opp["bench"]:
                        target_b = min(opp["bench"], key=lambda m: m["hp"])
                        target_b["hp"] -= spread
                        if target_b["hp"] <= 0:
                            opp["bench"].remove(target_b)
                            opp["discard"].append(target_b)
                            taken = min(len(me["prizes"]), get_prize_value(target_b))
                            for _ in range(taken):
                                me["hand"].append(me["prizes"].pop(0))
                    if opp["active"]["hp"] <= 0:
                        ko_mon = opp["active"]
                        opp["discard"].append(ko_mon)
                        taken = min(len(me["prizes"]), get_prize_value(ko_mon))
                        for _ in range(taken):
                            me["hand"].append(me["prizes"].pop(0))
                        if not me["prizes"]:
                            return outcome(active_tag, "PRIZES_6", turn)
                        if not opp["bench"]:
                            return outcome(active_tag, "NO_ACTIVE_POKEMON", turn)
                        opp_state = self._view_state(opp, me, turn, step)
                        opp_state["prompt_type"] = "PROMOTE_ACTIVE"
                        prom_actions = [
                            {"id": f"prom_{b['id']}", "type": "PROMOTE", "target_card": b}
                            for b in opp["bench"]
                        ]
                        prom_id = policies[opp_tag].choose_action(opp_state, prom_actions, trackers[opp_tag])
                        chosen_b = next(
                            (a["target_card"] for a in prom_actions if a["id"] == prom_id),
                            opp["bench"][0],
                        )
                        opp["bench"].remove(chosen_b)
                        opp["active"] = chosen_b
                    break

        red_taken = 6 - len(sides["RED"]["prizes"])
        blue_taken = 6 - len(sides["BLUE"]["prizes"])
        winner = "RED" if red_taken >= blue_taken else "BLUE"
        return outcome(winner, "TURN_LIMIT", self.max_turns)


def _exact_two_sided_binomial_p(k: int, n: int, p0: float = 0.5) -> float:
    if n == 0:
        return 1.0
    observed_pmf = math.comb(n, k) * (p0 ** k) * ((1.0 - p0) ** (n - k))
    p_val = 0.0
    for i in range(n + 1):
        pmf = math.comb(n, i) * (p0 ** i) * ((1.0 - p0) ** (n - i))
        if pmf <= observed_pmf + 1e-12:
            p_val += pmf
    return min(1.0, p_val)


def _wilson_ci(wins: int, n: int, z: float = 1.959963984540054) -> Tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p_hat = wins / n
    denom = 1.0 + (z ** 2) / n
    center = p_hat + (z ** 2) / (2.0 * n)
    margin = z * math.sqrt((p_hat * (1.0 - p_hat) + (z ** 2) / (4.0 * n)) / n)
    return max(0.0, (center - margin) / denom), min(1.0, (center + margin) / denom)


def _mcnemar_paired_p(n10: int, n01: int) -> Tuple[float, float]:
    discordant = n10 + n01
    if discordant == 0:
        return 0.0, 1.0
    chi2 = ((abs(n10 - n01) - 1.0) ** 2) / discordant
    p_val = math.erfc(math.sqrt(chi2 / 2.0))
    return chi2, p_val


def run_red_blue_benchmark(
    champion: AgentPolicy, challenger: AgentPolicy, total_games: int = 500,
    base_seed: int = 20261123, promotion_threshold_wr: float = 0.54, alpha: float = 0.05,
) -> dict:
    assert total_games % 2 == 0, "total_games must be even for paired first/second seat mirroring."
    sim = LocalTCGSimulator()
    pairs = total_games // 2
    challenger_wins = challenger_first_wins = challenger_second_wins = 0
    n10_sweeps = n01_sweeps = 0
    win_reasons: Dict[str, int] = {}
    challenger_latencies: List[float] = []
    champion_latencies: List[float] = []

    for pair_idx in range(pairs):
        seed = base_seed + pair_idx
        out_a = sim.play_game(red=challenger, blue=champion, seed=seed)
        c_won_a = out_a.winner == "RED"
        if c_won_a:
            challenger_wins += 1
            challenger_first_wins += 1
        win_reasons[out_a.reason] = win_reasons.get(out_a.reason, 0) + 1
        challenger_latencies.append(out_a.red_avg_latency_ms)
        champion_latencies.append(out_a.blue_avg_latency_ms)

        out_b = sim.play_game(red=champion, blue=challenger, seed=seed)
        c_won_b = out_b.winner == "BLUE"
        if c_won_b:
            challenger_wins += 1
            challenger_second_wins += 1
        win_reasons[out_b.reason] = win_reasons.get(out_b.reason, 0) + 1
        champion_latencies.append(out_b.red_avg_latency_ms)
        challenger_latencies.append(out_b.blue_avg_latency_ms)

        if c_won_a and c_won_b:
            n10_sweeps += 1
        elif not c_won_a and not c_won_b:
            n01_sweeps += 1

    win_rate = challenger_wins / total_games
    ci_low, ci_high = _wilson_ci(challenger_wins, total_games)
    binom_p = _exact_two_sided_binomial_p(challenger_wins, total_games, p0=0.50)
    mcnemar_chi2, mcnemar_p = _mcnemar_paired_p(n10_sweeps, n01_sweeps)
    clamped_wr = min(0.999, max(0.001, win_rate))
    elo_delta = -400.0 * math.log10((1.0 / clamped_wr) - 1.0)
    promote = (
        win_rate >= promotion_threshold_wr
        and binom_p < alpha
        and mcnemar_p < alpha
        and ci_low > 0.50
    )
    return {
        "challenger": challenger.name, "champion": champion.name,
        "total_games": total_games, "challenger_wins": challenger_wins,
        "champion_wins": total_games - challenger_wins,
        "win_rate": round(win_rate, 4), "ci_95": (round(ci_low, 4), round(ci_high, 4)),
        "elo_delta": round(elo_delta, 1), "exact_binomial_p": round(binom_p, 6),
        "mcnemar_chi2": round(mcnemar_chi2, 3), "mcnemar_paired_p": round(mcnemar_p, 6),
        "paired_sweeps": {"challenger_2_0": n10_sweeps, "champion_2_0": n01_sweeps},
        "seat_split": {
            "going_first_wr": round(challenger_first_wins / pairs, 4),
            "going_second_wr": round(challenger_second_wins / pairs, 4),
        },
        "latency_ms": {
            "challenger_mean": round(statistics.mean(challenger_latencies), 2),
            "champion_mean": round(statistics.mean(champion_latencies), 2),
        },
        "termination_breakdown": win_reasons,
        "PROMOTE_TO_PROD": promote,
    }


def _build_sample_60_card_deck() -> List[str]:
    return (
        ["Dreepy Basic"] * 4 + ["Dragapult Stage2"] * 4 + ["Cleffa Pivot"] * 4
        + ["Nest Ball"] * 8 + ["Switch Item"] * 4 + ["Crushing Hammer"] * 4
        + ["Professor Supporter"] * 10 + ["Boss Supporter"] * 4
        + ["Psychic Energy"] * 10 + ["Fire Energy"] * 8
    )


def greedy_baseline_selector(state: dict, legal_actions: List[dict], tracker: CardTracker) -> str:
    if state.get("prompt_type") in NESTED_PROMPTS:
        return legal_actions[0]["id"]
    for pref in ("PLAY_BASIC_BENCH", "ATTACH_ENERGY", "EVOLVE", "ATTACK"):
        for act in legal_actions:
            if act.get("type") == pref:
                return act["id"]
    return legal_actions[-1]["id"]


if __name__ == "__main__":
    deck = _build_sample_60_card_deck()
    v_prod = AgentPolicy(name="v1_greedy_baseline", deck_list=deck, custom_selector=greedy_baseline_selector)
    v_cand = AgentPolicy(name="v3_expectimax_champion", deck_list=deck, budget_ms=120, temperature=0.15)
    summary = run_red_blue_benchmark(
        champion=v_prod, challenger=v_cand, total_games=500,
        promotion_threshold_wr=0.54, alpha=0.05,
    )
    print("\n=== RED-BLUE ADVERSARIAL SELF-PLAY REPORT (N = 500 PAIRED GAMES) ===")
    for k, v in summary.items():
        print(f"{k:24s}: {v}")
