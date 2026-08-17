"""ML-001-R2 deterministic backtest mechanics.

Per ``ML-001-R2-CLEAN-REBUILD-SPEC.md`` Section 10 (Trading Rules) and
Section 6/11 (Backtest Implementation / Risk Implementation). All
constants below originate directly from the spec. This module is
mechanics only — it is not tuned, not optimized, and per the governing
implementation-phase instruction it is never run against real market
data or used to compute an economic-validation verdict in this phase.

Execution-timing convention (documented, not left implicit):

- Entries and signal-reversal exits are *signals*: computed from the
  probability at bar close ``t`` and executed at bar open ``t+1``
  (TIMING_PARITY, spec Section 12).
- Stop-loss, take-profit, and max-holding-period are *risk triggers*,
  not signals: they are evaluated against the current bar's intrabar
  high/low/close as soon as they occur, same bar, which is the standard
  and only sound way to model risk controls in a bar backtest.
- Exit priority when multiple risk triggers fire on the same bar:
  STOP_LOSS > TAKE_PROFIT > MAX_HOLDING_PERIOD > SIGNAL_REVERSAL,
  exactly as specified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from utils.exceptions import EAFactoryError

BACKTEST_SPEC_ID = "BACKTEST-R2-001"


class BacktestConfigError(EAFactoryError):
    """Raised when backtest configuration or input data is invalid."""


@dataclass(frozen=True)
class BacktestConfig:
    """All constants originate from ML-001-R2-CLEAN-REBUILD-SPEC.md Section 10."""

    long_threshold: float = 0.55
    short_threshold: float = 0.45
    risk_per_trade: float = 0.02
    stop_loss_atr_mult: float = 1.5
    take_profit_atr_mult: float = 2.5
    max_holding_bars: int = 24
    max_positions_per_symbol: int = 1

    # Cost model placeholders (spec Section 17, Open Question #2 — final
    # figures pending broker selection; documented deterministic stand-ins).
    pip_size: float = 0.0001
    pip_value_per_lot: float = 10.0
    commission_per_lot_round_turn: float = 7.0
    slippage_price: float = 0.00002  # 0.2 pip, per spec Section 7


@dataclass
class Trade:
    entry_time: pd.Timestamp
    entry_price: float
    direction: int  # +1 long, -1 short
    size_lots: float
    stop_loss_price: float
    take_profit_price: float
    entry_bar_index: int
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    holding_bars: Optional[int] = None
    pnl: Optional[float] = None

    def close(self, exit_time: pd.Timestamp, exit_price: float, reason: str, holding_bars: int, pnl: float) -> None:
        self.exit_time = exit_time
        self.exit_price = exit_price
        self.exit_reason = reason
        self.holding_bars = holding_bars
        self.pnl = pnl


@dataclass
class BacktestResult:
    trades: List[Trade] = field(default_factory=list)
    equity_curve: "pd.Series" = None  # type: ignore[assignment]
    final_equity: float = 0.0


def _position_size(equity: float, stop_loss_distance_price: float, config: BacktestConfig) -> float:
    if stop_loss_distance_price <= 0:
        raise BacktestConfigError("stop_loss_distance_price must be positive")
    sl_distance_pips = stop_loss_distance_price / config.pip_size
    risk_amount = equity * config.risk_per_trade
    return risk_amount / (sl_distance_pips * config.pip_value_per_lot)


def _trade_pnl(trade: Trade, exit_price: float, config: BacktestConfig) -> float:
    price_move = (exit_price - trade.entry_price) * trade.direction
    pips = price_move / config.pip_size
    gross = pips * config.pip_value_per_lot * trade.size_lots
    cost = config.commission_per_lot_round_turn * trade.size_lots
    return gross - cost


def run_backtest(
    ohlcv: pd.DataFrame,
    probabilities: pd.Series,
    config: BacktestConfig,
    initial_equity: float = 10_000.0,
) -> BacktestResult:
    """Run the deterministic ML-001-R2 trading-rule mechanics.

    Args:
        ohlcv: frame with ``open, high, low, close, atr_14`` columns,
            indexed by a strictly increasing DatetimeIndex.
        probabilities: ``predict_proba`` output aligned to a subset of
            ``ohlcv.index`` (one probability per usable bar).
        config: deterministic trading-rule constants.
        initial_equity: starting account equity.

    Returns:
        BacktestResult with the full trade list and equity curve.
    """
    required = {"open", "high", "low", "close", "atr_14"}
    missing = required - set(ohlcv.columns)
    if missing:
        raise BacktestConfigError("ohlcv missing required columns", missing=list(missing))
    if not ohlcv.index.is_monotonic_increasing:
        raise BacktestConfigError("ohlcv timestamps must be strictly increasing")

    equity = initial_equity
    open_trade: Optional[Trade] = None
    pending_entry: Optional[dict] = None
    pending_exit: Optional[str] = None
    trades: List[Trade] = []
    equity_points: List[tuple] = []

    index = ohlcv.index

    for i, ts in enumerate(index):
        row = ohlcv.loc[ts]

        # --- execute anything scheduled for "this bar's open" ---
        if pending_exit is not None and open_trade is not None:
            exit_price = row["open"]
            pnl = _trade_pnl(open_trade, exit_price, config)
            equity += pnl
            open_trade.close(ts, exit_price, pending_exit, i - open_trade.entry_bar_index, pnl)
            trades.append(open_trade)
            open_trade = None
            pending_exit = None

        if pending_entry is not None and open_trade is None:
            direction = pending_entry["direction"]
            entry_price = row["open"] + direction * config.slippage_price
            atr_at_entry = pending_entry["atr"]
            sl_dist = config.stop_loss_atr_mult * atr_at_entry
            tp_dist = config.take_profit_atr_mult * atr_at_entry
            size = _position_size(equity, sl_dist, config)
            open_trade = Trade(
                entry_time=ts,
                entry_price=entry_price,
                direction=direction,
                size_lots=size,
                stop_loss_price=entry_price - direction * sl_dist,
                take_profit_price=entry_price + direction * tp_dist,
                entry_bar_index=i,
            )
            pending_entry = None

        # --- same-bar risk triggers (priority: SL > TP > MAX_HOLD > REVERSAL) ---
        if open_trade is not None:
            holding_bars = i - open_trade.entry_bar_index
            reason = None
            exit_price = None

            if open_trade.direction == 1:
                if row["low"] <= open_trade.stop_loss_price:
                    reason, exit_price = "STOP_LOSS", open_trade.stop_loss_price
                elif row["high"] >= open_trade.take_profit_price:
                    reason, exit_price = "TAKE_PROFIT", open_trade.take_profit_price
            else:
                if row["high"] >= open_trade.stop_loss_price:
                    reason, exit_price = "STOP_LOSS", open_trade.stop_loss_price
                elif row["low"] <= open_trade.take_profit_price:
                    reason, exit_price = "TAKE_PROFIT", open_trade.take_profit_price

            if reason is None and holding_bars >= config.max_holding_bars:
                reason, exit_price = "MAX_HOLDING_PERIOD", row["close"]

            if reason is not None:
                pnl = _trade_pnl(open_trade, exit_price, config)
                equity += pnl
                open_trade.close(ts, exit_price, reason, holding_bars, pnl)
                trades.append(open_trade)
                open_trade = None
            elif ts in probabilities.index:
                p = probabilities.loc[ts]
                reversal = (open_trade.direction == 1 and p < config.short_threshold) or (
                    open_trade.direction == -1 and p > config.long_threshold
                )
                if reversal:
                    pending_exit = "SIGNAL_REVERSAL"

        # --- new-entry signal scheduling (next bar's open) ---
        if open_trade is None and pending_entry is None and ts in probabilities.index:
            p = probabilities.loc[ts]
            if p > config.long_threshold:
                pending_entry = {"direction": 1, "atr": row["atr_14"]}
            elif p < config.short_threshold:
                pending_entry = {"direction": -1, "atr": row["atr_14"]}

        unrealized = 0.0
        if open_trade is not None:
            unrealized = _trade_pnl(open_trade, row["close"], config)
        equity_points.append((ts, equity + unrealized))

    equity_curve = pd.Series({t: v for t, v in equity_points}, name="equity")
    return BacktestResult(trades=trades, equity_curve=equity_curve, final_equity=equity)
