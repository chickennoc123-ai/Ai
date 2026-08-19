"""Generation 5 hypothesis/candidate budget — Phase 2.

A **governance contract**, not a compute limit (module docstring of the
execution contract, verbatim). This is deliberately a new, Generation-5-
specific dataclass rather than an extension of ``core.factory.
research_budget.ResearchBudget`` (Generation 3): that class's fields are
all required positive integers with no defaults, consumed by existing
Generation 3 tests -- adding fields to it would either break every
existing caller or require a default, and a defaulted budget limit is
exactly the "silent generous default" this project's budget philosophy
(-1-is-not-representable) forbids. A new contract gets a new, explicit
dataclass instead.

Declared once, persisted, and immutable for the remainder of the
generation: :meth:`GenerationFiveBudgetStore.declare` refuses a second
declaration unless ``allow_redeclare=True`` is passed explicitly, which
itself must be justified by a recorded governance decision (a redeclare
without one is exactly the "silently increase the research budget"
outcome the execution contract's stop conditions forbid).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Dict, Optional

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

DEFAULT_BUDGET_PATH = Path("reports/factory/generation5_budget.json")


class GenerationFiveBudgetError(EAFactoryError):
    pass


class GenerationFiveBudgetExceededError(EAFactoryError):
    pass


@dataclass(frozen=True)
class GenerationFiveBudget:
    """Every field is a required positive integer -- an unbounded run
    must be an explicit, visible, enormous number, never a silent
    default or a -1 sentinel."""

    max_new_hypotheses: int
    max_new_candidates: int
    max_candidates_per_family: int
    max_search_space_size_per_hypothesis: int
    max_research_retries: int
    max_research_branches: int

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise GenerationFiveBudgetError(
                    "Generation 5 budget limits must be positive integers", limit=f.name, value=value,
                )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GenerationFiveBudgetStore:
    """Persistent, declare-once budget + usage tracker."""

    def __init__(self, path: Path = DEFAULT_BUDGET_PATH) -> None:
        self.path = Path(path)
        self._state: Optional[Dict[str, Any]] = None
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        self._state = json.loads(self.path.read_text())

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
    def declared(self) -> bool:
        return self._state is not None

    def declare(
        self, budget: GenerationFiveBudget, *, justification: str, allow_redeclare: bool = False,
    ) -> None:
        if self.declared and not allow_redeclare:
            raise GenerationFiveBudgetError(
                "Generation 5 budget is already declared and is immutable for the remainder of the "
                "generation; a change requires an explicit governance decision (allow_redeclare=True "
                "with its own recorded justification), not a silent increase",
                current=self._state["budget"] if self._state else None,
            )
        if not justification.strip():
            raise GenerationFiveBudgetError("a budget declaration requires a non-empty justification")
        self._state = {
            "budget": budget.to_dict(),
            "justification": justification,
            "declared_at": utcnow().isoformat(),
            "usage": {"new_hypotheses": 0, "new_candidates": 0},
            "family_candidate_usage": {},
            "exhausted": {},
        }
        self._save()

    def _budget(self) -> GenerationFiveBudget:
        if not self.declared:
            raise GenerationFiveBudgetError("no Generation 5 budget has been declared yet")
        return GenerationFiveBudget(**self._state["budget"])

    def charge_hypothesis(self) -> None:
        b = self._budget()
        used = self._state["usage"]["new_hypotheses"]
        if used + 1 > b.max_new_hypotheses:
            self._state["exhausted"]["new_hypotheses"] = True
            self._save()
            raise GenerationFiveBudgetExceededError(
                "BUDGET_EXHAUSTED: max_new_hypotheses reached -- generation stopped safely, all "
                "already-recorded evidence is preserved",
                limit=b.max_new_hypotheses, used=used,
            )
        self._state["usage"]["new_hypotheses"] += 1
        self._save()

    def charge_candidate(self, *, family_id: str) -> None:
        b = self._budget()
        used = self._state["usage"]["new_candidates"]
        if used + 1 > b.max_new_candidates:
            self._state["exhausted"]["new_candidates"] = True
            self._save()
            raise GenerationFiveBudgetExceededError(
                "BUDGET_EXHAUSTED: max_new_candidates reached", limit=b.max_new_candidates, used=used,
            )
        fam_used = self._state["family_candidate_usage"].get(family_id, 0)
        if fam_used + 1 > b.max_candidates_per_family:
            self._state["exhausted"][f"family:{family_id}"] = True
            self._save()
            raise GenerationFiveBudgetExceededError(
                "BUDGET_EXHAUSTED: max_candidates_per_family reached -- parameter-variant explosion "
                "blocked", family_id=family_id, limit=b.max_candidates_per_family, used=fam_used,
            )
        self._state["usage"]["new_candidates"] += 1
        self._state["family_candidate_usage"][family_id] = fam_used + 1
        self._save()

    def usage_summary(self) -> Dict[str, Any]:
        if not self.declared:
            return {"declared": False}
        return {
            "declared": True,
            "budget": self._state["budget"],
            "usage": dict(self._state["usage"]),
            "family_candidate_usage": dict(self._state["family_candidate_usage"]),
            "exhausted": dict(self._state["exhausted"]),
        }
