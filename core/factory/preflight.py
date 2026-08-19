"""Early rejection / pre-flight checks — Generation 3, Phase 14.

Cheap, named checks a hypothesis + search space must pass BEFORE any
expensive candidate evaluation is attempted. Failures are returned as an
exact, named list (never just a boolean) and are recorded into the
Failure Library so early rejection still contributes information.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from core.factory.dataset_registry import DatasetRegistry
from core.factory.failure_library import FailureLibrary
from core.factory.feature_catalog import implementation_status
from core.factory.hypothesis import HypothesisRecord
from core.factory.hypothesis_quality_gates import evaluate_hypothesis_quality_gates
from core.factory.novelty_engine import FamilyRegistry, mechanism_signature, text_signature
from core.factory.search_space import SearchSpace

#: The named pre-flight checks, in execution order.
PREFLIGHT_CHECKS = (
    "DATA_AVAILABLE",
    "FEATURE_AVAILABLE",
    "TEMPORAL_SAFE",
    "TARGET_DEFINED",
    "MINIMUM_HISTORY",
    "COST_MODEL_AVAILABLE",
    "SEARCH_SPACE_VALID",
    "HYPOTHESIS_ELIGIBLE",
    "DUPLICATE_STATUS",
)

#: Minimum usable rows a dataset must offer before candidate evaluation
#: is worth attempting -- matches the reality that RF-R2-001's own spec
#: needs multi-year windows; a few hundred bars cannot support the
#: train/validation/holdout protocol at all.
MINIMUM_HISTORY_ROWS = 5000


def run_preflight(
    hypothesis: HypothesisRecord,
    search_space: SearchSpace,
    *,
    dataset_registry: DatasetRegistry,
    family_registry: Optional[FamilyRegistry] = None,
    failure_library: Optional[FailureLibrary] = None,
    max_search_space_size: Optional[int] = None,
    known_statements: Optional[Dict[str, str]] = None,
) -> List[str]:
    """Returns the list of FAILED check names with reasons, empty if all
    pass. Every failure is also recorded to ``failure_library`` when one
    is supplied — early rejection is information, not discarded work."""
    failures: List[str] = []

    # DATA_AVAILABLE + MINIMUM_HISTORY: every symbol in the search space
    # must have a registered, real-market-eligible dataset with enough rows.
    for symbol in search_space.symbols:
        eligible = [d for d in dataset_registry.list_by_instrument(symbol) if d.is_real_market_data_eligible]
        if not eligible:
            failures.append(f"DATA_AVAILABLE (no eligible registered dataset for {symbol})")
        elif all(d.row_count < MINIMUM_HISTORY_ROWS for d in eligible):
            failures.append(
                f"MINIMUM_HISTORY (best available {max(d.row_count for d in eligible)} rows "
                f"< required {MINIMUM_HISTORY_ROWS} for {symbol})"
            )

    # FEATURE_AVAILABLE + TEMPORAL_SAFE: every declared feature dependency
    # must be actually IMPLEMENTED (not merely cataloged) -- an
    # unimplemented feature has no verified temporal-safety guarantee.
    for feat in hypothesis.feature_dependencies:
        status = implementation_status(feat)
        if status == "UNKNOWN":
            failures.append(f"FEATURE_AVAILABLE (unrecognized feature: {feat})")
        elif status == "CATALOGED_NOT_IMPLEMENTED":
            failures.append(f"TEMPORAL_SAFE ({feat} is cataloged but has no implemented, temporally-verified formula)")

    # TARGET_DEFINED
    if hypothesis.target_definition.strip().upper() in ("", "UNKNOWN"):
        failures.append("TARGET_DEFINED (hypothesis target_definition is missing)")

    # COST_MODEL_AVAILABLE
    if not search_space.cost_model.strip() or hypothesis.cost_assumptions.strip().upper() in ("", "UNKNOWN"):
        failures.append("COST_MODEL_AVAILABLE (search space or hypothesis lacks an explicit cost model)")

    # SEARCH_SPACE_VALID (+ explicit budget bound when given)
    combos = search_space.combination_count()
    if combos < 1:
        failures.append("SEARCH_SPACE_VALID (zero combinations)")
    if max_search_space_size is not None and combos > max_search_space_size:
        failures.append(f"SEARCH_SPACE_VALID (combination count {combos} exceeds budget {max_search_space_size})")

    # HYPOTHESIS_ELIGIBLE (full quality gates, reused, not re-implemented)
    gate_failures = evaluate_hypothesis_quality_gates(hypothesis, search_space=search_space)
    if gate_failures:
        failures.append(f"HYPOTHESIS_ELIGIBLE (quality gates failed: {gate_failures})")

    # DUPLICATE_STATUS: an EXACT duplicate (identical normalized statement
    # already registered under a different hypothesis id in the same
    # mechanism family) fails pre-flight -- re-running the identical
    # research is waste, not independence. Mere family membership (a
    # parameter variant) is deliberately NOT a failure: variants are
    # legitimate research that the family/multiple-testing accounting
    # tracks; only literal duplication is rejected here.
    if family_registry is not None and known_statements:
        sig = mechanism_signature(hypothesis.original_claim)
        family = family_registry.find_by_signature("HYPOTHESIS_FAMILY", sig)
        if family is not None:
            own_text_sig = text_signature(hypothesis.original_claim)
            for member_id in family.members:
                if member_id == hypothesis.hypothesis_id:
                    continue
                member_statement = known_statements.get(member_id)
                if member_statement is not None and text_signature(member_statement) == own_text_sig:
                    failures.append(f"DUPLICATE_STATUS (exact statement duplicate of {member_id})")
                    break

    if failures and failure_library is not None:
        for failure in failures:
            check_name = failure.split(" ", 1)[0]
            category = {
                "DATA_AVAILABLE": "INVALID_DATA",
                "MINIMUM_HISTORY": "INSUFFICIENT_HISTORY",
                "FEATURE_AVAILABLE": "SEARCH_SPACE_INVALID",
                "TEMPORAL_SAFE": "TEMPORAL_INVALIDITY",
                "TARGET_DEFINED": "FORMALIZATION_INCOMPLETE",
                "COST_MODEL_AVAILABLE": "FORMALIZATION_INCOMPLETE",
                "SEARCH_SPACE_VALID": "SEARCH_SPACE_INVALID",
                "HYPOTHESIS_ELIGIBLE": "FORMALIZATION_INCOMPLETE",
                "DUPLICATE_STATUS": "DUPLICATE",
            }.get(check_name, "GOVERNANCE_FAILURE")
            failure_library.record(
                entity_id=hypothesis.hypothesis_id,
                failure_stage="PREFLIGHT",
                failure_category=category,
                failure_reason=failure,
                related_search_space=search_space.search_space_id,
                related_features=tuple(hypothesis.feature_dependencies),
            )
    return failures
