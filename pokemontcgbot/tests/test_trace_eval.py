"""Proof-first tests for TRACE evaluator, A2A envelope, and tick chain."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import trace_eval


FIELDS = {"matchId", "seq", "chosen", "policyPath", "policyVersion", "latencyMs", "obs", "state"}
EVIDENCE_FIELDS = {"command", "commit", "expected", "observed", "counts", "exit_code"}


def _record(mid="m1", seq=1, chosen="[0]", legal=("[0]", "[1]"), policy="l1-2026-11-24-guardrail-first"):
    return {
        "matchId": mid, "seq": seq, "ts": 1795000000000 + seq,
        "chosen": chosen, "legalActions": list(legal), "policyPath": "scoring",
        "policyVersion": policy, "latencyMs": 5.0,
        "selectType": 0,
        "obs": {"current": {"yourIndex": 0, "energyAttached": True,
                            "players": [{}, {}],
                            "select": {"option": [{"type": 14}, {"type": 14}]}}},
        "state": {"active": {"id": 1, "hp": 100, "energy": 0}, "bench": [], "prizes": 6},
    }


def _write_corpus(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def test_r1_trace_identity_and_parent(tmp_path):
    corpus = _write_corpus(tmp_path / "c.jsonl", [_record(seq=1), _record(seq=2)])
    report = trace_eval.evaluate_corpus(corpus, active_version="l1-2026-11-24-guardrail-first")
    traces = report["traces"]
    assert traces[0]["traceId"] == "m1:1"
    assert traces[0]["parentTraceId"] is None
    assert traces[1]["parentTraceId"] == "m1:1"
    assert FIELDS <= set(traces[0])


def test_ae1_mandatory_bypass_is_blocking(tmp_path):
    record = _record()
    record["obs"]["current"]["energyAttached"] = False
    record["obs"]["current"]["select"]["option"] = [{"type": 8, "inPlayArea": 4, "inPlayIndex": 0}, {"type": 13, "attackId": 1071}]
    record["chosen"] = "[1]"
    record["legalActions"] = ["[0]", "[1]"]
    corpus = _write_corpus(tmp_path / "c.jsonl", [record])
    report = trace_eval.evaluate_corpus(corpus, active_version="l1-2026-11-24-guardrail-first")
    assert report["traces"][0]["mandatoryActionEligible"] is True
    assert report["traces"][0]["mandatoryActionSatisfied"] is False
    assert any(f["class"] == "MANDATORY_ACTION_BYPASS" and f["severity"] == "blocking" for f in report["findings"])
    assert trace_eval.gate_b(report) == "FAIL"


def test_ae4_missing_corpus_is_not_run(tmp_path):
    report = trace_eval.evaluate_corpus(tmp_path / "absent.jsonl", active_version="v")
    assert report["status"] == "NOT_RUN"
    assert "absent.jsonl" in report["observed"]
    assert trace_eval.gate_b(report) == "NOT_RUN"


def test_r3_unknown_version_has_null_eligibility(tmp_path):
    corpus = _write_corpus(tmp_path / "c.jsonl", [_record(policy="legacy")])
    report = trace_eval.evaluate_corpus(corpus, active_version="v")
    assert report["traces"][0]["mandatoryActionEligible"] is None


def test_illegal_action_finding(tmp_path):
    corpus = _write_corpus(tmp_path / "c.jsonl", [_record(chosen="[3]")])
    report = trace_eval.evaluate_corpus(corpus, active_version="l1-2026-11-24-guardrail-first")
    assert any(f["class"] == "ILLEGAL_ACTION" for f in report["findings"])


def test_r9_evidence_fields(tmp_path):
    corpus = _write_corpus(tmp_path / "c.jsonl", [_record()])
    out = tmp_path / "evidence.json"
    rc = trace_eval.write_evidence(corpus, out, active_version="l1-2026-11-24-guardrail-first")
    ev = json.loads(out.read_text())
    assert rc in (0, 1)
    assert EVIDENCE_FIELDS <= set(ev)


ENVELOPE = {
    "task_id": "T1", "from_agent": "lead", "to_agent": "builder",
    "base_commit": None, "artifact_path": "docs/plans/plan.md",
    "requirement_ids": ["R1"], "findings": [], "checks": [],
    "blockers": [], "next_action": "implement",
}


def _validate_handoff(envelope, head="HEAD", root=ROOT):
    """Use repo-relative artifact paths while validating."""
    artifact = envelope.get("artifact_path")
    if artifact and Path(artifact).exists():
        return trace_eval.validate_handoff(envelope, head=head)
    relative = artifact
    try:
        relative = str(Path(artifact).relative_to(root))
    except ValueError:
        pass
    adjusted = dict(envelope, artifact_path=relative)
    return trace_eval.validate_handoff(adjusted, head=head)


def test_ae2_stale_envelope_rejected(tmp_path):
    target = ROOT / "docs/plans/plan.md"
    target.write_text("x")
    try:
        env = dict(ENVELOPE, base_commit="0000000000000000000000000000000000000000")
        result = _validate_handoff(env, head="HEAD")
        assert result["status"] == "REJECT"
        assert any(f["class"] == "SCHEMA_INVALID" for f in result["findings"])
    finally:
        target.unlink()


def test_valid_envelope_accepted(tmp_path):
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    target = ROOT / "docs/plans/plan.md"
    target.write_text("x")
    check = {
        "command": "python3 -m py_compile trace_eval.py",
        "commit": head, "expected": "compile OK", "observed": "compile OK",
        "counts": {c: 0 for c in trace_eval.CLASSES}, "exit_code": 0,
    }
    try:
        env = dict(ENVELOPE, base_commit=head, checks=[check])
        result = _validate_handoff(env, head=head)
        assert result["status"] == "PASS"
    finally:
        target.unlink()


def test_fabricated_check_rejected(tmp_path):
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    target = ROOT / "docs/plans/plan.md"
    target.write_text("x")
    check = {
        "command": "this-command-does-not-exist", "commit": head,
        "expected": "PASS", "observed": "PASS",
        "counts": {c: 0 for c in trace_eval.CLASSES}, "exit_code": 0,
    }
    try:
        env = dict(ENVELOPE, base_commit=head, checks=[check])
        result = _validate_handoff(env, head=head)
        assert result["status"] == "REJECT"
    finally:
        target.unlink()


def test_gate_a_enrichment():
    plan = ROOT / "docs/plans/2026-11-24-2105-feat-trace-a2a-loop-plan.md"
    assert trace_eval.gate_a(plan) == "PASS"


def test_gate_c_rejects_stale_tip(tmp_path):
    env = dict(ENVELOPE, base_commit="a")
    ticks = [{"commit": "old", "state": "VERIFYING"}]
    assert trace_eval.gate_c(env, ticks, head="new") == "BLOCKED"


def test_display_path_normalizes_home():
    p = Path.home() / ".arena-does-not-exist.jsonl"
    assert trace_eval._display_path(p) == "~/.arena-does-not-exist.jsonl"


def test_handoff_with_blocking_finding_rejected(tmp_path):
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    target = ROOT / "docs/plans/plan.md"
    target.write_text("x")
    try:
        blocker = {
            "traceId": "t", "class": "MANDATORY_ACTION_BYPASS", "severity": "blocking",
            "requirementId": "R2", "evidence": "historical bypass",
        }
        env = dict(ENVELOPE, base_commit=head, findings=[blocker], blockers=["G-B FAIL"])
        result = _validate_handoff(env, head=head)
        assert result["status"] == "REJECT"
    finally:
        target.unlink()


def test_ae3_drift_on_unchanged_commit(tmp_path):
    valid = {"requirement_ids": ["R1"], "findings": [], "checks": [], "blockers": []}
    (tmp_path / "e1.json").write_text(json.dumps(valid))
    head = "abc123"
    t0 = trace_eval.new_tick("root", None, "T1", head, "VERIFYING", "e1.json", "e1.json", None)
    chain = tmp_path / "ticks.jsonl"
    chain.write_text(json.dumps(t0) + "\n")
    t1 = trace_eval.new_tick("next", "root", "T1", head, "DONE", "e1.json", "e1.json", None)
    result = trace_eval.append_tick(t1, chain, head=head)
    assert result["status"] == "BLOCKED"
    assert any(f["class"] == "SCHEMA_INVALID" for f in result["findings"])


def test_root_tick_and_append_with_new_evidence(tmp_path):
    e1 = {"requirement_ids": ["R1"], "findings": [], "checks": [], "blockers": [],
          "gate_b": "PASS", "status": "RUN"}
    e2 = dict(e1, gate_b="PASS")
    (tmp_path / "e1.json").write_text(json.dumps(e1))
    (tmp_path / "e2.json").write_text(json.dumps(e2))
    chain = tmp_path / "ticks.jsonl"
    head = "abc123"
    t0 = trace_eval.new_tick("root", None, "T1", head, "IMPLEMENTING", "e1.json", "e1.json", None)
    assert trace_eval.append_tick(t0, chain, head=head)["status"] == "PASS"
    t1 = trace_eval.new_tick("next", "root", "T1", head, "IMPLEMENTING", "e2.json", "e2.json", None)
    assert trace_eval.append_tick(t1, chain, head=head)["status"] == "PASS"
    assert len(chain.read_text().splitlines()) == 2
