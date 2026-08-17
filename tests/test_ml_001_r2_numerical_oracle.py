"""CANONICAL_NUMERICAL_ORACLE tests for rsi_14/atr_14 (spec Section 4,
post-M-5 amendment).

Every expected value in this file is computed independently — either by
hand (documented inline) or via a from-scratch reimplementation of the
seeded-Wilder recurrence written directly in each test (never by
importing and calling ``_seeded_wilder_smooth`` or the production
``compute_rsi_14``/``compute_atr_14`` functions to generate its own
"expected" value). This is deliberate: an oracle that calls the
implementation under test to produce its own expected value is not
independent and cannot catch a defect the implementation shares with
itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.features.fe_r2_001 import (
    WilderSmoothingError,
    compute_atr_14,
    compute_rsi_14,
)


class TestRSIWorkedTextbookExample:
    """A classic, independently-hand-computable 15-bar RSI example.

    Closes: 44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
            45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28

    Hand-derived gains/losses (delta[t] = close[t]-close[t-1]):
      t=1: -0.25  -> loss=0.25
      t=2: +0.06  -> gain=0.06 (0.05999999999999517 in float64)
      t=3: -0.54  -> loss=0.54 (0.5399999999999991)
      t=4: +0.72  -> gain=0.72
      t=5: +0.50  -> gain=0.50
      t=6: +0.27  -> gain=0.27
      t=7: +0.32  -> gain=0.32
      t=8: +0.42  -> gain=0.42
      t=9: +0.24  -> gain=0.24
      t=10: -0.19 -> loss=0.19
      t=11: +0.14 -> gain=0.14
      t=12: -0.42 -> loss=0.42
      t=13: +0.67 -> gain=0.67
      t=14: 0.00  -> neither

    Seed (mean of gain[1..14], loss[1..14], 14 values each):
      avg_gain_seed = (0+0.06+0+0.72+0.50+0.27+0.32+0.42+0.24+0+0.14+0+0.67+0)/14
                     = 3.34/14 = 0.238571428571...
      avg_loss_seed = (0.25+0+0.54+0+0+0+0+0+0+0.19+0+0.42+0+0)/14
                     = 1.40/14 = 0.1

      RS  = 0.238571428571.../0.1 = 2.38571428571...
      RSI = 100 - 100/(1+RS) = 100 - 100/3.38571428571... = 70.46413502109705
    """

    CLOSES = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
              45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]

    def test_first_valid_rsi_value_matches_hand_calculation(self) -> None:
        close = pd.Series(self.CLOSES)
        rsi = compute_rsi_14(close)
        assert rsi.iloc[:14].isna().all()
        assert rsi.iloc[14] == pytest.approx(70.46413502109705, abs=1e-9)

    def test_series_beyond_seed_is_undefined_with_only_15_bars(self) -> None:
        """Only one post-seed bar's worth of data exists (index 14 is the
        seed itself); nothing beyond it to verify recurrence continuation
        in this fixture — covered by the independent-reimplementation
        tests below instead, which extend further."""
        close = pd.Series(self.CLOSES)
        rsi = compute_rsi_14(close)
        assert len(rsi) == 15


class TestIndependentReimplementationOracle:
    """A from-scratch, independent Python reimplementation of the seeded
    Wilder recurrence (NOT calling _seeded_wilder_smooth), used as the
    oracle for longer synthetic series across multiple market regimes."""

    @staticmethod
    def _oracle_rsi(closes: list) -> list:
        """Independent reimplementation — deliberately not sharing any
        code with core/features/fe_r2_001.py."""
        n = len(closes)
        deltas = [None] + [closes[i] - closes[i - 1] for i in range(1, n)]
        gains = [None] + [max(d, 0.0) for d in deltas[1:]]
        losses = [None] + [max(-d, 0.0) for d in deltas[1:]]

        rsi = [None] * n
        if n < 15:
            return rsi

        avg_gain = sum(gains[1:15]) / 14.0
        avg_loss = sum(losses[1:15]) / 14.0

        def _rsi_from(ag, al):
            if al == 0.0 and ag == 0.0:
                return 50.0
            if al == 0.0:
                return 100.0
            rs = ag / al
            return 100.0 - 100.0 / (1.0 + rs)

        rsi[14] = _rsi_from(avg_gain, avg_loss)
        for t in range(15, n):
            avg_gain = (avg_gain * 13 + gains[t]) / 14.0
            avg_loss = (avg_loss * 13 + losses[t]) / 14.0
            rsi[t] = _rsi_from(avg_gain, avg_loss)
        return rsi

    @staticmethod
    def _oracle_atr(highs: list, lows: list, closes: list) -> list:
        n = len(highs)
        tr = [None] * n
        tr[0] = highs[0] - lows[0]
        for t in range(1, n):
            tr[t] = max(
                highs[t] - lows[t],
                abs(highs[t] - closes[t - 1]),
                abs(lows[t] - closes[t - 1]),
            )
        atr = [None] * n
        if n < 14:
            return atr
        avg_tr = sum(tr[0:14]) / 14.0
        atr[13] = avg_tr
        for t in range(14, n):
            avg_tr = (avg_tr * 13 + tr[t]) / 14.0
            atr[t] = avg_tr
        return atr

    def test_monotonic_increasing_market_rsi(self) -> None:
        """Constant +1 per bar: gains constantly 1, losses constantly 0 ->
        RSI must be exactly 100 from the seed onward (RS -> infinity)."""
        closes = [100.0 + i for i in range(40)]
        expected = self._oracle_rsi(closes)
        actual = compute_rsi_14(pd.Series(closes))
        for t in range(14, 40):
            assert actual.iloc[t] == pytest.approx(expected[t], abs=1e-9)
            assert actual.iloc[t] == pytest.approx(100.0, abs=1e-9)

    def test_monotonic_decreasing_market_rsi(self) -> None:
        closes = [140.0 - i for i in range(40)]
        expected = self._oracle_rsi(closes)
        actual = compute_rsi_14(pd.Series(closes))
        for t in range(14, 40):
            assert actual.iloc[t] == pytest.approx(expected[t], abs=1e-9)
            assert actual.iloc[t] == pytest.approx(0.0, abs=1e-9)

    def test_flat_market_rsi_is_neutral_fifty(self) -> None:
        closes = [100.0] * 40
        expected = self._oracle_rsi(closes)
        actual = compute_rsi_14(pd.Series(closes))
        for t in range(14, 40):
            assert actual.iloc[t] == pytest.approx(expected[t], abs=1e-9)
            assert actual.iloc[t] == pytest.approx(50.0, abs=1e-9)

    def test_alternating_market_rsi(self) -> None:
        """+2, -1, +2, -1, ... pattern."""
        closes = [100.0]
        for i in range(59):
            closes.append(closes[-1] + (2.0 if i % 2 == 0 else -1.0))
        expected = self._oracle_rsi(closes)
        actual = compute_rsi_14(pd.Series(closes))
        for t in range(14, len(closes)):
            assert actual.iloc[t] == pytest.approx(expected[t], abs=1e-9)

    def test_random_walk_rsi_matches_independent_oracle_throughout(self) -> None:
        rng = np.random.default_rng(2024)
        closes = list(100.0 + np.cumsum(rng.normal(0, 0.5, 200)))
        expected = self._oracle_rsi(closes)
        actual = compute_rsi_14(pd.Series(closes))
        for t in range(14, 200):
            assert actual.iloc[t] == pytest.approx(expected[t], abs=1e-9), f"mismatch at t={t}"

    def test_atr_monotonic_market(self) -> None:
        closes = [100.0 + i for i in range(40)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        expected = self._oracle_atr(highs, lows, closes)
        actual = compute_atr_14(pd.Series(highs), pd.Series(lows), pd.Series(closes))
        for t in range(13, 40):
            assert actual.iloc[t] == pytest.approx(expected[t], abs=1e-9)

    def test_atr_flat_market_is_zero(self) -> None:
        closes = [100.0] * 40
        highs = list(closes)
        lows = list(closes)
        expected = self._oracle_atr(highs, lows, closes)
        actual = compute_atr_14(pd.Series(highs), pd.Series(lows), pd.Series(closes))
        for t in range(13, 40):
            assert actual.iloc[t] == pytest.approx(expected[t], abs=1e-9)
            assert actual.iloc[t] == pytest.approx(0.0, abs=1e-9)

    def test_atr_random_walk_matches_independent_oracle_throughout(self) -> None:
        rng = np.random.default_rng(2025)
        closes = list(100.0 + np.cumsum(rng.normal(0, 0.5, 200)))
        highs = [c + abs(rng.normal(0, 0.2)) for c in closes]
        lows = [c - abs(rng.normal(0, 0.2)) for c in closes]
        expected = self._oracle_atr(highs, lows, closes)
        actual = compute_atr_14(pd.Series(highs), pd.Series(lows), pd.Series(closes))
        for t in range(13, 200):
            assert actual.iloc[t] == pytest.approx(expected[t], abs=1e-9), f"mismatch at t={t}"


class TestWarmupAndInitialization:
    def test_rsi_first_valid_index_is_14(self) -> None:
        closes = [100.0 + 0.1 * i for i in range(30)]
        rsi = compute_rsi_14(pd.Series(closes))
        assert rsi.iloc[:14].isna().all()
        assert pd.notna(rsi.iloc[14])

    def test_atr_first_valid_index_is_13(self) -> None:
        """One bar earlier than RSI, since True Range[0] is defined
        (high[0]-low[0] fallback) while RSI's delta[0] is not."""
        closes = [100.0 + 0.1 * i for i in range(30)]
        highs = [c + 0.3 for c in closes]
        lows = [c - 0.3 for c in closes]
        atr = compute_atr_14(pd.Series(highs), pd.Series(lows), pd.Series(closes))
        assert atr.iloc[:13].isna().all()
        assert pd.notna(atr.iloc[13])

    def test_insufficient_history_rsi_all_nan(self) -> None:
        closes = [100.0 + i for i in range(10)]  # fewer than 15 bars
        rsi = compute_rsi_14(pd.Series(closes))
        assert rsi.isna().all()

    def test_insufficient_history_atr_all_nan(self) -> None:
        closes = [100.0 + i for i in range(10)]  # fewer than 14 bars
        highs = [c + 0.3 for c in closes]
        lows = [c - 0.3 for c in closes]
        atr = compute_atr_14(pd.Series(highs), pd.Series(lows), pd.Series(closes))
        assert atr.isna().all()

    def test_exactly_enough_history_produces_exactly_one_value(self) -> None:
        closes = [100.0 + i for i in range(15)]  # exactly 15 bars
        rsi = compute_rsi_14(pd.Series(closes))
        assert rsi.iloc[:14].isna().all()
        assert pd.notna(rsi.iloc[14])


class TestMissingDataHandling:
    def test_nan_within_seed_window_raises(self) -> None:
        closes = [100.0 + i for i in range(30)]
        closes[5] = float("nan")
        with pytest.raises(WilderSmoothingError):
            compute_rsi_14(pd.Series(closes))

    def test_nan_after_seed_window_raises(self) -> None:
        closes = [100.0 + i for i in range(30)]
        closes[20] = float("nan")
        with pytest.raises(WilderSmoothingError):
            compute_rsi_14(pd.Series(closes))

    def test_atr_nan_within_seed_window_raises(self) -> None:
        """A NaN must appear in BOTH high and low at the same bar to
        propagate through True Range as NaN — see
        test_single_column_nan_is_silently_absorbed_by_true_range below
        for why a single-column NaN does not raise here."""
        closes = [100.0 + i for i in range(30)]
        highs = [c + 0.3 for c in closes]
        lows = [c - 0.3 for c in closes]
        highs[5] = float("nan")
        lows[5] = float("nan")
        with pytest.raises(WilderSmoothingError):
            compute_atr_14(pd.Series(highs), pd.Series(lows), pd.Series(closes))

    def test_single_column_nan_is_silently_absorbed_by_true_range(self) -> None:
        """Documented, disclosed, pre-existing property of the reused
        core.indicators.true_range function (not part of the M-5 formula
        ambiguity, and not modified by this remediation, per the explicit
        instruction not to touch code shared by unrelated strategies):
        pandas' `.max(axis=1)` defaults to skipna=True, so a NaN in only
        ONE of high[t]/low[t] does not make True Range NaN at that bar —
        it silently falls back to whichever of the three candidate terms
        is still defined, which may not equal the true (unknown) range.
        This is a real, disclosed limitation of the reused True Range
        computation, not a defect introduced by the seeded-Wilder
        smoothing fix. A single missing high or low price will not be
        caught by WilderSmoothingError; only a fully-missing bar (both
        high and low absent) will be."""
        closes = [100.0 + i for i in range(30)]
        highs = [c + 0.3 for c in closes]
        lows = [c - 0.3 for c in closes]
        highs[10] = float("nan")  # low[10] remains defined; position 10 is
        # inside the seed window (positions 0-13), so if the single-column
        # NaN propagated to True Range, the seed itself would raise
        # WilderSmoothingError. It must NOT raise -- the corrupted-but-
        # non-NaN TR[10] value is silently absorbed into the seed mean.
        atr = compute_atr_14(pd.Series(highs), pd.Series(lows), pd.Series(closes))
        assert pd.notna(atr.iloc[13])  # seed completed without raising
        assert atr.iloc[13:].notna().all()  # recurrence continues normally


class TestNumericalTolerance:
    """Explicit tolerance policy: spec requires float64 precision with no
    additional rounding. All comparisons in this file use abs=1e-9,
    tighter than any expected floating-point accumulation error over a
    200-bar recurrence (verified empirically: the random-walk oracle
    tests above match to this tolerance across 186 recurrence steps)."""

    def test_deterministic_repeatability_at_full_precision(self) -> None:
        closes = list(100.0 + np.cumsum(np.random.default_rng(9).normal(0, 0.5, 100)))
        first = compute_rsi_14(pd.Series(closes))
        second = compute_rsi_14(pd.Series(closes))
        pd.testing.assert_series_equal(first, second)  # bit-for-bit, not approx
