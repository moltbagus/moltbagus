"""Regression: mandatory guardrails must run before belief ISMCTS."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot
import scoring
import telemetry
from ismcts import BeliefWeightedHeuristic, create_belief_tracker

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


class StubBelief:
    """Belief path that always answers with an attack, as the bug did."""

    def __init__(self, choice="[2]"):
        self.search = self
        self.choice = choice
        self.updates = 0

    def update_belief_from_obs(self, obs):
        self.updates += 1

    def choose(self, obs, legal):
        return self.choice


def _replace_options(obs, options, legal=None, energy_attached=False):
    out = copy.deepcopy(obs)
    out["current"]["select"]["option"] = options
    out["current"]["energyAttached"] = energy_attached
    return out, legal or ["[%d]" % i for i in range(len(options))]


def test_mandatory_action_prefers_active_attach():
    action, reason = scoring.mandatory_action(OBS, LEGAL)
    assert (action, reason) == ("[0]", "attach")


def test_belief_path_respects_mandatory_action_and_syncs_belief():
    heuristic = StubBelief("[2]")
    action, path = bot._choose_action_with_path(
        {"obs": OBS, "legalActions": LEGAL}, heuristic
    )
    assert action == "[0]"
    assert path == "mandatory"
    assert heuristic.updates == 1


def test_mandatory_path_is_attributed_in_telemetry(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "HAS_BELIEF", True)
    path = tmp_path / "mandatory.jsonl"
    monkeypatch.setenv("ARENA_TELEMETRY_PATH", str(path))
    bot.choose_action(
        {"obs": OBS, "legalActions": LEGAL, "matchId": "m", "seq": 1},
        StubBelief("[2]"),
    )
    record = telemetry.read(path)[-1]
    assert record["chosen"] == "[0]"
    assert record["policyPath"] == "mandatory"
    assert record["policyVersion"] == bot.POLICY_VERSION


def test_malformed_obs_does_not_fall_through_to_belief():
    bad = copy.deepcopy(OBS)
    bad["current"]["select"]["option"] = {"0": {"type": 8}}
    heuristic = StubBelief("[2]")
    action, path = bot._choose_action_with_path(
        {"obs": bad, "legalActions": LEGAL}, heuristic
    )
    assert path == "fallback"
    assert action == LEGAL[0]
    assert heuristic.updates == 1


def test_evolve_beats_belief_attack_when_energy_already_attached():
    obs, legal = _replace_options(
        OBS,
        [
            {"type": 9, "inPlayArea": 4, "inPlayIndex": 0},
            {"type": 13, "attackId": 1071},
            {"type": 14},
        ],
        energy_attached=True,
    )
    action, path = bot._choose_action_with_path(
        {"obs": obs, "legalActions": legal}, StubBelief("[1]")
    )
    assert (action, path) == ("[0]", "mandatory")


def test_empty_bench_play_beats_belief_attack():
    obs, legal = _replace_options(
        OBS,
        [
            {"type": 7, "index": 0},
            {"type": 13, "attackId": 1071},
            {"type": 14},
        ],
        energy_attached=True,
    )
    obs["current"]["players"][0]["bench"] = []
    action, path = bot._choose_action_with_path(
        {"obs": obs, "legalActions": legal}, StubBelief("[1]")
    )
    assert (action, path) == ("[0]", "mandatory")


def test_zero_damage_attack_play_beats_belief_attack():
    obs, legal = _replace_options(
        OBS,
        [
            {"type": 7, "index": 0},
            {"type": 13, "attackId": 423},
            {"type": 14},
        ],
        energy_attached=True,
    )
    action, path = bot._choose_action_with_path(
        {"obs": obs, "legalActions": legal}, StubBelief("[1]")
    )
    assert (action, path) == ("[0]", "mandatory")


def test_energy_already_attached_skips_attach_guardrail():
    obs, legal = _replace_options(
        OBS,
        [
            {"type": 8, "inPlayArea": 4, "inPlayIndex": 0},
            {"type": 13, "attackId": 1071},
            {"type": 14},
        ],
        energy_attached=True,
    )
    assert scoring.mandatory_action(obs, legal) is None
    action, path = bot._choose_action_with_path(
        {"obs": obs, "legalActions": legal}, StubBelief("[1]")
    )
    assert (action, path) == ("[1]", "belief")


def test_best_action_still_uses_mandatory_action():
    assert scoring.best_action(OBS, LEGAL) == "[0]"
