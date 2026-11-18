# TCG Bot — Local ptcg-engine A/B Plan (D)

## request.bind
- origin: Telegram thread 715591
- requester: Colbert Low (owner/CTO delegate)
- repo: `<repo-root>` (`pokemontcgbot/`)
- goal: Add a local, deterministic A/B harness on ptcg-engine so deck and policy changes are measured offline before any live deploy.
- acceptance: A seeded A/B run returns W/L, win rate, Wilson 95% CI, and a JSON evidence record; replaying the same seed gives identical results; the harness distinguishes a known-better policy (heuristic vs random) with CI excluding 50%.
- grants: local code, local engine, local test runs.
- paths: `ab_harness/**`, `tests/test_ab_*.py`, `docs/**`, `.agent-team/**`.
- stop_when: engine/arena rule mismatch makes the gate meaningless, or the engine cannot run at ≥ 5 games/sec.

## authority.resolve
- requester is the owner and CTO delegate.
- Local read/write, venv, and offline self-play are ALLOW.
- Live bot restart is ALLOW only when `activeMatches == 0`.
- Paid entries, hosted-bundle deploys, and season/agent changes are ESCALATE.
- Never run the live bot and a second poller; single-instance lock is mandatory.

## current state (evidence)
- Repo has `self_play.py` and `self_play_v2.py`, both hard-wired to `~/ptcg-lab/src`.
- Engine import fails: `ModuleNotFoundError: loguru`; `rich` is present.
- `self_play_v2.py` measures heuristic vs random on `charizard_ex`/`miraidon_ex`, not the arena deck.
- Audit: strategy depth 1/5, deck quality 1/5; no offline evaluation gate exists.

## scope
In scope:
- A reusable `ab_harness` package: deck conversion, policy wrappers, seeded seat-swapped runner, Wilson CI, JSON evidence.
- A smoke path: random vs random, then current heuristic vs random.
- A first real experiment: current policy vs C (prize-race + bench/retreat) once C exists.
- Integration with `.agent-team/verify.sh` as an optional check.

Out of scope:
- Training a neural policy.
- Full arena obs/engine state equivalence.
- Live deployment or paid season entry.
- Deck changes in the locked remote season.

## architecture
```
ab_harness/
  __init__.py
  deck.py        # arena card ids -> engine deck; legality checks
  policies.py    # RandomPolicy, CurrentHeuristicPolicy (wraps bot.choose_action)
  adapter.py     # engine info/obs -> the shape bot.choose_action expects
  runner.py      # seeded, seat-swapped A/B; W/L, WR, Wilson CI, JSON
  cli.py         # python -m ab_harness.cli --games ... --seed ...
tests/
  test_ab_deck.py
  test_ab_runner.py
  test_ab_adapter.py
```

## phases
### P0 — environment (small)
- Create `~/ptcg-lab/.venv` with `loguru>=0.7`, `rich>=15`.
- Pin the engine commit in `ab_harness/ENGINE.lock`.
- Smoke: import `ptcg.core.envs.PokemonTCG`, run 1 random-vs-random game.

### P1 — deck conversion (small)
- Map the arena 60-card list to the engine deck format.
- Validate 60 cards, copy limits, basic-energy exemption, at least one Basic.
- Test: current deck converts; an illegal deck is rejected.

### P2 — policy adapter (medium)
- Wrap `bot.choose_action` as an engine policy.
- Map engine legal actions to arena-style action strings and back.
- Test: adapter never returns an illegal action on 100 random states.
- If the mapping is lossy, record the exact unsupported action classes.

**P2 blocker discovered in P0 (2026-11-18):** at engine commit `92c3cc4`, the engine implements
none of the five arena Pokémon (Druddigon 625, Pikachu ex 328, Hop's Zacian ex 299, Enamorus 39,
Tauros 390) and has no Grass Energy. `ab_harness.deck.to_engine_lines()` raises
`UnresolvedEngineCardError` rather than fabricating IDs. P2 must either (a) add the arena cards to
the engine, or (b) run A/B on an explicitly chosen proxy deck via `card_map`. The A/B conclusion is
only valid for the deck actually simulated; do not present proxy-deck results as arena-deck results.

### P3 — seeded A/B runner (medium)
- CLI: `python3 -m ab_harness.cli --baseline random --candidate current --games 100 --seed 42`.
- Seat-swap every game; report W/L/D, WR, Wilson 95% CI, p-value vs 50%.
- Same seed twice => byte-identical summary (excluding timestamps).
- Write `evidence/ab-<run>.json`.
- Performance gate: ≥ 5 games/sec.

### P4 — first decision experiment (medium)
- Baseline: current policy.
- Candidate: C (prize-race + bench/retreat) once implemented.
- 500 games, seat-swapped, pre-registered seed.
- Decision rule: ship only if candidate WR > baseline WR and the 95% CI of the difference excludes 0.

### P5 — gate integration (small)
- Add an `.agent-team` check: `python3 -m ab_harness.cli --games 100 --seed 42` must pass and produce evidence.
- Do not make the A/B a live-deploy gate until P3 reproducibility passes twice.

## acceptance
- `python3 -m pytest -q` passes, including new `tests/test_ab_*.py`.
- `python3 -m ab_harness.cli --baseline random --candidate current --games 100 --seed 42` returns a JSON evidence file with W/L, WR, CI, and p-value.
- Same seed twice => same W/L/WR.
- Heuristic vs random CI excludes 50% (sanity that the harness can detect a real difference).
- No live bot process is started, stopped, or joined by the harness.

## risks
- **Engine/arena mismatch:** different card pool, rules, or obs schema. Mitigation: P1 deck legality, P2 action-mapping tests, and a known-better sanity check.
- **Hidden information:** engine may expose full state; the arena policy sees partial obs. Mitigation: adapter must hide opponent hand/deck.
- **Engine version drift:** pin the commit; record it in evidence.
- **Performance:** if <5 games/sec, reduce scope to 100-game smoke and optimize later.
- **False confidence:** a simulator win does not guarantee arena win. The live `wr_report.py` remains the final judge.

## governance / check.record
- requirement: local A/B harness
- commit: TBD
- worktree: TBD
- environment: Python 3.12, ptcg-lab venv, pinned engine
- execution: `pytest -q` + `python3 -m ab_harness.cli ...`
- expected: tests pass, seeded reproducibility, heuristic > random with CI excluding 50%
- observed: TBD
- status: NOT_RUN

## next action
Dispatch `TASK-D-AB` for P0–P1 only (environment + deck conversion + smoke). P2–P4 follow after the lead verifies the seed and evidence.
