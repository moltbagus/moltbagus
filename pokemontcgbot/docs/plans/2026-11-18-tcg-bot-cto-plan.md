# TCG Bot — CTO Plan (2026-11-18)

## request.bind
- origin: Telegram thread 715591
- requester: Colbert Low (owner)
- repo: <repo-root> (GitHub moltbagus/moltbagus → pokemontcgbot/)
- goal: Make the DevFun Arena TCG bot measurably better and keep changes verifiable.
- acceptance: Every strategy change has a repeatable before/after win-rate check; new code passes tests; live bot does not forfeit on restart.
- grants: owner authorization for free practice season and local code changes.
- paths: <repo-root>/**, <repo-root>/**
- stop_when: season ends, owner stops, or a paid entry/deploy is required.

## authority.resolve
- requester is the owner and CTO delegate.
- Read-only arena API and local edits are ALLOWED.
- Paid entries, hosted-bundle deploys, and credential changes are ESCALATE.
- Single bot process rule: never start a second poller.

## CTO decision
Freeze heuristic/strategy tuning until measurement is trustworthy. The post-restart 43.3% (13/30) is a real signal but has a wide CI; tuning against 30 matches would be noise-chasing. Build the measurement and restart-safety layer first.

## Priority frame
1. **P0 — Measurement (now):** `wr_report.py` pulls paginated match records, filters by an ISO timestamp, computes W/L, win rate, Wilson 95% CI, and a binomial p-value vs a baseline. Writes JSON evidence. Tests use synthetic fixtures.
2. **P1 — Restart safety:** assert the bot is never restarted while `activeMatches > 0`; keep the idle watcher and add a dry-run test.
3. **P2 — Offline evaluation:** integrate the local ptcg-engine self-play harness for policy A/B before live deployment.
4. **P3 — Strategy/deck:** only after P0/P1, and only with a pre-registered hypothesis.

## Technical tradeoffs
- Measurement tool is low risk, high leverage; it prevents false positives.
- A live-only A/B is noisy and slow; offline self-play is faster but may not transfer to arena.
- Deck is locked for the season, so code changes must work with the current 60-card list.

## Delivery risks
- Arena match API caps `limit` at 50; must paginate with `nextCursor`.
- `agentResult.outcome` is only present for the caller's own matches.
- Restarting while a match is active forfeits it.
- Public repo privacy guard blocks home-directory paths in committed files.

## P0 acceptance
- `python3 wr_report.py --since 2026-11-17T22:49:27+08:00 --json` returns 30 matches, 13 wins, 43.33%, CI and p-value.
- `pytest -q` passes (existing 20 + new tests).
- Evidence written to `evidence/wr-report.json`.

## check.record (to fill after run)
- requirement: P0 measurement tool
- commit: TBD
- environment: Python 3.12, arena credentials at ~/.arena-credentials
- execution: `pytest -q && python3 wr_report.py --since ... --json`
- expected: 30/13/43.33% and tests pass
- observed: TBD
- status: NOT_RUN
