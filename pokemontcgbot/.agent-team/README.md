# TCG Bot Agent Team

Governance: `laurentan1` skill. Workflow: `hermes-agent-team-workflow` skill.
Lead: Hermes. Workers: Hermes `delegate_task` lanes.

The live bot runs from `~/tcg-bot`. The canonical git repo is `moltbagus/moltbagus`
and the bot code lives in `pokemontcgbot/`. This scaffold lives in that subdirectory
and is symlinked into the live directory as `~/tcg-bot/.agent-team`.

## Files

- `config.json` — repo subdir, live dir, worktree root, default checks.
- `dispatch.sh` — creates a branch + isolated worktree, seeds it from live, records the baseline.
- `verify.sh` — runs the acceptance command in the worktree and writes `check.record` JSON.
- `sync-live.sh` — copies verified files from the worktree into the live directory.
- `pr-template.md` — request.bind / authority.resolve / worker.cycle / proof.match / check.record.

## Procedure

1. `./.agent-team/dispatch.sh TASK-001 policy "prize-race and bench policy"`
2. Dispatch a worker into the printed `SUBDIR`; give it the task, acceptance command, and timeouts.
3. Worker edits, runs tests, commits in the worktree.
4. `./.agent-team/verify.sh TASK-001 "policy tests" "python3 -m pytest -q" "all tests pass"`
5. Read `evidence/TASK-001-verify.json`; require `status: PASS` and `commit` equal to the worker's commit.
6. Merge the branch in a separate worktree checked out at `main`; push.
7. `./.agent-team/sync-live.sh TASK-001 --yes` only after the live window has no active match.

## Rules

- Never dispatch a worker at the live directory; workers edit the worktree.
- Never merge on `FAIL`; correct the cause and rerun.
- Worker summaries are self-reports. The lead reruns the check and inspects the evidence.
- Do not restart the live bot while `activeMatches > 0`; poll until zero.
- Do not commit credentials, logs, databases, `__pycache__`, or `evidence/`.
- Paid entries and hosted-bundle deploys are ESCALATE, not ALLOW.
