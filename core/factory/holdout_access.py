"""Holdout access event — closes Generation 1 finding G1-M2.

Per the Generation 1 independent audit (finding G1): the state machine's
``HOLDOUT_TESTED`` transition was pure bookkeeping, with no code-level
link to a verified ``PURE_HOLDOUT`` data access. This module defines the
auditable event a caller must now present, and ``StrategyRegistry.
transition()`` (``core/factory/registry.py``) validates it before
allowing entry into ``HOLDOUT_TESTED`` — a bare ``reason`` string is no
longer sufficient.

**No real holdout data is exposed or accessed by this module or its
tests** — per the task's explicit instruction, this is governance
hardening only. Every test in ``tests/test_g1_m2_holdout_access_
linkage.py`` uses synthetic fixtures and a TEST-marked candidate; the real
``PURE_HOLDOUT`` partition of the EURUSD/GBPUSD data is never touched.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict

from utils.exceptions import EAFactoryError


class HoldoutAccessEventError(EAFactoryError):
    """Raised when a HoldoutAccessEvent is incomplete or self-contradictory."""


@dataclass(frozen=True)
class HoldoutAccessEvent:
    """An auditable record that a real PURE_HOLDOUT evaluation occurred
    for a specific, frozen candidate version.

    This is deliberately a plain, inspectable dataclass — not a
    cryptographic proof (an event can still be constructed with false
    values by a determined bad actor) — but it forces every caller to
    explicitly state, in one place, every fact ``ML-001-STRATEGY-FACTORY-
    SPEC.md`` §4 says must be true before ``HOLDOUT_TESTED`` is entered,
    rather than letting a bare ``reason`` string stand in for all of them.
    """

    candidate_id: str
    candidate_version: int
    dataset_id: str
    dataset_checksum: str
    holdout_partition_identity: str
    access_timestamp: str
    frozen_state_confirmed: bool
    evidence_reference: str

    def __post_init__(self) -> None:
        required = (
            "candidate_id",
            "dataset_id",
            "dataset_checksum",
            "holdout_partition_identity",
            "access_timestamp",
            "evidence_reference",
        )
        missing = [f for f in required if not getattr(self, f) or not str(getattr(self, f)).strip()]
        if missing:
            raise HoldoutAccessEventError("holdout access event is incomplete", missing_fields=missing)
        if self.candidate_version is None or self.candidate_version < 1:
            raise HoldoutAccessEventError("candidate_version must be a positive integer")
        if not self.frozen_state_confirmed:
            raise HoldoutAccessEventError(
                "frozen_state_confirmed must be True -- an event asserting the candidate was "
                "NOT confirmed frozen at access time cannot justify a HOLDOUT_TESTED transition"
            )

    def event_checksum(self) -> str:
        """Deterministic identity for this event's content — lets a
        Research Ledger entry (Generation 2, Phase 11) reference exactly
        this event without re-embedding every field."""
        data = asdict(self)
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def validate_holdout_access_event(event: HoldoutAccessEvent, *, candidate_id: str, candidate_version: int) -> None:
    """Cross-check ``event`` against the candidate it is being presented
    for. Raises ``HoldoutAccessEventError`` on any mismatch. Called by
    ``StrategyRegistry.transition()`` before allowing entry into
    ``HOLDOUT_TESTED`` — kept as a free function (not a method on the
    event itself) so the caller's own candidate/version is always the
    thing being checked against, never trusted from the event alone.
    """
    if event.candidate_id != candidate_id:
        raise HoldoutAccessEventError(
            "holdout access event candidate_id does not match the candidate being transitioned",
            event_candidate_id=event.candidate_id,
            candidate_id=candidate_id,
        )
    if event.candidate_version != candidate_version:
        raise HoldoutAccessEventError(
            "holdout access event candidate_version does not match the candidate's current version",
            event_candidate_version=event.candidate_version,
            candidate_version=candidate_version,
        )
