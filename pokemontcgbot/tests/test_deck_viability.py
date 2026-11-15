"""Deterministic deck viability checks — Lauren Tan principle.

Every correction becomes a test, not a memory note.
These tests enforce deck quality constraints that were previously
only documented in prose (SKILL.md, Obsidian notes).
"""
import json
from pathlib import Path

# Card data from arena catalog (subset for testing)
BASIC_POKEMON = {
    625: {"name": "Druddigon", "hp": 120, "max_damage": 40},
    328: {"name": "Pikachu ex", "hp": 190, "max_damage": 30},
    299: {"name": "Hop's Zacian ex", "hp": 230, "max_damage": 30},
    39: {"name": "Enamorus", "hp": 120, "max_damage": 30},
    390: {"name": "Tauros", "hp": 130, "max_damage": 30},
    235: {"name": "Budew", "hp": 30, "max_damage": 10},
}

MIN_HP = 80
MIN_DAMAGE = 30
MIN_DISTINCT_BASICS = 4
MIN_TOTAL_HP = 600


def _load_deck():
    """Load deck from bot.py DECK constant."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import bot
    return bot.DECK


def test_deck_size():
    deck = _load_deck()
    assert len(deck) == 60, f"Deck has {len(deck)} cards, need 60"


def test_basic_pokemon_hp():
    deck = _load_deck()
    basics = [c for c in deck if c in BASIC_POKEMON]
    for card_id in set(basics):
        hp = BASIC_POKEMON[card_id]["hp"]
        assert hp >= MIN_HP, (
            f"{BASIC_POKEMON[card_id]['name']} (card {card_id}) has {hp} HP < {MIN_HP}"
        )


def test_basic_pokemon_damage():
    deck = _load_deck()
    basics = [c for c in deck if c in BASIC_POKEMON]
    for card_id in set(basics):
        dmg = BASIC_POKEMON[card_id]["max_damage"]
        assert dmg >= MIN_DAMAGE, (
            f"{BASIC_POKEMON[card_id]['name']} (card {card_id}) max damage {dmg} < {MIN_DAMAGE}"
        )


def test_bench_depth():
    deck = _load_deck()
    basics = [c for c in deck if c in BASIC_POKEMON]
    distinct = len(set(basics))
    assert distinct >= MIN_DISTINCT_BASICS, (
        f"Only {distinct} distinct Basic Pokemon, need >= {MIN_DISTINCT_BASICS}"
    )


def test_total_basic_hp():
    deck = _load_deck()
    basics = [c for c in deck if c in BASIC_POKEMON]
    total_hp = sum(BASIC_POKEMON[c]["hp"] for c in set(basics))
    assert total_hp >= MIN_TOTAL_HP, (
        f"Total Basic HP {total_hp} < {MIN_TOTAL_HP}"
    )


def test_no_budew_in_competitive_deck():
    """Budew (30 HP) deck is for validation only, not competition."""
    deck = _load_deck()
    budew_count = deck.count(235)
    # Allow Budew in validation decks but warn
    if budew_count > 0:
        basics = [c for c in deck if c in BASIC_POKEMON and c != 235]
        assert len(basics) >= 16, (
            "Budew-only deck detected — too weak for competition"
        )
