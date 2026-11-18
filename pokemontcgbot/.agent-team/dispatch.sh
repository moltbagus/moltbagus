#!/usr/bin/env bash
# Create an isolated worktree and baseline for one TCG bot task.
# Usage: ./.agent-team/dispatch.sh TASK-XXX branch-slug "summary"
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
HERE="$(cd "$(dirname "$SOURCE")" && pwd -P)"
REPO_ROOT="$(cd "$HERE/../.." && pwd -P)"
CONFIG="$HERE/config.json"

TASK_ID="${1:?usage: dispatch.sh TASK-XXX branch-slug summary}"
SLUG="${2:?usage: dispatch.sh TASK-XXX branch-slug summary}"
SUMMARY="${3:?usage: dispatch.sh TASK-XXX branch-slug summary}"

SUBDIR="$(jq -r '.repo_subdir' "$CONFIG")"
MAIN="$(jq -r '.main_branch' "$CONFIG")"
WT_ROOT="${WORKTREE_ROOT:-$(jq -r '.worktree_root' "$CONFIG")}"
WT_ROOT="${WT_ROOT/#\~/$HOME}"
LIVE="${TCG_LIVE_DIR:-$(jq -r '.live_dir' "$CONFIG")}"
LIVE="${LIVE/#\~/$HOME}"

BRANCH="task/${TASK_ID}-${SLUG}"
WT="$WT_ROOT/${TASK_ID}-${SLUG}"
BASE="$(git -C "$REPO_ROOT" rev-parse --short "$MAIN")"

mkdir -p "$WT_ROOT" "$HERE/runs"
git -C "$REPO_ROOT" fetch --all --prune >/dev/null 2>&1 || true
git -C "$REPO_ROOT" worktree add -B "$BRANCH" "$WT" "$BASE" >/dev/null

# Seed only the live code and tests into the worktree. Repo docs and
# governance stay at the committed (sanitized) version so the baseline is clean.
for f in bot.py bot_async.py belief.py ismcts.py ruflo_tcg.py scoring.py wr_report.py pytest.ini restart_when_idle.sh; do
  if [ -f "$LIVE/$f" ]; then
    cp -a "$LIVE/$f" "$WT/$SUBDIR/$f"
  fi
done
if [ -d "$LIVE/tests" ]; then
  mkdir -p "$WT/$SUBDIR/tests"
  rsync -a --exclude '__pycache__' "$LIVE/tests/" "$WT/$SUBDIR/tests/"
fi

mkdir -p "$WT/$SUBDIR/evidence"
jq -n \
  --arg task_id "$TASK_ID" \
  --arg branch "$BRANCH" \
  --arg base_commit "$BASE" \
  --arg worktree "$WT" \
  --arg subdir "$SUBDIR" \
  --arg live "$LIVE" \
  --arg summary "$SUMMARY" \
  '{task_id:$task_id,branch:$branch,base_commit:$base_commit,worktree:$worktree,subdir:$subdir,live_dir:$live,summary:$summary,dispatched_at:(now|todateiso8601)}' \
  > "$HERE/runs/$TASK_ID.json"

echo "TASK      $TASK_ID"
echo "BRANCH    $BRANCH"
echo "BASE      $BASE"
echo "WORKTREE  $WT"
echo "SUBDIR    $WT/$SUBDIR"
echo "RUN       $HERE/runs/$TASK_ID.json"
echo "Next: dispatch the worker into $WT/$SUBDIR, then run verify.sh."
