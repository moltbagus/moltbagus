"""Fetch the arena card pool once and write a bounded snapshot for M3.

The candidate deck (``deck_candidate.json``) must be checkable offline, against
card and attack facts that came from the arena rather than from memory. This
script is the only place that touches the network for that purpose:

1. ``GET /tcg/cards?competitionId=<id>``   (1267 cards on 2026-11-21)
2. ``GET /tcg/attacks?competitionId=<id>`` (1556 attacks on 2026-11-21)
3. keep the bound below, drop the rest, and write
   ``docs/data/card_pool_snapshot.json``.

The bound is intentionally wider than the candidate list: every card the plan
argues about (chosen, cut, and considered-then-rejected) is kept, so a reader
can re-derive any decision from the snapshot alone. The full pool is never
checked in — 748 KB of cards the deck cannot use would rot.

Usage::

    python3 scripts/build_card_pool_snapshot.py                 # fetch
    python3 scripts/build_card_pool_snapshot.py --raw raw.json  # reuse a fetch

The API key is read from ``~/.arena-credentials`` and never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import arena_config  # noqa: E402

CREDS_PATH = Path.home() / ".arena-credentials"
OUT_PATH = REPO / "docs" / "data" / "card_pool_snapshot.json"
CANDIDATE_PATH = REPO / "deck_candidate.json"

# Cards the plan reasons about but that are NOT in the candidate list. Each
# group exists so a reviewer can re-run the rejected-option argument offline.
CONSIDERED = {
    # draw supporters inspected and rejected (weaker, conditional, or hostile)
    "rejected_draw_supporters": [
        1181,  # Billy & O'Nare — draw 2 (+2 only at 10+ cards in hand)
        1187,  # Morty's Conviction — requires discarding a card
        1192,  # Carmine — discard your hand, draw 5
        1199,  # Lacey — shuffle hand, draw 4 (8 only at <=3 prizes)
        1200,  # Kofu — requires putting 2 cards on the bottom
        1203,  # Surfer — switch + draw to 5
        1207,  # Amarys — draw 4 then discard hand at end of turn
        1208,  # Iris's Fighting Spirit — requires discarding a card
        1214,  # Emcee's Hype — draw 2 (+2 only at <=3 prizes)
        1216,  # Team Rocket's Ariana — draw to 5, 8 only with TR board
        1217,  # Team Rocket's Archer — requires a TR Pokemon KO'd
        1223,  # Harlequin — coin flip
        1226,  # Lt. Surge's Bargain — opponent chooses
        1236,  # Urbain — draw 3 (same text as Cheren; Cheren kept by name)
        1237,  # Lucian — coin flips
        1239,  # Naveen — draw to 5
    ],
    # energy acceleration inspected
    "rejected_acceleration": [
        1135,  # Energy Coin — flip 2 coins, both heads
        1163,  # Powerglass — tool, end of turn, active only
        1235,  # Waitress — supporter slot, top 6
        1240,  # Rosa's Encouragement — only with more prizes remaining
        1089,  # Reboot Pod — Future Pokemon only
        1098,  # Glass Trumpet — Tera Pokemon only
        1113,  # N's PP Up — N's Pokemon only
        1147,  # Jumbo Ice Cream — heal, not ramp
    ],
    # ACE SPECs inspected (the candidate runs none)
    "rejected_ace_spec": [
        10,    # Enriching Energy — special energy, draw 4 on attach
        12,    # Legacy Energy
        1088,  # Prime Catcher — gusting we already have via Boss's Orders
        1092,  # Secret Box — discard 3
        1093,  # Scoop Up Cyclone
        1096,  # Poke Vital A
        1100,  # Energy Search Pro
        1109,  # Miracle Headset
        1110,  # Max Rod
        1125,  # Master Ball
        1126,  # Precious Trolley
        1128,  # Brilliant Blender
        1155,  # Survival Brace
        1158,  # Maximum Belt
        1159,  # Hero's Cape
    ],
    # stadiums inspected
    "rejected_stadiums": [1245, 1246, 1264, 1267],
    # cut from the live list
    "cut_from_live": [
        554,   # Audino — draw-to-6 body replaced by unconditional supporters
        1081,  # Enhanced Hammer — dead vs. basic-energy decks
        1197,  # Xerosic's Machinations — conditional hand size
        1198,  # Crispin — capped at one card by a mono-energy line
    ],
}

CARD_TYPE_ENERGY = 5
CARD_TYPE_SPECIAL_ENERGY = 6


def credentials_key() -> str:
    data = json.loads(CREDS_PATH.read_text(encoding="utf-8"))
    key = data.get("apiKey")
    if not key:
        raise SystemExit(f"{CREDS_PATH} carries no apiKey")
    return str(key)


def fetch(path: str, params: dict) -> Any:
    url = f"{arena_config.BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "x-arena-api-key": credentials_key(),
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def candidate_ids() -> list[int]:
    payload = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
    return sorted({int(card["id"]) for card in payload["cards"]})


def keep_ids(cards: list[dict]) -> tuple[list[int], dict[str, list[int]]]:
    """The snapshot bound: deck + live deck + every id the plan argues about."""
    groups: dict[str, list[int]] = {
        "candidate": candidate_ids(),
        "live_s7_deck": sorted(set(arena_config.DECK)),
        "all_basic_energy": sorted(
            card["cardId"]
            for card in cards
            if card["cardType"] == CARD_TYPE_ENERGY
        ),
        "all_special_energy": sorted(
            card["cardId"]
            for card in cards
            if card["cardType"] == CARD_TYPE_SPECIAL_ENERGY
        ),
    }
    groups.update(CONSIDERED)
    keep: set[int] = set()
    for ids in groups.values():
        keep.update(ids)
    return sorted(keep), groups


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--raw",
        type=Path,
        help="reuse a previous {cards_raw, attacks_raw} fetch instead of calling the API",
    )
    args = parser.parse_args()

    compp = arena_config.COMPETITION_ID
    if args.raw:
        raw = json.loads(args.raw.read_text(encoding="utf-8"))
        cards = raw["cards_raw"]
        attacks = raw["attacks_raw"]
    else:
        cards = fetch("/tcg/cards", {"competitionId": compp})
        attacks = fetch("/tcg/attacks", {"competitionId": compp})

    keep, groups = keep_ids(cards)
    cards_by_id = {card["cardId"]: card for card in cards}
    attacks_by_id = {attack["attackId"]: attack for attack in attacks}

    missing = [card_id for card_id in keep if card_id not in cards_by_id]
    if missing:
        raise SystemExit(f"pool has no card ids {missing}")

    kept_cards = []
    attack_ids: set[int] = set()
    for card_id in keep:
        record = cards_by_id[card_id]
        attack_ids.update(int(a) for a in record.get("attacks") or ())
        kept_cards.append(record)

    missing_attacks = sorted(a for a in attack_ids if a not in attacks_by_id)
    if missing_attacks:
        raise SystemExit(f"pool has no attack ids {missing_attacks}")

    snapshot = {
        "meta": {
            "competitionId": compp,
            "season": arena_config.SEASON_NUMBER,
            "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "endpoints": [
                f"{arena_config.BASE_URL}/tcg/cards?competitionId={compp}",
                f"{arena_config.BASE_URL}/tcg/attacks?competitionId={compp}",
            ],
            "pool_size": {"cards": len(cards), "attacks": len(attacks)},
            "kept": {"cards": len(kept_cards), "attacks": len(attack_ids)},
            "bound": {
                "description": (
                    "candidate deck + live S7 deck + every card the M3 plan "
                    "argues about (rejected draw, rejected acceleration, "
                    "rejected ACE SPEC, rejected stadiums, cards cut from the "
                    "live list) + all basic and special energy"
                ),
                "groups": {name: sorted(ids) for name, ids in groups.items()},
            },
        },
        "cards": kept_cards,
        "attacks": [attacks_by_id[attack_id] for attack_id in sorted(attack_ids)],
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {OUT_PATH.relative_to(REPO)}: "
        f"{len(kept_cards)} cards / {len(attack_ids)} attacks "
        f"(pool {len(cards)} / {len(attacks)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
