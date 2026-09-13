"""The three MCP servers this project exposes to its agents.

Each runs as its own OS process over stdio and is launched by the agent runtime,
not by us. Run one directly to inspect it:

    python -m trading_floor.mcp_servers.accounts_server
"""
