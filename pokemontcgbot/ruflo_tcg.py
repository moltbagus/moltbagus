"""Ruflo Self-Improvement Backbone for Pokemon TCG Bot.

Adapts the Ruflo autonomy ladder (from pokerdevfun) for TCG bot self-improvement.
Tracks match outcomes, heuristic performance, and gates strategy promotions
using Bayesian evidence (win rate, sample size, z-score).

Autonomy levels:
  L1 (DRY_RUN):       Log decisions, no strategy changes.
  L2 (HUMAN_APPROVE): Propose strategy changes, require human approval.
  L3 (AUTO_KILLSWITCH): Auto-apply strategy changes with kill-switch safety.
  L4 (FULL_AUTO):     Full autonomous self-improvement.

Usage:
    from ruflo_tcg import RufloTCG
    ruflo = RufloTCG(state_dir=Path("/home/colb/.hermes/state/tcgbot"))
    ruflo.observe_match(result="win", actions=18, forfeit=False)
    decision = ruflo.check_promotion()
"""
from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import statistics
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WR_BASELINE: float = 0.5  # break-even win rate
DEMOTION_Z_MAX: float = -2.0  # ~97.7% confidence strategy is losing

PROMOTION_GATES: dict[tuple[int, int], dict[str, Any]] = {
    (1, 2): {
        "matches_min": 10,
        "wr_min": 0.40,  # at least 40% WR to promote from L1
        "wr_zscore_min": 0.0,  # any positive edge
        "elapsed_hours_min": 1,
        "no_forfeit_in_window": True,
    },
    (2, 3): {
        "matches_min": 30,
        "wr_min": 0.45,
        "wr_zscore_min": 1.0,  # ~68% confident
        "elapsed_hours_min": 6,
        "no_forfeit_in_window": True,
        "human_override_count_max": 0,
    },
    (3, 4): {
        "matches_min": 100,
        "wr_min": 0.50,
        "wr_zscore_min": 1.96,  # ~95% confident
        "elapsed_hours_min": 24,
        "no_forfeit_in_window": True,
        "human_override_count_max": 0,
    },
}

DEMOTION_TRIGGERS: dict[str, dict[str, Any]] = {
    "forfeit_streak": {"target": 1},  # 3+ consecutive forfeits → L1
    "wr_drop": {"target": 1},  # WR z-score <= -2.0 → L1
    "timeout_streak": {"delta": -1},  # 5+ timeouts → demote 1
    "human_override": {"delta": -1, "freeze_hours": 12},
}

# ---------------------------------------------------------------------------
# State directory
# ---------------------------------------------------------------------------


def _resolve_state_dir() -> Path:
    return Path(
        os.environ.get(
            "RUFLO_TCG_STATE_DIR",
            str(Path.home() / ".hermes" / "state" / "tcgbot"),
        )
    )


DEFAULT_STATE_DIR = _resolve_state_dir()

_RUFLO_SCHEMA = """
CREATE TABLE IF NOT EXISTS autonomy_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS match_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    result      TEXT NOT NULL,  -- 'win' | 'loss' | 'forfeit' | 'timeout'
    opponent    TEXT DEFAULT '',
    actions     INTEGER DEFAULT 0,
    our_hp_lost INTEGER DEFAULT 0,
    opp_hp_lost INTEGER DEFAULT 0,
    prizes_taken INTEGER DEFAULT 0,
    prizes_lost  INTEGER DEFAULT 0,
    deck_version TEXT DEFAULT '',
    heuristic   TEXT DEFAULT '',
    notes       TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS strategy_proposals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    proposal    TEXT NOT NULL,
    status      TEXT DEFAULT 'pending',  -- 'pending' | 'applied' | 'reverted' | 'rejected'
    evidence    TEXT DEFAULT '',
    win_rate_before REAL DEFAULT 0.0,
    win_rate_after  REAL DEFAULT 0.0
);
CREATE TABLE IF NOT EXISTS sfl_failures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    failure_type TEXT NOT NULL,
    rule_id     TEXT NOT NULL,
    evidence    TEXT NOT NULL,
    severity    TEXT NOT NULL,
    ts          TEXT NOT NULL,
    extra       TEXT DEFAULT '{}'
);
"""


def _open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    conn.executescript(_RUFLO_SCHEMA)
    return conn


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MatchResult:
    result: str  # 'win' | 'loss' | 'forfeit' | 'timeout'
    opponent: str = ""
    actions: int = 0
    our_hp_lost: int = 0
    opp_hp_lost: int = 0
    prizes_taken: int = 0
    prizes_lost: int = 0
    deck_version: str = ""
    heuristic: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PhaseDecision:
    current_level: int
    proposed_level: int
    action: str  # 'promote' | 'hold' | 'demote' | 'freeze'
    gates_passed: dict = field(default_factory=dict)
    gates_failed: dict = field(default_factory=dict)
    reason: str = ""
    ts: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AutonomyState:
    current_level: int = 1
    entered_at: str = ""
    keep_count: int = 0
    apply_count: int = 0
    human_override_count: int = 0
    freeze_until: str = ""
    promotion_history: list = field(default_factory=list)
    demotion_history: list = field(default_factory=list)
    last_decision: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AutonomyState":
        return cls(
            current_level=int(d.get("current_level", 1)),
            entered_at=d.get("entered_at", ""),
            keep_count=int(d.get("keep_count", 0)),
            apply_count=int(d.get("apply_count", 0)),
            human_override_count=int(d.get("human_override_count", 0)),
            freeze_until=d.get("freeze_until", ""),
            promotion_history=list(d.get("promotion_history", [])),
            demotion_history=list(d.get("demotion_history", [])),
            last_decision=dict(d.get("last_decision", {})),
        )


# ---------------------------------------------------------------------------
# Bayesian evidence
# ---------------------------------------------------------------------------


def compute_bayesian_evidence(
    win_rate: float | None,
    sample_size: int,
    baseline: float = WR_BASELINE,
    min_sample: int = 10,
    z_threshold: float = 0.0,
) -> dict:
    """Bayesian evidence check: is there significant positive edge?"""
    if win_rate is None:
        return {"passed": False, "reason": "no win_rate evidence", "z_score": None}
    if sample_size < 1:
        return {"passed": False, "reason": "sample_size < 1", "z_score": None}
    se = math.sqrt(baseline * (1.0 - baseline) / sample_size)
    z = (win_rate - baseline) / se if se > 0 else 0.0
    sample_sufficient = sample_size >= min_sample
    edge_positive = z > 0 and win_rate > baseline
    passed = sample_sufficient and edge_positive and z >= z_threshold
    reason = (
        "pass"
        if passed
        else "insufficient sample"
        if not sample_sufficient
        else "no positive edge"
        if not edge_positive
        else "edge not significant"
    )
    return {
        "passed": passed,
        "reason": reason,
        "z_score": z,
        "win_rate": win_rate,
        "sample_size": sample_size,
        "sample_sufficient": sample_sufficient,
        "edge_positive": edge_positive,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RufloTCG:
    """Self-improvement backbone for Pokemon TCG bot.

    Tracks match outcomes, gates strategy promotions via Bayesian evidence,
    and provides self-learning from match replays.
    """

    def __init__(self, state_dir: Path | None = None):
        self.state_dir = state_dir or _resolve_state_dir()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "ruflo_tcg.db"
        self.db = _open_db(self.db_path)
        self.state = self._load_state()
        self._lock = threading.Lock()
        self._loaded_mtime: float | None = None

    # ------------------------------------------------------------------ #
    # State persistence
    # ------------------------------------------------------------------ #

    def _load_state(self) -> AutonomyState:
        try:
            row = self.db.execute(
                "SELECT value FROM autonomy_state WHERE key='autonomy_state'"
            ).fetchone()
            if row is not None:
                return AutonomyState.from_dict(json.loads(row["value"]))
        except Exception as exc:
            log.warning("ruflo_tcg: _load_state failed (%s)", exc)
        return AutonomyState(current_level=1, entered_at=_now_iso())

    def _save_state(self) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO autonomy_state (key, value) VALUES (?, ?)",
            ("autonomy_state", json.dumps(self.state.to_dict())),
        )
        self.db.commit()

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _hours_at_level(self) -> float | None:
        if not self.state.entered_at:
            return None
        try:
            entered = datetime.fromisoformat(self.state.entered_at.replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - entered).total_seconds() / 3600.0
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------ #
    # Match tracking
    # ------------------------------------------------------------------ #

    def observe_match(self, result: MatchResult | dict) -> None:
        """Record a match result."""
        if isinstance(result, dict):
            result = MatchResult(**result)

        with self._lock:
            self.db.execute(
                """INSERT INTO match_results
                   (ts, result, opponent, actions, our_hp_lost, opp_hp_lost,
                    prizes_taken, prizes_lost, deck_version, heuristic, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self._now_iso(),
                    result.result,
                    result.opponent,
                    result.actions,
                    result.our_hp_lost,
                    result.opp_hp_lost,
                    result.prizes_taken,
                    result.prizes_lost,
                    result.deck_version,
                    result.heuristic,
                    result.notes,
                ),
            )
            self.db.commit()

            # Update keep_count on win
            if result.result == "win":
                self.state.keep_count += 1
            elif result.result in ("loss", "forfeit", "timeout"):
                self.state.keep_count = 0

            self._save_state()

    def get_win_rate(self, window: int = 50) -> tuple[float | None, int]:
        """Get win rate over last `window` matches."""
        rows = self.db.execute(
            "SELECT result FROM match_results ORDER BY ts DESC LIMIT ?", (window,)
        ).fetchall()
        if not rows:
            return None, 0
        wins = sum(1 for r in rows if r["result"] == "win")
        total = len(rows)
        return wins / total if total > 0 else None, total

    def get_forfeit_streak(self) -> int:
        """Count consecutive forfeits from most recent."""
        rows = self.db.execute(
            "SELECT result FROM match_results ORDER BY ts DESC LIMIT 10"
        ).fetchall()
        streak = 0
        for r in rows:
            if r["result"] == "forfeit":
                streak += 1
            else:
                break
        return streak

    def get_timeout_streak(self) -> int:
        """Count consecutive timeouts from most recent."""
        rows = self.db.execute(
            "SELECT result FROM match_results ORDER BY ts DESC LIMIT 10"
        ).fetchall()
        streak = 0
        for r in rows:
            if r["result"] == "timeout":
                streak += 1
            else:
                break
        return streak

    # ------------------------------------------------------------------ #
    # Promotion / demotion
    # ------------------------------------------------------------------ #

    def check_promotion(self) -> PhaseDecision:
        """Decide whether to promote, hold, or demote."""
        with self._lock:
            return self._check_promotion_impl()

    def _check_promotion_impl(self) -> PhaseDecision:
        current = self.state.current_level
        if current >= 4:
            decision = PhaseDecision(
                current_level=4,
                proposed_level=4,
                action="hold",
                reason="already at L4 (FULL_AUTO)",
                ts=self._now_iso(),
            )
            self.state.last_decision = decision.to_dict()
            self._save_state()
            return decision

        gate = PROMOTION_GATES.get((current, current + 1))
        if gate is None:
            decision = PhaseDecision(
                current_level=current,
                proposed_level=current,
                action="hold",
                reason=f"no gate for L{current}->L{current+1}",
                ts=self._now_iso(),
            )
            self.state.last_decision = decision.to_dict()
            self._save_state()
            return decision

        gates_passed: dict[str, bool] = {}
        gates_failed: dict[str, bool] = {}

        # Forfeit streak check
        forfeit_streak = self.get_forfeit_streak()
        gates_passed["no_forfeit"] = forfeit_streak == 0
        if not gates_passed["no_forfeit"]:
            gates_failed["no_forfeit"] = True

        # Match count
        wr, sample_size = self.get_win_rate(window=gate["matches_min"])
        gates_passed["matches_min"] = sample_size >= gate["matches_min"]
        if not gates_passed["matches_min"]:
            gates_failed["matches_min"] = True

        # Win rate
        if wr is not None:
            gates_passed["wr_min"] = wr >= gate["wr_min"]
            if not gates_passed["wr_min"]:
                gates_failed["wr_min"] = True
        else:
            gates_passed["wr_min"] = False
            gates_failed["wr_min"] = True

        # Elapsed hours
        elapsed = self._hours_at_level()
        if elapsed is not None:
            gates_passed["elapsed_hours"] = elapsed >= gate["elapsed_hours_min"]
            if not gates_passed["elapsed_hours"]:
                gates_failed["elapsed_hours"] = True
        else:
            gates_passed["elapsed_hours"] = False
            gates_failed["elapsed_hours"] = True

        # Bayesian edge
        _win_rate = wr
        _sample_size = sample_size
        ev = compute_bayesian_evidence(
            _win_rate,
            _sample_size,
            min_sample=gate["matches_min"],
            z_threshold=gate["wr_zscore_min"],
        )
        gates_passed["bayesian_edge"] = ev["passed"]
        if not gates_passed["bayesian_edge"]:
            gates_failed["bayesian_edge"] = True

        # Human override (L2+)
        if "human_override_count_max" in gate:
            gates_passed["human_override"] = (
                self.state.human_override_count <= gate["human_override_count_max"]
            )
            if not gates_passed["human_override"]:
                gates_failed["human_override"] = True

        # Demotion triggers (checked first)
        forfeit_streak = self.get_forfeit_streak()
        if forfeit_streak >= 3:
            return self._demote("forfeit_streak", f"{forfeit_streak} consecutive forfeits")

        timeout_streak = self.get_timeout_streak()
        if timeout_streak >= 5:
            return self._demote("timeout_streak", f"{timeout_streak} consecutive timeouts")

        if all(gates_passed.values()):
            from_lvl = current
            to_lvl = current + 1
            decision = PhaseDecision(
                current_level=from_lvl,
                proposed_level=to_lvl,
                action="promote",
                gates_passed=gates_passed,
                gates_failed={},
                reason=f"PROMOTED L{from_lvl}->L{to_lvl}",
                ts=self._now_iso(),
            )
            self.state.current_level = to_lvl
            self.state.entered_at = self._now_iso()
            self.state.keep_count = 0
            self.state.promotion_history.append(
                {"from": from_lvl, "to": to_lvl, "ts": self._now_iso(), "gates": gates_passed}
            )
            self.state.last_decision = decision.to_dict()
            self._save_state()
            return decision
        else:
            parts = [k for k, v in gates_failed.items()]
            reason = f"L{current}->L{current+1} gate(s) not met: {', '.join(parts)}"
            decision = PhaseDecision(
                current_level=current,
                proposed_level=current,
                action="hold",
                gates_passed=gates_passed,
                gates_failed=gates_failed,
                reason=reason,
                ts=self._now_iso(),
            )
            self.state.last_decision = decision.to_dict()
            self._save_state()
            return decision

    def _demote(self, trigger: str, reason: str) -> PhaseDecision:
        trigger_cfg = DEMOTION_TRIGGERS.get(trigger, {})
        from_lvl = self.state.current_level
        if "target" in trigger_cfg:
            to_lvl = max(1, int(trigger_cfg["target"]))
        elif "delta" in trigger_cfg:
            to_lvl = max(1, from_lvl + int(trigger_cfg["delta"]))
        else:
            to_lvl = max(1, from_lvl - 1)

        decision = PhaseDecision(
            current_level=from_lvl,
            proposed_level=to_lvl,
            action="demote",
            gates_passed={},
            gates_failed={trigger: True},
            reason=reason,
            ts=self._now_iso(),
        )
        self.state.current_level = to_lvl
        self.state.entered_at = self._now_iso()
        self.state.keep_count = 0
        self.state.demotion_history.append(
            {"from": from_lvl, "to": to_lvl, "trigger": trigger, "ts": self._now_iso(), "reason": reason}
        )
        self.state.last_decision = decision.to_dict()
        self._save_state()
        return decision

    # ------------------------------------------------------------------ #
    # Self-learning from match replays
    # ------------------------------------------------------------------ #

    def record_failure(self, failure_type: str, rule_id: str, evidence: str, severity: str = "warning") -> None:
        """Record a self-learning failure (SFL Stage 1)."""
        self.db.execute(
            "INSERT INTO sfl_failures (failure_type, rule_id, evidence, severity, ts, extra) VALUES (?, ?, ?, ?, ?, ?)",
            (failure_type, rule_id, evidence, severity, self._now_iso(), "{}"),
        )
        self.db.commit()

    def propose_strategy(self, proposal: str, evidence: str = "") -> int:
        """Propose a strategy change. Returns proposal ID."""
        cur = self.db.execute(
            "INSERT INTO strategy_proposals (ts, proposal, status, evidence) VALUES (?, ?, 'pending', ?)",
            (self._now_iso(), proposal, evidence),
        )
        self.db.commit()
        return cur.lastrowid

    def apply_proposal(self, proposal_id: int, win_rate_before: float, win_rate_after: float) -> None:
        """Mark a proposal as applied with before/after win rates."""
        self.db.execute(
            "UPDATE strategy_proposals SET status='applied', win_rate_before=?, win_rate_after=? WHERE id=?",
            (win_rate_before, win_rate_after, proposal_id),
        )
        self.db.commit()
        self.state.apply_count += 1
        self._save_state()

    def revert_proposal(self, proposal_id: int, reason: str) -> None:
        """Revert a proposal."""
        self.db.execute(
            "UPDATE strategy_proposals SET status='reverted', evidence=? WHERE id=?",
            (reason, proposal_id),
        )
        self.db.commit()

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #

    def summary(self) -> str:
        wr, n = self.get_win_rate()
        lines = [
            f"Autonomy level: L{self.state.current_level}",
            f"Matches: {n}, Win rate: {wr:.1%}" if wr is not None else f"Matches: {n}, Win rate: N/A",
            f"Forfeit streak: {self.get_forfeit_streak()}",
            f"Timeout streak: {self.get_timeout_streak()}",
            f"Keep count: {self.state.keep_count}",
            f"Apply count: {self.state.apply_count}",
            f"Last decision: {self.state.last_decision.get('action', 'none')}",
        ]
        return "\n".join(lines)

    def __repr__(self) -> str:
        wr, n = self.get_win_rate()
        wr_str = f"{wr:.1%}" if wr is not None else "N/A"
        return f"RufloTCG(L{self.state.current_level}, matches={n}, wr={wr_str})"


if __name__ == "__main__":
    # Smoke test
    ruflo = RufloTCG()
    print(ruflo.summary())
    ruflo.observe_match(MatchResult(result="win", opponent="test", actions=18))
    ruflo.observe_match(MatchResult(result="loss", opponent="test", actions=16))
    print(ruflo.summary())
    decision = ruflo.check_promotion()
    print(f"Decision: {decision.action} — {decision.reason}")
