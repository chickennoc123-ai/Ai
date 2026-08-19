"""
Generation 6, Phase 1-2: Data Independence Contract & Overlap Engine

Formal classification of evidence independence levels and detection of overlaps
between evaluation datasets.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Set, List, Dict, Any
from datetime import datetime
import hashlib


class IndependenceLevel(Enum):
    """Levels of independence for evaluation datasets."""
    LEVEL_0 = "same_observations"  # identical rows
    LEVEL_1 = "different_processing"  # same rows, different calculation
    LEVEL_2 = "different_split"  # different train/test of same historical data
    LEVEL_3 = "unseen_time_period"  # genuinely later timestamp range
    LEVEL_4 = "new_instrument"  # different symbol/market
    LEVEL_5 = "independently_sourced"  # from unrelated source
    LEVEL_6 = "forward_paper"  # genuine forward/paper observation


class OverlapStatus(Enum):
    """Classification of overlap between datasets."""
    NO_OVERLAP = "no_overlap"
    PARTIAL_OVERLAP = "partial_overlap"
    SUBSTANTIAL_OVERLAP = "substantial_overlap"
    IDENTICAL_DATA = "identical_data"
    UNKNOWN = "unknown"


class ResearchExposureStatus(Enum):
    """Whether a dataset was exposed to research decisions."""
    UNEXPOSED = "unexposed"
    EXPOSED_TO_HYPOTHESIS = "exposed_to_hypothesis_generation"
    EXPOSED_TO_SELECTION = "exposed_to_hypothesis_selection"
    EXPOSED_TO_FEATURES = "exposed_to_feature_design"
    EXPOSED_TO_PARAMETERS = "exposed_to_parameter_design"
    EXPOSED_TO_CANDIDATE = "exposed_to_candidate_generation"
    EXPOSED_TO_REJECTION = "exposed_to_candidate_rejection"
    EXPOSED_TO_POSTMORTEM = "exposed_to_postmortem"
    EXPOSED_TO_PRIORITIZATION = "exposed_to_research_prioritization"
    FULLY_EXPOSED = "fully_exposed"


@dataclass
class DataOverlapMetrics:
    """Measured overlap between two datasets."""
    timestamp_overlap_count: int = 0
    timestamp_overlap_percentage: float = 0.0
    instrument_overlap: bool = False
    timeframe_overlap: bool = False
    price_overlap_count: int = 0
    source_overlap: bool = False
    checksum_identity: bool = False
    coverage_overlap_bars: int = 0
    coverage_overlap_percentage: float = 0.0


@dataclass
class DataIndependenceRecord:
    """Formal record of a dataset's independence status."""
    dataset_id: str
    source_id: str
    instrument: str
    timeframe: str
    coverage_start: datetime
    coverage_end: datetime
    timezone: str
    price_type: str  # OHLC, bid/ask, synthetic, etc.
    checksum: str  # SHA256 of complete dataset
    parent_dataset_ids: Set[str] = field(default_factory=set)
    derived_from: Optional[str] = None  # source dataset if derived

    # Independence assessment
    independence_level: IndependenceLevel = IndependenceLevel.LEVEL_0
    overlap_status: OverlapStatus = OverlapStatus.UNKNOWN
    research_exposure: ResearchExposureStatus = ResearchExposureStatus.UNEXPOSED

    # Eligibility
    eligibility_status: str = "PENDING"  # ELIGIBLE, NOT_ELIGIBLE, UNCERTAIN
    eligibility_reason: Optional[str] = None

    # Audit trail
    assessed_at: datetime = field(default_factory=datetime.utcnow)
    assessed_by: str = "generation_6_audit"

    def is_eligible_for_validation(self) -> bool:
        """Datasets with UNKNOWN overlap do not qualify."""
        return (
            self.eligibility_status == "ELIGIBLE" and
            self.research_exposure == ResearchExposureStatus.UNEXPOSED and
            self.overlap_status != OverlapStatus.UNKNOWN
        )


@dataclass
class DataOverlapReport:
    """Complete overlap analysis between two datasets."""
    dataset_a_id: str
    dataset_b_id: str
    metrics: DataOverlapMetrics
    overlap_status: OverlapStatus
    observations: List[str] = field(default_factory=list)
    assessed_at: datetime = field(default_factory=datetime.utcnow)

    def is_independent(self) -> bool:
        """True only if NO overlap detected."""
        return self.overlap_status == OverlapStatus.NO_OVERLAP


class DataOverlapEngine:
    """Machine-checkable overlap detection between datasets."""

    def __init__(self):
        self.overlap_reports: Dict[tuple, DataOverlapReport] = {}
        self.datasets: Dict[str, DataIndependenceRecord] = {}

    def register_dataset(self, record: DataIndependenceRecord) -> None:
        """Register a dataset for overlap analysis."""
        self.datasets[record.dataset_id] = record

    def compute_timestamp_overlap(self,
                                 dataset_a_start: datetime,
                                 dataset_a_end: datetime,
                                 dataset_b_start: datetime,
                                 dataset_b_end: datetime) -> tuple:
        """Compute timestamp overlap between two datasets."""
        overlap_start = max(dataset_a_start, dataset_b_start)
        overlap_end = min(dataset_a_end, dataset_b_end)

        if overlap_start > overlap_end:
            return (0, 0.0)

        a_duration = (dataset_a_end - dataset_a_start).total_seconds()
        overlap_duration = (overlap_end - overlap_start).total_seconds()
        overlap_pct = (overlap_duration / a_duration * 100) if a_duration > 0 else 0.0

        return (int(overlap_duration), overlap_pct)

    def detect_overlap(self,
                      dataset_a_id: str,
                      dataset_b_id: str,
                      a_records: Optional[List[Dict]] = None,
                      b_records: Optional[List[Dict]] = None) -> DataOverlapReport:
        """
        Detect overlap between two datasets.

        If a_records/b_records not provided, uses only metadata.
        If provided, performs deep comparison.
        """
        a = self.datasets.get(dataset_a_id)
        b = self.datasets.get(dataset_b_id)

        if not a or not b:
            raise ValueError(f"Dataset not registered: {dataset_a_id} or {dataset_b_id}")

        metrics = DataOverlapMetrics()
        observations = []

        # Checksum identity check (strongest signal)
        if a.checksum == b.checksum:
            observations.append("Checksums are identical")
            overlap_status = OverlapStatus.IDENTICAL_DATA
        else:
            # Metadata overlap checks
            if a.instrument == b.instrument:
                metrics.instrument_overlap = True
                observations.append("Same instrument")

            if a.timeframe == b.timeframe:
                metrics.timeframe_overlap = True
                observations.append("Same timeframe")

            if a.source_id == b.source_id:
                metrics.source_overlap = True
                observations.append("Same source")

            # Timestamp overlap (if same instrument/timeframe)
            if metrics.instrument_overlap and metrics.timeframe_overlap:
                ts_overlap_count, ts_overlap_pct = self.compute_timestamp_overlap(
                    a.coverage_start, a.coverage_end,
                    b.coverage_start, b.coverage_end
                )
                if ts_overlap_count > 0:
                    metrics.timestamp_overlap_count = ts_overlap_count
                    metrics.timestamp_overlap_percentage = ts_overlap_pct
                    observations.append(
                        f"Timestamp overlap: {ts_overlap_pct:.1f}% "
                        f"({ts_overlap_count} seconds)"
                    )
                else:
                    observations.append("No timestamp overlap")

            # Record-level checks (if data provided)
            if a_records and b_records:
                overlap_count = self._count_record_overlap(a_records, b_records)
                if overlap_count > 0:
                    metrics.price_overlap_count = overlap_count
                    observations.append(f"Price-bar overlap: {overlap_count} records")

            # Classify overall overlap
            if metrics.timestamp_overlap_percentage > 90:
                overlap_status = OverlapStatus.SUBSTANTIAL_OVERLAP
            elif metrics.timestamp_overlap_percentage > 10:
                overlap_status = OverlapStatus.PARTIAL_OVERLAP
            else:
                overlap_status = OverlapStatus.NO_OVERLAP

        report = DataOverlapReport(
            dataset_a_id=dataset_a_id,
            dataset_b_id=dataset_b_id,
            metrics=metrics,
            overlap_status=overlap_status,
            observations=observations
        )

        self.overlap_reports[(dataset_a_id, dataset_b_id)] = report
        return report

    def _count_record_overlap(self, a_records: List[Dict], b_records: List[Dict]) -> int:
        """Count identical price records (timestamp + OHLC)."""
        a_hashes = {
            hashlib.sha256(
                f"{r.get('timestamp')}:{r.get('open')}:{r.get('high')}:{r.get('low')}:{r.get('close')}".encode()
            ).hexdigest()
            for r in a_records
        }

        overlap = 0
        for b_record in b_records:
            b_hash = hashlib.sha256(
                f"{b_record.get('timestamp')}:{b_record.get('open')}:{b_record.get('high')}:{b_record.get('low')}:{b_record.get('close')}".encode()
            ).hexdigest()
            if b_hash in a_hashes:
                overlap += 1

        return overlap

    def classify_overlap(self, overlap_status: OverlapStatus) -> str:
        """Classify overlap for eligibility."""
        if overlap_status == OverlapStatus.UNKNOWN:
            return "NOT_ELIGIBLE"  # Unknown = conservative fail
        elif overlap_status == OverlapStatus.NO_OVERLAP:
            return "ELIGIBLE"
        elif overlap_status == OverlapStatus.IDENTICAL_DATA:
            return "NOT_ELIGIBLE"
        elif overlap_status == OverlapStatus.SUBSTANTIAL_OVERLAP:
            return "NOT_ELIGIBLE"
        else:  # PARTIAL_OVERLAP
            return "UNCERTAIN"


class ResearchExposureEngine:
    """Track research exposure of datasets."""

    def __init__(self):
        self.exposure_records: Dict[str, Set[ResearchExposureStatus]] = {}

    def expose_dataset(self, dataset_id: str, exposure_type: ResearchExposureStatus) -> None:
        """Record that a dataset was exposed to a research decision."""
        if dataset_id not in self.exposure_records:
            self.exposure_records[dataset_id] = set()
        self.exposure_records[dataset_id].add(exposure_type)

    def get_exposure_status(self, dataset_id: str) -> ResearchExposureStatus:
        """Get aggregate exposure status for a dataset."""
        if dataset_id not in self.exposure_records or not self.exposure_records[dataset_id]:
            return ResearchExposureStatus.UNEXPOSED

        if ResearchExposureStatus.FULLY_EXPOSED in self.exposure_records[dataset_id]:
            return ResearchExposureStatus.FULLY_EXPOSED

        # If exposed to any meaningful research decision
        if any(
            exp in self.exposure_records[dataset_id]
            for exp in [
                ResearchExposureStatus.EXPOSED_TO_HYPOTHESIS,
                ResearchExposureStatus.EXPOSED_TO_CANDIDATE,
                ResearchExposureStatus.EXPOSED_TO_REJECTION,
                ResearchExposureStatus.EXPOSED_TO_PRIORITIZATION,
            ]
        ):
            return ResearchExposureStatus.FULLY_EXPOSED

        # Otherwise, report specific exposure
        if len(self.exposure_records[dataset_id]) == 1:
            return list(self.exposure_records[dataset_id])[0]

        return ResearchExposureStatus.FULLY_EXPOSED

    def is_clean(self, dataset_id: str) -> bool:
        """True if dataset has no research exposure."""
        return self.get_exposure_status(dataset_id) == ResearchExposureStatus.UNEXPOSED
