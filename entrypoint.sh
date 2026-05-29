#!/bin/bash
export RADAR_DB_PATH="/app/data/radar.db"
mkdir -p /app/data /app/logs

# 启动 HTTP API（8080 端口，Railway 需要）
python3 -u -c "
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, sqlite3, os
from pathlib import Path

DB_PATH = Path(os.environ.get('RADAR_DB_PATH', '/app/data/radar.db'))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM sources')
            sources = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM btc_addresses')
            addrs = c.fetchone()[0]
            c.execute('SELECT ba.address, as2.balance_sats, as2.tx_count FROM btc_addresses ba JOIN address_status as2 ON as2.address_id = ba.id WHERE as2.balance_sats > 0 ORDER BY as2.balance_sats DESC')
            funded = [{'address': r[0], 'balance_sats': r[1], 'tx_count': r[2]} for r in c.fetchall()]
            conn.close()
            result = {'status': 'ok', 'sources': sources, 'addresses': addrs, 'funded': funded, 'funded_count': len(funded)}
        except Exception as e:
            result = {'status': 'error', 'message': str(e)}
        self.wfile.write(json.dumps(result).encode())
    def log_message(self, *a): pass

port = int(os.environ.get('PORT', 8080))
print(f'API running on port {port}')
HTTPServer(('0.0.0.0', port), Handler).serve_forever()
" &

# 等 API 启动
sleep 2

# 启动雷达循环
while true; do
  echo "[$(date -Iseconds)] Starting Radar..."
  python3 -u radar.py run-all 2>&1
  echo "[$(date -Iseconds)] Done. Sleeping 2 hours..."
  sleep 7200
done
