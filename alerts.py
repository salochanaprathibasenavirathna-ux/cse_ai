import threading
import time
from core import database as db
from core.price_fetcher import get_price_decimal
from core.financial import to_decimal
from config import CHECK_INTERVAL_SEC

_started = False


def check_once():
    fired = 0
    for a in db.fetch_all("alerts"):
        if not a["active"]:
            continue
        # Alerts must not fire on an old quote left in the in-memory snapshot.
        price = get_price_decimal(a["symbol"], max_age=180)
        if price is None:
            continue
        current = to_decimal(price)
        target = to_decimal(a.get("target_exact") or a["target"])
        hit = (a["kind"] == "above" and current >= target) or \
              (a["kind"] in ("below", "stop-loss") and current <= target)
        if hit:
            from core.agent import notify
            if notify(f"Price alert: {a['symbol']}\nPrice {current} hit {a['kind']} {target}"):
                db.add_row("UPDATE alerts SET active=0 WHERE id=?", (a["id"],))
                fired += 1
    return fired


def start_background():
    global _started
    if _started:
        return
    _started = True

    def loop():
        while True:
            try:
                check_once()
            except Exception as e:
                print("alert loop error:", e)
            time.sleep(CHECK_INTERVAL_SEC)

    threading.Thread(target=loop, daemon=True).start()
