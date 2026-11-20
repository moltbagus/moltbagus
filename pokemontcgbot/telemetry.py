"""One JSON line per decision point (world-class spec section 7).

Why this exists: the bot used to log only ``match <id> seq <n> -> [i] : 200``,
which cannot be replayed offline. Every strategic claim about this policy has
had to be re-derived from the arena API by hand. This module records the
decision input, the choice, the alternatives the policy scored, and the board
state, so a replay harness can report illegal actions and choice deltas without
touching the network.

Rules this module keeps:

* It never raises into the decision path. ``build_record`` returns ``None`` on
  any unexpected observation shape and ``record`` swallows every error.
* It re-derives nothing scoring already owns: options, action indices and
  scores come from ``scoring`` helpers.
* Only public/own-side state is written. No API key, no credentials, no
  opponent hand contents (the arena does not expose them anyway).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from arena_config import POLICY_VERSION, TELEMETRY_PATH
from scoring import action_score, parse_action_indices, players_of, select_of

# Rotate once at this size; a rotated file stays replayable on its own.
MAX_BYTES = 64 * 1024 * 1024
# A deck-search decision can expose ~60 options; scoring all of them every
# decision is waste. The chosen action is always scored, the rest are capped.
MAX_CANDIDATES = 24


def _as_int(value: Any, default: Optional[int] = 0) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _card_snapshot(card: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(card, dict):
        return None
    snap: Dict[str, Any] = {"id": _as_int(card.get("id"), -1)}
    hp = card.get("hp")
    if hp is not None:
        snap["hp"] = _as_int(hp, None)
    energies = card.get("energies")
    snap["energy"] = len(energies) if isinstance(energies, list) else 0
    return snap


def _first_card(cards: Any) -> Optional[Dict[str, Any]]:
    if isinstance(cards, list):
        for card in cards:
            if isinstance(card, dict):
                return card
    return None


def _current_of(obs: Any) -> Dict[str, Any]:
    current = obs.get("current") if isinstance(obs, dict) else None
    return current if isinstance(current, dict) else {}


def _state_snapshot(obs: Any) -> Dict[str, Any]:
    """Compact board snapshot: ours in full, the opponent's public board."""
    current = _current_of(obs)
    players = players_of(obs)
    your_index = _as_int(current.get("yourIndex", 0), 0) or 0
    theirs = 0 if your_index == 1 else 1

    ours = players[your_index] if 0 <= your_index < len(players) else {}
    theirs_player = players[theirs] if 0 <= theirs < len(players) else {}
    ours = ours if isinstance(ours, dict) else {}
    theirs_player = theirs_player if isinstance(theirs_player, dict) else {}

    bench: List[List[int]] = []
    for card in ours.get("bench") or []:
        snap = _card_snapshot(card)
        if snap is not None:
            bench.append([snap["id"], snap["energy"]])

    prizes = ours.get("prize") or []
    return {
        "active": _card_snapshot(_first_card(ours.get("active"))),
        "bench": bench,
        "oppActive": _card_snapshot(_first_card(theirs_player.get("active"))),
        "handCount": _as_int(ours.get("handCount"), 0),
        "prizes": len(prizes) if isinstance(prizes, list) else 0,
    }


def build_record(
    pending_entry: Any,
    chosen: Any,
    latency_ms: float,
    policy_version: str = POLICY_VERSION,
    now_ms: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Build one telemetry record. Returns ``None`` on an unusable entry."""
    if not isinstance(pending_entry, dict):
        return None
    obs = pending_entry.get("obs") or {}
    select = select_of(obs)
    raw_options = select.get("option")
    options = raw_options if isinstance(raw_options, list) else []
    raw_legal = pending_entry.get("legalActions")
    legal = [a for a in raw_legal if isinstance(a, str)] if isinstance(raw_legal, list) else []

    indices = parse_action_indices(chosen)
    chosen_types: List[int] = []
    for index in indices:
        if 0 <= index < len(options) and isinstance(options[index], dict):
            chosen_types.append(_as_int(options[index].get("type"), -1))

    try:
        chosen_scores: List[Optional[float]] = [
            round(float(action_score(chosen, obs)), 3)
        ]
    except Exception:
        chosen_scores = [None]

    candidates: List[Dict[str, Any]] = []
    for action in legal[:MAX_CANDIDATES]:
        try:
            score: Optional[float] = round(float(action_score(action, obs)), 3)
        except Exception:
            score = None
        candidates.append({"action": action, "score": score})

    current = _current_of(obs)
    return {
        "ts": int(now_ms if now_ms is not None else time.time() * 1000),
        "matchId": str(pending_entry.get("matchId") or ""),
        "seq": _as_int(pending_entry.get("seq"), 0),
        "turn": _as_int(current.get("turn"), None),
        "selectType": _as_int(select.get("type"), None),
        "context": _as_int(select.get("context"), None),
        "nOptions": len(options) if isinstance(options, list) else 0,
        "nLegal": len(legal),
        "chosen": chosen if isinstance(chosen, str) else str(chosen),
        "chosenTypes": chosen_types,
        "latencyMs": round(float(latency_ms), 3),
        "scores": chosen_scores,
        "candidates": candidates,
        "state": _state_snapshot(obs),
        "policyVersion": policy_version,
    }


def _rotate_if_needed(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_BYTES:
            path.replace(path.with_suffix(path.suffix + ".1"))
    except OSError:
        pass


def record(
    pending_entry: Any,
    chosen: Any,
    latency_ms: float,
    path: Optional[Path] = None,
    policy_version: str = POLICY_VERSION,
) -> bool:
    """Append one decision record. Never raises; returns False on failure."""
    try:
        entry = build_record(pending_entry, chosen, latency_ms, policy_version)
        if entry is None:
            return False
        target = Path(path) if path is not None else TELEMETRY_PATH
        _rotate_if_needed(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, separators=(",", ":")) + "\n")
        return True
    except Exception:
        return False


def read(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Read back records, skipping any line that is not valid JSON."""
    target = Path(path) if path is not None else TELEMETRY_PATH
    out: List[Dict[str, Any]] = []
    try:
        with target.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        return out
    return out
