"""Idea Generator (Phase 3) — knowledge in, falsifiable proposals out.

The generator walks the knowledge graph, binds concepts into mechanism
templates, and emits :class:`~idea_machine.core.idea_spec.IdeaSpec` objects.

Three properties matter more than volume:

* **Mechanism-gated.** A template that cannot fill its roles emits nothing.
  ``IdeaSpec`` itself rejects a mechanism too thin to explain anything, so a
  proposal without a "why" cannot physically reach the queue.
* **Deterministic.** Concepts and templates are iterated in sorted order and
  ideas are content-addressed, so the same knowledge base yields the same
  ideas in the same order, forever.
* **Provenance-preserving.** Every idea's provenance derives from the actual
  sources that mentioned the bound concepts, and can never out-rank them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from idea_machine.core.errors import SpecValidationError
from idea_machine.core.ids import content_hash
from idea_machine.core.idea_spec import ExpectedEffect, IdeaSpec, deduplicate
from idea_machine.core.provenance import Provenance
from idea_machine.generator.templates import TEMPLATES, MechanismTemplate
from idea_machine.governance import guard
from idea_machine.knowledge.base import KnowledgeBase
from idea_machine.knowledge.taxonomy import is_bindable, kind_of
from utils.helpers import isoformat

#: How a concept maps onto a tradable instrument. A concept with no mapping can
#: never be bound as ``target`` -- if you cannot hold it, you cannot test a
#: trading rule on it.
CONCEPT_INSTRUMENTS: Dict[str, Tuple[str, ...]] = {
    "USD": ("EURUSD", "GBPUSD"),
    "GOLD": ("XAUUSD",),
    "EQUITIES": ("US500",),
    "OIL": ("USOIL",),
    "EURUSD": ("EURUSD",),
    "GBPUSD": ("GBPUSD",),
    "XAUUSD": ("XAUUSD",),
}


@dataclass(frozen=True)
class GenerationRejection:
    """Why a candidate binding did not become an idea. Kept for observability."""

    template_id: str
    bindings: Mapping[str, str]
    reason: str


@dataclass(frozen=True)
class GenerationResult:
    ideas: Tuple[IdeaSpec, ...]
    rejections: Tuple[GenerationRejection, ...]

    def summary(self) -> Dict[str, Any]:
        by_family: Dict[str, int] = {}
        for i in self.ideas:
            by_family[i.family] = by_family.get(i.family, 0) + 1
        by_reason: Dict[str, int] = {}
        for r in self.rejections:
            by_reason[r.reason] = by_reason.get(r.reason, 0) + 1
        return {
            "generated": len(self.ideas),
            "rejected": len(self.rejections),
            "by_family": dict(sorted(by_family.items())),
            "rejection_reasons": dict(sorted(by_reason.items())),
        }


class IdeaGenerator:
    """Binds knowledge-graph concepts into mechanism templates."""

    def __init__(
        self,
        knowledge: KnowledgeBase,
        *,
        templates: Sequence[MechanismTemplate] = TEMPLATES,
        clock=isoformat,
        max_ideas: Optional[int] = None,
    ) -> None:
        self.knowledge = knowledge
        self.templates = tuple(templates)
        self._clock = clock
        self.max_ideas = max_ideas

    # ------------------------------------------------------------- generate

    def generate(self) -> GenerationResult:
        guard.require("GENERATE_IDEA", template_count=len(self.templates))
        concepts = set(self.knowledge.concepts())
        ideas: List[IdeaSpec] = []
        rejections: List[GenerationRejection] = []

        for template in sorted(self.templates, key=lambda t: t.template_id):
            for bindings in self._candidate_bindings(template, concepts):
                try:
                    ideas.append(self._build(template, bindings))
                except SpecValidationError as exc:
                    rejections.append(
                        GenerationRejection(template.template_id, bindings, f"spec_rejected: {exc.message}")
                    )
                except KeyError as exc:
                    rejections.append(
                        GenerationRejection(template.template_id, bindings, f"unbound_role: {exc}")
                    )

        unique = deduplicate(ideas)
        if self.max_ideas is not None:
            unique = unique[: self.max_ideas]
        return GenerationResult(tuple(unique), tuple(rejections))

    # ------------------------------------------------------------- bindings

    def _candidate_bindings(
        self, template: MechanismTemplate, concepts: set
    ) -> Tuple[Mapping[str, str], ...]:
        """Every legal role assignment for ``template``, in deterministic order.

        Only concepts the knowledge graph actually contains are considered, and
        the graph is consulted for *support*: a driver/target pair with no
        asserted edge and no shared source is not proposed, because there would
        be nothing behind the mechanism but the template's own wording.
        """
        pools = {
            role: tuple(
                sorted(
                    c
                    for c in concepts
                    if is_bindable(c) and kind_of(c) in template.role_kinds.get(role, ())
                )
            )
            for role in template.roles
        }
        # A target must be something we can actually hold a position in.
        if "target" in pools:
            pools["target"] = tuple(c for c in pools["target"] if c in CONCEPT_INSTRUMENTS)
        if any(not pool for pool in pools.values()):
            return ()

        out: List[Mapping[str, str]] = []
        for driver in pools.get("driver", ("",)):
            for target in pools.get("target", ("",)):
                if driver == target:
                    continue
                if not self._supported(driver, target):
                    continue
                if "conditioner" in template.roles:
                    for cond in pools["conditioner"]:
                        if cond in (driver, target):
                            continue
                        out.append({"driver": driver, "target": target, "conditioner": cond})
                else:
                    out.append({"driver": driver, "target": target})
        return tuple(out)

    def _supported(self, driver: str, target: str) -> bool:
        """Is there anything in the knowledge base linking these two concepts?"""
        for relation, other, _direction in self.knowledge.neighbours(driver):
            if other == target and relation in ("AFFECTS", "PRECEDES", "CO_OCCURS", "CONDITIONS"):
                return True
        # Co-mention in a single source is weaker support, but it is still
        # evidence that somebody discussed them together, which is exactly what
        # an *idea* (not a fact) requires.
        driver_sources = set(self.knowledge.source_ids_for(driver))
        target_sources = set(self.knowledge.source_ids_for(target))
        return bool(driver_sources & target_sources)

    # ---------------------------------------------------------------- build

    def _build(self, template: MechanismTemplate, bindings: Mapping[str, str]) -> IdeaSpec:
        text = template.render(bindings)
        target = bindings["target"]
        instruments = CONCEPT_INSTRUMENTS.get(target)
        if not instruments:
            raise KeyError(f"concept {target!r} has no tradable instrument mapping")

        provenance = self._provenance_for(template, bindings)
        required = tuple(sorted(set(template.required_data) | {f"instrument:{i}" for i in instruments}))

        return IdeaSpec(
            family=template.family,
            hypothesis=text["hypothesis"],
            mechanism=text["mechanism"],
            instruments=instruments,
            timeframe=template.timeframe,
            entry={**dict(template.entry), "bindings": dict(bindings)},
            exit=dict(template.exit),
            holding_period=template.holding_period,
            required_data=required,
            economic_rationale=text["economic_rationale"],
            expected_effect=ExpectedEffect(
                magnitude=template.prior_effect,
                unit=template.effect_unit,
                direction=template.direction,
                horizon_bars=int(template.exit.get("bars", 4) or 4),
                basis=template.effect_basis or "template prior; measured only by the Strategy Factory",
            ),
            falsification_condition=text["falsification"],
            provenance=provenance,
            created_at=self._clock(),
        )

    def _provenance_for(self, template: MechanismTemplate, bindings: Mapping[str, str]) -> Provenance:
        """Derive provenance from the real sources behind the bound concepts."""
        source_ids = self.knowledge.source_ids_for(*sorted(set(bindings.values())))
        return Provenance(
            origin_kind="INTERNAL_DERIVATION",
            origin_ref=f"idea:{template.template_id}:" + content_hash(dict(bindings))[:12],
            retrieved_at=self._clock(),
            content_hash=content_hash({"t": template.template_id, "b": dict(bindings)}),
            # DERIVED_HYPOTHESIS carries the same evidential rank as the
            # IDEA_SOURCE_ONLY material it was reasoned from -- generating an
            # idea about a claim does not make the claim any better supported.
            authority="DERIVED_HYPOTHESIS",
            parents=tuple(source_ids),
            note=(
                f"template {template.template_id} over concepts "
                f"{', '.join(sorted(bindings.values()))}; supported by {len(source_ids)} source(s); "
                "an unvalidated proposal, not evidence"
            ),
        )
