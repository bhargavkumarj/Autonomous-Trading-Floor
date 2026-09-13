"""Tests for the read-only HTTP API.

Uses FastAPI's TestClient, so no server is started and no model is called. The
point of these is contract stability: the TypeScript frontend is a separate
codebase that cannot be type-checked against Python, so these tests are the only
thing standing between a field rename here and a blank dashboard there.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from trading_floor.api.app import app
from trading_floor.core.accounts import Account

client = TestClient(app)


def test_roster_lists_the_floor() -> None:
    traders = client.get("/api/traders").json()
    assert {t["name"] for t in traders} == {"Warren", "George", "Ray", "Cathie"}
    assert all({"name", "lastname", "model_name"} <= t.keys() for t in traders)


def test_market_reports_the_price_source() -> None:
    body = client.get("/api/market").json()
    assert body["source"] == "simulator"  # no MASSIVE_API_KEY in the test environment
    assert isinstance(body["is_market_open"], bool)


def test_unknown_trader_is_a_404() -> None:
    assert client.get("/api/traders/nobody").status_code == 404
    assert client.get("/api/traders/nobody/logs").status_code == 404


def test_trader_names_are_case_insensitive() -> None:
    assert client.get("/api/traders/warren").status_code == 200
    assert client.get("/api/traders/WARREN").status_code == 200


def test_trader_payload_has_the_shape_the_frontend_expects() -> None:
    body = client.get("/api/traders/Warren").json()
    assert {
        "name",
        "lastname",
        "model_name",
        "balance",
        "strategy",
        "portfolio_value",
        "pnl",
        "holdings",
        "transactions",
        "time_series",
    } <= body.keys()


def test_holdings_are_enriched_with_valuation() -> None:
    account = Account.get("Warren")
    account.reset("Test strategy.")
    account.buy_shares("AAPL", 3, "seeding the API test")

    holding = client.get("/api/traders/Warren").json()["holdings"][0]
    assert holding["symbol"] == "AAPL"
    assert holding["quantity"] == 3
    assert holding["market_value"] > 0
    # Bought this instant, so the spread is the entire loss so far.
    assert holding["unrealized_pnl"] < 0


def test_logs_carry_a_colour_for_every_line() -> None:
    Account.get("Warren").report()  # writes an "account" log line
    logs = client.get("/api/traders/Warren/logs").json()
    assert logs
    assert all(line["color"].startswith("#") for line in logs)
