"""
RSS情報収集モジュール
ローカル: SQLite に保存
クラウド: GitHub Gist (news.json) に保存
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

try:
    from cloud_storage import get_storage, IS_CLOUD
except ImportError:
    IS_CLOUD = False
    def get_storage(): return None

# カテゴリ別の絵文字・色
CATEGORY_STYLE = {
    "manga":        {"emoji": "📚", "color": 0xFF4081,  "label": "漫画・新刊"},
    "anime":        {"emoji": "📺", "color": 0x7C4DFF,  "label": "アニメ情報"},
    "pokemon_card": {"emoji": "⚡", "color": 0xFFD600,  "label": "ポケモンカード"},
    "onepiece_card":{"emoji": "🏴", "color": 0xFF6D00,  "label": "ワンピースカード"},
    "ai_paper":     {"emoji": "🧠", "color": 0x00BCD4,  "label": "AI論文"},
    "ai_news":      {"emoji": "🤖", "color": 0x4CAF50,  "label": "AIニュース"},
    "news":         {"emoji": "📰", "color": 0x607D8B,  "label": "ニュース"},
    "magazine":     {"emoji": "📖", "color": 0xA16207,  "label": "雑誌"},
    "game_news":    {"emoji": "🎮", "color": 0x6366F1,  "label": "ゲーム"},
    "education":    {"emoji": "🎓", "color": 0xFF9800,  "label": "教育情報"},
}

# ── config 読み込み ──────────────────────────────────────
def load_config():
    if IS_CLOUD:
        st = get_storage()
        if st:
            return st.read_config()
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# ── ローカルDB ───────────────────────────────────────────
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feed_last_checked (
            feed_name TEXT PRIMARY KEY,
            last_checked TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def item_exists_db(conn, url: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM rss_items WHERE url=?", (url,)).fetchone())

def save_item_db(conn, feed_name, category, title, url, summary, published):
    conn.execute(
        "INSERT OR IGNORE INTO rss_items (feed_name,category,title,url,summary,published,created_at) VALUES (?,?,?,?,?,?,?)",
        (feed_name, category, title, url, (summary or "")[:500], published, datetime.now().isoformat())
    )
    conn.commit()

def get_last_checked_db(conn, name):
    row = conn.execute("SELECT last_checked FROM feed_last_checked WHERE feed_name=?", (name,)).fetchone()
    return row[0] if row else None

def set_last_checked_db(conn, name):
    conn.execute("INSERT OR REPLACE INTO feed_last_checked (feed_name,last_checked) VALUES (?,?)",
                 (name, datetime.now().isoformat()))
    conn.commit()

# ── クラウド既読管理（Gist の seen_urls.json）───────────
def load_seen_urls(st) -> set:
    data = st._read("seen_urls.json", [])
    return set(data) if isinstance(data, list) else set()

def save_seen_urls(st, seen: set):
    # 最新3000件だけ保持（Gist 容量節約）
    urls = list(seen)[-3000:]
    st._write("seen_urls.json", urls)

# ── Discord通知 ──────────────────────────────────────────
def send_discord_rss(webhook_url: str, items: list, category: str):
    if not items or not webhook_url:
        return
    style = CATEGORY_STYLE.get(category, {"emoji": "📰", "color": 0x607D8B, "label": category})
    for i in range(0, len(items), 5):
        batch = items[i:i+5]
        fields = []
        for item in batch:
            title = (item.get("title_ja") or item["title"])[:80]
            fields.append({
                "name": title,
                "value": f"[記事を開く]({item['url']})" + (
                    f"\n📅 {item.get('published','')[:10]}" if item.get("published") else ""
                ),
                "inline": False
            })
        embed = {
            "title": f"{style['emoji']} {style['label']} - {len(batch)}件の新着",
            "color": style["color"],
            "fields": fields,
            "footer": {"text": f"リサーチAgent | {datetime.now().strftime('%Y-%m-%d %H:%M')}"}
        }
        try:
            requests.post(webhook_url, json={"embeds": [embed]}, timeout=10).raise_for_status()
        except Exception as e:
            print(f"  [通知エラー] {e}")
        time.sleep(1)

def get_webhook(config, channel_key: str) -> str:
    channels = config.get("discord", {}).get("channels", {})
    if channels:
        ch = channels.get(channel_key) or channels.get("default") or next(iter(channels.values()), {})
        return ch.get("webhook_url", "")
    return ""

# ── 最終チェック時刻管理（クラウド用）─────────────────
def load_last_checked_cloud(st) -> dict:
    return st._read("last_checked.json", {})

def save_last_checked_cloud(st, data: dict):
    st._write("last_checked.json", data)

# ── RSS収集メイン ────────────────────────────────────────
def run_rss_collector():
    config = load_config()
    feeds  = [f for f in config.get("rss_feeds", {}).get("feeds", [])
              if f.get("enabled", True) and f.get("url")]

    print(f"[RSS収集] {len(feeds)}フィードをチェック中... ({datetime.now().strftime('%H:%M:%S')})")
    print(f"[モード] {'☁️ クラウド(Gist)' if IS_CLOUD else '💻 ローカル(SQLite)'}")

    now = datetime.now()
    new_items_map: dict[str, dict[str, list]] = {}  # channel -> category -> items
    new_gist_items: list = []  # クラウド用新着アイテム

    if IS_CLOUD:
        st           = get_storage()
        seen_urls    = load_seen_urls(st)
        last_checked = load_last_checked_cloud(st)
        conn = None
    else:
        db_path = config.get("storage", {}).get("db_path", "")
        if not db_path:
            print("[ERROR] DB パスが未設定です (設定タブで設定してください)")
            return
        conn         = init_db(db_path)
        st           = None
        seen_urls    = None
        last_checked = None

    for feed_cfg in feeds:
        name     = feed_cfg["name"]
        url      = feed_cfg["url"]
        category = feed_cfg.get("category", "news")
        channel  = feed_cfg.get("discord_channel", "default")
        notify   = feed_cfg.get("discord_notify", True)   # Discord通知ON/OFF
        interval = int(feed_cfg.get("check_interval_hours", 1))

        # 頻度チェック
        if IS_CLOUD:
            last_time = last_checked.get(name)
        else:
            last_time = get_last_checked_db(conn, name)

        if last_time:
            try:
                elapsed_h = (now - datetime.fromisoformat(last_time)).total_seconds() / 3600
                if elapsed_h < interval:
                    print(f"  スキップ: {name} (次回まで{int((interval - elapsed_h)*60)}分)")
                    continue
            except Exception:
                pass

        try:
            print(f"  取得: {name}")
            parsed    = feedparser.parse(url)
            new_count = 0

            for entry in parsed.entries[:15]:
                item_url = getattr(entry, "link", "")
                if not item_url:
                    continue

                # 既読チェック
                if IS_CLOUD:
                    if item_url in seen_urls:
                        continue
                else:
                    if item_exists_db(conn, item_url):
                        continue

                title     = getattr(entry, "title",     "タイトルなし")
                summary   = getattr(entry, "summary",   "")
                published = getattr(entry, "published", "")

                # 保存
                if IS_CLOUD:
                    seen_urls.add(item_url)
                    gist_item = {
                        "id":         len(new_gist_items) + 1,
                        "feed":       name,
                        "category":   category,
                        "title":      title,
                        "title_ja":   None,
                        "url":        item_url,
                        "published":  published[:10] if published else "",
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                    new_gist_items.append(gist_item)
                else:
                    save_item_db(conn, name, category, title, item_url, summary, published)

                # Discord通知用に保存
                if notify:
                    new_items_map \
                        .setdefault(channel, {}) \
                        .setdefault(category, []) \
                        .append({"title": title, "title_ja": None,
                                 "url": item_url, "published": published})
                new_count += 1

            # 最終チェック時刻を更新
            if IS_CLOUD:
                last_checked[name] = now.isoformat()
            else:
                set_last_checked_db(conn, name)

            print(f"  → {new_count}件の新着")
            time.sleep(0.5)

        except Exception as e:
            print(f"  [ERROR] {name}: {e}")

    # クラウド: Gist に新着を保存
    if IS_CLOUD and st:
        if new_gist_items:
            st.append_news(new_gist_items)
            print(f"\n[Gist] {len(new_gist_items)}件を news.json に保存")
        save_seen_urls(st, seen_urls)
        save_last_checked_cloud(st, last_checked)

    if conn:
        conn.close()

    # Discord通知
    total_new = sum(len(items) for ch in new_items_map.values() for items in ch.values())
    print(f"\n[通知] 合計{total_new}件をDiscordに送信")
    for channel_key, cat_dict in new_items_map.items():
        webhook_url = get_webhook(config, channel_key)
        if not webhook_url:
            print(f"  [SKIP] チャンネル '{channel_key}' のWebhookが未設定")
            continue
        for category, items in cat_dict.items():
            send_discord_rss(webhook_url, items, category)
            print(f"  送信完了: {channel_key}/{category} ({len(items)}件)")
            time.sleep(1)

if __name__ == "__main__":
    run_rss_collector()
