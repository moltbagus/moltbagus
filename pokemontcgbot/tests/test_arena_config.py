"""The season identity is defined once and imported everywhere."""

import arena_config
import bot
import bot_async
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
