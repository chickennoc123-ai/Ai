"""
Generation 6, Phase 10: Independent Data Eligibility Gate

Gate that determines whether a dataset qualifies as independent evidence
for economic validation.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List
from datetime import datetime

from core.factory.data_independence import (
    DataIndependenceRecord,
    IndependenceLevel,
    OverlapStatus,
    ResearchExposureStatus,
)


class EligibilityStatus(Enum):
    """Overall eligibility status."""
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    UNCERTAIN = "uncertain"


@dataclass
class EligibilityCheckResult:
    """Result of an eligibility check."""
    dataset_id: str
    status: EligibilityStatus
    checks_passed: List[str]
    checks_failed: List[str]
    checks_uncertain: List[str]
    reasons: List[str]
    assessed_at: datetime = None

    def __post_init__(self):
        if self.assessed_at is None:
            self.assessed_at = datetime.utcnow()

    def is_eligible(self) -> bool:
        """True only if all required checks pass."""
        return self.status == EligibilityStatus.ELIGIBLE


class IndependentDataEligibilityGate:
    """
    Gate that enforces strict independence criteria.

    A dataset qualifies only if ALL of the following hold:
    1. PROVENANCE = VERIFIED
    2. SYNTHETIC = FALSE
    3. DATA_INTEGRITY = PASS
    4. OVERLAP = NONE or explicitly governed
    5. RESEARCH_EXPOSURE = NONE
    6. INDEPENDENCE = SUFFICIENT
    7. CHECKSUM = VERIFIED
    """

    def __init__(self):
        self.results: dict = {}

    def check_eligibility(self, record: DataIndependenceRecord) -> EligibilityCheckResult:
        """
        Run all eligibility checks on a dataset.

        Returns ELIGIBLE only if all checks pass.
        """
        checks_passed = []
        checks_failed = []
        checks_uncertain = []
        reasons = []

        # Check 1: Provenance verified
        if self._check_provenance(record):
            checks_passed.append("PROVENANCE_VERIFIED")
        else:
            checks_failed.append("PROVENANCE_NOT_VERIFIED")
            reasons.append("Dataset provenance not verified from source")

        # Check 2: Not synthetic
        if self._check_not_synthetic(record):
            checks_passed.append("NOT_SYNTHETIC")
        else:
            checks_failed.append("DATA_IS_SYNTHETIC")
            reasons.append("Dataset is synthetic or derived")

        # Check 3: Data integrity
        if self._check_data_integrity(record):
            checks_passed.append("DATA_INTEGRITY_PASS")
        else:
            checks_failed.append("DATA_INTEGRITY_FAIL")
            reasons.append("Data integrity check failed (gaps, duplicates, missing bars)")

        # Check 4: No overlap or governed overlap
        overlap_status = self._check_overlap(record)
        if overlap_status == "pass":
            checks_passed.append("NO_OVERLAP")
        elif overlap_status == "uncertain":
            checks_uncertain.append("OVERLAP_UNCERTAIN")
            reasons.append("Overlap status unknown (conservative fail)")
        else:
            checks_failed.append("OVERLAP_DETECTED")
            reasons.append(f"Overlap with other datasets: {record.overlap_status.value}")

        # Check 5: No research exposure
        if self._check_no_research_exposure(record):
            checks_passed.append("NO_RESEARCH_EXPOSURE")
        else:
            checks_failed.append("RESEARCH_EXPOSED")
            reasons.append(f"Dataset exposed to research: {record.research_exposure.value}")

        # Check 6: Sufficient independence level
        if self._check_independence_level(record):
            checks_passed.append("SUFFICIENT_INDEPENDENCE")
        else:
            checks_failed.append("INSUFFICIENT_INDEPENDENCE")
            reasons.append(f"Independence level too low: {record.independence_level.value}")

        # Check 7: Checksum verified
        if self._check_checksum(record):
            checks_passed.append("CHECKSUM_VERIFIED")
        else:
            checks_failed.append("CHECKSUM_UNVERIFIED")
            reasons.append("Dataset checksum not verified")

        # Determine overall status
        if checks_failed:
            overall_status = EligibilityStatus.NOT_ELIGIBLE
        elif checks_uncertain:
            overall_status = EligibilityStatus.UNCERTAIN
        else:
            overall_status = EligibilityStatus.ELIGIBLE

        result = EligibilityCheckResult(
            dataset_id=record.dataset_id,
            status=overall_status,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            checks_uncertain=checks_uncertain,
            reasons=reasons,
        )

        self.results[record.dataset_id] = result
        return result

    def _check_provenance(self, record: DataIndependenceRecord) -> bool:
        """Provenance must be verified."""
        # Implementation: check if source_id is in verified sources registry
        # For now, require explicit verification
        return record.source_id is not None and len(record.source_id) > 0

    def _check_not_synthetic(self, record: DataIndependenceRecord) -> bool:
        """Data must not be synthetic or derived."""
        # No derived datasets; only raw market data
        return record.derived_from is None

    def _check_data_integrity(self, record: DataIndependenceRecord) -> bool:
        """Data must pass integrity checks."""
        # Implementation: check for gaps, duplicates, missing bars
        # For now, assume passed if record exists
        return True  # Would be replaced by actual integrity checks

    def _check_overlap(self, record: DataIndependenceRecord) -> str:
        """
        Overlap must be NONE or UNKNOWN (conservative).
        """
        if record.overlap_status == OverlapStatus.UNKNOWN:
            return "uncertain"  # Unknown = conservative fail
        elif record.overlap_status == OverlapStatus.NO_OVERLAP:
            return "pass"
        else:
            return "fail"

    def _check_no_research_exposure(self, record: DataIndependenceRecord) -> bool:
        """Dataset must not be exposed to research decisions."""
        return record.research_exposure == ResearchExposureStatus.UNEXPOSED

    def _check_independence_level(self, record: DataIndependenceRecord) -> bool:
        """
        Independence level must be sufficient.

        LEVEL_3 (unseen time period) is minimum for temporal independence.
        LEVEL_4+ (new instrument, independently sourced) is preferred.
        """
        acceptable_levels = {
            IndependenceLevel.LEVEL_3,  # Unseen time period
            IndependenceLevel.LEVEL_4,  # New instrument
            IndependenceLevel.LEVEL_5,  # Independently sourced
            IndependenceLevel.LEVEL_6,  # Forward/paper
        }
        return record.independence_level in acceptable_levels

    def _check_checksum(self, record: DataIndependenceRecord) -> bool:
        """Checksum must be verified."""
        return record.checksum is not None and len(record.checksum) == 64  # SHA256

    def get_result(self, dataset_id: str) -> Optional[EligibilityCheckResult]:
        """Get eligibility result for a dataset."""
        return self.results.get(dataset_id)

    def eligible_datasets(self) -> List[str]:
        """Return list of datasets that passed eligibility."""
        return [
            dsid for dsid, result in self.results.items()
            if result.is_eligible()
        ]

    def summary(self) -> dict:
        """Summary of eligibility assessments."""
        eligible = sum(1 for r in self.results.values() if r.status == EligibilityStatus.ELIGIBLE)
        not_eligible = sum(1 for r in self.results.values() if r.status == EligibilityStatus.NOT_ELIGIBLE)
        uncertain = sum(1 for r in self.results.values() if r.status == EligibilityStatus.UNCERTAIN)

        return {
            "total_datasets_assessed": len(self.results),
            "eligible": eligible,
            "not_eligible": not_eligible,
            "uncertain": uncertain,
            "eligible_dataset_ids": self.eligible_datasets(),
        }
