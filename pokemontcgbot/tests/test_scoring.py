from belief import BeliefTracker
from ismcts import BeliefWeightedHeuristic
from scoring import best_action, option_score, real_damage


def make_obs(options, our_hp=120, our_max_hp=120, opp_hp=210, yi=0):
    you = {
        "active": [{"id": 625, "hp": our_hp, "maxHp": our_max_hp}],
        "bench": [],
        "handCount": 5,
        "deckCount": 45,
        "prize": [None] * 6,
        "discard": [],
    }
    opponent = {
        "active": [{"id": 96, "hp": opp_hp, "maxHp": 210}],
        "bench": [],
        "handCount": 6,
        "deckCount": 45,
        "prize": [None] * 6,
        "discard": [],
    }
    players = [you, opponent] if yi == 0 else [opponent, you]
    return {
        "current": {
            "yourIndex": yi,
            "players": players,
            "select": {"option": options},
        }
    }


def test_attack_option_uses_attack_id_not_damage_field():
    # Real options have no "damage" key; attackId 901 is Druddigon's 40-damage Shred.
    obs = make_obs([{"type": 13, "attackId": 901}, {"type": 14}])
    assert best_action(obs, ["[0]", "[1]"]) == "[0]"


def test_attack_beats_end_turn_even_without_damage_field():
    obs = make_obs([{"type": 14}, {"type": 13, "attackId": 456}])
    assert best_action(obs, ["[0]", "[1]"]) == "[1]"


def test_multi_card_selection_prefers_completing_selection():
    obs = make_obs([{"type": 3, "area": 1, "index": 0}, {"type": 3, "area": 1, "index": 1}])
    assert best_action(obs, ["[]", "[0]", "[1]", "[0,1]"]) == "[0,1]"


def test_low_hp_active_retreats_with_charged_bench():
    obs = make_obs(
        [{"type": 12}, {"type": 14}],
        our_hp=20,
        our_max_hp=120,
    )
    obs["current"]["players"][0]["bench"] = [
        {"id": 328, "hp": 190, "maxHp": 190, "energies": [1]}
    ]
    assert best_action(obs, ["[0]", "[1]"]) == "[0]"


def test_low_hp_active_passes_without_charged_bench():
    obs = make_obs(
        [{"type": 12}, {"type": 14}],
        our_hp=20,
        our_max_hp=120,
    )
    assert best_action(obs, ["[0]", "[1]"]) == "[1]"


def test_heuristic_choose_does_not_update_belief_twice():
    class CountingBelief(BeliefTracker):
        def __init__(self):
            super().__init__({328: 4})
            self.sync_calls = 0

        def sync_from_obs(self, obs):
            self.sync_calls += 1
            return super().sync_from_obs(obs)

    belief = CountingBelief()
    heuristic = BeliefWeightedHeuristic(belief)
    obs = make_obs([{"type": 13, "attackId": 901}, {"type": 14}])

    assert heuristic.choose(obs, ["[0]", "[1]"]) == "[0]"
    assert belief.sync_calls == 0  # bot.choose_action owns the single update


# --- catalog-backed facts -------------------------------------------------


def test_unknown_attack_id_scores_as_neutral_damage():
    assert real_damage(999999, make_obs([])) == 0


def test_cruel_arrow_uses_the_parsed_effect_not_the_printed_zero():
    # Printed damage for attack 183 is 0; the text says 100 to a chosen Pokemon.
    assert real_damage(183, make_obs([])) == 100


def test_choose_card_hp_bonus_comes_from_the_catalog():
    # Option carries the card id but the zone is not visible, so scoring falls
    # back to the catalog HP: 10 + 270/10 for Mega Audino ex.
    assert option_score({"type": 3, "id": 1006}, make_obs([])) == 37.0
