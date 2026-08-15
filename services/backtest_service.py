"""Backtest service: runs backtests off the event loop and caches results."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Mapping, Optional

from core.backtest import BacktestConfig, BacktestEngine, BacktestResult, PortfolioResult
from core.data_manager import DataManager
from core.strategy_registry import create_strategy
from models.database import Database, session_scope
from models.trade import TradeRecord
from utils.config import Config, get_config
from utils.helpers import new_id
from utils.logger import get_logger

logger = get_logger(__name__)


class BacktestService:
    """Coordinates backtest execution for the API, agents and dashboard."""

    def __init__(
        self,
        data_manager: Optional[DataManager] = None,
        config: Optional[Config] = None,
        database: Optional[Database] = None,
    ) -> None:
        """Initialise the service."""
        self.config = config or get_config()
        self.data_manager = data_manager or DataManager(self.config)
        self.database = database
        self.engine = BacktestEngine(BacktestConfig.from_config(self.config))
        self._results: Dict[str, BacktestResult] = {}

    async def run(
        self,
        name: str,
        symbol: str,
        timeframe: str = "H1",
        bars: Optional[int] = None,
        params: Optional[Mapping[str, Any]] = None,
        overrides: Optional[Mapping[str, Any]] = None,
        persist: bool = False,
    ) -> Dict[str, Any]:
        """Run one backtest.

        Args:
            name: Registered strategy name.
            symbol: Instrument to trade.
            timeframe: Bar timeframe.
            bars: Number of bars of history.
            params: Strategy parameter overrides.
            overrides: Backtest configuration overrides (commission, ...).
            persist: Store the resulting trades in the database.

        Returns:
            The serialised backtest result including the equity curve.
        """
        frame = await self.data_manager.get_ohlcv(
            symbol, timeframe, bars or self.config.get_int("data.history_bars", 5000)
        )
        strategy = create_strategy(name, symbol, timeframe, params)
        engine = (
            BacktestEngine(BacktestConfig.from_config(self.config, **dict(overrides)))
            if overrides
            else self.engine
        )
        result = await asyncio.to_thread(engine.run, strategy, frame)
        self._results[result.strategy_id] = result
        if persist:
            self._persist_trades(result)
        logger.info(
            "Backtest complete",
            strategy=name,
            symbol=symbol,
            sharpe=round(result.metrics.sharpe, 3),
            trades=result.metrics.trades,
        )
        return result.to_dict(include_curve=True)

    async def run_matrix(
        self,
        names: List[str],
        symbols: List[str],
        timeframe: str = "H1",
        bars: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Backtest every ``(strategy, symbol)`` pair and return a summary."""
        frames = await self.data_manager.get_many(symbols, timeframe, bars)
        rows: List[Dict[str, Any]] = []
        for name in names:
            for symbol, frame in frames.items():
                try:
                    strategy = create_strategy(name, symbol, timeframe)
                    result = await asyncio.to_thread(self.engine.run, strategy, frame)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Matrix cell failed", strategy=name, symbol=symbol, error=str(exc))
                    continue
                self._results[result.strategy_id] = result
                metrics = result.metrics
                rows.append(
                    {
                        "strategy": name,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "sharpe": round(metrics.sharpe, 3),
                        "sortino": round(metrics.sortino, 3),
                        "calmar": round(metrics.calmar, 3),
                        "max_drawdown": round(metrics.max_drawdown, 4),
                        "win_rate": round(metrics.win_rate, 4),
                        "profit_factor": round(metrics.profit_factor, 3),
                        "trades": metrics.trades,
                        "net_profit": round(metrics.net_profit, 2),
                        "strategy_id": result.strategy_id,
                    }
                )
        rows.sort(key=lambda item: item["sharpe"], reverse=True)
        return rows

    async def run_portfolio(
        self,
        names: List[str],
        symbols: List[str],
        timeframe: str = "H1",
        bars: Optional[int] = None,
        weights: Optional[Mapping[str, float]] = None,
    ) -> Dict[str, Any]:
        """Backtest a portfolio of strategies and return the blended result."""
        frames = await self.data_manager.get_many(symbols, timeframe, bars)
        strategies = [
            create_strategy(name, symbol, timeframe) for name in names for symbol in frames
        ]
        portfolio: PortfolioResult = await asyncio.to_thread(
            self.engine.run_portfolio, strategies, frames, weights
        )
        return {
            "metrics": portfolio.metrics.to_dict(),
            "weights": portfolio.weights,
            "equity_curve": {
                "timestamps": [ts.isoformat() for ts in portfolio.equity_curve.index],
                "values": [float(value) for value in portfolio.equity_curve.to_numpy()],
            },
            "legs": {key: result.to_dict() for key, result in portfolio.legs.items()},
        }

    def get_result(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """Return a cached backtest result."""
        result = self._results.get(strategy_id)
        return result.to_dict(include_curve=True) if result else None

    def cached_results(self) -> List[str]:
        """Return the ids of cached results."""
        return list(self._results)

    def _persist_trades(self, result: BacktestResult) -> None:
        """Store backtest trades for later analysis."""
        if self.database is None:
            return
        try:
            with session_scope(self.database) as session:
                for trade in result.trades:
                    session.add(
                        TradeRecord(
                            trade_id=new_id("bt"),
                            strategy_id=result.strategy_id,
                            strategy_name=result.strategy_name,
                            symbol=trade.symbol,
                            timeframe=result.timeframe,
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
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unable to persist backtest trades", error=str(exc))
