# TCG Bot — World-Class Brainstorm (2026-11-18)

## Context
- Current: rank 62/63, lifetime 208W–771L (21.25%), post-restart 13W–17L (43.3%, n=30).
- Deck is locked for S6: 4x Druddigon, 4x Pikachu ex, 4x Hop's Zacian ex, 4x Enamorus, 4x Tauros, 40x Grass Energy. No trainer cards.
- Code: belief tracker, greedy card-aware scorer, ISMCTS scaffolding, Ruflo self-improvement, 20 tests.
- Top bots field 2-5 bench Pokémon and trainer/search cards; 3 of the top 10 use the private `tcg-arena-bot` framework.

## Ideas

### 1. Opponent-aware one-ply rollout
Simulate our legal action, estimate opponent's best response from public board + belief hand, score net prize trade instead of raw damage.
- Effort: M
- Impact: M
- Risk: opponent model may be wrong.

### 2. Two-turn attack planner
Map attack damage/energy cost and choose the line that maximizes knockout probability over the next two turns.
- Effort: M
- Impact: M
- Risk: overlaps with `scoring.py`; incremental.

### 3. Prize-race heuristic
Prioritize actions that take a prize or deny the opponent's active, not just max damage.
- Effort: S
- Impact: H
- Risk: low; easy to unit test.

### 4. Bench/retreat policy
Prevent `no_active_pokemon` losses: promote the highest-HP bench, retreat a low-HP active when a healthy bench exists.
- Effort: S
- Impact: H
- Risk: low; known loss mode.

### 5. Local ptcg-engine policy A/B
Use the existing `self_play.py` / ptcg-engine lab to evaluate candidate policies offline at ~10 games/sec, then deploy only winners.
- Effort: L
- Impact: H
- Risk: simulator may not match arena rules/obs exactly.

### 6. New deck + new agent
Build a meta deck with trainers and 2-5 bench Pokémon; deploy via hosted bundle or new season.
- Effort: L
- Impact: Very High
- Risk: requires owner approval, possibly paid entry; remote deck is locked.

### 7. Opponent archetype model
Mine top-10 match decisions, cluster archetypes, adjust belief priors and threat weights.
- Effort: M
- Impact: M
- Risk: data volume and label noise.

## Critique
- 6 is the biggest lever but cannot be done in the current locked season without approval. Park as an escalation.
- 5 is the most credible path to "world class" because it gives repeatable policy evaluation; it is the next major investment after measurement.
- 3 and 4 are cheap, testable, and address known loss modes; they are the right next code changes.
- 1 and 2 are useful but should follow 3/4 so the scorer is not overfit before the basics are right.
- 7 is useful but secondary until the policy is stable.

## CTO decision
1. **P0 (running):** `wr_report.py` measurement tool.
2. **P1:** restart safety — never restart while `activeMatches > 0`.
3. **P2a:** prize-race + bench/retreat policy, with unit tests and replay checks.
4. **P2b:** local ptcg-engine A/B harness.
5. **P3 (ESCALATE):** new deck + new agent/sandbox deploy; requires owner approval.

## P2a acceptance
- New policy functions are unit-tested with synthetic `obs` fixtures.
- Replay of real decision JSON shows no illegal actions and a measurable preference for prize-taking lines.
- Existing 20 tests still pass.
- No live-loop restart until `activeMatches == 0`.

## check.record
- requirement: P2a policy
- commit: TBD
- environment: Python 3.12, arena S6 obs fixtures
- execution: `pytest -q` + replay script
- expected: tests pass, all actions legal, prize preference observed
- observed: TBD
- status: NOT_RUN
