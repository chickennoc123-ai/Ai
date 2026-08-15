"""Shared pytest fixtures.

Every fixture is offline: the simulated data provider and the simulated broker
mean the suite never touches the network or a real database.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Iterator

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broker.xm_connection import XMConnection  # noqa: E402
from core.backtest import BacktestConfig, BacktestEngine  # noqa: E402
from core.data_manager import SimulatedProvider  # noqa: E402
from core.strategy_registry import load_strategies  # noqa: E402
from models.database import Database, set_database  # noqa: E402
from utils.config import Config, get_config  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _load_registry() -> None:
    """Ensure every strategy is registered before the tests run."""
    load_strategies()


@pytest.fixture(scope="session")
def config() -> Config:
    """Return the platform configuration."""
    return get_config()


@pytest.fixture(scope="session")
def ohlcv() -> pd.DataFrame:
    """Return a deterministic EURUSD H1 frame."""
    return SimulatedProvider(seed=42).generate("EURUSD", "H1", 3000)


@pytest.fixture(scope="session")
def gold_ohlcv() -> pd.DataFrame:
    """Return a deterministic XAUUSD H1 frame."""
    return SimulatedProvider(seed=42).generate("XAUUSD", "H1", 3000)


@pytest.fixture(scope="session")
def short_ohlcv() -> pd.DataFrame:
    """Return a short frame used by fast tests."""
    return SimulatedProvider(seed=7).generate("EURUSD", "H1", 600)


@pytest.fixture
def engine() -> BacktestEngine:
    """Return a backtest engine with deterministic settings."""
    return BacktestEngine(
        BacktestConfig(
            initial_capital=10_000.0,
            commission=0.00007,
            slippage=0.00002,
            risk_per_trade=0.01,
        )
    )


@pytest.fixture
async def connection() -> Any:
    """Return a connected simulated broker connection."""
    broker = XMConnection(mode="simulated")
    await broker.connect()
    try:
        yield broker
    finally:
        await broker.disconnect()


@pytest.fixture
def memory_database(tmp_path: Path) -> Iterator[Database]:
    """Return a throwaway SQLite database bound to the singleton."""
    database = Database(url=f"sqlite:///{tmp_path / 'test.db'}")
    database.create_all()
    set_database(database)
    try:
        yield database
    finally:
        database.dispose()
        set_database(None)


@pytest.fixture
def sample_signal() -> Dict[str, Any]:
    """Return a well-formed signal payload."""
    return {
        "symbol": "XAUUSD",
        "timeframe": "H1",
        "direction": 1,
        "direction_label": "BUY",
        "confidence": 0.75,
        "entry_price": 2035.0,
        "stop_loss": 2029.0,
        "take_profit": 2047.0,
        "atr": 3.0,
        "strategy_id": "test-strategy",
    }
