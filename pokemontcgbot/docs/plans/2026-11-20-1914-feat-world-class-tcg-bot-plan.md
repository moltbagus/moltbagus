---
title: World-Class DevFun TCG Bot - Plan
type: feat
date: 2026-11-20
topic: world-class-tcg-bot
artifact_contract: ce-unified-plan/v1
artifact_readiness: requirements-only
product_contract_source: ce-brainstorm
execution: code
---

# World-Class DevFun TCG Bot - Plan

## Goal Capsule

**Objective:** The S7 bot clears the rank-10 competence bar on the live S7 board and holds it over a full measurement window, with every claim bound to the commit and process that produced it.

**Product authority:** The arena leaderboard is the authority for rank; `wr_report.py` over settled S7 matches is the authority for win rate. Neither substitutes for the other.

**Open blockers:** The S7 deck is locked for the season, so deck-construction changes cannot ship without a new agent or an arena-supported deck update. The local A/B harness cannot yet load the S7 card pool.

---

## Product Contract

### Summary

Fix the live decision pipeline so it develops the board before an attack ends the turn, then measure the result against pre-registered gates that are achievable at their stated sample. Treat deck construction and offline simulation as separately gated work, not as part of the live policy fix.

### Problem Frame

The bot sits at 36.0% over 261 S7 matches, rank 29/30. The largest loss bucket is `no_active_pokemon` (54 of 167 losses, 32%). The decision layer attacks while a trainer, evolution, or ability is legal, and 47% of legal seven-card openings contain exactly one Basic when the deck runs 12 Basics. The current 46%-at-n=300 gate cannot pass its own confidence clause: at n=300 a 46% rate has a Wilson lower bound of 40.4%, below the stated 44% floor. The existing spec is a working-copy artifact, not a committed requirements plan, and the live service previously ran a module older than the measured commit.

### Requirements

**Policy correctness**

R1. Before any attack, the policy resolves every legal non-turn-ending development action: evolution, ability, and trainer play.

R2. When the bench is empty and a Basic can be played to it, the policy plays that Basic before attacking.

R3. A legal evolution is chosen before an attack. Ties between evolutions are broken by a deterministic board-value rule, not by the server's option order.

R4. Attack scoring uses real damage, including effect scaling, weakness, resistance, and prize value. A zero-printed-damage utility attack is a last resort, not a default.

**Measurement integrity**

R5. Every live measurement records the commit, process id, process start time, competition id, and the `wr_report.py --json` artifact path. A measurement whose process predates the measured commit is invalid.

R6. Win-rate gates are jointly achievable at their stated sample: G1 is ≥46% at n≥600 with a Wilson lower bound ≥42.0%; G2 is ≥52% at n≥600 with a lower bound ≥48.0%; G3 is ≥57% at n≥1100 with a lower bound ≥54.0%; G4 is ≥58% at n≥1500 with a lower bound ≥54.0% and rank ≤10.

R7. Rank and win rate are separate signals. The plan never equates a win-rate threshold with a leaderboard position.

**Deck construction**

R8. The deck carries 15–16 Basic Pokémon, so the probability of a seven-card opening with at most one Basic is at most 44%. It also carries at least two unconditional draw supporters and no card whose effect cannot function with the deck's energy types.

**Offline evaluation**

R9. The A/B harness loads the S7 deck and every attack id used by the deck, or the milestones that depend on it are explicitly marked blocked.

**Evidence integrity**

R10. Competition id, agent id, season number, and deck thesis have one source of truth. No S6 string appears in S7 evidence, labels, or state.

R11. The requirements plan is committed under `docs/plans/` in `ce-unified-plan/v1` shape. A working-copy-only spec is not the plan of record.

### Key Decisions

- **Fix the live policy before changing the deck.** The deck is locked for the season; the policy is the only live lever. Governs R1–R4.
- **Pre-register achievable gates.** G1 moves from n≥300 to n≥600 because the lower-bound clause is arithmetically impossible at n=300. Governs R6–R7.
- **Rank is a rating, not a win rate.** A 46.4% agent can sit at rank 10 while a 60.1% agent sits at rank 14. Governs R7.
- **15–16 Basics is a hard deck rule.** At 12 Basics, 57.2% of seven-card openings contain at most one Basic; at 15, 43.4%. Governs R8.
- **No world-class claim without an independent gate.** The claim requires a committed plan, a bound measurement, and a gate pass. Governs R5–R7, R11.

### Key Flows

F1. **Decision flow.**
- **Trigger:** a pending action arrives.
- **Steps:** enumerate legal options; resolve attach; resolve evolution, ability, and trainer play; only then score attacks; break ties deterministically; submit.
- **Covers R1–R4.**

F2. **Measurement flow.**
- **Trigger:** a policy change is ready to ship.
- **Steps:** commit; restart only at `activeMatches == 0`; record PID and start time; collect n settled matches; run `wr_report.py --json`; evaluate G1–G4.
- **Covers R5–R7.**

### Acceptance Examples

AE1. **Empty bench, damaging attack legal.**
- **Covers R2.**
- Given an empty bench, a playable Basic in hand, and a 20-damage attack legal, the chosen action is the play, not the attack.

AE2. **Evolution, damaging attack legal.**
- **Covers R1, R3.**
- Given a legal evolution and a 40-damage attack, the chosen action is the evolution. The attack remains legal afterward.

AE3. **No development action.**
- **Covers R1, R4.**
- Given only an attack and an end-turn option, the attack is chosen.

AE4. **Deck opening.**
- **Covers R8.**
- With 15 Basics, the probability of at most one Basic in a seven-card opening is 43.4%, below the 44% rule.

### Success Criteria

- G1: ≥46% over n≥600 settled S7 matches, Wilson lower bound ≥42.0%.
- G2: ≥52% over n≥600, lower bound ≥48.0%.
- G3: ≥57% over n≥1100, lower bound ≥54.0%.
- G4: ≥58% over n≥1500, lower bound ≥54.0%, and rank ≤10 at sample close.
- `no_active_pokemon` share of losses falls from 32% to ≤15%.
- Every reported rate names its commit, PID, process start time, and evidence path.

### Scope Boundaries

- Not building a full PTCGL engine, a transformer policy, or a self-play training loop in this plan.
- Not changing the live deck until the season lock permits it or a new agent is approved.
- Not claiming a win-rate improvement from a sub-100 window or a leaderboard delta.
- Paid entries, new agents, and hosted deploys remain owner-approved actions.

### Dependencies / Assumptions

- The arena exposes settled match records and the card/attack catalogs used by `wr_report.py`.
- The live service runs `bot_async.py` under `tcg-bot.service`.
- The S7 deck remains locked for the current season.

### Outstanding Questions

- **Resolve Before Planning:** Can the deck be updated mid-season without a new agent? If not, R8 is deferred until the next season and the live plan is R1–R7 only.
- **Deferred to Planning:** Which cards leave the deck to reach 15 Basics, and which draw supporters replace them?
- **Deferred to Planning:** Can `ab_harness` be extended to the S7 pool, or are M3/M4 blocked for this season?

### Sources / Research

- `docs/specs/2026-11-20-world-class-tcg-bot.md` — diagnostic spec and option-type table.
- `docs/brainstorms/2026-11-18-tcg-gap-analysis.md` — deck-ratio and search-lever evidence.
- Live S7 leaderboard, 2026-11-20: rank 1 58.2%, rank 10 46.4%, rank 14 60.1%, ours 36.0% at rank 29/30.
- `scoring.py`, `wr_report.py`, `belief.py`, `ismcts.py` — current decision and measurement code.
