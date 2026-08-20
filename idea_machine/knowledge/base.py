"""Knowledge Engine (Phase 2) — structured memory of what is actually known.

The knowledge base holds two kinds of node:

* **Concepts** — ``NFP``, ``US10Y``, ``GOLD``, ``VOLATILITY_REGIME`` — and the
  edges between them, each edge annotated with the sources that asserted it.
* **Findings** — statements about a (family, mechanism, horizon) region of
  search space, each carrying an :mod:`~idea_machine.core.epistemic` state.

The rule the whole module exists to enforce is that a finding's state can only
move along the legal transition table, so *"we haven't looked"* can never be
silently upgraded into *"there is an edge"*. In fact no state in the vocabulary
means "edge" at all; ``SURVIVED`` means "the Factory's tests did not refute
it", and the class refuses to store anything stronger.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from idea_machine.core import epistemic
from idea_machine.core.errors import KnowledgeError
from idea_machine.core.ids import mint_id
from idea_machine.core.store import DEFAULT_ROOT, AppendOnlyStore
from idea_machine.governance import guard
from idea_machine.scanner.source import SourceRecord
from utils.helpers import isoformat

DEFAULT_KNOWLEDGE_PATH = DEFAULT_ROOT / "knowledge_base.json"

#: How two concepts may relate. Kept small on purpose — a rich ontology invites
#: the machine to invent relationships it cannot support.
RELATIONS = frozenset(
    {
        "AFFECTS",         # A moves B
        "PRECEDES",        # A leads B in time
        "CONDITIONS",      # A changes the strength of another relation
        "CO_OCCURS",       # observed together, direction unclear
        "MEASURED_BY",     # A is observed through dataset/series B
    }
)


@dataclass(frozen=True)
class ConceptEdge:
    """An asserted relationship, with the sources that asserted it."""

    subject: str
    relation: str
    object: str
    source_ids: Tuple[str, ...]
    note: str = ""
    edge_id: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if self.relation not in RELATIONS:
            raise KnowledgeError("unknown relation", relation=self.relation, allowed=sorted(RELATIONS))
        if not self.source_ids:
            raise KnowledgeError(
                "a concept edge must name the source(s) that asserted it -- unattributed "
                "relationships are how unverified claims become assumed facts",
                subject=self.subject,
                object=self.object,
            )
        object.__setattr__(self, "source_ids", tuple(sorted(set(self.source_ids))))
        if not self.edge_id:
            object.__setattr__(
                self,
                "edge_id",
                mint_id("EDGE", {"s": self.subject, "r": self.relation, "o": self.object}),
            )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["source_ids"] = list(self.source_ids)
        return d

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "ConceptEdge":
        return ConceptEdge(
            subject=d["subject"],
            relation=d["relation"],
            object=d["object"],
            source_ids=tuple(d.get("source_ids", ())),
            note=d.get("note", ""),
            edge_id=d.get("edge_id", ""),
        )


@dataclass(frozen=True)
class Finding:
    """What is known about one region of search space."""

    family: str
    mechanism_signature: str
    horizon: str
    state: str
    statement: str
    evidence_refs: Tuple[str, ...] = field(default_factory=tuple)
    updated_at: str = ""
    finding_id: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        epistemic.validate_state(self.state)
        if not str(self.statement).strip():
            raise KnowledgeError("a finding must say something", family=self.family)
        object.__setattr__(self, "evidence_refs", tuple(sorted(set(self.evidence_refs))))
        if not self.finding_id:
            object.__setattr__(
                self,
                "finding_id",
                mint_id(
                    "FIND",
                    {"f": self.family, "m": self.mechanism_signature, "h": self.horizon},
                ),
            )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["evidence_refs"] = list(self.evidence_refs)
        return d

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "Finding":
        return Finding(
            family=d["family"],
            mechanism_signature=d["mechanism_signature"],
            horizon=d["horizon"],
            state=d["state"],
            statement=d["statement"],
            evidence_refs=tuple(d.get("evidence_refs", ())),
            updated_at=d.get("updated_at", ""),
            finding_id=d.get("finding_id", ""),
        )


class KnowledgeBase:
    """Append-only concept graph plus a state-machine-guarded finding index.

    Findings are versioned, not overwritten: every state change appends a new
    row carrying the previous state, so the history of what the machine
    believed — and when — is reconstructable. The "current" state of a finding
    is simply its most recent row.
    """

    def __init__(self, path: Path = DEFAULT_KNOWLEDGE_PATH, *, clock=isoformat) -> None:
        self.store = AppendOnlyStore(path, id_field="row_id", kind="knowledge")
        self._clock = clock

    # -------------------------------------------------------------- concepts

    def ingest_source(self, record: SourceRecord) -> Tuple[str, ...]:
        """Register the concepts a source mentioned. Returns concept names."""
        guard.require("UPDATE_KNOWLEDGE", source_id=record.source_id)
        rows = []
        for concept in record.concepts:
            rows.append(
                {
                    "row_id": mint_id("KROW", {"k": "concept", "c": concept, "s": record.source_id}),
                    "kind": "concept_mention",
                    "concept": concept,
                    "source_id": record.source_id,
                    "reference": record.reference,
                    "timestamp": record.retrieved_at,
                }
            )
        if rows:
            self.store.append_many(rows)
        return record.concepts

    def assert_edge(self, edge: ConceptEdge) -> ConceptEdge:
        """Record a relationship between two concepts."""
        guard.require("UPDATE_KNOWLEDGE", edge=edge.edge_id)
        existing = self._latest_edge(edge.edge_id)
        merged_sources = tuple(sorted(set(edge.source_ids) | set(existing.source_ids if existing else ())))
        merged = ConceptEdge(
            subject=edge.subject,
            relation=edge.relation,
            object=edge.object,
            source_ids=merged_sources,
            note=edge.note or (existing.note if existing else ""),
            edge_id=edge.edge_id,
        )
        timestamp = self._clock()
        self.store.append(
            {
                "row_id": mint_id(
                    "KROW", {"k": "edge", "e": edge.edge_id, "src": merged_sources, "t": timestamp}
                ),
                "kind": "concept_edge",
                "edge": merged.to_dict(),
                "timestamp": timestamp,
            }
        )
        return merged

    def _latest_edge(self, edge_id: str) -> Optional[ConceptEdge]:
        rows = [r for r in self.store.all() if r.get("kind") == "concept_edge" and r["edge"]["edge_id"] == edge_id]
        return ConceptEdge.from_dict(rows[-1]["edge"]) if rows else None

    def edges(self) -> Tuple[ConceptEdge, ...]:
        latest: Dict[str, ConceptEdge] = {}
        for row in self.store.all():
            if row.get("kind") == "concept_edge":
                e = ConceptEdge.from_dict(row["edge"])
                latest[e.edge_id] = e
        return tuple(latest[k] for k in sorted(latest))

    def concepts(self) -> Tuple[str, ...]:
        names = set()
        for row in self.store.all():
            if row.get("kind") == "concept_mention":
                names.add(row["concept"])
            elif row.get("kind") == "concept_edge":
                names.add(row["edge"]["subject"])
                names.add(row["edge"]["object"])
        return tuple(sorted(names))

    def neighbours(self, concept: str) -> Tuple[Tuple[str, str, str], ...]:
        """``(relation, other_concept, direction)`` triples touching ``concept``."""
        out: List[Tuple[str, str, str]] = []
        for e in self.edges():
            if e.subject == concept:
                out.append((e.relation, e.object, "OUT"))
            elif e.object == concept:
                out.append((e.relation, e.subject, "IN"))
        return tuple(sorted(set(out)))

    def source_ids_for(self, *concepts: str) -> Tuple[str, ...]:
        """Every source that mentioned any of ``concepts`` — provenance carrier."""
        wanted = set(concepts)
        ids = set()
        for row in self.store.all():
            if row.get("kind") == "concept_mention" and row["concept"] in wanted:
                ids.add(row["source_id"])
            elif row.get("kind") == "concept_edge":
                e = row["edge"]
                if e["subject"] in wanted or e["object"] in wanted:
                    ids.update(e.get("source_ids", []))
        return tuple(sorted(ids))

    # -------------------------------------------------------------- findings

    def record_finding(self, finding: Finding) -> Finding:
        """Insert or advance a finding, enforcing the epistemic state machine."""
        guard.require("UPDATE_KNOWLEDGE", finding=finding.finding_id)
        current = self.get_finding(finding.finding_id)
        if current is not None:
            epistemic.assert_transition(current.state, finding.state, subject=finding.finding_id)
        elif finding.state not in (epistemic.UNKNOWN, epistemic.KNOWN, epistemic.BLOCKED):
            raise KnowledgeError(
                "a finding cannot be created already TESTED/SURVIVED/REFUTED -- it must "
                "pass through the states that record how it got there",
                finding=finding.finding_id,
                state=finding.state,
            )
        stamped = Finding(
            family=finding.family,
            mechanism_signature=finding.mechanism_signature,
            horizon=finding.horizon,
            state=finding.state,
            statement=finding.statement,
            evidence_refs=finding.evidence_refs,
            updated_at=finding.updated_at or self._clock(),
            finding_id=finding.finding_id,
        )
        self.store.append(
            {
                # Each assertion about a finding is its own event, so the row id
                # covers WHAT was asserted and WHEN. Keying only on the state
                # would collide the moment the same state is asserted twice with
                # different wording -- which is exactly what happens when an
                # experiment completes and then reports its outcome.
                "row_id": mint_id(
                    "KROW",
                    {
                        "k": "finding",
                        "f": finding.finding_id,
                        "s": stamped.state,
                        "e": stamped.evidence_refs,
                        "st": stamped.statement,
                        "t": stamped.updated_at,
                    },
                ),
                "kind": "finding",
                "finding": stamped.to_dict(),
                "previous_state": current.state if current else None,
                "timestamp": stamped.updated_at,
            }
        )
        return stamped

    def get_finding(self, finding_id: str) -> Optional[Finding]:
        rows = [r for r in self.store.all() if r.get("kind") == "finding" and r["finding"]["finding_id"] == finding_id]
        return Finding.from_dict(rows[-1]["finding"]) if rows else None

    def findings(self, *, state: Optional[str] = None) -> Tuple[Finding, ...]:
        latest: Dict[str, Finding] = {}
        for row in self.store.all():
            if row.get("kind") == "finding":
                f = Finding.from_dict(row["finding"])
                latest[f.finding_id] = f
        out = [latest[k] for k in sorted(latest)]
        if state is not None:
            epistemic.validate_state(state)
            out = [f for f in out if f.state == state]
        return tuple(out)

    def finding_history(self, finding_id: str) -> Tuple[Dict[str, Any], ...]:
        return tuple(
            r for r in self.store.all() if r.get("kind") == "finding" and r["finding"]["finding_id"] == finding_id
        )

    def state_of(self, *, family: str, mechanism_signature: str, horizon: str) -> str:
        """Current epistemic state of a search-space region (UNKNOWN if unseen)."""
        fid = mint_id("FIND", {"f": family, "m": mechanism_signature, "h": horizon})
        found = self.get_finding(fid)
        return found.state if found else epistemic.UNKNOWN

    def is_refuted(self, *, family: str, mechanism_signature: str, horizon: str) -> bool:
        return self.state_of(
            family=family, mechanism_signature=mechanism_signature, horizon=horizon
        ) == epistemic.REFUTED

    # --------------------------------------------------------------- summary

    def summary(self) -> Dict[str, Any]:
        by_state: Dict[str, int] = {s: 0 for s in sorted(epistemic.STATES)}
        for f in self.findings():
            by_state[f.state] += 1
        return {
            "concepts": len(self.concepts()),
            "edges": len(self.edges()),
            "findings": len(self.findings()),
            "findings_by_state": by_state,
            "search_space_closed": by_state[epistemic.REFUTED],
            "search_space_open_but_unproven": by_state[epistemic.UNDERPOWERED] + by_state[epistemic.BLOCKED],
            "checksum": self.store.checksum(),
        }
