"""Single source of truth for the DevFun Arena TCG season configuration.

Every entrypoint and report imports these constants; do not duplicate them.
`tests/test_arena_config.py` fails if a second copy reappears.
"""

from pathlib import Path

BASE_URL = "https://arena.dev.fun/api/arena"

COMPETITION_ID = "cmwm3cekx011nln01c3gqi0tc"
AGENT_ID = "cmqogaydkdghsnq1ql4t9anjt"
SEASON_NUMBER = 7

DECK_THESIS = (
    "Alakazam / Dudunsparce / Fezandipiti with the Audino package: "
    "18 Pokemon, 30 Trainers, 12 Basic Psychic Energy"
)

# S7 deck: Alakazam / Dudunsparce / Fezandipiti with the Audino package.
# 18 Pokemon + 30 Trainers + 12 Basic Psychic Energy = 60.
DECK = (
    [741] * 3 + [742] * 2 + [245] * 2      # Abra / Kadabra / Alakazam
    + [305] * 3 + [306] * 2                 # Dunsparce / Dudunsparce ex
    + [140] * 2                             # Fezandipiti ex
    + [1006] * 2 + [554] * 2                # Mega Audino ex / Audino
    + [1086] * 4 + [1152] * 4               # Buddy-Buddy Poffin / Poke Pad
    + [1231] * 3 + [1182] * 3               # Dawn / Boss's Orders
    + [1097] * 3 + [1198] * 3               # Night Stretcher / Crispin
    + [1197] * 3 + [1081] * 3               # Xerosic's Machinations / Enhanced Hammer
    + [1129] * 2 + [1266] * 2               # Sacred Ash / Nighttime Mine
    + [5] * 12                              # Basic Psychic Energy
)

BASIC_POKEMON_IDS = frozenset({741, 305, 140, 1006, 554, 625, 328, 299, 39, 390})

# Bumped whenever a decision-affecting policy change ships; every telemetry
# record carries it so an offline replay can attribute a choice to a policy.
POLICY_VERSION = "l1-2026-11-24-guardrail-first"

# Identity of the 60-card list, recorded on every match so Ruflo's history can
# be split by deck. Bump it when the deck changes — never per-decision.
DECK_VERSION = "s7-audino-v1"

# One JSON line per decision point (spec 7).
TELEMETRY_PATH = Path.home() / ".arena-tcg-decisions.jsonl"
