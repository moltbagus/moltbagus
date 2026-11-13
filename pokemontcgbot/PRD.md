# PRD — Pokemon TCG Minimal Bot

## Problem
We need a working Pokemon TCG agent in DevFun Arena to validate the full owner-hosted play loop and gather real match data before investing in stronger strategies.

## Goal
Ship a minimal but legal bot that can join `[TCG] Playground S6`, play matches without forfeits, and produce decision logs for later analysis.

## User Stories
- As the owner, I can start the bot with one command and have it join the season.
- As the owner, I can see match progress and outcomes in the console.
- As the owner, I can stop the bot and resume later without losing queue position.

## Requirements
### Functional
- FR1: Read credentials from file; never expose apiKey.
- FR2: Validate 60-card deck against arena rules.
- FR3: Join idempotently.
- FR4: Poll pending actions every ~2s.
- FR5: Post exactly one legal action per decision point.
- FR6: Retry transient 409 busy.
- FR7: Persist state to `.arena-tcg-state`.
- FR8: Track opponent belief state via Bayesian belief tracker (belief.py).
- FR9: Use belief probabilities to inform action selection (heuristic weighting).

### Non-Functional
- NFR1: No uncaught exceptions during normal play.
- NFR2: Decision latency under deadline (budget 1-2s).
- NFR3: No secrets in logs/state.
- NFR4: Runs continuously in WSL.

## Starter Deck
- 4x Druddigon (625) + 4x Pikachu ex (328) + 4x Hop's Zacian ex (299) + 4x Enamorus (39) + 4x Tauros (390) + 40x Grass Energy (1).
- All 0-energy attacks (can attack turn 1), mixed HP tiers (120-230 HP), Druddigon leads with 40 damage.
- Rationale: Previous Budew deck (30 HP, 10 damage) was too weak — all 5 matches lost with "no active Pokémon". New deck has 4-8x HP and 3-4x damage per attack.

## Metrics
- Matches played / won.
- Forfeit count (target 0).
- Timeout count (target 0).
- Decision latency.

## Risks
- Deck is weak; expect losses. This is acceptable for validation.
- Remote-mode deck lock; first join is irreversible.
- Arena engine may differ from local sims.

## Milestones
- M1: Bot joins successfully.
- M2: Completes first match without forfeit.
- M3: 10+ matches logged for scouting.
- M4: Hand off to stronger heuristic (Phase 3).
- M5: Belief tracker integrated into bot (Phase 2.5).
- M6: ISMCTS search engine (Phase 4).

## Self-Improvement (Ruflo)
- Autonomy ladder L1-L4 with Bayesian promotion gates.
- Match tracking with win rate, forfeit streak, timeout streak.
- Strategy proposals with before/after win rate tracking.
- Demotion on: forfeit streak (3+), WR drop (z <= -2.0), timeout streak (5+), human override (3+).
- State persisted in SQLite (ruflo_tcg.db).

## Architecture
- bot.py: Main loop, deck validation, join, poll, act.
- belief.py: Bayesian opponent hand tracking.
- ismcts.py: Belief-weighted action scoring (heuristic + search framework).
- ruflo_tcg.py: Self-improvement backbone (autonomy, promotion, match tracking).
- All modules optional with graceful degradation (HAS_* flags).
