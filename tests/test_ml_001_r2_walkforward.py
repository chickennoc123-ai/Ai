"""Temporal split and walk-forward protocol tests.

Covers: temporal boundaries, no leakage, no random split, OOS
prediction registration, holdout access prevention (one-time-only).
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.ml_r2.walkforward_r2 import (
    HoldoutAccessGuard,
    MAX_WARMUP_BARS,
    TemporalSplitError,
    compute_temporal_split,
    generate_oos_predictions,
    make_walk_forward_windows,
)
from core.provenance_enforcement import DataAccessAction, DataState, DataStateViolationError
from tests.r2_fixtures import make_synthetic_ohlcv


class TestTemporalSplit:
    def test_split_is_chronological_and_non_overlapping(self) -> None:
        df = make_synthetic_ohlcv(3000, seed=40)
        split = compute_temporal_split(df)
        assert split.development.index[-1] < split.validation.index[0]
        assert split.validation.index[-1] < split.holdout.index[0]

    def test_split_fractions_approximately_60_20_20(self) -> None:
        df = make_synthetic_ohlcv(3000, seed=41)
        split = compute_temporal_split(df)
        n = len(df)
        assert abs(len(split.development) / n - 0.60) < 0.01
        assert abs(len(split.validation) / n - 0.20) < 0.01
        assert abs(len(split.holdout) / n - 0.20) < 0.02

    def test_split_covers_the_entire_series(self) -> None:
        df = make_synthetic_ohlcv(3000, seed=42)
        split = compute_temporal_split(df)
        assert len(split.development) + len(split.validation) + len(split.holdout) == len(df)

    def test_insufficient_rows_raises(self) -> None:
        df = make_synthetic_ohlcv(3, seed=43)
        with pytest.raises(TemporalSplitError):
            compute_temporal_split(df)

    def test_non_datetime_index_raises(self) -> None:
        df = make_synthetic_ohlcv(100, seed=44).reset_index(drop=True)
        with pytest.raises(TemporalSplitError):
            compute_temporal_split(df)


class TestHoldoutAccessGuard:
    def test_development_training_allowed(self) -> None:
        guard = HoldoutAccessGuard(hypothesis_id="ML-001-R2-test")
        guard.validate(DataState.DEVELOPMENT, DataAccessAction.TRAINING)  # should not raise

    def test_holdout_training_blocked(self) -> None:
        guard = HoldoutAccessGuard(hypothesis_id="ML-001-R2-test")
        with pytest.raises(DataStateViolationError):
            guard.validate(DataState.PURE_HOLDOUT, DataAccessAction.TRAINING)

    def test_holdout_final_evaluation_allowed_once(self) -> None:
        guard = HoldoutAccessGuard(hypothesis_id="ML-001-R2-test")
        guard.validate(DataState.PURE_HOLDOUT, DataAccessAction.FINAL_EVALUATION)
        assert guard.holdout_opened is True

    def test_holdout_second_access_blocked(self) -> None:
        guard = HoldoutAccessGuard(hypothesis_id="ML-001-R2-test")
        guard.validate(DataState.PURE_HOLDOUT, DataAccessAction.FINAL_EVALUATION)
        with pytest.raises(DataStateViolationError):
            guard.validate(DataState.PURE_HOLDOUT, DataAccessAction.FINAL_EVALUATION)

    def test_validation_training_blocked(self) -> None:
        guard = HoldoutAccessGuard(hypothesis_id="ML-001-R2-test")
        with pytest.raises(DataStateViolationError):
            guard.validate(DataState.VALIDATION, DataAccessAction.TRAINING)


class TestWalkForwardOOSGeneration:
    def test_windows_are_chronological_no_overlap_train_test(self) -> None:
        df = make_synthetic_ohlcv(2500, seed=45)
        windows = make_walk_forward_windows(df, train_window_size=1200, test_window_size=200, step_size=200, hypothesis_id="ML-001-R2-test")
        assert len(windows) > 0
        for w in windows:
            assert w.train_end <= w.test_start
            assert w.test_start < w.test_end

    def test_oos_predictions_are_registered_with_full_provenance(self) -> None:
        df = make_synthetic_ohlcv(2500, seed=46)
        windows = make_walk_forward_windows(df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="ML-001-R2-test")
        batches, provenance = generate_oos_predictions(
            df, windows[:1], hypothesis_id="ML-001-R2-test", dataset_id="synthetic-fixture-46",
            validation_period=("2023-01-01", "2023-12-31"), holdout_period=("2024-01-01", "2024-12-31"),
        )
        assert len(batches) == 1
        batch = batches[0]
        assert batch.model_version == "RF-R2-001"
        assert batch.feature_version == "FE-R2-003"
        assert batch.training_data_state == DataState.DEVELOPMENT
        assert batch.test_data_state == DataState.VALIDATION
        # every prediction is (class, probability) with a matching timestamp
        assert len(batch.predictions) == len(batch.test_indices) == len(batch.test_dates)
        # RunProvenance is produced automatically, one per window, not left unwired.
        assert len(provenance) == 1
        provenance[0].validate_complete()  # must not raise

    def test_oos_predictions_use_only_past_training_data(self) -> None:
        df = make_synthetic_ohlcv(2500, seed=47)
        windows = make_walk_forward_windows(df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="ML-001-R2-test")
        batches, _ = generate_oos_predictions(
            df, windows[:1], hypothesis_id="ML-001-R2-test", dataset_id="synthetic-fixture-47",
            validation_period=("2023-01-01", "2023-12-31"), holdout_period=("2024-01-01", "2024-12-31"),
        )
        batch = batches[0]
        for test_date in batch.test_dates:
            assert batch.window.train_dates[1] < test_date

    def test_holdout_state_requires_final_evaluation_semantics(self) -> None:
        df = make_synthetic_ohlcv(2500, seed=48)
        windows = make_walk_forward_windows(df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="ML-001-R2-test")
        batches, _ = generate_oos_predictions(
            df, windows[:1], hypothesis_id="ML-001-R2-test", dataset_id="synthetic-fixture-48",
            validation_period=("2023-01-01", "2023-12-31"), holdout_period=("2024-01-01", "2024-12-31"),
            test_data_state=DataState.PURE_HOLDOUT,
        )
        assert batches[0].test_data_state == DataState.PURE_HOLDOUT

    def test_warmup_bars_constant_matches_feature_spec(self) -> None:
        from core.features.fe_r2_001 import WARMUP_BARS

        assert MAX_WARMUP_BARS == max(WARMUP_BARS.values())
