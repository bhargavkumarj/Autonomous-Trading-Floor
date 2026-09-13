# Autonomous Trading Floor

Four autonomous LLM agents run a simulated hedge fund. Each has its own
investment thesis, its own account, its own long-term memory, and the ability to
rewrite its own strategy based on how its trades actually performed. They
research the market over the web, place orders through a broker that can refuse
them, and report back to a human by push notification — continuously, on a
schedule, without supervision.

Every capability the agents have reaches them through the **Model Context
Protocol**. Three of the six MCP servers are written from scratch in this
repository; the other three come from the ecosystem, and the agents cannot tell
the difference.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  SCHEDULER  (trading_floor.floor)                                        │
│  every N minutes, if the market is open → asyncio.gather over 4 traders  │
└───────────────┬──────────────────────────────────────────────────────────┘
                │
     ┌──────────┴──────────┬──────────────┬──────────────┐
     ▼                     ▼              ▼              ▼
  Warren                George           Ray          Cathie        ← 4 Agents,
  (value)               (macro)      (risk parity)   (crypto)         4 theses
     │
     │  tools
     ├──────────────────────────────────────────► Researcher  ← an Agent
     │                                             exposed as a tool
     │  mcp_servers                                    │  mcp_servers
     ▼                                                 ▼
 ┌────────────┐ ┌────────────┐ ┌───────────┐   ┌────────┐ ┌────────┐ ┌────────┐
 │  accounts  │ │    push    │ │  market   │   │ fetch  │ │ tavily │ │ memory │
 │   server   │ │   server   │ │  server   │   │ (uvx)  │ │ (npx)  │ │ libSQL │
 │  ▲ OURS    │ │  ▲ OURS    │ │  ▲ OURS   │   │        │ │ search │ │  graph │
 │ 5 tools    │ │            │ │  or       │   └────────┘ └────────┘ └────────┘
 │ 2 resources│ │            │ │ Massive's │       └── third-party MCP servers ─┘
 └─────┬──────┘ └────────────┘ └───────────┘
       │
       ▼
 ┌──────────────────────────────┐        ┌────────────────────────────────┐
 │  SQLite: accounts + logs     │◄───────┤ SQLiteLogTracer                │
 │  (WAL, multi-process)        │        │ mirrors every agent span       │
 └──────┬───────────────┬───────┘        └────────────────────────────────┘
        │               │
        ▼               ▼
  Gradio dashboard   FastAPI  ──►  TypeScript + Vite frontend
```

---

## Why this project is interesting

**The broker is not an LLM.** `core/accounts.py` is plain, tested Python. When an
agent tries to buy 400 shares it cannot afford, a `ValueError` travels back
through the MCP tool call and the agent reads it and resizes. The rule that stops
it lives in code, not in a prompt — because a prompt is a request and code is a
constraint. This is the single most important design decision in the project.

**The agents genuinely learn.** Two mechanisms, deliberately different:

* a **libSQL knowledge graph** per researcher (an MCP server), where entities and
  relationships about companies and market conditions accumulate across runs;
* a **`change_strategy` tool** that lets each trader rewrite the instructions it
  will be given on every future run, after reviewing how its own past trades
  performed.

After a week of running, the strategy text in the database is the agent's, not
the one it started with.

**It is observable.** The OpenAI Agents SDK emits spans to its own dashboard,
which is useless for watching four agents at once. A custom `TracingProcessor`
mirrors every span into SQLite, attributed to the right trader, and the dashboard
tails it at 2 Hz — so you can watch an agent search the web, think, and place an
order, live.

**It degrades instead of breaking.** No market data key? A deterministic price
simulator takes over and the whole floor still runs. No Pushover credentials? The
push tool logs. Massive rate-limits the good endpoint? It falls back a tier and
remembers. You can clone this and run it end to end with one API key.

---

## Quick start

```bash
cp .env.example .env    # then put your OPENAI_API_KEY in it
```

```bash
uv sync && uv run trading-floor doctor
```

`doctor` tells you what is configured and what will silently degrade — worth
running first, because a misconfigured stdio MCP server fails *quietly* (the
child dies inside the transport and the agent just reports that a tool did not
work).

```bash
uv run trading-floor reset
```

Then run the floor and the dashboard in two terminals:

```bash
uv run trading-floor run
```

```bash
uv run trading-floor dashboard
```

To trade immediately rather than waiting for the market to open, set
`RUN_EVEN_WHEN_MARKET_IS_CLOSED=true` in `.env`.

### Requirements

* Python 3.12+
* Node.js 18+ — `npx` launches the Tavily and memory MCP servers
* `uv` — `uvx` launches the fetch MCP server
* An OpenAI API key. Everything else is optional.

---

## The other frontend

The Gradio dashboard reads the database in-process. A decoupled TypeScript SPA
reads the same data over a read-only JSON API instead:

```bash
uv run trading-floor api --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

The API is read-only on purpose: the trading floor is the only writer, so no
request to this service can move money.

---

## Layout

```
src/trading_floor/
├── config.py              every environment-driven setting, read once
├── cli.py                 reset / run / dashboard / api / doctor
├── floor.py               the roster and the scheduler loop
├── strategies.py          the four opening theses; agents rewrite their own
├── core/                  the domain. no LLM code lives here.
│   ├── accounts.py          the broker — the layer that says no
│   ├── database.py          SQLite, WAL, multi-process
│   ├── market.py            Massive, with a simulator fallback
│   └── market_simulator.py  deterministic value-noise prices
├── mcp_servers/           OUR MCP servers — each its own OS process
│   ├── accounts_server.py   5 tools + 2 resources
│   ├── market_server.py     1 tool
│   └── push_server.py       1 tool
├── agents/                the agent layer
│   ├── trader.py            the Trader: agent + researcher-as-tool
│   ├── accounts_client.py   an MCP *client*, reading resources
│   ├── mcp_registry.py      which servers each agent gets, and how
│   ├── prompts.py           every prompt, out of the code
│   └── models.py            multi-provider model routing
├── observability/
│   └── tracing.py           spans → SQLite, attributed per trader
├── api/app.py             read-only FastAPI
└── ui/dashboard.py        the Gradio operator view
```

---

## Configuration

Everything is read once in `config.py`. The ones worth knowing:

| Variable | Default | Effect |
|---|---|---|
| `OPENAI_API_KEY` | — | **Required.** |
| `MASSIVE_API_KEY` | unset | Live prices, and Massive's own richer MCP server replaces ours |
| `TAVILY_API_KEY` | unset | Web search for the researcher |
| `PUSHOVER_USER` / `_TOKEN` | unset | Push notifications actually send |
| `USE_MANY_MODELS` | `false` | Each trader on a different frontier model — the floor becomes a model bake-off |
| `RUN_EVERY_N_MINUTES` | `60` | Scheduler cadence |
| `RUN_EVEN_WHEN_MARKET_IS_CLOSED` | `false` | Trade any time (useful for demos) |
| `MAX_TURNS` | `30` | Hard ceiling on tool-calling turns per trader run |
| `INITIAL_BALANCE` | `10000` | Opening cash |
| `SPREAD` | `0.002` | Half-spread charged against the agent on both sides |

---

## Tests

```bash
uv run --extra dev pytest
```

No model calls, no network. The suite covers the broker's refusal paths (the
part that must never be wrong), the determinism of the price simulator, and the
JSON contract the TypeScript frontend depends on.

---

## Cost and safety

The agents spend real API budget. A single cycle of four traders with research is
roughly a few cents on a mini model and materially more on a frontier one, and
the scheduler runs forever. `MAX_TURNS` caps a runaway agent, but the meaningful
control is the cadence: start at `RUN_EVERY_N_MINUTES=60` and watch a few cycles
before leaving it running.

No real money is at risk. The broker is a simulation, the trades are recorded in
SQLite, and nothing in the system can reach a real brokerage.

---
