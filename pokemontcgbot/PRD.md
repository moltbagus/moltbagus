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

## Current state — 2026-11-23
- Live competition: `[TCG] Playground S7` (`cmwm3cekx011nln01c3gqi0tc`); deck locked for the season (18 Pokémon / 30 Trainers / 12 Psychic Energy, Audino core).
- Supervisor: pm2 service `tcg-bot`, one poller behind `~/.arena-tcg.lock`. Do not run systemd and pm2 together.
- Live policy: S7 Audino deck, post-bench-fix scoring, belief-weighted ISMCTS. No decision-affecting change has shipped since 2026-11-20 23:01 +08.
- Measured outcome: 995 S7 matches, 221 W = 22.21% (Wilson 95% CI 19.74–24.90%, p=0.473 vs 21.28% baseline). Post-2026-11-20 build: 686 matches, 108 W = 15.74% (CI 13.21–18.66%, p=0.0000 vs 36.02%). Today: 160 matches, 21 W = 13.12% (p=0.0053 vs 22.29%). This is a regression, not an improvement.
- World-class gates remain unmet. Top-3 S7 bots run ~47–59%; this bot ranks near bottom.

## New plans / backlogs
- P0: find and fix the regression introduced by the 2026-11-20 policy build using red-team replay of real losses; rollback to the last known-good commit is a candidate, not a measured result.
- P1: prepare a catalog-validated S8 deck offline; no live deck change until the season resets or the owner approves a new agent.
- P2: keep the offline v2 package (`devfun_tcg_bot/`) as reference/adapter only. It is not imported by the live loop and is not evidence of live improvement.
- P3: paid [TCG] Stakes entry, bankroll automation, and wallet/payment flows are out of scope until explicitly authorized with a loss cap.

