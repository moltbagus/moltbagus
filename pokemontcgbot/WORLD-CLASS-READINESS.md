# World-Class Readiness Audit — Pokémon TCG Bot (DevFun Arena S6)

**Audit date:** 2026-11-18
**Subject:** `pokemontcgbot` — agent `SirshibaninjaBot` (`cmqogaydkdghsnq1ql4t9anjt`), competition `cmw99opb57gssgfb7rj39a1o1` (`[TCG] Playground S6`)
**Mode:** read-only. No code changed, no bot started/stopped. `python3 -m pytest` and `wr_report.py` were executed; live match data was read through the public arena API with the existing credentials.

---

## Post-audit actions (2026-11-18 10:50 +08)

- Duplicate `bot_async.py` (PID 2542499) was killed; only `tcg-bot.service` (`bot.py`, PID 3916820) remains.
- An `fcntl` single-instance lock was added to `bot.py` and `bot_async.py`, with `tests/test_single_instance.py`.
- `tests/test_basic.py` was deleted; plain `python3 -m pytest -q` now runs the full suite (62 passed).
- `.agent-team/config.json` now runs the full suite instead of a hand-picked subset.

These close gaps #1 and #5. The remaining findings — deck, search, belief prior, telemetry, Ruflo loop, log timestamps, docs — still stand.

---

## Verdict

**Not world-class. This is a working hobby-grade bot operating in the bottom decile of the field.**

It is legal, it runs, it does not crash, and its measurement tooling is better than most hobby bots — but its win rate is **29% post-fix (21.7% lifetime)** against top-10 agents at **40–60%+**, its "search" engine is a one-ply greedy argmax that uses **0.008% of its declared thinking budget**, its deck runs **zero trainer cards**, and **two bot processes are currently racing on the same agent seat**, corrupting roughly a third of action submissions.

| Dimension | Score | One-line justification |
|---|---|---|
| Correctness | **2 / 5** | 62 tests pass, but the default `pytest` invocation fails at collection; belief model is seeded with our own deck; duplicate control paths drift. |
| Reliability | **2 / 5** | Excellent HTTP hardening (0 unacknowledged posts in 2,390), fatally undermined by two concurrent processes and no supervisor. |
| Measurement | **3.5 / 5** | `wr_report.py` is genuinely strong (Wilson CI, binomial test, evidence JSON). State counters are dead; no per-decision telemetry. |
| Strategy depth | **1 / 5** | "ISMCTS" is a static one-ply argmax; dead MCTS scaffolding; no opponent model, no prize-race, no energy plan. |
| Deck quality | **1 / 5** | 20 basics + 40 basic energy + 0 trainers. No draw, search, gust, or switch. |
| Maintainability | **2 / 5** | Reasonable module split, 62% coverage, but duplicated sync/async loops, a dead test file, dead classes, and stale docs. |
| Governance | **2.5 / 5** | Strong written governance and an agent-team scaffold, undermined by a canonical test command that hides a broken test and findings that reference deleted files. |
| **Overall** | **≈ 2.0 / 5** | |

---

## 1. Correctness — 2/5

### What holds
- Deck validation is real: 60 cards, copy limits, basic-energy exemption, at least one Basic.
- `error_code()` handles both arena error shapes (`{"error": {"code": …}}` and `{"error": "action_conflict"}`), which is the exact payload that previously crashed the loop. Covered by tests.
- `match_result_from_api` correctly normalises `win/loss/forfeit/timeout` and maps `timeout`/`deadline` in `result.reason`.
- Live evidence: **0 tracebacks**, **0 `UNACKNOWLEDGED`**, **0 `pending entry failed`** across 2,390 action posts.

### What fails
1. **The default test command is broken.** `python3 -m pytest` aborts on collection:
   `ModuleNotFoundError: No module named 'bot.client'; 'bot' is not a package` (`tests/test_basic.py:7`).
   The module it imports was deleted with the old engine era. Only `--ignore=tests/test_basic.py` yields green (62 passed).
2. **The belief model is seeded with our own deck.** `bot.py:371` builds the archetype as `{625:4, 328:4, 299:4, 39:4, 390:4, 1:40}` — our list — and passes it as `opponent_archetype` to `create_belief_tracker`. Every "probability the opponent holds card X" is therefore computed from our own composition. The tracker then adds opponent cards it observes on top, so priors and evidence are mixed.
3. **Belief inference mutates the prior.** `belief.py:337` decrements `self.archetype[searched_card]` inside `update_on_search`, permanently corrupting the deck prior. (Currently unreachable — the method is never called — but it is a trap for the next author.)
4. **Two control paths, quietly diverging.** `bot.py` and `bot_async.py` each implement `error_code`, `validate_deck`, `join`, `feed_ruflo_results`, and a full `play_loop` (~250 duplicated lines). The sync retry path sleeps and re-posts once without checking the deadline; the async path has a bounded budget. Only the async path is exercised in production, so the sync path rots untested at 34% file coverage.
5. **State counters are written as constants.** `_write_state` sets `matches_played: 0`, `matches_won: 0`, `decisions_answered: 0`, `forfeits: 0` and **nothing ever increments them**. `grep` finds no other writer. The persisted state is decorative.
6. **Scoring cannot see hand contents.** In remote play `players[i].hand` is `null`; `_option_card_id` resolves via `area: 2, index: N` into that null list and returns `None`. Every PLAY and ATTACH option therefore scores flat (`45.0` / `25.0`) regardless of which card it is. The code does not acknowledge this limitation — `scoring.py`'s docstring claims card-aware scoring.

---

## 2. Reliability — 2/5

### What holds (this is the strongest engineering in the repo)
Measured over the current `bot_async.log` (≈5 h):

| Signal | Observed |
|---|---|
| Action POSTs | 2,390 |
| HTTP 200 | 2,389 |
| HTTP 409 | 1 (`match_closed`, handled, attempt 1) |
| Transport failures (`UNACKNOWLEDGED`) | **0** |
| Unhandled exceptions | **0** |
| Poll timeouts (`pending-actions error 0: timeout`) | 19 (~0.4% of polls, retried next cycle) |

`post_action` implements a bounded retry budget (4 attempts, 15 s wall clock), retries transport/408/429/5xx and `arena_transaction_busy`, and deliberately does **not** retry `action_conflict`. Per-request timeouts are separate constants (3 s poll / 5 s join / 5 s results) so a slow poll cannot eat an action deadline, and the action timeout shrinks to fit the remaining deadline. That is competent production I/O.

### What fails
1. **Two processes are playing the same seat right now.**

```
PID 2542499  Wed Nov 18 02:28  python3 -u bot_async.py
PID 3916820  Wed Nov 18 09:39  /usr/bin/python3 -u bot.py
```

   Both logs are live and both are answering **the same match IDs** (`2db6cacb`, `3de50acc`, `77921f02`, `b9777f3e`). In `bot.log`, **439 of 1,420 action posts (31%)** returned `{"idempotent": true}` — the server deduplicating a submission the other process had already made. Consequences:
   - the action actually played is whichever process wins the race, so behaviour is nondeterministic and any A/B experiment is confounded;
   - forfeit/`action_conflict` paths fire constantly;
   - CPU, queue slots and join quota are doubled (1,728 `join -> 200` calls in the async log alone).
2. **No supervisor.** `systemctl is-active tcg-bot` → inactive; no unit file exists. The bot runs under `nohup` via `restart_when_idle.sh`, which only manages `python3 -u bot.py` — that is *how* the second process was born: the script restarts the sync bot while the async bot keeps running. A crash means no restart until a human notices.
3. **`SystemExit` on transient join failure.** `bot_async.py:353` raises and exits on any non-2xx/409 join. A 500 during a deploy takes the bot down permanently.
4. **No log timestamps.** Neither log line carries a timestamp (verified), so latency, duration, and sequence anomalies cannot be reconstructed after the fact. `grep`-based forensics is the only option, which is what this audit had to do.

---

## 3. Measurement — 3.5/5

### What holds — the one genuinely world-class component
`wr_report.py` (553 lines, 77% covered, 240 lines of tests) does the statistics correctly:
- counts caller outcomes in an explicit window, with timezone-correct rendering (Asia/Shanghai);
- **Wilson 95% CI** rather than a naive proportion;
- **two-sided binomial p-value** against a supplied baseline, with `z`;
- paginated fetch with an explicit `stop_reason` (`page_older_than_since`), `pages`, `matches_seen`, `total_reported`;
- writes a JSON evidence artifact alongside the human report.

Verified run in this audit:

```
$ python3 wr_report.py --since 2026-11-17T00:00:00
Matches 298  W 53  L 245  D 0
Win rate 17.79%  Wilson 95% CI [13.86%, 22.53%]
Baseline 21.64% (238W/1100M)  z=-1.61  p=0.1064
```

Stored evidence (`~/tcg-bot/evidence/wr-postaudit.json`, 09:30) for the post-fix window:

| Window | Matches | W | L | WR | 95% CI |
|---|---|---|---|---|---|
| Since 2026-11-17 22:49 (belief + card-aware scoring shipped) | 135 | 39 | 96 | **28.9%** | [21.9%, 37.0%] |
| Since 2026-11-18 02:06 | 99 | 26 | 73 | 26.3% | [18.6%, 35.7%] |
| Lifetime (baseline) | 1,100 | 238 | 862 | 21.6% | — |

That is a **real, statistically visible improvement**: pre-22:49 on Nov 17 the bot was at roughly 14W/163M (8.6%); post-change 28.9% (p=0.039 vs lifetime). Credit where due — the feedback loop between `loss-analysis.md`, `scoring.py`, and `wr_report.py` demonstrably worked once.

### What fails
1. **The 71.5% self-play number does not measure this bot.** `self_play_v2.py` hardcodes `sys.path.insert(0, "~/ptcg-lab/src")`, uses a different engine (`ptcg.core.envs`), different decks (`charizard_ex` vs `miraidon_ex`), and a different policy class. It reports heuristic-vs-random. It is not a proxy for arena strength, and the report's own table admits the 72.5% → 29% transfer gap. It also **cannot currently run** (`ModuleNotFoundError: loguru`).
2. **Dead in-bot metrics.** See §1.5. There is no decision log, no per-decision timing, no per-match record of prizes/bench/attack chosen. Every strategic claim in the docs had to be re-derived by replaying the API in this audit.
3. **No evaluation discipline around changes.** The 22:49 improvement is only visible because a human ran `wr_report.py` afterwards. There is no gate that says "a strategy change ships only with a pre-registered window, a control, and a CI that excludes the baseline". `ruflo_tcg.py` looks like that gate but is not (see §7.3).
4. **Doc numbers contradict the data.** `world-class-plan.md` states 29.2% and rank 56; the live window says 17.8%; `scouting-report.md` calls 633/1,308 (48.4%) "48.7%… highest among active agents" while its own table shows clairenuttall at 826/1,443 (57.2%).

---

## 4. Strategy depth — 1/5

### What the code actually does
`ismcts.py` advertises information-set MCTS with chance nodes. It does not contain MCTS:

```python
def search(self, obs, legal_actions):
    scored = [(a, self._score_action(a, obs, legal_actions)) for a in legal_actions]
    scored.sort(key=lambda x: -x[1])
    return scored[0][0]
```

`_score_action` delegates to `scoring.action_score`, a static weighted sum: attack `60 + 1.5×damage` (+80 for a knockout), play `45`, attach `25`, ability `20`, retreat `5`, end turn `-25`. The `Node` dataclass and `ucb1()` are dead code never instantiated. There are no rollouts, no determinisation, no tree.

Measured cost of "search": **median 0.08 ms, p95 0.19 ms, max 9.9 ms** over 238 replayed decision points — against a declared `time_budget_ms=1000`. The bot spends **0.008%** of its budget.

### What the replays show
Replaying 8 settled matches (`/tcg/battle/{id}/decisions`) against the live policy:

| Match | Turns | Max bench | Our decisions | Attacks used (attackId:count) |
|---|---|---|---|---|
| win 64433d67 | 7 | 5 | 17 | 412:2, 456:1 |
| win ba096869 | 41 | 3 | 26 | 545:20 |
| win 52b10fd9 | 35 | 0 | 23 | 901:17 |
| win 85f24f85 | 39 | 5 | 40 | 901:15, 456:1, 31:3 |
| loss 36448ff4 | 23 | 3 | 30 | 545:9, 456:1, 31:1 |
| loss c8ae3e69 | 15 | 2 | 27 | 412:2, 456:4, 901:1 |
| loss c43c89e8 | 17 | 5 | 38 | 412:4, 31:2, 545:2 |
| loss 18192465 | 25 | 5 | 37 | 901:7, 31:3, 456:1 |

- Attack IDs used: 901 (Druddigon Shred, **40 dmg**), 456 (Pikachu Tail Whap, **30**), 412/413 (Zacian, 30), 31 (Enamorus, 30), 545 (Tauros Clean Hit, **50**). The high-damage attacks in the catalog (902: 90, 457: 220, 413: 240) **never appear** — they need 2–4 energy and there is no acceleration or attachment planning.
- Typical exchange: 30–50 damage per turn into a 200–340 HP ex attacker that one- or two-shots our 120–230 HP body. The prize race is lost by construction.
- Attack choice is usually trivial: in the losing replays the decision often offers exactly **one** attack option plus end-turn, so the "heuristic" is choosing between "attack" and "pass".
- Retreat is scored at 5 (plus 30 if the active is under half HP) versus ≥60 for any attack — it is effectively never selected.
- The belief tracker's only influence on play is `+10` retreat score when `top_threats[0][1] >= 0.6`, computed against the wrong archetype (§1.2).

**There is no opponent model, no prize-race valuation, no energy planning, no targeting, and no lookahead. The strategy is a fixed priority table.**

---

## 5. Deck quality — 1/5

```python
DECK = [625]*4 + [328]*4 + [299]*4 + [39]*4 + [390]*4 + [1]*40   # 20 Pokémon + 40 Grass Energy
```

- **Zero trainer cards.** No draw (Professor's Research, Iono), no search (Ultra Ball, Buddy-Buddy Poffin), no gust (Boss's Orders), no switch, no stadium. The deck cannot fix a bad hand, cannot find an attacker, cannot choose its target.
- **67% of the deck is basic energy.** With no acceleration and a 1-attachment-per-turn rule, 40 energy converts directly into dead draws: the bot's own replays show hands growing to 10–12 cards while bench and board stagnate.
- **No evolution line, no ability engine, no 2-prize plan.** Every attacker is a Basic with a 0–1 energy attack capped at 50 damage.
- Comparative evidence from `scouting-report.md` (as of 2026-11-15, repo docs, not re-verified here): top-10 agents win 40–60%+ and run supporter-based search/draw plus 2–5 bench Pokémon. Three of the top 10 use `tcg-arena-bot`.
- The guardrails that should have caught this are too weak. `tests/test_deck_viability.py` enforces HP ≥ 80 and damage ≥ 30 — both satisfied by a deck that loses 71% of its games. Its `test_total_basic_hp` sums **distinct** basics (`for c in set(basics)`), so 19 copies of one 200 HP card would pass a "600 total HP" check.

The deck is legal. It is not competitive, and no test in the repo can tell the difference.

---

## 6. Maintainability — 2/5

| Metric | Value |
|---|---|
| Python LOC (lib + tests) | 4,303 |
| Test coverage, all modules | **62%** |
| `bot.py` | 34% |
| `bot_async.py` | 42% |
| `ismcts.py` | 67% |
| `scoring.py` | 75% |
| `belief.py` | 68% |
| `self_play.py` / `self_play_v2.py` | **0% / 0%** |

Positives: clear module boundaries (transport / scoring / belief / search / governance report); `scoring.py` is typed, documented, and unit-tested; `bot_async.py`'s retry contract has eight targeted regression tests, including the exact string-shaped 409 that used to crash production.

Negatives:
- **~250 duplicated lines** across `bot.py` and `bot_async.py` with already-divergent behaviour (§1.4).
- **Dead weight:** `tests/test_basic.py` (imports a deleted module), `ismcts.Node`/`ucb1`, `belief.update_on_search`/`update_on_discard`/`update_on_end_turn` (never called), `self_play.py` superseded by `self_play_v2.py`, both at 0% coverage and both un-runnable without `loguru`.
- **No fixtures from real observations.** `tests/test_decision_latency.py` exercises `{"damage": 30}` options — a schema `scoring.py` explicitly says does not exist. The test passes while measuring a code path production never takes. There is not a single recorded arena obs in the test suite.
- **No README, no CI, no linter/type-check config.** `.github/` does not exist; the only automated check is a human running `pytest`.
- **Docs rot fast:** `kanban.md` marks "ISMCTS heuristic — Done" and "Belief state tracker — Bayesian opponent hand tracking" as complete; `loss-analysis.md` describes a Budew-only deck that is no longer the deck; `deterministic-checks.md` lists checkboxes ("need test files") for tests that exist.

---

## 7. Governance — 2.5/5

### What holds
`GOVERNANCE.md` is a real governance document, not ceremony: request binding, authority resolution, allow/clarify/escalate routing (paid entries and hosted deploys are ESCALATE), stop conditions, a `worker.cycle`, and a `check.record` template with `PASS | FAIL | NOT_RUN`.

`.agent-team/` implements it: `dispatch.sh` (branch + isolated worktree + baseline), `verify.sh` (runs the acceptance command, records commit, dirty-file count, environment, observed output, exit code as JSON), `sync-live.sh` (guarded copy into `~/tcg-bot`). `.gitignore` correctly excludes credentials, state, DBs, logs, and `evidence/`.

### What fails
1. **The canonical check hides a broken test.** `.agent-team/config.json` enumerates seven test files and omits `tests/test_basic.py`. The natural command — and the one a new contributor types — fails. Hiding a red test in the config is worse than deleting it.
2. **Findings that were never closed.** `red-team-findings.md` reviews `bot/client.py` (12 findings, 2 "CRITICAL") — a file that no longer exists. None of the 12 has a recorded disposition. The document is now fiction.
3. **Autonomy theater.** `ruflo_tcg.py` is at **L2 (HUMAN_APPROVE)** with **301 recorded matches**, **0 strategy proposals**, **0 applications**, `apply_count: 0`. It promoted itself from L1 on a window where the WR gate (0.40) could only have been met transiently, and it has never proposed a change. The ladder is a level counter, not a learning loop.
4. **A live incident no process caught.** Two competing bot processes (§2.1) is exactly the class of failure `verify.sh` and `GOVERNANCE.md`'s `worker.cycle` exist to prevent, yet nothing in the repo checks "how many clients are attached to this agent". There is no runtime reconciliation between the documented procedure and the actual machine.
5. **No CI.** `proof.match` is manual, and the evidence directory it writes to is gitignored — so the proof is local and perishable.

---

## 8. Top gaps, in priority order

| # | Gap | Why it matters | Concrete fix |
|---|---|---|---|
| 1 | **Two bot processes racing on one agent** | Corrupts 31% of submissions, makes every experiment non-reproducible, and is arguably the single largest unmeasured drag on win rate today | Kill one path. Pick `bot_async.py`, delete or archive `bot.py`'s loop, and add a single-instance lock (pidfile/flock). Change `restart_when_idle.sh` to manage the async process. |
| 2 | **Deck has no trainers** | Structural: cannot draw, search, or gust. Caps win rate regardless of policy quality | Build a real list: 12–16 trainers (draw/search/gust/switch) + an evolution line, 8–12 energy. Test it in a **hosted/sandbox** competition before any season-wrecking join. |
| 3 | **"ISMCTS" is a static argmax** | Zero lookahead against opponents that set up 2–4 turns ahead; uses 0.08 ms of a 1000 ms budget | Either delete the name and own the heuristic, or implement a real one-ply-with-rollouts searcher on a deterministic engine. The budget is already there; the search is not. |
| 4 | **Belief seeded with our own deck** | Every threat probability is wrong; the only belief-driven signal (retreat) is noise | Infer the opponent archetype from observed cards only (`merge_archetype` already does this), start with an empty prior, and add a regression test that asserts P(opponent holds our card) is not suspiciously high on turn 1. |
| 5 | **Broken default test run** | Contributors and agents cannot trust green | Delete `tests/test_basic.py`, add `--cov-fail-under=70`, add a CI job that runs plain `pytest`. |
| 6 | **No decision telemetry** | Every strategic claim in this repo had to be manually re-derived from the API | Log one JSON line per decision: `matchId, seq, turn, selectType, options, chosen, latencyMs, bench, prizes`. Then a replay harness can score policies offline. |
| 7 | **State counters never update** | Metrics that lie are worse than no metrics | Delete the dead counters or wire them; add a test that after N decisions the counter is N. |
| 8 | **Ruflo does not close the loop** | Gives a false sense of an improving system | Either wire proposals → code/config → A/B → keep/revert with `wr_report.py` as the judge, or demote `ruflo_tcg.py` to "match log" and remove the autonomy language. |
| 9 | **No timestamps in logs** | Forensics and latency attribution are impossible | Prefix every log line with ISO-8601. |
| 10 | **Stale docs contradict live data** | Governance degrades into narrative | Regenerate the numbers in `kanban.md` / `world-class-plan.md` / `scouting-report.md` from `wr_report.py` output, or delete the numbers. |

---

## 9. What would have to be true for "world-class"

1. **Single supervised deployment** with a health check, log timestamps, and a proven single-instance guarantee.
2. **A real deck**: trainers, an evolution or ability engine, and a measured 40%+ WR in this field before any further policy work.
3. **Search that uses its budget**: ≥ 100 ms of actual lookahead per non-trivial decision, with a simulator whose obs schema matches the arena's.
4. **A closed evaluation loop**: every change pre-registered with a window, a control, and `wr_report.py` as the arbiter; regressions auto-reverted.
5. **Tests against recorded arena observations**, not invented schemas — with coverage gates in CI.
6. **Documentation regenerated from evidence**, not from memory.

None of these are exotic. All six are absent today.

---

## Appendix A — Reproduction

```bash
cd <worktree>
python3 -m pytest -q                      # FAILS: tests/test_basic.py → ModuleNotFoundError: bot.client
python3 -m pytest -q --ignore=tests/test_basic.py   # 62 passed
python3 -m pytest -q --ignore=tests/test_basic.py --cov=. --cov-report=term-missing  # 62%
python3 wr_report.py --since 2026-11-17T00:00:00    # 298 matches, 17.79% [13.86, 22.53]
```

## Appendix B — Evidence sources

| Claim | Source |
|---|---|
| Window WR / CI / p-value | `evidence/wr-postaudit.json`, `evidence/wr-current.json`, live `wr_report.py` run |
| Loss/win reason mix (135 matches) | `wr-postaudit.json` → 96 L (64 `all_prizes_taken`, 31 `no_active_pokemon`, 1 `timeout_forfeit`); 39 W (15 `deck_out`, 14 `all_prizes_taken`, 7 `no_active_pokemon`, 3 `timeout_forfeit`) |
| Action POST reliability | `~/tcg-bot/bot_async.log` → 2,390 posts, 2,389 × 200, 1 × 409, 0 `UNACKNOWLEDGED`, 19 poll timeouts, 0 tracebacks |
| Duplicate submissions | `~/tcg-bot/bot.log` → 439 `idempotent: true` of 1,420 posts; shared match IDs with `bot_async.log`; `ps` shows both PIDs |
| Deck composition | `bot.py:53`, validated by `python3 -c "import bot; print(len(bot.DECK))"` → 60 |
| Decision latency & attack usage | Replay of 8 matches via `/api/arena/tcg/battle/{id}/decisions`, scored with the live `bot.choose_action` + `BeliefWeightedHeuristic` |
| Test/coverage numbers | `pytest --cov=. --cov-report=term-missing` |
| Ruflo level / inactive loops | `~/.hermes/state/tcgbot/ruflo_tcg.db` → `current_level: 2`, 301 `match_results`, 0 `strategy_proposals` |
| Governance structure | `GOVERNANCE.md`, `.agent-team/{config.json,verify.sh,README.md}`, `.gitignore` |

*All live data read on 2026-11-18 between 10:36 and 10:45 +08. No credentials were printed or persisted. No code, state, or process was modified by this audit.*
