"""
Provenance: the 5-stage evidence ladder every EA-Code-Intelligence-derived
hypothesis must climb, one rung at a time, with each rung earned by a real
event -- never self-declared.

  SOURCE_ONLY         -- raw mined material (a repo, a README, a forum post).
                         No claim about markets has been made yet.
  DERIVED_HYPOTHESIS  -- a falsifiable, testable prediction was synthesized
                         from Strategy DNA. Still zero market evidence.
  DATA_SUPPORTED      -- the hypothesis was run through the real Factory
                         internal-validation gate on dev data and produced
                         SOME quantitative result (pass or fail). This stage
                         means "we looked," not "it worked."
  FACTORY_TESTED      -- the hypothesis passed internal validation AND was
                         run through GEN 12 adversarial. Still pre-holdout.
  SURVIVOR            -- passed GEN 12 and was granted GEN 14 sealed-holdout
                         authorization by the existing holdout_authorization
                         gate, with a recorded PASS. This is the only stage
                         that is ever legitimate grounds for productization,
                         and even then the EA must still be labeled
                         EXPERIMENTAL/UNRESOLVED per this project's existing
                         productization rules.

Transitions are one-way and one-step: this class raises if code tries to
skip a rung or move backward implicitly. It does NOT talk to the Factory
itself -- it only records what the caller asserts happened, so it is the
caller's responsibility to have actually run the gate before calling
advance(). This module's only enforcement is structural (no skipping), not
evidentiary (it cannot itself verify a claimed Factory result is real) --
that verification is the job of whatever populates the FactoryGateResult
this class is given.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional


class Stage(Enum):
    SOURCE_ONLY = 0
    DERIVED_HYPOTHESIS = 1
    DATA_SUPPORTED = 2
    FACTORY_TESTED = 3
    SURVIVOR = 4


class ProvenanceViolation(RuntimeError):
    """Raised when code attempts to skip a stage or self-declare SURVIVOR."""


@dataclass
class ProvenanceEvent:
    from_stage: str
    to_stage: str
    reason: str
    timestamp: str


@dataclass
class ProvenanceTracker:
    entity_id: str
    stage: Stage = Stage.SOURCE_ONLY
    history: List[ProvenanceEvent] = field(default_factory=list)

    def advance(self, to_stage: Stage, reason: str):
        expected_next = Stage(self.stage.value + 1)
        if to_stage != expected_next:
            raise ProvenanceViolation(
                f"{self.entity_id}: cannot advance {self.stage.name} -> {to_stage.name}; "
                f"only {expected_next.name} is a legal next stage. No skipping, no self-declared edges."
            )
        self.history.append(ProvenanceEvent(
            from_stage=self.stage.name, to_stage=to_stage.name, reason=reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))
        self.stage = to_stage

    def to_derived_hypothesis(self, reason: str):
        self.advance(Stage.DERIVED_HYPOTHESIS, reason)

    def to_data_supported(self, factory_cycle_file: str, verdict: str):
        """Requires evidence: the actual cycle file and verdict string that produced this transition."""
        if not factory_cycle_file or not verdict:
            raise ProvenanceViolation(
                f"{self.entity_id}: DATA_SUPPORTED requires a real factory_cycle_file and verdict"
            )
        self.advance(Stage.DATA_SUPPORTED,
                    f"Factory internal-validation run recorded in {factory_cycle_file}: {verdict}")

    def to_factory_tested(self, gen12_result: str):
        if "PASS" not in gen12_result.upper() and "SURVIV" not in gen12_result.upper():
            raise ProvenanceViolation(
                f"{self.entity_id}: FACTORY_TESTED requires a passing GEN12 result, got: {gen12_result}"
            )
        self.advance(Stage.FACTORY_TESTED, f"GEN12 adversarial result: {gen12_result}")

    def to_survivor(self, gen14_evidence_vault_ref: str):
        if not gen14_evidence_vault_ref:
            raise ProvenanceViolation(
                f"{self.entity_id}: SURVIVOR requires a real evidence_vault.json reference "
                f"from an actual GEN14 sealed-holdout authorization and PASS"
            )
        self.advance(Stage.SURVIVOR, f"GEN14 sealed-holdout PASS, evidence_vault ref: {gen14_evidence_vault_ref}")

    def current_label(self) -> str:
        return self.stage.name
