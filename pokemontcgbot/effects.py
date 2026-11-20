"""Attack-effect descriptors parsed from card text.

The arena observation never carries a damage number for an attack, so scoring has
to know how an attack's printed ``damage`` scales with the board. Rather than
hard-code "attack 1454 is 20 + 80 per opponent energy" in the scoring module,
this module parses the printed text once into a descriptor that scoring can
evaluate against a board context.

Coverage is deliberate and conservative: a text is only described when the
damage formula is fully understood. Anything that mentions a damage change this
module does not model is reported as :data:`UNPARSED` and keeps its printed
``damage`` (never silently zero), so the gap is visible as a coverage number
instead of hiding inside a decision.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Effect kinds. ``UNPARSED`` is the only one that asserts nothing about scaling.
FLAT = "flat"
OPPONENT_ACTIVE_ENERGY = "opponent_active_energy"
OPPONENT_EX_IN_PLAY = "opponent_ex_in_play"
CHOSEN_POKEMON = "chosen_pokemon"
UNPARSED = "UNPARSED"

MODELED_KINDS = frozenset({FLAT, OPPONENT_ACTIVE_ENERGY, OPPONENT_EX_IN_PLAY, CHOSEN_POKEMON})


@dataclass(frozen=True)
class DamageContext:
    """Board facts an effect needs; supplied by the caller, never guessed."""

    opponent_active_energy: int = 0
    opponent_ex_in_play: int = 0


@dataclass(frozen=True)
class Effect:
    """A described attack effect.

    ``base`` is the printed damage on the attack record; the descriptor only
    carries the *modification* so the two never disagree.
    """

    kind: str
    per: Optional[int] = None
    amount: Optional[int] = None
    detail: str = ""

    @property
    def parsed(self) -> bool:
        return self.kind in MODELED_KINDS

    def damage(self, base: int, context: Optional[DamageContext] = None) -> int:
        """Expected damage for ``base`` printed damage against ``context``."""
        ctx = context or DamageContext()
        if self.kind == OPPONENT_ACTIVE_ENERGY:
            return base + (self.per or 0) * max(0, ctx.opponent_active_energy)
        if self.kind == OPPONENT_EX_IN_PLAY:
            return base + (self.per or 0) * max(0, ctx.opponent_ex_in_play)
        if self.kind == CHOSEN_POKEMON:
            return self.amount if self.amount is not None else base
        return base


def _normalise(text: str) -> str:
    """Fold the punctuation and accents the catalog uses into ASCII."""
    folded = (
        text.lower()
        .replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u00e9", "e")
        .replace("\u2014", " ")
        .replace("\u2013", " ")
    )
    return re.sub(r"\s+", " ", folded).strip()


# A modelled scaling clause, most specific first.
_OPPONENT_ACTIVE_ENERGY_RE = re.compile(
    r"this attack does (\d+) more damage for each energy attached to "
    r"your opponent's active"
)
_OPPONENT_EX_IN_PLAY_RE = re.compile(
    r"this attack does (\d+) damage for each of your opponent's pokemon \{ex\} in play"
)
_CHOSEN_POKEMON_RE = re.compile(
    r"this attack does (\d+) damage to 1 of your opponent's pokemon"
)

# A damage change we know we do not model. Matching any of these means the
# printed damage understates the real one, so the attack is reported UNPARSED.
_UNMODELED_RE = re.compile(
    r"more damage"
    r"|damage for each"
    r"|damage is doubled"
    r"|doubled"
    r"|damage is increased"
    r"|damage for each of your"
)


def parse_effect(text: Optional[str]) -> Effect:
    """Describe one attack's printed text.

    Empty text is a flat attack. Text with a damage clause this module models
    becomes that descriptor; text with any other damage clause is ``UNPARSED``.
    """
    raw = text or ""
    speaking = _normalise(raw)
    if not speaking:
        return Effect(FLAT, detail="no text")

    match = _OPPONENT_ACTIVE_ENERGY_RE.search(speaking)
    if match:
        per = int(match.group(1))
        return Effect(
            OPPONENT_ACTIVE_ENERGY,
            per=per,
            detail=f"base + {per} per energy on the opponent's Active",
        )
    match = _OPPONENT_EX_IN_PLAY_RE.search(speaking)
    if match:
        per = int(match.group(1))
        return Effect(
            OPPONENT_EX_IN_PLAY,
            per=per,
            detail=f"base + {per} per opponent Pokemon ex in play",
        )
    match = _CHOSEN_POKEMON_RE.search(speaking)
    if match:
        amount = int(match.group(1))
        return Effect(
            CHOSEN_POKEMON,
            amount=amount,
            detail=f"{amount} to one chosen opponent Pokemon",
        )

    if _UNMODELED_RE.search(speaking):
        return Effect(UNPARSED, detail="damage clause not modelled")

    return Effect(FLAT, detail="no damage clause")
