"""
OGD-4 Data Acquisition Workstream: Primary Holdout Acquisition Gate.

Implements the source-verification, artifact-integrity, and independence
checks a candidate primary-holdout artifact must pass BEFORE it may ever be
sealed via ``core.factory.evidence_vault.EvidenceVault``. Sealing itself is
a separate, later, deliberate step -- this module's job is only to decide
ELIGIBLE / INELIGIBLE, never to seal.

Nothing here downloads, fabricates, or synthesizes market data. It
classifies source candidates (Phase 2-3 of the acquisition spec) and
validates already-acquired artifact bytes (Phase 6-8), using the same
"UNKNOWN = NOT_ELIGIBLE" default as the rest of the OGD-4 framework
(``core.factory.data_independence``).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import hashlib

from core.factory.data_independence import (
    DataIndependenceRecord,
    DataOverlapEngine,
    IndependenceLevel,
    OverlapStatus,
    ResearchExposureStatus,
)


# ============================================================
# PHASE 2-3: SOURCE CANDIDATE EVALUATION
# ============================================================


class SourceAccessStatus(Enum):
    AVAILABLE = "AVAILABLE"
    ACCESS_FAILED = "ACCESS_FAILED"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"


class ProvenanceStatus(Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class SourceEligibilityStatus(Enum):
    AVAILABLE = "AVAILABLE"
    ACCESS_FAILED = "ACCESS_FAILED"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    PROVENANCE_FAILED = "PROVENANCE_FAILED"
    INELIGIBLE = "INELIGIBLE"
    ELIGIBLE = "ELIGIBLE"


@dataclass
class SourceCandidate:
    """One attempted acquisition path, evaluated honestly."""
    source_id: str
    source_name: str
    source_url: str
    source_type: str  # "primary" | "documented_secondary" | "unverified_mirror" | "user_provided"
    publisher: str
    claimed_origin: str  # e.g. "Dukascopy Bank SA"
    actual_origin_evidence: str  # what actually supports the claim; "" if none
    access_status: SourceAccessStatus
    network_status: str  # raw description, e.g. "HTTP 403 (proxy policy denial)"
    license_status: str
    download_method: str
    download_timestamp: Optional[datetime] = None
    notes: str = ""

    # Computed by evaluate_source_candidate(), not set directly
    provenance_status: ProvenanceStatus = ProvenanceStatus.UNKNOWN
    identity_status: str = "UNVERIFIED"
    eligibility_status: SourceEligibilityStatus = SourceEligibilityStatus.AMBIGUOUS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "publisher": self.publisher,
            "claimed_origin": self.claimed_origin,
            "actual_origin_evidence": self.actual_origin_evidence,
            "access_status": self.access_status.value,
            "network_status": self.network_status,
            "license_status": self.license_status,
            "download_method": self.download_method,
            "download_timestamp": self.download_timestamp.isoformat() if self.download_timestamp else None,
            "provenance_status": self.provenance_status.value,
            "identity_status": self.identity_status,
            "eligibility_status": self.eligibility_status.value,
            "notes": self.notes,
        }


def evaluate_source_candidate(candidate: SourceCandidate) -> SourceCandidate:
    """
    Apply Phase 3 source-verification rules in place and return the
    candidate with provenance_status / identity_status / eligibility_status
    filled in.

    Rules (all conservative -- default to rejection, never to acceptance):

    - A claimed_origin string is NEVER sufficient evidence on its own.
      ``actual_origin_evidence`` must be non-empty and describe something
      concrete (a matching checksum against a known-good artifact, a
      reproducible download methodology hitting the claimed publisher's own
      endpoint, documented chain of custody) -- not a restated claim.
    - access_status != AVAILABLE => INELIGIBLE regardless of provenance
      (there are no bytes to seal).
    - provenance_status != VERIFIED => INELIGIBLE ("probably Dukascopy" is
      not accepted; unverified mirrors are rejected, not provisionally
      trusted).
    """
    if candidate.access_status == SourceAccessStatus.ACCESS_FAILED:
        candidate.provenance_status = ProvenanceStatus.UNKNOWN
        candidate.identity_status = "UNVERIFIED"
        candidate.eligibility_status = SourceEligibilityStatus.ACCESS_FAILED
        return candidate

    if candidate.access_status == SourceAccessStatus.NOT_FOUND:
        candidate.provenance_status = ProvenanceStatus.UNKNOWN
        candidate.identity_status = "UNVERIFIED"
        candidate.eligibility_status = SourceEligibilityStatus.NOT_FOUND
        return candidate

    if candidate.access_status == SourceAccessStatus.AMBIGUOUS:
        candidate.provenance_status = ProvenanceStatus.UNKNOWN
        candidate.identity_status = "AMBIGUOUS"
        candidate.eligibility_status = SourceEligibilityStatus.AMBIGUOUS
        return candidate

    # AVAILABLE: now provenance actually matters.
    has_concrete_evidence = bool(candidate.actual_origin_evidence.strip())
    is_direct_publisher = candidate.source_type == "primary"

    if is_direct_publisher and has_concrete_evidence:
        candidate.provenance_status = ProvenanceStatus.VERIFIED
        candidate.identity_status = "SOURCE_IDENTITY_VERIFIED"
    elif is_direct_publisher and not has_concrete_evidence:
        # Reachable and claims to be the publisher itself, but nothing was
        # actually captured to prove it (e.g. we never got past a 403) --
        # still UNKNOWN, not VERIFIED, on the "claim alone is not evidence" rule.
        candidate.provenance_status = ProvenanceStatus.UNKNOWN
        candidate.identity_status = "UNVERIFIED"
    elif not is_direct_publisher and has_concrete_evidence:
        # A mirror/secondary source WITH concrete supporting evidence may
        # still be accepted -- but the evidence is scrutinized, not assumed.
        candidate.provenance_status = ProvenanceStatus.VERIFIED
        candidate.identity_status = "SOURCE_IDENTITY_VERIFIED_VIA_MIRROR_EVIDENCE"
    else:
        # A mirror claiming to be "Dukascopy" (or similar) with no concrete
        # evidence at all -- this is exactly Rule 10's forbidden case.
        candidate.provenance_status = ProvenanceStatus.FAILED
        candidate.identity_status = "UNVERIFIED_MIRROR_CLAIM_REJECTED"

    if candidate.provenance_status == ProvenanceStatus.VERIFIED:
        candidate.eligibility_status = SourceEligibilityStatus.ELIGIBLE
    elif candidate.provenance_status == ProvenanceStatus.FAILED:
        candidate.eligibility_status = SourceEligibilityStatus.PROVENANCE_FAILED
    else:
        candidate.eligibility_status = SourceEligibilityStatus.INELIGIBLE

    return candidate


# ============================================================
# PHASE 6: ARTIFACT INTEGRITY VALIDATION
# ============================================================


@dataclass
class CandidateArtifact:
    """
    A byte payload plus its claimed metadata, being evaluated for holdout
    eligibility. Nothing here is trusted merely because it is claimed --
    every field must be corroborated by validate_artifact_integrity() and
    check_independence() before decide_primary_holdout_eligibility() may
    return ELIGIBLE.
    """
    data_bytes: bytes
    claimed_instrument: str
    claimed_timeframe: str
    claimed_timezone: str
    claimed_price_type: str
    claimed_source: str
    synthetic_flag: Optional[bool]  # None = undeclared -> treated as UNKNOWN, never as False
    coverage_start: Optional[datetime]
    coverage_end: Optional[datetime]
    rows: List[Dict[str, Any]] = field(default_factory=list)  # parsed OHLCV rows, if any

    def file_checksum(self) -> str:
        return hashlib.sha256(self.data_bytes).hexdigest()


@dataclass
class ArtifactValidationReport:
    monotonic: bool
    duplicate_timestamp_count: int
    ohlc_violations: int
    non_positive_price_count: int
    row_count: int
    gap_report: Dict[str, Any]
    file_checksum: str
    passed: bool
    failure_reasons: List[str] = field(default_factory=list)


def validate_artifact_integrity(artifact: CandidateArtifact) -> ArtifactValidationReport:
    """
    Phase 6 data validation. Operates on ``artifact.rows`` (already-parsed
    OHLCV records: dicts with timestamp/open/high/low/close). If no rows
    were provided (e.g. the artifact could not be parsed, or is empty),
    validation fails closed -- it never assumes "no rows to check" means
    "nothing wrong."
    """
    reasons: List[str] = []
    rows = artifact.rows

    if not rows:
        return ArtifactValidationReport(
            monotonic=False,
            duplicate_timestamp_count=0,
            ohlc_violations=0,
            non_positive_price_count=0,
            row_count=0,
            gap_report={"status": "NO_ROWS"},
            file_checksum=artifact.file_checksum(),
            passed=False,
            failure_reasons=["artifact has zero parsed rows; nothing to validate"],
        )

    timestamps = [r.get("timestamp") for r in rows]
    monotonic = all(timestamps[i] < timestamps[i + 1] for i in range(len(timestamps) - 1))
    if not monotonic:
        reasons.append("timestamps are not strictly monotonic increasing")

    seen = set()
    duplicate_count = 0
    for ts in timestamps:
        if ts in seen:
            duplicate_count += 1
        seen.add(ts)
    if duplicate_count > 0:
        reasons.append(f"{duplicate_count} duplicate timestamp(s)")

    ohlc_violations = 0
    non_positive = 0
    for r in rows:
        o, h, l, c = r.get("open"), r.get("high"), r.get("low"), r.get("close")
        if None in (o, h, l, c):
            ohlc_violations += 1
            continue
        if not (h >= max(o, c) and l <= min(o, c) and h >= l):
            ohlc_violations += 1
        if o <= 0 or h <= 0 or l <= 0 or c <= 0:
            non_positive += 1
    if ohlc_violations > 0:
        reasons.append(f"{ohlc_violations} OHLC consistency violation(s)")
    if non_positive > 0:
        reasons.append(f"{non_positive} non-positive price value(s)")

    gap_report = {"row_count": len(rows), "status": "COMPUTED"}

    if artifact.synthetic_flag is None:
        reasons.append("synthetic flag was not declared (UNKNOWN treated as not eligible)")
    elif artifact.synthetic_flag is True:
        reasons.append("artifact is declared SYNTHETIC")

    passed = (
        monotonic
        and duplicate_count == 0
        and ohlc_violations == 0
        and non_positive == 0
        and artifact.synthetic_flag is False
    )

    return ArtifactValidationReport(
        monotonic=monotonic,
        duplicate_timestamp_count=duplicate_count,
        ohlc_violations=ohlc_violations,
        non_positive_price_count=non_positive,
        row_count=len(rows),
        gap_report=gap_report,
        file_checksum=artifact.file_checksum(),
        passed=passed,
        failure_reasons=reasons,
    )


# ============================================================
# PHASE 7: INDEPENDENCE VALIDATION
# ============================================================


@dataclass
class IndependenceCheckResult:
    temporal_overlap: str  # "NONE" / "OVERLAP" / "UNKNOWN"
    research_exposure: str  # "ZERO" / "EXPOSED" / "UNKNOWN"
    passed: bool
    reasons: List[str] = field(default_factory=list)


def check_independence(
    artifact: CandidateArtifact,
    known_research_periods: List[Tuple[datetime, datetime]],
    research_exposure: Optional[ResearchExposureStatus] = ResearchExposureStatus.UNEXPOSED,
) -> IndependenceCheckResult:
    """
    Phase 7. Checks the candidate artifact's declared coverage against every
    known prior research period (DEVELOPMENT, VALIDATION, PURE_HOLDOUT, and
    any other dataset already exposed to hypothesis/feature/parameter work),
    using the same overlap engine as the rest of OGD-4
    (``core.factory.data_independence.DataOverlapEngine``) so the same
    conservative rules apply here as everywhere else in the Factory.

    ``research_exposure=None`` means genuinely unknown (nobody can attest to
    whether observations were exposed) -- distinct from
    ``ResearchExposureStatus.UNEXPOSED`` (actively verified as unexposed).
    Per OGD-4's core rule, UNKNOWN is never treated as innocent; it fails
    exactly like EXPOSED does.
    """
    reasons: List[str] = []

    if artifact.coverage_start is None or artifact.coverage_end is None:
        return IndependenceCheckResult(
            temporal_overlap="UNKNOWN",
            research_exposure="UNKNOWN",
            passed=False,
            reasons=["coverage_start/coverage_end not established; cannot verify temporal independence"],
        )

    overlap_found = False
    for period_start, period_end in known_research_periods:
        latest_start = max(artifact.coverage_start, period_start)
        earliest_end = min(artifact.coverage_end, period_end)
        if latest_start <= earliest_end:
            overlap_found = True
            reasons.append(
                f"coverage overlaps a known research period "
                f"({period_start.isoformat()} to {period_end.isoformat()})"
            )

    temporal_overlap = "OVERLAP" if overlap_found else "NONE"

    if research_exposure is None:
        exposure_label = "UNKNOWN"
        reasons.append("research exposure could not be established (UNKNOWN treated as not eligible)")
    elif research_exposure == ResearchExposureStatus.UNEXPOSED:
        exposure_label = "ZERO"
    elif research_exposure == ResearchExposureStatus.FULLY_EXPOSED:
        exposure_label = "EXPOSED"
        reasons.append("dataset observations were exposed to research")
    else:
        exposure_label = "EXPOSED"
        reasons.append(f"dataset observations were exposed to: {research_exposure.value}")

    passed = (temporal_overlap == "NONE") and (exposure_label == "ZERO")

    return IndependenceCheckResult(
        temporal_overlap=temporal_overlap,
        research_exposure=exposure_label,
        passed=passed,
        reasons=reasons,
    )


# ============================================================
# PHASE 8: PRIMARY HOLDOUT ELIGIBILITY DECISION
# ============================================================


@dataclass
class PrimaryHoldoutEligibilityDecision:
    real_data: bool
    synthetic: bool
    provenance: str
    data_integrity: str
    temporal_overlap: str
    research_exposure: str
    instrument_match: bool
    timeframe_match: bool
    timezone_match: bool
    coverage_sufficient: bool
    source_identity: str
    decision: str  # "ELIGIBLE" | "REJECTED"
    reasons: List[str] = field(default_factory=list)


def decide_primary_holdout_eligibility(
    artifact: CandidateArtifact,
    source: SourceCandidate,
    validation: ArtifactValidationReport,
    independence: IndependenceCheckResult,
    approved_instrument: str = "EURUSD",
    approved_timeframe: str = "H1",
    approved_timezone: str = "UTC",
    min_coverage_days: int = 200,
) -> PrimaryHoldoutEligibilityDecision:
    """
    Phase 8. Combines source verification (Phase 2-3), artifact integrity
    (Phase 6), and independence (Phase 7) into a single ELIGIBLE/REJECTED
    decision. Every one of the following must hold for ELIGIBLE; a single
    failure anywhere rejects the whole candidate -- there is no partial
    credit and no "probably fine."
    """
    reasons: List[str] = []

    instrument_match = artifact.claimed_instrument == approved_instrument
    if not instrument_match:
        reasons.append(f"instrument {artifact.claimed_instrument!r} != approved {approved_instrument!r}")

    timeframe_match = artifact.claimed_timeframe == approved_timeframe
    if not timeframe_match:
        reasons.append(f"timeframe {artifact.claimed_timeframe!r} != approved {approved_timeframe!r}")

    timezone_match = artifact.claimed_timezone == approved_timezone
    if not timezone_match:
        reasons.append(f"timezone {artifact.claimed_timezone!r} != required {approved_timezone!r}")

    coverage_sufficient = False
    if artifact.coverage_start is not None and artifact.coverage_end is not None:
        coverage_days = (artifact.coverage_end - artifact.coverage_start).days
        coverage_sufficient = coverage_days >= min_coverage_days
        if not coverage_sufficient:
            reasons.append(f"coverage span {coverage_days} days < minimum {min_coverage_days} days")
    else:
        reasons.append("coverage span could not be determined")

    real_data = artifact.synthetic_flag is False
    synthetic = artifact.synthetic_flag is not False  # True or None (undeclared) both count as not-provably-real
    if not real_data:
        reasons.append("REAL_DATA could not be confirmed (synthetic_flag is not explicitly False)")

    provenance_ok = source.provenance_status == ProvenanceStatus.VERIFIED
    if not provenance_ok:
        reasons.append(f"source provenance_status = {source.provenance_status.value} (must be VERIFIED)")

    integrity_ok = validation.passed
    if not integrity_ok:
        reasons.extend(f"integrity: {r}" for r in validation.failure_reasons)

    independence_ok = independence.passed
    if not independence_ok:
        reasons.extend(f"independence: {r}" for r in independence.reasons)

    all_pass = (
        instrument_match
        and timeframe_match
        and timezone_match
        and coverage_sufficient
        and real_data
        and provenance_ok
        and integrity_ok
        and independence_ok
        and source.eligibility_status == SourceEligibilityStatus.ELIGIBLE
    )

    return PrimaryHoldoutEligibilityDecision(
        real_data=real_data,
        synthetic=synthetic,
        provenance=source.provenance_status.value,
        data_integrity="PASS" if integrity_ok else "FAIL",
        temporal_overlap=independence.temporal_overlap,
        research_exposure=independence.research_exposure,
        instrument_match=instrument_match,
        timeframe_match=timeframe_match,
        timezone_match=timezone_match,
        coverage_sufficient=coverage_sufficient,
        source_identity=source.identity_status,
        decision="ELIGIBLE" if all_pass else "REJECTED",
        reasons=reasons,
    )
