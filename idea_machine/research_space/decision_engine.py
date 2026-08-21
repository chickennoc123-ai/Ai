"""Decision engine: ties allocation + scoring + explanation into one cycle.

Answers "what should we research next?", not "how do we make this pass?".
Every accepted or rejected candidate gets a :class:`DecisionRecord`; nothing
is silently dropped. Branch-closure is only ever PROPOSED here -- Factory
governance remains the sole authority that actually marks a family REFUTED
(spec item 15): this engine never writes to ``research_family_registry.json``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from discovery.cost_model import cost_table
from discovery.cycle8_intraday import FX_M1_ROOT

from idea_machine.core import epistemic
from idea_machine.governance import guard
from idea_machine.research_space.decision_record import DecisionLedger, DecisionRecord
from idea_machine.research_space.exploration_debt import ExplorationDebtState, ExplorationDebtTracker
from idea_machine.research_space.information_gain import (
    EXPLOIT, EXPLORE, RECOMBINE, InformationGainScorer, ResearchCandidate,
)
from idea_machine.research_space.novelty_budget import NoveltyBudgetTracker
from idea_machine.research_space.research_allocator import AllocationPolicy, AllocationResult, ResearchAllocator
from idea_machine.research_space.search_space import SearchSpace
from idea_machine.research_space.search_space_ledger import SearchSpaceLedger

#: Real per-instrument folder mapping, extended by the same three files
#: Cycle 13 confirmed present (see discovery/cycle13_idea_machine_live.py's
#: module docstring for the underlying data-root check).
_FX_FOLDERS = {
    "EURUSD": "EUR_USD", "GBPUSD": "GBP_USD", "XAUUSD": "XAU_USD",
    "USDCAD": "USD_CAD", "AUDUSD": "AUD_USD", "EURJPY": "EUR_JPY",
}
_DRIVER_FOLDERS = {
    "WTICO": "WTICO_USD", "SPX500": "SPX500_USD", "US10Y": "USB10Y_USD", "NAS100": "NAS100_USD",
    "UK10YB": "UK10YB_GBP", "USB02Y": "USB02Y_USD", "DE10YB": "DE10YB_EUR",
    "JP225": "JP225_USD", "UK100": "UK100_GBP", "AU200": "AU200_AUD",
    "US2000": "US2000_USD", "NATGAS": "NATGAS_USD",
}


def data_available(instrument: str, driver: Optional[str]) -> bool:
    """Real filesystem check -- never assumed, mirrors Cycle 13's own discipline."""
    instr_folder = _FX_FOLDERS.get(instrument)
    if instr_folder is None or not (FX_M1_ROOT / instr_folder).is_dir():
        if instrument in ("USDJPY", "USDCHF"):
            pass  # H1-only, real dev-data fallback exists elsewhere in the Factory
        else:
            return False
    if driver:
        driver_folder = _DRIVER_FOLDERS.get(driver)
        if driver_folder is None or not (FX_M1_ROOT / driver_folder).is_dir():
            return False
    return True


def cost_registered(instrument: str) -> bool:
    return instrument in cost_table()


@dataclass(frozen=True)
class CandidateDecision:
    candidate: ResearchCandidate
    accepted: bool
    score: float
    breakdown: Dict
    decision_record_id: str
    reason: str


@dataclass(frozen=True)
class CycleDecisionReport:
    cycle_id: str
    allocation: AllocationResult
    debt: ExplorationDebtState
    decisions: Tuple[CandidateDecision, ...]
    accepted: Tuple[ResearchCandidate, ...]
    rejected: Tuple[CandidateDecision, ...]
    novelty_saturation: str
    closure_proposals: Tuple[Dict, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict:
        return {
            "cycle_id": self.cycle_id,
            "allocation": self.allocation.to_dict(),
            "exploration_debt": self.debt.to_dict(),
            "novelty_saturation": self.novelty_saturation,
            "decisions": [
                {"candidate": d.candidate.to_dict(), "accepted": d.accepted, "score": d.score,
                 "breakdown": d.breakdown, "decision_record_id": d.decision_record_id, "reason": d.reason}
                for d in self.decisions
            ],
            "accepted_candidate_ids": [c.candidate_id for c in self.accepted],
            "closure_proposals": list(self.closure_proposals),
        }


class ResearchSpaceDecisionEngine:
    """The Phase 9 orchestrator: one autonomous-cycle decision, end to end."""

    def __init__(
        self,
        search_space: SearchSpace,
        *,
        allocator: Optional[ResearchAllocator] = None,
        scorer: Optional[InformationGainScorer] = None,
        novelty_tracker: Optional[NoveltyBudgetTracker] = None,
        debt_tracker: Optional[ExplorationDebtTracker] = None,
        decision_ledger: Optional[DecisionLedger] = None,
        space_ledger: Optional[SearchSpaceLedger] = None,
    ) -> None:
        self.search_space = search_space
        self.allocator = allocator or ResearchAllocator()
        self.scorer = scorer or InformationGainScorer(search_space)
        self.novelty_tracker = novelty_tracker or NoveltyBudgetTracker()
        self.debt_tracker = debt_tracker or ExplorationDebtTracker()
        self.decision_ledger = decision_ledger or DecisionLedger()
        self.space_ledger = space_ledger or SearchSpaceLedger()

    def run_cycle(
        self,
        *,
        cycle_id: str,
        candidate_pool: Sequence[ResearchCandidate],
        history: Sequence = (),
        total_slots: Optional[int] = None,
    ) -> CycleDecisionReport:
        debt = self.debt_tracker.compute(list(history))
        total_slots = total_slots if total_slots is not None else len(candidate_pool)
        allocation = self.allocator.allocate_slots(total_slots, debt)

        # Respect the mode allocation: keep at most `slots_by_mode[mode]`
        # candidates per mode, ranked by score within the mode, computed below.
        scored: List[Tuple[ResearchCandidate, float, Dict]] = []
        for cand in candidate_pool:
            avail = data_available(cand.instrument, cand.driver)
            cost_ok = cost_registered(cand.instrument)
            breakdown = self.scorer.score(
                cand, data_available=avail, cost_registered=cost_ok,
                discriminates_competing_hypotheses=bool(cand.competing_hypotheses),
            )
            scored.append((cand, breakdown.total, breakdown.to_dict()))

        by_mode: Dict[str, List[Tuple[ResearchCandidate, float, Dict]]] = {EXPLOIT: [], EXPLORE: [], RECOMBINE: []}
        for cand, score, breakdown in scored:
            by_mode[cand.research_mode].append((cand, score, breakdown))
        for mode in by_mode:
            by_mode[mode].sort(key=lambda t: (-t[1], t[0].candidate_id))

        decisions: List[CandidateDecision] = []
        accepted: List[ResearchCandidate] = []
        selected_for_novelty: List[ResearchCandidate] = []

        for mode, slots in allocation.slots_by_mode.items():
            pool = by_mode[mode]
            chosen = pool[:slots]
            not_chosen = pool[slots:]
            for cand, score, breakdown in chosen:
                selected_for_novelty.append(cand)

            for cand, score, breakdown in chosen + not_chosen:
                will_accept = (cand, score, breakdown) in chosen
                # BLOCKED cost -> never accepted, regardless of slot availability.
                if not cost_registered(cand.instrument):
                    will_accept = False
                    if (cand, score, breakdown) in chosen:
                        chosen.remove((cand, score, breakdown))
                reason = self._reason_for(cand, score, breakdown, will_accept, mode, slots, len(pool))
                record = DecisionRecord(
                    cycle_id=cycle_id, decision=("ACCEPT" if will_accept else "REJECT"),
                    target=cand.candidate_id, reason=reason,
                    evidence=[cand.rationale], alternatives_considered=[c.candidate_id for c, _, _ in pool if c.candidate_id != cand.candidate_id][:5],
                    score_breakdown=breakdown,
                    confidence=("HIGH" if score >= 30 else "MEDIUM" if score >= 10 else "LOW"),
                    reversible=True,
                )
                self.decision_ledger.record(record)
                self.space_ledger.record(
                    cycle_id=cycle_id, research_mode=mode, family=f"{cand.mechanism}/{cand.instrument}",
                    hypothesis=cand.candidate_id, decision=("ACCEPT" if will_accept else "REJECT"),
                    reason=reason, score_breakdown=breakdown, information_gain=breakdown.get("information_gain", 0.0),
                    touched_new_family_or_dimension=(cand.novelty_tag == "NEW"),
                )
                decision = CandidateDecision(cand, will_accept, score, breakdown, record.decision_id, reason)
                decisions.append(decision)
                if will_accept:
                    accepted.append(cand)

        accepted, dropped_family_notes = self.allocator.enforce_family_cap(accepted)
        accepted_ids = {c.candidate_id for c in accepted}
        decisions = [d if d.candidate.candidate_id in accepted_ids or not d.accepted
                    else CandidateDecision(d.candidate, False, d.score, d.breakdown, d.decision_record_id,
                                          d.reason + "; " + "; ".join(dropped_family_notes))
                    for d in decisions]

        novelty_report = self.novelty_tracker.classify(accepted) if accepted else None
        saturation = novelty_report.saturation if novelty_report else "LOW"

        closures = self.propose_closures()

        return CycleDecisionReport(
            cycle_id=cycle_id, allocation=allocation, debt=debt, decisions=tuple(decisions),
            accepted=tuple(accepted), rejected=tuple(d for d in decisions if not d.accepted),
            novelty_saturation=saturation, closure_proposals=tuple(closures),
        )

    #: Dimensions where a REFUTED cell means ONE coherent thing was refuted
    #: (a real family_id maps 1:1 to a research_family_registry.json entry).
    #: Instrument/driver/mechanism cells are deliberately EXCLUDED: those are
    #: coarse rollups over many unrelated triples (an instrument can carry
    #: REFUTED evidence from one narrow hypothesis while a dozen OTHER
    #: triples on that same instrument are merely underpowered), so proposing
    #: to close "the instrument" from that rollup would overstate the real
    #: evidence -- exactly the bug found live in Cycle 14's first run
    #: (see PHASE9_DECISION_AUDIT.md item 4/9), just in this consumer instead
    #: of ExploitationEngine.
    CLOSURE_ELIGIBLE_DIMENSIONS = frozenset({"combinations"})

    def propose_closures(self) -> List[Dict]:
        """Spec item 15: advisory-only branch-closure proposals.

        This engine NEVER marks a family REFUTED itself -- it only surfaces
        cells the search space already shows as REFUTED with multiple
        independent evidence entries, for a human/Factory governance layer to
        act on. ``guard.require("PROPOSE_BRANCH_CLOSURE", ...)`` records the
        proposal in the governance audit trail; it grants no authority.
        """
        proposals: List[Dict] = []
        for cell in self.search_space.by_status(epistemic.REFUTED):
            if cell.dimension not in self.CLOSURE_ELIGIBLE_DIMENSIONS:
                continue
            if len(cell.evidence) >= 2:
                guard.require("PROPOSE_BRANCH_CLOSURE", dimension=cell.dimension, value=cell.value)
                proposals.append({
                    "dimension": cell.dimension, "value": cell.value,
                    "proposal": "BRANCH_CLOSED",
                    "evidence_count": len(cell.evidence),
                    "evidence": list(cell.evidence),
                    "authority": "Factory governance decides; this is a proposal only, not a closure",
                })
        return proposals

    @staticmethod
    def _reason_for(cand: ResearchCandidate, score: float, breakdown: Dict, accepted: bool,
                    mode: str, slots: int, pool_size: int) -> str:
        available = min(slots, pool_size)
        if not accepted:
            return (f"score {score} ranked outside the top {available} of {pool_size} {mode} "
                   f"candidates this cycle (allocator gave {mode} {slots} slot(s); breakdown: {breakdown})")
        return (f"score {score} ranked within the top {available} of {pool_size} {mode} candidates "
               f"({cand.mutation_operator}: {cand.rationale})")
