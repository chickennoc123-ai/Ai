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

from core.indicators import true_range
from utils.exceptions import EAFactoryError

# NOT the ML-001-R2 numerical oracle: core.indicators.rsi / core.indicators.atr
# remain in place, unmodified, ONLY because other strategies (the RSI
# strategy, MACD's ATR-based stop-loss sizing — see strategies/base_strategy.py,
# core/strategy.py) depend on their existing pandas-ewm-based behavior. They
# are intentionally NOT imported here. ML-001-R2's rsi_14/atr_14 use the
# CANONICAL_NUMERICAL_ORACLE defined below (_seeded_wilder_smooth), which is
# mathematically distinct from core.indicators.py's ewm(adjust=False)
# formulation (see ML-001-M5-FULL-REMEDIATION-REPORT.md for the empirical
# proof these two are not equivalent, contrary to what an earlier version of
# this spec incorrectly asserted).

#: Bumped from FE-R2-001 to FE-R2-002 per spec Section 2/16's immutability
#: rule: rsi_14/atr_14's smoothing formula changed (M-5 remediation — see
#: ML-001-M5-FULL-REMEDIATION-REPORT.md), which changes computed feature
#: values, which requires a new feature_version. Any artifact recorded
#: under FE-R2-001 used the old (spec-inconsistent) formula and is
#: automatically rejected by RFR2Model.load()'s feature_version check.
FEATURE_VERSION = "FE-R2-002"

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

#: H1 is this strategy's frozen timeframe (spec Section 2/7) — not an
#: invented value, the expected spacing between consecutive bars follows
#: directly from that declaration.
_BAR_WIDTH = pd.Timedelta(hours=1)

#: FX market closure window per spec Section 7's Weekend policy, verbatim:
#: "FX market closed Fri 22:00 UTC – Sun 22:00 UTC; this window is
#: excluded from continuity checks, not treated as missing data." No
#: other calendar exception is defined anywhere in the spec, so none is
#: invented here.
_WEEKEND_CLOSE_WEEKDAY = 4  # Friday (Monday=0 ... Sunday=6)
_WEEKEND_CLOSE_HOUR = 22
_WEEKEND_REOPEN_WEEKDAY = 6  # Sunday
_WEEKEND_REOPEN_HOUR = 22


class FeatureEngineeringError(EAFactoryError):
    """Raised when input data or computed features violate FE-R2-001."""


def _is_weekend_closure_time(ts: pd.Timestamp) -> bool:
    """True if ``ts`` falls inside the spec Section 7 weekend closure window."""
    dow = ts.weekday()
    if dow == _WEEKEND_CLOSE_WEEKDAY:
        return ts.hour >= _WEEKEND_CLOSE_HOUR
    if _WEEKEND_CLOSE_WEEKDAY < dow < _WEEKEND_REOPEN_WEEKDAY:
        return True  # Saturday
    if dow == _WEEKEND_REOPEN_WEEKDAY:
        return ts.hour < _WEEKEND_REOPEN_HOUR
    return False


def _check_weekday_gaps(index: pd.DatetimeIndex) -> None:
    """Enforce spec Section 7: weekday gaps >1 bar are a data-quality
    violation; the declared Fri 22:00 UTC – Sun 22:00 UTC weekend closure
    is excluded from this check, per spec, and no other exception exists.

    A "gap" here is any interval between two consecutive bars wider than
    one H1 bar (i.e. at least one expected bar is missing). For each such
    interval, every expected-but-missing H1 timestamp strictly between the
    two bars must fall inside the weekend closure window; if any one of
    them does not, the gap is a weekday data-quality violation.
    """
    violations = []
    for prev_ts, curr_ts in zip(index[:-1], index[1:]):
        delta = curr_ts - prev_ts
        if delta <= _BAR_WIDTH:
            continue
        missing = pd.date_range(prev_ts + _BAR_WIDTH, curr_ts - _BAR_WIDTH, freq="h")
        if not all(_is_weekend_closure_time(ts) for ts in missing):
            violations.append((prev_ts, curr_ts))

    if violations:
        first_start, first_end = violations[0]
        raise FeatureEngineeringError(
            "OHLCV frame contains unexpected weekday gap(s) (spec Section 7 "
            "data-quality violation) — not a legitimate Fri 22:00-Sun 22:00 "
            "UTC weekend closure",
            violation_count=len(violations),
            first_violation_start=first_start.isoformat(),
            first_violation_end=first_end.isoformat(),
        )


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
    _check_weekday_gaps(df.index)


def compute_momentum(close: pd.Series, lookback: int) -> pd.Series:
    """Percentage return over ``lookback`` bars: ``(close[t]-close[t-n])/close[t-n]``."""
    prior = close.shift(lookback)
    with np.errstate(divide="ignore", invalid="ignore"):
        result = (close - prior) / prior
    return result.replace([np.inf, -np.inf], np.nan)


class WilderSmoothingError(FeatureEngineeringError):
    """Raised when Wilder smoothing encounters an internal NaN gap it cannot seed past."""


def _seeded_wilder_smooth(values: pd.Series, period: int) -> pd.Series:
    """CANONICAL_NUMERICAL_ORACLE for rsi_14/atr_14 (spec Section 4, post-M-5).

    Classic Wilder smoothing, explicit and deterministic, with NO
    dependency on any library's internal recursion/initialization
    semantics:

        seed  = simple arithmetic mean of the first ``period`` valid
                (non-NaN) input values, found starting from the series'
                first non-NaN entry
        avg[t_seed] = seed
        avg[t] = (avg[t-1] * (period - 1) + values[t]) / period   for t > t_seed

    All positions before the seed are NaN. A leading NaN in ``values``
    (e.g. from ``close.diff()``) is tolerated and skipped over to find
    the seed window; an internal NaN gap after that point is treated as
    a hard error (the causal input, once validated by
    ``_check_weekday_gaps``/``_validate_ohlcv``, should never contain one).

    This is a plain, explicit, loop-based recurrence — deliberately not
    vectorized — so its behavior is auditable by hand, matches spec
    Section 4's prose exactly, and needs no cross-reference to any
    library's own documentation to verify.
    """
    arr = values.to_numpy(dtype="float64")
    n = len(arr)
    out = np.full(n, np.nan)

    first_non_nan = None
    for i in range(n):
        if not np.isnan(arr[i]):
            first_non_nan = i
            break
    if first_non_nan is None or first_non_nan + period > n:
        return pd.Series(out, index=values.index)

    seed_window = arr[first_non_nan : first_non_nan + period]
    if np.isnan(seed_window).any():
        raise WilderSmoothingError(
            "non-contiguous NaN gap within the Wilder seed window",
            seed_window_start=first_non_nan,
            period=period,
        )

    seed_pos = first_non_nan + period - 1
    prev = float(seed_window.mean())
    out[seed_pos] = prev

    for t in range(seed_pos + 1, n):
        val = arr[t]
        if np.isnan(val):
            raise WilderSmoothingError(
                "unexpected NaN encountered after the Wilder seed", position=t
            )
        prev = (prev * (period - 1) + val) / period
        out[t] = prev

    return pd.Series(out, index=values.index)


def compute_rsi_14(close: pd.Series) -> pd.Series:
    """Seeded Wilder RSI(14) — spec Section 4 CANONICAL_NUMERICAL_ORACLE.

    delta[t] = close[t] - close[t-1]; gain = max(delta, 0); loss = max(-delta, 0).
    avg_gain/avg_loss via ``_seeded_wilder_smooth``. RS = avg_gain / avg_loss.
    RSI = 100 - 100 / (1 + RS).

    Division-by-zero convention (spec Section 4): a zero average loss
    with a positive average gain correctly yields RSI = 100 (RS -> inf);
    a completely flat window (zero gain AND zero loss) is defined as
    neutral, RSI = 50, rather than left undefined (0/0).
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = _seeded_wilder_smooth(gain, 14)
    avg_loss = _seeded_wilder_smooth(loss, 14)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
    result = 100.0 - (100.0 / (1.0 + rs))
    return result.mask((avg_gain == 0.0) & (avg_loss == 0.0), 50.0)


def compute_atr_14(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Seeded Wilder ATR(14) — spec Section 4 CANONICAL_NUMERICAL_ORACLE.

    True Range itself has no seeding ambiguity (a stateless per-bar max
    of three terms) and is reused directly from ``core.indicators.true_range``.
    Only the smoothing step — ``_seeded_wilder_smooth`` — is the part
    spec Section 4 required to be unambiguous, and is applied here.
    """
    tr = true_range(high, low, close)
    return _seeded_wilder_smooth(tr, 14)


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
            "rsi_14": (
                "Seeded Wilder RSI, period=14: avg_gain/avg_loss seeded as the "
                "simple mean of the first 14 values, then avg[t]=(avg[t-1]*13+"
                "value[t])/14; RSI=100-100/(1+avg_gain/avg_loss); flat market "
                "(0/0) -> RSI=50"
            ),
            "atr_14": (
                "Seeded Wilder ATR of True Range, period=14: seeded as the "
                "simple mean of the first 14 True Range values, then "
                "avg[t]=(avg[t-1]*13+TR[t])/14"
            ),
            "volatility_regime": (
                "ordinal {0,1,2} from atr_14 vs. trailing 500-bar 33rd/67th percentile"
            ),
        },
    }
