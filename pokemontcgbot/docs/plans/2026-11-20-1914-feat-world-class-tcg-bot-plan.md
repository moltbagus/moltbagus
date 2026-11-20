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

**Objective:** The S7 bot clears gate G1 on the live S7 board and holds it over the stated sample, with every claim bound to the commit and process that produced it.

**Product authority:** The arena leaderboard is the authority for rank; `wr_report.py` over settled S7 matches is the authority for win rate. Neither substitutes for the other.

**Open blockers:** The S7 deck is locked (`executionMode: remote`), so deck-construction changes ship in S8 at the earliest. The local A/B harness cannot yet load the S7 card pool.

---

## Product Contract

### Summary

Fix the live decision pipeline so it develops the board before an attack ends the turn, then measure the result against pre-registered gates that are achievable at their stated sample. Treat deck construction and offline simulation as separately gated work, not as part of the live policy fix.

### Problem Frame

The bot sits at 36.0% over 261 S7 matches, rank 29/30. Across 282 S7 records, losses split **125 `all_prizes_taken` (69.4%)** and **55 `no_active_pokemon` (30.6%)**. The policy fix targets the minority bucket because it is the cheap live lever: the decision layer attacks while a trainer, evolution, or ability is legal, and 57.2% of seven-card openings contain at most one Basic when the deck runs 12 Basics. The prize race is the larger bucket, but it is a deck-and-attacker problem (three `ex`/Mega-ex Pokémon) and the deck is locked this season; this plan does not claim to solve it. The earlier 46%-at-n=300 gate could not pass its own confidence clause: at n=300 a 46% rate has a Wilson lower bound of 40.4%, below the stated 44% floor.

### Requirements

**Policy correctness**

R1. Before an attack, the policy resolves legal evolution and ability actions. It plays a card when the bench is empty or the best attack does zero printed damage; otherwise it attacks. It does not blindly play every legal Trainer.

R2. When the bench is empty and a Basic can be played to it, the policy plays that Basic before attacking.

R3. A legal evolution is chosen before an attack. When multiple evolutions are legal, the tie-break is deferred: the remote hand gives no card identity.

R4. Attack scoring uses real damage, including effect scaling, weakness, resistance, and prize value. A zero-printed-damage utility attack is a last resort, not a default.

**Measurement integrity**

R5. `wr_report.py --json` embeds the commit, process id, process start time, and competition id, so the evidence file itself proves the measurement's binding.

R5a. A measurement whose process predates the measured commit is invalid and is not quoted as a result.

R6. Win-rate gates have real slack at their stated sample: G1 is ≥46% at n≥900 with a Wilson lower bound ≥42.5%; G2 is ≥52% at n≥900 with a lower bound ≥48.5%; G3 is ≥57% at n≥1200 with a lower bound ≥54.0%; G4 is ≥58% at n≥1500 with a lower bound ≥55.0% and rank ≤10.

R7. Rank and win rate are separate signals. The plan never equates a win-rate threshold with a leaderboard position.

**Evidence integrity**

R10. Competition id, agent id, season number, and deck thesis have one source of truth. No S6 string appears in S7 evidence, labels, or state.

R11. The requirements plan is committed under `docs/plans/` in `ce-unified-plan/v1` shape. A working-copy-only spec is not the plan of record.

### Key Decisions

- **Fix the live policy before changing the deck.** The deck is locked for the season; the policy is the only live lever. Governs R1–R4.
- **Pre-register gates with slack.** G1/G2 move to n≥900 so the lower-bound clause is not a restatement of the point estimate. Governs R6–R7.
- **Rank is a rating, not a win rate.** A 44.6% agent can sit at rank 10 while a 60.1% agent sits at rank 14. Governs R7.
- **No world-class claim without an independent gate.** The claim requires a committed plan, a bound measurement, and a gate pass. Governs R5–R7, R11.

<!-- ce-section: work-relationships -->
### How This Work Fits Together

This plan owns the live policy and measurement slice. The deck rebuild and offline harness are related but not active scope.

- **Current slice:** R1–R7, R10–R11.
- **Deferred to S8:** deck rebuild to 15–16 Basics, draw supporters, and removal of dead cards. The S7 deck is locked.
- **Blocked:** A/B harness cannot load the S7 card pool, so local simulation cannot gate the deck change yet.
- **Still to decide:** the evolution tie-break and the real-damage model.

### Key Flows

F1. **Decision flow.**
- **Trigger:** a pending action arrives.
- **Steps:** enumerate legal options; resolve attach; resolve evolution and ability; play a card only when the bench is empty or the attack does zero damage; otherwise score and attack; submit.
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

AE4. **Non-empty bench, damaging attack legal.**
- **Covers R1.**
- Given a non-empty bench and a 20-damage attack, the chosen action is the attack, not a blind Trainer play.

### Success Criteria

- G1: ≥46% over n≥900 settled S7 matches, Wilson lower bound ≥42.5%.
- G2: ≥52% over n≥900, lower bound ≥48.5%.
- G3: ≥57% over n≥1200, lower bound ≥54.0%.
- G4: ≥58% over n≥1500, lower bound ≥55.0%, and rank ≤10 at sample close.
- `no_active_pokemon` share of losses falls from 30.6% to ≤15%.
- Every reported rate names its commit, PID, process start time, and evidence path.

### Scope Boundaries

- Not building a full PTCGL engine, a transformer policy, or a self-play training loop in this plan.
- **Deferred to S8:** deck rebuild to 15–16 Basics, draw supporters, and removal of dead cards. The S7 deck is locked (`executionMode: remote`).
- **Blocked:** the A/B harness cannot load the S7 card pool; local simulation cannot gate the deck change yet.
- Not claiming a win-rate improvement from a sub-100 window or a leaderboard delta.
- Paid entries, new agents, and hosted deploys remain owner-approved actions.

### Dependencies / Assumptions

- The arena exposes settled match records and the card/attack catalogs used by `wr_report.py`.
- The live service runs `bot_async.py` under `tcg-bot.service`.
- The S7 deck remains locked for the current season.

### Outstanding Questions

- **Deferred to Planning:** Which cards leave the deck to reach 15 Basics, and which draw supporters replace them? This is S8 work; the S7 deck is locked.
- **Deferred to Planning:** Can `ab_harness` be extended to the S7 pool, or are the simulation milestones blocked for this season?
- **Deferred to Planning:** The evolution tie-break and the real-damage model need implementation; neither is claimed as shipped.

### Sources / Research

- `docs/specs/2026-11-20-world-class-tcg-bot.md` — diagnostic spec and option-type table.
- `docs/brainstorms/2026-11-18-tcg-gap-analysis.md` — deck-ratio and search-lever evidence.
- Live S7 leaderboard, 2026-11-20: rank 1 57.3%, rank 10 44.6%, rank 14 59.6%, ours 36.0% at rank 29/30.
- 282 S7 match records: 125 `all_prizes_taken`, 55 `no_active_pokemon`.
- `scoring.py`, `wr_report.py`, `belief.py`, `ismcts.py` — current decision and measurement code.
