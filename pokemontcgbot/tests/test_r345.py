"""R3 tie-break, R4 effect damage, R5 binding fields."""

from scoring import best_action, real_damage
import wr_report


def _obs(options, bench=None):
    return {
        "current": {
            "yourIndex": 0,
            "energyAttached": True,
            "players": [
                {
                    "active": [{"id": 305, "hp": 70, "maxHp": 70, "energies": [1]}],
                    "bench": bench or [],
                },
                {
                    "active": [{"id": 245, "hp": 140, "maxHp": 140, "energies": [5, 5, 5]}],
                    "bench": [{"id": 1006, "hp": 270, "maxHp": 270, "energies": []}],
                },
            ],
            "select": {"type": 0, "option": options},
        }
    }


def test_evolution_tie_break_prefers_higher_value_target():
    bench = [
        {"id": 741, "hp": 50, "maxHp": 50, "energies": []},
        {"id": 305, "hp": 70, "maxHp": 100, "energies": [5, 5]},
    ]
    a = {"type": 9, "area": 2, "index": 1, "inPlayArea": 5, "inPlayIndex": 0}
    b = {"type": 9, "area": 2, "index": 1, "inPlayArea": 5, "inPlayIndex": 1}
    assert best_action(_obs([a, b], bench), ["[0]", "[1]"]) == "[1]"
    assert best_action(_obs([b, a], bench), ["[0]", "[1]"]) == "[0]"


def test_ear_force_scales_with_opponent_energy():
    assert real_damage(1454, _obs([])) == 260


def test_psychic_scales_with_opponent_energy():
    assert real_damage(339, _obs([])) == 160


def test_tenacious_tail_counts_opponent_ex():
    assert real_damage(425, _obs([])) == 60


def test_cruel_arrow_is_100():
    assert real_damage(183, _obs([])) == 100


def test_report_has_binding_fields():
    fields = wr_report.binding_fields()
    assert set(fields) == {"commit", "bot_pid", "bot_start", "competition_id"}
    assert fields["competition_id"] == "cmwm3cekx011nln01c3gqi0tc"
