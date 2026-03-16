@echo off
chcp 65001 >nul
echo === デバッグ開始 ===
cd /d "%~dp0"
echo カレント: %CD%

echo.
echo --- pythonw の場所確認 ---
where pythonw
echo エラーコード: %ERRORLEVEL%

echo.
echo --- ポート 8765 のプロセス ---
netstat -ano | findstr ":8765"

echo.
echo --- gui_app プロセス確認 ---
wmic process where "name='pythonw.exe'" get processid,commandline 2>&1
wmic process where "name='python.exe'" get processid,commandline 2>&1

echo.
echo === 終了 ===
pause
