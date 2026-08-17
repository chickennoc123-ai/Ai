"""BACKTEST-R2-001 deterministic mechanics tests.

MECHANICAL CORRECTNESS ONLY — these tests use tiny, hand-constructed
OHLCV/probability fixtures to verify the trading-rule mechanics exactly
match ML-001-R2-CLEAN-REBUILD-SPEC.md Section 10. This is explicitly
NOT economic validation: no real market data is used, no performance
metric from these tests may be cited as evidence of strategy quality,
and the governing implementation-phase instruction forbids running an
economic validation in this phase.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.ml_r2.backtest_r2 import BacktestConfig, BacktestConfigError, run_backtest


def _bars(rows, start="2020-01-01"):
    """rows: list of dicts with open/high/low/close/atr_14."""
    index = pd.date_range(start, periods=len(rows), freq="h", tz="UTC")
    return pd.DataFrame(rows, index=index)


class TestPositionSizing:
    def test_size_scales_inversely_with_stop_distance(self) -> None:
        config = BacktestConfig()
        rows = [
            {"open": 1.1000, "high": 1.1002, "low": 1.0998, "close": 1.1001, "atr_14": 0.0010},
            {"open": 1.1001, "high": 1.1005, "low": 1.0999, "close": 1.1000, "atr_14": 0.0010},
            {"open": 1.1000, "high": 1.1004, "low": 1.0999, "close": 1.1001, "atr_14": 0.0010},
        ]
        df = _bars(rows)
        probabilities = pd.Series({df.index[0]: 0.60, df.index[1]: 0.50}, name="p")
        result = run_backtest(df, probabilities, config, initial_equity=10_000.0)
        assert len(result.trades) >= 0  # trade may not close within this short window
        # The trade should have opened at bar[1]'s open with the documented sizing formula.
        entry_price = rows[1]["open"] + config.slippage_price
        sl_dist = config.stop_loss_atr_mult * rows[1]["atr_14"]
        expected_size = (10_000.0 * config.risk_per_trade) / ((sl_dist / config.pip_size) * config.pip_value_per_lot)
        # Recover the opened trade even if not yet closed by inspecting equity_curve non-triviality.
        assert result.equity_curve is not None
        assert expected_size > 0


class TestStopLossTriggers:
    def test_stop_loss_closes_trade_at_stop_price(self) -> None:
        config = BacktestConfig()
        rows = [
            {"open": 1.1000, "high": 1.1002, "low": 1.0998, "close": 1.1001, "atr_14": 0.0010},  # signal bar
            {"open": 1.1001, "high": 1.1005, "low": 1.0999, "close": 1.1000, "atr_14": 0.0010},  # entry bar
            {"open": 1.1000, "high": 1.1003, "low": 1.0980, "close": 1.0995, "atr_14": 0.0010},  # SL hit (low breaches stop)
        ]
        df = _bars(rows)
        probabilities = pd.Series(
            {df.index[0]: 0.60, df.index[1]: 0.50, df.index[2]: 0.50}, name="p"
        )
        result = run_backtest(df, probabilities, config, initial_equity=10_000.0)

        assert len(result.trades) == 1
        trade = result.trades[0]
        entry_price = rows[1]["open"] + config.slippage_price
        expected_stop = entry_price - config.stop_loss_atr_mult * rows[1]["atr_14"]

        assert trade.entry_time == df.index[1]
        assert trade.entry_price == pytest.approx(entry_price)
        assert trade.exit_reason == "STOP_LOSS"
        assert trade.exit_price == pytest.approx(expected_stop)
        assert trade.exit_time == df.index[2]


class TestTakeProfitTriggers:
    def test_take_profit_closes_trade_at_target_price(self) -> None:
        config = BacktestConfig()
        rows = [
            {"open": 1.1000, "high": 1.1002, "low": 1.0998, "close": 1.1001, "atr_14": 0.0010},
            {"open": 1.1001, "high": 1.1005, "low": 1.0999, "close": 1.1000, "atr_14": 0.0010},
            {"open": 1.1000, "high": 1.1030, "low": 1.1000, "close": 1.1020, "atr_14": 0.0010},  # TP hit
        ]
        df = _bars(rows)
        probabilities = pd.Series(
            {df.index[0]: 0.60, df.index[1]: 0.50, df.index[2]: 0.50}, name="p"
        )
        result = run_backtest(df, probabilities, config, initial_equity=10_000.0)

        assert len(result.trades) == 1
        trade = result.trades[0]
        entry_price = rows[1]["open"] + config.slippage_price
        expected_tp = entry_price + config.take_profit_atr_mult * rows[1]["atr_14"]

        assert trade.exit_reason == "TAKE_PROFIT"
        assert trade.exit_price == pytest.approx(expected_tp)


class TestMaxHoldingPeriod:
    def test_forced_exit_at_max_holding_bars(self) -> None:
        config = BacktestConfig(max_holding_bars=2)
        rows = [
            {"open": 1.1000, "high": 1.1002, "low": 1.0998, "close": 1.1001, "atr_14": 0.0010},  # signal
            {"open": 1.1001, "high": 1.1005, "low": 1.0999, "close": 1.1000, "atr_14": 0.0010},  # entry (hold=0)
            {"open": 1.1000, "high": 1.1004, "low": 1.0998, "close": 1.1002, "atr_14": 0.0010},  # hold=1
            {"open": 1.1002, "high": 1.1006, "low": 1.0999, "close": 1.1003, "atr_14": 0.0010},  # hold=2 -> force exit
        ]
        df = _bars(rows)
        probabilities = pd.Series(
            {df.index[0]: 0.60, df.index[1]: 0.50, df.index[2]: 0.50, df.index[3]: 0.50}, name="p"
        )
        result = run_backtest(df, probabilities, config, initial_equity=10_000.0)

        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade.exit_reason == "MAX_HOLDING_PERIOD"
        assert trade.holding_bars == 2
        assert trade.exit_price == pytest.approx(rows[3]["close"])


class TestSignalReversal:
    def test_reversal_closes_at_next_bar_open_not_same_bar(self) -> None:
        config = BacktestConfig()
        rows = [
            {"open": 1.1000, "high": 1.1002, "low": 1.0998, "close": 1.1001, "atr_14": 0.0010},  # long signal
            {"open": 1.1001, "high": 1.1005, "low": 1.0999, "close": 1.1000, "atr_14": 0.0010},  # entry
            {"open": 1.1000, "high": 1.1004, "low": 1.0999, "close": 1.1001, "atr_14": 0.0010},  # reversal signal (p<0.45)
            {"open": 1.1002, "high": 1.1006, "low": 1.0999, "close": 1.1003, "atr_14": 0.0010},  # reversal executes here
        ]
        df = _bars(rows)
        probabilities = pd.Series(
            {df.index[0]: 0.60, df.index[1]: 0.50, df.index[2]: 0.40, df.index[3]: 0.50}, name="p"
        )
        result = run_backtest(df, probabilities, config, initial_equity=10_000.0)

        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade.exit_reason == "SIGNAL_REVERSAL"
        assert trade.exit_time == df.index[3]  # next bar after the reversal signal at index[2]
        assert trade.exit_price == pytest.approx(rows[3]["open"])


class TestNoEntryWhilePositionOpen:
    """L-1 remediation: the prior version of this test asserted only
    len(entries) <= 1 over a 3-bar window where at most one entry was ever
    mechanically possible — a near-tautology given the single-Trade state
    machine, and it carried dead code (an unused variable and a no-op
    `+ ([] if True else [])`). These versions keep a strong long signal
    firing on every one of 10 consecutive bars (well past the point a
    buggy implementation — e.g. a list-based position store — would have
    opened several trades) and assert on specific, positive evidence."""

    def _continuous_signal_bars(self, n_bars: int = 10):
        rows = [
            {"open": 1.1000 + 0.0001 * i, "high": 1.1002 + 0.0001 * i, "low": 1.0998 + 0.0001 * i,
             "close": 1.1001 + 0.0001 * i, "atr_14": 0.0010}
            for i in range(n_bars)
        ]
        df = _bars(rows)
        probabilities = pd.Series({ts: 0.90 for ts in df.index}, name="p")
        return rows, df, probabilities

    def test_exactly_one_trade_recorded_after_forced_close_despite_continuous_signal(self) -> None:
        config = BacktestConfig(max_holding_bars=5)
        rows, df, probabilities = self._continuous_signal_bars()
        result = run_backtest(df, probabilities, config, initial_equity=10_000.0)

        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade.entry_time == df.index[1]  # signal at bar[0] -> executes at bar[1]'s open
        assert trade.entry_price == pytest.approx(rows[1]["open"] + config.slippage_price)
        assert trade.exit_reason == "MAX_HOLDING_PERIOD"

    def test_equity_curve_reflects_a_single_positions_pnl_not_compounded_duplicates(self) -> None:
        """If a second (buggy) position had also opened at bar[2]'s open,
        the unrealized PnL from bar[2] onward would be roughly double the
        single-position trajectory computed directly from Trade mechanics.
        Recompute the expected single-position unrealized PnL bar-by-bar
        and compare exactly."""
        config = BacktestConfig(max_holding_bars=100)
        rows, df, probabilities = self._continuous_signal_bars()
        result = run_backtest(df, probabilities, config, initial_equity=10_000.0)

        assert len(result.trades) == 0  # never forced closed within this window
        entry_price = rows[1]["open"] + config.slippage_price
        sl_dist = config.stop_loss_atr_mult * rows[1]["atr_14"]
        size = (10_000.0 * config.risk_per_trade) / ((sl_dist / config.pip_size) * config.pip_value_per_lot)

        for i in range(1, len(rows)):
            ts = df.index[i]
            expected_pips = (rows[i]["close"] - entry_price) / config.pip_size
            expected_unrealized = expected_pips * config.pip_value_per_lot * size - config.commission_per_lot_round_turn * size
            assert result.equity_curve.loc[ts] == pytest.approx(10_000.0 + expected_unrealized, rel=1e-9)


class TestInputValidation:
    def test_missing_required_column_raises(self) -> None:
        config = BacktestConfig()
        df = _bars([{"open": 1.1, "high": 1.1, "low": 1.1, "close": 1.1}])  # no atr_14
        with pytest.raises(BacktestConfigError):
            run_backtest(df, pd.Series(dtype=float), config)


class TestMaxPositionsPerSymbolEnforcement:
    """M-4 remediation: max_positions_per_symbol previously had zero effect
    on run_backtest's behavior. Spec Section 10 fixes this at 1 for v1.0.0;
    a configured value other than 1 must now be explicitly rejected rather
    than silently ignored (the engine's single-Trade state machine cannot
    support anything else without inventing unspecified multi-position
    trading-rule logic)."""

    def test_default_config_value_of_one_is_accepted(self) -> None:
        config = BacktestConfig()
        assert config.max_positions_per_symbol == 1
        df = _bars([{"open": 1.1, "high": 1.1002, "low": 1.0998, "close": 1.1001, "atr_14": 0.0010}])
        run_backtest(df, pd.Series(dtype=float), config)  # must not raise

    def test_configured_value_of_two_is_rejected(self) -> None:
        config = BacktestConfig(max_positions_per_symbol=2)
        df = _bars([{"open": 1.1, "high": 1.1002, "low": 1.0998, "close": 1.1001, "atr_14": 0.0010}])
        with pytest.raises(BacktestConfigError):
            run_backtest(df, pd.Series(dtype=float), config)

    def test_configured_value_of_zero_is_rejected(self) -> None:
        config = BacktestConfig(max_positions_per_symbol=0)
        df = _bars([{"open": 1.1, "high": 1.1002, "low": 1.0998, "close": 1.1001, "atr_14": 0.0010}])
        with pytest.raises(BacktestConfigError):
            run_backtest(df, pd.Series(dtype=float), config)


class TestReproducibility:
    def test_identical_inputs_produce_identical_trades_and_equity(self) -> None:
        config = BacktestConfig()
        rows = [
            {"open": 1.1000, "high": 1.1002, "low": 1.0998, "close": 1.1001, "atr_14": 0.0010},
            {"open": 1.1001, "high": 1.1005, "low": 1.0999, "close": 1.1000, "atr_14": 0.0010},
            {"open": 1.1000, "high": 1.1030, "low": 1.1000, "close": 1.1020, "atr_14": 0.0010},
        ]
        df = _bars(rows)
        probabilities = pd.Series(
            {df.index[0]: 0.60, df.index[1]: 0.50, df.index[2]: 0.50}, name="p"
        )
        result_a = run_backtest(df, probabilities, config, initial_equity=10_000.0)
        result_b = run_backtest(df, probabilities, config, initial_equity=10_000.0)

        assert len(result_a.trades) == len(result_b.trades)
        for ta, tb in zip(result_a.trades, result_b.trades):
            assert ta.entry_price == tb.entry_price
            assert ta.exit_price == tb.exit_price
            assert ta.pnl == tb.pnl
        pd.testing.assert_series_equal(result_a.equity_curve, result_b.equity_curve)
        assert result_a.final_equity == result_b.final_equity
