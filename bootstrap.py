"""Starts the WHOLE AI system in one go when the app opens.

Runs these in PARALLEL (so the app is usable immediately, while the AI warms up in the background):
  1. Live market data   - background refresher (core.live)
  2. Ollama engine      - start the server if it is not running, wait until it answers
  3. AI model           - check it is installed (auto-download if missing) and load it into memory (warm-up),
                          so the first Copilot answer is fast instead of waiting 20-60 s
  4. AI Agent           - news / alerts / Windows PC notifications (skipped if the background service already runs it)
  5. News + company index pre-load

get_status() feeds the "AI System" panel in the sidebar.
"""
import socket
import threading
import time

from config import OLLAMA_MODEL, OLLAMA_NUM_CTX
from core import database as db
from core import live

KEEP_ALIVE = "2h"                 # keep the model in RAM for 2 hours after the last use

_lock = threading.Lock()
_started = False
_status = {}
_ORDER = ["data", "ollama", "model", "agent", "news"]
_LABEL = {"data": "Live market data", "ollama": "Ollama engine", "model": "AI model",
          "agent": "AI agent", "news": "News & company index"}


def _set(key, state, detail=""):
    """state: wait | busy | ok | warn | err"""
    with _lock:
        _status[key] = {"state": state, "detail": detail, "ts": time.time()}


def get_status():
    with _lock:
        snap = {k: dict(v) for k, v in _status.items()}
    return [dict(key=k, label=_LABEL[k], **snap.get(k, {"state": "wait", "detail": "starting..."})) for k in _ORDER]


def all_ready():
    return all(s["state"] in ("ok", "warn") for s in get_status())


# ------------------------------------------------------------------ ollama helpers
def ollama_up(port=11434):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def installed_models():
    """Names of models installed in Ollama ([] if it is not reachable)."""
    try:
        import ollama
        resp = ollama.list()
        models = getattr(resp, "models", None)
        if models is None and isinstance(resp, dict):
            models = resp.get("models", [])
        names = []
        for m in models or []:
            n = getattr(m, "model", None) or getattr(m, "name", None)
            if n is None and isinstance(m, dict):
                n = m.get("model") or m.get("name")
            if n:
                names.append(str(n))
        return names
    except Exception:
        return []


def _has_model(model, names):
    base = model if ":" in model else model + ":latest"
    return model in names or base in names


def _current_model():
    return db.get_setting("ollama_model", OLLAMA_MODEL) or OLLAMA_MODEL


# ------------------------------------------------------------------ startup tasks
def _task_data():
    _set("data", "busy", "connecting to cse.lk...")
    live.start()
    live.overview(wait=8)
    live.trades(wait=8)
    h = live.health()
    if h["overview"]["age"] is None and h["trades"]["age"] is None:
        _set("data", "warn", "cse.lk not reachable yet - retrying every few seconds")
    else:
        _set("data", "ok", "refreshing automatically")


def _task_ollama_and_model():
    try:
        import ollama
    except ImportError:
        _set("ollama", "err", "python package 'ollama' missing")
        _set("model", "err", "install requirements.txt")
        return

    _set("ollama", "busy", "starting...")
    if not ollama_up():
        try:
            from core.ai_analyzer import ensure_ollama_running
            ensure_ollama_running()
        except Exception as e:
            print("ollama start failed:", e)
        for _ in range(60):                       # wait up to ~30 s for the server
            if ollama_up():
                break
            time.sleep(0.5)
    if not ollama_up():
        _set("ollama", "err", "not running - install from ollama.com")
        _set("model", "wait", "needs Ollama")
        return
    _set("ollama", "ok", "running")

    model = _current_model()
    _set("model", "busy", f"checking {model}...")
    try:
        if not _has_model(model, installed_models()):
            _set("model", "busy", f"downloading {model} (first time only)...")
            last = 0.0
            for part in ollama.pull(model, stream=True):
                done = getattr(part, "completed", None) or (part.get("completed") if isinstance(part, dict) else None)
                total = getattr(part, "total", None) or (part.get("total") if isinstance(part, dict) else None)
                if done and total and time.time() - last > 1:
                    last = time.time()
                    _set("model", "busy", f"downloading {model}: {done / total * 100:.0f}%")
        _set("model", "busy", f"loading {model} into memory...")
        ollama.chat(model=model, messages=[{"role": "user", "content": "hi"}],
                    options={"num_predict": 1, "num_ctx": OLLAMA_NUM_CTX}, keep_alive=KEEP_ALIVE)
        _set("model", "ok", f"{model} ready")
    except Exception as e:
        _set("model", "err", f"{type(e).__name__}: {str(e)[:60]}")


def _task_agent():
    _set("agent", "busy", "starting...")
    try:
        from core import agent
        if agent.start_agent():
            _set("agent", "ok", "running in this app")
        else:
            _set("agent", "ok", "running as background service")
    except Exception as e:
        _set("agent", "err", f"{type(e).__name__}")


def _task_news():
    _set("news", "busy", "loading...")
    try:
        from core import agent
        from core.companies import load_companies
        load_companies()
        agent.find_companies("")                 # builds the company-name index once
        from core.news_fetcher import fetch_latest_news
        n = len(fetch_latest_news(limit_per_source=20))
        _set("news", "ok" if n else "warn", f"{n} headlines" if n else "feeds unreachable - will retry")
    except Exception as e:
        _set("news", "warn", f"{type(e).__name__}")


def start_all():
    """Idempotent: safe to call on every Streamlit rerun."""
    global _started
    with _lock:
        if _started:
            return False
        _started = True
    try:
        db.init_db()
    except Exception as e:
        print("init_db:", e)
    for target in (_task_data, _task_ollama_and_model, _task_agent, _task_news):
        threading.Thread(target=target, daemon=True, name=target.__name__).start()
    return True


def rewarm(model=None, on_success=None):
    """Warm a selected model; optionally persist it only after a successful load."""
    def run():
        m = model or _current_model()
        _set("model", "busy", f"loading {m}...")
        try:
            import ollama
            if not _has_model(m, installed_models()):
                _set("model", "busy", f"downloading {m}...")
                ollama.pull(m)
            ollama.chat(model=m, messages=[{"role": "user", "content": "hi"}],
                        options={"num_predict": 1, "num_ctx": OLLAMA_NUM_CTX}, keep_alive=KEEP_ALIVE)
            if on_success:
                on_success()
            _set("model", "ok", f"{m} ready")
        except Exception as e:
            _set("model", "err", f"{type(e).__name__}: {str(e)[:60]}")
    threading.Thread(target=run, daemon=True).start()
