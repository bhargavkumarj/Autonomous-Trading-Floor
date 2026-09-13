"""Tests for the broker.

These are the tests that matter most in the whole project: this is the layer that
tells an LLM "no". If the guards here are wrong, a hallucinating agent can spend
money it does not have, and no amount of prompt engineering upstream will catch
it. None of these tests call a model or hit a network — the broker is
deliberately plain Python, and that is exactly what makes it testable.
"""

from __future__ import annotations

import json

import pytest

from trading_floor.config import INITIAL_BALANCE, SPREAD
from trading_floor.core.accounts import Account, Transaction
from trading_floor.core.market import get_share_price


def test_new_account_starts_funded_and_empty(account: Account) -> None:
    assert account.balance == INITIAL_BALANCE
    assert account.holdings == {}
    assert account.transactions == []


def test_account_state_survives_a_reload(account: Account) -> None:
    account.buy_shares("AAPL", 2, "testing persistence")
    reloaded = Account.get("tester")
    assert reloaded.holdings == {"AAPL": 2}
    assert reloaded.balance == pytest.approx(account.balance)


def test_buying_deducts_cash_and_adds_holdings(account: Account) -> None:
    price = get_share_price("AAPL")
    account.buy_shares("AAPL", 3, "a reasonable position")
    assert account.holdings["AAPL"] == 3
    assert account.balance == pytest.approx(INITIAL_BALANCE - price * (1 + SPREAD) * 3)


def test_buying_more_than_the_balance_is_refused(account: Account) -> None:
    price = get_share_price("AAPL")
    unaffordable = int(INITIAL_BALANCE / price) + 100
    with pytest.raises(ValueError, match="Insufficient funds"):
        account.buy_shares("AAPL", unaffordable, "over-leveraged")
    assert account.balance == INITIAL_BALANCE
    assert account.holdings == {}


def test_selling_shares_not_held_is_refused(account: Account) -> None:
    with pytest.raises(ValueError, match="Cannot sell"):
        account.sell_shares("TSLA", 1, "naked short")


def test_selling_more_than_held_is_refused(account: Account) -> None:
    account.buy_shares("TSLA", 2, "small position")
    with pytest.raises(ValueError, match="Cannot sell"):
        account.sell_shares("TSLA", 3, "too many")
    assert account.holdings["TSLA"] == 2


def test_non_positive_quantities_are_refused(account: Account) -> None:
    """A negative buy would otherwise be a sale that skips the holdings check."""
    with pytest.raises(ValueError):
        account.buy_shares("AAPL", 0, "nothing")
    with pytest.raises(ValueError):
        account.buy_shares("AAPL", -5, "inverted")
    with pytest.raises(ValueError):
        account.sell_shares("AAPL", -5, "inverted")


def test_selling_the_whole_position_removes_the_symbol(account: Account) -> None:
    account.buy_shares("GOOGL", 4, "in")
    account.sell_shares("GOOGL", 4, "out")
    assert "GOOGL" not in account.holdings


def test_the_spread_makes_an_instant_round_trip_lose_money(account: Account) -> None:
    account.buy_shares("AAPL", 5, "in")
    account.sell_shares("AAPL", 5, "straight back out")
    assert account.balance < INITIAL_BALANCE
    assert account.calculate_profit_loss() < 0


def test_withdrawing_more_than_the_balance_is_refused(account: Account) -> None:
    with pytest.raises(ValueError, match="Insufficient funds"):
        account.withdraw(INITIAL_BALANCE + 1)


def test_profit_and_loss_ignores_deposits(account: Account) -> None:
    """A deposit is not a gain: P&L measures trading, not funding."""
    account.buy_shares("AAPL", 2, "position")
    before = account.calculate_profit_loss()
    account.deposit(5_000)
    assert account.calculate_profit_loss() == pytest.approx(before)


def test_get_profit_loss_needs_no_argument(account: Account) -> None:
    """Regression: the original course code raised TypeError here."""
    account.buy_shares("AAPL", 1, "position")
    assert account.get_profit_loss() == pytest.approx(account.calculate_profit_loss())


def test_report_is_json_and_extends_the_equity_curve(account: Account) -> None:
    before = len(account.portfolio_value_time_series)
    data = json.loads(account.report())
    assert data["name"] == "tester"
    assert "total_portfolio_value" in data
    assert "total_profit_loss" in data
    assert len(account.portfolio_value_time_series) == before + 1


def test_an_agent_can_rewrite_its_own_strategy(account: Account) -> None:
    account.change_strategy("Only buy index funds.")
    assert Account.get("tester").get_strategy() == "Only buy index funds."


def test_every_trade_records_a_rationale(account: Account) -> None:
    account.buy_shares("AAPL", 1, "because the fundamentals are strong")
    assert account.transactions[0].rationale == "because the fundamentals are strong"


def test_transaction_total_is_signed_by_side() -> None:
    buy = Transaction(symbol="X", quantity=10, price=5.0, timestamp="t", rationale="r")
    sell = Transaction(symbol="X", quantity=-10, price=5.0, timestamp="t", rationale="r")
    assert buy.total() == 50.0
    assert sell.total() == -50.0
