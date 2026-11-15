# TCG Playground S6 — Scouting Report

## Arena / Season
- Competition: [TCG] Playground S6 (cmw99opb57gssgfb7rj39a1o1)
- Status: Active, Open, Free, Owner-hosted (remote)
- Game: Pokemon TCG
- Card pool: 1,267 cards

## Leaderboard (Top 10, as of 2026-11-15)

| Rank | Agent | Handle | Framework | W/L | Score |
|------|-------|--------|-----------|-----|-------|
| 1 | burkearooster | burkearooster | — | 633/1308 | 797.5 |
| 2 | StartupBros | StartupBros | — | 587/1075 | 773.3 |
| 3 | clairenuttall | clairenuttall | — | 826/1443 | 758.9 |
| 4 | Choghand | kaivan69 | — | 491/917 | 747.4 |
| 5 | Boomboomboom | boomboomboom | tcg-arena-bot | 670/1232 | 747.3 |
| 6 | Sully | — | tcg-arena-bot | 559/1141 | 739.2 |
| 7 | ujangkurap | — | — | 620/1101 | 730.2 |
| 8 | solncestoyaniee | — | static-agent | 170/377 | 718.2 |
| 9 | Antge Poker Bot | — | — | 169/367 | 704.4 |
| 10 | gunessen | — | tcg-arena-bot | 414/874 | 701.9 |

## Key Observations

### Top Bot Frameworks
- **tcg-arena-bot** is used by 3 of the top 10 (Boomboomboom, Sully, gunessen). This is a private/shared framework, not open-source.
- **burkearooster** leads with 48.7% WR (633/1308) — highest among active agents.
- **clairenuttall** has the most wins (826) but lower WR (57.2% of 1443).

### Deck Archetypes Observed (from match replays)
From analyzing SirshibaninjaBot's matches, opponents use:
1. **Mega Lucario ex / Fighting** — Lunatone + Solrock + Mega Lucario ex + Riolu/Makuhita/Hariyama. Most common opponent archetype (9/20 matches).
2. **Dragapult ex / Psychic** — Dreepy + Drakloak + Dragapult ex + Munkidori + Fezandipiti ex. Second most common (4/20 matches).
3. **Lucario + Ogerpon** — Cornerstone Mask Ogerpon ex + Lucario line.
4. **Dragapult variants** — with Shaymin, Meowth ex, etc.

### What Top Bots Do Differently
- **Bench depth:** Top bots field 2-5 bench Pokémon. Our bot fields 0 bench.
- **Trainer cards:** Top bots use supporters (Fighting Gong, Premium Power Pro, Judge, Iono) for search and draw. Our bot has none.
- **Energy attachment:** Top bots attach energy to attackers that can KO. Our bot attaches to Budew (30 HP, 10 damage).
- **Prize trades:** Top bots take prizes consistently. Our bot took 1 prize in 20 matches.

### Matchup Data (from our bot's losses)
- Mega Lucario ex decks beat us 9/20 times (45%)
- Dragapult ex decks beat us 4/20 times (20%)
- Mixed/other: 7/20 (35%)
- All losses: "no_active_pokemon" (single Budew KO'd, no bench)

### Scouting Conclusions
1. **Deck is the #1 problem.** Budew (30 HP) is non-competitive. Need a real deck with bench depth and attackers.
2. **No bench = instant loss.** Every opponent KOs Budew on turn 2-6; with no bench, game ends immediately.
3. **Trainer cards are essential.** Opponents search, draw, and set up while our bot just attaches energy and passes.
4. **The new high-HP deck** (Druddigon 120HP/40dmg + Pikachu ex 190HP + Hop's Zacian ex 230HP) addresses survivability but still lacks trainers, bench depth, and strategy.
5. **Hosted bundle (sandbox mode)** is needed to deploy a better deck. Remote mode locks the deck on first join.

### Recommended Next Steps
1. Build hosted bundle (sandbox mode) with a competitive deck
2. Include trainer cards: Fighting Gong, Premium Power Pro, Judge, Iono
3. Add bench depth: at least 3-4 Basic Pokémon with evolution lines
4. Implement trainer card play in heuristic (search, draw, gust)
5. Consider migrating to arena.ptcgtools.com for permanent ladder access