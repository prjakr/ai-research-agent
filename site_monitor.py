"""
サイト変化検知モジュール
指定したサイトの特定部分が変化したらDiscordに通知する
Claude APIは一切使用しない → トークン消費ゼロ
"""
import hashlib
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── 設定読み込み ──────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

# ── データベース初期化 ─────────────────────────────────────
def init_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS site_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            url         TEXT NOT NULL,
            selector    TEXT,
            content_hash TEXT NOT NULL,
            content_text TEXT,
            checked_at  TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def get_last_snapshot(conn, name: str):
    row = conn.execute(
        "SELECT content_hash, content_text FROM site_snapshots WHERE name=? ORDER BY checked_at DESC LIMIT 1",
        (name,)
    ).fetchone()
    return row  # (hash, text) or None

def save_snapshot(conn, name: str, url: str, selector: str, content_hash: str, content_text: str):
    conn.execute(
        "INSERT INTO site_snapshots (name, url, selector, content_hash, content_text, checked_at) VALUES (?,?,?,?,?,?)",
        (name, url, selector, content_hash, content_text, datetime.now().isoformat())
    )
    conn.commit()

# ── サイトコンテンツ取得 ──────────────────────────────────
def fetch_content(url: str, selector: str | None) -> tuple[str, str]:
    """
    URLからコンテンツを取得し (hash, text) を返す
    selectorがあればその部分だけ、なければbody全体
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    if selector:
        target = soup.select_one(selector)
        text = target.get_text(strip=True) if target else ""
    else:
        text = soup.get_text(strip=True)

    content_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
    return content_hash, text

# ── Discord通知 ───────────────────────────────────────────
def send_discord_alert(webhook_url: str, name: str, url: str, message: str = None):
    embed = {
        "title": f"🔔 変化検知: {name}",
        "description": message or "指定したページに変化が検出されました。",
        "url": url,
        "color": 0xFF6B35,  # オレンジ
        "fields": [
            {"name": "URL", "value": url, "inline": False},
            {"name": "検知時刻", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "inline": True}
        ],
        "footer": {"text": "情報リサーチエージェント 📡"}
    }
    payload = {"embeds": [embed]}
    resp = requests.post(webhook_url, json=payload, timeout=10)
    resp.raise_for_status()
    print(f"  [Discord] 通知送信完了: {name}")

def send_discord_info(webhook_url: str, message: str, color: int = 0x00BFFF):
    """一般的な情報通知"""
    payload = {"content": message}
    requests.post(webhook_url, json=payload, timeout=10)

# ── Webhook取得（複数チャンネル対応）─────────────────────
def get_webhook(config, channel_key: str) -> str:
    channels = config.get("discord", {}).get("channels", {})
    if channels:
        ch = channels.get(channel_key) or channels.get("default") or next(iter(channels.values()), {})
        return ch.get("webhook_url", "")
    return config.get("discord", {}).get("webhook_url", "")

# ── 前回チェック時刻（頻度制御）──────────────────────────
def get_last_checked_time(conn, name: str):
    row = conn.execute(
        "SELECT checked_at FROM site_snapshots WHERE name=? ORDER BY checked_at DESC LIMIT 1",
        (name,)
    ).fetchone()
    return row[0] if row else None

# ── メイン監視処理 ─────────────────────────────────────────
def run_site_monitor():
    config = load_config()
    monitor_cfg = config["site_monitor"]
    db_path = config["storage"]["db_path"]

    conn = init_db(db_path)

    targets = [t for t in monitor_cfg["targets"] if t.get("enabled", True)]
    print(f"[サイト監視] {len(targets)}件のサイトをチェック中... ({datetime.now().strftime('%H:%M:%S')})")

    changed_count = 0
    error_count = 0

    from datetime import timedelta
    now = datetime.now()

    for target in targets:
        name     = target["name"]
        url      = target["url"]
        selector = target.get("selector")
        interval = int(target.get("check_interval_minutes", 30))
        channel  = target.get("discord_channel", "default")
        webhook_url = get_webhook(config, channel)

        # 頻度チェック：前回から interval 分未満ならスキップ
        last_time = get_last_checked_time(conn, name)
        if last_time:
            try:
                elapsed = (now - datetime.fromisoformat(last_time)).total_seconds() / 60
                if elapsed < interval:
                    print(f"  スキップ: {name} (次回まで{int(interval - elapsed)}分)")
                    continue
            except Exception:
                pass

        try:
            print(f"  チェック: {name}")
            new_hash, new_text = fetch_content(url, selector)
            last = get_last_snapshot(conn, name)

            if last is None:
                save_snapshot(conn, name, url, selector or "", new_hash, new_text[:2000])
                print(f"  → 初回登録完了")

            elif last[0] != new_hash:
                print(f"  → 変化検知!")
                save_snapshot(conn, name, url, selector or "", new_hash, new_text[:2000])
                if webhook_url:
                    send_discord_alert(webhook_url, name, url)
                changed_count += 1
            else:
                print(f"  → 変化なし")

            time.sleep(2)

        except Exception as e:
            print(f"  [ERROR] {name}: {e}")
            error_count += 1

    conn.close()

    # サマリー通知
    if changed_count > 0 or error_count > 0:
        summary = f"📊 監視完了: 変化{changed_count}件 / エラー{error_count}件"
        print(summary)

if __name__ == "__main__":
    run_site_monitor()
