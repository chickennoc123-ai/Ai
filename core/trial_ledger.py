"""Trial Ledger: Research accounting and budget tracking.

Records every research attempt with full provenance:
- Tracks all trials (attempted, completed, failed, abandoned)
- Enforces research budget limits
- Provides degrees of freedom accounting
- Ensures all results include trial count context
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)


class TrialStatus(str, Enum):
    """Status of a research trial."""

    ATTEMPTED = "ATTEMPTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"
    REJECTED = "REJECTED"


class ResearchBudgetError(EAFactoryError):
    """Raised when research budget is exhausted."""


class TrialLedgerError(EAFactoryError):
    """Raised when trial ledger operation fails."""


@dataclass
class TrialRecord:
    """Immutable record of a research trial."""

    trial_id: str
    hypothesis_id: str
    timestamp: datetime
    status: TrialStatus

    model: str
    hyperparameters: Dict[str, Any]
    features: List[str]
    target: str

    train_period: tuple  # (start_date, end_date)
    validation_period: tuple  # (start_date, end_date)
    holdout_period: Optional[tuple] = None  # (start_date, end_date) or None

    # Results (only for COMPLETED)
    oos_metrics: Optional[Dict[str, float]] = None
    baseline_metrics: Optional[Dict[str, float]] = None
    selection_rule: Optional[str] = None

    # Degrees of freedom
    degrees_of_freedom: Dict[str, Any] = field(default_factory=dict)

    def is_completed(self) -> bool:
        """Check if trial completed successfully."""
        return self.status == TrialStatus.COMPLETED

    def has_results(self) -> bool:
        """Check if trial has OOS results."""
        return self.oos_metrics is not None

    def summary(self) -> Dict[str, Any]:
        """Return trial summary."""
        return {
            "trial_id": self.trial_id,
            "hypothesis_id": self.hypothesis_id,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "model": self.model,
            "hyperparameters": self.hyperparameters,
            "features": self.features,
            "target": self.target,
            "train_period": self.train_period,
            "validation_period": self.validation_period,
            "holdout_period": self.holdout_period,
            "oos_metrics": self.oos_metrics,
            "baseline_metrics": self.baseline_metrics,
            "selection_rule": self.selection_rule,
            "degrees_of_freedom": self.degrees_of_freedom,
        }


class TrialLedger:
    """Track and enforce research budget constraints."""

    def __init__(self, hypothesis_id: str, max_trials: int = 100):
        """Initialize trial ledger.

        Args:
            hypothesis_id: Hypothesis identifier
            max_trials: Maximum number of trials allowed (research budget)
        """
        if max_trials <= 0:
            raise TrialLedgerError("max_trials must be positive")

        self.hypothesis_id = hypothesis_id
        self.max_trials = max_trials
        self.trials: List[TrialRecord] = []

    def record_trial(self, trial_record: TrialRecord) -> None:
        """Record a research trial.

        Args:
            trial_record: Trial to record

        Raises:
            ResearchBudgetError: If budget is exhausted
            TrialLedgerError: If trial is invalid
        """
        if len(self.trials) >= self.max_trials:
            raise ResearchBudgetError(
                f"Research budget exhausted: {self.max_trials} trials used",
                hypothesis_id=self.hypothesis_id,
                max_trials=self.max_trials,
            )

        if trial_record.hypothesis_id != self.hypothesis_id:
            raise TrialLedgerError(
                "Trial hypothesis_id mismatch",
                expected=self.hypothesis_id,
                actual=trial_record.hypothesis_id,
            )

        self.trials.append(trial_record)

        logger.info(
            "Trial recorded",
            hypothesis_id=self.hypothesis_id,
            trial_id=trial_record.trial_id,
            status=trial_record.status.value,
            num_trials=len(self.trials),
            remaining_budget=self.max_trials - len(self.trials),
        )

    def get_trial(self, trial_id: str) -> TrialRecord:
        """Retrieve a trial by ID."""
        for trial in self.trials:
            if trial.trial_id == trial_id:
                return trial
        raise TrialLedgerError(
            "Trial not found",
            trial_id=trial_id,
            hypothesis_id=self.hypothesis_id,
        )

    def count_by_status(self, status: TrialStatus) -> int:
        """Count trials by status."""
        return sum(1 for t in self.trials if t.status == status)

    def get_trials_by_status(self, status: TrialStatus) -> List[TrialRecord]:
        """Get all trials with given status."""
        return [t for t in self.trials if t.status == status]

    def get_completed_trials(self) -> List[TrialRecord]:
        """Get all completed trials."""
        return self.get_trials_by_status(TrialStatus.COMPLETED)

    def get_trials_with_results(self) -> List[TrialRecord]:
        """Get all trials with OOS results."""
        return [t for t in self.trials if t.has_results()]

    def get_remaining_budget(self) -> int:
        """Get remaining trial budget."""
        return self.max_trials - len(self.trials)

    def get_budget_utilization(self) -> float:
        """Get budget utilization percentage."""
        if self.max_trials == 0:
            return 100.0
        return (len(self.trials) / self.max_trials) * 100.0

    def summary(self) -> Dict[str, Any]:
        """Return ledger summary."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "total_trials": len(self.trials),
            "max_trials": self.max_trials,
            "remaining_budget": self.get_remaining_budget(),
            "budget_utilization": self.get_budget_utilization(),
            "by_status": {
                status.value: self.count_by_status(status)
                for status in TrialStatus
            },
            "completed_trials": len(self.get_completed_trials()),
            "trials_with_results": len(self.get_trials_with_results()),
            "trials": [t.summary() for t in self.trials],
        }
