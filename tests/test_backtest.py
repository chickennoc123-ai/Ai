"""Tests for the backtest engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.backtest import BacktestConfig, BacktestEngine, summarize_results
from core.strategy_registry import create_strategy
from core.utils import compute_metrics, get_instrument, position_pnl
from utils.exceptions import DataError


def test_backtest_returns_populated_result(ohlcv: pd.DataFrame, engine: BacktestEngine) -> None:
    """A backtest produces an equity curve aligned to the input."""
    result = engine.run(create_strategy("SMA_Cross", "EURUSD", "H1"), ohlcv)
    assert len(result.equity_curve) == len(ohlcv)
    assert result.equity_curve.index.equals(ohlcv.index)
    assert result.initial_capital == 10_000.0
    assert result.bars == len(ohlcv)


def test_equity_starts_at_initial_capital(ohlcv: pd.DataFrame, engine: BacktestEngine) -> None:
    """The curve starts at the configured capital."""
    result = engine.run(create_strategy("RSI", "EURUSD", "H1"), ohlcv)
    assert result.equity_curve.iloc[0] == pytest.approx(10_000.0)


def test_equity_never_goes_negative(gold_ohlcv: pd.DataFrame, engine: BacktestEngine) -> None:
    """The engine stops trading rather than reporting negative equity."""
    result = engine.run(create_strategy("Volatility_Breakout", "XAUUSD", "H1"), gold_ohlcv)
    assert (result.equity_curve >= 0).all()


def test_trades_are_internally_consistent(ohlcv: pd.DataFrame, engine: BacktestEngine) -> None:
    """Every trade closes after it opens and reports a coherent P&L."""
    result = engine.run(create_strategy("MACD", "EURUSD", "H1"), ohlcv)
    assert result.trades, "the strategy should trade on this data"
    spec = get_instrument("EURUSD")
    for trade in result.trades:
        assert trade.exit_time >= trade.entry_time
        assert trade.volume >= spec.min_lot
        assert trade.direction in (-1, 1)
        gross = position_pnl(spec, trade.direction, trade.entry_price, trade.exit_price, trade.volume)
        assert trade.gross_pnl == pytest.approx(gross, rel=1e-6)
        assert trade.pnl == pytest.approx(trade.gross_pnl - trade.commission, rel=1e-6)


def test_only_one_position_at_a_time(ohlcv: pd.DataFrame, engine: BacktestEngine) -> None:
    """Trades never overlap in time."""
    result = engine.run(create_strategy("Donchian", "EURUSD", "H1"), ohlcv)
    ordered = sorted(result.trades, key=lambda trade: trade.entry_time)
    for previous, current in zip(ordered, ordered[1:]):
        assert current.entry_time >= previous.exit_time


def test_stop_out_does_not_immediately_re_enter(ohlcv: pd.DataFrame, engine: BacktestEngine) -> None:
    """After a stop-out the engine waits for the signal to change."""
    result = engine.run(create_strategy("Keltner", "EURUSD", "H1"), ohlcv)
    ordered = sorted(result.trades, key=lambda trade: trade.entry_time)
    for previous, current in zip(ordered, ordered[1:]):
        if previous.exit_reason == "STOP_LOSS" and current.entry_time == previous.exit_time:
            assert current.direction != previous.direction


def test_higher_costs_reduce_profit(ohlcv: pd.DataFrame) -> None:
    """Doubling costs can only make the result worse."""
    strategy = create_strategy("MACD", "EURUSD", "H1")
    cheap = BacktestEngine(BacktestConfig(commission=0.00005, slippage=0.00001)).run(strategy, ohlcv)
    expensive = BacktestEngine(BacktestConfig(commission=0.0005, slippage=0.0002)).run(strategy, ohlcv)
    assert expensive.metrics.net_profit <= cheap.metrics.net_profit


def test_zero_signal_strategy_does_nothing(ohlcv: pd.DataFrame, engine: BacktestEngine) -> None:
    """A strategy that never trades leaves the equity flat."""
    strategy = create_strategy("RSI", "EURUSD", "H1")
    flat = pd.DataFrame(
        {"signal": 0, "confidence": 0.5, "sl": np.nan, "tp": np.nan}, index=ohlcv.index
    )
    result = engine.run(strategy, ohlcv, signals=flat)
    assert not result.trades
    assert result.equity_curve.nunique() == 1


def test_short_frame_is_rejected(engine: BacktestEngine, ohlcv: pd.DataFrame) -> None:
    """A frame with too few bars raises a clear error."""
    with pytest.raises(DataError):
        engine.run(create_strategy("RSI", "EURUSD", "H1"), ohlcv.head(20))


def test_empty_frame_is_rejected(engine: BacktestEngine) -> None:
    """An empty frame raises a clear error."""
    with pytest.raises(DataError):
        engine.run(create_strategy("RSI", "EURUSD", "H1"), pd.DataFrame())


def test_backtest_is_deterministic(ohlcv: pd.DataFrame, engine: BacktestEngine) -> None:
    """The same inputs always produce the same result."""
    strategy = create_strategy("SMA_Cross", "EURUSD", "H1")
    first = engine.run(strategy, ohlcv)
    second = engine.run(strategy, ohlcv)
    assert first.metrics.sharpe == pytest.approx(second.metrics.sharpe)
    assert len(first.trades) == len(second.trades)


def test_no_look_ahead_in_execution(ohlcv: pd.DataFrame, engine: BacktestEngine) -> None:
    """Truncating the future cannot change past trades."""
    strategy = create_strategy("SMA_Cross", "EURUSD", "H1")
    full = engine.run(strategy, ohlcv)
    truncated = engine.run(strategy, ohlcv.iloc[:-200])
    cutoff = ohlcv.index[-201]
    # The truncated run force-closes its open position on the last bar; that
    # flush is an artefact of the shorter window, not a difference in history.
    full_early = [trade for trade in full.trades if trade.exit_time <= cutoff]
    truncated_early = [
        trade
        for trade in truncated.trades
        if trade.exit_time <= cutoff and trade.exit_reason != "END_OF_DATA"
    ]
    assert len(full_early) == len(truncated_early)
    for left, right in zip(full_early, truncated_early):
        assert left.entry_price == pytest.approx(right.entry_price)
        assert left.pnl == pytest.approx(right.pnl)


def test_multi_symbol_backtest(engine: BacktestEngine, ohlcv: pd.DataFrame, gold_ohlcv: pd.DataFrame) -> None:
    """One strategy can be evaluated across several instruments."""
    results = engine.run_multi(
        create_strategy("RSI", "EURUSD", "H1"), {"EURUSD": ohlcv, "XAUUSD": gold_ohlcv}
    )
    assert set(results) == {"EURUSD", "XAUUSD"}
    assert results["XAUUSD"].symbol == "XAUUSD"


def test_portfolio_backtest_blends_curves(engine: BacktestEngine, ohlcv: pd.DataFrame, gold_ohlcv: pd.DataFrame) -> None:
    """A portfolio result aggregates its legs."""
    strategies = [
        create_strategy("RSI", "EURUSD", "H1"),
        create_strategy("MACD", "XAUUSD", "H1"),
    ]
    portfolio = engine.run_portfolio(strategies, {"EURUSD": ohlcv, "XAUUSD": gold_ohlcv})
    assert len(portfolio.legs) == 2
    assert not portfolio.equity_curve.empty
    assert sum(portfolio.weights.values()) == pytest.approx(1.0)


def test_result_serialisation(ohlcv: pd.DataFrame, engine: BacktestEngine) -> None:
    """Results serialise for the API, with and without the curve."""
    result = engine.run(create_strategy("RSI", "EURUSD", "H1"), ohlcv)
    compact = result.to_dict()
    assert "equity_curve" not in compact
    full = result.to_dict(include_curve=True)
    assert len(full["equity_curve"]["values"]) == len(ohlcv)
    assert full["trade_count"] == len(result.trades)


def test_summary_table(ohlcv: pd.DataFrame, engine: BacktestEngine) -> None:
    """The comparison helper returns one row per result."""
    results = [engine.run(create_strategy(name, "EURUSD", "H1"), ohlcv) for name in ("RSI", "MACD")]
    table = summarize_results(results)
    assert len(table) == 2
    assert {"strategy", "sharpe", "trades"}.issubset(table.columns)


def test_metrics_of_known_curve() -> None:
    """Metric maths is verified against a hand-built curve."""
    curve = [100.0, 110.0, 105.0, 120.0, 115.0]
    metrics = compute_metrics(curve, [10.0, -5.0, 15.0, -5.0], periods_per_year=252)
    assert metrics.total_return == pytest.approx(0.15)
    # Deepest trough is 105 against the 110 peak, not 115 against 120.
    assert metrics.max_drawdown == pytest.approx(5.0 / 110.0, rel=1e-6)
    assert metrics.win_rate == pytest.approx(0.5)
    assert metrics.profit_factor == pytest.approx(25.0 / 10.0)
    assert metrics.trades == 4
