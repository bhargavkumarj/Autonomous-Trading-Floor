"""SQLite persistence for accounts and the agent activity log.

Two tables, one file. Accounts are stored as a JSON blob keyed by trader name —
the schema is the Pydantic ``Account`` model, so there is no second place to keep
it in sync. Logs are append-only rows written by the tracing processor and by the
account operations themselves, and are what the dashboard's live panel reads.

Every writer opens its own short-lived connection. The MCP servers, the scheduler
and the dashboard are separate OS processes, so a shared connection object would
not help them anyway; WAL mode plus a busy timeout is what lets them interleave.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from trading_floor.config import DB_PATH

BUSY_TIMEOUT_MS = 5000


@contextmanager
def _connect(path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    """A connection with WAL and a busy timeout, committed on clean exit.

    WAL lets the dashboard read while a trader writes; the busy timeout absorbs
    the moments when four traders commit at once.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: Path = DB_PATH) -> None:
    """Create the tables if they are not there yet. Safe to call repeatedly."""
    with _connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS accounts (name TEXT PRIMARY KEY, account TEXT)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                datetime DATETIME,
                type TEXT,
                message TEXT
            )"""
        )
        # The dashboard reads the tail of one trader's log every second.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_name_id ON logs (name, id)")


init_db()


def write_account(name: str, account: dict[str, Any]) -> None:
    """Upsert a trader's account state."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO accounts (name, account) VALUES (?, ?)
               ON CONFLICT(name) DO UPDATE SET account=excluded.account""",
            (name.lower(), json.dumps(account)),
        )


def read_account(name: str) -> dict[str, Any] | None:
    """A trader's account state, or None if they have never traded."""
    with _connect() as conn:
        row = conn.execute("SELECT account FROM accounts WHERE name = ?", (name.lower(),)).fetchone()
    return json.loads(row[0]) if row else None


def write_log(name: str, kind: str, message: str) -> None:
    """Append one activity line for a trader.

    ``kind`` is the span type from the tracing processor (agent, function,
    generation, response, trace) or "account" for a balance-changing operation.
    The dashboard colours the line by it.
    """
    with _connect() as conn:
        conn.execute(
            "INSERT INTO logs (name, datetime, type, message) VALUES (?, ?, ?, ?)",
            (name.lower(), datetime.now().isoformat(), kind, message),
        )


def read_log(name: str, last_n: int = 10) -> list[tuple[str, str, str]]:
    """The most recent ``last_n`` log lines for a trader, oldest first.

    Ordered by the autoincrement id rather than the timestamp: several lines can
    land inside the same second, and insertion order is the true order.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT datetime, type, message FROM logs WHERE name = ? ORDER BY id DESC LIMIT ?",
            (name.lower(), last_n),
        ).fetchall()
    return list(reversed(rows))
