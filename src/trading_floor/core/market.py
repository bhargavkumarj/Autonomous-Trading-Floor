"""Share prices: live from the Massive market data API, or simulated.

The whole floor runs with no market data key at all — prices then come from
``market_simulator``, which is deterministic in (ticker, timestamp) so a run is
reproducible and prices still drift the way a real one does. Set
``MASSIVE_API_KEY`` and the same function returns real quotes instead.
"""

from __future__ import annotations

import logging
from typing import Callable

from massive import RESTClient

from trading_floor.config import MASSIVE_API_KEY
from trading_floor.core.market_simulator import simulated_price

logger = logging.getLogger(__name__)


def _last_trade(client: RESTClient, symbol: str) -> float:
    return float(client.get_last_trade(symbol).price)


def _snapshot(client: RESTClient, symbol: str) -> float:
    snapshot = client.get_snapshot_ticker("stocks", symbol)
    return float(snapshot.min.close or snapshot.prev_day.close)


def _previous_close(client: RESTClient, symbol: str) -> float:
    return float(client.get_previous_close_agg(symbol)[0].close)


#: Freshest price first, prior close last. Cheaper Massive plans reject the earlier
#: calls, so the first tier that works is remembered and tried first next time
#: rather than paying for two failures on every single lookup.
_PRICE_METHODS: list[Callable[[RESTClient, str], float]] = [_last_trade, _snapshot, _previous_close]
_plan_tier = 0


def get_share_price(symbol: str) -> float:
    """The current price for a symbol, from Massive if configured, else simulated."""
    if MASSIVE_API_KEY:
        try:
            return get_share_price_live(symbol)
        except Exception as error:  # any provider failure falls back rather than halting a trade
            logger.warning("Massive API unavailable (%s); using a simulated price", error)
    return simulated_price(symbol)


def get_share_price_live(symbol: str) -> float:
    """The best price this Massive plan allows, remembering the working tier."""
    global _plan_tier
    client = RESTClient(MASSIVE_API_KEY)
    for tier in range(_plan_tier, len(_PRICE_METHODS)):
        try:
            price = _PRICE_METHODS[tier](client, symbol)
            _plan_tier = tier
            return price
        except Exception:
            continue
    raise RuntimeError(f"No Massive price available for {symbol}")


def is_market_open() -> bool:
    """Whether the US market is open.

    True on simulated data (the simulator never closes) and true if Massive is
    unreachable, so a data outage pauses the floor rather than a network blip.
    """
    if not MASSIVE_API_KEY:
        return True
    try:
        return RESTClient(MASSIVE_API_KEY).get_market_status().market == "open"
    except Exception:
        return True
