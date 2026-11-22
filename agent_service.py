"""Runs the AI agent in the background (no window) so alerts reach your PC
(Windows notifications) even when the app is closed.
Start with:  install_autostart.bat   (runs automatically when you log in to Windows)
"""
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    BASE = Path(sys.executable).resolve().parent
BUNDLE = Path(getattr(sys, "_MEIPASS", BASE))
os.chdir(BASE)
sys.path.insert(0, str(BUNDLE))

if sys.stdout is None or sys.stderr is None or Path(sys.executable).name.lower() == "pythonw.exe":
    from config import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = open(DATA_DIR / "agent_service.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log

from core import database as db   # noqa: E402
from core import agent             # noqa: E402


def main():
    db.init_db()
    if not agent.start_agent():
        print("Agent already running (another process owns it). Exiting.")
        return
    print("CSE AI agent service started.")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
