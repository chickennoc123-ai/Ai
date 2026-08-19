"""Research prioritization + expected information value — Generation 3,
Phases 12-13, 16.

A transparent, decomposable research-scheduling score. **A priority score
is NOT an economic-edge probability** — it ranks what to research next
for information quality and research efficiency, never how likely a
strategy is to make money. There is deliberately no dimension named
anything like "expected profit".

**Knowledge-feedback firewall (Phase 16)**: the only historical inputs
this module accepts are ``ResearchKnowledge`` objects, which carry family
*counts* (how much a family has been researched/failed) and nothing else.
``ResearchKnowledge`` has no field for a return, profit factor,
expectancy, Sharpe, or any performance metric — "this family has been
tested 100 times" can lower novelty; "this family lost money on holdout"
structurally cannot enter, because there is nowhere to put it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict

from utils.exceptions import EAFactoryError

#: The recognized scoring dimensions, each valued in [0, 1].
PRIORITY_DIMENSIONS = (
    "mechanism_plausibility",
    "data_availability",
    "testability",
    "novelty",
    "expected_information_gain",
    "computational_cost_efficiency",  # 1.0 = cheap to test, 0.0 = prohibitively expensive
    "lineage_quality",
    "research_diversity_contribution",
)


class PrioritizationError(EAFactoryError):
    pass


@dataclass(frozen=True)
class ResearchKnowledge:
    """The ONLY sanctioned shape for feeding past research back into
    prioritization: counts of prior activity, per family. Adding a
    performance-metric field to this dataclass would be a governance
    change requiring explicit authorization — see
    ML-001-RESEARCH-PRIORITIZATION-SPEC.md §4."""

    family_prior_test_count: int = 0
    family_prior_failure_count: int = 0
    family_member_count: int = 0

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if not isinstance(value, int) or value < 0:
                raise PrioritizationError(
                    "ResearchKnowledge fields must be non-negative integer COUNTS",
                    field=f.name, value=value,
                )


@dataclass(frozen=True)
class PriorityDimensions:
    mechanism_plausibility: float = 0.5
    data_availability: float = 0.0
    testability: float = 0.0
    novelty: float = 0.5
    expected_information_gain: float = 0.5
    computational_cost_efficiency: float = 0.5
    lineage_quality: float = 0.0
    research_diversity_contribution: float = 0.5

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if not (0.0 <= value <= 1.0):
                raise PrioritizationError("priority dimensions must be in [0, 1]", dimension=f.name, value=value)


@dataclass(frozen=True)
class PriorityScore:
    """The decomposition IS the score: ``total`` is nothing more than the
    unweighted mean of the named dimensions, so any score can be explained
    dimension by dimension. NOT an edge probability."""

    dimensions: Dict[str, float]
    total: float

    def to_dict(self) -> Dict[str, Any]:
        return {"dimensions": dict(self.dimensions), "total": self.total,
                "meaning": "research scheduling priority -- NOT economic edge probability"}


def novelty_from_knowledge(knowledge: ResearchKnowledge) -> float:
    """Deterministic novelty in [0, 1] from prior-activity counts alone:
    an untested family scores 1.0; heavily-tested families decay toward 0.
    Formula: 1 / (1 + prior_tests + prior_failures) — transparent,
    monotone, no tunable hidden constants."""
    return 1.0 / (1.0 + knowledge.family_prior_test_count + knowledge.family_prior_failure_count)


def expected_information_value(
    *, novelty: float, testability: float, computational_cost_efficiency: float
) -> float:
    """Phase 13's EXPECTED_INFORMATION_VALUE: how much a test is likely to
    teach us per unit of effort — high for novel, cleanly-testable, cheap
    hypotheses; low for retreads. Simple transparent mean of the three
    inputs (each already in [0, 1]). A research-efficiency aid, not a
    profit predictor."""
    for name, v in (("novelty", novelty), ("testability", testability),
                    ("computational_cost_efficiency", computational_cost_efficiency)):
        if not (0.0 <= v <= 1.0):
            raise PrioritizationError("information-value inputs must be in [0, 1]", input=name, value=v)
    return (novelty + testability + computational_cost_efficiency) / 3.0


def score_priority(dimensions: PriorityDimensions) -> PriorityScore:
    dims = {f.name: getattr(dimensions, f.name) for f in fields(dimensions)}
    total = sum(dims.values()) / len(dims)
    return PriorityScore(dimensions=dims, total=total)
