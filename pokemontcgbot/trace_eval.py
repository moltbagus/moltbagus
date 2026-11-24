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


def evaluate_corpus(path: Path, active_version: Optional[str] = None) -> Dict[str, Any]:
    """Read a JSONL corpus and return traces, findings, and counts."""
    active = active_version or arena_config.POLICY_VERSION
    path = Path(path)
    if not path.exists():
        return {
            "status": "NOT_RUN",
            "command": "trace_eval.evaluate_corpus",
            "observed": f"missing corpus: {path}",
            "traces": [],
            "findings": [],
            "counts": {c: 0 for c in CLASSES},
        }

    traces: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    counts = {c: 0 for c in CLASSES}
    parents: Dict[str, str] = {}
    scorable = 0
    illegal = 0
    changed = 0
    unscorable = 0

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

            if eligible is True and satisfied is False:
                counts["MANDATORY_ACTION_BYPASS"] += 1
                findings.append(_finding(
                    "MANDATORY_ACTION_BYPASS", "blocking", tid, "R2",
                    "eligible mandatory action was not satisfied",
                ))

            version = record.get("policyVersion")
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

    return {
        "status": "RUN",
        "command": "trace_eval.evaluate_corpus",
        "observed": f"scorable={scorable} illegal={illegal} changed={changed} unscorable={unscorable}",
        "traces": traces,
        "findings": findings,
        "counts": counts,
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


def write_evidence(corpus: Path, out: Path, active_version: Optional[str] = None) -> int:
    report = evaluate_corpus(corpus, active_version)
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


def validate_handoff(envelope: Dict[str, Any], head: str = "HEAD") -> Dict[str, Any]:
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
        if not isinstance(check, dict) or not {"command", "expected", "observed", "exit_code"} <= set(check):
            findings.append(_finding("SCHEMA_INVALID", "observed", "envelope", "R9", "check missing evidence fields"))
    status = "PASS" if not any(f["severity"] == "blocking" for f in findings) else "REJECT"
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


def append_tick(tick: Dict[str, Any], chain: Path, head: str = "HEAD") -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    missing = [f for f in TICK_FIELDS if f not in tick]
    if missing:
        findings.append(_finding("SCHEMA_INVALID", "blocking", str(tick.get("tick_id")), "R14", f"missing fields: {missing}"))
    if tick.get("state") not in STATES:
        findings.append(_finding("SCHEMA_INVALID", "blocking", str(tick.get("tick_id")), "R15", f"invalid state: {tick.get('state')}"))
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
    if not args.corpus or not args.json_out:
        parser.error("--corpus and --json-out are required")
    return write_evidence(args.corpus, args.json_out, args.active_version)


if __name__ == "__main__":
    sys.exit(main())
