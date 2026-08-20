"""Governance tests (Phase 16 + Phase 18).

The most important test in the package is
:func:`test_no_module_can_swallow_a_governance_violation`: it is what makes the
"self-crash on governance bypass" requirement real rather than aspirational.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from idea_machine.core.errors import GovernanceViolation
from idea_machine.economics.cost_model import DEFAULT_COST_MODEL, verify_frozen_costs
from idea_machine.governance import guard
from idea_machine.governance.authority import FORBIDDEN, HUMAN_AUTHORITY, PERMITTED
from idea_machine.integration.factory_bridge import FactoryBridge, InMemorySubmitter
from idea_machine.experiment.prereg import PreregistrationLedger
from idea_machine.novelty.memory import FailureMemory

PACKAGE_ROOT = Path(guard.__file__).resolve().parent.parent


# ------------------------------------------------------- static source audit


def test_source_tree_has_no_forbidden_imports_or_broad_handlers():
    findings = guard.audit_source_tree()
    assert findings == [], "\n".join(f"{f.file}:{f.line} {f.kind}: {f.detail}" for f in findings)


def test_no_module_can_swallow_a_governance_violation():
    """No except clause anywhere in the package may catch a GovernanceViolation.

    This is the structural guarantee behind "the machine crashes rather than
    bypassing governance". A handler is acceptable only if it always re-raises.
    """
    offenders = []
    for py in sorted(PACKAGE_ROOT.rglob("*.py")):
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
                offenders.append(f"{py.relative_to(PACKAGE_ROOT)}:{node.lineno} except {names or 'BARE'}")
    assert offenders == [], "handlers that could swallow a GovernanceViolation:\n" + "\n".join(offenders)


def test_governance_violation_is_not_a_control_flow_signal():
    """It derives from the repo's base error but is documented as uncaught."""
    from utils.exceptions import EAFactoryError

    assert issubclass(GovernanceViolation, EAFactoryError)


# ------------------------------------------------------------ runtime denials


@pytest.mark.parametrize("action", sorted(FORBIDDEN))
def test_every_forbidden_action_raises(action, audit):
    with pytest.raises(GovernanceViolation) as exc:
        guard.forbid(action)
    assert action in str(exc.value)
    assert FORBIDDEN[action][:30] in str(exc.value)
    assert any(e["action"] == action and e["verdict"] == "DENIED" for e in audit.all_events())


@pytest.mark.parametrize("action", sorted(PERMITTED))
def test_every_permitted_action_is_allowed(action, audit):
    guard.require(action)
    assert any(e["action"] == action and e["verdict"] == "ALLOWED" for e in audit.all_events())


def test_unknown_action_is_denied_by_default():
    """An action nobody declared is forbidden, not silently permitted."""
    with pytest.raises(GovernanceViolation):
        guard.require("EXFILTRATE_EVERYTHING")


def test_guard_survives_adversarial_context_keys():
    """Context keys that collide with the guard's own fields must not break it.

    A TypeError from inside the governance layer would obscure the violation
    being reported, which is the one moment the layer has to work.
    """
    with pytest.raises(GovernanceViolation) as exc:
        guard.forbid("READ_HOLDOUT", action="x", actor="y", detail="z", verdict="w")
    assert exc.value.context["action"] == "READ_HOLDOUT"


# ------------------------------------------------ specific forbidden capabilities


def test_holdout_cannot_be_read(tmp_path):
    bridge = FactoryBridge(
        PreregistrationLedger(tmp_path / "p.json"),
        submitter=InMemorySubmitter(),
        ledger_path=tmp_path / "s.json",
    )
    with pytest.raises(GovernanceViolation):
        bridge.request_holdout()


def test_gen14_cannot_be_authorized(tmp_path):
    bridge = FactoryBridge(
        PreregistrationLedger(tmp_path / "p.json"),
        submitter=InMemorySubmitter(),
        ledger_path=tmp_path / "s.json",
    )
    with pytest.raises(GovernanceViolation):
        bridge.authorize_gen14()


def test_ea_cannot_be_created(tmp_path):
    bridge = FactoryBridge(
        PreregistrationLedger(tmp_path / "p.json"),
        submitter=InMemorySubmitter(),
        ledger_path=tmp_path / "s.json",
    )
    with pytest.raises(GovernanceViolation):
        bridge.generate_ea()


def test_factory_gate_cannot_be_bypassed(tmp_path):
    bridge = FactoryBridge(
        PreregistrationLedger(tmp_path / "p.json"),
        submitter=InMemorySubmitter(),
        ledger_path=tmp_path / "s.json",
    )
    with pytest.raises(GovernanceViolation):
        bridge.skip_gate("PURE_HOLDOUT")


def test_cost_model_cannot_be_modified():
    with pytest.raises(GovernanceViolation):
        DEFAULT_COST_MODEL.update(minimum_edge_multiple=0.01)
    with pytest.raises(GovernanceViolation):
        DEFAULT_COST_MODEL.relax()


def test_frozen_costs_match_their_checksum():
    verify_frozen_costs()


def test_failure_history_cannot_be_edited(tmp_path):
    memory = FailureMemory(tmp_path / "fm.json")
    with pytest.raises(GovernanceViolation):
        memory.forget("FAILMEM-anything")


def test_research_budget_cannot_be_reset(tmp_path):
    from idea_machine.budget.manager import ResearchBudget

    budget = ResearchBudget(path=tmp_path / "b.json")
    with pytest.raises(GovernanceViolation):
        budget.reset()


def test_adaptive_search_cannot_touch_a_completed_experiment(tmp_path, machine):
    with pytest.raises(GovernanceViolation):
        machine.adaptive.apply_to_experiment("EXP-anything")


def test_human_authority_is_declared_and_non_empty():
    assert "GEN14 authorization" in HUMAN_AUTHORITY
    assert "Live deployment" in HUMAN_AUTHORITY
    assert "Capital allocation" in HUMAN_AUTHORITY


def test_governance_report_is_serialisable():
    import json

    report = guard.governance_report()
    json.dumps(report)
    assert report["static_audit_findings"] == []
