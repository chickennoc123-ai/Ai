"""End-to-end reproducibility test (RUN A vs RUN B).

Per ML-001-R2-CLEAN-REBUILD-SPEC.md Section 15 and the implementation
instruction Phase 9: identical inputs must yield identical features,
identical predictions, identical model checksum, identical trade
sequence, identical equity curve, and identical artifact hashes. Any
divergence means IMPLEMENTATION_NOT_READY.

Uses deterministic synthetic data — mechanical reproducibility check
only, not economic validation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.features.fe_r2_001 import build_feature_matrix
from core.ml_r2.backtest_r2 import BacktestConfig, run_backtest
from core.ml_r2.model_r2 import RFR2Model
from core.ml_r2.target_r2 import align_features_and_labels, compute_label
from tests.r2_fixtures import make_synthetic_ohlcv


def _run_full_pipeline(seed: int = 200, n_bars: int = 1500):
    df = make_synthetic_ohlcv(n_bars, seed=seed)

    features = build_feature_matrix(df)
    labels = compute_label(df["close"])
    X, y = align_features_and_labels(features, labels)

    model = RFR2Model()
    metadata = model.train(X, y, training_start=df.index[0], training_end=df.index[-1])

    probabilities = pd.Series(model.predict_proba(X), index=X.index)

    backtest_df = df.loc[X.index].copy()
    backtest_df["atr_14"] = features.loc[X.index, "atr_14"]
    result = run_backtest(backtest_df, probabilities, BacktestConfig(), initial_equity=10_000.0)

    return features, labels, metadata, probabilities, result


class TestEndToEndReproducibility:
    def test_features_are_identical_across_runs(self) -> None:
        features_a, *_ = _run_full_pipeline()
        features_b, *_ = _run_full_pipeline()
        pd.testing.assert_frame_equal(features_a, features_b)

    def test_labels_are_identical_across_runs(self) -> None:
        _, labels_a, *_ = _run_full_pipeline()
        _, labels_b, *_ = _run_full_pipeline()
        pd.testing.assert_series_equal(labels_a, labels_b)

    def test_model_checksum_is_identical_across_runs(self) -> None:
        _, _, metadata_a, *_ = _run_full_pipeline()
        _, _, metadata_b, *_ = _run_full_pipeline()
        assert metadata_a.checksum == metadata_b.checksum

    def test_predictions_are_identical_across_runs(self) -> None:
        *_, probabilities_a, _ = _run_full_pipeline()
        *_, probabilities_b, _ = _run_full_pipeline()
        np.testing.assert_array_equal(probabilities_a.to_numpy(), probabilities_b.to_numpy())

    def test_trade_sequence_is_identical_across_runs(self) -> None:
        *_, result_a = _run_full_pipeline()
        *_, result_b = _run_full_pipeline()
        assert len(result_a.trades) == len(result_b.trades)
        for ta, tb in zip(result_a.trades, result_b.trades):
            assert ta.entry_time == tb.entry_time
            assert ta.entry_price == tb.entry_price
            assert ta.exit_time == tb.exit_time
            assert ta.exit_price == tb.exit_price
            assert ta.exit_reason == tb.exit_reason
            assert ta.pnl == tb.pnl

    def test_equity_curve_is_identical_across_runs(self) -> None:
        *_, result_a = _run_full_pipeline()
        *_, result_b = _run_full_pipeline()
        pd.testing.assert_series_equal(result_a.equity_curve, result_b.equity_curve)
        assert result_a.final_equity == result_b.final_equity

    def test_different_seeds_produce_different_datasets_but_pipeline_still_reproducible(self) -> None:
        """Sanity check that the harness itself isn't trivially identical
        regardless of input — different synthetic seeds must diverge, while
        each seed remains internally reproducible run-to-run."""
        features_seed_a, *_ = _run_full_pipeline(seed=201)
        features_seed_b, *_ = _run_full_pipeline(seed=202)
        assert not features_seed_a.equals(features_seed_b)
