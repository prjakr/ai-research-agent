"""
Amazon入荷監視モジュール
Keepa API（公式）のみ使用 - 月250リクエスト無料

※ Amazon直接スクレイピングはAmazon利用規約で禁止されているため実装しない
  参照: https://www.amazon.co.jp/gp/help/customer/display.html?nodeId=201909000

Keepa APIキー取得: https://keepa.com/
  - 無料プラン: 月250リクエスト
  - 1ASINにつき1リクエスト消費

config.json の設定:
  "amazon_monitor": {
    "asins": ["B0CXXXXX", "B0YYYYYYY"],  ← 監視する商品のASIN
    "keepa_api_key": "YOUR_KEY",          ← Keepaで取得したAPIキー
    "enabled": true
  }
"""
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

# ── データベース ──────────────────────────────────────────
def init_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS amazon_items (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            asin         TEXT NOT NULL,
            name         TEXT,
            price        TEXT,
            in_stock     INTEGER,
            checked_at   TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def get_last_stock(conn, asin: str):
    row = conn.execute(
        "SELECT in_stock, price FROM amazon_items WHERE asin=? ORDER BY checked_at DESC LIMIT 1",
        (asin,)
    ).fetchone()
    return row  # (in_stock, price) or None

def save_stock(conn, asin: str, name: str, price: str, in_stock: bool):
    conn.execute(
        "INSERT INTO amazon_items (asin, name, price, in_stock, checked_at) VALUES (?,?,?,?,?)",
        (asin, name, price, 1 if in_stock else 0, datetime.now().isoformat())
    )
    conn.commit()

# ── Keepa API（公式・月250回無料）──────────────────────────
def check_keepa(asin: str, api_key: str) -> dict:
    """
    Keepa公式APIで在庫・価格を確認
    ドキュメント: https://keepa.com/#!api
    domain=5 = Amazon.co.jp
    """
    try:
        url = (
            f"https://api.keepa.com/product"
            f"?key={api_key}&domain=5&asin={asin}&stats=1"
        )
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        products = data.get("products", [])
        if not products:
            return {"error": "商品が見つかりません"}

        product = products[0]
        title = product.get("title", "不明")

        # csv[0] = Amazon直販の価格履歴
        # 値が -1 のときは在庫なし/取り扱いなし
        csv_data = product.get("csv", [])
        amazon_price_history = csv_data[0] if csv_data else []

        current_price = None
        in_stock = False

        if amazon_price_history and len(amazon_price_history) >= 2:
            # Keepaは [timestamp, price, timestamp, price, ...] の形式
            # 最後の price 値を取得
            latest_price = amazon_price_history[-1]
            if latest_price != -1:
                current_price = latest_price / 100  # Keepaは100倍で格納
                in_stock = True

        return {
            "title": title,
            "in_stock": in_stock,
            "price": f"¥{int(current_price):,}" if current_price else "価格不明",
            "url": f"https://www.amazon.co.jp/dp/{asin}"
        }

    except requests.HTTPError as e:
        if e.response.status_code == 400:
            return {"error": "Keepa APIキーが無効か月間制限に達しています"}
        return {"error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        return {"error": str(e)}

# ── Discord通知 ───────────────────────────────────────────
def send_discord_amazon(webhook_url: str, asin: str, info: dict, change_type: str):
    if change_type == "restock":
        title_text = f"🛒 入荷アラーム！ {info.get('title','')[:40]}"
        color = 0x00C853
        desc = f"**在庫が復活しました！**\n価格: {info.get('price', '不明')}"
    else:
        title_text = f"📦 在庫切れ: {info.get('title','')[:40]}"
        color = 0xB71C1C
        desc = "在庫がなくなりました"

    embed = {
        "title": title_text,
        "description": desc,
        "url": info.get("url", f"https://www.amazon.co.jp/dp/{asin}"),
        "color": color,
        "fields": [
            {"name": "ASIN", "value": asin, "inline": True},
            {"name": "確認時刻", "value": datetime.now().strftime("%Y-%m-%d %H:%M"), "inline": True}
        ],
        "footer": {"text": "情報リサーチエージェント Amazon監視（Keepa API）🛒"}
    }
    requests.post(webhook_url, json={"embeds": [embed]}, timeout=10)

# ── メイン処理 ────────────────────────────────────────────
def run_amazon_monitor():
    config = load_config()
    amazon_cfg = config.get("amazon_monitor", {})

    if not amazon_cfg.get("enabled", False):
        print("[Amazon監視] config.json で enabled: true に設定してください")
        return

    keepa_key = amazon_cfg.get("keepa_api_key", "")
    if not keepa_key or keepa_key == "YOUR_KEEPA_API_KEY_HERE":
        print("[Amazon監視] Keepa APIキーが必要です")
        print("  取得先: https://keepa.com/  (無料プランで月250回)")
        print("  config.json の keepa_api_key に設定してください")
        return

    asins = amazon_cfg.get("asins", [])
    if not asins:
        print("[Amazon監視] config.json の asins にASINを追加してください")
        print('  例: "asins": ["B0XXXXXXXXX", "B0YYYYYYYYY"]')
        return

    webhook_url = config["discord"]["webhook_url"]
    db_path = config["storage"]["db_path"]
    conn = init_db(db_path)

    print(f"[Amazon監視] {len(asins)}件チェック中... (Keepa API) ({datetime.now().strftime('%H:%M:%S')})")

    for asin in asins:
        try:
            print(f"  チェック: {asin}")
            info = check_keepa(asin, keepa_key)

            if "error" in info:
                print(f"  [ERROR] {info['error']}")
                continue

            in_stock = info.get("in_stock", False)
            price = info.get("price", "不明")
            title = info.get("title", asin)

            last = get_last_stock(conn, asin)
            save_stock(conn, asin, title, price, in_stock)

            stock_str = "在庫あり" if in_stock else "在庫なし"
            print(f"  → {title[:30]} | {price} | {stock_str}")

            if last is not None:
                last_in_stock = bool(last[0])
                if not last_in_stock and in_stock:
                    print(f"  ⚡ 入荷検知!")
                    send_discord_amazon(webhook_url, asin, info, "restock")

            time.sleep(2)

        except Exception as e:
            print(f"  [ERROR] {asin}: {e}")

    conn.close()

if __name__ == "__main__":
    run_amazon_monitor()
