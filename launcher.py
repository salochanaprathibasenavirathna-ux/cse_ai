"""Opens the app in its own desktop window (pywebview)."""
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
BASE = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
BUNDLE = Path(getattr(sys, "_MEIPASS", BASE)) if FROZEN else BASE
from config import DATA_DIR

LOG_PATH = DATA_DIR / "desktop_app.log"


def _frozen_worker():
    """Run Streamlit or the background agent from this same packaged executable."""
    mode, *args = sys.argv[1:]
    sys.path.insert(0, str(BUNDLE))
    if mode == "--_streamlit":
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        worker_log = LOG_PATH.open("a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = worker_log
        sys.argv = ["streamlit", *args]
        from streamlit.web.cli import main as streamlit_main
        streamlit_main()
    elif mode == "--_agent":
        from agent_service import main as agent_main
        agent_main()
    else:
        raise SystemExit(f"Unknown internal mode: {mode}")


def choose_port():
    """Use the familiar port when free; avoid attaching to an old app if it is busy."""
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", 8501))
            return 8501
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def ensure_ollama():
    """Auto start Ollama if not running."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        if s.connect_ex(("127.0.0.1", 11434)) == 0:
            return  # already running

    ollama_path = shutil.which("ollama")
    if not ollama_path:
        cand = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
        if os.path.exists(cand):
            ollama_path = cand

    if ollama_path:
        try:
            print("Starting Ollama background service...")
            creationflags = 0x08000000  # CREATE_NO_WINDOW
            subprocess.Popen([ollama_path, "serve"], creationflags=creationflags)
        except Exception as e:
            print(f"Could not launch Ollama: {e}")



def wait_for_port(port, proc, timeout=45):
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        if proc.poll() is not None:
            return False
        time.sleep(0.15)
    return False


def stop_server(proc):
    """Close this launch's Streamlit process tree without touching another instance."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5, check=False)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    proc.terminate()


SPLASH = """<html><body style="margin:0;background:#07090f;color:#e6edf7;font-family:Segoe UI,sans-serif;
display:grid;place-items:center;height:100vh"><div style="text-align:center">
<div style="width:56px;height:56px;border-radius:16px;margin:0 auto 18px;background:linear-gradient(135deg,#22d3ee,#6366f1);
box-shadow:0 8px 30px rgba(34,211,238,.35);animation:p 1.4s ease-in-out infinite"></div>
<div style="font-size:20px;font-weight:800;letter-spacing:-.02em">CSE AI Alpha Terminal</div>
<div style="color:#8a97ab;font-size:13px;margin-top:8px">Opening your desktop workspace...</div></div>
<style>@keyframes p{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(.88);opacity:.6}}</style></body></html>"""


def main():
    port = choose_port()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log = LOG_PATH.open("a", encoding="utf-8")
    log.write(f"\n--- Desktop app start {time.strftime('%Y-%m-%d %H:%M:%S')} (port {port}) ---\n")
    log.flush()
    ensure_ollama()                      # AI engine starts at the same moment as the app
    if FROZEN:
        # The release build runs the background agent from the same executable.
        subprocess.Popen([sys.executable, "--_agent"], cwd=BASE,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=0x08000000)
        streamlit_command = [sys.executable, "--_streamlit", "run", str(BUNDLE / "app.py")]
    else:
        streamlit_command = [sys.executable, "-m", "streamlit", "run", "app.py"]
    proc = subprocess.Popen(
        [*streamlit_command,
         "--server.address", "127.0.0.1", "--server.port", str(port), "--server.headless", "true",
         "--browser.gatherUsageStats", "false"],
        cwd=BASE, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        try:
            import webview
        except ImportError:
            if wait_for_port(port, proc):
                webbrowser.open(url)
                proc.wait()
            else:
                print(f"App did not start. Check {LOG_PATH}")
            return

        # window opens INSTANTLY with a splash screen; the app replaces it as soon as it is ready
        window = webview.create_window("CSE AI Analyzer", html=SPLASH, width=1350, height=860,
                                       background_color="#07090f")

        def go():
            if wait_for_port(port, proc):
                # The UI can load while Ollama starts and the model warms in the background.
                window.load_url(url)
            else:
                reason = ("The app process stopped during startup." if proc.poll() is not None
                          else "The app took too long to start.")
                message = (f"{reason} Check the desktop_app.log file in the app's data folder, "
                           "then run the desktop shortcut again.")
                window.load_html("<body style='background:#07090f;color:#e6edf7;font-family:sans-serif;padding:40px'>"
                                 f"<h2 style='color:#f43f5e'>CSE AI Alpha could not open</h2><p>{message}</p></body>")

        webview.start(go)
    finally:
        stop_server(proc)
        log.close()


if __name__ == "__main__":
    if FROZEN and len(sys.argv) > 1 and sys.argv[1] in {"--_streamlit", "--_agent"}:
        _frozen_worker()
    else:
        main()
