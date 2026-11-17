"""Self-play harness for PTCG bot using ptcg-engine (gemelom/ptcg-engine).

Runs thousands of games between heuristic agents for fast policy evaluation.
Uses the engine's Gym-like reset()/step() API with masked observations.

Usage:
    python self_play.py --games 100 --deck1 charizard_ex --deck2 miraidon_ex
    python self_play.py --games 1000 --deck1 charizard_ex --deck2 charizard_ex --self-play
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

# Add ptcg-engine to path
sys.path.insert(0, "/home/colb/ptcg-lab/src")

from ptcg.core.envs import PokemonTCG
from ptcg.core.enums import PlayerId
from ptcg.core.action import Action

# ---------------------------------------------------------------- policy base
class Policy:
    name = "base"

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def choose(self, obs, info) -> Action:
        raise NotImplementedError


class RandomPolicy(Policy):
    name = "random"

    def choose(self, obs, info) -> Action:
        actions = info.get("raw_available_actions", [])
        if not actions:
            return None
        return self.rng.choice(actions)


class HeuristicPolicy(Policy):
    """Improved heuristic: abilities -> bench -> search -> energy -> attacks (KO-first)."""
    name = "heuristic"

    def choose(self, obs, info) -> Action:
        actions = info.get("raw_available_actions", [])
        if not actions:
            return None

        from ptcg.core.enums import ActionType

        # 1. Abilities first
        abilities = [a for a in actions if a.actionType in (ActionType.USE_ABILITY_ACTION, ActionType.USE_STADIUM_ACTION)]
        if abilities:
            return abilities[0]

        # 2. Bench discipline: bench basics if bench < 3
        state = info.get("full_state") or {}
        me = state.player1 if hasattr(state, "player1") else None
        bench_count = len(me.bench) if me and hasattr(me, "bench") else 0
        plays = [a for a in actions if a.actionType == ActionType.PLAY_POKEMON_ACTION]
        if plays and bench_count < 3:
            return plays[0]

        # 3. Search/consistency (items)
        items = [a for a in actions if a.actionType == ActionType.USE_ITEM_ACTION]
        if items:
            return items[0]

        # 4. Supporters
        supporters = [a for a in actions if a.actionType == ActionType.USE_SUPPORTER_ACTION]
        if supporters:
            return supporters[0]

        # 5. Energy attachment
        energies = [a for a in actions if a.actionType == ActionType.ATTACH_ENERGY_ACTION]
        if energies:
            return energies[0]

        # 6. Attacks: prefer KO
        attacks = [a for a in actions if a.actionType == ActionType.ATTACK_ACTION]
        if attacks:
            return attacks[-1]

        # 7. Evolutions
        evos = [a for a in actions if a.actionType == ActionType.EVOLVE_POKEMON_ACTION]
        if evos:
            return evos[0]

        # 8. Play remaining
        if plays:
            return plays[0]

        # 9. Fallback
        return next((a for a in actions if a.actionType == ActionType.PASS_TURN), actions[0])


POLICIES = {"random": RandomPolicy, "heuristic": HeuristicPolicy, "heuristic-v2": HeuristicPolicy}


def run_game(env, p1_policy, p2_policy, seed=None) -> dict:
    """Run a single game and return result."""
    if seed is not None:
        env.set_seed(seed)

    obs, reward, done, info = env.reset()
    turn = 0
    actions = 0

    while not done:
        # Determine current player from obs
        # PTCGEnv uses generator pattern; obs is from current player's perspective
        policy = p1_policy if turn % 2 == 0 else p2_policy
        action = policy.choose(obs, info)
        if action is None:
            # No legal actions — shouldn't happen
            break
        obs, reward, done, info = env.step(action)
        actions += 1
        turn += 1
        if turn > 1000:  # safety valve
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
    """Run N self-play games and return aggregate stats."""
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
    parser = argparse.ArgumentParser(description="PTCG self-play harness")
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--deck1", default="charizard_ex")
    parser.add_argument("--deck2", default="miraidon_ex")
    parser.add_argument("--policy1", default="heuristic", choices=list(POLICIES))
    parser.add_argument("--policy2", default="random", choices=list(POLICIES))
    parser.add_argument("--self-play", action="store_true", help="Same policy vs itself")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=None, help="Save results to JSON file")
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
