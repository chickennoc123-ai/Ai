"""Production wiring — closes Generation 1 finding G1-M1.

Per the Generation 1 independent audit (``ML-001-GENERATION-1-INDEPENDENT-
AUDIT.md`` §4/§5, finding D1/M1): the Data Factory and Market Universe
registries existed and were correct, but were not consumed by any real
training/evaluation entry point — ``core/ml_r2/walkforward_r2.py`` read
CSV files directly, bypassing the registries entirely.

This module is the fix: **the one canonical, wired entry point** for
running a walk-forward evaluation against a *registered* dataset. It does
not reimplement any economic logic — ``core/ml_r2/walkforward_r2.py`` is
imported and used completely unmodified (confirmed: this file makes no
edits to that module). What changes is that a caller can no longer get a
DataFrame into that pipeline without first passing the Data Factory's
eligibility gate, the Market Universe's instrument/timeframe compatibility
gate, and a live on-disk checksum re-verification
(``DatasetRegistry.load_verified_dataframe``) — there is no second,
unofficial path in this module that skips those checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd

from core.factory.dataset_registry import DatasetRecord, DatasetRegistry
from core.factory.instrument_registry import (
    InstrumentRecord,
    InstrumentRegistry,
    assert_dataset_matches_instrument,
    assert_supported_timeframe,
)
from core.ml_r2.walkforward_r2 import (
    OOSPredictionBatch,
    RunProvenance,
    TemporalSplit,
    compute_temporal_split,
    generate_oos_predictions,
    make_walk_forward_windows,
)
from utils.exceptions import EAFactoryError


class ResearchPipelineError(EAFactoryError):
    """Raised for a wiring-layer failure not already covered by a more
    specific Data Factory / Market Universe exception."""


@dataclass
class WiredWalkForwardResult:
    """Everything a caller needs, with the canonical identities attached
    — not just raw batches, so the chain back to dataset/instrument
    identity never has to be reconstructed separately."""

    dataset: DatasetRecord
    instrument: InstrumentRecord
    split: TemporalSplit
    batches: List[OOSPredictionBatch]
    provenance_records: List[RunProvenance]
    windows_run: int
    windows_available: int


def run_registered_walkforward(
    *,
    dataset_id: str,
    hypothesis_id: str,
    train_window_size: int,
    test_window_size: int,
    step_size: int,
    window_limit: Optional[int] = None,
    dataset_registry: Optional[DatasetRegistry] = None,
    instrument_registry: Optional[InstrumentRegistry] = None,
) -> WiredWalkForwardResult:
    """The one sanctioned way to run a walk-forward evaluation against a
    dataset that is supposed to be treated as real, eligible market data.

    Raises (never silently falls back to an unofficial path):

    - ``core.factory.dataset_registry.DatasetNotFoundError`` if
      ``dataset_id`` is not registered.
    - ``core.factory.dataset_registry.RealMarketDataEligibilityError`` if
      the dataset fails the provenance/synthetic/integrity contract.
    - ``core.factory.dataset_registry.DatasetPathNotRecordedError`` /
      ``DatasetIntegrityViolationError`` if the on-disk file is missing,
      unrecorded, or no longer matches its registered checksum.
    - ``core.factory.instrument_registry.InstrumentNotFoundError`` if no
      instrument is registered for the dataset's symbol.
    - ``core.factory.instrument_registry.InstrumentSpecError`` if the
      dataset's symbol does not match the resolved instrument (should be
      structurally impossible via ``get_by_symbol``, checked anyway as
      defense in depth against a future registry change).
    - ``core.factory.instrument_registry.UnsupportedTimeframeError`` if
      the dataset's timeframe is outside the architecture's enumeration.

    ``window_limit`` truncates the walk-forward window list — intended
    for tests/proofs that must run fast and must NOT be read as an
    economic result (a truncated run is explicitly not the same claim as
    the full, already-reported 65-window evaluation in
    ``ML-001-R2-REAL-DATA-TRAINING-AND-WALKFORWARD-REPORT.md``).
    """
    ds_reg = dataset_registry or DatasetRegistry()
    instr_reg = instrument_registry or InstrumentRegistry()

    # Gate 1: Data Factory eligibility + on-disk checksum re-verification.
    # This call alone is what makes bypassing the registry impossible --
    # it is the only way this function ever obtains a DataFrame.
    df = ds_reg.load_verified_dataframe(dataset_id)
    dataset = ds_reg.get(dataset_id)

    # Gate 2: Market Universe compatibility.
    instrument = instr_reg.get_by_symbol(dataset.instrument)
    assert_dataset_matches_instrument(dataset.instrument, dataset.timeframe, instrument)
    assert_supported_timeframe(dataset.timeframe)

    split = compute_temporal_split(df)
    dev_val = pd.concat([split.development, split.validation])

    windows = make_walk_forward_windows(dev_val, train_window_size, test_window_size, step_size, hypothesis_id)
    windows_available = len(windows)
    if window_limit is not None:
        windows = windows[:window_limit]

    batches, provenance_records = generate_oos_predictions(
        dev_val,
        windows,
        hypothesis_id=hypothesis_id,
        dataset_id=dataset.dataset_id,
        validation_period=(str(split.validation_range[0]), str(split.validation_range[1])),
        holdout_period=(str(split.holdout_range[0]), str(split.holdout_range[1])),
    )

    return WiredWalkForwardResult(
        dataset=dataset,
        instrument=instrument,
        split=split,
        batches=batches,
        provenance_records=provenance_records,
        windows_run=len(windows),
        windows_available=windows_available,
    )
