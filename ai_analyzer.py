import json
import re
import socket
import subprocess
import shutil
import ollama
from decimal import Decimal, InvalidOperation
from config import OLLAMA_MODEL, OLLAMA_NUM_CTX
from core.financial import divide, to_decimal

PROMPT = """You are a financial report data extractor. Reply ONLY with JSON using exactly these keys:
company, period, assets, liabilities, equity, revenue, net_profit, current_assets,
current_liabilities, shares_outstanding, eps, dividend_per_share, summary.
Copy figures from the CURRENT period column (first column) without rounding, estimating,
or calculating. Statement totals are in LKR millions; share count is a count and EPS /
dividend_per_share are LKR per share. Use exact plain-number strings (no commas or text);
use null when a figure is absent. Keep the report's stated unit in the summary.
summary = 3 short sentences.

REPORT:
"""


def is_ollama_running(port=11434):
    """Check if Ollama server port is responding."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_ollama_running():
    """If Ollama is not running, automatically start it in the background."""
    if is_ollama_running():
        return True

    ollama_path = shutil.which("ollama")
    if not ollama_path:
        # Fallback to default Windows install path
        import os
        candidate = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
        if os.path.exists(candidate):
            ollama_path = candidate

    if ollama_path:
        try:
            # Start Ollama serve in hidden background process
            creationflags = 0x08000000  # CREATE_NO_WINDOW on Windows
            subprocess.Popen([ollama_path, "serve"], creationflags=creationflags)
            return True
        except Exception as e:
            print(f"Could not auto-start Ollama: {e}")
    return False


MONEY = ("assets", "liabilities", "equity", "revenue", "net_profit",
         "current_assets", "current_liabilities", "shares_outstanding", "eps",
         "dividend_per_share")

LABELS = {
    "assets": ["total assets"],
    "liabilities": ["total liabilities"],
    "equity": ["total equity", "shareholders' equity", "total shareholders"],
    "revenue": ["revenue", "turnover", "gross income"],
    "net_profit": ["profit for the period", "profit for the year",
                   "net profit", "profit after tax"],
    "current_assets": ["total current assets", "current assets"],
    "current_liabilities": ["total current liabilities", "current liabilities"],
    "shares_outstanding": ["number of ordinary shares", "weighted average shares",
                           "issued shares", "shares in issue"],
    "eps": ["earnings per share", "basic earnings per share"],
    "dividend_per_share": ["dividend per share", "dividend (lkr) per share"],
}
NUM = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?\)?")


def _to_decimal(v):
    if v is None:
        return None
    s = str(v).strip()
    if s.lower() in {"", "null", "none", "n/a", "na", "not available"}:
        return None
    neg = s.startswith("(") or s.startswith("-")
    s = re.sub(r"[^\d.eE+-]", "", s)
    try:
        x = Decimal(s)
    except InvalidOperation:
        return None
    if not x.is_finite():
        return None
    return -abs(x) if neg else x


def _regex_value(text, labels, key):
    """Find a source-text figure when the model did not return one."""
    for line in text.splitlines():
        low = line.lower()
        for lab in labels:
            i = low.find(lab)
            if i < 0:
                continue
            if key == "liabilities" and "equity" in low:
                continue  # skip 'total liabilities and equity'
            m = NUM.search(line[i + len(lab):])
            if m:
                return _to_decimal(m.group())
    return None


def _parse_json(raw):
    try:
        return json.loads(raw, parse_float=Decimal, parse_int=Decimal)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            return json.loads(m.group(), parse_float=Decimal, parse_int=Decimal)
        raise


def analyze(text, model=None):
    ensure_ollama_running()
    model = model or OLLAMA_MODEL
    resp = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": PROMPT + text}],
        format="json",
        options={"temperature": 0, "num_ctx": OLLAMA_NUM_CTX},
        keep_alive="2h",
    )
    data = _parse_json(resp["message"]["content"])
    data["company"] = str(data.get("company") or "Unknown")
    data["period"] = str(data.get("period") or "")
    data["summary"] = str(data.get("summary") or "")
    for k in MONEY:
        v = _to_decimal(data.get(k))
        if v is None:
            v = _regex_value(text, LABELS[k], k)
        data[k] = v
    data["score"] = health_score(data)
    return data


def health_score(d):
    """Simple 0-100 score. Adjust the weights to your taste."""
    required = ("assets", "liabilities", "revenue", "net_profit", "equity")
    if any(d.get(key) is None for key in required):
        return None
    assets = to_decimal(d.get("assets"))
    liabilities = to_decimal(d.get("liabilities"))
    revenue = to_decimal(d.get("revenue"))
    net_profit = to_decimal(d.get("net_profit"))
    equity = to_decimal(d.get("equity"))
    score = Decimal(0)
    scored = False
    if assets > 0:
        debt_ratio = min(Decimal(1), max(Decimal(0), divide(liabilities, assets)))
        score += Decimal(40) * (1 - debt_ratio)
        scored = True
    if revenue > 0:
        margin = divide(net_profit, revenue)
        score += min(Decimal(35), max(Decimal(0), margin * Decimal(175)))
        scored = True
    if equity > 0 and net_profit > 0:
        roe = divide(net_profit, equity)
        score += min(Decimal(25), max(Decimal(0), roe * Decimal(125)))
        scored = True
    return int(score.quantize(Decimal("1"))) if scored else None


def chat_with_report(report_text, user_question, model=None):
    """Ask AI questions about the uploaded report."""
    ensure_ollama_running()
    model = model or OLLAMA_MODEL
    prompt = f"""You are a professional financial advisor reviewing a Sri Lankan Colombo Stock Exchange (CSE) corporate report.
Report content:
\"\"\"{report_text[:12000]}\"\"\"

Question: {user_question}

Answer directly, accurately, and concisely based on the figures and context in the report. If the information is not in the text, mention that clearly."""
    try:
        resp = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2, "num_ctx": OLLAMA_NUM_CTX},
            keep_alive="2h",
        )
        return resp["message"]["content"]
    except Exception as e:
        return f"Error talking to AI model: {e}"


def ask_market_assistant(user_prompt, model=None):
    """AI Copilot: live market + portfolio + news context, answers in Sinhala (read-only agent)."""
    from core import agent
    return agent.answer(user_prompt, model)
