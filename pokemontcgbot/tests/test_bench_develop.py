"""An empty bench must be filled before an attack ends the turn."""

from scoring import best_action


def _obs(options, bench=None, energy_attached=True):
    return {
        "current": {
            "yourIndex": 0,
            "energyAttached": energy_attached,
            "players": [
                {
                    "active": [{"id": 305, "hp": 70, "maxHp": 70, "energies": [1]}],
                    "bench": bench or [],
                },
                {"active": [], "bench": []},
            ],
            "select": {"type": 0, "option": options},
        }
    }


def test_empty_bench_plays_basic_before_attack():
    obs = _obs([{"type": 7}, {"type": 13, "attackId": 1454}])
    assert best_action(obs, ["[0]", "[1]"]) == "[0]"


def test_trainer_play_precedes_attack_with_nonempty_bench():
    obs = _obs(
        [{"type": 7}, {"type": 13, "attackId": 1454}],
        bench=[{"id": 741, "hp": 50, "maxHp": 50}],
    )
    assert best_action(obs, ["[0]", "[1]"]) == "[0]"


def test_attack_still_chosen_without_development():
    obs = _obs([{"type": 13, "attackId": 1454}, {"type": 14}])
    assert best_action(obs, ["[0]", "[1]"]) == "[0]"
