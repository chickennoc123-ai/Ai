"""Generation 4 execution-engine parity and integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.economic_validation.execution import CostModel, RiskRules, execute
from core.economic_validation.metrics import compute_metrics
from core.economic_validation.rule_engine import CrossoverRule, generate_signals
from core.ml_r2.backtest_r2 import BacktestConfig, run_backtest

REPO_ROOT = Path(__file__).resolve().parents[1]
G4 = REPO_ROOT / "reports" / "generation4"


def _fixture(n: int = 2000, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 1.10 * np.exp(np.cumsum(rng.normal(0.0, 0.0005, size=n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.0004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.0004, n)))
    idx = pd.date_range("2016-01-04 05:00", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "atr_14": 0.0012}, index=idx)


def test_exec_r4_001_matches_backtest_r2_under_matched_settings():
    """EXEC-R4-001 must reproduce the audited BACKTEST-R2-001 mechanics exactly.

    Matched settings: no spread, no exit slippage, same entry slippage,
    same commission, same SL/TP/max-hold geometry. Any difference here
    would mean Generation 4's cost extension silently changed the timing
    or priority semantics rather than only adding cost legs.
    """
    frame = _fixture()
    rng = np.random.default_rng(3)
    signal_positions = sorted(rng.choice(np.arange(50, len(frame) - 50), size=60, replace=False))
    signals = pd.Series(0, index=frame.index, dtype="int64")
    signals.iloc[signal_positions] = 1

    config = BacktestConfig(long_threshold=0.55, short_threshold=0.45, risk_per_trade=0.02,
                            stop_loss_atr_mult=1.5, take_profit_atr_mult=2.0, max_holding_bars=12,
                            pip_size=0.0001, pip_value_per_lot=10.0,
                            commission_per_lot_round_turn=7.0, slippage_price=0.00002)
    probabilities = pd.Series(np.where(signals.to_numpy() == 1, 1.0, 0.5), index=frame.index)
    reference = run_backtest(frame, probabilities, config, initial_equity=10_000.0)

    costs = CostModel(spread_price=0.0, slippage_price=0.00002,
                      commission_per_lot_round_turn=7.0, pip_size=0.0001,
                      pip_value_per_lot=10.0, apply_exit_slippage=False, label="PARITY")
    risk = RiskRules(risk_per_trade=0.02, stop_loss_atr_mult=1.5,
                     take_profit_atr_mult=2.0, max_holding_bars=12)
    result = execute(frame, signals, costs=costs, risk=risk, initial_equity=10_000.0)

    assert len(result.trades) == len(reference.trades)
    for mine, theirs in zip(result.trades, reference.trades):
        assert mine.entry_time == theirs.entry_time
        assert mine.exit_time == theirs.exit_time
        assert mine.exit_reason == theirs.exit_reason
        assert mine.entry_price == pytest.approx(theirs.entry_price, rel=1e-12)
        assert mine.exit_price == pytest.approx(theirs.exit_price, rel=1e-12)
        assert mine.size_lots == pytest.approx(theirs.size_lots, rel=1e-12)
        assert mine.pnl == pytest.approx(theirs.pnl, rel=1e-9)
    assert result.final_equity == pytest.approx(reference.final_equity, rel=1e-9)


def test_costs_are_charged_on_both_legs():
    """The Generation 4 extension must actually charge what it claims to."""
    frame = _fixture()
    signals = pd.Series(0, index=frame.index, dtype="int64")
    signals.iloc[200] = 1

    free = CostModel(spread_price=0.0, slippage_price=0.0, commission_per_lot_round_turn=0.0,
                     pip_size=0.0001, pip_value_per_lot=10.0, apply_exit_slippage=False, label="FREE")
    risk = RiskRules(0.02, 1.5, 2.0, 12)
    baseline = execute(frame, signals, costs=free, risk=risk)

    with_spread = CostModel(spread_price=0.00016, slippage_price=0.0,
                            commission_per_lot_round_turn=0.0, pip_size=0.0001,
                            pip_value_per_lot=10.0, apply_exit_slippage=False, label="SPREAD")
    spread_run = execute(frame, signals, costs=with_spread, risk=risk)
    assert spread_run.trades[0].entry_price > baseline.trades[0].entry_price

    with_exit_slip = CostModel(spread_price=0.0, slippage_price=0.00002,
                               commission_per_lot_round_turn=0.0, pip_size=0.0001,
                               pip_value_per_lot=10.0, apply_exit_slippage=True, label="SLIP")
    slip_run = execute(frame, signals, costs=with_exit_slip, risk=risk)
    assert slip_run.trades[0].exit_price < baseline.trades[0].exit_price

    commission = CostModel(spread_price=0.0, slippage_price=0.0,
                           commission_per_lot_round_turn=7.0, pip_size=0.0001,
                           pip_value_per_lot=10.0, apply_exit_slippage=False, label="COMM")
    comm_run = execute(frame, signals, costs=commission, risk=risk)
    assert comm_run.trades[0].pnl < baseline.trades[0].pnl


def test_signal_generation_is_a_strict_crossover():
    """A bar already above the threshold must not re-fire the signal."""
    idx = pd.date_range("2020-01-01", periods=6, freq="h", tz="UTC")
    features = pd.DataFrame({"rsi_14": [np.nan, 25.0, 28.0, 31.0, 33.0, 29.0]}, index=idx)
    rule = CrossoverRule(feature="rsi_14", threshold=30.0, crossing_direction="up", direction=1)
    signals = generate_signals(features, rule)
    assert list(signals) == [0, 0, 0, 1, 0, 0]


def test_metrics_report_none_not_zero_when_there_are_no_trades():
    frame = _fixture()
    result = execute(frame, pd.Series(0, index=frame.index, dtype="int64"),
                     costs=CostModel(0.0, 0.0, 0.0, 0.0001, 10.0, False, "NONE"),
                     risk=RiskRules(0.02, 1.5, 2.0, 12))
    metrics = compute_metrics(result)
    assert metrics.trade_count == 0
    for field in ("profit_factor", "win_rate", "expectancy", "average_trade", "largest_win"):
        assert getattr(metrics, field) is None, field
