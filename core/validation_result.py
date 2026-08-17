"""Validation Result: Final verdict system for ML hypothesis validation.

States:
- NOT_TESTED: No experiment run
- INVALID: Leakage detected or audit failed
- INCONCLUSIVE: OOS clean, but insufficient evidence
- REJECTED: OOS clean, evidence exists, but no edge
- VALIDATED: OOS clean, edge detected, ready for Decision Engine
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Literal, Optional

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)


class ValidationVerdict(str, Enum):
    """Final validation verdict."""

    NOT_TESTED = "NOT_TESTED"
    INVALID = "INVALID"
    INCONCLUSIVE = "INCONCLUSIVE"
    REJECTED = "REJECTED"
    VALIDATED = "VALIDATED"


class ValidationRecommendation(str, Enum):
    """Recommendation for Decision Engine."""

    INVALID = "INVALID"
    REJECT = "REJECT"
    INCONCLUSIVE = "INCONCLUSIVE"
    AUTHORIZE = "AUTHORIZE"


class ValidationResultError(EAFactoryError):
    """Raised when validation result is invalid."""


@dataclass(frozen=True)
class ValidationReport:
    """Immutable final validation report."""

    hypothesis_id: str
    dataset_version: str
    verdict: ValidationVerdict

    oos_observations: int = 0
    oos_trades: int = 0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    pbo_score: Optional[float] = None
    deflated_sharpe: Optional[float] = None

    baseline_sharpe: float = 0.0
    improvement: float = 0.0

    trials_attempted: int = 0
    trials_completed: int = 0
    degrees_of_freedom: Dict[str, Any] = field(default_factory=dict)

    cost_stress_pass: bool = False
    regime_tests: Dict[str, bool] = field(default_factory=dict)

    brier_score: float = 0.0
    ece_score: float = 0.0

    recommendation: ValidationRecommendation = ValidationRecommendation.INVALID
    report_timestamp: datetime = field(default_factory=utcnow)
    report_id: str = ""
    methodology_version: str = "VR-001-v1.0"

    def __post_init__(self) -> None:
        """Validate and compute report ID."""
        # Validate verdict-specific requirements
        if self.verdict == ValidationVerdict.INVALID:
            # INVALID can have no metrics
            pass
        elif self.verdict == ValidationVerdict.NOT_TESTED:
            # NOT_TESTED has no metrics
            if self.oos_observations != 0:
                raise ValidationResultError(
                    "NOT_TESTED should have no observations",
                    oos_observations=self.oos_observations,
                )
        elif self.verdict == ValidationVerdict.INCONCLUSIVE:
            # INCONCLUSIVE has clean results but insufficient evidence
            if self.oos_observations == 0:
                raise ValidationResultError(
                    "INCONCLUSIVE requires OOS observations",
                )
        elif self.verdict == ValidationVerdict.REJECTED:
            # REJECTED: Edge detected but failed robustness (cost_stress_pass=False)
            if self.oos_observations == 0:
                raise ValidationResultError(
                    "REJECTED requires OOS observations",
                )
            # REJECTED can have either: (1) sharpe ≤ 0.3 or (2) sharpe > 0.3 but cost_stress fails
            # No additional validation needed here
        elif self.verdict == ValidationVerdict.VALIDATED:
            # VALIDATED has clean results and clear edge
            if self.oos_observations == 0:
                raise ValidationResultError(
                    "VALIDATED requires OOS observations",
                )
            if self.sharpe_ratio <= 0.3:
                raise ValidationResultError(
                    "VALIDATED verdict requires edge (sharpe > 0.3)",
                    sharpe_ratio=self.sharpe_ratio,
                )
            if not self.cost_stress_pass:
                raise ValidationResultError(
                    "VALIDATED verdict requires cost_stress_pass",
                )

        # Validate probability scores
        if not 0.0 <= self.brier_score <= 1.0:
            raise ValidationResultError(
                "brier_score must be in [0, 1]",
                brier_score=self.brier_score,
            )
        if not 0.0 <= self.ece_score <= 1.0:
            raise ValidationResultError(
                "ece_score must be in [0, 1]",
                ece_score=self.ece_score,
            )

        # Compute report ID if not provided
        if not self.report_id:
            hash_str = self._compute_report_id()
            object.__setattr__(self, "report_id", hash_str)

    def _compute_report_id(self) -> str:
        """Compute deterministic report ID."""
        data = (
            f"{self.hypothesis_id}:{self.dataset_version}:{self.verdict.value}:"
            f"{self.report_timestamp.isoformat()}:{self.recommendation.value}"
        )
        return hashlib.sha256(data.encode()).hexdigest()[:12]

    def is_valid(self) -> bool:
        """Check if verdict is VALID."""
        return self.verdict != ValidationVerdict.INVALID

    def is_ready_for_authorization(self) -> bool:
        """Check if hypothesis is ready for Decision Engine."""
        return self.verdict == ValidationVerdict.VALIDATED

    def is_blocked(self) -> bool:
        """Check if validation is blocked."""
        return self.verdict == ValidationVerdict.INVALID

    def summary(self) -> Dict[str, Any]:
        """Return report summary."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "dataset_version": self.dataset_version,
            "verdict": self.verdict.value,
            "recommendation": self.recommendation.value,
            "oos_observations": self.oos_observations,
            "oos_trades": self.oos_trades,
            "sharpe_ratio": self.sharpe_ratio,
            "profit_factor": self.profit_factor,
            "win_rate": self.win_rate,
            "max_drawdown": self.max_drawdown,
            "pbo_score": self.pbo_score,
            "deflated_sharpe": self.deflated_sharpe,
            "baseline_sharpe": self.baseline_sharpe,
            "improvement": self.improvement,
            "trials_attempted": self.trials_attempted,
            "trials_completed": self.trials_completed,
            "degrees_of_freedom": self.degrees_of_freedom,
            "cost_stress_pass": self.cost_stress_pass,
            "regime_tests": self.regime_tests,
            "brier_score": self.brier_score,
            "ece_score": self.ece_score,
            "report_timestamp": self.report_timestamp.isoformat(),
            "report_id": self.report_id,
            "methodology_version": self.methodology_version,
        }


class ValidationEngine:
    """Compute validation verdict based on evidence."""

    @staticmethod
    def determine_verdict(
        audit_passed: bool,
        oos_observations: int,
        sharpe_ratio: float,
        cost_stress_pass: bool,
        trials_completed: int,
    ) -> ValidationVerdict:
        """Determine validation verdict based on evidence.

        Args:
            audit_passed: Whether IA-001 audit passed
            oos_observations: Number of OOS observations
            sharpe_ratio: Out-of-sample Sharpe ratio
            cost_stress_pass: Whether cost stress test passed
            trials_completed: Number of completed trials

        Returns:
            ValidationVerdict
        """
        # INVALID if audit failed
        if not audit_passed:
            return ValidationVerdict.INVALID

        # NOT_TESTED if no observations
        if oos_observations == 0:
            return ValidationVerdict.NOT_TESTED

        # INCONCLUSIVE if no clear edge
        if sharpe_ratio <= 0.3:
            return ValidationVerdict.INCONCLUSIVE

        # REJECTED if edge exists but cost stress fails
        if not cost_stress_pass:
            return ValidationVerdict.REJECTED

        # VALIDATED if all evidence passes
        return ValidationVerdict.VALIDATED

    @staticmethod
    def determine_recommendation(
        verdict: ValidationVerdict,
        audit_passed: bool,
    ) -> ValidationRecommendation:
        """Determine recommendation for Decision Engine.

        Args:
            verdict: Validation verdict
            audit_passed: Whether IA-001 audit passed

        Returns:
            ValidationRecommendation
        """
        if not audit_passed or verdict == ValidationVerdict.INVALID:
            return ValidationRecommendation.INVALID

        if verdict == ValidationVerdict.INCONCLUSIVE:
            return ValidationRecommendation.INCONCLUSIVE

        if verdict == ValidationVerdict.REJECTED:
            return ValidationRecommendation.REJECT

        if verdict == ValidationVerdict.VALIDATED:
            return ValidationRecommendation.AUTHORIZE

        return ValidationRecommendation.INVALID


class ValidationResultBuilder:
    """Build validation reports with evidence accumulation."""

    def __init__(self, hypothesis_id: str, dataset_version: str):
        """Initialize builder."""
        self.hypothesis_id = hypothesis_id
        self.dataset_version = dataset_version
        self.audit_passed = False
        self.oos_observations = 0
        self.oos_trades = 0
        self.sharpe_ratio = 0.0
        self.profit_factor = 0.0
        self.win_rate = 0.0
        self.max_drawdown = 0.0
        self.pbo_score: Optional[float] = None
        self.deflated_sharpe: Optional[float] = None
        self.baseline_sharpe = 0.0
        self.improvement = 0.0
        self.trials_attempted = 0
        self.trials_completed = 0
        self.degrees_of_freedom: Dict[str, Any] = {}
        self.cost_stress_pass = False
        self.regime_tests: Dict[str, bool] = {}
        self.brier_score = 0.0
        self.ece_score = 0.0

    def set_audit_passed(self, passed: bool) -> ValidationResultBuilder:
        """Set audit status."""
        self.audit_passed = passed
        return self

    def set_oos_metrics(
        self,
        observations: int,
        trades: int,
        sharpe: float,
        profit_factor: float,
        win_rate: float,
        max_dd: float,
    ) -> ValidationResultBuilder:
        """Set out-of-sample metrics."""
        self.oos_observations = observations
        self.oos_trades = trades
        self.sharpe_ratio = sharpe
        self.profit_factor = profit_factor
        self.win_rate = win_rate
        self.max_drawdown = max_dd
        return self

    def set_baseline_metrics(
        self,
        baseline_sharpe: float,
        improvement: float,
    ) -> ValidationResultBuilder:
        """Set baseline comparison."""
        self.baseline_sharpe = baseline_sharpe
        self.improvement = improvement
        return self

    def set_trial_metrics(
        self,
        attempted: int,
        completed: int,
        dof: Dict[str, Any],
    ) -> ValidationResultBuilder:
        """Set trial metrics."""
        self.trials_attempted = attempted
        self.trials_completed = completed
        self.degrees_of_freedom = dof
        return self

    def set_robustness_metrics(
        self,
        cost_stress_pass: bool,
        regime_tests: Dict[str, bool],
    ) -> ValidationResultBuilder:
        """Set robustness metrics."""
        self.cost_stress_pass = cost_stress_pass
        self.regime_tests = regime_tests
        return self

    def set_calibration_metrics(
        self,
        brier_score: float,
        ece_score: float,
    ) -> ValidationResultBuilder:
        """Set calibration metrics."""
        self.brier_score = brier_score
        self.ece_score = ece_score
        return self

    def set_advanced_metrics(
        self,
        pbo_score: Optional[float] = None,
        deflated_sharpe: Optional[float] = None,
    ) -> ValidationResultBuilder:
        """Set advanced metrics."""
        self.pbo_score = pbo_score
        self.deflated_sharpe = deflated_sharpe
        return self

    def build(self) -> ValidationReport:
        """Build validation report."""
        verdict = ValidationEngine.determine_verdict(
            audit_passed=self.audit_passed,
            oos_observations=self.oos_observations,
            sharpe_ratio=self.sharpe_ratio,
            cost_stress_pass=self.cost_stress_pass,
            trials_completed=self.trials_completed,
        )

        recommendation = ValidationEngine.determine_recommendation(
            verdict=verdict,
            audit_passed=self.audit_passed,
        )

        report = ValidationReport(
            hypothesis_id=self.hypothesis_id,
            dataset_version=self.dataset_version,
            verdict=verdict,
            oos_observations=self.oos_observations,
            oos_trades=self.oos_trades,
            sharpe_ratio=self.sharpe_ratio,
            profit_factor=self.profit_factor,
            win_rate=self.win_rate,
            max_drawdown=self.max_drawdown,
            pbo_score=self.pbo_score,
            deflated_sharpe=self.deflated_sharpe,
            baseline_sharpe=self.baseline_sharpe,
            improvement=self.improvement,
            trials_attempted=self.trials_attempted,
            trials_completed=self.trials_completed,
            degrees_of_freedom=self.degrees_of_freedom,
            cost_stress_pass=self.cost_stress_pass,
            regime_tests=self.regime_tests,
            brier_score=self.brier_score,
            ece_score=self.ece_score,
            recommendation=recommendation,
        )

        logger.info(
            "Built validation report",
            hypothesis_id=self.hypothesis_id,
            verdict=verdict.value,
            recommendation=recommendation.value,
        )

        return report
