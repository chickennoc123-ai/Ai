"""Event-driven backtest engine with realistic execution costs.

Semantics
---------
* A strategy's ``signal`` column is the **desired position** for the next bar
  (``1`` long, ``-1`` short, ``0`` flat).  Decisions are taken on the bar close
  and filled on the **next bar open**, which removes look-ahead bias.
* Fills pay half the spread plus a slippage fraction, and commission is
  charged on both legs as a fraction of traded notional.
* Stop-loss and take-profit are evaluated intrabar against high/low.  When a
  bar touches both levels the stop is assumed to trigger first (conservative).
* One position per strategy/symbol is held at a time; a flip closes and
  re-opens in the same bar.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from core.indicators import atr as atr_indicator
from core.strategy import Strategy
from core.utils import (
    InstrumentSpec,
    PerformanceMetrics,
    annualisation_factor,
    compute_metrics,
    get_instrument,
    lots_for_risk,
    notional_value,
    position_pnl,
)
from utils.config import Config, get_config
from utils.exceptions import DataError
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BacktestConfig:
    """Execution and money-management assumptions for a backtest."""

    initial_capital: float = 10_000.0
    commission: float = 0.0004
    slippage: float = 0.0002
    risk_per_trade: float = 0.01
    use_spread: bool = True
    allow_short: bool = True
    atr_period: int = 14
    default_sl_atr: float = 2.0
    default_tp_atr: float = 3.0
    max_lot: float = 5.0
    min_bars: int = 120
    leverage: float = 500.0

    @classmethod
    def from_config(cls, config: Optional[Config] = None, **overrides: Any) -> "BacktestConfig":
        """Build a config from ``config.yaml`` with optional overrides."""
        cfg = config or get_config()
        base = cls(
            initial_capital=cfg.get_float("backtest.initial_capital", 10_000.0),
            commission=cfg.get_float("backtest.commission", 0.0004),
            slippage=cfg.get_float("backtest.slippage", 0.0002),
            risk_per_trade=cfg.get_float("backtest.risk_per_trade", 0.01),
            leverage=cfg.get_float("broker.xmtrading.leverage", 500.0),
        )
        for key, value in overrides.items():
            if hasattr(base, key) and value is not None:
                setattr(base, key, value)
        return base


@dataclass
class Trade:
    """A single round-turn trade produced by the backtester."""

    symbol: str
    direction: int
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    volume: float
    gross_pnl: float
    commission: float
    pnl: float
    return_pct: float
    bars_held: int
    exit_reason: str
    mae: float = 0.0
    mfe: float = 0.0
    confidence: float = 0.5
    strategy_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """JSON friendly representation."""
        payload = asdict(self)
        payload["entry_time"] = self.entry_time.isoformat() if hasattr(self.entry_time, "isoformat") else str(self.entry_time)
        payload["exit_time"] = self.exit_time.isoformat() if hasattr(self.exit_time, "isoformat") else str(self.exit_time)
        return payload


@dataclass
class BacktestResult:
    """Full output of a backtest run."""

    strategy_name: str
    strategy_id: str
    symbol: str
    timeframe: str
    equity_curve: pd.Series
    trades: List[Trade]
    metrics: PerformanceMetrics
    params: Dict[str, Any] = field(default_factory=dict)
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    bars: int = 0
    exposure: float = 0.0
    initial_capital: float = 10_000.0

    @property
    def trade_pnls(self) -> List[float]:
        """Realised P&L of each closed trade."""
        return [trade.pnl for trade in self.trades]

    @property
    def returns(self) -> pd.Series:
        """Bar-by-bar equity returns."""
        if self.equity_curve.empty:
            return pd.Series(dtype="float64")
        return self.equity_curve.pct_change().fillna(0.0)

    def trades_frame(self) -> pd.DataFrame:
        """Return the trade list as a DataFrame."""
        if not self.trades:
            return pd.DataFrame(
                columns=["symbol", "direction", "entry_time", "entry_price", "exit_time",
                         "exit_price", "volume", "pnl", "exit_reason"]
            )
        return pd.DataFrame([trade.to_dict() for trade in self.trades])

    def to_dict(self, include_curve: bool = False) -> Dict[str, Any]:
        """Serialise the result for the API and persistence."""
        payload: Dict[str, Any] = {
            "strategy_name": self.strategy_name,
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "params": self.params,
            "bars": self.bars,
            "exposure": self.exposure,
            "initial_capital": self.initial_capital,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "metrics": self.metrics.to_dict(),
            "trade_count": len(self.trades),
        }
        if include_curve:
            payload["equity_curve"] = {
                "timestamps": [ts.isoformat() for ts in self.equity_curve.index],
                "values": [float(value) for value in self.equity_curve.to_numpy()],
            }
            payload["trades"] = [trade.to_dict() for trade in self.trades]
        return payload


class BacktestEngine:
    """Runs strategies over historical bars and measures the outcome."""

    def __init__(self, config: Optional[BacktestConfig] = None) -> None:
        """Initialise the engine with execution assumptions."""
        self.config = config or BacktestConfig()

    # -- public API ----------------------------------------------------------
    def run(
        self,
        strategy: Strategy,
        df: pd.DataFrame,
        signals: Optional[pd.DataFrame] = None,
    ) -> BacktestResult:
        """Backtest a single strategy on a single OHLCV frame.

        Args:
            strategy: Strategy instance (its ``symbol`` defines the contract).
            df: Canonical OHLCV frame.
            signals: Pre-computed signal frame; computed when omitted.

        Returns:
            A populated :class:`BacktestResult`.

        Raises:
            DataError: If the frame is too short to evaluate.
        """
        if df is None or df.empty:
            raise DataError("Cannot backtest on an empty frame", strategy=strategy.name)
        if len(df) < 30:
            raise DataError("Not enough bars for a backtest", bars=len(df), strategy=strategy.name)

        spec = get_instrument(strategy.symbol)
        frame = df.copy()
        signal_frame = signals if signals is not None else strategy.generate_signals(frame)
        signal_frame = signal_frame.reindex(frame.index).fillna({"signal": 0, "confidence": 0.5})

        atr_values = atr_indicator(frame["high"], frame["low"], frame["close"], self.config.atr_period)
        atr_values = atr_values.bfill().fillna(frame["close"] * 0.002)

        result = self._simulate(strategy, spec, frame, signal_frame, atr_values)
        logger.debug(
            "Backtest finished",
            strategy=strategy.name,
            symbol=strategy.symbol,
            trades=len(result.trades),
            sharpe=round(result.metrics.sharpe, 3),
        )
        return result

    def run_multi(
        self,
        strategy: Strategy,
        data: Mapping[str, pd.DataFrame],
    ) -> Dict[str, BacktestResult]:
        """Backtest one strategy across several symbols."""
        results: Dict[str, BacktestResult] = {}
        for symbol, frame in data.items():
            try:
                results[symbol] = self.run(strategy.for_symbol(symbol), frame)
            except Exception as exc:
                logger.warning("Backtest failed", strategy=strategy.name, symbol=symbol, error=str(exc))
        return results

    def run_portfolio(
        self,
        strategies: Sequence[Strategy],
        data: Mapping[str, pd.DataFrame],
        weights: Optional[Mapping[str, float]] = None,
    ) -> "PortfolioResult":
        """Backtest several strategies and aggregate their equity curves.

        Args:
            strategies: Strategy instances (each bound to its own symbol).
            data: Mapping of symbol to OHLCV frame.
            weights: Optional capital weight per ``strategy_id``.

        Returns:
            A :class:`PortfolioResult` with the blended curve and per-strategy
            results.
        """
        results: Dict[str, BacktestResult] = {}
        for strategy in strategies:
            frame = data.get(strategy.symbol)
            if frame is None or frame.empty:
                continue
            try:
                results[strategy.strategy_id] = self.run(strategy, frame)
            except Exception as exc:
                logger.warning("Portfolio leg failed", strategy=strategy.name, error=str(exc))
        return PortfolioResult.build(results, self.config.initial_capital, weights)

    # -- simulation core -----------------------------------------------------
    def _simulate(
        self,
        strategy: Strategy,
        spec: InstrumentSpec,
        frame: pd.DataFrame,
        signal_frame: pd.DataFrame,
        atr_values: pd.Series,
    ) -> BacktestResult:
        """Bar-by-bar simulation loop."""
        cfg = self.config
        opens = frame["open"].to_numpy(dtype="float64")
        highs = frame["high"].to_numpy(dtype="float64")
        lows = frame["low"].to_numpy(dtype="float64")
        closes = frame["close"].to_numpy(dtype="float64")
        index = frame.index

        desired = signal_frame["signal"].to_numpy(dtype="int8")
        confidence = signal_frame["confidence"].to_numpy(dtype="float64")
        sl_levels = signal_frame["sl"].to_numpy(dtype="float64") if "sl" in signal_frame else np.full(len(frame), np.nan)
        tp_levels = signal_frame["tp"].to_numpy(dtype="float64") if "tp" in signal_frame else np.full(len(frame), np.nan)
        atr_array = atr_values.to_numpy(dtype="float64")

        half_spread = (spec.typical_spread_pips * spec.pip_size) / 2.0 if cfg.use_spread else 0.0

        equity = cfg.initial_capital
        balance = cfg.initial_capital
        equity_curve = np.empty(len(frame), dtype="float64")

        trades: List[Trade] = []
        position = 0
        entry_price = 0.0
        entry_index = 0
        volume = 0.0
        stop_price = np.nan
        target_price = np.nan
        best_price = 0.0
        worst_price = 0.0
        entry_confidence = 0.5
        bars_in_market = 0
        # Direction we were last stopped/targeted out of. Re-entry in the same
        # direction is blocked until the strategy changes its mind, otherwise a
        # persistent signal would immediately re-open the position it just lost.
        blocked_direction = 0

        for i in range(len(frame)):
            price_open, price_high, price_low, price_close = opens[i], highs[i], lows[i], closes[i]

            # --- manage the open position against intrabar extremes ----------
            if position != 0:
                bars_in_market += 1
                best_price = max(best_price, price_high) if position > 0 else min(best_price, price_low)
                worst_price = min(worst_price, price_low) if position > 0 else max(worst_price, price_high)

                exit_price, reason = self._check_stops(position, stop_price, target_price, price_high, price_low)
                if exit_price is not None:
                    fill = self._exit_fill(exit_price, position, half_spread)
                    trade, balance = self._close_position(
                        spec, strategy, position, entry_price, fill, volume, balance,
                        index[entry_index], index[i], i - entry_index, reason,
                        best_price, worst_price, entry_confidence,
                    )
                    trades.append(trade)
                    blocked_direction = position
                    position, volume, stop_price, target_price = 0, 0.0, np.nan, np.nan

            # --- act on the signal produced by the previous bar --------------
            if i > 0:
                target_position = int(desired[i - 1])
                if not cfg.allow_short and target_position < 0:
                    target_position = 0
                if blocked_direction != 0 and target_position != blocked_direction:
                    blocked_direction = 0

                if position != 0 and target_position != position:
                    fill = self._exit_fill(price_open, position, half_spread)
                    trade, balance = self._close_position(
                        spec, strategy, position, entry_price, fill, volume, balance,
                        index[entry_index], index[i], i - entry_index, "SIGNAL",
                        best_price, worst_price, entry_confidence,
                    )
                    trades.append(trade)
                    position, volume, stop_price, target_price = 0, 0.0, np.nan, np.nan

                if position == 0 and target_position != 0 and target_position != blocked_direction:
                    fill = self._entry_fill(price_open, target_position, half_spread)
                    stop_candidate = sl_levels[i - 1]
                    target_candidate = tp_levels[i - 1]
                    atr_value = atr_array[i - 1] if not np.isnan(atr_array[i - 1]) else price_open * 0.002
                    if np.isnan(stop_candidate):
                        stop_candidate = fill - target_position * cfg.default_sl_atr * atr_value
                    if np.isnan(target_candidate):
                        target_candidate = fill + target_position * cfg.default_tp_atr * atr_value
                    stop_distance = abs(fill - stop_candidate)
                    lots = lots_for_risk(spec, equity, cfg.risk_per_trade, stop_distance, fill)
                    lots = min(lots, cfg.max_lot)
                    if lots >= spec.min_lot:
                        position = target_position
                        entry_price = fill
                        entry_index = i
                        volume = lots
                        stop_price = stop_candidate
                        target_price = target_candidate
                        best_price = fill
                        worst_price = fill
                        entry_confidence = float(confidence[i - 1])
                        balance -= self._commission(spec, fill, lots)
                        bars_in_market += 1

                        # The entry bar can still hit its own stop or target.
                        exit_price, reason = self._check_stops(
                            position, stop_price, target_price, price_high, price_low
                        )
                        if exit_price is not None:
                            exit_fill = self._exit_fill(exit_price, position, half_spread)
                            trade, balance = self._close_position(
                                spec, strategy, position, entry_price, exit_fill, volume, balance,
                                index[i], index[i], 0, reason, price_high, price_low, entry_confidence,
                            )
                            trades.append(trade)
                            blocked_direction = position
                            position, volume, stop_price, target_price = 0, 0.0, np.nan, np.nan

            # --- mark to market ---------------------------------------------
            if position != 0:
                unrealised = position_pnl(spec, position, entry_price, price_close, volume)
                equity = balance + unrealised
            else:
                equity = balance
            equity_curve[i] = equity
            if equity <= 0:  # account blown up - stop trading
                equity_curve[i:] = max(equity, 0.0)
                logger.warning("Backtest account depleted", strategy=strategy.name, bar=i)
                position = 0
                break

        # --- close any position left open at the end -------------------------
        if position != 0:
            last = len(frame) - 1
            fill = self._exit_fill(closes[last], position, half_spread)
            trade, balance = self._close_position(
                spec, strategy, position, entry_price, fill, volume, balance,
                index[entry_index], index[last], last - entry_index, "END_OF_DATA",
                best_price, worst_price, entry_confidence,
            )
            trades.append(trade)
            equity_curve[last] = balance

        curve = pd.Series(equity_curve, index=index, name="equity")
        periods = annualisation_factor(strategy.timeframe)
        exposure = bars_in_market / max(len(frame), 1)
        metrics = compute_metrics(
            curve,
            [trade.pnl for trade in trades],
            periods_per_year=periods,
            initial_capital=cfg.initial_capital,
            extras={"exposure": exposure},
        )
        metrics.exposure = exposure
        metrics.commission_paid = float(sum(trade.commission for trade in trades))

        return BacktestResult(
            strategy_name=strategy.name,
            strategy_id=strategy.strategy_id,
            symbol=strategy.symbol,
            timeframe=strategy.timeframe,
            equity_curve=curve,
            trades=trades,
            metrics=metrics,
            params=dict(strategy.params),
            start=index[0].to_pydatetime(),
            end=index[-1].to_pydatetime(),
            bars=len(frame),
            exposure=exposure,
            initial_capital=cfg.initial_capital,
        )

    @staticmethod
    def _check_stops(
        direction: int, stop_price: float, target_price: float, high: float, low: float
    ) -> tuple[Optional[float], str]:
        """Return the triggered protective level for a bar, if any.

        When a bar touches both the stop and the target the stop is assumed to
        trigger first, which keeps the simulation conservative.
        """
        if direction > 0:
            if not np.isnan(stop_price) and low <= stop_price:
                return stop_price, "STOP_LOSS"
            if not np.isnan(target_price) and high >= target_price:
                return target_price, "TAKE_PROFIT"
        elif direction < 0:
            if not np.isnan(stop_price) and high >= stop_price:
                return stop_price, "STOP_LOSS"
            if not np.isnan(target_price) and low <= target_price:
                return target_price, "TAKE_PROFIT"
        return None, ""

    # -- fills and costs -----------------------------------------------------
    def _entry_fill(self, price: float, direction: int, half_spread: float) -> float:
        """Return the entry fill price including spread and slippage."""
        slip = price * self.config.slippage
        return price + direction * (half_spread + slip)

    def _exit_fill(self, price: float, direction: int, half_spread: float) -> float:
        """Return the exit fill price including spread and slippage."""
        slip = price * self.config.slippage
        return price - direction * (half_spread + slip)

    def _commission(self, spec: InstrumentSpec, price: float, lots: float) -> float:
        """Commission charged for one leg of a trade."""
        notional = notional_value(spec, price, lots)
        return notional * self.config.commission + spec.commission_per_lot * lots / 2.0

    def _close_position(
        self,
        spec: InstrumentSpec,
        strategy: Strategy,
        direction: int,
        entry_price: float,
        exit_price: float,
        volume: float,
        balance: float,
        entry_time: Any,
        exit_time: Any,
        bars_held: int,
        reason: str,
        best_price: float,
        worst_price: float,
        confidence: float,
    ) -> tuple[Trade, float]:
        """Close a position and return the trade plus the updated balance."""
        gross = position_pnl(spec, direction, entry_price, exit_price, volume)
        commission = self._commission(spec, exit_price, volume)
        net = gross - commission
        new_balance = balance + net
        risk_capital = max(self.config.initial_capital, 1.0)
        trade = Trade(
            symbol=strategy.symbol,
            direction=direction,
            entry_time=entry_time.to_pydatetime() if hasattr(entry_time, "to_pydatetime") else entry_time,
            entry_price=float(entry_price),
            exit_time=exit_time.to_pydatetime() if hasattr(exit_time, "to_pydatetime") else exit_time,
            exit_price=float(exit_price),
            volume=float(volume),
            gross_pnl=float(gross),
            commission=float(commission),
            pnl=float(net),
            return_pct=float(net / risk_capital),
            bars_held=int(bars_held),
            exit_reason=reason,
            mae=float(position_pnl(spec, direction, entry_price, worst_price, volume)),
            mfe=float(position_pnl(spec, direction, entry_price, best_price, volume)),
            confidence=float(confidence),
            strategy_id=strategy.strategy_id,
        )
        return trade, new_balance


@dataclass
class PortfolioResult:
    """Aggregated result of several strategies traded together."""

    equity_curve: pd.Series
    metrics: PerformanceMetrics
    legs: Dict[str, BacktestResult] = field(default_factory=dict)
    weights: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        results: Mapping[str, BacktestResult],
        initial_capital: float,
        weights: Optional[Mapping[str, float]] = None,
    ) -> "PortfolioResult":
        """Blend individual equity curves into a portfolio curve."""
        if not results:
            empty = pd.Series(dtype="float64")
            return cls(empty, compute_metrics(empty), {}, {})
        count = len(results)
        applied = {key: float(weights.get(key, 1.0 / count)) if weights else 1.0 / count for key in results}
        total_weight = sum(applied.values()) or 1.0
        applied = {key: value / total_weight for key, value in applied.items()}

        combined: Optional[pd.Series] = None
        for key, result in results.items():
            normalised = result.equity_curve / result.initial_capital
            contribution = normalised * applied[key]
            combined = contribution if combined is None else combined.add(contribution, fill_value=applied[key])
        assert combined is not None
        curve = (combined * initial_capital).sort_index()
        all_trades: List[float] = []
        for key, result in results.items():
            all_trades.extend(pnl * applied[key] * count for pnl in result.trade_pnls)
        timeframe = next(iter(results.values())).timeframe
        metrics = compute_metrics(
            curve, all_trades, annualisation_factor(timeframe), initial_capital
        )
        return cls(curve, metrics, dict(results), applied)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the portfolio summary."""
        return {
            "metrics": self.metrics.to_dict(),
            "weights": self.weights,
            "legs": {key: result.to_dict() for key, result in self.legs.items()},
        }


def quick_backtest(
    strategy: Strategy,
    df: pd.DataFrame,
    config: Optional[BacktestConfig] = None,
) -> BacktestResult:
    """Convenience helper used by agents and validation routines."""
    return BacktestEngine(config or BacktestConfig.from_config()).run(strategy, df)


def summarize_results(results: Iterable[BacktestResult]) -> pd.DataFrame:
    """Return a comparison table for a collection of backtests."""
    rows: List[Dict[str, Any]] = []
    for result in results:
        metrics = result.metrics
        rows.append(
            {
                "strategy": result.strategy_name,
                "symbol": result.symbol,
                "timeframe": result.timeframe,
                "sharpe": round(metrics.sharpe, 3),
                "sortino": round(metrics.sortino, 3),
                "calmar": round(metrics.calmar, 3),
                "max_dd": round(metrics.max_drawdown, 4),
                "win_rate": round(metrics.win_rate, 3),
                "profit_factor": round(metrics.profit_factor, 3),
                "trades": metrics.trades,
                "net_profit": round(metrics.net_profit, 2),
            }
        )
    return pd.DataFrame(rows).sort_values("sharpe", ascending=False) if rows else pd.DataFrame()
