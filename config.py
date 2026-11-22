from pathlib import Path
import os
import sys

BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    # Keep the database and uploaded reports writable and persistent when the app
    # is extracted anywhere (including a protected Windows folder).
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "CSE AI Alpha Terminal"
else:
    DATA_DIR = BASE_DIR / "data"      # source installs keep data beside the app
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "stock.db"

OLLAMA_MODEL = "qwen2.5:1.5b"
OLLAMA_NUM_CTX = 8192                 # default 2048 is too small for reports
CHECK_INTERVAL_SEC = 300              # price check every 5 minutes
MAX_PDF_CHARS = 7000                  # small model = keep prompt short
