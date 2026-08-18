"""Strategy Factory candidate registry + search-history accounting.

Per roadmap Sections 6, 16, 19, 20: a durable, file-backed registry that
(a) hands out immutable, monotonically increasing candidate IDs
(``STRAT-000001``, ...), (b) enforces the state-machine transition rules
from ``core.factory.state_machine``, (c) refuses to let a FROZEN-or-later
candidate's specification change in place, (d) preserves rejected
candidates with their rejection reason rather than deleting them, and
(e) maintains the mandatory multiple-testing/search-bias counters so the
Factory can always answer "how many alternatives were tested before this
one passed."

Persistence is a single JSON file, written atomically (write to a temp
file, then rename) so a crash mid-write cannot corrupt the registry. This
is intentionally NOT a database — the roadmap's evidence-preservation
requirement is about durability and auditability, not query performance,
and a single flat file is trivially diffable/reviewable in git.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.factory.candidate import (
    FrozenCandidateMutationError,
    StrategyCandidate,
    StrategyCandidateSpec,
)
from core.factory.state_machine import (
    CandidateState,
    assert_legal_transition,
    is_terminal,
)
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

DEFAULT_REGISTRY_PATH = Path("reports/factory/strategy_registry.json")

#: States at or beyond which a candidate's spec is immutable (roadmap
#: Section 10/20: "once a candidate enters a frozen validation stage").
_FROZEN_OR_LATER = {
    CandidateState.FROZEN,
    CandidateState.HOLDOUT_TESTED,
    CandidateState.OOS_TESTED,
    CandidateState.WFA_TESTED,
    CandidateState.ROBUSTNESS_TESTED,
    CandidateState.COST_TESTED,
    CandidateState.STATISTICALLY_VALIDATED,
    CandidateState.EVG_REVIEW,
    CandidateState.RESEARCH_CANDIDATE,
    CandidateState.PAPER_VALIDATION,
    CandidateState.LIVE_CANDIDATE,
}


class CandidateNotFoundError(EAFactoryError):
    pass


class DuplicateCandidateError(EAFactoryError):
    pass


class RegistryCorruptionError(EAFactoryError):
    """Raised when the on-disk registry file cannot be parsed as valid JSON."""


def _empty_search_history() -> Dict[str, Any]:
    return {
        "total_strategies_generated": 0,
        "total_strategies_tested": 0,
        "total_strategies_rejected": 0,
        "total_strategies_failed": 0,
        "total_strategies_surviving": 0,
        "total_strategies_passed": 0,
        "search_space": {},
        "search_method": None,
        "parameter_search_count": 0,
        "model_search_count": 0,
        "selection_criteria": None,
        "selection_bias_status": "UNACCOUNTED",
        "events": [],
    }


class StrategyRegistry:
    def __init__(self, path: Path = DEFAULT_REGISTRY_PATH) -> None:
        self.path = Path(path)
        self._next_id = 1
        self._candidates: Dict[str, StrategyCandidate] = {}
        self._search_history: Dict[str, Any] = _empty_search_history()
        self._load()

    # ---- persistence -----------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise RegistryCorruptionError(
                "strategy registry file is not valid JSON; refusing to load",
                path=str(self.path),
            ) from exc
        self._next_id = raw.get("next_id", 1)
        self._search_history = raw.get("search_history", _empty_search_history())
        self._candidates = {
            cid: StrategyCandidate.from_dict(cdata)
            for cid, cdata in raw.get("candidates", {}).items()
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "next_id": self._next_id,
            "search_history": self._search_history,
            "candidates": {cid: c.to_dict() for cid, c in self._candidates.items()},
        }
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2, sort_keys=True, default=str)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    # ---- identity ----------------------------------------------------------

    def allocate_candidate_id(self) -> str:
        """Return the next immutable, monotonically increasing candidate ID.

        This mutates and persists the counter immediately (not just on
        register), so two allocations never collide even if the first
        candidate is never actually registered.
        """
        cid = f"STRAT-{self._next_id:06d}"
        self._next_id += 1
        self._save()
        return cid

    # ---- registration / lifecycle ------------------------------------------

    def register(
        self,
        spec: StrategyCandidateSpec,
        *,
        generator_id: str,
        generator_parameters: Dict[str, Any],
        code_version: str,
        dataset_id: str,
        parent_candidate_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
    ) -> StrategyCandidate:
        """Register a new candidate in state GENERATED. Updates search-history counters."""
        cid = candidate_id or self.allocate_candidate_id()
        if cid in self._candidates:
            raise DuplicateCandidateError("candidate_id already registered", candidate_id=cid)

        candidate = StrategyCandidate(
            candidate_id=cid,
            version=1,
            spec=spec,
            state=CandidateState.GENERATED,
            creation_timestamp=utcnow().isoformat(),
            generator_id=generator_id,
            generator_parameters=dict(generator_parameters),
            code_version=code_version,
            dataset_id=dataset_id,
            parent_candidate_id=parent_candidate_id,
            history=[{"state": CandidateState.GENERATED.value, "timestamp": utcnow().isoformat(), "reason": "registered"}],
        )
        self._candidates[cid] = candidate
        self._search_history["total_strategies_generated"] += 1
        self._search_history["events"].append(
            {"event": "generated", "candidate_id": cid, "timestamp": utcnow().isoformat()}
        )
        self._save()
        return candidate

    def get(self, candidate_id: str) -> StrategyCandidate:
        try:
            return self._candidates[candidate_id]
        except KeyError as exc:
            raise CandidateNotFoundError("no such candidate", candidate_id=candidate_id) from exc

    def transition(
        self,
        candidate_id: str,
        new_state: CandidateState,
        *,
        reason: str,
        evidence_reference: Optional[str] = None,
    ) -> StrategyCandidate:
        """Move ``candidate_id`` to ``new_state``, enforcing the state machine.

        Raises ``IllegalStateTransitionError`` (from
        ``core.factory.state_machine``) for any structurally-disallowed
        move. Every transition is appended to the candidate's ``history``,
        never overwritten, and the search-history counters are updated for
        the terminal outcomes (REJECTED/FAILED) and for first-time entry
        into an active testing state (TESTED).
        """
        candidate = self.get(candidate_id)
        assert_legal_transition(candidate.state, new_state)

        candidate.state = new_state
        candidate.history.append(
            {
                "state": new_state.value,
                "timestamp": utcnow().isoformat(),
                "reason": reason,
                "evidence_reference": evidence_reference,
            }
        )

        if new_state is CandidateState.DATA_VALIDATED:
            self._search_history["total_strategies_tested"] += 1
        elif new_state is CandidateState.REJECTED:
            self._search_history["total_strategies_rejected"] += 1
        elif new_state is CandidateState.FAILED:
            self._search_history["total_strategies_failed"] += 1
        elif new_state is CandidateState.STATISTICALLY_VALIDATED:
            self._search_history["total_strategies_surviving"] += 1
        elif new_state is CandidateState.EVG_REVIEW:
            pass  # EVG outcome (PASS/FAIL/INSUFFICIENT) is recorded by the caller separately
        elif new_state is CandidateState.RESEARCH_CANDIDATE:
            self._search_history["total_strategies_passed"] += 1

        self._search_history["events"].append(
            {
                "event": "transition",
                "candidate_id": candidate_id,
                "to_state": new_state.value,
                "reason": reason,
                "timestamp": utcnow().isoformat(),
            }
        )
        self._save()
        return candidate

    def reject(
        self,
        candidate_id: str,
        *,
        reason: str,
        failed_phase: str,
        evidence_reference: Optional[str] = None,
    ) -> StrategyCandidate:
        """Convenience wrapper: transition to REJECTED with structured rejection metadata."""
        candidate = self.transition(
            candidate_id,
            CandidateState.REJECTED,
            reason=f"[{failed_phase}] {reason}",
            evidence_reference=evidence_reference,
        )
        return candidate

    def derive_new_version(
        self,
        parent_candidate_id: str,
        new_spec: StrategyCandidateSpec,
        *,
        generator_id: str,
        generator_parameters: Dict[str, Any],
        code_version: str,
        dataset_id: str,
    ) -> StrategyCandidate:
        """Register a brand-new candidate derived from ``parent_candidate_id``.

        This is the ONLY sanctioned way to change a candidate's spec after
        the parent has been generated: a new ``candidate_id`` is minted, the
        parent is linked via ``parent_candidate_id``, and the parent's own
        record is left completely untouched (roadmap Section 20: "Never
        mutate v1 into v2").
        """
        parent = self.get(parent_candidate_id)  # raises if parent doesn't exist
        del parent
        return self.register(
            new_spec,
            generator_id=generator_id,
            generator_parameters=generator_parameters,
            code_version=code_version,
            dataset_id=dataset_id,
            parent_candidate_id=parent_candidate_id,
        )

    def assert_mutation_allowed(self, candidate_id: str) -> None:
        """Raise ``FrozenCandidateMutationError`` if ``candidate_id`` is FROZEN or later.

        Call this before applying ANY change to a candidate's spec/params/
        features/model/timeframe/cost assumptions. There is deliberately no
        code path in this module that mutates ``StrategyCandidate.spec`` in
        place at all — this guard exists for callers (e.g. a training
        script) that might otherwise be tempted to patch a spec dict
        directly instead of going through ``derive_new_version``.
        """
        candidate = self.get(candidate_id)
        if candidate.state in _FROZEN_OR_LATER or is_terminal(candidate.state):
            raise FrozenCandidateMutationError(
                "candidate is FROZEN or later; spec is immutable — "
                "use derive_new_version() to propose a change",
                candidate_id=candidate_id,
                state=candidate.state.value,
            )

    # ---- queries -----------------------------------------------------------

    def list_by_state(self, state: CandidateState) -> List[StrategyCandidate]:
        return [c for c in self._candidates.values() if c.state is state]

    def list_all(self) -> List[StrategyCandidate]:
        return list(self._candidates.values())

    def rejected_population(self) -> List[StrategyCandidate]:
        """The full, preserved set of REJECTED/FAILED candidates (roadmap Section 19:
        "the rejected population is part of the scientific record")."""
        return [c for c in self._candidates.values() if c.state in (CandidateState.REJECTED, CandidateState.FAILED)]

    def search_history_summary(self) -> Dict[str, Any]:
        return dict(self._search_history)

    def set_search_space(
        self,
        *,
        search_space: Dict[str, Any],
        search_method: str,
        parameter_search_count: int,
        model_search_count: int,
        selection_criteria: str,
    ) -> None:
        """Record the declared search space/method for this registry's run.

        Roadmap Section 16 requires this to exist before any "best
        candidate" claim can be made; ``selection_bias_status`` starts
        ``UNACCOUNTED`` and must be explicitly set (e.g. to
        ``"DISCLOSED_NO_CORRECTION_APPLIED"`` or
        ``"MULTIPLE_TESTING_CORRECTED"``) by the statistical-validation
        phase, never silently defaulted to a passing status.
        """
        self._search_history["search_space"] = search_space
        self._search_history["search_method"] = search_method
        self._search_history["parameter_search_count"] = parameter_search_count
        self._search_history["model_search_count"] = model_search_count
        self._search_history["selection_criteria"] = selection_criteria
        self._save()
