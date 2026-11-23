# M3 — deck candidate (built, tested, queued — not deployed)

Date: 2026-11-21 · Season: `[TCG] Playground S7` `cmwm3cekx011nln01c3gqi0tc` ·
Status: **candidate**. `arena_config.DECK` is unchanged, `bot.py` / `bot_async.py`
are unchanged, and nothing was submitted or restarted.

The S7 deck is locked for the 500-match window by
`docs/precommit/2026-11-21-c-baseline-500.md` rule 2: *"No policy or deck change
ships inside this window. M2 and M3 are built, tested and queued, not deployed,
until the window closes."* So this rebuild is written where it can be checked and
not played: `deck_candidate.json`, validated by `tests/test_deck_candidate.py`
against a one-shot card-pool snapshot.

**This candidate cannot be measured in this season.** Its win rate is unknown and
will stay unknown until either the window closes and a new list deploys into a new
playground season, or `ptcg-engine` parity (§6) lets the list be simulated. Every
claim below is a construction argument, not a result.

---

## 1. What the live list actually does wrong

Spec §5 names three construction defects. Each is a fact about the 60 card ids,
not a hypothesis:

| # | Defect | Evidence in the live list |
|---|---|---|
| 1 | **3× Crispin (`1198`) is near-dead** | Crispin searches "up to 2 Basic Energy cards of **different types**". The list carries 12× Basic {P} (`5`) and nothing else, so every Crispin is a one-card search. Three slots are 3 supporters of `draw 1`. |
| 2 | **Zero unconditional draw supporters** | Draw today: Kadabra's *Psychic Draw* (needs the evolution to land), Audino's *Return* (draw to 6, one card at a time on a 100 HP body), Fezandipiti's *Flip the Script* (needs a KO last turn), Dawn (searches Pokémon, does not draw). There is no Cheren / Judge / Lillie's class card. A bad opening hand is unrecoverable. |
| 3 | **Three-energy attackers with one coin-flip acceleration card** | Ear Force (`1454`), Destructive Drill (`426`) and Cruel Arrow (`183`) all cost `{C}{C}{C}`. The only acceleration is Kaleidowaltz (`1453`, "flip 3 coins… for each heads search up to 2 Basic Energy") plus the degraded Crispin. |

The pool was checked for the obvious outs before choosing a fix: the snapshot holds
**no** Professor's Research and **no** Iono (`GET /tcg/cards`, 1267 cards). The
available unconditional draw class is Cheren / Urbain (draw 3), Judge (both draw 4),
Lillie's Determination (shuffle hand, draw 6), Billy & O'Nare, Emcee's Hype, Lacey,
Naveen, Amarys, Carmine. Conditional or coin-flip draws (Harlequin, Lucian, Morty's
Conviction, Iris's Fighting Spirit, Kofu, Surge's Bargain) were rejected.

## 2. The candidate

18 Pokémon / 30 Trainers / 12 Energy = 60 · 0 ACE SPEC · 8 unconditional draw supporters.

| Count | Card | id | Role |
|---:|---|---:|---|
| 3 | Abra | 741 | evolution base |
| 3 | Kadabra | 742 | *Psychic Draw* on evolve |
| 3 | Alakazam | 245 | **plan A attacker: one {P}** |
| 3 | Dunsparce | 305 | evolution base |
| 2 | Dudunsparce ex | 306 | 270 HP; *Tenacious Tail* for one {C} |
| 2 | Fezandipiti ex | 140 | *Flip the Script* draw; 3-energy finisher |
| 2 | Mega Audino ex | 1006 | 270 HP wall; *Ear Force* finisher |
| 4 | Buddy-Buddy Poffin | 1086 | bench Abra (50 HP) / Dunsparce (70 HP) |
| 4 | Poké Pad | 1152 | fetch any non-Rule-Box Pokémon |
| 3 | Night Stretcher | 1097 | recover a Pokémon **or a Basic Energy** |
| 2 | Wondrous Patch | 1146 | **deterministic** {P} ramp from the discard pile |
| 1 | Sacred Ash | 1129 | shuffle 5 Pokémon back |
| 3 | Dawn | 1231 | fetch Basic + Stage 1 + Stage 2 in one card |
| 3 | Boss's Orders | 1182 | gust |
| 3 | Cheren | 1224 | draw 3, hand kept |
| 3 | Judge | 1213 | draw 4 + hand disruption |
| 2 | Lillie's Determination | 1227 | shuffle hand, draw 6 |
| 2 | Nighttime Mine | 1266 | taxes opposing Tera attacks; our list has no Tera |
| 12 | Basic Psychic Energy | 5 | the whole energy line |

Diff against `arena_config.DECK` — twelve cards leave, twelve arrive:

```
-3 Crispin (1198)              +3 Cheren (1224)
-3 Enhanced Hammer (1081)      +3 Judge (1213)
-3 Xerosic's Machinations      +2 Wondrous Patch (1146)  +2 Lillie's (1227)
-1 Sacred Ash (1129, 2 -> 1)
-2 Audino (554)                +1 Kadabra (742)          +1 Alakazam (245)
```

Pokémon 18 → 18, Trainers 30 → 30, Energy 12 → 12: the list is a swap at fixed
counts, not a change of shape.

### Why each change

**Crispin → Cheren (×3).** Defect 1 and 2 in one move. Crispin cannot exceed one
card in a mono-{P} list; Cheren is three cards, unconditional, and keeps the hand.
Cutting Crispin is the fix §5 sanctions ("or cut Crispin for draw").

**Enhanced Hammer → Judge (×3).** Enhanced Hammer only discards a *Special* Energy,
so against a field that runs Basic Energy it is a blank card, and it does nothing on
our own turn. Judge is never blank and hands a mid-game answer against an opponent
holding a stacked hand.

**Xerosic's Machinations, 3 → 0 (+ Lillie's ×2, Wondrous Patch ×2, Sacred Ash 2 → 1).**
Xerosic only matters when the opponent is holding 4+ cards at the moment we draw it;
its floor is a dead turn. The slots go to the two things the list lacked: an
unconditional refill (Lillie's) and real ramp (Wondrous Patch).

**Audino (554) → Kadabra +1, Alakazam +1.** Plain Audino existed for *Return*
(draw to 6 on a 100 HP body, one card per turn). That is exactly the job the draw
supporters now do better, and 100 HP is a liability in the active spot. The freed
slots go to the line that is actually plan A: Alakazam attacks for **one** {P} with
*Psychic* (`339`, 10 + 50 per Energy on the opponent's Active) and *Strange
Hacking* (confuse + move damage counters). 3-3-3 keeps the line complete and, for
once, gives the deck more copies of its Stage 2 than a coin-flip chance of drawing it.

### Why the energy line stays mono-Psychic

Every energy cost in the list is `{P}` or `{C}`, and `{C}` is payable by any energy,
so 12× Basic {P} pays for all of them:

```
Abra/Teleportation Attack [5]        Kadabra/Super Psy Bolt [5]
Alakazam/Strange Hacking [5]         Alakazam/Psychic [5]
Dunsparce/Trading Places [0]         Dunsparce/Ram [0,0]
Dudunsparce ex/Tenacious Tail [0]    Dudunsparce ex/Destructive Drill [0,0,0]
Fezandipiti ex/Cruel Arrow [0,0,0]   Mega Audino ex/Kaleidowaltz [0]
Mega Audino ex/Ear Force [0,0,0]
```

A second basic type would make Crispin live again, but it would also make the deck
depend on a supporter whose best case is "two cards", and it buys nothing the
Colorless attackers can't already do with {P}. Cutting Crispin is the cheaper fix.

### Defect 3, answered honestly

The list still carries three-cost attacks. They are now **plan B**, not the plan:

- **Plan A** is 1-energy: Alakazam's *Psychic*, and *Tenacious Tail* (`425`, 60 per
  opposing Pokémon ex, 1 energy) on a 270 HP body.
- **Plan B** is the 3-cost finisher. It is paid for by manual attach plus
  **Wondrous Patch ×2** (`Attach a Basic {P} Energy card from your discard pile to 1
  of your Benched {P} Pokémon` — no coin flip, no opponent choice) and
  **Night Stretcher ×3**, which returns a Basic Energy to hand. The deck therefore
  has five deterministic energy-return cards instead of one coin-flip search.
- This is a real improvement and **not** a full fix: 12 energy is still thin for six
  three-cost bodies, and Wondrous Patch is a recovery card (it needs energy in the
  discard pile, which usually means an attacker already died). A list that wanted
  the 3-cost line as plan A would need a dedicated ramp engine; that is a different
  archetype and was not attempted here.

### Why zero ACE SPEC

`≤1` is a ceiling, not a floor. The pool's ACE SPECs were inspected and each was
rejected for this list: Prime Catcher duplicates Boss's Orders; Scramble Switch and
Scoop Up Cyclone are reactive; Unfair Stamp needs a KO last turn; Max Rod /
Miracle Headset / Master Ball duplicate items the list already runs at four.
Enriching Energy (draw 4 on attach) was the closest fit and was cut because a
single unrecoverable special energy cannot be fetched by Night Stretcher or Pokemon
search, and its marginal value cannot be measured from here. The slot stays open
rather than being filled with an untested guess.

---

## 3. What is verified, and how

`tests/test_deck_candidate.py` (14 tests, all green):

| Claim | Test |
|---|---|
| exactly 60 cards | `test_the_candidate_is_exactly_sixty_cards` |
| ≤4 of any card, by id **and** by name, basic energy exempt | `test_copy_limits_hold`, `test_no_copy_limit_is_bypassed_by_a_second_printing` |
| ≥6 unconditional draw supporters (list has 8) | `test_at_least_six_draw_supporters` |
| Crispin is absent while the energy line is mono-type | `test_crispin_is_cut_from_a_single_type_energy_line` |
| every attack on **every** Pokémon is payable by the energy line | `test_every_attack_on_every_pokemon_is_payable_by_the_energy_line` |
| the 3-cost attacks have deterministic ramp | `test_three_energy_attacks_have_more_than_a_coin_flip_to_pay_for_them` |
| every id resolves in the pool snapshot | `test_every_candidate_id_is_in_the_pool_snapshot` |
| 15–18 Pokémon / 30–33 Trainers / 10–12 Energy / ≤1 ACE SPEC | `test_composition_is_inside_the_section_5_targets`, `test_at_most_one_ace_spec` |
| evolution lines complete and count-monotonic | `test_every_evolution_line_is_complete`, `test_stage_two_lines_have_a_stage_one_between_them` |

The snapshot (`docs/data/card_pool_snapshot.json`, 83 cards / 12 attacks) is a
bounded slice of the live pool (1267 cards / 1556 attacks) fetched once by
`scripts/build_card_pool_snapshot.py`. It keeps the candidate, the live deck, every
card the argument above names, and all basic and special energy, so each rejection
in §2 can be re-derived offline. The bound is recorded in `meta.bound`.

## 4. What could not be verified offline

Stated plainly, because none of it is covered by the tests:

1. **Win rate.** No match has been played with this list. The 500-match window is
   measuring the *locked* deck; this candidate has no sample and cannot get one
   this season. Any claim that it "fixes" the 36.0% baseline would be invention.
2. **Engine parity.** `engine_adapter.py` / `ptcg-engine` (§6) is not wired to this
   list, so there is no simulation number either — no goldfish, no matchup table,
   no proof that 12 energy draws well with 8 draw supporters.
3. **Deck-submission legality.** The arena's own deck validator was not called. All
   60 ids are in the live pool and every count is ≤4 with 12 basic energy, which is
   standard construction, but "the submission endpoint accepted it" is unverified.
4. **Supporter power ranking.** Cheren vs Judge vs Lillie's was chosen on
   unconditional-ness and floor, not on measured cards-seen-per-turn. Against an
   opponent who also dumps their hand, Judge's disruption could be worth less than
   its draw.
5. **Matchup dependence.** Nighttime Mine only taxes Tera decks; Enhanced Hammer and
   Xerosic were cut for being dead against non-special-energy / small-hand decks.
   If the S7 field turns out to be Tera- or special-energy-heavy, those cuts cost
   real equity. The field composition was not measured.
6. **Snapshot drift.** The pool is a snapshot of 2026-11-21. If the arena rotates
   cards mid-season, the snapshot (and this list) need re-fetching; the tests will
   fail loudly on any id the new snapshot drops.

## 5. Deployment path (when it is allowed)

1. Window closes at 500 settled matches; baseline is reported as found
   (`docs/precommit/2026-11-21-c-baseline-500.md`).
2. Bump `arena_config.DECK` to the candidate list, bump `DECK_VERSION` to
   `m3-audino-v1`, keep `POLICY_VERSION` (policy is unchanged — this is a list
   change only), and refresh `catalog_data.json` so `tests/test_catalog.py` sees the
   same ids the snapshot carries.
3. Deploy into a new playground season or a sandbox submission, never by mutating
   `DECK` under the locked competition.
