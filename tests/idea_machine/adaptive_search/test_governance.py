"""Governance tests (spec item 17 "Governance")."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from idea_machine.adaptive_search import AdaptiveSearchController, GOVERNANCE_MIN_EXPLORATION_FRACTION
from idea_machine.core.errors import GovernanceViolation
from idea_machine.governance import guard
from idea_machine.governance.authority import FORBIDDEN_IMPORTS, PERMITTED

PACKAGE_ROOT = Path(guard.__file__).resolve().parent.parent
NEW_MODULES = [
    PACKAGE_ROOT / "adaptive_search.py", PACKAGE_ROOT / "exploration_engine.py",
    PACKAGE_ROOT / "exploitation_engine.py", PACKAGE_ROOT / "search_space_registry.py",
    PACKAGE_ROOT / "search_decision_ledger.py", PACKAGE_ROOT / "search_economic_rationale.py",
]


def test_minimum_exploration_cannot_be_bypassed():
    with pytest.raises(GovernanceViolation):
        AdaptiveSearchController(min_exploration_fraction=0.19)
    with pytest.raises(GovernanceViolation):
        AdaptiveSearchController(min_exploration_fraction=0.0)
    with pytest.raises(GovernanceViolation):
        AdaptiveSearchController(min_exploration_fraction=-0.5)


def test_exact_floor_is_allowed():
    AdaptiveSearchController(min_exploration_fraction=GOVERNANCE_MIN_EXPLORATION_FRACTION)  # must not raise


def test_new_phase9_actions_declared_permitted():
    for action in ("REQUEST_SEARCH_SPACE_EXPANSION", "CHECK_IDEA_EXPLAINABILITY", "REGISTER_SEARCH_REGION"):
        assert action in PERMITTED


def test_holdout_never_read_in_new_modules():
    """No CODE path in these modules reads or opens anything holdout-related.
    Module docstrings legitimately explain what the code does NOT do (e.g.
    "never reads the holdout"), which is prose, not a code path -- so this
    checks actual function calls / attribute access patterns, not the raw
    text of every comment and docstring."""
    for py in NEW_MODULES:
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                name = node.func.id
            if name and "holdout" in name.lower():
                pytest.fail(f"{py.name} has code (not prose) referencing holdout: {name!r}")


def test_no_forbidden_imports_in_new_modules():
    for py in NEW_MODULES:
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for banned in FORBIDDEN_IMPORTS:
                    assert not (node.module == banned or node.module.startswith(banned + ".")), (
                        f"{py.name} imports forbidden target {node.module!r}"
                    )


def test_no_swallowed_governance_violation_in_new_modules():
    offenders = []
    for py in NEW_MODULES:
        tree = ast.parse(py.read_text(), filename=str(py))
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


def test_static_source_audit_still_clean_with_new_modules():
    findings = guard.audit_source_tree()
    assert findings == [], "\n".join(f"{f.file}:{f.line} {f.kind}: {f.detail}" for f in findings)


def test_search_decision_ledger_is_append_only(decision_ledger):
    from idea_machine.search_decision_ledger import SearchDecisionScore

    score = SearchDecisionScore(0.5, 0.5, 1.0, 0.5, 0.5, 0.0, 0.0, 0.0)
    row1 = decision_ledger.record(
        cycle_id="C1", region_id="REGION-TEST", mode="EXPLORE", selected=True, score=score,
        reason_codes=["TEST"], source_evidence=["e1"], timestamp="2026-01-01T00:00:00Z",
    )
    before_count = decision_ledger.store.count()
    # Re-recording identical content is idempotent (no growth), never a rewrite.
    row2 = decision_ledger.record(
        cycle_id="C1", region_id="REGION-TEST", mode="EXPLORE", selected=True, score=score,
        reason_codes=["TEST"], source_evidence=["e1"], timestamp="2026-01-01T00:00:00Z",
    )
    assert row1["decision_id"] == row2["decision_id"]
    assert decision_ledger.store.count() == before_count


def test_cost_model_never_written_by_new_modules():
    for py in NEW_MODULES:
        src = py.read_text()
        assert ".update(" not in src
        assert ".relax(" not in src
        assert "FROZEN_COSTS[" not in src


def test_search_space_registry_never_writes_factory_files(registry, tmp_path):
    registry_path = Path("reports/factory/research_family_registry.json")
    before = registry_path.read_bytes()
    registry.register_region({"instrument": "TESTFX", "macro_driver": "TESTDRV"}, tag="TEST")
    after = registry_path.read_bytes()
    assert before == after
