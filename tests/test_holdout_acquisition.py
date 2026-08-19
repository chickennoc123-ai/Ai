"""
OGD-4 Data Acquisition Workstream: adversarial tests for
core/factory/holdout_acquisition.py.

Covers the acquisition-spec Phase 14 scenario list. Scenarios that are
inherent to the Evidence Vault's state machine rather than the acquisition
gate (resealing, replacing a sealed artifact, consuming before/twice,
persistence/reload, fresh-process verification, altered bytes/metadata
after seal, substituted bytes against an existing seal) are already covered
by ``tests/test_ogd4_evidence_vault.py`` -- cross-referenced in comments
below rather than duplicated.

Every test here uses synthetic fixture bytes standing in for "a candidate
artifact under evaluation." None of these fixtures are claimed to be real
market data, and nothing in this file calls EvidenceVault.seal_dataset() --
this module's whole purpose is to decide ELIGIBLE/REJECTED *before* sealing
is ever considered.
"""

from datetime import datetime

import pytest

from core.factory.data_independence import ResearchExposureStatus
from core.factory.holdout_acquisition import (
    CandidateArtifact,
    SourceCandidate,
    SourceAccessStatus,
    ProvenanceStatus,
    SourceEligibilityStatus,
    evaluate_source_candidate,
    validate_artifact_integrity,
    check_independence,
    decide_primary_holdout_eligibility,
)


def _valid_rows(n=300, start=datetime(2022, 1, 3)):
    """Deterministic, clean synthetic OHLCV rows -- fixture only, never
    claimed as real market data. Used purely to exercise the integrity
    checker's PASS path so other tests can isolate the one dimension they
    are probing."""
    from datetime import timedelta
    rows = []
    price = 1.1000
    for i in range(n):
        ts = start + timedelta(hours=i)
        o, c = price, price + 0.0001
        h, l = max(o, c) + 0.00005, min(o, c) - 0.00005
        rows.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": c})
        price = c
    return rows


def _dukascopy_primary_source(access_status=SourceAccessStatus.AVAILABLE, evidence="matches published Dukascopy tick checksum for the same period"):
    return SourceCandidate(
        source_id="SRC-DUKASCOPY-01",
        source_name="Dukascopy Bank SA",
        source_url="https://datafeed.dukascopy.com/datafeed/EURUSD/",
        source_type="primary",
        publisher="Dukascopy Bank SA",
        claimed_origin="Dukascopy Bank SA",
        actual_origin_evidence=evidence,
        access_status=access_status,
        network_status="HTTP 200" if access_status == SourceAccessStatus.AVAILABLE else "HTTP 403 (proxy policy denial)",
        license_status="free for personal/research use per Dukascopy terms",
        download_method="direct API",
    )


class TestSourceProvenanceGating:
    """Scenarios 1, 2, 11, 14: fake/claimed-only provenance must never pass."""

    def test_fake_dukascopy_filename_with_no_evidence_is_rejected(self):
        """Scenario 1: a file merely NAMED like a Dukascopy export, with no
        actual_origin_evidence, must not be accepted as VERIFIED provenance."""
        candidate = SourceCandidate(
            source_id="SRC-MIRROR-01",
            source_name="random-github-mirror/dukascopy_eurusd_h1_2022_2026.csv",
            source_url="https://raw.githubusercontent.com/someuser/somerepo/main/dukascopy_eurusd_h1_2022_2026.csv",
            source_type="unverified_mirror",
            publisher="unknown",
            claimed_origin="Dukascopy Bank SA",  # the filename/repo CLAIMS this
            actual_origin_evidence="",  # but nothing actually supports it
            access_status=SourceAccessStatus.AVAILABLE,
            network_status="HTTP 200",
            license_status="unstated",
            download_method="raw file fetch",
        )
        result = evaluate_source_candidate(candidate)
        assert result.provenance_status == ProvenanceStatus.FAILED
        assert result.eligibility_status == SourceEligibilityStatus.PROVENANCE_FAILED

    def test_fake_source_metadata_claiming_primary_publisher_without_evidence(self):
        """Scenario 2: claiming to BE the primary publisher (not just a
        mirror of one) is not self-authenticating either -- a claim without
        concrete evidence stays UNKNOWN/ineligible, never VERIFIED."""
        candidate = SourceCandidate(
            source_id="SRC-CLAIM-01",
            source_name="Dukascopy Bank SA",  # claims to BE Dukascopy itself
            source_url="https://not-actually-dukascopy.example.com",
            source_type="primary",  # asserted, not demonstrated
            publisher="Dukascopy Bank SA",
            claimed_origin="Dukascopy Bank SA",
            actual_origin_evidence="",  # no corroboration at all
            access_status=SourceAccessStatus.AVAILABLE,
            network_status="HTTP 200",
            license_status="unstated",
            download_method="direct fetch",
        )
        result = evaluate_source_candidate(candidate)
        assert result.provenance_status == ProvenanceStatus.UNKNOWN
        assert result.eligibility_status == SourceEligibilityStatus.INELIGIBLE

    def test_mirror_without_provenance_is_rejected_not_provisionally_trusted(self):
        """Scenario 14: an accessible mirror with zero supporting evidence
        must be PROVENANCE_FAILED, not "uncertain but let's proceed."""
        candidate = SourceCandidate(
            source_id="SRC-MIRROR-02",
            source_name="some-forex-data-archive",
            source_url="https://example-mirror.test/eurusd_h1.csv",
            source_type="unverified_mirror",
            publisher="unknown archive maintainer",
            claimed_origin="aggregated from various sources",
            actual_origin_evidence="",
            access_status=SourceAccessStatus.AVAILABLE,
            network_status="HTTP 200",
            license_status="unstated",
            download_method="raw file fetch",
        )
        result = evaluate_source_candidate(candidate)
        assert result.eligibility_status == SourceEligibilityStatus.PROVENANCE_FAILED
        assert result.eligibility_status != SourceEligibilityStatus.ELIGIBLE

    def test_provenance_unknown_source_cannot_reach_eligible_decision(self):
        """Scenario 11: PROVENANCE_STATUS = UNKNOWN must propagate all the
        way to a REJECTED final decision, not just a warning."""
        source = _dukascopy_primary_source(evidence="")  # reachable, but no evidence captured
        source = evaluate_source_candidate(source)
        assert source.provenance_status == ProvenanceStatus.UNKNOWN

        artifact = CandidateArtifact(
            data_bytes=b"irrelevant for this test",
            claimed_instrument="EURUSD",
            claimed_timeframe="H1",
            claimed_timezone="UTC",
            claimed_price_type="OHLC",
            claimed_source="dukascopy",
            synthetic_flag=False,
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2026, 12, 31),
            rows=_valid_rows(),
        )
        validation = validate_artifact_integrity(artifact)
        independence = check_independence(artifact, known_research_periods=[])
        decision = decide_primary_holdout_eligibility(artifact, source, validation, independence)
        assert decision.decision == "REJECTED"
        assert decision.provenance == "UNKNOWN"

    def test_access_failed_source_is_never_eligible_regardless_of_claimed_origin(self):
        """A source that returns ACCESS_FAILED (matches this session's real
        Dukascopy/HistData 403s) is INELIGIBLE even if claimed_origin and
        actual_origin_evidence both look perfect on paper -- there are no
        bytes to seal."""
        source = _dukascopy_primary_source(access_status=SourceAccessStatus.ACCESS_FAILED)
        result = evaluate_source_candidate(source)
        assert result.eligibility_status == SourceEligibilityStatus.ACCESS_FAILED
        assert result.provenance_status != ProvenanceStatus.VERIFIED


class TestArtifactIntegrityGating:
    """Scenarios 6, 7: synthetic and incomplete data must fail closed."""

    def test_synthetic_flagged_data_is_rejected(self):
        """Scenario 6."""
        artifact = CandidateArtifact(
            data_bytes=b"fixture",
            claimed_instrument="EURUSD",
            claimed_timeframe="H1",
            claimed_timezone="UTC",
            claimed_price_type="OHLC",
            claimed_source="dukascopy",
            synthetic_flag=True,  # explicitly synthetic
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 6, 1),
            rows=_valid_rows(),
        )
        report = validate_artifact_integrity(artifact)
        assert report.passed is False
        assert any("SYNTHETIC" in r for r in report.failure_reasons)

    def test_undeclared_synthetic_flag_defaults_to_not_eligible(self):
        """synthetic_flag=None (undeclared) must be treated the same as
        UNKNOWN elsewhere in OGD-4 -- never silently assumed real."""
        artifact = CandidateArtifact(
            data_bytes=b"fixture",
            claimed_instrument="EURUSD",
            claimed_timeframe="H1",
            claimed_timezone="UTC",
            claimed_price_type="OHLC",
            claimed_source="dukascopy",
            synthetic_flag=None,
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 6, 1),
            rows=_valid_rows(),
        )
        report = validate_artifact_integrity(artifact)
        assert report.passed is False

    def test_incomplete_data_with_zero_rows_is_rejected(self):
        """Scenario 7."""
        artifact = CandidateArtifact(
            data_bytes=b"",
            claimed_instrument="EURUSD",
            claimed_timeframe="H1",
            claimed_timezone="UTC",
            claimed_price_type="OHLC",
            claimed_source="dukascopy",
            synthetic_flag=False,
            coverage_start=None,
            coverage_end=None,
            rows=[],
        )
        report = validate_artifact_integrity(artifact)
        assert report.passed is False
        assert report.row_count == 0

    def test_duplicate_timestamps_are_detected(self):
        rows = _valid_rows(n=10)
        rows.append(dict(rows[0]))  # duplicate of the first row's timestamp
        artifact = CandidateArtifact(
            data_bytes=b"fixture",
            claimed_instrument="EURUSD",
            claimed_timeframe="H1",
            claimed_timezone="UTC",
            claimed_price_type="OHLC",
            claimed_source="dukascopy",
            synthetic_flag=False,
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 1, 2),
            rows=rows,
        )
        report = validate_artifact_integrity(artifact)
        assert report.duplicate_timestamp_count >= 1
        assert report.passed is False

    def test_ohlc_inconsistency_is_detected(self):
        """high < low is physically impossible and must be caught."""
        rows = [{"timestamp": datetime(2022, 1, 1), "open": 1.10, "high": 1.05, "low": 1.20, "close": 1.10}]
        artifact = CandidateArtifact(
            data_bytes=b"fixture",
            claimed_instrument="EURUSD",
            claimed_timeframe="H1",
            claimed_timezone="UTC",
            claimed_price_type="OHLC",
            claimed_source="dukascopy",
            synthetic_flag=False,
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 1, 1),
            rows=rows,
        )
        report = validate_artifact_integrity(artifact)
        assert report.ohlc_violations >= 1
        assert report.passed is False

    def test_non_positive_price_is_detected(self):
        rows = [{"timestamp": datetime(2022, 1, 1), "open": 0.0, "high": 1.0, "low": 0.0, "close": 0.5}]
        artifact = CandidateArtifact(
            data_bytes=b"fixture",
            claimed_instrument="EURUSD",
            claimed_timeframe="H1",
            claimed_timezone="UTC",
            claimed_price_type="OHLC",
            claimed_source="dukascopy",
            synthetic_flag=False,
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 1, 1),
            rows=rows,
        )
        report = validate_artifact_integrity(artifact)
        assert report.non_positive_price_count >= 1
        assert report.passed is False


class TestInstrumentTimeframeTimezoneGating:
    """Scenarios 8, 9, 10: wrong timeframe, wrong symbol, wrong timezone."""

    def _eligible_source(self):
        return evaluate_source_candidate(_dukascopy_primary_source())

    def test_wrong_timeframe_is_rejected(self):
        """Scenario 8: e.g. daily bars presented as the H1 holdout."""
        artifact = CandidateArtifact(
            data_bytes=b"fixture", claimed_instrument="EURUSD", claimed_timeframe="D1",
            claimed_timezone="UTC", claimed_price_type="OHLC", claimed_source="dukascopy",
            synthetic_flag=False, coverage_start=datetime(2022, 1, 1), coverage_end=datetime(2022, 12, 31),
            rows=_valid_rows(),
        )
        validation = validate_artifact_integrity(artifact)
        independence = check_independence(artifact, known_research_periods=[])
        decision = decide_primary_holdout_eligibility(artifact, self._eligible_source(), validation, independence)
        assert decision.timeframe_match is False
        assert decision.decision == "REJECTED"

    def test_wrong_symbol_is_rejected(self):
        """Scenario 9: e.g. GBPUSD presented as the approved EURUSD holdout."""
        artifact = CandidateArtifact(
            data_bytes=b"fixture", claimed_instrument="GBPUSD", claimed_timeframe="H1",
            claimed_timezone="UTC", claimed_price_type="OHLC", claimed_source="dukascopy",
            synthetic_flag=False, coverage_start=datetime(2022, 1, 1), coverage_end=datetime(2022, 12, 31),
            rows=_valid_rows(),
        )
        validation = validate_artifact_integrity(artifact)
        independence = check_independence(artifact, known_research_periods=[])
        decision = decide_primary_holdout_eligibility(artifact, self._eligible_source(), validation, independence)
        assert decision.instrument_match is False
        assert decision.decision == "REJECTED"

    def test_wrong_timezone_is_rejected(self):
        """Scenario 10: e.g. America/New_York timestamps presented without
        conversion to the required UTC."""
        artifact = CandidateArtifact(
            data_bytes=b"fixture", claimed_instrument="EURUSD", claimed_timeframe="H1",
            claimed_timezone="America/New_York", claimed_price_type="OHLC", claimed_source="dukascopy",
            synthetic_flag=False, coverage_start=datetime(2022, 1, 1), coverage_end=datetime(2022, 12, 31),
            rows=_valid_rows(),
        )
        validation = validate_artifact_integrity(artifact)
        independence = check_independence(artifact, known_research_periods=[])
        decision = decide_primary_holdout_eligibility(artifact, self._eligible_source(), validation, independence)
        assert decision.timezone_match is False
        assert decision.decision == "REJECTED"


class TestIndependenceGating:
    """Scenarios 12, 13: unknown research exposure, temporal overlap."""

    def test_research_exposure_unknown_is_rejected(self):
        """Scenario 12: nobody can attest the observations were never seen
        during research -- UNKNOWN must fail exactly like EXPOSED."""
        artifact = CandidateArtifact(
            data_bytes=b"fixture", claimed_instrument="EURUSD", claimed_timeframe="H1",
            claimed_timezone="UTC", claimed_price_type="OHLC", claimed_source="dukascopy",
            synthetic_flag=False, coverage_start=datetime(2022, 1, 1), coverage_end=datetime(2022, 12, 31),
            rows=_valid_rows(),
        )
        result = check_independence(artifact, known_research_periods=[], research_exposure=None)
        assert result.research_exposure == "UNKNOWN"
        assert result.passed is False

    def test_temporal_overlap_with_development_period_is_rejected(self):
        """Scenario 13: a candidate claiming 2022-2026 coverage that
        actually overlaps the real DEVELOPMENT period
        (2012-11-16 to 2022-03-05, per data/csv/PROVENANCE_MANIFEST.json)
        must be caught, not waved through because the label says 2022+."""
        artifact = CandidateArtifact(
            data_bytes=b"fixture", claimed_instrument="EURUSD", claimed_timeframe="H1",
            claimed_timezone="UTC", claimed_price_type="OHLC", claimed_source="dukascopy",
            synthetic_flag=False,
            coverage_start=datetime(2022, 1, 1),  # claimed to start in 2022...
            coverage_end=datetime(2022, 12, 31),
            rows=_valid_rows(),
        )
        development_period = (datetime(2012, 11, 16), datetime(2022, 3, 5))  # actual DEVELOPMENT coverage
        result = check_independence(artifact, known_research_periods=[development_period])
        assert result.temporal_overlap == "OVERLAP"
        assert result.passed is False

    def test_pure_holdout_period_overlap_is_rejected(self):
        artifact = CandidateArtifact(
            data_bytes=b"fixture", claimed_instrument="EURUSD", claimed_timeframe="H1",
            claimed_timezone="UTC", claimed_price_type="OHLC", claimed_source="dukascopy",
            synthetic_flag=False,
            coverage_start=datetime(2021, 6, 1),
            coverage_end=datetime(2022, 6, 1),
            rows=_valid_rows(),
        )
        pure_holdout_period = (datetime(2021, 1, 1), datetime(2021, 12, 31))
        result = check_independence(artifact, known_research_periods=[pure_holdout_period])
        assert result.temporal_overlap == "OVERLAP"
        assert result.passed is False

    def test_genuinely_unseen_period_passes_independence_check(self):
        """Sanity check: the acquisition gate is not simply "always reject"
        -- a genuinely non-overlapping period with confirmed zero exposure
        must pass."""
        artifact = CandidateArtifact(
            data_bytes=b"fixture", claimed_instrument="EURUSD", claimed_timeframe="H1",
            claimed_timezone="UTC", claimed_price_type="OHLC", claimed_source="dukascopy",
            synthetic_flag=False,
            coverage_start=datetime(2022, 4, 1),
            coverage_end=datetime(2026, 12, 31),
            rows=_valid_rows(),
        )
        development_period = (datetime(2012, 11, 16), datetime(2022, 3, 5))
        pure_holdout_period = (datetime(2021, 1, 1), datetime(2021, 12, 31))
        result = check_independence(
            artifact,
            known_research_periods=[development_period, pure_holdout_period],
            research_exposure=ResearchExposureStatus.UNEXPOSED,
        )
        assert result.temporal_overlap == "NONE"
        assert result.research_exposure == "ZERO"
        assert result.passed is True


class TestFullDecisionIntegration:
    """End-to-end: a fully clean, well-sourced, non-overlapping artifact
    reaches ELIGIBLE -- proving the gate isn't just a rejection machine --
    while any single defect (source, integrity, or independence) is enough
    to flip a decision back to REJECTED."""

    def _clean_artifact(self):
        return CandidateArtifact(
            data_bytes=b"synthetic fixture bytes standing in for a real download -- NOT claimed as real market data",
            claimed_instrument="EURUSD",
            claimed_timeframe="H1",
            claimed_timezone="UTC",
            claimed_price_type="OHLC",
            claimed_source="dukascopy",
            synthetic_flag=False,
            coverage_start=datetime(2022, 4, 1),
            coverage_end=datetime(2026, 12, 31),
            rows=_valid_rows(),
        )

    def test_fully_clean_candidate_reaches_eligible(self):
        source = evaluate_source_candidate(_dukascopy_primary_source())
        artifact = self._clean_artifact()
        validation = validate_artifact_integrity(artifact)
        independence = check_independence(
            artifact,
            known_research_periods=[(datetime(2012, 11, 16), datetime(2022, 3, 5)), (datetime(2021, 1, 1), datetime(2021, 12, 31))],
            research_exposure=ResearchExposureStatus.UNEXPOSED,
        )
        decision = decide_primary_holdout_eligibility(artifact, source, validation, independence)
        assert decision.decision == "ELIGIBLE"

    def test_one_bad_dimension_is_enough_to_reject_an_otherwise_clean_candidate(self):
        """Everything is clean except provenance -- still REJECTED overall.
        No partial credit."""
        bad_source = evaluate_source_candidate(_dukascopy_primary_source(evidence=""))
        artifact = self._clean_artifact()
        validation = validate_artifact_integrity(artifact)
        independence = check_independence(
            artifact,
            known_research_periods=[(datetime(2012, 11, 16), datetime(2022, 3, 5))],
            research_exposure=ResearchExposureStatus.UNEXPOSED,
        )
        decision = decide_primary_holdout_eligibility(artifact, bad_source, validation, independence)
        assert decision.decision == "REJECTED"
        assert decision.data_integrity == "PASS"  # confirms integrity itself was fine
        assert decision.temporal_overlap == "NONE"  # confirms independence itself was fine


class TestFileChecksumDeterminism:
    """Scenario 3 (acquisition-gate side): identical bytes always produce
    the identical checksum; different bytes never collide in practice.
    (Vault-side substitution-after-seal is covered by
    test_ogd4_evidence_vault.py::test_verify_seal_rejects_substituted_dataset_bytes.)"""

    def test_identical_bytes_produce_identical_checksum(self):
        a = CandidateArtifact(
            data_bytes=b"identical content", claimed_instrument="EURUSD", claimed_timeframe="H1",
            claimed_timezone="UTC", claimed_price_type="OHLC", claimed_source="dukascopy",
            synthetic_flag=False, coverage_start=None, coverage_end=None,
        )
        b = CandidateArtifact(
            data_bytes=b"identical content", claimed_instrument="EURUSD", claimed_timeframe="H1",
            claimed_timezone="UTC", claimed_price_type="OHLC", claimed_source="dukascopy",
            synthetic_flag=False, coverage_start=None, coverage_end=None,
        )
        assert a.file_checksum() == b.file_checksum()

    def test_different_bytes_produce_different_checksum(self):
        a = CandidateArtifact(
            data_bytes=b"original bytes", claimed_instrument="EURUSD", claimed_timeframe="H1",
            claimed_timezone="UTC", claimed_price_type="OHLC", claimed_source="dukascopy",
            synthetic_flag=False, coverage_start=None, coverage_end=None,
        )
        b = CandidateArtifact(
            data_bytes=b"substituted bytes claiming the same identity", claimed_instrument="EURUSD",
            claimed_timeframe="H1", claimed_timezone="UTC", claimed_price_type="OHLC",
            claimed_source="dukascopy", synthetic_flag=False, coverage_start=None, coverage_end=None,
        )
        assert a.file_checksum() != b.file_checksum()


# ============================================================
# Cross-reference: scenarios covered elsewhere, not duplicated here
# ============================================================
#
# Scenario 4  (altered bytes after checksum)      -> test_ogd4_evidence_vault.py::TestSealIntegrity::test_data_mutation_changes_seal
# Scenario 5  (altered metadata after seal)        -> test_ogd4_evidence_vault.py::TestResearchExposureDetection::test_metadata_field_change_after_seal_breaks_verification
# Scenario 15 (resealing)                          -> test_ogd4_evidence_vault.py::TestOnceConsumed::test_seal_dataset_cannot_be_sealed_twice
# Scenario 16 (replacing a sealed artifact)         -> same as 15: seal_dataset() on an already-SEALED dataset_id is rejected outright
# Scenario 17 (consuming before authorization)      -> test_ogd4_evidence_vault.py::TestOnceConsumed::test_consumption_requires_prior_authorization
# Scenario 18 (consuming twice)                     -> test_ogd4_evidence_vault.py::TestOnceConsumed::test_second_consumption_is_forbidden
# Scenario 19 (persistence/reload)                  -> test_ogd4_evidence_vault.py::TestAuditTrail::test_audit_trail_persists_across_fresh_vault_instance
# Scenario 20 (fresh-process verification)          -> test_ogd4_evidence_vault.py::TestOGD4Principles::test_seal_survives_a_genuinely_fresh_process
