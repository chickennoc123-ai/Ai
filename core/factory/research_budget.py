"""Research budgets + kill switch — Generation 3, Phases 20-21.

A runaway generator must never accidentally create millions of
candidates. ``BudgetTracker.charge()`` raises the moment a declared limit
would be exceeded, and ``ResearchKillSwitch`` provides a persistent,
trip-once safety stop for systemic conditions (candidate/search-space/
duplicate explosion, ledger or provenance failure, accounting mismatch,
resource exhaustion).

**A safety stop preserves evidence**: neither class deletes, truncates,
or rolls back anything — they only refuse NEW generation. Everything
already recorded stays recorded.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

DEFAULT_KILL_SWITCH_PATH = Path("reports/factory/research_kill_switch.json")

#: The recognized systemic trip conditions.
KILL_SWITCH_CONDITIONS = frozenset(
    {
        "CANDIDATE_EXPLOSION",
        "SEARCH_SPACE_EXPLOSION",
        "DUPLICATE_EXPLOSION",
        "RESOURCE_EXHAUSTION",
        "LEDGER_FAILURE",
        "PROVENANCE_FAILURE",
        "ACCOUNTING_MISMATCH",
    }
)


class ResearchBudgetExceededError(EAFactoryError):
    """Raised when a charge would exceed a declared budget limit."""


class KillSwitchTrippedError(EAFactoryError):
    """Raised by assert_not_tripped() once the switch has been tripped."""


class ResearchBudgetError(EAFactoryError):
    pass


@dataclass(frozen=True)
class ResearchBudget:
    """Explicit per-run generation limits. -1 = unlimited is deliberately
    NOT representable: every limit is a required positive integer, so an
    unbounded run has to be an explicit, visible choice of a huge number,
    never a silent default."""

    max_sources: int
    max_hypotheses: int
    max_candidates: int
    max_search_space_size: int
    max_candidates_per_family: int

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, int) or value < 1:
                raise ResearchBudgetError("budget limits must be positive integers", limit=name, value=value)


class BudgetTracker:
    """In-memory usage counter against a fixed ResearchBudget. charge()
    is check-then-increment: the increment that WOULD exceed the limit
    raises and is not applied, so the recorded state never overshoots."""

    def __init__(self, budget: ResearchBudget) -> None:
        self.budget = budget
        self._usage: Dict[str, int] = {"sources": 0, "hypotheses": 0, "candidates": 0}
        self._family_candidates: Dict[str, int] = {}

    def charge(self, kind: str, *, family_id: Optional[str] = None) -> None:
        limits = {"sources": self.budget.max_sources, "hypotheses": self.budget.max_hypotheses,
                  "candidates": self.budget.max_candidates}
        if kind not in limits:
            raise ResearchBudgetError("unknown budget kind", kind=kind, allowed=sorted(limits))
        if self._usage[kind] + 1 > limits[kind]:
            raise ResearchBudgetExceededError(
                f"research budget exhausted for '{kind}' -- generation stopped safely; "
                "all already-recorded evidence is preserved",
                kind=kind, limit=limits[kind], used=self._usage[kind],
            )
        if kind == "candidates" and family_id is not None:
            used = self._family_candidates.get(family_id, 0)
            if used + 1 > self.budget.max_candidates_per_family:
                raise ResearchBudgetExceededError(
                    "per-family candidate budget exhausted -- parameter-variant explosion blocked",
                    family_id=family_id, limit=self.budget.max_candidates_per_family, used=used,
                )
            self._family_candidates[family_id] = used + 1
        self._usage[kind] += 1

    def check_search_space(self, combination_count: int) -> None:
        if combination_count > self.budget.max_search_space_size:
            raise ResearchBudgetExceededError(
                "search space exceeds the declared size budget",
                combination_count=combination_count, limit=self.budget.max_search_space_size,
            )

    def usage(self) -> Dict[str, Any]:
        return {**dict(self._usage), "per_family_candidates": dict(self._family_candidates)}


class ResearchKillSwitch:
    """Persistent trip-once safety stop. Once tripped, every subsequent
    assert_not_tripped() raises until a human explicitly resets by
    constructing a new state (there is deliberately no reset() method —
    clearing a safety stop is a manual, visible act on the state file,
    not an API call a runaway process could invoke on itself)."""

    def __init__(self, path: Path = DEFAULT_KILL_SWITCH_PATH) -> None:
        self.path = Path(path)
        self._state: Dict[str, Any] = {"tripped": False, "condition": None, "reason": None, "tripped_timestamp": None}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            self._state = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            # A corrupted safety-state file fails CLOSED: treat as tripped.
            self._state = {"tripped": True, "condition": "LEDGER_FAILURE",
                           "reason": f"kill-switch state file unreadable: {exc}", "tripped_timestamp": utcnow().isoformat()}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._state, f, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    @property
    def tripped(self) -> bool:
        return bool(self._state.get("tripped"))

    def trip(self, condition: str, *, reason: str) -> None:
        if condition not in KILL_SWITCH_CONDITIONS:
            raise ResearchBudgetError("unknown kill-switch condition", condition=condition,
                                       allowed=sorted(KILL_SWITCH_CONDITIONS))
        self._state = {"tripped": True, "condition": condition, "reason": reason,
                        "tripped_timestamp": utcnow().isoformat()}
        self._save()

    def assert_not_tripped(self) -> None:
        if self.tripped:
            raise KillSwitchTrippedError(
                "research kill switch is tripped -- new generation is blocked; all recorded "
                "evidence is preserved",
                condition=self._state.get("condition"), reason=self._state.get("reason"),
            )

    def check_metric(self, condition: str, *, metric: float, threshold: float, reason: str) -> None:
        """Trip if ``metric`` exceeds ``threshold`` for ``condition`` —
        the guard a generation loop calls each iteration."""
        if metric > threshold:
            self.trip(condition, reason=f"{reason} (metric={metric} > threshold={threshold})")
            self.assert_not_tripped()
