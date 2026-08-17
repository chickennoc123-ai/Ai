"""Evidence Aggregator: Consolidate ML validation evidence.

Combines validation reports, OOS predictions, trial ledger data, and robustness
metrics into a single authorizable evidence package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.prediction_artifact import PredictionArtifact
from core.trial_ledger import TrialLedger
from core.validation_result import ValidationReport
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)


class EvidenceAggregationError(EAFactoryError):
    """Raised when evidence aggregation fails."""


@dataclass(frozen=True)
class AggregatedEvidence:
    """Immutable package of all evidence for decision-making."""

    hypothesis_id: str
    validation_report: ValidationReport
    oos_predictions: List[PredictionArtifact]
    trial_ledger: TrialLedger
    calibration_metrics: Dict[str, float]
    robustness_tests: Dict[str, bool]
    aggregated_score: float
    confidence_level: str  # HIGH, MEDIUM, LOW
    aggregated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        """Validate aggregated evidence."""
        if not self.hypothesis_id:
            raise EvidenceAggregationError("hypothesis_id is required")

        if self.aggregated_score < 0.0 or self.aggregated_score > 1.0:
            raise EvidenceAggregationError(
                "aggregated_score must be in [0, 1]",
                score=self.aggregated_score,
            )

        if self.confidence_level not in ("HIGH", "MEDIUM", "LOW"):
            raise EvidenceAggregationError(
                "confidence_level must be HIGH, MEDIUM, or LOW",
                level=self.confidence_level,
            )

        # Verify consistency
        if (
            self.validation_report.hypothesis_id != self.hypothesis_id
            or self.trial_ledger.hypothesis_id != self.hypothesis_id
        ):
            raise EvidenceAggregationError(
                "hypothesis_id mismatch across evidence components",
            )

    def is_authorizable(self) -> bool:
        """Check if evidence meets minimum thresholds for authorization.

        Returns:
            True if evidence supports authorization

        Criteria:
            - Verdict must be VALIDATED
            - Sharpe ratio ≥ 1.0
            - Profit factor ≥ 1.5
            - Max drawdown ≤ 15%
            - PBO score ≤ 0.5
            - Cost stress test passed
            - Sufficient OOS observations
        """
        # Verdict check
        if self.validation_report.verdict.value != "VALIDATED":
            return False

        # Sharpe ratio check
        if self.validation_report.sharpe_ratio < 1.0:
            return False

        # Profit factor check
        if self.validation_report.profit_factor < 1.5:
            return False

        # Drawdown check
        if self.validation_report.max_drawdown > 0.15:
            return False

        # PBO score check
        if self.validation_report.pbo_score and self.validation_report.pbo_score > 0.5:
            return False

        # Cost stress check
        if not self.validation_report.cost_stress_pass:
            return False

        # Sufficient observations
        if self.validation_report.oos_observations < 50:
            return False

        return True

    def get_score_breakdown(self) -> Dict[str, float]:
        """Get breakdown of how aggregated score is calculated."""
        sharpe_component = min(
            self.validation_report.sharpe_ratio / 2.0, 1.0
        )  # Normalize to [0, 1]
        pf_component = min(
            self.validation_report.profit_factor / 3.0, 1.0
        )  # Normalize to [0, 1]
        wr_component = self.validation_report.win_rate  # Already [0, 1]

        # If PBO score available, reduce by PBO
        pbo_penalty = 1.0
        if self.validation_report.pbo_score:
            pbo_penalty = 1.0 - min(self.validation_report.pbo_score, 1.0)

        return {
            "sharpe_component": sharpe_component,
            "profit_factor_component": pf_component,
            "win_rate_component": wr_component,
            "pbo_penalty": pbo_penalty,
            "final_score": self.aggregated_score,
        }

    def summary(self) -> Dict[str, Any]:
        """Return aggregated evidence summary."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "is_authorizable": self.is_authorizable(),
            "aggregated_score": self.aggregated_score,
            "confidence_level": self.confidence_level,
            "validation_verdict": self.validation_report.verdict.value,
            "validation_recommendation": self.validation_report.recommendation.value,
            "sharpe_ratio": self.validation_report.sharpe_ratio,
            "profit_factor": self.validation_report.profit_factor,
            "win_rate": self.validation_report.win_rate,
            "max_drawdown": self.validation_report.max_drawdown,
            "pbo_score": self.validation_report.pbo_score,
            "cost_stress_pass": self.validation_report.cost_stress_pass,
            "oos_observations": self.validation_report.oos_observations,
            "oos_trades": self.validation_report.oos_trades,
            "trials_completed": self.validation_report.trials_completed,
            "oos_predictions_count": len(self.oos_predictions),
            "calibration_metrics": self.calibration_metrics,
            "robustness_tests": self.robustness_tests,
            "aggregated_at": self.aggregated_at.isoformat(),
            "score_breakdown": self.get_score_breakdown(),
        }


class EvidenceAggregator:
    """Aggregate evidence from multiple sources."""

    def aggregate(
        self,
        validation_report: ValidationReport,
        oos_predictions: List[PredictionArtifact],
        trial_ledger: TrialLedger,
        calibration_metrics: Optional[Dict[str, float]] = None,
        robustness_tests: Optional[Dict[str, bool]] = None,
    ) -> AggregatedEvidence:
        """Aggregate evidence from all sources.

        Args:
            validation_report: ValidationReport from ML pipeline
            oos_predictions: List of out-of-sample predictions
            trial_ledger: TrialLedger with research accounting
            calibration_metrics: Prediction calibration metrics (brier, ece)
            robustness_tests: Dict of robustness test results

        Returns:
            AggregatedEvidence

        Raises:
            EvidenceAggregationError: If aggregation fails
        """
        # Compute aggregated score
        aggregated_score = self._compute_aggregated_score(
            validation_report,
            oos_predictions,
            trial_ledger,
        )

        # Determine confidence level
        confidence_level = self._determine_confidence_level(
            aggregated_score,
            len(oos_predictions),
            len(trial_ledger.get_completed_trials()),
        )

        evidence = AggregatedEvidence(
            hypothesis_id=validation_report.hypothesis_id,
            validation_report=validation_report,
            oos_predictions=oos_predictions,
            trial_ledger=trial_ledger,
            calibration_metrics=calibration_metrics or {},
            robustness_tests=robustness_tests or {},
            aggregated_score=aggregated_score,
            confidence_level=confidence_level,
        )

        logger.info(
            "Evidence aggregated",
            hypothesis_id=validation_report.hypothesis_id,
            aggregated_score=aggregated_score,
            confidence_level=confidence_level,
            is_authorizable=evidence.is_authorizable(),
        )

        return evidence

    def _compute_aggregated_score(
        self,
        validation_report: ValidationReport,
        oos_predictions: List[PredictionArtifact],
        trial_ledger: TrialLedger,
    ) -> float:
        """Compute aggregated score from evidence components."""
        # Sharpe component: [0, 1]
        sharpe_score = min(validation_report.sharpe_ratio / 2.0, 1.0)

        # Profit factor component: [0, 1]
        pf_score = min(validation_report.profit_factor / 3.0, 1.0)

        # Win rate component: already [0, 1]
        wr_score = validation_report.win_rate

        # Observation count component: min of [0, 1]
        obs_score = min(validation_report.oos_observations / 500.0, 1.0)

        # Trial efficiency: [0, 1]
        trials_completed = len(trial_ledger.get_completed_trials())
        if trials_completed > 0:
            efficiency = min(
                validation_report.sharpe_ratio / trials_completed, 1.0
            )
        else:
            efficiency = 0.0

        # PBO penalty: reduce if PBO score present
        pbo_penalty = 1.0
        if validation_report.pbo_score:
            pbo_penalty = 1.0 - min(validation_report.pbo_score, 1.0)

        # Aggregate (equal weights, then apply PBO penalty)
        base_score = (sharpe_score + pf_score + wr_score + obs_score + efficiency) / 5.0
        final_score = base_score * pbo_penalty

        return min(final_score, 1.0)

    def _determine_confidence_level(
        self,
        aggregated_score: float,
        num_predictions: int,
        num_trials: int,
    ) -> str:
        """Determine confidence level based on evidence quality."""
        # High confidence: score >= 0.7, sufficient predictions and trials
        if aggregated_score >= 0.7 and num_predictions >= 100 and num_trials >= 10:
            return "HIGH"

        # Medium confidence: score >= 0.5
        if aggregated_score >= 0.5:
            return "MEDIUM"

        # Low confidence: score < 0.5
        return "LOW"
