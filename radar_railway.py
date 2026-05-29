#!/usr/bin/env python3
"""Railway 版 radar - 使用内存数据库，每次运行后导出结果"""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))

# 用内存数据库
os.environ['RADAR_DB_PATH'] = ':memory:'

import radar
from datetime import datetime, timezone

def main():
    config_path = os.path.join(os.path.dirname(__file__), 'config_railway.json')
    cfg = json.load(open(config_path))
    
    conn = radar.connect_db()
    radar.init_schema(conn)
    
    print(f"[{datetime.now(timezone.utc).isoformat()}] Railway Radar started")
    
    # 采集
    print("=== 采集 StackExchange ===")
    n = radar.collect_stackexchange(conn.cursor(), cfg)
    print(f"  StackExchange: {n} pages")
    
    print("=== 采集 GitHub ===")
    n = radar.collect_github(conn.cursor(), cfg)
    print(f"  GitHub: {n} pages")
    
    print("=== 采集 BitcoinWiki ===")
    n = radar.collect_bitcoin_wiki(conn.cursor(), cfg)
    print(f"  BitcoinWiki: {n} pages")
    
    # 查余额
    print("=== 查余额 ===")
    n = radar.check_balances(conn.cursor(), cfg)
    print(f"  检查: {n} 个地址")
    
    # 统计
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM sources")
    sources = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM btc_addresses")
    addrs = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM address_status WHERE balance_sats > 0")
    funded = c.fetchone()[0]
    
    # 输出结果（Railway 日志可见）
    print(f"\n=== 本轮结果 ===")
    print(f"来源: {sources}")
    print(f"地址: {addrs}")
    print(f"有余额: {funded}")
    
    # 有余额的地址输出到日志
    c.execute("""
        SELECT ba.address, as2.balance_sats, as2.tx_count
        FROM btc_addresses ba
        JOIN address_status as2 ON as2.address_id = ba.id
        WHERE as2.balance_sats > 0
        ORDER BY as2.balance_sats DESC
    """)
    for addr, bal, tx in c.fetchall():
        print(f"  FUNDED: {addr} {bal/1e8:.8f} BTC ({tx} tx)")
    
    conn.close()
    print(f"[{datetime.now(timezone.utc).isoformat()}] Done")

if __name__ == "__main__":
    main()
