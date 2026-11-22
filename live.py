"""Live CSE data engine.

WHY THIS EXISTS
  Before: every click made the app call cse.lk 4-6 times in a row (3-10 s timeouts that silently
  turned into 0.00 values) -> slow tabs and numbers that differed from the real market.
  Now: ONE background thread refreshes everything into memory. Every tab just reads memory
  (instant), all tabs show the SAME snapshot, and if cse.lk fails we keep the last good numbers
  (never zeros) and show how old they are.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import requests
from core.financial import decimal_text, to_decimal

SL = timezone(timedelta(hours=5, minutes=30))          # Sri Lanka time (no DST)
BASE = "https://www.cse.lk/api/"
HEADERS = {                                            # cse.lk expects browser-like headers
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Origin": "https://www.cse.lk",
    "Referer": "https://www.cse.lk/",
}

FAST_SEC, SLOW_SEC = 10, 60                            # refresh every 10 s (market open) / 60 s (closed)
TRADES_FAST_SEC, TRADES_SLOW_SEC = 15, 120
NEWS_SEC = 90

_session = requests.Session()
_session.headers.update(HEADERS)
_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="cse")

_lock = threading.RLock()
_started = False
_ready = {"overview": threading.Event(), "trades": threading.Event()}

DEFAULT_OVERVIEW = {
    "status": "Market Closed", "aspi": 0.0, "aspi_change": 0.0, "aspi_pct": 0.0, "aspi_high": 0.0, "aspi_low": 0.0,
    "snp": 0.0, "snp_change": 0.0, "snp_pct": 0.0, "snp_high": 0.0, "snp_low": 0.0,
    "turnover": 0.0, "share_volume": 0, "trades": 0, "last_updated": "-",
}

_store = {
    "overview": dict(DEFAULT_OVERVIEW),
    "trades": [],              # every symbol traded today (sorted by turnover)
    "by_symbol": {},           # symbol -> trade record
    "ts": {"overview": 0.0, "trades": 0.0, "news": 0.0},
    "err": {"overview": "", "trades": "", "news": ""},
}


# ------------------------------------------------------------------ helpers
def _post(path, data=None, timeout=8):
    r = _session.post(BASE + path, data=data, timeout=timeout)
    r.raise_for_status()
    return r.json(parse_float=Decimal, parse_int=Decimal)


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def now_sl():
    return datetime.now(SL)


def _fmt_ts(ms):
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, SL).strftime("%Y-%m-%d %I:%M %p")
    except Exception:
        return ""


def is_open(status=None):
    s = (status or _store["overview"].get("status", "")).lower()
    if "pre" in s:
        return True
    return ("open" in s or "trading" in s) and "closed" not in s


# ------------------------------------------------------------------ fetchers
def _fetch_overview():
    """4 calls IN PARALLEL. A failed part keeps its previous (last good) value."""
    jobs = {
        "status": _pool.submit(_post, "marketStatus", None, 6),
        "aspi": _pool.submit(_post, "aspiData", None, 6),
        "snp": _pool.submit(_post, "snpData", None, 6),
        "summary": _pool.submit(_post, "marketSummery", None, 6),
    }
    res, errors = {}, []
    for k, fut in jobs.items():
        try:
            res[k] = fut.result(timeout=9)
        except Exception as e:
            errors.append(f"{k}: {type(e).__name__}")

    with _lock:
        d = dict(_store["overview"])
    if "status" in res:
        d["status"] = res["status"].get("status") or d["status"]
    if "aspi" in res:
        a = res["aspi"]
        d.update(aspi=_f(a.get("value")) or d["aspi"], aspi_change=_f(a.get("change")), aspi_pct=_f(a.get("percentage")),
                 aspi_high=_f(a.get("highValue")) or d["aspi_high"], aspi_low=_f(a.get("lowValue")) or d["aspi_low"])
        if a.get("timestamp"):
            d["last_updated"] = _fmt_ts(a["timestamp"]) or d["last_updated"]
    if "snp" in res:
        s = res["snp"]
        d.update(snp=_f(s.get("value")) or d["snp"], snp_change=_f(s.get("change")), snp_pct=_f(s.get("percentage")),
                 snp_high=_f(s.get("highValue")) or d["snp_high"], snp_low=_f(s.get("lowValue")) or d["snp_low"])
    if "summary" in res:
        m = res["summary"]
        d.update(turnover=_f(m.get("tradeVolume")), share_volume=int(_f(m.get("shareVolume"))), trades=int(_f(m.get("trades"))))
    with _lock:
        _store["overview"] = d
        if all(k in res for k in ("status", "aspi", "snp", "summary")):
            # Freshness reflects a complete snapshot; partial success must not make
            # stale index or turnover values look current.
            _store["ts"]["overview"] = time.time()
        _store["err"]["overview"] = ", ".join(errors)
    _ready["overview"].set()


def _fetch_trades():
    """tradeSummary = ALL symbols in one call. Used by dashboard, explorer, compare, portfolio, alerts."""
    try:
        items = _post("tradeSummary", None, 10).get("reqTradeSummery", []) or []
    except Exception as e:
        with _lock:
            _store["err"]["trades"] = type(e).__name__
        _ready["trades"].set()
        return
    rows = []
    for it in items:
        exact_price = to_decimal(it.get("price"), default=Decimal(0))
        exact_turnover = to_decimal(it.get("turnover"), default=Decimal(0))
        price = _f(exact_price)
        qty = int(_f(it.get("quantity")))
        if price <= 0:
            continue
        prev = _f(it.get("previousClose"))
        pct = it.get("percentageChange")
        pct = _f(pct) if pct not in (None, "") else ((price - prev) / prev * 100 if prev else 0.0)
        turnover = _f(exact_turnover)
        est = False
        if turnover <= 0 and qty > 0:             # API did not give turnover -> estimate (flagged)
            turnover, est = price * qty, True
        rows.append({
            "symbol": it.get("symbol", ""), "name": it.get("name", ""), "price": price,
            "price_exact": decimal_text(exact_price),
            "turnover_exact": decimal_text(exact_turnover),
            "change": _f(it.get("change")), "change_pct": pct, "previous_close": prev,
            "high": _f(it.get("high")), "low": _f(it.get("low")),
            "volume": qty, "turnover": turnover, "turnover_est": est, "trades": int(_f(it.get("trades"))),
        })
    rows.sort(key=lambda r: r["turnover"], reverse=True)
    with _lock:
        # An empty but successful response is meaningful (for example, a new
        # session with no trades yet) and must clear the previous session's data.
        _store["trades"] = rows
        _store["by_symbol"] = {r["symbol"]: r for r in rows}
        _store["ts"]["trades"] = time.time()
        _store["err"]["trades"] = "" if rows else "empty"
    _ready["trades"].set()


def _fetch_news():
    try:
        from core.news_fetcher import fetch_latest_news
        fetch_latest_news(limit_per_source=20, force=True)
        with _lock:
            _store["ts"]["news"] = time.time()
            _store["err"]["news"] = ""
    except Exception as e:
        with _lock:
            _store["err"]["news"] = type(e).__name__


# ------------------------------------------------------------------ refresher thread
def _loop():
    nxt = {"overview": 0.0, "trades": 0.0, "news": 0.0}
    while True:
        t = time.time()
        fast = is_open()
        try:
            if t >= nxt["overview"]:
                nxt["overview"] = t + (FAST_SEC if fast else SLOW_SEC)
                _fetch_overview()
            if t >= nxt["trades"]:
                nxt["trades"] = t + (TRADES_FAST_SEC if fast else TRADES_SLOW_SEC)
                _fetch_trades()
            if t >= nxt["news"]:
                nxt["news"] = t + NEWS_SEC
                _fetch_news()
        except Exception as e:                    # the loop must never die
            print("live loop error:", e)
        time.sleep(1)


def start():
    """Idempotent. Starts the refresher once per process."""
    global _started
    with _lock:
        if _started:
            return False
        _started = True
    threading.Thread(target=_loop, daemon=True, name="live-refresher").start()
    return True


# ------------------------------------------------------------------ read API (instant, never blocks on network)
def overview(wait=0.0):
    """Latest market overview. On the very first call it waits (max `wait` s) for the first fetch."""
    start()
    if not _ready["overview"].is_set() and wait:
        _ready["overview"].wait(wait)
    with _lock:
        d = dict(_store["overview"])
    d["fetched_at"] = _store["ts"]["overview"]
    d["age_sec"] = (time.time() - d["fetched_at"]) if d["fetched_at"] else None
    return d


def trades(wait=0.0):
    start()
    if not _ready["trades"].is_set() and wait:
        _ready["trades"].wait(wait)
    with _lock:
        return list(_store["trades"])


def trade(symbol):
    """Today's trade record for one symbol (or None)."""
    trades(wait=0)
    with _lock:
        return _store["by_symbol"].get(symbol)


def price(symbol, max_age=None):
    """Last traded price from the shared snapshot (None if the symbol is unknown).
    max_age=None -> last good price at any age (the UI shows a 'delayed' warning when the feed is old)."""
    trades(wait=0)
    with _lock:
        rec = _store["by_symbol"].get(symbol)
        fresh = max_age is None or time.time() - _store["ts"]["trades"] <= max_age
    return rec["price"] if rec and fresh else None


def price_decimal(symbol, max_age=None):
    """Last traded price from the exact decimal value decoded from the CSE JSON response."""
    trades(wait=0)
    with _lock:
        rec = _store["by_symbol"].get(symbol)
        fresh = max_age is None or time.time() - _store["ts"]["trades"] <= max_age
    return to_decimal(rec["price_exact"], default=None) if rec and fresh else None


def breadth():
    """Advancers / decliners / unchanged among stocks that traded."""
    up = down = flat = 0
    for r in trades(wait=0):
        if r["volume"] <= 0:
            continue
        if r["change_pct"] > 0:
            up += 1
        elif r["change_pct"] < 0:
            down += 1
        else:
            flat += 1
    return up, down, flat


def age_text(sec):
    if sec is None:
        return "waiting for data"
    sec = int(sec)
    if sec < 5:
        return "just now"
    if sec < 60:
        return f"{sec}s ago"
    if sec < 3600:
        return f"{sec // 60}m ago"
    return f"{sec // 3600}h ago"


def health():
    """For the status panel: how fresh is each feed."""
    with _lock:
        ts, err = dict(_store["ts"]), dict(_store["err"])
    now = time.time()
    return {k: {"age": (now - v) if v else None, "error": err.get(k, "")} for k, v in ts.items()}
