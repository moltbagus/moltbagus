# Specification — Pokemon TCG Minimal Bot

## 1. Purpose
A minimal, legal, always-legal Pokemon TCG agent for DevFun Arena owner-hosted (remote) seasons. It exists to prove end-to-end play (join, poll, act, settle) before stronger strategies are added.

## 2. Scope
In scope:
- Load credentials from `~/.arena-credentials`.
- Validate and submit a 60-card deck.
- Join `[TCG] Playground S6` (`cmw99opb57gssgfb7rj39a1o1`).
- Poll pending actions and post exactly one legal action per decision point.
- Persist `.arena-tcg-state`.
- Run continuously until stopped.

Out of scope (future):
- Deck optimization, search, learning, hosted bundles, credits seasons.

## 3. Deck Specification
- 4x Druddigon (cardId 625): Basic Colorless Pokemon, 120 HP, 0-energy attack "Shred" (40 damage, ignores effects on Defending Pokemon).
- 4x Pikachu ex (cardId 328): Basic Lightning Pokemon, 190 HP, 0-energy attack "Tail Whap" (30 damage).
- 4x Hop's Zacian ex (cardId 299): Basic Metal Pokemon, 230 HP, 0-energy attack "Insta-Strike" (30 damage).
- 4x Enamorus (cardId 39): Basic Grass Pokemon, 120 HP, 0-energy attack "Heart Sign" (30 damage).
- 4x Tauros (cardId 390): Basic Colorless Pokemon, 130 HP, 0-energy attack "Horn Attack" (30 damage).
- 40x Basic {G} Energy (cardId 1).
- Total 60. Copy limits satisfied (energy exempt). At least one Basic. No ACE SPEC. No evolutions.
- Rationale: All 0-energy attacks (can attack turn 1), mixed HP tiers (120-230), higher damage than previous Budew deck. Druddigon leads with 40 damage.

## 4. Runtime Behavior
1. Validate deck locally.
2. Join via `POST /api/arena/tcg/join`.
3. Loop:
   - `GET /api/arena/tcg/pending-actions?competitionId=...`
   - If pending empty and activeMatches non-empty: opponent acting; wait 2s.
   - If pending empty and no active: re-join to keep queue; wait 2s.
   - For each pending entry: choose action, `POST /tcg/action`, retry on `arena_transaction_busy`.
4. On Settled/Aborted: log and continue polling.
5. Persist state after join.

## 5. Action Selection (minimal)
- Parse legal action strings like `[0]`.
- Score by option damage in `obs.select.option[idx]`; pick highest; tie-break first legal.
- Fallback: first legal action.
- Never send an action not in `legalActions`.

## 6. Safety
- Never hardcode or print apiKey.
- Wrap network errors; retry with backoff.
- Near deadline, still post best legal action.
- No secrets in state file or logs.

## 7. Success Criteria
- Joins without 4xx (except idempotent re-join).
- Completes at least 1 match without forfeit/timeout.
- `strategyComputeMsMedian` > 0 if hosted; decision log present.
- State file updated.

## 9. Belief State Tracker (belief.py)
- Bayesian tracker for opponent's hidden hand.
- Tracks public zones: discard, board, prizes taken.
- Hypergeometric probability: P(card in hand) = 1 - C(N-r, h) / C(N, h).
- Updates on: play, draw, discard, search, prize take.
- Provides: hand_probabilities(), top_threats(), expected_copies_in_hand(), is_likely_in_hand().
- Integration point for ISMCTS search (Phase 4).

## 10. Files
- `bot.py` — implementation.
- `belief.py` — Bayesian belief state tracker.
- `spec.md` — this file.
- `PRD.md` — product requirements.

## 11. Current implementation (2026-11-23)
- Entrypoint: `bot_async.py` under pm2 service `tcg-bot`; single instance enforced by `~/.arena-tcg.lock`.
- Season identity is owned by `arena_config.py` (`COMPETITION_ID`, `AGENT_ID`, `SEASON_NUMBER`, `DECK_THESIS`) and imported by the entrypoints and `wr_report.py`.
- Live contract: `x-arena-api-key` auth at `/api/arena`; join `/tcg/join` with `{competitionId, joinPayload}`; poll `/tcg/pending-actions`; act `/tcg/action` with `{matchId, seq, action}` where `action` is a string from `legalActions`.
- Decision path: `scoring.best_action()` with card-aware option scoring, attach-before-attack, bench protection, evolve/ability ranking, belief-weighted `ismcts` under a wall-clock budget. Deterministic rules first; no LLM in the action path.
- Deck S7: 18/30/12 Audino core, locked for the season. Attack and HP tables in `scoring.py` are deck-specific.
- Verification: `python3 -m pytest -q --ignore=tests/test_ab_deck.py --ignore=tests/test_ab_engine_lock.py` — 184 passed. Full collection has two known A/B-harness errors from missing dependencies.

## 12. Offline v2 package — NOT in the live path
- `devfun_tcg_bot/` contains `tracker.py`, `engine.py`, `benchmark_selfplay.py`, `arena_adapter.py`, and `deploy_reference/`.
- `arena_adapter.py` maps the verified live introspection schema to flat state and request bodies. It performs no HTTP, join, action, or payment operations.
- The uploaded `runner.py`/`config.py` deployment variant is stored only as `deploy_reference/`; it targets endpoints that do not exist on the live arena and must never replace `bot_async.py`.
- A seeded 500-game offline benchmark is reproducible: 52.2% challenger win rate, binomial p≈0.348, `PROMOTE_TO_PROD=False`. This is simulator evidence, not arena strength.

## 16. Ruflo self-fixing loop (2026-11-25)
- `sfl_loop.py` is offline-only and stdlib-only. `CorrectionStore` writes append-only `corrections/tcg/failures.jsonl`, derives deduplicated `rules.md`, and records `verify.json` with `rule_passed` separate from outcome.
- `failures.jsonl` is authoritative. `active_rules()` rebuilds from the log and ignores tampered `rules.md`; `verify()` refreshes rules before rejecting unknown ids.
- Writes are atomic via temp file + fsync + `os.replace`; reads and writes are serialized with RLock and POSIX `flock`. Corrupt `verify.json` raises `VerificationDataCorrupt`; malformed log lines are skipped with a warning.
- `RufloTCG.record_failure` commits the sqlite row first; derived correction-write failures are logged and never raised into the live failure path.
- Verification at merge `83dc12e`: 22 SFL unit tests, 7 integration tests, 238 full-suite tests with A/B ignores, live 29 SFL tests, privacy clean.
- Follow-ups shipped at merge `66ff4ae`: strict collision-safe rule ids; committed invalid-UTF-8, two-process flock, and temp-cleanup regressions; a post-append refresh failure now preserves prior `rules.md` and the in-memory map. A fresh missing log is still an empty map. Re-review found no blockers.

## 15. TRACE evaluator (2026-11-24)
- `trace_eval.py` is offline-only. It reads `~/.arena-tcg-decisions.jsonl` or a repo-relative copy, derives `traceId`/`parentTraceId` and mandatory-action markers with `scoring.mandatory_action`, and writes R9 evidence.
- A2A envelopes require full R9 check fields and an evidence reference. `rerun_check` re-runs only allowlisted offline commands and rejects fabricated `observed`, `counts`, `commit`, or `exit_code`.
- Ticks are append-only at `evidence/trace-loop/ticks.jsonl`. State is derived from referenced evidence; R16 checks both incoming and tip commit against an explicit evaluation head.
- Gates are produced by `python3 trace_eval.py gates`. Committed result: G-A PASS, G-B FAIL, G-C BLOCKED. G-B FAIL is a finding on the historical corpus, not a failure of the evaluator.
- Verification: 16 focused tests, 209 full-suite tests, privacy scan clean. `PRD.md`, `spec.md`, `kanban.md`, and `learnings.md` are updated by the coding-session closeout.

## 14. Guardrail-first policy (2026-11-24)
- `scoring.mandatory_action(obs, legal)` is the single source for attach-first and development-first rules; both `best_action()` and `bot._choose_action_with_path()` call it first.
- Belief sync happens on every decision point, including guardrail decisions, so ISMCTS never samples from a stale tracker.
- Telemetry records `policyPath='mandatory'`; malformed observations stop at the deterministic fallback instead of falling through to belief.
- Policy version `l1-2026-11-24-guardrail-first`; boundary and gate in `docs/precommit/2026-11-24-guardrail-first.md`.
- TRACE/A2A/loop requirements plan: `docs/plans/2026-11-24-2105-feat-trace-a2a-loop-plan.md` (requirements-only, not executed).

## 13. Measurement rules
- Use `wr_report.py --since ... --baseline ... --no-json` from the live directory against paginated match records. Never subtract leaderboard snapshots.
- Quote Wilson 95% CI, sample size, baseline, p-value, and pm2 binding (commit, PID, start) together.
- Windows under ~100 settled matches are directional only.
- Any decision-affecting change requires a `POLICY_VERSION` bump in the same commit and a new measurement boundary from the first record carrying that version; do not tune inside a frozen window.
- Restart only when `activeMatches == 0`. Use `restart_pm2_when_idle.sh`; never kill pm2 during a live match.

