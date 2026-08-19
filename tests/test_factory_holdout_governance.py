"""Governance/immutability regression tests for the Strategy Factory, added
per the STRAT-000001 failure-closure task.

These do not change `core.factory.state_machine`'s transition table or
`core.provenance_enforcement`'s access matrix — both are treated as
frozen pending the formal specification decision documented in
`ML-001-HOLDOUT-WFA-GOVERNANCE-DECISION.md`. They instead lock in, as
tests, the properties that decision explicitly relies on already holding:
a REJECTED candidate cannot be revived or mutated, holdout can never be
reopened once entered, a frozen spec can only be changed via a brand-new
candidate version, and the search-history counters reflect the real,
un-inflated STRAT-000001 population.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from core.factory.candidate import FrozenCandidateMutationError, StrategyCandidateSpec
from core.factory.registry import (
    DEFAULT_REGISTRY_PATH,
    MultipleTestingAccountingRequiredError,
    StrategyRegistry,
)
from core.factory.state_machine import CandidateState, IllegalStateTransitionError, assert_legal_transition
from core.provenance_enforcement import DataAccessAction, DataState, DataStateViolationError, ProvenanceEnforcer
from tests.test_factory_registry import _holdout_event, _spec, _walk_to_frozen, _walk_to_holdout_tested


class TestRejectedCandidateImmutability:
    """A REJECTED candidate is a permanent scientific record, not a draft."""

    def test_rejected_candidate_spec_mutation_is_blocked(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        reg.reject(c.candidate_id, reason="no edge", failed_phase="WFA")
        with pytest.raises(FrozenCandidateMutationError):
            reg.assert_mutation_allowed(c.candidate_id)

    @pytest.mark.parametrize(
        "attempted_next",
        [
            CandidateState.GENERATED,
            CandidateState.DATA_VALIDATED,
            CandidateState.TRAINED,
            CandidateState.FROZEN,
            CandidateState.HOLDOUT_TESTED,
            CandidateState.STATISTICALLY_VALIDATED,
            CandidateState.RESEARCH_CANDIDATE,
            CandidateState.LIVE_CANDIDATE,
        ],
    )
    def test_rejected_candidate_cannot_transition_anywhere(self, tmp_path, attempted_next) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        reg.reject(c.candidate_id, reason="no edge", failed_phase="WFA")
        with pytest.raises(IllegalStateTransitionError):
            reg.transition(c.candidate_id, attempted_next, reason="attempted revival")
        assert reg.get(c.candidate_id).state == CandidateState.REJECTED

    def test_strategycandidatespec_is_a_frozen_dataclass(self) -> None:
        """Even bypassing the registry entirely, the spec object itself
        refuses in-place mutation (belt-and-suspenders with the registry
        guard, enforced at the type level, not by convention)."""
        spec = _spec()
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.max_hold_bars = 999  # type: ignore[misc]

    def test_rejected_candidate_history_is_append_only_and_preserved(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        reg.transition(c.candidate_id, CandidateState.DATA_VALIDATED, reason="ok")
        reg.transition(c.candidate_id, CandidateState.TRAINED, reason="ok")
        reg.reject(c.candidate_id, reason="no edge", failed_phase="WFA")

        history_before = list(reg.get(c.candidate_id).history)
        with pytest.raises(IllegalStateTransitionError):
            reg.transition(c.candidate_id, CandidateState.TRAINED, reason="try to un-reject")
        # the failed attempt must not have appended a spurious history entry
        assert reg.get(c.candidate_id).history == history_before
        # every real prior transition remains, in order, none dropped
        assert [h["state"] for h in history_before] == [
            "GENERATED",
            "DATA_VALIDATED",
            "TRAINED",
            "REJECTED",
        ]


class TestNewVersionRequiredAfterFrozenModification:
    def test_cannot_patch_a_frozen_candidates_spec_in_place(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_frozen(reg, c.candidate_id)
        with pytest.raises(FrozenCandidateMutationError):
            reg.assert_mutation_allowed(c.candidate_id)

    def test_only_sanctioned_path_is_derive_new_version_with_fresh_id(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        parent = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_frozen(reg, parent.candidate_id)

        child = reg.derive_new_version(
            parent.candidate_id, _spec(max_hold_bars=48), generator_id="G",
            generator_parameters={"max_hold_bars": 48}, code_version="abc", dataset_id="D",
        )
        assert child.candidate_id != parent.candidate_id
        assert child.version == 1  # a NEW candidate identity, not "v2" of the parent's own record
        assert child.parent_candidate_id == parent.candidate_id
        assert child.state == CandidateState.GENERATED
        # the parent's own spec content is byte-for-byte unchanged
        assert reg.get(parent.candidate_id).spec.max_hold_bars == 24


class TestFinalHoldoutSemantics:
    """PURE_HOLDOUT access is a one-time, forward-only, non-optimizable event."""

    def test_holdout_tested_is_unreachable_except_via_frozen(self) -> None:
        """No reusable-data gate (OOS/WFA/ROBUSTNESS/COST/STATISTICS) may
        jump directly into HOLDOUT_TESTED, and once a candidate is past
        HOLDOUT_TESTED (at EVG_REVIEW or later), it can never re-enter
        HOLDOUT_TESTED either -- it is reachable from exactly one state,
        FROZEN, and from nowhere else in the spine."""
        for other_state in (
            CandidateState.TRAINED,
            CandidateState.OOS_TESTED,
            CandidateState.WFA_TESTED,
            CandidateState.ROBUSTNESS_TESTED,
            CandidateState.COST_TESTED,
            CandidateState.STATISTICALLY_VALIDATED,
            CandidateState.MULTIPLE_TESTING_REVIEWED,
            CandidateState.EVG_REVIEW,
            CandidateState.RESEARCH_CANDIDATE,
            CandidateState.PAPER_VALIDATION,
            CandidateState.LIVE_CANDIDATE,
        ):
            with pytest.raises(IllegalStateTransitionError):
                assert_legal_transition(other_state, CandidateState.HOLDOUT_TESTED)
        # the one legal entry point
        assert_legal_transition(CandidateState.FROZEN, CandidateState.HOLDOUT_TESTED)

    def test_holdout_tested_candidate_is_also_mutation_blocked(self, tmp_path) -> None:
        """No mutation after holdout access (task requirement, distinct
        from the FROZEN-specific test above): once a candidate reaches
        HOLDOUT_TESTED itself, its spec is still immutable."""
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_holdout_tested(reg, c.candidate_id)
        with pytest.raises(FrozenCandidateMutationError):
            reg.assert_mutation_allowed(c.candidate_id)

    def test_holdout_access_guard_permits_only_final_evaluation(self) -> None:
        enforcer = ProvenanceEnforcer(hypothesis_id="TEST-HOLDOUT-SEMANTICS")
        # allowed: the one sanctioned use
        enforcer.validate_access(DataState.PURE_HOLDOUT, DataAccessAction.FINAL_EVALUATION)
        # forbidden: every use that would let holdout influence a decision
        for action in (DataAccessAction.TRAINING, DataAccessAction.SELECTION):
            with pytest.raises(DataStateViolationError):
                enforcer.validate_access(DataState.PURE_HOLDOUT, action)

    def test_trained_may_bypass_holdout_entirely_via_direct_rejection(self, tmp_path) -> None:
        """Documents the currently-legal, currently-used path this project
        relies on: a candidate may be rejected straight from TRAINED (as
        STRAT-000001 was, on real WFA evidence) without ever opening
        PURE_HOLDOUT. This is intentional -- see
        ML-001-HOLDOUT-WFA-GOVERNANCE-DECISION.md -- and must keep working
        regardless of how the HOLDOUT_TESTED/WFA_TESTED ordering question
        is eventually resolved."""
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        reg.transition(c.candidate_id, CandidateState.DATA_VALIDATED, reason="ok")
        reg.transition(c.candidate_id, CandidateState.TRAINED, reason="ok")
        reg.reject(c.candidate_id, reason="no edge found in walk-forward", failed_phase="WFA")
        assert reg.get(c.candidate_id).state == CandidateState.REJECTED


class TestEVGOnlyAfterRequiredEvidence:
    """EVG_REVIEW must not be reachable without every earlier gate --
    including HOLDOUT_TESTED specifically -- having actually happened."""

    def test_evg_review_unreachable_from_any_state_except_holdout_tested(self) -> None:
        for other_state in (
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
        ):
            with pytest.raises(IllegalStateTransitionError):
                assert_legal_transition(other_state, CandidateState.EVG_REVIEW)
        assert_legal_transition(CandidateState.HOLDOUT_TESTED, CandidateState.EVG_REVIEW)

    def test_registry_level_evg_review_requires_full_walk_through_holdout(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_frozen(reg, c.candidate_id)
        with pytest.raises(IllegalStateTransitionError):
            reg.transition(c.candidate_id, CandidateState.EVG_REVIEW, reason="skip holdout")
        reg.transition(
            c.candidate_id, CandidateState.HOLDOUT_TESTED, reason="holdout evaluated",
            holdout_access_event=_holdout_event(reg, c.candidate_id),
        )
        reg.transition(c.candidate_id, CandidateState.EVG_REVIEW, reason="ok, now legal")
        assert reg.get(c.candidate_id).state == CandidateState.EVG_REVIEW


class TestMultipleTestingGateEnforcement:
    """MULTIPLE_TESTING_REVIEWED must not be a label with nothing behind
    it -- the search-space accounting it certifies must already exist."""

    def test_cannot_enter_multiple_testing_reviewed_without_search_space_declared(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        reg.transition(c.candidate_id, CandidateState.DATA_VALIDATED, reason="ok")
        reg.transition(c.candidate_id, CandidateState.TRAINED, reason="ok")
        reg.transition(c.candidate_id, CandidateState.OOS_TESTED, reason="ok")
        reg.transition(c.candidate_id, CandidateState.WFA_TESTED, reason="ok")
        reg.transition(c.candidate_id, CandidateState.ROBUSTNESS_TESTED, reason="ok")
        reg.transition(c.candidate_id, CandidateState.COST_TESTED, reason="ok")
        reg.transition(c.candidate_id, CandidateState.STATISTICALLY_VALIDATED, reason="ok")
        # set_search_space() deliberately never called
        with pytest.raises(MultipleTestingAccountingRequiredError):
            reg.transition(c.candidate_id, CandidateState.MULTIPLE_TESTING_REVIEWED, reason="attempt without accounting")
        # the failed attempt must not have advanced the candidate's state
        assert reg.get(c.candidate_id).state == CandidateState.STATISTICALLY_VALIDATED

    def test_succeeds_once_search_space_is_declared(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_frozen(reg, c.candidate_id)  # calls set_search_space() internally
        assert reg.get(c.candidate_id).state == CandidateState.FROZEN


class TestMultipleTestingAccountingIsHonest:
    """Confirms the counters this task's final status block cites are not
    aspirational -- they come from the real, on-disk production registry."""

    def test_production_registry_reflects_exactly_one_tested_one_rejected_zero_passed(self) -> None:
        if not DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("production registry not present in this checkout")
        reg = StrategyRegistry(path=DEFAULT_REGISTRY_PATH)
        summary = reg.search_history_summary()
        assert summary["total_strategies_tested"] == 1
        assert summary["total_strategies_rejected"] == 1
        assert summary["total_strategies_passed"] == 0
        assert summary["total_strategies_failed"] == 0
        assert summary["total_strategies_surviving"] == 0
        # exactly one candidate was ever generated -- "tested vs generated"
        # cannot be silently inflated or deflated relative to each other
        assert summary["total_strategies_generated"] == 1

    def test_selection_bias_status_is_not_silently_marked_pass(self) -> None:
        if not DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("production registry not present in this checkout")
        reg = StrategyRegistry(path=DEFAULT_REGISTRY_PATH)
        summary = reg.search_history_summary()
        # with exactly one candidate ever tested, there is no selection
        # among alternatives to correct for -- PASS would misrepresent a
        # formal multiple-testing correction that was never performed.
        assert summary["selection_bias_status"] != "PASS"

    def test_strat_000001_is_rejected_in_production_registry(self) -> None:
        if not DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("production registry not present in this checkout")
        reg = StrategyRegistry(path=DEFAULT_REGISTRY_PATH)
        candidate = reg.get("STRAT-000001")
        assert candidate.state == CandidateState.REJECTED
        assert "HOLDOUT_TESTED" not in [h["state"] for h in candidate.history]
