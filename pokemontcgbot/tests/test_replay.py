"""Replay gate: the corpus must be scorable, and illegal choices must be zero."""

import json

import arena_config
import bot
import replay
import telemetry


def _obs():
    return {
        "current": {
            "turn": 3,
            "yourIndex": 0,
            "energyAttached": True,
            "players": [
                {
                    "active": [{"id": 245, "hp": 140, "energies": [5, 5, 5]}],
                    "bench": [{"id": 306, "hp": 140, "energies": []}],
                    "handCount": 3,
                    "prize": [1, 2, 3],
                },
                {
                    "active": [{"id": 96, "hp": 210, "energies": [5]}],
                    "bench": [],
                    "handCount": 2,
                    "prize": [1, 2, 3, 4, 5, 6],
                },
            ],
        },
        "select": {
            "type": 1,
            "context": 0,
            "minCount": 1,
            "maxCount": 1,
            "option": [{"type": 13, "attackId": 339}, {"type": 14}],
        },
    }


def _record(seq, chosen, legal, select_type=13, with_obs=True):
    """A minimal but honestly-shaped corpus record."""
    return {
        "ts": 1795187000000 + seq,
        "matchId": "m-1",
        "seq": seq,
        "turn": 3,
        "selectType": select_type,
        "chosen": chosen,
        "legalActions": legal,
        "obs": _obs() if with_obs else None,
        "policyVersion": arena_config.POLICY_VERSION,
    }


def test_replay_counts_changes_and_illegal_choices():
    records = [
        _record(1, "[0]", ["[0]", "[1]"]),          # policy picks "[0]"
        _record(2, "[1]", ["[0]", "[1]"]),          # policy picks "[0]" -> change
        _record(3, "[7]", ["[0]", "[1]"]),          # not legal -> illegal
    ]
    report = replay.replay(records, choose=lambda obs, legal: legal[0])
    assert report["records"] == 3
    assert report["scored"] == 3
    assert report["illegal"] == 1
    assert report["changed"] == 2
    assert report["passed"] is False
    assert report["bySelectType"]["13"]["n"] == 3


def test_replay_passes_a_clean_corpus():
    records = [_record(i, "[0]", ["[0]", "[1]"]) for i in range(1, 5)]
    report = replay.replay(records, choose=lambda obs, legal: "[0]")
    assert report["illegal"] == 0
    assert report["changed"] == 0
    assert report["passed"] is True


def test_replay_marks_records_without_obs_unscorable():
    records = [_record(1, "[0]", ["[0]"], with_obs=False)]
    report = replay.replay(records)
    assert report["scored"] == 0
    assert report["unscorable"] == 1
    assert report["passed"] is False


def test_replay_since_filter():
    records = [_record(1, "[0]", ["[0]"]), dict(_record(2, "[0]", ["[0]"]), ts=1795187000000 + 10_000)]
    report = replay.replay(records, since_ms=1795187000000 + 5_000)
    assert report["records"] == 1


def test_default_policy_replays_a_recorded_decision():
    """A record produced by telemetry must be scorable by the live policy."""
    entry = {
        "matchId": "m-2",
        "seq": 5,
        "legalActions": ["[0]", "[1]"],
        "obs": _obs(),
    }
    record = telemetry.build_record(entry, "[0]", 0.5)
    report = replay.replay([record])
    assert report["scored"] == 1
    assert report["illegal"] == 0
    assert report["passed"] is True


def test_telemetry_stores_a_replayable_observation():
    entry = {"matchId": "m-3", "seq": 1, "legalActions": ["[0]", "[1]"], "obs": _obs()}
    record = telemetry.build_record(entry, "[0]", 0.1)
    stored = record["obs"]
    assert isinstance(stored, dict)
    assert stored["select"]["option"] == _obs()["select"]["option"]
    assert stored["current"]["players"][0]["active"][0]["id"] == 245
    assert stored["current"]["players"][1]["handCount"] == 2
    assert "logs" not in stored["current"]  # the bulky turn history is dropped


def test_cli_fails_on_an_illegal_corpus(tmp_path, capsys):
    path = tmp_path / "corpus.jsonl"
    rows = [_record(1, "[9]", ["[0]", "[1]"])]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    code = replay.main(["--path", str(path)])
    assert code == 1
    out = capsys.readouterr().out
    assert "illegal       1" in out
    assert "FAIL" in out


def test_cli_writes_evidence(tmp_path):
    path = tmp_path / "corpus.jsonl"
    path.write_text(json.dumps(_record(1, "[0]", ["[0]", "[1]"])) + "\n", encoding="utf-8")
    evidence = tmp_path / "evidence" / "replay.json"
    code = replay.main(["--path", str(path), "--json-out", str(evidence)])
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert code == 0
    assert payload["illegal"] == 0
    assert payload["policyVersion"] == arena_config.POLICY_VERSION
