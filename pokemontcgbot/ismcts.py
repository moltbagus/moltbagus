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
from scoring import action_score


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
        """Score a legal action with card/board semantics.

        Delegates to ``scoring.action_score``: the arena obs has no ``damage``
        field, attacks carry ``attackId``, and multi-card selections use
        ``[i,j]`` actions.  Belief is consulted only for defensive retreat value.
        """
        return action_score(action, obs, self.belief)

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
