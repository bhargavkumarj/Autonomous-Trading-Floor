"""The floor itself: who trades, and the scheduler that keeps them trading.

Four traders, each an homage to a real investor and each given a genuinely
different thesis. That is not decoration — it is the experiment. Same tools, same
market, same broker; only the strategy prompt differs. Watching value investing
diverge from macro trading over a week is the thing this project actually
demonstrates, and it is why the equity curves are worth plotting side by side.

With ``USE_MANY_MODELS=true`` each trader also runs on a different frontier
model, and the floor becomes a head-to-head model comparison as well.
"""

from __future__ import annotations

import asyncio
import logging

from agents import add_trace_processor

from trading_floor.agents.trader import Trader
from trading_floor.config import (
    DEFAULT_MODEL,
    RUN_EVEN_WHEN_MARKET_IS_CLOSED,
    RUN_EVERY_N_MINUTES,
    USE_MANY_MODELS,
)
from trading_floor.core.market import is_market_open
from trading_floor.observability.tracing import SQLiteLogTracer

logger = logging.getLogger(__name__)

NAMES = ["Warren", "George", "Ray", "Cathie"]
LASTNAMES = ["Patience", "Bold", "Systematic", "Crypto"]

if USE_MANY_MODELS:
    MODEL_NAMES = ["gpt-5.5", "deepseek-v4-flash", "gemini-3.5-flash", "grok-4.3"]
    SHORT_MODEL_NAMES = ["GPT 5.5", "DeepSeek V4", "Gemini 3.5 Flash", "Grok 4.3"]
else:
    MODEL_NAMES = [DEFAULT_MODEL] * len(NAMES)
    SHORT_MODEL_NAMES = [DEFAULT_MODEL] * len(NAMES)


def create_traders() -> list[Trader]:
    """The four traders, freshly constructed. State lives in the database, not here."""
    return [
        Trader(name, lastname, model_name)
        for name, lastname, model_name in zip(NAMES, LASTNAMES, MODEL_NAMES)
    ]


async def run_one_cycle(traders: list[Trader]) -> None:
    """Run every trader once, concurrently.

    ``gather`` and not a loop: each trader spends most of its cycle waiting on a
    model or a web search, so four run in roughly the time of one. Each trader's
    ``run()`` swallows its own exceptions, so ``gather`` cannot be torn down by a
    single failure.
    """
    await asyncio.gather(*(trader.run() for trader in traders))


async def run_once() -> None:
    """Run a single scheduled cycle across all traders."""
    add_trace_processor(SQLiteLogTracer())
    traders = create_traders()
    logger.info("Trading floor single cycle starting: %d traders (%s)", len(traders), ", ".join(NAMES))
    if RUN_EVEN_WHEN_MARKET_IS_CLOSED or is_market_open():
        await run_one_cycle(traders)
    else:
        logger.info("Market is closed, skipping this cycle")
    logger.info("Trading floor single cycle completed.")


async def run_forever() -> None:
    """The scheduler loop: trade, sleep, repeat, until interrupted."""
    add_trace_processor(SQLiteLogTracer())
    traders = create_traders()
    logger.info("Trading floor starting: %d traders, every %d minutes", len(traders), RUN_EVERY_N_MINUTES)
    while True:
        if RUN_EVEN_WHEN_MARKET_IS_CLOSED or is_market_open():
            await run_one_cycle(traders)
        else:
            logger.info("Market is closed, skipping this cycle")
        await asyncio.sleep(RUN_EVERY_N_MINUTES * 60)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s")
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        logger.info("Trading floor stopped.")


if __name__ == "__main__":
    main()
