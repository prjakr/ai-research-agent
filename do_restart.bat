@echo off
timeout /t 1 /nobreak >nul
powershell -NoProfile -WindowStyle Hidden -Command "$p=Get-NetTCPConnection -LocalPort 8765 -EA SilentlyContinue|Select -Exp OwningProcess -Unique;if($p){$p|ForEach-Object{Stop-Process -Id $_ -Force -EA SilentlyContinue}}"
timeout /t 1 /nobreak >nul
start "" /B "C:\Users\user\AppData\Local\Programs\Python\Python314\pythonw.exe" -X utf8 "%~dp0gui_app.py"
