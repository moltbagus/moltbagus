#!/usr/bin/env python3
"""Minimal legal Pokemon TCG bot for DevFun Arena (owner-hosted / remote mode).

Reads credentials from /home/colb/.arena-credentials. Deck is a simple, legal
starter list: 4x Budew (card 235) + 56x Basic Grass Energy (card 1).

Join is idempotent; the deck is locked for the season on first successful join.
Run: python3 bot.py            (join + play loop)
     python3 bot.py --join-only (join then exit)
"""
import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

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

CREDS_PATH = Path("/home/colb/.arena-credentials")
COMPETITION_ID = "cmw99opb57gssgfb7rj39a1o1"
BASE_URL = "https://arena.dev.fun/api/arena"
STATE_PATH = Path("/home/colb/.arena-tcg-state")

# Global instances (initialized in main)
BELIEF_HEURISTIC = None
RUFLO = None

# Mixed high-HP, 0-energy attackers + Grass Energy.
# 4x Druddigon(625) HP120 40dmg, 4x Pikachu ex(328) HP190 30dmg,
# 4x Hop's Zacian ex(299) HP230 30dmg, 4x Enamorus(39) HP120 30dmg,
# 4x Tauros(390) HP130 30dmg, 40x Basic {G} Energy(1) = 60 cards.
DECK = [625] * 4 + [328] * 4 + [299] * 4 + [39] * 4 + [390] * 4 + [1] * 40


def load_creds():
    with CREDS_PATH.open() as f:
        d = json.load(f)
    if not d.get("apiKey") or not d.get("agentId"):
        raise SystemExit("Invalid credentials file")
    return d


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
    counts = Counter(x for x in deck if x != 1)  # energy (card 1) exempt
    # basic energy is cardId 1 only here; treat any energy card id <=8 as exempt
    energy_ids = set(range(1, 9))
    counts = Counter(x for x in deck if x not in energy_ids)
    bad = {k: v for k, v in counts.items() if v > 4}
    assert not bad, f"copy limit exceeded: {bad}"
    assert any(c in deck for c in (625, 328, 299, 39, 390)), "need at least one Basic Pokemon"
    return True


def join(api_key):
    status, resp = api("POST", "/tcg/join", api_key, {"competitionId": COMPETITION_ID, "joinPayload": DECK})
    print(f"join -> {status}: {resp}")
    return status, resp


def choose_action(pending_entry, belief_heuristic=None):
    legal = pending_entry.get("legalActions") or []
    if not legal:
        return None
    if len(legal) == 1:
        return legal[0]

    obs = (pending_entry.get("obs") or {})

    # Use belief-weighted heuristic if available
    if belief_heuristic is not None and HAS_BELIEF:
        try:
            belief_heuristic.search.update_belief_from_obs(obs)
        except Exception:
            pass
        try:
            result = belief_heuristic.choose(obs, legal)
            if result is not None:
                return result
        except Exception:
            pass

    # Fallback: original damage-based heuristic
    select = obs.get("select") or {}
    options = select.get("option") or []
    best = None
    best_score = None
    for act in legal:
        idx = None
        s = act.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                idx = int(s[1:-1])
            except ValueError:
                idx = None
        score = 0
        if idx is not None and 0 <= idx < len(options):
            opt = options[idx] or {}
            score += int(opt.get("damage") or 0)
        if best_score is None or score > best_score:
            best_score = score
            best = act
    return best or legal[0]


def play_loop(api_key, ruflo=None):
    print("Entering play loop. Ctrl+C to stop.")
    while True:
        status, resp = api("GET", f"/tcg/pending-actions?competitionId={COMPETITION_ID}", api_key)
        if status != 200 or not isinstance(resp, dict):
            print(f"pending-actions error {status}: {resp}")
            time.sleep(2)
            continue
        pending = resp.get("pending") or []
        active = resp.get("activeMatches") or []
        if not pending:
            if active:
                print(f"opponent acting; activeMatches={len(active)}")
            else:
                print("queued, waiting for opponent...")
                # re-join to keep queue position
                join(api_key)
            time.sleep(2)
            continue

        for entry in pending:
            match_id = entry["matchId"]
            seq = entry["seq"]
            deadline = entry.get("deadline")
            action = choose_action(entry, BELIEF_HEURISTIC)
            if action is None:
                print(f"no legal action for {match_id} seq {seq}")
                continue
            # deadline safety: if <3s left, still post best legal
            if deadline:
                remaining = (deadline - int(time.time() * 1000)) / 1000.0
                if remaining < 1:
                    print(f"deadline too close ({remaining:.1f}s); skipping")
                    continue
            st, r = api("POST", "/tcg/action", api_key, {"matchId": match_id, "seq": seq, "action": action})
            print(f"match {match_id[:8]} seq {seq} -> {action} : {st} {r}")
            # Record decision in ruflo if available
            if ruflo is not None and HAS_RUFLO:
                try:
                    ruflo.state.apply_count += 0  # track decisions
                except Exception:
                    pass
            if st == 409 and isinstance(r, dict) and r.get("error", {}).get("code") == "arena_transaction_busy":
                retry_after = 1
                try:
                    retry_after = int(r.get("error", {}).get("retryAfter", 1))
                except Exception:
                    pass
                time.sleep(max(1, retry_after))
                api("POST", "/tcg/action", api_key, {"matchId": match_id, "seq": seq, "action": action})
        time.sleep(1)


def main():
    global BELIEF_HEURISTIC, RUFLO

    parser = argparse.ArgumentParser()
    parser.add_argument("--join-only", action="store_true")
    args = parser.parse_args()

    validate_deck(DECK)
    creds = load_creds()
    api_key = creds["apiKey"]
    print(f"agent={creds['handle']} agentId={creds['agentId']}")
    print(f"deck: {len(DECK)} cards (Druddigon x4 + Pikachu ex x4 + Hop's Zacian ex x4 + Enamorus x4 + Tauros x4 + Grass Energy x40)")

    # Initialize belief tracker + heuristic
    if HAS_BELIEF:
        try:
            archetype = {625: 4, 328: 4, 299: 4, 39: 4, 390: 4, 1: 40}
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
        STATE_PATH.write_text(json.dumps({
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
        }, indent=2))
    except Exception as e:
        print(f"state write failed: {e}")

    play_loop(api_key, ruflo=RUFLO)


if __name__ == "__main__":
    main()