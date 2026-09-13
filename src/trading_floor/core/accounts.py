"""The broker: a trader's cash, holdings, transaction history and strategy.

This is the only place money moves, and it is deliberately plain Python with no
LLM anywhere near it. The agent asks for a trade through an MCP tool; this class
decides whether the trade is legal. An agent cannot spend cash it does not have
or sell shares it does not hold, because the rule lives here rather than in a
prompt — a prompt is a request, and this is the thing that says no.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from trading_floor.config import INITIAL_BALANCE, SPREAD
from trading_floor.core.database import read_account, write_account, write_log
from trading_floor.core.market import get_share_price


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Transaction(BaseModel):
    """One executed trade. Quantity is negative for a sale.

    ``rationale`` is required, so the agent has to state why it is trading. It
    costs nothing at execution time and turns the transaction log into a readable
    account of the agent's reasoning after the fact.
    """

    symbol: str
    quantity: int
    price: float
    timestamp: str
    rationale: str

    def total(self) -> float:
        """Signed cash effect: positive when buying, negative when selling."""
        return self.quantity * self.price

    def __repr__(self) -> str:
        side = "BUY" if self.quantity > 0 else "SELL"
        return f"{side} {abs(self.quantity)} {self.symbol} @ {self.price:.2f}"


class Account(BaseModel):
    """A trader's whole state, persisted as JSON under their name."""

    name: str
    balance: float
    strategy: str
    holdings: dict[str, int]
    transactions: list[Transaction]
    portfolio_value_time_series: list[tuple[str, float]]

    # ------------------------------------------------------------- persistence

    @classmethod
    def get(cls, name: str) -> "Account":
        """Load a trader's account, creating a funded empty one on first use."""
        fields = read_account(name.lower())
        if not fields:
            fields = {
                "name": name.lower(),
                "balance": INITIAL_BALANCE,
                "strategy": "",
                "holdings": {},
                "transactions": [],
                "portfolio_value_time_series": [],
            }
            write_account(name, fields)
        return cls(**fields)

    def save(self) -> None:
        write_account(self.name.lower(), self.model_dump())

    def reset(self, strategy: str = "") -> None:
        """Wipe the account back to its opening balance and install a strategy."""
        self.balance = INITIAL_BALANCE
        self.strategy = strategy
        self.holdings = {}
        self.transactions = []
        self.portfolio_value_time_series = []
        self.save()

    # ------------------------------------------------------------------- cash

    def deposit(self, amount: float) -> None:
        if amount <= 0:
            raise ValueError("Deposit amount must be positive.")
        self.balance += amount
        self.save()

    def withdraw(self, amount: float) -> None:
        if amount > self.balance:
            raise ValueError("Insufficient funds for withdrawal.")
        self.balance -= amount
        self.save()

    # ----------------------------------------------------------------- trading

    def buy_shares(self, symbol: str, quantity: int, rationale: str) -> str:
        """Buy shares if the cash is there. Raises ValueError if it is not.

        The exception is the point: it travels back to the agent as a tool error,
        and the agent reads it and sizes the next attempt down. Refusing badly is
        how the broker teaches the agent its own limits.
        """
        if quantity <= 0:
            raise ValueError("Quantity to buy must be positive.")
        price = get_share_price(symbol)
        if price == 0:
            raise ValueError(f"Unrecognized symbol {symbol}")

        buy_price = price * (1 + SPREAD)
        total_cost = buy_price * quantity
        if total_cost > self.balance:
            raise ValueError(
                f"Insufficient funds: {quantity} {symbol} costs {total_cost:,.2f} "
                f"but the balance is {self.balance:,.2f}."
            )

        self.holdings[symbol] = self.holdings.get(symbol, 0) + quantity
        self.balance -= total_cost
        self.transactions.append(
            Transaction(
                symbol=symbol, quantity=quantity, price=buy_price, timestamp=_now(), rationale=rationale
            )
        )
        self.save()
        write_log(self.name, "account", f"Bought {quantity} of {symbol}")
        return "Completed. Latest details:\n" + self.report()

    def sell_shares(self, symbol: str, quantity: int, rationale: str) -> str:
        """Sell shares the trader actually holds. Raises ValueError otherwise."""
        if quantity <= 0:
            raise ValueError("Quantity to sell must be positive.")
        held = self.holdings.get(symbol, 0)
        if held < quantity:
            raise ValueError(f"Cannot sell {quantity} shares of {symbol}; only {held} held.")

        sell_price = get_share_price(symbol) * (1 - SPREAD)
        self.holdings[symbol] -= quantity
        if self.holdings[symbol] == 0:
            del self.holdings[symbol]
        self.balance += sell_price * quantity
        self.transactions.append(
            Transaction(
                symbol=symbol, quantity=-quantity, price=sell_price, timestamp=_now(), rationale=rationale
            )
        )
        self.save()
        write_log(self.name, "account", f"Sold {quantity} of {symbol}")
        return "Completed. Latest details:\n" + self.report()

    # --------------------------------------------------------------- valuation

    def calculate_portfolio_value(self) -> float:
        """Cash plus the market value of every holding, priced right now."""
        return self.balance + sum(
            get_share_price(symbol) * quantity for symbol, quantity in self.holdings.items()
        )

    def calculate_profit_loss(self, portfolio_value: float | None = None) -> float:
        """Profit or loss from trading alone.

        Measured as (value of what is held) minus (net cash spent acquiring it),
        rather than against the opening balance, so a deposit or withdrawal does
        not read as a gain or a loss.
        """
        if portfolio_value is None:
            portfolio_value = self.calculate_portfolio_value()
        net_spend = sum(transaction.total() for transaction in self.transactions)
        return portfolio_value - net_spend - self.balance

    def get_holdings(self) -> dict[str, int]:
        return self.holdings

    def get_profit_loss(self) -> float:
        """Current trading profit or loss."""
        return self.calculate_profit_loss()

    def list_transactions(self) -> list[dict[str, Any]]:
        return [transaction.model_dump() for transaction in self.transactions]

    def report(self) -> str:
        """The account as JSON, with a fresh valuation appended to the time series.

        This is what the agent reads at the start of every run and after every
        trade, and what the MCP resource serves. Taking the snapshot here means
        the equity curve is sampled exactly when the agent looks at itself.
        """
        portfolio_value = self.calculate_portfolio_value()
        self.portfolio_value_time_series.append((_now(), portfolio_value))
        self.save()
        data = self.model_dump()
        data["total_portfolio_value"] = portfolio_value
        data["total_profit_loss"] = self.calculate_profit_loss(portfolio_value)
        write_log(self.name, "account", "Retrieved account details")
        return json.dumps(data)

    # ---------------------------------------------------------------- strategy

    def get_strategy(self) -> str:
        write_log(self.name, "account", "Retrieved strategy")
        return self.strategy

    def change_strategy(self, strategy: str) -> str:
        """Replace this trader's strategy. Called by the agent, about itself.

        This is the mechanism behind the floor's self-improvement: the trader
        reviews how its own past trades performed and rewrites the instructions
        it will be given on every future run.
        """
        self.strategy = strategy
        self.save()
        write_log(self.name, "account", "Changed strategy")
        return "Changed strategy"
