"""Strategy Factory candidate registry + search-history accounting.

Per ``ML-001-STRATEGY-FACTORY-SPEC.md`` §2, §5, §7, §8: a durable,
file-backed registry that (a) hands out immutable, monotonically
increasing candidate IDs (``STRAT-000001``, ...), (b) enforces the
state-machine transition rules from ``core.factory.state_machine``,
(c) refuses to let a FROZEN-or-later candidate's specification change in
place, (d) preserves rejected candidates with their rejection reason
rather than deleting them, (e) maintains the mandatory multiple-testing/
search-bias counters so the Factory can always answer "how many
alternatives were tested before this one passed," and (f) refuses to let
a candidate enter ``MULTIPLE_TESTING_REVIEWED`` until its search-space has
actually been recorded (§7) — the accounting must exist before the gate
named after it can be passed, not be backfilled afterward.

Persistence is a single JSON file, written atomically (write to a temp
file, then rename) so a crash mid-write cannot corrupt the registry. This
is intentionally NOT a database — the durability/auditability requirement
(§5, §6) is about evidence preservation, not query performance, and a
single flat file is trivially diffable/reviewable in git.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.factory.candidate import (
    DatasetProvenanceRecord,
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

#: States at or beyond which a candidate's spec is immutable
#: (ML-001-STRATEGY-FACTORY-SPEC.md §5: "once a candidate enters a frozen
#: validation stage"). Deliberately starts at OOS_TESTED, not at the
#: later-placed FROZEN state (§4) -- a candidate's spec must not be
#: swappable in response to OOS/WFA/robustness/cost/statistics feedback
#: either, since that would itself be an undisclosed form of
#: validation-period tuning. FROZEN (§4) is a distinct, later checkpoint:
#: an explicit declaration that this exact candidate is now finalized for
#: PURE_HOLDOUT access specifically, on top of the immutability that has
#: already applied since OOS_TESTED.
_FROZEN_OR_LATER = {
    CandidateState.OOS_TESTED,
    CandidateState.WFA_TESTED,
    CandidateState.ROBUSTNESS_TESTED,
    CandidateState.COST_TESTED,
    CandidateState.STATISTICALLY_VALIDATED,
    CandidateState.MULTIPLE_TESTING_REVIEWED,
    CandidateState.FROZEN,
    CandidateState.HOLDOUT_TESTED,
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


class MultipleTestingAccountingRequiredError(EAFactoryError):
    """Raised when a candidate attempts MULTIPLE_TESTING_REVIEWED before
    ``StrategyRegistry.set_search_space`` has ever been called for this
    registry. Per ML-001-STRATEGY-FACTORY-SPEC.md §7: the search-space
    accounting must exist BEFORE this gate is passed, not be a label
    applied after the fact with nothing behind it."""


def _empty_search_history() -> Dict[str, Any]:
    return {
        "total_strategies_generated": 0,
        "total_strategies_tested": 0,
        "total_strategies_rejected": 0,
        "total_strategies_failed": 0,
        "total_strategies_surviving": 0,
        "total_strategies_passed": 0,
        "total_hypotheses_ingested": 0,
        "search_space": {},
        "search_method": None,
        "parameter_search_count": 0,
        "model_search_count": 0,
        "selection_criteria": None,
        "selection_bias_status": "UNACCOUNTED",
        # Explicit named subspaces (ML-001-STRATEGY-FACTORY-SPEC.md §7).
        # "total_strategies_*" above IS "TOTAL_CANDIDATES_*" in that spec's
        # vocabulary -- "strategy" and "candidate" are the same concept in
        # this codebase's history; these fields are not duplicated under a
        # second name, only documented as synonyms (see §7).
        "feature_search_space": {},
        "parameter_search_space": {},
        "symbol_search_space": {},
        "timeframe_search_space": {},
        "model_search_space": {},
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
        # Merge onto the current defaults rather than replacing outright, so
        # a registry file written before a search-history field existed
        # (e.g. total_hypotheses_ingested, the explicit *_search_space
        # dicts) still loads with that field correctly defaulted, instead
        # of silently missing it.
        self._search_history = {**_empty_search_history(), **raw.get("search_history", {})}
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
        instrument_universe: Tuple[DatasetProvenanceRecord, ...] = (),
        hypothesis_id: Optional[str] = None,
    ) -> StrategyCandidate:
        """Register a new candidate in state GENERATED. Updates search-history counters.

        ``instrument_universe`` (ML-001-STRATEGY-FACTORY-SPEC.md §12) should
        carry one ``DatasetProvenanceRecord`` per instrument this candidate
        is declared to be tested against — optional/defaulted to ``()`` for
        callers not yet using per-instrument provenance tracking, never
        required retroactively of already-registered candidates.
        ``hypothesis_id`` links back to a ``core.factory.hypothesis
        .HypothesisRecord`` if this candidate originated from an ingested
        external source claim rather than a directly-specified hypothesis.
        """
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
            instrument_universe=tuple(instrument_universe),
            hypothesis_id=hypothesis_id,
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
        move. Raises ``MultipleTestingAccountingRequiredError`` if
        ``new_state`` is ``MULTIPLE_TESTING_REVIEWED`` but
        ``set_search_space`` has never been called on this registry (§7:
        the accounting must exist before this gate can be passed). Every
        transition is appended to the candidate's ``history``, never
        overwritten, and the search-history counters are updated for the
        terminal outcomes (REJECTED/FAILED) and for first-time entry into
        an active testing state (TESTED).
        """
        candidate = self.get(candidate_id)
        assert_legal_transition(candidate.state, new_state)

        if new_state is CandidateState.MULTIPLE_TESTING_REVIEWED and self._search_history["search_method"] is None:
            raise MultipleTestingAccountingRequiredError(
                "cannot enter MULTIPLE_TESTING_REVIEWED before set_search_space() has been "
                "called on this registry -- the search-space accounting this gate certifies "
                "must exist first, not be backfilled after the fact",
                candidate_id=candidate_id,
            )

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
        record is left completely untouched (ML-001-STRATEGY-FACTORY-SPEC.md §5: "Never
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
        """The full, preserved set of REJECTED/FAILED candidates
        (ML-001-STRATEGY-FACTORY-SPEC.md §6: "the rejected population is
        part of the scientific record")."""
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
        feature_search_space: Optional[Dict[str, Any]] = None,
        parameter_search_space: Optional[Dict[str, Any]] = None,
        symbol_search_space: Optional[Dict[str, Any]] = None,
        timeframe_search_space: Optional[Dict[str, Any]] = None,
        model_search_space: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record the declared search space/method for this registry's run.

        ML-001-STRATEGY-FACTORY-SPEC.md §7 requires this to exist before
        any "best candidate" claim can be made, and before a candidate may
        enter ``MULTIPLE_TESTING_REVIEWED`` (enforced by ``transition()``);
        ``selection_bias_status`` starts ``UNACCOUNTED`` and must be
        explicitly set (e.g. to ``"DISCLOSED_NO_CORRECTION_APPLIED"`` or
        ``"MULTIPLE_TESTING_CORRECTED"``) by the statistical-validation
        phase, never silently defaulted to a passing status.

        The five ``*_search_space`` keyword-only dicts are optional,
        additive detail (§7's explicit FEATURE_SEARCH_SPACE /
        PARAMETER_SEARCH_SPACE / SYMBOL_SEARCH_SPACE /
        TIMEFRAME_SEARCH_SPACE / MODEL_SEARCH_SPACE) — the pre-existing
        ``search_space``/``parameter_search_count``/``model_search_count``
        remain the required, backward-compatible summary fields; callers
        that also want the per-dimension breakdown pass these too.
        """
        self._search_history["search_space"] = search_space
        self._search_history["search_method"] = search_method
        self._search_history["parameter_search_count"] = parameter_search_count
        self._search_history["model_search_count"] = model_search_count
        self._search_history["selection_criteria"] = selection_criteria
        self._search_history["feature_search_space"] = feature_search_space or {}
        self._search_history["parameter_search_space"] = parameter_search_space or {}
        self._search_history["symbol_search_space"] = symbol_search_space or {}
        self._search_history["timeframe_search_space"] = timeframe_search_space or {}
        self._search_history["model_search_space"] = model_search_space or {}
        self._save()

    def record_hypothesis_ingested(self) -> None:
        """Increment ``total_hypotheses_ingested`` (ML-001-STRATEGY-FACTORY-
        SPEC.md §7). Call once per ``HypothesisRecord`` registered in
        ``core.factory.hypothesis.HypothesisRegistry`` that is intended to
        feed this Strategy Registry's candidate population — kept as an
        explicit, separate counter rather than inferred from
        ``HypothesisRegistry`` directly, since the two registries are
        independent files and a hypothesis need not ever produce a
        candidate here."""
        self._search_history["total_hypotheses_ingested"] += 1
        self._save()
