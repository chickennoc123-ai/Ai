"""Vectorised technical indicator library.

All functions operate on :mod:`pandas` objects and return objects aligned to
the input index, so they can be composed inside strategies without look-ahead
bias.  No third-party TA dependency is required.
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "adx",
    "aroon",
    "atr",
    "bollinger_bands",
    "cci",
    "donchian_channel",
    "ema",
    "ichimoku",
    "keltner_channel",
    "macd",
    "momentum",
    "obv",
    "realized_volatility",
    "roc",
    "rsi",
    "sma",
    "stochastic",
    "supertrend",
    "true_range",
    "vwap",
    "wma",
    "zscore",
    "compute_indicator_set",
]


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average (Wilder-compatible ``adjust=False``)."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def wma(series: pd.Series, period: int) -> pd.Series:
    """Linearly weighted moving average."""
    weights = np.arange(1, period + 1, dtype="float64")

    def _apply(window: np.ndarray) -> float:
        return float(np.dot(window, weights) / weights.sum())

    return series.rolling(window=period, min_periods=period).apply(_apply, raw=True)


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing.

    Args:
        series: Close price series.
        period: Lookback window.

    Returns:
        RSI values in ``[0, 100]``.
    """
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    # A zero average loss makes RS infinite, which correctly yields RSI = 100;
    # only a completely flat series (no gains and no losses) is neutral at 50.
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
    result = 100.0 - (100.0 / (1.0 + rs))
    return result.mask((avg_gain == 0.0) & (avg_loss == 0.0), 50.0)


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Moving Average Convergence Divergence.

    Returns:
        Tuple of ``(macd_line, signal_line, histogram)``.
    """
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return macd_line, signal_line, macd_line - signal_line


def bollinger_bands(
    series: pd.Series, period: int = 20, num_std: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands.

    Returns:
        Tuple of ``(upper, middle, lower)``.
    """
    middle = sma(series, period)
    deviation = series.rolling(window=period, min_periods=period).std(ddof=0)
    return middle + num_std * deviation, middle, middle - num_std * deviation


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Wilder's True Range."""
    previous_close = close.shift(1)
    ranges = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    )
    return ranges.max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range with Wilder smoothing."""
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Average Directional Index.

    Returns:
        Tuple of ``(adx, plus_di, minus_di)``.
    """
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)
    atr_values = atr(high, low, close, period)
    safe_atr = atr_values.replace(0.0, np.nan)
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / safe_atr
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean() / safe_atr
    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx_values = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    return adx_values, plus_di, minus_di


def stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3, smooth: int = 3
) -> Tuple[pd.Series, pd.Series]:
    """Stochastic oscillator.

    Returns:
        Tuple of ``(%K, %D)``.
    """
    lowest = low.rolling(window=k_period, min_periods=k_period).min()
    highest = high.rolling(window=k_period, min_periods=k_period).max()
    span = (highest - lowest).replace(0.0, np.nan)
    raw_k = 100.0 * (close - lowest) / span
    percent_k = raw_k.rolling(window=smooth, min_periods=smooth).mean()
    percent_d = percent_k.rolling(window=d_period, min_periods=d_period).mean()
    return percent_k, percent_d


def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    """Commodity Channel Index."""
    typical = (high + low + close) / 3.0
    moving = typical.rolling(window=period, min_periods=period).mean()
    deviation = (typical - moving).abs().rolling(window=period, min_periods=period).mean()
    return (typical - moving) / (0.015 * deviation.replace(0.0, np.nan))


def roc(series: pd.Series, period: int = 12) -> pd.Series:
    """Rate of change in percent."""
    return 100.0 * (series / series.shift(period) - 1.0)


def momentum(series: pd.Series, period: int = 10) -> pd.Series:
    """Absolute price momentum."""
    return series - series.shift(period)


def aroon(high: pd.Series, low: pd.Series, period: int = 25) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Aroon Up/Down and the Aroon oscillator."""
    def _since_extreme(window: np.ndarray, take_max: bool) -> float:
        index = int(np.argmax(window)) if take_max else int(np.argmin(window))
        return 100.0 * index / (len(window) - 1) if len(window) > 1 else 0.0

    aroon_up = high.rolling(window=period + 1, min_periods=period + 1).apply(
        lambda window: _since_extreme(window, True), raw=True
    )
    aroon_down = low.rolling(window=period + 1, min_periods=period + 1).apply(
        lambda window: _since_extreme(window, False), raw=True
    )
    return aroon_up, aroon_down, aroon_up - aroon_down


def keltner_channel(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20, multiplier: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Keltner Channels built on an EMA basis and ATR width."""
    basis = ema(close, period)
    width = multiplier * atr(high, low, close, period)
    return basis + width, basis, basis - width


def donchian_channel(high: pd.Series, low: pd.Series, period: int = 20) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Donchian Channels (rolling highest high / lowest low)."""
    upper = high.rolling(window=period, min_periods=period).max()
    lower = low.rolling(window=period, min_periods=period).min()
    return upper, (upper + lower) / 2.0, lower


def ichimoku(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    conversion: int = 9,
    base: int = 26,
    span_b: int = 52,
    displacement: int = 26,
) -> Dict[str, pd.Series]:
    """Ichimoku Kinko Hyo components.

    Returns:
        Mapping with ``tenkan``, ``kijun``, ``senkou_a``, ``senkou_b`` and
        ``chikou`` series. Leading spans are shifted forward by
        ``displacement`` bars, so comparisons against price are lag-free.
    """
    def _midpoint(period: int) -> pd.Series:
        return (
            high.rolling(window=period, min_periods=period).max()
            + low.rolling(window=period, min_periods=period).min()
        ) / 2.0

    tenkan = _midpoint(conversion)
    kijun = _midpoint(base)
    senkou_a = ((tenkan + kijun) / 2.0).shift(displacement)
    senkou_b = _midpoint(span_b).shift(displacement)
    chikou = close.shift(-displacement)
    return {
        "tenkan": tenkan,
        "kijun": kijun,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b,
        "chikou": chikou,
    }


def supertrend(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 10, multiplier: float = 3.0
) -> Tuple[pd.Series, pd.Series]:
    """SuperTrend line and its direction (+1 bullish, -1 bearish)."""
    atr_values = atr(high, low, close, period)
    hl2 = (high + low) / 2.0
    upper = (hl2 + multiplier * atr_values).to_numpy(dtype="float64", copy=True)
    lower = (hl2 - multiplier * atr_values).to_numpy(dtype="float64", copy=True)
    close_values = close.to_numpy(dtype="float64", copy=True)
    length = len(close_values)
    trend = np.ones(length)
    line = np.full(length, np.nan)
    for i in range(1, length):
        if np.isnan(upper[i]) or np.isnan(lower[i]):
            continue
        upper[i] = min(upper[i], upper[i - 1]) if close_values[i - 1] <= upper[i - 1] and not np.isnan(upper[i - 1]) else upper[i]
        lower[i] = max(lower[i], lower[i - 1]) if close_values[i - 1] >= lower[i - 1] and not np.isnan(lower[i - 1]) else lower[i]
        if close_values[i] > upper[i - 1]:
            trend[i] = 1.0
        elif close_values[i] < lower[i - 1]:
            trend[i] = -1.0
        else:
            trend[i] = trend[i - 1]
        line[i] = lower[i] if trend[i] > 0 else upper[i]
    return pd.Series(line, index=close.index), pd.Series(trend, index=close.index)


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = np.sign(close.diff().fillna(0.0))
    return (direction * volume.fillna(0.0)).cumsum()


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """Rolling cumulative Volume Weighted Average Price."""
    typical = (high + low + close) / 3.0
    cumulative_volume = volume.fillna(0.0).cumsum().replace(0.0, np.nan)
    return (typical * volume.fillna(0.0)).cumsum() / cumulative_volume


def zscore(series: pd.Series, period: int = 20) -> pd.Series:
    """Rolling z-score of a series."""
    mean = series.rolling(window=period, min_periods=period).mean()
    std = series.rolling(window=period, min_periods=period).std(ddof=0).replace(0.0, np.nan)
    return (series - mean) / std


def realized_volatility(close: pd.Series, period: int = 20, annualisation: float = 252.0) -> pd.Series:
    """Annualised rolling realised volatility of log returns."""
    log_returns = np.log(close / close.shift(1))
    return log_returns.rolling(window=period, min_periods=period).std(ddof=0) * np.sqrt(annualisation)


def compute_indicator_set(df: pd.DataFrame, names: Tuple[str, ...] | list[str]) -> pd.DataFrame:
    """Attach a named set of indicators to an OHLCV frame.

    Args:
        df: Frame containing ``open``/``high``/``low``/``close``/``volume``.
        names: Indicator keys, e.g. ``["rsi", "macd", "bb", "atr", "adx"]``.

    Returns:
        A copy of ``df`` with indicator columns appended.
    """
    out = df.copy()
    high, low, close = out["high"], out["low"], out["close"]
    volume = out["volume"] if "volume" in out else pd.Series(1.0, index=out.index)
    wanted = {name.lower() for name in names}

    if "rsi" in wanted:
        out["rsi"] = rsi(close)
    if "macd" in wanted:
        out["macd"], out["macd_signal"], out["macd_hist"] = macd(close)
    if "bb" in wanted:
        out["bb_upper"], out["bb_middle"], out["bb_lower"] = bollinger_bands(close)
    if "sma" in wanted:
        out["sma_fast"], out["sma_slow"] = sma(close, 20), sma(close, 50)
    if "ema" in wanted:
        out["ema_fast"], out["ema_slow"] = ema(close, 12), ema(close, 26)
    if "atr" in wanted:
        out["atr"] = atr(high, low, close)
    if "adx" in wanted:
        out["adx"], out["plus_di"], out["minus_di"] = adx(high, low, close)
    if "stoch" in wanted:
        out["stoch_k"], out["stoch_d"] = stochastic(high, low, close)
    if "cci" in wanted:
        out["cci"] = cci(high, low, close)
    if "obv" in wanted:
        out["obv"] = obv(close, volume)
    if "vwap" in wanted:
        out["vwap"] = vwap(high, low, close, volume)
    return out
