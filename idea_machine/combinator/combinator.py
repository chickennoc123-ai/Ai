"""Combination Engine (Phase 4) — new mechanisms out of known concepts.

This is where genuinely new ideas come from: ``NFP surprise`` + ``US10Y
reaction`` + ``gold reaction`` + ``volatility regime`` is not any one of its
parts. But the roadmap is emphatic that this must not become random
brute-force combination, so every combination here must clear four bars:

1. **Graph support** — the added concept must be linked, in the knowledge base,
   to something already in the base idea. Combining two concepts nobody has
   ever discussed together is not a hypothesis, it is a cartesian product.
2. **A compositional mechanism** — the strategy must be able to say why the
   *conjunction* is more than the parts. If the added leg does not change the
   economic story, the combination is rejected as ``NO_COMPOSITIONAL_GAIN``.
3. **A new falsification condition** — specifically, one that could fail even
   if the base idea is true. Otherwise the combination is untestable as a
   distinct claim.
4. **A new data requirement** — a combination that needs no extra data is
   usually a re-description of the base idea.

Depth is capped: a combination may not be built on another combination beyond
:data:`MAX_DEPTH`, because that is exactly how a search space explodes into
noise that no multiple-testing correction can survive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from idea_machine.core.errors import SpecValidationError
from idea_machine.core.ids import content_hash
from idea_machine.core.idea_spec import ExpectedEffect, IdeaSpec, deduplicate
from idea_machine.core.provenance import Provenance
from idea_machine.governance import guard
from idea_machine.knowledge.base import KnowledgeBase
from idea_machine.knowledge.taxonomy import (
    RATE_SERIES,
    STATE_VARIABLE,
    TRADABLE_ASSET,
    VOL_MEASURE,
    is_bindable,
    kind_of,
)
from utils.helpers import isoformat

#: A combination of combinations of combinations is not an idea, it is a
#: fishing expedition. Depth 1 means "one composition on top of a base idea".
MAX_DEPTH = 1

#: Combinations attempted per base idea, before novelty/economics screening.
DEFAULT_MAX_PER_IDEA = 6


@dataclass(frozen=True)
class CombinationStrategy:
    """One *way* of composing an extra concept onto a base idea."""

    name: str
    added_kinds: Tuple[str, ...]
    mechanism_suffix: str
    hypothesis_suffix: str
    falsification: str
    rationale_suffix: str
    data_requirement: str
    entry_patch: Mapping[str, Any] = field(default_factory=dict)
    #: Multiplier applied to the base idea's expected effect. Conditioning on a
    #: state usually *raises* per-trade effect while cutting sample size; the
    #: sample-size cost is charged later, by the power check.
    effect_multiplier: float = 1.0


STRATEGIES: Tuple[CombinationStrategy, ...] = (
    CombinationStrategy(
        name="REGIME_CONDITIONING",
        added_kinds=(STATE_VARIABLE, VOL_MEASURE),
        mechanism_suffix=(
            " The transmission is not constant: {added} measures the risk-bearing capacity available "
            "to absorb the flow, and when that capacity is scarce the same information produces a "
            "larger price move, so the effect should concentrate in the elevated {added} state."
        ),
        hypothesis_suffix=" This effect is materially larger when {added} is elevated.",
        falsification=(
            "The effect is the same size in both {added} states -- i.e. the interaction term adds "
            "nothing over the unconditional effect. This can fail even if the base effect is real."
        ),
        rationale_suffix=(
            " Risk-bearing capacity, which {added} proxies, determines the compensation demanded for "
            "absorbing flow."
        ),
        data_requirement="conditioner_series:{added}",
        entry_patch={"regime_gate": "{added}_elevated"},
        effect_multiplier=1.4,
    ),
    CombinationStrategy(
        name="CROSS_ASSET_CONFIRMATION",
        added_kinds=(TRADABLE_ASSET, RATE_SERIES),
        mechanism_suffix=(
            " {added} is driven by the same underlying state but traded by a partly different set of "
            "participants; requiring {added} to move consistently filters out moves caused by "
            "instrument-specific liquidity noise rather than by the shared driver."
        ),
        hypothesis_suffix=" The effect is stronger when {added} moves consistently with it.",
        falsification=(
            "Requiring agreement with {added} does not improve the signal beyond what the reduced "
            "sample size would produce by chance -- the confirmation adds no information."
        ),
        rationale_suffix=(
            " Two segmented markets responding to one driver give an independent read on whether the "
            "driver, rather than local noise, is what moved price."
        ),
        data_requirement="confirmation_series:{added}",
        entry_patch={"confirmation": {"series": "{added}", "require": "same_sign"}},
        effect_multiplier=1.25,
    ),
    CombinationStrategy(
        name="SEQUENTIAL_TRANSMISSION",
        added_kinds=(RATE_SERIES, TRADABLE_ASSET),
        mechanism_suffix=(
            " Transmission is sequential rather than simultaneous: the driver reprices {added} first, "
            "because {added}'s participants are closest to the information, and only then propagates "
            "onward. The {added} reaction is therefore an observable early read on the size of the "
            "move still to come."
        ),
        hypothesis_suffix=" The size of the {added} reaction predicts the size of the subsequent move.",
        falsification=(
            "The magnitude of the {added} reaction carries no information about the subsequent move "
            "once the driver's own magnitude is controlled for."
        ),
        rationale_suffix=(
            " Information reaches segmented markets in a stable order, so the fast market's reaction "
            "is a leading measurement of the shock's size."
        ),
        data_requirement="lead_series:{added}",
        entry_patch={"lead_signal": {"series": "{added}", "measure": "reaction_magnitude"}},
        effect_multiplier=1.15,
    ),
)


@dataclass(frozen=True)
class CombinationRejection:
    base_idea_id: str
    added_concept: str
    strategy: str
    reason: str


@dataclass(frozen=True)
class CombinationResult:
    ideas: Tuple[IdeaSpec, ...]
    rejections: Tuple[CombinationRejection, ...]

    def summary(self) -> Dict[str, Any]:
        by_reason: Dict[str, int] = {}
        for r in self.rejections:
            by_reason[r.reason] = by_reason.get(r.reason, 0) + 1
        return {
            "combined": len(self.ideas),
            "rejected": len(self.rejections),
            "rejection_reasons": dict(sorted(by_reason.items())),
        }


class CombinationEngine:
    """Composes extra legs onto base ideas, under the four bars above."""

    def __init__(
        self,
        knowledge: KnowledgeBase,
        *,
        strategies: Sequence[CombinationStrategy] = STRATEGIES,
        max_per_idea: int = DEFAULT_MAX_PER_IDEA,
        clock=isoformat,
    ) -> None:
        self.knowledge = knowledge
        self.strategies = tuple(strategies)
        self.max_per_idea = max_per_idea
        self._clock = clock

    def combine(self, base_ideas: Sequence[IdeaSpec]) -> CombinationResult:
        guard.require("COMBINE_CONCEPTS", base_count=len(base_ideas))
        produced: List[IdeaSpec] = []
        rejections: List[CombinationRejection] = []
        concepts = tuple(sorted(c for c in self.knowledge.concepts() if is_bindable(c)))

        for base in sorted(base_ideas, key=lambda i: i.idea_id):
            depth = int(base.entry.get("combination_depth", 0) or 0)
            if depth >= MAX_DEPTH:
                rejections.append(
                    CombinationRejection(base.idea_id, "", "*", "max_depth_reached")
                )
                continue

            made = 0
            for strategy in sorted(self.strategies, key=lambda s: s.name):
                for added in concepts:
                    if made >= self.max_per_idea:
                        break
                    verdict = self._screen(base, added, strategy)
                    if verdict is not None:
                        rejections.append(CombinationRejection(base.idea_id, added, strategy.name, verdict))
                        continue
                    try:
                        produced.append(self._build(base, added, strategy, depth))
                        made += 1
                    except SpecValidationError as exc:
                        rejections.append(
                            CombinationRejection(base.idea_id, added, strategy.name, f"spec_rejected: {exc.message}")
                        )

        return CombinationResult(deduplicate(produced), tuple(rejections))

    # --------------------------------------------------------------- screening

    def _screen(self, base: IdeaSpec, added: str, strategy: CombinationStrategy) -> Optional[str]:
        """Return a rejection reason, or ``None`` if the combination is allowed."""
        if kind_of(added) not in strategy.added_kinds:
            return "wrong_kind_for_strategy"

        bindings = dict(base.entry.get("bindings", {}))
        base_concepts = {str(v) for v in bindings.values()}
        if added in base_concepts:
            return "already_in_base_idea"

        # Bar 1: graph support. The added concept must be connected to the base.
        if not self._linked(added, base_concepts):
            return "no_graph_support"

        # Bar 4: the leg must actually require data the base idea did not need.
        new_requirement = strategy.data_requirement.format(added=added)
        if new_requirement in base.required_data:
            return "no_new_data_requirement"

        # Bar 2: compositional gain. Conditioning an already-conditioned idea on
        # a second state variable does not tell a new economic story -- it just
        # slices the sample again, which is what the power check exists to
        # punish. One conditioner per idea.
        if strategy.name == "REGIME_CONDITIONING" and "conditioner" in bindings:
            return "already_conditioned"

        # A confirmation leg on an instrument the base idea already trades tells
        # you nothing you did not already see.
        if strategy.name == "CROSS_ASSET_CONFIRMATION":
            from idea_machine.generator.generator import CONCEPT_INSTRUMENTS

            if set(CONCEPT_INSTRUMENTS.get(added, ())) & set(base.instruments):
                return "no_compositional_gain"
        return None

    def _linked(self, added: str, base_concepts: set) -> bool:
        for relation, other, _direction in self.knowledge.neighbours(added):
            if other in base_concepts:
                return True
        added_sources = set(self.knowledge.source_ids_for(added))
        for concept in base_concepts:
            if added_sources & set(self.knowledge.source_ids_for(concept)):
                return True
        return False

    # ------------------------------------------------------------------ build

    def _build(
        self, base: IdeaSpec, added: str, strategy: CombinationStrategy, depth: int
    ) -> IdeaSpec:
        entry = dict(base.entry)
        entry["bindings"] = {**dict(base.entry.get("bindings", {})), "added": added}
        entry["combination_depth"] = depth + 1
        entry["combination_strategy"] = strategy.name
        for key, value in strategy.entry_patch.items():
            entry[key] = _format_deep(value, added=added)

        required = tuple(sorted(set(base.required_data) | {strategy.data_requirement.format(added=added)}))

        combined_provenance = Provenance(
            origin_kind="COMBINATION",
            origin_ref=f"combine:{strategy.name}:{base.idea_id}:{added}",
            retrieved_at=self._clock(),
            content_hash=content_hash({"base": base.idea_id, "added": added, "s": strategy.name}),
            authority="DERIVED_HYPOTHESIS",
            parents=tuple(sorted(set(base.provenance.parents) | {base.provenance.identity()})),
            note=(
                f"{strategy.name} of {base.idea_id} with {added}; "
                "a composed proposal, still unvalidated"
            ),
        )

        return IdeaSpec(
            family=base.family,
            hypothesis=base.hypothesis + strategy.hypothesis_suffix.format(added=added),
            mechanism=base.mechanism + strategy.mechanism_suffix.format(added=added),
            instruments=base.instruments,
            timeframe=base.timeframe,
            entry=entry,
            exit=dict(base.exit),
            holding_period=base.holding_period,
            required_data=required,
            economic_rationale=base.economic_rationale + strategy.rationale_suffix.format(added=added),
            expected_effect=ExpectedEffect(
                magnitude=round(base.expected_effect.magnitude * strategy.effect_multiplier, 8),
                unit=base.expected_effect.unit,
                direction=base.expected_effect.direction,
                horizon_bars=base.expected_effect.horizon_bars,
                basis=(
                    f"base prior scaled by {strategy.effect_multiplier}x for {strategy.name}; "
                    "conditioning raises per-trade effect but cuts sample size, which the power "
                    "check charges for separately"
                ),
            ),
            falsification_condition=strategy.falsification.format(added=added),
            provenance=combined_provenance,
            created_at=self._clock(),
        )


def _format_deep(value: Any, **kwargs: str) -> Any:
    if isinstance(value, str):
        return value.format(**kwargs)
    if isinstance(value, Mapping):
        return {k: _format_deep(v, **kwargs) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_format_deep(v, **kwargs) for v in value]
    return value
