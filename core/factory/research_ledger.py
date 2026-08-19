"""Research Ledger — Generation 2, Phase 11 (CORE REQUIREMENT).

A durable, append-only record of every meaningful research event across
the entire pipeline (source ingestion through candidate rejection/
freezing). Never rewritten, never deleted from — a correction is a new
entry, not an edit to an old one.
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

DEFAULT_RESEARCH_LEDGER_PATH = Path("reports/factory/research_ledger.json")

EVENT_TYPES = frozenset(
    {
        "SOURCE_INGESTED",
        "SOURCE_NEW_VERSION",
        "CLAIM_CREATED",
        "CLAIM_STATUS_CHANGED",
        "HYPOTHESIS_CREATED",
        "HYPOTHESIS_FORMALIZED",
        "HYPOTHESIS_REJECTED",
        "HYPOTHESIS_STATUS_CHANGED",
        "SEARCH_SPACE_CREATED",
        "CANDIDATE_GENERATED",
        "CANDIDATE_REJECTED",
        "CANDIDATE_FROZEN",
        "EVALUATION_REQUESTED",
        "EVALUATION_BLOCKED",
        "DUPLICATE_DETECTED",
        # --- Generation 4 (candidate economic validation) ---
        # Additive only: no existing event type was renamed, removed or
        # given a new meaning, so every ledger entry written by
        # Generations 1-3 still loads and still means exactly what it did.
        "DATA_ELIGIBILITY_AUDITED",
        "LEAKAGE_AUDITED",
        "EVALUATION_COMPLETED",
        "HOLDOUT_RELEASED",
        "HOLDOUT_EVALUATED",
        "WFA_COMPLETED",
        "ROBUSTNESS_COMPLETED",
        "COST_STRESS_COMPLETED",
        "STATISTICS_COMPLETED",
        "MULTIPLE_TESTING_COMPLETED",
        "EVG_VERDICT",
        "CANDIDATE_CLASSIFIED",
    }
)


class LedgerEventError(EAFactoryError):
    """Raised when a LedgerEvent is incomplete or references an unknown event_type."""


class LedgerMutationError(EAFactoryError):
    """Raised if code attempts to alter or remove an already-appended
    ledger entry -- there is deliberately no such code path; this
    exception exists so a future maintainer who tries to add one gets an
    explicit, named thing to NOT implement, not silence."""


class LedgerCorruptionError(EAFactoryError):
    pass


@dataclass(frozen=True)
class LedgerEvent:
    """One append-only research event.

    Fields chosen so WHO/WHAT, WHEN, WHY, FROM_WHICH_SOURCE, USING_WHICH_
    DATA, USING_WHICH_FEATURES, USING_WHICH_SEARCH_SPACE, RESULT, and
    ARTIFACT are all directly answerable from one entry without needing
    to reconstruct them from other registries (though the ids here are
    exactly the ids those registries use, so cross-referencing is always
    possible too).
    """

    event_id: str
    event_type: str
    timestamp: str
    subject_id: str  # the primary entity this event is about (source/claim/hypothesis/candidate id)
    reason: str
    source_id: Optional[str] = None
    dataset_id: Optional[str] = None
    feature_ids: tuple = ()
    search_space_id: Optional[str] = None
    result: str = ""
    artifact_reference: str = ""

    def __post_init__(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise LedgerEventError("unknown event_type", event_type=self.event_type, allowed=sorted(EVENT_TYPES))
        required = ("event_id", "timestamp", "subject_id", "reason")
        missing = [f for f in required if not getattr(self, f) or not str(getattr(self, f)).strip()]
        if missing:
            raise LedgerEventError("ledger event is incomplete", missing_fields=missing)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["feature_ids"] = list(self.feature_ids)
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "LedgerEvent":
        d = dict(d)
        d["feature_ids"] = tuple(d.get("feature_ids", ()))
        return LedgerEvent(**d)


class ResearchLedger:
    """Append-only. There is no ``update``/``delete``/``rewrite`` method
    anywhere in this class, by design — every research event, once
    recorded, is permanent."""

    def __init__(self, path: Path = DEFAULT_RESEARCH_LEDGER_PATH) -> None:
        self.path = Path(path)
        self._next_seq = 1
        self._events: List[LedgerEvent] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise LedgerCorruptionError(
                "research ledger file is not valid JSON; refusing to load", path=str(self.path)
            ) from exc
        self._next_seq = raw.get("next_seq", 1)
        self._events = [LedgerEvent.from_dict(e) for e in raw.get("events", [])]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"next_seq": self._next_seq, "events": [e.to_dict() for e in self._events]}
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def append(
        self,
        event_type: str,
        *,
        subject_id: str,
        reason: str,
        source_id: Optional[str] = None,
        dataset_id: Optional[str] = None,
        feature_ids: tuple = (),
        search_space_id: Optional[str] = None,
        result: str = "",
        artifact_reference: str = "",
    ) -> LedgerEvent:
        """The ONLY way to add to this ledger. Always appends; never
        replaces or removes an existing entry — even calling this twice
        with identical arguments creates two distinct events (with
        different ``event_id``/``timestamp``), which is correct: two
        real occurrences of the same kind of event are two real events,
        not one to be deduplicated away."""
        event_id = f"LEDGER-{self._next_seq:08d}"
        self._next_seq += 1
        event = LedgerEvent(
            event_id=event_id,
            event_type=event_type,
            timestamp=utcnow().isoformat(),
            subject_id=subject_id,
            reason=reason,
            source_id=source_id,
            dataset_id=dataset_id,
            feature_ids=tuple(feature_ids),
            search_space_id=search_space_id,
            result=result,
            artifact_reference=artifact_reference,
        )
        self._events.append(event)
        self._save()
        return event

    def all_events(self) -> List[LedgerEvent]:
        return list(self._events)

    def events_for_subject(self, subject_id: str) -> List[LedgerEvent]:
        return [e for e in self._events if e.subject_id == subject_id]

    def events_by_type(self, event_type: str) -> List[LedgerEvent]:
        return [e for e in self._events if e.event_type == event_type]

    def ledger_checksum(self) -> str:
        """A checksum over the FULL ordered event sequence -- changes if
        any event is added, reordered, or (were it ever possible) edited.
        Lets a caller detect tampering with the underlying JSON file
        independent of git history."""
        data = [e.to_dict() for e in self._events]
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
