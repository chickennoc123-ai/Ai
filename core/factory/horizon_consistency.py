"""Horizon consistency audit — Generation 5, Phase 12.

Compares the horizon implied at each lineage stage (source claim,
hypothesis, candidate/target, holding period) and classifies any
difference as either an ``EXPLICIT_MECHANISTIC_TRANSFORMATION`` (recorded,
with a stated reason) or ``SILENT_HORIZON_DRIFT`` (not recorded anywhere
-- a defect this audit exists to catch).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

HORIZON_CLASSIFICATIONS = frozenset({"CONSISTENT", "EXPLICIT_MECHANISTIC_TRANSFORMATION", "SILENT_HORIZON_DRIFT"})


@dataclass(frozen=True)
class HorizonAuditRecord:
    hypothesis_id: str
    source_horizon: str
    hypothesis_horizon: str
    candidate_horizon: Optional[str]
    holding_horizon: Optional[str]
    classification: str
    transformation_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id, "source_horizon": self.source_horizon,
            "hypothesis_horizon": self.hypothesis_horizon, "candidate_horizon": self.candidate_horizon,
            "holding_horizon": self.holding_horizon, "classification": self.classification,
            "transformation_reason": self.transformation_reason,
        }


def audit_hypothesis_horizon(hypothesis, *, source_claim_text: str = "") -> HorizonAuditRecord:
    """A source claim in this Factory (e.g. CLAIM-000001's verbatim RSI
    70/30 lore) typically states NO horizon at all -- "UNSPECIFIED" is
    the honest source_horizon, not a guess. What matters is whether the
    hypothesis's own transformation_history *says* it chose a horizon the
    source didn't specify (EXPLICIT_MECHANISTIC_TRANSFORMATION) or whether
    a horizon appears with no explanation anywhere in the record (SILENT_
    HORIZON_DRIFT).
    """
    source_horizon = "UNSPECIFIED" if not source_claim_text.strip() else "SEE_SOURCE_TEXT"
    hypothesis_horizon = hypothesis.holding_period or hypothesis.target_definition or "UNSPECIFIED"

    explains_choice = any(
        ("horizon" in str(event.get("detail", "")).lower() or "testable framing" in str(event.get("detail", "")).lower())
        for event in hypothesis.transformation_history
    ) or "this project's testable framing" in hypothesis.formalized_trading_rule.lower()

    if hypothesis_horizon == "UNSPECIFIED":
        classification, reason = "CONSISTENT", "hypothesis states no horizon either; nothing to compare"
    elif explains_choice:
        classification = "EXPLICIT_MECHANISTIC_TRANSFORMATION"
        reason = (
            f"hypothesis explicitly states horizon={hypothesis_horizon} is this project's own testable "
            "framing, not asserted by the source -- recorded in formalized_trading_rule/"
            "transformation_history, not silent"
        )
    else:
        classification = "SILENT_HORIZON_DRIFT"
        reason = "hypothesis specifies a horizon with no recorded explanation of why it differs from the (unspecified or different) source horizon"

    return HorizonAuditRecord(
        hypothesis_id=hypothesis.hypothesis_id, source_horizon=source_horizon,
        hypothesis_horizon=hypothesis_horizon,
        candidate_horizon=(hypothesis.candidate_ids[0] if hypothesis.candidate_ids else None),
        holding_horizon=hypothesis.holding_period, classification=classification,
        transformation_reason=reason,
    )


def audit_all_hypotheses(hypothesis_registry, claim_registry) -> List[HorizonAuditRecord]:
    records = []
    for h in hypothesis_registry.list_all():
        claim_text = ""
        if h.source_claim_id:
            try:
                claim_text = claim_registry.get(h.source_claim_id).claim_text
            except Exception:
                claim_text = ""
        records.append(audit_hypothesis_horizon(h, source_claim_text=claim_text))
    return records
