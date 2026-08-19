"""Hypothesis Formalization Engine — Generation 2, Phase 5.

Converts a natural-language claim into a formal, testable hypothesis.
Per the task's own example:

    Source claim: "Momentum tends to persist in trending markets."
    Formalization:
        Condition: trend_regime == TRUE
        Signal: N-period momentum > threshold
        Target: future_return over K bars
        Direction: positive
        Falsification: conditional expectancy <= 0 after realistic costs
                        OR effect disappears out-of-sample

``FormalizationSpec`` requires every one of INPUTS / CONDITION / SIGNAL /
TARGET / HORIZON / DIRECTION / REGIME / COST ASSUMPTIONS / FALSIFICATION
RULE to be explicitly, non-vaguely stated — a hypothesis missing any of
these cannot be formalized, and cannot proceed to candidate generation
(``core.factory.candidate_generation_engine`` refuses to consume an
un-formalized hypothesis).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Tuple

from core.factory.hypothesis import HypothesisRecord, HypothesisRegistry, HypothesisSpecError
from utils.exceptions import EAFactoryError

#: Values that count as "not actually specified" -- a spec containing one
#: of these is rejected exactly as if the field were empty, closing the
#: obvious loophole of typing the literal word "unknown"/"tbd" to satisfy
#: a non-empty-string check without actually saying anything.
_VAGUE_VALUES = frozenset({"", "unknown", "tbd", "n/a", "na", "none", "?", "..."})


class FormalizationSpecError(EAFactoryError):
    """Raised when a FormalizationSpec is incomplete or vague."""


def _reject_if_vague(field_name: str, value: str) -> None:
    if not value or value.strip().lower() in _VAGUE_VALUES:
        raise FormalizationSpecError(f"formalization field '{field_name}' is missing or vague", value=value)


@dataclass(frozen=True)
class FormalizationSpec:
    """The nine mandatory, explicit components of a formalized hypothesis."""

    inputs: Tuple[str, ...]  # feature ids / raw data series the signal is computed from
    condition: str  # the regime/precondition that must hold (e.g. "trend_regime == TRUE")
    signal: str  # the concrete, computable trigger (e.g. "5-period momentum > 0.5%")
    target: str  # what is being predicted (e.g. "future_return over 12 bars")
    horizon_bars: int  # K in "future_return over K bars"
    direction: str  # "positive" / "negative" / "long_only" / "short_only" / "long_and_short"
    regime: str  # explicit regime label/definition this hypothesis is scoped to
    instrument_scope: str  # explicit instrument(s) this hypothesis is scoped to
    cost_assumptions: str  # explicit statement of what cost model is assumed
    falsification_rule: str  # the concrete condition(s) that would refute this hypothesis

    def __post_init__(self) -> None:
        if not self.inputs:
            raise FormalizationSpecError("inputs must not be empty -- a hypothesis with no stated inputs is vague")
        for name, value in (
            ("condition", self.condition),
            ("signal", self.signal),
            ("target", self.target),
            ("direction", self.direction),
            ("regime", self.regime),
            ("instrument_scope", self.instrument_scope),
            ("cost_assumptions", self.cost_assumptions),
            ("falsification_rule", self.falsification_rule),
        ):
            _reject_if_vague(name, value)
        if self.horizon_bars is None or self.horizon_bars <= 0:
            raise FormalizationSpecError("horizon_bars must be a positive integer", horizon_bars=self.horizon_bars)

    def to_trading_rule_text(self) -> str:
        """A single-string rendering, for ``HypothesisRecord.
        formalized_trading_rule`` (kept as a readable summary; the
        structured spec itself is the authoritative, machine-checkable
        form)."""
        return (
            f"IF {self.condition} AND {self.signal} "
            f"THEN expect {self.direction} movement in {self.target} "
            f"(horizon={self.horizon_bars} bars, regime={self.regime}); "
            f"falsified if {self.falsification_rule} (costs: {self.cost_assumptions})"
        )


def formalize_hypothesis(
    registry: HypothesisRegistry,
    hypothesis_id: str,
    spec: FormalizationSpec,
    *,
    reason: str = "formalized",
) -> HypothesisRecord:
    """Apply ``spec`` to the hypothesis, advance both status axes, and
    record the event. Refuses (raises, does not silently skip) if the
    hypothesis is already past ``DRAFT`` on the formalization axis, since
    re-formalizing in place would erase the prior formalization's
    provenance -- callers that need a materially different formalization
    should create a new hypothesis version instead (Phase 4: "if a
    hypothesis changes materially, create a new hypothesis version")."""
    record = registry.get(hypothesis_id)
    if record.formalization_status != "DRAFT":
        raise FormalizationSpecError(
            "hypothesis is not in DRAFT formalization_status -- cannot formalize in place; "
            "create a new hypothesis version for a materially different formalization",
            hypothesis_id=hypothesis_id, current_status=record.formalization_status,
        )

    # Mutate the in-memory record's rich fields directly -- registry.get()
    # returns the SAME object HypothesisRegistry holds internally (not a
    # copy), so these are visible to the registry immediately; the
    # formalize()/transition_formalization_status() calls below each
    # persist to disk (both call _save() internally), so the last one
    # captures every field set here, not just its own.
    record.economic_mechanism = f"{spec.condition} => {spec.signal}"
    record.target_definition = spec.target
    record.expected_direction = spec.direction
    record.holding_period = f"{spec.horizon_bars} bars"
    record.regime_conditions = spec.regime
    record.instrument_scope = spec.instrument_scope
    record.cost_assumptions = spec.cost_assumptions
    record.falsification_conditions = spec.falsification_rule
    record.feature_dependencies = tuple(spec.inputs)

    registry.formalize(hypothesis_id, formalized_trading_rule=spec.to_trading_rule_text(), reason=reason)
    registry.transition_formalization_status(hypothesis_id, "FORMALIZED", reason=reason)
    return registry.get(hypothesis_id)
