"""Regression: mandatory guardrails must run before belief ISMCTS."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scoring
from ismcts import BeliefWeightedHeuristic, create_belief_tracker
import bot

# Fixture modeled on real loss 8d90e2b0 seq 24: belief chose an attack
# while the turn's energy attachment was still available.
OBS = {
    "current": {
        "yourIndex": 0,
        "energyAttached": False,
        "players": [
            {
                "active": [{"id": 1006, "hp": 270, "maxHp": 270, "energies": []}],
                "bench": [{"id": 741, "hp": 70, "maxHp": 70, "energies": []}],
                "handCount": 4,
                "deckCount": 40,
                "discard": [],
                "prize": [None] * 6,
            },
            {
                "active": [{"id": 677, "hp": 80, "maxHp": 80, "energies": []}],
                "bench": [],
                "handCount": 5,
                "deckCount": 35,
                "discard": [],
                "prize": [None] * 6,
            },
        ],
        "select": {
            "option": [
                {"type": 8, "inPlayArea": 4, "inPlayIndex": 0},
                {"type": 8, "inPlayArea": 5, "inPlayIndex": 0},
                {"type": 13, "attackId": 1071},
                {"type": 14},
            ]
        },
    }
}
LEGAL = ["[0]", "[1]", "[2]", "[3]"]


def test_mandatory_action_exists_and_returns_attach():
    assert hasattr(scoring, "mandatory_action")
    action, reason = scoring.mandatory_action(OBS, LEGAL)
    assert action in ("[0]", "[1]")
    assert reason == "attach"


def test_belief_path_respects_mandatory_action():
    heuristic = BeliefWeightedHeuristic(create_belief_tracker({}), time_budget_ms=20)
    action, path = bot._choose_action_with_path(
        {"obs": OBS, "legalActions": LEGAL}, heuristic
    )
    assert action in ("[0]", "[1]")
    assert path in ("mandatory", "scoring")


def test_best_action_still_uses_mandatory_action():
    assert scoring.best_action(OBS, LEGAL) in ("[0]", "[1]")
