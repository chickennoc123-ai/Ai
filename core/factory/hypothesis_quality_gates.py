"""Hypothesis Quality Gates — Generation 2, Phase 14.

Before a hypothesis can generate a research candidate, verify (per the
task's own list) that it is falsifiable, has a defined target, time
horizon, instrument scope, known feature dependencies, known temporal
availability, explicit cost assumptions, falsification conditions, source
lineage, and (checked separately, at generation time) an explicit search
space. Missing fields are never silently filled — a hypothesis that fails
any gate is rejected with the exact list of what is missing.
"""

from __future__ import annotations

from typing import List, Optional

from core.factory.feature_catalog import implementation_status
from core.factory.hypothesis import HypothesisRecord
from core.factory.search_space import SearchSpace
from utils.exceptions import EAFactoryError

_VAGUE_VALUES = frozenset({"", "unknown", "tbd", "n/a", "na", "none", "?", "..."})


class HypothesisNotEligibleError(EAFactoryError):
    """Raised when a hypothesis fails one or more mandatory quality
    gates -- carries the full list of failing gates, not just the first
    one, so a caller can fix everything in one pass."""


def _is_vague(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in _VAGUE_VALUES)


def evaluate_hypothesis_quality_gates(
    hypothesis: HypothesisRecord, *, search_space: Optional[SearchSpace] = None
) -> List[str]:
    """Returns the list of FAILED gate names (empty list = all gates
    pass). Never raises -- callers that want fail-closed behavior should
    use ``assert_hypothesis_eligible_for_candidate_generation`` instead;
    this function is for callers (e.g. a REJECT/HOLD/NEEDS_FORMALIZATION
    classifier) that want the full picture."""
    failed: List[str] = []

    # 1. Falsifiable
    if _is_vague(hypothesis.falsification_conditions):
        failed.append("FALSIFIABLE (falsification_conditions missing/vague)")
    # 2. Target defined
    if _is_vague(hypothesis.target_definition):
        failed.append("TARGET_DEFINED (target_definition missing/vague)")
    # 3. Time horizon defined
    if _is_vague(hypothesis.holding_period):
        failed.append("TIME_HORIZON_DEFINED (holding_period missing/vague)")
    # 4. Instrument scope defined
    if _is_vague(hypothesis.instrument_scope):
        failed.append("INSTRUMENT_SCOPE_DEFINED (instrument_scope missing/vague)")
    # 5. Feature dependencies known
    if not hypothesis.feature_dependencies:
        failed.append("FEATURE_DEPENDENCIES_KNOWN (feature_dependencies is empty)")
    # 6. Temporal availability known -- every declared feature dependency
    # must resolve to something the Factory actually knows about (either
    # implemented or at least cataloged); an unrecognized name means
    # availability cannot be assessed at all.
    unknown_features = [f for f in hypothesis.feature_dependencies if implementation_status(f) == "UNKNOWN"]
    if unknown_features:
        failed.append(f"TEMPORAL_AVAILABILITY_KNOWN (unrecognized feature dependencies: {unknown_features})")
    # 7. Cost assumptions explicit
    if _is_vague(hypothesis.cost_assumptions):
        failed.append("COST_ASSUMPTIONS_EXPLICIT (cost_assumptions missing/vague)")
    # 8. Falsification conditions exist -- same field as gate 1, kept as
    # a separate named gate per the task's own numbered list, but not
    # double-penalized: only appended once above.
    # 9. Source lineage exists
    if _is_vague(hypothesis.source_reference) or _is_vague(hypothesis.original_claim):
        failed.append("SOURCE_LINEAGE_EXISTS (source_reference/original_claim missing)")
    # 10. Search space explicit (checked only if provided -- a hypothesis
    # can legitimately be FORMALIZED and eligible in every other respect
    # before any search space has been declared for it yet; candidate
    # generation itself always requires one, enforced separately in
    # core.factory.candidate_generation_engine).
    if search_space is not None and search_space.combination_count() < 1:
        failed.append("SEARCH_SPACE_EXPLICIT (search space has zero combinations)")

    # Also require formalization to have actually happened -- a DRAFT
    # hypothesis cannot pass regardless of how complete its (unset)
    # fields look, since formalization_status is the record of intent.
    if hypothesis.formalization_status == "DRAFT":
        failed.append("FORMALIZED (formalization_status is still DRAFT)")

    return failed


def assert_hypothesis_eligible_for_candidate_generation(
    hypothesis: HypothesisRecord, *, search_space: Optional[SearchSpace] = None
) -> None:
    """Fail-closed gate: raises ``HypothesisNotEligibleError`` listing
    every failed gate if the hypothesis is not ready to generate a
    candidate from. Never silently fills a missing field, never proceeds
    partially."""
    failed = evaluate_hypothesis_quality_gates(hypothesis, search_space=search_space)
    if failed:
        raise HypothesisNotEligibleError(
            "hypothesis is not eligible for candidate generation -- REJECT/HOLD/NEEDS_FORMALIZATION",
            hypothesis_id=hypothesis.hypothesis_id,
            failed_gates=failed,
        )
