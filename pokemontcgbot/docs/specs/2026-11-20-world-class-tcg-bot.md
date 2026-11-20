# Spec — World-Class DevFun Arena Pokémon TCG Bot

Status: proposed (review artifact). Supersedes `spec.md` and `PRD.md`, both of which
still describe the S6 Druddigon starter deck and a `obs.select.option.damage` field
that does not exist.

Owner: Colbert Low. Season under test: `[TCG] Playground S7` `cmwm3cekx011nln01c3gqi0tc`.

---

## 0. Delivery log (evidence, newest first)

| Date | Unit | Evidence |
|---|---|---|
| 2026-11-20 | **Telemetry** — `telemetry.py` records one JSON line per decision (input, choice, scored alternatives, board, latency, policy version), wired once in `bot.choose_action`; measured **0.022 ms** per record | `tests/test_telemetry.py`, full suite `116 passed, 4 skipped`; records land at `~/.arena-tcg-decisions.jsonl` |
| 2026-11-20 | **Season identity closed (§8 gap 2)** — `DECK`, `BASIC_POKEMON_IDS` and `POLICY_VERSION` exist only in `arena_config.py`; both entrypoints import them | `tests/test_arena_config.py::test_deck_is_one_object_across_entrypoints`, `::test_no_module_redeclares_the_deck` |
| 2026-11-20 | **Restart gate fixed** — `restart_when_idle.sh` carried the **S6** competition id, so its "is a match running?" probe read 0 while S7 had a live match and the restart killed it; it now reads `arena_config` | `tests/test_deploy_scripts.py::test_restart_script_reads_the_season_from_arena_config` |
| 2026-11-20 | **Deploy list fixed** — `.agent-team/sync-live.sh` did not copy `arena_config.py` or `telemetry.py`, so a sync could ship an entrypoint whose import was missing | `tests/test_deploy_scripts.py::test_sync_live_deploys_every_module` |
| 2026-11-20 | **Test/live isolation** — running the suite wrote 12 synthetic decisions into the production log; `conftest.py` now redirects `ARENA_TELEMETRY_PATH` and telemetry resolves its path at call time | `tests/test_telemetry.py::test_env_override_keeps_test_runs_out_of_the_live_log`; live log repopulated with real S7 records only |

---

## 1. Definition of "world-class" (pre-registered, no post-hoc thresholds)

Measured on the S7 board on 2026-11-20:

| Agent | W/played | WR |
|---|---|---|
| rank 1 `ujangkurap` | 502/862 | 58.2% |
| rank 4 `burkearooster` | 564/998 | 56.5% |
| rank 10 `arena_oracle` | 326/702 | 46.4% |
| median (≥50 matches) | — | 49.7% |
| **ours, rank 29/30** | **94/261** | **36.0%** |

Gates, in order. Each is evaluated only at the stated sample; a gate that cannot be
evaluated at its sample is reported `NOT_RUN`, never substituted.

- **G1 (competence):** ≥46% over n≥300 in-season matches, Wilson 95% lower bound ≥44%.
  This is the current rank-10 bar. FAIL today (36.0%, CI 30.3–42.1%).
- **G2 (contender):** ≥52% over n≥300, CI lower bound ≥49.5% (above the board median).
- **G3 (top-3):** ≥57% over n≥300, CI lower bound ≥54%.
- **G4 (leader):** ≥58% over n≥500 and rank 1–2 at sample close.
- Every gate is bound to a commit, a competition id, and a `wr_report.py --json`
  artifact path. No gate is claimed from a leaderboard delta or a sub-100 window.

---

## 2. What the arena actually gives us (verified against live obs, 2026-11-20)

Facts the design must be built on. Each was read from `GET /tcg/battle/{id}/decisions`
and the live `pending-actions` payload, not from documentation.

**Observation shape**

```
obs.current = {
  turn, turnActionCount, yourIndex, firstPlayer,
  supporterPlayed, stadiumPlayed, energyAttached, retreated, result, stadium[], looking,
  players[2] = {
    active[], bench[], benchMax, deckCount, discard[], prize[], handCount,
    hand,                       # null for BOTH players in remote mode
    poisoned, burned, asleep, paralyzed, confused
  }
}
obs.select = { type, context, minCount, maxCount, remainDamageCounter,
               remainEnergyCost, option[], deck, contextCard, effect }
```

**Hard information limits (present in every match, not a bug to route around):**

1. `players[i].hand` is `null`, including our own hand. A `type: 7` (play) option
   carries only `{type, index}` — a hand slot, with **no card identity**. Every
   trainer play is currently a blind pick; `scoring.py:246` scores them all 45.0.
2. Deck searches (`select.context: 5`) emit options like
   `{type: 3, area: 1, index: 9}` with `select.deck: null` and `looking: null` in the
   archive. Card identity must be reconstructed (see §4.3) or the search is blind.
3. The attack catalog (`GET /tcg/attacks`) gives `{attackId, name, text, damage, energies}`.
   `damage` is **printed** damage. Effect-scaled attacks report their base:
   Ear Force `1454` = 20 (+80 per energy on the opponent's Active), Psychic `339` = 10
   (+50 each), Cruel Arrow `183` = 0 (100 to a chosen target), Tenacious Tail `425` = 0
   (60 per opponent ex). Scoring printed damage as real damage is a systematic error.
4. Energy type `0` is Colorless and still costs one energy. Verified energy lines:
   all eight attackers in the current deck cost only Psychic or Colorless, so 12×
   Basic {P} (`5`) is legal — but Ear Force, Destructive Drill and Cruel Arrow all
   cost **three** energy with no acceleration except Kaleidowaltz.

**Option type codes (empirically confirmed; the API does not document them)**

| code | meaning | verified by |
|---|---|---|
| 0 | number / yes-no (`{type:0, number:0\|1}`) | coin flip, play-order choice |
| 3 | choose a card in a visible zone | search, promotion, discard pickup |
| 7 | play a card from hand | trainer play |
| 8 | attach energy from hand to in-play target | `inPlayArea` 4=active, 5=bench |
| 9 | **evolve** from hand onto in-play target | board 741→742, 305→306, 742→245 across consecutive decisions |
| 10 | use an ability (Fezandipiti *Flip the Script*, Kadabra *Psychic Draw*) | inferred from option shape; no confirmed fixture yet |
| 12 | retreat | — |
| 13 | attack (`attackId`) | — |
| 14 | end turn | — |

`scoring.py` defines 10 constants; **type 9 is not among them** and falls into the
default `10.0` branch (`scoring.py:302`), i.e. evolution is scored as "unknown".

---

## 3. Target architecture

Five layers, each independently testable, each with one owner module. Nothing
downstream may re-derive a fact an upstream layer already owns.

```
arena_config.py   single source of truth: base URL, competition id, season, deck, paths
catalog.py        cards + attacks loaded from the API; typed Card/Attack records
state.py          observation -> GameState (known, inferred, hidden)
effects.py        effect interpreter: damage, draw, search, gust, switch, recover, ramp
policy/
  pipeline.py     L0 must-do-before-attack ordering
  scoring.py      L1 card-semantics evaluation from catalog (no hand-typed tables)
  determinize.py  sample opponent hand/prizes from belief + deck model
  rollout.py      L2 one-ply / L3 PIMC-PUCT evaluation on the simulator
  choose.py       entry point: choose(obs, legal_actions) -> str
engine_adapter.py ptcg-engine bridge + card-coverage gate
telemetry.py      one JSON decision record per decision point
```

### 3.1 `arena_config.py` (blocking prerequisite)

One module exporting `BASE_URL`, `COMPETITION_ID`, `SEASON_NUMBER`, `DECK`,
`DEFAULT_STATE_PATH`. `bot.py`, `bot_async.py`, `wr_report.py` and every test import
it. Why: the season id currently exists in three files (`bot.py:38`,
`bot_async.py:48`, `wr_report.py:29`) and the state writer hardcodes
`season_number: 6` (`bot.py:430`, `bot_async.py:378`) with a Druddigon
`deck_thesis` while running the S7 Audino deck. A test asserts all three call sites
resolve to the same constant object.

### 3.2 `catalog.py`

- Loads `/tcg/cards?competitionId=` and `/tcg/attacks` once, caches to disk with the
  competition id and a content hash; refuses to start when the hash changes without
  an explicit refresh flag.
- Exposes `Card(id, name, card_type, hp, type, basic, stage, evolves_from, retreat,
  weakness, resistance, ace_spec, attacks[], abilities[])` and
  `Attack(id, name, damage, energies, text, effect)`.
- `Attack.effect` is a parsed descriptor (`damage_per_energy`, `damage_per_opp_ex`,
  `bench_snipe`, `draw_until`, `switch_self`, `confuse`, `gust`, `search`, `ramp`,
  `recover`), produced by an explicit parser with a coverage report. Unknown effect
  text is `effect=UNPARSED` and counts against a coverage gate (≤5% of deck cards).
- Deletes `ATTACK_DAMAGE`, `CARD_HP`, `BASIC_POKEMON` hand tables. They drift on every
  deck change (`tests/test_deck_viability.py:11-24` already
  records `max_damage: 100` for Mega Audino ex `1006`, whose printed attack damage is
  20).

### 3.3 `state.py`

`GameState` per match, keyed by `matchId`, rebuilt from each obs (idempotent) plus
incremental inference:

- `our_hand: dict[slot -> Optional[CardId]]` — the core new capability. Slots are
  assigned when the deck is known and draws are observed; a slot is resolved when the
  card is played (revealed in discard/log), named in a log entry, or returned by a
  search. Unresolved slots carry a probability distribution, not a guess.
- `our_deck_order_belief`, `prizes: list[Optional[CardId]]`, `opponent_public`
  (board/discard/prizes), `opponent_hand_distribution`.
- `energy_in_play`, `can_attack_next_turn(card, attack)` — requires energy cost vs
  attached count; today no layer knows an attack's cost.
- Invariant: `sync(obs)` twice yields identical state (property test).

### 3.4 `effects.py`

Interprets a parsed effect into state deltas: damage with weakness/resistance and
conditional scalers, bench snipe, draw-until, search-and-pick (with the pick chosen by
the *deck plan*, not by index), gust, switch, energy ramp, recovery, hand disruption.
Every effect used by the 60-card list gets a unit test with a real obs fixture.
Unparsed effects are a scored penalty (`-0.05` value), never a silent 0.

---

## 4. Policy stack

### 4.1 L0 — pre-attack pipeline (must ship first; ~1 day, highest measured EV)

Attacks end the turn. Everything else that does not end the turn must be evaluated
*before* the attack branch, in this order:

1. `type: 10` ability with non-negative effect (draw/ramp).
2. `type: 9` evolution available for a card that advances the plan (e.g. Dunsparce →
   Dudunsparce ex when a 3-energy body is needed; Abra → Kadabra → Alakazam).
3. `type: 8` attach energy — to the Pokémon that can actually attack next turn given
   the *catalog energy cost*, not a hardcoded 180-HP threshold (`scoring.py:351`).
4. `type: 7` play a trainer whose effect is known and useful now (search before draw,
   draw before attach, gust when it converts a prize, stadium when it taxes the
   opponent, recovery only when the discard holds the win condition).
5. `type: 13` attack — with effect-aware real damage, prize value of the target
   (1 vs 2 prizes, and "this is the 6th prize" as terminal), and a lethal check.
6. `type: 12` retreat — only when the active cannot survive the next hit and the
   bench can attack.
7. `type: 14` end turn.

Regression test built from a real archived decision: S7 match `abb9ce3b` seq 42,
turn 16 — active Dunsparce 70/70 with 1 energy, bench Abra + Dunsparce, four legal
trainer plays and two legal evolutions, opponent Active 240 HP. The bot chose
`attackId 423` (*Trading Places*, 0 damage, self-switch) and ended the turn. Expected:
evolve first, then play the useful trainer, then attack.

**Measured cost of not having this**, 10 recent S7 matches, 270 decision points:
52 attack choices, **33 of them zero-printed-damage utility attacks**, and **45 of the
52 were made while a trainer play, evolution or ability was simultaneously legal**.

### 4.2 L1 — card-semantics scoring (replace, don't extend)

- Score from `catalog` + `state`: real damage (weakness/resistance/scalers), prize
  delta, tempo (does this action let me attack this turn?), survival (opponent's best
  available KO next turn), and deck-plan progress (did I get the Stage 2 online).
- No magic constants tied to one deck (the 180-HP attach rule and the flat
  `+80` KO bonus belong in a policy configuration object with named, tested knobs).
- Tie-breaking: never resolve ties by legal-list order. `scoring.py:393` keeps the
  first legal action on ties, so server ordering decides every tie — the play-order
  choice, the starting Pokémon, and every trainer pick. Ties are broken by a seeded
  deterministic hash of `(matchId, seq, action)` so runs are reproducible and not
  index-biased, and every tie is logged.

### 4.3 L2 — determinized one-ply rollout (the actual search lever)

Per legal action: sample K=20 determinizations of the hidden state (our hand slots,
our prizes, opponent hand from belief, opponent prizes), apply the action and the
opponent's best reply from `effects.py`, evaluate the resulting `GameState` with the
L1 evaluator plus a 1-turn threat model, average. This is what `ismcts.py` claims to
be and is not: `ISMCTSSearch.search` (`ismcts.py:80-104`) is a flat argmax over
`scoring.action_score`, with `Node`/`ucb1` dead (`ismcts.py:37-54`). Either implement
rollouts or delete the module and the `heuristic="belief-ismcts"` label
(`bot.py:203`).

### 4.4 L3 — PIMC-PUCT

PUCT over determinized states, 200–800 simulations inside a 1.2 s budget, with a
value function bootstrapped from L2 outcomes. Ship only after L2 clears its gate, and
only with a measured comparison at equal latency.

### 4.5 Belief model (currently inert, must be rebuilt)

`belief.py` cannot influence play as written: `hand_probabilities()` iterates
`archetype`, which starts `{}` and is only ever filled by
`infer_archetype_from_played()` at one copy per seen card (`belief.py:358-362`), so
`remaining_copies()` returns 0 for exactly the cards the opponent has shown
(`belief.py:238-246`) and the probability for unseen cards is `1/60`-scale. A real
model needs a deck-archetype prior mined from top-10 replays (r=2–4 per staple),
public-zone subtraction, search-deck reveals, and `top_threats()` wired into gust and
retreat decisions, not only retreat (`scoring.py:270-276`).

---

## 5. Deck specification

The list is the largest single lever (gap analysis, 2026-11-18) and the current list
has concrete construction defects the tests cannot see:

- **3× Crispin (`1198`) with 12× Basic {P} only.** Crispin searches "up to 2 Basic
  Energy cards of **different types**"; a mono-energy deck caps it at one card. Three
  slots are near-dead. Fix: either a second basic energy type that the attackers can
  use, or cut Crispin for draw.
- **Zero unconditional draw supporters.** The only draw is Kadabra's ability, Audino's
  *Return* (draw to 6), Fezandipiti's *Flip the Script* (draw 3 after a KO), and Dawn.
  A 60-card list with no Professor's Research / Iono / Judge-class card cannot recover
  from a bad hand. Target: 6–8 draw supporters.
- **Three-energy attackers with one ramp card.** Ear Force, Destructive Drill and
  Cruel Arrow all need 3 energy; Kaleidowaltz is coin-flip ramp and Crispin is
  degraded. Either commit to a 2-energy attacker line or add real acceleration.
- Target composition: 15–18 Pokémon, 30–33 Trainers, 10–12 Energy, ≤1 ACE SPEC,
  every evolution line complete, every attack cost payable by the energy line.

Deck changes cannot be validated on the locked season: evaluate on `ptcg-engine`
(§6) and deploy in a new playground season or a sandbox submission, never by
mutating the live `DECK` under a locked competition.

---

## 6. Simulator parity gate (`engine_adapter.py`)

- Pin `ptcg-engine` by commit in `ab_harness/ENGINE.lock` (exists; keep).
- **Coverage gate:** before any A/B is reported, assert every card and every effect in
  the candidate deck is implemented by the pinned engine. `to_engine_lines()` raising
  `UnresolvedEngineCardError` is the designed failure; a proxy deck result is never
  quoted as arena evidence.
- **Parity gate:** replay 50 archived arena decisions through the adapter and require
  the adapter's legal-action set to match the arena's for ≥95% of decision points.
  Until this passes, the simulator may rank policies but not predict win rates.
- Self-play numbers from `self_play.py` (72.5% vs random) are never reported as arena
  strength.

---

## 7. Telemetry, evaluation, and promotion rules

`telemetry.py` writes one JSON line per decision (before 2026-11-20 the bot
logged only `match seq -> [i] : status`, which cannot be replayed offline):

```json
{"ts":0,"matchId":"","seq":0,"turn":0,"selectType":0,"context":0,"nOptions":7,
 "chosen":"[2]","chosenTypes":[7],"latencyMs":12,
 "state":{"active":{"id":305,"hp":70,"energy":1},"bench":[[741,0],[305,1]],
          "oppActive":{"id":63,"hp":240},"handCount":5,"prizes":4},
 "scores":{"attack":60.0,"play":45.0,"evolve":10.0},"policyVersion":"l0-2026-11-20"}
```

- **Offline gate:** replay harness runs the archived decision corpus through the policy
  and reports (a) illegal actions (must be 0), (b) choice deltas vs live, (c) predicted
  prize-delta improvement. A policy change ships only with a favourable delta on a held-out
  match split (train on matches 1–N/2 by `updatedAt`, evaluate on the rest).
- **Live gate:** pre-register `metric/basis/bound/sample` before the deploy
  (`decision.precommit`), restart only at `activeMatches == 0`, and evaluate with
  `wr_report.py --since <restart> --competition-id <c> --json`. A change that cannot
  beat the old rate with a CI excluding it at n≥300 is reverted, not re-tuned.
- **Attribution:** the Ruflo match record currently labels every match
  `deck_version="druddigon-v2"`, `heuristic="belief-ismcts"` (`bot.py:202-204`). Both
  are false for S7 and poison the promotion gates. Labels come from `arena_config` +
  `policyVersion`.

---

## 8. Reliability invariants (keep what works, close two gaps)

Already correct: flock single-instance lock (`bot.py:78-91`), 3 s pending timeout,
deadline-aware action budget, 409 `action_conflict` handling, per-entry try/except,
bounded action retries with `UNACKNOWLEDGED` alarm in `bot_async.post_action`.

Gaps:

1. **`bot.py` (the live service, `ExecStart=/usr/bin/python3 -u bot.py`) has no
   transport retry.** A status-0 POST prints and moves on (`bot.py:353-380`), which is
   exactly the unacknowledged-decision forfeit the async path fixed. Port
   `post_action` into the sync path or run `bot_async.py` in the unit.
2. **CLOSED 2026-11-20.** `bot.py` and `bot_async.py` each held a copy of `DECK`
   and `BASIC_POKEMON_IDS` (`bot.py:55`, `bot_async.py:59`). Both now import them
   from `arena_config`, and `test_no_module_redeclares_the_deck` fails if a second
   literal reappears.

Latency budget: p95 decision ≤ 400 ms, hard fail ≤ 1.5 s
(`tests/test_decision_latency.py` exists in the repo checkout but not in the working
copy). Restart discipline unchanged.

---

## 9. Test matrix (each item is a gate, not a suggestion)

| Area | Test | Fails today |
|---|---|---|
| L0 ordering | archived `abb9ce3b` seq 42 fixture: evolve/trainer before 0-damage attack | yes |
| L0 ordering | synthetic: ability legal + attack legal → ability chosen | yes |
| Catalog | every attackId in `DECK` has cost, damage and parsed effect; coverage ≥95% | yes (no cost model) |
| Catalog | no hand-typed HP/damage table exists (grep guard) | yes |
| Effect | Ear Force vs 3-energy Active evaluates to 260, not 20 | yes |
| Prize | last-prize KO outranks a bigger non-KO attack | yes (no prize term) |
| Tie-break | equal scores resolve deterministically and are logged | yes (list order) |
| State | `sync(obs)` twice is a no-op | yes (belief only) |
| Config | one `COMPETITION_ID`/`DECK` across entrypoints and report | yes |
| Deck | trainer ≥30, draw-supporters ≥6, every attack cost payable, Crispin legality | yes |
| Metas | `ismcts` either performs rollouts or is not imported anywhere | yes |
| Replay | 0 illegal actions over the archived corpus | unknown, untested |
| Reliability | status-0 action POST retried in the live entrypoint | yes |

---

## 10. Milestones and expected effect

| # | Deliverable | Gate | Expected |
|---|---|---|---|
| M0 | `arena_config.py`, stale state/spec/docs corrected, Ruflo labels truthful, sync-path retry | tests + grep guards | 0 WR, removes false evidence |
| M1 | `catalog.py` + `effects.py` + L0 pipeline | archived-decision replay shows ≥90% of "attack-before-develop" decisions flip | +4–8 pts (biggest single step; 45/52 attacks in the sample were development-blocking) |
| M2 | `state.py` hand/deck inference + search picks by plan | replay: search choices no longer index-ordered; 0 unmodeled trainer plays | +2–4 pts |
| M3 | Deck rebuild (draw engine, Crispin fix, energy curves) via new season/sandbox | offline A/B with engine coverage gate | +3–6 pts |
| M4 | L2 determinized 1-ply | replay delta + live pre-registered gate | +2–4 pts |
| M5 | L3 PIMC-PUCT at equal latency | beats L2 on held-out split | +1–3 pts |
| M6 | Opponent archetype priors from top-10 replays | gust/retreat accuracy on archived decisions | +1–2 pts |

Cumulative G1 (≥46%) is reachable at M1–M3; G2 requires M4. Anything beyond that is
speculation until the gates exist.

---

## 11. Anti-patterns this spec forbids

- Reporting a module name as a capability (`ismcts.py` is not search).
- Scoring printed damage as real damage; scoring unknown option types as 10.0.
- Resolving ties by legal-list order.
- Flat scores for whole action classes (all trainer plays = 45) while the highest-scoring
  class ends the turn.
- Deck-specific magic numbers (`180` HP, `+80` KO) outside a named, tested policy config.
- Claiming a win rate from a window under 100 matches, or a threshold chosen after
  seeing the number.
- Presenting engine self-play or proxy-deck results as arena evidence.
- Editing `DECK`/`COMPETITION_ID` in one of three files and calling it a fix.
