# PTCG Bot — Self-Play Lab Results (2026-11-17)

## Lab Setup
- Engine: gemelom/ptcg-engine (Python 3.12, Gym-like reset/step, seeded RNG)
- Location: /home/colb/ptcg-lab (cloned)
- Self-play harness: self_play.py
- Decks: charizard_ex vs miraidon_ex

## Baseline Results (200 games)
- **Win rate: 72.5%** (145W / 55L / 0D) — heuristic vs random
- **Speed: 10.72 games/sec** (~38,600 games/hour)
- **Loss reasons:** 187 deck_out, 13 unknown
- **No illegal actions** — all games completed normally

## Heuristic Improvements (Phase 2)
The improved heuristic (v2) uses actionType-based scoring:
1. Abilities first (USE_ABILITY_ACTION, USE_STADIUM_ACTION)
2. Bench discipline: bench basics if bench < 3
3. Search/consistency: items first (USE_ITEM_ACTION)
4. Supporters (USE_SUPPORTER_ACTION)
5. Energy attachment (ATTACH_ENERGY_ACTION)
6. Attacks: prefer last (usually biggest)
7. Evolutions (EVOLVE_POKEMON_ACTION)
8. Play remaining (PLAY_POKEMON_ACTION)
9. Fallback: PASS_TURN

## Win Rate Progression
| Version | WR vs Random | Games | Key Change |
|---------|-------------|-------|------------|
| v1 (string-based) | 47.0% | 100 | Basic heuristic |
| v2 (actionType-based) | 72.5% | 200 | Proper action type scoring |

## Key Findings
1. ActionType-based scoring is 25% better than string matching
2. 10.7 games/sec enables rapid iteration (~38K games/hour)
3. All games end by deck-out (no prizes taken) — need prize targeting
4. No illegal actions — legality guard works perfectly

## Next Steps
1. Add prize-value targeting (ex = 2 prizes, prefer ex KOs)
2. Add bench discipline check (never leave active unprotected)
3. Add energy accounting (only attack when energy sufficient)
4. Run 1000+ game batches for statistical significance
5. Implement belief state tracking for hidden info
6. Add MCTS search for complex decisions

## Comparison with Arena Baseline
- Arena (arena.ptcgtools.com): 2W-4L (33% WR) vs yopifutto/takeuchi
- Self-play (ptcg-engine): 72.5% WR vs random
- The gap is expected: arena opponents are stronger than random
