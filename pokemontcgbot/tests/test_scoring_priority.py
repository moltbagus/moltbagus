"""Regression tests for phase-aware scoring priorities."""

from scoring import best_action


def _obs(select, *, energy_attached=False, active=None, bench=None):
    return {
        "current": {
            "yourIndex": 0,
            "energyAttached": energy_attached,
            "players": [
                {
                    "active": active or [],
                    "bench": bench or [],
                },
                {"active": [], "bench": []},
            ],
            "select": select,
        }
    }


def test_attach_prefers_healthy_bench_when_active_fragile():
    obs = _obs(
        {
            "type": 0,
            "option": [
                {"type": 8, "area": 2, "index": 0, "inPlayArea": 4, "inPlayIndex": 0},
                {"type": 8, "area": 2, "index": 0, "inPlayArea": 5, "inPlayIndex": 0},
                {"type": 13, "attackId": 545},
                {"type": 14},
            ],
        },
        active=[{"id": 390, "hp": 130, "maxHp": 130, "energies": []}],
        bench=[{"id": 328, "hp": 190, "maxHp": 190, "energies": []}],
    )
    legal = ["[0]", "[1]", "[2]", "[3]"]
    assert best_action(obs, legal) == "[1]"


def test_attach_stays_active_when_active_is_high_hp():
    obs = _obs(
        {
            "type": 0,
            "option": [
                {"type": 8, "area": 2, "index": 0, "inPlayArea": 4, "inPlayIndex": 0},
                {"type": 8, "area": 2, "index": 0, "inPlayArea": 5, "inPlayIndex": 0},
                {"type": 13, "attackId": 456},
            ],
        },
        active=[{"id": 328, "hp": 190, "maxHp": 190, "energies": []}],
        bench=[{"id": 390, "hp": 120, "maxHp": 130, "energies": []}],
    )
    assert best_action(obs, ["[0]", "[1]", "[2]"]) == "[0]"


def test_attach_priority_disabled_after_attachment():
    obs = _obs(
        {
            "type": 0,
            "option": [
                {"type": 8, "area": 2, "index": 0, "inPlayArea": 4, "inPlayIndex": 0},
                {"type": 13, "attackId": 545},
            ],
        },
        energy_attached=True,
        active=[{"id": 390, "hp": 130, "maxHp": 130, "energies": [1]}],
    )
    assert best_action(obs, ["[0]", "[1]"]) == "[1]"


def test_promotion_prefers_highest_hp_bench():
    obs = _obs(
        {
            "type": 1,
            "context": 4,
            "option": [
                {"type": 3, "area": 5, "index": 0, "playerIndex": 0},
                {"type": 3, "area": 5, "index": 1, "playerIndex": 0},
                {"type": 3, "area": 5, "index": 2, "playerIndex": 0},
            ],
        },
        bench=[
            {"id": 390, "hp": 40, "maxHp": 130, "energies": [1]},
            {"id": 328, "hp": 190, "maxHp": 190, "energies": []},
            {"id": 299, "hp": 230, "maxHp": 230, "energies": []},
        ],
    )
    assert best_action(obs, ["[0]", "[1]", "[2]"]) == "[2]"
