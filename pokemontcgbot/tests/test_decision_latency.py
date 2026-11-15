"""Decision latency checks — Lauren Tan principle.

Measures choose_action() execution time and fails if > 1.5s.
Converts "timeout_forfeit" memory note into a deterministic check.
"""
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

MAX_LATENCY_S = 1.5


def test_choose_action_latency_no_belief():
    """Damage-based heuristic must complete in < 1.5s."""
    import bot
    entry = {
        "legalActions": ["[0]", "[1]", "[2]", "[3]"],
        "obs": {"select": {"option": [
            {"damage": 30}, {"damage": 40}, {"damage": 0}, {"damage": 20}
        ]}},
    }
    start = time.monotonic()
    action = bot.choose_action(entry)
    elapsed = time.monotonic() - start
    assert elapsed < MAX_LATENCY_S, f"choose_action took {elapsed:.3f}s > {MAX_LATENCY_S}s"
    assert action is not None


def test_choose_action_latency_with_belief():
    """Belief-weighted heuristic must complete in < 1.5s."""
    try:
        from ismcts import BeliefWeightedHeuristic
        from belief import BeliefTracker
    except ImportError:
        return  # skip if modules not available

    archetype = {625: 4, 328: 4, 299: 4, 39: 4, 390: 4, 1: 40}
    tracker = BeliefTracker(archetype)
    tracker.observe_hand_size(7)
    tracker.observe_deck_size(53)
    heuristic = BeliefWeightedHeuristic(tracker, time_budget_ms=1000)

    entry = {
        "legalActions": ["[0]", "[1]", "[2]", "[3]"],
        "obs": {"select": {"option": [
            {"damage": 30}, {"damage": 40}, {"damage": 0}, {"damage": 20}
        ]}},
    }
    start = time.monotonic()
    import bot
    action = bot.choose_action(entry, belief_heuristic=heuristic)
    elapsed = time.monotonic() - start
    assert elapsed < MAX_LATENCY_S, f"Belief choose took {elapsed:.3f}s > {MAX_LATENCY_S}s"
    assert action is not None
