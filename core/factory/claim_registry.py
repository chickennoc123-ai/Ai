"""Claim Registry — Generation 2, Phase 3.

Per ``ML-001-RESEARCH-SOURCE-SPEC.md``: a source may contain zero, one, or
many claims. Each claim is independently identifiable and versioned, and
its status is tracked through a lifecycle that explicitly distinguishes
"the source said this" from "this was tested and supported" — a claim is
never marked ``SUPPORTED`` merely because its source asserted it.
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

DEFAULT_CLAIM_REGISTRY_PATH = Path("reports/factory/claim_registry.json")

CLAIM_TYPES = frozenset(
    {
        "PREDICTIVE_SIGNAL",  # "X predicts future returns"
        "REGIME_DEPENDENCE",  # "X works only in condition Y"
        "RISK_PREMIUM",  # "X is compensation for bearing risk Y"
        "MICROSTRUCTURE_EFFECT",
        "SEASONALITY",
        "CROSS_ASSET_RELATIONSHIP",
        "EVENT_DRIVEN",
        "OTHER",
    }
)

#: UNEXTRACTED -> EXTRACTED -> FORMALIZATION_PENDING -> FORMALIZED -> TESTED
#: -> {SUPPORTED, REFUTED} ; SUPERSEDED is reachable from any non-terminal
#: state (a claim re-extracted/re-worded from the same source material).
CLAIM_STATUSES = (
    "UNEXTRACTED",
    "EXTRACTED",
    "FORMALIZATION_PENDING",
    "FORMALIZED",
    "TESTED",
    "SUPPORTED",
    "REFUTED",
    "SUPERSEDED",
)
_TERMINAL_CLAIM_STATUSES = frozenset({"SUPPORTED", "REFUTED", "SUPERSEDED"})

_CLAIM_FORWARD_ORDER = {s: i for i, s in enumerate(CLAIM_STATUSES) if s not in ("SUPPORTED", "REFUTED", "SUPERSEDED")}


class ClaimSpecError(EAFactoryError):
    """Raised when a ClaimRecord is incomplete or invalid."""


class ClaimNotFoundError(EAFactoryError):
    pass


class DuplicateClaimError(EAFactoryError):
    pass


class IllegalClaimStatusTransitionError(EAFactoryError):
    """Raised on a structurally-disallowed claim status transition
    (mirrors core.factory.state_machine's discipline for candidates)."""


class ClaimRegistryCorruptionError(EAFactoryError):
    pass


def _claim_status_legal_next(current: str) -> frozenset:
    if current in _TERMINAL_CLAIM_STATUSES:
        return frozenset()
    forward = []
    order = list(_CLAIM_FORWARD_ORDER.keys())
    idx = order.index(current)
    if idx + 1 < len(order):
        forward.append(order[idx + 1])
    forward.append("SUPERSEDED")
    if current in ("TESTED",):
        forward.extend(["SUPPORTED", "REFUTED"])
    return frozenset(forward)


def assert_legal_claim_transition(current: str, requested: str) -> None:
    if requested not in _claim_status_legal_next(current):
        raise IllegalClaimStatusTransitionError(
            f"illegal claim status transition: {current} -> {requested} "
            f"(allowed: {sorted(_claim_status_legal_next(current))})"
        )


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    source_id: str
    claim_text: str
    claim_type: str
    creation_timestamp: str
    claim_version: int = 1
    mechanism: str = "UNKNOWN"
    instrument_scope: str = "UNKNOWN"
    timeframe_scope: str = "UNKNOWN"
    direction: str = "UNKNOWN"
    supporting_context: str = ""
    verification_status: str = "UNEXTRACTED"

    def __post_init__(self) -> None:
        required = ("claim_id", "source_id", "claim_text", "creation_timestamp")
        missing = [f for f in required if not getattr(self, f) or not str(getattr(self, f)).strip()]
        if missing:
            raise ClaimSpecError("claim record is incomplete", missing_fields=missing)
        if self.claim_type not in CLAIM_TYPES:
            raise ClaimSpecError("unknown claim_type", claim_type=self.claim_type, allowed=sorted(CLAIM_TYPES))
        if self.verification_status not in CLAIM_STATUSES:
            raise ClaimSpecError(
                "unknown verification_status", verification_status=self.verification_status, allowed=list(CLAIM_STATUSES)
            )

    def identity_checksum(self) -> str:
        data = {"source_id": self.source_id, "claim_text": self.claim_text, "claim_type": self.claim_type}
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ClaimRecord":
        return ClaimRecord(**d)


class ClaimRegistry:
    def __init__(self, path: Path = DEFAULT_CLAIM_REGISTRY_PATH) -> None:
        self.path = Path(path)
        self._next_id = 1
        self._claims: Dict[str, ClaimRecord] = {}
        self._history: Dict[str, List[Dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise ClaimRegistryCorruptionError(
                "claim registry file is not valid JSON; refusing to load", path=str(self.path)
            ) from exc
        self._next_id = raw.get("next_id", 1)
        self._claims = {cid: ClaimRecord.from_dict(cdata) for cid, cdata in raw.get("claims", {}).items()}
        self._history = raw.get("history", {})

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "next_id": self._next_id,
            "claims": {cid: c.to_dict() for cid, c in self._claims.items()},
            "history": self._history,
        }
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def allocate_claim_id(self) -> str:
        cid = f"CLAIM-{self._next_id:06d}"
        self._next_id += 1
        self._save()
        return cid

    def register(self, record: ClaimRecord) -> ClaimRecord:
        if record.claim_id in self._claims:
            raise DuplicateClaimError("claim_id already registered", claim_id=record.claim_id)
        self._claims[record.claim_id] = record
        self._history[record.claim_id] = [
            {"status": record.verification_status, "timestamp": utcnow().isoformat(), "reason": "registered"}
        ]
        self._save()
        return record

    def get(self, claim_id: str) -> ClaimRecord:
        try:
            return self._claims[claim_id]
        except KeyError as exc:
            raise ClaimNotFoundError("no such claim", claim_id=claim_id) from exc

    def transition_status(self, claim_id: str, new_status: str, *, reason: str) -> ClaimRecord:
        """Status is tracked out-of-band (in ``_history``) because
        ``ClaimRecord`` is frozen (immutability discipline consistent
        with ``StrategyCandidate``) -- ``get()`` always reflects the
        latest status via a rebuilt record, never a stale cached one."""
        current = self.get(claim_id)
        assert_legal_claim_transition(current.verification_status, new_status)
        updated = ClaimRecord(**{**current.to_dict(), "verification_status": new_status})
        self._claims[claim_id] = updated
        self._history.setdefault(claim_id, []).append(
            {"status": new_status, "timestamp": utcnow().isoformat(), "reason": reason}
        )
        self._save()
        return updated

    def history(self, claim_id: str) -> List[Dict[str, Any]]:
        if claim_id not in self._claims:
            raise ClaimNotFoundError("no such claim", claim_id=claim_id)
        return list(self._history.get(claim_id, []))

    def list_all(self) -> List[ClaimRecord]:
        return list(self._claims.values())

    def list_by_source(self, source_id: str) -> List[ClaimRecord]:
        return [c for c in self._claims.values() if c.source_id == source_id]

    def find_duplicate(self, candidate: ClaimRecord) -> Optional[ClaimRecord]:
        target = candidate.identity_checksum()
        for existing in self._claims.values():
            if existing.identity_checksum() == target:
                return existing
        return None
