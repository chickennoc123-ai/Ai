"""The cost model — an input the Idea Machine may read and never write.

Loosening cost assumptions is the cheapest possible way to manufacture a fake
edge, so Phase 16 makes ``MODIFY_COST_MODEL`` a forbidden action. That is
enforced structurally here:

* :class:`CostModel` is a frozen dataclass, and every mutating access raises.
* The frozen defaults carry a checksum; :func:`verify_frozen_costs` recomputes
  it, so an edit to the constants is detectable rather than silent.
* There is no setter, no ``update()``, and no ``from_env()``. A different cost
  model can only arrive by being passed in explicitly by a caller outside the
  Idea Machine.

The numbers below are carried from the Strategy Factory's frozen cost
assumption (``discovery/engine.py``: 1.1 pips round-trip for EURUSD H1) so the
two halves of the system screen ideas against the same reality.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping

from idea_machine.core.ids import content_hash
from idea_machine.governance import guard


@dataclass(frozen=True)
class InstrumentCost:
    """Round-trip cost decomposition for one instrument, in price terms."""

    instrument: str
    median_spread: float
    commission: float
    expected_slippage: float

    @property
    def round_trip(self) -> float:
        return self.median_spread + self.commission + self.expected_slippage

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["round_trip"] = self.round_trip
        return d


#: Frozen per-instrument costs. Price terms, round-trip.
FROZEN_COSTS: Mapping[str, InstrumentCost] = {
    "EURUSD": InstrumentCost("EURUSD", 0.000080, 0.000010, 0.000020),
    "GBPUSD": InstrumentCost("GBPUSD", 0.000120, 0.000010, 0.000030),
    "XAUUSD": InstrumentCost("XAUUSD", 0.250000, 0.020000, 0.080000),
    "US500":  InstrumentCost("US500",  0.400000, 0.050000, 0.150000),
    "USOIL":  InstrumentCost("USOIL",  0.030000, 0.005000, 0.010000),
    "US10Y":  InstrumentCost("US10Y",  0.015000, 0.002000, 0.005000),
}

#: Recorded at authoring time. A change to FROZEN_COSTS changes this, and
#: verify_frozen_costs() will say so.
FROZEN_COSTS_CHECKSUM = content_hash({k: v.to_dict() for k, v in sorted(FROZEN_COSTS.items())})


@dataclass(frozen=True)
class CostModel:
    """Read-only view over instrument costs."""

    costs: Mapping[str, InstrumentCost] = field(default_factory=lambda: dict(FROZEN_COSTS))
    #: Extra multiple of round-trip cost an idea must clear to be worth testing.
    #: 1.0 would mean "break even before slippage variance, taxes, and the fact
    #: that the estimate itself is optimistic" -- which is not worth a slot.
    minimum_edge_multiple: float = 2.0

    def round_trip(self, instrument: str) -> float:
        cost = self.costs.get(instrument)
        if cost is None:
            raise KeyError(
                f"no cost assumption for {instrument!r}; an instrument with no cost model "
                "cannot be economically screened, so it must not be traded"
            )
        return cost.round_trip

    def worst_round_trip(self, instruments: Any) -> float:
        """The most expensive instrument in the basket sets the bar."""
        return max(self.round_trip(i) for i in instruments)

    def update(self, **_: Any) -> None:
        """Forbidden. Present so the attempt crashes rather than silently working."""
        guard.deny_cost_model_mutation(attempted="CostModel.update")

    def relax(self, **_: Any) -> None:
        """Forbidden. See :meth:`update`."""
        guard.deny_cost_model_mutation(attempted="CostModel.relax")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "minimum_edge_multiple": self.minimum_edge_multiple,
            "instruments": {k: v.to_dict() for k, v in sorted(self.costs.items())},
            "checksum": content_hash({k: v.to_dict() for k, v in sorted(self.costs.items())}),
        }


def verify_frozen_costs() -> None:
    """Raise if the frozen cost constants no longer match their checksum."""
    current = content_hash({k: v.to_dict() for k, v in sorted(FROZEN_COSTS.items())})
    if current != FROZEN_COSTS_CHECKSUM:
        guard.deny_cost_model_mutation(
            expected=FROZEN_COSTS_CHECKSUM, actual=current, detail="FROZEN_COSTS was edited"
        )


DEFAULT_COST_MODEL = CostModel()
