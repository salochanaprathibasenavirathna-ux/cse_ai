import sqlite3
from contextlib import contextmanager
from config import DB_PATH, DATA_DIR, UPLOAD_DIR
from core.financial import decimal_text

TABLES = {"reports", "dividends", "alerts", "journal", "portfolio", "agent_log"}


@contextmanager
def get_conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT, period TEXT,
            assets REAL, liabilities REAL, equity REAL,
            revenue REAL, net_profit REAL,
            score INTEGER, summary TEXT,
            current_assets_exact TEXT, current_liabilities_exact TEXT,
            shares_outstanding_exact TEXT, eps_exact TEXT, dividend_per_share_exact TEXT,
            assets_exact TEXT, liabilities_exact TEXT, equity_exact TEXT,
            revenue_exact TEXT, net_profit_exact TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS dividends(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, amount REAL, pay_date TEXT, amount_exact TEXT,
            shares_exact TEXT, dividend_per_share_exact TEXT);
        CREATE TABLE IF NOT EXISTS alerts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, target REAL, kind TEXT,
            active INTEGER DEFAULT 1, target_exact TEXT);
        CREATE TABLE IF NOT EXISTS journal(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, action TEXT, reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS portfolio(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, shares REAL, buy_price REAL, buy_date TEXT,
            shares_exact TEXT, buy_price_exact TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS seen_news(
            link TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS agent_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT, message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """)
        # Add exact TEXT columns to databases created by earlier app versions.
        migrations = {
            "reports": {
                "current_assets_exact": "TEXT", "current_liabilities_exact": "TEXT",
                "shares_outstanding_exact": "TEXT", "eps_exact": "TEXT",
                "dividend_per_share_exact": "TEXT", "assets_exact": "TEXT",
                "liabilities_exact": "TEXT", "equity_exact": "TEXT",
                "revenue_exact": "TEXT", "net_profit_exact": "TEXT",
            },
            "dividends": {"amount_exact": "TEXT", "shares_exact": "TEXT",
                          "dividend_per_share_exact": "TEXT"},
            "alerts": {"target_exact": "TEXT"},
            "portfolio": {"shares_exact": "TEXT", "buy_price_exact": "TEXT"},
        }
        for table, columns in migrations.items():
            existing = {row["name"] for row in c.execute(f"PRAGMA table_info({table})")}
            for name, kind in columns.items():
                if name not in existing:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
        # Preserve existing records; prior REAL values can only be migrated to their stored
        # decimal text representation, so historical binary-float errors cannot be recovered.
        for table, exact, legacy in (
            ("reports", "assets_exact", "assets"), ("reports", "liabilities_exact", "liabilities"),
            ("reports", "equity_exact", "equity"), ("reports", "revenue_exact", "revenue"),
            ("reports", "net_profit_exact", "net_profit"), ("dividends", "amount_exact", "amount"),
            ("alerts", "target_exact", "target"), ("portfolio", "shares_exact", "shares"),
            ("portfolio", "buy_price_exact", "buy_price"),
        ):
            c.execute(f"UPDATE {table} SET {exact}=CAST({legacy} AS TEXT) "
                      f"WHERE {exact} IS NULL AND {legacy} IS NOT NULL")

        # Notification delivery is now Windows-PC only; discard obsolete channel secrets.
        c.execute(
            "DELETE FROM settings WHERE key IN (?,?,?,?,?,?,?)",
            ("whatsapp_phone", "callmebot_key", "whatsapp_access_token",
             "whatsapp_phone_number_id", "whatsapp_api_version", "telegram_token",
             "telegram_chat_id"),
        )
        c.execute("DELETE FROM settings WHERE key='telegram_pending'")


def save_report(d):
    with get_conn() as c:
        c.execute(
            """INSERT INTO reports(company,period,assets,liabilities,equity,
               revenue,net_profit,score,summary,current_assets_exact,
               current_liabilities_exact,shares_outstanding_exact,eps_exact,
               dividend_per_share_exact,assets_exact,liabilities_exact,equity_exact,
               revenue_exact,net_profit_exact) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (d["company"], d["period"], *_legacy_values(d),
             d["score"], d["summary"],
             decimal_text(d.get("current_assets")), decimal_text(d.get("current_liabilities")),
             decimal_text(d.get("shares_outstanding")), decimal_text(d.get("eps")),
             decimal_text(d.get("dividend_per_share")), decimal_text(d.get("assets")),
             decimal_text(d.get("liabilities")), decimal_text(d.get("equity")),
             decimal_text(d.get("revenue")), decimal_text(d.get("net_profit"))))


def _legacy_values(d):
    """Maintain old REAL fields for compatibility while exact TEXT columns are authoritative."""
    names = ("assets", "liabilities", "equity", "revenue", "net_profit")
    return tuple(float(d[name]) if d.get(name) is not None else None for name in names)


def fetch_all(table):
    if table not in TABLES:
        raise ValueError("bad table")
    with get_conn() as c:
        return [dict(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY id DESC")]


def add_row(sql, params=()):
    with get_conn() as c:
        c.execute(sql, params)


def delete_row(table, row_id):
    if table not in TABLES:
        raise ValueError("bad table")
    with get_conn() as c:
        c.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))


def get_setting(key, default=""):
    with get_conn() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(key, value):
    with get_conn() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


# ---- AI agent helpers (news de-duplication + activity log)
def news_seen(key):
    with get_conn() as c:
        return c.execute("SELECT 1 FROM seen_news WHERE link=?", (key,)).fetchone() is not None


def mark_news(key):
    with get_conn() as c:
        c.execute("INSERT OR IGNORE INTO seen_news(link) VALUES(?)", (key,))


def any_news_seen():
    with get_conn() as c:
        return c.execute("SELECT 1 FROM seen_news LIMIT 1").fetchone() is not None


def log_agent(kind, message):
    with get_conn() as c:
        c.execute("INSERT INTO agent_log(kind,message) VALUES(?,?)", (kind, str(message)[:600]))
        c.execute("DELETE FROM agent_log WHERE id NOT IN (SELECT id FROM agent_log ORDER BY id DESC LIMIT 300)")
