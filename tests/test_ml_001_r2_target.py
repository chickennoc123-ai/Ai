"""TARGET-R2-001 label construction tests.

Covers: horizon alignment, positive class, negative class, boundary
conditions (last bar undefined, not silently 0), and leakage checks.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.features.fe_r2_001 import build_feature_matrix
from core.ml_r2.target_r2 import (
    LabelConstructionError,
    align_features_and_labels,
    assert_no_leakage,
    compute_label,
)
from tests.r2_fixtures import make_synthetic_ohlcv


def _index(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")


class TestLabelCorrectness:
    def test_positive_class_when_next_close_higher(self) -> None:
        close = pd.Series([100.0, 101.0], index=_index(2))
        label = compute_label(close)
        assert label.iloc[0] == 1.0

    def test_negative_class_when_next_close_lower(self) -> None:
        close = pd.Series([100.0, 99.0], index=_index(2))
        label = compute_label(close)
        assert label.iloc[0] == 0.0

    def test_negative_class_when_next_close_equal(self) -> None:
        close = pd.Series([100.0, 100.0], index=_index(2))
        label = compute_label(close)
        assert label.iloc[0] == 0.0  # spec: close[t+1] <= close[t] -> 0

    def test_last_bar_is_undefined_not_zero(self) -> None:
        close = pd.Series([100.0, 101.0, 99.0], index=_index(3))
        label = compute_label(close)
        assert pd.isna(label.iloc[-1])

    def test_horizon_is_exactly_one_bar(self) -> None:
        close = pd.Series([100.0, 105.0, 90.0, 110.0], index=_index(4))
        label = compute_label(close)
        assert label.iloc[0] == 1.0  # 100 -> 105
        assert label.iloc[1] == 0.0  # 105 -> 90
        assert label.iloc[2] == 1.0  # 90 -> 110
        assert pd.isna(label.iloc[3])

    def test_non_datetime_index_raises(self) -> None:
        close = pd.Series([1.0, 2.0]).reset_index(drop=True)
        with pytest.raises(LabelConstructionError):
            compute_label(close)


class TestFeatureLabelAlignment:
    def test_align_drops_warmup_and_final_row(self) -> None:
        df = make_synthetic_ohlcv(700, seed=20)
        features = build_feature_matrix(df)
        labels = compute_label(df["close"])
        X, y = align_features_and_labels(features, labels)
        assert len(X) == len(y)
        assert X.notna().all().all()
        assert y.notna().all()
        # strictly fewer rows than the raw frame (warmup + final bar removed)
        assert len(X) < len(df)

    def test_align_preserves_chronological_order(self) -> None:
        df = make_synthetic_ohlcv(700, seed=21)
        features = build_feature_matrix(df)
        labels = compute_label(df["close"])
        X, _ = align_features_and_labels(features, labels)
        assert X.index.is_monotonic_increasing

    def test_mismatched_index_raises(self) -> None:
        df = make_synthetic_ohlcv(50, seed=22)
        features = build_feature_matrix(df)
        labels = compute_label(df["close"]).iloc[:-1]
        with pytest.raises(LabelConstructionError):
            align_features_and_labels(features, labels)


class TestLeakageGuard:
    def test_assert_no_leakage_passes_for_canonical_labels(self) -> None:
        df = make_synthetic_ohlcv(700, seed=23)
        features = build_feature_matrix(df)
        labels = compute_label(df["close"])
        assert_no_leakage(df["close"], features, labels)  # should not raise

    def test_assert_no_leakage_detects_shifted_labels(self) -> None:
        df = make_synthetic_ohlcv(700, seed=24)
        features = build_feature_matrix(df)
        # Simulate a leakage bug: label uses close[t] vs close[t] (always False) instead of t+1.
        tampered = pd.Series(0.0, index=df.index)
        tampered.iloc[-1] = np.nan
        with pytest.raises(LabelConstructionError):
            assert_no_leakage(df["close"], features, tampered)

    def test_assert_no_leakage_detects_wrong_last_row_definedness(self) -> None:
        df = make_synthetic_ohlcv(50, seed=25)
        features = build_feature_matrix(df)
        labels = compute_label(df["close"])
        # Leakage bug: someone filled in the undefined final label instead of leaving it NaN.
        tampered = labels.copy()
        tampered.iloc[-1] = 1.0
        with pytest.raises(LabelConstructionError):
            assert_no_leakage(df["close"], features, tampered)
