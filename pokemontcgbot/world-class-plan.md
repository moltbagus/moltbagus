# Plan: World-Class Pokémon TCG Bot (Full PTCGL Standard)

## Decision: Target Format
**Full PTCGL Standard** (not Pocket). Rationale: current Standard has ~1,900+ cards, public ladder at arena.ptcgtools.com (OpenSkill ratings, replays, spectating), continuous set updates. Top bots (Sully, gunessen, Boomboomboom) compete here. Skills transfer from DevFun Arena.

## High-Level Architecture

```
[Card Database + Effects]
        ↓
[Deterministic Engine] ← source of truth (legal actions only)
        ↓
[Observation / Belief State Encoder]  (hidden info tracking)
        ↓
[Policy / Search Layer]  (heuristic → BC → PPO/Transformer → optional MCTS/rollouts)
        ↓
[Action Selector]  (returns index into legal options)
        ↓
[Client]  (WebSocket for arena, or local loop for training)
```

Server (or local engine) is always the referee. Bot only chooses among enumerated legal actions. Hidden information (opponent hand, deck order, prizes) handled via belief tracking or sampling.

## Skills to Extract from Highlighted Projects

| Project | Key Skills / Components |
|---------|------------------------|
| chongjiazhen/ptcg-engine (PTCG-Bench, Kaggle cabt) | Rule engine correctness, agent contract (obs → list[int]), observation layout, time budget handling |
| AngelFireLA/PokemonTCGP-BattleSimulator | Clean agent interface (get_action), CSV-driven card DB, high-volume deck vs deck simulation loops |
| sethkarten/tcg + PokeChamp | Lightweight C simulator ideas; LLM minimax / opponent modeling patterns |
| keeshii/ryuu-play | Full TS monorepo (server + client + sets + SimpleBot), WebSocket state sync, state sanitizer (hidden info), bot registration, ranking, SimpleBot that scores simulated outcomes |
| tcg-arena-bot / arena.ptcgtools.com | WebSocket client protocol, OpenSkill ladder awareness, continuous play, view masking, auth for rated play |
| Kaggle solutions (dipamc, ymgaq) | Token-transformer policies, PPO self-play, GBDT imitation, observation encoders, deck pooling |
| PTCG-Bench | LLM agent harness (ReAct-style) on full engine |
| deckgym-core (Rust) | Extreme simulation speed (if pivoting to Pocket) |

## Phased Build Plan

### Phase 0 — Foundations (1–2 weeks)
- Clone and run ryuu-play (or Python engine like ptcg-analyzer / PTCG-Bench) locally
- Implement random agent + simple heuristic agent (energy attachment priority, prize race awareness, attack selection)
- Validate determinism and legal-action enumeration
- For Pocket experiments: use AngelFireLA's agent pattern or deckgym-core CLI

### Phase 1 — Local Training Loop
- Build high-throughput self-play harness (target thousands of games/hour)
- Feature engineering / observation encoder (board state, energy, prize race, visible cards, belief over hidden cards)
- Collect trajectories. Start with behavior cloning from heuristic or strong baselines
- Study Kaggle-style token transformers or simple MLPs as policy head

### Phase 2 — Stronger Decision Making
- Add search: short-horizon rollouts, MCTS, or "own-turn sequencer"
- Hybrid: heuristic for forced/obvious moves + learned policy or search for complex decisions
- Optional: LLM high-level planner (PokeChamp minimax or PTCG-Bench) for strategy, fast policy for low-level
- Hidden-information tracking (belief state or determinization) — already have belief.py

### Phase 3 — Arena Integration
- Write WebSocket client matching arena.ptcgtools.com protocol (room/vs/ladder modes, participant-id + auth-token for rated)
- Server supplies legal actions; bot returns choices
- Continuous ladder play, logging, iteration on matchups
- Deck selection / meta adaptation layer (pool of decks + win-rate matrix)

### Phase 4 — Differentiation & Scaling
- Better prize-race and energy-management evaluation
- Opponent modeling or meta-adaptive deck choice
- Population-based training or league (multiple decks/agents)
- Time management under real latency/budget constraints
- Optional: Rust or C++ core for speed if Python becomes bottleneck

## Tech Stack
- **Language:** Python (AI + rapid iteration) + optional TypeScript client (ryuu-play)
- **ML:** PyTorch (or pure NumPy for deployment)
- **Simulation:** Local engine first; Rust (deckgym-core) if targeting Pocket at extreme volume
- **Deployment:** Lightweight WebSocket bot, 24/7 on arena
- **Data:** Pokémon TCG API / pokemontcg.io / TCGdex for card metadata; arena replays for real data

## Realistic Starting Path
1. Get working local engine + random/heuristic bot (ryuu-play SimpleBot or AngelFireLA agent style = fastest on-ramp)
2. Add basic evaluation function and search
3. Train policy via self-play
4. Connect to public arena and iterate against real opponents

## Current State (DevFun Arena Bot)
- **Engine:** DevFun Arena (not arena.ptcgtools.com) — same skill set transfers
- **Bot:** sirshibaninjabot02, [TCG] Playground S6
- **Win rate:** 29.2% (28W/96 submissions), rank 56
- **Modules:** bot.py (join/poll/act), belief.py (Bayesian tracker), ismcts.py (belief-weighted search), ruflo_tcg.py (self-improvement)
- **Deck:** Mixed high-HP 0-energy attackers (Druddigon, Pikachu ex, Hop's Zacian ex, Enamorus, Tauros + 40 Grass Energy)
- **Loss reasons:** 66% "no_active_pokemon", 34% "timeout_forfeit"

## Decision Points
1. **Engine choice:** DevFun Arena (current) vs arena.ptcgtools.com (permanent ladder, OpenSkill ratings). DevFun is simpler; ptcgtools has more competitive scene.
2. **Format:** Full Standard (recommended) vs Pocket (simpler rules, faster sims).
3. **Language:** Python (current) vs TypeScript (ryuu-play) vs Rust (deckgym-core for Pocket).
4. **ML approach:** Heuristic-only (current) → BC → PPO/Transformer → MCTS.

## Immediate Next Actions
1. Run new deck for 10+ matches to establish baseline
2. Analyze results vs old deck
3. If improved, proceed to async I/O (Phase B)
4. Scout top agents (t_43a9d6bc) for deck/strategy insights
5. Consider migrating to arena.ptcgtools.com for permanent ladder access