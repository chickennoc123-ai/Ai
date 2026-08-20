"""Epistemic states (roadmap Phase 2).

The single most important rule in the whole roadmap is stated here:

    *"Không được biến 'chưa biết' thành 'có edge'."*
    Never turn "we don't know" into "there is an edge".

So the knowledge base distinguishes seven states, and the transition table
below makes the dangerous moves impossible rather than merely discouraged:

  UNKNOWN        nothing has been asserted
  KNOWN          a source claims it; nobody has tested it here
  TESTED         an experiment ran to completion
  SURVIVED       the experiment did not refute it (NOT "has an edge")
  REFUTED        the experiment refuted it
  BLOCKED        cannot be tested yet (missing data, missing capability)
  UNDERPOWERED   tested, but the sample could not have detected the effect

``UNDERPOWERED`` is deliberately *not* a synonym for ``REFUTED``: an
underpowered result says the experiment was too small, which is a statement
about the experiment, not about the market. Collapsing the two would let the
machine permanently close search space it never actually explored.
"""

from __future__ import annotations

from typing import Dict, FrozenSet

from idea_machine.core.errors import KnowledgeError

UNKNOWN = "UNKNOWN"
KNOWN = "KNOWN"
TESTED = "TESTED"
SURVIVED = "SURVIVED"
REFUTED = "REFUTED"
BLOCKED = "BLOCKED"
UNDERPOWERED = "UNDERPOWERED"

STATES: FrozenSet[str] = frozenset(
    {UNKNOWN, KNOWN, TESTED, SURVIVED, REFUTED, BLOCKED, UNDERPOWERED}
)

#: States that close search space. Only REFUTED does; everything else leaves
#: the door open, which is why UNDERPOWERED must never be folded into REFUTED.
CLOSES_SEARCH_SPACE: FrozenSet[str] = frozenset({REFUTED})

#: States that permit an idea to be researched again later.
REOPENABLE: FrozenSet[str] = frozenset({UNKNOWN, KNOWN, BLOCKED, UNDERPOWERED, SURVIVED})

_ALLOWED: Dict[str, FrozenSet[str]] = {
    UNKNOWN: frozenset({KNOWN, BLOCKED}),
    KNOWN: frozenset({BLOCKED, TESTED}),
    BLOCKED: frozenset({KNOWN, TESTED}),           # unblocks once data arrives
    TESTED: frozenset({SURVIVED, REFUTED, UNDERPOWERED}),
    UNDERPOWERED: frozenset({TESTED}),             # re-testable with more data
    SURVIVED: frozenset({TESTED, REFUTED}),        # replication may still refute
    REFUTED: frozenset(),                          # terminal
}


def validate_state(state: str) -> str:
    if state not in STATES:
        raise KnowledgeError("unknown epistemic state", state=state, allowed=sorted(STATES))
    return state


def can_transition(current: str, target: str) -> bool:
    validate_state(current)
    validate_state(target)
    return target in _ALLOWED[current]


def assert_transition(current: str, target: str, *, subject: str = "") -> None:
    """Raise :class:`KnowledgeError` unless ``current -> target`` is legal."""
    if current == target:
        return
    if not can_transition(current, target):
        raise KnowledgeError(
            "illegal epistemic transition",
            subject=subject,
            current=current,
            target=target,
            allowed=sorted(_ALLOWED[validate_state(current)]),
        )


def is_edge_claim(state: str) -> bool:
    """No epistemic state in this module means "has an edge".

    Kept as an explicit function so the answer is discoverable in code review:
    the Idea Machine has no vocabulary for asserting an edge. ``SURVIVED`` is
    the strongest thing it can say and it means "not refuted".
    """
    validate_state(state)
    return False
