"""Renders `python3 -m idea_machine.cli explain <decision_id>` (spec item 26)."""

from __future__ import annotations

from typing import Dict, Optional

from idea_machine.research_space.decision_record import DecisionLedger


def render_explain(decision_id: str, ledger: Optional[DecisionLedger] = None) -> str:
    ledger = ledger or DecisionLedger()
    row = ledger.get(decision_id)
    if row is None:
        return f"No decision found with id {decision_id!r}."

    lines = []
    lines.append("=" * 72)
    lines.append(f"DECISION: {row['decision']}  ({row['decision_id']})")
    lines.append("=" * 72)
    lines.append(f"Cycle:      {row['cycle_id']}")
    lines.append(f"Target:     {row['target']}")
    lines.append(f"Confidence: {row['confidence']}")
    lines.append(f"Reversible: {row['reversible']}")
    lines.append("")
    lines.append("WHY:")
    lines.append(f"  {row['reason']}")
    lines.append("")
    lines.append("EVIDENCE:")
    for e in row["evidence"]:
        lines.append(f"  - {e}")
    lines.append("")
    lines.append("ALTERNATIVES CONSIDERED:")
    if row["alternatives_considered"]:
        for a in row["alternatives_considered"]:
            lines.append(f"  - {a}")
    else:
        lines.append("  (none recorded)")
    lines.append("")
    lines.append("SCORE BREAKDOWN:")
    for k, v in row["score_breakdown"].items():
        if k == "total":
            lines.append(f"  {'TOTAL':24s} {v}")
        else:
            sign = "+" if v > 0 else ("-" if v < 0 else " ")
            lines.append(f"  {k:24s} {sign}{abs(v)}")
    lines.append("")
    lines.append("RISKS:")
    if row["decision"] == "ACCEPT":
        lines.append("  - Real Factory evaluation may still reject this on real data (this is a")
        lines.append("    research-priority decision, not a survivor claim).")
    else:
        lines.append("  - Rejecting this candidate means the region it would have tested stays")
        lines.append("    UNEXPLORED/UNDERPOWERED; it is not marked REFUTED by this decision.")
    lines.append("")
    lines.append("GOVERNANCE CHECKS:")
    lines.append("  - No holdout access. No GEN14 authorization. No cost-model mutation.")
    lines.append("  - This decision was recorded via idea_machine.governance.guard.require(\"RECORD_DECISION\", ...).")
    return "\n".join(lines)


def explain_dict(decision_id: str, ledger: Optional[DecisionLedger] = None) -> Dict:
    ledger = ledger or DecisionLedger()
    row = ledger.get(decision_id)
    return row or {"error": f"no decision found with id {decision_id!r}"}
