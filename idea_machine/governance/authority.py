"""What the Idea Machine may and may not do (roadmap Phase 16).

This module is the single, readable statement of the boundary. It contains no
logic — just the two lists and the reasons — so that a reviewer can audit the
machine's authority without reading any implementation.

The enforcement lives in :mod:`idea_machine.governance.guard`.
"""

from __future__ import annotations

from typing import Dict, Tuple

#: Actions the Idea Machine performs as a matter of course.
PERMITTED: Tuple[str, ...] = (
    "SCAN_SOURCES",
    "EXTRACT_CONCEPTS",
    "UPDATE_KNOWLEDGE",
    "GENERATE_IDEA",
    "COMBINE_CONCEPTS",
    "CHECK_NOVELTY",
    "CHECK_DATA_FEASIBILITY",
    "APPLY_ECONOMIC_PREFILTER",
    "RANK_IDEAS",
    "DESIGN_EXPERIMENT",
    "PREREGISTER_EXPERIMENT",
    "ENQUEUE_IDEA",
    "SUBMIT_TO_FACTORY",
    "READ_FACTORY_RESULT",
    "RECORD_FEEDBACK",
    "ALLOCATE_RESEARCH_BUDGET",
    "REPORT_OBSERVABILITY",
    # Phase 9 -- Research Space Evolution Engine. Declared here, the Idea
    # Machine's own authority module, not the Strategy Factory: these are
    # read/propose/record actions only, none of them authorize anything the
    # Factory itself has not already gated.
    "MAP_SEARCH_SPACE",
    "COMPUTE_EXPLORATION_DEBT",
    "ALLOCATE_RESEARCH_MODE_BUDGET",
    "SCORE_RESEARCH_VALUE",
    "RECORD_DECISION",
    "PROPOSE_BRANCH_CLOSURE",
    "DESIGN_DISCRIMINATING_EXPERIMENT",
)

#: Actions that terminate the run if attempted. Each maps to *why*.
FORBIDDEN: Dict[str, str] = {
    "READ_HOLDOUT": (
        "The sealed holdout is the Strategy Factory's last independent evidence. "
        "An idea generator that can see it will, over enough cycles, fit to it."
    ),
    "CONSUME_HOLDOUT": (
        "Consuming a holdout partition spends a one-time resource; only the Factory's "
        "governed pipeline may spend it."
    ),
    "AUTHORIZE_GEN14": (
        "GEN14 authorization is a human decision. A machine that can authorize its own "
        "final gate has no final gate."
    ),
    "MODIFY_COST_MODEL": (
        "Loosening costs is the cheapest way to manufacture a fake edge. The cost model "
        "is an input to the Idea Machine, never an output."
    ),
    "RESET_LEDGER": (
        "Research ledgers are append-only. A machine that can reset its ledger can erase "
        "the record of what it already tried."
    ),
    "MODIFY_FAILURE_HISTORY": (
        "The failure library is the map of where not to dig. Editing it lets the machine "
        "re-dig exhausted ground and re-discover the same non-edge forever."
    ),
    "DECLARE_EDGE": (
        "Only the Factory, through its full gate sequence, may call something an edge. "
        "The Idea Machine's strongest statement is SURVIVED, meaning 'not refuted'."
    ),
    "CREATE_EA": (
        "An EA is a deployable product. Producing one from a candidate that has not "
        "PASSED is how research becomes an accident in a live account."
    ),
    "RETEST_FAILED_BY_PARAMETER_TWEAK": (
        "Re-running a refuted idea with a nudged parameter is p-hacking with extra steps. "
        "A refuted mechanism needs a NEW mechanism, not a new threshold."
    ),
    "BYPASS_FACTORY_GATE": (
        "Every gate exists because something once got through without it."
    ),
    "MUTATE_PREREGISTRATION": (
        "A pre-registered experiment that can be edited after seeing results is not "
        "pre-registered."
    ),
    "DEPLOY_LIVE": (
        "Capital allocation and live deployment are human authority, full stop."
    ),
}

#: Decisions that remain with a human being, listed for the dashboard.
HUMAN_AUTHORITY: Tuple[str, ...] = (
    "GEN14 authorization",
    "Live deployment",
    "Capital allocation",
    "Final product release",
)

#: Import targets the Idea Machine must never reach for. Enforced statically by
#: ``idea_machine.governance.guard.audit_source_tree`` and by the test suite.
FORBIDDEN_IMPORTS: Tuple[str, ...] = (
    "core.factory.holdout_access",
    "core.factory.evidence_vault",
    "qualification",
    "discovery.holdout_authorization",
    "discovery.replication",
    "ea_generator",
)
