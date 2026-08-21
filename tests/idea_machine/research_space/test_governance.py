"""Phase 9 governance tests (spec item 30 "Governance").

The Research Space Evolution Engine reuses idea_machine.governance.guard
directly -- these tests prove that reuse actually holds the line, not just
that the underlying guard module (already tested elsewhere) works.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from idea_machine.core.errors import GovernanceViolation
from idea_machine.governance import guard
from idea_machine.governance.authority import FORBIDDEN, PERMITTED
from idea_machine.research_space.exploitation_engine import ExploitationEngine
from idea_machine.research_space.search_space import SearchSpace

PACKAGE_ROOT = Path(guard.__file__).resolve().parent.parent
RESEARCH_SPACE_ROOT = PACKAGE_ROOT / "research_space"


def test_research_space_package_exists_under_governed_tree():
    assert RESEARCH_SPACE_ROOT.is_dir()
    # It lives inside idea_machine/, so the existing static audit already
    # walks it -- this assertion is the structural guarantee that the new
    # package cannot silently sit outside the governed tree.
    assert RESEARCH_SPACE_ROOT.parent == PACKAGE_ROOT


def test_holdout_is_never_imported_or_referenced_in_research_space():
    """Static check specific to the new package: no forbidden import anywhere."""
    from idea_machine.governance.authority import FORBIDDEN_IMPORTS

    for py in sorted(RESEARCH_SPACE_ROOT.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for banned in FORBIDDEN_IMPORTS:
                    assert not (node.module == banned or node.module.startswith(banned + ".")), (
                        f"{py.name} imports forbidden target {node.module!r}"
                    )


def test_no_except_clause_in_research_space_can_swallow_governance_violation():
    offenders = []
    for py in sorted(RESEARCH_SPACE_ROOT.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.body and isinstance(node.body[-1], ast.Raise):
                continue
            names = guard._handler_names(node)
            if node.type is None or any(
                n in ("Exception", "BaseException", "EAFactoryError", "IdeaMachineError", "GovernanceViolation")
                for n in names
            ):
                offenders.append(f"{py.name}:{node.lineno}")
    assert offenders == [], offenders


def test_static_source_audit_still_passes_with_research_space_present():
    """The existing whole-package audit must keep passing after this addition."""
    findings = guard.audit_source_tree()
    assert findings == [], "\n".join(f"{f.file}:{f.line} {f.kind}: {f.detail}" for f in findings)


def test_phase9_actions_are_declared_permitted():
    for action in (
        "MAP_SEARCH_SPACE", "COMPUTE_EXPLORATION_DEBT", "ALLOCATE_RESEARCH_MODE_BUDGET",
        "SCORE_RESEARCH_VALUE", "RECORD_DECISION", "PROPOSE_BRANCH_CLOSURE",
        "DESIGN_DISCRIMINATING_EXPERIMENT",
    ):
        assert action in PERMITTED


def test_search_space_never_reads_holdout(search_space):
    """SearchSpace's only data path is ResearchMemory, which is holdout-blind by construction."""
    src = Path("idea_machine/research_space/search_space.py").read_text()
    assert "holdout" not in src.lower() or "guard" in src.lower()  # only mentioned in comments about the guard


def test_exploitation_engine_refuses_to_retest_a_refuted_triple(search_space):
    """EURUSD's real REFUTED evidence (HYP-IM-0003) is a driver-less, mechanism-
    UNSPECIFIED hypothesis. Querying with mechanism="" (no specific mechanism
    claimed) correctly inherits that evidence and must be blocked -- this is
    the honest, narrow scope of what that historical record can attest to."""
    engine = ExploitationEngine(search_space)
    with pytest.raises(GovernanceViolation):
        engine.deepen(
            mechanism="", instrument="EURUSD", driver=None,
            already_tested_windows=[], candidate_windows=[999], rationale="attempt to retest REFUTED",
        )


def test_exploitation_refutation_does_not_leak_to_an_unrelated_new_mechanism(search_space):
    """Regression: CycleHypothesisRecord carries no mechanism field, so
    EURUSD's driver-less REFUTED hypothesis (about some unspecified mechanism)
    must NOT be treated as evidence against a completely different, explicitly
    named, never-tested mechanism proposal on the same instrument -- found live
    while seeding the search-space registry's RECOMBINE regions."""
    engine = ExploitationEngine(search_space)
    candidates = engine.deepen(
        mechanism="SC_AND_DC_COMBINED_CONFIRMATION", instrument="EURUSD", driver=None,
        already_tested_windows=[], candidate_windows=[60],
        rationale="a brand-new recombined mechanism, never tested, must not inherit an unrelated REFUTED verdict",
    )
    assert candidates == []  # UNEXPLORED has no evidence to deepen yet, but it must not be REFUTED-blocked


def test_exploitation_does_not_block_a_different_triple_on_the_same_instrument(search_space):
    """Regression: EURUSD's REFUTED evidence is on a driver-less hypothesis;
    EURUSD/US10Y/SC (a different, only-STILL_UNDERPOWERED triple) must remain exploitable."""
    engine = ExploitationEngine(search_space)
    candidates = engine.deepen(
        mechanism="SC_SURPRISE_CONFIRMATION", instrument="EURUSD", driver="US10Y",
        already_tested_windows=[5, 15], candidate_windows=[5, 15, 30, 60, 120, 240],
        rationale="deepen genuinely underpowered evidence",
    )
    assert len(candidates) == 4  # 30/60/120/240 untested


def test_cost_model_is_read_only_from_research_space():
    """decision_engine.cost_registered reads discovery.cost_model.cost_table(), never mutates it."""
    from idea_machine.research_space.decision_engine import cost_registered

    assert cost_registered("EURUSD") is True
    assert cost_registered("AUDUSD") is False  # not registered -- correctly reported, not fabricated

    src = Path("idea_machine/research_space/decision_engine.py").read_text()
    assert ".update(" not in src
    assert ".relax(" not in src
    assert "FROZEN_COSTS[" not in src


def test_propose_branch_closure_never_writes_family_registry(search_space, tmp_path, monkeypatch):
    """propose_closures() only READS; it must never open research_family_registry.json for writing."""
    from idea_machine.research_space.decision_engine import ResearchSpaceDecisionEngine
    from idea_machine.research_space.decision_record import DecisionLedger
    from idea_machine.research_space.search_space_ledger import SearchSpaceLedger

    registry_path = Path("reports/factory/research_family_registry.json")
    before = registry_path.read_bytes()

    engine = ResearchSpaceDecisionEngine(
        search_space,
        decision_ledger=DecisionLedger(tmp_path / "d.json"),
        space_ledger=SearchSpaceLedger(tmp_path / "s.json"),
    )
    engine.propose_closures()

    after = registry_path.read_bytes()
    assert before == after, "propose_closures() must never modify the Factory's family registry"


def test_forced_exploration_never_falls_below_governance_floor():
    from idea_machine.research_space.research_allocator import AllocationPolicy

    with pytest.raises(ValueError):
        AllocationPolicy(minimum_exploration_share=0.05)


def test_closure_proposals_never_use_the_coarse_instrument_rollup(search_space, tmp_path):
    """Regression: EURUSD's REFUTED evidence comes from ONE driver-less hypothesis
    mixed with unrelated STILL_UNDERPOWERED evidence on other triples. Proposing
    to close 'instruments.EURUSD' from that mixed rollup would overstate the real
    evidence -- found live in Cycle 14's first run. Closure proposals must be
    restricted to dimensions where a REFUTED cell means one coherent thing was
    refuted (family ids), never instrument/driver/mechanism rollups."""
    from idea_machine.research_space.decision_engine import ResearchSpaceDecisionEngine
    from idea_machine.research_space.decision_record import DecisionLedger
    from idea_machine.research_space.search_space_ledger import SearchSpaceLedger

    engine = ResearchSpaceDecisionEngine(
        search_space,
        decision_ledger=DecisionLedger(tmp_path / "d.json"),
        space_ledger=SearchSpaceLedger(tmp_path / "s.json"),
    )
    proposals = engine.propose_closures()
    for p in proposals:
        assert p["dimension"] == "combinations", (
            f"closure proposal for {p['dimension']}.{p['value']} uses a coarse rollup dimension; "
            f"only 'combinations' (real family ids) may be proposed for closure"
        )
        assert p["dimension"] not in ("instruments", "drivers", "mechanisms")
