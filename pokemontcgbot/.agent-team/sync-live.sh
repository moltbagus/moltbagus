#!/usr/bin/env bash
# Copy verified files from a task worktree into the live bot directory.
# Usage: ./.agent-team/sync-live.sh TASK-XXX --yes
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
HERE="$(cd "$(dirname "$SOURCE")" && pwd -P)"
CONFIG="$HERE/config.json"

TASK_ID="${1:?usage: sync-live.sh TASK-XXX --yes}"
CONFIRM="${2:-}"
[ "$CONFIRM" = "--yes" ] || { echo "refusing to touch live without --yes" >&2; exit 2; }

RUN="$HERE/runs/$TASK_ID.json"
[ -f "$RUN" ] || { echo "no run record for $TASK_ID" >&2; exit 2; }

WT="$(jq -r '.worktree' "$RUN")"
SUBDIR="$(jq -r '.subdir' "$RUN")"
LIVE="$(jq -r '.live_dir' "$RUN")"

for f in arena_config.py telemetry.py bot.py bot_async.py belief.py ismcts.py ruflo_tcg.py scoring.py wr_report.py pytest.ini GOVERNANCE.md PRD.md spec.md restart_when_idle.sh; do
  if [ -f "$WT/$SUBDIR/$f" ]; then
    cp -a "$WT/$SUBDIR/$f" "$LIVE/$f"
  fi
done
if [ -d "$WT/$SUBDIR/tests" ]; then
  mkdir -p "$LIVE/tests"
  rsync -a --exclude '__pycache__' "$WT/$SUBDIR/tests/" "$LIVE/tests/"
fi
if [ -d "$WT/$SUBDIR/docs" ]; then
  mkdir -p "$LIVE/docs"
  rsync -a "$WT/$SUBDIR/docs/" "$LIVE/docs/"
fi
echo "synced $TASK_ID -> $LIVE"
