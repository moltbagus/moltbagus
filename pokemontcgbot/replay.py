"""Offline replay gate over the recorded decision corpus (spec section 7).

What it answers, for a policy change: if this exact policy had been in place at
every decision the live bot faced, what would it have done differently, and
would any of those choices have been illegal?

Reported:

* ``illegal`` — the recorded choice was not in its own legal-action list. This
  must be 0; anything else means the corpus is corrupt or the recorder lies.
* ``changed`` — the replayed policy picks a different action than the live one.
* ``meanScoreDelta`` — the replayed choice's score minus the recorded choice's
  score, averaged over changed decisions.
* ``bySelectType`` — where the changes concentrate (trainer play, attach, attack…).
* ``byPath`` — which code path answered each decision (``belief``, ``scoring``,
  ``fallback``, or ``unknown`` for records that predate attribution), so a
  belief-path override is separated from a genuine ``scoring`` policy delta.

Usage::

    python3 replay.py                      # whole corpus
    python3 replay.py --since 2026-11-20T23:00:00 --json-out evidence/replay.json

Exit code is 1 when the gate fails (illegal action found, or nothing scorable).
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import arena_config
import scoring
import telemetry

Chooser = Callable[[Dict[str, Any], List[str]], Optional[str]]

POLICY_PATHS = ("belief", "scoring", "fallback")


def _path_of(record: Dict[str, Any]) -> str:
    """The recorded decision path, or ``unknown`` when absent/unrecognised."""
    path = record.get("policyPath")
    return path if path in POLICY_PATHS else "unknown"


def default_choices(obs: Dict[str, Any], legal: List[str]) -> Optional[str]:
    """The live policy: one shared implementation, no re-implementation here."""
    return scoring.best_action(obs, legal)


def _score(action: str, obs: Dict[str, Any]) -> Optional[float]:
    try:
        return float(scoring.action_score(action, obs))
    except Exception:
        return None


def _parse_since(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value).timestamp() * 1000.0
    except ValueError:
        return None


def replay(
    records: Iterable[Dict[str, Any]],
    choose: Optional[Chooser] = None,
    since_ms: Optional[float] = None,
) -> Dict[str, Any]:
    """Replay the corpus through ``choose`` and return the gate report."""
    chooser = choose or default_choices
    total = scored = illegal = changed = unscorable = 0
    deltas: List[float] = []
    by_type: Dict[str, Dict[str, int]] = {}
    by_path: Dict[str, Dict[str, int]] = {}
    matches = set()
    versions = set()
    first_ts: Optional[float] = None
    last_ts: Optional[float] = None

    for record in records:
        if not isinstance(record, dict):
            continue
        ts = record.get("ts")
        if since_ms is not None and isinstance(ts, (int, float)) and ts < since_ms:
            continue
        total += 1

        obs = record.get("obs")
        raw_legal = record.get("legalActions")
        legal = [a for a in raw_legal if isinstance(a, str)] if isinstance(raw_legal, list) else []
        chosen = record.get("chosen")
        if isinstance(ts, (int, float)):
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
        if record.get("matchId"):
            matches.add(record.get("matchId"))
        if record.get("policyVersion"):
            versions.add(record.get("policyVersion"))

        if not isinstance(obs, dict) or not legal or not isinstance(chosen, str):
            unscorable += 1
            continue

        scored += 1
        if chosen not in legal:
            illegal += 1

        select_type = str(record.get("selectType"))
        bucket = by_type.setdefault(select_type, {"n": 0, "changed": 0})
        bucket["n"] += 1
        path_bucket = by_path.setdefault(_path_of(record), {"n": 0, "changed": 0})
        path_bucket["n"] += 1

        try:
            replayed = chooser(obs, legal)
        except Exception:
            replayed = None
        if not isinstance(replayed, str) or replayed not in legal:
            unscorable += 1
            continue
        if replayed != chosen:
            changed += 1
            bucket["changed"] += 1
            path_bucket["changed"] += 1
            new_score = _score(replayed, obs)
            old_score = _score(chosen, obs)
            if new_score is not None and old_score is not None:
                deltas.append(new_score - old_score)

    mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
    return {
        "records": total,
        "scored": scored,
        "unscorable": unscorable,
        "illegal": illegal,
        "changed": changed,
        "changeRate": (changed / scored) if scored else 0.0,
        "meanScoreDelta": round(mean_delta, 3),
        "bySelectType": dict(sorted(by_type.items())),
        "byPath": dict(sorted(by_path.items())),
        "matches": len(matches),
        "policyVersions": sorted(versions),
        "firstTs": first_ts,
        "lastTs": last_ts,
        "passed": illegal == 0 and scored > 0,
    }


def _fmt_ts(value: Optional[float]) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return datetime.datetime.fromtimestamp(value / 1000.0).strftime("%Y-%m-%d %H:%M:%S")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Replay the decision corpus through the current policy.")
    parser.add_argument("--path", default=None, help="telemetry JSONL (default: arena_config.TELEMETRY_PATH)")
    parser.add_argument("--since", default=None, help="ISO timestamp; earlier records are ignored")
    parser.add_argument("--json-out", default=None, help="write the report as JSON evidence")
    args = parser.parse_args(argv)

    records = telemetry.read(args.path)
    report = replay(records, since_ms=_parse_since(args.since))

    print("Replay gate — offline policy check")
    print(f"  corpus        {report['records']} records / {report['matches']} matches  "
          f"({_fmt_ts(report['firstTs'])} → {_fmt_ts(report['lastTs'])})")
    print(f"  policy        current scoring.best_action  (recorded: {', '.join(report['policyVersions']) or 'unknown'})")
    print(f"  scorable      {report['scored']}   unscorable {report['unscorable']}")
    print(f"  illegal       {report['illegal']}   {'OK' if report['illegal'] == 0 else 'FAIL'}")
    print(f"  changed       {report['changed']} of {report['scored']} "
          f"({report['changeRate'] * 100:.1f}%)   mean score delta {report['meanScoreDelta']:+.3f}")
    if report["bySelectType"]:
        print("  by select type")
        for key, bucket in report["bySelectType"].items():
            print(f"    type {key:>4}  n={bucket['n']:>4}  changed={bucket['changed']}")
    if report["byPath"]:
        print("  by policyPath")
        for key, bucket in report["byPath"].items():
            print(f"    {key:<8}  n={bucket['n']:>4}  changed={bucket['changed']}")
    print(f"  gate          {'PASS' if report['passed'] else 'FAIL'}")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(report)
        payload["policyVersion"] = arena_config.POLICY_VERSION
        payload["generatedAt"] = datetime.datetime.now().isoformat(timespec="seconds")
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"  evidence      {out}")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
