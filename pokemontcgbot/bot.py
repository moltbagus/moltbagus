#!/usr/bin/env python3
"""Minimal legal Pokemon TCG bot for DevFun Arena (owner-hosted / remote mode).

Reads credentials from ~/.arena-credentials. Deck is a simple, legal
starter list: 4x Budew (card 235) + 56x Basic Grass Energy (card 1).

Join is idempotent; the deck is locked for the season on first successful join.
Run: python3 bot.py            (join + play loop)
     python3 bot.py --join-only (join then exit)
"""
import argparse
import fcntl
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from scoring import best_action

# Belief tracking + ISMCTS search
try:
    from belief import BeliefTracker, build_tracker_from_obs
    from ismcts import ISMCTSSearch, BeliefWeightedHeuristic, create_belief_tracker
    HAS_BELIEF = True
except ImportError:
    HAS_BELIEF = False

# Ruflo self-improvement
try:
    from ruflo_tcg import RufloTCG, MatchResult
    HAS_RUFLO = True
except ImportError:
    HAS_RUFLO = False

CREDS_PATH = Path.home() / ".arena-credentials"
COMPETITION_ID = "cmwm3cekx011nln01c3gqi0tc"
BASE_URL = "https://arena.dev.fun/api/arena"
STATE_PATH = Path.home() / ".arena-tcg-state"
LOCK_PATH = Path.home() / ".arena-tcg.lock"

# Keep every non-action request short so a slow poll cannot eat a match deadline.
PENDING_TIMEOUT = 3.0
JOIN_TIMEOUT = 5.0
RESULTS_TIMEOUT = 5.0

# Global instances (initialized in main)
BELIEF_HEURISTIC = None
RUFLO = None
_LOCK_HANDLE = None

# S7 deck: Alakazam / Dudunsparce / Fezandipiti with the Audino package.
# 18 Pokemon + 30 Trainers + 12 Basic Psychic Energy = 60.
DECK = (
    [741] * 3 + [742] * 2 + [245] * 2      # Abra / Kadabra / Alakazam
    + [305] * 3 + [306] * 2                 # Dunsparce / Dudunsparce ex
    + [140] * 2                             # Fezandipiti ex
    + [1006] * 2 + [554] * 2                # Mega Audino ex / Audino
    + [1086] * 4 + [1152] * 4               # Buddy-Buddy Poffin / Poke Pad
    + [1231] * 3 + [1182] * 3              # Dawn / Boss's Orders
    + [1097] * 3 + [1198] * 3              # Night Stretcher / Crispin
    + [1197] * 3 + [1081] * 3              # Xerosic's Machinations / Enhanced Hammer
    + [1129] * 2 + [1266] * 2              # Sacred Ash / Nighttime Mine
    + [5] * 12                              # Basic Psychic Energy
)
BASIC_POKEMON_IDS = {741, 305, 140, 1006, 554, 625, 328, 299, 39, 390}


def load_creds():
    with CREDS_PATH.open() as f:
        d = json.load(f)
    if not d.get("apiKey") or not d.get("agentId"):
        raise SystemExit("Invalid credentials file")
    return d


def acquire_single_instance_lock(path=None):
    """Refuse to run a second poller for the same agent/competition."""
    lock_path = Path(path) if path is not None else LOCK_PATH
    handle = open(lock_path, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise SystemExit(
            f"another TCG bot poller is already running (lock: {lock_path})"
        )
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def api(method, path, api_key=None, body=None, timeout=30):
    url = BASE_URL + path
    data = None
    headers = {"Accept": "application/json"}
    if api_key:
        headers["x-arena-api-key"] = api_key
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"error": raw}
    except Exception as e:
        return 0, {"error": str(e)}


def validate_deck(deck):
    assert len(deck) == 60, f"deck must be 60 cards, got {len(deck)}"
    from collections import Counter
    # basic energy is cardId 1-8; treat any basic energy as exempt
    energy_ids = set(range(1, 9))
    counts = Counter(x for x in deck if x not in energy_ids)
    bad = {k: v for k, v in counts.items() if v > 4}
    assert not bad, f"copy limit exceeded: {bad}"
    assert any(c in deck for c in BASIC_POKEMON_IDS), "need at least one Basic Pokemon"
    return True


def join(api_key):
    status, resp = api("POST", "/tcg/join", api_key, {"competitionId": COMPETITION_ID, "joinPayload": DECK}, timeout=JOIN_TIMEOUT)
    print(f"join -> {status}: {resp}")
    return status, resp


def _read_state():
    try:
        data = json.loads(STATE_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(updates=None):
    """Merge updates into the persisted state file and write atomically."""
    state = _read_state()
    if updates:
        state.update(updates)
    tmp = Path(str(STATE_PATH) + ".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_PATH)


def load_reported_matches():
    """Match ids already handed to Ruflo, so restarts do not double-count."""
    ids = _read_state().get("ruflo_reported_matches") or []
    return {str(mid) for mid in ids if mid}


def save_reported_matches(match_ids):
    _write_state({"ruflo_reported_matches": sorted(match_ids)})


def match_result_from_api(match, our_agent_id):
    """Convert one /tcg/matches entry into a Ruflo MatchResult."""
    if not isinstance(match, dict) or match.get("status") != "Settled":
        return None
    if not HAS_RUFLO:
        return None

    result_info = match.get("result") or {}
    agent_result = match.get("agentResult") or {}
    outcome = str(agent_result.get("outcome") or "").lower()
    if not outcome:
        winner = result_info.get("winnerAgentId")
        outcome = "win" if winner == our_agent_id else "loss"
    if outcome not in ("win", "loss", "forfeit", "timeout"):
        outcome = "loss"

    reason = str(result_info.get("reason") or "")
    if outcome == "loss":
        if "timeout" in reason or "deadline" in reason:
            outcome = "timeout"
        elif "forfeit" in reason:
            outcome = "forfeit"

    opponent = ""
    for player in match.get("players") or []:
        if isinstance(player, dict) and player.get("agentId") != our_agent_id:
            opponent = str(player.get("handle") or player.get("name") or "")
            break

    try:
        actions = int(match.get("playedActionCount") or 0)
    except (TypeError, ValueError):
        actions = 0

    return MatchResult(
        result=outcome,
        opponent=opponent,
        actions=actions,
        deck_version="druddigon-v2",
        heuristic="belief-ismcts",
        notes=reason,
    )


def feed_ruflo_results(api_key, agent_id, ruflo, reported):
    """Poll recent matches and record newly settled ones in Ruflo."""
    if ruflo is None or not HAS_RUFLO:
        return 0
    status, resp = api(
        "GET",
        f"/tcg/matches?competitionId={COMPETITION_ID}&agentId={agent_id}&limit=10",
        api_key,
        timeout=RESULTS_TIMEOUT,
    )
    if status != 200 or not isinstance(resp, dict):
        return 0

    added = 0
    for match in resp.get("matches") or []:
        result = match_result_from_api(match, agent_id)
        if result is None:
            continue
        match_id = match.get("matchId")
        if not match_id or match_id in reported:
            continue
        try:
            ruflo.observe_match(result)
            reported.add(match_id)
            added += 1
        except Exception as exc:
            print(f"ruflo observe_match failed for {match_id[:8]}: {exc}")
    if added:
        save_reported_matches(reported)
        print(f"ruflo: recorded {added} settled match(es)")
    return added


def error_code(resp):
    """Return an arena error code from either a dict or a plain string error."""
    if not isinstance(resp, dict):
        return None
    err = resp.get("error")
    if isinstance(err, dict):
        return err.get("code")
    if isinstance(err, str):
        return err
    return None


def choose_action(pending_entry, belief_heuristic=None):
    legal = pending_entry.get("legalActions") or []
    if not legal:
        return None

    obs = pending_entry.get("obs") or {}

    # Single belief-update path for every decision point.
    if belief_heuristic is not None and HAS_BELIEF:
        try:
            belief_heuristic.search.update_belief_from_obs(obs)
        except Exception:
            pass
        try:
            result = belief_heuristic.choose(obs, legal)
            if result in legal:
                return result
        except Exception:
            pass

    # Card-aware fallback (the obs has no damage field; options use type/attackId).
    chosen = best_action(obs, legal)
    return chosen if chosen is not None else legal[0]


def play_loop(api_key, agent_id, ruflo=None):
    print("Entering play loop. Ctrl+C to stop.")
    current_match = None
    last_rejoin = 0.0
    last_results_poll = 0.0
    reported = load_reported_matches() if (ruflo is not None and HAS_RUFLO) else set()

    while True:
        now = time.time()

        status, resp = api("GET", f"/tcg/pending-actions?competitionId={COMPETITION_ID}", api_key, timeout=PENDING_TIMEOUT)
        if status != 200 or not isinstance(resp, dict):
            print(f"pending-actions error {status}: {resp}")
            time.sleep(2)
            continue
        pending = resp.get("pending") or []
        active = resp.get("activeMatches") or []
        if not pending:
            # Only poll results while there is no decision to answer, so the
            # extra request can never eat an action deadline.
            if ruflo is not None and HAS_RUFLO and now - last_results_poll >= 15:
                try:
                    feed_ruflo_results(api_key, agent_id, ruflo, reported)
                except Exception as exc:
                    print(f"ruflo result poll failed: {exc}")
                last_results_poll = now

            if active:
                print(f"opponent acting; activeMatches={len(active)}")
            else:
                current_match = None
                # Keep queue position by re-joining; idempotent on the arena.
                if now - last_rejoin >= 10:
                    join(api_key)
                    last_rejoin = now
                else:
                    print("queued, waiting for opponent (re-join throttled)")
            time.sleep(2)
            continue

        for entry in pending:
            match_id = entry["matchId"]
            seq = entry["seq"]

            # One opponent belief per match; snapshots are idempotent.
            if match_id != current_match:
                current_match = match_id
                if BELIEF_HEURISTIC is not None and HAS_BELIEF:
                    try:
                        BELIEF_HEURISTIC.belief.reset_for_match()
                    except Exception:
                        pass

            action = choose_action(entry, BELIEF_HEURISTIC)
            if action is None:
                legal = entry.get("legalActions") or []
                if not legal:
                    print(f"no legal action for {match_id} seq {seq}")
                    continue
                action = legal[0]

            # Never forfeit by skipping: post the best legal action even when
            # the deadline is close.  Shrink the HTTP timeout to fit what is left.
            deadline = entry.get("deadline")
            timeout = 10.0
            if deadline:
                try:
                    remaining = (int(deadline) - int(time.time() * 1000)) / 1000.0
                except (TypeError, ValueError):
                    remaining = None
                if remaining is not None:
                    if remaining < 2:
                        print(f"deadline {remaining:.1f}s; posting best legal action anyway")
                    timeout = max(2.0, min(10.0, remaining)) if remaining > 0 else 2.0

            st, r = api(
                "POST",
                "/tcg/action",
                api_key,
                {"matchId": match_id, "seq": seq, "action": action},
                timeout=timeout,
            )
            print(f"match {match_id[:8]} seq {seq} -> {action} : {st} {r}")

            err_code = error_code(r)
            err = r.get("error") if isinstance(r, dict) else None
            if st == 409 and err_code == "arena_transaction_busy":
                retry_after = 1
                try:
                    retry_after = int(err.get("retryAfter", 1)) if isinstance(err, dict) else 1
                except Exception:
                    pass
                time.sleep(max(1, retry_after))
                api(
                    "POST",
                    "/tcg/action",
                    api_key,
                    {"matchId": match_id, "seq": seq, "action": action},
                    timeout=timeout,
                )
            elif st == 409 and err_code == "action_conflict":
                # Another action already won this seq; re-poll instead of crashing.
                print(f"seq {seq} already answered; continuing")
        time.sleep(1)


def main():
    global BELIEF_HEURISTIC, RUFLO, _LOCK_HANDLE

    parser = argparse.ArgumentParser()
    parser.add_argument("--join-only", action="store_true")
    args = parser.parse_args()

    _LOCK_HANDLE = acquire_single_instance_lock()
    validate_deck(DECK)
    creds = load_creds()
    api_key = creds["apiKey"]
    print(f"agent={creds['handle']} agentId={creds['agentId']}")
    print(f"deck: {len(DECK)} cards (Abra/Kadabra/Alakazam + Dunsparce/Dudunsparce ex + Fezandipiti ex + Mega Audino ex/Audino + 30 trainers + 12 Psychic Energy)")

    # Initialize belief tracker + heuristic
    if HAS_BELIEF:
        try:
            archetype = {}  # infer opponent archetype from observed cards only
            tracker = create_belief_tracker(archetype)
            BELIEF_HEURISTIC = BeliefWeightedHeuristic(tracker, time_budget_ms=1000)
            print("Belief tracker + ISMCTS heuristic: ENABLED")
        except Exception as e:
            print(f"Belief tracker init failed: {e}")

    # Initialize ruflo self-improvement
    if HAS_RUFLO:
        try:
            RUFLO = RufloTCG()
            print(f"Ruflo self-improvement: ENABLED (level L{RUFLO.state.current_level})")
        except Exception as e:
            print(f"Ruflo init failed: {e}")

    status, resp = join(api_key)
    if status not in (200, 201, 202, 409):
        raise SystemExit(f"join failed: {status} {resp}")

    if args.join_only:
        return

    # persist state
    try:
        _write_state({
            "competition_id": COMPETITION_ID,
            "season_number": 6,
            "deck": DECK,
            "deck_locked": True,
            "deck_thesis": "Mixed high-HP 0-energy attackers: Druddigon(40dmg) + Pikachu ex(190HP) + Hop's Zacian ex(230HP) + Enamorus + Tauros + 40 Grass Energy",
            "belief_enabled": HAS_BELIEF,
            "ruflo_enabled": HAS_RUFLO,
            "matches_played": 0,
            "matches_won": 0,
            "decisions_answered": 0,
            "forfeits": 0,
        })
    except Exception as e:
        print(f"state write failed: {e}")

    play_loop(api_key, creds["agentId"], ruflo=RUFLO)


if __name__ == "__main__":
    main()