"""Pre-registration ledger (Phase 9) — the anti-p-hacking mechanism.

The loop this module exists to break:

    backtest -> result is disappointing -> change the rule -> backtest again
    -> report the version that worked

Every experiment is registered *before* it runs, with a checksum over its
design. When a result comes back, :meth:`PreregistrationLedger.attach_result`
recomputes that checksum. If the design changed, the result is rejected — not
warned about, rejected — and the attempt is recorded permanently.

Amendments are possible but never silent: :meth:`amend` registers a **new**
experiment that supersedes the old one, keeping both in the ledger, so the
count of designs tried is visible to multiple-testing correction rather than
hidden by overwriting.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from idea_machine.core.errors import IdeaMachineError
from idea_machine.core.ids import mint_id
from idea_machine.core.store import DEFAULT_ROOT, AppendOnlyStore
from idea_machine.experiment.spec import ExperimentSpec
from idea_machine.governance import guard
from utils.helpers import isoformat

DEFAULT_PREREG_PATH = DEFAULT_ROOT / "preregistrations.json"


class PreregistrationError(IdeaMachineError):
    """A result does not match the design it claims to be a result for."""


@dataclass(frozen=True)
class PreregistrationRecord:
    experiment_id: str
    idea_id: str
    checksum: str
    registered_at: str
    spec: Mapping[str, Any]
    supersedes: str = ""
    amendment_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.experiment_id,
            "experiment_id": self.experiment_id,
            "idea_id": self.idea_id,
            "checksum": self.checksum,
            "registered_at": self.registered_at,
            "spec": dict(self.spec),
            "supersedes": self.supersedes,
            "amendment_reason": self.amendment_reason,
        }


class PreregistrationLedger:
    """Append-only registry of frozen experiment designs and their results."""

    def __init__(self, path: Path = DEFAULT_PREREG_PATH, *, clock=isoformat) -> None:
        self.store = AppendOnlyStore(path, id_field="record_id", kind="preregistration")
        self._clock = clock

    # ------------------------------------------------------------- register

    def register(self, spec: ExperimentSpec) -> ExperimentSpec:
        """Freeze ``spec`` and commit its design. Returns the frozen spec."""
        guard.require("PREREGISTER_EXPERIMENT", experiment_id=spec.experiment_id)
        if self.store.has(spec.experiment_id):
            existing = self.store.get(spec.experiment_id) or {}
            if existing.get("checksum") != spec.preregistration_checksum():
                guard.deny_preregistration_mutation(
                    spec.experiment_id,
                    registered_checksum=existing.get("checksum"),
                    presented_checksum=spec.preregistration_checksum(),
                )
            return ExperimentSpec.from_dict(existing["spec"])

        frozen = spec if spec.frozen else spec.freeze(at=self._clock())
        record = PreregistrationRecord(
            experiment_id=frozen.experiment_id,
            idea_id=frozen.idea_id,
            checksum=frozen.preregistration_checksum(),
            registered_at=frozen.frozen_at or self._clock(),
            spec=frozen.to_dict(),
        )
        self.store.append(record.to_dict())
        return frozen

    def amend(self, original_id: str, revised: ExperimentSpec, *, reason: str) -> ExperimentSpec:
        """Register a revised design that *supersedes* ``original_id``.

        Both designs stay in the ledger. An amendment is a legitimate research
        act; hiding it is not, so the count of designs tried for one idea stays
        visible to whoever applies the multiple-testing correction.
        """
        guard.require("PREREGISTER_EXPERIMENT", experiment_id=revised.experiment_id, amends=original_id)
        if not self.store.has(original_id):
            raise PreregistrationError("cannot amend an experiment that was never registered", experiment_id=original_id)
        if not str(reason).strip():
            raise PreregistrationError("an amendment must state why the design changed", experiment_id=original_id)
        if self.has_result(original_id):
            guard.deny_preregistration_mutation(
                original_id,
                detail="the original experiment already has a result; amending it now would be "
                       "changing the design after seeing the outcome",
            )
        frozen = revised if revised.frozen else revised.freeze(at=self._clock())
        record = PreregistrationRecord(
            experiment_id=frozen.experiment_id,
            idea_id=frozen.idea_id,
            checksum=frozen.preregistration_checksum(),
            registered_at=frozen.frozen_at or self._clock(),
            spec=frozen.to_dict(),
            supersedes=original_id,
            amendment_reason=reason,
        )
        self.store.append(record.to_dict())
        return frozen

    # --------------------------------------------------------------- verify

    def verify(self, spec: ExperimentSpec) -> None:
        """Raise unless ``spec`` matches exactly what was registered."""
        record = self.store.get(spec.experiment_id)
        if record is None:
            raise PreregistrationError(
                "this experiment was never pre-registered; a result for an unregistered design "
                "cannot be distinguished from a design chosen after seeing the data",
                experiment_id=spec.experiment_id,
            )
        if record["checksum"] != spec.preregistration_checksum():
            guard.deny_preregistration_mutation(
                spec.experiment_id,
                registered_checksum=record["checksum"],
                presented_checksum=spec.preregistration_checksum(),
                detail="the experimental design changed after pre-registration",
            )

    def attach_result(
        self, spec: ExperimentSpec, *, outcome: str, evidence_reference: str, detail: str = ""
    ) -> Dict[str, Any]:
        """Record that a Factory result arrived for this exact frozen design."""
        self.verify(spec)
        if not str(evidence_reference).strip():
            raise PreregistrationError(
                "a result must reference the Factory evidence it came from",
                experiment_id=spec.experiment_id,
            )
        row_id = mint_id("PREGRES", {"e": spec.experiment_id, "o": outcome, "r": evidence_reference})
        row = {
            "record_id": row_id,
            "kind": "result",
            "experiment_id": spec.experiment_id,
            "idea_id": spec.idea_id,
            "checksum": spec.preregistration_checksum(),
            "outcome": outcome,
            "evidence_reference": evidence_reference,
            "detail": detail,
            "recorded_at": self._clock(),
        }
        self.store.append(row)
        return row

    # ----------------------------------------------------------------- read

    def has_result(self, experiment_id: str) -> bool:
        return any(
            r.get("kind") == "result" and r.get("experiment_id") == experiment_id
            for r in self.store.all()
        )

    def results_for(self, experiment_id: str) -> Tuple[Dict[str, Any], ...]:
        return tuple(
            r for r in self.store.all()
            if r.get("kind") == "result" and r.get("experiment_id") == experiment_id
        )

    def registrations(self) -> Tuple[Dict[str, Any], ...]:
        return tuple(r for r in self.store.all() if r.get("kind") != "result")

    def get(self, experiment_id: str) -> Optional[ExperimentSpec]:
        record = self.store.get(experiment_id)
        return ExperimentSpec.from_dict(record["spec"]) if record and "spec" in record else None

    def designs_tried_for_idea(self, idea_id: str) -> int:
        """How many distinct designs this idea has consumed.

        This is the number a multiple-testing correction needs and the number
        that silent amendment would hide.
        """
        return sum(1 for r in self.registrations() if r.get("idea_id") == idea_id)

    def summary(self) -> Dict[str, Any]:
        regs = self.registrations()
        results = [r for r in self.store.all() if r.get("kind") == "result"]
        by_outcome: Dict[str, int] = {}
        for r in results:
            by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
        return {
            "registered": len(regs),
            "amendments": sum(1 for r in regs if r.get("supersedes")),
            "results": len(results),
            "by_outcome": dict(sorted(by_outcome.items())),
            "awaiting_result": len(regs) - len(results),
            "checksum": self.store.checksum(),
        }
