"""Price / market data access.

Everything here is a thin, INSTANT wrapper over core.live (the shared background snapshot), so the
dashboard, explorer, portfolio, alerts and the AI agent all see exactly the same numbers.
Function names are unchanged, so the rest of the app keeps working.
"""
import time
from decimal import Decimal

import requests

from core import live
from core.financial import to_decimal

_single = {}      # symbol -> (ts, price)   tiny fallback cache for symbols missing from the snapshot
_single_decimal = {}


def get_price(symbol):
    """Last traded price. Snapshot first (instant); if the symbol is not in it, ask cse.lk once (cached 20 s)."""
    p = live.price(symbol)
    if p:
        return p
    hit = _single.get(symbol)
    if hit and time.time() - hit[0] < 20:
        return hit[1]
    try:
        r = requests.post(live.BASE + "companyInfoSummery", data={"symbol": symbol},
                          headers=live.HEADERS, timeout=8)
        info = r.json().get("reqSymbolInfo", {}) or {}
        p = float(info.get("lastTradedPrice") or 0) or None
        if p:
            _single[symbol] = (time.time(), p)
        return p
    except Exception as e:
        print("Price fetch failed:", e)
        return hit[1] if hit else None


def get_price_decimal(symbol, max_age=None):
    """Exact Decimal quote for financial calculations; presentation callers can use get_price()."""
    price = live.price_decimal(symbol, max_age=max_age)
    if price is not None:
        return price
    # A caller that specifies a freshness limit (alerts and portfolio valuation)
    # must not fall back to an un-timestamped quote from the company-info API.
    if max_age is not None:
        return None
    hit = _single_decimal.get(symbol)
    if hit and time.time() - hit[0] < 20:
        return hit[1]
    try:
        response = requests.post(
            live.BASE + "companyInfoSummery",
            data={"symbol": symbol},
            headers=live.HEADERS,
            timeout=8,
        )
        response.raise_for_status()
        info = response.json(parse_float=Decimal, parse_int=Decimal).get("reqSymbolInfo", {}) or {}
        price = to_decimal(info.get("lastTradedPrice"), default=None)
        if price is not None and price > 0:
            _single_decimal[symbol] = (time.time(), price)
            return price
        return None
    except Exception as e:
        print("Exact price fetch failed:", e)
        return hit[1] if hit else None


def get_market_overview():
    """ASPI, S&P SL20, status, turnover, trades. Never zeros after a failed refresh (last good value is kept)."""
    return live.overview()


def get_live_market_movers():
    """Stocks that actually traded today, MOST TRADED (by turnover) first."""
    return [r for r in live.trades() if r["volume"] > 0]


def get_market_breadth():
    return live.breadth()
