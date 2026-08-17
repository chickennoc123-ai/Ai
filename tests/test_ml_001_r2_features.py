"""FE-R2-001 feature engineering tests.

Covers: normal data, insufficient history, NaN handling, boundary
candles, timestamp alignment, deterministic repeatability.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.features.fe_r2_001 import (
    FEATURE_ORDER,
    FEATURE_VERSION,
    WARMUP_BARS,
    FeatureEngineeringError,
    build_feature_matrix,
    compute_momentum,
    compute_volatility_regime,
    get_feature_schema,
)
from tests.r2_fixtures import make_synthetic_ohlcv


class TestFeatureCorrectness:
    def test_feature_order_and_version_are_fixed(self) -> None:
        assert FEATURE_ORDER == ["momentum_5", "momentum_20", "rsi_14", "atr_14", "volatility_regime"]
        assert FEATURE_VERSION == "FE-R2-001"

    def test_normal_data_produces_all_columns_in_order(self) -> None:
        df = make_synthetic_ohlcv(700, seed=1)
        features = build_feature_matrix(df)
        assert list(features.columns) == FEATURE_ORDER
        assert features.index.equals(df.index)

    def test_momentum_5_formula_is_exact(self) -> None:
        close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 110.0], index=pd.date_range("2020-01-01", periods=6, freq="h", tz="UTC"))
        result = compute_momentum(close, 5)
        expected_last = (110.0 - 100.0) / 100.0
        assert result.iloc[:5].isna().all()
        assert result.iloc[5] == pytest.approx(expected_last)

    def test_insufficient_history_yields_all_nan(self) -> None:
        df = make_synthetic_ohlcv(3, seed=2)  # shorter than even the smallest warmup (momentum_5=5)
        features = build_feature_matrix(df)
        assert features.isna().all().all()

    def test_warmup_boundaries_are_exact(self) -> None:
        df = make_synthetic_ohlcv(700, seed=3)
        features = build_feature_matrix(df)
        for name, warmup in WARMUP_BARS.items():
            col = features[name]
            assert col.iloc[: warmup].isna().all(), f"{name}: expected NaN before warmup={warmup}"
            # At least one valid value should exist once warmup is satisfied
            # (momentum/rsi/atr are defined immediately after warmup; volatility_regime
            # requires the full 500-bar percentile window on top of atr's own warmup).
            assert col.iloc[warmup:].notna().any(), f"{name}: expected some non-NaN values after warmup"

    def test_boundary_candle_exact_warmup_index(self) -> None:
        df = make_synthetic_ohlcv(30, seed=4)
        features = build_feature_matrix(df)
        # momentum_5 warmup=5: index 4 (0-based) must be NaN, index 5 must be defined.
        assert pd.isna(features["momentum_5"].iloc[4])
        assert pd.notna(features["momentum_5"].iloc[5])
        # momentum_20 warmup=20: index 19 NaN, index 20 defined.
        assert pd.isna(features["momentum_20"].iloc[19])
        assert pd.notna(features["momentum_20"].iloc[20])

    def test_timestamp_alignment_preserved(self) -> None:
        df = make_synthetic_ohlcv(700, seed=5)
        features = build_feature_matrix(df)
        assert (features.index == df.index).all()

    def test_deterministic_repeatability(self) -> None:
        df = make_synthetic_ohlcv(700, seed=6)
        first = build_feature_matrix(df)
        second = build_feature_matrix(df)
        pd.testing.assert_frame_equal(first, second)

    def test_volatility_regime_is_ordinal_zero_one_two(self) -> None:
        df = make_synthetic_ohlcv(1200, seed=7)
        features = build_feature_matrix(df)
        valid = features["volatility_regime"].dropna()
        assert set(valid.unique()).issubset({0.0, 1.0, 2.0})

    def test_volatility_regime_uses_only_past_atr(self) -> None:
        atr = pd.Series(np.linspace(0.001, 0.002, 600), index=pd.date_range("2020-01-01", periods=600, freq="h", tz="UTC"))
        regime = compute_volatility_regime(atr)
        # Truncating the tail must not change earlier values (causality check).
        truncated_regime = compute_volatility_regime(atr.iloc[:550])
        pd.testing.assert_series_equal(regime.iloc[:550], truncated_regime, check_names=False)

    def test_get_feature_schema_matches_module_constants(self) -> None:
        schema = get_feature_schema()
        assert schema["feature_version"] == FEATURE_VERSION
        assert schema["feature_order"] == FEATURE_ORDER
        assert schema["warmup_bars"] == WARMUP_BARS


class TestFeatureInputValidation:
    def test_missing_ohlcv_columns_raises(self) -> None:
        df = make_synthetic_ohlcv(50, seed=8).drop(columns=["high"])
        with pytest.raises(FeatureEngineeringError):
            build_feature_matrix(df)

    def test_non_datetime_index_raises(self) -> None:
        df = make_synthetic_ohlcv(50, seed=9).reset_index(drop=True)
        with pytest.raises(FeatureEngineeringError):
            build_feature_matrix(df)

    def test_duplicate_timestamps_raise(self) -> None:
        df = make_synthetic_ohlcv(50, seed=10)
        bad = pd.concat([df, df.iloc[[0]]]).sort_index()
        with pytest.raises(FeatureEngineeringError):
            build_feature_matrix(bad)

    def test_non_monotonic_timestamps_raise(self) -> None:
        df = make_synthetic_ohlcv(50, seed=11)
        shuffled = df.iloc[np.random.default_rng(0).permutation(len(df))]
        with pytest.raises(FeatureEngineeringError):
            build_feature_matrix(shuffled)
