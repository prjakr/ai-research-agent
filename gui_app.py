"""
情報リサーチエージェント WebGUI
Flask + Bootstrap 5  /  port 8765
"""
import io, json, socket, sqlite3, subprocess, sys, threading, webbrowser
from pathlib import Path

from flask import Flask, jsonify, render_template, request

try:
    from cloud_storage import get_storage, IS_CLOUD
except ImportError:
    IS_CLOUD = False
    def get_storage(): return None

if sys.stdout and sys.stdout.encoding != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR    = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
app = Flask(__name__)

VERSION = "1.5.0"

# ─── local IP ────────────────────────────────────────────────────────
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()

# ─── config (ローカル or Gist) ────────────────────────────────────────
def load_cfg():
    if IS_CLOUD:
        st = get_storage()
        if st:
            return st.read_config()
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_cfg(cfg):
    if IS_CLOUD:
        st = get_storage()
        if st:
            st.write_config(cfg); return
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def ok(data=None):   return jsonify({"ok": True,  **(data or {})})
def err(msg, c=400): return jsonify({"ok": False, "error": msg}), c

# ─── デフォルトRSSフィード ────────────────────────────────────────────
DEFAULT_FEEDS = [
    {"name": "ITMedia AI+",     "url": "https://www.itmedia.co.jp/aiplus/rss20/index.rdf",   "category": "ai_news",   "check_interval_hours": 1},
    {"name": "Zenn トレンド",    "url": "https://zenn.dev/feed",                               "category": "ai_news",   "check_interval_hours": 3},
    {"name": "ArXiv AI",        "url": "https://arxiv.org/rss/cs.AI",                         "category": "ai_paper",  "check_interval_hours": 12},
    {"name": "ArXiv ML",        "url": "https://arxiv.org/rss/cs.LG",                         "category": "ai_paper",  "check_interval_hours": 12},
    {"name": "コミックナタリー", "url": "https://natalie.mu/comic/feed/news",                   "category": "manga",     "check_interval_hours": 6},
    {"name": "NHKニュース",      "url": "https://www3.nhk.or.jp/rss/news/cat0.xml",            "category": "news",      "check_interval_hours": 1},
    {"name": "TechCrunch Japan", "url": "https://jp.techcrunch.com/feed/",                    "category": "news",      "check_interval_hours": 3},
    {"name": "アニメ!アニメ!",   "url": "https://animeanime.jp/rss20.xml",                     "category": "anime",     "check_interval_hours": 6},
]

# ─── config migration ────────────────────────────────────────────────
def migrate_config():
    cfg = load_cfg(); changed = False
    disc = cfg.setdefault("discord", {})
    if "webhook_url" in disc:
        old = disc.pop("webhook_url"); disc.pop("_comment", None)
        disc.setdefault("channels", {})["default"] = {
            "webhook_url": old, "label": "デフォルト", "enabled": True}
        changed = True
    if "links" not in cfg:
        cfg["links"] = []; changed = True
    # デフォルトフィードを追加（フィードが1件もない場合）
    rss = cfg.setdefault("rss_feeds", {})
    fl  = rss.setdefault("feeds", [])
    if not fl:
        for f in DEFAULT_FEEDS:
            fl.append({**f, "discord_channel": "default", "enabled": True})
        changed = True
    for f in fl:
        if "discord_channel" not in f:   f["discord_channel"] = "default"; changed = True
        if "check_interval_hours" not in f: f["check_interval_hours"] = 1; changed = True
    if "vercel_url" not in cfg:
        cfg["vercel_url"] = ""; changed = True
    for k in ("cloud",):
        if k in cfg: cfg.pop(k); changed = True
    if changed:
        save_cfg(cfg)
        print("[設定] config を更新しました")

# ─── pages ───────────────────────────────────────────────────────────
@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/version")
def version():
    return jsonify({"version": VERSION, "is_cloud": IS_CLOUD})

# ══════════════════════════════════════════════════════════════════════
#  Discord
# ══════════════════════════════════════════════════════════════════════
@app.route("/api/discord")
def get_discord():
    ch = load_cfg().get("discord", {}).get("channels", {})
    return jsonify([{"key": k, **v} for k, v in ch.items()])

@app.route("/api/discord/channel", methods=["POST"])
def add_discord_channel():
    cfg = load_cfg(); d = request.json
    key = d["key"].strip().replace(" ", "_")
    cfg.setdefault("discord", {}).setdefault("channels", {})[key] = {
        "webhook_url": d.get("webhook_url", ""),
        "label": d.get("label", key), "enabled": True}
    save_cfg(cfg); return ok()

@app.route("/api/discord/channel/<key>", methods=["PUT", "DELETE"])
def discord_channel(key):
    cfg = load_cfg(); ch = cfg.get("discord", {}).get("channels", {})
    if request.method == "DELETE":
        ch.pop(key, None); save_cfg(cfg); return ok()
    d = request.json
    if key in ch:
        ch[key].update({k: d[k] for k in ("webhook_url","label","enabled") if k in d})
    save_cfg(cfg); return ok()

@app.route("/api/discord/test/<key>", methods=["POST"])
def test_discord(key):
    import requests as req
    ch = load_cfg().get("discord", {}).get("channels", {}).get(key, {})
    webhook = ch.get("webhook_url", "")
    if not webhook: return err("Webhook URLが未設定です")
    try:
        r = req.post(webhook, json={"content": f"✅ テスト通知 [{ch.get('label',key)}]"}, timeout=10)
        return ok({"status": r.status_code})
    except Exception as e: return err(str(e))

# ══════════════════════════════════════════════════════════════════════
#  RSS Feeds
# ══════════════════════════════════════════════════════════════════════
CATEGORIES = [
    ("ai_news",       "🤖 AIニュース"),
    ("ai_paper",      "🧠 AI論文"),
    ("manga",         "📚 漫画・新刊"),
    ("anime",         "📺 アニメ"),
    ("news",          "📰 ニュース"),
    ("magazine",      "📖 雑誌"),
    ("pokemon_card",  "⚡ ポケモンカード"),
    ("onepiece_card", "🏴 ワンピースカード"),
    ("game_news",     "🎮 ゲーム"),
    ("education",     "🎓 教育"),
]

@app.route("/api/categories")
def get_categories():
    return jsonify([{"value": v, "label": l} for v, l in CATEGORIES])

@app.route("/api/feeds", methods=["GET", "POST"])
def feeds():
    cfg = load_cfg()
    fl = cfg.setdefault("rss_feeds", {}).setdefault("feeds", [])
    if request.method == "POST":
        d = request.json
        fl.append({"name": d["name"], "url": d["url"],
                   "category": d.get("category", "news"),
                   "discord_channel": d.get("discord_channel", "default"),
                   "check_interval_hours": int(d.get("check_interval_hours", 1)),
                   "enabled": True})
        save_cfg(cfg); return ok()
    return jsonify([f for f in fl if f.get("url")])

@app.route("/api/feeds/<int:idx>", methods=["PUT", "DELETE"])
def feed_item(idx):
    cfg = load_cfg(); fl = cfg["rss_feeds"]["feeds"]
    vi = [i for i, f in enumerate(fl) if f.get("url")]
    if idx >= len(vi): return err("not found", 404)
    real = vi[idx]
    if request.method == "DELETE":
        fl.pop(real); save_cfg(cfg); return ok()
    fl[real].update(request.json); save_cfg(cfg); return ok()

@app.route("/api/feeds/<int:idx>/toggle", methods=["POST"])
def toggle_feed(idx):
    cfg = load_cfg(); fl = cfg["rss_feeds"]["feeds"]
    vi = [i for i, f in enumerate(fl) if f.get("url")]
    real = vi[idx]
    fl[real]["enabled"] = not fl[real].get("enabled", True)
    save_cfg(cfg); return ok({"enabled": fl[real]["enabled"]})

# ══════════════════════════════════════════════════════════════════════
#  Quick Links
# ══════════════════════════════════════════════════════════════════════
@app.route("/api/links", methods=["GET", "POST"])
def links():
    cfg = load_cfg()
    lk = cfg.setdefault("links", [])
    if request.method == "POST":
        d = request.json
        lk.append({"name": d["name"], "url": d["url"],
                   "category": d.get("category", ""),
                   "memo": d.get("memo", ""),
                   "enabled": True})
        save_cfg(cfg); return ok()
    return jsonify(lk)

@app.route("/api/links/<int:idx>", methods=["PUT", "DELETE"])
def link_item(idx):
    cfg = load_cfg(); lk = cfg.get("links", [])
    if idx >= len(lk): return err("not found", 404)
    if request.method == "DELETE":
        lk.pop(idx); save_cfg(cfg); return ok()
    lk[idx].update(request.json); save_cfg(cfg); return ok()

@app.route("/api/links/reorder", methods=["POST"])
def reorder_links():
    cfg = load_cfg()
    order = request.json.get("order", [])
    lk = cfg.get("links", [])
    cfg["links"] = [lk[i] for i in order if i < len(lk)]
    save_cfg(cfg); return ok()

# ══════════════════════════════════════════════════════════════════════
#  Dashboard (RSS news)
# ══════════════════════════════════════════════════════════════════════
@app.route("/api/news")
def recent_news():
    limit = request.args.get("limit", 80, type=int)
    cat   = request.args.get("category", "")
    # クラウドモード: Gist から読む
    if IS_CLOUD:
        st = get_storage()
        if st:
            return jsonify(st.read_news(category=cat, limit=limit))
        return jsonify([])
    # ローカルモード: SQLite
    cfg = load_cfg()
    db  = cfg.get("storage", {}).get("db_path", "")
    try:
        conn = sqlite3.connect(db)
        q = "SELECT id,feed_name,category,title,title_ja,url,published,created_at FROM rss_items"
        p = []
        if cat: q += " WHERE category=?"; p.append(cat)
        q += " ORDER BY created_at DESC LIMIT ?"; p.append(limit)
        rows = conn.execute(q, p).fetchall(); conn.close()
        return jsonify([{"id": r[0], "feed": r[1], "category": r[2],
            "title": r[3], "title_ja": r[4], "url": r[5],
            "published": (r[6] or "")[:10], "created_at": (r[7] or "")[:16]} for r in rows])
    except Exception:
        return jsonify([])

@app.route("/api/news/<int:item_id>", methods=["DELETE"])
def delete_news(item_id):
    if IS_CLOUD:
        st = get_storage()
        if st: st.delete_news(item_id)
        return ok()
    cfg = load_cfg()
    try:
        conn = sqlite3.connect(cfg["storage"]["db_path"])
        conn.execute("DELETE FROM rss_items WHERE id=?", (item_id,))
        conn.commit(); conn.close()
    except Exception:
        pass
    return ok()

@app.route("/api/stats")
def stats():
    if IS_CLOUD:
        st = get_storage()
        if st: return jsonify(st.get_stats())
        return jsonify({"total_news": 0, "today_news": 0})
    cfg = load_cfg()
    db  = cfg.get("storage", {}).get("db_path", "")
    try:
        conn  = sqlite3.connect(db)
        total = conn.execute("SELECT COUNT(*) FROM rss_items").fetchone()[0]
        today = conn.execute("SELECT COUNT(*) FROM rss_items WHERE created_at>=date('now')").fetchone()[0]
        conn.close()
        return jsonify({"total_news": total, "today_news": today})
    except Exception:
        return jsonify({"total_news": 0, "today_news": 0})

# ══════════════════════════════════════════════════════════════════════
#  Settings & Network info
# ══════════════════════════════════════════════════════════════════════
@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    cfg = load_cfg()
    if request.method == "POST":
        d = request.json
        if "storage"    in d: cfg.setdefault("storage", {}).update(d["storage"])
        if "vercel_url" in d: cfg["vercel_url"] = d["vercel_url"].strip()
        save_cfg(cfg); return ok()
    return jsonify({
        "storage":    cfg.get("storage", {}),
        "vercel_url": cfg.get("vercel_url", ""),
        "is_cloud":   IS_CLOUD,
    })

@app.route("/api/network-info")
def network_info():
    cfg = load_cfg()
    return jsonify({
        "localhost":  "http://localhost:8765",
        "local_ip":   LOCAL_IP,
        "mobile_url": f"http://{LOCAL_IP}:8765",
        "vercel_url": cfg.get("vercel_url", ""),
        "is_cloud":   IS_CLOUD,
    })

# ══════════════════════════════════════════════════════════════════════
#  Manual run / Restart
# ══════════════════════════════════════════════════════════════════════
@app.route("/api/restart", methods=["POST"])
def restart_server():
    if IS_CLOUD:
        return err("クラウドモードでは再起動不要です")
    def _do():
        import time, os
        time.sleep(0.5)
        py     = sys.executable
        script = str(BASE_DIR / "gui_app.py")
        helper = BASE_DIR / "_restart_helper.bat"
        helper.write_text(
            "@echo off\r\ntimeout /t 2 /nobreak >nul\r\n"
            f"start \"\" /B \"{py}\" -X utf8 \"{script}\"\r\n",
            encoding="ascii"
        )
        subprocess.Popen(
            ["cmd", "/c", str(helper)],
            cwd=str(BASE_DIR),
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 8) |
                          getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200),
            close_fds=True
        )
        time.sleep(0.3)
        os._exit(0)
    threading.Thread(target=_do, daemon=True).start()
    return ok({"message": "再起動中..."})

@app.route("/api/run/<mode>", methods=["POST"])
def run_mode(mode):
    if mode not in ("rss", "test"):
        return err("invalid mode")
    if IS_CLOUD:
        return ok({"stdout": "☁️ クラウドモード: GitHub Actionsが自動実行しています。\nGitHub → Actions タブから手動実行できます。", "stderr": ""})
    try:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(BASE_DIR / "main.py"), mode],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120, cwd=str(BASE_DIR))
        return ok({"stdout": result.stdout[-4000:], "stderr": result.stderr[-1000:]})
    except subprocess.TimeoutExpired:
        return err("タイムアウト(120秒)")
    except Exception as e:
        return err(str(e))

# ─── launch ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    migrate_config()
    PORT = 8765
    _is_pythonw = (sys.executable or "").lower().endswith("pythonw.exe")
    if not _is_pythonw:
        def _open():
            import time; time.sleep(1.2)
            webbrowser.open(f"http://localhost:{PORT}")
        threading.Thread(target=_open, daemon=True).start()
    print("=" * 50)
    print("  情報リサーチエージェント GUI 起動")
    print(f"  PC:             http://localhost:{PORT}")
    print(f"  スマホ(同じWiFi): http://{LOCAL_IP}:{PORT}")
    print("=" * 50)
    app.run(debug=False, port=PORT, host="0.0.0.0")
