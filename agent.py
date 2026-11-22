"""CSE AI Agent  (READ-ONLY).

* watches the market + news in the background (while the app is running)
* tags every news item with the company / sector it affects and explains it in Sinhala
* sends PC-only Windows notifications for market updates and relevant news
* answers your questions in the app Copilot

It can NEVER buy / sell / edit your portfolio or alerts. It only reads data and sends Windows notifications.
"""
import re
import socket
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from config import OLLAMA_MODEL, OLLAMA_NUM_CTX
from core import database as db

SL = timezone(timedelta(hours=5, minutes=30))     # Sri Lanka time (no DST)
NEWS_EVERY_SEC = 90                               # align alerts with the background news-feed refresh
MAX_NEWS_PER_CYCLE = 6
MORNING_AT = (9, 45)                              # market-open check
CLOSING_AT = (14, 45)                             # after 14:30 close
QUIET_FROM, QUIET_TO = (22, 0), (6, 30)           # no news pings at night

_state = {"next_news_ts": 0.0}
_started = False
_lock_sock = None
LOCK_PORT = 48555                                 # only ONE process (service or app) runs the agent
_ollama_client = None


def now_sl():
    return datetime.now(SL)


def flag(key, default="1"):
    return db.get_setting(key, default) == "1"


def _put(key, value):
    try:
        db.set_setting(f"agent_{key}", str(value))
    except Exception:
        pass


def get_state():
    """Read from DB so the app can show what the background service is doing."""
    hb = db.get_setting("agent_heartbeat", "0")
    try:
        alive = time.time() - float(hb) < 120
    except ValueError:
        alive = False
    return {"running": alive, "last_news_check": db.get_setting("agent_last_news_check"),
            "last_error": db.get_setting("agent_last_error"),
            "sent": int(db.get_setting("agent_sent", "0") or 0)}


# ------------------------------------------------------------------ sectors
SECTORS = {
    "banks": ("බැංකු සහ මූල්‍ය", ["bank", "banks", "banking", "lender", "leasing", "finance company", "npl", "deposit rates", "microfinance"]),
    "insurance": ("රක්ෂණ", ["insurance", "insurer", "life insurance"]),
    "tourism": ("සංචාරක සහ හෝටල්", ["tourism", "tourist", "tourists", "hotel", "hotels", "resort", "arrivals", "hospitality", "airline"]),
    "telecom": ("telecom", ["telecom", "telecommunications", "broadband", "5g", "spectrum", "mobile network"]),
    "plantation": ("වතු සහ කෘෂිකර්ම", ["tea", "rubber", "coconut", "plantation", "plantations", "cinnamon", "palm oil", "paddy"]),
    "energy": ("බලශක්ති", ["electricity", "fuel", "petrol", "diesel", "solar", "ceb", "renewable", "lpg", "energy", "oil price", "power cut"]),
    "manufacturing": ("නිෂ්පාදන සහ අපනයන", ["export", "exports", "garment", "apparel", "textile", "manufacturing", "factory", "exporters"]),
    "construction": ("ඉදිකිරීම් සහ දේපළ", ["construction", "cement", "real estate", "property", "housing", "infrastructure"]),
    "food": ("ආහාර, බීම සහ දුම්කොළ", ["food", "beverage", "beverages", "dairy", "brewery", "liquor", "tobacco", "cigarette", "cigarettes"]),
    "health": ("සෞඛ්‍ය සහ ඖෂධ", ["hospital", "hospitals", "pharma", "pharmaceutical", "healthcare", "medicine", "drug"]),
    "retail": ("සිල්ලර සහ පාරිභෝගික", ["retail", "supermarket", "consumer", "vehicle imports", "vehicles"]),
    "transport": ("ප්‍රවාහන සහ නැව්", ["shipping", "port", "logistics", "container", "aviation", "freight"]),
    "economy": ("ආර්ථිකය / ප්‍රතිපත්ති", ["cbsl", "central bank", "interest rate", "interest rates", "policy rate", "inflation", "rupee", "exchange rate",
                                          "imf", "budget", "tax", "taxes", "treasury bill", "t-bill", "gdp", "debt restructuring", "reserves", "import restrictions"]),
    "market": ("කොටස් වෙළඳපොළ", ["cse", "colombo stock exchange", "aspi", "share market", "stock market", "dividend", "ipo", "rights issue", "takeover", "listed"]),
}


def tag_sectors(text):
    low = (text or "").lower()
    hits = []
    for key, (_label, words) in SECTORS.items():
        if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
            hits.append(key)
    return hits[:3]


# ---------------------------------------------------------------- companies
_LEGAL = {"plc", "limited", "ltd", "pvt", "company", "the", "co"}
_GENERIC = {"sri", "lanka", "lankan", "ceylon", "national", "united", "first", "new", "asian", "group", "holdings",
            "capital", "finance", "bank", "industries", "general", "international", "of", "and", "investments",
            "development", "services", "trading", "global", "lanka's"}
_MANUAL = {"lolc": "LOLC.N0000", "keells": "JKH.N0000", "john keells": "JKH.N0000", "sampath": "SAMP.N0000",
           "dialog": "DIAL.N0000", "hnb": "HNB.N0000", "slt": "SLTL.N0000", "sri lanka telecom": "SLTL.N0000",
           "ceylon tobacco": "CTC.N0000", "commercial bank": "COMB.N0000", "hayleys": "HAYL.N0000",
           "expolanka": "EXPO.N0000", "lion brewery": "LION.N0000", "nestle lanka": "NEST.N0000",
           "cargills": "CARG.N0000", "teejay": "TJL.N0000", "access engineering": "AEL.N0000"}
_index = None


def _tokens(name):
    n = re.sub(r"[().,&]", " ", name.lower())
    toks = [t for t in re.sub(r"\s+", " ", n).split() if t not in _LEGAL]
    out, run = [], []
    for t in toks:                       # "l o l c" -> "lolc"
        if len(t) == 1 and t.isalpha():
            run.append(t)
        else:
            if run:
                out.append("".join(run))
                run = []
            out.append(t)
    if run:
        out.append("".join(run))
    return out


def _prefer(old, new):
    return old is None or (not old[0].endswith(".N0000") and new[0].endswith(".N0000"))


def _build_index():
    from core.companies import load_companies
    comps = load_companies()
    by_sym = {c["symbol"]: c["name"] for c in comps}
    aliases, tickers = {}, {}
    for c in comps:
        sym, name = c["symbol"], c["name"]
        toks = _tokens(name)
        if not toks:
            continue
        cands = set()
        full = " ".join(toks)
        if len(full) >= 5 and not set(toks) <= _GENERIC:
            cands.add(full)
        if len(toks) >= 2:
            two = " ".join(toks[:2])
            if len(two) >= 9 and not set(toks[:2]) <= _GENERIC:
                cands.add(two)
        for a in cands:
            if _prefer(aliases.get(a), (sym, name)):
                aliases[a] = (sym, name)
        base = sym.split(".")[0]
        if len(base) >= 3 and _prefer(tickers.get(base), (sym, name)):
            tickers[base] = (sym, name)
    for a, sym in _MANUAL.items():
        if sym in by_sym:
            aliases[a] = (sym, by_sym[sym])
    return {
        "aliases": [(re.compile(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])"), v) for a, v in aliases.items()],
        "tickers": [(re.compile(rf"(?<![A-Za-z0-9]){re.escape(b)}(?![A-Za-z0-9])"), v) for b, v in tickers.items()],
    }


def find_companies(text, limit=4):
    global _index
    if _index is None:
        _index = _build_index()
    low = re.sub(r"\s+", " ", re.sub(r"[().,&]", " ", (text or "").lower()))
    found = {}
    for rx, (sym, name) in _index["aliases"]:
        if rx.search(low):
            found[sym.split(".")[0]] = (sym, name)
    for rx, (sym, name) in _index["tickers"]:
        if rx.search(text or ""):
            found.setdefault(sym.split(".")[0], (sym, name))
    return list(found.values())[:limit]


# --------------------------------------------------------------- market state
def market_state(status):
    s = (status or "").lower()
    if "pre" in s:
        return "pre"
    from core.live import is_open
    if is_open(s):
        return "open"
    elif "closed" in s:
        return "closed"
    return "closed"
    return "open" if is_open(s) else "closed"


def next_open_text():
    n = now_sl()
    d = n
    if not (n.weekday() < 5 and (n.hour, n.minute) < (9, 30)):
        d = n + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
    days = ["සඳුදා", "අඟහරුවාදා", "බදාදා", "බ්‍රහස්පතින්දා", "සිකුරාදා", "සෙනසුරාදා", "ඉරිදා"]
    when = "අද" if d.date() == n.date() else days[d.weekday()]
    return f"ඊළඟ සැසිය: {when} පෙ.ව. 9:30 (නිවාඩු දිනයක් නොවේ නම්)"


def market_state_si(status):
    st = market_state(status)
    if st == "open":
        return "වෙළඳපොළ විවෘතයි", ""
    if st == "pre":
        return "වෙළඳපොළ ආරම්භ වීමට පෙර", ""
    return "වෙළඳපොළ වසා ඇත", next_open_text()


# ------------------------------------------------------------------------ LLM
SYSTEM_SI = """ඔබ CSE AI Agent ය - ශ්‍රී ලංකා කොළඹ කොටස් වෙළඳපොළ (CSE) සඳහා වන සහායකයෙකි.
නීති:
1. සෑම විටම සරල සිංහලෙන් පිළිතුරු දෙන්න (සමාගම් නම්, සංකේත සහ සංඛ්‍යා ඒවායේ මුල් ස්වරූපයෙන් තබන්න).
2. පහත "සජීවී දත්ත" තුළ ඇති තොරතුරු පමණක් භාවිත කරන්න. නැති දෙයක් සොයා නොගන්න; නැත්නම් 'දත්ත නැත' යැයි කියන්න.
3. ඔබට කිසිවක් මිලදී ගැනීමට, විකිණීමට, portfolio හෝ alerts වෙනස් කිරීමට බැහැ. ඔබ කියවීමට පමණි (read-only). කිසිවක් කළා යැයි කිසිවිටක නොකියන්න.
4. "මිලදී ගන්න" හෝ "විකුණන්න" යනුවෙන් උපදෙස් නොදෙන්න. තත්ත්වය, අවදානම් සහ සැලකිය යුතු කරුණු පැහැදිලි කරන්න. අවසාන තීරණය පරිශීලකයාගේ බව අවශ්‍ය විට සඳහන් කරන්න.
5. කෙටි සහ පැහැදිලි පිළිතුරු දෙන්න."""

SYSTEM_EN = """You are the CSE AI Agent for the Colombo Stock Exchange. Rules: use ONLY the live data given; never invent facts;
you are READ-ONLY and can never buy, sell or change the portfolio/alerts and must never claim you did; never tell the user to buy or sell -
explain the situation, risks and what to watch; keep answers short and clear."""

NEWS_SI = """ඔබ ශ්‍රී ලංකා කොටස් වෙළඳපොළ විශ්ලේෂකයෙකි. ලබා දෙන පුවත සිංහලෙන් වාක්‍ය 2ක් තුළ සරලව පැහැදිලි කරන්න.
ඉන්පසු මෙය සඳහන් සමාගම්/අංශයට ධනාත්මක, ඍණාත්මක හෝ මධ්‍යස්ථ බලපෑමක්ද යන්න එක් වාක්‍යයකින් කියන්න.
පුවතේ නැති දේ සොයා නොගන්න. මිලදී ගන්න/විකුණන්න යැයි උපදෙස් නොදෙන්න. සිංහලෙන් පමණක් පිළිතුරු දෙන්න."""

NEWS_EN = """You are a Sri Lankan stock market analyst. Explain the news in 2 plain sentences, then one sentence on whether it is
positive, negative or neutral for the named companies/sectors. Do not invent facts. Never say buy or sell."""


def _lang():
    return db.get_setting("ai_language", "si")


def _llm(system, user, temperature=0.3, num_ctx=OLLAMA_NUM_CTX, model=None):
    global _ollama_client
    try:
        import ollama
        from core.ai_analyzer import ensure_ollama_running
        ensure_ollama_running()
        if _ollama_client is None:
            _ollama_client = ollama.Client(timeout=45)
        resp = _ollama_client.chat(
            model=model or db.get_setting("ollama_model", OLLAMA_MODEL),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            options={"temperature": temperature, "num_ctx": num_ctx, "num_predict": 120},
            keep_alive="2h")
        return (resp["message"]["content"] or "").strip() or None
    except Exception as e:
        _put("last_error", f"LLM: {type(e).__name__} (Ollama running? model pulled?)")
        return None


# ------------------------------------------------------------------ live data
def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def portfolio_snapshot():
    from core.price_fetcher import get_price_decimal
    from core.financial import divide, to_decimal
    rows, tot_i, tot_c = [], to_decimal("0"), to_decimal("0")
    for h in db.fetch_all("portfolio")[:20]:
        buy = to_decimal(h.get("buy_price_exact") or h["buy_price"])
        shares = to_decimal(h.get("shares_exact") or h["shares"])
        live_price = _safe(lambda: get_price_decimal(h["symbol"], max_age=300), None)
        price = live_price if live_price is not None else buy
        inv, cur = shares * buy, shares * price
        tot_i += inv
        tot_c += cur
        rows.append({"symbol": h["symbol"], "shares": shares, "buy": buy, "price": price,
                     "price_is_live": live_price is not None,
                     "pnl": cur - inv, "pnl_pct": divide((cur - inv) * 100, inv) or to_decimal("0")})
    return rows, tot_i, tot_c


def movers_split(n=3):
    from core.price_fetcher import get_live_market_movers
    m = [x for x in _safe(get_live_market_movers, []) if x.get("turnover", 0) > 0]
    up = sorted(m, key=lambda x: x["change_pct"], reverse=True)[:n]
    down = sorted(m, key=lambda x: x["change_pct"])[:n]
    return up, down


def tagged_news(limit=15):
    from core.news_fetcher import fetch_latest_news
    out = []
    for it in _safe(lambda: fetch_latest_news(limit_per_source=limit, wait_if_empty=False), []):
        comps, secs = find_companies(it["title"]), tag_sectors(it["title"])
        out.append({**it, "companies": comps, "sectors": secs})
    return out


LBL = {
    "si": dict(status="වෙළඳපොළ තත්ත්වය", asof="දත්ත වේලාව", turnover="මාරුවීම් අගය", trades="ගනුදෙනු", up="ඉහළම ලාභ",
               down="ඉහළම පාඩු", pf="පරිශීලකයාගේ portfolio", invested="ආයෝජනය", value="වර්තමාන වටිනාකම", pnl="ලාභ/අලාභ",
               nopf="පරිශීලකයාගේ portfolio: සටහන් කර නැත", shares="කොටස්", bought="මිලදී ගත්", now="දැන්",
               company="සමාගම", news="පුවත"),
    "en": dict(status="Market status", asof="Data as of", turnover="Turnover", trades="Trades", up="Top gainers",
               down="Top losers", pf="User portfolio", invested="Invested", value="Current value", pnl="P/L",
               nopf="User portfolio: none recorded", shares="shares", bought="bought at", now="now",
               company="Company", news="News"),
}


def _short(name):
    return re.sub(r"\s+plc$", "", name.title(), flags=re.I)


def _sinhala_ok(t):
    """Small models often output broken Sinhala. Accept only if it looks like real, non-looping Sinhala."""
    if not t:
        return False
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 10:
        return False
    si = sum(1 for c in letters if "\u0d80" <= c <= "\u0dff")
    if si / len(letters) < 0.35:
        return False
    words = t.split()
    return not (len(words) > 12 and len(set(words)) / len(words) < 0.4)


def _fmt_company_info(sym):
    from core.companies import get_company_info
    i = _safe(lambda: get_company_info(sym, timeout=2), {})
    if not i:
        return f"{sym}: n/a"
    return (f"{i.get('name', sym)} ({sym}): last LKR {float(i.get('lastTradedPrice') or 0):,.2f}, "
            f"change {float(i.get('change') or 0):+,.2f} ({float(i.get('changePercentage') or 0):+.2f}%), "
            f"prev close {float(i.get('previousClose') or 0):,.2f}, mkt cap LKR {float(i.get('marketCap') or 0)/1e9:,.1f} Bn")


def live_context(question="", lang=None):
    from core.price_fetcher import get_market_overview
    L = LBL[lang or _lang()]
    ov = _safe(get_market_overview, {})
    lines = []
    if ov:
        si, _ = market_state_si(ov.get("status", ""))
        lines += [f"{L['status']}: {ov.get('status')}" + (f" ({si})" if (lang or _lang()) == "si" else "") + f" | {L['asof']}: {ov.get('last_updated')}",
                  f"ASPI: {ov['aspi']:,.2f} ({ov['aspi_change']:+.2f} / {ov['aspi_pct']:+.2f}%)",
                  f"S&P SL20: {ov['snp']:,.2f} ({ov['snp_change']:+.2f} / {ov['snp_pct']:+.2f}%)",
                  f"{L['turnover']}: LKR {ov['turnover']/1e6:,.1f} Mn | {L['trades']}: {ov['trades']:,}"]
    up, down = movers_split()
    if up:
        lines.append(f"{L['up']}: " + ", ".join(f"{x['symbol']} {x['change_pct']:+.1f}%" for x in up))
        lines.append(f"{L['down']}: " + ", ".join(f"{x['symbol']} {x['change_pct']:+.1f}%" for x in down))
    rows, ti, tc = portfolio_snapshot()
    if rows:
        estimated = any(not r["price_is_live"] for r in rows)
        estimate_note = " (includes buy-price estimates where live quotes are unavailable)" if estimated else ""
        lines.append(f"{L['pf']}: {L['invested']} LKR {ti:,.0f}, {L['value']} LKR {tc:,.0f}, "
                     f"{L['pnl']} {tc-ti:+,.0f} ({(tc-ti)/ti*100 if ti else 0:+.2f}%){estimate_note}")
        lines += [f"  - {r['symbol']}: {r['shares']:,.0f} {L['shares']}, {L['bought']} {r['buy']:.2f}, {L['now']} {r['price']:.2f} ({r['pnl_pct']:+.1f}%)" + (" [buy-price estimate; live quote unavailable]" if not r["price_is_live"] else "") for r in rows]
    else:
        lines.append(L["nopf"])
    mentioned = find_companies(question, 2)
    for sym, _ in mentioned:
        lines.append(f"{L['company']}: " + _fmt_company_info(sym))
    news = tagged_news(8)
    rel = [n for n in news if set(n["companies"]) & set(mentioned)] if mentioned else []
    for n in (rel + news)[:6]:
        tag = ", ".join(s for _, s in n["companies"]) or ", ".join(SECTORS[x][0] for x in n["sectors"]) or "-"
        lines.append(f"{L['news']}: {n['title']} [{tag}]")
    return "\n".join(lines)


def answer(question, model=None):
    """Copilot answer. Sinhala first; if the small model's Sinhala is broken -> English answer; else raw facts."""
    lang = _lang()
    # Use one compact, English-labeled snapshot for both language attempts. Re-fetching
    # it on Sinhala fallback repeated CSE/news lookups before the second model call.
    ctx = live_context(question, "en")
    if lang == "si":
        reply = _llm(SYSTEM_SI, f"සජීවී දත්ත:\n{ctx}\n\nප්‍රශ්නය: {question}", 0.2, OLLAMA_NUM_CTX, model)
        if reply and _sinhala_ok(reply):
            return reply
        if not reply:
            return "The local AI model did not respond. Please try again in a moment. Live data:\n\n" + ctx
        en = _llm(SYSTEM_EN, f"Live data:\n{ctx}\n\nQuestion: {question}\nAnswer in English.", 0.2, OLLAMA_NUM_CTX, model)
        if en:
            return "⚠️ AI model එකට (1.5b) සිංහලෙන් හොඳින් පිළිතුරු දිය නොහැකි විය. English පිළිතුර:\n\n" + en
        return "AI model එකට සම්බන්ධ විය නොහැකි විය (Ollama ධාවනය වෙනවාදැයි බලන්න). සජීවී දත්ත:\n\n" + ctx
    reply = _llm(SYSTEM_EN, f"Live data:\n{ctx}\n\nQuestion: {question}", 0.2, OLLAMA_NUM_CTX, model)
    return reply or ("AI unavailable (is Ollama running?). Live data:\n\n" + ctx)


# ------------------------------------------------------------------- messages
def _desktop_on():
    return sys.platform == "win32" and flag("agent_desktop")


def notify(text):
    """Deliver notifications to this Windows PC only."""
    if not _desktop_on():
        return False
    from core.desktop_notify import toast
    head, _, body = text.partition("\n")
    body = " ".join(x.strip() for x in body.split("\n") if x.strip())
    return toast(head, body)


def _channel_ready():
    return _desktop_on()


def _market_block(ov):
    return (f"📈 ASPI: {ov['aspi']:,.2f} ({ov['aspi_change']:+.2f} / {ov['aspi_pct']:+.2f}%)\n"
            f"📊 S&P SL20: {ov['snp']:,.2f} ({ov['snp_change']:+.2f} / {ov['snp_pct']:+.2f}%)\n"
            f"💰 මාරුවීම්: LKR {ov['turnover']/1e6:,.1f} Mn | ගනුදෙනු {ov['trades']:,}")


def _movers_block():
    up, down = movers_split()
    if not up:
        return ""
    return ("\n🟢 ඉහළම: " + ", ".join(f"{x['symbol'].split('.')[0]} {x['change_pct']:+.1f}%" for x in up) +
            "\n🔴 පහළම: " + ", ".join(f"{x['symbol'].split('.')[0]} {x['change_pct']:+.1f}%" for x in down))


def _portfolio_block():
    rows, ti, tc = portfolio_snapshot()
    if not rows:
        return ""
    return f"\n\n💼 ඔබේ portfolio: LKR {tc:,.0f} ({tc-ti:+,.0f} / {(tc-ti)/ti*100 if ti else 0:+.2f}%)"


def _commentary(kind):
    if _lang() != "si":
        return ""
    txt = _llm(SYSTEM_SI, f"සජීවී දත්ත:\n{live_context()}\n\n{kind} වෙළඳපොළ ගැන සිංහලෙන් වාක්‍ය 2ක සාරාංශයක් ලියන්න.", 0.3, OLLAMA_NUM_CTX)
    return f"\n\n🧠 {txt}" if txt and _sinhala_ok(txt) else ""


def morning_message():
    from core.price_fetcher import get_market_overview
    ov = get_market_overview()
    st = market_state(ov["status"])
    if st == "open":
        head = "🟢 සුභ උදෑසනක්! අද කොටස් වෙළඳපොළ විවෘතයි."
    elif st == "pre":
        head = "🟡 වෙළඳපොළ ආරම්භ වීමට සූදානම් (Pre-open)."
    else:
        head = "🔴 අද වෙළඳපොළ වසා ඇත (නිවාඩු දිනයක් විය හැක). " + next_open_text()
    msg = head + "\n\n" + _market_block(ov) + _movers_block() + _portfolio_block()
    n_rel = sum(1 for n in tagged_news(8) if n["companies"] or n["sectors"])
    if n_rel:
        msg += f"\n\n📰 අදට අදාළ පුවත් {n_rel}ක් තිබේ."
    if st != "closed":
        msg += _commentary("අද")
    return msg + "\n\n📲 වැඩි විස්තර බැලීමට App එක විවෘත කරන්න."


def closing_message():
    from core.price_fetcher import get_market_overview
    ov = get_market_overview()
    head = "🔔 අද වෙළඳපොළ වසා දැමීම" if market_state(ov["status"]) != "open" else "🔔 වෙළඳපොළ තවමත් විවෘතයි"
    return head + "\n\n" + _market_block(ov) + _movers_block() + _portfolio_block() + _commentary("අද දවසේ") + "\n\n📲 App එකේ සම්පූර්ණ විස්තර බලන්න."


SENT_SI = {"POSITIVE": "ධනාත්මක බලපෑමක් විය හැක", "NEGATIVE": "ඍණාත්මක බලපෑමක් විය හැක",
           "NEUTRAL": "විශේෂ බලපෑමක් නොමැති බව පෙනේ"}
_POS = ("profit", "surge", "jump", "record", "growth", "gain", "dividend", "upgrade", "strong", "boost", "recovery", "wins", "expands")
_NEG = ("loss", "fall", "drop", "slump", "decline", "default", "downgrade", "fraud", "probe", "penalty", "shortage", "crisis", "suspend", "plunge", "ban")


def sentiment(title, target):
    out = _llm("Reply with exactly one word: POSITIVE, NEGATIVE or NEUTRAL (effect of this news on the share price or sector).",
               f"News: {title}\nAffected: {target}", 0, OLLAMA_NUM_CTX)
    if out:
        u = out.upper()
        for k in ("POSITIVE", "NEGATIVE", "NEUTRAL"):
            if k in u:
                return k
    low = title.lower()
    p, n = sum(w in low for w in _POS), sum(w in low for w in _NEG)
    return "POSITIVE" if p > n else "NEGATIVE" if n > p else "NEUTRAL"


def news_message(item, companies, sectors, in_portfolio):
    parts = [f"📰 නව පුවතක් ({item['source'].split(' (')[0]})", item["title"]]
    if companies:
        parts.append("🏢 සමාගම්: " + ", ".join(f"{_short(n)} ({s})" for s, n in companies))
    if sectors:
        parts.append("📂 අංශය: " + ", ".join(SECTORS[s][0] for s in sectors))
    if in_portfolio:
        parts.append("⭐ මෙය ඔබේ portfolio/alerts එකේ සමාගමක් ගැන!")
    target = ", ".join(_short(n) for _, n in companies) or ", ".join(SECTORS[s][0] for s in sectors)
    parts.append(f"🧠 මෙය {target} සඳහා {SENT_SI[sentiment(item['title'], target)]}. (AI අනුමානයක් පමණි - ආයෝජන උපදෙසක් නොවේ)")
    if _lang() == "si":
        why = _llm(NEWS_SI, f"පුවත: {item['title']}\nසමාගම්: {', '.join(n for _, n in companies) or '-'}", 0.2, OLLAMA_NUM_CTX)
        if why and _sinhala_ok(why):
            parts.append("📝 " + why)
    if item.get("link"):
        parts.append("🔗 " + item["link"])
    return "\n".join(parts)


# ------------------------------------------------------------------ monitors
def _watched_symbols():
    rows = db.fetch_all("portfolio") + [a for a in db.fetch_all("alerts") if a["active"]]
    return {r["symbol"].split(".")[0] for r in rows}


def check_news(force=False):
    """Fetch news, tag company/sector, push relevant NEW items. Returns number sent."""
    from core.news_fetcher import fetch_latest_news
    _put("last_news_check", now_sl().strftime("%Y-%m-%d %H:%M"))
    items = fetch_latest_news(limit_per_source=15)
    if not items:
        return 0
    if not db.any_news_seen():                       # first ever run: remember, don't spam old news
        for it in items:
            db.mark_news(it["link"] or it["title"])
        db.log_agent("news", f"baseline: {len(items)} existing items noted")
        return 0
    if not _channel_ready() and not force:
        return 0
    watched, sent = _watched_symbols(), 0
    for it in items:
        key = it["link"] or it["title"]
        if db.news_seen(key):
            continue
        if sent >= MAX_NEWS_PER_CYCLE:
            break
        comps, secs = find_companies(it["title"]), tag_sectors(it["title"])
        if not comps and not secs:
            db.mark_news(key)
            continue
        hit = any(s.split(".")[0] in watched for s, _ in comps)
        if notify(news_message(it, comps, secs, hit)):
            db.mark_news(key)
            sent += 1
            _put("sent", int(db.get_setting("agent_sent", "0") or 0) + 1)
            db.log_agent("news", it["title"])
        else:
            db.log_agent("error", "news notification failed (Windows PC popup)")
            break
    return sent


def send_morning():
    ok = notify(morning_message())
    db.log_agent("morning" if ok else "error", "morning brief " + ("sent" if ok else "FAILED"))
    return ok


def send_closing():
    ok = notify(closing_message())
    db.log_agent("closing" if ok else "error", "closing summary " + ("sent" if ok else "FAILED"))
    return ok


def _minutes(t):
    return t[0] * 60 + t[1]


def _in_quiet(now):
    m = now.hour * 60 + now.minute
    return m >= _minutes(QUIET_FROM) or m < _minutes(QUIET_TO)


def tick(now=None):
    now = now or now_sl()
    today = now.strftime("%Y-%m-%d")
    m = now.hour * 60 + now.minute
    if flag("agent_news") and not _in_quiet(now) and time.time() >= _state["next_news_ts"]:
        _state["next_news_ts"] = time.time() + NEWS_EVERY_SEC
        check_news()
    if now.weekday() < 5 and _channel_ready():
        if flag("agent_morning") and _minutes(MORNING_AT) <= m < 12 * 60 and db.get_setting("last_morning") != today:
            if send_morning():
                db.set_setting("last_morning", today)
        if flag("agent_closing") and _minutes(CLOSING_AT) <= m < 18 * 60 and db.get_setting("last_closing") != today:
            if send_closing():
                db.set_setting("last_closing", today)


def _loop():
    while True:
        _put("heartbeat", time.time())
        try:
            tick()
        except Exception as e:
            _put("last_error", f"{type(e).__name__}: {str(e)[:120]}")
        time.sleep(30)


def _acquire_lock():
    global _lock_sock
    sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sk.bind(("127.0.0.1", LOCK_PORT))
        sk.listen(1)
        _lock_sock = sk
        return True
    except OSError:
        sk.close()
        return False


def start_agent():
    """Start the background agent once per PC. Returns True if THIS process runs it
    (False = the background service is already running it)."""
    global _started
    if _started:
        return True
    if not _acquire_lock():
        return False
    _started = True
    from core import alerts
    threading.Thread(target=_loop, daemon=True).start()
    alerts.start_background()
    return True
