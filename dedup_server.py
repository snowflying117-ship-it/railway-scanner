#!/usr/bin/env python3
"""去重服务器 - 提供已采来源列表，接收新来源"""
import json, os
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

DEDUP_FILE = "/app/data/existing_sources.json"

def load_dedup():
    try:
        return json.load(open(DEDUP_FILE))
    except:
        return {"sources": [], "addresses": []}

def save_dedup(data):
    os.makedirs(os.path.dirname(DEDUP_FILE), exist_ok=True)
    json.dump(data, open(DEDUP_FILE, "w"))

class DedupHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """获取已采来源列表"""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        data = load_dedup()
        self.wfile.write(json.dumps(data).encode())
    
    def do_POST(self):
        """接收新来源"""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        new_data = json.loads(body)
        
        existing = load_dedup()
        existing["sources"].extend(new_data.get("sources", []))
        existing["addresses"].extend(new_data.get("addresses", []))
        existing["sources"] = list(set(existing["sources"]))
        existing["addresses"] = list(set(existing["addresses"]))
        save_dedup(existing)
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok",
            "sources": len(existing["sources"]),
            "addresses": len(existing["addresses"])
        }).encode())
    
    def log_message(self, *a):
        pass

if __name__ == "__main__":
    port = int(os.environ.get("DEDUP_PORT", 8081))
    server = HTTPServer(("0.0.0.0", port), DedupHandler)
    print(f"Dedup server running on port {port}")
    server.serve_forever()
