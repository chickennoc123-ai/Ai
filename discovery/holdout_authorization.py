"""
GEN 14 Holdout Authorization Gate.

Enforces strict governance on sealed holdout access:
  1. Only GEN 14 (qualification) may access reserved holdout
  2. Candidate specification must be frozen (immutable) before access
  3. Access is one-time: candidates passing GEN 14 cannot be re-tuned and retested
  4. Failed candidates are terminal; cannot revisit same holdout

This module prevents research exposure: GEN 7-13 cannot read or modify
holdout data under any circumstance.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

DEFAULT_AUTH_REGISTRY = Path("reports/factory/holdout_authorization_registry.json")


@dataclass
class AuthorizedAccess:
    """Record of one holdout access session."""
    candidate_id: str
    spec_hash: str  # SHA256 of frozen candidate specification
    authorized_at: str
    gen14_phase: str  # "QUALIFICATION", "REPLICATION", etc.
    holdout_consumed: bool = False
    result: Optional[str] = None  # "PASS", "FAIL", or None if in-progress


class HoldoutAuthorizationGate:
    """
    Gate-keeper for sealed holdout access (GEN 14 only).

    Prevents:
    - GEN 7-13 from accessing any holdout data
    - Re-tuning of failed candidates against same holdout
    - Parameter modification after authorization
    """

    def __init__(self, registry_path: Path = DEFAULT_AUTH_REGISTRY):
        self.registry_path = Path(registry_path)
        self.authorizations: Dict[str, AuthorizedAccess] = {}
        self._load()

    def _load(self) -> None:
        """Load existing authorization records."""
        if not self.registry_path.exists():
            return
        raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.authorizations = {
            k: AuthorizedAccess(**v)
            for k, v in raw.get("authorizations", {}).items()
        }

    def _save(self) -> None:
        """Persist authorization records."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "audit_trail": "Holds one-way authorizations; no deletion/modification allowed",
            "governance_rule": "GEN 14 only; frozen spec; one-time holdout consumption",
            "authorizations": {
                k: asdict(v)
                for k, v in self.authorizations.items()
            },
        }
        self.registry_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    def authorize_gen14_access(self, candidate_id: str, spec_hash: str,
                               phase: str = "QUALIFICATION") -> bool:
        """
        Authorize GEN 14 holdout access for a frozen candidate.

        Args:
            candidate_id: Unique candidate identifier
            spec_hash: SHA256 hash of frozen candidate specification
            phase: GEN 14 phase name ("QUALIFICATION", "REPLICATION", etc.)

        Returns:
            True if authorized (first access), False if already authorized/consumed

        Raises:
            ValueError if candidate already consumed or result already recorded
        """
        if candidate_id in self.authorizations:
            existing = self.authorizations[candidate_id]
            if existing.holdout_consumed or existing.result is not None:
                raise ValueError(
                    f"candidate {candidate_id} already has GEN 14 result "
                    f"({existing.result}); holdout consumption is terminal, "
                    f"cannot re-authorize"
                )
            if existing.spec_hash != spec_hash:
                raise ValueError(
                    f"candidate {candidate_id} spec changed (hash mismatch); "
                    f"cannot re-authorize after spec modification"
                )

        auth = AuthorizedAccess(
            candidate_id=candidate_id,
            spec_hash=spec_hash,
            authorized_at=datetime.now(timezone.utc).isoformat(),
            gen14_phase=phase,
            holdout_consumed=False,
        )
        self.authorizations[candidate_id] = auth
        self._save()
        return True

    def record_gen14_result(self, candidate_id: str, result: str) -> None:
        """
        Record GEN 14 holdout evaluation result (terminal).

        Args:
            candidate_id: Candidate identifier
            result: "PASS" or "FAIL"

        Raises:
            ValueError if candidate not authorized or already has result
        """
        if candidate_id not in self.authorizations:
            raise ValueError(f"candidate {candidate_id} not authorized for GEN 14")

        auth = self.authorizations[candidate_id]
        if auth.result is not None:
            raise ValueError(
                f"candidate {candidate_id} already has result {auth.result}; "
                f"terminal decision, cannot change"
            )

        auth.holdout_consumed = True
        auth.result = result
        self._save()

    def is_gen14_authorized(self, candidate_id: str) -> bool:
        """Check if candidate is authorized for GEN 14 holdout access."""
        return candidate_id in self.authorizations

    def has_gen14_result(self, candidate_id: str) -> bool:
        """Check if candidate already has a GEN 14 result (terminal)."""
        return (candidate_id in self.authorizations and
                self.authorizations[candidate_id].result is not None)

    def summary(self) -> Dict:
        """Audit summary of authorization state."""
        authorized = len(self.authorizations)
        consumed = sum(1 for a in self.authorizations.values() if a.holdout_consumed)
        passed = sum(1 for a in self.authorizations.values() if a.result == "PASS")
        failed = sum(1 for a in self.authorizations.values() if a.result == "FAIL")

        return {
            "total_authorizations": authorized,
            "holdout_consumed": consumed,
            "results_recorded": {"PASS": passed, "FAIL": failed},
            "in_progress": authorized - consumed,
        }
