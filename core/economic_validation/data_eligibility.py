"""Generation 4, Phase 2 — Data eligibility audit.

The dataset registry already records a *declared* integrity/provenance
status (Generation 1). This module does not trust that declaration: it
re-derives every checkable fact from the bytes on disk and reports what
it actually found, then compares. A registry that says ``PASS`` over a
file that is corrupt fails here.

The central judgement this module has to make is the one the Generation 4
contract calls out explicitly:

    distinguish a REAL GAP from DATA CORRUPTION

A real gap is an absence of market activity that the market itself
produced — a weekend close, a public holiday. Data corruption is an
absence the *pipeline* produced. This module uses the already-audited,
already-committed FE-R2-003 gap semantics (``_check_weekday_gaps_v3``,
governance decision recorded 2026-08-18, see
``ML-001-REAL-MARKET-GAP-SEMANTICS-AUDIT.md``) as the authority on which
is which, rather than inventing a second, more convenient definition
here. Anything that classifier does *not* admit is reported as an
unexplained gap and counted against the dataset — it is never quietly
reclassified, interpolated over, or repaired.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.factory.dataset_registry import DatasetRecord, DatasetRegistry
from core.features.fe_r2_001 import _check_weekday_gaps_v3, _is_corrected_weekend_closure_time
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

#: Eligibility verdicts. INSUFFICIENT is a first-class outcome, not a
#: softened FAIL: it means the data cannot support the economic question,
#: which stops the economic path without asserting the data is wrong.
ELIGIBLE = "ELIGIBLE"
INELIGIBLE = "INELIGIBLE"
INSUFFICIENT = "INSUFFICIENT"

#: Minimum usable bars for an H1 economic study. Derived from the
#: pre-existing partition governance, not chosen to fit this dataset: the
#: 60/20/20 split (core/ml_r2/walkforward_r2.py) must leave a PURE_HOLDOUT
#: of at least one full year of H1 bars (~6,000) to be a meaningful final
#: evaluation, which requires ~30,000 usable bars overall.
MIN_USABLE_BARS = 30_000

#: A single-bar move larger than this fraction is flagged as an extreme
#: jump for manual classification. Not a rejection threshold -- FX really
#: does move 5% in an hour (2015 CHF, 2016 GBP), so this flags for review
#: and the report says how many were found; it never deletes a bar.
EXTREME_JUMP_FRACTION = 0.05


class DataEligibilityError(EAFactoryError):
    """Raised when an eligibility audit cannot be performed at all."""


@dataclass(frozen=True)
class GapClassification:
    """How this dataset's missing bars break down."""

    total_missing_intervals: int
    admitted_real_gaps: int
    unexplained_gaps: int
    admitted_by_reason: Dict[str, int] = field(default_factory=dict)
    unexplained_samples: tuple = ()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["unexplained_samples"] = list(self.unexplained_samples)
        return d


@dataclass(frozen=True)
class DataEligibilityReport:
    """The observed truth about one dataset file, plus the verdict."""

    dataset_id: str
    verdict: str
    audit_timestamp: str

    # declared (from the registry)
    declared_provenance_status: str
    declared_integrity_status: str
    declared_synthetic: bool
    declared_row_count: int
    declared_file_checksum: str

    # observed (recomputed from the file)
    observed_file_checksum: str
    observed_row_count: int
    observed_symbol: str
    observed_timeframe: str
    observed_timezone: str
    observed_coverage_start: str
    observed_coverage_end: str
    observed_usable_bars: int

    # integrity checks
    chronology_ok: bool
    duplicate_timestamp_count: int
    ohlc_violation_count: int
    non_positive_price_count: int
    nan_price_count: int
    extreme_jump_count: int
    weekend_bar_count: int
    inferred_bar_interval_seconds: int

    gap_classification: Dict[str, Any]
    checksum_matches_registry: bool
    real_market_data: bool
    findings: tuple = ()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["findings"] = list(self.findings)
        return d

    def report_checksum(self) -> str:
        """Checksum of the audit's findings, excluding when it was run.

        Excluding ``audit_timestamp`` is what makes this checksum usable
        as reproducibility evidence: a re-audit of the same bytes must
        produce the same value, and it cannot if the wall clock is inside
        the hash.
        """
        d = self.to_dict()
        d.pop("audit_timestamp", None)
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


#: Outer envelope of the weekly market closure for this dataset's
#: disclosed UTC-5-fixed (no DST) convention: no bar may EXIST from
#: Saturday 05:00 UTC through Monday 04:59 UTC.
#:
#: This is deliberately narrower than FE-R2-003's
#: ``_is_corrected_weekend_closure_time`` (Saturday 01:00 -> Monday
#: 05:00), and the asymmetry is intentional rather than an inconsistency.
#: That function classifies *missing* timestamps and must be generous,
#: because the actual weekly close drifts between Saturday 01:00 and
#: 04:00 UTC from week to week, so a bar missing at Saturday 02:00 is
#: ordinary. The check here classifies *present* timestamps, and must use
#: the outermost hour at which a bar was ever legitimately observed
#: (Saturday 04:00, empirically the latest close across both symbols).
#: Using the generous window for presence would wrongly condemn ~1,810
#: real end-of-week bars as fabricated; using the strict window for
#: absence would wrongly condemn every ordinary weekly close as a
#: corruption. Two questions, two boundaries.
_CLOSED_WINDOW_SATURDAY_FIRST_CLOSED_HOUR = 5
_CLOSED_WINDOW_MONDAY_REOPEN_HOUR = 5


def _count_bars_in_closed_window(index: pd.DatetimeIndex) -> int:
    """Count bars whose timestamp falls when the market cannot be open.

    A non-zero count means the series contains bars the market did not
    produce -- i.e. fabricated or forward-filled rows -- which disqualifies
    the dataset as economic evidence.
    """
    saturday = (index.dayofweek == 5) & (index.hour >= _CLOSED_WINDOW_SATURDAY_FIRST_CLOSED_HOUR)
    sunday = index.dayofweek == 6
    monday = (index.dayofweek == 0) & (index.hour < _CLOSED_WINDOW_MONDAY_REOPEN_HOUR)
    return int((saturday | sunday | monday).sum())


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_raw_ohlcv(path: Path) -> pd.DataFrame:
    """Read a normalized OHLCV CSV exactly as the pipeline reads it.

    Deliberately does no cleaning, no forward-filling, no reindexing and
    no dropping. Whatever pathologies the file has must survive into the
    frame so the audit below can see them.
    """
    df = pd.read_csv(path)
    if "timestamp" not in df.columns:
        raise DataEligibilityError("OHLCV file has no 'timestamp' column", path=str(path))
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp")
    return df


def _classify_gaps(index: pd.DatetimeIndex, interval: pd.Timedelta) -> GapClassification:
    """Split missing intervals into market-explained and unexplained."""
    admitted = _check_weekday_gaps_v3(index)
    admitted_by_reason: Dict[str, int] = {}
    admitted_keys = set()
    for entry in admitted:
        reason = str(entry.get("reason", entry.get("classification", "ADMITTED")))
        admitted_by_reason[reason] = admitted_by_reason.get(reason, 0) + 1
        # entries carry the gap's start timestamp under one of these keys
        for key in ("gap_start", "start", "from_timestamp", "prev_timestamp", "timestamp"):
            if key in entry:
                admitted_keys.add(str(pd.Timestamp(entry[key])))
                break

    deltas = pd.Series(index[1:]) - pd.Series(index[:-1])
    gap_positions = np.flatnonzero((deltas > interval).to_numpy())
    unexplained: List[str] = []
    for pos in gap_positions:
        start_ts = index[pos]
        if str(pd.Timestamp(start_ts)) not in admitted_keys:
            unexplained.append(f"{start_ts} -> {index[pos + 1]}")

    return GapClassification(
        total_missing_intervals=int(len(gap_positions)),
        admitted_real_gaps=len(admitted),
        unexplained_gaps=len(unexplained),
        admitted_by_reason=admitted_by_reason,
        unexplained_samples=tuple(unexplained[:20]),
    )


def audit_dataset(
    record: DatasetRecord,
    *,
    expected_instrument: Optional[str] = None,
    expected_timeframe: Optional[str] = None,
    min_usable_bars: int = MIN_USABLE_BARS,
) -> DataEligibilityReport:
    """Re-derive every checkable fact about ``record``'s file and judge it.

    ``expected_instrument``/``expected_timeframe`` come from the frozen
    candidate, so "SYMBOL = CORRECT" / "TIMEFRAME = CORRECT" are checked
    against what the candidate asked for, not against what the dataset
    claims about itself.
    """
    findings: List[str] = []
    path = Path(record.file_path)
    if not record.file_path:
        raise DataEligibilityError("dataset record has no file_path; cannot audit", dataset_id=record.dataset_id)
    if not path.exists():
        raise DataEligibilityError("dataset file not found", dataset_id=record.dataset_id, path=str(path))

    observed_checksum = _sha256_file(path)
    checksum_matches = observed_checksum == record.file_checksum
    if not checksum_matches:
        findings.append(
            f"file checksum mismatch: registry={record.file_checksum} observed={observed_checksum}"
        )

    df = load_raw_ohlcv(path)
    index = df.index

    chronology_ok = bool(index.is_monotonic_increasing)
    if not chronology_ok:
        findings.append("timestamps are not monotonically increasing")

    duplicate_count = int(index.duplicated().sum())
    if duplicate_count:
        findings.append(f"{duplicate_count} duplicate timestamps")

    price_cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
    missing_cols = {"open", "high", "low", "close"} - set(price_cols)
    if missing_cols:
        raise DataEligibilityError(
            "OHLCV file is missing required price columns", dataset_id=record.dataset_id, missing=sorted(missing_cols)
        )

    nan_price_count = int(df[price_cols].isna().any(axis=1).sum())
    if nan_price_count:
        findings.append(f"{nan_price_count} rows with NaN prices")

    non_positive = int((df[price_cols] <= 0).any(axis=1).sum())
    if non_positive:
        findings.append(f"{non_positive} rows with non-positive prices")

    ohlc_violations = int(
        (
            (df["high"] < df["low"])
            | (df["high"] < df["open"])
            | (df["high"] < df["close"])
            | (df["low"] > df["open"])
            | (df["low"] > df["close"])
        ).sum()
    )
    if ohlc_violations:
        findings.append(f"{ohlc_violations} rows violating OHLC ordering")

    returns = df["close"].pct_change()
    extreme_jumps = int((returns.abs() > EXTREME_JUMP_FRACTION).sum())

    # Bar interval inferred from the data itself (the modal delta), never assumed.
    deltas = pd.Series(index[1:]) - pd.Series(index[:-1])
    if deltas.empty:
        raise DataEligibilityError("dataset has fewer than two bars", dataset_id=record.dataset_id)
    interval = deltas.mode().iloc[0]
    inferred_interval_seconds = int(interval.total_seconds())

    timeframe_map = {60: "M1", 300: "M5", 900: "M15", 1800: "M30", 3600: "H1", 14400: "H4", 86400: "D1"}
    observed_timeframe = timeframe_map.get(inferred_interval_seconds, f"{inferred_interval_seconds}s")
    if expected_timeframe and observed_timeframe != expected_timeframe:
        findings.append(
            f"timeframe mismatch: candidate expects {expected_timeframe}, data's modal bar interval is {observed_timeframe}"
        )
    if record.timeframe != observed_timeframe:
        findings.append(
            f"registry declares timeframe {record.timeframe} but modal bar interval is {observed_timeframe}"
        )

    if expected_instrument and record.instrument != expected_instrument:
        findings.append(
            f"symbol mismatch: candidate expects {expected_instrument}, dataset is {record.instrument}"
        )

    weekend_bars = int(_count_bars_in_closed_window(index))
    if weekend_bars:
        findings.append(f"{weekend_bars} bars fall inside the market's closed window")

    gaps = _classify_gaps(index, interval)
    if gaps.unexplained_gaps:
        findings.append(
            f"{gaps.unexplained_gaps} gaps are not explained by weekend/holiday market closure"
        )

    usable_bars = int(df[price_cols].notna().all(axis=1).sum())

    real_market_data = bool(not record.synthetic and record.provenance_status != "KNOWN_SYNTHETIC")
    if not real_market_data:
        findings.append("dataset is synthetic; it can never be economic evidence")

    # --- verdict ---
    hard_failures = (
        not real_market_data
        or not checksum_matches
        or not chronology_ok
        or duplicate_count > 0
        or ohlc_violations > 0
        or non_positive > 0
        or nan_price_count > 0
        or weekend_bars > 0
        or gaps.unexplained_gaps > 0
        or record.provenance_status not in ("VERIFIED", "VERIFIED_WITH_QUALIFICATION")
        or (expected_instrument is not None and record.instrument != expected_instrument)
        or (expected_timeframe is not None and observed_timeframe != expected_timeframe)
    )
    if hard_failures:
        verdict = INELIGIBLE
    elif usable_bars < min_usable_bars:
        verdict = INSUFFICIENT
        findings.append(f"only {usable_bars} usable bars; {min_usable_bars} required for the declared partitioning")
    else:
        verdict = ELIGIBLE

    return DataEligibilityReport(
        dataset_id=record.dataset_id,
        verdict=verdict,
        audit_timestamp=utcnow().isoformat(),
        declared_provenance_status=record.provenance_status,
        declared_integrity_status=record.integrity_status,
        declared_synthetic=bool(record.synthetic),
        declared_row_count=int(record.row_count),
        declared_file_checksum=record.file_checksum,
        observed_file_checksum=observed_checksum,
        observed_row_count=int(len(df)),
        observed_symbol=record.instrument,
        observed_timeframe=observed_timeframe,
        observed_timezone=str(index.tz),
        observed_coverage_start=str(index[0]),
        observed_coverage_end=str(index[-1]),
        observed_usable_bars=usable_bars,
        chronology_ok=chronology_ok,
        duplicate_timestamp_count=duplicate_count,
        ohlc_violation_count=ohlc_violations,
        non_positive_price_count=non_positive,
        nan_price_count=nan_price_count,
        extreme_jump_count=extreme_jumps,
        weekend_bar_count=weekend_bars,
        inferred_bar_interval_seconds=inferred_interval_seconds,
        gap_classification=gaps.to_dict(),
        checksum_matches_registry=checksum_matches,
        real_market_data=real_market_data,
        findings=tuple(findings),
    )


def audit_datasets(
    dataset_ids: List[str],
    *,
    dataset_registry: DatasetRegistry,
    expected_timeframe: Optional[str] = None,
) -> Dict[str, DataEligibilityReport]:
    return {
        did: audit_dataset(
            dataset_registry.get(did),
            expected_instrument=dataset_registry.get(did).instrument,
            expected_timeframe=expected_timeframe,
        )
        for did in dataset_ids
    }
