"""Convert the live bot's arena deck into ptcg-engine deck-list format.

The bot expresses its deck as arena.dev.fun integer card ids. ptcg-engine's
``load_deck`` understands ``<count> <card name> <set> <number>`` lines resolved
through its card registry, so every arena id needs an explicit engine card
reference (set code + collector number).

At the pinned engine commit (see ``ENGINE.lock``) the engine implements none of
the five Pokemon in this deck. This module therefore refuses to invent set
numbers: ``to_engine_lines`` raises ``UnresolvedEngineCardError`` naming the
missing cards. P2 can pass verified ``EngineCard`` references through
``card_map`` once the cards exist (or a proxy deck is deliberately chosen)
without changing the validation rules here.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DECK_SIZE = 60
MAX_COPIES = 4


class DeckError(ValueError):
    """Base class for deck conversion errors."""


class DeckValidationError(DeckError):
    """The deck violates standard construction rules."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("Invalid deck: " + "; ".join(self.errors))


class UnresolvedEngineCardError(DeckError):
    """One or more cards have no verified ptcg-engine set/number reference."""

    def __init__(self, unresolved: Mapping[int, str]) -> None:
        self.unresolved = dict(unresolved)
        details = ", ".join(f"{name} ({card_id})" for card_id, name in self.unresolved.items())
        super().__init__(
            "Cannot express cards in ptcg-engine deck format: "
            f"{details}. Provide verified EngineCard(set_code, number) mappings via card_map."
        )


@dataclass(frozen=True)
class EngineCard:
    """A card as ptcg-engine knows it: display name plus set code and number."""

    name: str
    set_code: str
    number: str

    def __post_init__(self) -> None:
        if not self.set_code or not self.number:
            raise ValueError("EngineCard requires both a set code and a collector number")
        if self.number != self.number.zfill(len(self.number)):
            raise ValueError(f"Collector number must be digits only; got {self.number!r}")


@dataclass(frozen=True)
class CardSpec:
    """Arena card id plus the facts deck validation needs."""

    arena_id: int
    name: str
    is_basic_pokemon: bool = False
    is_basic_energy: bool = False
    engine: EngineCard | None = None


# The live deck from bot.py: 20 Pokemon + 40 Basic {G} Energy.
# Basic {G} Energy is SVE 001 under the SVE numbering the engine already uses
# (Fire 002, Lightning 004, Psychic 005, Darkness 007, Metal 008); the engine at
# the pinned commit does not implement it yet.
_CARDS: dict[int, CardSpec] = {
    625: CardSpec(625, "Druddigon", is_basic_pokemon=True),
    328: CardSpec(328, "Pikachu ex", is_basic_pokemon=True),
    299: CardSpec(299, "Hop's Zacian ex", is_basic_pokemon=True),
    39: CardSpec(39, "Enamorus", is_basic_pokemon=True),
    390: CardSpec(390, "Tauros", is_basic_pokemon=True),
    1: CardSpec(1, "Basic {G} Energy", is_basic_energy=True, engine=EngineCard("Grass Energy", "SVE", "001")),
}

ARENA_DECK: dict[int, int] = {
    625: 4,
    328: 4,
    299: 4,
    39: 4,
    390: 4,
    1: 40,
}

assert sum(ARENA_DECK.values()) == DECK_SIZE


def arena_deck() -> dict[int, int]:
    """Return a copy of the live 60-card arena deck (card id -> count)."""
    return dict(ARENA_DECK)


def deck_size(counts: Mapping[int, int] | None = None) -> int:
    return sum((counts if counts is not None else ARENA_DECK).values())


def card_spec(card_id: int) -> CardSpec | None:
    return _CARDS.get(card_id)


def validation_errors(counts: Mapping[int, int] | None = None) -> list[str]:
    """Return every standard-construction violation in ``counts``.

    Rules (Pokemon TCG rulebook): exactly 60 cards, at most 4 cards with the
    same name except basic Energy, and at least one Basic Pokemon.
    """
    deck = ARENA_DECK if counts is None else counts
    errors: list[str] = []

    total = 0
    named = Counter()
    has_basic = False

    for card_id, count in deck.items():
        if not isinstance(card_id, int) or isinstance(card_id, bool):
            errors.append(f"Card id must be an int; got {card_id!r}")
            continue
        if not isinstance(count, int) or isinstance(count, bool):
            errors.append(f"Count for card {card_id} must be an int; got {count!r}")
            continue

        spec = _CARDS.get(card_id)
        if spec is None:
            errors.append(f"Unknown card id {card_id} is not part of the arena card table")
            continue
        if count <= 0:
            errors.append(f"{spec.name} ({card_id}) has non-positive count {count}")
            continue

        total += count
        if spec.is_basic_pokemon:
            has_basic = True
        if not spec.is_basic_energy:
            named[spec.name] += count

    if total != DECK_SIZE:
        errors.append(f"A standard deck must contain exactly {DECK_SIZE} cards; found {total}")

    for name, count in sorted(named.items()):
        if count > MAX_COPIES:
            errors.append(f"{name} has {count} copies; at most {MAX_COPIES} cards with one name are allowed")

    if not has_basic:
        errors.append("A standard deck must contain at least one Basic Pokemon")

    return errors


def validate(counts: Mapping[int, int] | None = None) -> None:
    """Raise ``DeckValidationError`` when the deck is not legal."""
    errors = validation_errors(counts)
    if errors:
        raise DeckValidationError(errors)


def to_engine_lines(
    counts: Mapping[int, int] | None = None,
    card_map: Mapping[int, EngineCard] | None = None,
) -> list[str]:
    """Return ``<count> <name> <set> <number>`` lines for ptcg-engine.

    ``card_map`` supplies verified engine references, overriding the built-in
    table. Unmapped cards raise instead of being dropped, so a partial deck can
    never reach the engine.
    """
    deck = ARENA_DECK if counts is None else counts
    overrides = card_map or {}
    validate(deck)

    unresolved: dict[int, str] = {}
    lines: list[str] = []

    for card_id, count in deck.items():
        if count <= 0:
            continue
        spec = _CARDS[card_id]
        engine = overrides.get(card_id) or spec.engine
        if engine is None:
            unresolved[card_id] = spec.name
            continue
        lines.append(f"{count} {engine.name} {engine.set_code} {engine.number}")

    if unresolved:
        raise UnresolvedEngineCardError(unresolved)

    return lines


def write_engine_lines(
    path: str | Path,
    counts: Mapping[int, int] | None = None,
    card_map: Mapping[int, EngineCard] | None = None,
) -> Path:
    """Write a ptcg-engine deck file and return its path."""
    target = Path(path)
    target.write_text("\n".join(to_engine_lines(counts, card_map)) + "\n", encoding="utf-8")
    return target


def missing_in_engine(
    counts: Mapping[int, int] | None = None,
    card_map: Mapping[int, EngineCard] | None = None,
) -> dict[int, str]:
    """Return card id -> reason for every deck card the engine cannot resolve.

    Requires the ptcg-engine venv; callers should treat ImportError as an
    environment gap, not a deck problem.
    """
    from ptcg.core.card_registry import registry

    deck = ARENA_DECK if counts is None else counts
    overrides = card_map or {}
    missing: dict[int, str] = {}

    for card_id, count in deck.items():
        if count <= 0:
            continue
        spec = _CARDS[card_id]
        engine = overrides.get(card_id) or spec.engine
        if engine is None:
            missing[card_id] = f"{spec.name}: no verified ptcg-engine card reference"
        elif registry.get_by_set_and_number(engine.set_code, engine.number) is None:
            missing[card_id] = (
                f"{spec.name}: {engine.set_code}-{engine.number} is absent from the ptcg-engine registry"
            )

    return missing


def available_engine_decks() -> list[str]:
    """List deck fixtures bundled with the installed ptcg-engine."""
    from ptcg.utils.deck_validation import get_available_decks

    return get_available_decks()
