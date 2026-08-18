"""Tests for core.factory.data_source_registry and core.factory.dataset_registry
— Generation 1 Phase 1 (Data Factory).
"""

from __future__ import annotations

import json

import pytest

from core.factory.data_source_registry import (
    DataSourceRecord,
    DataSourceRegistry,
    DataSourceSpecError,
    DuplicateDataSourceError,
)
from core.factory.dataset_registry import (
    DatasetRecord,
    DatasetRegistry,
    DatasetSpecError,
    RealMarketDataEligibilityError,
    assert_real_market_data_eligible,
    compute_file_checksum,
)


def _source(**overrides) -> DataSourceRecord:
    base = dict(
        source_id="SRC-TEST-001",
        provider="Test Provider",
        source_url="https://example.invalid/data",
        access_method="HTTP_DOWNLOAD",
        coverage="2020-2021",
        supported_instruments=("EURUSD",),
        supported_timeframes=("H1",),
        timezone_semantics="UTC",
        price_type="mid",
        availability="reachable",
    )
    base.update(overrides)
    return DataSourceRecord(**base)


def _dataset(**overrides) -> DatasetRecord:
    base = dict(
        dataset_id="DATASET-TEST-001",
        instrument="EURUSD",
        timeframe="H1",
        source_id="SRC-TEST-001",
        source_url="https://example.invalid/data/eurusd.csv",
        download_timestamp="2026-01-01T00:00:00+00:00",
        timezone="UTC",
        price_type="mid",
        coverage_start="2020-01-01T00:00:00+00:00",
        coverage_end="2021-01-01T00:00:00+00:00",
        row_count=1000,
        duplicate_count=0,
        missing_bar_count=0,
        gap_report={},
        checksum="deadbeef",
        file_checksum="deadbeef",
        download_method="curl",
        synthetic=False,
        provenance_status="VERIFIED",
        integrity_status="PASS",
        verification_method="independently cross-checked against a known historical event",
    )
    base.update(overrides)
    return DatasetRecord(**base)


class TestDataSourceRecordHonestDefaults:
    def test_new_source_defaults_to_unknown_license_and_unverified_provenance(self) -> None:
        s = _source()
        assert s.license_status == "UNKNOWN"
        assert s.provenance_confidence == "UNVERIFIED"

    def test_unknown_never_silently_becomes_verified(self) -> None:
        """Constructing a source never auto-upgrades license_status --
        it must be explicitly asserted by the caller."""
        s1 = _source()
        s2 = _source(source_id="SRC-TEST-002")
        assert s1.license_status == s2.license_status == "UNKNOWN"

    def test_invalid_license_status_rejected(self) -> None:
        with pytest.raises(DataSourceSpecError):
            _source(license_status="DEFINITELY_FINE")

    def test_invalid_access_method_rejected(self) -> None:
        with pytest.raises(DataSourceSpecError):
            _source(access_method="TELEPATHY")

    def test_empty_supported_instruments_rejected(self) -> None:
        with pytest.raises(DataSourceSpecError):
            _source(supported_instruments=())

    def test_missing_required_field_rejected(self) -> None:
        with pytest.raises(DataSourceSpecError):
            _source(source_url="")


class TestDataSourceRegistryPersistence:
    def test_register_and_reload(self, tmp_path) -> None:
        path = tmp_path / "sources.json"
        reg = DataSourceRegistry(path=path)
        reg.register(_source())
        reloaded = DataSourceRegistry(path=path)
        assert reloaded.get("SRC-TEST-001").provider == "Test Provider"

    def test_duplicate_source_id_rejected(self, tmp_path) -> None:
        reg = DataSourceRegistry(path=tmp_path / "sources.json")
        reg.register(_source())
        with pytest.raises(DuplicateDataSourceError):
            reg.register(_source())


class TestDatasetRecordProvenanceDiscipline:
    def test_synthetic_dataset_cannot_claim_verified_provenance(self) -> None:
        with pytest.raises(DatasetSpecError):
            _dataset(synthetic=True, provenance_status="VERIFIED")

    def test_known_synthetic_requires_synthetic_flag(self) -> None:
        with pytest.raises(DatasetSpecError):
            _dataset(synthetic=False, provenance_status="KNOWN_SYNTHETIC")

    def test_known_synthetic_with_synthetic_flag_constructs(self) -> None:
        d = _dataset(
            synthetic=True,
            provenance_status="KNOWN_SYNTHETIC",
            integrity_status="PASS",
            verification_method="",  # not required for synthetic
        )
        assert d.synthetic is True
        assert d.is_real_market_data_eligible is False

    def test_verified_status_requires_verification_method(self) -> None:
        with pytest.raises(DatasetSpecError):
            _dataset(provenance_status="VERIFIED", verification_method="")

    def test_unverified_dataset_not_real_market_eligible(self) -> None:
        d = _dataset(provenance_status="UNVERIFIED", verification_method="")
        assert d.is_real_market_data_eligible is False

    def test_verified_with_qualification_and_pass_is_eligible(self) -> None:
        d = _dataset(provenance_status="VERIFIED_WITH_QUALIFICATION", verification_method="checked against event X")
        assert d.is_real_market_data_eligible is True

    def test_integrity_partial_blocks_eligibility_even_if_verified(self) -> None:
        d = _dataset(provenance_status="VERIFIED", integrity_status="PARTIAL")
        assert d.is_real_market_data_eligible is False

    def test_assert_real_market_data_eligible_raises_for_ineligible_dataset(self) -> None:
        d = _dataset(provenance_status="UNVERIFIED", verification_method="")
        with pytest.raises(RealMarketDataEligibilityError):
            assert_real_market_data_eligible(d)

    def test_assert_real_market_data_eligible_passes_for_eligible_dataset(self) -> None:
        d = _dataset()
        assert_real_market_data_eligible(d)  # must not raise


class TestDatasetRegistryPersistenceAndIntegrity:
    def test_register_and_reload(self, tmp_path) -> None:
        path = tmp_path / "datasets.json"
        reg = DatasetRegistry(path=path)
        reg.register(_dataset())
        reloaded = DatasetRegistry(path=path)
        got = reloaded.get("DATASET-TEST-001")
        assert got.instrument == "EURUSD"
        assert got.is_real_market_data_eligible is True

    def test_list_by_instrument(self, tmp_path) -> None:
        reg = DatasetRegistry(path=tmp_path / "datasets.json")
        reg.register(_dataset())
        reg.register(_dataset(dataset_id="DATASET-TEST-002", instrument="GBPUSD"))
        assert len(reg.list_by_instrument("EURUSD")) == 1
        assert len(reg.list_by_instrument("GBPUSD")) == 1
        assert len(reg.list_by_instrument("USDJPY")) == 0

    def test_verify_file_checksum_detects_tampering(self, tmp_path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("timestamp,open,high,low,close\n2020-01-01,1.1,1.2,1.0,1.15\n")
        real_checksum = compute_file_checksum(f)
        reg = DatasetRegistry(path=tmp_path / "datasets.json")
        reg.register(_dataset(dataset_id="DATASET-TAMPER-TEST", file_checksum=real_checksum))

        assert reg.verify_file_checksum("DATASET-TAMPER-TEST", f) is True

        f.write_text("timestamp,open,high,low,close\n2020-01-01,9.9,9.9,9.9,9.9\n")  # tampered
        assert reg.verify_file_checksum("DATASET-TAMPER-TEST", f) is False


class TestRealDatasetsAreActuallyRegisteredAndEligible:
    """Locks in Phase 1's exit criterion: at least one real dataset passes
    the complete Data Factory contract, using the production registry."""

    def test_production_dataset_registry_contains_eurusd_and_gbpusd(self) -> None:
        from core.factory.dataset_registry import DEFAULT_DATASET_REGISTRY_PATH

        if not DEFAULT_DATASET_REGISTRY_PATH.exists():
            pytest.skip("production dataset registry not present in this checkout")
        reg = DatasetRegistry(path=DEFAULT_DATASET_REGISTRY_PATH)
        eurusd = reg.get("DATASET-EURUSD-H1-KOMO135-V1")
        gbpusd = reg.get("DATASET-GBPUSD-H1-KOMO135-V1")
        assert eurusd.is_real_market_data_eligible is True
        assert gbpusd.is_real_market_data_eligible is True
        assert eurusd.synthetic is False
        assert gbpusd.synthetic is False

    def test_production_dataset_file_checksums_match_on_disk_files(self) -> None:
        from pathlib import Path

        from core.factory.dataset_registry import DEFAULT_DATASET_REGISTRY_PATH

        if not DEFAULT_DATASET_REGISTRY_PATH.exists():
            pytest.skip("production dataset registry not present in this checkout")
        reg = DatasetRegistry(path=DEFAULT_DATASET_REGISTRY_PATH)
        repo_root = Path(__file__).resolve().parent.parent
        eurusd_csv = repo_root / "data" / "csv" / "EURUSD_H1.csv"
        if not eurusd_csv.exists():
            pytest.skip("real EURUSD CSV not present in this checkout")
        assert reg.verify_file_checksum("DATASET-EURUSD-H1-KOMO135-V1", eurusd_csv) is True

    def test_production_data_source_registry_contains_the_real_source(self) -> None:
        from core.factory.data_source_registry import DEFAULT_DATA_SOURCE_REGISTRY_PATH

        if not DEFAULT_DATA_SOURCE_REGISTRY_PATH.exists():
            pytest.skip("production data source registry not present in this checkout")
        reg = DataSourceRegistry(path=DEFAULT_DATA_SOURCE_REGISTRY_PATH)
        source = reg.get("SRC-KOMO135-FOREX-HISTORICAL-DATA")
        # this project has NOT verified this source's license -- must remain honest
        assert source.license_status == "UNKNOWN"
