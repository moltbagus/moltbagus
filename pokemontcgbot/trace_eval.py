"""Offline TRACE evaluator, A2A envelope validator, and loop tick chain.

This module performs no network calls, reads no credentials, never starts a
bot, and never changes a live process. It is the offline evaluator described in
docs/plans/2026-11-24-2105-feat-trace-a2a-loop-plan.md.

Usage:
  python3 trace_eval.py --corpus PATH --json-out PATH
  python3 trace_eval.py validate-handoff --envelope PATH
  python3 trace_eval.py append-tick --tick PATH --chain PATH
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import arena_config
import scoring

CLASSES = (
    "ILLEGAL_ACTION",
    "MANDATORY_ACTION_BYPASS",
    "ATTRIBUTION_MISMATCH",
    "UNSCORABLE_RECORD",
    "POLICY_DELTA",
    "LATENCY_REGRESSION",
    "SCHEMA_INVALID",
)
TRACE_FIELDS = ("matchId", "seq", "chosen", "policyPath", "policyVersion", "latencyMs", "obs", "state")
LATENCY_BOUND_MS = 1500.0
KNOWN_VERSIONS = ("l0-2026-11-23-belief-ismcts", "l1-2026-11-24-guardrail-first")
CLASSIFICATION_CURRENT = "current-policy"
CLASSIFICATION_HISTORICAL = "historical-unscorable-known-policy"
STATES = ("REQUIREMENTS", "PLANNING", "IMPLEMENTING", "VERIFYING", "BLOCKED", "DONE")
ENVELOPE_FIELDS = (
    "task_id", "from_agent", "to_agent", "base_commit", "artifact_path",
    "requirement_ids", "findings", "checks", "blockers", "next_action",
)
TICK_FIELDS = (
    "tick_id", "parent_tick_id", "task_id", "commit", "state",
    "findings_ref", "checks_ref", "handoff_ref", "created_at",
)


def _finding(class_name: str, severity: str, trace_id: str, requirement_id: str, evidence: str) -> Dict[str, Any]:
    return {
        "traceId": trace_id,
        "class": class_name,
        "severity": severity,
        "requirementId": requirement_id,
        "evidence": evidence,
    }


def _trace_id(record: Dict[str, Any]) -> str:
    return f"{record.get('matchId')}:{record.get('seq')}"


def _eligibility(record: Dict[str, Any]) -> tuple[Optional[bool], Optional[bool]]:
    """Derive mandatory-action eligibility from the stored public observation."""
    version = record.get("policyVersion")
    if version not in KNOWN_VERSIONS:
        return None, None
    obs = record.get("obs")
    legal = record.get("legalActions")
    if not isinstance(obs, dict) or not isinstance(legal, list):
        return None, None
    legal = [a for a in legal if isinstance(a, str)]
    try:
        forced = scoring.mandatory_action(obs, legal)
    except Exception:
        return None, None
    if forced is None:
        return False, None
    chosen = record.get("chosen")
    return True, chosen == forced[0]


def _bypass_classification(version: Optional[str], active: Optional[str]) -> Optional[str]:
    """Disposition of an eligible-but-unsatisfied mandatory action.

    The eligibility markers themselves are derived in ``_eligibility`` through
    ``scoring.mandatory_action`` -- the same production helper that governs live
    decisions. This helper only decides whether a bypass belongs to the active
    policy or to a known pre-guardrail policy: a known version other than the
    active one predates the active guardrail, so its bypass is historical and
    cannot be scored against the current policy. Unknown versions are never
    eligible (``_eligibility`` returns null for them).
    """
    if version == active:
        return CLASSIFICATION_CURRENT
    if version in KNOWN_VERSIONS:
        return CLASSIFICATION_HISTORICAL
    return None


def evaluate_corpus(path: Path, active_version: Optional[str] = None, accepted_change_note: Optional[str] = None) -> Dict[str, Any]:
    """Read a JSONL corpus and return traces, findings, and counts."""
    active = active_version or arena_config.POLICY_VERSION
    path = Path(path)
    if not path.exists():
        return {
            "status": "NOT_RUN",
            "command": "trace_eval.evaluate_corpus",
            "observed": f"{_display_path(path)}; gate=NOT_RUN",
            "traces": [],
            "findings": [],
            "counts": {c: 0 for c in CLASSES},
            "bypass_classification": {CLASSIFICATION_CURRENT: 0, CLASSIFICATION_HISTORICAL: 0},
        }

    traces: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    counts = {c: 0 for c in CLASSES}
    parents: Dict[str, str] = {}
    scorable = 0
    illegal = 0
    changed = 0
    unscorable = 0
    bypass_current = 0
    bypass_historical = 0

    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                unscorable += 1
                findings.append(_finding("SCHEMA_INVALID", "blocking", "unknown", "R4", "invalid JSON line"))
                counts["SCHEMA_INVALID"] += 1
                continue
            if not isinstance(record, dict):
                unscorable += 1
                continue

            tid = _trace_id(record)
            match_id = str(record.get("matchId"))
            parent = parents.get(match_id)
            parents[match_id] = tid
            eligible, satisfied = _eligibility(record)
            trace = {field: record.get(field) for field in TRACE_FIELDS}
            trace.update({
                "traceId": tid,
                "parentTraceId": parent,
                "mandatoryActionEligible": eligible,
                "mandatoryActionSatisfied": satisfied,
            })
            traces.append(trace)

            missing = [f for f in TRACE_FIELDS if f not in record]
            if missing:
                counts["SCHEMA_INVALID"] += 1
                findings.append(_finding("SCHEMA_INVALID", "blocking", tid, "R1", f"missing fields: {missing}"))

            legal = record.get("legalActions")
            legal = [a for a in legal if isinstance(a, str)] if isinstance(legal, list) else []
            chosen = record.get("chosen")
            if not isinstance(record.get("obs"), dict) or not legal or not isinstance(chosen, str):
                unscorable += 1
                counts["UNSCORABLE_RECORD"] += 1
                continue
            scorable += 1

            if chosen not in legal:
                illegal += 1
                counts["ILLEGAL_ACTION"] += 1
                findings.append(_finding("ILLEGAL_ACTION", "blocking", tid, "R5", f"chosen {chosen} not in legalActions"))

            version = record.get("policyVersion")
            if eligible is True and satisfied is False:
                classification = _bypass_classification(version, active)
                if classification is None:
                    # Fail closed: an unrecognized version must never soften a bypass.
                    classification = CLASSIFICATION_CURRENT
                severity = "observed" if classification == CLASSIFICATION_HISTORICAL else "blocking"
                finding = _finding(
                    "MANDATORY_ACTION_BYPASS", severity, tid, "R2",
                    f"eligible mandatory action was not satisfied; classification={classification}",
                )
                finding["classification"] = classification
                counts["MANDATORY_ACTION_BYPASS"] += 1
                findings.append(finding)
                if classification == CLASSIFICATION_HISTORICAL:
                    bypass_historical += 1
                else:
                    bypass_current += 1

            if version != active:
                counts["ATTRIBUTION_MISMATCH"] += 1
                findings.append(_finding(
                    "ATTRIBUTION_MISMATCH", "observed", tid, "R5",
                    f"record version {version} differs from active {active}",
                ))

            latency = record.get("latencyMs")
            if isinstance(latency, (int, float)) and latency > LATENCY_BOUND_MS:
                counts["LATENCY_REGRESSION"] += 1
                findings.append(_finding(
                    "LATENCY_REGRESSION", "observed", tid, "R5", f"latency {latency} ms exceeds {LATENCY_BOUND_MS}",
                ))

            try:
                replay = scoring.best_action(record["obs"], legal)
            except Exception:
                replay = None
            if replay is not None and replay != chosen:
                changed += 1
                counts["POLICY_DELTA"] += 1
                findings.append(_finding("POLICY_DELTA", "observed", tid, "R7", f"recorded {chosen}, replay {replay}"))

    # R7: a policy delta alone stays observed. It becomes blocking when any
    # other finding is blocking or no accepted-change note is attached.
    other_blocking = any(
        f.get("severity") == "blocking" and f.get("class") != "POLICY_DELTA"
        for f in findings
    )
    if other_blocking or not accepted_change_note:
        for f in findings:
            if f.get("class") == "POLICY_DELTA":
                f["severity"] = "blocking"

    return {
        "status": "RUN",
        "command": "trace_eval.evaluate_corpus",
        "observed": f"scorable={scorable} illegal={illegal} changed={changed} unscorable={unscorable}",
        "traces": traces,
        "findings": findings,
        "counts": counts,
        "bypass_classification": {
            CLASSIFICATION_CURRENT: bypass_current,
            CLASSIFICATION_HISTORICAL: bypass_historical,
        },
        "scorable": scorable,
        "illegal": illegal,
        "changed": changed,
        "unscorable": unscorable,
    }


def gate_b(report: Dict[str, Any]) -> str:
    if report.get("status") == "NOT_RUN":
        return "NOT_RUN"
    if report.get("illegal") == 0 and report.get("scorable", 0) > 0:
        if any(f.get("severity") == "blocking" for f in report.get("findings", [])):
            return "FAIL"
        return "PASS"
    return "FAIL"


def write_evidence(corpus: Path, out: Path, active_version: Optional[str] = None,
                   accepted_change_note: Optional[str] = None) -> int:
    report = evaluate_corpus(corpus, active_version, accepted_change_note)
    gate = gate_b(report)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
    ).stdout.strip()
    evidence = {
        "command": f"python3 trace_eval.py --corpus {_display_path(corpus)} --json-out {_display_path(out)}",
        "commit": commit,
        "expected": "G-B PASS with illegal==0 and scorable>0 and no blocking findings",
        "observed": f"{report['observed']}; gate={gate}",
        "counts": report["counts"],
        "bypass_classification": report["bypass_classification"],
        "exit_code": 0 if gate == "PASS" else 1,
        "status": report["status"],
        "blocking_findings": sum(1 for f in report["findings"] if f.get("severity") == "blocking"),
        "gate_b": gate,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return evidence["exit_code"]


def _display_path(path: Path) -> str:
    """Return a portable path for evidence; never emit a literal home path."""
    text = str(path)
    home = str(Path.home())
    return text.replace(home, "~", 1) if text.startswith(home) else text


def _is_ancestor(base: str, head: str) -> bool:
    if head == "HEAD":
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, head], capture_output=True
    )
    return result.returncode == 0


ALLOWED_CHECKS = (
    "python3 -m pytest", "python3 -m py_compile", "python3 replay.py", "python3 trace_eval.py",
)


def rerun_check(check: Dict[str, Any], root: Path, head: str = "HEAD") -> Dict[str, Any]:
    """Re-run a cited R8 check and verify its claimed fields against its evidence."""
    import shlex
    command = str(check.get("command") or "")
    argv = shlex.split(command)
    argv = [str(Path(arg).expanduser()) if arg.startswith("~/") else arg for arg in argv]
    if not argv or argv[0] != "python3" or not command.startswith(ALLOWED_CHECKS):
        return {"status": "REJECT", "reason": "command not in allowed R8 set"}
    evidence_ref = check.get("evidence_ref")
    if not evidence_ref:
        return {"status": "REJECT", "reason": "check has no evidence_ref"}
    evidence_path = Path(evidence_ref)
    if not evidence_path.is_absolute():
        evidence_path = root / evidence_path
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "NOT_RUN", "reason": f"unreadable evidence_ref: {type(exc).__name__}"}
    required = {"command", "commit", "expected", "observed", "counts", "exit_code"}
    if not required <= set(evidence):
        return {"status": "REJECT", "reason": "evidence_ref missing R9 fields"}
    if head == "HEAD":
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    mismatches = []
    if check.get("commit") != evidence.get("commit"):
        mismatches.append("commit")
    if check.get("observed") != evidence.get("observed"):
        mismatches.append("observed")
    if check.get("counts") != evidence.get("counts"):
        mismatches.append("counts")
    if check.get("exit_code") != evidence.get("exit_code"):
        mismatches.append("exit_code")
    if str(check.get("command")) != str(evidence.get("command")):
        mismatches.append("command")
    if mismatches:
        return {"status": "REJECT", "reason": f"claim mismatches evidence: {mismatches}"}
    if evidence.get("commit") != head:
        return {"status": "REJECT", "reason": f"evidence commit {evidence.get('commit')} differs from evaluation head {head}"}
    try:
        result = subprocess.run(argv, capture_output=True, text=True, cwd=root, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "NOT_RUN", "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "status": "RUN",
        "exit_code": result.returncode,
        "expected_exit_code": check.get("exit_code"),
        "match": result.returncode == check.get("exit_code"),
        "observed_tail": result.stdout[-500:],
    }


def validate_handoff(envelope: Dict[str, Any], head: str = "HEAD", root: Optional[Path] = None) -> Dict[str, Any]:
    root = root or Path(__file__).resolve().parent
    findings: List[Dict[str, Any]] = []
    missing = [f for f in ENVELOPE_FIELDS if f not in envelope]
    if missing:
        findings.append(_finding("SCHEMA_INVALID", "blocking", "envelope", "R11", f"missing fields: {missing}"))
    artifact = envelope.get("artifact_path")
    if artifact and not Path(artifact).exists():
        findings.append(_finding("SCHEMA_INVALID", "blocking", "envelope", "R11", f"missing artifact: {artifact}"))
    base = envelope.get("base_commit")
    if base and not _is_ancestor(str(base), head):
        findings.append(_finding("SCHEMA_INVALID", "blocking", "envelope", "R12", f"base_commit {base} is not ancestor of {head}"))
    for check in envelope.get("checks") or []:
        if not isinstance(check, dict) or not {
            "command", "commit", "expected", "observed", "counts", "exit_code"
        } <= set(check):
            findings.append(_finding("SCHEMA_INVALID", "blocking", "envelope", "R9", "check missing full R9 evidence fields"))
            continue
        rerun = rerun_check(check, root, head=head)
        if rerun["status"] != "RUN" or not rerun.get("match"):
            findings.append(_finding(
                "SCHEMA_INVALID", "blocking", "envelope", "R12",
                f"check re-run failed: {rerun}",
            ))
    if envelope.get("findings"):
        findings.extend(envelope["findings"])
    for blocker in envelope.get("blockers") or []:
        findings.append(_finding("SCHEMA_INVALID", "blocking", "envelope", "R20", str(blocker)))
    status = "PASS" if not any(f.get("severity") == "blocking" for f in findings) else "REJECT"
    return {"status": status, "findings": findings, "base_commit": base, "head": head}


def new_tick(tick_id: str, parent_tick_id: Optional[str], task_id: str, commit: str,
             state: str, findings_ref: str, checks_ref: str, handoff_ref: Optional[str]) -> Dict[str, Any]:
    import datetime
    return {
        "tick_id": tick_id,
        "parent_tick_id": parent_tick_id,
        "task_id": task_id,
        "commit": commit,
        "state": state,
        "findings_ref": findings_ref,
        "checks_ref": checks_ref,
        "handoff_ref": handoff_ref,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def _read_chain(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            out.append(json.loads(raw))
    return out


def _resolve_ref(ref: Optional[str], chain: Path) -> Optional[Path]:
    if not ref:
        return None
    path = Path(ref)
    if path.is_absolute() or path.exists():
        return path if path.exists() else None
    sibling = chain.parent / path.name
    return sibling if sibling.exists() else None


def _derive_state(tick: Dict[str, Any], chain: Path) -> str:
    findings_path = _resolve_ref(tick.get("findings_ref"), chain)
    checks_path = _resolve_ref(tick.get("checks_ref"), chain)
    handoff_path = _resolve_ref(tick.get("handoff_ref"), chain)
    for path in (findings_path, checks_path):
        if not path:
            return "BLOCKED"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return "BLOCKED"
        if not isinstance(data, dict):
            return "BLOCKED"
        if data.get("blocking_findings", 0) or data.get("gate_b") == "FAIL" or data.get("status") == "BLOCKED":
            return "BLOCKED"
        if data.get("findings"):
            return "BLOCKED"
    return "VERIFYING" if handoff_path else "IMPLEMENTING"


def append_tick(tick: Dict[str, Any], chain: Path, head: str = "HEAD") -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    missing = [f for f in TICK_FIELDS if f not in tick]
    if missing:
        findings.append(_finding("SCHEMA_INVALID", "blocking", str(tick.get("tick_id")), "R14", f"missing fields: {missing}"))
    derived = _derive_state(tick, chain)
    if tick.get("state") != derived:
        findings.append(_finding(
            "SCHEMA_INVALID", "blocking", str(tick.get("tick_id")), "R15",
            f"state {tick.get('state')} does not match derived state {derived}",
        ))
    else:
        tick["state"] = derived
    for ref_key in ("findings_ref", "checks_ref", "handoff_ref"):
        ref = tick.get(ref_key)
        if not ref:
            continue
        ref_path = Path(ref)
        if not ref_path.is_absolute() and not ref_path.exists():
            ref_path = chain.parent / ref_path.name
        if not ref_path.exists():
            findings.append(_finding("SCHEMA_INVALID", "blocking", str(tick.get("tick_id")), "R15", f"missing {ref_key}: {ref}"))
    if head == "HEAD":
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
    if tick.get("commit") != head:
        findings.append(_finding("SCHEMA_INVALID", "blocking", str(tick.get("tick_id")), "R16", f"tick commit {tick.get('commit')} differs from HEAD {head}"))

    ticks = _read_chain(chain)
    tip = ticks[-1] if ticks else None
    expected_parent = None if tip is None else tip.get("tick_id")
    if tick.get("parent_tick_id") != expected_parent:
        findings.append(_finding("SCHEMA_INVALID", "blocking", str(tick.get("tick_id")), "R14", f"parent must be {expected_parent}"))
    if tip is not None:
        if tip.get("commit") != head:
            findings.append(_finding(
                "SCHEMA_INVALID", "blocking", str(tip.get("tick_id")), "R16",
                f"tip commit {tip.get('commit')} differs from evaluation head {head}",
            ))
        same_commit = tip.get("commit") == tick.get("commit")
        state_changed = tip.get("state") != tick.get("state")
        new_evidence = (tip.get("findings_ref"), tip.get("checks_ref")) != (tick.get("findings_ref"), tick.get("checks_ref"))
        if same_commit and state_changed and not new_evidence:
            findings.append(_finding("SCHEMA_INVALID", "blocking", str(tick.get("tick_id")), "R16", "state changed on unchanged commit with no new evidence"))

    if any(f["severity"] == "blocking" for f in findings):
        result = {"status": "BLOCKED", "findings": findings}
        return result
    chain.parent.mkdir(parents=True, exist_ok=True)
    with chain.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(tick) + "\n")
    return {"status": "PASS", "findings": findings}


def gate_c(envelope: Dict[str, Any], ticks: List[Dict[str, Any]], head: str) -> str:
    if not ticks:
        return "NOT_RUN"
    if any(t.get("commit") != head for t in ticks):
        return "BLOCKED"
    if _derive_state(ticks[-1], Path(".")) == "BLOCKED":
        return "BLOCKED"
    validation = validate_handoff(envelope, head=head)
    return "PASS" if validation["status"] == "PASS" else "BLOCKED"


def gate_a(plan_path: Path) -> str:
    try:
        text = Path(plan_path).read_text(encoding="utf-8")
    except OSError:
        return "NOT_RUN"
    required = (
        "artifact_contract: ce-unified-plan/v1",
        "artifact_readiness: implementation-ready",
        "product_contract_source: ce-brainstorm",
    )
    return "PASS" if all(token in text for token in required) else "FAIL"


def write_gate_evidence(plan: Path, evidence: Path, envelope_path: Path, chain: Path,
                        out: Path, head: str) -> int:
    eval_ev = json.loads(evidence.read_text(encoding="utf-8"))
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    ticks = _read_chain(chain)
    a = gate_a(plan)
    b = str(eval_ev.get("gate_b") or "NOT_RUN")
    c = gate_c(envelope, ticks, head)
    blocked = any(v in ("FAIL", "BLOCKED") for v in (a, b, c))
    payload = {
        "command": f"python3 trace_eval.py gates --plan {_display_path(plan)} --evidence {_display_path(evidence)} --envelope {_display_path(envelope_path)} --chain {_display_path(chain)} --head {head} --json-out {_display_path(out)}",
        "commit": head,
        "expected": "G-A PASS, G-B PASS, G-C PASS",
        "observed": f"G-A={a} G-B={b} G-C={c}",
        "counts": eval_ev.get("counts", {}),
        "exit_code": 1 if blocked else 0,
        "gates": {"G-A": a, "G-B": b, "G-C": c},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload["exit_code"]


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--active-version")
    sub = parser.add_subparsers(dest="command")
    handoff = sub.add_parser("validate-handoff")
    handoff.add_argument("--envelope", type=Path, required=True)
    handoff.add_argument("--head", default="HEAD")
    tick = sub.add_parser("append-tick")
    tick.add_argument("--tick", type=Path, required=True)
    tick.add_argument("--chain", type=Path, required=True)
    tick.add_argument("--head", default="HEAD")
    gates = sub.add_parser("gates")
    gates.add_argument("--plan", type=Path, required=True)
    gates.add_argument("--evidence", type=Path, required=True)
    gates.add_argument("--envelope", type=Path, required=True)
    gates.add_argument("--chain", type=Path, required=True)
    gates.add_argument("--head", default="HEAD")
    gates.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "validate-handoff":
        envelope = json.loads(args.envelope.read_text(encoding="utf-8"))
        result = validate_handoff(envelope, head=args.head)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "PASS" else 1
    if args.command == "append-tick":
        tick_obj = json.loads(args.tick.read_text(encoding="utf-8"))
        result = append_tick(tick_obj, args.chain, head=args.head)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "PASS" else 1
    if args.command == "gates":
        rc = write_gate_evidence(
            args.plan, args.evidence, args.envelope, args.chain, args.json_out, args.head
        )
        print(json.dumps(json.loads(args.json_out.read_text(encoding="utf-8")), indent=2))
        return rc
    if not args.corpus or not args.json_out:
        parser.error("--corpus and --json-out are required")
    return write_evidence(args.corpus, args.json_out, args.active_version)


if __name__ == "__main__":
    sys.exit(main())
