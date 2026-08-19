"""Generation 4 — Economic performance metrics.

One implementation, used by every phase (development, holdout, OOS, each
walk-forward window, each robustness point, each cost scenario). A second
implementation anywhere would make cross-phase comparison meaningless.

Conventions that are easy to get silently wrong, fixed here explicitly:

* **Sharpe/Sortino are computed on the per-bar equity return series**,
  not on per-trade P&L, and annualized with the bar count per year for
  the instrument's timeframe. Per-trade "Sharpe" is a different quantity
  and is reported separately as ``trade_sharpe`` so the two are never
  confused.
* **Profit factor with zero losses is ``inf``**, reported as ``None``
  rather than a large finite number, so no downstream comparison silently
  treats "never lost" as a specific numeric edge.
* **Max drawdown is computed on the equity curve including open-trade
  unrealized P&L**, which is the drawdown an account actually experiences.
* **Zero trades yields ``None`` for every ratio**, never 0.0. Absence of
  trades is absence of evidence, not evidence of zero performance.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from core.economic_validation.execution import ExecutedTrade, ExecutionResult

#: H1 bars per year for FX: 24 bars x 5 days x 52 weeks.
BARS_PER_YEAR = {"H1": 6240, "H4": 1560, "D1": 260, "M15": 24960, "M5": 74880}


@dataclass(frozen=True)
class PerformanceMetrics:
    trade_count: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    gross_profit: float
    gross_loss: float
    net_profit: float
    profit_factor: Optional[float]
    win_rate: Optional[float]
    expectancy: Optional[float]
    average_trade: Optional[float]
    average_win: Optional[float]
    average_loss: Optional[float]
    largest_win: Optional[float]
    largest_loss: Optional[float]
    sharpe: Optional[float]
    sortino: Optional[float]
    trade_sharpe: Optional[float]
    max_drawdown: float
    max_drawdown_pct: Optional[float]
    max_drawdown_duration_bars: int
    recovery_factor: Optional[float]
    longest_losing_streak: int
    longest_winning_streak: int
    turnover: Optional[float]
    exposure: Optional[float]
    total_costs_paid: float
    gross_pnl_before_costs: float
    return_distribution: Dict[str, Any]
    exit_reason_counts: Dict[str, int]
    initial_equity: float
    final_equity: float
    bars: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _safe_div(num: float, den: float) -> Optional[float]:
    if den == 0:
        return None
    return num / den


def _max_drawdown(equity: pd.Series) -> tuple:
    """Return ``(max_drawdown_abs, max_drawdown_pct, duration_bars)``."""
    if equity is None or len(equity) == 0:
        return 0.0, None, 0
    values = equity.to_numpy(dtype="float64")
    running_max = np.maximum.accumulate(values)
    drawdown = running_max - values
    max_dd = float(drawdown.max()) if len(drawdown) else 0.0

    with np.errstate(divide="ignore", invalid="ignore"):
        dd_pct = np.where(running_max > 0, drawdown / running_max, np.nan)
    max_dd_pct = float(np.nanmax(dd_pct)) if len(dd_pct) and not np.all(np.isnan(dd_pct)) else None

    # Longest span spent below a previous peak.
    duration = 0
    current = 0
    for i in range(len(values)):
        if values[i] < running_max[i]:
            current += 1
            duration = max(duration, current)
        else:
            current = 0
    return max_dd, max_dd_pct, duration


def _streaks(pnls: Sequence[float]) -> tuple:
    longest_loss = longest_win = 0
    cur_loss = cur_win = 0
    for p in pnls:
        if p < 0:
            cur_loss += 1
            cur_win = 0
        elif p > 0:
            cur_win += 1
            cur_loss = 0
        else:
            cur_loss = cur_win = 0
        longest_loss = max(longest_loss, cur_loss)
        longest_win = max(longest_win, cur_win)
    return longest_loss, longest_win


def _distribution(values: Sequence[float]) -> Dict[str, Any]:
    if len(values) == 0:
        return {"n": 0}
    arr = np.asarray(values, dtype="float64")
    return {
        "n": int(arr.size),
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)) if arr.size > 1 else None,
        "min": float(arr.min()),
        "p05": float(np.percentile(arr, 5)),
        "p25": float(np.percentile(arr, 25)),
        "median": float(np.median(arr)),
        "p75": float(np.percentile(arr, 75)),
        "p95": float(np.percentile(arr, 95)),
        "max": float(arr.max()),
        "skew": float(pd.Series(arr).skew()) if arr.size > 2 else None,
        "kurtosis": float(pd.Series(arr).kurtosis()) if arr.size > 3 else None,
    }


def compute_metrics(
    result: ExecutionResult,
    *,
    timeframe: str = "H1",
) -> PerformanceMetrics:
    """Compute the full Generation 4 metric set from an execution result."""
    trades: List[ExecutedTrade] = [t for t in result.trades if t.pnl is not None]
    pnls = [float(t.pnl) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    breakeven = [p for p in pnls if p == 0]

    gross_profit = float(sum(wins))
    gross_loss = float(-sum(losses))  # positive magnitude
    net_profit = float(sum(pnls))

    profit_factor: Optional[float]
    if gross_loss == 0:
        profit_factor = None if gross_profit > 0 else None
    else:
        profit_factor = gross_profit / gross_loss

    equity = result.equity_curve
    max_dd, max_dd_pct, dd_duration = _max_drawdown(equity)

    if equity is not None and len(equity) > 1:
        bar_returns = equity.pct_change().dropna()
        periods = BARS_PER_YEAR.get(timeframe)
        if periods and len(bar_returns) > 1 and bar_returns.std(ddof=1) > 0:
            sharpe = float(bar_returns.mean() / bar_returns.std(ddof=1) * math.sqrt(periods))
        else:
            sharpe = None
        downside = bar_returns[bar_returns < 0]
        if periods and len(downside) > 1 and downside.std(ddof=1) > 0:
            sortino = float(bar_returns.mean() / downside.std(ddof=1) * math.sqrt(periods))
        else:
            sortino = None
        return_dist = _distribution(bar_returns.to_numpy())
    else:
        sharpe = sortino = None
        return_dist = {"n": 0}

    if len(pnls) > 1 and np.std(pnls, ddof=1) > 0:
        trade_sharpe = float(np.mean(pnls) / np.std(pnls, ddof=1) * math.sqrt(len(pnls)))
    else:
        trade_sharpe = None

    longest_loss_streak, longest_win_streak = _streaks(pnls)

    exit_reasons: Dict[str, int] = {}
    for t in trades:
        exit_reasons[t.exit_reason or "UNKNOWN"] = exit_reasons.get(t.exit_reason or "UNKNOWN", 0) + 1

    total_costs = float(sum(t.cost_paid or 0.0 for t in trades))
    gross_before_costs = float(sum(t.gross_pnl if t.gross_pnl is not None else 0.0 for t in trades))
    turnover = float(sum(t.size_lots for t in trades)) if trades else None
    exposure = _safe_div(float(result.bars_in_market), float(result.n_bars)) if result.n_bars else None

    return PerformanceMetrics(
        trade_count=len(trades),
        winning_trades=len(wins),
        losing_trades=len(losses),
        breakeven_trades=len(breakeven),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_profit=net_profit,
        profit_factor=profit_factor,
        win_rate=_safe_div(float(len(wins)), float(len(pnls))),
        expectancy=_safe_div(net_profit, float(len(pnls))),
        average_trade=_safe_div(net_profit, float(len(pnls))),
        average_win=_safe_div(gross_profit, float(len(wins))) if wins else None,
        average_loss=_safe_div(-gross_loss, float(len(losses))) if losses else None,
        largest_win=max(wins) if wins else None,
        largest_loss=min(losses) if losses else None,
        sharpe=sharpe,
        sortino=sortino,
        trade_sharpe=trade_sharpe,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_duration_bars=dd_duration,
        recovery_factor=_safe_div(net_profit, max_dd) if max_dd > 0 else None,
        longest_losing_streak=longest_loss_streak,
        longest_winning_streak=longest_win_streak,
        turnover=turnover,
        exposure=exposure,
        total_costs_paid=total_costs,
        gross_pnl_before_costs=gross_before_costs,
        return_distribution=return_dist,
        exit_reason_counts=exit_reasons,
        initial_equity=result.initial_equity,
        final_equity=result.final_equity,
        bars=result.n_bars,
    )
