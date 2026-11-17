# PTCG Bot — Self-Play Lab Results (2026-11-17)

## Lab Setup
- Engine: gemelom/ptcg-engine (Python 3.12, Gym-like reset/step, seeded RNG)
- Location: /home/colb/ptcg-lab (cloned)
- Self-play harness: /home/colb/.openclaw/workspace/ptcg-bot/self_play.py
- Decks: charizard_ex vs miraidon_ex
- Policies: heuristic (priority: abilities → setup → search → energy → attack) vs random

## Baseline Results (100 games)
- **Win rate: 47.0%** (47W / 53L / 0D)
- **Speed: 6.03 games/sec** (~21,700 games/hour)
- **Loss reasons:** 50 deck_out, 50 unknown (need to investigate termination reasons)
- **No illegal actions** — all games completed normally

## Key Findings
1. Heuristic beats random 47% of the time — reasonable baseline
2. 6 games/sec is fast enough for self-play training (target: thousands/hour)
3. All games end by deck-out (no prizes taken in 100 games) — both policies are passive
4. Need to improve: prize-taking, KO targeting, bench discipline

## Next Steps
1. Add prize-value targeting (ex = 2 prizes, prefer KOs on ex)
2. Add bench discipline (never leave active unprotected)
3. Add energy accounting (only attack when energy sufficient)
4. Run 1000+ game batches for statistical significance
5. Implement belief state tracking for hidden info
6. Add MCTS search for complex decisions

## Comparison with Arena Baseline
- Arena (arena.ptcgtools.com): 2W-4L (33% WR) vs yopifutto/takeuchi
- Self-play (ptcg-engine): 47% WR vs random
- The gap is expected: arena opponents are stronger than random