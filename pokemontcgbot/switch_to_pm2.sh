#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
LOG="switch-to-pm2.log"
KEY=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.arena-credentials')))['apiKey'])")
CID=$(python3 -c "from arena_config import COMPETITION_ID; print(COMPETITION_ID)")
for i in $(seq 1 180); do
  ACTIVE=$(curl -s --max-time 10 -H "x-arena-api-key: $KEY" "https://arena.dev.fun/api/arena/tcg/pending-actions?competitionId=$CID" | python3 -c "import sys,json;print(len(json.load(sys.stdin).get('activeMatches',[])))" 2>/dev/null || echo "1")
  if [ "$ACTIVE" != "0" ]; then
    sleep 10
    continue
  fi
  echo "$(date -Is) active=0; stopping systemd service" >> "$LOG"
  systemctl --user stop tcg-bot.service || true
  systemctl --user disable tcg-bot.service >> "$LOG" 2>&1 || true
  sleep 2
  LEFT=$(pgrep -af "python3 -u bot(_async)?\.py" | grep -v "bash -c" || true)
  if [ -n "$LEFT" ]; then
    echo "$(date -Is) BLOCKED: existing poller $LEFT" >> "$LOG"
    exit 3
  fi
  pm2 start ecosystem.config.cjs >> "$LOG" 2>&1
  pm2 save >> "$LOG" 2>&1
  echo "$(date -Is) pm2 started" >> "$LOG"
  pm2 list >> "$LOG" 2>&1
  exit 0
done
echo "$(date -Is) timeout waiting for activeMatches=0" >> "$LOG"
exit 1
