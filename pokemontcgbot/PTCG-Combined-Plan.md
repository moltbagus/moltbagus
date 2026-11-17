# PTCG Bot — Combined Plan & Status (2026-11-17)

## Arena Target
- **Primary:** arena.ptcgtools.com (open, free, OpenSkill-rated ladder, 1,907 Standard cards)
- **Secondary:** DevFun Arena [TCG] Playground S6 (remote mode, deck locked, 34.7% WR)

## Baseline
- Arena (arena.ptcgtools.com): 2W-4L (33% WR) vs dragapult-yopifutto/takeuchi
- Self-play (ptcg-engine): 47% WR (47W/53L) heuristic vs random, 6.0 games/sec
- DevFun Arena: 23.6% WR (183W/776), rank 61, locked to Budew deck

## Self-Play Lab
- Engine: gemelom/ptcg-engine (Python 3.12, Gym-like, seeded RNG)
- Location: /home/colb/ptcg-lab (cloned)
- Harness: self_play.py (100 games in ~16s)
- Decks: charizard_ex vs miraidon_ex
- Policies: random, heuristic (abilities → setup → search → energy → attack)

## Architecture
```
ptcg-bot/
├── bot/client.py       # WebSocket client (arena.ptcgtools.com)
├── bot/policy.py       # random + heuristic policies
├── decks/              # BYO deck YAMLs (dragapult-ex)
├── self_play.py        # Self-play harness (ptcg-engine)
├── self-play-results.md # Baseline results
├── PLAN.md             # Original research plan
└── .venv/              # Python 3.12 + websockets + pyyaml + loguru + rich
```

## Roadmap
### Phase 0 — Scaffolding ✅
- [x] Python client speaking wire protocol
- [x] Legality-safe random + heuristic policies
- [x] Dragapult ex deck, 6 real games, 2W-4L, no protocol errors
- [x] ptcg-engine cloned and self-play harness working (47% WR, 6 games/sec)

### Phase 1 — Instrumentation (next)
- [ ] Persist raw.jsonl per match
- [ ] eval.py: N games vs each built-in bot, win rate + reason histogram
- [ ] Card facts from pokemon-card-data (HP, is_ex, attack cost)

### Phase 2 — Real Policy (2-3 days)
- [ ] Threat model: opponent HP vs my damage → KO or not
- [ ] Prize math: ex = 2 prizes → target selection
- [ ] Bench discipline (fix NoBenchOnKo)
- [ ] Search card targets by archetype
- [ ] Energy accounting

### Phase 3 — Search (1 week)
- [ ] Determinize hidden info (sample opponent hand/prizes)
- [ ] Bounded MCTS over legal_actions
- [ ] Clock guard: <2s per decision

### Phase 4 — LLM Policy (optional)
- [ ] State → compact JSON → model picks index
- [ ] Hard 2s budget, fall back to heuristic
- [ ] Benchmark vs heuristic

### Phase 5 — Ladder Presence
- [ ] Register handle at arena.ptcgtools.com
- [ ] systemd user unit for 24/7 play
- [ ] Daily rating report

## Skills to Reuse
| Skill | Reuse |
|---|---|
| automations | daily ladder/rating report |
| secrets | arena auth token |
| polymarket-master pattern | config.yaml + strategy class + risk limits + dry-run |
| openclaw-bot-prob-trade layout | deploy/ + SKILL.md + config.yaml convention |

## Open Questions
1. Register ladder handle now or after Phase 2? → **Now** (accumulate rating data)
2. Stay on Dragapult ex or port different archetype? → **Stay** (baseline data)
3. Offline ptcg-engine lab or 6 games/min on arena? → **Offline lab** (1000s games/hour)