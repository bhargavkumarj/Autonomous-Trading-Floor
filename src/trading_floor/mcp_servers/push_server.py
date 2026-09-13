"""MCP server that sends a push notification to the operator's phone.

The floor runs unattended, so this is how it reaches a human: each trader ends
its run by summarising what it did and pushing it. With no Pushover credentials
configured the tool degrades to logging rather than failing, because a missing
notification channel is not a reason to fail a completed trade.

    python -m trading_floor.mcp_servers.push_server
"""

from __future__ import annotations

import logging

import requests
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from trading_floor.config import PUSHOVER_TOKEN, PUSHOVER_USER, push_configured

logger = logging.getLogger(__name__)

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"
TIMEOUT_SECONDS = 10

mcp = FastMCP("push_server")


class PushArgs(BaseModel):
    message: str = Field(description="A brief message to push")


@mcp.tool()
def push(args: PushArgs) -> str:
    """Send a push notification with this brief message"""
    if not push_configured():
        logger.info("Push (not configured, logged only): %s", args.message)
        return "Push notification skipped: Pushover is not configured."
    try:
        response = requests.post(
            PUSHOVER_URL,
            data={"user": PUSHOVER_USER, "token": PUSHOVER_TOKEN, "message": args.message},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        # Reported back to the agent rather than raised: the trades already
        # happened, and a failed notification must not fail the run.
        logger.warning("Push notification failed: %s", error)
        return f"Push notification failed: {error}"
    return "Push notification sent"


if __name__ == "__main__":
    mcp.run(transport="stdio")
