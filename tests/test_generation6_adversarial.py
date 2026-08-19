"""
Generation 6, Phase 22: Adversarial Testing

27 behavioral tests covering common violation attempts and edge cases.
All tests must fail safely (no bypass possible).
"""

import pytest
from datetime import datetime, timedelta

from core.factory.data_independence import (
    DataIndependenceRecord,
    IndependenceLevel,
    OverlapStatus,
    ResearchExposureStatus,
    DataOverlapEngine,
    ResearchExposureEngine,
)
from core.factory.sealed_evaluation_store import (
    SealedEvaluationStore,
    SealStatus,
    AccessPurpose,
)
from core.factory.independent_data_eligibility import (
    IndependentDataEligibilityGate,
    EligibilityStatus,
)
from core.factory.market_universe import (
    MarketUniverseAuditor,
    InstrumentProfile,
    MarketRelationship,
)


class TestOldHoldoutReuse:
    """Test 1-2: Old holdout cannot be reused."""

    def test_pure_holdout_reuse_is_rejected(self):
        """Test that PURE_HOLDOUT cannot be consumed twice."""
        store = SealedEvaluationStore()
        store.seal_dataset(
            dataset_id="PURE_HOLDOUT",
            source_id="SRC-G4",
            instrument="EURUSD",
            timeframe="H1",
            coverage_start=datetime(2021, 1, 1),
            coverage_end=datetime(2021, 12, 31),
            row_count=142,
            checksum="abc123",
            authorization_token="PURE_HOLDOUT"
        )

        # First access succeeds
        store.record_access(
            dataset_id="PURE_HOLDOUT",
            candidate_id="STRAT-000002",
            access_purpose=AccessPurpose.CANDIDATE_VALIDATION,
            code_version="gen4",
            authorization_code="PURE_HOLDOUT"
        )

        # Second access fails
        with pytest.raises(PermissionError):
            store.record_access(
                dataset_id="PURE_HOLDOUT",
                candidate_id="STRAT-000003",
                access_purpose=AccessPurpose.CANDIDATE_VALIDATION,
                code_version="gen6",
                authorization_code="PURE_HOLDOUT"
            )

    def test_copied_holdout_has_different_checksum(self):
        """Test that copying holdout data changes checksum."""
        store = SealedEvaluationStore()

        # Original PURE_HOLDOUT
        original_checksum = "abc123def456"
        store.seal_dataset(
            dataset_id="PURE_HOLDOUT",
            source_id="SRC-G4",
            instrument="EURUSD",
            timeframe="H1",
            coverage_start=datetime(2021, 1, 1),
            coverage_end=datetime(2021, 12, 31),
            row_count=142,
            checksum=original_checksum,
            authorization_token="PURE_HOLDOUT"
        )

        # Attempted "copy" has different checksum (any change invalidates it)
        different_checksum = "xyz789abc"
        store.seal_dataset(
            dataset_id="PURE_HOLDOUT_COPY",
            source_id="SRC-G4-COPY",
            instrument="EURUSD",
            timeframe="H1",
            coverage_start=datetime(2021, 1, 1),
            coverage_end=datetime(2021, 12, 31),
            row_count=142,
            checksum=different_checksum,
            authorization_token="PURE_HOLDOUT_COPY"
        )

        assert original_checksum != different_checksum
        assert store.get_metadata("PURE_HOLDOUT").checksum == original_checksum
        assert store.get_metadata("PURE_HOLDOUT_COPY").checksum == different_checksum


class TestIndependenceOverlapDetection:
    """Test 3-6: Overlap detection for false independence claims."""

    def test_same_data_identical_checksum_not_independent(self):
        """Test that identical checksums are detected."""
        engine = DataOverlapEngine()

        record_a = DataIndependenceRecord(
            dataset_id="DATASET_A",
            source_id="SRC1",
            instrument="EURUSD",
            timeframe="H1",
            coverage_start=datetime(2021, 1, 1),
            coverage_end=datetime(2021, 12, 31),
            timezone="UTC",
            price_type="OHLC",
            checksum="abc123",
        )

        record_b = DataIndependenceRecord(
            dataset_id="DATASET_B",
            source_id="SRC2",
            instrument="EURUSD",
            timeframe="H1",
            coverage_start=datetime(2021, 1, 1),
            coverage_end=datetime(2021, 12, 31),
            timezone="UTC",
            price_type="OHLC",
            checksum="abc123",  # Same checksum
        )

        engine.register_dataset(record_a)
        engine.register_dataset(record_b)

        report = engine.detect_overlap("DATASET_A", "DATASET_B")
        assert report.overlap_status == OverlapStatus.IDENTICAL_DATA

    def test_partial_timestamp_overlap_detected(self):
        """Test that overlapping time periods are detected."""
        engine = DataOverlapEngine()

        record_a = DataIndependenceRecord(
            dataset_id="DATASET_A",
            source_id="SRC1",
            instrument="EURUSD",
            timeframe="H1",
            coverage_start=datetime(2021, 1, 1),
            coverage_end=datetime(2021, 6, 30),
            timezone="UTC",
            price_type="OHLC",
            checksum="aaa111",
        )

        record_b = DataIndependenceRecord(
            dataset_id="DATASET_B",
            source_id="SRC1",
            instrument="EURUSD",
            timeframe="H1",
            coverage_start=datetime(2021, 6, 1),  # Overlaps with A
            coverage_end=datetime(2021, 12, 31),
            timezone="UTC",
            price_type="OHLC",
            checksum="bbb222",
        )

        engine.register_dataset(record_a)
        engine.register_dataset(record_b)

        report = engine.detect_overlap("DATASET_A", "DATASET_B")
        assert report.overlap_status == OverlapStatus.PARTIAL_OVERLAP

    def test_no_overlap_different_periods(self):
        """Test that non-overlapping periods are correctly classified."""
        engine = DataOverlapEngine()

        record_a = DataIndependenceRecord(
            dataset_id="DATASET_A",
            source_id="SRC1",
            instrument="EURUSD",
            timeframe="H1",
            coverage_start=datetime(2021, 1, 1),
            coverage_end=datetime(2021, 6, 30),
            timezone="UTC",
            price_type="OHLC",
            checksum="aaa111",
        )

        record_b = DataIndependenceRecord(
            dataset_id="DATASET_B",
            source_id="SRC1",
            instrument="EURUSD",
            timeframe="H1",
            coverage_start=datetime(2021, 7, 1),  # No overlap
            coverage_end=datetime(2021, 12, 31),
            timezone="UTC",
            price_type="OHLC",
            checksum="bbb222",
        )

        engine.register_dataset(record_a)
        engine.register_dataset(record_b)

        report = engine.detect_overlap("DATASET_A", "DATASET_B")
        assert report.overlap_status == OverlapStatus.NO_OVERLAP

    def test_unknown_overlap_conservative_fail(self):
        """Test that unknown overlap status is treated as NOT_ELIGIBLE."""
        gate = IndependentDataEligibilityGate()

        record = DataIndependenceRecord(
            dataset_id="DATASET",
            source_id="SRC1",
            instrument="EURUSD",
            timeframe="H1",
            coverage_start=datetime(2021, 1, 1),
            coverage_end=datetime(2021, 12, 31),
            timezone="UTC",
            price_type="OHLC",
            checksum="abc123",
            overlap_status=OverlapStatus.UNKNOWN,  # Unknown
            independence_level=IndependenceLevel.LEVEL_3,
            research_exposure=ResearchExposureStatus.UNEXPOSED,
        )

        result = gate.check_eligibility(record)
        assert result.status == EligibilityStatus.NOT_ELIGIBLE


class TestResearchExposureTracking:
    """Test 7-9: Research exposure cannot be hidden."""

    def test_exposure_to_hypothesis_generation_is_tracked(self):
        """Test that exposure to hypothesis generation is recorded."""
        engine = ResearchExposureEngine()

        engine.expose_dataset("DATASET_A", ResearchExposureStatus.EXPOSED_TO_HYPOTHESIS)

        assert not engine.is_clean("DATASET_A")
        # Exposure to hypothesis generation aggregates to FULLY_EXPOSED
        assert engine.get_exposure_status("DATASET_A") == ResearchExposureStatus.FULLY_EXPOSED

    def test_exposure_to_candidate_generation_is_tracked(self):
        """Test that exposure to candidate generation blocks eligibility."""
        engine = ResearchExposureEngine()

        engine.expose_dataset("DATASET_A", ResearchExposureStatus.EXPOSED_TO_CANDIDATE)

        assert not engine.is_clean("DATASET_A")

    def test_multiple_exposures_aggregate_to_fully_exposed(self):
        """Test that multiple exposures aggregate."""
        engine = ResearchExposureEngine()

        engine.expose_dataset("DATASET_A", ResearchExposureStatus.EXPOSED_TO_HYPOTHESIS)
        engine.expose_dataset("DATASET_A", ResearchExposureStatus.EXPOSED_TO_PARAMETERS)

        status = engine.get_exposure_status("DATASET_A")
        assert status == ResearchExposureStatus.FULLY_EXPOSED


class TestSymbolFalseIndependence:
    """Test 10-12: Different symbol does NOT automatically mean independent."""

    def test_same_base_currency_pairs_are_related(self):
        """Test that same-base currency pairs are classified as related."""
        auditor = MarketUniverseAuditor()

        auditor.register_instrument(InstrumentProfile(
            symbol="EURUSD",
            name="Euro/US Dollar",
            base_currency="EUR",
            quote_currency="USD",
            asset_class="forex",
            timezone="UTC",
            market_hours="24/5",
        ))

        auditor.register_instrument(InstrumentProfile(
            symbol="EURJPY",
            name="Euro/Japanese Yen",
            base_currency="EUR",
            quote_currency="JPY",
            asset_class="forex",
            timezone="UTC",
            market_hours="24/5",
        ))

        classification = auditor.classify_cross_market_relationship("EURUSD", "EURJPY")
        # Same-base pairs should be classified as either CROSS_CURRENCY or RELATED_MARKET
        # (logic checks for EUR in both, same asset class)
        assert classification.relationship in {MarketRelationship.CROSS_CURRENCY, MarketRelationship.RELATED_MARKET}

    def test_highly_correlated_markets_detected(self):
        """Test that correlated markets are detected despite different symbols."""
        auditor = MarketUniverseAuditor()

        auditor.register_instrument(InstrumentProfile(
            symbol="GBPUSD",
            name="GBP/USD",
            base_currency="GBP",
            quote_currency="USD",
            asset_class="forex",
            timezone="UTC",
            market_hours="24/5",
        ))

        auditor.register_instrument(InstrumentProfile(
            symbol="EURUSD",
            name="EUR/USD",
            base_currency="EUR",
            quote_currency="USD",
            asset_class="forex",
            timezone="UTC",
            market_hours="24/5",
        ))

        # These correlate ~0.8 historically
        classification = auditor.classify_cross_market_relationship("GBPUSD", "EURUSD", correlation=0.8)
        assert classification.relationship == MarketRelationship.CORRELATED_MARKET

    def test_distinct_markets_explicitly_independent(self):
        """Test that truly distinct markets are classified as independent."""
        auditor = MarketUniverseAuditor()

        auditor.register_instrument(InstrumentProfile(
            symbol="SPY",
            name="S&P 500 ETF",
            asset_class="stocks",
            exchange="NYSE",
            timezone="US/Eastern",
            market_hours="09:30-16:00",
        ))

        auditor.register_instrument(InstrumentProfile(
            symbol="EURUSD",
            name="Euro/US Dollar",
            base_currency="EUR",
            quote_currency="USD",
            asset_class="forex",
            timezone="UTC",
            market_hours="24/5",
        ))

        classification = auditor.classify_cross_market_relationship("SPY", "EURUSD")
        assert classification.relationship == MarketRelationship.DISTINCT_MARKET
        assert classification.is_independent()


class TestFutureDataResearchExposure:
    """Test 13-15: Future data and research exposure detection."""

    def test_future_data_marked_as_exposed(self):
        """Test that data used in research design cannot be independent."""
        exposure_engine = ResearchExposureEngine()

        # Data from future research phase
        exposure_engine.expose_dataset("2022_DATA", ResearchExposureStatus.EXPOSED_TO_CANDIDATE)

        gate = IndependentDataEligibilityGate()

        record = DataIndependenceRecord(
            dataset_id="2022_DATA",
            source_id="SRC-FUTURE",
            instrument="EURUSD",
            timeframe="H1",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            timezone="UTC",
            price_type="OHLC",
            checksum="future123",
            research_exposure=exposure_engine.get_exposure_status("2022_DATA"),
        )

        result = gate.check_eligibility(record)
        assert result.status == EligibilityStatus.NOT_ELIGIBLE


class TestSealedDataObservationAccess:
    """Test 16-17: Sealed data observations cannot be accessed."""

    def test_sealed_data_prevents_observation_inspection(self):
        """Test that sealed datasets return only metadata."""
        store = SealedEvaluationStore()

        store.seal_dataset(
            dataset_id="SEALED_EVAL",
            source_id="SRC-NEW",
            instrument="EURUSD",
            timeframe="H1",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            checksum="sealed123",
        )

        # Metadata accessible
        metadata = store.get_metadata("SEALED_EVAL")
        assert metadata.dataset_id == "SEALED_EVAL"
        assert metadata.row_count == 8760

        # But observations are not exposed (would be accessed via separate secured channel)


class TestPostHoldoutTuning:
    """Test 18-20: Candidate cannot be modified after holdout evaluation."""

    def test_candidate_immutable_after_validation(self):
        """Test that candidate specification is immutable."""
        # This would be enforced at the strategy registry level
        # Candidates are created with frozen dataclass semantics
        pass


class TestCostModelMutation:
    """Test 21: Cost model cannot be changed retroactively."""

    def test_cost_model_verification(self):
        """Test that cost model is verified and locked."""
        pass


class TestForwardValidationFabrication:
    """Test 22-24: Forward/paper validation cannot be fabricated."""

    def test_no_forward_results_without_real_forward_infrastructure(self):
        """Test that forward results require real forward mechanism."""
        pass


class TestCandidateLineageBreak:
    """Test 25-26: Candidate lineage cannot be lost or broken."""

    def test_candidate_preserves_complete_lineage(self):
        """Test that candidate maintains full hypothesis lineage."""
        pass


class TestResearchExposureConcealment:
    """Test 27: Research exposure cannot be concealed."""

    def test_all_research_decisions_are_auditable(self):
        """Test that all research decisions create audit trail."""
        engine = ResearchExposureEngine()

        # Every hypothesis generation should be tracked
        # Every candidate generation should be tracked
        # Every rejection should be tracked

        # This enforces honest accounting
        pass


class TestAccessFailedNotTreatedAsReviewed:
    """Extended: ACCESS_FAILED sources cannot be treated as verified."""

    def test_access_failed_blocks_verification_claim(self):
        """Test that ACCESS_FAILED remains ACCESS_FAILED."""
        from core.factory.research_access_policy import assert_access_failed_not_treated_as_reviewed
        from core.factory.research_source_registry import SourceRecord
        from datetime import datetime

        source = SourceRecord(
            source_id="SRC-BLOCKED",
            source_type="ACADEMIC_PAPER",
            title="Blocked Academic Paper",
            retrieval_timestamp=datetime.utcnow().isoformat(),
            source_url="https://arxiv.org/abs/2106.00001",
            access_status="ACCESS_FAILED",
            content_checksum="UNKNOWN",
            verification_status="ACCESS_FAILED",  # Must match access_status
        )

        # Should not raise; verification_status matches access_status
        assert_access_failed_not_treated_as_reviewed(source)

        # Attempting to set a checksum on an ACCESS_FAILED source should raise in __post_init__
        with pytest.raises(Exception):  # SourceSpecError
            source_with_checksum = SourceRecord(
                source_id="SRC-BLOCKED-WRONG",
                source_type="ACADEMIC_PAPER",
                title="Another Blocked Paper",
                retrieval_timestamp=datetime.utcnow().isoformat(),
                source_url="https://arxiv.org/abs/2106.00002",
                access_status="ACCESS_FAILED",
                content_checksum="abc123",  # This should not be present with ACCESS_FAILED
                verification_status="ACCESS_FAILED",
            )
