"""
Start / restart launcher for gui_app.py
- Kills any existing process on port 8765
- Starts python.exe gui_app.py (minimized window)
- Polls until Flask is ready, then opens browser
Run via start_gui.vbs (pythonw, no console window)
"""
import subprocess, sys, time, urllib.request, webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).parent
# Use python.exe (not pythonw) so errors show in minimized window
py = str(Path(sys.executable).with_name("python.exe"))

# Kill any process currently on port 8765
subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "Get-NetTCPConnection -LocalPort 8765 -EA SilentlyContinue"
     " | Select-Object -Exp OwningProcess -Unique"
     " | ForEach-Object { Stop-Process -Id $_ -Force -EA SilentlyContinue }"],
    capture_output=True
)
time.sleep(0.5)

# Start Flask with a minimized (not hidden) console window
si = subprocess.STARTUPINFO()
si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
si.wShowWindow = 7  # SW_SHOWMINNOACTIVE
subprocess.Popen(
    [py, "-X", "utf8", str(BASE_DIR / "gui_app.py")],
    cwd=str(BASE_DIR),
    startupinfo=si
)

# Poll every 500ms until server responds (up to 15 seconds)
for _ in range(30):
    time.sleep(0.5)
    try:
        with urllib.request.urlopen(
            "http://localhost:8765/api/version", timeout=1
        ) as r:
            if r.status == 200:
                break
    except Exception:
        pass

webbrowser.open("http://localhost:8765")
