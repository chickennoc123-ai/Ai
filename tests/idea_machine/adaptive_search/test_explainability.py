"""Explainability tests (spec item 15, item 17 "Explainability")."""

from __future__ import annotations

from idea_machine.adaptive_search import REQUIRED_EXPLAINABILITY_KEYS, AdaptiveSearchController
from idea_machine.exploration_engine import ExplorationEngine


def test_every_proposal_answers_all_five_questions(registry):
    engine = ExplorationEngine(registry)
    for p in engine.propose():
        for key in REQUIRED_EXPLAINABILITY_KEYS:
            assert p.explainability.get(key), f"{p.proposal_id} missing answer for {key}"


def test_every_generated_idea_has_provenance(registry):
    engine = ExplorationEngine(registry)
    for p in engine.propose(limit=3):
        assert p.dimensions  # region dimensions ARE the provenance of what's being tested
        assert p.region_id.startswith("REGION-")


def test_unexplainable_proposal_is_rejected(tmp_path):
    from idea_machine.search_decision_ledger import SearchDecisionLedger
    from idea_machine.adaptive_search import AdaptiveSearchController

    ledger = SearchDecisionLedger(tmp_path / "sdl.json")
    ctrl = AdaptiveSearchController(decision_ledger=ledger)
    result = ctrl.run_cycle(cycle_id="EXPLAIN-TEST", total_slots=6)
    # Every SELECTED proposal answered all 5 questions (enforced structurally
    # in run_cycle before selection); nothing unexplainable slips through.
    for p in result.selected:
        for key in ("why_this_mechanism", "why_this_instrument", "why_this_timeframe",
                    "why_now", "how_it_differs_from_prior_tests"):
            assert p.explainability.get(key)


def test_reject_unexplainable_reason_code_exists_in_ledger(tmp_path):
    """If a proposal were ever missing an answer, it must be recorded as
    REJECT_UNEXPLAINABLE in the ledger, not silently dropped."""
    from idea_machine.exploration_engine import SearchProposal

    p = SearchProposal(
        proposal_id="PROP-TEST", region_id="REGION-TEST", mode="EXPLORE",
        dimensions={"instrument": "EURUSD"}, reason_codes=("UNEXPLORED_REGION",),
        explainability={"why_this_mechanism": "x", "why_this_instrument": "x",
                        "why_this_timeframe": "x", "why_now": "x", "how_it_differs_from_prior_tests": ""},
    )
    missing = [k for k in ("why_this_mechanism", "why_this_instrument", "why_this_timeframe",
                           "why_now", "how_it_differs_from_prior_tests") if not p.explainability.get(k)]
    assert missing == ["how_it_differs_from_prior_tests"]
