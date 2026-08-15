"""Seed the database with strategies, historical candles and a demo account.

Usage::

    python scripts/seed_data.py                    # default seeding
    python scripts/seed_data.py --bars 8000 --backtest
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.backtest import BacktestConfig, BacktestEngine  # noqa: E402
from core.data_manager import DataManager  # noqa: E402
from core.strategy_registry import create_strategy, load_strategies  # noqa: E402
from models.account import AccountSnapshot  # noqa: E402
from models.database import get_database, session_scope  # noqa: E402
from models.metrics import SystemEvent  # noqa: E402
from models.strategy import StrategyRecord  # noqa: E402
from models.trade import TradeRecord  # noqa: E402
from utils.config import get_config  # noqa: E402
from utils.helpers import new_id  # noqa: E402
from utils.logger import get_logger, setup_logging_from_config  # noqa: E402


async def seed(bars: int, run_backtests: bool) -> None:
    """Populate the database and the market data cache.

    Args:
        bars: Number of candles to fetch and cache per symbol.
        run_backtests: Also store backtest trades for the active strategies.
    """
    config = get_config()
    setup_logging_from_config(config)
    logger = get_logger("seed_data")
    load_strategies()

    database = get_database(config)
    database.create_all()

    symbols: List[str] = list(config.get("broker.xmtrading.symbols", ["EURUSD"]))
    active: List[str] = list(config.get("strategies.active", ["RSI"]))
    timeframe = str(config.get("agents.analysis.timeframe", "H1"))

    # --- market data cache ---------------------------------------------------
    data_manager = DataManager(config)
    logger.info("Fetching market data", symbols=symbols, timeframe=timeframe, bars=bars)
    frames = await data_manager.get_many(symbols, timeframe, bars)
    for symbol, frame in frames.items():
        path = data_manager.save_cache(symbol, timeframe, frame)
        logger.info("Cached candles", symbol=symbol, rows=len(frame), path=str(path))

    # --- strategies ----------------------------------------------------------
    created = 0
    with session_scope(database) as session:
        for name in active:
            for symbol in symbols:
                strategy = create_strategy(name, symbol, timeframe)
                existing = (
                    session.query(StrategyRecord)
                    .filter(StrategyRecord.strategy_id == strategy.strategy_id)
                    .one_or_none()
                )
                if existing is not None:
                    continue
                metadata = strategy.metadata()
                session.add(
                    StrategyRecord(
                        strategy_id=strategy.strategy_id,
                        name=strategy.name,
                        category=strategy.category,
                        symbol=symbol,
                        timeframe=timeframe,
                        params=dict(strategy.params),
                        description=metadata.description,
                        enabled=True,
                    )
                )
                created += 1
    logger.info("Strategies seeded", created=created, total=len(active) * len(symbols))

    # --- account snapshot ----------------------------------------------------
    initial = config.get_float("broker.xmtrading.initial_balance", 10_000.0)
    with session_scope(database) as session:
        session.add(
            AccountSnapshot(
                account_id=str(config.get("broker.xmtrading.account_id", "DEMO-1000001")),
                balance=initial,
                equity=initial,
                margin=0.0,
                free_margin=initial,
                margin_level=0.0,
                leverage=config.get_float("broker.xmtrading.leverage", 500.0),
                server=str(config.get("broker.xmtrading.server", "XMGlobal-Demo")),
                demo=True,
            )
        )
        session.add(
            SystemEvent(
                level="INFO",
                category="system",
                source="seed_data",
                message="Database seeded",
                payload={"symbols": symbols, "strategies": active, "bars": bars},
            )
        )

    # --- optional backtest trades -------------------------------------------
    if run_backtests:
        engine = BacktestEngine(BacktestConfig.from_config(config))
        stored = 0
        for name in active:
            for symbol, frame in frames.items():
                try:
                    result = engine.run(create_strategy(name, symbol, timeframe), frame)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Backtest failed", strategy=name, symbol=symbol, error=str(exc))
                    continue
                with session_scope(database) as session:
                    for trade in result.trades:
                        session.add(
                            TradeRecord(
                                trade_id=new_id("seed"),
                                strategy_id=result.strategy_id,
                                strategy_name=result.strategy_name,
                                symbol=trade.symbol,
                                timeframe=timeframe,
                                direction=trade.direction,
                                volume=trade.volume,
                                entry_price=trade.entry_price,
                                exit_price=trade.exit_price,
                                gross_pnl=trade.gross_pnl,
                                commission=trade.commission,
                                pnl=trade.pnl,
                                return_pct=trade.return_pct,
                                bars_held=trade.bars_held,
                                exit_reason=trade.exit_reason,
                                confidence=trade.confidence,
                                source="backtest",
                                entry_time=trade.entry_time,
                                exit_time=trade.exit_time,
                            )
                        )
                        stored += 1
                logger.info(
                    "Backtest stored",
                    strategy=name,
                    symbol=symbol,
                    sharpe=round(result.metrics.sharpe, 3),
                    trades=result.metrics.trades,
                )
        logger.info("Backtest trades seeded", trades=stored)

    await data_manager.close()
    print("Seeding complete.")
    print(f"  Symbols   : {', '.join(symbols)}")
    print(f"  Strategies: {', '.join(active)}")
    print(f"  Candles   : {bars} per symbol ({timeframe})")


def main() -> int:
    """Parse arguments and run the seeding routine."""
    parser = argparse.ArgumentParser(description="Seed the EA Factory Pro database")
    parser.add_argument("--bars", type=int, default=5000, help="Candles to cache per symbol")
    parser.add_argument("--backtest", action="store_true", help="Also store backtest trades")
    arguments = parser.parse_args()
    asyncio.run(seed(arguments.bars, arguments.backtest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
