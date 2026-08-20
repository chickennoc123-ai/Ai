"""
Candidate Specification Registry (GEN 7-14).

Maintains immutable snapshots of candidate specifications at freeze time.
Prevents parameter modification after GEN 14 authorization (holdout access).

Governance rule:
  Before GEN 14 holdout access:
    - Candidate spec is mutable during GEN 7-13 research
  After GEN 14 authorization:
    - Spec becomes frozen (read-only)
    - Any modification attempt raises FrozenSpecViolation
    - Failure memory cannot re-tune and reuse same holdout
"""

import hashlib
import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Any

DEFAULT_SPEC_REGISTRY = Path("reports/factory/candidate_spec_registry.json")


class FrozenSpecViolation(RuntimeError):
    """Raised when attempting to modify a frozen candidate specification."""


@dataclass
class CandidateSpec:
    """Immutable specification snapshot."""
    candidate_id: str
    mechanism: str
    parameters: Dict[str, Any]  # e.g., {"k": 3, "horizon": 4, "hours": [9, 10]}
    test_framework: str  # e.g., "streak_fade", "gap_continuation"
    created_at: str
    frozen_at: Optional[str] = None
    spec_hash: str = ""

    def compute_hash(self) -> str:
        """Compute stable SHA256 hash of this spec (deterministic)."""
        canonical = json.dumps(
            {
                "candidate_id": self.candidate_id,
                "mechanism": self.mechanism,
                "parameters": self.parameters,
                "test_framework": self.test_framework,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def is_frozen(self) -> bool:
        """Check if spec is frozen (immutable)."""
        return self.frozen_at is not None

    def to_dict(self) -> Dict:
        return asdict(self)


class CandidateSpecRegistry:
    """
    Maintains candidate specifications with freeze gates.
    Once frozen for GEN 14, modifications are forbidden.
    """

    def __init__(self, registry_path: Path = DEFAULT_SPEC_REGISTRY):
        self.registry_path = Path(registry_path)
        self.specs: Dict[str, CandidateSpec] = {}
        self._load()

    def _load(self) -> None:
        """Load existing spec registry."""
        if not self.registry_path.exists():
            return
        raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.specs = {
            k: CandidateSpec(**v)
            for k, v in raw.get("candidates", {}).items()
        }

    def _save(self) -> None:
        """Persist registry."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "audit": "Candidate specs with freeze gates; locked at GEN 14 authorization",
            "candidates": {k: v.to_dict() for k, v in self.specs.items()},
        }
        self.registry_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    def register_candidate(self, candidate_id: str, mechanism: str,
                          parameters: Dict[str, Any],
                          test_framework: str) -> CandidateSpec:
        """
        Register a new candidate specification (GEN 7-13).

        Spec is mutable until frozen at GEN 14 authorization.
        """
        if candidate_id in self.specs:
            raise ValueError(f"candidate {candidate_id} already registered")

        spec = CandidateSpec(
            candidate_id=candidate_id,
            mechanism=mechanism,
            parameters=parameters,
            test_framework=test_framework,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        spec.spec_hash = spec.compute_hash()
        self.specs[candidate_id] = spec
        self._save()
        return spec

    def update_candidate(self, candidate_id: str,
                        parameters: Optional[Dict[str, Any]] = None,
                        mechanism: Optional[str] = None) -> CandidateSpec:
        """
        Update candidate parameters/mechanism (GEN 7-13 only, before freeze).

        Raises:
            ValueError if candidate not found
            FrozenSpecViolation if already frozen for GEN 14
        """
        if candidate_id not in self.specs:
            raise ValueError(f"candidate {candidate_id} not registered")

        spec = self.specs[candidate_id]
        if spec.is_frozen():
            raise FrozenSpecViolation(
                f"candidate {candidate_id} is frozen (GEN 14 authorized); "
                f"cannot modify parameters or mechanism. "
                f"Failed candidates are terminal; cannot reuse same holdout."
            )

        if parameters is not None:
            spec.parameters = parameters
        if mechanism is not None:
            spec.mechanism = mechanism

        spec.spec_hash = spec.compute_hash()
        self._save()
        return spec

    def freeze_candidate(self, candidate_id: str) -> CandidateSpec:
        """
        Freeze candidate spec for GEN 14 authorization (immutable thereafter).

        Once frozen, spec becomes read-only. No parameter modifications allowed.
        """
        if candidate_id not in self.specs:
            raise ValueError(f"candidate {candidate_id} not registered")

        spec = self.specs[candidate_id]
        if spec.is_frozen():
            raise ValueError(f"candidate {candidate_id} already frozen")

        spec.frozen_at = datetime.now(timezone.utc).isoformat()
        spec.spec_hash = spec.compute_hash()
        self._save()
        return spec

    def get_candidate(self, candidate_id: str) -> Optional[CandidateSpec]:
        """Retrieve candidate specification (read-only)."""
        return self.specs.get(candidate_id)

    def get_hash(self, candidate_id: str) -> Optional[str]:
        """Get spec hash for authorization matching."""
        spec = self.specs.get(candidate_id)
        return spec.spec_hash if spec else None

    def summary(self) -> Dict:
        """Summary of spec registry state."""
        total = len(self.specs)
        frozen = sum(1 for s in self.specs.values() if s.is_frozen())
        mutable = total - frozen

        return {
            "total_candidates": total,
            "frozen_for_gen14": frozen,
            "still_mutable": mutable,
        }
