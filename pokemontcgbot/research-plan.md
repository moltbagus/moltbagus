# Plan: Fix Pokemon TCG Bot Losing Streak

## Problem Statement

The Pokemon TCG bot (SirshibaninjaBot) is losing 71% of matches (28W/96 submissions = 29.2% win rate, rank 56). Sampled 50 matches show 18 wins, 32 losses (36.0%). Loss reasons are split:

- **66% "no_active_pokemon"** — bot's Pokémon get knocked out and it has no backup on bench
- **34% "timeout_forfeit"** — decision loop too slow, misses deadline

The original Budew deck (30 HP, 10 damage) was extremely weak. A new high-HP deck (Druddigon 120HP/40dmg, Pikachu ex 190HP, Hop's Zacian ex 230HP, Enamorus 120HP, Tauros 130HP) has been built and joined successfully but not yet tested in matches. The bot's heuristic only scores by damage and cannot play trainer cards, attach energy, evolve, or retreat.

## Root Cause Analysis

### RC1: Deck Too Weak (66% of losses)
- Original Budew deck: 30 HP, 10 damage — knocked out in 1 hit by 40-damage attacks
- New high-HP deck addresses this but hasn't been tested in matches yet
- Opponent decks are optimized: fighting types (Makuhita 80HP, Riolu) with trainers (Fighting Gong, Premium Power Pro, Judge)
- Bot has no trainer cards, no evolution, no strategic depth

### RC2: Decision Loop Too Slow (34% of losses)
- Bot polls every 2s, but opponent turns take 30-60s with complex setups
- When bot's turn comes, it has ~1-2s deadline but may be mid-poll
- No async I/O — synchronous urllib blocks the event loop
- No deadline safety beyond simple skip

### RC3: Heuristic Too Simple
- Only scores legal actions by `obs.select.option[idx].damage`
- Cannot evaluate: retreat value, prize trades, trainer card plays, energy attachment
- Cannot use belief tracker (built but not integrated into decision loop)
- No search — just greedy damage maximization

### RC4: No Self-Play or Training
- Bot has never been tested against itself
- No evaluation of deck matchups
- Ruflo self-improvement is at L1 (DRY_RUN) — no promotions possible yet

## Research Findings

### From Match Replay (Match 5: vs Warden)
- Bot: Budew (30 HP), 6 cards in hand, 6 prizes
- Opponent: Makuhita (80 HP), benched Riolu, 8 cards in hand
- Turn 1: Bot attached energy, ended turn (no attack possible — Budew needs 0 energy but 10 damage insufficient)
- Turn 2: Opponent played Riolu, attached energy, played Fighting Gong (searched deck), played Solrock, played Premium Power Pro, played Judge, played Riolu, played Lunatone, Makuhita used Corkscrew Punch (40 damage → Budew KO)
- **Key insight**: Opponent had 8-card hand with full setup; bot had no trainers to match

### From Arena Skill References
- Belief tracking must update on every observed action
- Minimal bot heuristic only works with 0-energy attack decks
- Remote-mode deck is locked on first join — treat smoke-test join as real commitment
- 409 on /tcg/action is terminal for that seq; re-poll instead of fighting it

### From Top Bot Frameworks
1. **ronniepiku/pokemon-tcg-ai-battle-agent** — robust-first, strong-second. Typed heuristic scoring of every legal option. Layered fallbacks: parse → safety valve → search → heuristic → minimal legal answer. Forward-model MCTS with opponent-as-MDP.
2. **jibai-devs/pkm** — PPO self-play + expert iteration. numpy-only inference for hosted bundle.
3. **TomatoCream/pkm-cabt-ppo** — Pretrained pointer policy (0.5M params) for bootstrap.
4. **gemelom/ptcg-engine** — Local deterministic sim for training/tests.

## Implementation Plan

### Phase A: Validate New Deck (Immediate)
**Goal:** Test the high-HP deck in real matches to confirm improvement.

1. Run `python3 bot.py` with new deck (already joined)
2. Collect 10+ matches
3. Analyze win rate improvement vs old deck
4. Record results in Ruflo

**Success criteria:** WR > 40% (up from 29.2%), fewer "no_active_pokemon" losses

### Phase B: Fix Timeout Losses (1-2 days)
**Goal:** Eliminate "timeout_forfeit" losses.

1. Convert bot.py to async I/O (httpx or aiohttp)
2. Add deadline-aware polling with adaptive intervals
3. Pre-compute action selection during opponent's turn
4. Add watchdog timer to force-post near deadline

**Success criteria:** 0 timeout forfeits in 20+ matches

### Phase C: Improve Heuristic (2-3 days)
**Goal:** Make action selection smarter than "highest damage."

1. Integrate belief tracker into choose_action() (already built, needs wiring)
2. Add typed scoring per selection context:
   - Attack selection: prefer KOs, prize trades
   - Retreat decision: retreat when active HP < 60% and bench has healthy backup
   - Trainer play: prefer draw/search supporters when hand is small
   - Energy attachment: attach to Pokémon that can attack next turn
3. Add safety valves: always post legal action before deadline

**Success criteria:** WR > 50%, fewer "no_active_pokemon" losses

### Phase D: Add Search (1-2 weeks)
**Goal:** Look ahead 1-2 turns.

1. Install ptcg-engine for local simulation
2. Implement forward-model MCTS with opponent-as-MDP
3. Gate search on time budget (fall back to heuristic if <500ms)
4. Hidden info determinization (mirror our deck) sampled once per decision

**Success criteria:** WR > 60%, MCTS activates in >80% of decisions

### Phase E: Self-Play Training (2-4 weeks)
**Goal:** Learn from experience.

1. Implement PPO self-play on ptcg-engine
2. Export numpy-only inference for hosted bundle
3. Expert iteration (IS-MCTS distillation)
4. A/B test new models vs current heuristic

**Success criteria:** WR > 70%, model promotes via Ruflo gates

## Decision Points

1. **Should we join the season now with the new deck?** The deck is already locked (joined during testing). We can't change it. This is the validation deck.
2. **Should we build a hosted bundle?** Only after Phase C is complete and we have a strong heuristic. Hosted bundles allow deck changes.
3. **Should we scout top agents first?** Yes — scouting task t_43a9d6bc is queued. Results will inform deck and strategy choices.

## Risk Assessment

| Risk | Mitigation |
|---|---|
| New deck still weak | Scouting will reveal top archetypes; build hosted bundle with better deck |
| Async conversion breaks bot | Keep sync version as fallback; test in practice matches |
| MCTS too slow for 2s deadline | Gate on time budget; fall back to heuristic |
| Ruflo promotion gates too strict | Start at L1, manually promote to L2 after validation |

## Immediate Next Actions

1. Run bot with new deck for 10+ matches to establish baseline
2. Analyze results: compare "no_active_pokemon" rate vs old deck
3. If improved, proceed to Phase B (async I/O)
4. If not improved, investigate deck matchup issues via scouting