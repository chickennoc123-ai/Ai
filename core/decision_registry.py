"""Decision Registry: Immutable audit trail of all decisions.

Records every decision with timestamp and status for compliance and backtesting.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from core.decision_engine import Decision
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow
from utils.logger import get_logger

logger = get_logger(__name__)


class DecisionStatus(str, Enum):
    """Status of a recorded decision."""

    PENDING = "PENDING"  # Not yet active
    ACTIVE = "ACTIVE"  # Currently deployed
    CLOSED = "CLOSED"  # Completed trading
    REVOKED = "REVOKED"  # Cancelled before execution


class DecisionRegistryError(EAFactoryError):
    """Raised when registry operation fails."""


@dataclass(frozen=True)
class DecisionRecord:
    """Immutable record of a decision."""

    decision: Decision
    recorded_at: datetime
    status: DecisionStatus
    record_id: str = ""
    performance: Optional[Dict[str, float]] = None

    def __post_init__(self) -> None:
        """Compute record ID if not provided."""
        if not self.record_id:
            data = f"{self.decision.hypothesis_id}:{self.recorded_at.isoformat()}"
            record_hash = hashlib.sha256(data.encode()).hexdigest()[:12]
            object.__setattr__(self, "record_id", record_hash)

    def is_active(self) -> bool:
        """Check if decision is currently active."""
        return self.status == DecisionStatus.ACTIVE

    def summary(self) -> Dict[str, Any]:
        """Return record summary."""
        return {
            "record_id": self.record_id,
            "decision_id": self.decision.decision_id,
            "hypothesis_id": self.decision.hypothesis_id,
            "decision": self.decision.decision.value,
            "allocation": self.decision.allocation,
            "status": self.status.value,
            "recorded_at": self.recorded_at.isoformat(),
            "performance": self.performance,
        }


class DecisionRegistry:
    """Immutable registry of all decisions ever made."""

    def __init__(self):
        """Initialize registry."""
        self._records: List[DecisionRecord] = []

    def record(self, decision: Decision) -> str:
        """Record a decision with initial PENDING status.

        Args:
            decision: Decision to record

        Returns:
            record_id for future reference
        """
        record = DecisionRecord(
            decision=decision,
            recorded_at=utcnow(),
            status=DecisionStatus.PENDING,
        )

        self._records.append(record)

        logger.info(
            "Decision recorded",
            record_id=record.record_id,
            hypothesis_id=decision.hypothesis_id,
            decision=decision.decision.value,
            allocation=decision.allocation,
        )

        return record.record_id

    def update_status(self, record_id: str, new_status: DecisionStatus) -> None:
        """Update status of a recorded decision.

        Args:
            record_id: Record ID to update
            new_status: New status

        Raises:
            DecisionRegistryError: If record not found
        """
        for i, record in enumerate(self._records):
            if record.record_id == record_id:
                # Immutable: create new record with updated status
                new_record = DecisionRecord(
                    decision=record.decision,
                    recorded_at=record.recorded_at,
                    status=new_status,
                    record_id=record.record_id,
                    performance=record.performance,
                )
                self._records[i] = new_record

                logger.info(
                    "Decision status updated",
                    record_id=record_id,
                    hypothesis_id=record.decision.hypothesis_id,
                    old_status=record.status.value,
                    new_status=new_status.value,
                )
                return

        raise DecisionRegistryError(
            f"Record not found: {record_id}",
            record_id=record_id,
        )

    def update_performance(
        self, record_id: str, performance: Dict[str, float]
    ) -> None:
        """Update performance metrics for a decision.

        Args:
            record_id: Record ID to update
            performance: Performance metrics dict

        Raises:
            DecisionRegistryError: If record not found
        """
        for i, record in enumerate(self._records):
            if record.record_id == record_id:
                # Immutable: create new record with performance
                new_record = DecisionRecord(
                    decision=record.decision,
                    recorded_at=record.recorded_at,
                    status=record.status,
                    record_id=record.record_id,
                    performance=performance,
                )
                self._records[i] = new_record

                logger.info(
                    "Decision performance updated",
                    record_id=record_id,
                    hypothesis_id=record.decision.hypothesis_id,
                )
                return

        raise DecisionRegistryError(
            f"Record not found: {record_id}",
            record_id=record_id,
        )

    def get_record(self, record_id: str) -> DecisionRecord:
        """Get a specific record by ID."""
        for record in self._records:
            if record.record_id == record_id:
                return record
        raise DecisionRegistryError(f"Record not found: {record_id}", record_id=record_id)

    def get_records_by_status(self, status: DecisionStatus) -> List[DecisionRecord]:
        """Get all records with given status."""
        return [r for r in self._records if r.status == status]

    def get_active_records(self) -> List[DecisionRecord]:
        """Get all active (ACTIVE status) records."""
        return self.get_records_by_status(DecisionStatus.ACTIVE)

    def get_records_by_hypothesis(self, hypothesis_id: str) -> List[DecisionRecord]:
        """Get all records for a hypothesis."""
        return [r for r in self._records if r.decision.hypothesis_id == hypothesis_id]

    def count_by_status(self, status: DecisionStatus) -> int:
        """Count records by status."""
        return len(self.get_records_by_status(status))

    def get_all_records(self) -> List[DecisionRecord]:
        """Get all records in chronological order."""
        return self._records.copy()

    def summary(self) -> Dict[str, Any]:
        """Return registry summary."""
        return {
            "total_records": len(self._records),
            "by_status": {
                status.value: self.count_by_status(status)
                for status in DecisionStatus
            },
            "active_records": len(self.get_active_records()),
            "records": [r.summary() for r in self._records],
        }
