#!/bin/bash
export RADAR_DB_PATH="/app/data/radar.db"
mkdir -p /app/data /app/logs

while true; do
  echo "[$(date -Iseconds)] Starting Radar..."
  python3 -u radar.py run-all 2>&1
  echo "[$(date -Iseconds)] Done. Sleeping 2 hours..."
  sleep 7200
done
