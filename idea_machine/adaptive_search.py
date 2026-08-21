"""Adaptive Search Controller (Phase 9, second pass).

Allocates the cycle's search budget between EXPLOIT and EXPLORE, scores every
candidate region with the seven explainable components spec item 6 requires,
enforces the mandatory exploration floor and the per-family diversity cap,
checks the 5-question explainability requirement, detects when the current
search space is exhausted, and records every decision -- selected or
rejected -- to the append-only :class:`~idea_machine.search_decision_ledger.SearchDecisionLedger`.

This module is the "what should we research next" layer. It never touches a
Factory gate, never declares an edge, and never reads the holdout -- all of
that remains ``idea_machine.real_factory_integration.RealFactoryIntegrator``'s
job, called by whoever consumes this controller's selected proposals (see
``AutonomousIdeaMachine.run_adaptive_search_cycle`` in ``autonomous_loop.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from idea_machine.core import epistemic
from idea_machine.core.errors import GovernanceViolation
from idea_machine.exploitation_engine import EXPLOIT, ExploitationEngine
from idea_machine.exploration_engine import EXPLORE, ExplorationEngine, SearchProposal
from idea_machine.governance import guard
from idea_machine.opportunity_queue import OpportunityQueue
from idea_machine.research_memory import ResearchMemory
from idea_machine.research_space.decision_engine import cost_registered, data_available
from idea_machine.search_decision_ledger import SearchDecisionLedger, SearchDecisionScore
from idea_machine.search_space_registry import SearchSpaceRegistry

#: Hard governance floor. GovernanceViolation if configured below this.
GOVERNANCE_MIN_EXPLORATION_FRACTION = 0.20
#: Default, spec item 3.
DEFAULT_MIN_EXPLORATION_FRACTION = 0.30
#: Spec item 9.
MAX_SAME_FAMILY_PER_CYCLE = 0.20

REQUIRED_EXPLAINABILITY_KEYS = (
    "why_this_mechanism", "why_this_instrument", "why_this_timeframe",
    "why_now", "how_it_differs_from_prior_tests",
)


@dataclass(frozen=True)
class SearchPlan:
    exploration_budget_fraction: float
    exploitation_budget_fraction: float
    explore_slots: int
    exploit_slots: int
    total_slots: int
    explore_regions: Tuple[str, ...]
    exploit_regions: Tuple[str, ...]
    space_constrained_note: Optional[str]

    def to_dict(self) -> Dict:
        return {
            "exploration_budget_fraction": self.exploration_budget_fraction,
            "exploitation_budget_fraction": self.exploitation_budget_fraction,
            "explore_slots": self.explore_slots, "exploit_slots": self.exploit_slots,
            "total_slots": self.total_slots,
            "explore_regions": list(self.explore_regions), "exploit_regions": list(self.exploit_regions),
            "space_constrained_note": self.space_constrained_note,
        }


@dataclass(frozen=True)
class SearchCycleResult:
    cycle_id: str
    plan: SearchPlan
    selected: Tuple[SearchProposal, ...]
    rejected_unexplainable: Tuple[str, ...]
    rejected_diversity: Tuple[str, ...]
    expansion_request: Optional[Dict]

    def to_dict(self) -> Dict:
        return {
            "cycle_id": self.cycle_id, "plan": self.plan.to_dict(),
            "selected": [p.to_dict() for p in self.selected],
            "rejected_unexplainable": list(self.rejected_unexplainable),
            "rejected_diversity": list(self.rejected_diversity),
            "expansion_request": self.expansion_request,
        }


class AdaptiveSearchController:
    def __init__(
        self,
        *,
        memory: Optional[ResearchMemory] = None,
        registry: Optional[SearchSpaceRegistry] = None,
        opportunity_queue: Optional[OpportunityQueue] = None,
        decision_ledger: Optional[SearchDecisionLedger] = None,
        min_exploration_fraction: float = DEFAULT_MIN_EXPLORATION_FRACTION,
    ) -> None:
        if min_exploration_fraction < GOVERNANCE_MIN_EXPLORATION_FRACTION:
            raise GovernanceViolation(
                f"minimum_exploration_fraction ({min_exploration_fraction}) may not be configured "
                f"below the governance floor ({GOVERNANCE_MIN_EXPLORATION_FRACTION})",
                requested=min_exploration_fraction, floor=GOVERNANCE_MIN_EXPLORATION_FRACTION,
            )
        self.memory = memory or ResearchMemory()
        if not self.memory._loaded:
            self.memory.load()
        self.registry = registry or SearchSpaceRegistry(self.memory)
        self.opportunity_queue = opportunity_queue or OpportunityQueue()
        if not self.opportunity_queue._loaded:
            self.opportunity_queue.load()
        self.exploration_engine = ExplorationEngine(self.registry)
        self.exploitation_engine = ExploitationEngine(self.registry, self.opportunity_queue)
        self.decision_ledger = decision_ledger or SearchDecisionLedger()
        self.min_exploration_fraction = min_exploration_fraction

    # ------------------------------------------------------------ planning

    def plan(self, *, total_slots: int) -> SearchPlan:
        guard.require("ALLOCATE_RESEARCH_MODE_BUDGET", total_slots=total_slots)
        explore_slots = max(1, round(total_slots * self.min_exploration_fraction)) if total_slots > 0 else 0
        exploit_slots = total_slots - explore_slots

        explore_candidates = self.exploration_engine.propose(limit=explore_slots)
        exploit_candidates = self.exploitation_engine.propose(limit=exploit_slots)

        constrained_note = self.exploration_engine.check_space_constrained()

        return SearchPlan(
            exploration_budget_fraction=self.min_exploration_fraction,
            exploitation_budget_fraction=round(1 - self.min_exploration_fraction, 4),
            explore_slots=explore_slots, exploit_slots=exploit_slots, total_slots=total_slots,
            explore_regions=tuple(p.region_id for p in explore_candidates),
            exploit_regions=tuple(p.region_id for p in exploit_candidates),
            space_constrained_note=constrained_note,
        )

    # ---------------------------------------------------------- one cycle

    def run_cycle(self, *, cycle_id: str, total_slots: int) -> SearchCycleResult:
        search_plan = self.plan(total_slots=total_slots)

        explore_proposals = self.exploration_engine.propose(limit=search_plan.explore_slots)
        exploit_proposals = self.exploitation_engine.propose(limit=search_plan.exploit_slots)
        all_proposals = list(explore_proposals) + list(exploit_proposals)

        # (1) Explainability gate -- spec item 15.
        explainable, rejected_unexplainable = [], []
        for p in all_proposals:
            missing = [k for k in REQUIRED_EXPLAINABILITY_KEYS if not p.explainability.get(k)]
            if missing:
                rejected_unexplainable.append(p.proposal_id)
                self._record(cycle_id, p, selected=False,
                            reason_codes=list(p.reason_codes) + ["REJECT_UNEXPLAINABLE"],
                            score=_zero_score(), extra_evidence=[f"missing: {missing}"])
                continue
            explainable.append(p)

        # (2) Diversity cap -- spec item 9. Family = (mechanism, instrument).
        by_family: Dict[Tuple[str, str], List[SearchProposal]] = {}
        for p in explainable:
            key = (p.dimensions.get("mechanism", ""), p.dimensions.get("instrument", ""))
            by_family.setdefault(key, []).append(p)
        max_per_family = max(1, int(len(explainable) * MAX_SAME_FAMILY_PER_CYCLE)) if explainable else 0
        diverse, rejected_diversity = [], []
        for key, members in sorted(by_family.items()):
            keep = members[:max_per_family]
            drop = members[max_per_family:]
            diverse.extend(keep)
            for p in drop:
                rejected_diversity.append(p.proposal_id)
                self._record(cycle_id, p, selected=False,
                            reason_codes=list(p.reason_codes) + ["REJECTED_DIVERSITY_CAP"],
                            score=_zero_score(), extra_evidence=[f"family {key} exceeds {MAX_SAME_FAMILY_PER_CYCLE:.0%} cap"])

        # (3) Score + record every remaining proposal (selected).
        selected: List[SearchProposal] = []
        for p in diverse:
            score = self._score(p, sibling_count=len(by_family[(p.dimensions.get("mechanism", ""),
                                                                p.dimensions.get("instrument", ""))]))
            self._record(cycle_id, p, selected=True, reason_codes=list(p.reason_codes), score=score,
                        extra_evidence=[])
            selected.append(p)

        expansion_request = self._expansion_request_if_needed()

        return SearchCycleResult(
            cycle_id=cycle_id, plan=search_plan, selected=tuple(selected),
            rejected_unexplainable=tuple(rejected_unexplainable), rejected_diversity=tuple(rejected_diversity),
            expansion_request=expansion_request,
        )

    # --------------------------------------------------------------- scoring

    def _score(self, proposal: SearchProposal, *, sibling_count: int) -> SearchDecisionScore:
        region = self.registry.get(proposal.region_id)
        instrument = proposal.dimensions.get("instrument", "")
        driver = proposal.dimensions.get("macro_driver")

        avail = data_available(instrument, driver) if instrument else False
        cost_ok = cost_registered(instrument) if instrument else False

        if proposal.mode == EXPLORE:
            exploration_value = 0.9
            evidence_value = 0.1
            novelty_value = 0.85
        else:
            exploration_value = 0.05
            evidence_value = 0.7 if region and region.status == epistemic.UNDERPOWERED else 0.4
            novelty_value = 0.15

        data_availability = 1.0 if (avail and cost_ok) else (0.3 if avail else 0.0)
        economic_value = 0.6 if instrument and driver else (0.4 if instrument else 0.0)
        failure_penalty = 0.5 if region and region.status == epistemic.TESTED else 0.0
        redundancy_penalty = min(0.6, 0.15 * max(0, sibling_count - 1))
        power_penalty = 0.2 if region and region.status == epistemic.UNDERPOWERED else 0.0

        return SearchDecisionScore(
            exploration_value=exploration_value, evidence_value=evidence_value,
            data_availability=data_availability, economic_value=economic_value,
            novelty_value=novelty_value, failure_penalty=failure_penalty,
            redundancy_penalty=redundancy_penalty, power_penalty=power_penalty,
        )

    def _record(self, cycle_id: str, proposal: SearchProposal, *, selected: bool,
               reason_codes: Sequence[str], score: SearchDecisionScore, extra_evidence: Sequence[str]) -> None:
        region = self.registry.get(proposal.region_id)
        evidence = list(region.evidence) if region else []
        evidence.extend(extra_evidence)
        self.decision_ledger.record(
            cycle_id=cycle_id, region_id=proposal.region_id, mode=proposal.mode, selected=selected,
            score=score, reason_codes=reason_codes, source_evidence=evidence,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------- expansion

    def _expansion_request_if_needed(self) -> Optional[Dict]:
        exhausted, detail = self.registry.is_exhausted()
        if not exhausted:
            return None
        guard.require("REQUEST_SEARCH_SPACE_EXPANSION", detail=detail)
        known_dims = sorted({k for r in self.registry.all_regions() for k in r.dimensions})
        return {
            "type": "SEARCH_SPACE_EXPANSION_REQUEST",
            "reason": detail,
            "current_space_dimensions": known_dims,
            "potential_expansion": [
                "new event families beyond NFP/CPI", "new asset classes (options-derived variables, volatility)",
                "new rates instruments", "new commodity instruments", "new equity index instruments",
                "new data sources -- proposal only, this controller never requests holdout or sensitive-data access",
            ],
            "authority": "Data/holdout access remains a human/Factory-governance decision; this is a proposal only",
        }


def _zero_score() -> SearchDecisionScore:
    return SearchDecisionScore(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
