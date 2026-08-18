"""ML-001-R2 deterministic Python<->Pine parity simulator tests.

Covers: layer separation (core.ml_r2.simulator_r2), the model-artifact
fail-closed contract (NullModelProvider, pine_model_exporter_r2), the
committed golden dataset's exact trade-event sequence (a real regression
test, not hand-traced), and fresh-process reproducibility.

MECHANICAL CORRECTNESS ONLY -- no economic claim is made or implied by
anything in this file.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.ml_r2.backtest_r2 import BacktestConfig
from core.ml_r2.pine_model_exporter_r2 import (
    ModelArtifactMissingError as ExporterModelArtifactMissingError,
)
from core.ml_r2.pine_model_exporter_r2 import export_model_to_pine
from core.ml_r2.simulator_r2 import (
    EVENT_ENTER_LONG,
    EVENT_ENTER_SHORT,
    EVENT_EXIT_MAX_HOLD,
    EVENT_EXIT_STOP,
    EVENT_EXIT_TP,
    MODEL_PARITY_TEST_FIXTURE_ONLY,
    FeatureEngine,
    FixtureAlignmentError,
    FixtureProbabilityProvider,
    ModelArtifactMissingError,
    NullModelProvider,
    SignalDecisionEngine,
    decide_signal,
    run_simulation,
)
from tests.r2_fixtures import make_synthetic_ohlcv

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_OHLCV = REPO_ROOT / "ML-001-R2-GOLDEN-OHLCV-FIXTURE.csv"
GOLDEN_PROB = REPO_ROOT / "ML-001-R2-GOLDEN-PROBABILITY-FIXTURE.csv"
GOLDEN_VECTOR = REPO_ROOT / "ML-001-R2-GOLDEN-PARITY-VECTOR.csv"


def _load_golden():
    ohlcv = pd.read_csv(GOLDEN_OHLCV, index_col="timestamp", parse_dates=True)
    probabilities = pd.read_csv(GOLDEN_PROB, index_col=0, parse_dates=True).iloc[:, 0]
    probabilities.name = "supplied_model_probability"
    return ohlcv, probabilities


class TestLayerSeparation:
    """Layer A/B/C are genuinely separate, independently callable units."""

    def test_feature_engine_adds_feature_valid_flag(self) -> None:
        df = make_synthetic_ohlcv(700, seed=11)
        features = FeatureEngine.compute(df)
        assert "feature_valid" in features.columns
        assert not features["feature_valid"].iloc[:600].any()
        assert features["feature_valid"].iloc[600:].all()

    def test_null_model_provider_fails_closed(self) -> None:
        with pytest.raises(ModelArtifactMissingError, match="MODEL_ARTIFACT_MISSING"):
            NullModelProvider().predict_probability(pd.DataFrame())

    def test_fixture_provider_rejects_relabeling(self) -> None:
        with pytest.raises(FixtureAlignmentError):
            FixtureProbabilityProvider(probabilities=pd.Series(dtype=float), label="NOT_THE_REQUIRED_LABEL")

    def test_fixture_provider_label_is_the_required_constant(self) -> None:
        provider = FixtureProbabilityProvider(probabilities=pd.Series(dtype=float))
        assert provider.label == MODEL_PARITY_TEST_FIXTURE_ONLY

    def test_fixture_provider_rejects_unaligned_timestamps(self) -> None:
        df = make_synthetic_ohlcv(700, seed=12)
        features = FeatureEngine.compute(df)
        bogus = pd.Series({pd.Timestamp("1999-01-01", tz="UTC"): 0.9})
        provider = FixtureProbabilityProvider(probabilities=bogus)
        with pytest.raises(FixtureAlignmentError):
            provider.predict_probability(features)

    @pytest.mark.parametrize(
        "p,expected",
        [(0.90, "LONG"), (0.56, "LONG"), (0.55, "FLAT"), (0.50, "FLAT"), (0.45, "FLAT"), (0.44, "SHORT"), (0.10, "SHORT"), (float("nan"), "FLAT")],
    )
    def test_decide_signal_boundaries(self, p: float, expected: str) -> None:
        assert decide_signal(p, 0.55, 0.45) == expected

    def test_signal_decision_engine_ignores_bars_where_features_are_not_valid(self) -> None:
        df = make_synthetic_ohlcv(700, seed=13)
        features = FeatureEngine.compute(df)
        # supply a probability during warmup (bar 50, well before bar 600)
        warmup_ts = df.index[50]
        probabilities = pd.Series({warmup_ts: 0.90})
        engine = SignalDecisionEngine(BacktestConfig())
        signals = engine.decide(features, probabilities)
        assert signals.loc[warmup_ts] == "FLAT"


class TestModelExporterFailsClosed:
    def test_export_fails_closed_when_artifact_missing(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "rf_r2_001.joblib"
        with pytest.raises(ExporterModelArtifactMissingError, match="MODEL_ARTIFACT_MISSING"):
            export_model_to_pine(nonexistent)

    def test_export_does_not_fabricate_pine_code(self, tmp_path: Path) -> None:
        """Even if a *file* exists at the path but was never produced by a
        real training run, the exporter must not silently succeed with
        fabricated tree code -- it should proceed to the (intentionally
        unimplemented) real translation logic and fail there instead."""
        fake_path = tmp_path / "not_a_real_model.joblib"
        fake_path.write_bytes(b"not a real trained artifact")
        with pytest.raises(NotImplementedError):
            export_model_to_pine(fake_path)


class TestSmallHandBuiltScenario:
    """A tiny, fully hand-traceable scenario -- independent of the large
    golden dataset -- exercising a stop-loss exit end to end through all
    five layers."""

    def test_long_entry_then_stop_loss(self) -> None:
        df = make_synthetic_ohlcv(650, seed=21)
        last_close = df["close"].iloc[-1]
        extra_index = pd.date_range(df.index[-1] + pd.Timedelta(hours=1), periods=3, freq="h", tz="UTC")

        features_so_far = FeatureEngine.compute(df)
        atr_now = features_so_far["atr_14"].iloc[-1]
        sl_dist = BacktestConfig().stop_loss_atr_mult * atr_now
        wick = 0.05 * sl_dist

        extra_rows = pd.DataFrame(
            {
                "open": [last_close, last_close, last_close],
                "high": [last_close + wick, last_close + 1e-6, last_close - sl_dist * 0.4],
                "low": [last_close - wick, last_close - sl_dist * 1.5, last_close - sl_dist * 1.6],
                "close": [last_close + wick * 0.2, last_close - sl_dist * 1.4, last_close - sl_dist * 1.5],
            },
            index=extra_index,
        )
        full_df = pd.concat([df, extra_rows])

        signal_ts = df.index[-1]
        probabilities = pd.Series({signal_ts: 0.90})
        provider = FixtureProbabilityProvider(probabilities=probabilities)

        result = run_simulation(full_df, provider)
        assert len(result.events) == 2
        assert result.events[0].event == EVENT_ENTER_LONG
        assert result.events[1].event == EVENT_EXIT_STOP


class TestGoldenDatasetRegression:
    """Real regression test against the committed golden dataset -- the
    exact trade-event sequence was independently verified (not hand-
    traced) when the fixture was generated; this test locks that
    sequence in so a future change to fe_r2_001.py or backtest_r2.py
    that silently alters behavior is caught."""

    @pytest.fixture(scope="class")
    def golden_result(self):
        ohlcv, probabilities = _load_golden()
        provider = FixtureProbabilityProvider(probabilities=probabilities)
        return run_simulation(ohlcv, provider, config=BacktestConfig())

    def test_exactly_seven_trades(self, golden_result) -> None:
        assert len(golden_result.backtest.trades) == 7

    def test_trade_event_sequence_exact(self, golden_result) -> None:
        expected = [
            (699, EVENT_ENTER_LONG), (700, EVENT_EXIT_STOP),
            (731, EVENT_ENTER_LONG), (732, EVENT_EXIT_TP),
            (763, EVENT_ENTER_SHORT), (764, EVENT_EXIT_STOP),
            (795, EVENT_ENTER_SHORT), (796, EVENT_EXIT_TP),
            (827, EVENT_ENTER_LONG), (851, EVENT_EXIT_MAX_HOLD),
            (883, EVENT_ENTER_LONG), (884, EVENT_EXIT_STOP),
            (915, EVENT_ENTER_LONG), (939, EVENT_EXIT_MAX_HOLD),
        ]
        index = golden_result.ohlcv.index
        actual = [(index.get_loc(e.timestamp), e.event) for e in golden_result.events]
        assert actual == expected

    def test_exit_priority_conflict_bar_resolves_to_stop_not_tp(self, golden_result) -> None:
        """Scenario 6 (entry at bar 883): the exit bar's range breaches
        BOTH stop-loss and take-profit simultaneously. Spec Section 10
        fixes SL > TP priority -- the trade whose entry_bar_index
        corresponds to bar 883 must show exit_reason STOP_LOSS."""
        index = golden_result.ohlcv.index
        conflict_trade = next(t for t in golden_result.backtest.trades if index.get_loc(t.entry_time) == 883)
        assert conflict_trade.exit_reason == "STOP_LOSS"
        assert index.get_loc(conflict_trade.exit_time) == 884

    def test_position_limit_blocks_repeated_signals_while_open(self, golden_result) -> None:
        """Scenario 7: signals supplied at bars 916 and 934 while a
        position entered at bar 915 is still open must NOT produce
        additional trades (no pyramiding, max 1 position/symbol)."""
        index = golden_result.ohlcv.index
        entries_between = [
            index.get_loc(t.entry_time) for t in golden_result.backtest.trades if 915 <= index.get_loc(t.entry_time) <= 939
        ]
        assert entries_between == [915]

    def test_max_hold_exits_at_exactly_24_bars(self, golden_result) -> None:
        max_hold_trades = [t for t in golden_result.backtest.trades if t.exit_reason == "MAX_HOLDING_PERIOD"]
        assert len(max_hold_trades) == 2
        for t in max_hold_trades:
            assert t.holding_bars == 24

    def test_threshold_boundary_produces_no_trade(self, golden_result) -> None:
        """p supplied at exactly 0.55 and exactly 0.45 (bars 970, 975)
        must not produce any additional trade beyond the 7 already
        accounted for by the other scenarios."""
        index = golden_result.ohlcv.index
        near_boundary = [t for t in golden_result.backtest.trades if index.get_loc(t.entry_time) >= 960]
        assert near_boundary == []

    def test_full_bar_table_matches_committed_csv(self, golden_result) -> None:
        actual = golden_result.full_bar_table()
        expected = pd.read_csv(GOLDEN_VECTOR, index_col="timestamp", parse_dates=True)
        numeric_cols = ["open", "high", "low", "close", "momentum_5", "momentum_20", "rsi_14", "atr_14", "volatility_regime"]
        for col in numeric_cols:
            pd.testing.assert_series_equal(actual[col], expected[col], check_names=False, atol=1e-9)
        for col in ["signal", "position_state"]:
            assert (actual[col].values == expected[col].values).all()


class TestFreshProcessReproducibility:
    """Runs the golden-dataset simulation in a brand-new Python
    interpreter process, twice, and asserts byte-identical trade-event
    output -- a stronger guarantee than an in-process double-run, since
    it also rules out any accidental cross-run state leakage inside a
    single interpreter."""

    _SCRIPT = """
import sys
sys.path.insert(0, {repo_root!r})
import pandas as pd
from core.ml_r2.backtest_r2 import BacktestConfig
from core.ml_r2.simulator_r2 import FixtureProbabilityProvider, run_simulation

ohlcv = pd.read_csv({ohlcv_path!r}, index_col="timestamp", parse_dates=True)
probabilities = pd.read_csv({prob_path!r}, index_col=0, parse_dates=True).iloc[:, 0]
provider = FixtureProbabilityProvider(probabilities=probabilities)
result = run_simulation(ohlcv, provider, config=BacktestConfig())
for e in result.events:
    print(e.timestamp.isoformat(), e.event, f"{{e.price:.10f}}")
"""

    def _run_fresh_process(self) -> str:
        script = self._SCRIPT.format(repo_root=str(REPO_ROOT), ohlcv_path=str(GOLDEN_OHLCV), prob_path=str(GOLDEN_PROB))
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT))
        assert proc.returncode == 0, proc.stderr
        return proc.stdout

    def test_two_fresh_processes_produce_byte_identical_output(self) -> None:
        output_a = self._run_fresh_process()
        output_b = self._run_fresh_process()
        assert output_a == output_b
        assert len(output_a.strip().splitlines()) == 14  # 7 trades * 2 events each
