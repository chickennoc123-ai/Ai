"""Generation 4, Phase 16 — Robustness / parameter-neighbourhood testing.

An important disclosure that governs how these results may be used:
**the perturbation ranges below were NOT pre-registered.** STRAT-000002's
search space (``SEARCHSPACE-000001``) declares alternative holding periods
and ATR multiples, but no robustness protocol was declared before the
candidate was generated. The ranges here are therefore a *new research
decision made during Generation 4*, and the contract is explicit about
what that means: the result is not an unbiased confirmation of anything.

It is recorded as a new research decision, and its role is restricted to
one question it can answer honestly:

    Is the frozen parameter point an isolated island, or does the
    surrounding region behave the same way?

If the whole neighbourhood behaves the same, the frozen point is not a
lucky pick — which is a claim about *fragility*, not about edge. If the
neighbourhood is negative and the frozen point is negative, no
"best parameter" exists to report and none is reported: this module
deliberately has no ``best`` field, and returns the full surface.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from core.economic_validation.evaluation import evaluate_partition
from core.economic_validation.execution import CostModel, RiskRules
from core.economic_validation.rule_engine import CrossoverRule
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

#: Declared once, here, before any robustness result is computed. Centred
#: on the frozen values; the RSI thresholds and holding periods that
#: appear in SEARCHSPACE-000001 are included so the declared search space
#: is fully covered, plus symmetric neighbours so the surface has a
#: meaningful shape rather than a one-sided edge.
ROBUSTNESS_GRID = {
    "rsi_threshold": [25.0, 27.5, 30.0, 32.5, 35.0],
    "stop_loss_atr_mult": [1.0, 1.5, 2.0],
    "take_profit_atr_mult": [1.5, 2.0, 2.5, 3.0],
    "max_holding_bars": [6, 12, 24],
}

#: Timing perturbation: enter one bar later than the specification says.
#: Tests whether the result depends on capturing a specific bar's open.
TIMING_PERTURBATIONS = [0, 1]


class RobustnessError(EAFactoryError):
    pass


@dataclass(frozen=True)
class RobustnessPoint:
    rsi_threshold: float
    stop_loss_atr_mult: float
    take_profit_atr_mult: float
    max_holding_bars: int
    entry_delay_bars: int
    is_frozen_point: bool
    trade_count: int
    net_profit: float
    profit_factor: Optional[float]
    expectancy: Optional[float]
    win_rate: Optional[float]
    max_drawdown: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RobustnessReport:
    candidate_id: str
    validation_run_id: str
    partition_name: str
    pre_registered: bool
    declaration: str
    grid: Dict[str, Any]
    points: tuple
    surface_summary: Dict[str, Any]
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["points"] = list(self.points)
        return d

    def report_checksum(self) -> str:
        d = self.to_dict()
        d.pop("timestamp", None)
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def _delay_signals(signals: pd.Series, delay: int) -> pd.Series:
    if delay == 0:
        return signals
    return signals.shift(delay).fillna(0).astype("int64")


def run_robustness(
    context_ohlcv: pd.DataFrame,
    *,
    evaluation_start: pd.Timestamp,
    frozen_rule: CrossoverRule,
    frozen_risk: RiskRules,
    costs: CostModel,
    candidate_id: str,
    validation_run_id: str,
    partition_name: str,
    dataset_checksum: str,
    code_version: str,
    grid: Optional[Dict[str, Sequence]] = None,
    timing_perturbations: Sequence[int] = tuple(TIMING_PERTURBATIONS),
    initial_equity: float = 10_000.0,
    timeframe: str = "H1",
    precomputed: Optional[Any] = None,
) -> RobustnessReport:
    """Evaluate the full declared grid. Every point is retained."""
    grid = dict(grid or ROBUSTNESS_GRID)
    points: List[RobustnessPoint] = []
    cached = precomputed.full() if precomputed is not None else None

    for thr in grid["rsi_threshold"]:
        rule = CrossoverRule(
            feature=frozen_rule.feature,
            threshold=float(thr),
            crossing_direction=frozen_rule.crossing_direction,
            direction=frozen_rule.direction,
        )
        for sl in grid["stop_loss_atr_mult"]:
            for tp in grid["take_profit_atr_mult"]:
                for hold in grid["max_holding_bars"]:
                    for delay in timing_perturbations:
                        risk = RiskRules(
                            risk_per_trade=frozen_risk.risk_per_trade,
                            stop_loss_atr_mult=float(sl),
                            take_profit_atr_mult=float(tp),
                            max_holding_bars=int(hold),
                        )
                        record = _evaluate_point(
                            context_ohlcv,
                            evaluation_start=evaluation_start,
                            rule=rule,
                            risk=risk,
                            costs=costs,
                            delay=int(delay),
                            candidate_id=candidate_id,
                            validation_run_id=validation_run_id,
                            partition_name=partition_name,
                            dataset_checksum=dataset_checksum,
                            code_version=code_version,
                            initial_equity=initial_equity,
                            timeframe=timeframe,
                            precomputed=cached,
                        )
                        m = record["metrics"]
                        points.append(
                            RobustnessPoint(
                                rsi_threshold=float(thr),
                                stop_loss_atr_mult=float(sl),
                                take_profit_atr_mult=float(tp),
                                max_holding_bars=int(hold),
                                entry_delay_bars=int(delay),
                                is_frozen_point=(
                                    float(thr) == frozen_rule.threshold
                                    and float(sl) == frozen_risk.stop_loss_atr_mult
                                    and float(tp) == frozen_risk.take_profit_atr_mult
                                    and int(hold) == frozen_risk.max_holding_bars
                                    and int(delay) == 0
                                ),
                                trade_count=int(m["trade_count"]),
                                net_profit=float(m["net_profit"]),
                                profit_factor=m["profit_factor"],
                                expectancy=m["expectancy"],
                                win_rate=m["win_rate"],
                                max_drawdown=float(m["max_drawdown"]),
                            )
                        )

    return RobustnessReport(
        candidate_id=candidate_id,
        validation_run_id=validation_run_id,
        partition_name=partition_name,
        pre_registered=False,
        declaration=(
            "NOT PRE-REGISTERED. No robustness protocol existed before Generation 4. This grid was "
            "declared in core/economic_validation/robustness.py before any robustness result was "
            "computed, and is recorded as a new research decision. Its results describe the shape of "
            "the parameter surface; they are not an unbiased confirmation of any hypothesis, and no "
            "'best parameter' is selected or reported."
        ),
        grid={**{k: list(v) for k, v in grid.items()}, "entry_delay_bars": list(timing_perturbations)},
        points=tuple(p.to_dict() for p in points),
        surface_summary=_summarize(points),
        timestamp=utcnow().isoformat(),
    )


def _evaluate_point(
    context_ohlcv: pd.DataFrame,
    *,
    evaluation_start,
    rule: CrossoverRule,
    risk: RiskRules,
    costs: CostModel,
    delay: int,
    candidate_id: str,
    validation_run_id: str,
    partition_name: str,
    dataset_checksum: str,
    code_version: str,
    initial_equity: float,
    timeframe: str,
    precomputed: Optional[Any] = None,
) -> Dict[str, Any]:
    if delay == 0:
        rec = evaluate_partition(
            context_ohlcv,
            evaluation_start=evaluation_start,
            rule=rule,
            costs=costs,
            risk=risk,
            candidate_id=candidate_id,
            validation_run_id=validation_run_id,
            partition_name=f"{partition_name}_ROBUSTNESS",
            dataset_checksum=dataset_checksum,
            code_version=code_version,
            initial_equity=initial_equity,
            timeframe=timeframe,
            precomputed=precomputed,
        )
        return rec.to_dict()

    # Timing perturbation needs the signal series shifted, which
    # evaluate_partition does not expose -- do it explicitly here using
    # the same building blocks, so the perturbation is visible rather
    # than hidden behind a parameter.
    from core.economic_validation.evaluation import build_execution_frame
    from core.economic_validation.execution import execute
    from core.economic_validation.metrics import compute_metrics
    from core.economic_validation.rule_engine import generate_signals

    if precomputed is not None:
        exec_frame, features = precomputed
    else:
        exec_frame, features = build_execution_frame(context_ohlcv)
    signals = generate_signals(features, rule)
    signals = signals.where(pd.Series(signals.index >= evaluation_start, index=signals.index), 0)
    signals = _delay_signals(signals, delay)
    frame = exec_frame.loc[exec_frame.index >= evaluation_start]
    result = execute(
        frame,
        signals.loc[signals.index >= evaluation_start],
        costs=costs,
        risk=risk,
        initial_equity=initial_equity,
    )
    return {"metrics": compute_metrics(result, timeframe=timeframe).to_dict()}


def _summarize(points: List[RobustnessPoint]) -> Dict[str, Any]:
    if not points:
        return {"n_points": 0}
    traded = [p for p in points if p.trade_count > 0]
    pfs = [p.profit_factor for p in traded if p.profit_factor is not None]
    nets = np.array([p.net_profit for p in traded], dtype="float64") if traded else np.array([])
    frozen = next((p for p in points if p.is_frozen_point), None)

    return {
        "n_points": len(points),
        "n_points_with_trades": len(traded),
        "n_points_net_positive": int((nets > 0).sum()) if nets.size else 0,
        "n_points_net_negative": int((nets < 0).sum()) if nets.size else 0,
        "fraction_net_positive": float((nets > 0).mean()) if nets.size else None,
        "profit_factor_min": float(min(pfs)) if pfs else None,
        "profit_factor_median": float(np.median(pfs)) if pfs else None,
        "profit_factor_max": float(max(pfs)) if pfs else None,
        "n_points_pf_above_1": int(sum(1 for pf in pfs if pf > 1.0)),
        "net_profit_min": float(nets.min()) if nets.size else None,
        "net_profit_median": float(np.median(nets)) if nets.size else None,
        "net_profit_max": float(nets.max()) if nets.size else None,
        "frozen_point": frozen.to_dict() if frozen else None,
        "frozen_point_percentile_within_surface": (
            float((nets < frozen.net_profit).mean()) if frozen and nets.size else None
        ),
        "viable_region": (
            "NONE" if not pfs or max(pfs) <= 1.0
            else "PARTIAL" if sum(1 for pf in pfs if pf > 1.0) < len(pfs) / 2
            else "BROAD"
        ),
    }
