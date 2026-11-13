# Specification — Pokemon TCG Minimal Bot

## 1. Purpose
A minimal, legal, always-legal Pokemon TCG agent for DevFun Arena owner-hosted (remote) seasons. It exists to prove end-to-end play (join, poll, act, settle) before stronger strategies are added.

## 2. Scope
In scope:
- Load credentials from `/home/colb/.arena-credentials`.
- Validate and submit a 60-card deck.
- Join `[TCG] Playground S6` (`cmw99opb57gssgfb7rj39a1o1`).
- Poll pending actions and post exactly one legal action per decision point.
- Persist `.arena-tcg-state`.
- Run continuously until stopped.

Out of scope (future):
- Deck optimization, search, learning, hosted bundles, credits seasons.

## 3. Deck Specification
- 4x Druddigon (cardId 625): Basic Colorless Pokemon, 120 HP, 0-energy attack "Shred" (40 damage, ignores effects on Defending Pokemon).
- 4x Pikachu ex (cardId 328): Basic Lightning Pokemon, 190 HP, 0-energy attack "Tail Whap" (30 damage).
- 4x Hop's Zacian ex (cardId 299): Basic Metal Pokemon, 230 HP, 0-energy attack "Insta-Strike" (30 damage).
- 4x Enamorus (cardId 39): Basic Grass Pokemon, 120 HP, 0-energy attack "Heart Sign" (30 damage).
- 4x Tauros (cardId 390): Basic Colorless Pokemon, 130 HP, 0-energy attack "Horn Attack" (30 damage).
- 40x Basic {G} Energy (cardId 1).
- Total 60. Copy limits satisfied (energy exempt). At least one Basic. No ACE SPEC. No evolutions.
- Rationale: All 0-energy attacks (can attack turn 1), mixed HP tiers (120-230), higher damage than previous Budew deck. Druddigon leads with 40 damage.

## 4. Runtime Behavior
1. Validate deck locally.
2. Join via `POST /api/arena/tcg/join`.
3. Loop:
   - `GET /api/arena/tcg/pending-actions?competitionId=...`
   - If pending empty and activeMatches non-empty: opponent acting; wait 2s.
   - If pending empty and no active: re-join to keep queue; wait 2s.
   - For each pending entry: choose action, `POST /tcg/action`, retry on `arena_transaction_busy`.
4. On Settled/Aborted: log and continue polling.
5. Persist state after join.

## 5. Action Selection (minimal)
- Parse legal action strings like `[0]`.
- Score by option damage in `obs.select.option[idx]`; pick highest; tie-break first legal.
- Fallback: first legal action.
- Never send an action not in `legalActions`.

## 6. Safety
- Never hardcode or print apiKey.
- Wrap network errors; retry with backoff.
- Near deadline, still post best legal action.
- No secrets in state file or logs.

## 7. Success Criteria
- Joins without 4xx (except idempotent re-join).
- Completes at least 1 match without forfeit/timeout.
- `strategyComputeMsMedian` > 0 if hosted; decision log present.
- State file updated.

## 9. Belief State Tracker (belief.py)
- Bayesian tracker for opponent's hidden hand.
- Tracks public zones: discard, board, prizes taken.
- Hypergeometric probability: P(card in hand) = 1 - C(N-r, h) / C(N, h).
- Updates on: play, draw, discard, search, prize take.
- Provides: hand_probabilities(), top_threats(), expected_copies_in_hand(), is_likely_in_hand().
- Integration point for ISMCTS search (Phase 4).

## 10. Files
- `bot.py` — implementation.
- `belief.py` — Bayesian belief state tracker.
- `spec.md` — this file.
- `PRD.md` — product requirements.

## 11. Ruflo Self-Improvement (ruflo_tcg.py)
- Autonomy ladder: L1 (DRY_RUN) → L2 (HUMAN_APPROVE) → L3 (AUTO_KILLSWITCH) → L4 (FULL_AUTO).
- Promotion gates: Bayesian evidence (win rate, sample size, z-score thresholds).
- Demotion triggers: forfeit streak, WR drop, timeout streak, human override.
- Match tracking: records win/loss/forfeit/timeout with opponent, actions, HP, prizes.
- Strategy proposals: propose → apply → revert lifecycle with before/after win rates.
- SFL Stage 1: failure recording for self-learning.
- State: SQLite (ruflo_tcg.db) with WAL mode.

## 12. Integration Architecture
- bot.py imports belief, ismcts, ruflo_tcg (all optional with HAS_* flags).
- choose_action() tries belief-weighted heuristic first, falls back to damage heuristic.
- play_loop() passes ruflo instance for match tracking.
- main() initializes all subsystems with graceful degradation.
