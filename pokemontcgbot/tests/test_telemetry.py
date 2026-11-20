"""Telemetry records the decision, never changes it (world-class spec section 7)."""

import json

import pytest

import arena_config
import bot
import telemetry


def _obs():
    """Observation shaped like the live remote obs (see spec section 2)."""
    return {
        "current": {
            "turn": 16,
            "yourIndex": 0,
            "energyAttached": True,
            "players": [
                {
                    "active": [{"id": 305, "hp": 70, "energies": [5]}],
                    "bench": [
                        {"id": 741, "hp": 60, "energies": []},
                        {"id": 305, "hp": 70, "energies": [5]},
                    ],
                    "handCount": 5,
                    "prize": [1, 2, 3, 4],
                },
                {
                    "active": [{"id": 63, "hp": 240, "energies": [5, 5, 5]}],
                    "bench": [],
                    "handCount": 4,
                    "prize": [1, 2, 3, 4, 5],
                },
            ],
            "select": {
                "type": 1,
                "context": 0,
                "minCount": 1,
                "maxCount": 1,
                "option": [
                    {"type": 7, "index": 0},
                    {"type": 9, "index": 1, "inPlayArea": 4},
                    {"type": 13, "attackId": 423},
                    {"type": 14},
                ],
            },
        }
    }


def _entry():
    return {
        "matchId": "abb9ce3b-0000-4000-8000-000000000000",
        "seq": 42,
        "deadline": 1795157007129,
        "legalActions": ["[0]", "[1]", "[2]", "[3]"],
        "obs": _obs(),
    }


def test_build_record_captures_the_decision():
    rec = telemetry.build_record(_entry(), "[1]", 12.5)
    assert rec is not None
    assert rec["matchId"].startswith("abb9ce3b")
    assert rec["seq"] == 42
    assert rec["turn"] == 16
    assert rec["selectType"] == 1
    assert rec["context"] == 0
    assert rec["nOptions"] == 4
    assert rec["nLegal"] == 4
    assert rec["chosen"] == "[1]"
    assert rec["chosenTypes"] == [9]  # evolution, not the default unknown branch
    assert rec["latencyMs"] == 12.5
    assert rec["policyVersion"] == arena_config.POLICY_VERSION


def test_build_record_keeps_the_board_and_the_alternatives():
    rec = telemetry.build_record(_entry(), "[2]", 3.0)
    state = rec["state"]
    assert state["active"] == {"id": 305, "hp": 70, "energy": 1}
    assert state["bench"] == [[741, 0], [305, 1]]
    assert state["oppActive"] == {"id": 63, "hp": 240, "energy": 3}
    assert state["handCount"] == 5
    assert state["prizes"] == 4
    # Every legal action is scored, so a replay can compute the choice delta.
    actions = [c["action"] for c in rec["candidates"]]
    assert actions == ["[0]", "[1]", "[2]", "[3]"]
    assert all(isinstance(c["score"], float) for c in rec["candidates"])


def test_build_record_survives_unusable_input():
    assert telemetry.build_record(None, "[0]", 1.0) is None
    assert telemetry.build_record({}, "[0]", 1.0) is not None  # empty but shaped
    junk = telemetry.build_record({"obs": "not-an-obs", "legalActions": 7}, None, 0.0)
    assert junk is not None
    assert junk["state"]["active"] is None
    assert junk["chosenTypes"] == []


def test_out_of_range_choice_does_not_crash():
    rec = telemetry.build_record(_entry(), "[99]", 1.0)
    assert rec["chosenTypes"] == []


def test_record_appends_jsonl_and_reads_back(tmp_path):
    path = tmp_path / "decisions.jsonl"
    assert telemetry.record(_entry(), "[1]", 4.0, path=path) is True
    assert telemetry.record(_entry(), "[2]", 5.0, path=path) is True
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["chosen"] == "[1]"
    records = telemetry.read(path)
    assert [r["chosen"] for r in records] == ["[1]", "[2]"]


def test_record_never_raises(tmp_path):
    assert telemetry.record(None, None, 0.0, path=tmp_path / "x.jsonl") is False
    # A directory where the file should be is unwritable-but-silent, not fatal.
    assert telemetry.record(_entry(), "[0]", 0.0, path=tmp_path) is False


def test_choose_action_returns_the_same_choice_and_records_once(monkeypatch, tmp_path):
    path = tmp_path / "decisions.jsonl"
    seen = []

    def fake_record(entry, chosen, latency_ms, *args, **kwargs):
        seen.append((entry, chosen, latency_ms))
        return True

    monkeypatch.setattr(telemetry, "record", fake_record)
    entry = _entry()
    expected = bot._choose_action(entry, None)
    chosen = bot.choose_action(entry, None)
    assert chosen == expected
    assert len(seen) == 1
    assert seen[0][1] == expected
    assert seen[0][2] >= 0.0


def test_choose_action_is_unchanged_when_telemetry_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(telemetry, "record", boom)
    entry = _entry()
    assert bot.choose_action(entry, None) == bot._choose_action(entry, None)


def test_telemetry_is_optional(monkeypatch):
    """A live copy without the module must still answer decisions."""
    monkeypatch.setattr(bot, "telemetry", None)
    entry = _entry()
    assert bot.choose_action(entry, None) == bot._choose_action(entry, None)
