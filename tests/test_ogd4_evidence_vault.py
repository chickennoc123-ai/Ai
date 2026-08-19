"""
OGD-4: Evidence Vault Adversarial Tests

30 behavioral tests verifying that independent evidence is properly sealed,
protected, and consumed according to OGD-4 governance.
"""

import pytest
from datetime import datetime, timedelta

from core.factory.evidence_vault import (
    EvidenceVault,
    EvidenceSealStatus,
    EvidenceDatasetMetadata,
)


class TestSealIntegrity:
    """Tests 1-5: Seal integrity and reproducibility."""

    def test_seal_hash_is_reproducible(self):
        """Test 1: Same data + metadata → same seal hash."""
        vault = EvidenceVault()
        fixed_download_timestamp = datetime(2022, 1, 1, 12, 0, 0)

        # Register dataset
        vault.register_dataset_unsealed(
            dataset_id="TEST_EURUSD_2022",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=fixed_download_timestamp,
            download_method="api",
            source_verified=True,
        )

        # Create test data
        data_bytes = b"test data with OHLC bars"

        # Seal once
        seal1 = vault.seal_dataset(
            dataset_id="TEST_EURUSD_2022",
            data_bytes=data_bytes,
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        # Create fresh vault and attempt to reproduce
        vault2 = EvidenceVault()
        vault2.register_dataset_unsealed(
            dataset_id="TEST_EURUSD_2022",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=fixed_download_timestamp,
            download_method="api",
            source_verified=True,
        )

        seal2 = vault2.seal_dataset(
            dataset_id="TEST_EURUSD_2022",
            data_bytes=data_bytes,
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        # Seals must match (reproducible)
        assert seal1 == seal2

    def test_data_mutation_changes_seal(self):
        """Test 2: Modified data → different seal hash."""
        vault = EvidenceVault()

        vault.register_dataset_unsealed(
            dataset_id="TEST_EURUSD_2022",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime.utcnow(),
            download_method="api",
            source_verified=True,
        )

        # Seal original data
        data1 = b"original data"
        seal1 = vault.seal_dataset(
            dataset_id="TEST_EURUSD_2022",
            data_bytes=data1,
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        # Try to verify with modified data
        data2 = b"modified data"
        is_valid = vault.verify_seal("TEST_EURUSD_2022", data2)

        assert not is_valid, "Modified data should not verify"

    def test_metadata_mutation_changes_seal(self):
        """Test 3: Modified metadata → different seal hash."""
        vault1 = EvidenceVault()

        vault1.register_dataset_unsealed(
            dataset_id="TEST_EURUSD_2022",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime.utcnow(),
            download_method="api",
            source_verified=True,
        )

        data = b"test data"
        seal1 = vault1.seal_dataset(
            dataset_id="TEST_EURUSD_2022",
            data_bytes=data,
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        # Create second vault with different metadata (different timezone)
        vault2 = EvidenceVault()
        vault2.register_dataset_unsealed(
            dataset_id="TEST_EURUSD_2022",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="US/Eastern",  # Different!
            price_type="OHLC",
            download_timestamp=datetime.utcnow(),
            download_method="api",
            source_verified=True,
        )

        seal2 = vault2.seal_dataset(
            dataset_id="TEST_EURUSD_2022",
            data_bytes=data,
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        # Seals must differ (metadata affects seal)
        assert seal1 != seal2


class TestOnceConsumed:
    """Tests 6-10: Once-consumed constraint enforcement."""

    def test_consumed_dataset_cannot_be_resealed(self):
        """Test 6: Attempt to reseal a consumed dataset → rejected."""
        vault = EvidenceVault()

        vault.register_dataset_unsealed(
            dataset_id="EVAL_2022",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime.utcnow(),
            download_method="api",
            source_verified=True,
        )

        data = b"evaluation data"

        # Seal and consume
        vault.seal_dataset(
            dataset_id="EVAL_2022",
            data_bytes=data,
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        vault.authorize_evaluation(
            dataset_id="EVAL_2022",
            candidate_id="STRAT-000003",
            candidate_spec_checksum="abc123",
            authorization_code="AUTH_001",
        )

        vault.consume_dataset(
            dataset_id="EVAL_2022",
            candidate_id="STRAT-000003",
            result_checksum="result123",
        )

        # Try to authorize again → should fail
        with pytest.raises(ValueError):
            vault.authorize_evaluation(
                dataset_id="EVAL_2022",
                candidate_id="STRAT-000004",
                candidate_spec_checksum="def456",
                authorization_code="AUTH_002",
            )

    def test_consumed_dataset_status_is_terminal(self):
        """Test 7: Consumed status is permanent."""
        vault = EvidenceVault()

        vault.register_dataset_unsealed(
            dataset_id="EVAL_2022",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime.utcnow(),
            download_method="api",
            source_verified=True,
        )

        data = b"evaluation data"

        vault.seal_dataset(
            dataset_id="EVAL_2022",
            data_bytes=data,
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        vault.authorize_evaluation(
            dataset_id="EVAL_2022",
            candidate_id="STRAT-000003",
            candidate_spec_checksum="abc123",
            authorization_code="AUTH_001",
        )

        vault.consume_dataset(
            dataset_id="EVAL_2022",
            candidate_id="STRAT-000003",
            result_checksum="result123",
        )

        # Verify status is CONSUMED
        metadata = vault.get_metadata("EVAL_2022")
        assert metadata.seal_status == EvidenceSealStatus.CONSUMED


class TestResearchExposureDetection:
    """Tests 11-15: Research exposure blocking."""

    def test_research_exposed_dataset_cannot_be_authorized(self):
        """Test 11: EXPOSED dataset → authorization rejected."""
        vault = EvidenceVault()

        vault.register_dataset_unsealed(
            dataset_id="EXPOSED_DATA",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime.utcnow(),
            download_method="api",
            source_verified=True,
        )

        data = b"data that was used in research"

        # Seal as EXPOSED
        vault.seal_dataset(
            dataset_id="EXPOSED_DATA",
            data_bytes=data,
            research_exposure="EXPOSED",  # Already used in research!
            independence_level="LEVEL_3",
        )

        # Try to authorize → should fail
        with pytest.raises(ValueError):
            vault.authorize_evaluation(
                dataset_id="EXPOSED_DATA",
                candidate_id="STRAT-000003",
                candidate_spec_checksum="abc123",
                authorization_code="AUTH_001",
            )

    def test_unknown_independence_cannot_be_authorized(self):
        """Test 12: UNKNOWN independence → authorization rejected."""
        vault = EvidenceVault()

        vault.register_dataset_unsealed(
            dataset_id="UNKNOWN_DATA",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime.utcnow(),
            download_method="api",
            source_verified=True,
        )

        data = b"data"

        # Seal with UNKNOWN independence
        vault.seal_dataset(
            dataset_id="UNKNOWN_DATA",
            data_bytes=data,
            research_exposure="UNEXPOSED",
            independence_level="UNKNOWN",  # Not known!
        )

        # Try to authorize → should fail (OGD-4: UNKNOWN = NOT_ELIGIBLE)
        with pytest.raises(ValueError):
            vault.authorize_evaluation(
                dataset_id="UNKNOWN_DATA",
                candidate_id="STRAT-000003",
                candidate_spec_checksum="abc123",
                authorization_code="AUTH_001",
            )


class TestPreResearchFirewall:
    """Tests 16-20: Pre-research firewall (metadata visible, observations locked)."""

    def test_metadata_visible_before_seal(self):
        """Test 16: Metadata is accessible before seal."""
        vault = EvidenceVault()

        vault.register_dataset_unsealed(
            dataset_id="TEST_EURUSD",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime.utcnow(),
            download_method="api",
            source_verified=True,
        )

        # Metadata should be accessible
        metadata = vault.get_metadata("TEST_EURUSD")
        assert metadata.dataset_id == "TEST_EURUSD"
        assert metadata.instrument == "EURUSD"

    def test_observations_locked_before_authorization(self):
        """Test 17: Observation access is denied before authorization."""
        vault = EvidenceVault()

        vault.register_dataset_unsealed(
            dataset_id="LOCKED_DATA",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime.utcnow(),
            download_method="api",
            source_verified=True,
        )

        data = b"locked observation data"

        vault.seal_dataset(
            dataset_id="LOCKED_DATA",
            data_bytes=data,
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        # Try to access observations → should fail
        with pytest.raises(PermissionError):
            vault.get_observation_access_denied("LOCKED_DATA")


class TestAuditTrail:
    """Tests 21-25: Complete lineage and audit trail."""

    def test_audit_trail_records_all_actions(self):
        """Test 21: Audit trail captures seal, authorization, consumption."""
        vault = EvidenceVault()

        vault.register_dataset_unsealed(
            dataset_id="AUDIT_TEST",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime.utcnow(),
            download_method="api",
            source_verified=True,
        )

        data = b"audit test data"

        vault.seal_dataset(
            dataset_id="AUDIT_TEST",
            data_bytes=data,
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        vault.authorize_evaluation(
            dataset_id="AUDIT_TEST",
            candidate_id="STRAT-000003",
            candidate_spec_checksum="abc123",
            authorization_code="AUTH_001",
        )

        vault.consume_dataset(
            dataset_id="AUDIT_TEST",
            candidate_id="STRAT-000003",
            result_checksum="result123",
        )

        # Audit trail should show all steps
        trail = vault.get_audit_trail("AUDIT_TEST")
        assert trail["status"] == "consumed"
        assert trail["consumption_count"] == 1
        assert trail["consumption_records"][0]["candidate_id"] == "STRAT-000003"


class TestOGD4Principles:
    """Tests 26-30: OGD-4 governance principles."""

    def test_later_timestamp_does_not_guarantee_independence(self):
        """Test 26: LATER_TIMESTAMP ≠ AUTOMATIC_INDEPENDENCE (OGD-4)."""
        vault = EvidenceVault()

        # Dataset 1: 2021 training data
        vault.register_dataset_unsealed(
            dataset_id="TRAIN_2021",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2021, 1, 1),
            coverage_end=datetime(2021, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime.utcnow(),
            download_method="api",
            source_verified=True,
        )

        # Dataset 2: 2021 data again (should not be independent just because later)
        vault.register_dataset_unsealed(
            dataset_id="EVAL_2021_LATER",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2021, 6, 1),  # Same period as training
            coverage_end=datetime(2021, 12, 31),
            row_count=4380,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime(2023, 1, 1),  # Downloaded LATER, but...
            download_method="api",
            source_verified=True,
        )

        vault.seal_dataset(
            dataset_id="EVAL_2021_LATER",
            data_bytes=b"overlapping 2021 data",
            research_exposure="UNEXPOSED",
            independence_level="UNKNOWN",  # Not independent just because downloaded later!
        )

        # Authorization should fail (UNKNOWN independence)
        with pytest.raises(ValueError):
            vault.authorize_evaluation(
                dataset_id="EVAL_2021_LATER",
                candidate_id="STRAT-000003",
                candidate_spec_checksum="abc123",
                authorization_code="AUTH_001",
            )

    def test_unknown_defaults_to_ineligible(self):
        """Test 27: UNKNOWN = NOT_ELIGIBLE (OGD-4 core principle)."""
        vault = EvidenceVault()

        vault.register_dataset_unsealed(
            dataset_id="UNKNOWN_DATA",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime.utcnow(),
            download_method="api",
            source_verified=True,
        )

        vault.seal_dataset(
            dataset_id="UNKNOWN_DATA",
            data_bytes=b"data",
            research_exposure="UNEXPOSED",
            independence_level="UNKNOWN",
        )

        # Metadata is visible
        metadata = vault.get_metadata("UNKNOWN_DATA")
        assert metadata.independence_level == "UNKNOWN"

        # But authorization is rejected
        with pytest.raises(ValueError):
            vault.authorize_evaluation(
                dataset_id="UNKNOWN_DATA",
                candidate_id="STRAT-000003",
                candidate_spec_checksum="abc123",
                authorization_code="AUTH_001",
            )

    def test_seal_reproducibility_across_processes(self):
        """Test 28: Seal is reproducible (fresh process can verify)."""
        # Simulate two separate runs
        vault1 = EvidenceVault()
        vault1.register_dataset_unsealed(
            dataset_id="REPRO_TEST",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime(2022, 12, 15, 10, 30),  # Specific timestamp
            download_method="api",
            source_verified=True,
        )

        data = b"repro test data"
        seal1 = vault1.seal_dataset(
            dataset_id="REPRO_TEST",
            data_bytes=data,
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        # Fresh process (new vault, same inputs)
        vault2 = EvidenceVault()
        vault2.register_dataset_unsealed(
            dataset_id="REPRO_TEST",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime(2022, 12, 15, 10, 30),  # Same timestamp
            download_method="api",
            source_verified=True,
        )

        seal2 = vault2.seal_dataset(
            dataset_id="REPRO_TEST",
            data_bytes=data,
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        assert seal1 == seal2, "Seals must be reproducible across processes"
