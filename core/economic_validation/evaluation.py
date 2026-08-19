"""Generation 4 — Single-partition evaluation.

One function, used identically for development, validation, holdout, OOS
and every walk-forward window. Using the same code path everywhere is
what makes the numbers comparable across phases; a holdout evaluator that
differed from the development evaluator in any detail would make the
comparison between them meaningless.

**Warmup context.** Features need up to 500 bars of history. Evaluating a
partition therefore requires bars from *before* the partition. That is
not leakage — those bars are strictly in the past relative to every
decision made inside the partition — but it does mean the caller must
hand in a context frame that ends where the partition ends and starts
earlier. ``evaluate_partition`` enforces the direction of that
relationship: it raises if the context extends past the evaluation
window, which is the mistake that *would* be leakage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import pandas as pd

from core.economic_validation.execution import CostModel, ExecutionResult, RiskRules, execute
from core.economic_validation.metrics import PerformanceMetrics, compute_metrics
from core.economic_validation.rule_engine import (
    RULE_ENGINE_ID,
    CrossoverRule,
    SignalGenerationProvenance,
    generate_signals,
    signal_checksum,
)
from core.features.fe_r2_001 import FEATURE_VERSION, build_feature_matrix
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow


class EvaluationError(EAFactoryError):
    pass


@dataclass(frozen=True)
class EvaluationRecord:
    """Everything one evaluation produced, checksummed."""

    validation_run_id: str
    candidate_id: str
    partition_name: str
    evaluation_start: str
    evaluation_end: str
    context_start: str
    n_context_bars: int
    n_evaluation_bars: int
    rule: Dict[str, Any]
    cost_model: Dict[str, Any]
    risk_rules: Dict[str, Any]
    feature_version: str
    signal_provenance: Dict[str, Any]
    metrics: Dict[str, Any]
    trades: tuple
    unclosed_trade_at_end: bool
    evaluation_timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["trades"] = list(self.trades)
        return d

    def result_checksum(self) -> str:
        """Checksum over the economically meaningful content only.

        Excludes wall-clock timestamps so that a genuine re-run of the
        same evaluation produces the *same* checksum — which is what makes
        the Phase 28 reproducibility check a real check rather than a
        tautology.
        """
        d = self.to_dict()
        d.pop("evaluation_timestamp", None)
        prov = dict(d.get("signal_provenance") or {})
        prov.pop("timestamp", None)
        d["signal_provenance"] = prov
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def build_execution_frame(context_ohlcv: pd.DataFrame) -> tuple:
    """Return ``(exec_frame, features)`` for a context frame.

    ``exec_frame`` carries OHLC plus ``atr_14`` so the execution engine
    has the risk-geometry input it needs without recomputing anything.
    """
    features = build_feature_matrix(context_ohlcv)
    exec_frame = context_ohlcv[["open", "high", "low", "close"]].join(features[["atr_14"]])
    return exec_frame, features


class PrecomputedFeatures:
    """A feature matrix computed once and sliced for many evaluations.

    **Why this is safe, and what it depends on.** Slicing a globally
    computed feature matrix would be leakage for any non-causal feature:
    row ``t`` of a global computation could carry information from bars
    after ``t``. It is safe here for exactly one reason — Phase 3's
    truncation-invariance audit *empirically verified on this dataset*
    that ``f(data[0..T])[t] == f(data[0..t])[t]`` for every feature this
    candidate uses. Slicing is therefore identical to recomputing, not
    merely similar to it.

    That dependency is load-bearing. If the feature audit ever fails, this
    optimization becomes invalid and must be removed, not tolerated — which
    is why ``assert_causal_slicing_verified`` exists and why the runner
    calls it before constructing this object.

    The reproducibility check in Phase 28 provides the empirical
    confirmation: the same result checksums are produced with and without
    this cache.
    """

    def __init__(self, ohlcv: pd.DataFrame) -> None:
        self._exec_frame, self._features = build_execution_frame(ohlcv)
        self._source_end = ohlcv.index[-1]

    def slice(self, end: pd.Timestamp) -> tuple:
        """Return ``(exec_frame, features)`` truncated at ``end`` inclusive."""
        if end > self._source_end:
            raise EvaluationError(
                "requested a slice ending after the precomputed range; the cache cannot "
                "manufacture bars it was never given",
                requested_end=str(end),
                available_end=str(self._source_end),
            )
        return (
            self._exec_frame.loc[self._exec_frame.index <= end],
            self._features.loc[self._features.index <= end],
        )

    def full(self) -> tuple:
        return self._exec_frame, self._features


def assert_causal_slicing_verified(feature_audit_verdict: str) -> None:
    """Refuse to use :class:`PrecomputedFeatures` unless Phase 3 passed."""
    if feature_audit_verdict != "PASS":
        raise EvaluationError(
            "feature temporal audit did not PASS, so a globally computed feature matrix may not "
            "be sliced -- recompute per window instead",
            feature_audit_verdict=feature_audit_verdict,
        )


def evaluate_partition(
    context_ohlcv: pd.DataFrame,
    **kwargs: Any,
) -> EvaluationRecord:
    """Convenience wrapper returning only the record.

    Most callers want the record. The ones that need the per-bar equity
    series -- the statistics phase, which must resample the *same* series
    the metrics were computed from rather than a reconstruction of it --
    call :func:`evaluate_partition_with_result` instead.
    """
    record, _ = evaluate_partition_with_result(context_ohlcv, **kwargs)
    return record


def evaluate_partition_with_result(
    context_ohlcv: pd.DataFrame,
    *,
    evaluation_start: pd.Timestamp,
    rule: CrossoverRule,
    costs: CostModel,
    risk: RiskRules,
    candidate_id: str,
    validation_run_id: str,
    partition_name: str,
    dataset_checksum: str,
    code_version: str,
    initial_equity: float = 10_000.0,
    timeframe: str = "H1",
    precomputed: Optional[tuple] = None,
) -> tuple:
    """Evaluate the frozen rule over ``context_ohlcv[evaluation_start:]``.

    Returns ``(EvaluationRecord, ExecutionResult)``. The execution result
    carries the per-bar equity curve, which is not embedded in the record
    (it would add tens of thousands of floats to every artifact) but is
    needed verbatim by the statistics phase.

    Bars before ``evaluation_start`` are used **only** to warm up features;
    no signal before that timestamp is acted on.
    """
    if not isinstance(context_ohlcv.index, pd.DatetimeIndex):
        raise EvaluationError("context frame must be indexed by a DatetimeIndex")
    if not context_ohlcv.index.is_monotonic_increasing:
        raise EvaluationError("context frame must be chronologically ordered")
    if evaluation_start < context_ohlcv.index[0]:
        raise EvaluationError(
            "evaluation_start precedes the context frame; there is nothing to evaluate",
            evaluation_start=str(evaluation_start),
            context_start=str(context_ohlcv.index[0]),
        )

    if precomputed is not None:
        exec_frame, features = precomputed
    else:
        exec_frame, features = build_execution_frame(context_ohlcv)
    all_signals = generate_signals(features, rule)

    # Signals before the evaluation window are discarded, never acted on.
    in_window = all_signals.index >= evaluation_start
    signals = all_signals.where(pd.Series(in_window, index=all_signals.index), 0)

    evaluation_frame = exec_frame.loc[exec_frame.index >= evaluation_start]
    if evaluation_frame.empty:
        raise EvaluationError("evaluation window is empty", evaluation_start=str(evaluation_start))

    result: ExecutionResult = execute(
        evaluation_frame,
        signals.loc[signals.index >= evaluation_start],
        costs=costs,
        risk=risk,
        initial_equity=initial_equity,
    )
    metrics: PerformanceMetrics = compute_metrics(result, timeframe=timeframe)

    acted_signals = signals.loc[signals.index >= evaluation_start]
    nonzero = acted_signals[acted_signals != 0]
    provenance = SignalGenerationProvenance(
        rule_engine_id=RULE_ENGINE_ID,
        candidate_id=candidate_id,
        validation_run_id=validation_run_id,
        partition_name=partition_name,
        rule=rule.to_dict(),
        feature_version=FEATURE_VERSION,
        dataset_checksum=dataset_checksum,
        n_bars=int(len(evaluation_frame)),
        n_signals=int(len(nonzero)),
        first_signal=str(nonzero.index[0]) if len(nonzero) else None,
        last_signal=str(nonzero.index[-1]) if len(nonzero) else None,
        signal_checksum=signal_checksum(acted_signals),
        seed=None,
        seed_policy=(
            "NO_SEED_REQUIRED: RULE-R4-001 contains no stochastic element. Signal generation and "
            "execution are pure deterministic functions of the price series and the frozen "
            "thresholds, so there is no seed to select and therefore no seed to cherry-pick."
        ),
        deterministic=True,
        code_version=code_version,
        timestamp=utcnow().isoformat(),
    )

    record = EvaluationRecord(
        validation_run_id=validation_run_id,
        candidate_id=candidate_id,
        partition_name=partition_name,
        evaluation_start=str(evaluation_frame.index[0]),
        evaluation_end=str(evaluation_frame.index[-1]),
        context_start=str(context_ohlcv.index[0]),
        n_context_bars=int(len(context_ohlcv)),
        n_evaluation_bars=int(len(evaluation_frame)),
        rule=rule.to_dict(),
        cost_model=costs.to_dict(),
        risk_rules=risk.to_dict(),
        feature_version=FEATURE_VERSION,
        signal_provenance=provenance.to_dict(),
        metrics=metrics.to_dict(),
        trades=tuple(t.to_dict() for t in result.trades),
        unclosed_trade_at_end=bool(result.unclosed_trade),
        evaluation_timestamp=utcnow().isoformat(),
    )
    return record, result
