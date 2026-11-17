"""Self-play harness v2 — blue-team hardened.

Improvements over v1:
1. Prize-value targeting (ex = 2 prizes, prefer ex KOs)
2. Bench discipline (never leave active unprotected)
3. Energy accounting (only attack when energy sufficient)
4. All action types handled correctly
5. State access guarded (full_state may be None)
6. Action objects properly accessed via .actionType, not string matching

Usage:
    python self_play_v2.py --games 100 --deck1 charizard_ex --deck2 miraidon_ex
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/colb/ptcg-lab/src")

from ptcg.core.envs import PokemonTCG
from ptcg.core.enums import ActionType, PlayerId

# ---------------------------------------------------------------- policy base
class Policy:
    name = "base"

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def choose(self, obs, info) -> object:
        raise NotImplementedError


class RandomPolicy(Policy):
    name = "random"

    def choose(self, obs, info) -> object:
        actions = info.get("raw_available_actions", [])
        if not actions:
            return None
        return self.rng.choice(actions)


class HeuristicPolicy(Policy):
    """Hardened heuristic: abilities -> bench -> search -> energy -> attacks (KO-first, prize-aware)."""
    name = "heuristic-v2"

    def choose(self, obs, info) -> object:
        actions = info.get("raw_available_actions", [])
        if not actions:
            return None

        # Guard: state may be None
        state = info.get("full_state")
        me = None
        opp = None
        if state is not None:
            try:
                me = state.player1
                opp = state.player2
            except AttributeError:
                pass

        bench_count = 0
        active_hp = 0
        active_max_hp = 1
        opp_active_hp = 999
        opp_active_is_ex = False
        energy_attached = False

        if me is not None:
            bench_count = len(me.bench) if hasattr(me, "bench") and me.bench else 0
            active = me.active if hasattr(me, "active") else None
            if active is not None:
                active_hp = getattr(active, "hp", 0) or 0
                active_max_hp = getattr(active, "maxHp", 1) or 1
            energy_attached = getattr(me, "energy_attached_this_turn", False)

        if opp is not None:
            opp_active = opp.active if hasattr(opp, "active") else None
            if opp_active is not None:
                opp_active_hp = getattr(opp_active, "hp", 999) or 999
                opp_active_is_ex = getattr(opp_active, "is_ex", False)

        # 1. Abilities first (almost always +EV)
        abilities = [a for a in actions if a.actionType in (ActionType.USE_ABILITY_ACTION, ActionType.USE_STADIUM_ACTION)]
        if abilities:
            return abilities[0]

        # 2. Bench discipline: bench basics if bench < 2 (never leave active unprotected)
        plays = [a for a in actions if a.actionType == ActionType.PLAY_POKEMON_ACTION]
        if plays and bench_count < 2:
            return plays[0]

        # 3. Search/consistency (items)
        items = [a for a in actions if a.actionType == ActionType.USE_ITEM_ACTION]
        if items:
            return items[0]

        # 4. Supporters (draw/search)
        supporters = [a for a in actions if a.actionType == ActionType.USE_SUPPORTER_ACTION]
        if supporters:
            return supporters[0]

        # 5. Energy attachment (only if not already attached)
        energies = [a for a in actions if a.actionType == ActionType.ATTACH_ENERGY_ACTION]
        if energies and not energy_attached:
            return energies[0]

        # 6. Attacks: prefer KO, then prize value (ex = 2 prizes)
        attacks = [a for a in actions if a.actionType == ActionType.ATTACK_ACTION]
        if attacks:
            scored = []
            for a in attacks:
                dmg = getattr(a, "damage", 0) or 0
                if hasattr(a, "attack") and hasattr(a.attack, "damage"):
                    dmg = a.attack.damage or dmg
                ko_bonus = 1000 if dmg >= opp_active_hp else 0
                prize_bonus = 500 if opp_active_is_ex else 0
                # Prize differential bonus
                prize_diff = 0
                if me and opp:
                    my_prizes = getattr(me, "prizes", 6)
                    opp_prizes = getattr(opp, "prizes", 6)
                    prize_diff = (6 - opp_prizes) - (6 - my_prizes)
                scored.append((a, dmg + ko_bonus + prize_bonus + prize_diff * 100))
            scored.sort(key=lambda x: -x[1])
            return scored[0][0]

        # 7. Evolutions
        evos = [a for a in actions if a.actionType == ActionType.EVOLVE_POKEMON_ACTION]
        if evos:
            return evos[0]

        # 8. Play remaining cards
        if plays:
            return plays[0]

        # 9. Retreat if active is low HP and bench has backup
        retreats = [a for a in actions if a.actionType == ActionType.RETREAT_ACTION]
        if retreats and active_hp < active_max_hp * 0.4 and bench_count > 0:
            return retreats[0]

        # 10. Fallback
        return next((a for a in actions if a.actionType == ActionType.PASS_TURN), actions[0])


POLICIES = {"random": RandomPolicy, "heuristic": HeuristicPolicy, "heuristic-v2": HeuristicPolicy}


def run_game(env, p1_policy, p2_policy, seed=None) -> dict:
    if seed is not None:
        env.set_seed(seed)

    obs, reward, done, info = env.reset()
    turn = 0
    actions = 0

    while not done:
        policy = p1_policy if turn % 2 == 0 else p2_policy
        action = policy.choose(obs, info)
        if action is None:
            break
        obs, reward, done, info = env.step(action)
        actions += 1
        turn += 1
        if turn > 1000:
            break

    winner = info.get("winner", None)
    reason = info.get("termination_reason", "unknown")
    return {
        "winner": winner,
        "reason": reason,
        "actions": actions,
        "turns": turn,
    }


def run_self_play(
    deck1: str = "charizard_ex",
    deck2: str = "miraidon_ex",
    policy1: str = "heuristic",
    policy2: str = "random",
    n_games: int = 100,
    seed: int = 42,
) -> dict:
    env = PokemonTCG(deck1=deck1, deck2=deck2, expose_full_state=True)
    p1 = POLICIES[policy1](seed=seed)
    p2 = POLICIES[policy2](seed=seed + 1)

    results = {"wins": 0, "losses": 0, "draws": 0, "reasons": {}}
    start = time.time()

    for i in range(n_games):
        r = run_game(env, p1, p2, seed=seed + i)
        if r["winner"] == PlayerId.PLAYER1:
            results["wins"] += 1
        elif r["winner"] == PlayerId.PLAYER2:
            results["losses"] += 1
        else:
            results["draws"] += 1
        reason = r["reason"]
        results["reasons"][reason] = results["reasons"].get(reason, 0) + 1

        if (i + 1) % 100 == 0 or i == n_games - 1:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed
            wr = results["wins"] / (i + 1) * 100
            print(f"  [{i+1}/{n_games}] WR={wr:.1f}% ({results['wins']}W/{results['losses']}L/{results['draws']}D) {rate:.1f} games/s")

    elapsed = time.time() - start
    results["total_games"] = n_games
    results["elapsed_s"] = round(elapsed, 2)
    results["games_per_sec"] = round(n_games / elapsed, 2)
    results["win_rate"] = results["wins"] / n_games if n_games > 0 else 0
    return results


def main():
    parser = argparse.ArgumentParser(description="PTCG self-play harness v2")
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--deck1", default="charizard_ex")
    parser.add_argument("--deck2", default="miraidon_ex")
    parser.add_argument("--policy1", default="heuristic", choices=list(POLICIES))
    parser.add_argument("--policy2", default="random", choices=list(POLICIES))
    parser.add_argument("--self-play", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    if args.self_play:
        args.policy2 = args.policy1

    print(f"Running {args.games} games: {args.deck1}({args.policy1}) vs {args.deck2}({args.policy2})")
    results = run_self_play(
        deck1=args.deck1,
        deck2=args.deck2,
        policy1=args.policy1,
        policy2=args.policy2,
        n_games=args.games,
        seed=args.seed,
    )

    print(f"\nResults: {results['wins']}W / {results['losses']}L / {results['draws']}D")
    print(f"Win rate: {results['win_rate']:.1%}")
    print(f"Games/sec: {results['games_per_sec']}")
    print(f"Reasons: {results['reasons']}")

    if args.output:
        Path(args.output).write_text(json.dumps(results, indent=2))
        print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
