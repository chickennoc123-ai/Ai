"""Governance boundary tests for the production/ package (spec Section 15).

Production mode must not weaken governance. These tests check the specific,
concrete ways it could:

  * idea_machine/ importing production/ (which would let the research layer
    reach ea_generator / holdout / qualification transitively, defeating the
    entire FORBIDDEN_IMPORTS boundary the audit already relies on).
  * production/ swallowing a GovernanceViolation instead of letting it
    propagate and stop the loop.
  * production/ importing ea_generator / discovery.holdout_authorization
    anywhere OTHER than the one deliberate, documented place
    (production/productization.py) that exists precisely to defer to their
    real gates.
  * agle.py or any production/ module carrying a god-mode flag
    (--force / --skip-gates / --ignore-governance) that could bypass a gate.
  * MasterSwitch controlling only whether NEW work starts, never governance
    itself -- turning the switch OFF must not touch any other ledger.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from idea_machine.core.errors import GovernanceViolation
from idea_machine.governance import guard
from idea_machine.governance.authority import FORBIDDEN_IMPORTS

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
IDEA_MACHINE_ROOT = REPO_ROOT / "idea_machine"
PRODUCTION_ROOT = REPO_ROOT / "production"

# production/productization.py is the ONE deliberate place allowed to import
# the modules idea_machine itself is forbidden from touching -- see its
# module docstring. Any other production/ file importing them would be an
# undocumented, unreviewed widening of the boundary.
_PRODUCTIZATION_ALLOWED_FORBIDDEN_IMPORTS = {"discovery.holdout_authorization", "ea_generator"}


def test_idea_machine_never_imports_production():
    """The research layer must never reach production/ -- that would let it
    reach ea_generator/holdout/qualification transitively through
    production.productization, silently defeating FORBIDDEN_IMPORTS."""
    offenders = []
    for py in sorted(IDEA_MACHINE_ROOT.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for mod in modules:
                if mod == "production" or mod.startswith("production."):
                    offenders.append(f"{py.relative_to(REPO_ROOT)}:{node.lineno} imports {mod!r}")
    assert offenders == [], f"idea_machine/ must never import production/: {offenders}"


def test_idea_machine_static_audit_still_clean():
    """The existing static audit (FORBIDDEN_IMPORT / BROAD_EXCEPT) must stay
    clean for idea_machine/ itself -- production mode changes must not have
    reopened anything the audit was already protecting."""
    findings = guard.audit_source_tree()
    assert findings == [], f"idea_machine/ governance audit findings: {findings}"


def test_production_package_has_no_broad_except():
    """production/ must never contain a handler wide enough to swallow a
    GovernanceViolation raised out of check_governance() or maybe_productize()
    -- the same BROAD_EXCEPT check the audit already runs on idea_machine/,
    run here against production/ instead."""
    findings = guard.audit_source_tree(root=PRODUCTION_ROOT)
    broad_except = [f for f in findings if f.kind == "BROAD_EXCEPT"]
    assert broad_except == [], f"production/ has a handler that could swallow governance: {broad_except}"


def test_production_forbidden_imports_are_only_the_documented_ones():
    """production/ is allowed to import ea_generator / discovery.holdout_
    authorization -- that is its entire purpose -- but ONLY from
    production/productization.py, and that must stay the sole, documented,
    reviewed exception, not something that quietly spreads to other files."""
    findings = guard.audit_source_tree(root=PRODUCTION_ROOT)
    forbidden = [f for f in findings if f.kind == "FORBIDDEN_IMPORT"]
    unexpected = [f for f in forbidden if f.file != "production/productization.py"]
    assert unexpected == [], f"unexpected forbidden import outside productization.py: {unexpected}"
    for f in forbidden:
        assert any(f.detail.count(mod) for mod in _PRODUCTIZATION_ALLOWED_FORBIDDEN_IMPORTS), (
            f"productization.py imports an undocumented forbidden module: {f}"
        )


def test_governance_violation_is_not_a_stdlib_exception_subclass():
    """Structural guarantee behind ProductionSupervisor.run_forever(): its
    bounded-retry except tuple (ValueError, KeyError, TypeError,
    AttributeError, OSError, RuntimeError) must be structurally INCAPABLE of
    catching a GovernanceViolation, not just accidentally miss it today."""
    stdlib_types = (ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError)
    assert not issubclass(GovernanceViolation, stdlib_types)


def test_supervisor_run_forever_never_catches_governance_violation(tmp_path):
    """Behavioral proof, not just structural: a GovernanceViolation raised
    from run_one_cycle() propagates all the way out of run_forever(),
    unconditionally, regardless of consecutive_failures budget."""
    from production.ea_registry import EAProductRegistry
    from production.evaluation_ledger import EvaluationLedger
    from production.master_switch import MasterSwitch
    from production.supervisor import ProductionSupervisor

    switch = MasterSwitch(state_path=tmp_path / "switch.json", audit_path=tmp_path / "switch_audit.json")
    switch.turn_on(reason="test", source="test")

    class ExplodingSupervisor(ProductionSupervisor):
        def run_one_cycle(self, *, total_slots: int = 10):
            raise GovernanceViolation("simulated governance failure", findings=["fake"])

    sup = ExplodingSupervisor(
        switch=switch,
        evaluation_ledger=EvaluationLedger(path=tmp_path / "ledger.json"),
        ea_registry=EAProductRegistry(path=tmp_path / "registry.json"),
        heartbeat_path=tmp_path / "heartbeat.json",
        operation_log_path=tmp_path / "operation_log.json",
    )
    with pytest.raises(GovernanceViolation):
        sup.run_forever(max_cycles=5, sleep_seconds=0)
    assert sup.state == "STOPPED"
    # It must not have been reclassified as an ordinary DEGRADED failure.
    assert sup.consecutive_failures == 0


def test_supervisor_bounded_retry_never_infinite(tmp_path):
    """An ordinary (non-governance) exception must stop the loop after
    max_consecutive_failures, never retry forever."""
    from production.ea_registry import EAProductRegistry
    from production.evaluation_ledger import EvaluationLedger
    from production.master_switch import MasterSwitch
    from production.supervisor import ProductionSupervisor

    switch = MasterSwitch(state_path=tmp_path / "switch.json", audit_path=tmp_path / "switch_audit.json")
    switch.turn_on(reason="test", source="test")

    call_count = {"n": 0}

    class FlakySupervisor(ProductionSupervisor):
        def run_one_cycle(self, *, total_slots: int = 10):
            call_count["n"] += 1
            raise RuntimeError("simulated ordinary failure")

    sup = FlakySupervisor(
        switch=switch,
        evaluation_ledger=EvaluationLedger(path=tmp_path / "ledger.json"),
        ea_registry=EAProductRegistry(path=tmp_path / "registry.json"),
        heartbeat_path=tmp_path / "heartbeat.json",
        operation_log_path=tmp_path / "operation_log.json",
        max_consecutive_failures=3,
    )
    summary = sup.run_forever(sleep_seconds=0)
    assert call_count["n"] == 3
    assert sup.state == "STOPPED"
    assert sup.consecutive_failures == 3


def test_master_switch_off_never_touches_other_ledgers(tmp_path):
    """Turning OFF must append exactly one switch record and touch nothing
    else -- no research memory, opportunity queue, ledger, or registry file
    may be created, deleted, or modified by a switch transition."""
    from production.master_switch import MasterSwitch

    other_dir = tmp_path / "reports"
    other_dir.mkdir()
    sentinel = other_dir / "untouched.json"
    sentinel.write_text('{"marker": true}', encoding="utf-8")
    before_mtime = sentinel.stat().st_mtime_ns

    switch = MasterSwitch(state_path=tmp_path / "switch.json", audit_path=tmp_path / "switch_audit.json")
    switch.turn_on(reason="test", source="test")
    switch.turn_off(reason="test", source="test")

    assert sentinel.stat().st_mtime_ns == before_mtime
    assert json_marker_untouched(sentinel)


def json_marker_untouched(path: Path) -> bool:
    import json

    return json.loads(path.read_text())["marker"] is True


def test_no_god_mode_flags_anywhere_in_production_path():
    """No --force / --skip-gates / --ignore-governance (or similarly named)
    flag may exist in agle.py or production/ -- the master switch controls
    only whether NEW work may start, never whether governance applies."""
    forbidden_patterns = [
        r"add_argument\(\s*[\"']--force", r"add_argument\(\s*[\"']--skip[-_]gates?",
        r"add_argument\(\s*[\"']--ignore[-_]governance",
        r"^\s*skip_governance\s*=", r"^\s*ignore_governance\s*=",
        r"^\s*def\s+bypass_gate", r"^\s*def\s+force_productize",
    ]
    combined = re.compile("|".join(forbidden_patterns), re.IGNORECASE)

    files_to_check = list(PRODUCTION_ROOT.rglob("*.py")) + [REPO_ROOT / "agle.py"]
    offenders = []
    for f in files_to_check:
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if combined.search(line):
                offenders.append(f"{f.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert offenders == [], f"god-mode flag found in production path: {offenders}"


def test_maybe_productize_never_authorizes_without_real_gen14_pass():
    """A candidate that was never registered anywhere must always be refused
    -- productization defers entirely to ea_generator's real gate, never
    fabricates authorization for an unknown/unqualified candidate."""
    from production.ea_registry import EAProductRegistry
    from production.productization import maybe_productize

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        registry = EAProductRegistry(path=Path(td) / "registry.json")
        result = maybe_productize(
            candidate_id="NONEXISTENT-CANDIDATE-GOVERNANCE-TEST", symbol="EURUSD",
            registry=registry, artifact_dir=Path(td) / "ea_products",
        )
        assert result.status == "NOT_AUTHORIZED"
        assert registry.count() == 0
