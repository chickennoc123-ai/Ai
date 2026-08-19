"""Generation 4, Phase 23 — Economic Validation Gate.

The EVG's one job is to **consume** evidence. It computes no metric,
executes no trade, resamples nothing, and touches no price series. If a
piece of evidence is missing, the gate does not go and produce it — it
returns ``BLOCKED``, which is a different and more useful answer than a
fabricated verdict.

Four verdicts, kept genuinely distinct:

``PASS``          every required gate is present and each one supports an edge
``FAIL``          every required gate is present and at least one refutes the edge
``INSUFFICIENT``  every required gate is present, none refutes, but the
                  evidence is too thin to support a conclusion either way
``BLOCKED``       a required piece of evidence is missing, malformed, or
                  inconsistent with the frozen candidate; no verdict is possible

The distinction between ``FAIL`` and ``INSUFFICIENT`` is the one that
matters most in practice, and it is decided by whether any gate produced
a *refuting* observation (a negative expectancy that the confidence
interval does not straddle, a profit factor below 1 with enough trades to
mean it) as opposed to merely failing to produce a supporting one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

PASS = "PASS"
FAIL = "FAIL"
INSUFFICIENT = "INSUFFICIENT"
BLOCKED = "BLOCKED"

#: The evidence chain the gate requires, in the order the Generation 4
#: contract specifies. Every one must be present; the gate will not
#: proceed on a partial chain.
REQUIRED_EVIDENCE = (
    "REAL_DATA",
    "DATA_INTEGRITY",
    "LEAKAGE_AUDIT",
    "TARGET_AUDIT",
    "CANDIDATE_FREEZE",
    "TRAINING",
    "DEVELOPMENT_EVALUATION",
    "HOLDOUT",
    "OOS",
    "WFA",
    "ROBUSTNESS",
    "COST_STRESS",
    "STATISTICS",
    "MULTIPLE_TESTING",
)


class EVGEvidenceError(EAFactoryError):
    """Raised when the evidence chain is structurally unusable."""


@dataclass(frozen=True)
class EvidenceItem:
    """One piece of evidence presented to the gate.

    ``verdict`` is the producing module's own verdict; ``checksum`` is
    that module's own report checksum. The gate stores both and never
    recomputes either — recomputation would mean the gate was deriving
    evidence rather than consuming it.
    """

    name: str
    verdict: str
    checksum: str
    artifact_reference: str
    candidate_id: str
    validation_run_id: str
    summary: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for f in ("name", "verdict", "checksum", "artifact_reference", "candidate_id", "validation_run_id"):
            if not str(getattr(self, f) or "").strip():
                raise EVGEvidenceError("evidence item is incomplete", field=f, name=self.name)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EVGReport:
    candidate_id: str
    validation_run_id: str
    candidate_checksum: str
    snapshot_checksum: str
    verdict: str
    verdict_basis: str
    evidence_present: tuple
    evidence_missing: tuple
    evidence: tuple
    refuting_observations: tuple
    supporting_observations: tuple
    insufficiency_observations: tuple
    blocking_reasons: tuple
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        for key in (
            "evidence_present", "evidence_missing", "evidence",
            "refuting_observations", "supporting_observations",
            "insufficiency_observations", "blocking_reasons",
        ):
            d[key] = list(getattr(self, key))
        return d

    def report_checksum(self) -> str:
        d = self.to_dict()
        d.pop("timestamp", None)
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def run_evg(
    evidence: List[EvidenceItem],
    *,
    candidate_id: str,
    validation_run_id: str,
    candidate_checksum: str,
    snapshot_checksum: str,
    required: tuple = REQUIRED_EVIDENCE,
) -> EVGReport:
    """Evaluate the gate. Consumes only what is handed to it."""
    blocking: List[str] = []
    by_name: Dict[str, EvidenceItem] = {}

    for item in evidence:
        if item.name in by_name:
            blocking.append(
                f"evidence '{item.name}' was presented more than once; the gate will not choose between duplicates"
            )
            continue
        if item.candidate_id != candidate_id:
            blocking.append(
                f"evidence '{item.name}' is for candidate {item.candidate_id}, not {candidate_id}"
            )
            continue
        if item.validation_run_id != validation_run_id:
            blocking.append(
                f"evidence '{item.name}' belongs to validation run {item.validation_run_id}, "
                f"not {validation_run_id} -- evidence may not be mixed across runs"
            )
            continue
        by_name[item.name] = item

    present = tuple(n for n in required if n in by_name)
    missing = tuple(n for n in required if n not in by_name)
    if missing:
        blocking.append(f"required evidence missing: {', '.join(missing)}")

    unknown = sorted(set(by_name) - set(required))
    extra_note = f" (also received non-required evidence: {', '.join(unknown)})" if unknown else ""

    refuting: List[str] = []
    supporting: List[str] = []
    insufficiency: List[str] = []

    for name, item in by_name.items():
        verdict = item.verdict.upper()
        if verdict in ("FAIL", "REFUTED", "INELIGIBLE", "NOT_SUPPORTED", "ZERO_COST_DEPENDENT"):
            refuting.append(f"{name}: {item.verdict} -- {item.summary.get('reason', 'see artifact')}")
        elif verdict in ("INSUFFICIENT", "MARGINAL", "UNDETERMINED", "NEARLY_UNINFORMATIVE"):
            insufficiency.append(f"{name}: {item.verdict} -- {item.summary.get('reason', 'see artifact')}")
        elif verdict in ("PASS", "SUPPORTED", "ELIGIBLE", "SURVIVES_COSTS"):
            supporting.append(f"{name}: {item.verdict}")
        else:
            blocking.append(
                f"evidence '{name}' carries verdict '{item.verdict}', which the gate does not "
                "recognise; it will not guess whether that supports or refutes"
            )

    if blocking:
        verdict = BLOCKED
        basis = (
            "The evidence chain could not be evaluated. A gate that produced a PASS/FAIL here would be "
            "asserting something the evidence does not say."
            + extra_note
        )
    elif refuting:
        verdict = FAIL
        basis = (
            f"{len(refuting)} gate(s) produced refuting evidence against the frozen candidate. "
            "The complete chain was present, so this is a conclusion, not a gap." + extra_note
        )
    elif insufficiency:
        verdict = INSUFFICIENT
        basis = (
            f"No gate refuted the candidate, but {len(insufficiency)} gate(s) reported evidence too "
            "thin to support a conclusion. Absence of refutation is not support." + extra_note
        )
    else:
        verdict = PASS
        basis = (
            "Every required gate was present and each supported the candidate. This is a statement "
            "about historical evidence under the frozen specification only." + extra_note
        )

    return EVGReport(
        candidate_id=candidate_id,
        validation_run_id=validation_run_id,
        candidate_checksum=candidate_checksum,
        snapshot_checksum=snapshot_checksum,
        verdict=verdict,
        verdict_basis=basis,
        evidence_present=present,
        evidence_missing=missing,
        evidence=tuple(by_name[n].to_dict() for n in sorted(by_name)),
        refuting_observations=tuple(refuting),
        supporting_observations=tuple(supporting),
        insufficiency_observations=tuple(insufficiency),
        blocking_reasons=tuple(blocking),
        timestamp=utcnow().isoformat(),
    )
