#!/usr/bin/env bash
# Consulta de cuotas programada (crontab). Deja log en data/logs/odds_cron.log.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/data/logs"
cd "$ROOT/backend" || exit 1
{
  echo "=== $(date -Iseconds)"
  "$ROOT/.venv/bin/python" odds_live.py snapshot --leagues "${1:-E0,SP1,D1,I1,F1}"
} >> "$ROOT/data/logs/odds_cron.log" 2>&1
