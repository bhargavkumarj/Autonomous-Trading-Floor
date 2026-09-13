"""The agent layer: traders, their researcher sub-agent, and their MCP wiring.

Note on naming: this package is ``trading_floor.agents``, while the OpenAI Agents
SDK is the top-level package ``agents``. Python 3 has no implicit relative
imports, so ``from agents import Agent`` inside these modules resolves to the SDK,
not to this package. The name is kept because it is the honest one for what lives
here.
"""
