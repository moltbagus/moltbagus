#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Season identity comes from arena_config, never from a literal here. This
# script once carried the PREVIOUS season's competition id, so its "is a match
# running?" gate read 0 active matches while the live season still had one, and
# the restart killed a match in progress.
COMPETITION_ID=$(python3 -c "import arena_config; print(arena_config.COMPETITION_ID)")
BASE_URL=$(python3 -c "import arena_config; print(arena_config.BASE_URL)")
KEY=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.arena-credentials')))['apiKey'])")
for i in $(seq 1 120); do
  active=$(curl -s --max-time 10 -H "x-arena-api-key: $KEY" "$BASE_URL/tcg/pending-actions?competitionId=$COMPETITION_ID" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('activeMatches',[])))" 2>/dev/null || echo "1")
  if [ "$active" = "0" ]; then
    systemctl --user restart tcg-bot.service
    echo "restarted systemd service at $(date -Is) (competition $COMPETITION_ID)" >> restart.log
    exit 0
  fi
  sleep 10
done
echo "timeout waiting for active match" >> restart.log
exit 1
