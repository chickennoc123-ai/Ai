"""Tests for the lifecycle manager and the decision engine."""

from __future__ import annotations

from datetime import timedelta

import pytest

from core.decision import DecisionEngine
from core.lifecycle import LifecycleManager, LifecycleState
from core.utils import PerformanceMetrics, get_instrument, lots_for_risk, required_margin
from utils.config import get_config
from utils.helpers import utcnow


def _metrics(sharpe: float, trades: int = 50, drawdown: float = 0.05, win_rate: float = 0.5) -> PerformanceMetrics:
    """Build a metric bundle for lifecycle tests."""
    metrics = PerformanceMetrics()
    metrics.sharpe = sharpe
    metrics.trades = trades
    metrics.max_drawdown = drawdown
    metrics.win_rate = win_rate
    metrics.payoff_ratio = 1.5
    return metrics


@pytest.fixture
def lifecycle() -> LifecycleManager:
    """Return a lifecycle manager with no dwell-time delay."""
    manager = LifecycleManager(get_config())
    manager.min_dwell_days = 0.0
    return manager


# -- lifecycle ---------------------------------------------------------------
def test_new_strategy_starts_active(lifecycle: LifecycleManager) -> None:
    """A registered strategy begins in the ACTIVE state."""
    record = lifecycle.register("s1")
    assert record.state is LifecycleState.ACTIVE
    assert lifecycle.allocation_multiplier("s1") == 1.0


def test_active_degrades_on_weak_sharpe(lifecycle: LifecycleManager) -> None:
    """Sharpe below the degrade threshold moves ACTIVE to DEGRADED."""
    lifecycle.register("s1")
    assert lifecycle.update_state("s1", _metrics(0.2)) is LifecycleState.DEGRADED
    assert lifecycle.allocation_multiplier("s1") == 0.4


def test_active_pauses_on_negative_sharpe(lifecycle: LifecycleManager) -> None:
    """A negative Sharpe pauses the strategy outright."""
    lifecycle.register("s1")
    assert lifecycle.update_state("s1", _metrics(-0.5)) is LifecycleState.PAUSED
    assert lifecycle.allocation_multiplier("s1") == 0.0
    assert not lifecycle.get("s1").state.tradable


def test_degraded_recovers_after_two_good_evaluations(lifecycle: LifecycleManager) -> None:
    """Recovery requires sustained performance, not a single good reading."""
    lifecycle.register("s1")
    lifecycle.update_state("s1", _metrics(0.2))
    assert lifecycle.get("s1").state is LifecycleState.DEGRADED
    assert lifecycle.update_state("s1", _metrics(1.2)) is LifecycleState.DEGRADED  # first good reading
    assert lifecycle.update_state("s1", _metrics(1.2)) is LifecycleState.ACTIVE


def test_paused_retires_after_the_grace_period(lifecycle: LifecycleManager) -> None:
    """A paused strategy retires once the grace period elapses."""
    lifecycle.register("s1")
    lifecycle.update_state("s1", _metrics(-1.0))
    record = lifecycle.get("s1")
    assert record.state is LifecycleState.PAUSED
    record.since = utcnow() - timedelta(days=lifecycle.retire_after_days + 1)
    assert lifecycle.update_state("s1", _metrics(-0.2)) is LifecycleState.RETIRED


def test_retired_is_terminal(lifecycle: LifecycleManager) -> None:
    """A retired strategy never comes back on its own."""
    lifecycle.register("s1")
    lifecycle.retire("s1")
    assert lifecycle.update_state("s1", _metrics(3.0)) is LifecycleState.RETIRED
    assert lifecycle.resume("s1") is LifecycleState.RETIRED


def test_severe_drawdown_pauses_immediately(lifecycle: LifecycleManager) -> None:
    """A 50% drawdown pauses regardless of the Sharpe ratio."""
    lifecycle.register("s1")
    assert lifecycle.update_state("s1", _metrics(2.0, drawdown=0.6)) is LifecycleState.PAUSED


def test_small_sample_does_not_trigger_a_transition(lifecycle: LifecycleManager) -> None:
    """Too few trades is not evidence, so the state is left alone."""
    lifecycle.register("s1")
    assert lifecycle.update_state("s1", _metrics(-2.0, trades=3)) is LifecycleState.ACTIVE


def test_dwell_time_prevents_flapping() -> None:
    """A minimum dwell time stops oscillation on noisy metrics."""
    manager = LifecycleManager(get_config())
    manager.min_dwell_days = 5.0
    manager.register("s1")
    assert manager.update_state("s1", _metrics(-1.0)) is LifecycleState.ACTIVE


def test_transitions_are_recorded(lifecycle: LifecycleManager) -> None:
    """Every transition is logged with a reason."""
    lifecycle.register("s1")
    lifecycle.update_state("s1", _metrics(0.1))
    status = lifecycle.get_strategy_status("s1")
    assert status["state"] == "DEGRADED"
    assert status["reason"]
    assert status["history"][-1]["from_state"] == "ACTIVE"


def test_snapshot_counts_states(lifecycle: LifecycleManager) -> None:
    """The snapshot summarises the whole population."""
    lifecycle.register("a")
    lifecycle.register("b")
    lifecycle.update_state("b", _metrics(-1.0))
    snapshot = lifecycle.snapshot()
    assert snapshot["total"] == 2
    assert snapshot["counts"]["ACTIVE"] == 1
    assert snapshot["counts"]["PAUSED"] == 1
    assert lifecycle.tradable_strategies() == ["a"]


# -- Kelly and allocation ----------------------------------------------------
def test_kelly_of_a_known_edge() -> None:
    """Kelly matches the closed-form result for a known edge."""
    # 60% win rate at 2:1 payoff -> 0.6 - 0.4/2 = 0.40
    assert DecisionEngine.kelly_criterion(0.6, 2.0) == pytest.approx(0.40)


def test_kelly_is_zero_without_an_edge() -> None:
    """A negative expectancy produces no stake."""
    assert DecisionEngine.kelly_criterion(0.3, 1.0) == 0.0
    assert DecisionEngine.kelly_criterion(0.5, 0.0) == 0.0


def test_uncertainty_haircut_grows_with_evidence() -> None:
    """More trades and a lower PBO increase the granted fraction."""
    engine = DecisionEngine(get_config())
    weak = engine.uncertainty_haircut(trades=8, pbo=0.6, wfa_efficiency=0.1, validation_score=0.2)
    strong = engine.uncertainty_haircut(trades=200, pbo=0.1, wfa_efficiency=0.8, validation_score=0.9)
    assert 0.0 <= weak < strong <= 1.0


def test_allocation_is_capped(lifecycle: LifecycleManager) -> None:
    """No single strategy exceeds the configured maximum allocation."""
    engine = DecisionEngine(get_config(), lifecycle)
    metrics = _metrics(3.0, trades=500, win_rate=0.8)
    metrics.payoff_ratio = 4.0
    decision = engine.calculate_allocation(
        "s1", "RSI", "EURUSD", metrics,
        {"score": 1.0, "pbo": {"pbo": 0.0, "computed": True}, "walk_forward": {"efficiency": 1.0}},
        10_000.0,
    )
    assert decision.allocation <= engine.max_allocation
    assert decision.capital == pytest.approx(decision.allocation * 10_000.0)


def test_no_allocation_without_an_edge(lifecycle: LifecycleManager) -> None:
    """A losing strategy receives no capital."""
    engine = DecisionEngine(get_config(), lifecycle)
    metrics = _metrics(-1.0, win_rate=0.2)
    metrics.payoff_ratio = 0.5
    decision = engine.calculate_allocation("s1", "RSI", "EURUSD", metrics, None, 10_000.0)
    assert decision.allocation == 0.0
    assert "No positive Kelly edge" in decision.reasons


def test_uncomputed_pbo_is_treated_as_unknown(lifecycle: LifecycleManager) -> None:
    """A skipped PBO test must not be read as certain overfitting."""
    engine = DecisionEngine(get_config(), lifecycle)
    metrics = _metrics(1.5, trades=200, win_rate=0.6)
    metrics.payoff_ratio = 2.0
    skipped = engine.calculate_allocation(
        "s1", "RSI", "EURUSD", metrics,
        {"score": 0.8, "pbo": {"pbo": 1.0, "computed": False}, "walk_forward": {"efficiency": 0.7}},
        10_000.0,
    )
    measured = engine.calculate_allocation(
        "s2", "RSI", "EURUSD", metrics,
        {"score": 0.8, "pbo": {"pbo": 1.0, "computed": True}, "walk_forward": {"efficiency": 0.7}},
        10_000.0,
    )
    assert skipped.allocation > measured.allocation


def test_lifecycle_state_scales_the_allocation(lifecycle: LifecycleManager) -> None:
    """A degraded strategy receives a fraction of its nominal allocation."""
    engine = DecisionEngine(get_config(), lifecycle)
    metrics = _metrics(2.0, trades=300, win_rate=0.65)
    metrics.payoff_ratio = 2.0
    validation = {"score": 0.9, "pbo": {"pbo": 0.1, "computed": True}, "walk_forward": {"efficiency": 0.8}}

    lifecycle.register("active")
    active = engine.calculate_allocation("active", "RSI", "EURUSD", metrics, validation, 10_000.0)
    lifecycle.register("weak")
    lifecycle.update_state("weak", _metrics(0.2))
    degraded = engine.calculate_allocation("weak", "RSI", "EURUSD", metrics, validation, 10_000.0)
    assert degraded.allocation < active.allocation


def test_portfolio_allocation_respects_the_global_cap(lifecycle: LifecycleManager) -> None:
    """Gross allocation never exceeds the configured total."""
    engine = DecisionEngine(get_config(), lifecycle)
    metrics = _metrics(2.5, trades=400, win_rate=0.7)
    metrics.payoff_ratio = 3.0
    validation = {"score": 0.95, "pbo": {"pbo": 0.05, "computed": True}, "walk_forward": {"efficiency": 0.9}}
    candidates = [
        {
            "strategy_id": f"s{index}",
            "strategy_name": "RSI",
            "symbol": "EURUSD",
            "metrics": metrics,
            "validation": validation,
        }
        for index in range(12)
    ]
    decisions = engine.allocate_portfolio(candidates, 10_000.0)
    assert sum(item.allocation for item in decisions) <= engine.max_total + 1e-9


def test_correlated_strategies_are_penalised(lifecycle: LifecycleManager) -> None:
    """Two strategies with identical returns share one risk budget."""
    engine = DecisionEngine(get_config(), lifecycle)
    metrics = _metrics(2.0, trades=300, win_rate=0.65)
    metrics.payoff_ratio = 2.0
    validation = {"score": 0.9, "pbo": {"pbo": 0.1, "computed": True}, "walk_forward": {"efficiency": 0.8}}
    series = [0.01, -0.005, 0.02, -0.01, 0.015] * 10
    candidates = [
        {"strategy_id": "a", "strategy_name": "RSI", "symbol": "EURUSD", "metrics": metrics, "validation": validation},
        {"strategy_id": "b", "strategy_name": "RSI", "symbol": "GBPUSD", "metrics": metrics, "validation": validation},
    ]
    decisions = engine.allocate_portfolio(candidates, 10_000.0, {"a": series, "b": series})
    assert all(item.correlation_penalty < 1.0 for item in decisions)


# -- position sizing ---------------------------------------------------------
def test_position_sizing_matches_the_risk_budget() -> None:
    """Stopping out costs approximately the intended risk amount."""
    engine = DecisionEngine(get_config())
    sizing = engine.get_position_sizing("XAUUSD", 10_000.0, 2035.0, 2025.0, risk_per_trade=0.01, equity=10_000.0)
    # 10 USD of stop distance x 100 oz x volume should be close to 100 USD.
    assert sizing.volume == pytest.approx(0.10, abs=0.01)
    assert sizing.risk_amount == pytest.approx(100.0)


def test_position_sizing_scales_with_the_stop_distance() -> None:
    """A wider stop produces a smaller position."""
    engine = DecisionEngine(get_config())
    tight = engine.get_position_sizing("EURUSD", 10_000.0, 1.0875, 1.0865)
    wide = engine.get_position_sizing("EURUSD", 10_000.0, 1.0875, 1.0775)
    assert tight.volume > wide.volume


def test_position_sizing_respects_the_margin_budget() -> None:
    """Sizing is reduced when the margin requirement is too large."""
    engine = DecisionEngine(get_config())
    sizing = engine.get_position_sizing("XAUUSD", 1_000_000.0, 2035.0, 2034.9, equity=500.0)
    assert sizing.capped_by in ("margin", "max_lot")
    assert sizing.volume <= get_instrument("XAUUSD").max_lot


def test_lots_for_risk_handles_degenerate_input() -> None:
    """A zero stop distance cannot produce a position."""
    spec = get_instrument("EURUSD")
    assert lots_for_risk(spec, 10_000.0, 0.01, 0.0, 1.0875) == 0.0
    assert lots_for_risk(spec, 0.0, 0.01, 0.001, 1.0875) == 0.0


def test_required_margin_is_leverage_scaled() -> None:
    """Margin falls linearly with leverage."""
    spec = get_instrument("EURUSD")
    assert required_margin(spec, 1.0875, 1.0, 100) == pytest.approx(
        required_margin(spec, 1.0875, 1.0, 500) * 5
    )


def test_risk_parity_weights_sum_to_one() -> None:
    """Inverse-volatility weights form a valid allocation."""
    weights = DecisionEngine.risk_parity_weights(
        {"a": [0.01, -0.01, 0.02, -0.02], "b": [0.001, -0.001, 0.002, -0.002]}
    )
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["b"] > weights["a"]  # the calmer series gets more capital
