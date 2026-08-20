"""Idea Queue (Phase 10) — the state machine an idea travels through.

    GENERATED -> SCREENED -> APPROVED_FOR_RESEARCH -> QUEUED -> RUNNING
              -> FACTORY_RESULT -> {SURVIVOR, FAIL, BLOCKED, UNDERPOWERED, REFUTED}

Two rules carry the governance weight:

* **No skipping.** An idea cannot jump from ``GENERATED`` to ``QUEUED``; the
  screening states exist because each one can reject. A transition table, not a
  convention, enforces this.
* **The Idea Machine does not decide terminal outcomes.** ``SURVIVOR``,
  ``FAIL``, ``REFUTED``, ``UNDERPOWERED`` and ``BLOCKED`` may only be entered
  from ``FACTORY_RESULT``, and only by presenting a Factory result reference.
  The queue has no code path that lets the machine mark its own idea a
  survivor, and ``SURVIVOR`` still does not mean "edge" — the Factory's own
  gates decide that.

Every transition is appended to the ledger with its reason, so the full history
of an idea is reconstructable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

from idea_machine.core.errors import QueueError
from idea_machine.core.idea_spec import IdeaSpec
from idea_machine.core.ids import mint_id
from idea_machine.core.store import DEFAULT_ROOT, AppendOnlyStore
from idea_machine.governance import guard
from utils.helpers import isoformat

DEFAULT_QUEUE_PATH = DEFAULT_ROOT / "idea_queue.json"

GENERATED = "GENERATED"
SCREENED = "SCREENED"
APPROVED_FOR_RESEARCH = "APPROVED_FOR_RESEARCH"
QUEUED = "QUEUED"
RUNNING = "RUNNING"
FACTORY_RESULT = "FACTORY_RESULT"
#: The Idea Machine's OWN pre-screen verdict: the data this idea needs is not
#: in the catalog, so it never reached the Factory. Distinct from BLOCKED,
#: which is a Factory outcome -- conflating them would either require the Idea
#: Machine to invent Factory evidence for its own screening decision, or let it
#: enter a Factory-owned state on its own authority.
BLOCKED_DATA = "BLOCKED_DATA"
SURVIVOR = "SURVIVOR"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
UNDERPOWERED = "UNDERPOWERED"
REFUTED = "REFUTED"
REJECTED = "REJECTED"

STATES: FrozenSet[str] = frozenset(
    {
        GENERATED, SCREENED, APPROVED_FOR_RESEARCH, QUEUED, RUNNING, FACTORY_RESULT,
        BLOCKED_DATA, SURVIVOR, FAIL, BLOCKED, UNDERPOWERED, REFUTED, REJECTED,
    }
)

#: Outcomes only the Strategy Factory may cause.
FACTORY_OUTCOMES: FrozenSet[str] = frozenset({SURVIVOR, FAIL, BLOCKED, UNDERPOWERED, REFUTED})

TERMINAL: FrozenSet[str] = FACTORY_OUTCOMES | {REJECTED}

_TRANSITIONS: Dict[str, FrozenSet[str]] = {
    GENERATED: frozenset({SCREENED, REJECTED}),
    SCREENED: frozenset({APPROVED_FOR_RESEARCH, REJECTED, BLOCKED_DATA}),
    APPROVED_FOR_RESEARCH: frozenset({QUEUED, REJECTED}),
    QUEUED: frozenset({RUNNING, REJECTED}),
    RUNNING: frozenset({FACTORY_RESULT}),
    FACTORY_RESULT: FACTORY_OUTCOMES,
    SURVIVOR: frozenset(),
    FAIL: frozenset(),
    BLOCKED_DATA: frozenset({SCREENED}),     # unblocks when the operator adds the data
    BLOCKED: frozenset({SCREENED}),          # the Factory could not run it; may retry
    UNDERPOWERED: frozenset({SCREENED}),     # re-testable with a bigger sample
    REFUTED: frozenset(),
    REJECTED: frozenset(),
}


@dataclass(frozen=True)
class QueueEntry:
    idea_id: str
    state: str
    reason: str
    experiment_id: str = ""
    evidence_reference: str = ""
    priority: float = 0.0
    updated_at: str = ""
    sequence: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "row_id": mint_id(
                "QROW",
                {"i": self.idea_id, "s": self.state, "n": self.sequence, "e": self.experiment_id},
            ),
            "idea_id": self.idea_id,
            "state": self.state,
            "reason": self.reason,
            "experiment_id": self.experiment_id,
            "evidence_reference": self.evidence_reference,
            "priority": self.priority,
            "updated_at": self.updated_at,
            "sequence": self.sequence,
        }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "QueueEntry":
        return QueueEntry(
            idea_id=d["idea_id"],
            state=d["state"],
            reason=d.get("reason", ""),
            experiment_id=d.get("experiment_id", ""),
            evidence_reference=d.get("evidence_reference", ""),
            priority=float(d.get("priority", 0.0)),
            updated_at=d.get("updated_at", ""),
            sequence=int(d.get("sequence", 0)),
        )


class IdeaQueue:
    """Append-only queue with an enforced state machine."""

    def __init__(self, path: Path = DEFAULT_QUEUE_PATH, *, clock=isoformat) -> None:
        self.store = AppendOnlyStore(path, id_field="row_id", kind="idea_queue")
        self._clock = clock

    # ------------------------------------------------------------ transitions

    def admit(self, idea: IdeaSpec, *, priority: float = 0.0, reason: str = "generated") -> QueueEntry:
        """Put a newly generated idea into the queue at ``GENERATED``."""
        guard.require("ENQUEUE_IDEA", idea_id=idea.idea_id)
        if self.state_of(idea.idea_id) is not None:
            return self.current(idea.idea_id)
        return self._append(idea.idea_id, GENERATED, reason, priority=priority)

    def advance(
        self,
        idea_id: str,
        target: str,
        *,
        reason: str,
        experiment_id: str = "",
        evidence_reference: str = "",
        priority: Optional[float] = None,
    ) -> QueueEntry:
        """Move ``idea_id`` to ``target``, or raise."""
        if target not in STATES:
            raise QueueError("unknown queue state", state=target, allowed=sorted(STATES))
        current = self.current(idea_id)
        if current is None:
            raise QueueError("idea is not in the queue", idea_id=idea_id)
        if current.state == target:
            return current
        allowed = _TRANSITIONS[current.state]
        if target not in allowed:
            raise QueueError(
                "illegal queue transition -- screening states exist because each one can reject",
                idea_id=idea_id,
                current=current.state,
                target=target,
                allowed=sorted(allowed),
            )
        if target in FACTORY_OUTCOMES:
            self._require_factory_evidence(idea_id, target, evidence_reference)
        if not str(reason).strip():
            raise QueueError("every transition must record why", idea_id=idea_id, target=target)

        return self._append(
            idea_id,
            target,
            reason,
            experiment_id=experiment_id or current.experiment_id,
            evidence_reference=evidence_reference,
            priority=current.priority if priority is None else priority,
        )

    def _require_factory_evidence(self, idea_id: str, target: str, evidence_reference: str) -> None:
        """A terminal outcome must point at the Factory result that caused it.

        Without this, the Idea Machine could mark its own ideas SURVIVOR, which
        is the ``DECLARE_EDGE`` violation wearing a different hat.
        """
        if not str(evidence_reference).strip():
            guard.deny_edge_declaration(
                idea_id=idea_id,
                target_state=target,
                detail=(
                    "a terminal outcome requires a Strategy Factory evidence reference; the Idea "
                    "Machine cannot decide its own idea's fate"
                ),
            )

    def _append(
        self,
        idea_id: str,
        state: str,
        reason: str,
        *,
        experiment_id: str = "",
        evidence_reference: str = "",
        priority: float = 0.0,
    ) -> QueueEntry:
        entry = QueueEntry(
            idea_id=idea_id,
            state=state,
            reason=reason,
            experiment_id=experiment_id,
            evidence_reference=evidence_reference,
            priority=priority,
            updated_at=self._clock(),
            sequence=len(self.history(idea_id)),
        )
        self.store.append(entry.to_dict())
        return entry

    # ------------------------------------------------------------------ reads

    def history(self, idea_id: str) -> Tuple[QueueEntry, ...]:
        return tuple(
            QueueEntry.from_dict(r) for r in self.store.all() if r.get("idea_id") == idea_id
        )

    def current(self, idea_id: str) -> Optional[QueueEntry]:
        rows = self.history(idea_id)
        return rows[-1] if rows else None

    def state_of(self, idea_id: str) -> Optional[str]:
        entry = self.current(idea_id)
        return entry.state if entry else None

    def in_state(self, state: str) -> Tuple[QueueEntry, ...]:
        latest: Dict[str, QueueEntry] = {}
        for row in self.store.all():
            e = QueueEntry.from_dict(row)
            latest[e.idea_id] = e
        return tuple(
            sorted(
                (e for e in latest.values() if e.state == state),
                key=lambda e: (-e.priority, e.idea_id),
            )
        )

    def next_for_research(self, limit: int) -> Tuple[QueueEntry, ...]:
        """The highest-priority QUEUED ideas, in priority order."""
        return self.in_state(QUEUED)[:limit]

    def counts(self) -> Dict[str, int]:
        latest: Dict[str, str] = {}
        for row in self.store.all():
            latest[row["idea_id"]] = row["state"]
        counts = {s: 0 for s in sorted(STATES)}
        for state in latest.values():
            counts[state] += 1
        return counts

    def summary(self) -> Dict[str, Any]:
        counts = self.counts()
        return {
            "ideas": sum(counts.values()),
            "by_state": counts,
            "in_flight": counts[QUEUED] + counts[RUNNING] + counts[FACTORY_RESULT],
            "terminal": sum(counts[s] for s in sorted(TERMINAL)),
            "transitions_recorded": self.store.count(),
            "checksum": self.store.checksum(),
        }

    def verify_integrity(self) -> None:
        """Replay every idea's history and confirm each step was legal."""
        self.store.verify_integrity()
        by_idea: Dict[str, List[QueueEntry]] = {}
        for row in self.store.all():
            by_idea.setdefault(row["idea_id"], []).append(QueueEntry.from_dict(row))
        for idea_id, rows in sorted(by_idea.items()):
            if rows[0].state != GENERATED:
                raise QueueError("an idea's history does not begin at GENERATED", idea_id=idea_id, first=rows[0].state)
            for prev, nxt in zip(rows, rows[1:]):
                if nxt.state not in _TRANSITIONS[prev.state]:
                    raise QueueError(
                        "queue history contains an illegal transition",
                        idea_id=idea_id, current=prev.state, target=nxt.state,
                    )
