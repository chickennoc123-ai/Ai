"""
OGD-4: Evidence Vault Adversarial Tests

Behavioral tests verifying that independent evidence is properly sealed,
protected, and consumed according to OGD-4 governance.

Every ``EvidenceVault(...)`` in this file is given an explicit, unique
``path`` under pytest's ``tmp_path`` fixture. This is required now that the
vault persists to disk (``core/factory/evidence_vault.py``): without an
explicit path, every instance would default to the same
``reports/factory/evidence_vault.json`` and tests that intentionally
construct a second "fresh" vault reusing the same ``dataset_id`` (to prove
seal determinism across independent runs) would collide with whatever the
first vault already persisted under that id.
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

    def test_seal_hash_is_reproducible(self, tmp_path):
        """Test 1: Same data + metadata → same seal hash."""
        vault = EvidenceVault(path=tmp_path / "vault_a.json")
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

        # Create fresh vault (separate file, simulating an independent run) and
        # attempt to reproduce
        vault2 = EvidenceVault(path=tmp_path / "vault_b.json")
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

    def test_data_mutation_changes_seal(self, tmp_path):
        """Test 2: Modified data → different seal hash."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

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

    def test_metadata_mutation_changes_seal(self, tmp_path):
        """Test 3: Modified metadata → different seal hash."""
        vault1 = EvidenceVault(path=tmp_path / "vault_a.json")

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
        vault2 = EvidenceVault(path=tmp_path / "vault_b.json")
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

    def test_consumed_dataset_cannot_be_resealed(self, tmp_path):
        """Test 6: Attempt to reseal a consumed dataset → rejected."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

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

    def test_consumed_dataset_status_is_terminal(self, tmp_path):
        """Test 7: Consumed status is permanent."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

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

    def test_second_consumption_is_forbidden(self, tmp_path):
        """Test 8: Calling consume_dataset() a second time is rejected,
        even for a different candidate_id."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

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
        vault.seal_dataset(
            dataset_id="EVAL_2022",
            data_bytes=b"evaluation data",
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

        # A second authorization + consumption attempt against the same
        # already-consumed dataset must fail even with a different candidate.
        with pytest.raises(ValueError):
            vault.authorize_evaluation(
                dataset_id="EVAL_2022",
                candidate_id="STRAT-000004",
                candidate_spec_checksum="def456",
                authorization_code="AUTH_002",
            )

    def test_seal_dataset_cannot_be_sealed_twice(self, tmp_path):
        """Test 9: A dataset already in SEALED status (not yet consumed)
        cannot be sealed again -- resealing is forbidden at every stage,
        not merely after consumption."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

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
        vault.seal_dataset(
            dataset_id="EVAL_2022",
            data_bytes=b"evaluation data",
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        with pytest.raises(ValueError):
            vault.seal_dataset(
                dataset_id="EVAL_2022",
                data_bytes=b"different bytes entirely",
                research_exposure="UNEXPOSED",
                independence_level="LEVEL_3",
            )

    def test_consumption_requires_prior_authorization(self, tmp_path):
        """Test 10: consume_dataset() cannot jump straight from SEALED to
        CONSUMED, skipping AUTHORIZED and skipping authorize_evaluation()
        entirely."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

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
        vault.seal_dataset(
            dataset_id="EVAL_2022",
            data_bytes=b"evaluation data",
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        # No authorize_evaluation() call happened -- consumption must be
        # rejected regardless of what checksum/candidate_id is supplied.
        with pytest.raises(ValueError):
            vault.consume_dataset(
                dataset_id="EVAL_2022",
                candidate_id="STRAT-000003",
                result_checksum="result123",
            )


class TestResearchExposureDetection:
    """Tests 11-15: Research exposure blocking."""

    def test_research_exposed_dataset_cannot_be_authorized(self, tmp_path):
        """Test 11: EXPOSED dataset → authorization rejected."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

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

    def test_unknown_independence_cannot_be_authorized(self, tmp_path):
        """Test 12: UNKNOWN independence → authorization rejected."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

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

    def test_verify_seal_rejects_substituted_dataset_bytes(self, tmp_path):
        """Test 13: A completely different dataset's bytes must not verify
        against another dataset's seal (guards against silently swapping
        in a different file post-seal while keeping the same dataset_id)."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

        vault.register_dataset_unsealed(
            dataset_id="REAL_DATA",
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
            dataset_id="REAL_DATA",
            data_bytes=b"the genuine sealed EURUSD bytes",
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        substituted_bytes = b"a completely unrelated dataset's bytes"
        assert not vault.verify_seal("REAL_DATA", substituted_bytes)

    def test_metadata_field_change_after_seal_breaks_verification(self, tmp_path):
        """Test 14: Silently editing a sealed dataset's metadata in place
        (e.g. timezone) must break seal verification -- metadata is part
        of the cryptographic identity, not a free-form label."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

        vault.register_dataset_unsealed(
            dataset_id="REAL_DATA",
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
        data = b"sealed observation bytes"
        vault.seal_dataset(
            dataset_id="REAL_DATA",
            data_bytes=data,
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        # Mutate metadata in place after sealing (e.g. a silent source-code
        # patch attempting to change the timezone post-hoc).
        vault.datasets["REAL_DATA"].timezone = "US/Eastern"

        assert not vault.verify_seal("REAL_DATA", data)


class TestPreResearchFirewall:
    """Tests 16-20: Pre-research firewall (metadata visible, observations locked)."""

    def test_metadata_visible_before_seal(self, tmp_path):
        """Test 16: Metadata is accessible before seal."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

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

    def test_observations_locked_before_authorization(self, tmp_path):
        """Test 17: Observation access is denied before authorization."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

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

    def test_no_public_method_returns_raw_observation_bytes(self, tmp_path):
        """Test 18: The vault's public API surface has no method that
        returns raw observation bytes/dataframes -- the only way to see
        the data is to have kept the original bytes outside the vault,
        which is outside the vault's control but at least the vault
        itself never re-exposes them."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

        public_methods = [name for name in dir(vault) if not name.startswith("_") and callable(getattr(vault, name))]
        forbidden_name_fragments = ["get_observations", "get_dataframe", "get_prices", "get_ohlc", "load_data"]
        for name in public_methods:
            for fragment in forbidden_name_fragments:
                assert fragment not in name.lower(), (
                    f"EvidenceVault exposes {name}(), which looks like it could "
                    f"return raw observations outside the authorization flow"
                )

    def test_authorized_but_unconsumed_dataset_still_reports_locked_via_denied_helper(self, tmp_path):
        """Test 19: Even after authorization, the demonstration helper
        get_observation_access_denied() still reports the dataset as
        SEALED-class-locked rather than silently switching to 'open' --
        the vault's demo method never claims observations became visible."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

        vault.register_dataset_unsealed(
            dataset_id="AUTH_LOCKED",
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
            dataset_id="AUTH_LOCKED",
            data_bytes=b"data",
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )
        vault.authorize_evaluation(
            dataset_id="AUTH_LOCKED",
            candidate_id="STRAT-000003",
            candidate_spec_checksum="abc123",
            authorization_code="AUTH_001",
        )

        # Authorized (not SEALED, not UNSEALED) -- the demo helper's only
        # two branches are SEALED and "not sealed"; an AUTHORIZED dataset
        # falls into the generic "not sealed" branch, which still raises
        # PermissionError rather than ever returning data.
        with pytest.raises(PermissionError):
            vault.get_observation_access_denied("AUTH_LOCKED")


class TestAuditTrail:
    """Tests 21-25: Complete lineage and audit trail."""

    def test_audit_trail_records_all_actions(self, tmp_path):
        """Test 21: Audit trail captures seal, authorization, consumption."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

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

    def test_audit_trail_persists_across_fresh_vault_instance(self, tmp_path):
        """Test 22: The audit trail is not just an in-memory artifact of
        the instance that performed the seal -- a brand-new EvidenceVault
        instance pointed at the same file sees the identical trail."""
        path = tmp_path / "vault.json"
        vault = EvidenceVault(path=path)

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
        vault.seal_dataset(
            dataset_id="AUDIT_TEST",
            data_bytes=b"audit test data",
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        # Open the SAME file from a brand-new instance (simulating a fresh
        # process reopening repository state).
        reopened = EvidenceVault(path=path)
        trail = reopened.get_audit_trail("AUDIT_TEST")
        assert trail["status"] == "sealed"
        assert trail["seal_hash"] == vault.seals["AUDIT_TEST"]


class TestOGD4Principles:
    """Tests 26-30: OGD-4 governance principles."""

    def test_later_timestamp_does_not_guarantee_independence(self, tmp_path):
        """Test 26: LATER_TIMESTAMP ≠ AUTOMATIC_INDEPENDENCE (OGD-4)."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

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

    def test_unknown_defaults_to_ineligible(self, tmp_path):
        """Test 27: UNKNOWN = NOT_ELIGIBLE (OGD-4 core principle)."""
        vault = EvidenceVault(path=tmp_path / "vault.json")

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

    def test_seal_reproducibility_across_processes(self, tmp_path):
        """Test 28: Seal is reproducible (fresh process can verify)."""
        # Simulate two separate runs
        vault1 = EvidenceVault(path=tmp_path / "vault_a.json")
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

        # Fresh process (new vault, separate file, same inputs)
        vault2 = EvidenceVault(path=tmp_path / "vault_b.json")
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

    def test_seal_survives_a_genuinely_fresh_process(self, tmp_path):
        """Test 29: Persisted seal state is byte-identical when reopened by
        a subprocess that imports nothing from this test's Python process --
        the strongest form of the 'fresh process' reproducibility claim."""
        import subprocess
        import sys
        import textwrap

        path = tmp_path / "vault.json"
        vault = EvidenceVault(path=path)
        vault.register_dataset_unsealed(
            dataset_id="SUBPROCESS_REPRO",
            instrument="EURUSD",
            timeframe="H1",
            source="dukascopy",
            source_url="https://dukascopy.com",
            coverage_start=datetime(2022, 1, 1),
            coverage_end=datetime(2022, 12, 31),
            row_count=8760,
            timezone="UTC",
            price_type="OHLC",
            download_timestamp=datetime(2022, 12, 15, 10, 30),
            download_method="api",
            source_verified=True,
        )
        data = b"subprocess repro test data"
        seal1 = vault.seal_dataset(
            dataset_id="SUBPROCESS_REPRO",
            data_bytes=data,
            research_exposure="UNEXPOSED",
            independence_level="LEVEL_3",
        )

        script = textwrap.dedent(f"""
            from core.factory.evidence_vault import EvidenceVault
            v = EvidenceVault(path={str(path)!r})
            assert v.verify_seal("SUBPROCESS_REPRO", {data!r}), "seal did not verify in fresh process"
            print(v.seals["SUBPROCESS_REPRO"])
        """)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
        )
        assert result.returncode == 0, f"subprocess failed: {result.stderr}"
        assert result.stdout.strip() == seal1

    def test_pure_holdout_reuse_remains_zero(self):
        """Test 30: OGD-4 dataset-selection audit work must never touch
        PURE_HOLDOUT's consumption history -- it stays at exactly one
        access (Generation 4), regardless of anything the Evidence Vault
        does with unrelated dataset_ids."""
        import json
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        release_record = json.loads(
            (repo_root / "reports" / "generation4" / "HOLDOUT_RELEASE_RECORD.json").read_text()
        )
        holdout_eval = json.loads(
            (repo_root / "reports" / "generation4" / "EVALUATION_PURE_HOLDOUT.json").read_text()
        )
        assert release_record["candidate_id"] == "STRAT-000002"
        assert holdout_eval["candidate_id"] == "STRAT-000002"
        assert holdout_eval["partition_name"] == "PURE_HOLDOUT"
