"""Provenance Enforcement: Runtime data usage boundary enforcement.

Prevents unauthorized data access by validating that:
- DEVELOPMENT data used only for training/exploration
- VALIDATION data used for selection only (not training)
- PURE_HOLDOUT data used only for final evaluation (once)
- OBSERVED data used for live trading only
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from utils.exceptions import EAFactoryError
from utils.logger import get_logger

logger = get_logger(__name__)


class DataState(str, Enum):
    """Runtime data state for enforcement."""

    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    PURE_HOLDOUT = "PURE_HOLDOUT"
    OBSERVED = "OBSERVED"


class DataAccessAction(str, Enum):
    """Requested action on data."""

    TRAINING = "TRAINING"
    SELECTION = "SELECTION"
    FINAL_EVALUATION = "FINAL_EVALUATION"
    OBSERVATION = "OBSERVATION"


class ProvenanceEnforcementError(EAFactoryError):
    """Raised when data access violates provenance boundaries."""


class DataStateViolationError(EAFactoryError):
    """Raised when access attempt violates data state rules."""


# Access matrix: DataState → set of allowed actions
ALLOWED_ACTIONS = {
    DataState.DEVELOPMENT: {
        DataAccessAction.TRAINING,
        DataAccessAction.SELECTION,
    },
    DataState.VALIDATION: {
        DataAccessAction.SELECTION,
    },
    DataState.PURE_HOLDOUT: {
        DataAccessAction.FINAL_EVALUATION,
    },
    DataState.OBSERVED: {
        DataAccessAction.OBSERVATION,
    },
}


@dataclass(frozen=True)
class ProvenanceEnforcer:
    """Enforce data usage boundaries at runtime."""

    hypothesis_id: str
    holdout_accessed: bool = False

    def validate_access(
        self,
        data_state: DataState,
        action: DataAccessAction,
    ) -> None:
        """Validate that action is allowed for data state.

        Args:
            data_state: Current data state
            action: Requested action

        Raises:
            DataStateViolationError: If action not allowed
        """
        if action not in ALLOWED_ACTIONS.get(data_state, set()):
            raise DataStateViolationError(
                f"Cannot use {data_state.value} for {action.value}",
                hypothesis_id=self.hypothesis_id,
                data_state=data_state.value,
                action=action.value,
                allowed_actions=[a.value for a in ALLOWED_ACTIONS[data_state]],
            )

        # PURE_HOLDOUT: One-time access only
        if data_state == DataState.PURE_HOLDOUT and self.holdout_accessed:
            raise DataStateViolationError(
                "PURE_HOLDOUT already accessed; cannot access again",
                hypothesis_id=self.hypothesis_id,
            )

        logger.info(
            "Provenance access validated",
            hypothesis_id=self.hypothesis_id,
            data_state=data_state.value,
            action=action.value,
        )

    @staticmethod
    def is_development(data_state: DataState) -> bool:
        """Check if state is DEVELOPMENT."""
        return data_state == DataState.DEVELOPMENT

    @staticmethod
    def is_validation(data_state: DataState) -> bool:
        """Check if state is VALIDATION."""
        return data_state == DataState.VALIDATION

    @staticmethod
    def is_pure_holdout(data_state: DataState) -> bool:
        """Check if state is PURE_HOLDOUT."""
        return data_state == DataState.PURE_HOLDOUT

    @staticmethod
    def is_observed(data_state: DataState) -> bool:
        """Check if state is OBSERVED."""
        return data_state == DataState.OBSERVED
