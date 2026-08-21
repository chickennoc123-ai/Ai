"""ResearchAllocator: split the cycle's candidate budget across EXPLOIT/EXPLORE/RECOMBINE.

Enforces the two hard floors from spec item 20:

    minimum_exploration_share  = 0.20   (governance floor, cannot be configured below this)
    maximum_single_family_share = 0.40  (no one family may consume more than this share)
    maximum_parameter_only_share = 0.25 (parameter-only candidates capped)

The exploration floor can only ever be RAISED by exploration debt (spec item
6); it is never silently lowered because EXPLOIT is scoring well. This module
does not itself spend the Idea Machine's real experiment budget
(``idea_machine.budget.manager.ResearchBudget`` remains the single source of
truth for that, reused as-is) -- it only decides how many of THIS cycle's
generated candidates should be EXPLOIT vs EXPLORE vs RECOMBINE before they are
ranked and handed to the real budget for pre-registration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from idea_machine.governance import guard
from idea_machine.research_space.exploration_debt import ExplorationDebtState
from idea_machine.research_space.information_gain import EXPLOIT, EXPLORE, RECOMBINE, ResearchCandidate

#: Governance floor. Never configurable below this value.
GOVERNANCE_MIN_EXPLORATION_SHARE = 0.20
DEFAULT_MAX_SINGLE_FAMILY_SHARE = 0.40
DEFAULT_MAX_PARAMETER_ONLY_SHARE = 0.25


@dataclass(frozen=True)
class AllocationPolicy:
    minimum_exploration_share: float = GOVERNANCE_MIN_EXPLORATION_SHARE
    maximum_single_family_share: float = DEFAULT_MAX_SINGLE_FAMILY_SHARE
    maximum_parameter_only_share: float = DEFAULT_MAX_PARAMETER_ONLY_SHARE

    def __post_init__(self) -> None:
        if self.minimum_exploration_share < GOVERNANCE_MIN_EXPLORATION_SHARE:
            raise ValueError(
                f"minimum_exploration_share ({self.minimum_exploration_share}) may not be "
                f"configured below the governance floor ({GOVERNANCE_MIN_EXPLORATION_SHARE})"
            )

    def to_dict(self) -> Dict:
        return {
            "minimum_exploration_share": self.minimum_exploration_share,
            "maximum_single_family_share": self.maximum_single_family_share,
            "maximum_parameter_only_share": self.maximum_parameter_only_share,
        }


@dataclass(frozen=True)
class AllocationResult:
    total_slots: int
    slots_by_mode: Dict[str, int]
    effective_exploration_share: float
    debt_forced_increase: bool
    reason: str

    def to_dict(self) -> Dict:
        return {
            "total_slots": self.total_slots,
            "slots_by_mode": dict(self.slots_by_mode),
            "effective_exploration_share": self.effective_exploration_share,
            "debt_forced_increase": self.debt_forced_increase,
            "reason": self.reason,
        }


class ResearchAllocator:
    def __init__(self, policy: AllocationPolicy = AllocationPolicy()) -> None:
        self.policy = policy

    def allocate_slots(self, total_slots: int, debt: ExplorationDebtState) -> AllocationResult:
        """How many of ``total_slots`` candidate slots go to each mode this cycle."""
        guard.require("ALLOCATE_RESEARCH_MODE_BUDGET", total_slots=total_slots)

        exploration_share = self.policy.minimum_exploration_share
        forced = False
        if debt.forced_exploration:
            # Debt only ever pushes exploration UP. A simple, deterministic
            # bump: +10 percentage points per unit of debt above threshold,
            # capped at 60% so EXPLOIT/RECOMBINE are never starved entirely.
            excess = max(0, debt.debt - debt.threshold + 1)
            exploration_share = min(0.60, exploration_share + 0.10 * excess)
            forced = True

        explore_slots = max(1, round(total_slots * exploration_share)) if total_slots > 0 else 0
        remaining = total_slots - explore_slots
        # Split the remainder EXPLOIT-heavy but leave room for RECOMBINE
        # (roughly 70/30 of the non-exploration budget, deterministic).
        recombine_slots = max(0, round(remaining * 0.30)) if remaining > 0 else 0
        exploit_slots = remaining - recombine_slots

        slots = {EXPLOIT: exploit_slots, EXPLORE: explore_slots, RECOMBINE: recombine_slots}
        effective_share = round(explore_slots / total_slots, 4) if total_slots else 0.0

        reason = (
            f"exploration floor {self.policy.minimum_exploration_share:.0%}"
            + (f", raised to {exploration_share:.0%} by exploration debt ({debt.reason})" if forced else "")
            + f" -> {explore_slots}/{total_slots} EXPLORE, {exploit_slots}/{total_slots} EXPLOIT, "
            f"{recombine_slots}/{total_slots} RECOMBINE"
        )
        return AllocationResult(
            total_slots=total_slots, slots_by_mode=slots,
            effective_exploration_share=effective_share, debt_forced_increase=forced, reason=reason,
        )

    def enforce_family_cap(
        self, candidates: Sequence[ResearchCandidate],
    ) -> Tuple[List[ResearchCandidate], List[str]]:
        """Drop candidates once one (mechanism, instrument, driver) family exceeds the cap.

        The family key matches novelty_budget.py's own parameter-family
        grouping exactly: (mechanism, instrument, driver). Grouping by
        (mechanism, instrument) ALONE would be wrong -- it would treat an
        EXPLORE candidate that swaps in a genuinely new driver as "the same
        family" as an EXPLOIT candidate on the same instrument/mechanism,
        letting the cap wipe out cross-mode diversity the allocator just
        deliberately created. This is the real bug found live in Cycle 14:
        EXPLOIT USDJPY/USB02Y and EXPLORE USDJPY/JP225 share mechanism and
        instrument but are economically distinct cross-asset relationships,
        and must not compete for the same one-family slot.
        """
        by_family: Dict[Tuple[str, str, str], List[ResearchCandidate]] = {}
        for c in candidates:
            by_family.setdefault((c.mechanism, c.instrument, c.driver or ""), []).append(c)

        total = len(candidates) or 1
        cap = max(1, int(total * self.policy.maximum_single_family_share))
        kept: List[ResearchCandidate] = []
        dropped_notes: List[str] = []
        for key, members in sorted(by_family.items()):
            allowed = members[:cap]
            kept.extend(allowed)
            if len(members) > cap:
                dropped_notes.append(
                    f"family {key[0]}/{key[1]}/{key[2] or 'NONE'}: {len(members)} candidates exceeds "
                    f"{self.policy.maximum_single_family_share:.0%} cap ({cap} of {total}); "
                    f"{len(members) - cap} dropped to keep budget from being consumed by one family"
                )
        return kept, dropped_notes
