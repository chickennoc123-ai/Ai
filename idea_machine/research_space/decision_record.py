"""DecisionRecord: every important decision, explainable on demand (spec item 12).

Answers "why did the machine test this?" without a bare score. Stored in its
own append-only store (reusing ``AppendOnlyStore``, not a new engine) so
``explain <decision_id>`` can look one up deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from idea_machine.core.ids import mint_id
from idea_machine.core.store import DEFAULT_ROOT, AppendOnlyStore
from idea_machine.governance import guard

DEFAULT_DECISION_LOG_PATH = DEFAULT_ROOT / "decision_records.json"


@dataclass(frozen=True)
class DecisionRecord:
    cycle_id: str
    decision: str                      # e.g. "EXPLORE", "EXPLOIT", "REJECT", "PROPOSE_CLOSURE"
    target: str                        # candidate_id or family/dimension name
    reason: str
    evidence: Sequence[str]
    alternatives_considered: Sequence[str]
    score_breakdown: Dict[str, Any]
    confidence: str                    # "LOW" | "MEDIUM" | "HIGH"
    reversible: bool
    decision_id: str = field(default="")

    def __post_init__(self) -> None:
        if self.confidence not in ("LOW", "MEDIUM", "HIGH"):
            raise ValueError(f"unknown confidence {self.confidence!r}")
        if not self.reason.strip():
            raise ValueError("DecisionRecord.reason is required -- an unexplained decision is not recorded")
        if not self.decision_id:
            object.__setattr__(self, "decision_id", mint_id("DEC", {
                "cycle": self.cycle_id, "decision": self.decision, "target": self.target,
                "reason": self.reason, "evidence": list(self.evidence),
            }))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "cycle_id": self.cycle_id,
            "decision": self.decision,
            "target": self.target,
            "reason": self.reason,
            "evidence": list(self.evidence),
            "alternatives_considered": list(self.alternatives_considered),
            "score_breakdown": dict(self.score_breakdown),
            "confidence": self.confidence,
            "reversible": self.reversible,
        }


class DecisionLedger:
    """Append-only store of every DecisionRecord ever made."""

    def __init__(self, path: Path = DEFAULT_DECISION_LOG_PATH) -> None:
        self.store = AppendOnlyStore(path, id_field="decision_id", kind="decision_record")

    def record(self, decision: DecisionRecord) -> Dict[str, Any]:
        guard.require("RECORD_DECISION", decision_id=decision.decision_id, decision=decision.decision)
        return self.store.append(decision.to_dict())

    def get(self, decision_id: str) -> Optional[Dict[str, Any]]:
        return self.store.get(decision_id)

    def all(self) -> List[Dict[str, Any]]:
        return self.store.all()

    def for_cycle(self, cycle_id: str) -> List[Dict[str, Any]]:
        return self.store.where(lambda r: r.get("cycle_id") == cycle_id)
