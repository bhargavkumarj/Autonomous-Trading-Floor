"""Every environment-driven setting in one place.

The original course code called ``load_dotenv(override=True)`` at the top of nine
different modules and read ``os.getenv`` wherever a value happened to be needed.
That works, but it means you cannot answer "what does this system need to run?"
without grepping. Here the environment is read exactly once, at import, and
exposed as typed module constants and small helpers.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

# --------------------------------------------------------------------------- paths

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent.parent

#: SQLite file holding accounts and the agent activity log. Absolute by default so
#: that the MCP servers, the scheduler, the API and the dashboard all agree on it
#: no matter which directory they were started from.
DB_PATH = Path(os.getenv("TRADING_FLOOR_DB", PROJECT_ROOT / "accounts.db")).resolve()

#: Where each researcher's libSQL knowledge-graph memory file lives.
MEMORY_DIR = Path(os.getenv("TRADING_FLOOR_MEMORY_DIR", PROJECT_ROOT / "memory")).resolve()

# ------------------------------------------------------------------------ api keys

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY")  # live market data; simulator used without it
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")  # researcher web search
PUSHOVER_USER = os.getenv("PUSHOVER_USER")
PUSHOVER_TOKEN = os.getenv("PUSHOVER_TOKEN")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GROK_API_KEY = os.getenv("GROK_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# ------------------------------------------------------------------- model routing

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
GROK_BASE_URL = "https://api.x.ai/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

#: The model every trader uses when USE_MANY_MODELS is off.
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-5.4-mini")

#: Run each trader on a different frontier model, so the floor doubles as a
#: head-to-head comparison. Requires the matching provider keys above.
USE_MANY_MODELS = os.getenv("USE_MANY_MODELS", "false").strip().lower() == "true"

# ----------------------------------------------------------------------- scheduling

RUN_EVERY_N_MINUTES = int(os.getenv("RUN_EVERY_N_MINUTES", "60"))
RUN_EVEN_WHEN_MARKET_IS_CLOSED = (
    os.getenv("RUN_EVEN_WHEN_MARKET_IS_CLOSED", "false").strip().lower() == "true"
)

# ------------------------------------------------------------------------- trading

INITIAL_BALANCE = float(os.getenv("INITIAL_BALANCE", "10000"))
#: Half-spread applied against the agent on both sides of a trade, so round-tripping
#: a position costs something and a strategy that churns is punished for it.
SPREAD = float(os.getenv("SPREAD", "0.002"))

#: Hard ceiling on tool-calling turns for one trader run. An agent that loops
#: without converging stops here rather than burning the budget.
MAX_TURNS = int(os.getenv("MAX_TURNS", "30"))

#: MCP stdio client timeout. Generous: a cold ``npx``/``uvx`` server download on a
#: first run genuinely can take a minute.
MCP_TIMEOUT_SECONDS = int(os.getenv("MCP_TIMEOUT_SECONDS", "120"))


def using_live_market_data() -> bool:
    """True when a Massive API key is present, so prices are real rather than simulated."""
    return bool(MASSIVE_API_KEY)


def push_configured() -> bool:
    """True when Pushover credentials are present and notifications will actually send."""
    return bool(PUSHOVER_USER and PUSHOVER_TOKEN)
