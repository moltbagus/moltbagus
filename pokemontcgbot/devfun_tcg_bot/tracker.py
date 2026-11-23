from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from math import comb
from typing import Dict, List, Set


@dataclass
class OpponentLedger:
    observed_cards: Counter = field(default_factory=Counter)
    gust_played: int = 0
    energy_denial_played: int = 0
    supporters_played: int = 0

    def record_action(self, action_event: dict) -> None:
        name = action_event.get("card_name", "")
        tags = set(action_event.get("tags", []))
        if not name:
            return
        self.observed_cards[name] += 1
        if "GUST" in tags or "Boss" in name:
            self.gust_played += 1
        if "ENERGY_DENIAL" in tags or "Hammer" in name:
            self.energy_denial_played += 1
        if action_event.get("card_type") == "SUPPORTER":
            self.supporters_played += 1

    def remaining_gust_outs(self, assumed_copies: int = 2) -> int:
        return max(0, assumed_copies - self.gust_played)


class CardTracker:
    """Exact hypergeometric draw probabilities and prize-trap deductions."""

    def __init__(self, full_deck_list: List[str]):
        self.full_deck: Counter = Counter(full_deck_list)
        self.known_cards: Counter = Counter()
        self.opp = OpponentLedger()

    def sync_from_state(self, state: dict) -> None:
        visible: Counter = Counter()
        for zone in ("my_hand", "my_discard", "my_active", "my_bench"):
            cards = state.get(zone, [])
            if isinstance(cards, dict):
                cards = [cards]
            if not isinstance(cards, (list, tuple)):
                continue
            for card in cards or []:
                if not card:
                    continue
                if isinstance(card, str):
                    visible[card] += 1
                    continue
                visible[card.get("name", "")] += 1
                for attached in card.get("attached_cards", []) or []:
                    if isinstance(attached, str):
                        visible[attached] += 1
                    else:
                        visible[attached.get("name", "")] += 1
        self.known_cards = visible

    @property
    def unknown_pool(self) -> Counter:
        pool = self.full_deck.copy()
        pool.subtract(self.known_cards)
        return Counter({k: v for k, v in pool.items() if v > 0})

    def remaining_copies(self, card_name: str) -> int:
        return self.unknown_pool.get(card_name, 0)

    def is_definitely_prized(self, card_name: str) -> bool:
        return self.full_deck.get(card_name, 0) > 0 and self.remaining_copies(card_name) == 0

    def prob_draw_at_least_one(self, target_cards: Set[str], draw_count: int) -> float:
        pool = self.unknown_pool
        total = sum(pool.values())
        if total <= 0 or draw_count <= 0:
            return 0.0
        hits = sum(pool[c] for c in target_cards)
        if hits <= 0:
            return 0.0
        if draw_count >= total - hits + 1:
            return 1.0
        prob_zero = comb(total - hits, draw_count) / comb(total, draw_count)
        return round(1.0 - prob_zero, 4)
