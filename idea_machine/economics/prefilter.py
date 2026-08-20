"""Economic pre-filter (Phase 7) — no backtest, just arithmetic.

The only question asked here: *if the mechanism is exactly right, is the effect
big enough to survive the cost of trading it?* That is answerable with a
multiplication, and answering it before a research slot is spent is the
cheapest filter in the whole machine.

Nothing in this module simulates anything. It compares the idea's own declared
``expected_effect`` against the frozen cost model, charges the round-trip cost
per trade, and applies three sanity checks:

* **Cost coverage** — expected effect must clear ``minimum_edge_multiple`` times
  the round-trip cost. An idea that is merely break-even before slippage
  variance is not worth testing.
* **Horizon/mechanism coherence** — a microstructure mechanism claiming a
  months-long holding period is describing something other than what it says.
* **Turnover realism** — a tiny per-trade edge traded very frequently is the
  classic way an idea looks good on paper and dies on costs; the filter charges
  costs at the implied trade frequency rather than once.

An idea rejected here is recorded as ``FAILED_ECONOMICS``, which is *not* a
refutation of the mechanism — it says this mechanism cannot pay for itself at
this horizon on this instrument. A different horizon may still be viable, which
is why the verdict carries the horizon that was assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

from idea_machine.core.families import horizon_is_plausible
from idea_machine.core.idea_spec import IdeaSpec
from idea_machine.economics.cost_model import DEFAULT_COST_MODEL, CostModel
from idea_machine.governance import guard

VIABLE = "VIABLE"
MARGINAL = "MARGINAL"
FAILED_ECONOMICS = "FAILED_ECONOMICS"

#: Bars per year, by timeframe. Used to turn a holding period into a trade
#: frequency so costs are charged at the rate the idea actually implies.
BARS_PER_YEAR: Dict[str, int] = {
    "M1": 372_000, "M5": 74_400, "M15": 24_800, "M30": 12_400,
    "H1": 6_200, "H4": 1_550, "D1": 260, "W1": 52,
}

#: Below this multiple of cost, an idea is hopeless; between this and
#: ``minimum_edge_multiple`` it is MARGINAL — kept, but deprioritised.
HOPELESS_MULTIPLE = 1.0


@dataclass(frozen=True)
class EconomicVerdict:
    idea_id: str
    verdict: str
    expected_effect: float
    round_trip_cost: float
    effect_vs_cost: float
    net_per_trade: float
    implied_trades_per_year: float
    horizon_coherent: bool
    reason: str
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def may_proceed(self) -> bool:
        """MARGINAL proceeds, deprioritised. Only FAILED_ECONOMICS stops."""
        return self.verdict in (VIABLE, MARGINAL)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_id": self.idea_id,
            "verdict": self.verdict,
            "expected_effect": self.expected_effect,
            "round_trip_cost": self.round_trip_cost,
            "effect_vs_cost": round(self.effect_vs_cost, 4),
            "net_per_trade": self.net_per_trade,
            "implied_trades_per_year": round(self.implied_trades_per_year, 1),
            "horizon_coherent": self.horizon_coherent,
            "reason": self.reason,
            "warnings": list(self.warnings),
        }


class EconomicPreFilter:
    """Arithmetic screening against the frozen cost model."""

    def __init__(self, cost_model: CostModel = DEFAULT_COST_MODEL) -> None:
        self.cost_model = cost_model

    def check(self, idea: IdeaSpec) -> EconomicVerdict:
        guard.require("APPLY_ECONOMIC_PREFILTER", idea_id=idea.idea_id)

        cost = self.cost_model.worst_round_trip(idea.instruments)
        effect = self._effect_in_price_terms(idea, cost)
        ratio = effect / cost if cost > 0 else 0.0
        net = effect - cost
        frequency = self._implied_trades_per_year(idea)
        coherent = horizon_is_plausible(idea.family, idea.holding_period)

        warnings: List[str] = []
        if not coherent:
            warnings.append(
                f"a {idea.family} mechanism does not usually operate over a "
                f"{idea.holding_period} horizon -- the stated mechanism and the stated "
                "holding period may not be describing the same effect"
            )
        if frequency > 2000 and ratio < self.cost_model.minimum_edge_multiple * 1.5:
            warnings.append(
                f"{frequency:.0f} trades/year at only {ratio:.2f}x cost -- high turnover "
                "multiplies every cost estimation error"
            )
        if idea.expected_effect.unit != "PRICE":
            warnings.append(
                f"expected effect declared in {idea.expected_effect.unit}; converted to price "
                "terms using a conservative assumption"
            )

        if ratio < HOPELESS_MULTIPLE:
            return EconomicVerdict(
                idea.idea_id, FAILED_ECONOMICS, effect, cost, ratio, net, frequency, coherent,
                reason=(
                    f"expected effect ({effect:.6f}) does not cover round-trip cost ({cost:.6f}) "
                    f"on {'/'.join(idea.instruments)}. This rejects the idea AT THIS HORIZON on "
                    "THESE INSTRUMENTS -- it is not a refutation of the mechanism."
                ),
                warnings=tuple(warnings),
            )

        if ratio < self.cost_model.minimum_edge_multiple or not coherent:
            return EconomicVerdict(
                idea.idea_id, MARGINAL, effect, cost, ratio, net, frequency, coherent,
                reason=(
                    f"effect is {ratio:.2f}x cost, below the {self.cost_model.minimum_edge_multiple}x "
                    "bar for a confident test; kept but deprioritised"
                ),
                warnings=tuple(warnings),
            )

        return EconomicVerdict(
            idea.idea_id, VIABLE, effect, cost, ratio, net, frequency, coherent,
            reason=f"effect is {ratio:.2f}x round-trip cost before any statistical evidence",
            warnings=tuple(warnings),
        )

    def _effect_in_price_terms(self, idea: IdeaSpec, cost: float) -> float:
        """Convert the declared effect into the same units as the cost.

        Only ``PRICE`` is exact. Other units are converted conservatively — the
        pre-filter must never make an idea look better than the operator can
        justify, so an ambiguous unit is charged, not credited.
        """
        effect = idea.expected_effect
        if effect.unit == "PRICE":
            return float(effect.magnitude)
        if effect.unit == "TICKS":
            return float(effect.magnitude) * cost * 0.1
        if effect.unit in ("BPS", "PCT"):
            # Without a price level we cannot convert exactly. Treat the
            # magnitude as a multiple of cost, conservatively floored.
            scale = 0.0001 if effect.unit == "BPS" else 0.01
            return float(effect.magnitude) * scale
        if effect.unit == "SIGMA":
            # A sigma-denominated effect needs a volatility estimate we do not
            # have here; assume the least favourable interpretation.
            return float(effect.magnitude) * cost
        return 0.0

    def _implied_trades_per_year(self, idea: IdeaSpec) -> float:
        bars = BARS_PER_YEAR.get(idea.timeframe, 6_200)
        hold = max(1, int(idea.expected_effect.horizon_bars))
        return bars / hold

    def screen(
        self, ideas: Sequence[IdeaSpec]
    ) -> Tuple[Tuple[IdeaSpec, ...], Tuple[EconomicVerdict, ...]]:
        passed: List[IdeaSpec] = []
        verdicts: List[EconomicVerdict] = []
        for idea in sorted(ideas, key=lambda i: i.idea_id):
            verdict = self.check(idea)
            verdicts.append(verdict)
            if verdict.may_proceed:
                passed.append(idea)
        return tuple(passed), tuple(verdicts)
