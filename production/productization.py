"""Productization gate: Factory SURVIVOR -> (GEN12->GEN13->GEN14) -> EA.

This module makes NO qualification decision itself. It defers entirely to
the existing, real, holdout-gated pipeline:
  ea_generator.EAGenerator._require_qualified() -- refuses to package
  anything unless the candidate's specification is frozen AND it carries a
  terminal GEN14 result AND that result is PASS.

UNDERPOWERED / PROMISING / HIGH_SCORE / TRAIN_ONLY candidates never reach
this function with anything to package -- ea_generator's own gate raises
UnqualifiedCandidateError for every one of them, and that is treated here as
the correct, expected outcome (recorded as NOT_AUTHORIZED), never worked
around.

Lives outside idea_machine/ deliberately: idea_machine's own
FORBIDDEN_IMPORTS bars it from ever importing ea_generator, qualification,
or discovery.holdout_authorization -- the Idea Machine researches, it does
not authorize or productize. This module has the authority the Idea Machine
structurally does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from discovery.candidate_spec_registry import CandidateSpecRegistry
from discovery.holdout_authorization import HoldoutAuthorizationGate
from ea_generator.generator import EAGenerator, UnqualifiedCandidateError

from production.ea_registry import EAProductRegistry

DEFAULT_ARTIFACT_DIR = Path("reports/production/ea_products")

NOT_AUTHORIZED = "NOT_AUTHORIZED"
PRODUCTIZED = "PRODUCTIZED"


@dataclass(frozen=True)
class ProductizationResult:
    candidate_id: str
    status: str  # NOT_AUTHORIZED | PRODUCTIZED
    reason: str
    product_id: Optional[str] = None
    artifact_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id, "status": self.status, "reason": self.reason,
            "product_id": self.product_id, "artifact_path": self.artifact_path,
        }


def maybe_productize(
    candidate_id: str, *, symbol: str, hypothesis_id: str = "", factory_evaluation_id: str = "",
    source: str = "production_loop",
    registry: Optional[EAProductRegistry] = None,
    artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
) -> ProductizationResult:
    """Attempt to productize a candidate. Only ever succeeds if the candidate
    already carries a real, terminal GEN14 PASS -- checked by ea_generator's
    own gate, not re-implemented here.
    """
    ea_registry = registry or EAProductRegistry()
    spec_registry = CandidateSpecRegistry()
    holdout_gate = HoldoutAuthorizationGate()
    generator = EAGenerator(spec_registry, holdout_gate)

    try:
        package = generator.package(candidate_id, symbol, artifact_dir)
    except UnqualifiedCandidateError as exc:
        return ProductizationResult(candidate_id=candidate_id, status=NOT_AUTHORIZED, reason=str(exc))

    row = ea_registry.register(
        candidate_id=candidate_id, hypothesis_id=hypothesis_id,
        factory_evaluation_id=factory_evaluation_id, spec_hash=package.spec_hash,
        source=source, artifact_path=str(artifact_dir / candidate_id),
    )
    return ProductizationResult(
        candidate_id=candidate_id, status=PRODUCTIZED, reason="GEN14 PASS, packaged",
        product_id=row["product_id"], artifact_path=row["artifact_path"],
    )
