"""CSE company directory (all listed companies) with local cache + offline fallback.

Source: https://www.cse.lk/api/allSecurityCode  (every symbol + company name)
The list is cached in data/companies.json for 24h so the app opens fast and
still works when the CSE site is unreachable.
"""
import json
import time
import requests
from config import DATA_DIR

CACHE = DATA_DIR / "companies.json"
CACHE_TTL = 24 * 3600
URL = "https://www.cse.lk/api/allSecurityCode"
HEADERS = {"User-Agent": "Mozilla/5.0", "Origin": "https://www.cse.lk",
           "Referer": "https://www.cse.lk/"}

# Small offline fallback (used only if the API AND the cache are unavailable)
SEED = [
    ("JKH.N0000", "JOHN KEELLS HOLDINGS PLC"), ("COMB.N0000", "COMMERCIAL BANK OF CEYLON PLC"),
    ("SAMP.N0000", "SAMPATH BANK PLC"), ("HNB.N0000", "HATTON NATIONAL BANK PLC"),
    ("LOLC.N0000", "L O L C HOLDINGS PLC"), ("CTC.N0000", "CEYLON TOBACCO COMPANY PLC"),
    ("DIAL.N0000", "DIALOG AXIATA PLC"), ("SLTL.N0000", "SRI LANKA TELECOM PLC"),
    ("LION.N0000", "LION BREWERY (CEYLON) PLC"), ("DIST.N0000", "DISTILLERIES COMPANY OF SRI LANKA PLC"),
    ("NEST.N0000", "NESTLE LANKA PLC"), ("HAYL.N0000", "HAYLEYS PLC"),
    ("AEL.N0000", "ACCESS ENGINEERING PLC"), ("EXPO.N0000", "EXPOLANKA HOLDINGS PLC"),
    ("TJL.N0000", "TEEJAY LANKA PLC"), ("CARG.N0000", "CARGILLS (CEYLON) PLC"),
]


def _clean(rows):
    out, seen = [], set()
    for r in rows:
        sym, name = str(r.get("symbol", "")).strip(), str(r.get("name", "")).strip()
        if not sym or sym in seen or r.get("active", 1) in (0, "0", False):
            continue
        seen.add(sym)
        out.append({"symbol": sym, "name": name})
    return sorted(out, key=lambda x: x["name"])


def load_companies(force=False):
    """Return [{'symbol','name'}, ...] — live → cache → seed."""
    if not force and CACHE.exists() and time.time() - CACHE.stat().st_mtime < CACHE_TTL:
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        r = requests.post(URL, headers=HEADERS, timeout=10)
        r.raise_for_status()
        rows = _clean(r.json())
        if rows:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(rows), encoding="utf-8")
            return rows
    except Exception as e:
        print("Company list fetch failed:", e)
    if CACHE.exists():  # stale cache is better than nothing
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return [{"symbol": s, "name": n} for s, n in SEED]


def label(c):
    return f"{c['symbol']}  ·  {c['name'].title()}"


_info_cache = {}      # symbol -> (ts, info)   15 s cache so reruns / fragments never re-hit cse.lk


def get_company_info(symbol, timeout=8):
    hit = _info_cache.get(symbol)
    if hit and time.time() - hit[0] < 15:
        return hit[1]
    try:
        r = requests.post("https://www.cse.lk/api/companyInfoSummery", headers=HEADERS,
                          data={"symbol": symbol}, timeout=timeout)
        r.raise_for_status()
        info = r.json().get("reqSymbolInfo", {}) or {}
        if info:
            _info_cache[symbol] = (time.time(), info)
        return info
    except Exception as e:
        print("Company info failed:", e)
        return hit[1] if hit else {}      # last good value instead of an empty box
