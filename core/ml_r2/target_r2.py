"""ML-001-R2 target/label construction.

Per ``ML-001-R2-CLEAN-REBUILD-SPEC.md`` Section 5: strict binary label,
no deadband, no inherited threshold from old (rejected) ML-001.

    label[t] = 1  if close[t+1] >  close[t]
    label[t] = 0  if close[t+1] <= close[t]
    label[t] = undefined (NaN) if close[t+1] does not exist (last bar)

The undefined case is deliberately NOT collapsed into class 0 — a
missing future value is not evidence of a "not up" outcome, it is an
absence of information, and must be excluded from training rather than
silently mislabeled.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from utils.exceptions import EAFactoryError

TARGET_SPEC_ID = "TARGET-R2-001"


class LabelConstructionError(EAFactoryError):
    """Raised when label construction input is malformed or leaks information."""


def compute_label(close: pd.Series) -> pd.Series:
    """Compute the ML-001-R2 binary label series, aligned to ``close.index``.

    ``label[t]`` depends on ``close[t+1]`` and is therefore information
    available only at ``t+1``, never at ``t`` — callers must never treat
    ``label[t]`` as observable at prediction time ``t``.
    """
    if not isinstance(close.index, pd.DatetimeIndex):
        raise LabelConstructionError(
            "close series must be indexed by a DatetimeIndex", index_type=type(close.index).__name__
        )
    if not close.index.is_monotonic_increasing:
        raise LabelConstructionError("close series timestamps must be strictly increasing")

    future_close = close.shift(-1)
    has_future = future_close.notna()
    label = pd.Series(np.nan, index=close.index, dtype="float64")
    label.loc[has_future] = (future_close.loc[has_future] > close.loc[has_future]).astype("float64")
    return label


def align_features_and_labels(
    features: pd.DataFrame, labels: pd.Series
) -> tuple[pd.DataFrame, pd.Series]:
    """Drop rows with any NaN feature or undefined label; return aligned (X, y).

    This removes both feature-warmup rows and the final bar (which has no
    ``t+1`` label). The returned frames share an identical, chronologically
    ordered index.
    """
    if not features.index.equals(labels.index):
        raise LabelConstructionError("features and labels must share an identical index")

    complete_mask = features.notna().all(axis=1) & labels.notna()
    X = features.loc[complete_mask]
    y = labels.loc[complete_mask]

    if not X.index.equals(y.index):  # pragma: no cover - defensive, mask guarantees this
        raise LabelConstructionError("post-alignment index mismatch between features and labels")
    if not X.index.is_monotonic_increasing:
        raise LabelConstructionError("aligned (X, y) must remain chronologically ordered")

    return X, y


def assert_no_leakage(close: pd.Series, features: pd.DataFrame, labels: pd.Series) -> None:
    """Recompute labels independently and verify they match ``labels`` exactly.

    A mismatch means ``labels`` was constructed from something other than
    this module's canonical definition — treated as a leakage/integrity
    violation, not a warning.
    """
    recomputed = compute_label(close)
    if not recomputed.index.equals(labels.index):
        raise LabelConstructionError("label index does not match the provided close series")

    both_defined = recomputed.notna() & labels.notna()
    mismatched = both_defined & (recomputed != labels)
    if mismatched.any():
        raise LabelConstructionError(
            "labels do not match TARGET-R2-001 recomputed from close prices",
            mismatched_count=int(mismatched.sum()),
        )

    both_undefined_mismatch = recomputed.isna() != labels.isna()
    if both_undefined_mismatch.any():
        raise LabelConstructionError(
            "label definedness does not match TARGET-R2-001 recomputed from close prices",
            mismatched_definedness_count=int(both_undefined_mismatch.sum()),
        )
