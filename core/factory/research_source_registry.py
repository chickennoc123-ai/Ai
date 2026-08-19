"""Research Source Registry — Generation 2, Phase 1-2.

Per ``ML-001-RESEARCH-SOURCE-SPEC.md``: the entry point of the research
pipeline (``SOURCE -> CLAIM -> HYPOTHESIS -> ... -> CANDIDATE``). A source
is raw research material — a paper, a book, a website, a video, an
observation. **A source is never evidence of an edge, by itself, no
matter its type or how it is worded.** This registry only catalogs where
material came from; ``core.factory.claim_registry`` extracts claims from
it, and only a real, tested ``StrategyCandidate`` (``core.factory.
registry``) can ever produce economic evidence.

This is a separate module from the lighter-weight ``core.factory.
hypothesis.HypothesisRegistry`` (Generation 1) — that module remains
untouched and still valid for its own purpose (capturing a raw external
claim directly, with a lightweight evidence-level track). This module is
the richer, source-first entry point Generation 2 requires, with its own
stable identity and a proper claim-extraction layer downstream
(``core.factory.claim_registry``).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

DEFAULT_SOURCE_REGISTRY_PATH = Path("reports/factory/research_source_registry.json")

#: Fixed today, but the architecture is not closed: SOURCE_TYPES is a
#: frozenset, not a hard-coded enum baked into a schema migration -- a
#: future source type can be added to this set without invalidating any
#: existing SourceRecord, since old records keep whatever value they were
#: given and this set is only consulted at construction/registration time.
SOURCE_TYPES = frozenset(
    {
        "ACADEMIC_PAPER",
        "WORKING_PAPER",
        "BOOK",
        "TEXTBOOK",
        "RESEARCH_REPORT",
        "WEBSITE",
        "YOUTUBE",
        "PUBLIC_STRATEGY",
        "OPEN_SOURCE_CODE",
        "HUMAN_HYPOTHESIS",
        "AI_GENERATED_HYPOTHESIS",
        "MARKET_OBSERVATION",
        "MACRO_DATA_SOURCE",
        "ALTERNATIVE_DATA_SOURCE",
    }
)

LICENSE_STATUSES = frozenset({"UNKNOWN", "PUBLIC_DOMAIN", "PERMISSIVE", "RESTRICTED", "PROPRIETARY", "DISPUTED"})
PROVENANCE_STATUSES = frozenset({"UNVERIFIED", "PARTIALLY_VERIFIED", "VERIFIED"})
VERIFICATION_STATUSES = frozenset({"UNVERIFIED", "SPOT_CHECKED", "INDEPENDENTLY_VERIFIED"})


class SourceSpecError(EAFactoryError):
    """Raised when a SourceRecord is incomplete or asserts an unrecognized status."""


class SourceNotFoundError(EAFactoryError):
    pass


class DuplicateSourceError(EAFactoryError):
    pass


class SourceRegistryCorruptionError(EAFactoryError):
    pass


@dataclass(frozen=True)
class SourceRecord:
    """One piece of research material. ``UNKNOWN`` is a valid, honest
    value for any field this project has not actually established —
    never guessed, never silently upgraded to something stronger."""

    source_id: str
    source_type: str
    title: str
    retrieval_timestamp: str
    source_version: int = 1
    author: str = "UNKNOWN"
    publisher: str = "UNKNOWN"
    source_url: str = "UNKNOWN"
    content_checksum: str = "UNKNOWN"
    publication_timestamp: str = "UNKNOWN"
    license_status: str = "UNKNOWN"
    provenance_status: str = "UNVERIFIED"
    verification_status: str = "UNVERIFIED"
    notes: str = ""
    #: Set only when this record supersedes an earlier version of the
    #: same source (Phase 2: "create a new source version if content
    #: materially changes" -- never overwrite the old one).
    supersedes_source_id: Optional[str] = None

    def __post_init__(self) -> None:
        required = ("source_id", "title", "retrieval_timestamp")
        missing = [f for f in required if not getattr(self, f) or not str(getattr(self, f)).strip()]
        if missing:
            raise SourceSpecError("source record is incomplete", missing_fields=missing)
        if self.source_type not in SOURCE_TYPES:
            raise SourceSpecError("unknown source_type", source_type=self.source_type, allowed=sorted(SOURCE_TYPES))
        if self.license_status not in LICENSE_STATUSES:
            raise SourceSpecError(
                "unknown license_status", license_status=self.license_status, allowed=sorted(LICENSE_STATUSES)
            )
        if self.provenance_status not in PROVENANCE_STATUSES:
            raise SourceSpecError(
                "unknown provenance_status", provenance_status=self.provenance_status, allowed=sorted(PROVENANCE_STATUSES)
            )
        if self.verification_status not in VERIFICATION_STATUSES:
            raise SourceSpecError(
                "unknown verification_status", verification_status=self.verification_status,
                allowed=sorted(VERIFICATION_STATUSES),
            )
        if self.source_version < 1:
            raise SourceSpecError("source_version must be >= 1", source_id=self.source_id)

    def identity_checksum(self) -> str:
        """Deterministic identity over the fields that define WHAT this
        source is (not when it was catalogued) -- used by
        ``ResearchSourceRegistry.find_duplicate`` (Phase 13)."""
        data = {"source_type": self.source_type, "title": self.title, "author": self.author,
                "source_url": self.source_url, "publisher": self.publisher}
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SourceRecord":
        return SourceRecord(**d)


class ResearchSourceRegistry:
    def __init__(self, path: Path = DEFAULT_SOURCE_REGISTRY_PATH) -> None:
        self.path = Path(path)
        self._next_id = 1
        self._sources: Dict[str, SourceRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise SourceRegistryCorruptionError(
                "research source registry file is not valid JSON; refusing to load", path=str(self.path)
            ) from exc
        self._next_id = raw.get("next_id", 1)
        self._sources = {sid: SourceRecord.from_dict(sdata) for sid, sdata in raw.get("sources", {}).items()}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"next_id": self._next_id, "sources": {sid: s.to_dict() for sid, s in self._sources.items()}}
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def allocate_source_id(self) -> str:
        sid = f"SRC2-{self._next_id:06d}"
        self._next_id += 1
        self._save()
        return sid

    def register(self, record: SourceRecord) -> SourceRecord:
        if record.source_id in self._sources:
            raise DuplicateSourceError("source_id already registered", source_id=record.source_id)
        self._sources[record.source_id] = record
        self._save()
        return record

    def get(self, source_id: str) -> SourceRecord:
        try:
            return self._sources[source_id]
        except KeyError as exc:
            raise SourceNotFoundError("no such source", source_id=source_id) from exc

    def list_all(self) -> List[SourceRecord]:
        return list(self._sources.values())

    def find_duplicate(self, candidate: SourceRecord) -> Optional[SourceRecord]:
        """Deterministic dedup (Phase 13): a source is a duplicate of an
        existing one only if its identity_checksum matches exactly (same
        type/title/author/url/publisher) -- never a fuzzy/similarity
        match, which could incorrectly merge genuinely different sources.
        Ignores ``candidate.source_id`` itself (not yet registered) and
        any record that is a different *version* chain member is still
        correctly flagged, since materially-changed content changes the
        checksum by design."""
        target = candidate.identity_checksum()
        for existing in self._sources.values():
            if existing.identity_checksum() == target:
                return existing
        return None

    def new_version(self, previous_source_id: str, **field_overrides: Any) -> SourceRecord:
        """Register a new version of an existing source (Phase 2: "never
        silently overwrite an existing source version"). The previous
        record is left completely untouched."""
        previous = self.get(previous_source_id)
        data = previous.to_dict()
        data.update(field_overrides)
        data["source_id"] = self.allocate_source_id()
        data["source_version"] = previous.source_version + 1
        data["supersedes_source_id"] = previous_source_id
        data["retrieval_timestamp"] = field_overrides.get("retrieval_timestamp", utcnow().isoformat())
        new_record = SourceRecord.from_dict(data)
        return self.register(new_record)
