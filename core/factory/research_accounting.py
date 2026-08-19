"""Search Accounting — Generation 2, Phase 12.

Aggregates counts across every Generation 2 registry into the single
answer the task requires the Factory be able to give: "what exactly was
searched, and how much." Read-only — this module holds no state of its
own; every number is recomputed from the underlying registries on every
call, so it can never drift from them (unlike a separately-maintained
counter that could fall out of sync).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.factory.claim_registry import ClaimRegistry
from core.factory.hypothesis import HypothesisRegistry
from core.factory.registry import StrategyRegistry
from core.factory.research_source_registry import ResearchSourceRegistry
from core.factory.search_space import SearchSpaceRegistry
from core.factory.state_machine import CandidateState

#: Never silently marked PASS by this module (Phase 12's explicit
#: instruction) -- SELECTION_BIAS_STATUS here is always one of these two
#: until the (separate, not-yet-built) statistical-validation layer
#: formally establishes something stronger, per
#: ML-001-SEARCH-SPACE-AND-MULTIPLE-TESTING-CONTRACT.md.
UNACCOUNTED = "UNACCOUNTED"
ACCOUNTING_ONLY = "ACCOUNTING_ONLY"


def compute_search_accounting_summary(
    *,
    source_registry: Optional[ResearchSourceRegistry] = None,
    claim_registry: Optional[ClaimRegistry] = None,
    hypothesis_registry: Optional[HypothesisRegistry] = None,
    search_space_registry: Optional[SearchSpaceRegistry] = None,
    strategy_registry: Optional[StrategyRegistry] = None,
) -> Dict[str, Any]:
    """Every registry argument is optional so a caller auditing only part
    of the pipeline (e.g. just hypotheses) doesn't need to construct
    every registry — an omitted registry's counts are reported as 0 with
    the field's presence still guaranteed, never silently absent."""
    sources = source_registry.list_all() if source_registry else []
    claims = claim_registry.list_all() if claim_registry else []
    hypotheses = hypothesis_registry.list_all() if hypothesis_registry else []
    search_spaces = search_space_registry.list_all() if search_space_registry else []
    candidates = strategy_registry.list_all() if strategy_registry else []

    total_formalized_hypotheses = sum(1 for h in hypotheses if h.formalization_status != "DRAFT")
    total_candidates_tested = sum(
        1 for c in candidates if c.state not in (CandidateState.GENERATED, CandidateState.DATA_VALIDATED)
    )
    total_candidates_rejected = sum(1 for c in candidates if c.state == CandidateState.REJECTED)
    total_candidates_surviving = sum(
        1 for c in candidates if c.state not in (CandidateState.REJECTED, CandidateState.FAILED)
    )
    total_candidates_frozen = sum(
        1 for c in candidates
        if c.state in (CandidateState.FROZEN, CandidateState.HOLDOUT_TESTED, CandidateState.EVG_REVIEW,
                       CandidateState.RESEARCH_CANDIDATE, CandidateState.PAPER_VALIDATION, CandidateState.LIVE_CANDIDATE)
    )

    parameter_combinations = sum(s.combination_count() for s in search_spaces)
    symbol_combinations = len({sym for s in search_spaces for sym in s.symbols})
    feature_combinations = len({feat for s in search_spaces for feat in s.features})

    return {
        "TOTAL_SOURCES": len(sources),
        "TOTAL_CLAIMS": len(claims),
        "TOTAL_HYPOTHESES": len(hypotheses),
        "TOTAL_FORMALIZED_HYPOTHESES": total_formalized_hypotheses,
        "TOTAL_SEARCH_SPACES": len(search_spaces),
        "TOTAL_CANDIDATES_GENERATED": len(candidates),
        "TOTAL_CANDIDATES_TESTED": total_candidates_tested,
        "TOTAL_CANDIDATES_REJECTED": total_candidates_rejected,
        "TOTAL_CANDIDATES_SURVIVING": total_candidates_surviving,
        "TOTAL_CANDIDATES_FROZEN": total_candidates_frozen,
        "SEARCH_SPACE_SIZE": parameter_combinations,
        "PARAMETER_COMBINATIONS": parameter_combinations,
        "SYMBOL_COMBINATIONS": symbol_combinations,
        "FEATURE_COMBINATIONS": feature_combinations,
        "GENERATION_METHOD": sorted({s.generation_method for s in search_spaces}) if search_spaces else [],
        "SELECTION_BIAS_STATUS": ACCOUNTING_ONLY if candidates else UNACCOUNTED,
    }
