"""Idea ranking (Phase 8) — research priority, never performance.

The roadmap's constraint is absolute: *"Không dùng backtest performance để
ranking trước experiment."* Ranking happens **before** any experiment runs, so
there is no performance to rank on — and this module has no way to accept one.
:class:`ResearchPriority` takes only the nine research-value inputs the roadmap
lists, and :meth:`IdeaRanker.rank` reads only the IdeaSpec plus the pre-test
verdicts. If a caller passes a backtest result anywhere near this module, the
``IdeaSpec`` contract has already rejected it upstream.

Scores are on 0-100 and each component is documented, because an opaque
priority score is indistinguishable from a preference.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from idea_machine.core.families import horizon_is_plausible
from idea_machine.core.idea_spec import IdeaSpec
from idea_machine.economics.data_feasibility import FeasibilityVerdict
from idea_machine.economics.prefilter import MARGINAL, VIABLE, EconomicVerdict
from idea_machine.governance import guard
from idea_machine.novelty.checker import NOVEL, REVIEW_REQUIRED, NoveltyVerdict

#: Component weights. They sum to 1.0; changing one changes what the machine
#: spends its budget on, so they are stated here rather than buried in code.
WEIGHTS: Mapping[str, float] = {
    "novelty": 0.18,
    "economic_plausibility": 0.18,
    "potential_magnitude": 0.12,
    "data_quality": 0.12,
    "statistical_power_potential": 0.12,
    "cost_feasibility": 0.08,
    "mechanism_clarity": 0.12,
    "distance_from_failed_ideas": 0.05,
    "research_value": 0.03,
}

#: Bars needed before a per-trade effect of a given size is detectable at all.
#: A crude power heuristic: required n scales with 1/effect^2.
_POWER_REFERENCE_EFFECT = 0.0005
_POWER_REFERENCE_N = 500


@dataclass(frozen=True)
class ResearchPriority:
    """The nine Phase 8 inputs, each in ``[0, 1]``, plus the weighted total."""

    idea_id: str
    novelty: float
    economic_plausibility: float
    potential_magnitude: float
    data_quality: float
    statistical_power_potential: float
    cost_feasibility: float
    mechanism_clarity: float
    distance_from_failed_ideas: float
    research_value: float
    score: float = 0.0
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["notes"] = list(self.notes)
        d["score"] = round(self.score, 2)
        return d


class IdeaRanker:
    """Scores ideas on how much *information* testing them would produce."""

    def __init__(self, *, weights: Mapping[str, float] = WEIGHTS, family_failure_counts: Optional[Mapping[str, int]] = None) -> None:
        total = sum(weights.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"ranking weights must sum to 1.0, got {total}")
        self.weights = dict(weights)
        self.family_failure_counts = dict(family_failure_counts or {})

    def score(
        self,
        idea: IdeaSpec,
        *,
        novelty: NoveltyVerdict,
        feasibility: FeasibilityVerdict,
        economics: EconomicVerdict,
    ) -> ResearchPriority:
        guard.require("RANK_IDEAS", idea_id=idea.idea_id)
        notes: List[str] = []

        novelty_score = {NOVEL: 1.0, REVIEW_REQUIRED: 0.45}.get(novelty.verdict, 0.0)
        if novelty.reopened_from:
            notes.append(f"reopened: {novelty.reopened_from}")

        econ_score = {VIABLE: 1.0, MARGINAL: 0.4}.get(economics.verdict, 0.0)

        # Magnitude: how far above cost, saturating at 5x. More is better, but
        # a claimed 50x effect is a reason for suspicion, not enthusiasm.
        ratio = economics.effect_vs_cost
        magnitude = min(ratio / 5.0, 1.0) if ratio > 0 else 0.0
        if ratio > 10:
            magnitude = 0.5
            notes.append(
                f"claimed effect is {ratio:.1f}x cost -- implausibly large for a public "
                "mechanism; treated with suspicion rather than rewarded"
            )

        data_quality = self._data_quality(feasibility, notes)
        power = self._power_potential(idea, feasibility, notes)
        cost_feasibility = min(ratio / 3.0, 1.0) if ratio > 0 else 0.0
        clarity = self._mechanism_clarity(idea)
        distance = self._distance_from_failures(idea, notes)
        research_value = self._research_value(idea, novelty)

        components = {
            "novelty": novelty_score,
            "economic_plausibility": econ_score,
            "potential_magnitude": magnitude,
            "data_quality": data_quality,
            "statistical_power_potential": power,
            "cost_feasibility": cost_feasibility,
            "mechanism_clarity": clarity,
            "distance_from_failed_ideas": distance,
            "research_value": research_value,
        }
        total = sum(self.weights[k] * v for k, v in components.items()) * 100.0

        return ResearchPriority(
            idea_id=idea.idea_id,
            score=total,
            notes=tuple(notes),
            **components,
        )

    # ------------------------------------------------------------ components

    def _data_quality(self, feasibility: FeasibilityVerdict, notes: List[str]) -> float:
        if not feasibility.may_proceed:
            return 0.0
        rows = feasibility.min_rows
        if rows >= 20_000:
            return 1.0
        if rows >= 5_000:
            return 0.75
        if rows >= 2_000:
            notes.append(f"only {rows} usable rows -- adequate but not comfortable")
            return 0.45
        return 0.2

    def _power_potential(self, idea: IdeaSpec, feasibility: FeasibilityVerdict, notes: List[str]) -> float:
        """Could a sample this size ever resolve an effect this small?

        A crude 1/effect^2 scaling, deliberately conservative. Its job is to
        stop the machine spending slots on experiments that were arithmetically
        incapable of producing an answer — the exact situation that generates
        UNDERPOWERED verdicts and burns budget for no information.
        """
        effect = idea.expected_effect.magnitude
        if effect <= 0:
            return 0.0
        required = _POWER_REFERENCE_N * (_POWER_REFERENCE_EFFECT / effect) ** 2
        available = max(feasibility.min_rows, 0)
        if available <= 0:
            return 0.0
        # Conditioning gates cut the usable sample; charge for that here.
        gates = sum(1 for k in idea.entry if k in ("regime_gate", "confirmation", "gate"))
        effective = available / (3.0 ** gates)
        if gates:
            notes.append(f"{gates} conditioning gate(s) cut the effective sample to ~{effective:.0f} rows")
        if required <= 0:
            return 1.0
        ratio = effective / required
        if ratio >= 10:
            return 1.0
        if ratio >= 3:
            return 0.75
        if ratio >= 1:
            return 0.5
        notes.append(
            f"sample may be too small: ~{effective:.0f} usable rows against ~{required:.0f} needed "
            "for an effect this size"
        )
        return 0.15

    def _mechanism_clarity(self, idea: IdeaSpec) -> float:
        """Longer is not clearer, but a mechanism must name a cause and a party."""
        text = idea.mechanism.lower()
        words = len(text.split())
        score = 0.3 if words >= 15 else 0.1
        # Does it name WHO is on the other side, and WHY they act?
        if any(w in text for w in ("dealer", "participant", "investor", "hedger", "institution", "provider", "trader")):
            score += 0.25
        if any(w in text for w in ("because", "so that", "since", "therefore", "as a result")):
            score += 0.2
        if any(w in text for w in ("risk", "constraint", "mandate", "capacity", "inventory", "premium")):
            score += 0.25
        if not horizon_is_plausible(idea.family, idea.holding_period):
            score *= 0.5
        return min(score, 1.0)

    def _distance_from_failures(self, idea: IdeaSpec, notes: List[str]) -> float:
        """Families that keep failing get less of the budget, not none of it.

        Only *counts* are used — never performance numbers — so holdout results
        cannot steer research targeting through this channel.
        """
        count = self.family_failure_counts.get(idea.family, 0)
        if count == 0:
            return 1.0
        if count >= 10:
            notes.append(f"family {idea.family} has {count} recorded refutations")
            return 0.1
        return max(0.1, 1.0 - count / 10.0)

    def _research_value(self, idea: IdeaSpec, novelty: NoveltyVerdict) -> float:
        """What do we learn if the answer is NO?

        An idea whose falsification is sharp teaches something either way; one
        whose falsification is vague teaches nothing when it fails.
        """
        falsification_words = len(idea.falsification_condition.split())
        sharp = 0.6 if falsification_words >= 12 else 0.3
        if novelty.verdict == NOVEL:
            sharp += 0.4
        return min(sharp, 1.0)

    # ----------------------------------------------------------------- rank

    def rank(
        self,
        ideas: Sequence[IdeaSpec],
        *,
        novelty: Mapping[str, NoveltyVerdict],
        feasibility: Mapping[str, FeasibilityVerdict],
        economics: Mapping[str, EconomicVerdict],
        top_n: Optional[int] = None,
    ) -> Tuple[Tuple[IdeaSpec, ResearchPriority], ...]:
        """Return ideas ordered by research priority, highest first.

        Ties break on ``idea_id`` so the ordering is total and reproducible.
        """
        scored: List[Tuple[IdeaSpec, ResearchPriority]] = []
        for idea in ideas:
            n, f, e = novelty.get(idea.idea_id), feasibility.get(idea.idea_id), economics.get(idea.idea_id)
            if n is None or f is None or e is None:
                continue
            scored.append((idea, self.score(idea, novelty=n, feasibility=f, economics=e)))

        scored.sort(key=lambda pair: (-pair[1].score, pair[0].idea_id))
        return tuple(scored[:top_n] if top_n is not None else scored)
