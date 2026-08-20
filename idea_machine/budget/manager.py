"""Research Budget Manager (Phase 14) — the brake on infinite brute force.

A machine that can generate ideas forever will, given the chance, test forever.
Every test is a draw from the same distribution, so an unbounded search
guarantees false positives no correction can rescue.

This module caps the search per window: how many ideas may be generated, how
many screened, and — the one that actually costs something — how many
experiments may be pre-registered. Consumption is recorded in an append-only
ledger, so the count survives a restart and cannot be quietly reset (that is
the ``RESET_LEDGER`` violation).

The Adaptive Search policy can *reallocate* the experiment budget between
families, but never *raise the total*: :meth:`allocate` normalises weights
across the fixed cap. Reallocation without expansion is the point — otherwise
"this family looks promising" becomes a way to buy extra draws.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from idea_machine.core.errors import BudgetExhausted
from idea_machine.core.ids import mint_id
from idea_machine.core.store import DEFAULT_ROOT, AppendOnlyStore
from idea_machine.governance import guard
from utils.helpers import isoformat

DEFAULT_BUDGET_PATH = DEFAULT_ROOT / "research_budget.json"

IDEAS_GENERATED = "IDEAS_GENERATED"
IDEAS_SCREENED = "IDEAS_SCREENED"
EXPERIMENTS_REGISTERED = "EXPERIMENTS_REGISTERED"

RESOURCES = (IDEAS_GENERATED, IDEAS_SCREENED, EXPERIMENTS_REGISTERED)


@dataclass(frozen=True)
class BudgetPolicy:
    """The per-window caps. The roadmap's example: 100 / 20 / 5."""

    ideas_generated: int = 100
    ideas_screened: int = 20
    experiments_registered: int = 5

    def cap_for(self, resource: str) -> int:
        return {
            IDEAS_GENERATED: self.ideas_generated,
            IDEAS_SCREENED: self.ideas_screened,
            EXPERIMENTS_REGISTERED: self.experiments_registered,
        }[resource]

    def to_dict(self) -> Dict[str, int]:
        return {
            IDEAS_GENERATED: self.ideas_generated,
            IDEAS_SCREENED: self.ideas_screened,
            EXPERIMENTS_REGISTERED: self.experiments_registered,
        }


class ResearchBudget:
    """Tracks and enforces consumption inside a named window."""

    def __init__(
        self,
        *,
        policy: BudgetPolicy = BudgetPolicy(),
        path: Path = DEFAULT_BUDGET_PATH,
        window: str = "",
        clock=isoformat,
    ) -> None:
        self.policy = policy
        self.store = AppendOnlyStore(path, id_field="row_id", kind="research_budget")
        self._clock = clock
        self.window = window or self._clock()[:10]     # daily window by default

    # ----------------------------------------------------------- consumption

    def consumed(self, resource: str, *, window: Optional[str] = None) -> int:
        w = window or self.window
        return sum(
            int(r.get("amount", 0))
            for r in self.store.all()
            if r.get("resource") == resource and r.get("window") == w
        )

    def remaining(self, resource: str) -> int:
        return max(0, self.policy.cap_for(resource) - self.consumed(resource))

    def can_spend(self, resource: str, amount: int = 1) -> bool:
        return self.remaining(resource) >= amount

    def spend(self, resource: str, amount: int = 1, *, note: str = "") -> int:
        """Consume budget, or raise :class:`BudgetExhausted`."""
        if resource not in RESOURCES:
            raise ValueError(f"unknown budget resource {resource!r}")
        guard.require("ALLOCATE_RESEARCH_BUDGET", resource=resource, amount=amount)
        remaining = self.remaining(resource)
        if amount > remaining:
            raise BudgetExhausted(
                "research budget for this window is spent -- an unbounded search is how a "
                "machine manufactures false positives faster than any correction can remove them",
                resource=resource,
                window=self.window,
                cap=self.policy.cap_for(resource),
                consumed=self.consumed(resource),
                requested=amount,
            )
        self.store.append(
            {
                "row_id": mint_id(
                    "BUD",
                    {"w": self.window, "r": resource, "a": amount, "n": note, "t": self._clock()},
                ),
                "window": self.window,
                "resource": resource,
                "amount": int(amount),
                "note": note,
                "timestamp": self._clock(),
            }
        )
        return self.remaining(resource)

    def spend_up_to(self, resource: str, wanted: int, *, note: str = "") -> int:
        """Spend as much as is available, up to ``wanted``. Returns what was spent."""
        available = min(wanted, self.remaining(resource))
        if available > 0:
            self.spend(resource, available, note=note)
        return available

    def reset(self, *_: Any, **__: Any) -> None:
        """Forbidden. A resettable budget is not a budget."""
        guard.deny_ledger_reset(detail="ResearchBudget.reset", window=self.window)

    # ------------------------------------------------------------ allocation

    def allocate(self, family_weights: Mapping[str, float]) -> Dict[str, int]:
        """Split the *remaining* experiment budget across families by weight.

        The total is fixed by the policy. Weights redistribute it; they never
        expand it. Largest-remainder apportionment keeps the parts summing to
        the whole without a family being silently rounded out of existence.
        """
        remaining = self.remaining(EXPERIMENTS_REGISTERED)
        if remaining <= 0 or not family_weights:
            return {}

        positive = {k: max(float(v), 0.0) for k, v in family_weights.items()}
        total = sum(positive.values())
        if total <= 0:
            return {}

        exact = {k: remaining * v / total for k, v in positive.items()}
        floors = {k: int(v) for k, v in exact.items()}
        leftover = remaining - sum(floors.values())
        # Hand out the remainder to the largest fractional parts, ties by name.
        order = sorted(exact, key=lambda k: (-(exact[k] - floors[k]), k))
        for k in order[:leftover]:
            floors[k] += 1
        return {k: v for k, v in sorted(floors.items()) if v > 0}

    # --------------------------------------------------------------- reports

    def summary(self) -> Dict[str, Any]:
        return {
            "window": self.window,
            "policy": self.policy.to_dict(),
            "consumed": {r: self.consumed(r) for r in RESOURCES},
            "remaining": {r: self.remaining(r) for r in RESOURCES},
            "exhausted": [r for r in RESOURCES if self.remaining(r) == 0],
            "ledger_rows": self.store.count(),
        }

    def history(self) -> Tuple[Dict[str, Any], ...]:
        return tuple(self.store.all())
