"""
情報リサーチエージェント メインランチャー
Claude Codeのスケジュールタスクから呼ばれる
コマンドライン引数で実行モードを切り替え
"""
import sys
import io
import argparse
from pathlib import Path

# Windows CP932対策: 標準出力をUTF-8に統一
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

def main():
    parser = argparse.ArgumentParser(description="情報リサーチエージェント")
    parser.add_argument(
        "mode",
        nargs="?",
        default="all",
        choices=["all", "site", "rss", "twitter", "amazon", "test"],
        help="実行モード (all=全て, site=サイト監視, rss=RSS収集, twitter=Twitter監視, amazon=Amazon監視, test=テスト)"
    )
    args = parser.parse_args()

    print(f"=" * 50)
    print(f"  情報リサーチエージェント 起動")
    print(f"  モード: {args.mode}")
    print(f"=" * 50)

    if args.mode in ("all", "site"):
        print("\n[1/3] サイト変化検知を実行中...")
        from site_monitor import run_site_monitor
        run_site_monitor()

    if args.mode in ("all", "rss"):
        print("\n[2/3] RSS情報収集を実行中...")
        from rss_collector import run_rss_collector
        run_rss_collector()

    if args.mode in ("all", "twitter"):
        print("\n[3/3] Twitter監視を実行中...")
        from twitter_monitor import run_twitter_monitor
        run_twitter_monitor()

    if args.mode == "amazon":
        print("\n[Amazon監視] 実行中...")
        try:
            from amazon_monitor import run_amazon_monitor
            run_amazon_monitor()
        except ImportError:
            print("  amazon_monitor.py はまだ未設定です")

    if args.mode == "test":
        print("\n[接続テスト] Discord Webhookをテスト中...")
        import json, requests
        config = json.load(open(Path(__file__).parent / "config.json", encoding="utf-8"))
        webhook_url = config["discord"]["webhook_url"]
        if webhook_url == "YOUR_DISCORD_WEBHOOK_URL_HERE":
            print("  ❌ config.json の webhook_url を設定してください")
        else:
            payload = {
                "content": "✅ 情報リサーチエージェント 接続テスト成功！\n設定が正しく完了しています。"
            }
            resp = requests.post(webhook_url, json=payload, timeout=10)
            if resp.status_code in (200, 204):
                print("  ✅ Discord通知テスト成功！")
            else:
                print(f"  ❌ Discord通知失敗: {resp.status_code}")

    # ── クラウド同期 (GITHUB_GIST_ID が設定されている場合のみ) ──────────
    _sync_to_cloud(args.mode)

    print("\n完了")


def _sync_to_cloud(mode: str):
    """収集した結果を GitHub Gist に同期する（クラウドGUI用）"""
    from cloud_storage import get_storage, IS_CLOUD
    if not IS_CLOUD:
        return
    cs = get_storage()
    if not cs:
        return
    print("\n[Cloud Sync] GitHub Gist に同期中...")

    # ① SQLite から最新ニュースを読み出して Gist に書き込む
    try:
        import sqlite3, json
        config  = json.load(open(Path(__file__).parent / "config.json", encoding="utf-8"))
        db_path = config.get("storage", {}).get("db_path", "")
        if db_path:
            conn  = sqlite3.connect(db_path)
            rows  = conn.execute(
                "SELECT id, feed_name, category, title, title_ja, url, published, created_at "
                "FROM rss_items ORDER BY created_at DESC LIMIT 500"
            ).fetchall()
            conn.close()
            items = [{"id": r[0], "feed": r[1], "category": r[2],
                      "title": r[3], "title_ja": r[4], "url": r[5],
                      "published": (r[6] or "")[:10], "created_at": (r[7] or "")[:16]}
                     for r in rows]
            if cs._write("news.json", items):
                print(f"  ✅ ニュース {len(items)} 件を同期しました")
    except Exception as e:
        print(f"  ⚠️ ニュース同期失敗: {e}")

    # ② サイト監視スナップショットを同期
    try:
        import sqlite3, json
        config  = json.load(open(Path(__file__).parent / "config.json", encoding="utf-8"))
        db_path = config.get("storage", {}).get("db_path", "")
        if db_path:
            conn  = sqlite3.connect(db_path)
            rows  = conn.execute(
                "SELECT name, url, checked_at FROM site_snapshots ORDER BY checked_at DESC"
            ).fetchall()
            conn.close()
            seen, snaps = {}, []
            for r in rows:
                if r[0] not in seen:
                    seen[r[0]] = True
                    snaps.append({"name": r[0], "url": r[1], "last_checked": (r[2] or "")[:16]})
            if cs._write("snapshots.json", snaps):
                print(f"  ✅ スナップショット {len(snaps)} 件を同期しました")
    except Exception as e:
        print(f"  ⚠️ スナップショット同期失敗: {e}")

    # ③ 設定ファイルを同期（ローカルの config.json → Gist）
    try:
        cfg = json.load(open(Path(__file__).parent / "config.json", encoding="utf-8"))
        if cs.write_config(cfg):
            print("  ✅ 設定ファイルを同期しました")
    except Exception as e:
        print(f"  ⚠️ 設定同期失敗: {e}")

    print("[Cloud Sync] 完了")

if __name__ == "__main__":
    main()
