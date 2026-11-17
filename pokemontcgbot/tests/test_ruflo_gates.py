from datetime import datetime, timedelta, timezone

from ruflo_tcg import MatchResult, RufloTCG, compute_bayesian_evidence


def age_level(ruflo, hours=2):
    entered = datetime.now(timezone.utc) - timedelta(hours=hours)
    ruflo.state.entered_at = entered.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_bayesian_evidence_edges():
    assert compute_bayesian_evidence(0.60, 100, z_threshold=1.0)["passed"] is True
    assert compute_bayesian_evidence(0.50, 100, z_threshold=1.0)["passed"] is False
    assert compute_bayesian_evidence(None, 0)["passed"] is False


def test_promotes_at_l1_gate(tmp_path):
    ruflo = RufloTCG(state_dir=tmp_path)
    age_level(ruflo)
    for _ in range(10):
        ruflo.observe_match(MatchResult(result="win"))

    decision = ruflo.check_promotion()

    assert decision.action == "promote"
    assert ruflo.state.current_level == 2
    assert decision.gates_failed == {}


def test_holds_below_match_minimum(tmp_path):
    ruflo = RufloTCG(state_dir=tmp_path)
    age_level(ruflo)
    for _ in range(9):
        ruflo.observe_match(MatchResult(result="win"))

    decision = ruflo.check_promotion()

    assert decision.action == "hold"
    assert ruflo.state.current_level == 1
    assert "matches_min" in decision.gates_failed


def test_forfeit_streak_demotes(tmp_path):
    ruflo = RufloTCG(state_dir=tmp_path)
    ruflo.state.current_level = 2
    age_level(ruflo)
    for _ in range(3):
        ruflo.observe_match(MatchResult(result="forfeit"))

    decision = ruflo.check_promotion()

    assert decision.action == "demote"
    assert ruflo.state.current_level == 1


def test_timeout_streak_demotes(tmp_path):
    ruflo = RufloTCG(state_dir=tmp_path)
    ruflo.state.current_level = 2
    age_level(ruflo)
    for _ in range(5):
        ruflo.observe_match(MatchResult(result="timeout"))

    decision = ruflo.check_promotion()

    assert decision.action == "demote"
    assert ruflo.state.current_level == 1
