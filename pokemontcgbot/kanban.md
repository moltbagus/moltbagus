# TCG Bot — Kanban Board

## Backlog
- [ ] ISMCTS search engine (Phase 4) — requires game simulator
- [ ] Self-play tuning (Phase 5) — run bot vs older versions
- [ ] Hosted bundle submission (Phase 6)
- [ ] Ranked/stakes season (Phase 7) — requires owner approval
- [ ] Trainer card support in heuristic
- [ ] Retreat decision logic
- [ ] Prize trade evaluation

## In Progress
- [ ] Ruflo self-improvement integration (L1 DRY_RUN)
- [ ] Scouting task (t_43a9d6bc) — top-10 match analysis pending

## Done
- [x] Minimal legal bot (bot.py) — joins + plays
- [x] Belief state tracker (belief.py) — Bayesian opponent hand tracking
- [x] ISMCTS heuristic (ismcts.py) — belief-weighted action scoring
- [x] Ruflo self-improvement backbone (ruflo_tcg.py) — autonomy ladder + promotion gates
- [x] Spec.md — technical specification
- [x] PRD.md — product requirements
- [x] Deck v2 — mixed high-HP 0-energy attackers
- [x] Obsidian vault sync — all docs copied

## Blocked
- [ ] Top-10 scouting — awaiting worker execution of t_43a9d6bc
- [ ] Full ISMCTS — needs game simulator (ptcg-engine)

## Win Rate (2026-11-14)
- Rank: 56 / 96+ agents
- Total submissions: 96
- Wins: 28 (29.2% from agent stats)
- Sampled 50 matches: 18 wins, 32 losses (36.0%)
- Loss reasons: 33 "no_active_pokemon", 17 "timeout_forfeit"
- Total score: -25.86
- Form (last 10): W L L L L L L L L W

## Notes
- Season: [TCG] Playground S6 (cmw99opb57gssgfb7rj39a1o1)
- Agent: sirshibaninjabot02 (cmqogaydkdghsnq1ql4t9anjt)
- Credentials: /home/colb/.arena-credentials
- State: /home/colb/.hermes/state/tcgbot/
- Repo: /home/colb/Git/moltbagus/pokemontcgbot/