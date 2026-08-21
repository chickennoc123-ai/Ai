"""Append-only exploration ledger (spec item 24).

Reuses ``idea_machine.core.store.AppendOnlyStore`` directly -- the same
refuse-to-shrink, refuse-to-rewrite-a-record discipline the rest of the Idea
Machine already relies on. No new storage engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from idea_machine.core.ids import mint_id
from idea_machine.core.store import DEFAULT_ROOT, AppendOnlyStore

DEFAULT_LEDGER_PATH = DEFAULT_ROOT / "research_space_ledger.json"


class SearchSpaceLedger:
    """Append-only record of every cycle/mode/hypothesis/decision/result."""

    def __init__(self, path: Path = DEFAULT_LEDGER_PATH) -> None:
        self.store = AppendOnlyStore(path, id_field="row_id", kind="research_space_ledger")

    def record(
        self,
        *,
        cycle_id: str,
        research_mode: str,
        family: str,
        hypothesis: str,
        decision: str,
        reason: str,
        score_breakdown: Optional[Dict[str, Any]] = None,
        result: str = "",
        information_gain: float = 0.0,
        touched_new_family_or_dimension: bool = False,
    ) -> Dict[str, Any]:
        row = {
            "cycle_id": cycle_id,
            "research_mode": research_mode,
            "family": family,
            "hypothesis": hypothesis,
            "decision": decision,
            "reason": reason,
            "score_breakdown": dict(score_breakdown or {}),
            "result": result,
            "information_gain": information_gain,
            "touched_new_family_or_dimension": touched_new_family_or_dimension,
        }
        row["row_id"] = mint_id("RSL", row)
        return self.store.append(row)

    def all(self) -> List[Dict[str, Any]]:
        return self.store.all()

    def for_cycle(self, cycle_id: str) -> List[Dict[str, Any]]:
        return self.store.where(lambda r: r.get("cycle_id") == cycle_id)

    def verify_integrity(self) -> None:
        self.store.verify_integrity()
