"""Governance enforcement — the machine's ability to stop itself.

Phase 18 requires that the Idea Machine "self-crash if it tries to bypass
governance". :class:`~idea_machine.core.errors.GovernanceViolation` is that
crash: it is raised here, it is never caught anywhere inside ``idea_machine``,
and a test enforces that no ``except`` clause in the package could swallow it.

Three enforcement layers:

* **Runtime** — :func:`require`, :func:`forbid`, and the specific ``deny_*``
  helpers, called at every boundary where the machine could overstep.
* **Static** — :func:`audit_source_tree` reads the package's own source and
  fails if any module imports a holdout / GEN14 / EA-generation target, or
  writes a broad ``except`` that could swallow a violation.
* **Structural** — the forbidden capabilities simply have no implementation
  here. There is no ``read_holdout`` function to call.

Every violation is also appended to a durable audit ledger, so an attempted
overstep survives the crash and shows up on the dashboard.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from idea_machine.core.errors import GovernanceViolation
from idea_machine.core.ids import mint_id
from idea_machine.core.store import DEFAULT_ROOT, AppendOnlyStore
from idea_machine.governance.authority import (
    FORBIDDEN,
    FORBIDDEN_IMPORTS,
    HUMAN_AUTHORITY,
    PERMITTED,
)
from utils.helpers import isoformat

DEFAULT_AUDIT_PATH = DEFAULT_ROOT / "governance_audit.json"

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------- audit


class GovernanceAudit:
    """Append-only record of every governance decision, allow or deny."""

    def __init__(self, path: Path = DEFAULT_AUDIT_PATH) -> None:
        self.store = AppendOnlyStore(path, id_field="event_id", kind="governance_audit")

    def record(
        self,
        *,
        action: str,
        verdict: str,
        actor: str,
        detail: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = dict(context or {})
        ts = isoformat()
        event = {
            "event_id": mint_id("GOV", {"a": action, "v": verdict, "actor": actor, "t": ts, "c": context}),
            "action": action,
            "verdict": verdict,
            "actor": actor,
            "detail": detail,
            "context": context,
            "timestamp": ts,
        }
        self.store.append(event)
        return event

    def denials(self) -> List[Dict[str, Any]]:
        return self.store.where(lambda r: r.get("verdict") == "DENIED")

    def all_events(self) -> List[Dict[str, Any]]:
        return self.store.all()


_audit: Optional[GovernanceAudit] = None


def set_audit(audit: Optional[GovernanceAudit]) -> None:
    """Point the module-level audit at a specific ledger (used by tests)."""
    global _audit
    _audit = audit


def _get_audit() -> Optional[GovernanceAudit]:
    return _audit


def _merge(context: Dict[str, Any], **fixed: Any) -> Dict[str, Any]:
    """Governance's own fields win; caller context fills the rest.

    Caller context is arbitrary and may reuse a name the guard also reports
    (``action``, ``actor``). Merging explicitly keeps that from raising a
    TypeError out of the governance layer, which would obscure the actual
    violation being reported.
    """
    merged = dict(fixed)
    for key, value in context.items():
        merged.setdefault(f"ctx_{key}" if key in fixed else key, value)
    return merged


def _detail(context: Dict[str, Any], reason: str) -> str:
    """Merge the caller's own ``detail`` (if any) with the governance reason.

    Callers pass arbitrary context, and ``detail`` is a natural key for them to
    use; without this the two would collide in the audit record.
    """
    own = str(context.pop("detail", "")).strip()
    return f"{reason} [{own}]" if own else reason


def _log(action: str, verdict: str, actor: str, detail: str, context: Dict[str, Any]) -> None:
    """Append one audit row.

    Context is passed as an explicit dict rather than ``**kwargs``: callers
    supply arbitrary keys, and any of them colliding with a parameter name
    (``action``, ``verdict``, ``actor``, ``detail``) would raise a TypeError
    from inside the governance layer -- turning a governance check into a crash
    for the wrong reason.
    """
    audit = _get_audit()
    if audit is not None:
        audit.record(action=action, verdict=verdict, actor=actor, detail=detail, context=context)


# ------------------------------------------------------------------- runtime


def require(action: str, /, *, actor: str = "idea_machine", **context: Any) -> None:
    """Assert that ``action`` is within the Idea Machine's authority.

    Anything not on the permitted list is refused — an unknown action is
    treated as forbidden, so adding a new capability requires editing
    :mod:`idea_machine.governance.authority` deliberately.
    """
    if action in FORBIDDEN:
        forbid(action, actor=actor, **context)
    if action not in PERMITTED:
        _log(action, "DENIED", actor, _detail(context, "action is not on the permitted list"), context)
        raise GovernanceViolation(
            "action is not within the Idea Machine's declared authority",
            **_merge(context, action=action, actor=actor, permitted=list(PERMITTED)),
        )
    _log(action, "ALLOWED", actor, "", context)


def forbid(action: str, /, *, actor: str = "idea_machine", **context: Any) -> None:
    """Unconditionally refuse ``action`` and terminate the run."""
    reason = FORBIDDEN.get(action, "action is outside the Idea Machine's authority")
    # _detail pops the caller's own "detail" out of context and folds it into
    # the message, so the specific thing that was attempted appears in the
    # exception a human reads -- not only in the audit ledger.
    detail = _detail(context, reason)
    _log(action, "DENIED", actor, detail, context)
    raise GovernanceViolation(
        f"GOVERNANCE: {action} is forbidden to the Idea Machine. {detail}",
        **_merge(context, action=action, actor=actor, human_authority=list(HUMAN_AUTHORITY)),
    )


def deny_holdout_access(*, actor: str = "idea_machine", **context: Any) -> None:
    """Called wherever a code path could conceivably touch holdout data."""
    forbid("READ_HOLDOUT", actor=actor, **context)


def deny_gen14_authorization(*, actor: str = "idea_machine", **context: Any) -> None:
    forbid("AUTHORIZE_GEN14", actor=actor, **context)


def deny_edge_declaration(*, actor: str = "idea_machine", **context: Any) -> None:
    forbid("DECLARE_EDGE", actor=actor, **context)


def deny_ea_creation(*, actor: str = "idea_machine", **context: Any) -> None:
    forbid("CREATE_EA", actor=actor, **context)


def deny_ledger_reset(*, actor: str = "idea_machine", **context: Any) -> None:
    forbid("RESET_LEDGER", actor=actor, **context)


def deny_cost_model_mutation(*, actor: str = "idea_machine", **context: Any) -> None:
    forbid("MODIFY_COST_MODEL", actor=actor, **context)


def deny_failed_idea_retest(idea_id: str, *, actor: str = "idea_machine", **context: Any) -> None:
    forbid("RETEST_FAILED_BY_PARAMETER_TWEAK", actor=actor, idea_id=idea_id, **context)


def deny_preregistration_mutation(experiment_id: str, *, actor: str = "idea_machine", **context: Any) -> None:
    forbid("MUTATE_PREREGISTRATION", actor=actor, experiment_id=experiment_id, **context)


# -------------------------------------------------------------------- static


@dataclass(frozen=True)
class SourceFinding:
    file: str
    line: int
    kind: str
    detail: str


#: ``except`` forms that could swallow a GovernanceViolation.
_BROAD_HANDLERS = ("Exception", "BaseException", "EAFactoryError", "IdeaMachineError", "GovernanceViolation")

#: Modules allowed to name GovernanceViolation in an except clause: none.
_HANDLER_EXEMPT_FILES: Tuple[str, ...] = ()


def audit_source_tree(root: Optional[Path] = None) -> List[SourceFinding]:
    """Statically audit the package for governance-defeating code.

    Returns every finding rather than raising, so a test can print them all.
    Two classes of finding:

    * ``FORBIDDEN_IMPORT`` — the module reaches for holdout / GEN14 / EA code.
    * ``BROAD_EXCEPT`` — a handler wide enough to swallow a GovernanceViolation.
    """
    base = Path(root) if root else _PACKAGE_ROOT
    findings: List[SourceFinding] = []

    for py in sorted(base.rglob("*.py")):
        rel = py.relative_to(base.parent).as_posix()
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError as exc:  # a syntax error is itself a finding
            findings.append(SourceFinding(rel, exc.lineno or 0, "SYNTAX_ERROR", str(exc)))
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    _check_import(alias.name, rel, node.lineno, findings)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    _check_import(node.module, rel, node.lineno, findings)
            elif isinstance(node, ast.ExceptHandler):
                if rel in _HANDLER_EXEMPT_FILES or _always_reraises(node):
                    continue
                for name in _handler_names(node):
                    if name in _BROAD_HANDLERS:
                        findings.append(
                            SourceFinding(
                                rel,
                                node.lineno,
                                "BROAD_EXCEPT",
                                f"'except {name}' could swallow a GovernanceViolation",
                            )
                        )
                if node.type is None:
                    findings.append(
                        SourceFinding(rel, node.lineno, "BROAD_EXCEPT", "bare 'except:' swallows everything")
                    )
    return findings


def _check_import(module: str, rel: str, line: int, findings: List[SourceFinding]) -> None:
    for banned in FORBIDDEN_IMPORTS:
        if module == banned or module.startswith(banned + "."):
            findings.append(
                SourceFinding(rel, line, "FORBIDDEN_IMPORT", f"imports {module!r} (forbidden: {banned})")
            )


def _always_reraises(node: ast.ExceptHandler) -> bool:
    """True when the handler cannot swallow anything because it always re-raises.

    A cleanup-then-reraise block (``except BaseException: cleanup(); raise``) is
    the one broad handler that is safe: control never continues past it, so a
    GovernanceViolation still propagates.
    """
    if not node.body:
        return False
    tail = node.body[-1]
    return isinstance(tail, ast.Raise)


def _handler_names(node: ast.ExceptHandler) -> List[str]:
    if node.type is None:
        return []
    targets = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
    names: List[str] = []
    for t in targets:
        if isinstance(t, ast.Name):
            names.append(t.id)
        elif isinstance(t, ast.Attribute):
            names.append(t.attr)
    return names


def assert_source_tree_clean(root: Optional[Path] = None) -> None:
    """Raise :class:`GovernanceViolation` if the static audit finds anything."""
    findings = audit_source_tree(root)
    if findings:
        raise GovernanceViolation(
            "the Idea Machine source tree contains governance-defeating code",
            findings=[f"{f.file}:{f.line} {f.kind}: {f.detail}" for f in findings],
        )


def governance_report() -> Dict[str, Any]:
    """Human-readable statement of the boundary, for the dashboard."""
    return {
        "permitted_actions": list(PERMITTED),
        "forbidden_actions": {k: v for k, v in sorted(FORBIDDEN.items())},
        "human_authority": list(HUMAN_AUTHORITY),
        "forbidden_imports": list(FORBIDDEN_IMPORTS),
        "static_audit_findings": [
            {"file": f.file, "line": f.line, "kind": f.kind, "detail": f.detail}
            for f in audit_source_tree()
        ],
    }
