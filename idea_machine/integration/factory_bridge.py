"""Strategy Factory integration (Phase 11) — the one and only hand-off.

    Idea Machine -> ExperimentSpec -> Strategy Factory

That is the whole interface. The Factory then runs its own sequence — discovery,
OOS, WFA, robustness, cost, statistics, multiple testing, GEN12, GEN13, GEN14,
EA — and the Idea Machine touches none of it.

What this module does:

* **Submits** a frozen, pre-registered ExperimentSpec, and refuses to submit one
  that is not both.
* **Receives** a :class:`FactoryResult` and validates that it refers to a real
  submission. It does not interpret, re-score, or re-run anything.

What this module deliberately cannot do: read the holdout, request GEN14
authorization, generate an EA, or skip a gate. Those have no functions here,
the forbidden-import audit blocks reaching for the modules that could, and the
``request_*`` methods below exist only to convert an attempt into a crash.

The submission mechanism itself is a pluggable :class:`FactorySubmitter`. The
default is :class:`FileHandoffSubmitter`, which writes the spec to a directory
the Factory reads. Nothing here invokes the Factory's pipeline in-process,
because a research generator that can call the validator directly is one
refactor away from being able to influence it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from idea_machine.core.errors import IdeaMachineError
from idea_machine.core.ids import content_hash, mint_id
from idea_machine.core.store import DEFAULT_ROOT, AppendOnlyStore
from idea_machine.experiment.prereg import PreregistrationLedger
from idea_machine.experiment.spec import ExperimentSpec
from idea_machine.governance import guard
from utils.helpers import isoformat

DEFAULT_SUBMISSION_LEDGER = DEFAULT_ROOT / "factory_submissions.json"
DEFAULT_HANDOFF_DIR = DEFAULT_ROOT / "handoff"

#: Verdicts the Factory can return. These are the Factory's words, not ours.
FACTORY_VERDICTS = frozenset({"SURVIVOR", "FAIL", "BLOCKED", "UNDERPOWERED", "REFUTED"})


class BridgeError(IdeaMachineError):
    """A submission or result is malformed."""


@dataclass(frozen=True)
class FactoryResult:
    """A verdict handed back by the Strategy Factory.

    Carries an ``evidence_reference`` — a pointer into the Factory's own
    reports — rather than the numbers themselves. The Idea Machine does not
    need the numbers to learn from the outcome, and not carrying them is what
    keeps holdout performance out of the research-targeting loop.
    """

    experiment_id: str
    idea_id: str
    verdict: str
    evidence_reference: str
    reason: str
    reported_at: str = ""
    gates_completed: Tuple[str, ...] = field(default_factory=tuple)
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.verdict not in FACTORY_VERDICTS:
            raise BridgeError(
                "unknown Factory verdict", verdict=self.verdict, allowed=sorted(FACTORY_VERDICTS)
            )
        for name in ("experiment_id", "idea_id", "evidence_reference"):
            if not str(getattr(self, name)).strip():
                raise BridgeError(f"FactoryResult.{name} is required")
        object.__setattr__(self, "gates_completed", tuple(self.gates_completed))
        object.__setattr__(self, "detail", dict(self.detail))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "idea_id": self.idea_id,
            "verdict": self.verdict,
            "evidence_reference": self.evidence_reference,
            "reason": self.reason,
            "reported_at": self.reported_at,
            "gates_completed": list(self.gates_completed),
            "detail": dict(self.detail),
        }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "FactoryResult":
        return FactoryResult(
            experiment_id=d["experiment_id"],
            idea_id=d["idea_id"],
            verdict=d["verdict"],
            evidence_reference=d["evidence_reference"],
            reason=d.get("reason", ""),
            reported_at=d.get("reported_at", ""),
            gates_completed=tuple(d.get("gates_completed", ())),
            detail=dict(d.get("detail", {})),
        )


class FactorySubmitter:
    """How a spec physically reaches the Factory."""

    name = "submitter"

    def submit(self, spec: ExperimentSpec) -> str:
        """Deliver ``spec`` and return a handle the Factory can be pointed at."""
        raise NotImplementedError


@dataclass
class FileHandoffSubmitter(FactorySubmitter):
    """Writes each spec as JSON into a directory the Factory reads.

    Chosen over an in-process call on purpose: a one-directional, file-shaped
    boundary is one the Idea Machine cannot reach back through.
    """

    directory: Path = DEFAULT_HANDOFF_DIR
    name: str = "file_handoff"

    def submit(self, spec: ExperimentSpec) -> str:
        path = Path(self.directory) / f"{spec.experiment_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "experiment": spec.to_dict(),
            "preregistration_checksum": spec.preregistration_checksum(),
            "submitted_by": "idea_machine",
            "note": (
                "This is a pre-registered research proposal. Every Strategy Factory gate applies "
                "unchanged; the Idea Machine asserts nothing about this idea's validity."
            ),
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        return str(path)


@dataclass
class InMemorySubmitter(FactorySubmitter):
    """Collects submissions in a list. Used by tests."""

    submissions: List[ExperimentSpec] = field(default_factory=list)
    name: str = "in_memory"

    def submit(self, spec: ExperimentSpec) -> str:
        self.submissions.append(spec)
        return f"memory://{spec.experiment_id}"


class FactoryBridge:
    """The Idea Machine's only door to the Strategy Factory."""

    def __init__(
        self,
        prereg: PreregistrationLedger,
        *,
        submitter: Optional[FactorySubmitter] = None,
        ledger_path: Path = DEFAULT_SUBMISSION_LEDGER,
        clock=isoformat,
    ) -> None:
        self.prereg = prereg
        self.submitter = submitter or FileHandoffSubmitter()
        self.store = AppendOnlyStore(ledger_path, id_field="row_id", kind="factory_submission")
        self._clock = clock

    # -------------------------------------------------------------- submit

    def submit(self, spec: ExperimentSpec) -> Dict[str, Any]:
        """Hand a frozen, pre-registered experiment to the Factory."""
        guard.require("SUBMIT_TO_FACTORY", experiment_id=spec.experiment_id)

        if not spec.frozen:
            raise BridgeError(
                "only a frozen experiment may be submitted -- an unfrozen design can still be "
                "edited after the Factory reports back",
                experiment_id=spec.experiment_id,
            )
        # Raises (or crashes, on a checksum mismatch) if this is not exactly
        # what was pre-registered.
        self.prereg.verify(spec)

        handle = self.submitter.submit(spec)
        row = {
            "row_id": mint_id("SUB", {"e": spec.experiment_id, "h": handle}),
            "kind": "submission",
            "experiment_id": spec.experiment_id,
            "idea_id": spec.idea_id,
            "checksum": spec.preregistration_checksum(),
            "handle": handle,
            "submitter": self.submitter.name,
            "submitted_at": self._clock(),
        }
        self.store.append(row)
        return row

    # -------------------------------------------------------------- receive

    def receive(self, result: FactoryResult) -> Dict[str, Any]:
        """Record a Factory verdict against a real submission."""
        guard.require("READ_FACTORY_RESULT", experiment_id=result.experiment_id)

        submission = self._submission_for(result.experiment_id)
        if submission is None:
            raise BridgeError(
                "received a result for an experiment that was never submitted",
                experiment_id=result.experiment_id,
            )
        if submission["idea_id"] != result.idea_id:
            raise BridgeError(
                "result idea_id does not match the submitted experiment",
                experiment_id=result.experiment_id,
                submitted=submission["idea_id"],
                reported=result.idea_id,
            )

        spec = self.prereg.get(result.experiment_id)
        if spec is None:
            raise BridgeError("no pre-registration for this experiment", experiment_id=result.experiment_id)
        self.prereg.attach_result(
            spec,
            outcome=result.verdict,
            evidence_reference=result.evidence_reference,
            detail=result.reason,
        )

        row = {
            "row_id": mint_id("RES", {"e": result.experiment_id, "v": result.verdict, "r": result.evidence_reference}),
            "kind": "result",
            **result.to_dict(),
            "reported_at": result.reported_at or self._clock(),
            "result_hash": content_hash(result.to_dict()),
        }
        self.store.append(row)
        return row

    def _submission_for(self, experiment_id: str) -> Optional[Dict[str, Any]]:
        for row in self.store.all():
            if row.get("kind") == "submission" and row.get("experiment_id") == experiment_id:
                return row
        return None

    # ------------------------------------------------------- forbidden doors

    def request_holdout(self, *_: Any, **__: Any) -> None:
        """Forbidden. Exists so the attempt crashes instead of being written."""
        guard.deny_holdout_access(detail="FactoryBridge.request_holdout")

    def authorize_gen14(self, *_: Any, **__: Any) -> None:
        """Forbidden. GEN14 authorization is human authority."""
        guard.deny_gen14_authorization(detail="FactoryBridge.authorize_gen14")

    def generate_ea(self, *_: Any, **__: Any) -> None:
        """Forbidden. Producing a deployable EA is not a research action."""
        guard.deny_ea_creation(detail="FactoryBridge.generate_ea")

    def skip_gate(self, gate: str, *_: Any, **__: Any) -> None:
        """Forbidden. Every gate exists because something once got through."""
        guard.forbid("BYPASS_FACTORY_GATE", gate=gate)

    # ------------------------------------------------------------------ read

    def submissions(self) -> Tuple[Dict[str, Any], ...]:
        return tuple(r for r in self.store.all() if r.get("kind") == "submission")

    def results(self) -> Tuple[FactoryResult, ...]:
        return tuple(
            FactoryResult.from_dict(r) for r in self.store.all() if r.get("kind") == "result"
        )

    def pending(self) -> Tuple[str, ...]:
        done = {r.experiment_id for r in self.results()}
        return tuple(sorted(s["experiment_id"] for s in self.submissions() if s["experiment_id"] not in done))

    def summary(self) -> Dict[str, Any]:
        results = self.results()
        by_verdict: Dict[str, int] = {}
        for r in results:
            by_verdict[r.verdict] = by_verdict.get(r.verdict, 0) + 1
        return {
            "submitted": len(self.submissions()),
            "results": len(results),
            "pending": len(self.pending()),
            "by_verdict": dict(sorted(by_verdict.items())),
            "submitter": self.submitter.name,
        }
