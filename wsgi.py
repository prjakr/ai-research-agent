"""
PythonAnywhere 用 WSGI エントリーポイント
────────────────────────────────────────────
PythonAnywhereのWebアプリ設定で
  Source code:  /home/あなたのユーザー名/AI_research_agent
  WSGI file:    /home/あなたのユーザー名/AI_research_agent/wsgi.py
と設定してください。
"""
import sys
import os
from pathlib import Path

# プロジェクトディレクトリをPythonパスに追加
project_dir = str(Path(__file__).parent)
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

# 環境変数はPythonAnywhereのWebアプリ設定 > Environment Variables で設定
# GITHUB_TOKEN=ghp_xxxxxxxxxxxx
# GITHUB_GIST_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

from gui_app import app as application  # noqa: F401 (PythonAnywhere が application を探す)

if __name__ == "__main__":
    application.run()
