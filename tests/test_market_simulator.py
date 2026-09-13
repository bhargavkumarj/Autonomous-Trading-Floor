"""Tests for the price simulator.

The simulator is what lets this project run with no market data vendor at all,
and its whole value rests on two properties: it is *deterministic* (the same
ticker at the same instant always gives the same price, so a run is reproducible
and the tests below are not flaky) and it *drifts* rather than jumping (so an
agent that reasons about a trend is reasoning about something real-shaped).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_floor.core.market_simulator import simulated_price

WHEN = datetime(2026, 3, 2, 15, 30, tzinfo=timezone.utc)


def test_price_is_deterministic_for_a_ticker_and_time() -> None:
    assert simulated_price("AAPL", WHEN) == simulated_price("AAPL", WHEN)


def test_different_tickers_get_different_prices() -> None:
    prices = {simulated_price(t, WHEN) for t in ("AAPL", "TSLA", "GOOGL", "NVDA", "MSFT")}
    assert len(prices) == 5


def test_ticker_case_does_not_matter() -> None:
    assert simulated_price("aapl", WHEN) == simulated_price("AAPL", WHEN)


def test_prices_are_positive_and_plausible() -> None:
    for ticker in ("AAPL", "TSLA", "GOOGL", "SPY", "BITO"):
        price = simulated_price(ticker, WHEN)
        assert 0 < price < 2000


def test_prices_drift_rather_than_jump() -> None:
    """Ten minutes apart should be a nudge, not a new price."""
    later = simulated_price("AAPL", WHEN + timedelta(minutes=10))
    now = simulated_price("AAPL", WHEN)
    assert later != now
    assert abs(later - now) / now < 0.05


def test_prices_actually_move_over_a_month() -> None:
    now = simulated_price("AAPL", WHEN)
    later = simulated_price("AAPL", WHEN + timedelta(days=30))
    assert later != pytest.approx(now)


def test_default_time_is_now() -> None:
    assert simulated_price("AAPL") > 0
