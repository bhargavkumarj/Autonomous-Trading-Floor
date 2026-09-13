"""MCP server exposing a single price-lookup tool.

Deliberately tiny. It exists so the trader has a market-data tool even with no
market data vendor configured: without a Massive key this serves simulated
prices, and with one the agent is handed Massive's own richer MCP server instead
(see ``trading_floor.agents.mcp_registry``). Either way the agent's instructions
and the rest of the system are unchanged — swapping the data source is a
deployment decision, not a code change.

    python -m trading_floor.mcp_servers.market_server
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from trading_floor.core.market import get_share_price

mcp = FastMCP("market_server")


@mcp.tool()
async def lookup_share_price(symbol: str) -> float:
    """This tool provides the current price of the given stock symbol.

    Args:
        symbol: the symbol of the stock
    """
    return get_share_price(symbol)


if __name__ == "__main__":
    mcp.run(transport="stdio")
