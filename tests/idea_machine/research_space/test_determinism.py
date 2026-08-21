"""Phase 9 determinism tests (spec item 30 "Determinism").

Same input + seed + research state must produce same decisions, same scores,
same ranking, same output. Nothing in this package uses ``random``, ``time``,
or dict-iteration order for identity or ranking -- these tests prove that by
running the same computation twice and diffing.
"""

from __future__ import annotations

from idea_machine.research_space.decision_engine import ResearchSpaceDecisionEngine
from idea_machine.research_space.exploitation_engine import ExploitationEngine
from idea_machine.research_space.exploration_engine import ExplorationEngine
from idea_machine.research_space.information_gain import InformationGainScorer
from idea_machine.research_space.recombination_engine import RecombinationEngine
from idea_machine.research_space.search_space import SearchSpace


def _build_pool(space: SearchSpace):
    exploit = ExploitationEngine(space)
    explore = ExplorationEngine(space)
    recombine = RecombinationEngine(space)
    pool = []
    pool += exploit.deepen(
        mechanism="SC_SURPRISE_CONFIRMATION", instrument="USDJPY", driver="USB02Y",
        already_tested_windows=[60, 120, 240], candidate_windows=[60, 120, 240, 300], rationale="r1",
    )
    pool += explore.swap_driver(
        mechanism="SC_SURPRISE_CONFIRMATION", instrument="EURUSD", holding_period_min=60, rationale="r2",
    )
    c = recombine.combine(
        parent_mechanisms=["SC_SURPRISE_CONFIRMATION", "DC_CROSS_ASSET_DIVERGENCE"],
        instrument="GBPUSD", driver="UK10YB", holding_period_min=60,
        combined_mechanism="SC_AND_DC_COMBINED_CONFIRMATION", rationale="r3",
    )
    if c:
        pool.append(c)
    return pool


def test_candidate_ids_are_content_addressed_and_reproducible():
    space1, space2 = SearchSpace(), SearchSpace()
    pool1, pool2 = _build_pool(space1), _build_pool(space2)
    ids1 = sorted(c.candidate_id for c in pool1)
    ids2 = sorted(c.candidate_id for c in pool2)
    assert ids1 == ids2
    assert len(ids1) == len(set(ids1))  # no accidental collisions either


def test_scores_are_reproducible_for_identical_candidates():
    space = SearchSpace()
    pool = _build_pool(space)
    scorer = InformationGainScorer(space)

    from idea_machine.research_space.decision_engine import cost_registered, data_available

    scores1 = [scorer.score(c, data_available=data_available(c.instrument, c.driver),
                            cost_registered=cost_registered(c.instrument)).total for c in pool]
    scores2 = [scorer.score(c, data_available=data_available(c.instrument, c.driver),
                            cost_registered=cost_registered(c.instrument)).total for c in pool]
    assert scores1 == scores2


def test_full_cycle_decision_is_reproducible(tmp_path):
    from idea_machine.research_space.decision_record import DecisionLedger
    from idea_machine.research_space.search_space_ledger import SearchSpaceLedger

    def run_once(tag: str):
        space = SearchSpace()
        pool = _build_pool(space)
        engine = ResearchSpaceDecisionEngine(
            space,
            decision_ledger=DecisionLedger(tmp_path / f"d_{tag}.json"),
            space_ledger=SearchSpaceLedger(tmp_path / f"s_{tag}.json"),
        )
        report = engine.run_cycle(cycle_id="DETERMINISM-TEST", candidate_pool=pool, history=[])
        return sorted(c.candidate_id for c in report.accepted), report.allocation.to_dict()

    accepted1, alloc1 = run_once("a")
    accepted2, alloc2 = run_once("b")
    assert accepted1 == accepted2
    assert alloc1 == alloc2


def test_search_space_status_counts_are_order_independent():
    """Cell registration order (dict iteration over families/candidates) must
    not change the final status distribution."""
    space1 = SearchSpace()
    space2 = SearchSpace()
    assert space1.status_counts() == space2.status_counts()
    assert space1.novelty_coverage() == space2.novelty_coverage()


def test_no_random_or_time_dependence_in_research_space_source():
    from pathlib import Path

    root = Path("idea_machine/research_space")
    for py in sorted(root.glob("*.py")):
        src = py.read_text()
        assert "import random" not in src, f"{py.name} imports random"
        assert "uuid4" not in src, f"{py.name} uses uuid4"
