"""FE-R2-001: canonical feature engineering for ML-001-R2.

Single source of truth for the five ML-001-R2 features. Per
``ML-001-R2-CLEAN-REBUILD-SPEC.md`` Section 4 and Section 12
(FEATURE_PARITY), this module must be the *only* place these features
are computed — research, backtest, and production inference all import
it directly; no second implementation is permitted.

Nothing here is inherited from old ML-001. ``volatility_regime`` in
particular never had any formula in the old codebase; the definition
below is new construction, not recovered history.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from core.indicators import atr as wilder_atr
from core.indicators import rsi as wilder_rsi
from utils.exceptions import EAFactoryError

FEATURE_VERSION = "FE-R2-001"

#: Fixed feature vector order. Any reordering requires a new feature_version.
FEATURE_ORDER: List[str] = [
    "momentum_5",
    "momentum_20",
    "rsi_14",
    "atr_14",
    "volatility_regime",
]

#: Bars that must elapse (from the start of the series) before a feature's
#: value is usable for training or live inference. Positions before this
#: index are forced to NaN even if the underlying rolling/ewm computation
#: is already numerically defined (see spec Section 4, RSI/ATR burn-in and
#: the 500-bar volatility_regime percentile window).
WARMUP_BARS: Dict[str, int] = {
    "momentum_5": 5,
    "momentum_20": 20,
    "rsi_14": 100,
    "atr_14": 100,
    "volatility_regime": 600,
}

_VOLATILITY_REGIME_WINDOW = 500
_VOLATILITY_REGIME_LOW_QUANTILE = 0.33
_VOLATILITY_REGIME_HIGH_QUANTILE = 0.67

REQUIRED_OHLCV_COLUMNS = ("open", "high", "low", "close")


class FeatureEngineeringError(EAFactoryError):
    """Raised when input data or computed features violate FE-R2-001."""


def _validate_ohlcv(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_OHLCV_COLUMNS if c not in df.columns]
    if missing:
        raise FeatureEngineeringError(
            "OHLCV frame missing required columns", missing_columns=missing
        )
    if not isinstance(df.index, pd.DatetimeIndex):
        raise FeatureEngineeringError(
            "OHLCV frame must be indexed by a DatetimeIndex", index_type=type(df.index).__name__
        )
    if df.index.has_duplicates:
        dupes = df.index[df.index.duplicated()].tolist()
        raise FeatureEngineeringError(
            "OHLCV frame contains duplicate timestamps", duplicate_count=len(dupes)
        )
    if not df.index.is_monotonic_increasing:
        raise FeatureEngineeringError("OHLCV frame timestamps must be strictly increasing")


def compute_momentum(close: pd.Series, lookback: int) -> pd.Series:
    """Percentage return over ``lookback`` bars: ``(close[t]-close[t-n])/close[t-n]``."""
    prior = close.shift(lookback)
    with np.errstate(divide="ignore", invalid="ignore"):
        result = (close - prior) / prior
    return result.replace([np.inf, -np.inf], np.nan)


def compute_rsi_14(close: pd.Series) -> pd.Series:
    """Wilder RSI(14). Delegates to the existing, tested ``core.indicators.rsi``."""
    return wilder_rsi(close, period=14)


def compute_atr_14(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Wilder ATR(14). Delegates to the existing, tested ``core.indicators.atr``."""
    return wilder_atr(high, low, close, period=14)


def compute_volatility_regime(atr_14: pd.Series) -> pd.Series:
    """Ordinal 3-class regime label from ``atr_14``'s trailing percentile.

    0 = LOW  (atr_14 < trailing 33rd percentile)
    1 = NORMAL
    2 = HIGH (atr_14 > trailing 67th percentile)

    The percentile window is strictly causal: it only uses bars up to and
    including ``t`` (pandas rolling window, right-aligned).
    """
    p_low = atr_14.rolling(
        window=_VOLATILITY_REGIME_WINDOW, min_periods=_VOLATILITY_REGIME_WINDOW
    ).quantile(_VOLATILITY_REGIME_LOW_QUANTILE)
    p_high = atr_14.rolling(
        window=_VOLATILITY_REGIME_WINDOW, min_periods=_VOLATILITY_REGIME_WINDOW
    ).quantile(_VOLATILITY_REGIME_HIGH_QUANTILE)

    regime = pd.Series(1.0, index=atr_14.index)
    regime = regime.mask(atr_14 < p_low, 0.0)
    regime = regime.mask(atr_14 > p_high, 2.0)

    valid = atr_14.notna() & p_low.notna() & p_high.notna()
    return regime.where(valid, np.nan)


def _apply_warmup(series: pd.Series, warmup_bars: int) -> pd.Series:
    """Force the first ``warmup_bars`` positions of ``series`` to NaN."""
    out = series.copy()
    out.iloc[:warmup_bars] = np.nan
    return out


def build_feature_matrix(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Compute the full FE-R2-001 feature matrix for an OHLCV frame.

    Args:
        ohlcv: DataFrame indexed by a strictly increasing, duplicate-free
            ``DatetimeIndex`` with at least ``open``, ``high``, ``low``,
            ``close`` columns.

    Returns:
        DataFrame with columns in ``FEATURE_ORDER``, aligned to
        ``ohlcv.index``, with warmup positions set to NaN.

    Raises:
        FeatureEngineeringError: If the input frame is malformed.
    """
    _validate_ohlcv(ohlcv)

    close = ohlcv["close"]
    high = ohlcv["high"]
    low = ohlcv["low"]

    atr_14 = compute_atr_14(high, low, close)

    raw = {
        "momentum_5": compute_momentum(close, 5),
        "momentum_20": compute_momentum(close, 20),
        "rsi_14": compute_rsi_14(close),
        "atr_14": atr_14,
        "volatility_regime": compute_volatility_regime(atr_14),
    }

    columns = {
        name: _apply_warmup(raw[name], WARMUP_BARS[name]) for name in FEATURE_ORDER
    }
    return pd.DataFrame(columns, index=ohlcv.index)[FEATURE_ORDER]


def get_feature_schema() -> Dict[str, object]:
    """Machine-readable FE-R2-001 schema for provenance manifests."""
    return {
        "feature_version": FEATURE_VERSION,
        "feature_order": list(FEATURE_ORDER),
        "warmup_bars": dict(WARMUP_BARS),
        "definitions": {
            "momentum_5": "(close[t]-close[t-5])/close[t-5]",
            "momentum_20": "(close[t]-close[t-20])/close[t-20]",
            "rsi_14": "Wilder RSI, period=14, seeded via ewm(alpha=1/14, adjust=False)",
            "atr_14": "Wilder ATR of True Range, period=14",
            "volatility_regime": (
                "ordinal {0,1,2} from atr_14 vs. trailing 500-bar 33rd/67th percentile"
            ),
        },
    }
