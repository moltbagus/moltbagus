# TCG Bot — Gap Analysis and Brainstorm (2026-11-18)

## Question
Why is the bot not world-class, given it is reliable, tested, and measured?

## Evidence
- Leaderboard: rank 1 is 1,333W/2,457M = **54.3%**; our bot is **29.3%** over 140 post-restart matches.
- Our deck: **20 Pokémon / 0 Trainers / 40 Energy** (4x Druddigon, 4x Pikachu ex, 4x Hop's Zacian ex, 4x Enamorus, 4x Tauros, 40x Grass).
- Competitive deck guidance: roughly **15 Pokémon / 33–35 Trainers / 10–12 Energy** (Card Chill, Kraken the Meta, 2025-2026).
- Top replays show trainers doing the work: Poké Pad, Buddy-Buddy Poffin, Night Stretcher, Boss's Orders, Dawn, Sacred Ash, Xerosic's Machinations, Enhanced Hammer, Crispin, Nighttime Mine.
- AI TCG research: search is the largest measured lever. At fixed weights, argmax 0.425 → 1-ply 0.688 → PIMC-PUCT 48 sims 0.912 (BlackMind Alphamon). Kaggle agents use determinized MCTS + value net, or imitation + search.
- Deck pivots matter: one agent went from 600 to 948 TrueSkill after four deck pivots (pokemon-tcg-ai-battle).

## Why the gaps exist
1. **Deck construction is the primary gap.** 40 Energy and 0 Trainers means no draw, search, switching, gusting, or recovery. The bot is playing a draft deck against constructed decks.
2. **Deck lock timing.** Remote mode locks the deck on first join. We locked a starter deck before optimizing, so code changes cannot fix the deck.
3. **Greedy policy.** `scoring.py` picks max damage/KO; it does not search or plan two turns ahead. Research says search, not a better greedy score, is the big lever.
4. **No trainer-action model.** Even with trainers, `choose_action` would need typed handling for search/draw/switch/gust/recovery.
5. **No offline deck/policy evaluation.** `self_play.py` exists but is not the gate for live changes, so we cannot cheaply compare decks or policies.
6. **Opponent model is passive.** Belief tracking exists but is not used inside rollouts.

## Options
### A. New deck + new agent (highest impact)
Build a 15/35/10 list from top replays, evaluate offline, deploy in a new season or sandbox.
- Effort: L
- Impact: Very High
- Risk: requires owner approval; remote deck is locked; may need paid entry.

### B. 1-ply / PIMC search on the current deck
Add determinized lookahead over legal actions and score the resulting board.
- Effort: M–L
- Impact: High
- Risk: needs a simulator or reliable transition model; current deck still weak.

### C. Prize-race + bench/retreat policy
Prioritize prizes and prevent `no_active_pokemon` losses.
- Effort: S
- Impact: Medium
- Risk: low; testable now.

### D. Local ptcg-engine A/B for decks and policies
Use the self-play lab as the gate for every change.
- Effort: L
- Impact: High (confidence)
- Risk: simulator/arena mismatch.

### E. Opponent archetype model
Mine top replays, cluster decks, adjust belief priors and threat weights.
- Effort: M
- Impact: Medium
- Risk: data volume; label noise.

## Critique
- C is the best immediate code change; it addresses 26 `no_active_pokemon` losses.
- B helps but is capped by the deck; search cannot find trainers that are not in the deck.
- A is the only path to top-10 win rates; it must be approved and tested offline first.
- D is the enabling investment that makes A and B safe.
- E is secondary until the policy is stable.

## CTO recommendation
1. Ship C now (prize-race + bench/retreat) on the locked deck.
2. Build D (offline A/B) in parallel.
3. Prepare A (new deck + new agent) as an ESCALATE proposal with an offline win-rate estimate.
4. Add B after D, not before.

## Sources
- https://cardchill.com/article/pokemon-tcg-deck-building-strategies-for-competitive-play-in-2025
- https://krakenthemeta.com/blog/how-to-build-a-pokemon-tcg-deck/
- https://blackmind.org/research/alphamon/
- https://github.com/henriquetakahiroito/pokemon-tcg-ai-battle
- https://arena.dev.fun/tcg-playground
