"""Generation 5 — Governance Closure.

Closes the two open governance decisions Generation 4 recorded rather
than resolved (ML-001-GENERATION-4-REPORT.md §12), and pins the
epistemic-chain closure that Generation 4 left incomplete.

OGD-1 (holdout ordering) is a documentation reconciliation with no code
change -- the committed state machine was already the authority and
already enforced the right order; the test below pins that authority so
a future generation cannot quietly re-open it by executing a different
order. OGD-2 (counter naming) is a real, backward-compatible schema
change, tested here for both the rename and the no-data-loss migration.
"""

from __future__ import annotations

import json

import pytest

from core.factory.registry import StrategyRegistry
from core.factory.state_machine import CandidateState, IllegalStateTransitionError, assert_legal_transition
from tests.test_factory_registry import _spec


class TestOGD2CounterRenameAndMigration:
    def test_new_counter_name_is_used_and_legacy_name_is_gone(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "reg.json")
        summary = reg.search_history_summary()
        assert "total_strategies_ever_statistically_validated" in summary
        assert "total_strategies_surviving" not in summary

    def test_legacy_registry_file_migrates_without_losing_the_count(self, tmp_path) -> None:
        """The migration that makes the rename safe: a registry written
        before the rename carries the OLD key with a real, non-zero
        historical count. Loading it must carry that number forward, not
        silently reset it to the new key's default of 0."""
        path = tmp_path / "legacy.json"
        path.write_text(json.dumps({
            "next_id": 3,
            "search_history": {
                "total_strategies_generated": 2,
                "total_strategies_surviving": 7,  # legacy key, real historical value
            },
            "candidates": {},
        }))
        reg = StrategyRegistry(path=path)
        summary = reg.search_history_summary()
        assert summary["total_strategies_ever_statistically_validated"] == 7  # carried forward
        assert "total_strategies_surviving" not in summary  # stale name retired
        assert summary["total_strategies_generated"] == 2  # untouched neighbours survive

    def test_already_migrated_file_is_not_clobbered_by_a_stale_legacy_key(self, tmp_path) -> None:
        """If both keys are somehow present, the already-migrated new key
        wins -- the legacy key is by definition the older writer's value."""
        path = tmp_path / "both.json"
        path.write_text(json.dumps({
            "next_id": 1,
            "search_history": {
                "total_strategies_surviving": 1,
                "total_strategies_ever_statistically_validated": 5,
            },
            "candidates": {},
        }))
        reg = StrategyRegistry(path=path)
        assert reg.search_history_summary()["total_strategies_ever_statistically_validated"] == 5

    def test_counter_still_increments_on_the_statistics_gate_only(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "reg.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="v", dataset_id="D")
        for state in (CandidateState.DATA_VALIDATED, CandidateState.TRAINED, CandidateState.OOS_TESTED,
                      CandidateState.WFA_TESTED, CandidateState.ROBUSTNESS_TESTED, CandidateState.COST_TESTED):
            reg.transition(c.candidate_id, state, reason="ok")
        assert reg.search_history_summary()["total_strategies_ever_statistically_validated"] == 0
        reg.transition(c.candidate_id, CandidateState.STATISTICALLY_VALIDATED, reason="ok")
        assert reg.search_history_summary()["total_strategies_ever_statistically_validated"] == 1
        # and it is MONOTONIC: a later rejection does not decrement it
        reg.reject(c.candidate_id, reason="no edge", failed_phase="EVG")
        assert reg.search_history_summary()["total_strategies_ever_statistically_validated"] == 1

    def test_production_registry_reads_the_migrated_counter(self) -> None:
        from core.factory.registry import DEFAULT_REGISTRY_PATH

        if not DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("production registry not present")
        summary = StrategyRegistry(path=DEFAULT_REGISTRY_PATH).search_history_summary()
        assert summary["total_strategies_ever_statistically_validated"] == 1  # STRAT-000002 reached the gate
        assert "total_strategies_surviving" not in summary


class TestOGD1HoldoutOrderingIsSettled:
    """OGD-1 resolution: the committed state machine is the single
    authority on holdout ordering. Generation 4's execution contract
    described a different phase numbering; the run correctly deferred to
    the committed governance. These assertions make that authority
    permanent so no future generation can execute a different order and
    call it a reconciliation."""

    def test_holdout_is_reachable_only_from_frozen(self) -> None:
        from core.factory.state_machine import _ALLOWED_TRANSITIONS

        sources = [s.value for s, nexts in _ALLOWED_TRANSITIONS.items()
                   if CandidateState.HOLDOUT_TESTED in nexts]
        assert sources == ["FROZEN"]

    def test_every_reusable_data_gate_precedes_holdout(self) -> None:
        for earlier in (CandidateState.TRAINED, CandidateState.OOS_TESTED, CandidateState.WFA_TESTED,
                        CandidateState.ROBUSTNESS_TESTED, CandidateState.COST_TESTED,
                        CandidateState.STATISTICALLY_VALIDATED, CandidateState.MULTIPLE_TESTING_REVIEWED):
            with pytest.raises(IllegalStateTransitionError):
                assert_legal_transition(earlier, CandidateState.HOLDOUT_TESTED)

    def test_evg_is_reachable_only_after_holdout(self) -> None:
        from core.factory.state_machine import _ALLOWED_TRANSITIONS

        sources = [s.value for s, nexts in _ALLOWED_TRANSITIONS.items()
                   if CandidateState.EVG_REVIEW in nexts]
        assert sources == ["HOLDOUT_TESTED"]

    def test_the_real_strat_000002_history_followed_this_order(self) -> None:
        from core.factory.registry import DEFAULT_REGISTRY_PATH

        if not DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("production registry not present")
        history = [h["state"] for h in StrategyRegistry(path=DEFAULT_REGISTRY_PATH).get("STRAT-000002").history]
        assert history.index("FROZEN") < history.index("HOLDOUT_TESTED") < history.index("EVG_REVIEW")
        for gate in ("OOS_TESTED", "WFA_TESTED", "ROBUSTNESS_TESTED", "COST_TESTED",
                     "STATISTICALLY_VALIDATED", "MULTIPLE_TESTING_REVIEWED"):
            assert history.index(gate) < history.index("HOLDOUT_TESTED")


class TestTerminalSealing:
    """Governance closure: a terminally-rejected candidate stays rejected,
    and its holdout cannot be re-consumed under any path."""

    def test_strat_000002_is_terminal_and_cannot_be_revived(self) -> None:
        from core.factory.registry import DEFAULT_REGISTRY_PATH

        if not DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("production registry not present")
        reg = StrategyRegistry(path=DEFAULT_REGISTRY_PATH)
        assert reg.get("STRAT-000002").state == CandidateState.REJECTED
        for target in (CandidateState.HOLDOUT_TESTED, CandidateState.EVG_REVIEW,
                       CandidateState.RESEARCH_CANDIDATE, CandidateState.TRAINED):
            with pytest.raises(IllegalStateTransitionError):
                assert_legal_transition(CandidateState.REJECTED, target)

    def test_both_production_candidates_are_terminally_rejected(self) -> None:
        from core.factory.registry import DEFAULT_REGISTRY_PATH

        if not DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("production registry not present")
        reg = StrategyRegistry(path=DEFAULT_REGISTRY_PATH)
        states = {c.candidate_id: c.state for c in reg.list_all()}
        assert states == {"STRAT-000001": CandidateState.REJECTED, "STRAT-000002": CandidateState.REJECTED}

    def test_holdout_was_consumed_exactly_once_across_all_history(self) -> None:
        from core.factory.registry import DEFAULT_REGISTRY_PATH

        if not DEFAULT_REGISTRY_PATH.exists():
            pytest.skip("production registry not present")
        reg = StrategyRegistry(path=DEFAULT_REGISTRY_PATH)
        holdout_entries = [h for c in reg.list_all() for h in c.history if h["state"] == "HOLDOUT_TESTED"]
        assert len(holdout_entries) == 1  # STRAT-000002 only, exactly once
