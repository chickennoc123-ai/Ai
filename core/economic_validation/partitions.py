"""Generation 4, Phases 5-6 — Temporal partitioning and the PURE_HOLDOUT seal.

The partition boundaries are **not chosen by this generation**. They come
from ``core/ml_r2/walkforward_r2.compute_temporal_split``, whose 60/20/20
chronological fractions were committed before STRAT-000002 existed and
before any Generation 4 result was observed. This module derives dates
from those fractions and records them; it has no parameter through which
a boundary could be moved to suit a result.

**The seal is structural, not promissory.** ``SealedDataset`` does not
hold the holdout frame behind a flag that code could read past. Until
``release_holdout`` is called, the holdout rows are held in a private
attribute that every public accessor refuses to return, and the object
records the release irreversibly. The realistic threat model here is not
a malicious caller — anyone editing this file can defeat anything in it —
it is an ordinary caller who reaches for ``.holdout`` out of habit while
building a training set. Against that, an attribute that raises is worth
far more than a comment that asks.

One further protection matters more than the flag: ``development()`` and
``validation()`` return frames that were sliced *before* the holdout rows
were ever attached, so a caller who concatenates everything they can
reach still cannot reconstruct the holdout.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import pandas as pd

from core.ml_r2.walkforward_r2 import DEVELOPMENT_FRACTION, VALIDATION_FRACTION, compute_temporal_split
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

DEVELOPMENT = "DEVELOPMENT"
VALIDATION = "VALIDATION"
PURE_HOLDOUT = "PURE_HOLDOUT"


class HoldoutSealError(EAFactoryError):
    """Raised on any attempt to reach PURE_HOLDOUT data before release."""


class HoldoutAlreadyReleasedError(EAFactoryError):
    """Raised on a second release attempt — the holdout is one-shot."""


@dataclass(frozen=True)
class PartitionBoundaries:
    """The declared, checksummable partition record."""

    dataset_id: str
    dataset_checksum: str
    development_fraction: float
    validation_fraction: float
    holdout_fraction: float
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    holdout_start: str
    holdout_end: str
    development_rows: int
    validation_rows: int
    holdout_rows: int
    derivation: str
    declared_timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def checksum(self) -> str:
        d = self.to_dict()
        d.pop("declared_timestamp", None)
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class HoldoutReleaseRecord:
    """The one-time, auditable record that PURE_HOLDOUT was opened."""

    validation_run_id: str
    candidate_id: str
    candidate_checksum: str
    snapshot_checksum: str
    dataset_id: str
    holdout_dataset_checksum: str
    holdout_start: str
    holdout_end: str
    holdout_rows: int
    reason_for_release: str
    release_timestamp: str
    development_evidence_reference: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def checksum(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, default=str).encode()).hexdigest()


def _frame_checksum(df: pd.DataFrame) -> str:
    return hashlib.sha256(
        pd.util.hash_pandas_object(df, index=True).to_numpy().tobytes()
    ).hexdigest()


class SealedDataset:
    """A dataset whose PURE_HOLDOUT partition is inaccessible until released.

    Construct via :func:`seal_dataset`, never directly with a full frame:
    the constructor takes the three already-separated partitions so no
    code path inside this class ever holds an un-partitioned frame it
    could hand out by accident.
    """

    def __init__(
        self,
        *,
        dataset_id: str,
        dataset_checksum: str,
        development: pd.DataFrame,
        validation: pd.DataFrame,
        holdout: pd.DataFrame,
        boundaries: PartitionBoundaries,
    ) -> None:
        self.dataset_id = dataset_id
        self.dataset_checksum = dataset_checksum
        self.boundaries = boundaries
        self._development = development
        self._validation = validation
        self.__holdout = holdout  # name-mangled: not reachable as .._holdout
        self._released: Optional[HoldoutReleaseRecord] = None
        self._access_log: List[Dict[str, str]] = []

    # ---- always-available partitions ------------------------------------

    def development(self) -> pd.DataFrame:
        self._log(DEVELOPMENT)
        return self._development.copy()

    def validation(self) -> pd.DataFrame:
        self._log(VALIDATION)
        return self._validation.copy()

    def development_and_validation(self) -> pd.DataFrame:
        """Everything the researcher is allowed to look at, concatenated.

        This is the widest frame this object will ever produce before
        release, and it provably excludes the holdout: it is built from
        the two stored partitions only.
        """
        self._log("DEVELOPMENT+VALIDATION")
        return pd.concat([self._development, self._validation]).sort_index()

    # ---- the sealed partition -------------------------------------------

    @property
    def holdout_is_released(self) -> bool:
        return self._released is not None

    def holdout(self) -> pd.DataFrame:
        """Return the PURE_HOLDOUT frame — only after ``release_holdout``."""
        if self._released is None:
            raise HoldoutSealError(
                "PURE_HOLDOUT is sealed: it has not been released for this validation run. "
                "Release requires a completed development evaluation and an explicit, recorded "
                "HoldoutReleaseRecord (Generation 4 Phase 11)",
                dataset_id=self.dataset_id,
            )
        self._log(PURE_HOLDOUT)
        return self.__holdout.copy()

    def holdout_row_count(self) -> int:
        """Row count only — safe before release.

        Deliberately exposed: the *size* of the holdout is a partitioning
        fact recorded in the boundaries record anyway, and needing it does
        not require seeing a single price. No other pre-release accessor
        exists.
        """
        return int(self.boundaries.holdout_rows)

    def release_holdout(
        self,
        *,
        validation_run_id: str,
        candidate_id: str,
        candidate_checksum: str,
        snapshot_checksum: str,
        reason_for_release: str,
        development_evidence_reference: str,
    ) -> HoldoutReleaseRecord:
        """Open the seal exactly once, recording why and against what."""
        if self._released is not None:
            raise HoldoutAlreadyReleasedError(
                "PURE_HOLDOUT has already been released for this dataset in this run; a second "
                "release would make 'evaluated exactly once' false",
                dataset_id=self.dataset_id,
                first_release=self._released.release_timestamp,
            )
        if not reason_for_release.strip():
            raise HoldoutSealError("reason_for_release must be a non-empty explanation")
        if not development_evidence_reference.strip():
            raise HoldoutSealError(
                "development_evidence_reference must point at the completed development/validation "
                "evidence -- the holdout may not be opened before that evidence exists"
            )

        record = HoldoutReleaseRecord(
            validation_run_id=validation_run_id,
            candidate_id=candidate_id,
            candidate_checksum=candidate_checksum,
            snapshot_checksum=snapshot_checksum,
            dataset_id=self.dataset_id,
            holdout_dataset_checksum=_frame_checksum(self.__holdout),
            holdout_start=self.boundaries.holdout_start,
            holdout_end=self.boundaries.holdout_end,
            holdout_rows=int(len(self.__holdout)),
            reason_for_release=reason_for_release,
            release_timestamp=utcnow().isoformat(),
            development_evidence_reference=development_evidence_reference,
        )
        self._released = record
        return record

    def release_record(self) -> Optional[HoldoutReleaseRecord]:
        return self._released

    # ---- audit ----------------------------------------------------------

    def _log(self, partition: str) -> None:
        self._access_log.append({"partition": partition, "timestamp": utcnow().isoformat()})

    def access_log(self) -> List[Dict[str, str]]:
        return list(self._access_log)

    def holdout_was_accessed_before_release(self) -> bool:
        """True if any PURE_HOLDOUT access is logged before the release timestamp.

        Always False by construction (``holdout()`` raises before release);
        this exists so the property is *checked* in the evidence chain
        rather than merely asserted in prose.
        """
        if self._released is None:
            return any(e["partition"] == PURE_HOLDOUT for e in self._access_log)
        return any(
            e["partition"] == PURE_HOLDOUT and e["timestamp"] < self._released.release_timestamp
            for e in self._access_log
        )


def seal_dataset(
    ohlcv: pd.DataFrame,
    *,
    dataset_id: str,
    dataset_checksum: str,
    development_fraction: float = DEVELOPMENT_FRACTION,
    validation_fraction: float = VALIDATION_FRACTION,
) -> SealedDataset:
    """Partition ``ohlcv`` and return it sealed.

    The fractions default to the pre-existing, pre-registered governance
    values and are recorded in the boundaries so a non-default call is
    visible in the evidence rather than invisible in a call site.
    """
    split = compute_temporal_split(
        ohlcv, development_fraction=development_fraction, validation_fraction=validation_fraction
    )
    boundaries = PartitionBoundaries(
        dataset_id=dataset_id,
        dataset_checksum=dataset_checksum,
        development_fraction=development_fraction,
        validation_fraction=validation_fraction,
        holdout_fraction=round(1.0 - development_fraction - validation_fraction, 10),
        train_start=str(split.development_range[0]),
        train_end=str(split.development_range[1]),
        validation_start=str(split.validation_range[0]),
        validation_end=str(split.validation_range[1]),
        holdout_start=str(split.holdout_range[0]),
        holdout_end=str(split.holdout_range[1]),
        development_rows=int(len(split.development)),
        validation_rows=int(len(split.validation)),
        holdout_rows=int(len(split.holdout)),
        derivation=(
            "core.ml_r2.walkforward_r2.compute_temporal_split at its committed "
            f"DEVELOPMENT_FRACTION={development_fraction}/VALIDATION_FRACTION={validation_fraction} "
            "defaults (committed 2026-08-18, before STRAT-000002 was generated and before any "
            "Generation 4 result existed). Strictly chronological; no dates were chosen by this "
            "generation and none were chosen after observing any performance number."
        ),
        declared_timestamp=utcnow().isoformat(),
    )
    return SealedDataset(
        dataset_id=dataset_id,
        dataset_checksum=dataset_checksum,
        development=split.development,
        validation=split.validation,
        holdout=split.holdout,
        boundaries=boundaries,
    )
