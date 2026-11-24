# TCG Bot — Kanban Board

## Backlog
- [ ] ISMCTS search engine (Phase 4) — requires game simulator
- [ ] Self-play tuning (Phase 5) — run bot vs older versions
- [ ] Hosted bundle submission (Phase 6)
- [ ] Ranked/stakes season (Phase 7) — requires owner approval
- [ ] Trainer card support in heuristic
- [ ] Retreat decision logic
- [ ] Prize trade evaluation

## In Progress
- [ ] Ruflo self-improvement integration (L1 DRY_RUN)
- [ ] Scouting task (t_43a9d6bc) — top-10 match analysis pending

## Done
- [x] Minimal legal bot (bot.py) — joins + plays
- [x] Belief state tracker (belief.py) — Bayesian opponent hand tracking
- [x] ISMCTS heuristic (ismcts.py) — belief-weighted action scoring
- [x] Ruflo self-improvement backbone (ruflo_tcg.py) — autonomy ladder + promotion gates
- [x] Spec.md — technical specification
- [x] PRD.md — product requirements
- [x] Deck v2 — mixed high-HP 0-energy attackers
- [x] Obsidian vault sync — all docs copied

## Blocked
- [ ] Top-10 scouting — awaiting worker execution of t_43a9d6bc
- [ ] Full ISMCTS — needs game simulator (ptcg-engine)

## Win Rate (2026-11-23, S7)
- 995 matches, 221 W = 22.21%; Wilson 95% CI [19.74%, 24.90%]; p=0.473 vs 21.28% baseline — no improvement.
- Since 2026-11-20 23:01 policy build: 686 matches, 108 W = 15.74%; CI [13.21%, 18.66%]; p=0.0000 vs 36.02% — significant regression.
- Since 2026-11-23 00:00: 160 matches, 21 W = 13.12%; p=0.0053 vs 22.29%.
- Rank near bottom of S7; top bots at ~47–59%. World-class gates not met.

## Done (updated 2026-11-23)
- [x] Verified real arena contract from `/api/arena/__introspection`: `x-arena-api-key`, `joinPayload`, `pending`/`activeMatches`, `{matchId, seq, action}`.
- [x] Offline v2 package: tracker, engine, expectimax, reproducible paired-seed benchmark, Docker image, and real-schema adapter.
- [x] Privacy guard fix in committed README; HEAD == origin/main before docs update.

## In Progress (2026-11-24)
- [x] Idle-gated pm2 restart on WSL: `activeMatches == 0`, restart completed 2026-11-24T21:28:35+08, new PID 3485746, restarts=4, one poller. Live files report policy `l1-2026-11-24-guardrail-first`.
- [x] Repo → WSL live sync of verified code and docs.
- [ ] Measure `l1-2026-11-24-guardrail-first` to the 900-match precommit; result `NOT_RUN` until sample closes.

## Done (2026-11-24)
- [x] Builder branch `task/TASK-GUARD-RESTORE-guardrestore` shipped `1f565a4`; independent Red and Blue lanes completed; four confirmed blockers corrected before merge.
- [x] TRACE/A2A/loop requirements plan merged at `055b8ac` (requirements-only).
- [x] Merged to `main` at `4d1880c`; merged suite 202 passed / 4 skipped; live focused suite 28 passed.

## Blocked
- [ ] MacBook M5 git sync: Tailscale host `colb-m5-macbook-air` is reachable by ping, but SSH on port 22 and 41641 is refused; Tailscale SSH returns 502. Need SSH/Tailscale SSH enabled on the Mac or an alternate sync path.
- [ ] Stakes/wallet/payment flow: no owner authorization or loss cap.
- [ ] Full ISMCTS game-tree simulation: pinned engine does not implement the S7 deck cards.

## Backlog (2026-11-23)
- [ ] P0 red-team replay of post-2026-11-20 losses; rank fix vs rollback to last known-good commit.
- [ ] P1 prepare catalog-validated S8 deck offline; no live deck change until reset or new-agent approval.
- [ ] P2 decision telemetry: one JSON line per decision with matchId, seq, chosen, latencyMs, bench, prizes.
- [ ] P3 wallet/payment/Stakes support only after explicit owner authorization.

## Notes
- Season: [TCG] Playground S7 (`cmwm3cekx011nln01c3gqi0tc`).
- Agent: `cmqogaydkdghsnq1ql4t9anjt`.
- Credentials: `~/.arena-credentials` (never commit or print).
- State: `~/.hermes/state/tcgbot/`.
- Repo: canonical checkout with `pokemontcgbot/` as the code subdirectory; WSL live working copy is separate and must be diffed before copying.
