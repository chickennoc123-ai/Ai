"""Information gain and the explainable research_value score (Phase 9, spec items 9-11).

Two hard rules this module enforces structurally:

1. No hidden ML model, no opaque neural ranking. Every component is a plain
   arithmetic term computed from real, inspectable inputs, and every score
   comes with its addend-by-addend breakdown attached (never a bare number).
2. ``expected_profit`` is never the sole criterion. ``information_gain`` can
   be high while expected profit is low -- an experiment that discriminates
   between two competing hypotheses is valuable research even if it is not
   expected to be profitable on its own.

``ResearchCandidate`` is the one shared candidate shape produced by all three
engines (exploit/explore/recombine) and consumed by the allocator, the
novelty-budget tracker, and the decision engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from idea_machine.core.ids import mint_id
from idea_machine.governance import guard

EXPLOIT = "EXPLOIT"
EXPLORE = "EXPLORE"
RECOMBINE = "RECOMBINE"
RESEARCH_MODES = (EXPLOIT, EXPLORE, RECOMBINE)

NEW = "NEW"
DERIVED = "DERIVED"
RECOMBINATION = "RECOMBINATION"
NOVELTY_TAGS = (NEW, DERIVED, RECOMBINATION)


@dataclass(frozen=True)
class ResearchCandidate:
    """One proposed hypothesis, tagged with the mutation that produced it.

    Carries no performance field -- this is a proposal, not a result, mirroring
    the same discipline ``idea_machine.core.idea_spec.IdeaSpec`` already
    enforces for the rest of the Idea Machine.
    """

    mechanism: str
    instrument: str
    driver: Optional[str]
    holding_period_min: int
    research_mode: str                      # EXPLOIT | EXPLORE | RECOMBINE
    mutation_operator: str                   # e.g. SWAP_DRIVER, MECHANISM_RECOMBINATION
    parent_candidate_id: str                 # "" if this is a root proposal
    rationale: str
    novelty_level: str                       # LEVEL_1/2/3 tag string (see novelty_budget.py)
    novelty_tag: str                         # NEW | DERIVED | RECOMBINATION
    competing_hypotheses: Tuple[str, ...] = field(default_factory=tuple)
    candidate_id: str = ""

    def __post_init__(self) -> None:
        if self.research_mode not in RESEARCH_MODES:
            raise ValueError(f"unknown research_mode {self.research_mode!r}")
        if self.novelty_tag not in NOVELTY_TAGS:
            raise ValueError(f"unknown novelty_tag {self.novelty_tag!r}")
        if not self.candidate_id:
            cid = mint_id("RSC", {
                "m": self.mechanism, "i": self.instrument, "d": self.driver or "",
                "h": self.holding_period_min, "mode": self.research_mode,
                "op": self.mutation_operator, "parent": self.parent_candidate_id,
            })
            object.__setattr__(self, "candidate_id", cid)

    def to_dict(self) -> Dict:
        return {
            "candidate_id": self.candidate_id,
            "mechanism": self.mechanism,
            "instrument": self.instrument,
            "driver": self.driver,
            "holding_period_min": self.holding_period_min,
            "research_mode": self.research_mode,
            "mutation_operator": self.mutation_operator,
            "parent_candidate_id": self.parent_candidate_id,
            "rationale": self.rationale,
            "novelty_level": self.novelty_level,
            "novelty_tag": self.novelty_tag,
            "competing_hypotheses": list(self.competing_hypotheses),
        }


@dataclass(frozen=True)
class ScoreBreakdown:
    """Every term that made up the final research_value, transparently."""

    information_gain: float
    novelty_value: float
    unexplored_space_value: float
    evidence_gap_value: float
    economic_plausibility: float
    data_feasibility: float
    redundancy_penalty: float
    refuted_similarity_penalty: float
    cost_risk: float

    @property
    def total(self) -> float:
        return round(
            self.information_gain + self.novelty_value + self.unexplored_space_value
            + self.evidence_gap_value + self.economic_plausibility + self.data_feasibility
            - self.redundancy_penalty - self.refuted_similarity_penalty - self.cost_risk,
            3,
        )

    def to_dict(self) -> Dict:
        return {
            "information_gain": self.information_gain,
            "novelty_value": self.novelty_value,
            "unexplored_space_value": self.unexplored_space_value,
            "evidence_gap_value": self.evidence_gap_value,
            "economic_plausibility": self.economic_plausibility,
            "data_feasibility": self.data_feasibility,
            "redundancy_penalty": -self.redundancy_penalty,
            "refuted_similarity_penalty": -self.refuted_similarity_penalty,
            "cost_risk": -self.cost_risk,
            "total": self.total,
        }

    def explain(self) -> str:
        parts = []
        for label, val in (
            ("information_gain", self.information_gain), ("novelty", self.novelty_value),
            ("unexplored_space", self.unexplored_space_value), ("evidence_gap", self.evidence_gap_value),
            ("economic_plausibility", self.economic_plausibility), ("data_feasibility", self.data_feasibility),
        ):
            if val:
                parts.append(f"{label}: +{val}")
        for label, val in (
            ("redundancy", self.redundancy_penalty), ("refuted_similarity", self.refuted_similarity_penalty),
            ("cost_risk", self.cost_risk),
        ):
            if val:
                parts.append(f"{label}: -{val}")
        parts.append(f"TOTAL: {self.total}")
        return "\n".join(parts)


class InformationGainScorer:
    """Deterministic, additive scoring. Never touches expected profit."""

    def __init__(self, search_space) -> None:  # search_space: SearchSpace
        self.search_space = search_space

    def score(
        self,
        candidate: ResearchCandidate,
        *,
        data_available: bool,
        cost_registered: bool,
        discriminates_competing_hypotheses: bool = False,
        redundant_with: Sequence[str] = (),
        refuted_similarity: float = 0.0,
    ) -> ScoreBreakdown:
        guard.require("SCORE_RESEARCH_VALUE", candidate_id=candidate.candidate_id)

        # information_gain: highest for a candidate that would discriminate
        # between two live competing hypotheses (spec item 10/13); otherwise
        # scaled by how unexplored the touched dimensions are, since testing
        # an unexplored region is itself informative regardless of expected
        # profit.
        instr_cell = self.search_space.cell("instruments", candidate.instrument)
        driver_cell = self.search_space.cell("drivers", candidate.driver) if candidate.driver else None
        mech_cell = self.search_space.cell("mechanisms", candidate.mechanism)

        untested_dims = sum(
            1 for c in (instr_cell, driver_cell, mech_cell)
            if c is not None and c.status in ("UNEXPLORED", "UNKNOWN", "BLOCKED")
        )
        information_gain = 8.0 * untested_dims
        if discriminates_competing_hypotheses:
            information_gain += 20.0

        novelty_value = {"NEW": 15.0, "RECOMBINATION": 8.0, "DERIVED": 4.0}[candidate.novelty_tag]

        unexplored_space_value = 10.0 if any(
            c is not None and c.status == "UNEXPLORED" for c in (instr_cell, driver_cell, mech_cell)
        ) else 0.0

        # evidence_gap_value: real signal previously seen but underpowered is
        # exactly the STILL_UNDERPOWERED opportunity-queue case -- worth more
        # research, not less.
        evidence_gap_value = 12.0 if any(
            c is not None and c.status == "UNDERPOWERED" for c in (instr_cell, driver_cell, mech_cell)
        ) else 0.0

        economic_plausibility = 10.0 if candidate.rationale.strip() else 0.0

        data_feasibility = 10.0 if data_available else 0.0
        if not cost_registered:
            data_feasibility = 0.0  # cannot be evaluated at all without a frozen cost

        redundancy_penalty = 5.0 * len(redundant_with)
        refuted_similarity_penalty = 25.0 * refuted_similarity  # refuted_similarity in [0,1]
        cost_risk = 0.0 if cost_registered else 15.0

        return ScoreBreakdown(
            information_gain=round(information_gain, 3),
            novelty_value=round(novelty_value, 3),
            unexplored_space_value=round(unexplored_space_value, 3),
            evidence_gap_value=round(evidence_gap_value, 3),
            economic_plausibility=round(economic_plausibility, 3),
            data_feasibility=round(data_feasibility, 3),
            redundancy_penalty=round(redundancy_penalty, 3),
            refuted_similarity_penalty=round(refuted_similarity_penalty, 3),
            cost_risk=round(cost_risk, 3),
        )


def design_discriminating_experiment(
    hypotheses: Sequence[str], *, instrument: str, driver: Optional[str], mechanism: str,
    holding_period_min: int, mutation_operator: str = "DISCRIMINATING_EXPERIMENT",
) -> ResearchCandidate:
    """Build a candidate explicitly framed to distinguish competing explanations.

    Example (spec item 13): H1 "surprise itself matters" vs H2 "surprise only
    matters under high volatility" vs H3 "liquidity reaction matters" -- one
    experiment, run once, whose result is informative about which hypothesis
    survives regardless of whether it is profitable.
    """
    guard.require("DESIGN_DISCRIMINATING_EXPERIMENT", instrument=instrument, mechanism=mechanism)
    if len(hypotheses) < 2:
        raise ValueError("a discriminating experiment needs at least two competing hypotheses")
    rationale = (
        f"Discriminates between {len(hypotheses)} competing explanations: "
        + " vs ".join(hypotheses)
        + f". Result is informative regardless of expected profit."
    )
    return ResearchCandidate(
        mechanism=mechanism, instrument=instrument, driver=driver,
        holding_period_min=holding_period_min, research_mode=EXPLORE,
        mutation_operator=mutation_operator, parent_candidate_id="",
        rationale=rationale, novelty_level="LEVEL_2_MECHANISM_VARIATION",
        novelty_tag=DERIVED, competing_hypotheses=tuple(hypotheses),
    )
