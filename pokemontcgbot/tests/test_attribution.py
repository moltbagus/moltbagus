"""Match labels must describe the deck and the policy that actually played.

Every settled S7 match used to be recorded as `deck_version="druddigon-v2"`,
`heuristic="belief-ismcts"` — a deck from a previous season and a search that is
a flat argmax. That is false evidence feeding the promotion gate (spec §7).
"""

import inspect

import arena_config
import bot


def _match(outcome="win"):
    return {
        "status": "Settled",
        "result": {"reason": ""},
        "agentResult": {"outcome": outcome},
        "players": [
            {"agentId": "us", "handle": "SirshibaninjaBot"},
            {"agentId": "them", "handle": "opponent"},
        ],
        "playedActionCount": 12,
    }


def test_match_labels_come_from_config(monkeypatch):
    monkeypatch.setattr(bot, "HAS_RUFLO", True)
    result = bot.match_result_from_api(_match(), "us")
    assert result is not None
    assert result.deck_version == arena_config.DECK_VERSION
    assert result.heuristic == arena_config.POLICY_VERSION


def test_deck_version_is_declared_once_like_the_other_identities():
    assert arena_config.DECK_VERSION
    assert bot.DECK_VERSION == arena_config.DECK_VERSION


def test_no_stale_labels_remain_in_the_module_source():
    """Guard the assignments, not the words: the comment explains the history."""
    source = inspect.getsource(bot)
    assert 'deck_version="druddigon' not in source
    assert 'heuristic="belief-ismcts"' not in source
