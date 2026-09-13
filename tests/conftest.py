"""Test fixtures.

The database path is read from the environment at import time, so it has to be
redirected *before* ``trading_floor`` is imported at all. Doing it here in
``conftest.py`` — which pytest loads first — is what keeps the test suite from
writing into a real trading database.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="trading-floor-tests-"))
os.environ["TRADING_FLOOR_DB"] = str(_TMP / "test.db")
os.environ["TRADING_FLOOR_MEMORY_DIR"] = str(_TMP / "memory")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
os.environ.pop("MASSIVE_API_KEY", None)  # force the deterministic price simulator

import pytest  # noqa: E402

from trading_floor.core.accounts import Account  # noqa: E402


@pytest.fixture
def account() -> Account:
    """A freshly reset account, isolated per test by name."""
    fresh = Account.get("tester")
    fresh.reset("A test strategy.")
    return fresh
