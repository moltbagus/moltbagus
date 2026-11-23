"""Deterministic deck viability checks — Lauren Tan principle.

Every correction becomes a test, not a memory note.

Card facts used to live in a hand-typed ``BASIC_POKEMON`` table here, with HP and
a printed ``max_damage`` per id. That table was wrong in both directions: it
recorded 100 damage for Mega Audino ex, whose attack prints 20 and adds 80 per
Energy on the opponent's Active, and 100 for Fezandipiti ex, whose attack prints
0 and deals a flat 100 to a chosen Pokemon. It also silently ignored every deck
card it did not list.

So the facts now come from ``catalog.CATALOG`` and every damage judgement goes
through ``effects.Effect.damage`` with a ``DamageContext``. The thresholds
(``MIN_HP`` / ``MIN_DAMAGE`` / ...) are unchanged; they are applied to
effect-aware damage instead of printed damage. The AST guard at the bottom fails
if an id table comes back.
"""
import ast
from pathlib import Path

from catalog import CATALOG
from effects import DamageContext

MIN_HP = 80
MIN_DAMAGE = 30
MIN_DISTINCT_BASICS = 4
MIN_TOTAL_HP = 600
MIN_SUPPORT_POKEMON = 16

# Board assumptions behind "max damage" — not card facts. Three Energy on the
# opponent's Active (a normal mid-game total) and two opponent Pokemon ex in
# play is the board the arena's damage-scaling attacks are read on.
REFERENCE_BOARD = DamageContext(opponent_active_energy=3, opponent_ex_in_play=2)


def _load_deck():
    """Load deck from bot.py DECK constant."""
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent))
    import bot

    return bot.DECK


def _card(card_id):
    """The catalog's card record; the snapshot must know every id we judge."""
    card = CATALOG.card(card_id)
    assert card is not None, (
        f"card {card_id} missing from catalog_data.json — refresh the snapshot"
    )
    return card


def _card_named(name):
    """Look a card up by its printed name, so no id is typed into this file."""
    for card in CATALOG.cards.values():
        if card.name == name:
            return card
    raise AssertionError(f"catalog_data.json has no card named {name!r}")


def _pokemon_in_deck():
    """Distinct Pokemon card ids in the deck, in deck order."""
    pokemon = []
    for card_id in _load_deck():
        card = _card(card_id)
        if card.is_pokemon and card_id not in pokemon:
            pokemon.append(card_id)
    return pokemon


def _attacks(card_id):
    """Every attack of a card, resolving each attack id in the catalog."""
    attacks = []
    for attack_id in _card(card_id).attack_ids:
        attack = CATALOG.attack(attack_id)
        assert attack is not None, (
            f"attack {attack_id} of card {card_id} missing from catalog_data.json"
        )
        attacks.append(attack)
    return attacks


def printed_damage(card_id):
    """Best printed damage on the card, ignoring every effect clause."""
    return max((attack.damage for attack in _attacks(card_id)), default=0)


def effect_aware_damage(card_id, context=REFERENCE_BOARD):
    """Best damage the card can actually deal on ``context``.

    ``Effect.damage`` adds the parsed scaling to the printed base, so an attack
    that prints 20 and adds 80 per Energy is judged at its real 260 instead of
    at 20 — and an attack that prints 0 but deals a flat 100 to a chosen
    Pokemon is judged at 100 instead of at 0.
    """
    return max(
        (attack.effect.damage(attack.damage, context) for attack in _attacks(card_id)),
        default=0,
    )


def _deck_profiles():
    """Every distinct deck Pokemon with the numbers the thresholds judge."""
    profiles = []
    for card_id in _pokemon_in_deck():
        card = _card(card_id)
        profiles.append(
            {
                "id": card_id,
                "name": card.name,
                "hp": card.hp,
                "printed": printed_damage(card_id),
                "damage": effect_aware_damage(card_id),
            }
        )
    return profiles


def _is_fighter(profile):
    """A card that clears both floors: the deck can attack with it as it is."""
    return profile["hp"] >= MIN_HP and profile["damage"] >= MIN_DAMAGE


def test_deck_size():
    deck = _load_deck()
    assert len(deck) == 60, f"Deck has {len(deck)} cards, need 60"


def test_hp_viable_pokemon_meet_the_damage_floor():
    """Anything that passes the HP floor has to hit hard enough to be worth it.

    The old test judged printed damage, which misreads the deck's real attackers:
    Mega Audino ex prints 20 and Fezandipiti ex prints 0 while both deal 260 and
    100. Effect-aware damage is the number this floor belongs on.
    """
    profiles = _deck_profiles()
    width = max(len(profile["name"]) for profile in profiles)
    print(f"{'pokemon':<{width}}  hp  printed  effect-aware  hp floor")
    for profile in sorted(profiles, key=lambda item: -item["damage"]):
        floor = "ok" if profile["hp"] >= MIN_HP else "fodder"
        print(
            f"{profile['name']:<{width}}  {profile['hp']:3d}  "
            f"{profile['printed']:7d}  {profile['damage']:12d}  {floor}"
        )

    for profile in profiles:
        if profile["hp"] < MIN_HP:
            # Below the HP floor this is the small end of an evolution line; its
            # damage belongs to the card it evolves into, checked separately.
            continue
        assert profile["damage"] >= MIN_DAMAGE, (
            f"{profile['name']} (card {profile['id']}) max effect-aware damage "
            f"{profile['damage']} < {MIN_DAMAGE}"
        )


def test_low_hp_pokemon_are_evolution_fodder():
    """A sub-MIN_HP Pokemon is allowed only when the deck evolves past it.

    The snapshot carries no evolution stage, so the deck itself is the evidence:
    something in it must be both bigger and hit harder, which is what the old
    hand-typed ``pre_evolution`` flag asserted about Abra and Dunsparce.
    """
    profiles = _deck_profiles()
    fighters = [profile for profile in profiles if _is_fighter(profile)]
    assert fighters, (
        f"no deck Pokemon clears both {MIN_HP} HP and {MIN_DAMAGE} effect-aware "
        f"damage: {[(p['name'], p['hp'], p['damage']) for p in profiles]}"
    )
    for profile in profiles:
        if profile["hp"] >= MIN_HP:
            continue
        evolves_into = [
            fighter["name"]
            for fighter in fighters
            if fighter["hp"] > profile["hp"] and fighter["damage"] > profile["damage"]
        ]
        assert evolves_into, (
            f"{profile['name']} (card {profile['id']}) has {profile['hp']} HP "
            f"< {MIN_HP} and nothing in the deck is both bigger and hits harder"
        )
        print(
            f"{profile['name']}: {profile['hp']} HP below the {MIN_HP} floor; "
            f"deck holds bigger and harder-hitting {', '.join(evolves_into)}"
        )


def test_effect_scaling_is_judged_past_the_printed_number():
    """The two cards the old table got wrong must be judged on their effects."""
    mega_audino = _card_named("Mega Audino ex")
    printed = printed_damage(mega_audino.card_id)
    aware = effect_aware_damage(mega_audino.card_id)
    assert printed < MIN_DAMAGE, (
        f"Mega Audino ex prints {printed}; the point of the test is that its "
        "Energy-scaling attack is not that small"
    )
    assert aware > 100, (
        f"Mega Audino ex prints {printed} but deals {aware} on the reference board"
    )

    fezandipiti = _card_named("Fezandipiti ex")
    assert printed_damage(fezandipiti.card_id) == 0, (
        "Fezandipiti ex prints 0; its damage lives entirely in the effect"
    )
    assert effect_aware_damage(fezandipiti.card_id) >= MIN_DAMAGE, (
        f"Fezandipiti ex deals {effect_aware_damage(fezandipiti.card_id)} to a "
        f"chosen Pokemon, below {MIN_DAMAGE}"
    )


def test_bench_depth():
    distinct = len(_pokemon_in_deck())
    assert distinct >= MIN_DISTINCT_BASICS, (
        f"Only {distinct} distinct Basic Pokemon, need >= {MIN_DISTINCT_BASICS}"
    )


def test_total_basic_hp():
    total_hp = sum(_card(card_id).hp for card_id in _pokemon_in_deck())
    assert total_hp >= MIN_TOTAL_HP, f"Total Basic HP {total_hp} < {MIN_TOTAL_HP}"


def test_no_budew_in_competitive_deck():
    """Budew (30 HP) is for validation only, not competition."""
    budew = _card_named("Budew")
    deck = _load_deck()
    budew_count = deck.count(budew.card_id)
    if budew_count > 0:
        support = sum(
            1
            for card_id in deck
            if _card(card_id).is_pokemon and card_id != budew.card_id
        )
        assert support >= MIN_SUPPORT_POKEMON, (
            f"Budew deck carries only {support} other Pokemon "
            f"(need >= {MIN_SUPPORT_POKEMON}) — too weak for competition"
        )


# --- drift guard: this module must not grow a card table back -----------------

MIN_TABLE_ENTRIES = 3


def _is_int_constant(node):
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
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
            if all(key is not None and _is_int_constant(key) for key in value.keys):
                found.append((node.lineno, names))
        elif (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in {"set", "frozenset"}
        ):
            found.append((node.lineno, names))
    return found


def _int_id_literals(source):
    """Any id-shaped literal in ``source``, including inside a function body.

    Catches the two shapes a card table takes: a set of integer ids, and a dict
    keyed by integer ids whose values are themselves record dicts.
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Set) and len(node.elts) >= MIN_TABLE_ENTRIES:
            if all(_is_int_constant(item) for item in node.elts):
                found.append(("id set", node.lineno))
        elif isinstance(node, ast.Dict) and len(node.keys) >= MIN_TABLE_ENTRIES:
            if all(key is not None and _is_int_constant(key) for key in node.keys):
                if all(isinstance(value, ast.Dict) for value in node.values):
                    found.append(("card table", node.lineno))
    return found


def test_module_keeps_no_hand_typed_card_table():
    source = Path(__file__).read_text(encoding="utf-8")
    tables = _hand_typed_id_tables(source)
    assert not tables, (
        f"test_deck_viability.py assigns a hand-typed id table at {tables}; "
        "every card fact must come from catalog.CATALOG"
    )
    literals = _int_id_literals(source)
    assert not literals, (
        f"test_deck_viability.py carries an id literal at {literals}; "
        "look the card up in catalog.CATALOG instead"
    )

    # The guard must catch the shapes this file used to carry.
    assert _hand_typed_id_tables(
        "BASIC_POKEMON = {625: {'hp': 120}, 328: {'hp': 190}, 140: {'hp': 210}}\n"
    )
    assert _hand_typed_id_tables("BASIC_IDS = {625, 328, 140}\n")
    assert _hand_typed_id_tables("BASIC_IDS = frozenset(range(1, 9))\n")
    assert _int_id_literals(
        "def f():\n    return {625: {'hp': 120}, 328: {'hp': 190}, 140: {}}\n"
    )
    assert _int_id_literals("def f():\n    return {625, 328, 140}\n")
    # Reading the catalog is not a table, and neither is a threshold.
    assert not _hand_typed_id_tables(
        "from catalog import CATALOG\nPOKEMON = _pokemon_in_deck()\nMIN_HP = 80\n"
    )
    assert not _int_id_literals(
        "def f():\n    return [CATALOG.card(cid) for cid in _pokemon_in_deck()]\n"
    )
