# Architecture

## 1. The shape of the system

This is a distributed system, not a script. At steady state a single cycle
involves **21 OS processes**: one scheduler, and for each of four traders, six
MCP servers spawned over stdio for the duration of that trader's run (four ×
five... in practice each trader opens three trader servers and three researcher
servers, so 4 × 6 = 24 children, opened and closed per cycle).

```
scheduler process
└── asyncio.gather
    ├── Warren  ─┬─ accounts_server   (subprocess, stdio)
    │            ├─ push_server       (subprocess, stdio)
    │            ├─ market_server     (subprocess, stdio)
    │            ├─ fetch             (uvx subprocess)
    │            ├─ tavily            (npx subprocess)
    │            └─ memory/warren.db  (npx subprocess)
    ├── George  ─── (same six, its own memory file)
    ├── Ray     ─── (same six, its own memory file)
    └── Cathie  ─── (same six, its own memory file)
```

Everything writes to one SQLite file. Two frontends read it. That is the whole
system.

### Why processes and not function calls

The obvious objection: `Account.get(name).buy_shares(...)` is a Python call away,
so why launch a subprocess and speak a protocol to reach it?

Because the boundary is the product. Once the broker is an MCP server:

* Claude Desktop, Cursor, or any other MCP client can drive it with zero changes;
* it can be swapped for a different implementation without touching the agent;
* third-party servers (Tavily, fetch, libSQL memory) plug into the same socket as
  ours, and the agent cannot tell which is which;
* a crash in a tool server does not take down the agent.

The cost is real — process startup on every run, and a whole class of failures
that manifest as silence.

---

## 2. Layers

```
  interfaces   cli · api/app.py · ui/dashboard.py · frontend/ (TS)
       │       read-only, replaceable, none of them owns state
  ─────┼──────────────────────────────────────────────────────────
  agents       trader.py · prompts.py · models.py · mcp_registry.py
       │       everything that talks to an LLM
  ─────┼──────────────────────────────────────────────────────────
  protocol     mcp_servers/*  ·  agents/accounts_client.py
       │       the MCP surface, in both directions
  ─────┼──────────────────────────────────────────────────────────
  domain       core/accounts.py · core/market.py · core/database.py
               plain Python. no LLM, no protocol, fully testable.
```

The rule that makes the layering worth having: **dependencies point downward
only**. `core/` imports nothing from `agents/`. That is why the whole broker can
be tested in 0.7 seconds with no API key.

---

## 3. Design decisions

### 3.1 The broker refuses; the prompt only asks

`Account.buy_shares` raises `ValueError` when the cash is not there. It does not
clamp the quantity, and it does not warn. The exception becomes a tool error the
agent reads and reacts to — usually by checking its balance and resizing.

The alternative, telling the model in its prompt to stay within budget, was
already there (and still is, as a hint). It is not a control. Prompts are
persuasion; the check in `accounts.py` is the thing that actually holds. Every
invariant in this system — sufficient funds, sufficient shares, positive
quantities, symbol validity — lives in code with a test next to it.

### 3.2 Tools versus resources

The accounts server exposes both, and the difference is deliberate:

| | Tool | Resource |
|---|---|---|
| Who chooses | the model | the client |
| Costs a turn | yes | no |
| Used here for | `buy_shares`, `sell_shares`, `change_strategy` | account state, strategy |

The trader begins each run already knowing its position and its strategy, because
`accounts_client.py` reads those two resources and puts them in the opening
message. Making the agent discover them through tool calls would burn two turns
of a 30-turn budget on facts we already have.

This is also why the project contains a hand-written MCP **client**: reading the
resources through the same URIs the agent would use means there is one definition
of "what an account looks like", not two.

### 3.3 Researcher as a tool, not a handoff

The trader's tool list contains `Researcher`, which is another full `Agent`
wrapped with `.as_tool()`.

A **handoff** would transfer the conversation to the researcher. That is wrong
here twice over: the researcher would inherit the trader's tools (including the
ability to buy shares — an agent whose job is reading the news must not be able
to place orders), and control would not return.

**Agent-as-tool** keeps the trader in charge, and — the part people miss —
isolates context. The researcher may make a dozen web searches and fetch three
pages; all of that noise stays in the researcher's own context window, and the
trader receives only the summary. Context isolation is the real reason this
pattern scales.

### 3.4 Context engineering at the boundary

`Trader.get_account_report()` deletes `portfolio_value_time_series` before the
account JSON reaches the model. The equity curve grows by one point per report
and is worth exactly nothing to a trading decision — it is a chart for humans.
Stripping it keeps the opening context the same size on run 500 as on run 1.

Similarly, Tavily's MCP server is filtered down to `tavily_search` alone. Its
crawl and deep-research tools are slower and dearer, and a model shown four tools
will eventually pick the expensive one. **The tool surface is part of the
prompt**, and trimming it is a design act.

### 3.5 Two kinds of memory

| | Knowledge graph (libSQL MCP) | Strategy (`change_strategy`) |
|---|---|---|
| Holds | entities and relations about companies, tickers, market conditions, useful URLs | the agent's own operating instructions |
| Written by | the researcher, continuously | the trader, when it reflects |
| Read | on demand, by query | injected into every prompt |
| Scope | one file per trader | one row per trader |

The first is retrieval. The second is closer to self-modification: the text that
shapes the next run is text the agent wrote about itself. Both survive process
restarts, which is what separates a scheduled agent that accumulates expertise
from one that wakes up amnesiac every hour.

### 3.6 Attribution through the trace id

`TracingProcessor` hooks receive a `Span`. A span knows its trace id and nothing
about which trader produced it — but four traders are running concurrently and
every log line must land in the right dashboard panel.

The trace id is the only field that survives from the caller down to the
processor, so the name is encoded into it:

```
make_trace_id("warren")  ->  "trace_warren0k3f9a2b8c1d..."
                                    └────┘└──────────────┘
                                    owner   random padding
```

The SDK requires exactly 32 characters after `trace_`, so the tag is padded with
randomness and separated by `0`, which cannot appear in a trader name.

It is a hack. It is also the correct hack: the alternative — a `ContextVar` — is
fragile across the SDK's task boundaries, and a global dict keyed by trace id
leaks. Being able to explain *why* the ugly solution is the right one is worth
more than not having one.

### 3.7 Failure is expected, not exceptional

Roughly a third of the non-obvious code in this project exists because things go
wrong at scale:

| Failure | Handling | Where |
|---|---|---|
| One trader's run raises | logged, swallowed, other three continue | `Trader.run` |
| Massive rejects an endpoint (plan tier) | fall to the next tier, remember it | `core/market.py` |
| Massive is down entirely | simulated price, run continues | `core/market.py` |
| Market status unreachable | assume open — a network blip must not halt the floor | `core/market.py` |
| Pushover fails | reported to the agent as text, not raised | `push_server.py` |
| Agent loops without converging | `max_turns=30` | `Trader.run_agent` |
| Run crashes mid-cycle | `AsyncExitStack` closes all six servers | `run_with_mcp_servers` |
| Four traders commit at once | WAL + 5s busy timeout | `core/database.py` |

The principle: **degrade the capability, never the run.** A missing notification
channel is not a reason to fail a completed trade.

### 3.8 Launching servers with `sys.executable`

Our MCP servers are launched as:

```python
{"command": sys.executable, "args": ["-m", "trading_floor.mcp_servers.accounts_server"]}
```

not `uv run -m ...`. The child then provably shares the parent's interpreter and
virtualenv. This matters more than it looks: when a stdio MCP server fails to
import, the traceback goes to a pipe nobody reads, the transport reports a
timeout, and the agent cheerfully tells you the tool was unavailable. Removing
the possibility of an environment mismatch removes the worst debugging session
in the project.

### 3.9 SQLite as the integration bus

Four writer processes, two reader processes, no server. WAL mode gives readers a
consistent snapshot while a writer commits; a 5-second busy timeout absorbs
contention; connections are per-operation because the participants are separate
processes anyway.

This is not the right answer at higher volume — one writer at a time is a real
ceiling — but for four agents acting a few times an hour it removes an entire
piece of infrastructure. Postgres would be a one-file change in `database.py`.

---

## 4. Data model

```sql
accounts(name TEXT PRIMARY KEY, account TEXT)   -- account is the Pydantic model as JSON
logs(id INTEGER PK, name TEXT, datetime, type TEXT, message TEXT)
```

The account is stored as a JSON blob rather than normalised into tables because
the Pydantic `Account` model *is* the schema — normalising it would create a
second place to keep in sync for no query we actually run. Every read is "give me
this one trader's whole state".

`logs` is append-only and read as a tail, so it is indexed on `(name, id)` and
ordered by `id` rather than by timestamp: several spans can land inside the same
second, and insertion order is the true order.

---

## 5. What I would change at production scale

* **Postgres, and a queue.** SQLite's single-writer limit is fine for four
  agents; it is not fine for four hundred. The database interface is already
  narrow enough to swap.
* **A pre-trade risk layer.** Position limits, sector concentration caps and a
  daily loss stop belong between the tool call and the broker. Today the only
  constraint is "can you afford it".
* **Prompt versioning.** Strategies mutate at runtime with no history. Every
  `change_strategy` should be an append, so a performance change can be traced to
  the strategy edit that caused it.
* **Spans to OpenTelemetry.** The SQLite tracer is perfect for the dashboard and
  wrong for aggregate analysis — cost per trader, tool latency percentiles,
  failure rates.
* **An evaluation harness.** There is currently no automated answer to "is this
  strategy any good?" beyond watching the equity curve. Replaying agents against
  recorded market data with a fixed seed would make strategy changes measurable
  rather than anecdotal.
