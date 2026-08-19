"""Generation 5, Phase 5 tests — instrumented execution parity + trade
record integrity, and Phases 6-9 analyzers.

The load-bearing test here is ``test_parity_with_execute``: it proves
``instrumented_execution.execute_instrumented`` reproduces
``core.economic_validation.execution.execute``'s trades exactly (entry/
exit price and time, direction, size, exit_reason, holding_bars, pnl,
gross_pnl, cost_paid) on real STRAT-000002 data, so its ADDITIONAL
measurements (MFE, MAE, signal_value) can be trusted without re-opening
the question of whether the replay silently changed the economics.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from core.economic_validation.cost_stress import base_cost_model
from core.economic_validation.data_eligibility import load_raw_ohlcv
from core.economic_validation.evaluation import build_execution_frame
from core.economic_validation.execution import RiskRules, execute
from core.economic_validation.instrumented_execution import execute_instrumented
from core.economic_validation.rule_engine import generate_signals, parse_atr_multiple, parse_entry_rule
from core.factory.registry import StrategyRegistry


def _load_strat2_context():
    registry = StrategyRegistry()
    candidate = registry.get("STRAT-000002")
    full = load_raw_ohlcv(REPO_ROOT / "data" / "csv" / "EURUSD_H1.csv")
    rule = parse_entry_rule(candidate.spec.entry_rule, candidate.spec.direction)
    risk = RiskRules(
        risk_per_trade=0.02,
        stop_loss_atr_mult=parse_atr_multiple(candidate.spec.stop_loss),
        take_profit_atr_mult=parse_atr_multiple(candidate.spec.take_profit),
        max_holding_bars=int(candidate.spec.max_hold_bars),
    )
    costs = base_cost_model("EURUSD")
    exec_frame, features = build_execution_frame(full)
    signals = generate_signals(features, rule)
    return exec_frame, features, signals, risk, costs, candidate


def test_parity_with_execute():
    exec_frame, features, signals, risk, costs, candidate = _load_strat2_context()
    # Use a manageable slice (one year) so the test runs fast; parity is a
    # per-bar-loop property, not something that only holds at full scale.
    window = exec_frame.loc["2021-01-01":"2021-12-31"]
    sig_window = signals.loc[signals.index.isin(window.index)]

    baseline = execute(window, sig_window, costs=costs, risk=risk, initial_equity=10_000.0)
    instrumented = execute_instrumented(
        window, sig_window, costs=costs, risk=risk, candidate_id="STRAT-000002", instrument="EURUSD",
        signal_feature_series=features["rsi_14"], signal_feature_name="rsi_14", rule_version="RULE-R4-001",
        initial_equity=10_000.0,
    )

    assert len(baseline.trades) == len(instrumented)
    assert len(baseline.trades) > 0, "test window must actually contain trades"
    for b, i in zip(baseline.trades, instrumented):
        assert str(b.entry_time) == i.entry_time
        assert b.entry_price == pytest.approx(i.entry_price, rel=1e-12)
        assert b.direction == i.direction
        assert b.size_lots == pytest.approx(i.size_lots, rel=1e-12)
        assert str(b.exit_time) == i.exit_time
        assert b.exit_price == pytest.approx(i.exit_price, rel=1e-12)
        assert b.exit_reason == i.exit_reason
        assert b.holding_bars == i.holding_period_bars
        assert b.pnl == pytest.approx(i.net_pnl, rel=1e-9)
        assert b.gross_pnl == pytest.approx(i.gross_pnl, rel=1e-9)
        assert b.cost_paid == pytest.approx(i.cost_paid, rel=1e-9)


def test_mfe_mae_are_non_negative_and_mfe_at_least_covers_the_exit_for_winners():
    exec_frame, features, signals, risk, costs, candidate = _load_strat2_context()
    window = exec_frame.loc["2021-01-01":"2021-12-31"]
    sig_window = signals.loc[signals.index.isin(window.index)]
    trades = execute_instrumented(
        window, sig_window, costs=costs, risk=risk, candidate_id="STRAT-000002", instrument="EURUSD",
        signal_feature_series=features["rsi_14"], signal_feature_name="rsi_14", rule_version="RULE-R4-001",
        initial_equity=10_000.0,
    )
    assert trades
    for t in trades:
        assert t.mfe_price >= 0.0
        assert t.mae_price >= 0.0
        if t.exit_reason == "TAKE_PROFIT":
            # the path must have reached at least the take-profit distance
            assert t.mfe_price >= abs(t.take_profit_price - t.entry_price) - 1e-9


def test_trade_id_is_unique_and_stable_within_a_replay():
    exec_frame, features, signals, risk, costs, candidate = _load_strat2_context()
    window = exec_frame.loc["2021-01-01":"2021-06-30"]
    sig_window = signals.loc[signals.index.isin(window.index)]
    trades = execute_instrumented(
        window, sig_window, costs=costs, risk=risk, candidate_id="STRAT-000002", instrument="EURUSD",
        signal_feature_series=features["rsi_14"], signal_feature_name="rsi_14", rule_version="RULE-R4-001",
        initial_equity=10_000.0,
    )
    ids = [t.trade_id for t in trades]
    assert len(ids) == len(set(ids))
    assert all(tid.startswith("STRAT-000002-TRADE-") for tid in ids)
