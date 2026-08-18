"""Tests for core.factory.state_machine — the Strategy Factory candidate lifecycle."""

from __future__ import annotations

import pytest

from core.factory.state_machine import (
    CandidateState,
    IllegalStateTransitionError,
    allowed_next_states,
    assert_legal_transition,
    is_terminal,
)


class TestLegalForwardTransitions:
    def test_generated_to_data_validated_is_legal(self) -> None:
        assert_legal_transition(CandidateState.GENERATED, CandidateState.DATA_VALIDATED)

    def test_full_forward_spine_is_legal(self) -> None:
        """Per ML-001-STRATEGY-FACTORY-SPEC.md §4 (holdout-last policy):
        TRAIN -> OOS -> WALK_FORWARD -> ROBUSTNESS -> COST_STRESS ->
        STATISTICS -> MULTIPLE_TESTING -> CANDIDATE_FREEZE -> PURE_HOLDOUT
        -> EVG. HOLDOUT_TESTED is deliberately the last reusable-data gate
        before EVG_REVIEW, not right after TRAINED."""
        spine = [
            CandidateState.GENERATED,
            CandidateState.DATA_VALIDATED,
            CandidateState.TRAINED,
            CandidateState.OOS_TESTED,
            CandidateState.WFA_TESTED,
            CandidateState.ROBUSTNESS_TESTED,
            CandidateState.COST_TESTED,
            CandidateState.STATISTICALLY_VALIDATED,
            CandidateState.MULTIPLE_TESTING_REVIEWED,
            CandidateState.FROZEN,
            CandidateState.HOLDOUT_TESTED,
            CandidateState.EVG_REVIEW,
            CandidateState.RESEARCH_CANDIDATE,
            CandidateState.PAPER_VALIDATION,
            CandidateState.LIVE_CANDIDATE,
        ]
        for a, b in zip(spine, spine[1:]):
            assert_legal_transition(a, b)

    def test_holdout_is_the_last_gate_before_evg(self) -> None:
        """Locks in the specific ordering decision, not just that SOME
        spine exists: OOS/WFA/ROBUSTNESS/COST/STATISTICS/MULTIPLE_TESTING
        must all precede FROZEN, which must precede HOLDOUT_TESTED, which
        must precede EVG_REVIEW."""
        assert_legal_transition(CandidateState.STATISTICALLY_VALIDATED, CandidateState.MULTIPLE_TESTING_REVIEWED)
        assert_legal_transition(CandidateState.MULTIPLE_TESTING_REVIEWED, CandidateState.FROZEN)
        assert_legal_transition(CandidateState.FROZEN, CandidateState.HOLDOUT_TESTED)
        assert_legal_transition(CandidateState.HOLDOUT_TESTED, CandidateState.EVG_REVIEW)
        # none of OOS/WFA/ROBUSTNESS/COST/STATISTICS may jump straight to HOLDOUT_TESTED
        for early_state in (
            CandidateState.TRAINED,
            CandidateState.OOS_TESTED,
            CandidateState.WFA_TESTED,
            CandidateState.ROBUSTNESS_TESTED,
            CandidateState.COST_TESTED,
            CandidateState.STATISTICALLY_VALIDATED,
        ):
            with pytest.raises(IllegalStateTransitionError):
                assert_legal_transition(early_state, CandidateState.HOLDOUT_TESTED)

    def test_live_candidate_to_retired_is_legal(self) -> None:
        assert_legal_transition(CandidateState.LIVE_CANDIDATE, CandidateState.RETIRED)


class TestRejectionIsAlwaysReachable:
    @pytest.mark.parametrize(
        "state",
        [
            CandidateState.GENERATED,
            CandidateState.DATA_VALIDATED,
            CandidateState.TRAINED,
            CandidateState.OOS_TESTED,
            CandidateState.WFA_TESTED,
            CandidateState.ROBUSTNESS_TESTED,
            CandidateState.COST_TESTED,
            CandidateState.STATISTICALLY_VALIDATED,
            CandidateState.MULTIPLE_TESTING_REVIEWED,
            CandidateState.FROZEN,
            CandidateState.HOLDOUT_TESTED,
            CandidateState.EVG_REVIEW,
            CandidateState.RESEARCH_CANDIDATE,
            CandidateState.PAPER_VALIDATION,
        ],
    )
    def test_can_reject_from_any_non_terminal_pre_live_state(self, state: CandidateState) -> None:
        assert_legal_transition(state, CandidateState.REJECTED)
        assert_legal_transition(state, CandidateState.FAILED)

    def test_live_candidate_cannot_be_rejected_only_retired(self) -> None:
        with pytest.raises(IllegalStateTransitionError):
            assert_legal_transition(CandidateState.LIVE_CANDIDATE, CandidateState.REJECTED)


class TestIllegalTransitions:
    def test_cannot_skip_gates(self) -> None:
        with pytest.raises(IllegalStateTransitionError):
            assert_legal_transition(CandidateState.GENERATED, CandidateState.LIVE_CANDIDATE)

    def test_cannot_go_backwards(self) -> None:
        with pytest.raises(IllegalStateTransitionError):
            assert_legal_transition(CandidateState.OOS_TESTED, CandidateState.TRAINED)

    def test_cannot_skip_a_single_gate(self) -> None:
        # skips MULTIPLE_TESTING_REVIEWED on the way to FROZEN
        with pytest.raises(IllegalStateTransitionError):
            assert_legal_transition(CandidateState.STATISTICALLY_VALIDATED, CandidateState.FROZEN)

    @pytest.mark.parametrize("terminal", [CandidateState.REJECTED, CandidateState.FAILED, CandidateState.RETIRED])
    def test_terminal_states_have_no_outgoing_transitions(self, terminal: CandidateState) -> None:
        assert is_terminal(terminal)
        assert allowed_next_states(terminal) == frozenset()
        with pytest.raises(IllegalStateTransitionError):
            assert_legal_transition(terminal, CandidateState.GENERATED)

    def test_error_message_lists_allowed_states(self) -> None:
        with pytest.raises(IllegalStateTransitionError) as exc_info:
            assert_legal_transition(CandidateState.GENERATED, CandidateState.LIVE_CANDIDATE)
        assert "DATA_VALIDATED" in str(exc_info.value)
