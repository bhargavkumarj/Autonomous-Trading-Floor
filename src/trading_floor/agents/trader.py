"""A trader: one autonomous agent with an account, a strategy and a research team.

The composition is the interesting part. A trader is an ``Agent`` whose tools are
three MCP servers *plus another whole agent* — the researcher, exposed via
``as_tool``. That is the agent-as-tool pattern rather than a handoff: control
never leaves the trader, the researcher's web searching and knowledge-graph
traffic stay out of the trader's context window, and the trader gets back a
summary it can act on. A handoff would have transferred the conversation to the
researcher, which is exactly wrong here — the researcher must not be able to
trade.

Lifecycle of one run:

    read strategy + account (via MCP resources)  ->  build the agent and open its
    six MCP servers  ->  run to completion or the turn cap  ->  close everything
    ->  flip to the other mode for next time

The servers are opened per run and closed with an ``AsyncExitStack``, so a crash
mid-run cannot leave six orphaned subprocesses behind.
"""

from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack

from agents import Agent, Runner, Tool, trace

from trading_floor.agents.accounts_client import read_accounts_resource, read_strategy_resource
from trading_floor.agents.mcp_registry import researcher_mcp_servers, trader_mcp_servers
from trading_floor.agents.models import get_model
from trading_floor.agents.prompts import (
    rebalance_message,
    research_tool_description,
    researcher_instructions,
    trade_message,
    trader_instructions,
)
from trading_floor.config import DEFAULT_MODEL, MAX_TURNS
from trading_floor.observability.tracing import make_trace_id

logger = logging.getLogger(__name__)


def build_researcher(mcp_servers: list, model_name: str) -> Agent:
    """The research sub-agent: web search, page fetch and its own knowledge graph."""
    return Agent(
        name="Researcher",
        instructions=researcher_instructions(),
        model=get_model(model_name),
        mcp_servers=mcp_servers,
    )


def build_researcher_tool(mcp_servers: list, model_name: str) -> Tool:
    """The researcher, wrapped as a single tool the trader can call."""
    return build_researcher(mcp_servers, model_name).as_tool(
        tool_name="Researcher", tool_description=research_tool_description()
    )


class Trader:
    """One named trader. Call ``run()`` once per scheduled cycle."""

    def __init__(self, name: str, lastname: str = "Trader", model_name: str = DEFAULT_MODEL) -> None:
        self.name = name
        self.lastname = lastname
        self.model_name = model_name
        self.agent: Agent | None = None
        #: Alternates: hunt for new positions, then rebalance the existing ones.
        self.do_trade = True

    # ------------------------------------------------------------------ agent

    def create_agent(self, trader_servers: list, researcher_servers: list) -> Agent:
        self.agent = Agent(
            name=self.name,
            instructions=trader_instructions(self.name),
            model=get_model(self.model_name),
            tools=[build_researcher_tool(researcher_servers, self.model_name)],
            mcp_servers=trader_servers,
        )
        return self.agent

    async def get_account_report(self) -> str:
        """The account as JSON, minus the equity curve.

        The time series grows without bound and is worth nothing to the model —
        it is a chart for humans. Dropping it before it reaches the prompt keeps
        the opening context small on run 500 as well as run 1.
        """
        account = json.loads(await read_accounts_resource(self.name))
        account.pop("portfolio_value_time_series", None)
        return json.dumps(account)

    # -------------------------------------------------------------- execution

    async def run_agent(self, trader_servers: list, researcher_servers: list) -> None:
        """Build the agent and run one cycle to completion."""
        self.create_agent(trader_servers, researcher_servers)
        strategy = await read_strategy_resource(self.name)
        account = await self.get_account_report()
        message = (
            trade_message(self.name, strategy, account)
            if self.do_trade
            else rebalance_message(self.name, strategy, account)
        )
        await Runner.run(self.agent, message, max_turns=MAX_TURNS)

    async def run_with_mcp_servers(self) -> None:
        """Open all six MCP servers for the duration of one run, then close them."""
        async with AsyncExitStack() as stack:
            trader_servers = [await stack.enter_async_context(s) for s in trader_mcp_servers()]
            researcher_servers = [
                await stack.enter_async_context(s) for s in researcher_mcp_servers(self.name)
            ]
            await self.run_agent(trader_servers, researcher_servers)

    async def run_with_trace(self) -> None:
        """Wrap the run in a trace whose id encodes the trader's name.

        The name is smuggled into the trace id because the SDK's tracing hooks
        receive a span, not a trader. Encoding it in the id is what lets the log
        processor attribute every span to the right dashboard panel while four
        traders run concurrently. See ``observability.tracing``.
        """
        trace_name = f"{self.name}-trading" if self.do_trade else f"{self.name}-rebalancing"
        with trace(trace_name, trace_id=make_trace_id(self.name.lower())):
            await self.run_with_mcp_servers()

    async def run(self) -> None:
        """One scheduled cycle. Never raises: one trader's bad day is not the floor's.

        Four traders run under a single ``asyncio.gather``; letting an exception
        escape would take down the other three and stop the scheduler. The error
        is logged, and the trader simply tries again next cycle.
        """
        try:
            await self.run_with_trace()
        except Exception as error:
            logger.exception("Trader %s failed this cycle: %s", self.name, error)
        finally:
            self.do_trade = not self.do_trade
