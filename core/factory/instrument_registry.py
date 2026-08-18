"""Instrument registry + timeframe registry + research scope — Generation 1
Phase 2 (Market Universe).

Per ``ML-001-MARKET-UNIVERSE-SPEC.md`` §2-§5: makes "which instrument, on
which timeframe, tested how broadly" an explicit, structured fact rather
than an implicit assumption a strategy carries around informally. Nothing
here fabricates metadata for an instrument this project has not actually
used — unknown fields are recorded as ``"UNKNOWN"``, never guessed.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.exceptions import EAFactoryError

DEFAULT_INSTRUMENT_REGISTRY_PATH = Path("reports/factory/instrument_registry.json")

#: Fixed timeframe enumeration this architecture can represent. Listing a
#: timeframe here does NOT assert data exists for it -- that is a
#: dataset-registry-level fact (core.factory.dataset_registry), checked
#: separately, never implied by mere membership in this tuple.
SUPPORTED_TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")

#: How broadly a candidate's evaluation is declared to apply, decided
#: BEFORE evaluation begins (ML-001-MARKET-UNIVERSE-SPEC.md §4) -- a
#: strategy tested on one instrument is never silently treated as having
#: validated a family or the whole universe.
RESEARCH_SCOPES = frozenset({"SINGLE_INSTRUMENT", "INSTRUMENT_FAMILY", "MULTI_INSTRUMENT"})

INSTRUMENT_STATUSES = frozenset({"ACTIVE", "CANDIDATE", "UNSUPPORTED", "RETIRED"})

UNKNOWN = "UNKNOWN"


class InstrumentSpecError(EAFactoryError):
    """Raised when an InstrumentRecord is incomplete or invalid."""


class InstrumentNotFoundError(EAFactoryError):
    pass


class DuplicateInstrumentError(EAFactoryError):
    pass


class InstrumentRegistryCorruptionError(EAFactoryError):
    pass


class UnsupportedTimeframeError(EAFactoryError):
    """Raised when a timeframe outside SUPPORTED_TIMEFRAMES is used where
    architecture support is required."""


def is_supported_timeframe(timeframe: str) -> bool:
    return timeframe in SUPPORTED_TIMEFRAMES


def assert_supported_timeframe(timeframe: str) -> None:
    if not is_supported_timeframe(timeframe):
        raise UnsupportedTimeframeError(
            "timeframe is not in the supported architecture enumeration",
            timeframe=timeframe,
            supported=list(SUPPORTED_TIMEFRAMES),
        )


def assert_valid_research_scope(scope: str) -> None:
    if scope not in RESEARCH_SCOPES:
        raise InstrumentSpecError("unknown research_scope", research_scope=scope, allowed=sorted(RESEARCH_SCOPES))


@dataclass(frozen=True)
class InstrumentRecord:
    """One tradeable instrument's metadata. Every field defaults to the
    honest literal string ``"UNKNOWN"`` where this project has not
    actually established the real value — never a guessed number, never a
    plausible-looking placeholder."""

    instrument_id: str
    symbol: str
    asset_class: str
    venue_provider: str = UNKNOWN
    quote_currency: str = UNKNOWN
    timezone_session_semantics: str = UNKNOWN
    tick_size: str = UNKNOWN
    price_precision: str = UNKNOWN
    contract_metadata: Dict[str, Any] = field(default_factory=dict)
    data_availability: str = UNKNOWN
    cost_model_reference: str = UNKNOWN
    status: str = "CANDIDATE"

    def __post_init__(self) -> None:
        required = ("instrument_id", "symbol", "asset_class")
        missing = [f for f in required if not getattr(self, f) or not str(getattr(self, f)).strip()]
        if missing:
            raise InstrumentSpecError("instrument record is incomplete", missing_fields=missing)
        if self.status not in INSTRUMENT_STATUSES:
            raise InstrumentSpecError("unknown status", status=self.status, allowed=sorted(INSTRUMENT_STATUSES))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "InstrumentRecord":
        return InstrumentRecord(**d)


class InstrumentRegistry:
    def __init__(self, path: Path = DEFAULT_INSTRUMENT_REGISTRY_PATH) -> None:
        self.path = Path(path)
        self._instruments: Dict[str, InstrumentRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise InstrumentRegistryCorruptionError(
                "instrument registry file is not valid JSON; refusing to load", path=str(self.path)
            ) from exc
        self._instruments = {
            iid: InstrumentRecord.from_dict(idata) for iid, idata in raw.get("instruments", {}).items()
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"instruments": {iid: i.to_dict() for iid, i in self._instruments.items()}}
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def register(self, record: InstrumentRecord) -> InstrumentRecord:
        if record.instrument_id in self._instruments:
            raise DuplicateInstrumentError("instrument_id already registered", instrument_id=record.instrument_id)
        self._instruments[record.instrument_id] = record
        self._save()
        return record

    def get(self, instrument_id: str) -> InstrumentRecord:
        try:
            return self._instruments[instrument_id]
        except KeyError as exc:
            raise InstrumentNotFoundError("no such instrument", instrument_id=instrument_id) from exc

    def get_by_symbol(self, symbol: str) -> InstrumentRecord:
        for i in self._instruments.values():
            if i.symbol == symbol:
                return i
        raise InstrumentNotFoundError("no instrument registered for symbol", symbol=symbol)

    def list_all(self) -> List[InstrumentRecord]:
        return list(self._instruments.values())


def assert_dataset_matches_instrument(dataset_symbol: str, dataset_timeframe: str, instrument: InstrumentRecord) -> None:
    """The core anti-substitution check (ML-001-MARKET-UNIVERSE-SPEC.md
    §3): a dataset may only be used for the instrument it actually
    belongs to. Raises ``InstrumentSpecError`` on any mismatch — this is
    the check a training/evaluation script must call before wiring a
    dataset to an instrument-scoped candidate, so a EURUSD dataset can
    never be silently fed to a GBPUSD-labeled evaluation."""
    if dataset_symbol != instrument.symbol:
        raise InstrumentSpecError(
            "dataset instrument does not match the declared instrument -- refusing silent substitution",
            dataset_symbol=dataset_symbol,
            instrument_symbol=instrument.symbol,
        )
