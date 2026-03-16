@echo off
chcp 65001 >nul
echo ========================================
echo  リサーチAgent 再起動
echo ========================================

cd /d "%~dp0"

:: ── gui_app.py を実行しているプロセスを終了 ──
echo [1] 既存プロセスを停止中...
wmic process where "name='pythonw.exe' and commandline like '%%gui_app%%'" delete >nul 2>&1
wmic process where "name='python.exe'  and commandline like '%%gui_app%%'" delete >nul 2>&1
timeout /t 2 /nobreak >nul

:: ── Flask サーバーをバックグラウンドで起動 ──
echo [2] サーバーを起動中...
start "" /B pythonw -X utf8 gui_app.py

:: ── 起動を待ってブラウザを開く ──
echo [3] ブラウザを開くまで待機中...
timeout /t 3 /nobreak >nul
start "" http://localhost:8765

echo [4] 完了！
timeout /t 2 /nobreak >nul
