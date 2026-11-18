#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
KEY=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.arena-credentials')))['apiKey'])")
for i in $(seq 1 120); do
  active=$(curl -s --max-time 10 -H "x-arena-api-key: $KEY" "https://arena.dev.fun/api/arena/tcg/pending-actions?competitionId=cmw99opb57gssgfb7rj39a1o1" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('activeMatches',[])))" 2>/dev/null || echo "1")
  if [ "$active" = "0" ]; then
    systemctl --user restart tcg-bot.service
    echo "restarted systemd service at $(date -Is)" >> restart.log
    exit 0
  fi
  sleep 10
done
echo "timeout waiting for active match" >> restart.log
exit 1
