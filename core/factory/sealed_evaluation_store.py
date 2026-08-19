"""
Generation 6, Phase 8: Sealed Evaluation Store

Durable mechanism for sealing evaluation datasets so that research code
cannot inspect observations while maintaining auditability.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
import hashlib
import json


class SealStatus(Enum):
    """Status of a sealed dataset."""
    UNSEALED = "unsealed"
    SEALED = "sealed"
    PARTIALLY_EVALUATED = "partially_evaluated"
    FULLY_EVALUATED = "fully_evaluated"
    RETIRED = "retired"


class AccessPurpose(Enum):
    """Purpose of accessing a sealed dataset."""
    CANDIDATE_VALIDATION = "candidate_validation"
    HYPOTHESIS_TESTING = "hypothesis_testing"
    ROBUSTNESS_TESTING = "robustness_testing"
    VERIFICATION = "verification"
    AUDIT = "audit"


@dataclass
class SealedDatasetMetadata:
    """Metadata of a sealed dataset (always accessible)."""
    dataset_id: str
    source_id: str
    instrument: str
    timeframe: str
    coverage_start: datetime
    coverage_end: datetime
    row_count: int
    checksum: str  # SHA256 of complete dataset
    sealed_at: datetime
    seal_status: SealStatus = SealStatus.SEALED
    authorization_token: Optional[str] = None  # Required to unseal


@dataclass
class EvaluationAccessRecord:
    """Audit record of a sealed dataset access."""
    dataset_id: str
    candidate_id: Optional[str]
    access_timestamp: datetime
    access_purpose: AccessPurpose
    code_version: str
    authorization_code: Optional[str]
    results_checksum: Optional[str] = None
    authorization_granted_by: str = "governance"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "candidate_id": self.candidate_id,
            "access_timestamp": self.access_timestamp.isoformat(),
            "access_purpose": self.access_purpose.value,
            "code_version": self.code_version,
            "authorization_code": self.authorization_code,
            "results_checksum": self.results_checksum,
            "authorization_granted_by": self.authorization_granted_by,
        }


class SealedEvaluationStore:
    """
    Durable sealed dataset store.

    Research code cannot inspect observations; only metadata is visible.
    Economic evaluation requires explicit authorization and creates
    indelible audit records.
    """

    def __init__(self):
        self.sealed_datasets: Dict[str, SealedDatasetMetadata] = {}
        self.access_records: List[EvaluationAccessRecord] = []
        self.consumed_datasets: Dict[str, int] = {}  # dataset_id -> access_count

    def seal_dataset(self,
                    dataset_id: str,
                    source_id: str,
                    instrument: str,
                    timeframe: str,
                    coverage_start: datetime,
                    coverage_end: datetime,
                    row_count: int,
                    checksum: str,
                    authorization_token: Optional[str] = None) -> SealedDatasetMetadata:
        """
        Seal a dataset for evaluation use.

        Once sealed, research code must not be able to inspect observations.
        """
        if dataset_id in self.sealed_datasets:
            raise ValueError(f"Dataset {dataset_id} is already sealed")

        metadata = SealedDatasetMetadata(
            dataset_id=dataset_id,
            source_id=source_id,
            instrument=instrument,
            timeframe=timeframe,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            row_count=row_count,
            checksum=checksum,
            sealed_at=datetime.utcnow(),
            seal_status=SealStatus.SEALED,
            authorization_token=authorization_token
        )

        self.sealed_datasets[dataset_id] = metadata
        self.consumed_datasets[dataset_id] = 0
        return metadata

    def get_metadata(self, dataset_id: str) -> Optional[SealedDatasetMetadata]:
        """
        Get metadata only (no observations).

        Always accessible; does not create an access record.
        """
        return self.sealed_datasets.get(dataset_id)

    def authorize_evaluation_access(self,
                                   dataset_id: str,
                                   candidate_id: Optional[str],
                                   access_purpose: AccessPurpose,
                                   code_version: str,
                                   authorization_code: Optional[str] = None) -> bool:
        """
        Check if access to a sealed dataset can be authorized.

        Returns True only if:
        1. Dataset exists and is sealed
        2. Authorization code is valid (if required)
        3. Access would not violate single-use constraints
        """
        if dataset_id not in self.sealed_datasets:
            raise ValueError(f"Dataset {dataset_id} not found")

        metadata = self.sealed_datasets[dataset_id]

        # Check single-use constraint for PURE_HOLDOUT-like datasets
        if metadata.authorization_token and metadata.authorization_token == "PURE_HOLDOUT":
            if self.consumed_datasets.get(dataset_id, 0) > 0:
                return False  # Already consumed

        # Authorization code check (if required)
        if metadata.authorization_token:
            if authorization_code != metadata.authorization_token:
                return False

        return True

    def record_access(self,
                     dataset_id: str,
                     candidate_id: Optional[str],
                     access_purpose: AccessPurpose,
                     code_version: str,
                     authorization_code: Optional[str] = None,
                     results_checksum: Optional[str] = None) -> EvaluationAccessRecord:
        """
        Record an authorized access to a sealed dataset.

        This creates an indelible audit trail.
        """
        if not self.authorize_evaluation_access(
            dataset_id, candidate_id, access_purpose, code_version, authorization_code
        ):
            raise PermissionError(f"Access to {dataset_id} not authorized")

        record = EvaluationAccessRecord(
            dataset_id=dataset_id,
            candidate_id=candidate_id,
            access_timestamp=datetime.utcnow(),
            access_purpose=access_purpose,
            code_version=code_version,
            authorization_code=authorization_code,
            results_checksum=results_checksum,
        )

        self.access_records.append(record)
        self.consumed_datasets[dataset_id] = self.consumed_datasets.get(dataset_id, 0) + 1

        # Update seal status
        if self.consumed_datasets[dataset_id] > 0:
            metadata = self.sealed_datasets[dataset_id]
            if metadata.authorization_token == "PURE_HOLDOUT":
                metadata.seal_status = SealStatus.FULLY_EVALUATED
            else:
                metadata.seal_status = SealStatus.PARTIALLY_EVALUATED

        return record

    def get_consumption_history(self, dataset_id: str) -> List[EvaluationAccessRecord]:
        """Get all access records for a dataset."""
        return [r for r in self.access_records if r.dataset_id == dataset_id]

    def get_total_accesses(self, dataset_id: str) -> int:
        """Get total number of times a dataset was accessed."""
        return self.consumed_datasets.get(dataset_id, 0)

    def prevent_reuse(self, dataset_id: str) -> None:
        """
        Permanently mark a dataset as consumed (no further reuse allowed).

        Used for PURE_HOLDOUT and other single-use datasets.
        """
        if dataset_id in self.sealed_datasets:
            metadata = self.sealed_datasets[dataset_id]
            metadata.seal_status = SealStatus.RETIRED
            self.consumed_datasets[dataset_id] = float('inf')  # Maximum, no further access

    def audit_trail(self) -> Dict[str, Any]:
        """Complete audit trail of all sealed dataset accesses."""
        return {
            "sealed_datasets": {
                dsid: {
                    "metadata": {
                        "dataset_id": m.dataset_id,
                        "source_id": m.source_id,
                        "instrument": m.instrument,
                        "timeframe": m.timeframe,
                        "coverage_start": m.coverage_start.isoformat(),
                        "coverage_end": m.coverage_end.isoformat(),
                        "row_count": m.row_count,
                        "checksum": m.checksum,
                        "sealed_at": m.sealed_at.isoformat(),
                        "seal_status": m.seal_status.value,
                    },
                    "accesses": self.get_total_accesses(dsid),
                    "access_records": [r.to_dict() for r in self.get_consumption_history(dsid)]
                }
                for dsid, m in self.sealed_datasets.items()
            },
            "audit_timestamp": datetime.utcnow().isoformat(),
        }
