import bot


def test_choose_action_updates_belief_once():
    class FakeHeuristic:
        def __init__(self):
            self.search = self
            self.updates = 0

        def update_belief_from_obs(self, obs):
            self.updates += 1

        def choose(self, obs, legal):
            return legal[-1]

    heuristic = FakeHeuristic()
    entry = {"obs": {}, "legalActions": ["[0]", "[1]"]}

    assert bot.choose_action(entry, heuristic) == "[1]"
    assert heuristic.updates == 1


def test_choose_action_fallback_is_card_aware():
    obs = {
        "current": {
            "yourIndex": 0,
            "players": [
                {"active": [{"id": 625, "hp": 120, "maxHp": 120}]},
                {"active": [{"id": 96, "hp": 210, "maxHp": 210}]},
            ],
            "select": {"option": [{"type": 13, "attackId": 901}, {"type": 14}]},
        }
    }
    entry = {"obs": obs, "legalActions": ["[0]", "[1]"]}

    assert bot.choose_action(entry, None) == "[0]"


def test_error_code_handles_string_error():
    assert bot.error_code({"error": "action_conflict"}) is None
    assert bot.error_code({"error": {"code": "action_conflict"}}) == "action_conflict"
    assert bot.error_code({"error": {"code": "arena_transaction_busy"}}) == "arena_transaction_busy"
    assert bot.error_code(None) is None


def test_match_result_maps_timeout_and_opponent():
    match = {
        "matchId": "m1",
        "status": "Settled",
        "players": [
            {"agentId": "me", "handle": "me"},
            {"agentId": "opp", "handle": "rival"},
        ],
        "playedActionCount": 42,
        "result": {"reason": "timeout", "winnerAgentId": "opp"},
        "agentResult": {"outcome": "loss"},
    }

    result = bot.match_result_from_api(match, "me")

    assert result is not None
    assert result.result == "timeout"
    assert result.opponent == "rival"
    assert result.actions == 42


def test_feed_ruflo_records_new_settled_matches(monkeypatch):
    settled = {
        "matchId": "m1",
        "status": "Settled",
        "players": [{"agentId": "me"}, {"agentId": "opp"}],
        "playedActionCount": 12,
        "result": {"reason": "all_prizes_taken", "winnerAgentId": "me"},
        "agentResult": {"outcome": "win"},
    }
    monkeypatch.setattr(
        bot, "api", lambda *args, **kwargs: (200, {"matches": [settled]})
    )
    monkeypatch.setattr(bot, "save_reported_matches", lambda ids: None)

    recorded = []

    class FakeRuflo:
        def observe_match(self, result):
            recorded.append(result)

    reported = set()
    count = bot.feed_ruflo_results("key", "me", FakeRuflo(), reported)

    assert count == 1
    assert reported == {"m1"}
    assert recorded[0].result == "win"

    # A second poll of the same settled match is a no-op.
    assert bot.feed_ruflo_results("key", "me", FakeRuflo(), reported) == 0
