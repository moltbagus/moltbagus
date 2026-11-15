"""Async Pokemon TCG bot for DevFun Arena (owner-hosted / remote mode).

Converts the synchronous bot.py to async I/O using aiohttp.
Fixes timeout forfeits by using non-blocking HTTP and deadline-aware polling.

Usage:
    python3 bot_async.py            (join + play loop)
    python3 bot_async.py --join-only (join then exit)
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

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

# New high-HP deck (will be locked on first join — use sandbox for changes)
DECK = [625] * 4 + [328] * 4 + [299] * 4 + [39] * 4 + [390] * 4 + [1] * 40

# Global instances
BELIEF_HEURISTIC = None
RUFLO = None


def load_creds():
    with CREDS_PATH.open() as f:
        d = json.load(f)
    if not d.get("apiKey") or not d.get("agentId"):
        raise SystemExit("Invalid credentials file")
    return d


async def api(client, method, path, api_key=None, body=None, timeout=30):
    url = BASE_URL + path
    headers = {"Accept": "application/json"}
    if api_key:
        headers["x-arena-api-key"] = api_key
    try:
        if method == "GET":
            r = await client.get(url, headers=headers, timeout=timeout)
        else:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode() if body else None
            r = await client.post(url, content=data, headers=headers, timeout=timeout)
        raw = r.text
        try:
            return r.status_code, (json.loads(raw) if raw else None)
        except json.JSONDecodeError:
            return r.status_code, {"error": raw}
    except httpx.TimeoutException:
        return 0, {"error": "timeout"}
    except Exception as e:
        return 0, {"error": str(e)}


def validate_deck(deck):
    assert len(deck) == 60, f"deck must be 60 cards, got {len(deck)}"
    from collections import Counter
    energy_ids = set(range(1, 9))
    counts = Counter(x for x in deck if x not in energy_ids)
    bad = {k: v for k, v in counts.items() if v > 4}
    assert not bad, f"copy limit exceeded: {bad}"
    assert any(c in deck for c in (625, 328, 299, 39, 390)), "need at least one Basic Pokemon"
    return True


async def join(client, api_key):
    status, resp = await api(client, "POST", "/tcg/join", api_key, {"competitionId": COMPETITION_ID, "joinPayload": DECK})
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

    # Fallback: damage-based heuristic
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


async def play_loop(client, api_key, ruflo=None):
    print("Entering async play loop. Ctrl+C to stop.")
    while True:
        status, resp = await api(client, "GET", f"/tcg/pending-actions?competitionId={COMPETITION_ID}", api_key)
        if status != 200 or not isinstance(resp, dict):
            print(f"pending-actions error {status}: {resp}")
            await asyncio.sleep(2)
            continue

        pending = resp.get("pending") or []
        active = resp.get("activeMatches") or []

        if not pending:
            if active:
                print(f"opponent acting; activeMatches={len(active)}")
            else:
                print("queued, waiting for opponent...")
                await join(client, api_key)
            await asyncio.sleep(2)
            continue

        for entry in pending:
            match_id = entry["matchId"]
            seq = entry["seq"]
            deadline = entry.get("deadline")
            action = choose_action(entry, BELIEF_HEURISTIC)

            if action is None:
                print(f"no legal action for {match_id} seq {seq}")
                continue

            # Deadline safety
            if deadline:
                remaining = (deadline - int(time.time() * 1000)) / 1000.0
                if remaining < 1:
                    print(f"deadline too close ({remaining:.1f}s); skipping")
                    continue

            st, r = await api(client, "POST", "/tcg/action", api_key, {"matchId": match_id, "seq": seq, "action": action})
            print(f"match {match_id[:8]} seq {seq} -> {action} : {st} {r}")

            if st == 409 and isinstance(r, dict) and r.get("error", {}).get("code") == "arena_transaction_busy":
                retry_after = int(r.get("error", {}).get("retryAfter", 1))
                await asyncio.sleep(max(1, retry_after))
                await api(client, "POST", "/tcg/action", api_key, {"matchId": match_id, "seq": seq, "action": action})

        await asyncio.sleep(1)


async def main():
    global BELIEF_HEURISTIC, RUFLO

    parser = argparse.ArgumentParser()
    parser.add_argument("--join-only", action="store_true")
    args = parser.parse_args()

    validate_deck(DECK)
    creds = load_creds()
    api_key = creds["apiKey"]
    print(f"agent={creds['handle']} agentId={creds['agentId']}")
    print(f"deck: {len(DECK)} cards (high-HP 0-energy attackers)")

    # Initialize belief tracker
    if HAS_BELIEF:
        try:
            archetype = {625: 4, 328: 4, 299: 4, 39: 4, 390: 4, 1: 40}
            tracker = create_belief_tracker(archetype)
            BELIEF_HEURISTIC = BeliefWeightedHeuristic(tracker, time_budget_ms=1000)
            print("Belief tracker + ISMCTS heuristic: ENABLED")
        except Exception as e:
            print(f"Belief tracker init failed: {e}")

    # Initialize ruflo
    if HAS_RUFLO:
        try:
            RUFLO = RufloTCG()
            print(f"Ruflo self-improvement: ENABLED (level L{RUFLO.state.current_level})")
        except Exception as e:
            print(f"Ruflo init failed: {e}")

    async with httpx.AsyncClient() as client:
        status, resp = await join(client, api_key)
        if status not in (200, 201, 202, 409):
            raise SystemExit(f"join failed: {status} {resp}")

        if args.join_only:
            return

        # Persist state
        try:
            STATE_PATH.write_text(json.dumps({
                "competition_id": COMPETITION_ID,
                "season_number": 6,
                "deck": DECK,
                "deck_locked": True,
                "async": True,
                "belief_enabled": HAS_BELIEF,
                "ruflo_enabled": HAS_RUFLO,
            }, indent=2))
        except Exception as e:
            print(f"state write failed: {e}")

        await play_loop(client, api_key, ruflo=RUFLO)


if __name__ == "__main__":
    if not HAS_HTTPX:
        print("ERROR: httpx not installed. Run: pip install httpx")
        raise SystemExit(1)
    asyncio.run(main())
