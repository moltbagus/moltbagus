"""Offline v2 policy facade.

Re-exports the self-contained offline helpers so the earlier guardrail/scorer
check has a single import surface. NOT wired into bot_async.py.
"""
from devfun_tcg_bot.tracker import CardTracker, OpponentLedger
from devfun_tcg_bot.engine import (
    NESTED_PROMPTS,
    check_mandatory_guardrails,
    compute_net_damage,
    evaluate_board_state,
    get_prize_value,
    resolve_sub_prompt,
    run_expectimax_search,
    simulate_action_lightweight,
    simulate_opponent_counter,
)


def prune_dominated_actions(obs, legal_actions):
    """Placeholder kept for API compatibility with the v1 spec."""
    return list(legal_actions)


def score_action(action, obs, tracker=None, belief=None):
    """Placeholder kept for API compatibility with the v1 spec."""
    return 0.0


__all__ = [
    "CardTracker", "OpponentLedger", "NESTED_PROMPTS",
    "check_mandatory_guardrails", "compute_net_damage", "evaluate_board_state",
    "get_prize_value", "resolve_sub_prompt", "run_expectimax_search",
    "simulate_action_lightweight", "simulate_opponent_counter",
    "prune_dominated_actions", "score_action",
]
