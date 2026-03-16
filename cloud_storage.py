"""
GitHub Gist をクラウドストレージとして使用するアダプター
────────────────────────────────────────────────
必要な環境変数 (PythonAnywhere / GitHub Actions に設定):
  GITHUB_TOKEN   : GitHub Personal Access Token (gist スコープ)
  GITHUB_GIST_ID : 設定・データを保存する Private Gist の ID

どちらも未設定の場合はローカルモード（既存動作）のまま。
"""
import json
import os
import time
from datetime import date

import requests as req

GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_GIST_ID = os.environ.get("GITHUB_GIST_ID", "").strip()
IS_CLOUD       = bool(GITHUB_TOKEN and GITHUB_GIST_ID)

_API_BASE = "https://api.github.com"
_TIMEOUT  = 20          # 秒
_CACHE_TTL = 30         # 秒（同一ファイルを何度も叩かないためのキャッシュ）


class GistStorage:
    """GitHub Gist を key-value ストレージとして扱うクラス"""

    def __init__(self, token: str, gist_id: str):
        self.token   = token
        self.gist_id = gist_id
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        # {filename: (data, fetched_at)}
        self._cache: dict[str, tuple] = {}

    # ── 低レベル ────────────────────────────────────────────────────
    def _get_gist(self) -> dict:
        r = req.get(
            f"{_API_BASE}/gists/{self.gist_id}",
            headers=self._headers, timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()

    def _read(self, filename: str, default):
        cached, fetched_at = self._cache.get(filename, (None, 0))
        if cached is not None and (time.time() - fetched_at) < _CACHE_TTL:
            return cached
        try:
            gist   = self._get_gist()
            file_d = gist.get("files", {}).get(filename, {})
            raw    = file_d.get("content") or ""
            data   = json.loads(raw) if raw else default
        except Exception as e:
            print(f"[Cloud] read {filename}: {e}")
            return default
        self._cache[filename] = (data, time.time())
        return data

    def _write(self, filename: str, data) -> bool:
        try:
            content = json.dumps(data, ensure_ascii=False, indent=2)
            r = req.patch(
                f"{_API_BASE}/gists/{self.gist_id}",
                headers=self._headers,
                json={"files": {filename: {"content": content}}},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            # キャッシュ更新
            self._cache[filename] = (data, time.time())
            return True
        except Exception as e:
            print(f"[Cloud] write {filename}: {e}")
            return False

    # ── config ──────────────────────────────────────────────────────
    def read_config(self) -> dict:
        return self._read("config.json", {})

    def write_config(self, cfg: dict) -> bool:
        return self._write("config.json", cfg)

    # ── news ────────────────────────────────────────────────────────
    NEWS_FILE = "news.json"
    MAX_NEWS  = 500          # Gist の容量節約のため上限を設定

    def read_news(self, category: str = "", limit: int = 80) -> list:
        items = self._read(self.NEWS_FILE, [])
        if category:
            items = [n for n in items if n.get("category") == category]
        return items[:limit]

    def append_news(self, new_items: list) -> bool:
        """既存ニュースに追記して重複排除・上限切り捨て後に保存"""
        existing = self._read(self.NEWS_FILE, [])
        seen_urls = {n.get("url") for n in existing}
        merged = [n for n in new_items if n.get("url") not in seen_urls] + existing
        merged = merged[: self.MAX_NEWS]
        return self._write(self.NEWS_FILE, merged)

    def delete_news(self, item_id: int) -> bool:
        items = self._read(self.NEWS_FILE, [])
        new_items = [n for n in items if n.get("id") != item_id]
        return self._write(self.NEWS_FILE, new_items)

    # ── snapshots (サイト監視) ────────────────────────────────────────
    SNAP_FILE = "snapshots.json"

    def read_snapshots(self) -> list:
        return self._read(self.SNAP_FILE, [])

    def write_snapshots(self, snaps: list) -> bool:
        return self._write(self.SNAP_FILE, snaps)

    # ── stats ────────────────────────────────────────────────────────
    def get_stats(self) -> dict:
        items = self._read(self.NEWS_FILE, [])
        snaps = self._read(self.SNAP_FILE, [])
        today_str = date.today().isoformat()
        return {
            "total_news":      len(items),
            "today_news":      sum(1 for n in items if n.get("created_at", "").startswith(today_str)),
            "monitored_sites": len({s.get("name") for s in snaps}),
        }


# ── シングルトン ──────────────────────────────────────────────────────
_storage: GistStorage | None = None


def get_storage() -> "GistStorage | None":
    """IS_CLOUD が True の場合のみ GistStorage インスタンスを返す"""
    global _storage
    if not IS_CLOUD:
        return None
    if _storage is None:
        _storage = GistStorage(GITHUB_TOKEN, GITHUB_GIST_ID)
    return _storage
