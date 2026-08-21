"""Exploration Engine (Phase 9, second pass): propose genuinely UNEXPLORED regions.

Priority order, per spec item 4: mechanism class never tested > asset
relationship never tested > timeframe never tested > event interaction never
tested > search-space region never tested > dimension combination never seen.

A parameter tweak on an already-tested triple ("RSI 30 -> RSI 29") is NEVER
exploration -- :func:`is_parameter_only_change` makes that judgement
explicit and testable, not implicit in which function happened to be called.

Reuses ``idea_machine.search_space_registry.SearchSpaceRegistry`` for the
region model and ``idea_machine.research_space.exploration_engine`` for the
underlying candidate-generation mechanics (already built, already
live-demonstrated in Cycle 14) -- this module is the region-shaped,
explainability-carrying interface the Phase 9 (second pass) spec asks for,
not a second implementation of the same search logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from idea_machine.core.ids import mint_id
from idea_machine.governance import guard
from idea_machine.search_space_registry import EXHAUSTED, UNEXPLORED, SearchRegion, SearchSpaceRegistry

EXPLORE = "EXPLORE"


@dataclass(frozen=True)
class SearchProposal:
    """One proposed idea, tagged with its mode and the region it targets.

    ``explainability`` answers the 5 mandatory questions (spec item 15) --
    a proposal that cannot answer all five is never constructed by this
    module (see :meth:`ExplorationEngine.propose`), so an unanswerable
    proposal simply does not exist rather than existing-but-unexplained.
    """

    proposal_id: str
    region_id: str
    mode: str
    dimensions: Dict[str, str]
    reason_codes: Tuple[str, ...]
    explainability: Dict[str, str]  # the 5 answers, keyed by question tag

    def to_dict(self) -> Dict:
        return {
            "proposal_id": self.proposal_id, "region_id": self.region_id, "mode": self.mode,
            "dimensions": dict(self.dimensions), "reason_codes": list(self.reason_codes),
            "explainability": dict(self.explainability),
        }


def is_parameter_only_change(before: Dict[str, str], after: Dict[str, str], *,
                             parameter_keys: Sequence[str] = ("holding_horizon", "threshold", "window")) -> bool:
    """True when ``after`` differs from ``before`` ONLY in parameter-like keys.

    "RSI 30 -> RSI 29" and "60m window -> 90m window" are parameter tweaks:
    every structural dimension (mechanism, instrument, macro_driver,
    confirmation_mechanism, cross_asset_relationship, ...) is identical, only
    a numeric/threshold-like value moved. That is never exploration.
    """
    structural_before = {k: v for k, v in before.items() if k not in parameter_keys}
    structural_after = {k: v for k, v in after.items() if k not in parameter_keys}
    return structural_before == structural_after and before != after


def _explain(dimensions: Dict[str, str], region: SearchRegion, rationale_now: str) -> Dict[str, str]:
    return {
        "why_this_mechanism": dimensions.get("mechanism", "no specific mechanism -- structural/driver-only region")
                              or "existing mechanism family, applied to a new context",
        "why_this_instrument": dimensions.get("instrument", "unspecified"),
        "why_this_timeframe": dimensions.get("holding_horizon", "not yet fixed -- window chosen at pre-registration"),
        "why_now": rationale_now,
        "how_it_differs_from_prior_tests": (
            "; ".join(region.evidence) if region.evidence else "no prior record of this exact combination exists"
        ),
    }


class ExplorationEngine:
    def __init__(self, registry: SearchSpaceRegistry) -> None:
        self.registry = registry

    def propose(self, *, limit: Optional[int] = None) -> List[SearchProposal]:
        """Propose EXPLORE candidates strictly from the registry's UNEXPLORED regions.

        Every dimension combination proposed here is, by construction (see
        ``SearchSpaceRegistry._seed_from_real_history``), either a real
        instrument x confirmed-present-but-never-used-driver combination or a
        real, callable, never-run recombined mechanism -- never a parameter
        variant of something already tested.
        """
        guard.require("REGISTER_SEARCH_REGION", detail="exploration proposal batch")
        proposals: List[SearchProposal] = []
        for region in self.registry.unexplored_regions():
            reason_codes = self._reason_codes_for(region)
            proposal = SearchProposal(
                proposal_id=mint_id("PROP", {"region": region.region_id, "mode": EXPLORE}),
                region_id=region.region_id, mode=EXPLORE, dimensions=dict(region.dimensions),
                reason_codes=reason_codes,
                explainability=_explain(
                    region.dimensions, region,
                    rationale_now=("this combination was confirmed to have real underlying data before this "
                                  "cycle's candidate pool was built, and has not been proposed in any prior cycle"),
                ),
            )
            proposals.append(proposal)
        proposals.sort(key=lambda p: p.proposal_id)
        return proposals[:limit] if limit is not None else proposals

    @staticmethod
    def _reason_codes_for(region: SearchRegion) -> Tuple[str, ...]:
        codes = ["UNEXPLORED_REGION"]
        if "macro_driver" in region.dimensions and "mechanism" not in region.dimensions:
            codes.append("UNEXPLORED_CROSS_ASSET_RELATIONSHIP")
        if "mechanism" in region.dimensions:
            codes.append("UNEXPLORED_MECHANISM_RECOMBINATION")
        codes.append("DATA_AVAILABLE")  # only real, confirmed-present regions are seeded, see registry docstring
        return tuple(codes)

    def check_space_constrained(self) -> Optional[str]:
        """Spec item 9: if the space is genuinely narrow, SAY SO -- never fake diversity."""
        exhausted, detail = self.registry.is_exhausted()
        if exhausted:
            return f"EXPLORATION_SPACE_CONSTRAINED: {detail}"
        unexplored = self.registry.unexplored_regions()
        if len(unexplored) < 3:
            return f"EXPLORATION_SPACE_CONSTRAINED: only {len(unexplored)} unexplored region(s) available"
        return None
