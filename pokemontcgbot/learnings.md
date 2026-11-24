# Learnings — TCG Bot

## Verification and contracts
- Treat any pasted bot blueprint as pseudocode until checked against `/api/arena/__introspection`. The v2 package in `devfun_tcg_bot/deploy_reference/` targets endpoints that do not exist on the live arena; it is reference only.
- The real arena contract is `x-arena-api-key` auth, `POST /tcg/join` with `{competitionId, joinPayload}`, `GET /tcg/pending-actions` returning `pending` + `activeMatches`, and `POST /tcg/action` with `{matchId, seq, action}` where `action` is a string from `legalActions`.
- `/agent/wallet` requires a `chain` query parameter. A payment/402 flow is not implemented and must not be without explicit owner authorization and a loss cap.
- Never wire the offline package into `bot_async.py` just because tests pass. A different MD5 on the live loop is the proof that it was not wired in.

## Determinism and measurement
- `benchmark_selfplay.py` originally used unseeded softmax sampling; identical 500-game runs returned different verdicts. Seed RNG per match; the reproducible result is 52.2% with `PROMOTE_TO_PROD=False`.
- Wilson CI + binomial p from paginated match records, not leaderboard deltas. Quote sample size, CI, baseline, and p together.
- Post-2026-11-20 policy is a significant regression (15.74% since build, p=0.0000 vs 36.02%). Do not call a change an improvement without a fresh measurement.
- Do not restart a live bot while `activeMatches > 0`; use `restart_pm2_when_idle.sh`.

## Safety and governance
- Single poller only; `~/.arena-tcg.lock` prevents duplicate action posts.
- Never print or commit `~/.arena-credentials`.
- Privacy guard blocks literal home paths in committed files; use `~` or repo-relative paths.
- Paid Stakes/wallet flows require escalation; they are not autonomous decisions.

## 2026-11-24 chief run
- Red review was decisive: a passing Builder suite is not proof. It found four confirmed defects (telemetry attribution, stale belief, exception bypass, fabricated gate) that the Builder's own tests missed. Independent review before merge is mandatory.
- The real loss mechanism was measurable: belief ISMCTS bypassed mandatory attach/development in 412 of 599 eligible decisions. Fix the decision path before tuning weights or decks.
- Precommit gates must cite an accepted document. A locally chosen 46/42 gate was wrong; plan R6 requires 47% at n≥900 with lower bound ≥43.5% and rank ≤3.
- Use one shared source for a guardrail: `scoring.mandatory_action`. A second scorer that ignores it is a bypass waiting to happen.
- Sync repo → live with explicit paths; worktree roots include a `pokemontcgbot/` subdirectory, and a wrong source path silently copies nothing.
- Never start the bot on the MacBook. WSL is the only runtime. Mac sync is blocked until SSH/Tailscale SSH is enabled.

## Process after each coding session
1. Update `PRD.md`, `spec.md`, `kanban.md`, `learnings.md` with current state, plans, and backlogs.
2. Commit and push to origin; verify `HEAD == origin/main`.
3. Sync repo → WSL live working copy only for genuine diffs; prove with `diff -q` and MD5 of `bot_async.py`.
4. MacBook M5 sync is blocked until SSH/Tailscale SSH is enabled on that host.
5. Restart the bot only when idle; record the restart time and new PID.
