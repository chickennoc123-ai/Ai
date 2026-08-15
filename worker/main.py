"""Standalone agent worker.

Runs the agent fleet outside the API process, which is the recommended
production topology: the API stays responsive while research, validation and
risk computations run in their own container.

Usage::

    python -m worker.main                  # run every enabled agent
    python -m worker.main --only risk,execution
    API_START_AGENTS=false uvicorn api.main:app   # API without agents
"""

from __future__ import annotations

import argparse
import asyncio
import signal
from typing import List, Optional

from agents.orchestrator import AgentOrchestrator
from models.database import get_database
from utils.config import get_config
from utils.logger import get_logger, setup_logging_from_config


async def run(only: Optional[List[str]] = None) -> None:
    """Start the fleet and block until a termination signal arrives.

    Args:
        only: Restrict startup to these agent names.
    """
    config = get_config()
    setup_logging_from_config(config)
    logger = get_logger("worker")

    try:
        get_database(config).create_all()
    except Exception as exc:  # noqa: BLE001 - the worker can run without persistence
        logger.warning("Database unavailable, continuing without persistence", error=str(exc))

    orchestrator = AgentOrchestrator(config)
    results = await orchestrator.start(only)
    logger.info(
        "Worker started",
        agents=[name for name, ok in results.items() if ok],
        environment=config.get("system.environment"),
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in ("SIGINT", "SIGTERM"):
        try:
            loop.add_signal_handler(getattr(signal, signal_name), stop.set)
        except (NotImplementedError, AttributeError):  # pragma: no cover - Windows
            pass

    try:
        await stop.wait()
    except asyncio.CancelledError:  # pragma: no cover - forced shutdown
        pass
    finally:
        logger.info("Shutdown signal received, stopping agents")
        await orchestrator.stop()


def main() -> None:
    """Parse arguments and run the worker."""
    parser = argparse.ArgumentParser(description="EA Factory Pro agent worker")
    parser.add_argument(
        "--only",
        type=str,
        default="",
        help="Comma separated agent names to start (research, analysis, execution, risk, meta)",
    )
    arguments = parser.parse_args()
    only = [name.strip() for name in arguments.only.split(",") if name.strip()] or None
    try:
        asyncio.run(run(only))
    except KeyboardInterrupt:  # pragma: no cover - interactive use
        pass


if __name__ == "__main__":
    main()
