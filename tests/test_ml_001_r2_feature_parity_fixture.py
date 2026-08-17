"""Canonical FE-R2-002 feature-vector parity fixture.

A single, fixed synthetic OHLC series with independently-computed
expected values for all five ML-001-R2 features (momentum_5,
momentum_20, rsi_14, atr_14, volatility_regime). This fixture is
committed as a permanent numerical parity oracle: any future change to
feature computation (intentional or accidental) that alters output
values will be caught here, at specific known points, independent of
the production code path.

Expected values are computed by dedicated, from-scratch reimplementations
in this file — never by calling core.features.fe_r2_001's own functions
to generate their own "expected" output.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.features.fe_r2_001 import FEATURE_ORDER, build_feature_matrix


def _make_canonical_ohlc(n_bars: int = 700, seed: int = 20260817) -> pd.DataFrame:
    """Fixed, deterministic synthetic OHLC series — the canonical fixture."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2021-06-07", periods=n_bars, freq="h", tz="UTC")  # a Monday

    log_returns = rng.normal(loc=0.0, scale=0.0005, size=n_bars)
    close = 1.1000 * np.exp(np.cumsum(log_returns))

    open_ = np.empty(n_bars)
    open_[0] = 1.1000
    open_[1:] = close[:-1]

    intrabar_range = np.abs(rng.normal(loc=0.0003, scale=0.00015, size=n_bars))
    high = np.maximum(open_, close) + intrabar_range
    low = np.minimum(open_, close) - intrabar_range

    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=index)


def _oracle_momentum(close: np.ndarray, t: int, lookback: int) -> float:
    return (close[t] - close[t - lookback]) / close[t - lookback]


def _oracle_rsi_14(closes: np.ndarray) -> np.ndarray:
    n = len(closes)
    deltas = np.full(n, np.nan)
    deltas[1:] = closes[1:] - closes[:-1]
    gains = np.where(np.isnan(deltas), np.nan, np.maximum(deltas, 0.0))
    losses = np.where(np.isnan(deltas), np.nan, np.maximum(-deltas, 0.0))

    out = np.full(n, np.nan)
    if n < 15:
        return out
    avg_gain = np.mean(gains[1:15])
    avg_loss = np.mean(losses[1:15])

    def _rsi(ag, al):
        if al == 0.0 and ag == 0.0:
            return 50.0
        if al == 0.0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + ag / al)

    out[14] = _rsi(avg_gain, avg_loss)
    for t in range(15, n):
        avg_gain = (avg_gain * 13 + gains[t]) / 14.0
        avg_loss = (avg_loss * 13 + losses[t]) / 14.0
        out[t] = _rsi(avg_gain, avg_loss)
    return out


def _oracle_atr_14(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    n = len(high)
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for t in range(1, n):
        tr[t] = max(high[t] - low[t], abs(high[t] - close[t - 1]), abs(low[t] - close[t - 1]))

    out = np.full(n, np.nan)
    if n < 14:
        return out
    avg_tr = np.mean(tr[0:14])
    out[13] = avg_tr
    for t in range(14, n):
        avg_tr = (avg_tr * 13 + tr[t]) / 14.0
        out[t] = avg_tr
    return out


def _oracle_volatility_regime(atr: np.ndarray, t: int, window: int = 500) -> float:
    """Independent percentile computation via numpy, not pandas .rolling()."""
    segment = atr[t - window + 1 : t + 1]
    if np.isnan(segment).any() or len(segment) < window:
        return np.nan
    p33 = np.percentile(segment, 33, method="linear")
    p67 = np.percentile(segment, 67, method="linear")
    if atr[t] < p33:
        return 0.0
    if atr[t] > p67:
        return 2.0
    return 1.0


class TestCanonicalFeatureVectorFixture:
    """The permanent numerical parity oracle."""

    def test_momentum_features_at_known_points(self) -> None:
        df = _make_canonical_ohlc()
        features = build_feature_matrix(df)
        close = df["close"].to_numpy()

        for t in [5, 20, 100, 350, 699]:
            expected_5 = _oracle_momentum(close, t, 5)
            assert features["momentum_5"].iloc[t] == pytest.approx(expected_5, abs=1e-12)
        for t in [20, 100, 350, 699]:
            expected_20 = _oracle_momentum(close, t, 20)
            assert features["momentum_20"].iloc[t] == pytest.approx(expected_20, abs=1e-12)

    def test_rsi_14_matches_independent_oracle_at_known_points(self) -> None:
        df = _make_canonical_ohlc()
        features = build_feature_matrix(df)
        expected = _oracle_rsi_14(df["close"].to_numpy())

        # Points inside the 100-bar warmup mask must be NaN in the feature
        # output even though the raw oracle has a defined value there.
        assert pd.isna(features["rsi_14"].iloc[50])
        assert not np.isnan(expected[50])  # raw computation was defined, warmup masks it

        for t in [100, 150, 300, 500, 699]:
            assert features["rsi_14"].iloc[t] == pytest.approx(expected[t], abs=1e-9)

    def test_atr_14_matches_independent_oracle_at_known_points(self) -> None:
        df = _make_canonical_ohlc()
        features = build_feature_matrix(df)
        expected = _oracle_atr_14(df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy())

        assert pd.isna(features["atr_14"].iloc[50])
        assert not np.isnan(expected[50])

        for t in [100, 150, 300, 500, 699]:
            assert features["atr_14"].iloc[t] == pytest.approx(expected[t], abs=1e-9)

    def test_volatility_regime_matches_independent_oracle_at_known_points(self) -> None:
        df = _make_canonical_ohlc()
        features = build_feature_matrix(df)
        atr_oracle = _oracle_atr_14(df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy())

        for t in [600, 650, 699]:
            expected = _oracle_volatility_regime(atr_oracle, t)
            assert features["volatility_regime"].iloc[t] == pytest.approx(expected, abs=1e-12)

        assert pd.isna(features["volatility_regime"].iloc[599])

    def test_full_feature_vector_at_a_single_representative_bar(self) -> None:
        """Cross-check all five features simultaneously at one bar, tying
        the whole fixture together as a single reproducible snapshot."""
        df = _make_canonical_ohlc()
        features = build_feature_matrix(df)
        t = 650

        close = df["close"].to_numpy()
        rsi_oracle = _oracle_rsi_14(df["close"].to_numpy())
        atr_oracle = _oracle_atr_14(df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy())
        vr_oracle = _oracle_volatility_regime(atr_oracle, t)

        expected_vector = [
            _oracle_momentum(close, t, 5),
            _oracle_momentum(close, t, 20),
            rsi_oracle[t],
            atr_oracle[t],
            vr_oracle,
        ]
        actual_vector = features.iloc[t][FEATURE_ORDER].tolist()

        for name, expected, actual in zip(FEATURE_ORDER, expected_vector, actual_vector):
            assert actual == pytest.approx(expected, abs=1e-9), f"{name} mismatch at t={t}"

    def test_fixture_is_deterministic_across_regeneration(self) -> None:
        """The fixture generator itself must be deterministic (fixed seed)
        so this oracle is stable across test runs and CI machines."""
        df_a = _make_canonical_ohlc()
        df_b = _make_canonical_ohlc()
        pd.testing.assert_frame_equal(df_a, df_b)
