# Specification — Pokemon TCG Bot (World-Class Target)

## 1. Purpose
A competitive Pokemon TCG agent for DevFun Arena (and future arena.ptcgtools.com) that can:
- Join and play owner-hosted (remote) seasons continuously
- Submit hosted bundles (sandbox mode) when available
- Train and evaluate locally against strong opponents
- Improve over time via scouting, self-play, and search
- Model opponent hidden information via Bayesian belief tracking

## 2. Current State (2026-11-15)
- **Arena:** [TCG] Playground S6 (cmw99opb57gssgfb7rj39a1o1), Active, Free, Remote mode
- **Agent:** sirshibaninjabot02 (cmqogaydkdghsnq1ql4t9anjt)
- **Win rate:** 34.7% (161W/464 submissions), rank 57, score -91.43
- **Form:** 10 consecutive losses
- **Deck:** Locked to Budew (30 HP) — cannot change in remote mode
- **Loss reasons:** 66% "no_active_pokemon", 34% "timeout_forfeit"

## 3. Architecture

### 3.1 Modules
| Module | File | Purpose | Status |
|---|---|---|---|
| Bot core | `bot.py` | Join, poll, act loop, deck validation | ✅ Working |
| Async bot | `bot_async.py` | httpx async I/O, deadline safety | ✅ Built, untested in matches |
| Belief tracker | `belief.py` | Bayesian opponent hand tracking | ✅ Built & tested |
| ISMCTS search | `ismcts.py` | Belief-weighted action scoring | ✅ Built & tested (heuristic only) |
| Ruflo backbone | `ruflo_tcg.py` | Self-improvement, promotion gates | ✅ Built & tested (L1) |
| Deterministic tests | `tests/` | Deck viability, latency, bench depth | ✅ 8 tests passing |
| Hosted bundle | `tcg-bundle/` | Sandbox submission (zip) | ✅ Built, not submitted (no sandbox season) |

### 3.2 Decision Flow
1. Poll pending-actions (~2s interval)
2. For each pending entry:
   a. Parse obs, yourIndex
   b. Update belief tracker from obs
   c. Generate legal actions (provided by arena)
   d. Score each action: damage (2x) + belief threat penalty + prize bonus + safety bonus
   e. Select best legal action
   f. Post action; retry on 409 arena_transaction_busy
3. On Settled/Aborted: log result, update Ruflo, continue polling

### 3.3 Deck Specification (current — locked to Budew in arena)
- 4x Budew (235) + 56x Grass Energy (1) = 60 cards
- **Weak**: 30 HP, 10 damage, no bench, no trainers

### 3.4 Deck Specification (new — for next season/bundle)
- 4x Druddigon (625): 120 HP, 0-energy Shred (40 dmg)
- 4x Pikachu ex (328): 190 HP, 0-energy Tail Whap (30 dmg)
- 4x Hop's Zacian ex (299): 230 HP, 0-energy Insta-Strike (30 dmg)
- 4x Enamorus (39): 120 HP, 0-energy Heart Sign (30 dmg)
- 4x Tauros (390): 130 HP, 0-energy Horn Attack (30 dmg)
- 40x Basic {G} Energy (1)
- Total: 60. All 0-energy attacks. Mixed HP tiers (120-230).

### 3.5 Belief State Tracking
- Hypergeometric: P(card in hand) = 1 - C(N-r, h) / C(N, h)
- Updates on: play, draw, discard, search, prize take
- Tracks: discard, board, prizes taken, hand size, deck size
- Deck inference from observed cards (when archetype unknown)

## 4. World-Class Roadmap

### Phase 0 — Foundations (DONE)
- [x] Local engine integration (arena API)
- [x] Random/heuristic agent (damage-based)
- [x] Determinism validation (8 tests)
- [x] Legal action enumeration

### Phase 1 — Local Training Loop (IN PROGRESS)
- [x] Belief state tracker (belief.py)
- [x] Self-play harness (ruflo_tcg.py match tracking)
- [ ] Feature engineering / observation encoder
- [ ] Behavior cloning from heuristic
- [ ] High-throughput self-play (target 1000s games/hour)

### Phase 2 — Stronger Decision Making (PLANNED)
- [ ] Typed heuristic scoring per selection context
- [ ] Prize trade evaluation
- [ ] Retreat decision logic
- [ ] Trainer card support (search, draw, gust)
- [ ] Energy attachment strategy
- [ ] Hidden-info determinization (mirror deck)

### Phase 3 — Search (PLANNED)
- [ ] Install ptcg-engine for local simulation
- [ ] Forward-model MCTS with opponent-as-MDP
- [ ] Gate on time budget (fall back to heuristic if < 500ms)
- [ ] Single determinization per decision

### Phase 4 — Arena Integration (PLANNED)
- [ ] Async I/O (httpx) — bot_async.py built, needs match testing
- [ ] Continuous ladder play with logging
- [ ] Deck selection / meta adaptation layer
- [ ] WebSocket client for arena.ptcgtools.com (future)

### Phase 5 — Self-Play Training (PLANNED)
- [ ] PPO self-play on ptcg-engine
- [ ] numpy-only inference export for hosted bundle
- [ ] Expert iteration (IS-MCTS distillation)
- [ ] A/B test new models vs current heuristic

### Phase 6 — Hosted Bundle (PLANNED)
- [ ] Build zip with manifest + strategy.py
- [ ] Ensure no network deps; test imports in clean env
- [ ] Submit when sandbox season available
- [ ] Monitor engine.allowance and strategyComputeMsMedian

## 5. Success Criteria

### Current (Phase 0-1)
- [x] Joins without 4xx
- [x] Completes matches without forfeit (when not timed out)
- [x] State file updated
- [x] 8 deterministic tests passing

### Target (Phase 2)
- [ ] Win rate > 50% (from 34.7%)
- [ ] 0 timeout forfeits in 20+ matches
- [ ] Fewer "no_active_pokemon" losses
- [ ] Belief tracker integrated into decision loop

### Target (Phase 3-4)
- [ ] Win rate > 60%
- [ ] MCTS activates in > 80% of decisions
- [ ] Async I/O eliminates timeout losses

### Target (Phase 5-6)
- [ ] Win rate > 70%
- [ ] Model promotes via Ruflo gates
- [ ] Hosted bundle submitted and competitive

## 6. Files

| File | Purpose |
|---|---|
| `bot.py` | Sync implementation (join, poll, act) |
| `bot_async.py` | Async implementation (httpx, deadline safety) |
| `belief.py` | Bayesian belief state tracker |
| `ismcts.py` | ISMCTS search + belief-weighted heuristic |
| `ruflo_tcg.py` | Self-improvement backbone |
| `spec.md` | This file |
| `PRD.md` | Product requirements |
| `kanban.md` | Task board |
| `research-plan.md` | Root cause analysis + 5-phase plan |
| `world-class-plan.md` | Full PTCGL Standard target plan |
| `scouting-report.md` | Top agent analysis |
| `loss-analysis.md` | 20-match loss breakdown |
| `deterministic-checks.md` | Lauren Tan principle applied |
| `tests/test_deck_viability.py` | Deck quality tests (6 tests) |
| `tests/test_decision_latency.py` | Latency tests (2 tests) |

## 7. Open Questions

1. When will a sandbox-mode TCG season open? (Need to deploy new deck)
2. Should we enter Stakes S6 (paid, 100k microUSD/entry)? Requires owner authorization.
3. Should we migrate to arena.ptcgtools.com for permanent ladder access?
4. What's the compute budget for self-play training (GPU available)?

## 8. Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-11-13 | Build minimal legal bot | Validate join/play loop |
| 2026-11-13 | Use Budew deck for validation | 0-energy, legal, simple |
| 2026-11-14 | Switch to high-HP deck | Budew too weak (30 HP) |
| 2026-11-14 | Build belief tracker | Model opponent hidden info |
| 2026-11-14 | Build Ruflo backbone | Autonomous self-improvement |
| 2026-11-14 | Build deterministic tests | Lauren Tan principle |
| 2026-11-15 | Build async bot | Fix timeout forfeits |
| 2026-11-15 | Research world-class plan | Full PTCGL Standard target |
| 2026-11-15 | Scout top agents | Understand competitive meta |
