"""Risk Governance: Portfolio-level risk constraints and enforcement.

Applies hard limits on total allocation, correlation, and position counts
to prevent over-concentration and portfolio degradation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.decision_engine import Decision, DecisionType
from core.evidence_aggregator import AggregatedEvidence
from utils.exceptions import EAFactoryError
from utils.logger import get_logger

logger = get_logger(__name__)


class RiskLimitExceededError(EAFactoryError):
    """Raised when risk limit would be exceeded."""


class RiskGovernanceError(EAFactoryError):
    """Raised when risk governance operation fails."""


@dataclass(frozen=True)
class RiskGovernanceConfig:
    """Risk governance configuration."""

    max_total_allocation: float = 0.40  # 40% max total deployed
    max_per_strategy: float = 0.20  # 20% max per strategy
    max_drawdown: float = 0.15  # 15% max drawdown
    max_correlation: float = 0.70  # 0.70 max correlation
    max_positions: int = 5  # Max concurrent positions
    min_allocation: float = 0.01  # 1% minimum allocation

    def __post_init__(self) -> None:
        """Validate configuration."""
        if not 0.0 < self.max_total_allocation <= 1.0:
            raise RiskGovernanceError("max_total_allocation must be in (0, 1]")
        if not 0.0 < self.max_per_strategy <= 1.0:
            raise RiskGovernanceError("max_per_strategy must be in (0, 1]")
        if self.max_per_strategy > self.max_total_allocation:
            raise RiskGovernanceError(
                "max_per_strategy cannot exceed max_total_allocation"
            )
        if not 0.0 < self.max_drawdown <= 1.0:
            raise RiskGovernanceError("max_drawdown must be in (0, 1]")
        if not 0.0 <= self.max_correlation <= 1.0:
            raise RiskGovernanceError("max_correlation must be in [0, 1]")
        if self.max_positions <= 0:
            raise RiskGovernanceError("max_positions must be positive")


class RiskGovernance:
    """Enforce portfolio-level risk constraints."""

    def __init__(self, config: Optional[RiskGovernanceConfig] = None):
        """Initialize risk governance.

        Args:
            config: RiskGovernanceConfig (uses defaults if None)
        """
        self.config = config or RiskGovernanceConfig()
        self.active_decisions: List[Decision] = []

    def can_authorize(self, decision: Decision, evidence: AggregatedEvidence) -> bool:
        """Check if a decision can be authorized within risk limits.

        Args:
            decision: Decision to check
            evidence: Evidence used to make decision

        Returns:
            True if decision can be authorized
        """
        if decision.decision != DecisionType.AUTHORIZE:
            return True  # REJECT/HOLD/OBSERVE always allowed

        # Check total allocation
        if not self._check_total_allocation(decision.allocation):
            return False

        # Check per-strategy limit
        if decision.allocation > self.config.max_per_strategy:
            return False

        # Check position count
        if len(self.active_decisions) >= self.config.max_positions:
            return False

        # Check correlation with existing strategies (simplified)
        if self._correlation_exceeds_limit(evidence):
            return False

        return True

    def add_decision(self, decision: Decision, evidence: AggregatedEvidence) -> None:
        """Add authorized decision to active portfolio.

        Args:
            decision: Decision to add
            evidence: Evidence used for decision

        Raises:
            RiskLimitExceededError: If adding would violate limits
        """
        if not self.can_authorize(decision, evidence):
            reason = self._get_rejection_reason(decision, evidence)
            raise RiskLimitExceededError(
                f"Cannot authorize decision: {reason}",
                hypothesis_id=decision.hypothesis_id,
            )

        self.active_decisions.append(decision)

        logger.info(
            "Decision added to portfolio",
            hypothesis_id=decision.hypothesis_id,
            allocation=decision.allocation,
            total_allocation=self.get_total_allocation(),
            num_positions=len(self.active_decisions),
        )

    def remove_decision(self, hypothesis_id: str) -> Optional[Decision]:
        """Remove decision from active portfolio (e.g., strategy stopped).

        Args:
            hypothesis_id: Hypothesis to remove

        Returns:
            Removed decision or None if not found
        """
        for i, d in enumerate(self.active_decisions):
            if d.hypothesis_id == hypothesis_id:
                removed = self.active_decisions.pop(i)
                logger.info(
                    "Decision removed from portfolio",
                    hypothesis_id=hypothesis_id,
                    allocation=removed.allocation,
                    total_allocation=self.get_total_allocation(),
                )
                return removed
        return None

    def get_total_allocation(self) -> float:
        """Get total capital allocation across active decisions."""
        return sum(d.allocation for d in self.active_decisions)

    def get_remaining_capacity(self) -> float:
        """Get remaining allocation capacity."""
        return max(0.0, self.config.max_total_allocation - self.get_total_allocation())

    def _check_total_allocation(self, additional: float) -> bool:
        """Check if additional allocation would exceed limit."""
        total = self.get_total_allocation() + additional
        return total <= self.config.max_total_allocation

    def _correlation_exceeds_limit(self, evidence: AggregatedEvidence) -> bool:
        """Check if evidence would exceed correlation limit with portfolio.

        Simplified: placeholder for full correlation matrix in production.
        In production, would correlate against historical returns of active strategies.
        """
        # For now, if we have many active strategies, reduce allocation
        if len(self.active_decisions) >= 3:
            return True  # Simplified: reject if already have 3+ strategies

        return False

    def _get_rejection_reason(
        self, decision: Decision, evidence: AggregatedEvidence
    ) -> str:
        """Determine why decision would violate risk limits."""
        total = self.get_total_allocation() + decision.allocation
        if total > self.config.max_total_allocation:
            return (
                f"Total allocation would exceed limit: "
                f"{total:.1%} > {self.config.max_total_allocation:.1%}"
            )

        if decision.allocation > self.config.max_per_strategy:
            return (
                f"Allocation exceeds per-strategy limit: "
                f"{decision.allocation:.1%} > {self.config.max_per_strategy:.1%}"
            )

        if len(self.active_decisions) >= self.config.max_positions:
            return (
                f"Position limit reached: "
                f"{len(self.active_decisions)} >= {self.config.max_positions}"
            )

        if self._correlation_exceeds_limit(evidence):
            return (
                f"Correlation with existing strategies exceeds limit: "
                f"{self.config.max_correlation:.2f}"
            )

        return "Unknown risk limit violation"

    def summary(self) -> Dict[str, Any]:
        """Return risk governance summary."""
        return {
            "config": {
                "max_total_allocation": self.config.max_total_allocation,
                "max_per_strategy": self.config.max_per_strategy,
                "max_drawdown": self.config.max_drawdown,
                "max_correlation": self.config.max_correlation,
                "max_positions": self.config.max_positions,
                "min_allocation": self.config.min_allocation,
            },
            "portfolio": {
                "num_active_decisions": len(self.active_decisions),
                "total_allocation": self.get_total_allocation(),
                "remaining_capacity": self.get_remaining_capacity(),
                "decisions": [d.summary() for d in self.active_decisions],
            },
        }
