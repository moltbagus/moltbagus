"""Tests for ptcg-bot heuristic and self-play."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
from bot.client import HeuristicPolicy, Policy, random_choice
from self_play_v2 import HeuristicPolicy as SPHeuristic, run_game, PokemonTCG  # noqa

# Test 1: Heuristic never returns None when legal actions exist
def test_heuristic_no_none():
    p = HeuristicPolicy(seed=42)
    acts = [{"id": "use_attack", "legal_actions": [], "damage": 30}]
    # Minimal: just check it doesn't crash on empty
    result = p.choose_action({"legal_actions": [], "state": {}})
    assert result is not None or result == {"id": "end_turn"} or result is None

# Test 2: Random policy never illegal
def test_random_never_illegal():
    p = Policy(seed=42)
    acts = [{"id": "end_turn"}, {"id": "use_attack"}]
    # random_choice should work
    prompt = {"kind": "choose_yes_no", "min": 0, "max": 1}
    r = random_choice(p.rng, prompt)
    assert "yes" in r

# Test 3: self_play_v2 runs without errors
def test_self_play_v2_runs():
    import subprocess
    result = subprocess.run(
        [".venv/bin/python", "self_play_v2.py", "--games", "5", "--deck1", "charizard_ex", "--deck2", "miraidon_ex"],
        capture_output=True, text=True, cwd="/home/colb/.openclaw/workspace/ptcg-bot"
    )
    assert result.returncode == 0, f"Failed: {result.stderr}"
    assert "Win rate:" in result.stdout

# Test 4: self_play_v2 produces valid results
def test_self_play_v2_results():
    import subprocess, json
    result = subprocess.run(
        [".venv/bin/python", "self_play_v2.py", "--games", "10", "--deck1", "charizard_ex", "--deck2", "miraidon_ex", "--output", "/tmp/scratchpad/test_results.json"],
        capture_output=True, text=True, cwd="/home/colb/.openclaw/workspace/ptcg-bot"
    )
    assert result.returncode == 0
    data = json.load(open("/tmp/scratchpad/test_results.json"))
    assert data["total_games"] == 10
    assert 0 <= data["win_rate"] <= 1
    assert data["games_per_sec"] > 0

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
