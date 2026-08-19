"""Research knowledge graph traversal — Generation 5, Phase 11.

The Factory's lineage was always reconstructible by hand (every prior
generation's "production research" test walks it ad hoc), but never
through one reusable function that returns the same shape forward and
backward. This module is that function: given any node in
SOURCE -> CLAIM -> HYPOTHESIS -> CANDIDATE -> EXPERIMENT/RESULT ->
FAILURE/SUPPORT, it returns the full chain both directions, so "what
refuted this hypothesis, under which operationalisation, from which
candidate/evidence/instrument/period" is one function call, not a
manual grep.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from utils.exceptions import EAFactoryError


class LineageGraphError(EAFactoryError):
    pass


@dataclass(frozen=True)
class LineageTrace:
    hypothesis_id: str
    sources: List[Dict[str, Any]]
    claims: List[Dict[str, Any]]
    candidates: List[Dict[str, Any]]
    failures: List[Dict[str, Any]]
    refutation_basis: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id, "sources": self.sources, "claims": self.claims,
            "candidates": self.candidates, "failures": self.failures, "refutation_basis": self.refutation_basis,
        }


def trace_hypothesis_lineage(
    hypothesis_id: str, *, hypothesis_registry, claim_registry, source_registry, strategy_registry, failure_library,
) -> LineageTrace:
    """Full backward+forward trace for one hypothesis: which sources and
    claims it descends from, which candidates it produced, and which
    failure records explain why it was refuted (if it was) -- with the
    operationalisation the refutation applies to, so a reader never has
    to infer scope from prose alone.
    """
    h = hypothesis_registry.get(hypothesis_id)

    sources = []
    for sid in h.parent_source_ids:
        try:
            sources.append(source_registry.get(sid).to_dict())
        except Exception:
            sources.append({"source_id": sid, "error": "not found"})

    claims = []
    for cid in h.parent_claim_ids:
        try:
            claims.append(claim_registry.get(cid).to_dict())
        except Exception:
            claims.append({"claim_id": cid, "error": "not found"})

    candidates = []
    for cand_id in h.candidate_ids:
        try:
            c = strategy_registry.get(cand_id)
            candidates.append({"candidate_id": cand_id, "state": c.state.value})
        except Exception:
            candidates.append({"candidate_id": cand_id, "error": "not found"})

    failures = [f.to_dict() for f in failure_library.failures_for_entity(hypothesis_id)]
    for cand_id in h.candidate_ids:
        failures.extend(f.to_dict() for f in failure_library.failures_for_entity(cand_id))

    if h.formalization_status == "REFUTED":
        refutation_basis = {
            "refuted": True,
            "falsification_conditions": h.falsification_conditions,
            "instrument_scope": h.instrument_scope,
            "target_definition": h.target_definition,
            "holding_period": h.holding_period,
            "cost_assumptions": h.cost_assumptions,
            "regime_conditions": h.regime_conditions,
            "evidence_level": h.evidence_level,
            "candidates_responsible": list(h.candidate_ids),
        }
    else:
        refutation_basis = {"refuted": False, "formalization_status": h.formalization_status}

    return LineageTrace(
        hypothesis_id=hypothesis_id, sources=sources, claims=claims, candidates=candidates,
        failures=failures, refutation_basis=refutation_basis,
    )


def trace_all_hypotheses(
    *, hypothesis_registry, claim_registry, source_registry, strategy_registry, failure_library,
) -> List[LineageTrace]:
    return [
        trace_hypothesis_lineage(
            h.hypothesis_id, hypothesis_registry=hypothesis_registry, claim_registry=claim_registry,
            source_registry=source_registry, strategy_registry=strategy_registry, failure_library=failure_library,
        )
        for h in hypothesis_registry.list_all()
    ]
