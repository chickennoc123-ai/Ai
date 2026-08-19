"""Source/research diversity metrics — Generation 3, Phase 19.

Read-only measurement (recomputed from the registries on every call,
never cached counters): counts by source type, market, timeframe,
hypothesis family, mechanism, and feature family, plus a simple
concentration measure. Used to DETECT research concentration and
over-reliance on one source ecosystem — never blindly optimized toward
"maximum diversity" (this module only reports; it makes no decisions).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.factory.feature_catalog import family_of
from core.factory.hypothesis import HypothesisRegistry
from core.factory.novelty_engine import FamilyRegistry
from core.factory.research_source_registry import ResearchSourceRegistry


def _count(items) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return out


def _max_share(counts: Dict[str, int]) -> float:
    total = sum(counts.values())
    return (max(counts.values()) / total) if total else 0.0


def compute_diversity_report(
    *,
    source_registry: Optional[ResearchSourceRegistry] = None,
    hypothesis_registry: Optional[HypothesisRegistry] = None,
    family_registry: Optional[FamilyRegistry] = None,
    concentration_flag_threshold: float = 0.75,
) -> Dict[str, Any]:
    sources = source_registry.list_all() if source_registry else []
    hypotheses = hypothesis_registry.list_all() if hypothesis_registry else []
    families = family_registry.list_all() if family_registry else []

    by_source_type = _count(s.source_type for s in sources)
    by_market = _count(h.instrument_scope for h in hypotheses)
    by_timeframe = _count(h.timeframe_scope for h in hypotheses)
    by_origin = _count(h.origin_type for h in hypotheses)
    by_feature_family = _count(
        family_of(feat) for h in hypotheses for feat in h.feature_dependencies
    )
    by_hypothesis_family = {
        f.family_id: len(f.members) for f in families if f.family_kind == "HYPOTHESIS_FAMILY"
    }

    concentration = {
        "source_type_max_share": _max_share(by_source_type),
        "market_max_share": _max_share(by_market),
        "origin_max_share": _max_share(by_origin),
    }
    flags = [
        f"CONCENTRATION:{axis}"
        for axis, share in concentration.items()
        if share >= concentration_flag_threshold and sum(
            {"source_type_max_share": by_source_type, "market_max_share": by_market,
             "origin_max_share": by_origin}[axis].values()
        ) >= 3  # a 1-2 item population is trivially concentrated; not a meaningful flag
    ]

    return {
        "by_source_type": by_source_type,
        "by_market": by_market,
        "by_timeframe": by_timeframe,
        "by_origin_type": by_origin,
        "by_feature_family": by_feature_family,
        "by_hypothesis_family": by_hypothesis_family,
        "concentration": concentration,
        "concentration_flags": flags,
        "meaning": "diversity is measured to detect concentration -- it is not itself optimized",
    }
