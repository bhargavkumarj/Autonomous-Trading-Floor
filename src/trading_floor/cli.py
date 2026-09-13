"""One entry point for every way of running the floor.

    trading-floor reset       wipe accounts and reinstall the opening strategies
    trading-floor run         start the scheduler (this is the actual system)
    trading-floor dashboard   the Gradio operator view
    trading-floor api         the read-only JSON API for the web frontend
    trading-floor doctor      check the environment before spending anything

``doctor`` exists because the failure mode of a misconfigured MCP setup is
horrible: a stdio server that cannot start dies silently inside the transport and
the agent simply reports that a tool did not work. Checking for Node, uv and the
keys up front turns twenty minutes of confusion into one line of output.
"""

from __future__ import annotations

import argparse
import shutil
import sys

from trading_floor import config


def _doctor() -> int:
    """Report what is configured and what will silently degrade without it."""
    print("Trading Floor environment check\n")

    required = [("OPENAI_API_KEY", config.OPENAI_API_KEY, "the traders cannot run at all")]
    optional = [
        ("MASSIVE_API_KEY", config.MASSIVE_API_KEY, "prices come from the built-in simulator"),
        ("TAVILY_API_KEY", config.TAVILY_API_KEY, "the researcher loses web search"),
        ("PUSHOVER_USER", config.PUSHOVER_USER, "push notifications are logged, not sent"),
        ("PUSHOVER_TOKEN", config.PUSHOVER_TOKEN, "push notifications are logged, not sent"),
    ]
    binaries = [
        ("node", "Tavily and the memory MCP servers cannot start"),
        ("npx", "Tavily and the memory MCP servers cannot start"),
        ("uvx", "the fetch MCP server cannot start"),
    ]

    ok = True
    for name, value, consequence in required:
        if value:
            print(f"  [ ok ] {name}")
        else:
            ok = False
            print(f"  [FAIL] {name} is missing — {consequence}")

    for name, value, consequence in optional:
        print(f"  [ ok ] {name}" if value else f"  [warn] {name} not set — {consequence}")

    for name, consequence in binaries:
        path = shutil.which(name)
        print(f"  [ ok ] {name} ({path})" if path else f"  [warn] {name} not found — {consequence}")

    print(f"\n  database  {config.DB_PATH}")
    print(f"  memory    {config.MEMORY_DIR}")
    print(f"  prices    {'Massive (live)' if config.using_live_market_data() else 'simulator'}")
    print(f"  models    {'one per trader' if config.USE_MANY_MODELS else config.DEFAULT_MODEL}")
    print(f"  schedule  every {config.RUN_EVERY_N_MINUTES} minutes")
    print("\nReady." if ok else "\nNot ready: fix the FAIL lines above.")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading-floor", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("reset", help="wipe accounts and reinstall the opening strategies")
    run_cmd = sub.add_parser("run", help="start the trading floor scheduler")
    run_cmd.add_argument("--once", action="store_true", help="run a single trading cycle and exit")
    sub.add_parser("dashboard", help="launch the Gradio operator dashboard")
    sub.add_parser("doctor", help="check keys, binaries and paths")
    api = sub.add_parser("api", help="serve the read-only JSON API")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)

    if args.command == "doctor":
        return _doctor()

    if args.command == "reset":
        from trading_floor.strategies import main as reset_main

        reset_main()
        return 0

    if args.command == "run":
        if args.once:
            import asyncio
            import logging
            from trading_floor.floor import run_once

            logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s")
            asyncio.run(run_once())
            return 0

        from trading_floor.floor import main as floor_main

        floor_main()
        return 0

    if args.command == "dashboard":
        from trading_floor.ui.dashboard import main as dashboard_main

        dashboard_main()
        return 0

    if args.command == "api":
        import uvicorn

        uvicorn.run("trading_floor.api.app:app", host=args.host, port=args.port)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
