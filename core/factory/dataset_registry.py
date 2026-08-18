"""Dataset registry — Generation 1 Phase 1 (Data Factory).

Per ``ML-001-DATA-FACTORY-SPEC.md`` §3-§4: a durable catalog giving every
downloaded/normalized market-data file a stable, checkable identity —
distinct from ``core.dataset_provenance``'s ``ProvenanceGuard`` (which
governs *runtime access* to an already-loaded DEVELOPMENT/VALIDATION/
PURE_HOLDOUT partition) and from ``core.provenance_enforcement`` (the
same kind of runtime access guard, older/simpler). Neither of those
answers "does this on-disk CSV have verified real-market provenance, and
exactly what does its checksum/coverage/gap profile look like" — that is
this module's job, upstream of both.

**Hard rule, enforced in code, not just documentation**: ``synthetic`` and
``provenance_status`` are never inferred. A caller must assert them
explicitly; the most permissive values (``synthetic=False``,
``provenance_status="VERIFIED"``) are never the default, and a dataset
with ``provenance_status`` other than ``VERIFIED``/``VERIFIED_WITH_
QUALIFICATION`` cannot be marked ``real_market_data_eligible`` (see
``DatasetRecord.is_real_market_data_eligible``).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from utils.exceptions import EAFactoryError

DEFAULT_DATASET_REGISTRY_PATH = Path("reports/factory/dataset_registry.json")

#: Never inferred from "the data looks realistic" -- only ever set by an
#: explicit caller assertion backed by actual acquisition evidence (a
#: recorded source URL + download method + checksum, at minimum).
PROVENANCE_STATUSES = frozenset(
    {
        "UNVERIFIED",  # cannot yet be used as real-market evidence
        "VERIFIED",  # provenance independently confirmed (see DatasetRecord.verification_method)
        "VERIFIED_WITH_QUALIFICATION",  # verified, but with a disclosed assumption/gap (e.g. timezone)
        "KNOWN_SYNTHETIC",  # explicitly test-only synthetic data, never eligible for economic evidence
    }
)

INTEGRITY_STATUSES = frozenset({"PASS", "FAIL", "PARTIAL", "NOT_YET_CHECKED"})


class DatasetSpecError(EAFactoryError):
    """Raised when a DatasetRecord is incomplete or self-contradictory."""


class DatasetNotFoundError(EAFactoryError):
    pass


class DuplicateDatasetError(EAFactoryError):
    pass


class DatasetRegistryCorruptionError(EAFactoryError):
    pass


class RealMarketDataEligibilityError(EAFactoryError):
    """Raised when code attempts to treat a non-eligible dataset as real-market evidence."""


def compute_file_checksum(path: Path) -> str:
    """SHA-256 of the raw file bytes on disk — the same style of check
    already used for model artifacts (``core.ml_r2.model_r2._checksum_
    bytes``) and for this project's real EURUSD/GBPUSD CSVs
    (``data/csv/PROVENANCE_MANIFEST.json``)."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


@dataclass(frozen=True)
class DatasetRecord:
    """One catalogued dataset file's complete provenance + integrity metadata."""

    dataset_id: str
    instrument: str
    timeframe: str
    source_id: str
    source_url: str
    download_timestamp: str
    timezone: str
    price_type: str
    coverage_start: str
    coverage_end: str
    row_count: int
    duplicate_count: int
    missing_bar_count: int
    gap_report: Dict[str, Any]
    checksum: str
    file_checksum: str
    download_method: str
    synthetic: bool
    provenance_status: str
    integrity_status: str
    dataset_version: str = "v1"
    verification_method: str = ""

    def __post_init__(self) -> None:
        required = (
            "dataset_id",
            "instrument",
            "timeframe",
            "source_id",
            "source_url",
            "download_timestamp",
            "timezone",
            "price_type",
            "coverage_start",
            "coverage_end",
            "checksum",
            "file_checksum",
            "download_method",
        )
        missing = [f for f in required if not getattr(self, f) or not str(getattr(self, f)).strip()]
        if missing:
            raise DatasetSpecError("dataset record is incomplete", missing_fields=missing)
        if self.provenance_status not in PROVENANCE_STATUSES:
            raise DatasetSpecError(
                "unknown provenance_status", provenance_status=self.provenance_status, allowed=sorted(PROVENANCE_STATUSES)
            )
        if self.integrity_status not in INTEGRITY_STATUSES:
            raise DatasetSpecError(
                "unknown integrity_status", integrity_status=self.integrity_status, allowed=sorted(INTEGRITY_STATUSES)
            )
        if self.row_count < 0 or self.duplicate_count < 0 or self.missing_bar_count < 0:
            raise DatasetSpecError("row_count/duplicate_count/missing_bar_count must be non-negative")
        if self.synthetic and self.provenance_status not in ("KNOWN_SYNTHETIC",):
            raise DatasetSpecError(
                "synthetic=True requires provenance_status='KNOWN_SYNTHETIC' -- a synthetic "
                "dataset can never simultaneously claim VERIFIED/VERIFIED_WITH_QUALIFICATION "
                "real-market provenance",
                dataset_id=self.dataset_id,
            )
        if self.provenance_status == "KNOWN_SYNTHETIC" and not self.synthetic:
            raise DatasetSpecError(
                "provenance_status='KNOWN_SYNTHETIC' requires synthetic=True", dataset_id=self.dataset_id
            )
        if self.provenance_status in ("VERIFIED", "VERIFIED_WITH_QUALIFICATION") and not self.verification_method:
            raise DatasetSpecError(
                "provenance_status VERIFIED/VERIFIED_WITH_QUALIFICATION requires a non-empty "
                "verification_method describing how it was independently confirmed -- a bare "
                "assertion is not sufficient",
                dataset_id=self.dataset_id,
            )

    @property
    def is_real_market_data_eligible(self) -> bool:
        """True only if this dataset may be used as REAL_MARKET_DATA
        evidence in the economic validation pipeline. Synthetic data, or
        data whose provenance has not actually been verified, is never
        eligible regardless of how realistic it looks or how the caller
        might wish to use it."""
        return (
            not self.synthetic
            and self.provenance_status in ("VERIFIED", "VERIFIED_WITH_QUALIFICATION")
            and self.integrity_status == "PASS"
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DatasetRecord":
        return DatasetRecord(**d)


def assert_real_market_data_eligible(record: DatasetRecord) -> None:
    """Raise ``RealMarketDataEligibilityError`` unless ``record`` may be
    used as real-market economic evidence. Call this at the boundary of
    any script that is about to train/evaluate against a dataset and
    claim ``REAL_MARKET_DATA = TRUE`` — never assume eligibility from a
    dataset merely existing in the registry."""
    if not record.is_real_market_data_eligible:
        raise RealMarketDataEligibilityError(
            "dataset is not eligible for real-market economic evidence",
            dataset_id=record.dataset_id,
            synthetic=record.synthetic,
            provenance_status=record.provenance_status,
            integrity_status=record.integrity_status,
        )


class DatasetRegistry:
    def __init__(self, path: Path = DEFAULT_DATASET_REGISTRY_PATH) -> None:
        self.path = Path(path)
        self._datasets: Dict[str, DatasetRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise DatasetRegistryCorruptionError(
                "dataset registry file is not valid JSON; refusing to load", path=str(self.path)
            ) from exc
        self._datasets = {did: DatasetRecord.from_dict(ddata) for did, ddata in raw.get("datasets", {}).items()}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"datasets": {did: d.to_dict() for did, d in self._datasets.items()}}
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def register(self, record: DatasetRecord) -> DatasetRecord:
        if record.dataset_id in self._datasets:
            raise DuplicateDatasetError("dataset_id already registered", dataset_id=record.dataset_id)
        self._datasets[record.dataset_id] = record
        self._save()
        return record

    def get(self, dataset_id: str) -> DatasetRecord:
        try:
            return self._datasets[dataset_id]
        except KeyError as exc:
            raise DatasetNotFoundError("no such dataset", dataset_id=dataset_id) from exc

    def list_all(self) -> List[DatasetRecord]:
        return list(self._datasets.values())

    def list_by_instrument(self, instrument: str) -> List[DatasetRecord]:
        return [d for d in self._datasets.values() if d.instrument == instrument]

    def verify_file_checksum(self, dataset_id: str, file_path: Path) -> bool:
        """Recompute the on-disk file's checksum and compare it against
        the registered ``file_checksum`` — the core "was this file
        altered since it was catalogued" check. Returns False rather than
        raising, so a caller can decide how to react (this module does
        not assume every mismatch is fatal to every caller, though most
        callers should treat it as one)."""
        record = self.get(dataset_id)
        return compute_file_checksum(file_path) == record.file_checksum
