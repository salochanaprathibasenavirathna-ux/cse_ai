import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from core.financial import to_decimal

GREEN, RED, AMBER, BLUE = "#22c55e", "#f43f5e", "#f59e0b", "#22d3ee"   # gain / loss / warn / accent
PALETTE = [BLUE, GREEN, "#a78bfa", AMBER, "#f472b6", "#818cf8", RED]


def _style(fig, height=340):
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#cbd5e1", family="Plus Jakarta Sans, Inter, Segoe UI, sans-serif"),
        margin=dict(l=10, r=10, t=50, b=10), height=height,
        title=dict(font=dict(size=16)),
        legend=dict(orientation="h", y=-0.15),
        hoverlabel=dict(
            bgcolor="#0d121c",
            bordercolor="rgba(34, 211, 238, 0.45)",
            font=dict(color="#f8fafc", family="Plus Jakarta Sans, sans-serif"),
        ),
        hovermode="closest",
        transition=dict(duration=500, easing="cubic-in-out"),
    )
    fig.update_xaxes(gridcolor="rgba(148,163,184,0.09)")
    fig.update_yaxes(gridcolor="rgba(148,163,184,0.09)")
    return fig


def _score_color(s):
    return GREEN if s >= 70 else AMBER if s >= 40 else RED


def balance_bar(d):
    items = ["Assets", "Liabilities", "Equity"]
    vals = [d["assets"], d["liabilities"], d["equity"]]
    fig = go.Figure(go.Bar(x=items, y=vals, marker_color=[BLUE, RED, GREEN],
                           text=[f"{v:,.0f}" for v in vals], textposition="outside"))
    fig.update_layout(title="Balance Sheet (LKR Mn)")
    return _style(fig)


def funding_donut(d):
    fig = go.Figure(go.Pie(labels=["Liabilities", "Equity"],
                           values=[max(d["liabilities"], 0), max(d["equity"], 0)],
                           hole=0.6, marker=dict(colors=[RED, GREEN]),
                           textinfo="label+percent"))
    fig.update_layout(title="Funding Structure")
    return _style(fig)


def profit_donut(d):
    cost = max(d["revenue"] - d["net_profit"], 0)
    fig = go.Figure(go.Pie(labels=["Net profit", "Costs & tax"],
                           values=[max(d["net_profit"], 0), cost],
                           hole=0.6, marker=dict(colors=[GREEN, "#475569"]),
                           textinfo="label+percent"))
    fig.update_layout(title="Where Revenue Goes")
    return _style(fig)


def score_gauge(score):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=score,
        number=dict(suffix=" / 100", font=dict(size=34)),
        gauge=dict(
            axis=dict(range=[0, 100]), bar=dict(color=_score_color(score)),
            bgcolor="rgba(255,255,255,0.04)",
            steps=[dict(range=[0, 40], color="rgba(239,68,68,0.20)"),
                   dict(range=[40, 70], color="rgba(245,158,11,0.20)"),
                   dict(range=[70, 100], color="rgba(34,197,94,0.20)")])))
    fig.update_layout(title="Financial Health Score")
    return _style(fig)


def score_bars(rows):
    df = pd.DataFrame(rows).drop_duplicates("company")
    fig = go.Figure(go.Bar(x=df["company"], y=df["score"],
                           marker_color=[_score_color(s) for s in df["score"]],
                           text=df["score"], textposition="outside"))
    fig.update_layout(title="Health Score by Company (latest)")
    fig.update_yaxes(range=[0, 110])
    return _style(fig)


def compare(rows, metric="net_profit"):
    df = pd.DataFrame(rows)
    fig = px.bar(df, x="company", y=metric, color="period", barmode="group",
                 color_discrete_sequence=PALETTE, title=f"Comparison: {metric}")
    return _style(fig, 400)


def ratio_compare(metric, company_a, value_a, company_b, value_b, unit=""):
    """Side-by-side plot of a single Decimal ratio (float conversion is display-only)."""
    pairs = [(company_a, value_a), (company_b, value_b)]
    labels = [name for name, value in pairs if value is not None]
    values = [float(value) for _, value in pairs if value is not None]
    if not values:
        return None
    fig = go.Figure(go.Bar(
        x=labels, y=values, marker_color=[BLUE, AMBER][:len(values)],
        text=[f"{value:,.2f}{unit}" for value in values], textposition="outside",
    ))
    fig.update_layout(title=metric, showlegend=False)
    return _style(fig, 330)


def dividends_by_year(rows):
    totals = {}
    for row in rows:
        year = str(row.get("pay_date") or "")[:4]
        amount = to_decimal(row.get("amount_exact") or row.get("amount"), default=None)
        if year and amount is not None:
            totals[year] = totals.get(year, to_decimal("0")) + amount
    g = pd.DataFrame([{"year": year, "amount": float(amount)}
                      for year, amount in sorted(totals.items())])
    fig = px.bar(g, x="year", y="amount", text_auto=",.0f",
                 color_discrete_sequence=[BLUE], title="Dividend Income per Year (LKR)")
    return _style(fig)


def dividends_donut(rows):
    totals = {}
    for row in rows:
        symbol = row.get("symbol")
        amount = to_decimal(row.get("amount_exact") or row.get("amount"), default=None)
        if symbol and amount is not None:
            totals[symbol] = totals.get(symbol, to_decimal("0")) + amount
    df = pd.DataFrame([{"symbol": symbol, "amount": float(amount)}
                       for symbol, amount in sorted(totals.items())])
    fig = px.pie(df, names="symbol", values="amount", hole=0.6,
                 color_discrete_sequence=PALETTE, title="Dividends by Stock")
    return _style(fig)


def portfolio_allocation(items):
    """Donut chart for portfolio value distribution."""
    df = pd.DataFrame(items)
    fig = px.pie(df, names="symbol", values="current_value", hole=0.6,
                 color_discrete_sequence=PALETTE, title="Portfolio Allocation")
    return _style(fig)


def index_gauge(name, val, change, pct, high, low):
    """Card-sized mini gauge or delta visual for ASPI / S&P."""
    color = GREEN if change >= 0 else RED
    fig = go.Figure(go.Indicator(
        mode="number+delta",
        value=val,
        delta=dict(reference=val - change, valueformat=".2f", relative=False, increasing=dict(color=GREEN), decreasing=dict(color=RED)),
        title=dict(text=f"<b>{name}</b><br><span style='font-size:12px;color:#94a3b8'>Day Range: {low:,.1f} - {high:,.1f}</span>", font=dict(size=18, color="#e2e8f0")),
        number=dict(valueformat=",.2f", font=dict(size=30, color=color)),
    ))
    _style(fig, 190)
    fig.update_layout(margin=dict(l=15, r=15, t=65, b=25))
    return fig



# ====================================================================== PIE CHARTS
# Every block of numbers in the app gets a pie next to it. Labels carry the NUMBER too,
# so you see both the figure and the share.
A_COLOR, B_COLOR, OTHER = BLUE, AMBER, "#475569"


def _fmt_big(v):
    v = float(v)
    for lim, suf in ((1e9, " Bn"), (1e6, " Mn"), (1e3, " K")):
        if abs(v) >= lim:
            return f"{v / lim:,.2f}{suf}"
    return f"{v:,.2f}"


def _pie(title, labels, values, colors=None, hole=0.55, height=340, sub=None):
    """Generic pie/donut. Returns None if there is nothing to draw (all values <= 0)."""
    base = colors or PALETTE
    trip = [(l, float(v), base[i % len(base)]) for i, (l, v) in enumerate(zip(labels, values))
            if v is not None and float(v) > 0]
    if not trip:
        return None
    labs, vals, cols = zip(*trip)
    fig = go.Figure(go.Pie(
        labels=list(labs), values=list(vals), hole=hole, sort=False,
        marker=dict(colors=list(cols), line=dict(color="#07090f", width=2)),
        textinfo="percent", textposition="inside", insidetextorientation="horizontal",
        hovertemplate="%{label}<br>%{percent}<extra></extra>",
        pull=[0.03] * len(labs),
    ))
    fig.update_layout(title=title)
    if sub:
        fig.add_annotation(text=sub, x=0.5, y=0.5, showarrow=False, font=dict(size=13, color="#94a3b8"))
    return _style(fig, height)


def market_breadth_pie(up, down, flat):
    """Advancers vs decliners vs unchanged (how many stocks went up / down today)."""
    return _pie("Market Breadth (stocks traded today)",
                [f"Gainers · {up}", f"Losers · {down}", f"Unchanged · {flat}"], [up, down, flat],
                colors=[GREEN, RED, OTHER], sub=f"{up + down + flat}<br>stocks")


def turnover_share_pie(movers, top=8):
    """Which stocks make up today's trading: top N by turnover + 'Others'."""
    rows = sorted(movers, key=lambda r: r["turnover"], reverse=True)
    head, rest = rows[:top], rows[top:]
    labels = [f"{r['symbol'].split('.')[0]} · {_fmt_big(r['turnover'])}" for r in head]
    values = [r["turnover"] for r in head]
    if rest:
        other = sum(r["turnover"] for r in rest)
        labels.append(f"Others · {_fmt_big(other)}")
        values.append(other)
    return _pie(f"Turnover Share · top {top} (LKR)", labels, values,
                colors=[PALETTE[i % len(PALETTE)] for i in range(len(head))] + [OTHER])


def company_vs_market_pie(symbol, company_turnover, market_turnover):
    """One company's slice of the whole market's turnover."""
    rest = max(market_turnover - company_turnover, 0)
    short = symbol.split(".")[0]
    return _pie("Share of Today's Market Turnover",
                [f"{short} · {_fmt_big(company_turnover)}", f"Rest of market · {_fmt_big(rest)}"],
                [company_turnover, rest], colors=[A_COLOR, OTHER])


def compare_pie(title, name_a, val_a, name_b, val_b, unit=""):
    """TWO companies, one pie: the circle is split between them. Numbers are in the labels."""
    return _pie(title,
                [f"{name_a} · {_fmt_big(val_a)}{unit}", f"{name_b} · {_fmt_big(val_b)}{unit}"],
                [max(val_a, 0), max(val_b, 0)], colors=[A_COLOR, B_COLOR], height=320)


def share_pie(title, names, values, unit=""):
    """Same idea for 3+ companies."""
    return _pie(title, [f"{n} · {_fmt_big(v)}{unit}" for n, v in zip(names, values)],
                [max(v, 0) for v in values], height=320)


def portfolio_cost_pie(items):
    """Where your MONEY went (cost basis) - pair it with the value allocation pie."""
    return _pie("Invested Capital (cost)",
                [f"{i['symbol'].split('.')[0]} · {_fmt_big(i['invested'])}" for i in items],
                [i["invested"] for i in items])


def portfolio_value_pie(items):
    return _pie("Current Value (live)",
                [f"{i['symbol'].split('.')[0]} · {_fmt_big(i['current_value'])}" for i in items],
                [i["current_value"] for i in items])


def pnl_split_pie(total_invested, total_pnl):
    """Invested money vs gain (or loss): is the portfolio earning or bleeding."""
    if total_pnl >= 0:
        return _pie("Invested vs Profit", [f"Invested · {_fmt_big(total_invested)}", f"Profit · {_fmt_big(total_pnl)}"],
                    [total_invested, total_pnl], colors=[OTHER, GREEN])
    kept = max(total_invested + total_pnl, 0)
    return _pie("Remaining vs Loss", [f"Remaining · {_fmt_big(kept)}", f"Loss · {_fmt_big(-total_pnl)}"],
                [kept, -total_pnl], colors=[OTHER, RED])


def balance_pie(d):
    """Assets split into what is owed (liabilities) and what the owners hold (equity)."""
    return _pie("Assets: Liabilities vs Equity (LKR Mn)",
                [f"Liabilities · {_fmt_big(d['liabilities'])}", f"Equity · {_fmt_big(d['equity'])}"],
                [d["liabilities"], d["equity"]], colors=[RED, GREEN])
