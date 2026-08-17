"""Out-of-Sample Walk-Forward Analysis Engine.

Generates genuinely out-of-sample predictions using walk-forward analysis:
- Train on DEVELOPMENT data
- Predict on VALIDATION or PURE_HOLDOUT data
- No look-ahead bias
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, List, Optional, Tuple

import pandas as pd

from core.provenance_enforcement import DataAccessAction, DataState, ProvenanceEnforcer, DataStateViolationError
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)


class WFAConfigurationError(EAFactoryError):
    """Raised when WFA configuration is invalid."""


class WFAPredictionError(EAFactoryError):
    """Raised when WFA prediction fails."""


@dataclass(frozen=True)
class WFAWindow:
    """Immutable walk-forward window specification."""

    window_index: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    train_dates: Tuple[datetime, datetime]
    test_dates: Tuple[datetime, datetime]

    def __post_init__(self) -> None:
        """Validate window boundaries."""
        if self.train_end > self.test_start:
            raise WFAConfigurationError(
                "Training window must end before test window starts",
                train_end=self.train_end,
                test_start=self.test_start,
            )
        if self.test_end <= self.test_start:
            raise WFAConfigurationError(
                "Test window invalid",
                test_start=self.test_start,
                test_end=self.test_end,
            )
        if self.train_dates[0] >= self.train_dates[1]:
            raise WFAConfigurationError("Train date range invalid")
        if self.test_dates[0] >= self.test_dates[1]:
            raise WFAConfigurationError("Test date range invalid")


@dataclass(frozen=True)
class OOSPredictionBatch:
    """Immutable batch of out-of-sample predictions."""

    window: WFAWindow
    model_version: str
    feature_version: str
    predictions: List[Tuple[int, float]]  # (prediction, probability)
    test_indices: List[int]
    test_dates: List[datetime]
    training_data_state: DataState
    test_data_state: DataState
    generation_timestamp: datetime

    def __post_init__(self) -> None:
        """Validate batch consistency."""
        if len(self.predictions) != len(self.test_indices):
            raise WFAPredictionError(
                "Predictions and indices length mismatch",
                predictions_len=len(self.predictions),
                indices_len=len(self.test_indices),
            )
        if len(self.test_dates) != len(self.test_indices):
            raise WFAPredictionError(
                "Test dates and indices length mismatch",
            )

    def verify_no_lookahead(self, cutoff_time: datetime) -> bool:
        """Verify that all predictions use only data available at cutoff."""
        for pred_date in self.test_dates:
            if pred_date > cutoff_time:
                return False
        return True


class WFAPredictionEngine:
    """Generate out-of-sample predictions using walk-forward analysis."""

    def __init__(
        self,
        train_window_size: int,
        test_window_size: int,
        step_size: int,
        hypothesis_id: str,
    ):
        """Initialize WFA engine.

        Args:
            train_window_size: Number of bars for training
            test_window_size: Number of bars for testing
            step_size: Step size for rolling forward
            hypothesis_id: Hypothesis identifier
        """
        if train_window_size <= 0:
            raise WFAConfigurationError("train_window_size must be positive")
        if test_window_size <= 0:
            raise WFAConfigurationError("test_window_size must be positive")
        if step_size <= 0:
            raise WFAConfigurationError("step_size must be positive")

        self.train_window_size = train_window_size
        self.test_window_size = test_window_size
        self.step_size = step_size
        self.hypothesis_id = hypothesis_id
        self.prediction_batches: List[OOSPredictionBatch] = []

    def generate_windows(self, df: pd.DataFrame) -> List[WFAWindow]:
        """Generate walk-forward windows from data."""
        windows = []
        window_index = 0

        for start in range(0, len(df) - self.train_window_size - self.test_window_size, self.step_size):
            train_end = start + self.train_window_size
            test_end = train_end + self.test_window_size

            if test_end > len(df):
                break

            train_df = df.iloc[start:train_end]
            test_df = df.iloc[train_end:test_end]

            window = WFAWindow(
                window_index=window_index,
                train_start=start,
                train_end=train_end,
                test_start=train_end,
                test_end=test_end,
                train_dates=(train_df.index[0], train_df.index[-1]),
                test_dates=(test_df.index[0], test_df.index[-1]),
            )
            windows.append(window)
            window_index += 1

        logger.info(
            "Generated WFA windows",
            hypothesis_id=self.hypothesis_id,
            num_windows=len(windows),
        )
        return windows

    def generate_predictions(
        self,
        df: pd.DataFrame,
        windows: List[WFAWindow],
        model_class: Callable,
        feature_extractor: Callable,
        model_version: str,
        feature_version: str,
        training_data_state: DataState,
        test_data_state: DataState,
    ) -> List[OOSPredictionBatch]:
        """Generate out-of-sample predictions using walk-forward windows.

        Args:
            df: Full dataframe with index as datetime
            windows: Pre-generated WFA windows
            model_class: Model class (must have fit, predict methods)
            feature_extractor: Function to extract features from df slice
            model_version: Version identifier for model
            feature_version: Version identifier for features
            training_data_state: DataState of training data (should be DEVELOPMENT)
            test_data_state: DataState of test data (VALIDATION or PURE_HOLDOUT)

        Returns:
            List of OOSPredictionBatch objects

        Raises:
            DataStateViolationError: If training on non-DEVELOPMENT data
        """
        enforcer = ProvenanceEnforcer(hypothesis_id=self.hypothesis_id)

        # Validate that we're training on DEVELOPMENT data
        enforcer.validate_access(training_data_state, DataAccessAction.TRAINING)

        # Validate that we can predict on test data
        if test_data_state == DataState.PURE_HOLDOUT:
            enforcer.validate_access(test_data_state, DataAccessAction.FINAL_EVALUATION)
        else:
            enforcer.validate_access(test_data_state, DataAccessAction.SELECTION)

        batches = []

        for window in windows:
            train_df = df.iloc[window.train_start : window.train_end]
            test_df = df.iloc[window.test_start : window.test_end]

            try:
                # Extract features
                train_features = feature_extractor(train_df)
                test_features = feature_extractor(test_df)

                # Train model
                model = model_class()
                model.fit(train_features)

                # Predict (no look-ahead bias)
                predictions_prob = model.predict_proba(test_features)
                predictions_class = model.predict(test_features)

                # Build prediction tuples
                pred_tuples = [
                    (int(pred_class), float(prob_positive))
                    for pred_class, prob_row in zip(predictions_class, predictions_prob)
                    for prob_positive in [prob_row[1] if len(prob_row) > 1 else prob_row[0]]
                ]

                batch = OOSPredictionBatch(
                    window=window,
                    model_version=model_version,
                    feature_version=feature_version,
                    predictions=pred_tuples,
                    test_indices=list(range(window.test_start, window.test_end)),
                    test_dates=list(test_df.index),
                    training_data_state=training_data_state,
                    test_data_state=test_data_state,
                    generation_timestamp=utcnow(),
                )

                batches.append(batch)
                self.prediction_batches.append(batch)

                logger.info(
                    "Generated OOS predictions",
                    hypothesis_id=self.hypothesis_id,
                    window=window.window_index,
                    num_predictions=len(pred_tuples),
                )

            except Exception as e:
                raise WFAPredictionError(
                    f"Failed to generate predictions for window {window.window_index}",
                    window_index=window.window_index,
                    error=str(e),
                )

        return batches

    def get_all_predictions(self) -> List[OOSPredictionBatch]:
        """Get all generated prediction batches."""
        return self.prediction_batches.copy()
