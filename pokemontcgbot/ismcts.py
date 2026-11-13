"""ISMCTS (Information Set MCTS) for Pokemon TCG.

Information-set Monte Carlo Tree Search for Pokemon TCG. Uses belief state
to sample opponent hands/deck, then runs MCTS with chance nodes for draws.

Since we don't have a full game simulator, this module provides:
1. A lightweight belief-weighted heuristic that uses the BeliefTracker
   to score legal actions by opponent threat probability.
2. A framework for ISMCTS that can be extended with a simulator later.

The search evaluates each legal action by:
- Immediate damage output
- Belief-weighted opponent response (what they likely have in hand)
- Prize trade value (KOs taken vs KOs given)
- Safety (retreat when active is low HP)

Usage:
    from belief import BeliefTracker
    from ismcts import ISMCTSSearch

    tracker = BeliefTracker(opponent_archetype)
    search = ISMCTSSearch(tracker, time_budget_ms=1500)
    best_action = search.search(obs, legal_actions)
"""
from __future__ import annotations

import time
import math
import random
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field

from belief import BeliefTracker


@dataclass
class Node:
    """MCTS node representing a game state after an action."""
    action: str
    parent: Optional["Node"] = None
    children: List["Node"] = field(default_factory=list)
    visits: int = 0
    value: float = 0.0
    untried_actions: List[str] = field(default_factory=list)

    def ucb1(self, c: float = 1.414) -> float:
        if self.visits == 0:
            return float("inf")
        if self.parent is None or self.parent.visits == 0:
            return self.value / self.visits
        return (self.value / self.visits) + c * math.sqrt(
            math.log(self.parent.visits) / self.visits
        )


class ISMCTSSearch:
    """Belief-weighted MCTS for Pokemon TCG.

    Without a full game simulator, this uses a heuristic evaluation that
    considers:
    1. Immediate damage (from obs.select.option)
    2. Belief-weighted opponent threat (what they likely have)
    3. Prize trade value
    4. Safety (retreat when low HP)
    """

    def __init__(
        self,
        belief: BeliefTracker,
        time_budget_ms: int = 1500,
        max_iterations: int = 200,
        exploration: float = 1.414,
    ):
        self.belief = belief
        self.time_budget_ms = time_budget_ms
        self.max_iterations = max_iterations
        self.exploration = exploration

    def search(self, obs: dict, legal_actions: List[str]) -> str:
        """Return the best legal action given obs and belief state."""
        if not legal_actions:
            return None
        if len(legal_actions) == 1:
            return legal_actions[0]

        # Score each action using belief-weighted heuristic
        scored = []
        for action in legal_actions:
            score = self._score_action(action, obs, legal_actions)
            scored.append((action, score))

        # Sort by score descending, tie-break by original order
        scored.sort(key=lambda x: -x[1])
        return scored[0][0]

    def _score_action(self, action: str, obs: dict, legal_actions: List[str]) -> float:
        """Score a single legal action using belief-weighted heuristic."""
        score = 0.0

        # 1. Immediate damage
        select = (obs.get("select") or {}) if isinstance(obs, dict) else {}
        options = select.get("option") or []
        idx = self._parse_index(action)
        if idx is not None and 0 <= idx < len(options):
            opt = options[idx] or {}
            score += int(opt.get("damage") or 0) * 2.0  # damage is king

        # 2. Belief-weighted threat assessment
        # If opponent likely has a counter card (high threat prob), be defensive
        threats = self.belief.top_threats(3)
        max_threat_prob = threats[0][1] if threats else 0.0
        # High threat → slight penalty for aggressive plays (prefer safe)
        if max_threat_prob > 0.6:
            score -= 5.0  # opponent likely has a counter

        # 3. Prize trade value
        # If this action takes a prize, bonus
        opt_text = ""
        if idx is not None and 0 <= idx < len(options):
            opt_text = str((options[idx] or {}).get("text", "")).lower()
        if "prize" in opt_text or "knock out" in opt_text:
            score += 50.0  # taking prizes is very valuable

        # 4. Safety: retreat when active is low HP
        # (Heuristic: if legal action is a retreat and our active is damaged, bonus)
        if "retreat" in action.lower() or (idx is not None and "retreat" in opt_text):
            # Check if our active Pokemon is low HP
            our_active_hp = self._get_our_active_hp(obs)
            if our_active_hp is not None and our_active_hp < 60:
                score += 30.0  # retreat when low HP

        # 5. Prefer playing cards that set up future turns
        if "play" in action.lower() or (idx is not None and "play" in opt_text):
            score += 2.0

        # 6. Avoid passing if we can attack
        if action.lower() in ("pass", "end turn", "endturn"):
            # Slight penalty for passing when we could do something
            if len(legal_actions) > 1:
                score -= 3.0

        # 7. Belief: if opponent likely has Boss's Orders, avoid benching weak Pokémon
        boss_prob = self.belief.hand_probabilities().get(0, 0.0)  # card 0 = unknown
        # (This is a placeholder; real implementation would check for specific card IDs)

        return score

    def _parse_index(self, action: str) -> Optional[int]:
        s = action.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                return int(s[1:-1])
            except ValueError:
                return None
        return None

    def _get_our_active_hp(self, obs: dict) -> Optional[int]:
        """Extract our active Pokemon's HP from obs if available."""
        if not isinstance(obs, dict):
            return None
        # Try various obs formats
        for key in ("activeHp", "ourActiveHp", "active_hp"):
            if key in obs:
                try:
                    return int(obs[key])
                except (ValueError, TypeError):
                    pass
        # Try nested
        our = obs.get("our", {}) if isinstance(obs.get("our"), dict) else {}
        for key in ("activeHp", "hp", "active_hp"):
            if key in our:
                try:
                    return int(our[key])
                except (ValueError, TypeError):
                    pass
        return None

    def update_belief_from_obs(self, obs: dict, prev_obs: Optional[dict] = None):
        """Update belief state based on new observation.

        Call this after each poll to track opponent's public actions.
        """
        if not isinstance(obs, dict):
            return

        # Extract opponent hand/deck/prize sizes
        opp = obs.get("opponent", {}) if isinstance(obs.get("opponent"), dict) else {}
        hand_size = opp.get("handSize", obs.get("opponentHandSize"))
        deck_size = opp.get("deckSize", obs.get("opponentDeckSize"))
        prizes = opp.get("prizesRemaining", obs.get("opponentPrizesRemaining"))

        if hand_size is not None:
            # Detect draws: if hand size increased, opponent drew
            if self.belief.hand_size > 0 and hand_size > self.belief.hand_size:
                self.belief.observe_draw(hand_size - self.belief.hand_size)
            self.belief.observe_hand_size(hand_size)
        if deck_size is not None:
            self.belief.observe_deck_size(deck_size)
        if prizes is not None:
            self.belief.prizes_remaining = prizes

        # Extract discard pile
        discard = obs.get("discard", obs.get("opponentDiscard", []))
        if isinstance(discard, list):
            for card_id in discard:
                if isinstance(card_id, int):
                    self.belief.observe_card(card_id, "discard")

        # Extract opponent board
        board = obs.get("opponentBoard", opp.get("board", []))
        if isinstance(board, list):
            for card_id in board:
                if isinstance(card_id, int):
                    self.belief.observe_card(card_id, "board")

        # Infer archetype from observed cards
        inferred = self.belief.infer_archetype_from_played()
        if inferred:
            self.belief.merge_archetype(inferred)


class BeliefWeightedHeuristic:
    """Drop-in replacement for bot.py's choose_action that uses belief state.

    Wraps ISMCTSSearch and adds belief-aware scoring.
    """

    def __init__(self, belief: BeliefTracker, time_budget_ms: int = 1000):
        self.belief = belief
        self.search = ISMCTSSearch(belief, time_budget_ms=time_budget_ms)

    def choose(self, obs: dict, legal_actions: List[str]) -> Optional[str]:
        """Choose best legal action using belief-weighted search."""
        if not legal_actions:
            return None
        if len(legal_actions) == 1:
            return legal_actions[0]

        # Update belief from obs before deciding
        self.search.update_belief_from_obs(obs)

        return self.search.search(obs, legal_actions)


# ------------------------------------------------------------------ #
# Integration helper for bot.py
# ------------------------------------------------------------------ #

def create_belief_tracker(opponent_archetype: Optional[Dict[int, int]] = None) -> BeliefTracker:
    """Create a BeliefTracker with optional known opponent archetype."""
    if opponent_archetype is None:
        # Unknown opponent — start empty, infer from plays
        opponent_archetype = {}
    return BeliefTracker(opponent_archetype)


if __name__ == "__main__":
    # Smoke test
    from belief import BeliefTracker

    archetype = {328: 2, 625: 2, 299: 2, 39: 2, 390: 2, 1: 40}
    tracker = BeliefTracker(archetype)
    tracker.observe_hand_size(7)
    tracker.observe_deck_size(53)

    search = ISMCTSSearch(tracker, time_budget_ms=500)
    obs = {"select": {"option": [{"damage": 30}, {"damage": 40}, {"damage": 0}]}}
    legal = ["[0]", "[1]", "[2]"]
    best = search.search(obs, legal)
    print(f"Best action: {best}")
    print(f"Belief: {tracker.summary()}")
