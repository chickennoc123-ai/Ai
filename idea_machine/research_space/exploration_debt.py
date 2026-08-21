"""Exploration debt (Phase 9, spec item 6).

If the machine exploits the same evidenced region cycle after cycle without
touching a new family/dimension, debt accumulates. Once debt crosses the
threshold, the allocator is required to raise the exploration share above its
configured floor -- debt can only ever push exploration UP, never down "just
because exploit is scoring well" (spec: "Không được tự động giảm exploration
chỉ vì exploit đang có điểm cao").

Deterministic: reads the append-only cycle history (research_space_ledger),
counts consecutive EXPLOIT-only cycles, computes debt, and reports it. Never
writes any Factory record; this module is pure history -> number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence

from idea_machine.governance import guard

#: Default debt threshold -- 3 consecutive cycles with no new family/dimension
#: touched forces the allocator to widen exploration on the next cycle.
DEFAULT_DEBT_THRESHOLD = 3


@dataclass(frozen=True)
class CycleTouch:
    """What one past cycle actually touched, for debt accounting."""

    cycle_id: str
    new_dimension_or_family_touched: bool
    exploit_only: bool


@dataclass(frozen=True)
class ExplorationDebtState:
    debt: int
    threshold: int
    forced_exploration: bool
    consecutive_exploit_only_cycles: int
    reason: str

    def to_dict(self) -> Dict:
        return {
            "debt": self.debt,
            "threshold": self.threshold,
            "forced_exploration": self.forced_exploration,
            "consecutive_exploit_only_cycles": self.consecutive_exploit_only_cycles,
            "reason": self.reason,
        }


class ExplorationDebtTracker:
    """Computes exploration debt from a sequence of past cycle touches."""

    def __init__(self, threshold: int = DEFAULT_DEBT_THRESHOLD) -> None:
        if threshold < 1:
            raise ValueError("exploration debt threshold must be >= 1")
        self.threshold = threshold

    def compute(self, history: Sequence[CycleTouch]) -> ExplorationDebtState:
        guard.require("COMPUTE_EXPLORATION_DEBT")

        streak = 0
        for touch in reversed(history):  # most recent first
            if touch.exploit_only and not touch.new_dimension_or_family_touched:
                streak += 1
            else:
                break

        debt = streak  # exploit_cycles_without_new_family, per spec formula
        forced = debt >= self.threshold
        reason = (
            f"{streak} consecutive cycle(s) exploited without touching a new family or "
            f"dimension -- debt {debt} >= threshold {self.threshold}, exploration is forced up"
            if forced else
            f"{streak} consecutive exploit-only cycle(s); debt {debt} below threshold {self.threshold}"
        )
        return ExplorationDebtState(
            debt=debt, threshold=self.threshold, forced_exploration=forced,
            consecutive_exploit_only_cycles=streak, reason=reason,
        )

    @staticmethod
    def touches_from_ledger(rows: Sequence[Dict]) -> List[CycleTouch]:
        """Build CycleTouch history from research_space_ledger rows.

        A row is expected to carry ``cycle_id``, ``research_mode``, and
        ``touched_new_family_or_dimension`` (bool); rows missing the latter
        are treated conservatively as NOT having touched anything new, so
        debt accrues rather than being silently forgiven by missing data.
        """
        by_cycle: Dict[str, List[Dict]] = {}
        for row in rows:
            by_cycle.setdefault(row.get("cycle_id", ""), []).append(row)

        touches: List[CycleTouch] = []
        for cycle_id in sorted(by_cycle):
            rows_for_cycle = by_cycle[cycle_id]
            modes = {r.get("research_mode") for r in rows_for_cycle}
            exploit_only = modes == {"EXPLOIT"}
            touched_new = any(bool(r.get("touched_new_family_or_dimension", False)) for r in rows_for_cycle)
            touches.append(CycleTouch(cycle_id, touched_new, exploit_only))
        return touches
