"""Bayesian Belief State Tracker for Pokemon TCG.

Models the opponent's hidden hand as a probability distribution over cards,
using public zone tracking and hypergeometric/Bayesian updates.

Designed for DevFun Arena Pokemon TCG (remote mode). Card IDs are integers
matching the arena card catalog.

Usage:
    tracker = BeliefTracker(opponent_deck_archetype)
    tracker.observe_play(card_id=328, zone="board")  # opponent played Pikachu ex
    tracker.observe_draw(n=1)  # opponent drew a card
    probs = tracker.hand_probabilities()  # P(card in hand) for each card
"""
from __future__ import annotations

import math
from collections import defaultdict, Counter
from typing import Dict, List, Optional, Set, Tuple


class BeliefTracker:
    """Tracks probabilistic belief about opponent's hand.

    Maintains:
    - known_public: cards observed in public zones (discard, board, prizes taken)
    - hand_size: estimated opponent hand size
    - deck_size: estimated opponent deck size
    - remaining_pool: max copies of each card still unaccounted for
    """

    def __init__(
        self,
        deck_archetype: Dict[int, int],
        total_deck_size: int = 60,
    ):
        """
        Args:
            deck_archetype: Mapping card_id -> count in a typical deck of this archetype.
                Used as the prior. If unknown, pass an empty dict and update as cards appear.
            total_deck_size: Standard deck size (60).
        """
        self.archetype = dict(deck_archetype)
        self.total_deck_size = total_deck_size

        # Public zones: card_id -> count
        self.discard: Counter = Counter()
        self.board: Counter = Counter()       # active + bench + attached
        self.prizes_taken: Counter = Counter()  # prizes opponent has taken
        self.prizes_remaining: int = 6  # opponent's remaining prize cards

        # Hand tracking
        self.hand_size: int = 0
        self.deck_size: int = total_deck_size

        # Track which cards we've seen played (for deck inference)
        self.seen_played: Set[int] = set()

        # Observed draws (opponent drew N cards this turn cycle)
        self.draws_this_turn: int = 0

    # ------------------------------------------------------------------ #
    # Public observation API
    # ------------------------------------------------------------------ #

    def observe_card(self, card_id: int, zone: str, count: int = 1):
        """Register a card revealed in a public zone.

        Args:
            card_id: Arena card ID.
            zone: One of "discard", "board", "prize_taken".
            count: Number of copies observed.
        """
        if zone == "discard":
            self.discard[card_id] += count
        elif zone == "board":
            self.board[card_id] += count
        elif zone == "prize_taken":
            self.prizes_taken[card_id] += count
            self.prizes_remaining = max(0, self.prizes_remaining - count)
        # Infer deck archetype from observed cards
        if card_id not in self.archetype:
            self.archetype[card_id] = max(self.archetype.get(card_id, 0), count)

    def observe_play(self, card_id: int):
        """Opponent played a card from hand (goes to board or discard)."""
        self.seen_played.add(card_id)
        self.hand_size = max(0, self.hand_size - 1)

    def observe_draw(self, n: int = 1):
        """Opponent drew n cards."""
        self.hand_size += n
        self.deck_size = max(0, self.deck_size - n)

    def observe_discard(self, card_id: int, count: int = 1):
        """Opponent discarded a card (e.g., via Iono, Judge, Professor's Research)."""
        self.discard[card_id] += count
        self.hand_size = max(0, self.hand_size - count)

    def observe_prize_take(self, card_id: Optional[int] = None):
        """Opponent took a prize card. If card_id known, record it."""
        self.prizes_remaining = max(0, self.prizes_remaining - 1)
        if card_id is not None:
            self.prizes_taken[card_id] += 1
            self.observe_card(card_id, "prize_taken")

    def observe_hand_size(self, size: int):
        """Set hand size from obs (if arena provides it)."""
        self.hand_size = size

    def observe_deck_size(self, size: int):
        """Set deck size from obs (if arena provides it)."""
        self.deck_size = size

    # ------------------------------------------------------------------ #
    # Core belief computation
    # ------------------------------------------------------------------ #

    def remaining_copies(self, card_id: int) -> int:
        """Max copies of card_id still unaccounted for (not in public zones)."""
        total = self.archetype.get(card_id, 0)
        accounted = (
            self.discard.get(card_id, 0)
            + self.board.get(card_id, 0)
            + self.prizes_taken.get(card_id, 0)
        )
        return max(0, total - accounted)

    def total_remaining_pool(self) -> int:
        """Total cards in deck+hand not yet observed in public zones."""
        accounted = (
            sum(self.discard.values())
            + sum(self.board.values())
            + sum(self.prizes_taken.values())
        )
        return max(0, self.total_deck_size - accounted)

    def hand_probabilities(self) -> Dict[int, float]:
        """Compute P(card_id is in opponent's hand) for each card.

        Uses hypergeometric: P(at least 1 copy in hand of size h from pool of
        size N, where r copies of this card remain in the pool).
        """
        h = self.hand_size
        N = self.total_remaining_pool()

        if h <= 0 or N <= 0:
            return {cid: 0.0 for cid in self.archetype}

        probs: Dict[int, float] = {}
        for card_id in self.archetype:
            r = self.remaining_copies(card_id)
            if r <= 0:
                probs[card_id] = 0.0
                continue
            # P(at least 1 in hand) = 1 - C(N-r, h) / C(N, h)
            if N - r >= h:
                try:
                    p_none = math.comb(N - r, h) / math.comb(N, h)
                    probs[card_id] = max(0.0, min(1.0, 1.0 - p_none))
                except (ValueError, ZeroDivisionError):
                    probs[card_id] = r / N if N > 0 else 0.0
            else:
                # All remaining copies must be in hand
                probs[card_id] = 1.0
        return probs

    def expected_copies_in_hand(self, card_id: int) -> float:
        """Expected number of copies of card_id in opponent's hand."""
        h = self.hand_size
        N = self.total_remaining_pool()
        if N <= 0:
            return 0.0
        r = self.remaining_copies(card_id)
        return r * h / N

    def top_threats(self, n: int = 5) -> List[Tuple[int, float]]:
        """Return top-n cards by P(in hand), sorted descending."""
        probs = self.hand_probabilities()
        return sorted(probs.items(), key=lambda x: -x[1])[:n]

    def is_likely_in_hand(self, card_id: int, threshold: float = 0.5) -> bool:
        """Quick check: is card_id likely in opponent's hand?"""
        return self.hand_probabilities().get(card_id, 0.0) >= threshold

    # ------------------------------------------------------------------ #
    # Bayesian conditional updates
    # ------------------------------------------------------------------ #

    def update_on_play(self, card_id: int):
        """Opponent played card_id from hand. Reduce hand, add to board."""
        self.observe_play(card_id)
        self.observe_card(card_id, "board")

    def update_on_discard(self, card_id: int, count: int = 1):
        """Opponent discarded card_id (e.g., via Iono, Judge, Professor's Research)."""
        self.observe_discard(card_id, count)
        self.observe_card(card_id, "discard", count)

    def update_on_search(self, searched_card: int):
        """Opponent searched their deck for a card (e.g., Ultra Ball, Buddy-Buddy Poffin).
        This card is now in their hand with high probability."""
        # The searched card moves from deck to hand
        self.hand_size += 1
        self.deck_size = max(0, self.deck_size - 1)
        # Reduce remaining pool for this card
        if searched_card in self.archetype:
            self.archetype[searched_card] = max(0, self.archetype[searched_card] - 1)
        # Mark as likely in hand (probability ~1.0)
        self.board[searched_card] = self.board.get(searched_card, 0)  # no-op, just tracking

    def update_on_end_turn(self):
        """Reset per-turn counters."""
        self.draws_this_turn = 0

    # ------------------------------------------------------------------ #
    # Deck inference
    # ------------------------------------------------------------------ #

    def infer_archetype_from_played(self) -> Dict[int, int]:
        """Infer opponent's deck archetype from cards seen played.

        Returns a dict of card_id -> estimated count based on observed cards.
        Useful when opponent's deck list is unknown.
        """
        inferred: Dict[int, int] = {}
        # Count each seen card at least once; estimate 2-4 copies for staples
        for cid in self.seen_played:
            inferred[cid] = max(inferred.get(cid, 0), 1)
        # Also include discarded and boarded cards
        for cid in set(list(self.discard.keys()) + list(self.board.keys())):
            inferred[cid] = max(inferred.get(cid, 0), 1)
        return inferred

    def merge_archetype(self, new_archetype: Dict[int, int]):
        """Merge a new archetype estimate into the current one (take max counts)."""
        for cid, count in new_archetype.items():
            self.archetype[cid] = max(self.archetype.get(cid, 0), count)

    # ------------------------------------------------------------------ #
    # Debug / introspection
    # ------------------------------------------------------------------ #

    def summary(self) -> str:
        """Human-readable summary of belief state."""
        lines = [
            f"Hand size: {self.hand_size}",
            f"Deck size: {self.deck_size}",
            f"Prizes remaining: {self.prizes_remaining}",
            f"Discard: {dict(self.discard)}",
            f"Board: {dict(self.board)}",
            f"Prizes taken: {dict(self.prizes_taken)}",
            f"Top threats: {self.top_threats(5)}",
        ]
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"BeliefTracker(hand={self.hand_size}, deck={self.deck_size}, prizes={self.prizes_remaining})"


# ------------------------------------------------------------------ #
# Example usage with arena obs
# ------------------------------------------------------------------ #

def build_tracker_from_obs(obs: dict, opponent_deck_archetype: Dict[int, int]) -> BeliefTracker:
    """Build a BeliefTracker from arena observation.

    The arena obs may include:
    - obs["opponent"]["handSize"] or obs["opponentHandSize"]
    - obs["opponent"]["deckSize"] or obs["opponentDeckSize"]
    - obs["opponent"]["prizesRemaining"]
    - obs["discard"] or obs["opponentDiscard"]
    """
    tracker = BeliefTracker(opponent_deck_archetype)

    # Try to extract hand/deck/prize sizes from obs
    opp = obs.get("opponent", {}) if isinstance(obs, dict) else {}
    hand_size = opp.get("handSize", obs.get("opponentHandSize", 0)) if isinstance(obs, dict) else 0
    deck_size = opp.get("deckSize", obs.get("opponentDeckSize", 60)) if isinstance(obs, dict) else 60
    prizes = opp.get("prizesRemaining", obs.get("opponentPrizesRemaining", 6)) if isinstance(obs, dict) else 6

    tracker.observe_hand_size(hand_size)
    tracker.observe_deck_size(deck_size)
    tracker.prizes_remaining = prizes

    # Extract discard pile
    discard = obs.get("discard", obs.get("opponentDiscard", [])) if isinstance(obs, dict) else []
    if isinstance(discard, list):
        for card_id in discard:
            if isinstance(card_id, int):
                tracker.observe_card(card_id, "discard")

    # Extract opponent's board
    board = obs.get("opponentBoard", obs.get("opponent", {}).get("board", [])) if isinstance(obs, dict) else []
    if isinstance(board, list):
        for card_id in board:
            if isinstance(card_id, int):
                tracker.observe_card(card_id, "board")

    return tracker


if __name__ == "__main__":
    # Quick smoke test
    archetype = {328: 2, 625: 2, 299: 2, 39: 2, 390: 2, 1: 40}
    t = BeliefTracker(archetype)
    t.observe_hand_size(7)
    t.observe_deck_size(53)
    print("Initial probs:", t.hand_probabilities())
    t.observe_play(328)  # opponent played Pikachu ex
    print("After play:", t.hand_probabilities())
    print(t.summary())
