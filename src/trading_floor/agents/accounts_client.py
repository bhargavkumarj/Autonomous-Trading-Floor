"""An MCP *client*, as opposed to the servers in ``trading_floor.mcp_servers``.

Everywhere else in this project the agent runtime is the MCP client and we only
write servers. This module is the other half of the protocol: our own code opens
a session to our own accounts server and reads its resources directly.

Why go through MCP at all, when ``Account.get(name).report()`` is right there? To
prime the agent's context. A trader should start its run already knowing its
position and its strategy, rather than spending two tool-calling turns
discovering them. Fetching that through the same resource URIs the agent would
have used keeps one definition of "what an account looks like" — and it is the
piece that makes this a genuine MCP client implementation rather than a server
exercise.
"""

from __future__ import annotations

import sys

import mcp
from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client

from trading_floor.config import PROJECT_ROOT

SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,
    args=["-m", "trading_floor.mcp_servers.accounts_server"],
    cwd=str(PROJECT_ROOT),
    env=None,
)


async def _read_resource(uri: str) -> str:
    """Open a session to the accounts server, read one resource, close it."""
    async with stdio_client(SERVER_PARAMS) as streams:
        async with mcp.ClientSession(*streams) as session:
            await session.initialize()
            result = await session.read_resource(uri)
            return result.contents[0].text


async def read_accounts_resource(name: str) -> str:
    """The trader's full account state, as JSON."""
    return await _read_resource(f"accounts://accounts_server/{name}")


async def read_strategy_resource(name: str) -> str:
    """The trader's current strategy, in their own words."""
    return await _read_resource(f"accounts://strategy/{name}")
