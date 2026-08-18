"""Generation 1 Phase 0 — explicit governance audit, traceable 1:1 to
task section 0.2's named transition list.

Every scenario below is ALSO covered by tests/test_factory_state_machine.py,
tests/test_factory_registry.py, and tests/test_factory_holdout_governance.py
(added in the prior governance-formalization task) -- this file does not
duplicate their assertions' depth, it exists so each of the task's
explicitly-named scenarios has one directly-traceable test with a name
matching the task text, for an auditor who wants to check the list without
cross-referencing three other files.
"""

from __future__ import annotations

import pytest

from core.factory.candidate import FrozenCandidateMutationError
from core.factory.registry import MultipleTestingAccountingRequiredError, StrategyRegistry
from core.factory.state_machine import CandidateState, IllegalStateTransitionError, assert_legal_transition
from tests.test_factory_registry import _spec, _walk_to_frozen


class TestPhase0NamedTransitionAudit:
    def test_trained_to_wfa_tested_path_never_touches_holdout(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        reg.transition(c.candidate_id, CandidateState.DATA_VALIDATED, reason="ok")
        reg.transition(c.candidate_id, CandidateState.TRAINED, reason="ok")
        reg.transition(c.candidate_id, CandidateState.OOS_TESTED, reason="ok")
        reg.transition(c.candidate_id, CandidateState.WFA_TESTED, reason="ok")
        history_states = [h["state"] for h in reg.get(c.candidate_id).history]
        assert "HOLDOUT_TESTED" not in history_states

    def test_trained_to_rejected(self) -> None:
        assert_legal_transition(CandidateState.TRAINED, CandidateState.REJECTED)

    def test_oos_to_rejected(self) -> None:
        assert_legal_transition(CandidateState.OOS_TESTED, CandidateState.REJECTED)

    def test_wfa_to_rejected(self) -> None:
        assert_legal_transition(CandidateState.WFA_TESTED, CandidateState.REJECTED)

    def test_robustness_to_rejected(self) -> None:
        assert_legal_transition(CandidateState.ROBUSTNESS_TESTED, CandidateState.REJECTED)

    def test_cost_stress_to_rejected(self) -> None:
        assert_legal_transition(CandidateState.COST_TESTED, CandidateState.REJECTED)

    def test_statistics_to_rejected(self) -> None:
        assert_legal_transition(CandidateState.STATISTICALLY_VALIDATED, CandidateState.REJECTED)

    def test_multiple_testing_to_freeze(self) -> None:
        assert_legal_transition(CandidateState.MULTIPLE_TESTING_REVIEWED, CandidateState.FROZEN)

    def test_freeze_to_holdout(self) -> None:
        assert_legal_transition(CandidateState.FROZEN, CandidateState.HOLDOUT_TESTED)

    def test_holdout_to_pass_or_fail(self) -> None:
        # PASS path -> EVG_REVIEW; FAIL path -> REJECTED. Both legal.
        assert_legal_transition(CandidateState.HOLDOUT_TESTED, CandidateState.EVG_REVIEW)
        assert_legal_transition(CandidateState.HOLDOUT_TESTED, CandidateState.REJECTED)

    def test_holdout_to_no_mutation(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_frozen(reg, c.candidate_id)
        reg.transition(c.candidate_id, CandidateState.HOLDOUT_TESTED, reason="evaluated")
        with pytest.raises(FrozenCandidateMutationError):
            reg.assert_mutation_allowed(c.candidate_id)

    def test_any_modified_post_holdout_candidate_becomes_a_new_version(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        parent = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_frozen(reg, parent.candidate_id)
        reg.transition(parent.candidate_id, CandidateState.HOLDOUT_TESTED, reason="evaluated")
        reg.reject(parent.candidate_id, reason="failed holdout", failed_phase="HOLDOUT")

        child = reg.derive_new_version(
            parent.candidate_id, _spec(max_hold_bars=48), generator_id="G",
            generator_parameters={"max_hold_bars": 48}, code_version="abc", dataset_id="D",
        )
        assert child.candidate_id != parent.candidate_id
        assert child.parent_candidate_id == parent.candidate_id
        # the ORIGINAL v1 record is never retested -- it stays REJECTED, terminal
        assert reg.get(parent.candidate_id).state == CandidateState.REJECTED
        with pytest.raises(IllegalStateTransitionError):
            reg.transition(parent.candidate_id, CandidateState.HOLDOUT_TESTED, reason="illegal retest attempt")

    def test_illegal_backward_transition(self) -> None:
        with pytest.raises(IllegalStateTransitionError):
            assert_legal_transition(CandidateState.WFA_TESTED, CandidateState.TRAINED)

    def test_illegal_skipped_transition(self) -> None:
        with pytest.raises(IllegalStateTransitionError):
            assert_legal_transition(CandidateState.TRAINED, CandidateState.FROZEN)

    def test_evg_cannot_run_without_required_evidence(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_frozen(reg, c.candidate_id)
        with pytest.raises(IllegalStateTransitionError):
            reg.transition(c.candidate_id, CandidateState.EVG_REVIEW, reason="skip holdout entirely")

    def test_holdout_cannot_be_used_for_parameter_search(self) -> None:
        from core.provenance_enforcement import DataAccessAction, DataState, DataStateViolationError, ProvenanceEnforcer

        enforcer = ProvenanceEnforcer(hypothesis_id="PHASE0-AUDIT")
        with pytest.raises(DataStateViolationError):
            enforcer.validate_access(DataState.PURE_HOLDOUT, DataAccessAction.SELECTION)

    def test_rejection_reachable_without_passing_every_gate(self) -> None:
        """A candidate does NOT need to pass every gate to be rejected --
        the always-legal early-exit path, exercised by the real
        STRAT-000001 (TRAINED -> REJECTED, never touching OOS/WFA/
        robustness/cost/statistics/multiple-testing/freeze/holdout)."""
        assert_legal_transition(CandidateState.TRAINED, CandidateState.REJECTED)
        assert_legal_transition(CandidateState.GENERATED, CandidateState.REJECTED)
        assert_legal_transition(CandidateState.DATA_VALIDATED, CandidateState.REJECTED)

    def test_multiple_testing_gate_requires_accounting_first(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        for state in (
            CandidateState.DATA_VALIDATED, CandidateState.TRAINED, CandidateState.OOS_TESTED,
            CandidateState.WFA_TESTED, CandidateState.ROBUSTNESS_TESTED, CandidateState.COST_TESTED,
            CandidateState.STATISTICALLY_VALIDATED,
        ):
            reg.transition(c.candidate_id, state, reason="ok")
        with pytest.raises(MultipleTestingAccountingRequiredError):
            reg.transition(c.candidate_id, CandidateState.MULTIPLE_TESTING_REVIEWED, reason="no accounting yet")
