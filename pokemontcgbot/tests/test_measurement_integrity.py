"""Measurement integrity after the belief ISMCTS policy change."""

import json
import subprocess

import arena_config
import telemetry
import wr_report


def test_policy_version_is_bumped():
    assert arena_config.POLICY_VERSION == "l0-2026-11-23-belief-ismcts"


def test_telemetry_uses_call_time_policy_version(monkeypatch):
    monkeypatch.setattr(arena_config, "POLICY_VERSION", "test-policy-v1")
    entry = {
        "obs": {
            "current": {
                "yourIndex": 0,
                "players": [{}, {}],
                "select": {"type": 0, "option": [{"type": 14}]},
            }
        },
        "legalActions": ["[0]"],
    }
    record = telemetry.build_record(entry, "[0]", 1.0, policy_path="belief")
    assert record is not None
    assert record["policyVersion"] == "test-policy-v1"


def test_wr_report_binds_to_pm2(monkeypatch):
    payload = json.dumps(
        [
            {
                "name": "tcg-bot",
                "pid": 4242,
                "pm2_env": {"created_at": 1795407635478, "status": "online"},
            }
        ]
    )

    def fake_output(*args, **kwargs):
        if args and args[0] == ["pm2", "jlist"]:
            return payload
        raise subprocess.SubprocessError("not used")

    monkeypatch.setattr(wr_report.subprocess, "check_output", fake_output)
    pid, start = wr_report._service_binding()
    assert pid == "4242"
    assert start.startswith("2026-")


def test_active_precommit_registers_new_version():
    from pathlib import Path

    doc = (
        Path(__file__).resolve().parents[1]
        / "docs/precommit/2026-11-23-belief-ismcts-rebaseline.md"
    ).read_text()
    assert arena_config.POLICY_VERSION in doc
    assert "900" in doc
    assert "43.5" in doc
