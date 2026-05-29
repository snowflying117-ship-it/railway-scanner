#!/usr/bin/env python3
"""Railway Radar - 黑天鹅资产雷达（Railway 部署版）"""
import json, re, sqlite3, urllib.parse, urllib.request, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("RADAR_DB_PATH", str(BASE / "data" / "radar.db")))

PAT = re.compile(r'\b([13][a-km-zA-HJ-NP-Z1-9]{25,34})\b')

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def http_get_json(url, headers=None):
    h = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())

def extract_addrs(text):
    return list(set(PAT.findall(text)))

def connect_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_schema(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY AUTOINCREMENT,platform TEXT,source_key TEXT UNIQUE,url TEXT,title TEXT,snippet TEXT,collected_at TEXT);
    CREATE TABLE IF NOT EXISTS btc_addresses(id INTEGER PRIMARY KEY AUTOINCREMENT,address TEXT UNIQUE,first_seen_at TEXT,last_seen_at TEXT,source_count INTEGER DEFAULT 1,is_blacklisted INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS address_status(id INTEGER PRIMARY KEY AUTOINCREMENT,address_id INTEGER NOT NULL,checked_at TEXT,funded_txo_sum INTEGER,spent_txo_sum INTEGER,tx_count INTEGER,balance_sats INTEGER,FOREIGN KEY(address_id) REFERENCES btc_addresses(id));
    CREATE TABLE IF NOT EXISTS address_map(source_id INTEGER,address_id INTEGER,FOREIGN KEY(source_id) REFERENCES sources(id),FOREIGN KEY(address_id) REFERENCES btc_addresses(id));
    CREATE TABLE IF NOT EXISTS funded_watchlist AS SELECT * FROM address_status WHERE 0;
    CREATE TABLE IF NOT EXISTS discarded_addresses(address TEXT PRIMARY KEY,latest_balance_sats INTEGER,latest_tx_count INTEGER,last_checked_at TEXT,discard_reason TEXT);
    """)

def iter_keywords(cfg):
    for tier, kws in cfg.get("keyword_tiers", {}).items():
        for kw in kws[:cfg.get("stackexchange", {}).get("max_keywords_per_tier", {}).get(tier, 999)]:
            yield kw

def get_existing_sources(c):
    return set(r[0] for r in c.execute("SELECT source_key FROM sources").fetchall())

def get_existing_addresses(c):
    addrs = set(r[0] for r in c.execute("SELECT address FROM btc_addresses").fetchall())
    try:
        addrs.update(r[0] for r in c.execute("SELECT DISTINCT address FROM address_tool_runs").fetchall())
    except:
        pass
    return addrs

def deduplicate_new_addresses(c, new_addrs, existing):
    fresh = [a for a in new_addrs if a not in existing]
    skipped = len(new_addrs) - len(fresh)
    if skipped > 0:
        print(f"  [去重] 跳过 {skipped} 个已采集地址，新增 {len(fresh)} 个")
    return fresh

def upsert_source(c, platform, source_key, url, title, snippet):
    c.execute("INSERT OR IGNORE INTO sources(platform,source_key,url,title,snippet,collected_at) VALUES(?,?,?,?,?,?)", (platform, source_key, url, title, snippet, now_iso()))
    return c.lastrowid

def upsert_address(c, addr, blacklist):
    if addr in blacklist:
        return None
    c.execute("INSERT INTO btc_addresses(address,first_seen_at,last_seen_at,source_count,is_blacklisted) VALUES(?,?,?,?,0) ON CONFLICT(address) DO UPDATE SET last_seen_at=?,source_count=source_count+1", (addr, now_iso(), now_iso(), 1, now_iso()))
    return c.lastrowid

def map_source_addr(c, sid, aid):
    if sid and aid:
        c.execute("INSERT OR IGNORE INTO address_map(source_id,address_id) VALUES(?,?)", (sid, aid))

def collect_stackexchange(c, cfg):
    if not cfg.get("stackexchange", {}).get("enabled", True):
        return 0
    count = 0
    skipped = 0
    existing = get_existing_addresses(c)
    existing_sources = get_existing_sources(c)
    blacklist = set(cfg.get("address_blacklist", []))
    for site in cfg.get("stackexchange", {}).get("sites", []):
        for kw in iter_keywords(cfg):
            q = urllib.parse.quote(kw)
            pagesize = cfg.get("stackexchange", {}).get("pagesize", 20)
            url = f"https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=activity&title={q}&site={site}&filter=withbody&pagesize={pagesize}"
            try:
                data = http_get_json(url)
            except:
                continue
            for it in data.get("items", []):
                source_key = f"se:{it.get('question_id')}"
                if source_key in existing_sources:
                    skipped += 1
                    continue
                sid = upsert_source(c, "stackexchange", source_key, it.get("link",""), it.get("title",""), (it.get("body_markdown") or it.get("body") or "")[:2000])
                existing_sources.add(source_key)
                text = f"{it.get('title','')}\n{it.get('body_markdown','')}\n{it.get('body','')}"
                raw = extract_addrs(text)
                new = deduplicate_new_addresses(c, raw, existing)
                for a in new:
                    aid = upsert_address(c, a, blacklist)
                    map_source_addr(c, sid, aid)
                    existing.add(a)
                count += 1
    if skipped:
        print(f"  [来源去重] SE 跳过 {skipped} 个已采集页面")
    return count

def collect_github(c, cfg):
    if not cfg.get("github", {}).get("enabled", True):
        return 0
    count = 0
    skipped = 0
    existing = get_existing_addresses(c)
    existing_sources = get_existing_sources(c)
    blacklist = set(cfg.get("address_blacklist", []))
    for q in cfg.get("github", {}).get("queries", []):
        query = urllib.parse.quote(q)
        url = f"https://api.github.com/search/code?q={query}&per_page=20"
        try:
            data = http_get_json(url)
        except:
            continue
        for it in data.get("items", []):
            source_key = f"gh:{it.get('sha')}"
            if source_key in existing_sources:
                skipped += 1
                continue
            repo = it.get("repository", {}).get("full_name", "")
            html_url = it.get("html_url", "")
            sid = upsert_source(c, "github", source_key, html_url, f"{repo}:{it.get('name','')}", it.get("path",""))
            existing_sources.add(source_key)
            text = f"{repo} {it.get('name','')} {it.get('path','')} {html_url}"
            raw = extract_addrs(text)
            new = deduplicate_new_addresses(c, raw, existing)
            for a in new:
                aid = upsert_address(c, a, blacklist)
                map_source_addr(c, sid, aid)
                existing.add(a)
            count += 1
    if skipped:
        print(f"  [来源去重] GitHub 跳过 {skipped} 个已采集文件")
    return count

def collect_bitcoin_wiki(c, cfg):
    if not cfg.get("bitcoin_wiki", {}).get("enabled", False):
        return 0
    count = 0
    skipped = 0
    existing = get_existing_addresses(c)
    existing_sources = get_existing_sources(c)
    blacklist = set(cfg.get("address_blacklist", []))
    max_pages = cfg.get("bitcoin_wiki", {}).get("max_pages_per_keyword", 5)
    for kw in iter_keywords(cfg):
        sr = urllib.parse.quote(kw)
        url = f"https://en.bitcoin.it/w/api.php?action=query&list=search&srsearch={sr}&format=json&srlimit={max_pages}"
        try:
            data = http_get_json(url)
        except:
            continue
        for it in data.get("query", {}).get("search", []):
            title = it.get("title", "")
            source_key = f"bw:{title}"
            if source_key in existing_sources:
                skipped += 1
                continue
            page_url = "https://en.bitcoin.it/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
            sid = upsert_source(c, "bitcoin_wiki", source_key, page_url, title, it.get("snippet",""))
            existing_sources.add(source_key)
            text = f"{title}\n{it.get('snippet','')}"
            raw = extract_addrs(text)
            new = deduplicate_new_addresses(c, raw, existing)
            for a in new:
                aid = upsert_address(c, a, blacklist)
                map_source_addr(c, sid, aid)
                existing.add(a)
            count += 1
    if skipped:
        print(f"  [来源去重] Wiki 跳过 {skipped} 个已采集页面")
    return count

def check_balances(c, cfg):
    if not cfg.get("balance_check", {}).get("enabled", True):
        return 0
    api = cfg.get("balance_check", {}).get("api_base", "https://mempool.space/api/address")
    max_n = cfg.get("balance_check", {}).get("max_addresses_per_run", 100)
    rows = c.execute("SELECT id,address FROM btc_addresses WHERE is_blacklisted=0 ORDER BY last_seen_at DESC LIMIT ?", (max_n,)).fetchall()
    checked = 0
    for aid, addr in rows:
        try:
            d = http_get_json(f"{api}/{addr}")
            funded = d["chain_stats"]["funded_txo_sum"]
            spent = d["chain_stats"]["spent_txo_sum"]
            tx = d["chain_stats"]["tx_count"]
            bal = funded - spent
            existing = c.execute("SELECT balance_sats FROM address_status WHERE address_id=? ORDER BY checked_at DESC LIMIT 1", (aid,)).fetchone()
            if existing and existing[0] == bal:
                continue
            c.execute("INSERT INTO address_status(address_id,checked_at,funded_txo_sum,spent_txo_sum,tx_count,balance_sats) VALUES(?,?,?,?,?,?)", (aid, now_iso(), funded, spent, tx, bal))
            checked += 1
        except:
            continue
        time.sleep(0.3)
    return checked

def report(c):
    lines = [f"# Radar Daily Report {now_iso()[:10]}", ""]
    for platform, cnt in c.execute("SELECT platform, COUNT(*) FROM sources GROUP BY platform"):
        lines.append(f"- {platform}: {cnt} sources")
    total = c.execute("SELECT COUNT(*) FROM btc_addresses").fetchone()[0]
    lines.append(f"- total addresses: {total}")
    c.execute("SELECT ba.address, as2.balance_sats FROM address_status as2 JOIN btc_addresses ba ON ba.id=as2.address_id WHERE as2.balance_sats>0 ORDER BY as2.balance_sats DESC LIMIT 20")
    funded = c.fetchall()
    lines.append(f"- funded addresses: {len(funded)}")
    if funded:
        lines.append("\nTop 20:")
        for addr, bal in funded:
            lines.append(f"- {addr}: {bal/1e8:.8f} BTC")
    text = "\n".join(lines)
    logs = BASE / "logs"
    logs.mkdir(exist_ok=True)
    (logs / f"daily_report_{now_iso()[:10]}.md").write_text(text, encoding="utf-8")
    return text

def run_all(cfg):
    conn = connect_db()
    c = conn.cursor()
    init_schema(c)
    conn.commit()
    print(f"[{now_iso()}] Radar started (DB: {DB_PATH})")
    n = collect_stackexchange(c, cfg)
    print(f"  StackExchange: {n} pages collected")
    conn.commit()
    n = collect_github(c, cfg)
    print(f"  GitHub: {n} pages collected")
    conn.commit()
    n = collect_bitcoin_wiki(c, cfg)
    print(f"  BitcoinWiki: {n} pages collected")
    conn.commit()
    n = check_balances(c, cfg)
    print(f"  Balances checked: {n} addresses")
    conn.commit()
    rpt = report(c)
    print(rpt)
    conn.close()
    print(f"[{now_iso()}] Done")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["init","collect","check-balances","report","run-all"])
    args = p.parse_args()
    cfg = json.load(open(BASE / "config.json"))
    if args.action == "run-all":
        run_all(cfg)
    elif args.action == "init":
        conn = connect_db(); init_schema(conn.cursor()); conn.commit(); conn.close()
    elif args.action == "collect":
        conn = connect_db(); c = conn.cursor(); init_schema(c); conn.commit()
        collect_stackexchange(c, cfg); conn.commit()
        collect_github(c, cfg); conn.commit()
        collect_bitcoin_wiki(c, cfg); conn.commit()
        conn.close()
    elif args.action == "check-balances":
        conn = connect_db(); c = conn.cursor()
        check_balances(c, cfg); conn.commit(); conn.close()
    elif args.action == "report":
        conn = connect_db(); print(report(conn.cursor())); conn.close()
