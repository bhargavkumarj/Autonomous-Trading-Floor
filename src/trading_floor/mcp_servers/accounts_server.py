"""MCP server exposing the broker to any MCP-speaking agent.

Five tools that change state, and two *resources* that read it. The split
matters: a tool is a verb the model chooses to invoke and pays a turn for; a
resource is a named piece of context the client can fetch and put in front of the
model before it starts thinking. The trader's opening position and strategy come
in as resources, so the agent begins its run already knowing where it stands
instead of spending two turns asking.

Run standalone to inspect it:

    python -m trading_floor.mcp_servers.accounts_server

Or point the MCP Inspector at that command.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from trading_floor.core.accounts import Account

mcp = FastMCP("accounts_server")


@mcp.tool()
async def get_balance(name: str) -> float:
    """Get the cash balance of the given account name.

    Args:
        name: The name of the account holder
    """
    return Account.get(name).balance


@mcp.tool()
async def get_holdings(name: str) -> dict[str, int]:
    """Get the holdings of the given account name.

    Args:
        name: The name of the account holder
    """
    return Account.get(name).holdings


@mcp.tool()
async def buy_shares(name: str, symbol: str, quantity: int, rationale: str) -> str:
    """Buy shares of a stock.

    Args:
        name: The name of the account holder
        symbol: The symbol of the stock
        quantity: The quantity of shares to buy
        rationale: The rationale for the purchase and fit with the account's strategy
    """
    return Account.get(name).buy_shares(symbol, quantity, rationale)


@mcp.tool()
async def sell_shares(name: str, symbol: str, quantity: int, rationale: str) -> str:
    """Sell shares of a stock.

    Args:
        name: The name of the account holder
        symbol: The symbol of the stock
        quantity: The quantity of shares to sell
        rationale: The rationale for the sale and fit with the account's strategy
    """
    return Account.get(name).sell_shares(symbol, quantity, rationale)


@mcp.tool()
async def change_strategy(name: str, strategy: str) -> str:
    """At your discretion, if you choose to, call this to change your investment
    strategy for the future.

    Args:
        name: The name of the account holder
        strategy: The new strategy for the account
    """
    return Account.get(name).change_strategy(strategy)


@mcp.resource("accounts://accounts_server/{name}")
async def read_account_resource(name: str) -> str:
    """The full account state as JSON: cash, holdings, transactions, equity curve."""
    return Account.get(name.lower()).report()


@mcp.resource("accounts://strategy/{name}")
async def read_strategy_resource(name: str) -> str:
    """The trader's current investment strategy, in their own words."""
    return Account.get(name.lower()).get_strategy()


if __name__ == "__main__":
    mcp.run(transport="stdio")
