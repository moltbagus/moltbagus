"""The catalog is the single source of card and attack facts.

These tests are the drift guard that the deleted ``ATTACK_DAMAGE`` and
``CARD_HP`` tables used to lack: the deck, the snapshot and the effect parser
must agree, and scoring must not grow a hand-written fact table back.
"""
import ast
import socket
from pathlib import Path

import arena_config
import catalog
import effects
import scoring

REPO = Path(__file__).resolve().parent.parent
DECK_CARD_IDS = sorted(set(arena_config.DECK))
# Names that used to be hand-typed fact tables in scoring.py. None may come back.
FACT_TABLES = ("ATTACK_DAMAGE", "CARD_HP", "EX_CARD_IDS")
# A module-level set/dict literal holding >= 3 plain integers is an id table.
MIN_TABLE_ENTRIES = 3

# The exact ids the hand-typed EX_CARD_IDS literal carried before the catalog
# owned the fact. Kept as the expectation: the derived set must equal it, so the
# move cannot silently change what scoring counts as a Pokemon ex.
PREVIOUS_EX_IDS = frozenset({
    24, 29, 30, 37, 40, 44, 46, 52, 63, 75, 79, 80,
    83, 84, 96, 99, 107, 108, 117, 121, 125, 130, 138, 139,
    140, 141, 150, 153, 154, 161, 176, 179, 184, 189, 190, 193,
    198, 205, 207, 210, 223, 229, 231, 232, 236, 239, 241, 243,
    244, 246, 248, 249, 259, 269, 272, 283, 293, 299, 302, 306,
    313, 316, 320, 326, 328, 329, 331, 336, 337, 340, 357, 369,
    372, 381, 389, 404, 407, 424, 431, 447, 455, 458, 471, 481,
    509, 515, 525, 527, 547, 561, 573, 583, 598, 618, 631, 641,
    648, 652, 662, 678, 687, 695, 723, 737, 747, 754, 756, 766,
    772, 781, 790, 795, 806, 813, 828, 835, 849, 861, 868, 886,
    896, 904, 911, 919, 928, 932, 939, 944, 951, 954, 957, 962,
    968, 969, 975, 979, 984, 988, 990, 993, 997, 1002, 1006, 1022,
    1026, 1031, 1040, 1056, 1062, 1064, 1071,
})
PREVIOUS_BASIC_ENERGY_IDS = frozenset(range(1, 9))


def _is_int_constant(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(
        node.value, bool
    )


def _hand_typed_id_tables(source):
    """Module-level id sets/dicts built from integer literals in ``source``."""
    found = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        value = node.value
        if isinstance(value, ast.Set) and len(value.elts) >= MIN_TABLE_ENTRIES:
            if all(_is_int_constant(item) for item in value.elts):
                found.append((node.lineno, names))
        elif isinstance(value, ast.Dict) and len(value.keys) >= MIN_TABLE_ENTRIES:
            if all(_is_int_constant(key) for key in value.keys):
                found.append((node.lineno, names))
        elif (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in {"set", "frozenset"}
        ):
            found.append((node.lineno, names))
    return found



def _read(name):
    return (REPO / name).read_text(encoding="utf-8")


def _card(card_id):
    card = catalog.CATALOG.card(card_id)
    assert card is not None, f"card {card_id} missing from catalog_data.json"
    return card


def _attack(attack_id):
    attack = catalog.CATALOG.attack(attack_id)
    assert attack is not None, f"attack {attack_id} missing from catalog_data.json"
    return attack


def test_catalog_is_typed_records():
    card = catalog.CATALOG.card(1006)
    assert isinstance(card, catalog.Card)
    assert card.name == "Mega Audino ex"
    attack = catalog.CATALOG.attack(1454)
    assert isinstance(attack, catalog.Attack)
    assert isinstance(attack.effect, effects.Effect)


def test_every_deck_card_resolves():
    missing = [card_id for card_id in DECK_CARD_IDS if catalog.CATALOG.card(card_id) is None]
    assert not missing, (
        f"deck card ids missing from catalog_data.json: {missing} — refresh the snapshot"
    )


def test_every_deck_attack_resolves():
    missing = []
    for card_id in DECK_CARD_IDS:
        card = catalog.CATALOG.card(card_id)
        assert card is not None, f"card {card_id} missing from the snapshot"
        for attack_id in card.attack_ids:
            if catalog.CATALOG.attack(attack_id) is None:
                missing.append((card_id, attack_id))
    assert not missing, f"attacks missing from catalog_data.json: {missing}"


def test_snapshot_has_no_dangling_attack_ids():
    dangling = sorted(
        {
            attack_id
            for card in catalog.CATALOG.cards.values()
            for attack_id in card.attack_ids
            if catalog.CATALOG.attack(attack_id) is None
        }
    )
    assert not dangling, f"attack ids referenced but not defined: {dangling}"


def test_deck_effect_coverage_is_at_least_95_percent():
    coverage = catalog.CATALOG.coverage(DECK_CARD_IDS)
    print(coverage.report())
    assert coverage.missing_card_ids == (), coverage.report()
    assert coverage.missing_attack_ids == (), coverage.report()
    assert coverage.ratio >= 0.95, coverage.report()
    assert coverage.attack_ratio >= 0.95, coverage.report()


def test_scoring_has_no_hand_written_fact_tables():
    source = _read("scoring.py")
    for name in FACT_TABLES:
        assert name not in source, f"scoring.py still carries the {name} table literal"
        assert not hasattr(scoring, name), f"scoring still exposes {name}"
    tables = _hand_typed_id_tables(source)
    assert not tables, f"scoring.py assigns a hand-typed id table at {tables}; derive it in catalog.py"
    # The guard itself must catch the shapes the old literals had.
    assert _hand_typed_id_tables("LEGACY_IDS = {1, 2, 3}\n")
    assert _hand_typed_id_tables("LEGACY_IDS = frozenset(range(1, 9))\n")
    assert _hand_typed_id_tables("ATTACK_DAMAGE = {901: 40, 902: 60, 903: 80}\n")
    assert not _hand_typed_id_tables("from catalog import EX_IDS\nids = EX_IDS\n")


def test_derived_id_sets_match_the_previous_hand_tables():
    print(
        f"derived EX_IDS={len(catalog.EX_IDS)} "
        f"BASIC_ENERGY_IDS={len(catalog.BASIC_ENERGY_IDS)}"
    )
    assert catalog.EX_IDS == PREVIOUS_EX_IDS, (
        f"catalog adds {sorted(catalog.EX_IDS - PREVIOUS_EX_IDS)}, "
        f"drops {sorted(PREVIOUS_EX_IDS - catalog.EX_IDS)}"
    )
    assert PREVIOUS_EX_IDS == catalog.EX_IDS
    assert not (catalog.EX_IDS ^ PREVIOUS_EX_IDS), sorted(
        catalog.EX_IDS ^ PREVIOUS_EX_IDS
    )
    assert catalog.BASIC_ENERGY_IDS == PREVIOUS_BASIC_ENERGY_IDS, sorted(
        catalog.BASIC_ENERGY_IDS ^ PREVIOUS_BASIC_ENERGY_IDS
    )
    assert PREVIOUS_BASIC_ENERGY_IDS == catalog.BASIC_ENERGY_IDS
    # scoring reads the catalog's sets; it must not keep copies of its own.
    assert scoring.EX_IDS is catalog.EX_IDS
    assert scoring.BASIC_ENERGY_IDS is catalog.BASIC_ENERGY_IDS


def test_catalog_and_effects_do_not_reach_the_network():
    for name in ("catalog.py", "effects.py"):
        source = _read(name)
        for token in ("urllib", "requests", "socket", "http.client"):
            assert token not in source, f"{name} imports {token}; the snapshot must be offline"


def test_snapshot_loads_without_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("catalog load must not open a socket")

    monkeypatch.setattr(socket, "socket", _blocked)
    fresh = catalog.load_catalog()
    assert fresh.card_hp(1006) == 270
    assert fresh.attack_damage(1454) == 20


def test_effect_parser_models_scaling_attacks():
    assert _attack(1454).effect.kind == effects.OPPONENT_ACTIVE_ENERGY
    assert _attack(339).effect.kind == effects.OPPONENT_ACTIVE_ENERGY
    assert _attack(425).effect.kind == effects.OPPONENT_EX_IN_PLAY
    assert _attack(183).effect.kind == effects.CHOSEN_POKEMON


def test_effect_parser_marks_unknown_damage_clauses_unparsed():
    unparsed = effects.parse_effect("Flip a coin. If heads, this attack does 60 more damage.")
    assert unparsed.kind == effects.UNPARSED
    assert not unparsed.parsed
    assert unparsed.damage(90) == 90  # printed damage is kept, never zeroed


def test_effect_parser_treats_plain_attacks_as_flat():
    assert effects.parse_effect("").kind == effects.FLAT
    assert effects.parse_effect(
        "This attack's damage isn't affected by any effects on your opponent's Active Pokemon."
    ).kind == effects.FLAT
    assert effects.parse_effect(
        "Your opponent's Active Pokemon is now Confused. You may move any number of "
        "damage counters on your opponent's Pokemon to their other Pokemon."
    ).kind == effects.FLAT


def test_effect_damage_matches_the_published_values():
    ctx = effects.DamageContext(opponent_active_energy=3, opponent_ex_in_play=1)
    for attack_id, expected in ((1454, 260), (339, 160), (425, 60), (183, 100), (426, 150)):
        attack = _attack(attack_id)
        assert attack.effect.damage(attack.damage, ctx) == expected, attack.name


def test_card_hp_matches_the_printed_catalog():
    assert catalog.CATALOG.card_hp(1006) == 270
    assert catalog.CATALOG.card_hp(741) == 50
    assert catalog.CATALOG.card_hp(1086) is None  # Trainer: no HP to score


def test_unknown_ids_keep_the_neutral_fallback():
    assert catalog.CATALOG.attack_damage(999999) == 0
    assert catalog.CATALOG.attack(999999) is None
    assert catalog.CATALOG.card_hp(999999) is None
    assert catalog.CATALOG.card("not-a-card") is None
