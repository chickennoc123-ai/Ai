"""Experiment Designer (Phase 9) — idea in, falsifiable experiment out.

The designer's job is to answer, before anything runs: how much data does this
need, over which windows, how many configurations may be tried, and what
result would end it.

Two decisions here matter more than the rest:

* **Sample requirement is computed, not assumed.** It comes from the idea's own
  declared effect size and the conditioning gates it applies. An experiment
  that cannot reach its own sample requirement is not designed — it is returned
  as ``UNDERPOWERED_BY_DESIGN``, which saves a research slot and, more
  importantly, avoids generating a meaningless answer.

* **Evaluation budget is small and explicit.** Every extra configuration tried
  is an extra draw from the same distribution. The budget is written into the
  pre-registration so the Factory's multiple-testing correction knows the true
  number of attempts rather than the number that happened to be reported.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from idea_machine.core.idea_spec import IdeaSpec
from idea_machine.economics.cost_model import DEFAULT_COST_MODEL, CostModel
from idea_machine.economics.data_feasibility import FeasibilityVerdict
from idea_machine.economics.prefilter import EconomicVerdict
from idea_machine.experiment.spec import EvaluationWindow, ExperimentSpec
from idea_machine.governance import guard
from utils.helpers import isoformat

DESIGNED = "DESIGNED"
UNDERPOWERED_BY_DESIGN = "UNDERPOWERED_BY_DESIGN"

#: Configurations an experiment may try. Deliberately small: the point of a
#: pre-registered experiment is to test one idea, not to search a grid.
DEFAULT_EVALUATION_BUDGET = 3

#: Fraction of usable history reserved for validation.
VALIDATION_FRACTION = 0.30

#: Two-sided z for alpha=0.05, and z for 80% power. Used in the sample-size
#: estimate below.
_Z_ALPHA = 1.96
_Z_POWER = 0.84


@dataclass(frozen=True)
class DesignOutcome:
    idea_id: str
    status: str
    spec: Optional[ExperimentSpec]
    required_sample: int
    available_sample: int
    reason: str

    @property
    def designed(self) -> bool:
        return self.status == DESIGNED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idea_id": self.idea_id,
            "status": self.status,
            "experiment_id": self.spec.experiment_id if self.spec else "",
            "required_sample": self.required_sample,
            "available_sample": self.available_sample,
            "reason": self.reason,
        }


class ExperimentDesigner:
    """Builds an :class:`ExperimentSpec` from a screened, ranked idea."""

    def __init__(
        self,
        *,
        cost_model: CostModel = DEFAULT_COST_MODEL,
        evaluation_budget: int = DEFAULT_EVALUATION_BUDGET,
        history_start: str = "2015-01-01",
        history_end: str = "2025-12-31",
        clock=isoformat,
    ) -> None:
        self.cost_model = cost_model
        self.evaluation_budget = evaluation_budget
        self.history_start = history_start
        self.history_end = history_end
        self._clock = clock

    def design(
        self,
        idea: IdeaSpec,
        *,
        feasibility: FeasibilityVerdict,
        economics: EconomicVerdict,
    ) -> DesignOutcome:
        guard.require("DESIGN_EXPERIMENT", idea_id=idea.idea_id)

        required = self._required_sample(idea, economics)
        available = self._effective_sample(idea, feasibility)

        if available < required:
            return DesignOutcome(
                idea.idea_id,
                UNDERPOWERED_BY_DESIGN,
                None,
                required,
                available,
                reason=(
                    f"needs ~{required} observations to resolve an effect of "
                    f"{economics.effect_vs_cost:.2f}x cost, but only ~{available} are available "
                    f"after {self._gate_count(idea)} conditioning gate(s). Running it anyway would "
                    "produce an UNDERPOWERED verdict, which costs a research slot and teaches "
                    "nothing about the market."
                ),
            )

        train, validation = self._windows()
        spec = ExperimentSpec(
            idea_id=idea.idea_id,
            research_question=self._research_question(idea),
            hypothesis=idea.hypothesis,
            entry=dict(idea.entry),
            exit=dict(idea.exit),
            holding_period=idea.holding_period,
            instruments=idea.instruments,
            timeframe=idea.timeframe,
            cost_model=self.cost_model.to_dict(),
            sample_requirement=required,
            train_period=train,
            validation_period=validation,
            evaluation_budget=self.evaluation_budget,
            success_gate=self._success_gate(idea, economics, required),
            kill_gate=self._kill_gate(idea, economics),
            required_data=idea.required_data,
            designed_at=self._clock(),
        )
        return DesignOutcome(
            idea.idea_id, DESIGNED, spec, required, available,
            reason=f"design is adequately powered: ~{available} available against ~{required} required",
        )

    # -------------------------------------------------------------- helpers

    def _research_question(self, idea: IdeaSpec) -> str:
        return (
            f"Does the mechanism stated for this {idea.family} idea produce a measurable, "
            f"cost-surviving effect in {'/'.join(idea.instruments)} on {idea.timeframe} over a "
            f"{idea.holding_period} holding period? Specifically: {idea.hypothesis}"
        )

    def _required_sample(self, idea: IdeaSpec, economics: EconomicVerdict) -> int:
        """Observations needed to detect this effect at alpha=0.05, power=0.80.

        Uses the standard ``n = ((z_a + z_b) / (effect/sd))^2`` form. The
        effect-to-noise ratio is approximated by the effect's size relative to
        round-trip cost, which is a deliberately pessimistic proxy: per-trade
        noise in liquid markets is comfortably larger than the spread, so this
        errs toward demanding more data rather than less.
        """
        ratio = max(economics.effect_vs_cost, 0.01)
        # Effect/noise: an effect of 1x cost is a very small standardised effect.
        standardised = ratio * 0.05
        n = ((_Z_ALPHA + _Z_POWER) / standardised) ** 2
        return int(math.ceil(min(max(n, 200), 5_000_000)))

    def _gate_count(self, idea: IdeaSpec) -> int:
        return sum(1 for k in idea.entry if k in ("regime_gate", "confirmation", "gate", "lead_signal"))

    def _effective_sample(self, idea: IdeaSpec, feasibility: FeasibilityVerdict) -> int:
        """Usable observations after conditioning gates and event sparsity."""
        base = max(feasibility.min_rows, 0)
        base = int(base / (3.0 ** self._gate_count(idea)))
        # An event-driven idea only has as many observations as there are events.
        if idea.family == "EVENT":
            base = min(base, 12 * 11)      # ~11 years of monthly releases
        elif idea.family == "SEASONALITY":
            base = min(base, 12 * 11)
        elif idea.family == "POSITIONING":
            base = min(base, 52 * 11)      # weekly positioning reports
        return max(base, 0)

    def _windows(self) -> Tuple[EvaluationWindow, ...]:
        """Split available history into train and validation, in time order.

        No holdout window is produced: the sealed holdout is the Factory's, and
        ``EvaluationWindow`` refuses to be named one.
        """
        start_year = int(self.history_start[:4])
        end_year = int(self.history_end[:4])
        span = end_year - start_year
        split_year = start_year + max(1, int(span * (1 - VALIDATION_FRACTION)))
        return (
            EvaluationWindow("TRAIN", self.history_start, f"{split_year}-01-01"),
            EvaluationWindow("VALIDATION", f"{split_year}-01-01", self.history_end),
        )

    def _success_gate(self, idea: IdeaSpec, economics: EconomicVerdict, required: int) -> str:
        return (
            f"In the validation window, the effect predicted by the mechanism is present with the "
            f"sign the hypothesis states, net of the frozen cost model, on at least {required} "
            f"observations, and it does not depend on any single sub-period. Support at this gate "
            f"means the idea is NOT REFUTED and may proceed to the Strategy Factory's own gates -- "
            f"it does not mean an edge exists."
        )

    def _kill_gate(self, idea: IdeaSpec, economics: EconomicVerdict) -> str:
        return (
            f"Stop if any of: (a) {idea.falsification_condition} "
            f"(b) the net-of-cost effect in the validation window is below "
            f"{economics.round_trip_cost:.6f} per trade; "
            f"(c) the result depends on one sub-period or one instrument; "
            f"(d) the evaluation budget is exhausted without meeting the success gate. "
            f"Reaching the kill gate ends this design -- it is not an invitation to adjust a "
            f"threshold and try again."
        )

    def design_batch(
        self,
        ideas: Sequence[IdeaSpec],
        *,
        feasibility: Mapping[str, FeasibilityVerdict],
        economics: Mapping[str, EconomicVerdict],
    ) -> Tuple[DesignOutcome, ...]:
        out: List[DesignOutcome] = []
        for idea in ideas:
            f, e = feasibility.get(idea.idea_id), economics.get(idea.idea_id)
            if f is None or e is None:
                continue
            out.append(self.design(idea, feasibility=f, economics=e))
        return tuple(out)
