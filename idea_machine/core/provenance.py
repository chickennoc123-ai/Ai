"""Provenance — where a thing came from, and how far you may trust it.

Roadmap Phase 1 is explicit: *"Website bên ngoài chỉ là nguồn ý tưởng, không
phải nguồn sự thật cuối cùng"* — an external site is a source of ideas, never
a source of final truth. This module encodes that as a type, not a convention:
every record the Idea Machine creates carries a :class:`Provenance` naming its
origin, and :attr:`Provenance.authority` can never rise above
``IDEA_SOURCE_ONLY`` for anything that came off the internet.

Only the Strategy Factory can produce ``VALIDATED_EVIDENCE``; the Idea Machine
has no code path that constructs it, and :func:`Provenance.derive` refuses to
raise the authority of a child above its parents.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Sequence, Tuple

from idea_machine.core.errors import ProvenanceError
from idea_machine.core.ids import content_hash

#: Display order, weakest -> strongest. The Idea Machine may mint the first three.
AUTHORITY_LEVELS: Tuple[str, ...] = (
    "IDEA_SOURCE_ONLY",      # a claim seen somewhere; unverified by us
    "DERIVED_HYPOTHESIS",    # our own reasoning over IDEA_SOURCE_ONLY material
    "INTERNAL_OBSERVATION",  # computed from data we hold, still untested
    "VALIDATED_EVIDENCE",    # ONLY the Strategy Factory may assert this
)

#: Evidential *rank*, which is not the same as display order. Reasoning over a
#: claim does not make the claim better evidence, so DERIVED_HYPOTHESIS sits at
#: the same rank as IDEA_SOURCE_ONLY rather than above it. This is what stops
#: the machine from laundering an unverified blog post into something stronger
#: by thinking about it: the only way rank rises is by touching real data
#: (INTERNAL_OBSERVATION) or by passing the Factory (VALIDATED_EVIDENCE).
_AUTHORITY_RANK = {
    "IDEA_SOURCE_ONLY": 0,
    "DERIVED_HYPOTHESIS": 0,
    "INTERNAL_OBSERVATION": 1,
    "VALIDATED_EVIDENCE": 2,
}

#: The authority level the Idea Machine is structurally forbidden from minting.
FACTORY_ONLY_AUTHORITY = "VALIDATED_EVIDENCE"

ORIGIN_KINDS = frozenset(
    {
        "ACADEMIC_PAPER",
        "WORKING_PAPER",
        "RESEARCH_REPORT",
        "MACRO_RESEARCH",
        "MARKET_STUDY",
        "PUBLIC_DATASET",
        "WEBSITE",
        "FORECASTER_STYLE_SOURCE",
        "BOOK",
        "MARKET_OBSERVATION",
        "INTERNAL_DERIVATION",
        "COMBINATION",
        "FACTORY_RESULT",
        "HUMAN_INPUT",
    }
)


@dataclass(frozen=True)
class Provenance:
    """An immutable statement of origin."""

    origin_kind: str
    origin_ref: str          # URL, DOI, dataset id, observation id, "human:<who>"
    retrieved_at: str        # ISO-8601 UTC; when we saw it, not when it was written
    content_hash: str        # hash of the retrieved content, for reproducibility
    authority: str = "IDEA_SOURCE_ONLY"
    parents: Tuple[str, ...] = field(default_factory=tuple)
    note: str = ""

    def __post_init__(self) -> None:
        if self.origin_kind not in ORIGIN_KINDS:
            raise ProvenanceError(
                "unknown origin_kind", origin_kind=self.origin_kind, allowed=sorted(ORIGIN_KINDS)
            )
        if self.authority not in _AUTHORITY_RANK:
            raise ProvenanceError("unknown authority level", authority=self.authority)
        if self.authority == FACTORY_ONLY_AUTHORITY and self.origin_kind != "FACTORY_RESULT":
            raise ProvenanceError(
                "VALIDATED_EVIDENCE may only be attached to a FACTORY_RESULT -- the Idea "
                "Machine cannot promote its own material to validated evidence",
                origin_kind=self.origin_kind,
            )
        for name in ("origin_ref", "retrieved_at", "content_hash"):
            if not str(getattr(self, name)).strip():
                raise ProvenanceError(f"provenance field '{name}' is required")

    @property
    def rank(self) -> int:
        return _AUTHORITY_RANK[self.authority]

    def derive(
        self,
        *,
        origin_kind: str,
        origin_ref: str,
        retrieved_at: str,
        content_hash_: str,
        authority: str = "DERIVED_HYPOTHESIS",
        note: str = "",
        extra_parents: Sequence["Provenance"] = (),
    ) -> "Provenance":
        """Create a child provenance that can never out-rank its parents."""
        parents = [self, *extra_parents]
        ceiling = min(p.rank for p in parents)
        if _AUTHORITY_RANK[authority] > ceiling:
            raise ProvenanceError(
                "a derived record cannot claim more authority than its weakest parent",
                requested=authority,
                requested_rank=_AUTHORITY_RANK[authority],
                parent_ceiling_rank=ceiling,
            )
        return Provenance(
            origin_kind=origin_kind,
            origin_ref=origin_ref,
            retrieved_at=retrieved_at,
            content_hash=content_hash_,
            authority=authority,
            parents=tuple(p.identity() for p in parents),
            note=note,
        )

    def identity(self) -> str:
        return content_hash(asdict(self))

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["parents"] = list(self.parents)
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Provenance":
        return Provenance(
            origin_kind=d["origin_kind"],
            origin_ref=d["origin_ref"],
            retrieved_at=d["retrieved_at"],
            content_hash=d["content_hash"],
            authority=d.get("authority", "IDEA_SOURCE_ONLY"),
            parents=tuple(d.get("parents", ())),
            note=d.get("note", ""),
        )


def combine(*provenances: Provenance, retrieved_at: str, note: str = "") -> Provenance:
    """Merge several provenances into one COMBINATION record.

    Used by the Combination Engine (Phase 4), which must preserve *all* parent
    lineage rather than picking a representative parent.
    """
    if len(provenances) < 2:
        raise ProvenanceError("a combination needs at least two parents", count=len(provenances))
    # A combination of ideas is always a derived hypothesis: rank 0, so it can
    # never out-rank any parent regardless of what the parents were.
    authority = "DERIVED_HYPOTHESIS"
    refs = sorted(p.identity() for p in provenances)
    return Provenance(
        origin_kind="COMBINATION",
        origin_ref="combination:" + content_hash(refs)[:16],
        retrieved_at=retrieved_at,
        content_hash=content_hash(refs),
        authority=authority,
        parents=tuple(refs),
        note=note,
    )
