"""P1 tests: arena deck -> ptcg-engine deck format conversion and validation."""

from __future__ import annotations

import pytest

from ab_harness import deck as deck_mod
from ab_harness.deck import (
    ARENA_DECK,
    DECK_SIZE,
    DeckValidationError,
    EngineCard,
    UnresolvedEngineCardError,
    to_engine_lines,
    validate,
    validation_errors,
    write_engine_lines,
)

# Verified references to cards the pinned engine actually implements, used to
# exercise the writer without inventing set numbers for the arena Pokemon.
FIXTURE_MAP = {
    625: EngineCard("Charmander", "PAF", "007"),
    328: EngineCard("Charmeleon", "PAF", "008"),
    299: EngineCard("Charizard ex", "PAF", "054"),
    39: EngineCard("Pidgey", "MEW", "016"),
    390: EngineCard("Pidgeot ex", "OBF", "164"),
    1: EngineCard("Fire Energy", "SVE", "002"),
}


def test_arena_deck_matches_live_bot_list():
    assert ARENA_DECK == {625: 4, 328: 4, 299: 4, 39: 4, 390: 4, 1: 40}
    assert sum(ARENA_DECK.values()) == DECK_SIZE


def test_default_deck_is_legal():
    validate()
    assert validation_errors() == []


def test_basic_energy_is_exempt_from_copy_limit():
    counts = {625: 4, 1: 56}
    assert validation_errors(counts) == []
    validate(counts)


def test_fifth_copy_of_a_pokemon_is_rejected():
    counts = {**ARENA_DECK, 625: 5, 1: 39}
    with pytest.raises(DeckValidationError) as excinfo:
        validate(counts)
    assert "Druddigon has 5 copies" in str(excinfo.value)


def test_deck_without_a_basic_pokemon_is_rejected():
    errors = validation_errors({1: 60})
    assert "at least one Basic Pokemon" in " ".join(errors)


def test_wrong_deck_size_is_rejected():
    errors = validation_errors({625: 4, 1: 39})
    assert "exactly 60 cards; found 43" in " ".join(errors)


def test_unknown_card_id_is_rejected():
    errors = validation_errors({625: 4, 999: 56})
    assert "Unknown card id 999" in " ".join(errors)


def test_nonpositive_count_is_rejected():
    counts = {625: 4, 328: 0, 1: 56}
    errors = validation_errors(counts)
    assert "Pikachu ex (328) has non-positive count 0" in " ".join(errors)


def test_conversion_refuses_to_invent_unimplemented_engine_cards():
    with pytest.raises(UnresolvedEngineCardError) as excinfo:
        to_engine_lines()
    err = excinfo.value
    assert set(err.unresolved) == {625, 328, 299, 39, 390}
    assert "Druddigon (625)" in str(err)
    assert "Hop's Zacian ex (299)" in str(err)


def test_conversion_with_verified_map_writes_a_loadable_engine_deck(tmp_path):
    pytest.importorskip("ptcg", reason="requires the pinned ptcg-engine venv")
    path = write_engine_lines(tmp_path / "fixture.deck", card_map=FIXTURE_MAP)
    text = path.read_text(encoding="utf-8")

    assert text.splitlines() == [
        "4 Charmander PAF 007",
        "4 Charmeleon PAF 008",
        "4 Charizard ex PAF 054",
        "4 Pidgey MEW 016",
        "4 Pidgeot ex OBF 164",
        "40 Fire Energy SVE 002",
    ]

    from ptcg.utils.load_deck import load_deck

    engine_deck = load_deck(str(path))
    assert len(engine_deck.cards) == 60
    assert engine_deck.validation_errors() == []


def test_missing_in_engine_names_every_unimplemented_card():
    pytest.importorskip("ptcg", reason="requires the pinned ptcg-engine venv")
    missing = deck_mod.missing_in_engine()
    assert set(missing) == {625, 328, 299, 39, 390, 1}
    assert "absent from the ptcg-engine registry" in missing[1]


def test_engine_bundles_expected_fixture_decks():
    pytest.importorskip("ptcg", reason="requires the pinned ptcg-engine venv")
    decks = deck_mod.available_engine_decks()
    assert "charizard_ex" in decks
    assert "miraidon_ex" in decks
