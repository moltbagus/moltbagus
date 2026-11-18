"""Offline A/B harness scaffolding for the local ptcg-engine (P0-P1)."""

from ab_harness.deck import (
    ARENA_DECK,
    DECK_SIZE,
    MAX_COPIES,
    DeckValidationError,
    EngineCard,
    UnresolvedEngineCardError,
    available_engine_decks,
    deck_size,
    to_engine_lines,
    validate,
    validation_errors,
)

__all__ = [
    "ARENA_DECK",
    "DECK_SIZE",
    "MAX_COPIES",
    "DeckValidationError",
    "EngineCard",
    "UnresolvedEngineCardError",
    "available_engine_decks",
    "deck_size",
    "to_engine_lines",
    "validate",
    "validation_errors",
]
