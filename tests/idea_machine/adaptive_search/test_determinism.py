"""Determinism tests (spec item 17 "Determinism")."""

from __future__ import annotations

from idea_machine.adaptive_search import AdaptiveSearchController
from idea_machine.search_space_registry import SearchSpaceRegistry


def test_identical_input_produces_identical_search_plan(memory):
    ctrl1 = AdaptiveSearchController(memory=memory, registry=SearchSpaceRegistry(memory))
    ctrl2 = AdaptiveSearchController(memory=memory, registry=SearchSpaceRegistry(memory))
    plan1 = ctrl1.plan(total_slots=10)
    plan2 = ctrl2.plan(total_slots=10)
    assert plan1.explore_regions == plan2.explore_regions
    assert plan1.exploit_regions == plan2.exploit_regions
    assert plan1.explore_slots == plan2.explore_slots


def test_identical_input_produces_identical_region_ids(memory):
    reg1 = SearchSpaceRegistry(memory)
    reg2 = SearchSpaceRegistry(memory)
    ids1 = sorted(r.region_id for r in reg1.all_regions())
    ids2 = sorted(r.region_id for r in reg2.all_regions())
    assert ids1 == ids2


def test_identical_input_produces_identical_hypothesis_ordering(tmp_path, memory):
    from idea_machine.search_decision_ledger import SearchDecisionLedger

    def run_once(tag):
        ctrl = AdaptiveSearchController(memory=memory, registry=SearchSpaceRegistry(memory),
                                        decision_ledger=SearchDecisionLedger(tmp_path / f"sdl_{tag}.json"))
        result = ctrl.run_cycle(cycle_id="DET-TEST", total_slots=8)
        return [p.proposal_id for p in result.selected]

    order1 = run_once("a")
    order2 = run_once("b")
    assert order1 == order2


def test_region_id_is_content_addressed_not_insertion_order():
    from idea_machine.search_space_registry import region_id_for

    dims_a = {"instrument": "EURUSD", "macro_driver": "US10Y"}
    dims_b = {"macro_driver": "US10Y", "instrument": "EURUSD"}  # same content, different key order
    assert region_id_for(dims_a) == region_id_for(dims_b)
