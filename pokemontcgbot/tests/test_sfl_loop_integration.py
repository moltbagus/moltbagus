"""Integration between RufloTCG and the durable SFL correction loop.
"""
import logging
from unittest import mock

from ruflo_tcg import RufloTCG


def test_record_failure_injects_persistent_rule(tmp_path):
    ruflo = RufloTCG(state_dir=tmp_path)
    ruflo.record_failure(
        "guardrail_bypass",
        "R-SFL-I1",
        "evidence",
        severity="critical",
        rule_text="Never override mandatory_action.",
    )
    rules = ruflo.active_rules()
    assert any("R-SFL-I1" in r and "mandatory_action" in r for r in rules)
    assert (tmp_path / "corrections/tcg/failures.jsonl").exists()
    # The existing sqlite log is still written.
    rows = ruflo.db.execute(
        "SELECT rule_id FROM sfl_failures WHERE rule_id='R-SFL-I1'"
    ).fetchall()
    assert len(rows) == 1


def test_default_rule_text_keeps_legacy_call_compatible(tmp_path):
    ruflo = RufloTCG(state_dir=tmp_path)
    ruflo.record_failure("timeout_streak", "R-SFL-I0", "five timeouts")
    assert any("R-SFL-I0" in r for r in ruflo.active_rules())


def test_verify_and_report_are_separate_from_outcome(tmp_path):
    ruflo = RufloTCG(state_dir=tmp_path)
    ruflo.record_failure("x", "R-SFL-I2", "e", rule_text="Keep one rule source.")
    ruflo.verify("R-SFL-I2", "dedupe", True, "loss", "lost but rule held")
    ruflo.verify("R-SFL-I2", "path", False, "win", "won by luck")
    assert ruflo.verification_report() == {
        "checks": 2,
        "rule_failures": 1,
        "outcome_wins": 1,
    }
    assert (tmp_path / "corrections/tcg/verify.json").exists()


def test_unknown_rule_verification_rejected_through_ruflo(tmp_path):
    ruflo = RufloTCG(state_dir=tmp_path)
    try:
        ruflo.verify("R-MISSING", "x", True, "win", "e")
    except ValueError as exc:
        assert "R-MISSING" in str(exc)
    else:
        raise AssertionError("unknown rule must be rejected")


def test_rules_persist_across_store_instances(tmp_path):
    first = RufloTCG(state_dir=tmp_path)
    first.record_failure("x", "R-SFL-I3", "e", rule_text="Rule survives restart.")
    second = RufloTCG(state_dir=tmp_path)
    assert any(
        "R-SFL-I3" in r and "survives restart" in r for r in second.active_rules()
    )
    # Verification against a rule loaded from disk is accepted.
    second.verify("R-SFL-I3", "persist", True, "win", "reloaded")
    assert second.verification_report()["checks"] == 1


def test_hardening_record_failure_never_raises_on_correction_error(tmp_path, caplog):
    ruflo = RufloTCG(state_dir=tmp_path)
    with mock.patch.object(
        ruflo.corrections, "record_failure", side_effect=OSError("disk full")
    ):
        with caplog.at_level(logging.WARNING, logger="ruflo_tcg"):
            ruflo.record_failure("x", "R-SAFE", "e", rule_text="rule")

    # The authoritative sqlite commit still happened.
    rows = ruflo.db.execute(
        "SELECT rule_id FROM sfl_failures WHERE rule_id='R-SAFE'"
    ).fetchall()
    assert len(rows) == 1
    assert any("correction write failed" in rec.message for rec in caplog.records)


def test_hardening_startup_survives_broken_correction_dir(tmp_path):
    (tmp_path / "corrections").mkdir()
    (tmp_path / "corrections" / "tcg").write_text("blocker", encoding="utf-8")
    ruflo = RufloTCG(state_dir=tmp_path)  # must not raise on startup
    ruflo.record_failure("x", "R-START", "e", rule_text="still logged in sqlite")
    rows = ruflo.db.execute(
        "SELECT rule_id FROM sfl_failures WHERE rule_id='R-START'"
    ).fetchall()
    assert len(rows) == 1
