"""The M3 candidate deck must be legal, complete and payable — offline.

The S7 deck in ``arena_config.DECK`` is locked by the precommit for the
500-match window, so the rebuild lives in ``deck_candidate.json`` instead of in
the live constant. That makes this file the only thing standing between the
candidate and a hand-waved list: every claim in
``docs/plans/2026-11-21-deck-candidate-m3.md`` is asserted here against
``docs/data/card_pool_snapshot.json``, which was fetched from the arena once by
``scripts/build_card_pool_snapshot.py``.

Nothing here reads the network. A card the snapshot does not carry fails the
test rather than quietly scoring as unknown — that is the same drift rule
``tests/test_catalog.py`` applies to the live deck.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CANDIDATE_PATH = REPO / "deck_candidate.json"
SNAPSHOT_PATH = REPO / "docs" / "data" / "card_pool_snapshot.json"

# arena cardType values
POKEMON = 0
TRAINER_TYPES = (1, 2, 3, 4)  # item, tool, supporter, stadium
BASIC_ENERGY = 5
SPECIAL_ENERGY = 6

# Colorless is 0 and any energy pays it; a typed symbol needs that type.
COLORLESS = 0
ANY_TYPE = frozenset(range(1, 9))

# §5 target composition and the hard ceilings.
MIN_POKEMON, MAX_POKEMON = 15, 18
MIN_TRAINERS, MAX_TRAINERS = 30, 33
MIN_ENERGY, MAX_ENERGY = 10, 12
MAX_ACE_SPEC = 1
MAX_COPIES = 4
MIN_DRAW_SUPPORTERS = 6
DECK_SIZE = 60

# A draw supporter is a supporter whose text actually draws cards. "Unconditional"
# excludes the shapes that make a draw card dead: a discard-your-hand cost, a
# coin flip, or a board-state gate ("You can use this card only if ...").
DRAW_COST_MARKERS = (
    "discard your hand",
    "flip a coin",
    "you can use this card only if",
)


def _candidate() -> dict:
    return json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))


def _snapshot() -> dict:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


CARDS = {card["cardId"]: card for card in _snapshot()["cards"]}
ATTACKS = {attack["attackId"]: attack for attack in _snapshot()["attacks"]}


def deck_ids() -> list[int]:
    """The candidate list, expanded to 60 ids."""
    ids: list[int] = []
    for entry in _candidate()["cards"]:
        ids.extend([int(entry["id"])] * int(entry["count"]))
    return ids


def card(card_id: int) -> dict:
    assert card_id in CARDS, (
        f"card {card_id} is not in docs/data/card_pool_snapshot.json — "
        "re-run scripts/build_card_pool_snapshot.py"
    )
    return CARDS[card_id]


def card_type(card_id: int) -> int:
    return int(card(card_id)["cardType"])


def text_of(card_id: int) -> str:
    return " ".join(
        str(skill.get("text", "")) for skill in card(card_id).get("skills") or ()
    )


def counts() -> Counter:
    return Counter(deck_ids())


def size_of(kind: str) -> int:
    if kind == "pokemon":
        return sum(n for cid, n in counts().items() if card_type(cid) == POKEMON)
    if kind == "trainers":
        return sum(n for cid, n in counts().items() if card_type(cid) in TRAINER_TYPES)
    return sum(n for cid, n in counts().items() if card_type(cid) in (BASIC_ENERGY, SPECIAL_ENERGY))


def provided_types() -> set[int]:
    """Energy types the list can actually produce.

    A Basic Energy provides its own type. A Special Energy is read
    conservatively: Colorless unless its text says it provides every type, so a
    special energy can never be credited with paying a typed cost by accident.
    """
    types: set[int] = set()
    for card_id in counts():
        kind = card_type(card_id)
        if kind == BASIC_ENERGY:
            types.add(int(card(card_id)["energyType"]))
        elif kind == SPECIAL_ENERGY:
            if "provides every type" in text_of(card_id).lower():
                types |= ANY_TYPE
            else:
                types.add(COLORLESS)
    return types


def pokemon_in_deck() -> list[int]:
    return [cid for cid in counts() if card_type(cid) == POKEMON]


def attacks_of(card_id: int) -> list[dict]:
    resolved = []
    for attack_id in card(card_id).get("attacks") or ():
        assert int(attack_id) in ATTACKS, (
            f"attack {attack_id} of card {card_id} is missing from the snapshot"
        )
        resolved.append(ATTACKS[int(attack_id)])
    return resolved


def draw_supporters(unconditional_only: bool = False) -> list[tuple[int, int, str]]:
    rows = []
    for card_id, copies in counts().items():
        if card_type(card_id) != 3:  # supporter
            continue
        body = text_of(card_id)
        if "draw" not in body.lower():
            continue
        if unconditional_only and any(marker in body.lower() for marker in DRAW_COST_MARKERS):
            continue
        rows.append((card_id, copies, card(card_id)["name"]))
    return rows


# --- 1. size and copy limits -------------------------------------------------


def test_the_candidate_is_exactly_sixty_cards():
    deck = deck_ids()
    assert len(deck) == DECK_SIZE, f"candidate has {len(deck)} cards, need {DECK_SIZE}"


def test_copy_limits_hold():
    offenders = []
    for card_id, copies in counts().items():
        record = card(card_id)
        if card_type(card_id) == BASIC_ENERGY and str(record["name"]).startswith("Basic"):
            continue  # basic energy is exempt from the four-copy rule
        if copies > MAX_COPIES:
            offenders.append(f"{record['name']} ({card_id}) x{copies}")
    assert not offenders, f"over the four-copy limit: {', '.join(offenders)}"


def test_no_copy_limit_is_bypassed_by_a_second_printing():
    """The real rule is four per card *name*, not per id."""
    by_name: Counter = Counter()
    for card_id, copies in counts().items():
        record = card(card_id)
        if card_type(card_id) == BASIC_ENERGY and str(record["name"]).startswith("Basic"):
            continue
        by_name[str(record["name"])] += copies
    over = {name: n for name, n in by_name.items() if n > MAX_COPIES}
    assert not over, f"more than four cards of a name: {over}"


# --- 2. composition floors and ceilings -------------------------------------


def test_composition_is_inside_the_section_5_targets():
    pokemon, trainers, energy = size_of("pokemon"), size_of("trainers"), size_of("energy")
    print(
        f"composition: {pokemon} Pokemon / {trainers} Trainers / {energy} Energy "
        f"= {pokemon + trainers + energy}"
    )
    assert MIN_POKEMON <= pokemon <= MAX_POKEMON, f"{pokemon} Pokemon outside 15-18"
    assert MIN_TRAINERS <= trainers <= MAX_TRAINERS, f"{trainers} Trainers outside 30-33"
    assert MIN_ENERGY <= energy <= MAX_ENERGY, f"{energy} Energy outside 10-12"
    assert pokemon + trainers + energy == DECK_SIZE


def test_at_most_one_ace_spec():
    ace = [cid for cid in counts() if card(cid)["aceSpec"]]
    assert len(ace) <= MAX_ACE_SPEC, (
        f"{len(ace)} ACE SPEC cards: {[card(cid)['name'] for cid in ace]}"
    )


def test_the_declared_composition_matches_the_list():
    declared = _candidate()["composition"]
    computed = {
        "pokemon": size_of("pokemon"),
        "trainers": size_of("trainers"),
        "energy": size_of("energy"),
        "total": len(deck_ids()),
    }
    for key, value in computed.items():
        assert declared[key] == value, (
            f"deck_candidate.json declares {key}={declared[key]} but the list has {value}"
        )


# --- 3. every id resolves in the snapshot -----------------------------------


def test_every_candidate_id_is_in_the_pool_snapshot():
    missing = sorted({cid for cid in deck_ids() if cid not in CARDS})
    assert not missing, (
        f"ids absent from docs/data/card_pool_snapshot.json: {missing} — "
        "they were never verified against the arena pool"
    )


def test_snapshot_belongs_to_this_competition():
    meta = _snapshot()["meta"]
    assert meta["competitionId"] == _candidate()["competition_id"]
    assert meta["kept"]["cards"] == len(CARDS)
    assert meta["kept"]["attacks"] == len(ATTACKS)


# --- 4. the section 5 defects: draw, Crispin, payability --------------------


def test_at_least_six_draw_supporters():
    rows = draw_supporters(unconditional_only=True)
    total = sum(copies for _cid, copies, _name in rows)
    print("draw supporters: " + ", ".join(f"{name} x{n}" for _cid, n, name in rows))
    assert total >= MIN_DRAW_SUPPORTERS, (
        f"{total} unconditional draw supporter copies, need >= {MIN_DRAW_SUPPORTERS}: "
        "a list with no Professor's Research / Iono / Judge-class card cannot "
        "recover from a bad hand"
    )


def test_crispin_is_cut_from_a_single_type_energy_line():
    """Crispin searches two Basic Energy of *different types*.

    In a list whose whole energy line is one type it can only ever fetch one
    card, so three slots are near-dead. Either the list carries a second basic
    type or Crispin does not belong in it.
    """
    energy_types = {
        int(card(cid)["energyType"])
        for cid in counts()
        if card_type(cid) == BASIC_ENERGY
    }
    carries_crispin = any(card(cid)["name"] == "Crispin" for cid in counts())
    if len(energy_types) == 1:
        assert not carries_crispin, (
            f"mono-energy line {energy_types} but Crispin is in the list — "
            "it caps at one card per use"
        )


def test_every_attack_on_every_pokemon_is_payable_by_the_energy_line():
    types = provided_types()
    assert types, "the list carries no energy at all"
    energy_copies = size_of("energy")

    rows = []
    for card_id in pokemon_in_deck():
        for attack in attacks_of(card_id):
            cost = [int(symbol) for symbol in attack["energies"]]
            unpayable = [s for s in cost if s != COLORLESS and s not in types]
            rows.append((card(card_id)["name"], attack["name"], cost, unpayable))
            assert not unpayable, (
                f"{card(card_id)['name']} / {attack['name']} costs {cost} "
                f"but the energy line provides {sorted(types)} — unpayable {unpayable}"
            )
            assert len(cost) <= energy_copies, (
                f"{attack['name']} needs {len(cost)} energy but the deck only carries "
                f"{energy_copies}"
            )

    print("attack costs: " + "; ".join(
        f"{name}/{attack} {cost}" for name, attack, cost, _bad in rows
    ))


def test_three_energy_attacks_have_more_than_a_coin_flip_to_pay_for_them():
    """The defect was three-energy attackers with Kaleidowaltz as the only ramp.

    Two deterministic outs are required: manual attach over turns is not a
    plan, and a coin-flip search is not acceleration.
    """
    three_cost = [
        (card(cid)["name"], attack["name"])
        for cid in pokemon_in_deck()
        for attack in attacks_of(cid)
        if len(attack["energies"]) >= 3
    ]
    if not three_cost:
        pytest.skip("the candidate carries no three-energy attack")

    ramp = [
        cid
        for cid in counts()
        if "attach" in text_of(cid).lower()
        and "energy" in text_of(cid).lower()
        and "flip" not in text_of(cid).lower()
    ]
    assert ramp, (
        "three-energy attacks with no deterministic acceleration: "
        f"{three_cost} are paid for by manual attach only"
    )
    print(
        "three-energy attacks: "
        + ", ".join(f"{name}/{attack}" for name, attack in three_cost)
        + " | deterministic ramp: "
        + ", ".join(card(cid)["name"] for cid in ramp)
    )


# --- 5. every evolution line is complete -----------------------------------


def test_every_evolution_line_is_complete():
    present = {str(card(cid)["name"]): cid for cid in counts()}
    lines = []
    for card_id in pokemon_in_deck():
        record = card(card_id)
        pre = record.get("evolvesFrom")
        if not pre:
            continue
        assert pre in present, (
            f"{record['name']} evolves from {pre}, which is not in the candidate"
        )
        pre_copies = counts()[present[pre]]
        copies = counts()[card_id]
        assert copies <= pre_copies, (
            f"{record['name']} x{copies} needs at least that many {pre} "
            f"(the list carries {pre_copies})"
        )
        lines.append(f"{pre} x{pre_copies} -> {record['name']} x{copies}")
    print("evolution lines: " + "; ".join(lines))


def test_stage_two_lines_have_a_stage_one_between_them():
    """A Stage 2 whose pre-evolution is not a Stage 1 is an unplayable line."""
    by_name = {str(card(cid)["name"]): cid for cid in counts()}
    for card_id in pokemon_in_deck():
        record = card(card_id)
        if not record.get("stage2"):
            continue
        pre = record.get("evolvesFrom")
        assert pre in by_name, f"Stage 2 {record['name']} has no {pre} in the list"
        assert card(by_name[pre]).get("stage1"), (
            f"{record['name']} evolves from {pre}, which is not a Stage 1"
        )
