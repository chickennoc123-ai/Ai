"""Data source registry — Generation 1 Phase 1 (Data Factory).

Per ``ML-001-DATA-FACTORY-SPEC.md`` §2: a durable, file-backed catalog of
*where* market data can legitimately come from, independent of any
specific downloaded file (``core.factory.dataset_registry`` catalogs the
files themselves). A source record never asserts more about its own
legal/licensing standing than has actually been verified — ``UNKNOWN`` is
a first-class, honest value, not a placeholder to be silently upgraded.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.exceptions import EAFactoryError

DEFAULT_DATA_SOURCE_REGISTRY_PATH = Path("reports/factory/data_source_registry.json")

#: License standing this project has actually verified for a source.
#: UNKNOWN is the mandatory starting point -- nothing in this module ever
#: infers VERIFIED_* from a source merely existing or being reachable.
LICENSE_STATUSES = frozenset(
    {
        "UNKNOWN",
        "VERIFIED_PERMISSIVE",  # e.g. explicit open license confirmed
        "VERIFIED_RESTRICTED",  # a license exists and has been read; it restricts use
        "VERIFIED_PROPRIETARY_LICENSED",  # a paid/contractual license has been confirmed
        "DISPUTED",  # conflicting or unclear signals found, flagged rather than guessed
    }
)

ACCESS_METHODS = frozenset({"HTTP_DOWNLOAD", "API", "MANUAL_UPLOAD", "VENDOR_FEED", "OTHER"})

PROVENANCE_CONFIDENCE_LEVELS = frozenset(
    {
        "UNVERIFIED",  # source's own claims only, nothing independently checked
        "PARTIALLY_VERIFIED",  # at least one independent check performed (e.g. a known historical event)
        "INDEPENDENTLY_VERIFIED",  # multiple independent checks, or a primary-source cross-reference
    }
)


class DataSourceSpecError(EAFactoryError):
    """Raised when a DataSourceRecord is incomplete or asserts an unverified status."""


class DataSourceNotFoundError(EAFactoryError):
    pass


class DuplicateDataSourceError(EAFactoryError):
    pass


class DataSourceRegistryCorruptionError(EAFactoryError):
    pass


@dataclass(frozen=True)
class DataSourceRecord:
    """One place market data can be obtained from.

    ``license_status`` and ``provenance_confidence`` default to the most
    conservative honest value (``UNKNOWN`` / ``UNVERIFIED``) rather than a
    permissive one — a caller must actively assert a stronger value, and
    that assertion is on record as a specific claim, not an assumption
    baked into a default.
    """

    source_id: str
    provider: str
    source_url: str
    access_method: str
    coverage: str
    supported_instruments: Tuple[str, ...]
    supported_timeframes: Tuple[str, ...]
    timezone_semantics: str
    price_type: str
    availability: str
    license_status: str = "UNKNOWN"
    provenance_confidence: str = "UNVERIFIED"
    notes: str = ""

    def __post_init__(self) -> None:
        required = ("source_id", "provider", "source_url", "access_method", "timezone_semantics", "price_type")
        missing = [f for f in required if not getattr(self, f) or not str(getattr(self, f)).strip()]
        if missing:
            raise DataSourceSpecError("data source record is incomplete", missing_fields=missing)
        if self.access_method not in ACCESS_METHODS:
            raise DataSourceSpecError(
                "unknown access_method", access_method=self.access_method, allowed=sorted(ACCESS_METHODS)
            )
        if self.license_status not in LICENSE_STATUSES:
            raise DataSourceSpecError(
                "unknown license_status", license_status=self.license_status, allowed=sorted(LICENSE_STATUSES)
            )
        if self.provenance_confidence not in PROVENANCE_CONFIDENCE_LEVELS:
            raise DataSourceSpecError(
                "unknown provenance_confidence",
                provenance_confidence=self.provenance_confidence,
                allowed=sorted(PROVENANCE_CONFIDENCE_LEVELS),
            )
        if not self.supported_instruments:
            raise DataSourceSpecError("supported_instruments must not be empty")
        if not self.supported_timeframes:
            raise DataSourceSpecError("supported_timeframes must not be empty")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["supported_instruments"] = list(self.supported_instruments)
        d["supported_timeframes"] = list(self.supported_timeframes)
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DataSourceRecord":
        d = dict(d)
        d["supported_instruments"] = tuple(d.get("supported_instruments", ()))
        d["supported_timeframes"] = tuple(d.get("supported_timeframes", ()))
        return DataSourceRecord(**d)


class DataSourceRegistry:
    def __init__(self, path: Path = DEFAULT_DATA_SOURCE_REGISTRY_PATH) -> None:
        self.path = Path(path)
        self._sources: Dict[str, DataSourceRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise DataSourceRegistryCorruptionError(
                "data source registry file is not valid JSON; refusing to load", path=str(self.path)
            ) from exc
        self._sources = {sid: DataSourceRecord.from_dict(sdata) for sid, sdata in raw.get("sources", {}).items()}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"sources": {sid: s.to_dict() for sid, s in self._sources.items()}}
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def register(self, record: DataSourceRecord) -> DataSourceRecord:
        if record.source_id in self._sources:
            raise DuplicateDataSourceError("source_id already registered", source_id=record.source_id)
        self._sources[record.source_id] = record
        self._save()
        return record

    def get(self, source_id: str) -> DataSourceRecord:
        try:
            return self._sources[source_id]
        except KeyError as exc:
            raise DataSourceNotFoundError("no such source", source_id=source_id) from exc

    def list_all(self) -> List[DataSourceRecord]:
        return list(self._sources.values())
