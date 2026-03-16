"""
Twitter/X 監視モジュール
Nitter（オープンソースX代替フロントエンド）のRSSを使用
公開アカウントの個人・非商用リサーチ目的のみ使用してください

注意: Nitterは非公式のXフロントエンドです
      公式X APIを使用する場合は有料プランが必要です
      インスタンスが不安定な場合があります
"""
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import feedparser
import requests

BASE_DIR    = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"

# 公開Nitterインスタンス（順番に試す）
NITTER_INSTANCES = [
    "nitter.poast.org",
    "xcancel.com",
    "nitter.privacydev.net",
    "nitter.net",
]

def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)

def get_webhook(config, channel_key: str) -> str:
    channels = config.get("discord", {}).get("channels", {})
    if not channels:
        return config.get("discord", {}).get("webhook_url", "")
    ch = channels.get(channel_key) or channels.get("default") or next(iter(channels.values()), {})
    return ch.get("webhook_url", "")

# ── DB ─────────────────────────────────────────────────────────────
def init_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rss_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_name  TEXT NOT NULL,
            category   TEXT,
            title      TEXT NOT NULL,
            title_ja   TEXT,
            url        TEXT UNIQUE,
            summary    TEXT,
            published  TEXT,
            notified   INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def item_exists(conn, url: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM rss_items WHERE url=?", (url,)
    ).fetchone() is not None

def save_item(conn, feed_name, title, url, summary, published):
    conn.execute(
        """INSERT OR IGNORE INTO rss_items
           (feed_name, category, title, url, summary, published, notified, created_at)
           VALUES (?,?,?,?,?,?,1,?)""",
        (feed_name, "twitter_monitor", title, url,
         (summary or "")[:500], published, datetime.now().isoformat())
    )
    conn.commit()

# ── Nitter RSS fetch ───────────────────────────────────────────────
def fetch_nitter_rss(handle: str) -> list:
    """複数インスタンスを順番に試してRSSエントリを取得"""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)"}
    for instance in NITTER_INSTANCES:
        url = f"https://{instance}/{handle}/rss"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue
            parsed = feedparser.parse(r.text)
            if parsed.entries:
                print(f"  [{handle}] {instance} で {len(parsed.entries)}件取得")
                return parsed.entries
        except Exception as e:
            print(f"  [{handle}] {instance} 失敗: {e}")
            continue
    print(f"  [{handle}] 全インスタンス失敗")
    return []

# ── Discord通知 ────────────────────────────────────────────────────
def send_discord_twitter(webhook_url: str, items: list, handle: str):
    if not items or not webhook_url:
        return
    fields = []
    for it in items[:5]:
        title = (it.get("title") or "")[:80]
        url   = it.get("url", "")
        pub   = (it.get("published") or "")[:10]
        fields.append({
            "name":   title,
            "value":  f"[ツイートを見る]({url})" + (f"\n📅 {pub}" if pub else ""),
            "inline": False
        })
    embed = {
        "title":  f"&#120143; @{handle} の新しいツイート ({len(items)}件)",
        "color":  0x1D9BF0,
        "fields": fields,
        "footer": {"text": f"情報リサーチエージェント | {datetime.now().strftime('%Y-%m-%d %H:%M')}"}
    }
    requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)

# ── メイン ─────────────────────────────────────────────────────────
def run_twitter_monitor():
    config  = load_config()
    db_path = config.get("storage", {}).get("db_path", "")
    conn    = init_db(db_path)

    accounts = [
        acc for acc in config.get("twitter_monitor", {}).get("accounts", [])
        if acc.get("enabled", True)
    ]
    if not accounts:
        print("[Twitter] 監視アカウントが登録されていません")
        conn.close()
        return

    print(f"[Twitter] {len(accounts)}アカウントをチェック中... ({datetime.now().strftime('%H:%M:%S')})")

    for acc in accounts:
        handle   = acc.get("handle", "")
        name     = acc.get("name", f"@{handle}")
        channel  = acc.get("discord_channel", "default")
        keywords = [kw.lower() for kw in acc.get("keywords", []) if kw]
        webhook  = get_webhook(config, channel)

        if not handle:
            continue

        print(f"  チェック: @{handle}")
        try:
            entries = fetch_nitter_rss(handle)
            new_items = []

            for entry in entries[:20]:
                url   = getattr(entry, "link", "")
                title = getattr(entry, "title", "")
                if not url or item_exists(conn, url):
                    continue

                # キーワードフィルター
                if keywords and not any(kw in title.lower() for kw in keywords):
                    continue

                summary   = getattr(entry, "summary", "")
                published = getattr(entry, "published", "")
                save_item(conn, name, title, url, summary, published)
                new_items.append({"title": title, "url": url, "published": published})

            if new_items and webhook:
                send_discord_twitter(webhook, new_items, handle)
                print(f"  → {len(new_items)}件の新着を通知")
            else:
                print(f"  → 新着なし")

            time.sleep(2)
        except Exception as e:
            print(f"  [ERROR] @{handle}: {e}")

    conn.close()

if __name__ == "__main__":
    run_twitter_monitor()
