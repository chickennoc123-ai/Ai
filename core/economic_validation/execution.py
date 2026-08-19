"""Generation 4 — Trade execution mechanics for a rule-based candidate.

``core/ml_r2/backtest_r2.py`` already implements this project's audited
execution semantics (bar-close signal -> next-bar-open fill, same-bar risk
triggers, exit priority STOP_LOSS > TAKE_PROFIT > MAX_HOLDING_PERIOD).
That module is frozen evidence for STRAT-000001 and is **not modified
here**.

This module reimplements the same mechanics with one deliberate
extension: a *complete* round-turn cost model. ``BacktestConfig`` applies
slippage on entry only, and models spread implicitly at best (see
``ML-001-R2-IMPLEMENTATION-INTEGRITY-AUDIT.md`` §"Cost model"). A cost
model that charges one side of the round turn systematically flatters
every strategy it evaluates, so Generation 4 charges:

    entry  = open[t+1] + direction * (spread + slippage)
    exit   = trigger_level - direction * slippage
    plus   commission_per_lot_round_turn * lots

``assert_parity_with_backtest_r2`` (tests) pins this module against
``run_backtest`` under matched settings (spread=0, exit slippage off), so
the extension is demonstrably an *addition* to the audited semantics and
not a silent divergence from them.

Costs are **parameters**, not constants baked into the engine, because
Phase 17 must be able to re-run the identical trade logic under several
cost scenarios. The scenario set is declared in ``cost_stress.py`` before
any result is seen.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from utils.exceptions import EAFactoryError

EXECUTION_ENGINE_ID = "EXEC-R4-001"


class ExecutionError(EAFactoryError):
    pass


@dataclass(frozen=True)
class CostModel:
    """Round-turn execution costs, in price units and account currency.

    ``spread_price`` is the FULL bid/ask spread in price units. The data
    is a bid series (``DatasetRecord.price_type == "Bid (assumed)"``), so
    a long pays the spread on entry (buys at ask) and exits at bid; a
    short sells at bid and buys back at ask. Charging the whole spread on
    the entry leg is equivalent for a round turn and keeps the stop/target
    levels expressed on the series the data actually contains.
    """

    spread_price: float
    slippage_price: float
    commission_per_lot_round_turn: float
    pip_size: float
    pip_value_per_lot: float
    apply_exit_slippage: bool = True
    label: str = "BASE"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RiskRules:
    """Position sizing and risk-trigger geometry, taken from the frozen spec."""

    risk_per_trade: float
    stop_loss_atr_mult: float
    take_profit_atr_mult: float
    max_holding_bars: int
    max_positions: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutedTrade:
    entry_time: pd.Timestamp
    entry_price: float
    direction: int
    size_lots: float
    stop_loss_price: float
    take_profit_price: float
    entry_bar_index: int
    signal_time: pd.Timestamp
    atr_at_signal: float
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    holding_bars: Optional[int] = None
    pnl: Optional[float] = None
    gross_pnl: Optional[float] = None
    cost_paid: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["entry_time"] = str(self.entry_time)
        d["signal_time"] = str(self.signal_time)
        d["exit_time"] = str(self.exit_time) if self.exit_time is not None else None
        return d


@dataclass
class ExecutionResult:
    trades: List[ExecutedTrade] = field(default_factory=list)
    equity_curve: Optional[pd.Series] = None
    final_equity: float = 0.0
    initial_equity: float = 0.0
    bars_in_market: int = 0
    n_bars: int = 0
    unclosed_trade: bool = False


def _position_size(equity: float, stop_distance_price: float, risk: RiskRules, costs: CostModel) -> float:
    if stop_distance_price <= 0:
        raise ExecutionError("stop distance must be positive", stop_distance_price=stop_distance_price)
    sl_pips = stop_distance_price / costs.pip_size
    risk_amount = equity * risk.risk_per_trade
    return risk_amount / (sl_pips * costs.pip_value_per_lot)


def _pnl(trade: ExecutedTrade, exit_price: float, costs: CostModel) -> tuple:
    """Return ``(net_pnl, gross_pnl, cost_component)``.

    ``gross_pnl`` is measured from the *unslipped, unspread* mid-reference
    the trade would have achieved, so cost attribution in Phase 17 is a
    real decomposition rather than a re-quoted total.
    """
    price_move = (exit_price - trade.entry_price) * trade.direction
    pips = price_move / costs.pip_size
    net_price_pnl = pips * costs.pip_value_per_lot * trade.size_lots
    commission = costs.commission_per_lot_round_turn * trade.size_lots
    net = net_price_pnl - commission

    # Reference price move with no spread/slippage applied on either leg.
    ref_entry = trade.entry_price - trade.direction * (costs.spread_price + costs.slippage_price)
    ref_exit = exit_price + trade.direction * (costs.slippage_price if costs.apply_exit_slippage else 0.0)
    ref_pips = ((ref_exit - ref_entry) * trade.direction) / costs.pip_size
    gross = ref_pips * costs.pip_value_per_lot * trade.size_lots
    return net, gross, gross - net


def execute(
    ohlcv: pd.DataFrame,
    signals: pd.Series,
    *,
    costs: CostModel,
    risk: RiskRules,
    initial_equity: float = 10_000.0,
    atr_column: str = "atr_14",
) -> ExecutionResult:
    """Execute ``signals`` against ``ohlcv`` under the frozen risk rules.

    Args:
        ohlcv: frame with ``open, high, low, close`` and ``atr_column``,
            indexed by a strictly increasing DatetimeIndex.
        signals: integer series (+1/-1/0) aligned to a subset of
            ``ohlcv.index``. A signal at bar ``t`` is filled at the open
            of bar ``t+1`` -- the signal bar's own close is the last
            information used, never bar ``t+1``'s close or beyond.

    Timing and priority are identical to ``core.ml_r2.backtest_r2``:
    signals fill at next-bar open; SL/TP/max-hold are same-bar risk
    triggers with priority STOP_LOSS > TAKE_PROFIT > MAX_HOLDING_PERIOD.
    """
    required = {"open", "high", "low", atr_column}
    missing = required - set(ohlcv.columns)
    if missing:
        raise ExecutionError("ohlcv missing required columns", missing=sorted(missing))
    if not ohlcv.index.is_monotonic_increasing:
        raise ExecutionError("ohlcv timestamps must be strictly increasing")
    if risk.max_positions != 1:
        raise ExecutionError(
            "EXEC-R4-001 models exactly one open position at a time; a different value would "
            "require multi-position logic no frozen candidate specifies",
            max_positions=risk.max_positions,
        )

    equity = float(initial_equity)
    open_trade: Optional[ExecutedTrade] = None
    pending_entry: Optional[dict] = None
    trades: List[ExecutedTrade] = []
    equity_points: List[tuple] = []
    bars_in_market = 0

    opens = ohlcv["open"].to_numpy(dtype="float64")
    highs = ohlcv["high"].to_numpy(dtype="float64")
    lows = ohlcv["low"].to_numpy(dtype="float64")
    closes = ohlcv["close"].to_numpy(dtype="float64") if "close" in ohlcv.columns else opens
    atrs = ohlcv[atr_column].to_numpy(dtype="float64")
    index = ohlcv.index

    signal_map = {ts: int(v) for ts, v in signals.items() if int(v) != 0}

    for i, ts in enumerate(index):
        # --- fill anything scheduled for this bar's open ---
        if pending_entry is not None and open_trade is None:
            direction = pending_entry["direction"]
            atr_at_signal = pending_entry["atr"]
            if np.isfinite(atr_at_signal) and atr_at_signal > 0:
                entry_price = opens[i] + direction * (costs.spread_price + costs.slippage_price)
                sl_dist = risk.stop_loss_atr_mult * atr_at_signal
                tp_dist = risk.take_profit_atr_mult * atr_at_signal
                size = _position_size(equity, sl_dist, risk, costs)
                open_trade = ExecutedTrade(
                    entry_time=ts,
                    entry_price=entry_price,
                    direction=direction,
                    size_lots=size,
                    stop_loss_price=entry_price - direction * sl_dist,
                    take_profit_price=entry_price + direction * tp_dist,
                    entry_bar_index=i,
                    signal_time=pending_entry["signal_time"],
                    atr_at_signal=atr_at_signal,
                )
            pending_entry = None

        # --- same-bar risk triggers ---
        if open_trade is not None:
            bars_in_market += 1
            holding_bars = i - open_trade.entry_bar_index
            reason = None
            trigger_level = None

            if open_trade.direction == 1:
                if lows[i] <= open_trade.stop_loss_price:
                    reason, trigger_level = "STOP_LOSS", open_trade.stop_loss_price
                elif highs[i] >= open_trade.take_profit_price:
                    reason, trigger_level = "TAKE_PROFIT", open_trade.take_profit_price
            else:
                if highs[i] >= open_trade.stop_loss_price:
                    reason, trigger_level = "STOP_LOSS", open_trade.stop_loss_price
                elif lows[i] <= open_trade.take_profit_price:
                    reason, trigger_level = "TAKE_PROFIT", open_trade.take_profit_price

            if reason is None and holding_bars >= risk.max_holding_bars:
                reason, trigger_level = "MAX_HOLDING_PERIOD", closes[i]

            if reason is not None:
                exit_price = trigger_level
                if costs.apply_exit_slippage:
                    exit_price = trigger_level - open_trade.direction * costs.slippage_price
                net, gross, cost = _pnl(open_trade, exit_price, costs)
                equity += net
                open_trade.exit_time = ts
                open_trade.exit_price = exit_price
                open_trade.exit_reason = reason
                open_trade.holding_bars = holding_bars
                open_trade.pnl = net
                open_trade.gross_pnl = gross
                open_trade.cost_paid = cost
                trades.append(open_trade)
                open_trade = None

        # --- schedule a new entry for the NEXT bar's open ---
        if open_trade is None and pending_entry is None:
            sig = signal_map.get(ts, 0)
            if sig != 0:
                pending_entry = {"direction": sig, "atr": float(atrs[i]), "signal_time": ts}

        unrealized = 0.0
        if open_trade is not None:
            unrealized = _pnl(open_trade, closes[i], costs)[0]
        equity_points.append((ts, equity + unrealized))

    equity_curve = pd.Series({t: v for t, v in equity_points}, name="equity")
    return ExecutionResult(
        trades=trades,
        equity_curve=equity_curve,
        final_equity=equity,
        initial_equity=float(initial_equity),
        bars_in_market=bars_in_market,
        n_bars=len(index),
        unclosed_trade=open_trade is not None,
    )
