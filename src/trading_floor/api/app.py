"""Read-only HTTP API over the trading floor.

The Gradio dashboard reads the database in-process; this serves the same data as
JSON so a decoupled frontend can render it without importing any Python. Strictly
read-only by design — the trading floor is the only writer, and the API is a
window onto it, not a second way in. That also means it can be exposed without
worrying that a stray request moves money.

    uvicorn trading_floor.api.app:app --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from trading_floor.config import using_live_market_data
from trading_floor.core import market
from trading_floor.core.accounts import Account
from trading_floor.core.database import read_log
from trading_floor.floor import LASTNAMES, NAMES, SHORT_MODEL_NAMES

#: Log line colours, mirroring the Gradio dashboard so both frontends look alike.
LOG_COLORS = {
    "trace": "#87CEEB",
    "agent": "#00dddd",
    "function": "#00dd00",
    "generation": "#dddd00",
    "response": "#aa00dd",
    "account": "#dd0000",
}
DEFAULT_LOG_COLOR = "#87CEEB"

ROSTER = [
    {"name": name, "lastname": lastname, "model_name": model_name}
    for name, lastname, model_name in zip(NAMES, LASTNAMES, SHORT_MODEL_NAMES)
]
ROSTER_BY_NAME = {trader["name"].lower(): trader for trader in ROSTER}

app = FastAPI(title="Trading Floor", version="1.0.0")


def average_cost(account: Account, symbol: str) -> float:
    """Mean price paid across this symbol's buys, for per-holding unrealised profit."""
    buys = [t for t in account.transactions if t.symbol == symbol and t.quantity > 0]
    bought = sum(t.quantity for t in buys)
    return sum(t.price * t.quantity for t in buys) / bought if bought else 0.0


def holdings_detail(account: Account) -> list[dict]:
    """Holdings enriched with live price, market value and unrealised profit."""
    details = []
    for symbol, quantity in account.holdings.items():
        price = market.get_share_price(symbol)
        cost = average_cost(account, symbol)
        details.append(
            {
                "symbol": symbol,
                "quantity": quantity,
                "price": price,
                "avg_cost": cost,
                "market_value": price * quantity,
                "unrealized_pnl": (price - cost) * quantity,
            }
        )
    return details


def require_trader(name: str) -> dict:
    trader = ROSTER_BY_NAME.get(name.lower())
    if not trader:
        raise HTTPException(status_code=404, detail=f"Unknown trader {name}")
    return trader


@app.get("/api/traders")
def get_traders() -> list[dict]:
    """The traders on the floor."""
    return ROSTER


@app.get("/api/market")
def get_market() -> dict:
    """Which price source is live, and whether the market is open."""
    return {
        "source": "massive" if using_live_market_data() else "simulator",
        "is_market_open": market.is_market_open(),
    }


@app.get("/api/traders/{name}")
def get_trader(name: str) -> dict:
    """One trader's full state: value, profit, holdings, transactions, equity curve."""
    trader = require_trader(name)
    account = Account.get(name)
    holdings = holdings_detail(account)
    portfolio_value = account.balance + sum(h["market_value"] for h in holdings)
    return {
        **trader,
        "balance": account.balance,
        "strategy": account.strategy,
        "portfolio_value": portfolio_value,
        "pnl": account.calculate_profit_loss(portfolio_value),
        "holdings": holdings,
        "transactions": account.list_transactions(),
        "time_series": [
            {"datetime": ts, "value": value} for ts, value in account.portfolio_value_time_series
        ],
    }


@app.get("/api/traders/{name}/logs")
def get_trader_logs(name: str, last_n: int = 13) -> list[dict]:
    """Recent agent activity for a trader, oldest first, with its panel colour."""
    require_trader(name)
    return [
        {"datetime": ts, "type": kind, "message": message, "color": LOG_COLORS.get(kind, DEFAULT_LOG_COLOR)}
        for ts, kind, message in read_log(name, last_n)
    ]
