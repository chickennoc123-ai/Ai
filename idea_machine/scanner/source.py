"""Source records — the raw material the scanner brings back (Phase 1).

A :class:`SourceRecord` is a *snapshot of something we read*, not a fact. It
stores the four things needed to make the reading reproducible and auditable —
``source``, ``timestamp``, ``content_hash``, ``provenance`` — plus the concepts
extracted from it.

The content hash is over the retrieved text, so re-scanning an unchanged page
produces the same record id and the knowledge base does not double-count it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, Tuple

from idea_machine.core.errors import SpecValidationError
from idea_machine.core.ids import content_hash, mint_id
from idea_machine.core.provenance import ORIGIN_KINDS, Provenance

#: The source classes Phase 1 asks the scanner to cover.
SOURCE_DOMAINS = frozenset(
    {
        "ACADEMIC",
        "FINANCIAL_RESEARCH",
        "MACRO_RESEARCH",
        "MARKET_STUDY",
        "ECONOMIC_ANOMALY",
        "SEASONALITY",
        "EVENT_EFFECT",
        "CROSS_ASSET",
        "VOLATILITY_RESEARCH",
        "POSITIONING",
        "MICROSTRUCTURE",
        "PUBLIC_DATASET",
        "FORECASTER_STYLE",
    }
)


@dataclass(frozen=True)
class SourceRecord:
    """One retrieved document, with everything needed to re-find it."""

    domain: str
    source: str            # human-readable name of the source
    origin_kind: str       # maps onto Provenance.ORIGIN_KINDS
    reference: str         # URL / DOI / dataset id
    title: str
    retrieved_at: str
    raw_content_hash: str
    summary: str = ""
    concepts: Tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_id: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if self.domain not in SOURCE_DOMAINS:
            raise SpecValidationError("unknown source domain", domain=self.domain, allowed=sorted(SOURCE_DOMAINS))
        if self.origin_kind not in ORIGIN_KINDS:
            raise SpecValidationError("unknown origin_kind", origin_kind=self.origin_kind)
        for name in ("source", "reference", "title", "retrieved_at", "raw_content_hash"):
            if not str(getattr(self, name)).strip():
                raise SpecValidationError(f"SourceRecord.{name} is required")
        object.__setattr__(self, "concepts", tuple(sorted(set(self.concepts))))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if not self.source_id:
            object.__setattr__(
                self,
                "source_id",
                mint_id("SRC", {"ref": self.reference.strip().lower(), "hash": self.raw_content_hash}),
            )

    def provenance(self) -> Provenance:
        """An IDEA_SOURCE_ONLY provenance — never more than that.

        Phase 1 is explicit that an external site is a source of ideas and not
        a source of truth, so this method has no parameter that could raise the
        authority level.
        """
        return Provenance(
            origin_kind=self.origin_kind,
            origin_ref=self.reference,
            retrieved_at=self.retrieved_at,
            content_hash=self.raw_content_hash,
            authority="IDEA_SOURCE_ONLY",
            note=f"{self.source}: {self.title}",
        )

    def checksum(self) -> str:
        return content_hash(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["concepts"] = list(self.concepts)
        d["metadata"] = dict(self.metadata)
        return d

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "SourceRecord":
        return SourceRecord(
            domain=d["domain"],
            source=d["source"],
            origin_kind=d["origin_kind"],
            reference=d["reference"],
            title=d["title"],
            retrieved_at=d["retrieved_at"],
            raw_content_hash=d["raw_content_hash"],
            summary=d.get("summary", ""),
            concepts=tuple(d.get("concepts", ())),
            metadata=dict(d.get("metadata", {})),
            source_id=d.get("source_id", ""),
        )
