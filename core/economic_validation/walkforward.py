"""Generation 4, Phases 14-15 — Walk-forward evaluation and stability audit.

A caveat that changes how these numbers should be read, stated up front
rather than buried: **STRAT-000002 fits nothing.** It has no parameters
estimated from data — the RSI threshold, the ATR multiples and the
holding period are all fixed constants in the frozen specification. A
walk-forward protocol's usual purpose is to test whether parameters
fitted on a training window survive on the following test window, and
that question does not exist for this candidate.

Rolling-window evaluation is still run, and is still worth running, for a
different reason: it measures **whether the result is stable across
time**, which is the Phase 15 question. Each window is out-of-sample by
construction (nothing was ever in-sample), so the training-window fields
are recorded as structurally empty rather than filled with a fitting step
that did not happen.

Every window is retained and aggregated. There is no code path here that
filters, ranks, or selects windows.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.economic_validation.evaluation import EvaluationRecord, evaluate_partition
from core.economic_validation.execution import CostModel, RiskRules
from core.economic_validation.rule_engine import CrossoverRule
from utils.exceptions import EAFactoryError
from utils.helpers import utcnow


class WalkForwardError(EAFactoryError):
    pass


@dataclass(frozen=True)
class WindowResult:
    window_id: int
    training_start: Optional[str]
    training_end: Optional[str]
    training_note: str
    test_start: str
    test_end: str
    context_start: str
    training_checksum: str
    model_checksum: str
    test_checksum: str
    trade_count: int
    net_profit: float
    profit_factor: Optional[float]
    expectancy: Optional[float]
    win_rate: Optional[float]
    sharpe: Optional[float]
    sortino: Optional[float]
    max_drawdown: float
    signal_checksum: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WalkForwardReport:
    candidate_id: str
    validation_run_id: str
    protocol: str
    window_months: int
    n_windows: int
    windows: tuple
    aggregate: Dict[str, Any]
    stability: Dict[str, Any]
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["windows"] = [w for w in self.windows]
        return d

    def report_checksum(self) -> str:
        d = self.to_dict()
        d.pop("timestamp", None)
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def _frame_checksum(df: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=True).to_numpy().tobytes()).hexdigest()


def generate_month_windows(index: pd.DatetimeIndex, window_months: int = 1) -> List[tuple]:
    """Contiguous, non-overlapping calendar windows covering ``index``.

    Non-overlapping matters: overlapping test windows would double-count
    the same trades and make the dispersion statistics look tighter than
    they are.
    """
    if len(index) == 0:
        return []
    # Month key as a plain integer (year*12 + month). Deliberately not
    # ``to_period("M")``, which drops the index's timezone and warns --
    # and a timezone-dropping conversion in the middle of a temporal
    # protocol is exactly the kind of silent semantic change this project
    # forbids, warning or not.
    month_key = index.year.to_numpy() * 12 + index.month.to_numpy()
    unique_months = np.unique(month_key)
    groups: List[tuple] = []
    for i in range(0, len(unique_months), window_months):
        chunk = unique_months[i : i + window_months]
        window_index = index[np.isin(month_key, chunk)]
        if len(window_index) == 0:
            continue
        groups.append((window_index[0], window_index[-1]))
    return groups


def run_walk_forward(
    context_ohlcv: pd.DataFrame,
    *,
    evaluation_start: pd.Timestamp,
    rule: CrossoverRule,
    costs: CostModel,
    risk: RiskRules,
    candidate_id: str,
    validation_run_id: str,
    dataset_checksum: str,
    code_version: str,
    window_months: int = 1,
    initial_equity: float = 10_000.0,
    timeframe: str = "H1",
    precomputed: Optional[Any] = None,
) -> WalkForwardReport:
    """Evaluate every rolling window over ``context_ohlcv[evaluation_start:]``.

    Each window is evaluated with the full preceding history available as
    warmup context — never with data from after the window.
    """
    eval_index = context_ohlcv.index[context_ohlcv.index >= evaluation_start]
    if len(eval_index) == 0:
        raise WalkForwardError("no bars at or after evaluation_start")

    windows = generate_month_windows(eval_index, window_months=window_months)
    if not windows:
        raise WalkForwardError("no windows could be formed")

    results: List[WindowResult] = []
    for wid, (w_start, w_end) in enumerate(windows, start=1):
        # Context ends AT the window end -- never later.
        context = context_ohlcv.loc[context_ohlcv.index <= w_end]
        window_precomputed = precomputed.slice(w_end) if precomputed is not None else None
        try:
            record: EvaluationRecord = evaluate_partition(
                context,
                evaluation_start=w_start,
                rule=rule,
                costs=costs,
                risk=risk,
                candidate_id=candidate_id,
                validation_run_id=validation_run_id,
                partition_name=f"WFA_WINDOW_{wid:03d}",
                dataset_checksum=dataset_checksum,
                code_version=code_version,
                initial_equity=initial_equity,
                timeframe=timeframe,
                precomputed=window_precomputed,
            )
        except Exception as exc:  # noqa: BLE001 - a failed window is recorded, never dropped
            raise WalkForwardError(
                "a walk-forward window failed to evaluate; windows are never silently dropped",
                window_id=wid,
                window_start=str(w_start),
                window_end=str(w_end),
                error=str(exc),
            ) from exc

        m = record.metrics
        test_frame = context.loc[context.index >= w_start]
        results.append(
            WindowResult(
                window_id=wid,
                training_start=None,
                training_end=None,
                training_note=(
                    "NO_TRAINING_WINDOW: STRAT-000002 fits no parameters, so no window was trained. "
                    "Every window is out-of-sample by construction."
                ),
                test_start=str(w_start),
                test_end=str(w_end),
                context_start=str(context.index[0]),
                training_checksum="",
                model_checksum="NONE_DETERMINISTIC_RULE",
                test_checksum=_frame_checksum(test_frame),
                trade_count=int(m["trade_count"]),
                net_profit=float(m["net_profit"]),
                profit_factor=m["profit_factor"],
                expectancy=m["expectancy"],
                win_rate=m["win_rate"],
                sharpe=m["sharpe"],
                sortino=m["sortino"],
                max_drawdown=float(m["max_drawdown"]),
                signal_checksum=str(record.signal_provenance["signal_checksum"]),
            )
        )

    aggregate, stability = _aggregate(results)

    return WalkForwardReport(
        candidate_id=candidate_id,
        validation_run_id=validation_run_id,
        protocol=(
            "Contiguous non-overlapping calendar windows over the reusable partitions. No training "
            "step: the candidate is a zero-free-parameter rule. Each window uses only bars at or "
            "before its own end as feature warmup context."
        ),
        window_months=window_months,
        n_windows=len(results),
        windows=tuple(w.to_dict() for w in results),
        aggregate=aggregate,
        stability=stability,
        timestamp=utcnow().isoformat(),
    )


def _aggregate(results: List[WindowResult]) -> tuple:
    nets = np.array([r.net_profit for r in results], dtype="float64")
    trades = np.array([r.trade_count for r in results], dtype="float64")
    traded = nets[trades > 0]

    positive = int((traded > 0).sum())
    negative = int((traded < 0).sum())
    flat = int((traded == 0).sum())
    n_traded = int(traded.size)

    aggregate = {
        "n_windows": len(results),
        "n_windows_with_trades": n_traded,
        "n_windows_without_trades": int((trades == 0).sum()),
        "total_trades": int(trades.sum()),
        "total_net_profit": float(nets.sum()),
        "positive_window_fraction": (positive / n_traded) if n_traded else None,
        "negative_window_fraction": (negative / n_traded) if n_traded else None,
        "flat_window_fraction": (flat / n_traded) if n_traded else None,
        "mean_window_net_profit": float(traded.mean()) if n_traded else None,
        "median_window_net_profit": float(np.median(traded)) if n_traded else None,
        "std_window_net_profit": float(traded.std(ddof=1)) if n_traded > 1 else None,
        "worst_window": _extreme(results, min),
        "best_window": _extreme(results, max),
    }

    # --- Phase 15: is the result concentrated in one place? ---
    order = np.argsort(-np.abs(traded)) if n_traded else np.array([], dtype=int)
    total_abs = float(np.abs(traded).sum()) if n_traded else 0.0
    top1 = float(np.abs(traded)[order[0]]) if n_traded else 0.0
    top5 = float(np.abs(traded)[order[:5]].sum()) if n_traded else 0.0

    time_index = np.arange(n_traded, dtype="float64")
    if n_traded > 2 and traded.std(ddof=1) > 0:
        time_corr = float(np.corrcoef(time_index, traded)[0, 1])
    else:
        time_corr = None

    cumulative = np.cumsum(traded) if n_traded else np.array([])
    stability = {
        "single_window_share_of_absolute_pnl": (top1 / total_abs) if total_abs > 0 else None,
        "top5_window_share_of_absolute_pnl": (top5 / total_abs) if total_abs > 0 else None,
        "correlation_of_window_pnl_with_time": time_corr,
        "sign_of_total_without_worst_window": (
            float(traded.sum() - traded.min()) if n_traded else None
        ),
        "sign_of_total_without_best_window": (
            float(traded.sum() - traded.max()) if n_traded else None
        ),
        "cumulative_final": float(cumulative[-1]) if len(cumulative) else None,
        "concentration_flag": (
            "CONCENTRATED"
            if total_abs > 0 and (top1 / total_abs) > 0.5
            else "DISTRIBUTED"
            if total_abs > 0
            else "NO_DATA"
        ),
        "interpretation": (
            "A DISTRIBUTED flag with a majority of negative windows means the result is a broad, "
            "persistent property of the strategy across time, not an artifact of one period. A "
            "CONCENTRATED flag would mean the opposite and would require the aggregate to be "
            "discounted accordingly."
        ),
    }
    return aggregate, stability


def _extreme(results: List[WindowResult], fn) -> Optional[Dict[str, Any]]:
    traded = [r for r in results if r.trade_count > 0]
    if not traded:
        return None
    chosen = fn(traded, key=lambda r: r.net_profit)
    return {
        "window_id": chosen.window_id,
        "test_start": chosen.test_start,
        "test_end": chosen.test_end,
        "net_profit": chosen.net_profit,
        "trade_count": chosen.trade_count,
        "profit_factor": chosen.profit_factor,
    }
