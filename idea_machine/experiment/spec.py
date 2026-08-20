"""ExperimentSpec (Phase 9) — turning an idea into something that can lose.

An IdeaSpec says what someone believes. An ExperimentSpec says what would have
to happen for that belief to be wrong, decided **in advance**. Everything the
Phase 9 list requires is a field here, and two of them do the real work:

* ``success_gate`` — what result would count as support.
* ``kill_gate`` — what result ends it.

Both are set before the experiment runs, which is the entire point. Once
:meth:`ExperimentSpec.freeze` is called the spec is sealed with a checksum, and
:mod:`idea_machine.experiment.prereg` refuses to accept a result for any spec
whose checksum has changed. That is what makes "backtest -> didn't like it ->
change the rule -> backtest again" detectable instead of invisible.

The spec carries no results and no holdout reference: the Idea Machine designs
the experiment, the Strategy Factory runs it and owns everything it produces.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, Tuple

from idea_machine.core.errors import ImmutabilityError, SpecValidationError
from idea_machine.core.idea_spec import assert_no_result_fields
from idea_machine.core.ids import content_hash, mint_id


@dataclass(frozen=True)
class EvaluationWindow:
    """A named, dated slice of data an experiment is allowed to use.

    There is deliberately no ``holdout`` window type. The Idea Machine may
    specify train and validation windows; the sealed holdout belongs to the
    Factory's governed pipeline and is not addressable from here.
    """

    name: str
    start: str
    end: str

    def __post_init__(self) -> None:
        if self.name.strip().upper() in ("HOLDOUT", "PURE_HOLDOUT", "SEALED"):
            raise SpecValidationError(
                "the Idea Machine may not name a holdout window -- holdout scheduling is the "
                "Strategy Factory's authority",
                window=self.name,
            )
        for f in ("name", "start", "end"):
            if not str(getattr(self, f)).strip():
                raise SpecValidationError(f"EvaluationWindow.{f} is required")
        if self.start >= self.end:
            raise SpecValidationError("window start must precede end", start=self.start, end=self.end)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExperimentSpec:
    """A pre-registerable experiment. Frozen once, then read-only forever."""

    idea_id: str
    research_question: str
    hypothesis: str
    entry: Mapping[str, Any]
    exit: Mapping[str, Any]
    holding_period: str
    instruments: Tuple[str, ...]
    timeframe: str
    cost_model: Mapping[str, Any]
    sample_requirement: int
    train_period: EvaluationWindow
    validation_period: EvaluationWindow
    evaluation_budget: int          # max distinct configurations that may be tried
    success_gate: str
    kill_gate: str
    required_data: Tuple[str, ...]
    designed_at: str = ""
    experiment_id: str = field(default="", compare=False)
    frozen: bool = False
    frozen_at: str = ""

    def __post_init__(self) -> None:
        for name in ("research_question", "hypothesis", "success_gate", "kill_gate"):
            if not str(getattr(self, name)).strip():
                raise SpecValidationError(f"ExperimentSpec.{name} is required")
        if self.sample_requirement < 1:
            raise SpecValidationError("sample_requirement must be positive")
        if self.evaluation_budget < 1:
            raise SpecValidationError(
                "evaluation_budget must be at least 1 -- an unbounded number of tries is how a "
                "single experiment turns into an undeclared multiple-testing problem"
            )
        if self.train_period.end > self.validation_period.start:
            raise SpecValidationError(
                "validation period must begin after the training period ends -- overlapping "
                "windows leak the answer into the setup",
                train_end=self.train_period.end,
                validation_start=self.validation_period.start,
            )
        assert_no_result_fields(
            {"entry": self.entry, "exit": self.exit, "cost_model": self.cost_model},
            where="experiment",
        )
        object.__setattr__(self, "instruments", tuple(self.instruments))
        object.__setattr__(self, "required_data", tuple(self.required_data))
        object.__setattr__(self, "entry", dict(self.entry))
        object.__setattr__(self, "exit", dict(self.exit))
        object.__setattr__(self, "cost_model", dict(self.cost_model))
        if not self.experiment_id:
            object.__setattr__(self, "experiment_id", mint_id("EXP", self.preregistration_payload()))

    # ------------------------------------------------------------- freezing

    def preregistration_payload(self) -> Dict[str, Any]:
        """Exactly what is being committed to, and nothing else.

        ``designed_at``/``frozen_at`` are excluded so that the checksum answers
        one question only: *did the experimental design change?*
        """
        return {
            "idea_id": self.idea_id,
            "research_question": self.research_question,
            "hypothesis": self.hypothesis,
            "entry": dict(self.entry),
            "exit": dict(self.exit),
            "holding_period": self.holding_period,
            "instruments": sorted(self.instruments),
            "timeframe": self.timeframe,
            "cost_model": dict(self.cost_model),
            "sample_requirement": self.sample_requirement,
            "train_period": self.train_period.to_dict(),
            "validation_period": self.validation_period.to_dict(),
            "evaluation_budget": self.evaluation_budget,
            "success_gate": self.success_gate,
            "kill_gate": self.kill_gate,
            "required_data": sorted(self.required_data),
        }

    def preregistration_checksum(self) -> str:
        return content_hash(self.preregistration_payload())

    def freeze(self, *, at: str) -> "ExperimentSpec":
        if self.frozen:
            raise ImmutabilityError(
                "experiment is already frozen", experiment_id=self.experiment_id, frozen_at=self.frozen_at
            )
        return ExperimentSpec(
            **{
                **{k: v for k, v in self._fields().items() if k not in ("frozen", "frozen_at")},
                "frozen": True,
                "frozen_at": at,
            }
        )

    def _fields(self) -> Dict[str, Any]:
        return {
            "idea_id": self.idea_id,
            "research_question": self.research_question,
            "hypothesis": self.hypothesis,
            "entry": dict(self.entry),
            "exit": dict(self.exit),
            "holding_period": self.holding_period,
            "instruments": self.instruments,
            "timeframe": self.timeframe,
            "cost_model": dict(self.cost_model),
            "sample_requirement": self.sample_requirement,
            "train_period": self.train_period,
            "validation_period": self.validation_period,
            "evaluation_budget": self.evaluation_budget,
            "success_gate": self.success_gate,
            "kill_gate": self.kill_gate,
            "required_data": self.required_data,
            "designed_at": self.designed_at,
            "experiment_id": self.experiment_id,
            "frozen": self.frozen,
            "frozen_at": self.frozen_at,
        }

    # -------------------------------------------------------- serialisation

    def to_dict(self) -> Dict[str, Any]:
        d = self._fields()
        d["instruments"] = list(self.instruments)
        d["required_data"] = list(self.required_data)
        d["train_period"] = self.train_period.to_dict()
        d["validation_period"] = self.validation_period.to_dict()
        d["preregistration_checksum"] = self.preregistration_checksum()
        return d

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "ExperimentSpec":
        return ExperimentSpec(
            idea_id=d["idea_id"],
            research_question=d["research_question"],
            hypothesis=d["hypothesis"],
            entry=dict(d["entry"]),
            exit=dict(d["exit"]),
            holding_period=d["holding_period"],
            instruments=tuple(d["instruments"]),
            timeframe=d["timeframe"],
            cost_model=dict(d["cost_model"]),
            sample_requirement=int(d["sample_requirement"]),
            train_period=EvaluationWindow(**d["train_period"]),
            validation_period=EvaluationWindow(**d["validation_period"]),
            evaluation_budget=int(d["evaluation_budget"]),
            success_gate=d["success_gate"],
            kill_gate=d["kill_gate"],
            required_data=tuple(d["required_data"]),
            designed_at=d.get("designed_at", ""),
            experiment_id=d.get("experiment_id", ""),
            frozen=bool(d.get("frozen", False)),
            frozen_at=d.get("frozen_at", ""),
        )
