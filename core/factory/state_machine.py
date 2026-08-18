"""Strategy Factory candidate state machine.

Per the ML-001 Strategy Factory roadmap Section 6: every candidate moves
through an explicit, auditable lifecycle. Illegal transitions are rejected
— a candidate can never silently skip a required evidence gate (e.g. jump
from GENERATED straight to LIVE_CANDIDATE), and a terminal state (REJECTED,
FAILED, RETIRED) can never be transitioned out of. This module contains no
economic logic — it only enforces which state changes are structurally
legal, given already-decided evidence outcomes.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet


class CandidateState(str, Enum):
    GENERATED = "GENERATED"
    DATA_VALIDATED = "DATA_VALIDATED"
    TRAINED = "TRAINED"
    FROZEN = "FROZEN"
    HOLDOUT_TESTED = "HOLDOUT_TESTED"
    OOS_TESTED = "OOS_TESTED"
    WFA_TESTED = "WFA_TESTED"
    ROBUSTNESS_TESTED = "ROBUSTNESS_TESTED"
    COST_TESTED = "COST_TESTED"
    STATISTICALLY_VALIDATED = "STATISTICALLY_VALIDATED"
    EVG_REVIEW = "EVG_REVIEW"
    RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"
    PAPER_VALIDATION = "PAPER_VALIDATION"
    LIVE_CANDIDATE = "LIVE_CANDIDATE"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    RETIRED = "RETIRED"


#: Terminal states: no outgoing transition is ever legal from these.
TERMINAL_STATES: FrozenSet[CandidateState] = frozenset(
    {CandidateState.REJECTED, CandidateState.FAILED, CandidateState.RETIRED}
)

#: The linear evidence spine a candidate must ascend, in order. Any state
#: in this list may transition to REJECTED or FAILED (a candidate can fail
#: at any gate) in addition to its declared forward transition(s).
_FORWARD_SPINE = [
    CandidateState.GENERATED,
    CandidateState.DATA_VALIDATED,
    CandidateState.TRAINED,
    CandidateState.FROZEN,
    CandidateState.HOLDOUT_TESTED,
    CandidateState.OOS_TESTED,
    CandidateState.WFA_TESTED,
    CandidateState.ROBUSTNESS_TESTED,
    CandidateState.COST_TESTED,
    CandidateState.STATISTICALLY_VALIDATED,
    CandidateState.EVG_REVIEW,
    CandidateState.RESEARCH_CANDIDATE,
    CandidateState.PAPER_VALIDATION,
    CandidateState.LIVE_CANDIDATE,
]

_ALLOWED_TRANSITIONS: Dict[CandidateState, FrozenSet[CandidateState]] = {}
for _i, _state in enumerate(_FORWARD_SPINE):
    _next_states = set()
    if _i + 1 < len(_FORWARD_SPINE):
        _next_states.add(_FORWARD_SPINE[_i + 1])
    if _state is not CandidateState.LIVE_CANDIDATE:
        _next_states.add(CandidateState.REJECTED)
        _next_states.add(CandidateState.FAILED)
    _ALLOWED_TRANSITIONS[_state] = frozenset(_next_states)

# LIVE_CANDIDATE's only forward motion is retirement (never silently
# dropped — a live/paper candidate that stops being used must be
# explicitly retired, preserving the audit trail).
_ALLOWED_TRANSITIONS[CandidateState.LIVE_CANDIDATE] = frozenset({CandidateState.RETIRED})
# PAPER_VALIDATION may also be retired directly (paper run abandoned
# without ever reaching live) in addition to its forward promotion.
_ALLOWED_TRANSITIONS[CandidateState.PAPER_VALIDATION] = frozenset(
    _ALLOWED_TRANSITIONS[CandidateState.PAPER_VALIDATION] | {CandidateState.RETIRED}
)

for _terminal in TERMINAL_STATES:
    _ALLOWED_TRANSITIONS[_terminal] = frozenset()


class IllegalStateTransitionError(Exception):
    """Raised when a candidate attempts a structurally illegal state change."""

    def __init__(self, current: CandidateState, requested: CandidateState) -> None:
        self.current = current
        self.requested = requested
        super().__init__(
            f"illegal candidate state transition: {current.value} -> {requested.value} "
            f"(allowed from {current.value}: "
            f"{sorted(s.value for s in _ALLOWED_TRANSITIONS[current])})"
        )


def assert_legal_transition(current: CandidateState, requested: CandidateState) -> None:
    """Raise ``IllegalStateTransitionError`` unless ``current -> requested`` is allowed."""
    if requested not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise IllegalStateTransitionError(current, requested)


def allowed_next_states(current: CandidateState) -> FrozenSet[CandidateState]:
    return _ALLOWED_TRANSITIONS.get(current, frozenset())


def is_terminal(state: CandidateState) -> bool:
    return state in TERMINAL_STATES
