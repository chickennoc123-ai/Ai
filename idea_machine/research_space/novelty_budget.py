"""Novelty budget: three levels, tracked separately (Phase 9, spec item 7).

LEVEL 1  parameter novelty        RSI(14) vs RSI(15) -- same mechanism, new number
LEVEL 2  mechanism variation      surprise-confirmation vs delayed-reaction -- new logic, same family
LEVEL 3  new mechanism family     cross-asset divergence appearing for the first time

RSI(14)/RSI(15)/RSI(16) must never be counted as three discoveries. This
module groups candidates into PARAMETER_FAMILY buckets by their (mechanism,
instrument, driver) signature and only counts the family once toward
mechanism/family-level novelty; the remaining members of the bucket count
only toward parameter-level novelty.

If a batch is dominated by parameter-only variation, saturation is reported
so the allocator can redirect budget toward mechanism-level exploration
(spec: "engine phải chuyển budget sang mechanism exploration").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from idea_machine.governance import guard
from idea_machine.research_space.information_gain import ResearchCandidate

LEVEL_PARAMETER = "LEVEL_1_PARAMETER"
LEVEL_MECHANISM_VARIATION = "LEVEL_2_MECHANISM_VARIATION"
LEVEL_NEW_FAMILY = "LEVEL_3_NEW_MECHANISM_FAMILY"

#: Above this fraction of a batch being parameter-only, saturation triggers.
SATURATION_THRESHOLD = 0.60


@dataclass(frozen=True)
class NoveltyLevelTag:
    candidate_id: str
    level: str
    parameter_family: str          # groups RSI(14)/RSI(15)/RSI(16) together
    reason: str

    def to_dict(self) -> Dict:
        return {
            "candidate_id": self.candidate_id,
            "level": self.level,
            "parameter_family": self.parameter_family,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class NoveltyBudgetReport:
    tags: Tuple[NoveltyLevelTag, ...]
    level_counts: Dict[str, int]
    distinct_parameter_families: int
    parameter_only_share: float
    saturation: str  # "LOW" | "MEDIUM" | "HIGH"

    def to_dict(self) -> Dict:
        return {
            "tags": [t.to_dict() for t in self.tags],
            "level_counts": dict(self.level_counts),
            "distinct_parameter_families": self.distinct_parameter_families,
            "parameter_only_share": self.parameter_only_share,
            "saturation": self.saturation,
        }


class NoveltyBudgetTracker:
    """Groups a batch of candidates into parameter families and levels."""

    def __init__(self, saturation_threshold: float = SATURATION_THRESHOLD) -> None:
        self.saturation_threshold = saturation_threshold

    def classify(self, candidates: Sequence[ResearchCandidate]) -> NoveltyBudgetReport:  # noqa: F821
        guard.require("SCORE_RESEARCH_VALUE", detail="novelty budget classification")

        # Group by (mechanism, instrument, driver): same mechanism+pair,
        # different windows/thresholds/delays is exactly the RSI(14/15/16) case.
        buckets: Dict[Tuple[str, str, str], List["ResearchCandidate"]] = {}  # noqa: F821
        for c in candidates:
            key = (c.mechanism, c.instrument, c.driver or "")
            buckets.setdefault(key, []).append(c)

        tags: List[NoveltyLevelTag] = []
        for key, members in sorted(buckets.items()):
            family_name = f"{key[0]}::{key[1]}::{key[2] or 'NONE'}"
            # First member of a parameter family carries the family's real
            # novelty level (mechanism-variation or new-family, decided by the
            # caller via candidate.novelty_level); every OTHER member sharing
            # the same (mechanism, instrument, driver) is parameter-only,
            # regardless of what it claims -- this is the anti-overfitting
            # rule from spec item 21, enforced structurally, not by request.
            ordered = sorted(members, key=lambda c: c.candidate_id)
            for i, cand in enumerate(ordered):
                if i == 0:
                    level = cand.novelty_level
                    reason = f"first of {len(ordered)} in parameter family {family_name}"
                else:
                    level = LEVEL_PARAMETER
                    reason = (f"{i+1}/{len(ordered)} in parameter family {family_name} -- "
                             f"same mechanism+instrument+driver as an earlier candidate this batch, "
                             f"differs only by parameter (window/threshold/delay)")
                tags.append(NoveltyLevelTag(cand.candidate_id, level, family_name, reason))

        level_counts: Dict[str, int] = {}
        for t in tags:
            level_counts[t.level] = level_counts.get(t.level, 0) + 1

        total = len(tags) or 1
        parameter_only_share = round(level_counts.get(LEVEL_PARAMETER, 0) / total, 4)
        if parameter_only_share >= self.saturation_threshold:
            saturation = "HIGH"
        elif parameter_only_share >= self.saturation_threshold / 2:
            saturation = "MEDIUM"
        else:
            saturation = "LOW"

        return NoveltyBudgetReport(
            tags=tuple(tags), level_counts=level_counts,
            distinct_parameter_families=len(buckets),
            parameter_only_share=parameter_only_share, saturation=saturation,
        )
