"""Information-set search for Pokemon TCG.

The implementation samples hidden threat cards from the belief hand
probabilities, then runs bounded UCB1 over legal action nodes with a heuristic
score. It does not simulate draws or full game trees; no rollout is claimed.

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
from typing import Any, Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field

from belief import BeliefTracker
from scoring import (
    OPTION_ATTACH,
    OPTION_ATTACK,
    OPTION_END_TURN,
    OPTION_PLAY,
    OPTION_RETREAT,
    action_score,
    our_active,
    parse_action_indices,
    players_of,
    select_of,
    your_index,
)


# Cards whose presence in the opponent's hand changes our move choice.
GUST_CARD_IDS = {1182}
ENERGY_DENIAL_CARD_IDS = {1120}
HAND_DISRUPTION_CARD_IDS = {1213}
THREAT_CARD_IDS = GUST_CARD_IDS | ENERGY_DENIAL_CARD_IDS | HAND_DISRUPTION_CARD_IDS


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
        belief: Any,
        time_budget_ms: int = 1500,
        max_iterations: int = 200,
        exploration: float = 1.414,
        rng_seed: Optional[int] = None,
    ):
        self.belief = belief
        self.time_budget_ms = time_budget_ms
        self.max_iterations = max_iterations
        self.exploration = exploration
        self.rng = random.Random(rng_seed)

    def _sample_threats(self) -> Set[int]:
        """Sample hidden threat cards from the belief hand probabilities."""
        try:
            probs = self.belief.hand_probabilities() or {}
        except Exception:
            return set()
        sampled: Set[int] = set()
        for card_id in THREAT_CARD_IDS:
            probability = probs.get(card_id, 0.0)
            if probability > 0 and self.rng.random() < probability:
                sampled.add(card_id)
        return sampled

    def _option_type(self, action: str, obs: dict) -> Optional[int]:
        indices = parse_action_indices(action)
        if len(indices) != 1:
            return None
        options = select_of(obs).get("option") or []
        index = indices[0]
        if not 0 <= index < len(options):
            return None
        option = options[index]
        return option.get("type") if isinstance(option, dict) else None

    def _belief_adjustment(self, action: str, obs: dict, threats: Set[int]) -> float:
        """Adjust a heuristic score by the sampled hidden-hand threats."""
        if not threats:
            return 0.0
        option_type = self._option_type(action, obs)
        adjustment = 0.0
        active = our_active(obs)
        fragile = False
        if isinstance(active, dict):
            try:
                fragile = float(active.get("hp", 0)) / max(1.0, float(active.get("maxHp", 1))) <= 0.5
            except (TypeError, ValueError):
                fragile = False
        if GUST_CARD_IDS & threats and fragile:
            if option_type == OPTION_RETREAT:
                adjustment += 120.0
            elif option_type in (OPTION_ATTACK, OPTION_END_TURN):
                adjustment -= 120.0
        if ENERGY_DENIAL_CARD_IDS & threats and option_type == OPTION_ATTACH:
            adjustment -= 30.0
        if HAND_DISRUPTION_CARD_IDS & threats and option_type == OPTION_PLAY:
            players = players_of(obs)
            index = your_index(obs)
            if 0 <= index < len(players):
                try:
                    hand = int((players[index] or {}).get("handCount", 0))
                    if hand <= 3:
                        adjustment += 20.0
                except (TypeError, ValueError):
                    pass
        return adjustment

    def search(self, obs: dict, legal_actions: List[str]) -> Optional[str]:
        """Return the best legal action using belief-weighted ISMCTS."""
        if not legal_actions:
            return None
        if len(legal_actions) == 1:
            return legal_actions[0]

        deadline = time.monotonic() + max(0, self.time_budget_ms) / 1000.0
        root = Node(action="root")
        for action in legal_actions:
            child = Node(action=action, parent=root, untried_actions=[action])
            root.children.append(child)

        iterations = 0
        while root.children and iterations < self.max_iterations and time.monotonic() < deadline:
            untried = [child for child in root.children if child.visits == 0]
            node = self.rng.choice(untried) if untried else max(
                root.children, key=lambda child: child.ucb1(self.exploration)
            )
            threats = self._sample_threats()
            value = self._score_action(node.action, obs, legal_actions, threats)
            node.visits += 1
            node.value += value
            iterations += 1

        visited = [child for child in root.children if child.visits > 0]
        if not visited:
            return legal_actions[0]
        best = max(
            visited,
            key=lambda child: (child.value / child.visits, child.visits, child.action),
        )
        return best.action if best.action in legal_actions else legal_actions[0]

    def _score_action(
        self,
        action: str,
        obs: dict,
        legal_actions: List[str],
        threats: Optional[Set[int]] = None,
    ) -> float:
        """Score a legal action with card semantics and sampled hand threats."""
        base = action_score(action, obs, self.belief)
        if threats:
            base += self._belief_adjustment(action, obs, threats)
        return base

    def update_belief_from_obs(self, obs: dict, prev_obs: Optional[dict] = None):
        """Sync belief to the latest arena observation.

        The tracker replaces public-zone snapshots, so this is safe to call
        repeatedly.  ``prev_obs`` is accepted for backwards compatibility.
        """
        self.belief.sync_from_obs(obs)


class BeliefWeightedHeuristic:
    """Drop-in replacement for bot.py's choose_action that uses belief state.

    Wraps ISMCTSSearch and adds belief-aware scoring.
    """

    def __init__(self, belief: BeliefTracker, time_budget_ms: int = 1000):
        self.belief = belief
        self.search = ISMCTSSearch(belief, time_budget_ms=time_budget_ms)

    def choose(self, obs: dict, legal_actions: List[str]) -> Optional[str]:
        """Choose best legal action using belief-weighted search.

        The caller owns belief updates (one per decision point); this method
        intentionally does not sync again.
        """
        if not legal_actions:
            return None
        if len(legal_actions) == 1:
            return legal_actions[0]

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
