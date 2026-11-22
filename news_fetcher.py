"""Business news (EconomyNext + Ada Derana) with a built-in cache.

* feeds are fetched in PARALLEL (was one after the other)
* result is cached for 90 s, so opening the News tab / the AI agent never waits on the network
* if a feed is down we keep its last good headlines instead of showing nothing
"""
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

FEEDS = [
    {"source": "EconomyNext (Business)", "url": "https://economynext.com/feed/"},
    {"source": "Ada Derana (Business)", "url": "https://www.adaderana.lk/rss.php?category=4"},
]
TTL = 90
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

_lock = threading.Lock()
_cache = {}            # source -> list of articles (last good)
_cache_ts = 0.0
_refreshing = False


def _fetch_feed(feed, per_feed=20):
    req = urllib.request.Request(feed["url"], headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=6) as response:
        root = ET.fromstring(response.read())
    out = []
    for it in root.findall(".//item")[:per_feed]:
        t, l, d = it.find("title"), it.find("link"), it.find("pubDate")
        out.append({
            "source": feed["source"],
            "title": t.text.strip() if t is not None and t.text else "No Title",
            "link": l.text.strip() if l is not None and l.text else "",
            "pub_date": d.text.strip() if d is not None and d.text else "",
        })
    return out


def _configured_feeds():
    feeds = list(FEEDS)
    try:
        from core import database as db
        url = db.get_setting("cse_announcements_feed_url").strip()
    except Exception:
        url = ""
    if url:
        feeds.append({"source": "CSE Announcements", "url": url})
    return feeds


def _refresh():
    global _cache_ts
    feeds = _configured_feeds()
    with ThreadPoolExecutor(max_workers=len(feeds)) as ex:
        futs = {f["source"]: ex.submit(_fetch_feed, f) for f in feeds}
        for src, fut in futs.items():
            try:
                items = fut.result(timeout=9)
                if items:
                    _cache[src] = items
            except Exception as e:
                print(f"Error fetching news from {src}: {e}")
    _cache_ts = time.time()


def _refresh_bg():
    global _refreshing
    try:
        with _lock:
            _refresh()
    finally:
        _refreshing = False


def fetch_latest_news(limit_per_source=5, force=False, wait_if_empty=True):
    """Recent business headlines. Never blocks the UI once there is something cached:
    stale cache is returned immediately and refreshed in the background. Callers that
    only need optional context can also request a background first fetch."""
    global _refreshing
    if force or (not _cache and wait_if_empty):
        with _lock:                       # first load (or forced): wait for real data
            _refresh()
    elif not _cache or time.time() - _cache_ts > TTL:
        with _lock:
            if not _refreshing:
                _refreshing = True
                threading.Thread(target=_refresh_bg, daemon=True).start()
    out = []
    for f in _configured_feeds():
        out.extend(_cache.get(f["source"], [])[:limit_per_source])
    return out
