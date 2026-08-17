"""Decision Engine: Evidence-based capital allocation decisions.

Evaluates aggregated evidence and produces immutable decisions with
allocation recommendations and risk constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from core.evidence_aggregator import AggregatedEvidence
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)


class DecisionType(str, Enum):
    """Types of decision outcomes."""

    AUTHORIZE = "AUTHORIZE"
    REJECT = "REJECT"
    HOLD = "HOLD"
    OBSERVE = "OBSERVE"


class DecisionEngineError(EAFactoryError):
    """Raised when decision engine fails."""


@dataclass(frozen=True)
class Decision:
    """Immutable allocation decision based on evidence."""

    hypothesis_id: str
    decision: DecisionType
    allocation: float  # Percentage of total capital (0.0-1.0)
    max_position_size: float  # Maximum per position
    risk_budget: float  # Maximum loss tolerance
    reason: str
    evidence_used: AggregatedEvidence
    timestamp: datetime = field(default_factory=utcnow)
    decision_id: str = ""

    def __post_init__(self) -> None:
        """Validate and compute decision ID."""
        if not 0.0 <= self.allocation <= 1.0:
            raise DecisionEngineError(
                "allocation must be in [0, 1]",
                allocation=self.allocation,
            )

        if self.max_position_size < 0.0:
            raise DecisionEngineError(
                "max_position_size must be non-negative",
                max_position_size=self.max_position_size,
            )

        if self.risk_budget < 0.0:
            raise DecisionEngineError(
                "risk_budget must be non-negative",
                risk_budget=self.risk_budget,
            )

        # If decision is REJECT or HOLD, allocation should be 0
        if self.decision in (DecisionType.REJECT, DecisionType.HOLD):
            if self.allocation != 0.0:
                raise DecisionEngineError(
                    f"{self.decision.value} decision must have allocation=0",
                    allocation=self.allocation,
                )

        # Compute decision ID if not provided
        if not self.decision_id:
            import hashlib

            data = f"{self.hypothesis_id}:{self.decision.value}:{self.timestamp.isoformat()}"
            decision_hash = hashlib.sha256(data.encode()).hexdigest()[:12]
            object.__setattr__(self, "decision_id", decision_hash)

    def is_active(self) -> bool:
        """Check if decision results in active trading."""
        return self.decision == DecisionType.AUTHORIZE and self.allocation > 0.0

    def summary(self) -> Dict[str, Any]:
        """Return decision summary."""
        return {
            "decision_id": self.decision_id,
            "hypothesis_id": self.hypothesis_id,
            "decision": self.decision.value,
            "allocation": self.allocation,
            "max_position_size": self.max_position_size,
            "risk_budget": self.risk_budget,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
            "evidence_score": self.evidence_used.aggregated_score,
            "evidence_confidence": self.evidence_used.confidence_level,
        }


class DecisionEngine:
    """Make allocation decisions based on aggregated evidence."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize decision engine.

        Args:
            config: Configuration dict with parameters:
                - max_total_allocation: Max % of total capital deployed
                - max_per_strategy: Max % per strategy
                - max_drawdown: Max drawdown tolerance
                - min_allocation: Minimum allocation if authorized
        """
        self.config = config
        self.decisions: list[Decision] = []

    def evaluate(self, evidence: AggregatedEvidence) -> Decision:
        """Evaluate evidence and produce a decision.

        Args:
            evidence: AggregatedEvidence to evaluate

        Returns:
            Decision with allocation and constraints

        Logic:
            1. If evidence not authorizable → REJECT
            2. If evidence authorizable → AUTHORIZE with calculated allocation
            3. Calculate allocation based on evidence quality
            4. Apply risk governance constraints
        """
        # 1. Check if evidence meets authorization thresholds
        if not evidence.is_authorizable():
            reason = self._get_rejection_reason(evidence)
            decision = Decision(
                hypothesis_id=evidence.hypothesis_id,
                decision=DecisionType.REJECT,
                allocation=0.0,
                max_position_size=0.0,
                risk_budget=0.0,
                reason=reason,
                evidence_used=evidence,
            )

            logger.warning(
                "Decision: REJECT",
                hypothesis_id=evidence.hypothesis_id,
                reason=reason,
            )

            self.decisions.append(decision)
            return decision

        # 2. Calculate allocation based on evidence quality
        base_allocation = self._calculate_base_allocation(evidence)

        # 3. Apply constraints
        final_allocation = self._apply_allocation_constraints(base_allocation)

        # 4. Calculate position sizing and risk budget
        max_position_size = self._calculate_position_size(final_allocation)
        risk_budget = self._calculate_risk_budget(final_allocation, evidence)

        decision = Decision(
            hypothesis_id=evidence.hypothesis_id,
            decision=DecisionType.AUTHORIZE,
            allocation=final_allocation,
            max_position_size=max_position_size,
            risk_budget=risk_budget,
            reason="Evidence validated and risk approved",
            evidence_used=evidence,
        )

        logger.info(
            "Decision: AUTHORIZE",
            hypothesis_id=evidence.hypothesis_id,
            allocation=final_allocation,
            max_position_size=max_position_size,
            risk_budget=risk_budget,
        )

        self.decisions.append(decision)
        return decision

    def _get_rejection_reason(self, evidence: AggregatedEvidence) -> str:
        """Determine why evidence was rejected."""
        # Check specific thresholds
        if evidence.validation_report.sharpe_ratio < 1.0:
            return f"Insufficient Sharpe ratio: {evidence.validation_report.sharpe_ratio:.2f} < 1.0"

        if evidence.validation_report.profit_factor < 1.5:
            return f"Insufficient profit factor: {evidence.validation_report.profit_factor:.2f} < 1.5"

        if evidence.validation_report.max_drawdown > 0.15:
            return f"Excessive drawdown: {evidence.validation_report.max_drawdown:.2%} > 15%"

        if not evidence.validation_report.cost_stress_pass:
            return "Failed cost stress test"

        if evidence.validation_report.oos_observations < 50:
            return f"Insufficient observations: {evidence.validation_report.oos_observations} < 50"

        return "Evidence below authorization thresholds"

    def _calculate_base_allocation(self, evidence: AggregatedEvidence) -> float:
        """Calculate base allocation from evidence quality.

        Formula:
        - Sharpe-based: min(sharpe / 2.0, 0.25) [cap at 25%]
        - Quality multiplier: min(win_rate / 0.5, 1.0)
        - PF multiplier: min(profit_factor / 2.0, 1.0)
        - Confidence multiplier: HIGH=1.0, MEDIUM=0.75, LOW=0.5
        - Final: base * quality * pf * confidence * safety_factor(0.5)
        """
        sharpe = evidence.validation_report.sharpe_ratio
        win_rate = evidence.validation_report.win_rate
        pf = evidence.validation_report.profit_factor

        # Sharpe component: cap at 25%
        base_allocation = min(sharpe / 2.0, 0.25)

        # Quality multiplier
        quality_multiplier = min(win_rate / 0.5, 1.0)

        # Profit factor multiplier
        pf_multiplier = min(pf / 2.0, 1.0)

        # Confidence multiplier
        confidence_multiplier = {
            "HIGH": 1.0,
            "MEDIUM": 0.75,
            "LOW": 0.5,
        }.get(evidence.confidence_level, 0.5)

        # PBO penalty if available
        pbo_penalty = 1.0
        if evidence.validation_report.pbo_score:
            pbo_penalty = 1.0 - min(evidence.validation_report.pbo_score, 1.0)

        # Safety factor
        safety_factor = 0.5

        # Combined
        allocation = (
            base_allocation
            * quality_multiplier
            * pf_multiplier
            * confidence_multiplier
            * pbo_penalty
            * safety_factor
        )

        return min(allocation, 0.25)  # Cap at 25%

    def _apply_allocation_constraints(self, allocation: float) -> float:
        """Apply risk governance constraints to allocation."""
        # Maximum per strategy
        max_per_strategy = self.config.get("max_per_strategy", 0.20)
        allocation = min(allocation, max_per_strategy)

        # Minimum allocation (if authorizing)
        min_allocation = self.config.get("min_allocation", 0.01)
        if allocation > 0:
            allocation = max(allocation, min_allocation)

        return allocation

    def _calculate_position_size(self, allocation: float) -> float:
        """Calculate maximum position size from allocation.

        Position size = allocation * notional_account_size
        For now, we return allocation as proxy (broker-specific in production)
        """
        return allocation

    def _calculate_risk_budget(
        self, allocation: float, evidence: AggregatedEvidence
    ) -> float:
        """Calculate risk budget (maximum loss tolerance) from allocation.

        Risk budget = allocation * max_drawdown_tolerance
        """
        max_drawdown_tolerance = self.config.get("max_drawdown_tolerance", 0.15)
        risk_budget = allocation * max_drawdown_tolerance
        return risk_budget

    def get_decisions(self) -> list[Decision]:
        """Get all decisions made."""
        return self.decisions.copy()

    def get_active_decisions(self) -> list[Decision]:
        """Get active (AUTHORIZE) decisions."""
        return [d for d in self.decisions if d.is_active()]

    def get_total_allocation(self) -> float:
        """Get total allocation across active decisions."""
        return sum(d.allocation for d in self.get_active_decisions())

    def summary(self) -> Dict[str, Any]:
        """Return engine summary."""
        active = self.get_active_decisions()
        return {
            "total_decisions": len(self.decisions),
            "authorized_decisions": len(active),
            "total_allocation": self.get_total_allocation(),
            "decisions": [d.summary() for d in self.decisions],
        }
