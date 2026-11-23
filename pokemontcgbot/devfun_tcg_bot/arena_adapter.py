"""Adapter from the real arena.dev.fun contract to the offline v2 policy.

Pure functions only: no HTTP client, no join, no action submission, no payment
handling. The live bot (bot_async.py) does not import this module.

Contract sources (read-only, verified 2026-11-23):
  GET /api/arena/__introspection -> {baseUrl, auth:{name:"x-arena-api-key"}, endpoints:[...]}
  GET /api/arena/tcg/pending-actions -> {"pending":[{matchId,seq,deadline,obs,legalActions}],
                                          "activeMatches":[...]}
  POST /api/arena/tcg/join -> {"competitionId":..., "joinPayload": <deck>}
  POST /api/arena/tcg/action -> {"matchId":..., "seq":..., "action": <legalActions string>}
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

REQUIRED_PATHS = {
    "join": "/api/arena/tcg/join",
    "pending": "/api/arena/tcg/pending-actions",
    "action": "/api/arena/tcg/action",
}

PLAYGROUND = "playground"
STAKES = "stakes"


class ContractError(ValueError):
    """Introspection payload does not expose the required TCG contract."""


class ArenaContract:
    """Endpoint/auth discovery from the authoritative introspection document."""

    def __init__(self, introspection: dict):
        if not isinstance(introspection, dict):
            raise ContractError("introspection payload is not an object")
        self.base_url = str(introspection.get("baseUrl") or "https://arena.dev.fun").rstrip("/")
        auth = introspection.get("auth") or {}
        self.auth_header = str(auth.get("name") or "x-arena-api-key")
        endpoints = introspection.get("endpoints")
        if not isinstance(endpoints, list):
            raise ContractError("introspection.endpoints is not a list of route objects")
        self.routes = {
            str(ep.get("path")): str(ep.get("method", "")).upper()
            for ep in endpoints
            if isinstance(ep, dict) and ep.get("path")
        }
        self.paths: Dict[str, str] = {}
        for name, path in REQUIRED_PATHS.items():
            if path not in self.routes:
                raise ContractError(f"missing required introspected route: {path}")
            self.paths[name] = path

    def url(self, name: str) -> str:
        return self.base_url + self.paths[name]

    def headers(self, api_key: str) -> Dict[str, str]:
        return {self.auth_header: api_key, "Content-Type": "application/json"}

    def summary(self) -> Dict[str, str]:
        return {"baseUrl": self.base_url, "auth": self.auth_header, **self.paths}


def classify_competitions(payload: Any) -> Dict[str, Optional[dict]]:
    """Split active competitions by gameType and name; ignore entryFee guesses."""
    comps = payload if isinstance(payload, list) else (payload or {}).get("competitions", [])
    result: Dict[str, Optional[dict]] = {PLAYGROUND: None, STAKES: None}
    for comp in comps or []:
        if not isinstance(comp, dict):
            continue
        if str(comp.get("gameType", "")).lower() != "pokemontcg":
            continue
        name = str(comp.get("name", "")).lower()
        key = STAKES if "stake" in name else PLAYGROUND
        if result[key] is None:
            result[key] = comp
    return result


def parse_pending(payload: Any) -> Tuple[List[dict], List[dict]]:
    """Return (pending, activeMatches) using the real response shape."""
    if not isinstance(payload, dict):
        raise ContractError("pending-actions payload is not an object")
    for key in ("pending", "activeMatches"):
        if key not in payload:
            raise ContractError(f"pending-actions payload missing required key: {key}")
    pending = payload["pending"] or []
    active = payload["activeMatches"] or []
    if not isinstance(pending, list) or not isinstance(active, list):
        raise ContractError("pending and activeMatches must be arrays")
    return pending, active


def pending_identity(entry: dict) -> Tuple[str, int]:
    """Server-side idempotency is keyed by (matchId, seq)."""
    if not isinstance(entry, dict) or not entry.get("matchId") or entry.get("seq") is None:
        raise ContractError("pending entry missing matchId or seq")
    return str(entry["matchId"]), int(entry["seq"])


def legal_action(entry: dict, action: str) -> str:
    """Reject any action outside the fresh legalActions list."""
    legal = entry.get("legalActions") or []
    if action not in legal:
        raise ContractError(f"action {action!r} is not in legalActions")
    return action


def join_body(competition_id: str, deck: List[Any]) -> Dict[str, Any]:
    """Owner-hosted join: the 60-card list is joinPayload, never 'deck'."""
    if not competition_id:
        raise ContractError("competitionId is required for join")
    if not isinstance(deck, list) or len(deck) != 60:
        raise ContractError("join deck must be a 60-card list")
    return {"competitionId": competition_id, "joinPayload": deck}


def action_body(entry: dict, action: str) -> Dict[str, Any]:
    """Build POST /tcg/action body with the verbatim seq from pending."""
    match_id, seq = pending_identity(entry)
    return {"matchId": match_id, "seq": seq, "action": legal_action(entry, action)}


def error_code(body: Any) -> str:
    """409 bodies vary: plain string or object with code/error."""
    if isinstance(body, str):
        return body
    if not isinstance(body, dict):
        return ""
    err = body.get("error")
    if isinstance(err, str):
        return err
    if isinstance(err, dict):
        return str(err.get("code") or "")
    return str(body.get("code") or "")


def retry_after_seconds(body: Any) -> Optional[float]:
    """Parse retryAfter defensively; a bad value must never raise into the loop."""
    if not isinstance(body, dict):
        return None
    raw = body.get("retryAfter")
    if raw is None and isinstance(body.get("error"), dict):
        raw = body["error"].get("retryAfter")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(value, 10.0))


def busy_conflict(status: int, body: Any) -> bool:
    """Only arena_transaction_busy is retryable; action_conflict is terminal."""
    return status == 409 and error_code(body) == "arena_transaction_busy"


def policy_state(entry: dict) -> Dict[str, Any]:
    """Map a real pending entry's obs into the offline policy's flat state shape.

    The real hand is hidden, so 'my_hand' is empty by design. Card entries are
    passed through as opaque objects/ids; the offline engine must not rely on
    card names here. This is an adapter, not a game-state emulator.
    """
    if not isinstance(entry, dict):
        raise ContractError("pending entry is not an object")
    obs = entry.get("obs") or {}
    current = obs.get("current") if isinstance(obs, dict) else None
    if not isinstance(current, dict):
        raise ContractError("entry.obs.current is not an object")
    try:
        yi = int(current["yourIndex"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("obs.current.yourIndex is required") from exc
    players = current.get("players") or []
    if len(players) < 2:
        raise ContractError("obs.current.players needs both seats")
    me = players[yi] or {}
    opp = players[1 - yi] or {}

    def count(zone: Any) -> int:
        if zone is None:
            return 0
        return len(zone) if isinstance(zone, (list, tuple, dict)) else 0

    return {
        "matchId": entry.get("matchId"),
        "seq": entry.get("seq"),
        "yourIndex": yi,
        "my_active": me.get("active"),
        "my_bench": list(me.get("bench") or []),
        "my_discard": list(me.get("discard") or []),
        "my_prizes": count(me.get("prize")),
        "my_deck_count": int(me.get("deckCount") or 0),
        "my_hand": [],  # hidden in owner-hosted play
        "opp_active": opp.get("active"),
        "opp_bench": list(opp.get("bench") or []),
        "opp_discard": list(opp.get("discard") or []),
        "opp_prizes": count(opp.get("prize")),
        "opp_deck_count": int(opp.get("deckCount") or 0),
        "legalActions": list(entry.get("legalActions") or []),
        "deadline": entry.get("deadline"),
    }


__all__ = [
    "ArenaContract", "ContractError", "classify_competitions", "parse_pending",
    "pending_identity", "legal_action", "join_body", "action_body", "error_code",
    "retry_after_seconds", "busy_conflict", "policy_state",
    "PLAYGROUND", "STAKES", "REQUIRED_PATHS",
]
