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

# Shared action selection + Ruflo result mapping (single implementation).
from bot import (
    _write_state,
    choose_action,
    match_result_from_api,
    load_reported_matches,
    save_reported_matches,
)

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


async def feed_ruflo_results(client, api_key, agent_id, ruflo, reported):
    """Poll recent matches and record newly settled ones in Ruflo."""
    if ruflo is None or not HAS_RUFLO:
        return 0
    status, resp = await api(
        client,
        "GET",
        f"/tcg/matches?competitionId={COMPETITION_ID}&agentId={agent_id}&limit=10",
        api_key,
        timeout=10,
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


async def play_loop(client, api_key, agent_id, ruflo=None):
    print("Entering async play loop. Ctrl+C to stop.")
    current_match = None
    last_rejoin = 0.0
    last_results_poll = 0.0
    reported = load_reported_matches() if (ruflo is not None and HAS_RUFLO) else set()

    while True:
        now = time.time()

        status, resp = await api(client, "GET", f"/tcg/pending-actions?competitionId={COMPETITION_ID}", api_key)
        if status != 200 or not isinstance(resp, dict):
            print(f"pending-actions error {status}: {resp}")
            await asyncio.sleep(2)
            continue

        pending = resp.get("pending") or []
        active = resp.get("activeMatches") or []

        if not pending:
            # Poll results only while idle so the request cannot delay an action.
            if ruflo is not None and HAS_RUFLO and now - last_results_poll >= 15:
                try:
                    await feed_ruflo_results(client, api_key, agent_id, ruflo, reported)
                except Exception as exc:
                    print(f"ruflo result poll failed: {exc}")
                last_results_poll = now

            if active:
                print(f"opponent acting; activeMatches={len(active)}")
            else:
                current_match = None
                if now - last_rejoin >= 10:
                    await join(client, api_key)
                    last_rejoin = now
                else:
                    print("queued, waiting for opponent (re-join throttled)")
            await asyncio.sleep(2)
            continue

        for entry in pending:
            match_id = entry["matchId"]
            seq = entry["seq"]

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

            # Never skip near the deadline; post the best legal action.
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

            st, r = await api(
                client,
                "POST",
                "/tcg/action",
                api_key,
                {"matchId": match_id, "seq": seq, "action": action},
                timeout=timeout,
            )
            print(f"match {match_id[:8]} seq {seq} -> {action} : {st} {r}")

            err = r.get("error") if isinstance(r, dict) else None
            err_code = err.get("code") if isinstance(err, dict) else None
            if st == 409 and err_code == "arena_transaction_busy":
                retry_after = int(err.get("retryAfter", 1)) if isinstance(err, dict) else 1
                await asyncio.sleep(max(1, retry_after))
                await api(
                    client,
                    "POST",
                    "/tcg/action",
                    api_key,
                    {"matchId": match_id, "seq": seq, "action": action},
                    timeout=timeout,
                )

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

        # Persist state (merge, so reported Ruflo match ids survive restarts)
        try:
            _write_state({
                "competition_id": COMPETITION_ID,
                "season_number": 6,
                "deck": DECK,
                "deck_locked": True,
                "async": True,
                "belief_enabled": HAS_BELIEF,
                "ruflo_enabled": HAS_RUFLO,
            })
        except Exception as e:
            print(f"state write failed: {e}")

        await play_loop(client, api_key, creds["agentId"], ruflo=RUFLO)


if __name__ == "__main__":
    if not HAS_HTTPX:
        print("ERROR: httpx not installed. Run: pip install httpx")
        raise SystemExit(1)
    asyncio.run(main())
