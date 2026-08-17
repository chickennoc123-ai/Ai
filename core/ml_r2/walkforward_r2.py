"""ML-001-R2 temporal validation and walk-forward protocol.

Per ``ML-001-R2-CLEAN-REBUILD-SPEC.md`` Sections 8-9.

Reuses existing, proven infrastructure where its semantics are already
correct and lookback-agnostic:

- ``core.provenance_enforcement.ProvenanceEnforcer`` — DEVELOPMENT /
  VALIDATION / PURE_HOLDOUT access-boundary enforcement.
- ``core.oos_wfa_engine.WFAWindow`` / ``OOSPredictionBatch`` — immutable
  window and prediction-batch record types.
- ``core.oos_wfa_engine.WFAPredictionEngine.generate_windows`` — pure
  window-boundary arithmetic (no feature computation involved, so it has
  no lookback dependency and is safe to reuse unmodified).

Does NOT reuse ``WFAPredictionEngine.generate_predictions``: that method
calls ``feature_extractor(df.iloc[window.test_start:window.test_end])``
on a bare slice with no preceding context, which is incompatible with
any feature set that needs lookback (FE-R2-001 needs up to 600 bars).
``generate_oos_predictions`` below is new code that extends each test
window backward by the required warmup before computing features, then
trims the output back to the window's true boundaries. This is a
documented, deliberate deviation — not a silent patch to shared code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List

import pandas as pd

from core.features.fe_r2_001 import FEATURE_ORDER, FEATURE_VERSION, WARMUP_BARS, build_feature_matrix
from core.ml_r2.model_r2 import MODEL_VERSION, RFR2Model
from core.ml_r2.target_r2 import align_features_and_labels, compute_label
from core.oos_wfa_engine import OOSPredictionBatch, WFAPredictionEngine, WFAWindow
from core.provenance_enforcement import DataAccessAction, DataState, DataStateViolationError, ProvenanceEnforcer
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

#: Largest warmup requirement across all FE-R2-001 features.
MAX_WARMUP_BARS = max(WARMUP_BARS.values())

DEVELOPMENT_FRACTION = 0.60
VALIDATION_FRACTION = 0.20
# Remainder (0.20) is PURE_HOLDOUT.


class TemporalSplitError(EAFactoryError):
    """Raised when the DEVELOPMENT/VALIDATION/PURE_HOLDOUT split is invalid."""


@dataclass(frozen=True)
class TemporalSplit:
    """Immutable, chronologically ordered three-way split boundary record."""

    development: pd.DataFrame
    validation: pd.DataFrame
    holdout: pd.DataFrame
    development_range: tuple
    validation_range: tuple
    holdout_range: tuple


def compute_temporal_split(
    ohlcv: pd.DataFrame,
    development_fraction: float = DEVELOPMENT_FRACTION,
    validation_fraction: float = VALIDATION_FRACTION,
) -> TemporalSplit:
    """Split ``ohlcv`` chronologically into DEVELOPMENT/VALIDATION/PURE_HOLDOUT.

    Strictly positional/chronological — never a random or shuffled split.
    """
    if not isinstance(ohlcv.index, pd.DatetimeIndex):
        raise TemporalSplitError("ohlcv must be indexed by a DatetimeIndex")
    if not ohlcv.index.is_monotonic_increasing:
        raise TemporalSplitError("ohlcv timestamps must be strictly increasing")
    if not (0.0 < development_fraction < 1.0) or not (0.0 < validation_fraction < 1.0):
        raise TemporalSplitError("fractions must be in (0, 1)")
    if development_fraction + validation_fraction >= 1.0:
        raise TemporalSplitError("development_fraction + validation_fraction must leave a positive holdout share")

    n = len(ohlcv)
    dev_end = int(n * development_fraction)
    val_end = dev_end + int(n * validation_fraction)

    if not (0 < dev_end < val_end < n):
        raise TemporalSplitError(
            "insufficient rows to form a non-degenerate three-way split", n_rows=n, dev_end=dev_end, val_end=val_end
        )

    development = ohlcv.iloc[:dev_end]
    validation = ohlcv.iloc[dev_end:val_end]
    holdout = ohlcv.iloc[val_end:]

    return TemporalSplit(
        development=development,
        validation=validation,
        holdout=holdout,
        development_range=(development.index[0], development.index[-1]),
        validation_range=(validation.index[0], validation.index[-1]),
        holdout_range=(holdout.index[0], holdout.index[-1]),
    )


class HoldoutAccessGuard:
    """Enforces PURE_HOLDOUT's one-time-access rule for a single hypothesis run.

    Wraps ``ProvenanceEnforcer`` (frozen dataclass) with mutable
    open/closed state, since a single logical research run needs the
    "already accessed" fact to persist across calls.
    """

    def __init__(self, hypothesis_id: str) -> None:
        self._hypothesis_id = hypothesis_id
        self._holdout_opened = False

    def validate(self, data_state: DataState, action: DataAccessAction) -> None:
        enforcer = ProvenanceEnforcer(hypothesis_id=self._hypothesis_id, holdout_accessed=self._holdout_opened)
        enforcer.validate_access(data_state, action)
        if data_state == DataState.PURE_HOLDOUT and action == DataAccessAction.FINAL_EVALUATION:
            self._holdout_opened = True

    @property
    def holdout_opened(self) -> bool:
        return self._holdout_opened


def generate_oos_predictions(
    df: pd.DataFrame,
    windows: List[WFAWindow],
    hypothesis_id: str,
    model_version: str = MODEL_VERSION,
    feature_version: str = FEATURE_VERSION,
    training_data_state: DataState = DataState.DEVELOPMENT,
    test_data_state: DataState = DataState.VALIDATION,
) -> List[OOSPredictionBatch]:
    """Generate genuinely out-of-sample RF-R2-001 predictions across walk-forward windows.

    Each test window's feature computation is extended backward by
    ``MAX_WARMUP_BARS`` so lookback-dependent features (e.g.
    ``volatility_regime``) are valid at the start of the window, then the
    output is trimmed back to the window's declared boundaries before
    being registered as an OOS prediction batch.
    """
    enforcer = ProvenanceEnforcer(hypothesis_id=hypothesis_id)
    enforcer.validate_access(training_data_state, DataAccessAction.TRAINING)
    if test_data_state == DataState.PURE_HOLDOUT:
        enforcer.validate_access(test_data_state, DataAccessAction.FINAL_EVALUATION)
    else:
        enforcer.validate_access(test_data_state, DataAccessAction.SELECTION)

    batches: List[OOSPredictionBatch] = []

    for window in windows:
        train_df = df.iloc[window.train_start : window.train_end]
        train_features = build_feature_matrix(train_df)
        train_labels = compute_label(train_df["close"])
        X_train, y_train = align_features_and_labels(train_features, train_labels)
        if len(X_train) == 0:
            raise TemporalSplitError(
                "training window produced zero usable rows after warmup/label alignment",
                window_index=window.window_index,
            )

        model = RFR2Model()
        model.train(X_train, y_train, training_start=window.train_dates[0], training_end=window.train_dates[1])

        # Extend the test slice backward for feature warmup, then trim to the true window.
        extended_start = max(0, window.test_start - MAX_WARMUP_BARS)
        extended_test_df = df.iloc[extended_start : window.test_end]
        extended_features = build_feature_matrix(extended_test_df)
        test_features = extended_features.loc[df.index[window.test_start] :]

        usable = test_features.notna().all(axis=1)
        usable_features = test_features.loc[usable]

        if len(usable_features) == 0:
            batches.append(
                OOSPredictionBatch(
                    window=window,
                    model_version=model_version,
                    feature_version=feature_version,
                    predictions=[],
                    test_indices=[],
                    test_dates=[],
                    training_data_state=training_data_state,
                    test_data_state=test_data_state,
                    generation_timestamp=utcnow(),
                )
            )
            continue

        probabilities = model.predict_proba(usable_features)
        classes = model.predict(usable_features)
        pred_tuples = [
            (int(cls), float(prob)) for cls, prob in zip(classes, probabilities)
        ]

        test_index_positions = [df.index.get_loc(ts) for ts in usable_features.index]

        batches.append(
            OOSPredictionBatch(
                window=window,
                model_version=model_version,
                feature_version=feature_version,
                predictions=pred_tuples,
                test_indices=test_index_positions,
                test_dates=list(usable_features.index),
                training_data_state=training_data_state,
                test_data_state=test_data_state,
                generation_timestamp=utcnow(),
            )
        )

    return batches


def make_walk_forward_windows(
    df: pd.DataFrame,
    train_window_size: int,
    test_window_size: int,
    step_size: int,
    hypothesis_id: str,
) -> List[WFAWindow]:
    """Thin, documented reuse of ``WFAPredictionEngine.generate_windows`` (pure index math)."""
    engine = WFAPredictionEngine(
        train_window_size=train_window_size,
        test_window_size=test_window_size,
        step_size=step_size,
        hypothesis_id=hypothesis_id,
    )
    return engine.generate_windows(df)
