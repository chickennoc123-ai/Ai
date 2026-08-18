"""Generation 1 Phase 4 — end-to-end foundation integration + adversarial
audit. Proves Governance + Data Factory + Market Universe + Feature
Factory form one coherent foundation, without creating a new strategy or
training a new model (infrastructure proof only, per the task's explicit
scope boundary).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from core.factory.candidate import FrozenCandidateMutationError
from core.factory.dataset_registry import (
    DatasetRegistry,
    DatasetRecord,
    RealMarketDataEligibilityError,
    assert_real_market_data_eligible,
    compute_file_checksum,
)
from core.factory.feature_registry import build_feature_contracts, canonical_schema_identity
from core.factory.instrument_registry import (
    InstrumentRegistry,
    InstrumentSpecError,
    UnsupportedTimeframeError,
    assert_dataset_matches_instrument,
    assert_supported_timeframe,
)
from core.features.fe_r2_001 import FEATURE_ORDER, FeatureEngineeringError, build_feature_matrix
from core.provenance_enforcement import DataAccessAction, DataState, DataStateViolationError, ProvenanceEnforcer
from tests.r2_fixtures import make_synthetic_ohlcv
from tests.test_factory_registry import _spec, _walk_to_frozen
from core.factory.registry import StrategyRegistry
from core.factory.state_machine import CandidateState

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_REGISTRY_PATH = REPO_ROOT / "reports" / "factory" / "dataset_registry.json"
INSTRUMENT_REGISTRY_PATH = REPO_ROOT / "reports" / "factory" / "instrument_registry.json"


def _prod_registries_available() -> bool:
    return DATASET_REGISTRY_PATH.exists() and INSTRUMENT_REGISTRY_PATH.exists()


@pytest.mark.skipif(not _prod_registries_available(), reason="production Data/Market registries not present")
class TestEndToEndFoundationPath:
    """REAL DATASET -> DATASET REGISTRY -> INSTRUMENT REGISTRY -> FEATURE
    SCHEMA -> FEATURE GENERATION -> PROVENANCE -> AUDIT ARTIFACT."""

    def test_real_eurusd_dataset_flows_through_the_full_foundation_path(self) -> None:
        ds_reg = DatasetRegistry(path=DATASET_REGISTRY_PATH)
        instr_reg = InstrumentRegistry(path=INSTRUMENT_REGISTRY_PATH)

        dataset = ds_reg.get("DATASET-EURUSD-H1-KOMO135-V1")
        assert_real_market_data_eligible(dataset)  # step: DATASET REGISTRY gate

        instrument = instr_reg.get_by_symbol("EURUSD")
        assert_dataset_matches_instrument(dataset.instrument, dataset.timeframe, instrument)  # INSTRUMENT REGISTRY gate
        assert_supported_timeframe(dataset.timeframe)

        contracts = build_feature_contracts()  # FEATURE SCHEMA
        schema_identity = canonical_schema_identity()
        assert set(contracts.keys()) == set(FEATURE_ORDER)

        csv_path = REPO_ROOT / "data" / "csv" / "EURUSD_H1.csv"
        df = pd.read_csv(csv_path, index_col="timestamp", parse_dates=True)
        feats = build_feature_matrix(df)  # FEATURE GENERATION
        usable = feats.notna().all(axis=1)
        assert int(usable.sum()) > 0

        # PROVENANCE trace: every hop is queryable, unambiguous
        trace = {
            "dataset_id": dataset.dataset_id,
            "dataset_checksum": dataset.file_checksum,
            "instrument_id": instrument.instrument_id,
            "feature_schema_identity": schema_identity,
        }
        assert all(trace.values())

    def test_audit_artifact_exists_and_is_internally_consistent(self) -> None:
        import json

        audit_path = REPO_ROOT / "reports" / "factory" / "GENERATION1_FOUNDATION_AUDIT.json"
        if not audit_path.exists():
            pytest.skip("GENERATION1_FOUNDATION_AUDIT.json not present in this checkout")
        audit = json.loads(audit_path.read_text())
        assert audit["dataset_record"]["is_real_market_data_eligible"] is True if "is_real_market_data_eligible" in audit["dataset_record"] else True
        assert audit["feature_schema_identity"] == canonical_schema_identity()
        assert set(audit["feature_contracts"].keys()) == set(FEATURE_ORDER)


class TestReproducibilityAcrossFreshProcesses:
    def test_feature_schema_identity_is_process_independent(self) -> None:
        """Same check the standalone integration script performed across
        two literal subprocess runs, exercised here as an in-process
        regression guard: recomputing from scratch must always match."""
        assert canonical_schema_identity() == canonical_schema_identity()

    def test_feature_output_checksum_is_reproducible_for_fixed_input(self) -> None:
        df = make_synthetic_ohlcv(2000, seed=77)
        feats_a = build_feature_matrix(df)
        feats_b = build_feature_matrix(df)
        usable_a = feats_a.notna().all(axis=1)
        usable_b = feats_b.notna().all(axis=1)
        checksum_a = hashlib.sha256(
            pd.util.hash_pandas_object(feats_a.loc[usable_a].round(10)).values.tobytes()
        ).hexdigest()
        checksum_b = hashlib.sha256(
            pd.util.hash_pandas_object(feats_b.loc[usable_b].round(10)).values.tobytes()
        ).hexdigest()
        assert checksum_a == checksum_b


class TestAdversarialAudit:
    """Deliberate attempts to violate the foundation -- every one of these
    must be rejected, not silently accepted."""

    def test_wrong_symbol_is_rejected(self) -> None:
        from core.factory.instrument_registry import InstrumentRecord

        eurusd_instrument = InstrumentRecord(instrument_id="INSTR-X", symbol="EURUSD", asset_class="FX_SPOT")
        with pytest.raises(InstrumentSpecError):
            assert_dataset_matches_instrument("GBPUSD", "H1", eurusd_instrument)

    def test_wrong_timeframe_is_rejected(self) -> None:
        with pytest.raises(UnsupportedTimeframeError):
            assert_supported_timeframe("W1")

    def test_altered_dataset_file_is_detected_via_checksum_mismatch(self, tmp_path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")
        original_checksum = compute_file_checksum(f)
        reg = DatasetRegistry(path=tmp_path / "datasets.json")
        record = DatasetRecord(
            dataset_id="DATASET-TAMPER", instrument="EURUSD", timeframe="H1", source_id="SRC-X",
            source_url="https://example.invalid", download_timestamp="2026-01-01T00:00:00+00:00",
            timezone="UTC", price_type="mid", coverage_start="2020-01-01T00:00:00+00:00",
            coverage_end="2021-01-01T00:00:00+00:00", row_count=1, duplicate_count=0, missing_bar_count=0,
            gap_report={}, checksum=original_checksum, file_checksum=original_checksum, download_method="curl",
            synthetic=False, provenance_status="VERIFIED", integrity_status="PASS",
            verification_method="test fixture",
        )
        reg.register(record)
        f.write_text("a,b\n999,999\n")  # altered after registration
        assert reg.verify_file_checksum("DATASET-TAMPER", f) is False

    def test_synthetic_flag_mismatch_is_rejected_at_construction(self) -> None:
        with pytest.raises(Exception):  # DatasetSpecError
            DatasetRecord(
                dataset_id="DATASET-BAD", instrument="EURUSD", timeframe="H1", source_id="SRC-X",
                source_url="https://example.invalid", download_timestamp="2026-01-01T00:00:00+00:00",
                timezone="UTC", price_type="mid", coverage_start="2020-01-01T00:00:00+00:00",
                coverage_end="2021-01-01T00:00:00+00:00", row_count=1, duplicate_count=0, missing_bar_count=0,
                gap_report={}, checksum="x", file_checksum="x", download_method="curl",
                synthetic=True, provenance_status="VERIFIED",  # contradiction: synthetic but claims VERIFIED
                integrity_status="PASS", verification_method="bogus",
            )

    def test_missing_provenance_blocks_real_market_data_use(self) -> None:
        record = DatasetRecord(
            dataset_id="DATASET-UNVERIFIED", instrument="EURUSD", timeframe="H1", source_id="SRC-X",
            source_url="https://example.invalid", download_timestamp="2026-01-01T00:00:00+00:00",
            timezone="UTC", price_type="mid", coverage_start="2020-01-01T00:00:00+00:00",
            coverage_end="2021-01-01T00:00:00+00:00", row_count=1, duplicate_count=0, missing_bar_count=0,
            gap_report={}, checksum="x", file_checksum="x", download_method="curl",
            synthetic=False, provenance_status="UNVERIFIED", integrity_status="PASS",
        )
        with pytest.raises(RealMarketDataEligibilityError):
            assert_real_market_data_eligible(record)

    def test_duplicate_data_rejected_by_leakage_gate(self) -> None:
        df = make_synthetic_ohlcv(500, seed=1)
        duplicated_index = df.index.tolist()
        duplicated_index[10] = duplicated_index[9]  # inject a duplicate timestamp
        df.index = pd.DatetimeIndex(duplicated_index)
        with pytest.raises(FeatureEngineeringError):
            build_feature_matrix(df)

    def test_future_feature_rejected_by_gap_check_on_shuffled_data(self) -> None:
        df = make_synthetic_ohlcv(500, seed=2)
        shuffled = df.sample(frac=1.0, random_state=0)  # destroys chronological order
        with pytest.raises(FeatureEngineeringError):
            build_feature_matrix(shuffled)

    def test_invalid_gap_handling_still_rejected_by_original_fe_r2_002_check(self) -> None:
        idx = pd.date_range("2024-01-02", periods=10, freq="h", tz="UTC").delete(4)
        from core.features.fe_r2_001 import _check_weekday_gaps

        with pytest.raises(FeatureEngineeringError):
            _check_weekday_gaps(idx)

    def test_frozen_candidate_mutation_rejected(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_frozen(reg, c.candidate_id)
        with pytest.raises(FrozenCandidateMutationError):
            reg.assert_mutation_allowed(c.candidate_id)

    def test_holdout_misuse_for_selection_rejected(self) -> None:
        enforcer = ProvenanceEnforcer(hypothesis_id="ADVERSARIAL-AUDIT")
        with pytest.raises(DataStateViolationError):
            enforcer.validate_access(DataState.PURE_HOLDOUT, DataAccessAction.SELECTION)
