#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
LOG="restart-pm2-when-idle.log"
KEY=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.arena-credentials')))['apiKey'])")
CID=$(python3 -c "from arena_config import COMPETITION_ID; print(COMPETITION_ID)")
for i in $(seq 1 180); do
  ACTIVE=$(curl -s --max-time 10 -H "x-arena-api-key: $KEY" "https://arena.dev.fun/api/arena/tcg/pending-actions?competitionId=$CID" | python3 -c "import sys,json;print(len(json.load(sys.stdin).get('activeMatches',[])))" 2>/dev/null || echo "1")
  if [ "$ACTIVE" != "0" ]; then
    sleep 10
    continue
  fi
  echo "$(date -Is) active=0; restarting pm2 tcg-bot" >> "$LOG"
  pm2 restart tcg-bot >> "$LOG" 2>&1
  pm2 save >> "$LOG" 2>&1
  pm2 list >> "$LOG" 2>&1
  echo "$(date -Is) restart complete" >> "$LOG"
  exit 0
done
echo "$(date -Is) timeout waiting for activeMatches=0" >> "$LOG"
exit 1
