"""One catalog of card and attack facts, loaded from a checked-in snapshot.

``catalog_data.json`` is an offline copy of the arena catalog for every card the
S7 deck can use (plus the ids the previous deck's tables referenced, so nothing
that used to resolve silently starts scoring as unknown) and for every id the
ex / basic-energy classification names. Nothing here touches the network: the
file is read once at import, so tests and the bot see the same facts with no API
key, no request, and no drift between runs.

The classification sets scoring needs are derived here from the snapshot's own
``ex`` / ``megaEx`` / ``cardType`` fields (:data:`EX_IDS`,
:data:`BASIC_ENERGY_IDS`), so no module keeps a hand-typed id list.

Behaviour for an id the snapshot does not carry is the same as the hand tables
it replaces: unknown attack -> 0 damage, unknown card -> no HP. That keeps the
failure mode neutral instead of crashing mid-turn, and
``tests/test_catalog.py`` fails loudly when the deck grows a card the snapshot
lacks.

Refresh recipe (only when the deck changes, never at import time):

1. ``GET https://arena.dev.fun/api/arena/tcg/cards?competitionId=<id>``
2. ``GET https://arena.dev.fun/api/arena/tcg/attacks?competitionId=<id>``
3. keep the deck's card ids, every id in :data:`EX_IDS` / :data:`BASIC_ENERGY_IDS`,
   each card's ``attacks``, and every referenced attack record, then re-run the
   suite -- the tests name any id that did not make it into the snapshot.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from effects import Effect, UNPARSED, parse_effect

SNAPSHOT_PATH = Path(__file__).resolve().with_name("catalog_data.json")

# ``cardType`` values used by the arena catalog.
CARD_TYPE_POKEMON = 0
CARD_TYPE_ENERGY = 5


@dataclass(frozen=True)
class Attack:
    """One attack, with its printed damage and parsed effect descriptor."""

    attack_id: int
    name: str
    damage: int
    text: str
    effect: Effect

    @property
    def parsed(self) -> bool:
        return self.effect.kind != UNPARSED


@dataclass(frozen=True)
class Card:
    """One card. ``attack_ids`` points into the catalog's attack table."""

    card_id: int
    name: str
    card_type: int
    hp: int
    ex: bool
    mega_ex: bool
    attack_ids: Tuple[int, ...]

    @property
    def is_pokemon(self) -> bool:
        return self.card_type == CARD_TYPE_POKEMON

    @property
    def is_basic_energy(self) -> bool:
        """A Basic Energy card (the snapshot holds no Special Energy)."""
        return self.card_type == CARD_TYPE_ENERGY and self.name.startswith("Basic")


@dataclass(frozen=True)
class Coverage:
    """How much of a requested card set the catalog can answer for."""

    requested: int = 0
    covered: int = 0
    attacks: int = 0
    attacks_parsed: int = 0
    missing_card_ids: Tuple[int, ...] = ()
    missing_attack_ids: Tuple[int, ...] = ()
    unparsed_attack_ids: Tuple[int, ...] = ()

    @property
    def ratio(self) -> float:
        return self.covered / self.requested if self.requested else 0.0

    @property
    def attack_ratio(self) -> float:
        return self.attacks_parsed / self.attacks if self.attacks else 1.0

    def report(self) -> str:
        return (
            f"catalog coverage {self.covered}/{self.requested} cards "
            f"({self.ratio:.1%}), {self.attacks_parsed}/{self.attacks} attacks parsed"
            + (f"; missing cards {list(self.missing_card_ids)}" if self.missing_card_ids else "")
            + (f"; missing attacks {list(self.missing_attack_ids)}" if self.missing_attack_ids else "")
            + (f"; unparsed attacks {list(self.unparsed_attack_ids)}" if self.unparsed_attack_ids else "")
        )


def _require(record: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in record:
        raise KeyError(f"{where}: missing {key!r}")
    return record[key]


def _build_card(record: Mapping[str, Any]) -> Card:
    where = "catalog card"
    return Card(
        card_id=int(_require(record, "cardId", where)),
        name=str(_require(record, "name", where)),
        card_type=int(_require(record, "cardType", where)),
        hp=int(_require(record, "hp", where)),
        ex=bool(record.get("ex", False)),
        mega_ex=bool(record.get("megaEx", False)),
        attack_ids=tuple(int(a) for a in record.get("attacks", ()) or ()),
    )


def _build_attack(record: Mapping[str, Any]) -> Attack:
    where = "catalog attack"
    text = str(record.get("text", "") or "")
    return Attack(
        attack_id=int(_require(record, "attackId", where)),
        name=str(_require(record, "name", where)),
        damage=int(_require(record, "damage", where)),
        text=text,
        effect=parse_effect(text),
    )


@dataclass(frozen=True)
class Catalog:
    """Card and attack facts with the lookups scoring needs."""

    cards: Mapping[int, Card]
    attacks: Mapping[int, Attack]
    source: str = ""
    competition_id: str = ""

    def card(self, card_id: Any) -> Optional[Card]:
        try:
            return self.cards.get(int(card_id))
        except (TypeError, ValueError):
            return None

    def attack(self, attack_id: Any) -> Optional[Attack]:
        try:
            return self.attacks.get(int(attack_id))
        except (TypeError, ValueError):
            return None

    def card_hp(self, card_id: Any) -> Optional[int]:
        """Printed HP, or ``None`` when the card is unknown or has no HP."""
        card = self.card(card_id)
        if card is None or card.hp <= 0:
            return None
        return card.hp

    def attack_damage(self, attack_id: Any) -> int:
        """Printed damage before effect scaling; 0 for an unknown attack."""
        attack = self.attack(attack_id)
        return attack.damage if attack is not None else 0

    def coverage(self, card_ids: Iterable[Any]) -> Coverage:
        """Report how much of ``card_ids`` the catalog resolves and parses."""
        requested_ids = []
        for card_id in card_ids:
            try:
                value = int(card_id)
            except (TypeError, ValueError):
                continue
            if value not in requested_ids:
                requested_ids.append(value)

        covered = 0
        attacks = parsed = 0
        missing_cards: list[int] = []
        missing_attacks: list[int] = []
        unparsed: list[int] = []

        for card_id in requested_ids:
            card = self.cards.get(card_id)
            if card is None:
                missing_cards.append(card_id)
                continue
            whole_card = True
            for attack_id in card.attack_ids:
                attacks += 1
                attack = self.attacks.get(attack_id)
                if attack is None:
                    missing_attacks.append(attack_id)
                    whole_card = False
                    continue
                if attack.parsed:
                    parsed += 1
                else:
                    unparsed.append(attack_id)
                    whole_card = False
            covered += 1 if whole_card else 0

        return Coverage(
            requested=len(requested_ids),
            covered=covered,
            attacks=attacks,
            attacks_parsed=parsed,
            missing_card_ids=tuple(missing_cards),
            missing_attack_ids=tuple(sorted(set(missing_attacks))),
            unparsed_attack_ids=tuple(sorted(set(unparsed))),
        )


def load_catalog(path: Optional[Path] = None) -> Catalog:
    """Read the snapshot from disk. Pure file IO -- never the network."""
    target = Path(path) if path is not None else SNAPSHOT_PATH
    with target.open(encoding="utf-8") as handle:
        payload: Dict[str, Any] = json.load(handle)

    cards = {}
    for record in payload.get("cards", ()):
        card = _build_card(record)
        cards[card.card_id] = card
    attacks = {}
    for record in payload.get("attacks", ()):
        attack = _build_attack(record)
        attacks[attack.attack_id] = attack

    meta = payload.get("snapshot") or {}
    return Catalog(
        cards=cards,
        attacks=attacks,
        source=str(meta.get("source", "")),
        competition_id=str(meta.get("competitionId", "")),
    )


CATALOG = load_catalog()

# Card classifications scoring asks about. They are derived from the snapshot's
# own card facts, not typed by hand: a card counts as ex when the arena catalog
# flags ``ex`` or ``megaEx`` (Mega ex counts as ex for effect damage), and the
# basic-energy set is the snapshot's Basic Energy cards.
EX_IDS = frozenset(
    card.card_id for card in CATALOG.cards.values() if card.ex or card.mega_ex
)
BASIC_ENERGY_IDS = frozenset(
    card.card_id for card in CATALOG.cards.values() if card.is_basic_energy
)
