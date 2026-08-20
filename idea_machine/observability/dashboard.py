"""Observability (Phase 17) — the two questions that matter.

Standard counters are here, but the roadmap singles out two questions the
dashboard must answer, and they are the ones a funnel chart cannot:

    "Where are we searching?"
    "Where have we already proven it doesn't work?"

Both are answered from the failure memory and knowledge base, using *counts and
states only* — never performance numbers. A third question is added because
leaving it out is how a search space silently shrinks:

    "Where did we never actually look?"

That last one lists mechanisms whose only verdicts were UNDERPOWERED or
BLOCKED. Those regions are open, not exhausted, and without a place on the
dashboard they look identical to refuted ones and quietly stop being revisited.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from idea_machine.core.families import FAMILY_NAMES
from idea_machine.governance import guard
from idea_machine.pipeline import IdeaMachine
from idea_machine.queue import queue as qs


def build_dashboard(machine: IdeaMachine) -> Dict[str, Any]:
    """Assemble the full observability payload for ``machine``."""
    guard.require("REPORT_OBSERVABILITY")

    counts = machine.queue.counts()
    memory = machine.memory
    entries = memory.entries()
    policy = machine.adaptive.derive_policy()

    ideas_generated = sum(counts.values())
    researched = counts[qs.SURVIVOR] + counts[qs.FAIL] + counts[qs.REFUTED] + counts[qs.UNDERPOWERED] + counts[qs.BLOCKED]

    searching: List[Dict[str, Any]] = []
    for family in FAMILY_NAMES:
        weight = policy.weight_for(family)
        tested = sum(1 for e in entries if e.family == family)
        searching.append(
            {
                "family": family,
                "search_weight": round(weight, 3),
                "ideas_tested": tested,
                "status": _family_status(weight, tested),
            }
        )
    searching.sort(key=lambda r: (-r["search_weight"], r["family"]))

    proven_not_to_work = [
        {
            "family": e.family,
            "horizon": e.horizon,
            "mechanism_signature": e.mechanism_signature,
            "reason": e.reason,
            "prevention_rule": e.prevention_rule,
        }
        for e in entries
        if e.closes_search_space
    ]

    never_looked = [
        {
            "family": e.family,
            "horizon": e.horizon,
            "mechanism_signature": e.mechanism_signature,
            "why_open": e.outcome,
            "reason": e.reason,
        }
        for e in entries
        if e.outcome in ("UNDERPOWERED", "BLOCKED")
        and not memory.is_closed(mechanism_signature=e.mechanism_signature, horizon=e.horizon)
    ]

    return {
        "counters": {
            "ideas_generated": ideas_generated,
            "ideas_rejected": counts[qs.REJECTED],
            "ideas_blocked": counts[qs.BLOCKED_DATA] + counts[qs.BLOCKED],
            "ideas_researched": researched,
            "ideas_failed": counts[qs.FAIL] + counts[qs.REFUTED],
            "ideas_underpowered": counts[qs.UNDERPOWERED],
            "survivors": counts[qs.SURVIVOR],
            "in_flight": counts[qs.QUEUED] + counts[qs.RUNNING] + counts[qs.FACTORY_RESULT],
            "experiments_registered": machine.prereg.summary()["registered"],
            "experiments_submitted": machine.bridge.summary()["submitted"],
            "research_budget_consumed": machine.budget.summary()["consumed"],
            "search_space_eliminated": len(proven_not_to_work),
        },
        # These two counters belong to the Strategy Factory, not to us. They are
        # shown as unknown rather than guessed: the Idea Machine has no
        # visibility into GEN12/GEN14 progression or EA production, and printing
        # a plausible-looking zero would imply it does.
        "downstream_owned_by_factory": {
            "gen12_candidates": "UNKNOWN_TO_IDEA_MACHINE",
            "gen14_candidates": "UNKNOWN_TO_IDEA_MACHINE",
            "eas_produced": "UNKNOWN_TO_IDEA_MACHINE",
            "note": (
                "GEN12/GEN14 progression and EA production are Strategy Factory state. "
                "The Idea Machine reports only what it can observe: what it proposed and what "
                "verdict came back."
            ),
        },
        "where_are_we_searching": searching,
        "where_have_we_proven_it_does_not_work": proven_not_to_work,
        "where_did_we_never_actually_look": never_looked,
        "wasted_budget_signals": list(policy.wasted_budget_signals),
        "governance": {
            "human_authority": list(guard.HUMAN_AUTHORITY),
            "static_audit_findings": len(guard.audit_source_tree()),
        },
        "ledgers": machine.status(),
    }


def _family_status(weight: float, tested: int) -> str:
    if tested == 0:
        return "UNEXPLORED"
    if weight >= 1.2:
        return "PRODUCTIVE"
    if weight <= 0.4:
        return "LOOKS_EXHAUSTED"
    return "NEUTRAL"


def render_text(dashboard: Mapping[str, Any]) -> str:
    """A terminal-readable rendering of :func:`build_dashboard`."""
    lines: List[str] = []
    add = lines.append
    add("=" * 74)
    add("IDEA MACHINE -- OBSERVABILITY")
    add("=" * 74)

    add("\nCOUNTERS")
    for key, value in dashboard["counters"].items():
        if isinstance(value, dict):
            add(f"  {key:28s} {', '.join(f'{k}={v}' for k, v in value.items())}")
        else:
            add(f"  {key:28s} {value}")

    add("\nWHERE ARE WE SEARCHING?")
    for row in dashboard["where_are_we_searching"][:12]:
        add(f"  {row['family']:18s} weight={row['search_weight']:<6} tested={row['ideas_tested']:<4} {row['status']}")

    add("\nWHERE HAVE WE PROVEN IT DOES NOT WORK?")
    proven = dashboard["where_have_we_proven_it_does_not_work"]
    if not proven:
        add("  (nothing refuted yet -- no search space has been closed)")
    for row in proven:
        add(f"  {row['family']:18s} {row['horizon']:12s} {row['reason'][:60]}")
        if row["prevention_rule"]:
            add(f"      rule: {row['prevention_rule'][:90]}")

    add("\nWHERE DID WE NEVER ACTUALLY LOOK? (open, not exhausted)")
    open_rows = dashboard["where_did_we_never_actually_look"]
    if not open_rows:
        add("  (none)")
    for row in open_rows:
        add(f"  {row['family']:18s} {row['horizon']:12s} {row['why_open']:14s} {row['reason'][:50]}")

    if dashboard["wasted_budget_signals"]:
        add("\nWASTED BUDGET SIGNALS")
        for signal in dashboard["wasted_budget_signals"]:
            add(f"  - {signal}")

    add("\nDOWNSTREAM (Strategy Factory authority)")
    for key, value in dashboard["downstream_owned_by_factory"].items():
        if key != "note":
            add(f"  {key:28s} {value}")

    add("\nHUMAN AUTHORITY (never the machine's)")
    for item in dashboard["governance"]["human_authority"]:
        add(f"  - {item}")
    add(f"\nstatic governance audit findings: {dashboard['governance']['static_audit_findings']}")
    return "\n".join(lines)
