"""Search Decision Ledger (Phase 9, second pass, spec item 7).

Append-only record of every search decision, selected or rejected, with its
full component-score breakdown and reason codes -- never a bare number.
Reuses ``idea_machine.core.store.AppendOnlyStore`` (same refuse-to-shrink,
refuse-to-rewrite discipline as every other Idea Machine ledger).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from idea_machine.core.ids import mint_id
from idea_machine.core.store import DEFAULT_ROOT, AppendOnlyStore
from idea_machine.governance import guard

DEFAULT_LEDGER_PATH = DEFAULT_ROOT / "search_decision_ledger.json"

#: Deterministic version tag for this ledger's scoring formula. Bumped only
#: when the scoring components in search_decision_score.py change shape.
SCORING_VERSION = "SDL-V1"


@dataclass(frozen=True)
class SearchDecisionScore:
    """The seven explainable components, spec item 6 -- never a black-box number."""

    exploration_value: float
    evidence_value: float
    data_availability: float
    economic_value: float
    novelty_value: float
    failure_penalty: float
    redundancy_penalty: float
    power_penalty: float

    @property
    def total(self) -> float:
        return round(
            self.exploration_value + self.evidence_value + self.data_availability
            + self.economic_value + self.novelty_value
            - self.failure_penalty - self.redundancy_penalty - self.power_penalty,
            4,
        )

    def to_dict(self) -> Dict[str, float]:
        return {
            "exploration_value": self.exploration_value, "evidence_value": self.evidence_value,
            "data_availability": self.data_availability, "economic_value": self.economic_value,
            "novelty_value": self.novelty_value, "failure_penalty": self.failure_penalty,
            "redundancy_penalty": self.redundancy_penalty, "power_penalty": self.power_penalty,
            "total": self.total,
        }


class SearchDecisionLedger:
    """Append-only store of every search decision (spec item 7 schema)."""

    def __init__(self, path: Path = DEFAULT_LEDGER_PATH) -> None:
        self.store = AppendOnlyStore(path, id_field="decision_id", kind="search_decision")

    def record(
        self,
        *,
        cycle_id: str,
        region_id: str,
        mode: str,
        selected: bool,
        score: SearchDecisionScore,
        reason_codes: Sequence[str],
        source_evidence: Sequence[str],
        timestamp: str,
    ) -> Dict[str, Any]:
        guard.require("RECORD_DECISION", cycle_id=cycle_id, region_id=region_id, mode=mode)
        row = {
            "cycle_id": cycle_id, "region_id": region_id, "mode": mode, "selected": bool(selected),
            "component_scores": score.to_dict(), "reason_codes": list(reason_codes),
            "source_evidence": list(source_evidence), "timestamp": timestamp,
            "scoring_version": SCORING_VERSION,
        }
        row["decision_id"] = mint_id("SDEC", row)
        return self.store.append(row)

    def all(self) -> List[Dict[str, Any]]:
        return self.store.all()

    def for_cycle(self, cycle_id: str) -> List[Dict[str, Any]]:
        return self.store.where(lambda r: r.get("cycle_id") == cycle_id)

    def get(self, decision_id: str) -> Optional[Dict[str, Any]]:
        return self.store.get(decision_id)

    def verify_integrity(self) -> None:
        self.store.verify_integrity()
