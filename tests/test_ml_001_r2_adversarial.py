"""Adversarial tests for the ML-001-R2 implementation.

Each test simulates a specific failure mode the implementation-phase
instruction requires to be defended against: future-data injection,
shuffled/duplicate timestamps, missing bars, feature reordering, model
mismatch, dataset mismatch, and holdout/validation access violations.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.features.fe_r2_001 import FEATURE_ORDER, FeatureEngineeringError, build_feature_matrix
from core.ml_r2.model_r2 import ModelIntegrityError, ModelSchemaError, RFR2Model
from core.ml_r2.target_r2 import LabelConstructionError, align_features_and_labels, compute_label
from core.ml_r2.walkforward_r2 import generate_oos_predictions, make_walk_forward_windows
from core.provenance_enforcement import DataAccessAction, DataState, DataStateViolationError
from tests.r2_fixtures import make_synthetic_ohlcv


class TestFutureDataInjection:
    def test_features_up_to_t_are_unaffected_by_bars_after_t(self) -> None:
        """No feature at time t may change when future bars are appended (no lookahead)."""
        df_short = make_synthetic_ohlcv(700, seed=90)
        df_long = pd.concat([df_short, make_synthetic_ohlcv(300, seed=91, start=df_short.index[-1] + pd.Timedelta(hours=1))])

        features_short = build_feature_matrix(df_short)
        features_long = build_feature_matrix(df_long)

        pd.testing.assert_frame_equal(features_short, features_long.loc[df_short.index])

    def test_seeded_wilder_rsi_atr_specifically_unaffected_by_future_bars(self) -> None:
        """Targeted re-verification for the M-5 remediation's new
        _seeded_wilder_smooth recurrence specifically: the loop-based
        implementation processes strictly left-to-right, but this is
        confirmed empirically, not merely by code inspection."""
        from core.features.fe_r2_001 import compute_atr_14, compute_rsi_14

        df_short = make_synthetic_ohlcv(200, seed=94)
        df_long = pd.concat(
            [df_short, make_synthetic_ohlcv(200, seed=95, start=df_short.index[-1] + pd.Timedelta(hours=1))]
        )

        rsi_short = compute_rsi_14(df_short["close"])
        rsi_long = compute_rsi_14(df_long["close"])
        pd.testing.assert_series_equal(rsi_short, rsi_long.loc[df_short.index])

        atr_short = compute_atr_14(df_short["high"], df_short["low"], df_short["close"])
        atr_long = compute_atr_14(df_long["high"], df_long["low"], df_long["close"])
        pd.testing.assert_series_equal(atr_short, atr_long.loc[df_short.index])

    def test_label_at_t_is_unaffected_by_bars_after_t_plus_1(self) -> None:
        df_short = make_synthetic_ohlcv(50, seed=92)
        df_long = pd.concat([df_short, make_synthetic_ohlcv(50, seed=93, start=df_short.index[-1] + pd.Timedelta(hours=1))])

        label_short = compute_label(df_short["close"])
        label_long = compute_label(df_long["close"])

        # Every label except the last bar of df_short is defined identically once
        # bar t+1 is available in both; the short frame's *final* bar differs
        # (undefined vs. now-defined), which is the correct, expected behavior —
        # not a leakage bug, since that label legitimately requires df_long's data.
        pd.testing.assert_series_equal(label_short.iloc[:-1], label_long.loc[df_short.index].iloc[:-1])
        assert pd.isna(label_short.iloc[-1])
        assert pd.notna(label_long.loc[df_short.index].iloc[-1])


class TestShuffledAndDuplicateTimestamps:
    def test_shuffled_timestamps_rejected_by_features(self) -> None:
        df = make_synthetic_ohlcv(200, seed=94)
        shuffled = df.iloc[np.random.default_rng(1).permutation(len(df))]
        with pytest.raises(FeatureEngineeringError):
            build_feature_matrix(shuffled)

    def test_shuffled_timestamps_rejected_by_labels(self) -> None:
        df = make_synthetic_ohlcv(200, seed=95)
        shuffled_close = df["close"].iloc[np.random.default_rng(2).permutation(len(df))]
        with pytest.raises(LabelConstructionError):
            compute_label(shuffled_close)

    def test_duplicate_timestamps_rejected_by_features(self) -> None:
        df = make_synthetic_ohlcv(200, seed=96)
        with_dupe = pd.concat([df, df.iloc[[10]]]).sort_index()
        with pytest.raises(FeatureEngineeringError):
            build_feature_matrix(with_dupe)


class TestMissingBars:
    def test_an_arbitrary_weekday_gap_is_now_rejected(self) -> None:
        """A gap removed from ordinary weekday hours is a spec Section 7
        data-quality violation and must be rejected, not silently tolerated.

        This supersedes the pre-remediation version of this test, which
        asserted the opposite (permissive) behavior — see
        ML-001-R2-IMPLEMENTATION-INTEGRITY-AUDIT.md Finding C-1 and
        ML-001-R2-IMPLEMENTATION-INTEGRITY-REMEDIATION-REPORT.md.
        make_synthetic_ohlcv(700, seed=97) starting 2020-01-03 (a Friday)
        places bars 300-349 in mid-January on ordinary weekdays.
        """
        df = make_synthetic_ohlcv(700, seed=97)
        gapped = pd.concat([df.iloc[:300], df.iloc[350:]])
        with pytest.raises(FeatureEngineeringError):
            build_feature_matrix(gapped)

    def test_a_genuine_weekend_gap_does_not_corrupt_downstream_computation(self) -> None:
        """A real Fri 22:00-Sun 22:00 UTC weekend closure is legal (per spec
        Section 7) and must not crash feature computation."""
        df = make_synthetic_ohlcv(2000, seed=97)
        # Last bar strictly before the Friday 22:00 UTC close (hour == 21).
        friday_close_bars = df.index[(df.index.weekday == 4) & (df.index.hour == 21)]
        last_bar_before_close = friday_close_bars[0]
        sunday_reopen = last_bar_before_close + pd.Timedelta(days=2, hours=1)  # Sunday 22:00 UTC

        pre_weekend = df.loc[:last_bar_before_close]
        post_weekend = df.loc[df.index >= sunday_reopen]
        gapped = pd.concat([pre_weekend, post_weekend])

        features = build_feature_matrix(gapped)  # must not raise
        assert list(features.columns) == FEATURE_ORDER
        assert features.index.equals(gapped.index)


class TestFeatureReordering:
    def test_model_train_rejects_reordered_columns(self) -> None:
        df = make_synthetic_ohlcv(800, seed=98)
        features = build_feature_matrix(df)
        labels = compute_label(df["close"])
        X, y = align_features_and_labels(features, labels)
        attacker_reordered = X[list(reversed(FEATURE_ORDER))]

        model = RFR2Model()
        with pytest.raises(ModelSchemaError):
            model.train(attacker_reordered, y, df.index[0], df.index[-1])

    def test_model_predict_rejects_reordered_columns_even_after_valid_training(self) -> None:
        df = make_synthetic_ohlcv(800, seed=99)
        features = build_feature_matrix(df)
        labels = compute_label(df["close"])
        X, y = align_features_and_labels(features, labels)

        model = RFR2Model()
        model.train(X, y, df.index[0], df.index[-1])

        attacker_reordered = X[list(reversed(FEATURE_ORDER))]
        with pytest.raises(ModelSchemaError):
            model.predict(attacker_reordered)


class TestModelMismatch:
    def test_feature_version_drift_is_rejected_at_load_time(self) -> None:
        """If FE-R2-001 is ever superseded, a model trained under the old
        feature_version must not be silently treated as compatible.

        Finding M-8 remediation (ML-001-R2-IMPLEMENTATION-INTEGRITY-AUDIT.md):
        this used to only be observable-if-checked-manually; load() now
        enforces it, per spec Section 12's "schema hash checked at each
        entry point," and fails closed."""
        df = make_synthetic_ohlcv(800, seed=100)
        features = build_feature_matrix(df)
        labels = compute_label(df["close"])
        X, y = align_features_and_labels(features, labels)

        model = RFR2Model()
        model.train(X, y, df.index[0], df.index[-1])

        with tempfile.TemporaryDirectory() as tmp:
            model_path = str(Path(tmp) / "model.joblib")
            meta_path = str(Path(tmp) / "metadata.json")
            model.save(model_path, meta_path)

            import json

            with open(meta_path) as f:
                meta = json.load(f)
            # Simulate a future feature-set change without recomputing this model.
            meta["feature_version"] = "FE-R2-999-SIMULATED-FUTURE-VERSION"
            with open(meta_path, "w") as f:
                json.dump(meta, f)

            with pytest.raises(ModelIntegrityError):
                RFR2Model.load(model_path, meta_path)


class TestDatasetMismatch:
    def test_dataset_checksum_distinguishes_different_datasets(self) -> None:
        """The provenance checksum mechanism must be sensitive enough to catch
        a silent dataset swap."""
        df_a = make_synthetic_ohlcv(500, seed=101)
        df_b = make_synthetic_ohlcv(500, seed=102)

        checksum_a = hashlib.sha256(pd.util.hash_pandas_object(df_a).values.tobytes()).hexdigest()
        checksum_b = hashlib.sha256(pd.util.hash_pandas_object(df_b).values.tobytes()).hexdigest()

        assert checksum_a != checksum_b

    def test_dataset_checksum_is_stable_for_identical_data(self) -> None:
        df_a = make_synthetic_ohlcv(500, seed=103)
        df_a_copy = df_a.copy()

        checksum_a = hashlib.sha256(pd.util.hash_pandas_object(df_a).values.tobytes()).hexdigest()
        checksum_a_copy = hashlib.sha256(pd.util.hash_pandas_object(df_a_copy).values.tobytes()).hexdigest()

        assert checksum_a == checksum_a_copy


class TestHoldoutAndValidationAccessViolations:
    def test_accidental_training_on_validation_blocked(self) -> None:
        df = make_synthetic_ohlcv(2500, seed=104)
        windows = make_walk_forward_windows(
            df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="ML-001-R2-test"
        )
        with pytest.raises(DataStateViolationError):
            generate_oos_predictions(
                df, windows[:1], hypothesis_id="ML-001-R2-test", dataset_id="synthetic-fixture-104",
                validation_period=("2023-01-01", "2023-12-31"), holdout_period=("2024-01-01", "2024-12-31"),
                training_data_state=DataState.VALIDATION,
            )

    def test_accidental_training_on_holdout_blocked(self) -> None:
        df = make_synthetic_ohlcv(2500, seed=105)
        windows = make_walk_forward_windows(
            df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="ML-001-R2-test"
        )
        with pytest.raises(DataStateViolationError):
            generate_oos_predictions(
                df, windows[:1], hypothesis_id="ML-001-R2-test", dataset_id="synthetic-fixture-105",
                validation_period=("2023-01-01", "2023-12-31"), holdout_period=("2024-01-01", "2024-12-31"),
                training_data_state=DataState.PURE_HOLDOUT,
            )

    def test_holdout_access_for_training_action_blocked(self) -> None:
        df = make_synthetic_ohlcv(2500, seed=106)
        windows = make_walk_forward_windows(
            df, train_window_size=1200, test_window_size=300, step_size=300, hypothesis_id="ML-001-R2-test"
        )
        # test_data_state=PURE_HOLDOUT combined with a training_data_state that
        # itself is not DEVELOPMENT must still fail at the training-action check.
        with pytest.raises(DataStateViolationError):
            generate_oos_predictions(
                df,
                windows[:1],
                hypothesis_id="ML-001-R2-test",
                dataset_id="synthetic-fixture-106",
                validation_period=("2023-01-01", "2023-12-31"),
                holdout_period=("2024-01-01", "2024-12-31"),
                training_data_state=DataState.PURE_HOLDOUT,
                test_data_state=DataState.PURE_HOLDOUT,
            )
