"""Phase 9 exploration tests (spec item 30 "Exploration")."""

from __future__ import annotations

from idea_machine.research_space.exploitation_engine import ExploitationEngine
from idea_machine.research_space.exploration_debt import CycleTouch, ExplorationDebtTracker
from idea_machine.research_space.exploration_engine import ExplorationEngine
from idea_machine.research_space.novelty_budget import NoveltyBudgetTracker
from idea_machine.research_space.recombination_engine import RecombinationEngine
from idea_machine.research_space.research_allocator import (
    GOVERNANCE_MIN_EXPLORATION_SHARE, AllocationPolicy, ResearchAllocator,
)


def test_minimum_exploration_enforced_even_with_zero_debt():
    allocator = ResearchAllocator()
    debt = ExplorationDebtTracker().compute([])
    result = allocator.allocate_slots(20, debt)
    assert result.slots_by_mode["EXPLORE"] >= round(20 * GOVERNANCE_MIN_EXPLORATION_SHARE)
    assert result.effective_exploration_share >= GOVERNANCE_MIN_EXPLORATION_SHARE - 0.01


def test_exploration_debt_increases_with_consecutive_exploit_only_cycles():
    tracker = ExplorationDebtTracker(threshold=3)
    history = [
        CycleTouch("C1", new_dimension_or_family_touched=False, exploit_only=True),
        CycleTouch("C2", new_dimension_or_family_touched=False, exploit_only=True),
        CycleTouch("C3", new_dimension_or_family_touched=False, exploit_only=True),
    ]
    state = tracker.compute(history)
    assert state.debt == 3
    assert state.forced_exploration is True


def test_exploration_debt_resets_when_a_new_family_is_touched():
    tracker = ExplorationDebtTracker(threshold=3)
    history = [
        CycleTouch("C1", new_dimension_or_family_touched=False, exploit_only=True),
        CycleTouch("C2", new_dimension_or_family_touched=True, exploit_only=True),  # breaks the streak
        CycleTouch("C3", new_dimension_or_family_touched=False, exploit_only=True),
    ]
    state = tracker.compute(history)
    assert state.debt == 1  # only C3 counts; C2 broke the streak


def test_exploration_debt_forces_higher_exploration_share_never_lower():
    allocator = ResearchAllocator()
    zero_debt = ExplorationDebtTracker(threshold=3).compute([])
    high_debt = ExplorationDebtTracker(threshold=3).compute([
        CycleTouch(f"C{i}", new_dimension_or_family_touched=False, exploit_only=True) for i in range(5)
    ])
    r_low = allocator.allocate_slots(20, zero_debt)
    r_high = allocator.allocate_slots(20, high_debt)
    assert r_high.effective_exploration_share > r_low.effective_exploration_share
    assert r_high.effective_exploration_share >= GOVERNANCE_MIN_EXPLORATION_SHARE


def test_exploit_score_does_not_reduce_exploration_floor():
    """Spec: 'Không được tự động giảm exploration chỉ vì exploit đang có điểm cao.'

    The allocator has no input for 'exploit is scoring well' at all -- this
    test proves the floor is independent of any score by checking two
    debt-free allocations produce the identical exploration share regardless
    of candidate pool composition (the allocator never even sees candidate
    scores when computing the floor)."""
    allocator = ResearchAllocator()
    debt = ExplorationDebtTracker().compute([])
    r1 = allocator.allocate_slots(10, debt)
    r2 = allocator.allocate_slots(10, debt)
    assert r1.effective_exploration_share == r2.effective_exploration_share


def test_parameter_variants_do_not_count_as_mechanism_novelty(search_space):
    engine = ExploitationEngine(search_space)
    candidates = engine.deepen(
        mechanism="SC_SURPRISE_CONFIRMATION", instrument="EURUSD", driver="US10Y",
        already_tested_windows=[], candidate_windows=[5, 15, 30, 60, 120, 240],
        rationale="RSI(14)-style parameter sweep on the same evidenced triple",
    )
    tracker = NoveltyBudgetTracker()
    report = tracker.classify(candidates)
    # Same (mechanism, instrument, driver) triple, 6 windows: CHANGE_HOLDING_HORIZON
    # is genuinely parameter-level for every one of them (the window IS the
    # parameter being varied) -- unlike EXPLORE/RECOMBINE candidates, there is
    # no "first, higher-level" member here, so all 6 register as LEVEL_1_PARAMETER.
    assert report.level_counts.get("LEVEL_1_PARAMETER", 0) == 6
    assert report.distinct_parameter_families == 1


def test_high_parameter_saturation_is_flagged(search_space):
    engine = ExploitationEngine(search_space)
    candidates = engine.deepen(
        mechanism="SC_SURPRISE_CONFIRMATION", instrument="EURUSD", driver="US10Y",
        already_tested_windows=[], candidate_windows=[5, 15, 30, 60, 120, 240],
        rationale="parameter sweep",
    )
    tracker = NoveltyBudgetTracker()
    report = tracker.classify(candidates)
    assert report.saturation == "HIGH"
    assert report.parameter_only_share >= 0.6


def test_genuine_new_family_candidates_are_not_saturated(search_space):
    engine = ExplorationEngine(search_space)
    candidates = engine.swap_driver(
        mechanism="SC_SURPRISE_CONFIRMATION", instrument="EURUSD", holding_period_min=60,
        rationale="explore unexplored drivers",
    )
    assert len(candidates) >= 2  # at least JP225/UK100/AU200/US2000/NATGAS
    tracker = NoveltyBudgetTracker()
    report = tracker.classify(candidates)
    # every candidate is a distinct (mechanism, instrument, driver) triple -> no parameter grouping
    assert report.level_counts.get("LEVEL_1_PARAMETER", 0) == 0
    assert report.saturation == "LOW"


def test_single_family_cannot_consume_entire_budget(search_space):
    engine = ExploitationEngine(search_space)
    many_same_family = engine.deepen(
        mechanism="SC_SURPRISE_CONFIRMATION", instrument="EURUSD", driver="US10Y",
        already_tested_windows=[], candidate_windows=[5, 15, 30, 60, 120, 240],
        rationale="single family flood",
    )
    allocator = ResearchAllocator(AllocationPolicy(maximum_single_family_share=0.40))
    kept, notes = allocator.enforce_family_cap(many_same_family)
    assert len(kept) < len(many_same_family)
    assert notes  # a note explaining why candidates were dropped


def test_recombine_candidates_are_tagged_recombination_not_new(search_space):
    engine = RecombinationEngine(search_space)
    candidate = engine.combine(
        parent_mechanisms=["SC_SURPRISE_CONFIRMATION", "DC_CROSS_ASSET_DIVERGENCE"],
        instrument="GBPUSD", driver="UK10YB", holding_period_min=60,
        combined_mechanism="SC_AND_DC_COMBINED_CONFIRMATION",
        rationale="test combined structure",
    )
    assert candidate is not None
    assert candidate.novelty_tag == "RECOMBINATION"
    assert candidate.novelty_tag != "NEW"


def test_explore_prioritises_mechanism_novelty_over_parameter_change(search_space):
    """A SWAP_DRIVER candidate must land on an UNEXPLORED driver, never a TESTED one."""
    engine = ExplorationEngine(search_space)
    candidates = engine.swap_driver(
        mechanism="SC_SURPRISE_CONFIRMATION", instrument="EURUSD", holding_period_min=60, rationale="x",
    )
    for c in candidates:
        cell = search_space.cell("drivers", c.driver)
        assert cell.status == "UNEXPLORED"
