"""Generation 4, Phase 3 — Feature temporal safety audit.

Documenting that a feature "uses a rolling window and is therefore
causal" proves nothing: the whole class of leakage bugs this phase exists
to catch consists of features whose author believed exactly that. So this
module tests the property directly, on real data, by construction:

**Truncation invariance.** For a causal feature, ``f(data[0..T])[t]``
must equal ``f(data[0..t])[t]`` for every ``t <= T``. If the value at
``t`` changes when bars after ``t`` are removed, the value depended on
them. This catches centered windows, ``shift(-n)``, backward fills,
whole-series normalization, whole-series quantiles, and scaler fitting on
the full sample — without needing to know which of those the author used.

**Future perturbation invariance.** Independently: replace every bar
after ``t`` with different prices and recompute. ``f[t]`` must be
bit-identical. This catches the same class from the other direction and,
unlike truncation, also catches a feature that reads the future only when
the future has particular values.

Both are run over many sampled cut points on the real dataset, not on a
toy fixture, because a feature can be causal on smooth synthetic data and
leak on real data with gaps.

A per-feature dependency record (source columns, lookback, alignment,
availability time, missing-data behavior) is produced alongside, so the
audit answers *why* a feature is safe as well as *whether* it is.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from core.features.fe_r2_001 import (
    FEATURE_ORDER,
    FEATURE_VERSION,
    WARMUP_BARS,
    build_feature_matrix,
    get_feature_schema,
)
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

PASS = "PASS"
FAIL = "FAIL"

#: Static dependency facts for each FE-R2-003 feature. These are read off
#: the implementation in core/features/fe_r2_001.py by hand; the empirical
#: tests below are what actually *verify* the claim, so a wrong entry here
#: is a documentation error that the tests would still catch.
FEATURE_DEPENDENCIES: Dict[str, Dict[str, Any]] = {
    "momentum_5": {
        "source_columns": ["close"],
        "lookback_bars": 5,
        "warmup_bars": WARMUP_BARS["momentum_5"],
        "timestamp_alignment": "right (value at t uses close[t] and close[t-5])",
        "availability_time": "bar close of t",
        "rolling_window_semantics": "none (point-to-point return)",
        "shift_semantics": "close.shift(+5) -- strictly backward",
        "missing_data_behavior": "NaN propagates; inf from a zero prior price is mapped to NaN",
        "forward_fill_behavior": "none",
        "aggregation_behavior": "none",
        "cross_symbol_dependencies": "none",
        "normalization": "none",
    },
    "momentum_20": {
        "source_columns": ["close"],
        "lookback_bars": 20,
        "warmup_bars": WARMUP_BARS["momentum_20"],
        "timestamp_alignment": "right (value at t uses close[t] and close[t-20])",
        "availability_time": "bar close of t",
        "rolling_window_semantics": "none (point-to-point return)",
        "shift_semantics": "close.shift(+20) -- strictly backward",
        "missing_data_behavior": "NaN propagates; inf from a zero prior price is mapped to NaN",
        "forward_fill_behavior": "none",
        "aggregation_behavior": "none",
        "cross_symbol_dependencies": "none",
        "normalization": "none",
    },
    "rsi_14": {
        "source_columns": ["close"],
        "lookback_bars": 14,
        "warmup_bars": WARMUP_BARS["rsi_14"],
        "timestamp_alignment": "right (recursive average ending at t)",
        "availability_time": "bar close of t",
        "rolling_window_semantics": "seeded Wilder recurrence over close.diff(); expanding-backward, never forward",
        "shift_semantics": "close.diff() = close - close.shift(+1)",
        "missing_data_behavior": "an internal NaN after the seed raises WilderSmoothingError (fails closed)",
        "forward_fill_behavior": "none",
        "aggregation_behavior": "recursive mean of gains/losses",
        "cross_symbol_dependencies": "none",
        "normalization": "bounded 0-100 by construction; no fitted scaler",
    },
    "atr_14": {
        "source_columns": ["high", "low", "close"],
        "lookback_bars": 14,
        "warmup_bars": WARMUP_BARS["atr_14"],
        "timestamp_alignment": "right (recursive average ending at t)",
        "availability_time": "bar close of t",
        "rolling_window_semantics": "seeded Wilder recurrence over true_range; expanding-backward, never forward",
        "shift_semantics": "true_range uses close.shift(+1) as the prior close",
        "missing_data_behavior": "an internal NaN after the seed raises WilderSmoothingError (fails closed)",
        "forward_fill_behavior": "none",
        "aggregation_behavior": "recursive mean of true range",
        "cross_symbol_dependencies": "none",
        "normalization": "none; absolute price units",
    },
    "volatility_regime": {
        "source_columns": ["high", "low", "close"],
        "lookback_bars": 500,
        "warmup_bars": WARMUP_BARS["volatility_regime"],
        "timestamp_alignment": "right-aligned rolling quantile ending at t",
        "availability_time": "bar close of t",
        "rolling_window_semantics": "pandas rolling(500, min_periods=500).quantile -- right-aligned, causal",
        "shift_semantics": "none beyond atr_14's own",
        "missing_data_behavior": "NaN wherever atr_14 or either quantile is undefined",
        "forward_fill_behavior": "none",
        "aggregation_behavior": "trailing 33rd/67th percentile of atr_14",
        "cross_symbol_dependencies": "none",
        "normalization": "trailing-percentile ranking; the percentiles are recomputed per bar from "
        "the trailing window only, never fitted once on the whole sample",
    },
}


class FeatureTemporalAuditError(EAFactoryError):
    """Raised when the audit cannot be performed (not when it finds leakage)."""


@dataclass(frozen=True)
class FeatureTemporalAuditReport:
    verdict: str
    audit_timestamp: str
    feature_version: str
    features_audited: tuple
    cut_points_tested: tuple
    truncation_invariance: Dict[str, str]
    future_perturbation_invariance: Dict[str, str]
    same_timestamp_leakage: Dict[str, str]
    dependency_records: Dict[str, Dict[str, Any]]
    cross_symbol_dependency: str
    scaler_or_imputation_state: str
    violations: tuple = ()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["features_audited"] = list(self.features_audited)
        d["cut_points_tested"] = list(self.cut_points_tested)
        d["violations"] = list(self.violations)
        return d

    def report_checksum(self) -> str:
        """Checksum of the findings, excluding ``audit_timestamp`` -- see
        ``DataEligibilityReport.report_checksum`` for why."""
        d = self.to_dict()
        d.pop("audit_timestamp", None)
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def _values_equal(a: float, b: float) -> bool:
    """NaN-aware exact comparison. Deliberately exact, not approximate: a
    causal feature recomputed on a prefix of the same bars must produce
    the *identical* float, and a tolerance here would hide small leaks."""
    if pd.isna(a) and pd.isna(b):
        return True
    return bool(a == b)


def check_truncation_invariance(
    ohlcv: pd.DataFrame,
    cut_points: Sequence[int],
    features: Optional[Sequence[str]] = None,
) -> Dict[str, List[str]]:
    """For each cut point ``c``: recompute features on ``ohlcv[:c]`` and
    require row ``c-1`` to match the full-sample computation exactly."""
    features = list(features or FEATURE_ORDER)
    full = build_feature_matrix(ohlcv)
    violations: Dict[str, List[str]] = {f: [] for f in features}

    for c in cut_points:
        if c < 2 or c > len(ohlcv):
            continue
        truncated = build_feature_matrix(ohlcv.iloc[:c])
        ts = ohlcv.index[c - 1]
        for f in features:
            if not _values_equal(full.loc[ts, f], truncated.loc[ts, f]):
                violations[f].append(
                    f"cut={c} ts={ts} full={full.loc[ts, f]!r} truncated={truncated.loc[ts, f]!r}"
                )
    return violations


def check_future_perturbation_invariance(
    ohlcv: pd.DataFrame,
    cut_points: Sequence[int],
    features: Optional[Sequence[str]] = None,
    *,
    seed: int = 20260819,
) -> Dict[str, List[str]]:
    """For each cut point ``c``: replace every bar at index >= ``c`` with
    materially different (but internally consistent) prices, recompute,
    and require rows ``< c`` to be unchanged."""
    features = list(features or FEATURE_ORDER)
    full = build_feature_matrix(ohlcv)
    rng = np.random.default_rng(seed)
    violations: Dict[str, List[str]] = {f: [] for f in features}

    for c in cut_points:
        if c < 2 or c >= len(ohlcv):
            continue
        perturbed = ohlcv.copy()
        n_future = len(perturbed) - c
        # A large multiplicative shock, applied uniformly to O/H/L/C so
        # the perturbed bars remain OHLC-valid (the validator would
        # otherwise reject them and we would be testing the validator).
        shock = 1.0 + rng.uniform(0.10, 0.40, size=n_future)
        for col in ("open", "high", "low", "close"):
            perturbed.iloc[c:, perturbed.columns.get_loc(col)] = (
                perturbed[col].to_numpy()[c:] * shock
            )
        recomputed = build_feature_matrix(perturbed)
        ts = ohlcv.index[c - 1]
        for f in features:
            if not _values_equal(full.loc[ts, f], recomputed.loc[ts, f]):
                violations[f].append(
                    f"cut={c} ts={ts} unperturbed={full.loc[ts, f]!r} after_future_shock={recomputed.loc[ts, f]!r}"
                )
    return violations


def check_same_timestamp_leakage(
    ohlcv: pd.DataFrame,
    cut_points: Sequence[int],
    features: Optional[Sequence[str]] = None,
) -> Dict[str, List[str]]:
    """Same-timestamp leakage: does ``feature[t]`` use bar ``t``'s own
    *future-revealing* fields in a way that would be unavailable at the
    decision moment?

    FE-R2-003's features are all declared available "at bar close of t",
    so using ``close[t]`` is legitimate — the leakage that matters is
    whether ``feature[t]`` changes when bar ``t+1`` (the very next bar,
    the tightest possible future) is altered. This is the ``c = t+1``
    special case of the perturbation test, isolated because a one-bar
    lookahead is by far the most common real leakage bug and deserves its
    own named result rather than being averaged into a general sweep.
    """
    features = list(features or FEATURE_ORDER)
    violations: Dict[str, List[str]] = {f: [] for f in features}
    full = build_feature_matrix(ohlcv)

    for c in cut_points:
        if c < 2 or c >= len(ohlcv):
            continue
        perturbed = ohlcv.copy()
        # Alter ONLY bar c (i.e. t+1 relative to the bar under test at c-1).
        for col in ("open", "high", "low", "close"):
            perturbed.iloc[c, perturbed.columns.get_loc(col)] = (
                float(perturbed.iloc[c][col]) * 1.25
            )
        recomputed = build_feature_matrix(perturbed)
        ts = ohlcv.index[c - 1]
        for f in features:
            if not _values_equal(full.loc[ts, f], recomputed.loc[ts, f]):
                violations[f].append(
                    f"t={ts} changed when the NEXT bar (index {c}) was altered: "
                    f"{full.loc[ts, f]!r} -> {recomputed.loc[ts, f]!r}"
                )
    return violations


def default_cut_points(n_rows: int, count: int = 12) -> List[int]:
    """Evenly spaced cut points across the usable range.

    Deterministic and derived only from the row count -- never chosen by
    looking at where a feature happens to behave well.
    """
    lo = max(WARMUP_BARS.values()) + 50
    hi = n_rows - 10
    if hi <= lo:
        return []
    return [int(round(x)) for x in np.linspace(lo, hi, count)]


def audit_feature_temporal_safety(
    ohlcv: pd.DataFrame,
    *,
    features: Optional[Sequence[str]] = None,
    cut_points: Optional[Sequence[int]] = None,
) -> FeatureTemporalAuditReport:
    """Run the full Phase 3 audit and return a verdict."""
    if not isinstance(ohlcv.index, pd.DatetimeIndex):
        raise FeatureTemporalAuditError("ohlcv must be indexed by a DatetimeIndex")

    features = list(features or FEATURE_ORDER)
    unknown = [f for f in features if f not in FEATURE_ORDER]
    if unknown:
        raise FeatureTemporalAuditError("unknown feature(s) requested", unknown=unknown)

    cuts = list(cut_points) if cut_points is not None else default_cut_points(len(ohlcv))
    if not cuts:
        raise FeatureTemporalAuditError("not enough rows to form any cut point", n_rows=len(ohlcv))

    trunc = check_truncation_invariance(ohlcv, cuts, features)
    perturb = check_future_perturbation_invariance(ohlcv, cuts, features)
    same_ts = check_same_timestamp_leakage(ohlcv, cuts, features)

    violations: List[str] = []
    for name, result in (("truncation", trunc), ("future_perturbation", perturb), ("same_timestamp", same_ts)):
        for feature, items in result.items():
            for item in items:
                violations.append(f"[{name}] {feature}: {item}")

    verdict = PASS if not violations else FAIL

    return FeatureTemporalAuditReport(
        verdict=verdict,
        audit_timestamp=utcnow().isoformat(),
        feature_version=FEATURE_VERSION,
        features_audited=tuple(features),
        cut_points_tested=tuple(cuts),
        truncation_invariance={f: (PASS if not trunc[f] else FAIL) for f in features},
        future_perturbation_invariance={f: (PASS if not perturb[f] else FAIL) for f in features},
        same_timestamp_leakage={f: (PASS if not same_ts[f] else FAIL) for f in features},
        dependency_records={f: FEATURE_DEPENDENCIES[f] for f in features},
        cross_symbol_dependency=(
            "STRUCTURALLY_ABSENT: build_feature_matrix takes exactly one symbol's OHLCV frame and "
            "has no parameter, import or global through which another symbol's data could reach it"
        ),
        scaler_or_imputation_state=(
            "STRUCTURALLY_ABSENT: FE-R2-003 fits no scaler and performs no imputation. Warmup rows "
            "are set to NaN and later dropped by alignment; they are never filled. There is no "
            "fit/transform object whose fitted state could span the train/test boundary"
        ),
        violations=tuple(violations),
    )
