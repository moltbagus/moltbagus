# TCG Bot Loss Analysis — 20 Recent Match Replays

**Bot:** SirshibaninjaBot (`sirshibaninjabot02`, agent `cmqogaydkdghsnq1ql4t9anjt`)
**Competition:** `cmw99opb57gssgfb7rj39a1o1`
**Source:** 20 most recent losses pulled from `/api/arena/tcg/matches` + `/api/arena/tcg/battle/{matchId}/decisions`
**All 20 losses ended with reason `no_active_pokemon`.**

## 1. Executive summary

- Every one of the 20 losses is the same failure mode at the game level: the bot's only in-play Pokémon (Budew, card 235) is knocked out and there is **no bench to promote**, so the game ends immediately.
- Observed bot Pokémon across all 20 replays: **only Budew (card 235)**. The bot never fields a bench Pokémon (`bot_final_bench` empty in all 20), so a single knockout is always fatal.
- The bot scored a prize (knocked out an opponent Pokémon) in only **1 of 20** matches (4b883248). In the other 19 it never took a prize.
- No loss was a timeout forfeit. Timeouts in this dataset only occur as **wins** (opponent forfeits). The bot's own decision latency (max gap ~14.6s) never triggered a forfeit.
- Most losses end early: 12 of 20 by turn 6 or earlier; only 3 extend past turn 10.

## 2. Opponent decks

Opponent Pokémon actually observed in play (from replay state), grouped by opponent handle.

| Opponent | Matches (n) | Key cards observed | Archetype |
|---|---|---|---|
| GTO Sage 4 | 9 | 675 Lunatone, 676 Solrock, 678 Mega Lucario ex, (333/677 Riolu, 673 Makuhita, 674 Hariyama) | Mega Lucario ex / Fighting (Lunatone–Solrock) |
| Richshrey | 4 | 121 Dragapult ex, 119 Dreepy, 120 Drakloak, 112 Munkidori, 140 Fezandipiti ex, (117 Cornerstone Mask Ogerpon ex) | Dragapult ex / Psychic (Munkidori, Fezandipiti) |
| Warden | 1 | 117 Cornerstone Mask Ogerpon ex, 673–678 Lucario line | Lucario + Ogerpon |
| Reaper | 1 | 117 Cornerstone Mask Ogerpon ex, 673–678 Lucario line | Lucario + Ogerpon |
| Bellwether | 1 | 673 Makuhita, 675 Lunatone | Lucario (partial) |
| Frostline | 1 | 112 Munkidori, 119 Dreepy, 235 Budew | Dragapult-ish + Budew |
| BBCA5100 (neon_savage) | 1 | 112 Munkidori, 119 Dreepy, 120 Drakloak, 235 Budew | Dragapult-ish + Budew |
| Neo Alpha | 1 | 119 Dreepy, 120 Drakloak, 235 Budew | Dragapult-ish + Budew |
| Samiyo | 1 | 121 Dragapult ex, 119 Dreepy, 120 Drakloak, 112 Munkidori, 140 Fezandipiti ex, 1013 Shaymin, 1071 Meowth ex | Dragapult ex variant |

Dominant opponents are **Mega Lucario ex / Fighting (9 matches)** and **Dragapult ex / Psychic (4 matches)**. The remaining 7 are mixed Lucario or Dragapult variants. Almost all opponents are running Stage-1/Stage-2 or ex attackers that comfortably out-damage a 30-HP Budew.

## 3. When the bot's Pokémon get knocked out

- The bot fields a single active Budew (30 HP) in every match and **never a bench**, so the game ends on the first knockout of that Budew.
- Loss-ending turn distribution (turn on which the final Budew is KO'd):
  - Turn 2: 1 match
  - Turn 4: 6 matches
  - Turn 6: 6 matches
  - Turn 8: 3 matches
  - Turn 10: 2 matches
  - Turn 12: 1 match
  - Turn 18: 1 match
  - Turn 32: 1 match (the only match where the bot scored a prize; 4b883248)
- 12 of 20 losses resolve by turn 6. Opponents routinely set up and attack within the first few turns; Budew's 30 HP means any attack is lethal.
- Bot prizes taken (bot knockouts of opponent Pokémon): 1 total across 20 matches. Opponent prizes taken: effectively 1 in every match (the final Budew KO; recorded prize decrease in 9 matches, unrecorded final-KO in the rest).

## 4. Timeout patterns

- **No loss in this sample is a timeout forfeit.** All 20 losses are `no_active_pokemon`.
- Timeouts in this dataset appear only as **wins** for the bot (opponent forfeits, `timeout_forfeit`).
- The bot's own action timing in losses: max gap between consecutive actions 4.0–14.6s; total match span 8s–155s. No gap exceeds ~15s, so the bot is not tripping its own deadline in these losses.
- Conclusion: timeouts are not a failure mode for this bot; they are an occasional source of free wins. The real failure mode is in-play knockout.

## 5. Opponent actions preceding bot losses

Common pre-loss sequence observed across replays:

1. Opponent benches a setup Pokémon (Lunatone/Solrock for Lucario decks; Dreepy/Drakloak for Dragapult decks) in the turns before the KO.
2. Opponent attaches energy to the active attacker (Mega Lucario ex / Dragapult ex) and attacks.
3. The attack KOs the 30-HP Budew; with no bench, the bot has no promotion and loses immediately.
4. In the 9 recorded cases, the prize decrease (opponent taking a prize) lands on turns 4–16, i.e. the KO happens after a short setup, not on turn 1.

Opponent final active at loss time is almost always the deck's main attacker: Mega Lucario ex (678) or Dragapult ex (121). The bot never disrupts this setup (no gust, no bench pressure, no prize trade) because it has no bench and no attacker that survives a hit.

## 6. Root-cause / actionable observations

- **Single-point-of-failure deck:** the bot runs effectively a one-Pokémon (Budew) deck with no bench. Any KO ends the game. This is the dominant, repeated failure mode.
- **No prize trades:** the bot took a prize in only 1/20 matches, so it is not pressuring the opponent's prize count at all.
- **Mismatch with configured deck:** `bot.py` declares a 60-card multi-attacker deck (Druddigon, Pikachu ex, Hop's Zacian ex, Enamorus, Tauros), but the observed in-play Pokémon is only Budew (235). The joined/locked deck appears to be a Budew-only starter list, not the configured one. Worth verifying which deck is actually locked for the season.
- **Timeouts are not the problem; survivability is.** Investing in bench depth and a real attacker (per the configured deck) is the highest-leverage fix; timeout handling is already adequate.