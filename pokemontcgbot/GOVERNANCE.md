# TCG Bot Governance (Lauren Tan method)

## request.bind
- origin: Telegram thread 715591 / this session
- requester: Colbert Low (colbe)
- repo: <repo-root>
- goal: Build and improve a competitive Pokemon TCG bot for DevFun Arena [TCG] Playground S6
- acceptance: Bot joins, plays matches without forfeits, collects decision logs, and improves win rate via heuristic/search/self-play
- grants: owner authorization for free practice season only; paid/credits seasons require explicit per-entry authorization
- paths: <repo-root>/**, <scout-dir>/**
- stop_when: season ends, match allowance exhausted, or owner stops

## authority.resolve
- requester: Colbert Low (owner)
- agent: sirshibaninjabot02 (cmqogaydkdghsnq1ql4t9anjt)
- credentials: ~/.arena-credentials (never print)
- tools: arena API, local filesystem, Python venv
- unresolved: paid entry authorization, deployment to hosted bundle, GPU training budget

## action.route
- ALLOW: read-only API calls, local code edits, bot restart, scouting, Obsidian notes
- CLARIFY: deck changes that lock the season, new dependencies, model training runs
- ESCALATE: any paid entry, credits purchase, secret handling, production deployment

## context.sync
- owner: Colbert Low
- accountable task owner: Hermes agent (this session)
- acceptance checks: join success, match completion without forfeit, decision logs saved, heuristic win rate > baseline

## worker.cycle
- pin baseline commit before changes
- reproduce current behavior (join + play loop)
- patch one cohesive change
- run actual bot and replay affected scenario
- inspect outputs and state

## proof.match
- build: python compile + import checks
- behavior: join returns matched, actions return 200, no forfeits
- quality: deck validation, copy limits, 60 cards
- acceptance: owner review of match logs and rank movement

## check.record (template)
- requirement: <item>
- commit: <sha>
- worktree: <diff>
- environment: <state>
- execution: <command>
- expected: <observation>
- observed: <result>
- status: PASS | FAIL | NOT_RUN

## result.route
- PASS: retain evidence, prepare review
- FAIL: correct cause, rerun
- NOT_RUN: name prerequisite and owner

## autonomy.expand
- repeatable verification before broader delegation
- defined permissions, isolation, stop conditions
- decision log and rollback options
- expand only within approved authority
