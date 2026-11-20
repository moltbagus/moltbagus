"""Regression tests: develop the board before an attack ends the turn."""

from scoring import best_action


def _obs(options, energy_attached=True):
    return {
        "current": {
            "yourIndex": 0,
            "energyAttached": energy_attached,
            "players": [
                {
                    "active": [{"id": 305, "hp": 70, "maxHp": 70, "energies": [1]}],
                    "bench": [],
                },
                {"active": [], "bench": []},
            ],
            "select": {"type": 0, "option": options},
        }
    }


def test_evolve_outranks_damaging_attack():
    obs = _obs([{"type": 9}, {"type": 13, "attackId": 901}])
    assert best_action(obs, ["[0]", "[1]"]) == "[0]"


def test_play_outranks_zero_damage_attack():
    obs = _obs([{"type": 7}, {"type": 13, "attackId": 423}])
    assert best_action(obs, ["[0]", "[1]"]) == "[0]"


def test_ability_outranks_damaging_attack():
    obs = _obs([{"type": 10}, {"type": 13, "attackId": 901}])
    assert best_action(obs, ["[0]", "[1]"]) == "[0]"


def test_damaging_attack_is_still_chosen_without_development():
    obs = _obs([{"type": 13, "attackId": 901}, {"type": 14}])
    assert best_action(obs, ["[0]", "[1]"]) == "[0]"


def test_zero_damage_attack_is_still_chosen_without_development():
    obs = _obs([{"type": 13, "attackId": 423}, {"type": 14}])
    assert best_action(obs, ["[0]", "[1]"]) == "[0]"
