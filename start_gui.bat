@echo off
chcp 65001 > nul
echo.
echo  情報リサーチエージェント GUI を起動します
echo  ブラウザで http://localhost:8765 を開いてください
echo  終了するには Ctrl+C を押してください
echo.
cd /d "%~dp0"
python -X utf8 gui_app.py
pause
