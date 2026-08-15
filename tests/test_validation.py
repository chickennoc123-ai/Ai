"""Tests for the validation suite."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.backtest import BacktestConfig, BacktestEngine
from core.strategy_registry import create_strategy
from core.utils import deflated_sharpe_ratio, sharpe_ratio, value_at_risk
from core.validation import (
    CalibrationChecker,
    PBOAnalyzer,
    RobustnessTester,
    ValidationSuite,
    WalkForwardAnalyzer,
    sample_parameters,
)


@pytest.fixture(scope="module")
def module_engine() -> BacktestEngine:
    """Return a shared engine for the (slow) validation tests."""
    return BacktestEngine(BacktestConfig(commission=0.00007, slippage=0.00002))


def test_sample_parameters_respects_the_space() -> None:
    """Sampled parameters always sit inside the declared bounds."""
    strategy = create_strategy("RSI", "EURUSD", "H1")
    samples = sample_parameters(strategy, 8, np.random.default_rng(0))
    assert 1 <= len(samples) <= 8
    for spec in strategy.param_space:
        for candidate in samples:
            assert spec.low <= candidate[spec.name] <= spec.high


def test_sample_parameters_handles_list_valued_params() -> None:
    """Strategies with list parameters can still be sampled."""
    strategy = create_strategy("Ensemble", "EURUSD", "H1")
    samples = sample_parameters(strategy, 4, np.random.default_rng(0))
    assert samples
    assert all(isinstance(candidate["members"], list) for candidate in samples)


def test_walk_forward_produces_folds(ohlcv: pd.DataFrame, module_engine: BacktestEngine) -> None:
    """Walk-forward analysis yields folds with train and test windows."""
    analyzer = WalkForwardAnalyzer(module_engine, train_bars=1200, test_bars=300, candidates=4)
    report = analyzer.run(create_strategy("SMA_Cross", "EURUSD", "H1"), ohlcv)
    assert report.folds
    for fold in report.folds:
        assert fold.train_start < fold.train_end <= fold.test_start < fold.test_end
    assert 0.0 <= report.consistency <= 1.0


def test_walk_forward_handles_short_history(short_ohlcv: pd.DataFrame, module_engine: BacktestEngine) -> None:
    """A short history shrinks the windows instead of crashing."""
    analyzer = WalkForwardAnalyzer(module_engine, train_bars=5000, test_bars=1000, candidates=3)
    report = analyzer.run(create_strategy("RSI", "EURUSD", "H1"), short_ohlcv)
    assert isinstance(report.efficiency, float)


@pytest.mark.slow
def test_pbo_is_a_probability(ohlcv: pd.DataFrame, module_engine: BacktestEngine) -> None:
    """PBO is a probability and reports that it was computed."""
    report = PBOAnalyzer(module_engine, partitions=6, configurations=8).run(
        create_strategy("RSI", "EURUSD", "H1"), ohlcv
    )
    assert report.computed
    assert 0.0 <= report.pbo <= 1.0
    assert report.combinations == 20  # C(6, 3)
    assert report.configurations >= 4


def test_pbo_defaults_to_not_computed() -> None:
    """An unrun PBO report is flagged, so consumers do not read 1.0 as data."""
    from core.validation import PBOReport

    report = PBOReport()
    assert report.pbo == 1.0
    assert report.computed is False


def test_calibration_report(ohlcv: pd.DataFrame, module_engine: BacktestEngine) -> None:
    """Calibration compares stated confidence with realised hit rate."""
    result = module_engine.run(create_strategy("MACD", "EURUSD", "H1"), ohlcv)
    report = CalibrationChecker(bins=5).run(result)
    if result.metrics.trades >= 10:
        assert report.samples == result.metrics.trades
        assert 0.0 <= report.expected_calibration_error <= 1.0
        assert 0.0 <= report.brier_score <= 1.0
        assert report.bins


def test_calibration_needs_enough_trades() -> None:
    """Fewer than ten trades produces an empty report."""
    from core.backtest import BacktestResult
    from core.utils import PerformanceMetrics

    empty = BacktestResult(
        strategy_name="x",
        strategy_id="x",
        symbol="EURUSD",
        timeframe="H1",
        equity_curve=pd.Series(dtype="float64"),
        trades=[],
        metrics=PerformanceMetrics(),
    )
    assert CalibrationChecker().run(empty).samples == 0


@pytest.mark.slow
def test_robustness_report(ohlcv: pd.DataFrame, module_engine: BacktestEngine) -> None:
    """Robustness testing reports stability, cost sensitivity and regimes."""
    strategy = create_strategy("SMA_Cross", "EURUSD", "H1")
    baseline = module_engine.run(strategy, ohlcv)
    report = RobustnessTester(module_engine, perturbations=5, magnitude=0.2).run(strategy, ohlcv, baseline)
    assert 0.0 <= report.parameter_stability <= 1.0
    assert isinstance(report.survives_double_costs, bool)
    assert report.regime_sharpes


@pytest.mark.slow
@pytest.mark.integration
def test_full_validation_report(ohlcv: pd.DataFrame) -> None:
    """The suite produces a complete, serialisable verdict."""
    report = ValidationSuite().run(create_strategy("RSI", "EURUSD", "H1"), ohlcv)
    assert isinstance(report.passed, bool)
    assert 0.0 <= report.score <= 1.0
    assert report.pbo.computed
    payload = report.to_dict()
    for key in ("baseline", "walk_forward", "pbo", "calibration", "robustness", "reasons"):
        assert key in payload
    if not report.passed:
        assert report.reasons, "a failed verdict must explain itself"


def test_quick_validation_skips_expensive_tests(short_ohlcv: pd.DataFrame) -> None:
    """Quick mode skips PBO and robustness but still runs walk-forward."""
    report = ValidationSuite().run(create_strategy("RSI", "EURUSD", "H1"), short_ohlcv, quick=True)
    assert not report.pbo.computed
    assert report.pbo.combinations == 0
    assert isinstance(report.score, float)


def test_validation_rejects_a_no_trade_strategy(short_ohlcv: pd.DataFrame) -> None:
    """A strategy with too few trades cannot pass the gate."""
    report = ValidationSuite().run(create_strategy("Ichimoku", "EURUSD", "H1"), short_ohlcv, quick=True)
    if report.baseline["metrics"]["trades"] < 30:
        assert not report.passed
        assert any("trades" in reason.lower() for reason in report.reasons)


def test_deflated_sharpe_penalises_many_trials() -> None:
    """More trials make the same Sharpe less convincing."""
    few = deflated_sharpe_ratio(1.5, trials=2, observations=1000)
    many = deflated_sharpe_ratio(1.5, trials=500, observations=1000)
    assert 0.0 <= many <= few <= 1.0


def test_sharpe_of_constant_returns_is_zero() -> None:
    """A zero-variance series has no Sharpe ratio."""
    assert sharpe_ratio(pd.Series([0.01] * 50)) == 0.0


def test_value_at_risk_is_positive_for_losses() -> None:
    """VaR is reported as a positive magnitude."""
    returns = pd.Series(np.random.default_rng(3).normal(0, 0.01, 500))
    assert value_at_risk(returns, 0.99) > 0
