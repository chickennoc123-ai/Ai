"""Refuted-family memory + related-hypothesis similarity — Generation 5,
Phases 3-4.

**Phase 3** answers "has this hypothesis family already been tested and
refuted?" **Phase 4** classifies how similar a candidate hypothesis is to
existing ones, so a minor parameter change is penalized relative to a
genuinely new mechanism (Principle 9-10: do not generate large parameter
grids, or repeatedly test minor variants of a refuted family, as a
substitute for research).

**Why this module does not rely solely on ``core.factory.novelty_engine.
FamilyRegistry`` membership.** That registry buckets by an EXACT
number-stripped mechanism-text hash. A real gap this module found while
auditing the Factory's own data: ``HYP-000001`` ("rsi_14 < 30 (source's
oversold threshold) => ...") and ``HYP-000002`` ("rsi_14 < 30 => ...",
its own 24-bar-horizon synthesis) differ only by a parenthetical aside,
which is enough non-numeric text to land them in *different* families
(``FAMILY-000001`` vs ``FAMILY-000002``) despite being the same mechanism
at a different horizon. Token-Jaccard similarity (already built in
``novelty_engine``, just not previously applied pairwise across all
hypotheses) catches this: 0.667 overlap, correctly classified below as
``CLOSE_VARIANT``. Exact family-signature membership is therefore treated
here as necessary but not sufficient -- every new hypothesis is compared
against every existing one, not only members of its own formal family.

Thresholds are declared once, below, before any similarity is computed --
a fixed, transparent, auditable classification, never an AI model's bare
assertion of "novel" (Principle: no such assertion may go unevidenced).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.factory.novelty_engine import FamilyRegistry, is_exact_duplicate, token_jaccard
from utils.exceptions import EAFactoryError

#: Declared before any similarity is computed. CLOSE_VARIANT's floor is
#: deliberately below is_same_mechanism's implicit 1.0-after-stripping
#: bar, because is_same_mechanism only catches identical text after
#: number-stripping -- a parenthetical aside (the HYP-001/002 case above)
#: needs the softer Jaccard floor to be caught at all.
SIMILARITY_THRESHOLDS = {
    "CLOSE_VARIANT": 0.60,
    "RELATED_FAMILY": 0.30,
    "DISTANT_ANALOG": 0.01,
    # below DISTANT_ANALOG's floor (including exactly 0.0 disjoint vocabulary) -> NOVEL
}

REFUTATION_SCOPES = frozenset(
    {"NOT_REFUTED", "PARTIALLY_TESTED", "REFUTED_UNDER_SPECIFIC_OPERATIONALISATION", "REFUTED_UNIVERSALLY"}
)

#: A family is only ever REFUTED_UNIVERSALLY if a human governance
#: decision explicitly says so (module has no code path that infers it) --
#: see the class docstring below. No family in this Factory currently
#: qualifies; every refutation on record states an instrument/timeframe/
#: horizon/cost-model scope, which is exactly what makes it NOT universal.
UNIVERSAL_REFUTATION_ALLOWLIST: frozenset = frozenset()


class RefutedFamilyMemoryError(EAFactoryError):
    pass


def classify_similarity(text_a: str, text_b: str) -> str:
    """Deterministic, auditable similarity class between two mechanism
    texts (typically ``economic_mechanism`` fields). Never delegates the
    call to an unexplained score."""
    if is_exact_duplicate(text_a, text_b):
        return "EXACT_DUPLICATE"
    j = token_jaccard(text_a, text_b)
    if j >= SIMILARITY_THRESHOLDS["CLOSE_VARIANT"]:
        return "CLOSE_VARIANT"
    if j >= SIMILARITY_THRESHOLDS["RELATED_FAMILY"]:
        return "RELATED_FAMILY"
    if j >= SIMILARITY_THRESHOLDS["DISTANT_ANALOG"]:
        return "DISTANT_ANALOG"
    return "NOVEL"


@dataclass(frozen=True)
class RelatedHypothesis:
    hypothesis_id: str
    similarity_class: str
    jaccard: float
    formalization_status: str
    is_refuted: bool

    def to_dict(self) -> Dict[str, Any]:
        return {"hypothesis_id": self.hypothesis_id, "similarity_class": self.similarity_class,
                "jaccard": self.jaccard, "formalization_status": self.formalization_status,
                "is_refuted": self.is_refuted}


@dataclass(frozen=True)
class HypothesisSimilarityAssessment:
    """Phase 4 output for one (candidate or existing) hypothesis text:
    its relation to every other hypothesis already in the registry."""

    subject_text: str
    related: Tuple[RelatedHypothesis, ...]
    novelty_delta: float  # 1.0 = nothing similar exists; lower = closer to prior art
    related_refuted_hypotheses: Tuple[str, ...]
    priority_penalty_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subject_text": self.subject_text,
            "related": [r.to_dict() for r in self.related],
            "novelty_delta": self.novelty_delta,
            "related_refuted_hypotheses": list(self.related_refuted_hypotheses),
            "priority_penalty_reason": self.priority_penalty_reason,
        }


def assess_similarity_against_registry(
    subject_text: str, *, hypothesis_registry, exclude_hypothesis_id: Optional[str] = None,
) -> HypothesisSimilarityAssessment:
    """Compare ``subject_text`` (an ``economic_mechanism`` string) against
    every hypothesis already on record, refuted or not."""
    related: List[RelatedHypothesis] = []
    for h in hypothesis_registry.list_all():
        if h.hypothesis_id == exclude_hypothesis_id:
            continue
        other_text = h.economic_mechanism
        sim_class = classify_similarity(subject_text, other_text)
        related.append(RelatedHypothesis(
            hypothesis_id=h.hypothesis_id,
            similarity_class=sim_class,
            jaccard=round(token_jaccard(subject_text, other_text), 6),
            formalization_status=h.formalization_status,
            is_refuted=(h.formalization_status == "REFUTED"),
        ))
    related.sort(key=lambda r: -r.jaccard)
    max_jaccard = related[0].jaccard if related else 0.0
    novelty_delta = round(1.0 - max_jaccard, 6)
    refuted_close = [r for r in related if r.is_refuted and r.similarity_class in ("EXACT_DUPLICATE", "CLOSE_VARIANT", "RELATED_FAMILY")]
    if refuted_close:
        worst = refuted_close[0]
        reason = (
            f"{worst.similarity_class} of refuted {worst.hypothesis_id} (jaccard={worst.jaccard}) -- "
            "novelty and priority must reflect this family's known failure, not treat this as fresh "
            "territory (Non-Negotiable Principle 8-10)."
        )
    else:
        reason = "no refuted hypothesis is a close/related match; no penalty applies from this assessment."
    return HypothesisSimilarityAssessment(
        subject_text=subject_text,
        related=tuple(related),
        novelty_delta=novelty_delta,
        related_refuted_hypotheses=tuple(r.hypothesis_id for r in refuted_close),
        priority_penalty_reason=reason,
    )


@dataclass(frozen=True)
class FamilyRefutationRecord:
    family_id: str
    family_kind: str
    members: Tuple[str, ...]
    refuted_members: Tuple[str, ...]
    refutation_scope: str
    tested_operationalisations: Tuple[Dict[str, Any], ...]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family_id": self.family_id, "family_kind": self.family_kind,
            "members": list(self.members), "refuted_members": list(self.refuted_members),
            "refutation_scope": self.refutation_scope,
            "tested_operationalisations": list(self.tested_operationalisations),
            "reason": self.reason,
        }


def compute_family_refutation_status(
    family_id: str, *, family_registry: FamilyRegistry, hypothesis_registry,
) -> FamilyRefutationRecord:
    """Phase 3. A family is REFUTED_UNIVERSALLY **only** if it appears in
    ``UNIVERSAL_REFUTATION_ALLOWLIST`` -- a human governance decision this
    module has no code path to infer on its own (there is no threshold of
    "enough refuted members" that upgrades a scope automatically, because
    that would let volume of testing manufacture a universal claim no
    single test actually supports). Anything else with at least one
    REFUTED member is REFUTED_UNDER_SPECIFIC_OPERATIONALISATION.
    """
    family = family_registry.get(family_id)
    members = family.members
    refuted_members = []
    operationalisations = []
    for member_id in members:
        if not member_id.startswith("HYP-"):
            continue
        try:
            h = hypothesis_registry.get(member_id)
        except Exception:
            continue
        if h.formalization_status == "REFUTED":
            refuted_members.append(member_id)
            operationalisations.append({
                "hypothesis_id": member_id,
                "instrument_scope": h.instrument_scope,
                "target_definition": h.target_definition,
                "holding_period": h.holding_period,
                "cost_assumptions": h.cost_assumptions,
                "regime_conditions": h.regime_conditions,
            })

    if not refuted_members:
        tested_any = any(
            getattr(hypothesis_registry.get(m), "formalization_status", "") in ("TESTED", "SUPPORTED", "REFUTED")
            for m in members if m.startswith("HYP-")
        )
        scope = "PARTIALLY_TESTED" if tested_any else "NOT_REFUTED"
        reason = "no member of this family has been refuted yet"
    elif family_id in UNIVERSAL_REFUTATION_ALLOWLIST:
        scope = "REFUTED_UNIVERSALLY"
        reason = f"family explicitly governance-declared universally refuted: {family_id} in UNIVERSAL_REFUTATION_ALLOWLIST"
    else:
        scope = "REFUTED_UNDER_SPECIFIC_OPERATIONALISATION"
        reason = (
            f"{len(refuted_members)}/{len(members)} member(s) refuted, each for a stated instrument/"
            "horizon/cost-model combination; other operationalisations of this mechanism remain "
            "untested and this scope does NOT extend the refutation to them (post-mortem scope "
            "discipline, ML-001-GENERATION-4-POST-MORTEM.md §5)."
        )

    return FamilyRefutationRecord(
        family_id=family_id, family_kind=family.family_kind, members=members,
        refuted_members=tuple(refuted_members), refutation_scope=scope,
        tested_operationalisations=tuple(operationalisations), reason=reason,
    )


def compute_all_family_refutation_statuses(
    *, family_registry: FamilyRegistry, hypothesis_registry,
) -> List[FamilyRefutationRecord]:
    return [
        compute_family_refutation_status(f.family_id, family_registry=family_registry, hypothesis_registry=hypothesis_registry)
        for f in family_registry.list_all()
        if f.family_kind == "HYPOTHESIS_FAMILY"
    ]
