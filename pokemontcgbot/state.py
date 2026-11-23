"""Observation -> ``GameState``: known, inferred and hidden facts (spec 3.3).

One ``GameState`` per ``matchId``. Every observation is folded in with
``sync``; replaying the same observation is a no-op (the property test in
``tests/test_state.py`` compares a stable serialisation). Nothing here decides
an action, touches the network or writes a record: this is the layer that the
policy stack reads, and the only place allowed to say "unknown".

What is modelled, and on what evidence
--------------------------------------

* ``our_hand`` -- slot -> card id. Slots are the hand indices the arena uses in
  ``type: 7`` (play), ``type: 8`` (attach) and ``type: 9`` (evolve) options.
  They are rebuilt exactly whenever the observation exposes our hand (it does
  in current battle payloads), and otherwise maintained incrementally:

  - a slot is removed when its option was chosen, and *resolved* when the
    resulting card is visible: an attach reveals the energy type on the target,
    an evolve reveals the new top card, a play is revealed by
    ``select.effect``/``select.contextCard``, a new body on the board, a new
    stadium, or a single new discard entry;
  - a slot is resolved in place when a search returns the card
    (``select.deck`` plus the chosen deck indices) or when a card is named in a
    log entry;
  - a slot whose card is never revealed stays ``None`` and carries a
    distribution over the unseen pool (``our_hand_distribution``). It is never
    filled with a guess.

* ``our_deck_order_belief`` -- when a search exposes ``select.deck`` the order
  for those positions is known; otherwise every remaining position carries the
  uniform distribution over :meth:`GameState.unseen_pool`. Cards stacked under
  an evolved Pokemon are not visible in the observation, so they stay in the
  pool: the pool is a conservative (upper-bound) view of what is still unseen.

* ``prizes`` -- reveal order then unknown. Arena observations do not expose our
  prize cards (every entry is ``null``), so a prize slot stays ``None`` unless
  an option shows the card.

* ``opponent_public`` -- the opponent's board, discard, prize count and hand
  count. ``opponent_hand_distribution`` is empty unless a deck prior is
  supplied (M6 supplies archetype priors); with a prior it is the
  hypergeometric probability that at least one unseen copy sits in hand. No
  invented archetype is assumed.

* ``energy_in_play`` -- attached energies per side and type.

* ``can_attack_next_turn(card, attack)`` -- compares the attack's energy cost
  (catalog record first, then the checked-in cost table) against the energies
  attached to that card plus the manual attachment still available this turn.
  The old scoring rule used a hard-coded 180 HP threshold for this decision.

Energy cost provenance: the arena ``/tcg/attacks`` endpoint carries
``energies``, but ``catalog_data.json`` does not snapshot that field yet.
``attack_costs.json`` is the checked-in copy of the field for every attack in
the snapshot, and this module prefers ``catalog.Attack.energies`` as soon as
``catalog.py`` grows it -- the field is not re-derived here.
"""

from __future__ import annotations

import argparse
import json
import math
import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import catalog
from arena_config import DECK
from scoring import (
    opponent_index,
    parse_action_indices,
    players_of,
    select_of,
    your_index,
)

# Option and area codes from the verified observation shape (spec section 2).
OPTION_CHOOSE_CARD = 3
OPTION_PLAY = 7
OPTION_ATTACH = 8
OPTION_EVOLVE = 9
OPTION_RETREAT = 12
OPTION_ATTACK = 13
OPTION_END_TURN = 14

AREA_DECK = 1
AREA_HAND = 2
AREA_DISCARD = 3
AREA_ACTIVE = 4
AREA_BENCH = 5
AREA_PRIZE = 6

HAND_ACTION_KINDS = {OPTION_PLAY: "play", OPTION_ATTACH: "attach", OPTION_EVOLVE: "evolve"}
COLORLESS = 0

ENERGY_COST_PATH = Path(__file__).resolve().with_name("attack_costs.json")


def _load_energy_costs(path: Optional[Path] = None) -> Dict[int, Tuple[int, ...]]:
    """Read the checked-in attack energy costs. Missing file means "unknown"."""
    target = Path(path) if path is not None else ENERGY_COST_PATH
    try:
        with target.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    raw = payload.get("costs") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return {}
    costs: Dict[int, Tuple[int, ...]] = {}
    for key, value in raw.items():
        try:
            attack_id = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, list):
            costs[attack_id] = tuple(int(v) for v in value if isinstance(v, int))
    return costs


# The field ``catalog.py`` will own once its snapshot carries it.
ATTACK_ENERGY_COSTS: Dict[int, Tuple[int, ...]] = _load_energy_costs()


def attack_energy_cost(
    attack: Any, costs: Optional[Mapping[int, Tuple[int, ...]]] = None
) -> Optional[Tuple[int, ...]]:
    """Energy cost of an attack, from the catalog record then the cost table.

    ``None`` means the cost is unknown; callers must treat that as "cannot
    certify an attack" rather than assuming it is free.
    """
    attack_id: Optional[int] = None
    record: Optional[catalog.Attack] = None
    if isinstance(attack, catalog.Attack):
        record = attack
    elif isinstance(attack, Mapping):
        raw = attack.get("attackId", attack.get("attack_id"))
        try:
            attack_id = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            attack_id = None
        energies = attack.get("energies")
        if isinstance(energies, list):
            return tuple(int(v) for v in energies if isinstance(v, int))
        if attack_id is not None:
            record = catalog.CATALOG.attack(attack_id)
    else:
        try:
            attack_id = int(attack)
        except (TypeError, ValueError):
            return None
        record = catalog.CATALOG.attack(attack_id)

    if record is not None:
        attack_id = record.attack_id
        field = getattr(record, "energies", None)
        if field is not None:
            return tuple(int(v) for v in field)

    table = costs if costs is not None else ATTACK_ENERGY_COSTS
    return table.get(attack_id) if attack_id is not None else None


def energy_cost_payable(
    cost: Optional[Sequence[int]],
    attached: Iterable[Any],
    pending: int = 0,
) -> bool:
    """Can ``cost`` be paid by ``attached`` types plus ``pending`` wild energy?

    A cost symbol is an energy type code; ``0`` is Colorless and can be paid by
    anything left over. ``pending`` is the manual attachment still available
    this turn, whose type is not known yet, so it is counted as wild.
    """
    if cost is None:
        return False
    pool: Counter = Counter()
    for value in attached:
        try:
            pool[int(value)] += 1
        except (TypeError, ValueError):
            continue
    wild = max(0, int(pending))
    colorless = 0
    for symbol in cost:
        if symbol == COLORLESS:
            colorless += 1
            continue
        try:
            symbol = int(symbol)
        except (TypeError, ValueError):
            return False
        if pool[symbol] <= 0:
            return False
        pool[symbol] -= 1
    return sum(pool.values()) + wild >= colorless


def _as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _card_id(card: Any) -> Optional[int]:
    if isinstance(card, Mapping):
        return _as_int(card.get("id", card.get("cardId")))
    if isinstance(card, int) and not isinstance(card, bool):
        return card
    return None


def _serial(card: Any) -> Optional[int]:
    if isinstance(card, Mapping):
        return _as_int(card.get("serial"))
    return None


def _energy_type(value: Any) -> Optional[int]:
    if isinstance(value, Mapping):
        return _as_int(value.get("id", value.get("type")))
    return _as_int(value)


def _card_energies(card: Any) -> Tuple[int, ...]:
    if not isinstance(card, Mapping):
        return ()
    raw = card.get("energies")
    if not isinstance(raw, list):
        return ()
    out: List[int] = []
    for value in raw:
        energy = _energy_type(value)
        if energy is not None:
            out.append(energy)
    return tuple(out)


def _zone(player: Any, key: str) -> List[Any]:
    if not isinstance(player, Mapping):
        return []
    raw = player.get(key)
    return raw if isinstance(raw, list) else []


def _zone_ids(player: Any, key: str) -> Tuple[int, ...]:
    out: List[int] = []
    for card in _zone(player, key):
        card_id = _card_id(card)
        if card_id is not None:
            out.append(card_id)
    return tuple(out)


def _first_card(cards: Iterable[Any]) -> Any:
    for card in cards:
        if isinstance(card, Mapping):
            return card
    return None


@dataclass(frozen=True)
class PublicCard:
    """A card in play, as far as both players can see it."""

    card_id: int
    hp: int = 0
    max_hp: int = 0
    energies: Tuple[int, ...] = ()


def _public_card(card: Any) -> Optional[PublicCard]:
    card_id = _card_id(card)
    if card_id is None:
        return None
    return PublicCard(
        card_id=card_id,
        hp=_as_int(card.get("hp"), 0) or 0,
        max_hp=_as_int(card.get("maxHp"), 0) or 0,
        energies=_card_energies(card),
    )


def _public_cards(cards: Iterable[Any]) -> Tuple[PublicCard, ...]:
    out: List[PublicCard] = []
    for card in cards:
        snap = _public_card(card)
        if snap is not None:
            out.append(snap)
    return tuple(out)


@dataclass(frozen=True)
class OpponentPublic:
    """Everything the opponent has exposed: board, discard, prizes, counts."""

    active: Optional[PublicCard] = None
    bench: Tuple[PublicCard, ...] = ()
    discard: Tuple[int, ...] = ()
    prizes: Tuple[Optional[int], ...] = ()
    hand_count: int = 0
    deck_count: int = 0

    def ids_in_play(self) -> Tuple[int, ...]:
        ids = [self.active.card_id] if self.active is not None else []
        ids.extend(card.card_id for card in self.bench)
        return tuple(ids)


def _public_dict(card: Optional[PublicCard]) -> Optional[Dict[str, Any]]:
    if card is None:
        return None
    return {
        "id": card.card_id,
        "hp": card.hp,
        "maxHp": card.max_hp,
        "energies": list(card.energies),
    }


def _board_of(player: Any) -> Tuple[Optional[PublicCard], Tuple[PublicCard, ...]]:
    active = _public_card(_first_card(_zone(player, "active")))
    bench = _public_cards(_zone(player, "bench"))
    return active, bench


def _hand_slot(option: Any) -> Optional[int]:
    """Hand index carried by a play/attach/evolve option, if it carries one."""
    if not isinstance(option, Mapping):
        return None
    if option.get("type") not in HAND_ACTION_KINDS:
        return None
    area = option.get("area")
    if area is not None and _as_int(area) != AREA_HAND:
        return None
    return _as_int(option.get("index"))


def _observation_signature(obs: Any) -> Optional[str]:
    """Stable hash of the decision-relevant observation, or None if unusable.

    Duplicate detection uses this, not a sequence number, so a caller can sync
    the same observation twice (with or without the chosen action) and get the
    same state.
    """
    if not isinstance(obs, Mapping):
        return None
    current = obs.get("current")
    if not isinstance(current, Mapping):
        return None
    players = players_of(obs)
    if not players or not any(isinstance(player, Mapping) for player in players):
        return None

    def player_view(player: Any) -> Dict[str, Any]:
        if not isinstance(player, Mapping):
            return {}
        hand = player.get("hand")
        hand_view = None
        if isinstance(hand, list):
            hand_view = [[_card_id(card), _serial(card)] for card in hand]
        return {
            "active": [[_card_id(c), _card_energies(c)] for c in _zone(player, "active") if isinstance(c, Mapping)],
            "bench": [[_card_id(c), _card_energies(c)] for c in _zone(player, "bench") if isinstance(c, Mapping)],
            "discard": list(_zone_ids(player, "discard")),
            "prize": len(_zone(player, "prize")),
            "deckCount": _as_int(player.get("deckCount")),
            "handCount": _as_int(player.get("handCount")),
            "hand": hand_view,
        }

    select = select_of(obs)
    options = select.get("option") if isinstance(select.get("option"), list) else []
    deck = select.get("deck")
    payload = {
        "current": {
            key: current.get(key)
            for key in (
                "turn",
                "turnActionCount",
                "yourIndex",
                "firstPlayer",
                "supporterPlayed",
                "stadiumPlayed",
                "energyAttached",
                "retreated",
                "stadium",
                "looking",
                "result",
            )
        },
        "players": [player_view(player) for player in players],
        "select": {
            "type": _as_int(select.get("type")),
            "context": _as_int(select.get("context")),
            "minCount": _as_int(select.get("minCount")),
            "maxCount": _as_int(select.get("maxCount")),
            "option": options,
            "deck": [ _card_id(card) for card in deck] if isinstance(deck, list) else None,
            "contextCard": _card_id(select.get("contextCard")),
            "effect": _card_id(select.get("effect")),
        },
    }
    try:
        blob = json.dumps(payload, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return None
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


class GameState:
    """Per-match state: resolved facts, inferred beliefs and explicit unknowns."""

    def __init__(
        self,
        match_id: Any,
        *,
        deck: Optional[Iterable[int]] = None,
        card_catalog: Optional[catalog.Catalog] = None,
        energy_costs: Optional[Mapping[int, Tuple[int, ...]]] = None,
        opponent_deck_prior: Optional[Mapping[int, int]] = None,
    ) -> None:
        self.match_id = str(match_id)
        self.deck: Tuple[int, ...] = tuple(int(card) for card in (deck if deck is not None else DECK))
        self._deck_counts = Counter(self.deck)
        self.catalog = card_catalog or catalog.CATALOG
        self.energy_costs: Dict[int, Tuple[int, ...]] = dict(
            energy_costs if energy_costs is not None else ATTACK_ENERGY_COSTS
        )
        self.opponent_deck_prior: Dict[int, int] = {
            int(card): int(copies)
            for card, copies in (opponent_deck_prior or {}).items()
        }

        self.turn = 0
        self.turn_action_count = 0
        self.your_index = 0
        self.first_player = 0
        self.energy_attached_this_turn = False
        self.supporter_played = False
        self.stadium_played = False
        self.retreated = False

        self.our_active: Optional[PublicCard] = None
        self.our_bench: Tuple[PublicCard, ...] = ()
        self.our_discard: Tuple[int, ...] = ()
        self.our_deck_count = 0
        self.stadium: Tuple[int, ...] = ()

        self.our_hand: Dict[int, Optional[int]] = {}
        self.our_hand_serials: Dict[int, Optional[int]] = {}
        self.our_hand_resolution: Dict[int, str] = {}
        self.our_hand_distribution: Dict[int, Dict[int, float]] = {}
        self.hand_events: List[Dict[str, Any]] = []
        self._deck_reveal: Optional[Tuple[int, ...]] = None

        self.prizes: List[Optional[int]] = []
        self.prize_reveals: List[int] = []

        self.opponent_public = OpponentPublic()
        self.opponent_hand_distribution: Dict[int, float] = {}
        self.opponent_hand_basis = "no_deck_prior"

        self.energy_in_play: Dict[str, Dict[int, int]] = {"ours": {}, "opponent": {}}

        self._prev_board: Dict[str, Any] = {}
        self._prev_discard: Tuple[int, ...] = ()
        self._prev_stadium: Tuple[int, ...] = ()
        self._prev_deck_count = 0

        # Play/attach/evolve chosen at the previous decision, resolved now.
        self._pending: List[Dict[str, Any]] = []
        # Cards picked from a revealed deck; assigned to hand slots if the hand
        # grew and the card did not instead appear on the board.
        self._pending_arrivals: List[int] = []

        self._signatures: set[str] = set()
        self.synced_observations = 0
        self.last_sync_status = "new"
        self.last_sync_detail = ""

    # ------------------------------------------------------------------ sync

    def sync(self, obs: Any, chosen: Any = None) -> bool:
        """Fold one observation in. Returns True when it changed the state.

        A repeated observation (same signature) is a no-op, which is the
        idempotency invariant: ``sync(obs); sync(obs)`` equals one ``sync``.
        """
        signature = _observation_signature(obs)
        if signature is None:
            self.last_sync_status = "unusable"
            self.last_sync_detail = "observation lacks current.players"
            return False
        if signature in self._signatures:
            self.last_sync_status = "duplicate"
            self.last_sync_detail = ""
            return False
        self._apply(obs, chosen)
        self._signatures.add(signature)
        self.synced_observations += 1
        self.last_sync_status = "applied"
        self.last_sync_detail = ""
        return True

    def _apply(self, obs: Mapping[str, Any], chosen: Any) -> None:
        current = obs.get("current") or {}
        select = select_of(obs)
        players = [player for player in players_of(obs) if isinstance(player, Mapping)]
        self.your_index = your_index(obs)
        ours = players[self.your_index] if 0 <= self.your_index < len(players) else {}
        opp_index = opponent_index(obs)
        theirs = players[opp_index] if 0 <= opp_index < len(players) else {}

        self.turn = _as_int(current.get("turn"), self.turn) or 0
        self.turn_action_count = _as_int(current.get("turnActionCount"), 0) or 0
        self.first_player = _as_int(current.get("firstPlayer"), 0) or 0
        self.energy_attached_this_turn = bool(current.get("energyAttached", False))
        self.supporter_played = bool(current.get("supporterPlayed", False))
        self.stadium_played = bool(current.get("stadiumPlayed", False))
        self.retreated = bool(current.get("retreated", False))

        our_active, our_bench = _board_of(ours)
        opp_active, opp_bench = _board_of(theirs)
        self.our_active, self.our_bench = our_active, our_bench
        self.our_discard = _zone_ids(ours, "discard")
        self.our_deck_count = _as_int(ours.get("deckCount"), 0) or 0
        self.stadium = tuple(
            card_id for card_id in (_card_id(card) for card in _zone({"stadium": current.get("stadium")}, "stadium"))
            if card_id is not None
        )

        options = select.get("option") if isinstance(select.get("option"), list) else []
        hand_list = ours.get("hand") if isinstance(ours.get("hand"), list) else None
        hand_count = _as_int(ours.get("handCount"), None)
        if hand_count is None:
            hand_count = len(hand_list) if hand_list is not None else len(self.our_hand)

        self._update_hand(hand_list, int(hand_count), select)

        prize_count = len(_zone(ours, "prize"))
        self._update_prizes(ours, theirs, options, prize_count)
        self._update_opponent(theirs, options, opp_active, opp_bench)

        self._update_deck_reveal(select)
        self._refresh_hand_distributions()
        self._update_energy_in_play()

        self._pending = self._pending_actions(select, options, chosen)
        self._pending_arrivals = self._pending_deck_picks(select, options, chosen)

        self._prev_board = {
            "ours": self._board_snapshot(our_active, our_bench),
            "opponent": self._board_snapshot(opp_active, opp_bench),
        }
        self._prev_discard = self.our_discard
        self._prev_stadium = self.stadium
        self._prev_deck_count = self.our_deck_count

    @staticmethod
    def _board_snapshot(
        active: Optional[PublicCard], bench: Sequence[PublicCard]
    ) -> Dict[str, Any]:
        return {
            "active": None if active is None else (active.card_id, active.energies),
            "bench": tuple((card.card_id, card.energies) for card in bench),
        }

    # ------------------------------------------------------------- hand model

    def _update_hand(
        self,
        hand_list: Optional[List[Any]],
        hand_count: int,
        select: Mapping[str, Any],
    ) -> None:
        previous = dict(self.our_hand)

        # 1. The card we chose last time left the hand; resolve it from evidence.
        for pending in self._pending:
            slot = pending.get("slot")
            if not isinstance(slot, int):
                continue
            card_id = self._pending_card_id(pending, select)
            if card_id is None:
                card_id = previous.get(slot)
            self.hand_events.append(
                {
                    "turn": pending.get("turn", self.turn),
                    "slot": slot,
                    "cardId": card_id,
                    "reason": HAND_ACTION_KINDS.get(pending.get("kind"), "unknown"),
                }
            )
            self._remove_slot(slot)

        # 2. Exact rebuild whenever the arena exposes our hand this turn.
        if hand_list is not None:
            self.our_hand = {}
            self.our_hand_serials = {}
            self.our_hand_resolution = {}
            for slot, card in enumerate(hand_list):
                card_id = _card_id(card)
                self.our_hand[slot] = card_id
                self.our_hand_serials[slot] = _serial(card)
                if card_id is not None:
                    self.our_hand_resolution[slot] = "hand_visible"
            return

        # 3. Hidden hand: reconcile the tracked slots to the observed size.
        arrivals = [card_id for card_id in self._pending_arrivals if card_id is not None]
        board_ids = set(self._board_ids())
        while len(self.our_hand) < hand_count:
            slot = len(self.our_hand)
            card_id = None
            for position, candidate in enumerate(arrivals):
                if candidate not in board_ids:
                    card_id = candidate
                    arrivals.pop(position)
                    break
            self.our_hand[slot] = card_id
            self.our_hand_serials[slot] = None
            if card_id is not None:
                self.our_hand_resolution[slot] = "search"
        while len(self.our_hand) > hand_count:
            self._drop_slot(max(self.our_hand))
        # Slot indices must stay 0..n-1 after removals.
        self._renumber_slots()

    def _remove_slot(self, slot: int) -> None:
        if slot not in self.our_hand:
            return
        del self.our_hand[slot]
        self.our_hand_serials.pop(slot, None)
        self.our_hand_resolution.pop(slot, None)
        self.our_hand_distribution.pop(slot, None)
        shifted = {index - 1 if index > slot else index: card for index, card in self.our_hand.items()}
        self.our_hand = shifted
        self.our_hand_serials = {
            index - 1 if index > slot else index: serial
            for index, serial in self.our_hand_serials.items()
        }
        self.our_hand_resolution = {
            index - 1 if index > slot else index: reason
            for index, reason in self.our_hand_resolution.items()
        }
        self.our_hand_distribution = {
            index - 1 if index > slot else index: dist
            for index, dist in self.our_hand_distribution.items()
        }

    def _drop_slot(self, slot: int) -> None:
        if slot not in self.our_hand:
            return
        del self.our_hand[slot]
        self.our_hand_serials.pop(slot, None)
        self.our_hand_resolution.pop(slot, None)
        self.our_hand_distribution.pop(slot, None)

    def _renumber_slots(self) -> None:
        order = sorted(self.our_hand)
        if order == list(range(len(order))):
            return
        mapping = {old: new for new, old in enumerate(order)}
        self.our_hand = {mapping[old]: card for old, card in self.our_hand.items()}
        self.our_hand_serials = {
            mapping[old]: serial for old, serial in self.our_hand_serials.items() if old in mapping
        }
        self.our_hand_resolution = {
            mapping[old]: reason for old, reason in self.our_hand_resolution.items() if old in mapping
        }
        self.our_hand_distribution = {
            mapping[old]: dist for old, dist in self.our_hand_distribution.items() if old in mapping
        }

    def resolve_slot(self, slot: int, card_id: Any, reason: str) -> bool:
        """Resolve a slot that is still in hand (search return, named in a log)."""
        card = _as_int(card_id)
        if card is None or slot not in self.our_hand:
            return False
        self.our_hand[slot] = card
        self.our_hand_resolution[slot] = str(reason)
        self.our_hand_distribution.pop(slot, None)
        return True

    def slot_distribution(self, slot: int) -> Dict[int, float]:
        """Distribution over card ids for an unresolved hand slot."""
        return dict(self.our_hand_distribution.get(slot, {}))

    def _pending_card_id(
        self, pending: Mapping[str, Any], select: Mapping[str, Any]
    ) -> Optional[int]:
        kind = pending.get("kind")
        if not isinstance(kind, int):
            return None
        if kind == OPTION_ATTACH:
            return self._attached_energy_delta(pending)
        if kind == OPTION_EVOLVE:
            return self._evolved_card_id(pending)
        if kind == OPTION_PLAY:
            for source in (select.get("effect"), select.get("contextCard")):
                card_id = _card_id(source) if isinstance(source, Mapping) else None
                if card_id is not None:
                    return card_id
            card_id = self._new_board_card()
            if card_id is not None:
                return card_id
            new_stadium = [card for card in self.stadium if card not in self._prev_stadium]
            if len(new_stadium) == 1:
                return new_stadium[0]
            new_discard = list(
                (Counter(self.our_discard) - Counter(self._prev_discard)).elements()
            )
            if len(new_discard) == 1:
                return new_discard[0]
        return None

    def _target_board_card(self, pending: Mapping[str, Any]) -> Optional[PublicCard]:
        area, index = pending.get("target", (None, None))
        if area == AREA_ACTIVE:
            return self.our_active
        if area == AREA_BENCH:
            try:
                return self.our_bench[int(index)]
            except (IndexError, TypeError, ValueError):
                return None
        return None

    def _attached_energy_delta(self, pending: Mapping[str, Any]) -> Optional[int]:
        area, index = pending.get("target", (None, None))
        current = self._target_board_card(pending)
        prev_active = self._prev_board.get("ours", {}).get("active")
        prev_bench = self._prev_board.get("ours", {}).get("bench") or ()
        if area == AREA_ACTIVE:
            before = prev_active[1] if prev_active else ()
        elif area == AREA_BENCH:
            try:
                before = prev_bench[int(index)][1]
            except (IndexError, TypeError, ValueError):
                before = ()
        else:
            before = ()
        if current is None:
            return None
        new = list((Counter(current.energies) - Counter(before)).elements())
        if len(new) == 1:
            return new[0]
        return None

    def _evolved_card_id(self, pending: Mapping[str, Any]) -> Optional[int]:
        area, index = pending.get("target", (None, None))
        current = self._target_board_card(pending)
        if current is None:
            return None
        if area == AREA_ACTIVE:
            before = self._prev_board.get("ours", {}).get("active")
            before_id = before[0] if before else None
        elif area == AREA_BENCH:
            try:
                before_id = self._prev_board["ours"]["bench"][int(index)][0]
            except (IndexError, KeyError, TypeError, ValueError):
                before_id = None
        else:
            before_id = None
        if before_id is not None and current.card_id != before_id:
            return current.card_id
        return None

    def _new_board_card(self) -> Optional[int]:
        before = set(self._prev_board_ids())
        after = self._board_ids()
        new = [card_id for card_id in after if card_id not in before]
        return new[0] if len(new) == 1 else None

    def _board_ids(self) -> Tuple[int, ...]:
        ids: List[int] = [self.our_active.card_id] if self.our_active is not None else []
        ids.extend(card.card_id for card in self.our_bench)
        return tuple(ids)

    def _prev_board_ids(self) -> Tuple[int, ...]:
        ours = self._prev_board.get("ours", {})
        active = ours.get("active")
        ids: List[int] = [active[0]] if active else []
        ids.extend(entry[0] for entry in ours.get("bench") or ())
        return tuple(ids)

    def _update_deck_reveal(self, select: Mapping[str, Any]) -> None:
        deck = select.get("deck")
        if isinstance(deck, list) and deck:
            ids = [card_id for card_id in (_card_id(card) for card in deck) if card_id is not None]
            if ids:
                self._deck_reveal = tuple(ids)
                return
        if self._deck_reveal is None:
            return
        drawn = self._prev_deck_count - self.our_deck_count
        if drawn > 0 and drawn <= len(self._deck_reveal):
            self._deck_reveal = self._deck_reveal[drawn:]
        elif drawn < 0:
            self._deck_reveal = None

    def _pending_actions(
        self, select: Mapping[str, Any], options: Sequence[Any], chosen: Any
    ) -> List[Dict[str, Any]]:
        pending: List[Dict[str, Any]] = []
        if not isinstance(chosen, str):
            return pending
        for index in parse_action_indices(chosen):
            if not 0 <= index < len(options):
                continue
            option = options[index]
            slot = _hand_slot(option)
            if slot is None:
                continue
            pending.append(
                {
                    "slot": slot,
                    "kind": option.get("type"),
                    "turn": self.turn,
                    "target": (option.get("inPlayArea"), option.get("inPlayIndex")),
                }
            )
        return pending

    def _pending_deck_picks(
        self, select: Mapping[str, Any], options: Sequence[Any], chosen: Any
    ) -> List[int]:
        """Cards chosen from a revealed deck, which may land in hand next obs."""
        deck = select.get("deck")
        if not isinstance(deck, list) or not isinstance(chosen, str):
            return []
        picks: List[int] = []
        for index in parse_action_indices(chosen):
            if not 0 <= index < len(options):
                continue
            option = options[index]
            if not isinstance(option, Mapping) or option.get("type") != OPTION_CHOOSE_CARD:
                continue
            if _as_int(option.get("area")) != AREA_DECK:
                continue
            deck_index = _as_int(option.get("index"))
            if deck_index is None or not 0 <= deck_index < len(deck):
                continue
            card_id = _card_id(deck[deck_index])
            if card_id is not None:
                picks.append(card_id)
        return picks

    def _refresh_hand_distributions(self) -> None:
        pool = self.unseen_pool()
        total = sum(pool.values())
        if total <= 0:
            self.our_hand_distribution = {
                slot: {} for slot, card_id in self.our_hand.items() if card_id is None
            }
            return
        distribution = {card_id: count / total for card_id, count in sorted(pool.items())}
        self.our_hand_distribution = {
            slot: dict(distribution)
            for slot, card_id in sorted(self.our_hand.items())
            if card_id is None
        }

    def unseen_pool(self) -> Dict[int, int]:
        """Deck cards whose location is not publicly visible (conservative).

        Cards under an evolved Pokemon are not exposed by the observation, so
        they remain in the pool; the result is an upper bound on the deck.
        """
        pool = Counter(self._deck_counts)
        for card_id in self.our_hand.values():
            if card_id is not None:
                pool[card_id] -= 1
        for card_id in self.our_discard:
            pool[card_id] -= 1
        for card_id in self._board_ids():
            pool[card_id] -= 1
        for card_id in self.prize_reveals:
            pool[card_id] -= 1
        return {card_id: count for card_id, count in sorted(pool.items()) if count > 0}

    @property
    def our_deck_order_belief(self) -> Dict[int, Dict[int, float]]:
        """Position -> card distribution for the remaining deck.

        A revealed deck (search) fixes the positions it shows. With no reveal
        the positions are exchangeable, so each carries the uniform
        distribution over :meth:`unseen_pool`.
        """
        if self._deck_reveal is not None:
            return {position: {card_id: 1.0} for position, card_id in enumerate(self._deck_reveal)}
        pool = self.unseen_pool()
        total = sum(pool.values())
        if total <= 0:
            return {position: {} for position in range(self.our_deck_count)}
        distribution = {card_id: count / total for card_id, count in sorted(pool.items())}
        return {position: dict(distribution) for position in range(self.our_deck_count)}

    # ----------------------------------------------------------- other zones

    def _update_prizes(
        self,
        ours: Mapping[str, Any],
        theirs: Mapping[str, Any],
        options: Sequence[Any],
        prize_count: int,
    ) -> None:
        revealed = list(self.prize_reveals)
        for option in options:
            if not isinstance(option, Mapping):
                continue
            if _as_int(option.get("area")) != AREA_PRIZE:
                continue
            player_index = _as_int(option.get("playerIndex"), self.your_index)
            index = _as_int(option.get("index"))
            if index is None:
                continue
            zone = _zone(ours if player_index == self.your_index else theirs, "prize")
            card_id = _card_id(zone[index]) if 0 <= index < len(zone) else None
            if card_id is None:
                card_id = _card_id(option)
            if card_id is not None and card_id not in revealed:
                revealed.append(card_id)
        self.prize_reveals = revealed
        known = revealed[:prize_count]
        self.prizes = list(known) + [None] * max(0, prize_count - len(known))

    def _update_opponent(
        self,
        theirs: Mapping[str, Any],
        options: Sequence[Any],
        active: Optional[PublicCard],
        bench: Tuple[PublicCard, ...],
    ) -> None:
        prize_count = len(_zone(theirs, "prize"))
        prizes: List[Optional[int]] = [None] * prize_count
        for option in options:
            if not isinstance(option, Mapping):
                continue
            if _as_int(option.get("area")) != AREA_PRIZE:
                continue
            if _as_int(option.get("playerIndex")) == self.your_index:
                continue
            index = _as_int(option.get("index"))
            card_id = _card_id(option)
            if index is not None and 0 <= index < prize_count and card_id is not None:
                prizes[index] = card_id

        self.opponent_public = OpponentPublic(
            active=active,
            bench=bench,
            discard=_zone_ids(theirs, "discard"),
            prizes=tuple(prizes),
            hand_count=_as_int(theirs.get("handCount"), 0) or 0,
            deck_count=_as_int(theirs.get("deckCount"), 0) or 0,
        )
        self.opponent_hand_distribution, self.opponent_hand_basis = (
            self._opponent_hand_distribution(self.opponent_public)
        )

    def _opponent_hand_distribution(
        self, public: OpponentPublic
    ) -> Tuple[Dict[int, float], str]:
        """P(at least one copy in hand) per card, only with a supplied prior."""
        if not self.opponent_deck_prior or public.hand_count <= 0:
            return {}, "no_deck_prior"
        seen = Counter(public.ids_in_play())
        seen.update(public.discard)
        seen.update(card_id for card_id in public.prizes if card_id is not None)
        hidden_prizes = sum(1 for card_id in public.prizes if card_id is None)
        unseen_total = public.hand_count + public.deck_count + hidden_prizes
        if unseen_total <= 0:
            return {}, "no_deck_prior"
        hand = min(public.hand_count, unseen_total)
        out: Dict[int, float] = {}
        for card_id, copies in sorted(self.opponent_deck_prior.items()):
            remaining = max(0, int(copies) - seen.get(card_id, 0))
            if remaining <= 0:
                continue
            if remaining >= unseen_total:
                out[card_id] = 1.0
                continue
            miss = math.comb(unseen_total - remaining, hand) / math.comb(unseen_total, hand)
            out[card_id] = 1.0 - miss
        return out, "hypergeometric_prior"

    def _update_energy_in_play(self) -> None:
        ours: Counter = Counter()
        for card in ([self.our_active] if self.our_active else []) + list(self.our_bench):
            ours.update(card.energies)
        theirs: Counter = Counter()
        for card in ([self.opponent_public.active] if self.opponent_public.active else []) + list(
            self.opponent_public.bench
        ):
            theirs.update(card.energies)
        self.energy_in_play = {
            "ours": dict(sorted(ours.items())),
            "opponent": dict(sorted(theirs.items())),
        }

    # --------------------------------------------------------------- attacks

    def _find_board_card(self, card: Any) -> Optional[PublicCard]:
        if isinstance(card, PublicCard):
            return card
        if isinstance(card, catalog.Card):
            card_id = card.card_id
        elif isinstance(card, Mapping):
            return None
        else:
            card_id = _as_int(card)
        if card_id is None:
            return None
        if self.our_active is not None and self.our_active.card_id == card_id:
            return self.our_active
        for bench_card in self.our_bench:
            if bench_card.card_id == card_id:
                return bench_card
        return None

    def can_attack_next_turn(
        self,
        card: Any,
        attack: Any,
        pending_attachments: Optional[int] = None,
    ) -> bool:
        """True when ``card`` can pay ``attack``'s catalog cost on the next turn.

        ``card`` may be a board card (mapping with ``energies``) or a card
        id/``catalog.Card`` already in play. ``pending_attachments`` defaults to
        the manual attachment still available this turn; next turn's attachment
        is deliberately not counted because the body may be knocked out first.
        An unknown energy cost returns False: the state layer never certifies
        an attack it cannot price.
        """
        attached: Tuple[int, ...] = ()
        if isinstance(card, Mapping) and not isinstance(card, PublicCard):
            attached = _card_energies(card)
        else:
            board_card = self._find_board_card(card)
            if board_card is None:
                return False
            attached = board_card.energies
        cost = attack_energy_cost(attack, self.energy_costs)
        if cost is None:
            return False
        if pending_attachments is None:
            pending = 0 if self.energy_attached_this_turn else 1
        else:
            pending = max(0, int(pending_attachments))
        return energy_cost_payable(cost, attached, pending)

    # ------------------------------------------------------------- reporting

    def snapshot(self, include_beliefs: bool = False) -> Dict[str, Any]:
        """Stable, JSON-safe view used by the idempotency property test."""
        data: Dict[str, Any] = {
            "matchId": self.match_id,
            "turn": self.turn,
            "turnActionCount": self.turn_action_count,
            "yourIndex": self.your_index,
            "energyAttachedThisTurn": self.energy_attached_this_turn,
            "ourHand": {str(slot): card for slot, card in sorted(self.our_hand.items())},
            "ourHandSerials": {
                str(slot): serial for slot, serial in sorted(self.our_hand_serials.items())
            },
            "ourHandResolution": {
                str(slot): reason for slot, reason in sorted(self.our_hand_resolution.items())
            },
            "ourHandDistribution": {
                str(slot): {
                    str(card_id): round(probability, 6)
                    for card_id, probability in sorted(distribution.items())
                }
                for slot, distribution in sorted(self.our_hand_distribution.items())
            },
            "handEvents": [
                {key: event.get(key) for key in ("turn", "slot", "cardId", "reason")}
                for event in self.hand_events
            ],
            "prizes": list(self.prizes),
            "prizeReveals": list(self.prize_reveals),
            "ourActive": _public_dict(self.our_active),
            "ourBench": [_public_dict(card) for card in self.our_bench],
            "ourDiscard": list(self.our_discard),
            "ourDeckCount": self.our_deck_count,
            "deckReveal": list(self._deck_reveal) if self._deck_reveal is not None else None,
            "opponent": {
                "active": _public_dict(self.opponent_public.active),
                "bench": [_public_dict(card) for card in self.opponent_public.bench],
                "discard": list(self.opponent_public.discard),
                "prizes": list(self.opponent_public.prizes),
                "handCount": self.opponent_public.hand_count,
                "deckCount": self.opponent_public.deck_count,
            },
            "opponentHandDistribution": {
                str(card_id): round(probability, 6)
                for card_id, probability in sorted(self.opponent_hand_distribution.items())
            },
            "opponentHandBasis": self.opponent_hand_basis,
            "energyInPlay": {
                "ours": {str(energy): count for energy, count in sorted(self.energy_in_play["ours"].items())},
                "opponent": {
                    str(energy): count for energy, count in sorted(self.energy_in_play["opponent"].items())
                },
            },
            "unseenPool": {str(card_id): count for card_id, count in sorted(self.unseen_pool().items())},
            "unresolvedSlots": len(self.our_hand_distribution),
        }
        if include_beliefs:
            data["ourDeckOrderBelief"] = {
                str(position): {
                    str(card_id): round(probability, 6)
                    for card_id, probability in sorted(distribution.items())
                }
                for position, distribution in sorted(self.our_deck_order_belief.items())
            }
        return data

    def serialize(self, include_beliefs: bool = False) -> str:
        """Stable serialisation for equality checks."""
        return json.dumps(
            self.snapshot(include_beliefs=include_beliefs),
            sort_keys=True,
            separators=(",", ":"),
        )


def _record_seq(record: Mapping[str, Any]) -> Tuple[int, int]:
    seq = _as_int(record.get("seq"), -1)
    ts = _as_int(record.get("ts"), 0)
    return (seq if seq is not None else -1, ts or 0)


def analyze_records(
    records: Iterable[Any],
    *,
    deck: Optional[Iterable[int]] = None,
    opponent_deck_prior: Optional[Mapping[int, int]] = None,
) -> Dict[str, Any]:
    """Replay a decision corpus through ``GameState.sync`` and report coverage.

    Read-only. Records are grouped by ``matchId`` and processed in ``seq``
    order, which is the order the bot saw them.
    """
    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    no_match = 0
    for record in records:
        if not isinstance(record, Mapping) or not record.get("matchId"):
            no_match += 1
            continue
        grouped.setdefault(str(record["matchId"]), []).append(record)

    stats: Counter = Counter()
    stats["records"] = len(grouped and [r for recs in grouped.values() for r in recs] or []) + no_match
    stats["matches"] = len(grouped)
    stats["noMatchId"] = no_match
    unknown_shapes: List[Dict[str, Any]] = []
    end_unresolved: List[Dict[str, Any]] = []
    states: Dict[str, GameState] = {}

    for match_id in sorted(grouped):
        state = GameState(match_id, deck=deck, opponent_deck_prior=opponent_deck_prior)
        stats["matchRecords"] += len(grouped[match_id])
        for record in sorted(grouped[match_id], key=_record_seq):
            stats["decisions"] += 1
            obs = record.get("obs")
            if not isinstance(obs, Mapping):
                stats["unusable"] += 1
                if len(unknown_shapes) < 25:
                    unknown_shapes.append(
                        {
                            "matchId": match_id,
                            "seq": _as_int(record.get("seq")),
                            "reason": "no obs (record predates telemetry upgrade)",
                        }
                    )
                continue
            applied = state.sync(obs, chosen=record.get("chosen"))
            if applied:
                stats["applied"] += 1
            elif state.last_sync_status == "duplicate":
                stats["duplicates"] += 1
            else:
                stats["unusable"] += 1
                if len(unknown_shapes) < 25:
                    unknown_shapes.append(
                        {
                            "matchId": match_id,
                            "seq": _as_int(record.get("seq")),
                            "reason": state.last_sync_detail or "sync rejected observation",
                        }
                    )
            current = obs.get("current") if isinstance(obs, Mapping) else None
            players = players_of(obs)
            yi = _as_int((current or {}).get("yourIndex"), 0)
            if 0 <= yi < len(players) and isinstance(players[yi], Mapping):
                hand = players[yi].get("hand")
                stats["handVisible" if isinstance(hand, list) else "handInferred"] += 1
        states[match_id] = state
        unresolved = len(state.our_hand_distribution)
        stats["slots"] += len(state.our_hand)
        stats["resolvedSlots"] += len(state.our_hand) - unresolved
        stats["unresolvedSlots"] += unresolved
        if unresolved:
            end_unresolved.append(
                {
                    "matchId": match_id,
                    "unresolvedSlots": unresolved,
                    "handSize": len(state.our_hand),
                }
            )

    stats["statesBuilt"] = stats["applied"] + stats["duplicates"]
    report = {key: stats[key] for key in sorted(stats)}
    report["states"] = len(states)
    report["endUnresolvedSlots"] = stats["unresolvedSlots"]
    report["matchesWithUnresolvedSlots"] = end_unresolved
    report["unusableSamples"] = unknown_shapes
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Replay a decision corpus through GameState.sync")
    parser.add_argument(
        "--corpus",
        default=str(Path.home() / ".arena-tcg-decisions.jsonl"),
        help="decision JSONL corpus (read-only)",
    )
    args = parser.parse_args(argv)

    from telemetry import read as read_records

    records = read_records(Path(args.corpus))
    report = analyze_records(records)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
