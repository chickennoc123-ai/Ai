"""Failure memory (Phase 5) — the map of where not to dig.

Two sources feed this map:

* The Idea Machine's **own** failure ledger, written by the Feedback Engine
  when the Factory returns a verdict.
* The Strategy Factory's existing ``core.factory.failure_library``, read
  **read-only**. The Idea Machine benefits from everything the Factory already
  learned, and Phase 16 forbids it from writing there or editing that history —
  :meth:`FailureMemory.factory_failure_counts` opens the library for reading
  and never calls ``record()``.

The critical distinction the whole module protects is ``REFUTED`` vs
``UNDERPOWERED``. A refuted mechanism closes search space. An underpowered one
does not — it means the experiment was too small to see anything, and treating
that as a refutation would permanently blacklist regions the machine never
actually examined.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from idea_machine.core.ids import mint_id
from idea_machine.core.store import DEFAULT_ROOT, AppendOnlyStore
from idea_machine.governance import guard
from utils.helpers import isoformat

DEFAULT_FAILURE_MEMORY_PATH = DEFAULT_ROOT / "failure_memory.json"

#: Outcomes that can be recorded. Only REFUTED closes search space.
#:
#: ``FAIL`` and ``REFUTED`` are not the same thing: FAIL means the tested
#: mechanism did not cover its costs at this horizon (the mechanism might still
#: be real at another horizon or on another instrument), while REFUTED means
#: the mechanism itself was contradicted. ``FAILED_ECONOMICS`` is narrower
#: still -- the Idea Machine's own pre-filter rejected it before any test ran.
OUTCOMES = frozenset(
    {"REFUTED", "FAIL", "UNDERPOWERED", "BLOCKED", "SURVIVED", "FAILED_ECONOMICS"}
)

#: Outcomes after which the same mechanism must not be proposed again.
CLOSING_OUTCOMES = frozenset({"REFUTED"})

#: Outcomes that leave the door open, with a reason recorded for later.
REOPENABLE_OUTCOMES = frozenset({"UNDERPOWERED", "BLOCKED"})


@dataclass(frozen=True)
class FailureEntry:
    """One durable lesson. Deliberately carries no performance metric.

    Storing "it made -0.3 Sharpe" here would let holdout numbers leak back into
    research targeting through the failure channel. What is stored instead is
    the *mechanism* that failed and the *rule* a future idea can be checked
    against — which is the part that actually generalises.
    """

    idea_id: str
    family: str
    mechanism_signature: str
    horizon: str
    outcome: str
    reason: str
    prevention_rule: str = ""
    scope: str = ""
    recorded_at: str = ""
    entry_id: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {self.outcome!r}; allowed: {sorted(OUTCOMES)}")
        if not self.entry_id:
            object.__setattr__(
                self,
                "entry_id",
                mint_id(
                    "FAILMEM",
                    {"i": self.idea_id, "o": self.outcome, "r": self.reason, "t": self.recorded_at},
                ),
            )

    @property
    def closes_search_space(self) -> bool:
        return self.outcome in CLOSING_OUTCOMES

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "FailureEntry":
        return FailureEntry(
            idea_id=d["idea_id"],
            family=d["family"],
            mechanism_signature=d["mechanism_signature"],
            horizon=d["horizon"],
            outcome=d["outcome"],
            reason=d["reason"],
            prevention_rule=d.get("prevention_rule", ""),
            scope=d.get("scope", ""),
            recorded_at=d.get("recorded_at", ""),
            entry_id=d.get("entry_id", ""),
        )


class FailureMemory:
    """Append-only failure ledger, plus read-only access to the Factory's."""

    def __init__(self, path: Path = DEFAULT_FAILURE_MEMORY_PATH, *, clock=isoformat) -> None:
        self.store = AppendOnlyStore(path, id_field="entry_id", kind="failure_memory")
        self._clock = clock

    # ------------------------------------------------------------- recording

    def record(self, entry: FailureEntry) -> FailureEntry:
        stamped = FailureEntry(
            idea_id=entry.idea_id,
            family=entry.family,
            mechanism_signature=entry.mechanism_signature,
            horizon=entry.horizon,
            outcome=entry.outcome,
            reason=entry.reason,
            prevention_rule=entry.prevention_rule,
            scope=entry.scope,
            recorded_at=entry.recorded_at or self._clock(),
            # Re-mint rather than carrying the pre-stamp id: the id must cover
            # the timestamp, or two genuine records of the same lesson at
            # different times collide as if one were rewriting the other.
            entry_id="",
        )
        self.store.append(stamped.to_dict())
        return stamped

    def forget(self, entry_id: str) -> None:
        """There is no forgetting. Calling this terminates the run.

        Present as a named method precisely so that any code (or future author)
        reaching for it hits the governance boundary instead of finding a
        convenient way to erase an inconvenient lesson.
        """
        guard.forbid("MODIFY_FAILURE_HISTORY", entry_id=entry_id)

    # --------------------------------------------------------------- reading

    def entries(self) -> Tuple[FailureEntry, ...]:
        return tuple(FailureEntry.from_dict(d) for d in self.store.all())

    def for_mechanism(self, mechanism_signature: str) -> Tuple[FailureEntry, ...]:
        return tuple(e for e in self.entries() if e.mechanism_signature == mechanism_signature)

    def is_closed(self, *, mechanism_signature: str, horizon: str) -> bool:
        """Has this exact mechanism/horizon been refuted?"""
        return any(
            e.closes_search_space and e.mechanism_signature == mechanism_signature and e.horizon == horizon
            for e in self.entries()
        )

    def reopenable_reason(self, *, mechanism_signature: str, horizon: str) -> Optional[str]:
        """Why an earlier attempt stalled, if it stalled recoverably."""
        for e in reversed(self.entries()):
            if e.mechanism_signature == mechanism_signature and e.horizon == horizon:
                if e.outcome in REOPENABLE_OUTCOMES:
                    return f"{e.outcome}: {e.reason}"
                return None
        return None

    def family_failure_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for e in self.entries():
            if e.closes_search_space:
                counts[e.family] = counts.get(e.family, 0) + 1
        return dict(sorted(counts.items()))

    def prevention_rules(self) -> Tuple[str, ...]:
        seen: List[str] = []
        for e in self.entries():
            if e.prevention_rule and e.prevention_rule not in seen:
                seen.append(e.prevention_rule)
        return tuple(seen)

    # --------------------------------------------- Strategy Factory, READ ONLY

    def factory_failure_counts(self) -> Dict[str, int]:
        """Family-level failure counts from the Factory's own library.

        Read-only by construction: this method opens the library, reads counts,
        and returns. It never calls ``record()``, and nothing in the Idea
        Machine holds a writable reference to the Factory's library.
        """
        from core.factory.failure_library import FailureLibrary

        library = FailureLibrary()
        counts: Dict[str, int] = {}
        for record in library.all_failures():
            family = getattr(record, "related_family", "") or "UNATTRIBUTED"
            counts[family] = counts.get(family, 0) + 1
        return dict(sorted(counts.items()))

    def summary(self) -> Dict[str, Any]:
        by_outcome: Dict[str, int] = {}
        for e in self.entries():
            by_outcome[e.outcome] = by_outcome.get(e.outcome, 0) + 1
        return {
            "entries": len(self.entries()),
            "by_outcome": dict(sorted(by_outcome.items())),
            "search_space_closed": sum(1 for e in self.entries() if e.closes_search_space),
            "reopenable": sum(1 for e in self.entries() if e.outcome in REOPENABLE_OUTCOMES),
            "prevention_rules": len(self.prevention_rules()),
        }
