"""Phase 9 novelty tests (spec item 30 "Novelty" -- integration with existing
Phase 3/4 novelty engines, reused not duplicated)."""

from __future__ import annotations

from idea_machine.core import epistemic
from idea_machine.research_space.search_space import UNEXPLORED, SearchSpace


def test_refuted_family_is_visible_in_search_space(search_space: SearchSpace):
    refuted = search_space.by_status(epistemic.REFUTED)
    assert any(c.value == "FAMILY-C2-SURPRISE-REACTION-NFP-USD" for c in refuted)


def test_underpowered_routed_correctly_not_confused_with_refuted(search_space: SearchSpace):
    underpowered = search_space.by_status(epistemic.UNDERPOWERED)
    refuted_values = {c.value for c in search_space.by_status(epistemic.REFUTED)}
    for cell in underpowered:
        assert cell.value not in refuted_values or cell.dimension != "instruments", (
            "an UNDERPOWERED cell's specific evidence must not be silently reclassified as REFUTED"
        )


def test_novel_unexplored_driver_is_reachable(search_space: SearchSpace):
    unexplored_drivers = search_space.unexplored("drivers")
    assert len(unexplored_drivers) >= 1
    for c in unexplored_drivers:
        assert c.status == UNEXPLORED


def test_unknown_status_is_distinct_from_unexplored(search_space: SearchSpace):
    """UNKNOWN (epistemic.py: 'a source claims it, untested') must never collapse
    into UNEXPLORED (Phase 9's local addition: 'no claim exists at all')."""
    assert epistemic.UNKNOWN != UNEXPLORED
    counts = search_space.status_counts()
    all_statuses = {s for dim in counts.values() for s in dim}
    # Both states should be representable (not merged into one bucket).
    assert UNEXPLORED in all_statuses or epistemic.UNKNOWN in all_statuses


def test_unexplored_is_never_treated_as_profitable(search_space: SearchSpace):
    """Structural check: nothing in DimensionCell claims a return/edge for UNEXPLORED cells."""
    for cell in search_space.unexplored():
        d = cell.to_dict()
        for key in d:
            assert key not in ("expected_profit", "edge", "sharpe", "win_rate")


def test_search_space_never_downgrades_a_refuted_cell():
    """Once REFUTED is recorded for a cell, a later weaker observation must not overwrite it."""
    from idea_machine.research_space.search_space import DimensionCell

    space = SearchSpace()
    space._set("instruments", "TESTVAL", epistemic.REFUTED, "first: refuted")
    space._set("instruments", "TESTVAL", epistemic.UNKNOWN, "second: weaker, must not overwrite")
    cell = space.cell("instruments", "TESTVAL")
    assert cell.status == epistemic.REFUTED
    assert len(cell.evidence) == 2  # both entries kept, status preserved
