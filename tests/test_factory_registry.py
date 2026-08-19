"""Tests for core.factory.registry — candidate registration, lifecycle,
immutability, rejection preservation, and search-history accounting."""

from __future__ import annotations

import json

import pytest

from core.factory.candidate import CandidateSpecError, FrozenCandidateMutationError, StrategyCandidateSpec
from core.factory.generator import build_spec, generate_candidates
from core.factory.registry import (
    CandidateNotFoundError,
    DuplicateCandidateError,
    RegistryCorruptionError,
    StrategyRegistry,
)
from core.factory.state_machine import CandidateState, IllegalStateTransitionError


def _spec(**overrides) -> StrategyCandidateSpec:
    base = dict(
        entry_rule="model probability > 0.55",
        exit_rule="stop/target/max_hold",
        features=("momentum_5", "rsi_14"),
        timeframe="H1",
        direction="long_only",
        stop_loss="1.5x ATR",
        take_profit="2.0x ATR",
        max_hold_bars=24,
        position_sizing="fixed_fractional",
        transaction_cost_model="realistic",
    )
    base.update(overrides)
    return StrategyCandidateSpec(**base)


def _walk_to_frozen(reg: StrategyRegistry, candidate_id: str) -> None:
    """Advance ``candidate_id`` through the full, real pre-holdout spine
    (ML-001-STRATEGY-FACTORY-SPEC.md §4): TRAIN -> OOS -> WALK_FORWARD ->
    ROBUSTNESS -> COST_STRESS -> STATISTICS -> MULTIPLE_TESTING ->
    CANDIDATE_FREEZE. Registers a minimal search-space declaration first,
    since MULTIPLE_TESTING_REVIEWED cannot legally be entered without one.
    Shared by every test that needs a FROZEN-or-later candidate, so a
    future spine change only needs to be taught to this one helper."""
    reg.transition(candidate_id, CandidateState.DATA_VALIDATED, reason="ok")
    reg.transition(candidate_id, CandidateState.TRAINED, reason="ok")
    reg.transition(candidate_id, CandidateState.OOS_TESTED, reason="ok")
    reg.transition(candidate_id, CandidateState.WFA_TESTED, reason="ok")
    reg.transition(candidate_id, CandidateState.ROBUSTNESS_TESTED, reason="ok")
    reg.transition(candidate_id, CandidateState.COST_TESTED, reason="ok")
    reg.transition(candidate_id, CandidateState.STATISTICALLY_VALIDATED, reason="ok")
    reg.set_search_space(
        search_space={"stop_loss_atr_multiple": [1.0, 2.0]},
        search_method="seeded_uniform_grid_sample",
        parameter_search_count=2,
        model_search_count=1,
        selection_criteria="test helper",
    )
    reg.transition(candidate_id, CandidateState.MULTIPLE_TESTING_REVIEWED, reason="accounting recorded")
    reg.transition(candidate_id, CandidateState.FROZEN, reason="freeze for holdout")


def _holdout_event(reg: StrategyRegistry, candidate_id: str, **overrides) -> "HoldoutAccessEvent":
    """A synthetic, test-only HoldoutAccessEvent (Generation 2, closing
    G1-M2) -- NEVER references real holdout data. ``dataset_checksum``
    and ``holdout_partition_identity`` below are fixture strings, not
    derived from data/csv/*_H1.csv."""
    from core.factory.holdout_access import HoldoutAccessEvent

    candidate = reg.get(candidate_id)
    base = dict(
        candidate_id=candidate_id,
        candidate_version=candidate.version,
        dataset_id="TEST-DATASET-FIXTURE",
        dataset_checksum="deadbeef" * 8,
        holdout_partition_identity="TEST-PURE-HOLDOUT-FIXTURE-PARTITION",
        access_timestamp="2026-01-01T00:00:00+00:00",
        frozen_state_confirmed=True,
        evidence_reference="test-fixture, not a real holdout evaluation",
    )
    base.update(overrides)
    return HoldoutAccessEvent(**base)


def _walk_to_holdout_tested(reg: StrategyRegistry, candidate_id: str) -> None:
    """``_walk_to_frozen`` plus the final, event-backed step into
    HOLDOUT_TESTED."""
    _walk_to_frozen(reg, candidate_id)
    reg.transition(
        candidate_id,
        CandidateState.HOLDOUT_TESTED,
        reason="holdout evaluated (test fixture)",
        holdout_access_event=_holdout_event(reg, candidate_id),
    )


class TestSpecCompleteness:
    def test_complete_spec_constructs(self) -> None:
        _spec()

    def test_missing_entry_rule_raises(self) -> None:
        with pytest.raises(CandidateSpecError):
            _spec(entry_rule="")

    def test_zero_max_hold_raises(self) -> None:
        with pytest.raises(CandidateSpecError):
            _spec(max_hold_bars=0)

    def test_empty_features_raises(self) -> None:
        with pytest.raises(CandidateSpecError):
            _spec(features=())

    def test_checksum_is_deterministic_and_content_sensitive(self) -> None:
        a = _spec()
        b = _spec()
        c = _spec(max_hold_bars=48)
        assert a.spec_checksum() == b.spec_checksum()
        assert a.spec_checksum() != c.spec_checksum()


class TestCandidateIdentity:
    def test_ids_are_monotonic_and_zero_padded(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        first = reg.allocate_candidate_id()
        second = reg.allocate_candidate_id()
        assert first == "STRAT-000001"
        assert second == "STRAT-000002"

    def test_registering_same_id_twice_raises(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c1 = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc123", dataset_id="D")
        with pytest.raises(DuplicateCandidateError):
            reg.register(
                _spec(), generator_id="G", generator_parameters={}, code_version="abc123", dataset_id="D",
                candidate_id=c1.candidate_id,
            )


class TestPersistenceRoundTrip:
    def test_registry_survives_reload(self, tmp_path) -> None:
        path = tmp_path / "registry.json"
        reg = StrategyRegistry(path=path)
        c = reg.register(_spec(), generator_id="G", generator_parameters={"x": 1}, code_version="abc", dataset_id="D")
        reg.transition(c.candidate_id, CandidateState.DATA_VALIDATED, reason="data ok")

        reloaded = StrategyRegistry(path=path)
        loaded = reloaded.get(c.candidate_id)
        assert loaded.state == CandidateState.DATA_VALIDATED
        assert loaded.spec.spec_checksum() == c.spec.spec_checksum()
        assert len(loaded.history) == 2

    def test_corrupted_registry_file_raises_not_silently_resets(self, tmp_path) -> None:
        path = tmp_path / "registry.json"
        path.write_text("{not valid json")
        with pytest.raises(RegistryCorruptionError):
            StrategyRegistry(path=path)

    def test_unknown_candidate_id_raises(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        with pytest.raises(CandidateNotFoundError):
            reg.get("STRAT-999999")


class TestLifecycleAndImmutability:
    def test_illegal_transition_is_rejected_and_state_unchanged(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        with pytest.raises(IllegalStateTransitionError):
            reg.transition(c.candidate_id, CandidateState.LIVE_CANDIDATE, reason="skip everything")
        assert reg.get(c.candidate_id).state == CandidateState.GENERATED

    def test_mutation_allowed_before_frozen(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        reg.assert_mutation_allowed(c.candidate_id)  # must not raise

    def test_mutation_blocked_once_frozen(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_frozen(reg, c.candidate_id)
        with pytest.raises(FrozenCandidateMutationError):
            reg.assert_mutation_allowed(c.candidate_id)

    def test_mutation_already_blocked_at_oos_tested_before_frozen(self, tmp_path) -> None:
        """Per registry.py's _FROZEN_OR_LATER: immutability begins at
        OOS_TESTED, not only at the later, named FROZEN checkpoint -- a
        candidate's spec must not be swappable in response to OOS/WFA/
        robustness/cost/statistics feedback either."""
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        reg.transition(c.candidate_id, CandidateState.DATA_VALIDATED, reason="ok")
        reg.transition(c.candidate_id, CandidateState.TRAINED, reason="ok")
        reg.assert_mutation_allowed(c.candidate_id)  # still mutable through TRAINED
        reg.transition(c.candidate_id, CandidateState.OOS_TESTED, reason="ok")
        with pytest.raises(FrozenCandidateMutationError):
            reg.assert_mutation_allowed(c.candidate_id)

    def test_derive_new_version_creates_separate_candidate_not_a_mutation(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        parent = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        _walk_to_frozen(reg, parent.candidate_id)
        reg.reject(parent.candidate_id, reason="failed holdout", failed_phase="HOLDOUT")

        child_spec = _spec(max_hold_bars=48)
        child = reg.derive_new_version(
            parent.candidate_id, child_spec, generator_id="G", generator_parameters={"max_hold_bars": 48},
            code_version="abc", dataset_id="D",
        )
        assert child.candidate_id != parent.candidate_id
        assert child.parent_candidate_id == parent.candidate_id
        assert child.state == CandidateState.GENERATED
        # parent's own record is untouched
        assert reg.get(parent.candidate_id).state == CandidateState.REJECTED
        assert reg.get(parent.candidate_id).spec.spec_checksum() != child.spec.spec_checksum()


class TestRejectedPopulationPreserved:
    def test_rejected_candidates_remain_queryable_with_reason(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        c = reg.register(_spec(), generator_id="G", generator_parameters={}, code_version="abc", dataset_id="D")
        reg.reject(c.candidate_id, reason="insufficient trade count", failed_phase="STATISTICS")

        population = reg.rejected_population()
        assert len(population) == 1
        assert population[0].candidate_id == c.candidate_id
        assert "insufficient trade count" in population[0].history[-1]["reason"]
        assert "STATISTICS" in population[0].history[-1]["reason"]


class TestSearchHistoryAccounting:
    def test_counters_increment_on_registration_and_terminal_transitions(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        drawn = generate_candidates(seed=42, count=5)
        ids = []
        for d in drawn:
            c = reg.register(
                d["spec"], generator_id=d["generator_id"], generator_parameters=d["generator_parameters"],
                code_version="abc", dataset_id="D",
            )
            ids.append(c.candidate_id)

        for cid in ids[:3]:
            reg.transition(cid, CandidateState.DATA_VALIDATED, reason="ok")
        reg.reject(ids[0], reason="leakage detected", failed_phase="LEAKAGE_AUDIT")
        reg.transition(ids[1], CandidateState.TRAINED, reason="ok")
        reg.transition(ids[1], CandidateState.FAILED, reason="model training diverged")

        summary = reg.search_history_summary()
        assert summary["total_strategies_generated"] == 5
        assert summary["total_strategies_tested"] == 3
        assert summary["total_strategies_rejected"] == 1
        assert summary["total_strategies_failed"] == 1

    def test_search_space_is_recorded_not_defaulted_to_passing(self, tmp_path) -> None:
        reg = StrategyRegistry(path=tmp_path / "registry.json")
        reg.set_search_space(
            search_space={"stop_loss_atr_multiple": [1.0, 2.0]},
            search_method="seeded_uniform_grid_sample",
            parameter_search_count=5,
            model_search_count=1,
            selection_criteria="statistically_validated + EVG_PASS",
        )
        summary = reg.search_history_summary()
        assert summary["search_method"] == "seeded_uniform_grid_sample"
        assert summary["selection_bias_status"] == "UNACCOUNTED"  # never silently defaulted to passing


class TestDeterministicGenerator:
    def test_same_seed_produces_identical_candidates(self) -> None:
        a = generate_candidates(seed=7, count=10)
        b = generate_candidates(seed=7, count=10)
        assert [x["spec"].spec_checksum() for x in a] == [x["spec"].spec_checksum() for x in b]

    def test_different_seed_can_produce_different_candidates(self) -> None:
        a = generate_candidates(seed=1, count=20)
        b = generate_candidates(seed=2, count=20)
        checksums_a = {x["spec"].spec_checksum() for x in a}
        checksums_b = {x["spec"].spec_checksum() for x in b}
        assert checksums_a != checksums_b

    def test_generator_never_touches_global_random_state(self) -> None:
        import random

        random.seed(12345)
        state_before = random.getstate()
        generate_candidates(seed=99, count=15)
        assert random.getstate() == state_before
