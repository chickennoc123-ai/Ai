"""Exploration tests (spec item 17)."""

from __future__ import annotations

from idea_machine.exploration_engine import ExplorationEngine, is_parameter_only_change
from idea_machine.search_space_registry import UNEXPLORED


def test_unexplored_region_selected(registry):
    engine = ExplorationEngine(registry)
    proposals = engine.propose()
    assert len(proposals) > 0
    for p in proposals:
        region = registry.get(p.region_id)
        assert region.status == UNEXPLORED


def test_parameter_tweak_is_not_considered_exploration():
    before = {"mechanism": "SC_SURPRISE_CONFIRMATION", "instrument": "EURUSD",
              "macro_driver": "US10Y", "holding_horizon": "60"}
    after = {"mechanism": "SC_SURPRISE_CONFIRMATION", "instrument": "EURUSD",
             "macro_driver": "US10Y", "holding_horizon": "90"}
    assert is_parameter_only_change(before, after) is True


def test_new_mechanism_is_not_a_parameter_tweak():
    before = {"mechanism": "SC_SURPRISE_CONFIRMATION", "instrument": "EURUSD", "macro_driver": "US10Y"}
    after = {"mechanism": "SC_AND_DC_COMBINED_CONFIRMATION", "instrument": "EURUSD", "macro_driver": "US10Y"}
    assert is_parameter_only_change(before, after) is False


def test_new_interaction_detected_as_distinct_region(registry):
    """A driver never used before (macro_driver) produces a genuinely distinct region."""
    engine = ExplorationEngine(registry)
    proposals = engine.propose()
    drivers = {p.dimensions.get("macro_driver") for p in proposals if p.dimensions.get("macro_driver")}
    assert len(drivers) >= 2  # multiple genuinely distinct, never-tested drivers proposed


def test_exploration_floor_enforced_in_plan():
    from idea_machine.adaptive_search import AdaptiveSearchController, GOVERNANCE_MIN_EXPLORATION_FRACTION

    ctrl = AdaptiveSearchController()
    plan = ctrl.plan(total_slots=20)
    assert plan.explore_slots / plan.total_slots >= GOVERNANCE_MIN_EXPLORATION_FRACTION - 0.01


def test_exploration_reason_codes_present(registry):
    engine = ExplorationEngine(registry)
    proposals = engine.propose(limit=3)
    for p in proposals:
        assert len(p.reason_codes) > 0
        assert "UNEXPLORED_REGION" in p.reason_codes


def test_space_constrained_signal_is_honest_not_fake(registry):
    """If check_space_constrained() reports nothing, there must genuinely be
    enough unexplored regions -- never silently fabricated diversity."""
    engine = ExplorationEngine(registry)
    note = engine.check_space_constrained()
    if note is None:
        assert len(registry.unexplored_regions()) >= 3
