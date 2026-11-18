#!/usr/bin/env bash
# Run the acceptance command in the task worktree and record check.record.
# Usage: ./.agent-team/verify.sh TASK-XXX "title" "command" "expected"
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
HERE="$(cd "$(dirname "$SOURCE")" && pwd -P)"
REPO_ROOT="$(cd "$HERE/../.." && pwd -P)"
CONFIG="$HERE/config.json"

TASK_ID="${1:?usage: verify.sh TASK-XXX title command expected}"
TITLE="${2:?usage: verify.sh TASK-XXX title command expected}"
CHECK_CMD="${3:?usage: verify.sh TASK-XXX title command expected}"
EXPECTED="${4:?usage: verify.sh TASK-XXX title command expected}"

RUN="$HERE/runs/$TASK_ID.json"
[ -f "$RUN" ] || { echo "no run record for $TASK_ID: $RUN" >&2; exit 2; }

WT="$(jq -r '.worktree' "$RUN")"
SUBDIR="$(jq -r '.subdir' "$RUN")"
WORKDIR="$WT/$SUBDIR"
[ -d "$WORKDIR" ] || { echo "worktree missing: $WORKDIR" >&2; exit 2; }

COMMIT="$(git -C "$WT" rev-parse --short HEAD)"
DIRTY="$(git -C "$WT" status --porcelain | wc -l | tr -d ' ')"
PYVER="$(python3 --version 2>&1 | cut -d' ' -f2)"

set +e
OBSERVED="$(cd "$WORKDIR" && bash -lc "$CHECK_CMD" 2>&1)"
EXIT_CODE=$?
set -e

STATUS="PASS"
[ "$EXIT_CODE" -ne 0 ] && STATUS="FAIL"

mkdir -p "$WORKDIR/evidence"
EVIDENCE="$WORKDIR/evidence/${TASK_ID}-verify.json"
jq -n \
  --arg task "$TASK_ID" \
  --arg requirement "$TITLE" \
  --arg commit "$COMMIT" \
  --arg worktree "$WT" \
  --arg workdir "$WORKDIR" \
  --arg dirty "$DIRTY" \
  --arg execution "$CHECK_CMD" \
  --arg expected "$EXPECTED" \
  --arg observed "$OBSERVED" \
  --arg status "$STATUS" \
  --arg environment "python3 $PYVER" \
  --argjson exit_code "$EXIT_CODE" \
  '{task:$task,requirement:$requirement,commit:$commit,worktree:$worktree,workdir:$workdir,dirty_files:($dirty|tonumber),environment:$environment,execution:$execution,expected:$expected,observed:$observed,exit_code:$exit_code,status:$status,recorded_at:(now|todateiso8601)}' \
  > "$EVIDENCE"

echo "TASK       $TASK_ID"
echo "COMMIT     $COMMIT"
echo "DIRTY      $DIRTY files"
echo "EXIT_CODE  $EXIT_CODE"
echo "STATUS     $STATUS"
echo "EVIDENCE   $EVIDENCE"
echo "--- observed ---"
echo "$OBSERVED"
exit "$EXIT_CODE"
