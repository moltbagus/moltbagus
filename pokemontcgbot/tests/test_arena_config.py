"""The season identity is defined once and imported everywhere."""

import inspect
import re

import arena_config
import bot
import bot_async
import telemetry
import wr_report


def test_all_entrypoints_share_competition_id():
    assert bot.COMPETITION_ID == arena_config.COMPETITION_ID
    assert bot_async.COMPETITION_ID == arena_config.COMPETITION_ID
    assert wr_report.DEFAULT_COMPETITION_ID == arena_config.COMPETITION_ID


def test_all_entrypoints_share_season_number():
    assert bot.SEASON_NUMBER == arena_config.SEASON_NUMBER == 7
    assert bot_async.SEASON_NUMBER == arena_config.SEASON_NUMBER


def test_deck_thesis_matches_config():
    assert bot.DECK_THESIS == arena_config.DECK_THESIS


def test_deck_is_one_object_across_entrypoints():
    assert bot.DECK is arena_config.DECK
    assert bot_async.DECK is arena_config.DECK
    assert bot.BASIC_POKEMON_IDS is arena_config.BASIC_POKEMON_IDS
    assert bot_async.BASIC_POKEMON_IDS is arena_config.BASIC_POKEMON_IDS


def test_deck_shape_and_copy_limits():
    deck = arena_config.DECK
    assert len(deck) == 60
    energy = {cid for cid in deck if cid in set(range(1, 9))}
    assert energy == {5}  # mono Psychic, as the thesis says
    assert any(cid in arena_config.BASIC_POKEMON_IDS for cid in deck)


def test_policy_version_is_declared_once():
    assert arena_config.POLICY_VERSION
    assert telemetry.POLICY_VERSION == arena_config.POLICY_VERSION


def test_no_module_redeclares_the_deck():
    """A second DECK literal is how the two entrypoints drift apart."""
    for module in (bot, bot_async):
        source = inspect.getsource(module)
        assert not re.search(r"^DECK\s*=", source, re.M), f"{module.__name__} redeclares DECK"
        assert not re.search(
            r"^BASIC_POKEMON_IDS\s*=", source, re.M
        ), f"{module.__name__} redeclares BASIC_POKEMON_IDS"
