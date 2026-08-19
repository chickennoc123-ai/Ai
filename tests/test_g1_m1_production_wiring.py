"""Closes Generation 1 finding G1-M1 (production wiring).

Per ML-001-GENERATION-1-INDEPENDENT-AUDIT.md finding D1/M1: the Data
Factory / Market Universe registries were correct but not consumed by any
real training/evaluation entry point. core.factory.research_pipeline is
the fix. These tests prove the wiring is real: a bypass attempt (tampered
checksum, unregistered dataset, wrong symbol, synthetic-flagged data)
must fail, not silently succeed.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.factory.dataset_registry import (
    DatasetIntegrityViolationError,
    DatasetNotFoundError,
    DatasetPathNotRecordedError,
    DatasetRecord,
    DatasetRegistry,
    RealMarketDataEligibilityError,
)
from core.factory.instrument_registry import InstrumentNotFoundError, InstrumentRecord, InstrumentRegistry
from core.factory.research_pipeline import run_registered_walkforward
from tests.r2_fixtures import make_synthetic_ohlcv


def _write_synthetic_csv(tmp_path: Path, n: int = 3000, seed: int = 1) -> Path:
    df = make_synthetic_ohlcv(n, seed=seed)
    p = tmp_path / "TESTFX_H1.csv"
    df.to_csv(p, index_label="timestamp")
    return p


def _dataset_record(csv_path: Path, file_checksum: str, **overrides) -> DatasetRecord:
    from core.factory.dataset_registry import compute_file_checksum

    base = dict(
        dataset_id="DATASET-TESTFX-H1-WIRING",
        instrument="TESTFX",
        timeframe="H1",
        source_id="SRC-TEST",
        source_url="https://example.invalid",
        download_timestamp="2026-01-01T00:00:00+00:00",
        timezone="UTC",
        price_type="mid",
        coverage_start="2020-01-01T00:00:00+00:00",
        coverage_end="2021-01-01T00:00:00+00:00",
        row_count=3000,
        duplicate_count=0,
        missing_bar_count=0,
        gap_report={},
        checksum=file_checksum,
        file_checksum=file_checksum,
        download_method="test-fixture",
        synthetic=False,
        provenance_status="VERIFIED",
        integrity_status="PASS",
        verification_method="synthetic test fixture, not real -- used only to exercise wiring",
        file_path=str(csv_path),
    )
    base.update(overrides)
    return DatasetRecord(**base)


def _instrument_record(**overrides) -> InstrumentRecord:
    base = dict(instrument_id="INSTR-TESTFX", symbol="TESTFX", asset_class="FX_SPOT", status="ACTIVE")
    base.update(overrides)
    return InstrumentRecord(**base)


class TestWiringPositivePath:
    def test_run_registered_walkforward_succeeds_against_registered_synthetic_data(self, tmp_path) -> None:
        from core.factory.dataset_registry import compute_file_checksum

        csv_path = _write_synthetic_csv(tmp_path)
        checksum = compute_file_checksum(csv_path)
        ds_reg = DatasetRegistry(path=tmp_path / "datasets.json")
        ds_reg.register(_dataset_record(csv_path, checksum))
        instr_reg = InstrumentRegistry(path=tmp_path / "instruments.json")
        instr_reg.register(_instrument_record())

        result = run_registered_walkforward(
            dataset_id="DATASET-TESTFX-H1-WIRING",
            hypothesis_id="WIRING-TEST",
            train_window_size=1400,
            test_window_size=200,
            step_size=200,
            window_limit=1,
            dataset_registry=ds_reg,
            instrument_registry=instr_reg,
        )
        assert result.windows_run == 1
        assert result.dataset.dataset_id == "DATASET-TESTFX-H1-WIRING"
        assert result.instrument.symbol == "TESTFX"
        assert len(result.batches) == 1


class TestWiringBypassMustFail:
    """Each of these proves the wiring is load-bearing: if the production
    path were changed to bypass the canonical registry (e.g. reading a
    CSV directly instead of calling load_verified_dataframe), these tests
    would stop failing on a real violation -- that is the point."""

    def test_unregistered_dataset_id_is_rejected(self, tmp_path) -> None:
        ds_reg = DatasetRegistry(path=tmp_path / "datasets.json")
        instr_reg = InstrumentRegistry(path=tmp_path / "instruments.json")
        with pytest.raises(DatasetNotFoundError):
            run_registered_walkforward(
                dataset_id="DATASET-DOES-NOT-EXIST", hypothesis_id="X",
                train_window_size=500, test_window_size=100, step_size=100,
                dataset_registry=ds_reg, instrument_registry=instr_reg,
            )

    def test_tampered_file_after_registration_is_rejected(self, tmp_path) -> None:
        """The canonical negative case: register a file, then MUTATE it on
        disk (simulating either corruption or a bypass attempt that swaps
        in different data under the same path), and confirm the wired
        path refuses to proceed."""
        from core.factory.dataset_registry import compute_file_checksum

        csv_path = _write_synthetic_csv(tmp_path)
        checksum = compute_file_checksum(csv_path)
        ds_reg = DatasetRegistry(path=tmp_path / "datasets.json")
        ds_reg.register(_dataset_record(csv_path, checksum))
        instr_reg = InstrumentRegistry(path=tmp_path / "instruments.json")
        instr_reg.register(_instrument_record())

        # tamper: overwrite the registered file with different content
        tampered = make_synthetic_ohlcv(2000, seed=999)
        tampered.to_csv(csv_path, index_label="timestamp")

        with pytest.raises(DatasetIntegrityViolationError):
            run_registered_walkforward(
                dataset_id="DATASET-TESTFX-H1-WIRING", hypothesis_id="X",
                train_window_size=500, test_window_size=100, step_size=100,
                dataset_registry=ds_reg, instrument_registry=instr_reg,
            )

    def test_synthetic_flagged_dataset_is_rejected_even_if_path_is_valid(self, tmp_path) -> None:
        from core.factory.dataset_registry import compute_file_checksum

        csv_path = _write_synthetic_csv(tmp_path)
        checksum = compute_file_checksum(csv_path)
        ds_reg = DatasetRegistry(path=tmp_path / "datasets.json")
        ds_reg.register(
            _dataset_record(
                csv_path, checksum, synthetic=True, provenance_status="KNOWN_SYNTHETIC", verification_method=""
            )
        )
        instr_reg = InstrumentRegistry(path=tmp_path / "instruments.json")
        instr_reg.register(_instrument_record())

        with pytest.raises(RealMarketDataEligibilityError):
            run_registered_walkforward(
                dataset_id="DATASET-TESTFX-H1-WIRING", hypothesis_id="X",
                train_window_size=500, test_window_size=100, step_size=100,
                dataset_registry=ds_reg, instrument_registry=instr_reg,
            )

    def test_unverified_provenance_dataset_is_rejected(self, tmp_path) -> None:
        from core.factory.dataset_registry import compute_file_checksum

        csv_path = _write_synthetic_csv(tmp_path)
        checksum = compute_file_checksum(csv_path)
        ds_reg = DatasetRegistry(path=tmp_path / "datasets.json")
        ds_reg.register(_dataset_record(csv_path, checksum, provenance_status="UNVERIFIED", verification_method=""))
        instr_reg = InstrumentRegistry(path=tmp_path / "instruments.json")
        instr_reg.register(_instrument_record())

        with pytest.raises(RealMarketDataEligibilityError):
            run_registered_walkforward(
                dataset_id="DATASET-TESTFX-H1-WIRING", hypothesis_id="X",
                train_window_size=500, test_window_size=100, step_size=100,
                dataset_registry=ds_reg, instrument_registry=instr_reg,
            )

    def test_dataset_with_no_recorded_path_is_rejected(self, tmp_path) -> None:
        ds_reg = DatasetRegistry(path=tmp_path / "datasets.json")
        ds_reg.register(_dataset_record(Path(""), "deadbeef", file_path=""))
        instr_reg = InstrumentRegistry(path=tmp_path / "instruments.json")
        instr_reg.register(_instrument_record())

        with pytest.raises(DatasetPathNotRecordedError):
            run_registered_walkforward(
                dataset_id="DATASET-TESTFX-H1-WIRING", hypothesis_id="X",
                train_window_size=500, test_window_size=100, step_size=100,
                dataset_registry=ds_reg, instrument_registry=instr_reg,
            )

    def test_missing_instrument_registration_is_rejected(self, tmp_path) -> None:
        from core.factory.dataset_registry import compute_file_checksum

        csv_path = _write_synthetic_csv(tmp_path)
        checksum = compute_file_checksum(csv_path)
        ds_reg = DatasetRegistry(path=tmp_path / "datasets.json")
        ds_reg.register(_dataset_record(csv_path, checksum))
        instr_reg = InstrumentRegistry(path=tmp_path / "instruments.json")  # TESTFX never registered

        with pytest.raises(InstrumentNotFoundError):
            run_registered_walkforward(
                dataset_id="DATASET-TESTFX-H1-WIRING", hypothesis_id="X",
                train_window_size=500, test_window_size=100, step_size=100,
                dataset_registry=ds_reg, instrument_registry=instr_reg,
            )


class TestProductionRealDataWiring:
    """Confirms the wiring works against the actual real EURUSD dataset,
    not only synthetic fixtures -- small scale (window_limit), never
    claimed as an economic result."""

    def test_real_eurusd_dataset_wires_through_the_canonical_path(self) -> None:
        from core.factory.dataset_registry import DEFAULT_DATASET_REGISTRY_PATH
        from core.factory.instrument_registry import DEFAULT_INSTRUMENT_REGISTRY_PATH

        if not (DEFAULT_DATASET_REGISTRY_PATH.exists() and DEFAULT_INSTRUMENT_REGISTRY_PATH.exists()):
            pytest.skip("production registries not present in this checkout")

        result = run_registered_walkforward(
            dataset_id="DATASET-EURUSD-H1-KOMO135-V1",
            hypothesis_id="GEN2-WIRING-PROOF-TEST",
            train_window_size=24 * 515,
            test_window_size=515,
            step_size=515,
            window_limit=1,  # deliberately tiny -- proof of wiring, not an economic run
        )
        assert result.windows_run == 1
        assert result.windows_available > 1  # confirms this really is a truncation, not the whole dataset
        assert result.dataset.dataset_id == "DATASET-EURUSD-H1-KOMO135-V1"
        assert result.instrument.symbol == "EURUSD"
        assert len(result.batches) == 1
