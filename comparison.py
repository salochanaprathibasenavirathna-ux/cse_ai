"""Financial ratio calculations and local-AI commentary for peer comparisons."""
from decimal import Decimal

from core.financial import divide, to_decimal

MILLION = Decimal("1000000")
METRICS = (
    ("net_profit_margin", "Net Profit Margin", "%"),
    ("roe", "ROE", "%"),
    ("eps", "EPS", "LKR"),
    ("debt_to_equity", "Debt-to-Equity Ratio", "x"),
    ("current_ratio", "Current Ratio", "x"),
    ("pe_ratio", "P/E Ratio", "x"),
    ("pb_ratio", "P/B Ratio", "x"),
    ("dividend_yield", "Dividend Yield", "%"),
    ("asset_turnover", "Asset Turnover Ratio", "x"),
)


def _value(report, name):
    exact = report.get(f"{name}_exact")
    return to_decimal(exact if exact is not None else report.get(name), default=None)


def calculate_metrics(report, price):
    """Calculate ratios from a saved report and current price; missing data stays None.

    Statement totals use LKR millions, as in the report analyzer. Per-share metrics
    are expressed in LKR and use the explicitly entered share count.
    """
    assets = _value(report, "assets")
    liabilities = _value(report, "liabilities")
    equity = _value(report, "equity")
    revenue = _value(report, "revenue")
    profit = _value(report, "net_profit")
    current_assets = _value(report, "current_assets")
    current_liabilities = _value(report, "current_liabilities")
    shares = _value(report, "shares_outstanding")
    reported_eps = _value(report, "eps")
    dividend_per_share = _value(report, "dividend_per_share")
    price = to_decimal(price, default=None)

    eps = reported_eps
    if eps is None and profit is not None and shares:
        eps = divide(profit * MILLION, shares)
    book_value_per_share = divide(equity * MILLION, shares) if equity is not None and shares else None

    return {
        "net_profit_margin": divide(profit * Decimal("100"), revenue) if profit is not None and revenue is not None else None,
        "roe": divide(profit * Decimal("100"), equity) if profit is not None and equity is not None else None,
        "eps": eps,
        "debt_to_equity": divide(liabilities, equity) if liabilities is not None and equity is not None else None,
        "current_ratio": divide(current_assets, current_liabilities)
        if current_assets is not None and current_liabilities is not None else None,
        "pe_ratio": divide(price, eps) if price is not None and eps is not None else None,
        "pb_ratio": divide(price, book_value_per_share) if price is not None and book_value_per_share is not None else None,
        "dividend_yield": divide(dividend_per_share * Decimal("100"), price)
        if dividend_per_share is not None and price is not None else None,
        "asset_turnover": divide(revenue, assets) if revenue is not None and assets is not None else None,
    }


def explain_comparison(company_a, metrics_a, company_b, metrics_b, model):
    """Ask the configured local Ollama model to interpret already-calculated ratios."""
    import ollama
    from config import OLLAMA_NUM_CTX
    from core.ai_analyzer import ensure_ollama_running

    ensure_ollama_running()
    rows = []
    for key, label, unit in METRICS:
        a = metrics_a.get(key)
        b = metrics_b.get(key)
        rows.append(f"{label} ({unit}): {company_a}={a if a is not None else 'unavailable'}; "
                    f"{company_b}={b if b is not None else 'unavailable'}")
    prompt = (
        "Compare these two CSE companies objectively using only the supplied calculated metrics. "
        "Do not recalculate or invent values. Discuss strengths, risks, missing data, and suitability "
        "for different investor priorities; do not make a buy/sell recommendation. "
        "This is educational information, not investment advice.\n\n" + "\n".join(rows)
    )
    response = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0, "num_ctx": OLLAMA_NUM_CTX},
        keep_alive="2h",
    )
    return response["message"]["content"]
