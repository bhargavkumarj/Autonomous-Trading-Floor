"""Which MCP servers each agent gets, and how they are launched.

Six servers in total: three written in this repository and three from the wider
ecosystem, all speaking the same protocol so the agent cannot tell them apart.

  trader     -> accounts (ours), push (ours), market data (ours or Massive's)
  researcher -> fetch, Tavily search, libSQL knowledge graph

Two details worth noticing:

*Launching with ``sys.executable``.* Our own servers are started with the exact
interpreter running this process rather than a bare ``uv run``, so a child server
can never come up against a different virtualenv than the parent — the single
most annoying class of stdio-MCP bug to diagnose, since the child's import error
is swallowed by the transport.

*Tool filtering.* Tavily's MCP server offers search, crawl, extract and a
deep-research tool. Handing an agent all four invites it to reach for the
expensive one; a static filter narrows it to plain search. Tool surface is part
of the prompt, and trimming it is a design decision, not a limitation.
"""

from __future__ import annotations

import sys

from agents.mcp import MCPServerStdio, create_static_tool_filter

from trading_floor.config import (
    MASSIVE_API_KEY,
    MCP_TIMEOUT_SECONDS,
    MEMORY_DIR,
    PROJECT_ROOT,
    TAVILY_API_KEY,
)


#: A server of ours, run as a module by this very interpreter.
def _own_server(module: str) -> dict:
    return {
        "command": sys.executable,
        "args": ["-m", f"trading_floor.mcp_servers.{module}"],
        "cwd": str(PROJECT_ROOT),
    }


def _market_params() -> dict:
    """Massive's own market data server when a key is set, otherwise ours.

    Massive's server exposes trends, technical indicators and fundamentals, so
    the agent gets a far richer toolset for free the moment a key appears. The
    prompt adapts to which one is live (see ``prompts.market_data_note``).
    """
    if MASSIVE_API_KEY:
        return {
            "command": "uvx",
            "args": ["--from", "git+https://github.com/massive-com/mcp_massive@v0.10.0", "mcp_massive"],
            "env": {"MASSIVE_API_KEY": MASSIVE_API_KEY},
        }
    return _own_server("market_server")


def trader_mcp_servers() -> list[MCPServerStdio]:
    """The trader's servers: accounts, push notifications and market data."""
    params = [_own_server("accounts_server"), _own_server("push_server"), _market_params()]
    return [MCPServerStdio(p, client_session_timeout_seconds=MCP_TIMEOUT_SECONDS) for p in params]


def researcher_mcp_servers(name: str) -> list[MCPServerStdio]:
    """The researcher's servers: page fetch, web search and a per-trader memory.

    The memory is a libSQL knowledge graph stored in its own file per trader, so
    Warren's accumulated view of the market never leaks into Cathie's. This is
    the floor's long-term memory: it survives process restarts, which is what
    makes a scheduled agent capable of building expertise instead of waking up
    amnesiac every hour.
    """
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    fetch = MCPServerStdio(
        {"command": "uvx", "args": ["--with", "mcp<2", "mcp-server-fetch"]},
        client_session_timeout_seconds=MCP_TIMEOUT_SECONDS,
    )
    servers = [fetch]
    if TAVILY_API_KEY:
        search = MCPServerStdio(
            {"command": "npx", "args": ["-y", "tavily-mcp@latest"], "env": {"TAVILY_API_KEY": TAVILY_API_KEY}},
            client_session_timeout_seconds=MCP_TIMEOUT_SECONDS,
            tool_filter=create_static_tool_filter(allowed_tool_names=["tavily_search"]),
        )
        servers.append(search)
    memory = MCPServerStdio(
        {
            "command": "npx",
            "args": ["-y", "mcp-memory-libsql"],
            "env": {"LIBSQL_URL": f"file:{MEMORY_DIR / f'{name.lower()}.db'}"},
        },
        client_session_timeout_seconds=MCP_TIMEOUT_SECONDS,
    )
    servers.append(memory)
    return servers
