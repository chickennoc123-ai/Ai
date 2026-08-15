"""Tests for the indicator library."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.indicators import (
    adx,
    atr,
    bollinger_bands,
    cci,
    donchian_channel,
    ema,
    ichimoku,
    keltner_channel,
    macd,
    realized_volatility,
    rsi,
    sma,
    stochastic,
    supertrend,
    true_range,
    zscore,
)


def test_sma_matches_manual_mean(ohlcv: pd.DataFrame) -> None:
    """SMA equals the rolling arithmetic mean."""
    result = sma(ohlcv["close"], 10)
    expected = ohlcv["close"].rolling(10).mean()
    pd.testing.assert_series_equal(result.dropna(), expected.dropna())


def test_sma_warmup_is_nan(ohlcv: pd.DataFrame) -> None:
    """The first ``period - 1`` values are undefined."""
    result = sma(ohlcv["close"], 20)
    assert result.iloc[:19].isna().all()
    assert not np.isnan(result.iloc[19])


def test_rsi_is_bounded(ohlcv: pd.DataFrame) -> None:
    """RSI always sits inside [0, 100]."""
    values = rsi(ohlcv["close"], 14).dropna()
    assert len(values) > 100
    assert values.between(0, 100).all()


def test_rsi_of_monotonic_series_is_high() -> None:
    """A strictly rising series pins the RSI near 100."""
    series = pd.Series(np.linspace(1.0, 2.0, 100))
    assert rsi(series, 14).iloc[-1] > 95


def test_rsi_of_falling_series_is_low() -> None:
    """A strictly falling series pins the RSI near 0."""
    series = pd.Series(np.linspace(2.0, 1.0, 100))
    assert rsi(series, 14).iloc[-1] < 5


def test_macd_histogram_is_difference(ohlcv: pd.DataFrame) -> None:
    """The histogram is the MACD line minus the signal line."""
    line, signal, histogram = macd(ohlcv["close"])
    pd.testing.assert_series_equal(histogram.dropna(), (line - signal).dropna(), check_names=False)


def test_bollinger_band_ordering(ohlcv: pd.DataFrame) -> None:
    """Upper >= middle >= lower everywhere the bands are defined."""
    upper, middle, lower = bollinger_bands(ohlcv["close"], 20, 2.0)
    frame = pd.concat([upper, middle, lower], axis=1).dropna()
    assert (frame.iloc[:, 0] >= frame.iloc[:, 1]).all()
    assert (frame.iloc[:, 1] >= frame.iloc[:, 2]).all()


def test_true_range_is_non_negative(ohlcv: pd.DataFrame) -> None:
    """True range can never be negative."""
    assert (true_range(ohlcv["high"], ohlcv["low"], ohlcv["close"]).dropna() >= 0).all()


def test_atr_is_positive(ohlcv: pd.DataFrame) -> None:
    """ATR is strictly positive on real price action."""
    values = atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14).dropna()
    assert (values > 0).all()


def test_adx_components_are_bounded(ohlcv: pd.DataFrame) -> None:
    """ADX and the directional indices stay within [0, 100]."""
    adx_values, plus_di, minus_di = adx(ohlcv["high"], ohlcv["low"], ohlcv["close"])
    for series in (adx_values, plus_di, minus_di):
        clean = series.dropna()
        assert clean.between(0, 100).all()


def test_stochastic_is_bounded(ohlcv: pd.DataFrame) -> None:
    """The stochastic oscillator stays within [0, 100]."""
    percent_k, percent_d = stochastic(ohlcv["high"], ohlcv["low"], ohlcv["close"])
    assert percent_k.dropna().between(0, 100).all()
    assert percent_d.dropna().between(0, 100).all()


def test_donchian_contains_price(ohlcv: pd.DataFrame) -> None:
    """Price never leaves its own Donchian channel."""
    upper, _, lower = donchian_channel(ohlcv["high"], ohlcv["low"], 20)
    frame = pd.concat([upper, lower, ohlcv["close"]], axis=1).dropna()
    assert (frame.iloc[:, 0] >= frame.iloc[:, 2]).all()
    assert (frame.iloc[:, 1] <= frame.iloc[:, 2]).all()


def test_keltner_channel_ordering(ohlcv: pd.DataFrame) -> None:
    """Keltner bands are correctly ordered."""
    upper, basis, lower = keltner_channel(ohlcv["high"], ohlcv["low"], ohlcv["close"])
    frame = pd.concat([upper, basis, lower], axis=1).dropna()
    assert (frame.iloc[:, 0] > frame.iloc[:, 1]).all()
    assert (frame.iloc[:, 1] > frame.iloc[:, 2]).all()


def test_ichimoku_spans_are_lagged(ohlcv: pd.DataFrame) -> None:
    """Leading spans are shifted forward, so early values are undefined."""
    components = ichimoku(ohlcv["high"], ohlcv["low"], ohlcv["close"])
    assert components["senkou_a"].iloc[:26].isna().all()
    assert set(components) == {"tenkan", "kijun", "senkou_a", "senkou_b", "chikou"}


def test_supertrend_direction_is_signed(ohlcv: pd.DataFrame) -> None:
    """SuperTrend direction only takes the values -1 and +1."""
    _, direction = supertrend(ohlcv["high"], ohlcv["low"], ohlcv["close"])
    assert set(direction.dropna().unique()).issubset({-1.0, 1.0})


def test_cci_reacts_to_extremes(ohlcv: pd.DataFrame) -> None:
    """CCI produces both positive and negative excursions."""
    values = cci(ohlcv["high"], ohlcv["low"], ohlcv["close"]).dropna()
    assert values.max() > 0 > values.min()


def test_zscore_is_centred(ohlcv: pd.DataFrame) -> None:
    """The rolling z-score has approximately zero mean."""
    values = zscore(ohlcv["close"], 50).dropna()
    assert abs(float(values.mean())) < 0.5


def test_realized_volatility_is_positive(ohlcv: pd.DataFrame) -> None:
    """Annualised realised volatility is positive and plausible."""
    values = realized_volatility(ohlcv["close"], 20, 252 * 24).dropna()
    assert (values > 0).all()
    assert float(values.median()) < 1.0


def test_ema_reacts_faster_than_sma(ohlcv: pd.DataFrame) -> None:
    """After a jump the EMA is closer to price than the SMA."""
    series = pd.concat([ohlcv["close"].iloc[:100], ohlcv["close"].iloc[:100] * 1.05])
    series = series.reset_index(drop=True)
    fast, slow = ema(series, 20).iloc[-1], sma(series, 20).iloc[-1]
    assert abs(series.iloc[-1] - fast) < abs(series.iloc[-1] - slow)


@pytest.mark.parametrize("period", [5, 14, 50])
def test_indicators_align_to_index(ohlcv: pd.DataFrame, period: int) -> None:
    """Indicators keep the input index for any period."""
    assert rsi(ohlcv["close"], period).index.equals(ohlcv.index)
    assert atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], period).index.equals(ohlcv.index)
