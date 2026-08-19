"""Generation 5, Phases 6-8 — Exit-mechanism, MFE/MAE, and holding-time
analysis over a list of ``InstrumentedTrade`` records.

Diagnostic only (module-level discipline, repeated per phase in the
execution contract): nothing here alters a candidate, re-scores it, or
feeds back into any economic verdict. ``STRAT-000002`` remains terminally
REJECTED regardless of what these functions report.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from core.economic_validation.instrumented_execution import InstrumentedTrade

HOLDING_TIME_BUCKETS = [(0, 1), (2, 4), (5, 8), (9, 12), (13, 24), (25, None)]


def _stats(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "p25": None, "p75": None, "p90": None, "max": None, "min": None}
    arr = np.array(values, dtype="float64")
    return {
        "count": int(arr.size), "mean": float(arr.mean()), "median": float(np.median(arr)),
        "p25": float(np.percentile(arr, 25)), "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)), "max": float(arr.max()), "min": float(arr.min()),
    }


def analyze_exit_mechanism(trades: List[InstrumentedTrade]) -> Dict[str, Any]:
    """Phase 6: exit-reason distribution, and nominal-vs-realized RR
    measured directly per trade (not inferred from aggregate PF/win_rate,
    unlike the Generation 4 post-mortem's necessarily algebraic version)."""
    by_reason: Dict[str, List[InstrumentedTrade]] = {}
    for t in trades:
        by_reason.setdefault(t.exit_reason or "UNKNOWN", []).append(t)

    breakdown = {}
    for reason, group in by_reason.items():
        rs = [t.realized_R for t in group if t.realized_R is not None]
        holds = [t.holding_period_bars for t in group if t.holding_period_bars is not None]
        mfes = [t.mfe_r for t in group if t.mfe_r is not None]
        maes = [t.mae_r for t in group if t.mae_r is not None]
        breakdown[reason] = {
            "count": len(group),
            "percentage": round(100.0 * len(group) / len(trades), 4) if trades else None,
            "realized_R": _stats(rs),
            "holding_bars": _stats([float(h) for h in holds]),
            "mfe_r": _stats(mfes),
            "mae_r": _stats(maes),
        }

    nominal_rr = trades[0].nominal_reward_risk if trades else None
    realized_rs = [t.realized_R for t in trades if t.realized_R is not None]
    win_rs = [t.realized_R for t in trades if t.net_pnl is not None and t.net_pnl > 0 and t.realized_R is not None]
    loss_rs = [t.realized_R for t in trades if t.net_pnl is not None and t.net_pnl < 0 and t.realized_R is not None]
    avg_win_r = float(np.mean(win_rs)) if win_rs else None
    avg_loss_r = float(np.mean(loss_rs)) if loss_rs else None  # negative
    # This is the SAME quantity the Generation 4 post-mortem could only
    # infer algebraically from aggregate profit_factor/win_rate
    # (realized_RR = PF*(1-wr)/wr) -- here it is measured directly from
    # each trade's own realized_R, decomposed by win/loss.
    realized_rr_measured = (avg_win_r / abs(avg_loss_r)) if (avg_win_r is not None and avg_loss_r) else None
    return {
        "n_trades": len(trades),
        "nominal_reward_risk": nominal_rr,
        "exit_reason_breakdown": breakdown,
        "realized_R_overall": _stats(realized_rs),
        "avg_win_R": avg_win_r,
        "avg_loss_R": avg_loss_r,
        "realized_reward_risk_measured": realized_rr_measured,
        "realized_vs_nominal_pct": (
            round(100.0 * realized_rr_measured / nominal_rr, 4)
            if realized_rr_measured and nominal_rr else None
        ),
        "measurement_basis": (
            "DIRECT_PER_TRADE: realized_reward_risk_measured = mean(realized_R | win) / "
            "abs(mean(realized_R | loss)), computed from each trade's own recorded outcome -- NOT "
            "the Generation 4 post-mortem's aggregate-PF/win_rate algebraic inference "
            "(realized_RR = PF*(1-wr)/wr). This is the confirming direct measurement Phase 5 exists "
            "to provide."
        ),
    }


def analyze_mfe_mae(trades: List[InstrumentedTrade]) -> Dict[str, Any]:
    """Phase 7: MFE/MAE distributions and a diagnostic classification of
    each losing trade. Diagnostic labels only -- Non-Negotiable rule:
    'do NOT use MFE/MAE to retroactively optimize a rejected candidate'."""
    mfes = [t.mfe_r for t in trades if t.mfe_r is not None]
    maes = [t.mae_r for t in trades if t.mae_r is not None]

    classification_counts = {"BAD_ENTRY": 0, "GOOD_ENTRY_BAD_EXIT": 0, "BAD_ENTRY_BAD_EXIT": 0, "EXECUTION_DEGRADATION": 0}
    for t in trades:
        if t.mfe_r is None or t.net_pnl is None:
            continue
        won = t.net_pnl > 0
        reached_meaningful_favour = t.mfe_r >= 0.5  # at least halfway to a 1R move in its favour
        if won:
            continue  # classification is for losers/timeouts only -- a winner has no "bad" label to assign
        if not reached_meaningful_favour and (t.mae_r or 0) >= 0.5:
            classification_counts["BAD_ENTRY"] += 1
        elif reached_meaningful_favour and t.exit_reason == "MAX_HOLDING_PERIOD":
            classification_counts["GOOD_ENTRY_BAD_EXIT"] += 1
        elif reached_meaningful_favour and t.exit_reason == "STOP_LOSS":
            classification_counts["EXECUTION_DEGRADATION"] += 1
        else:
            classification_counts["BAD_ENTRY_BAD_EXIT"] += 1

    by_exit_reason = {}
    grouped: Dict[str, List[InstrumentedTrade]] = {}
    for t in trades:
        grouped.setdefault(t.exit_reason or "UNKNOWN", []).append(t)
    for reason, group in grouped.items():
        by_exit_reason[reason] = {
            "mfe_r": _stats([t.mfe_r for t in group if t.mfe_r is not None]),
            "mae_r": _stats([t.mae_r for t in group if t.mae_r is not None]),
        }

    correlation = None
    if len(mfes) >= 2 and len(maes) == len(mfes):
        c = np.corrcoef(mfes, maes)
        correlation = float(c[0, 1]) if np.isfinite(c[0, 1]) else None

    return {
        "n_trades": len(trades),
        "mfe_r_distribution": _stats(mfes),
        "mae_r_distribution": _stats(maes),
        "mfe_mae_correlation": correlation,
        "by_exit_reason": by_exit_reason,
        "loss_classification": classification_counts,
        "classification_thresholds": {"reached_meaningful_favour_mfe_r": 0.5, "bad_entry_mae_r": 0.5},
        "usage_restriction": "DIAGNOSTIC ONLY -- not used to retune, reparameterize, or re-open STRAT-000002",
    }


def analyze_holding_time(trades: List[InstrumentedTrade]) -> Dict[str, Any]:
    """Phase 8: holding-time distribution and performance by bucket."""
    holds = [t.holding_period_bars for t in trades if t.holding_period_bars is not None]
    buckets = {}
    for lo, hi in HOLDING_TIME_BUCKETS:
        label = f"{lo}-{hi}" if hi is not None else f"{lo}+"
        group = [t for t in trades if t.holding_period_bars is not None
                 and t.holding_period_bars >= lo and (hi is None or t.holding_period_bars <= hi)]
        rs = [t.realized_R for t in group if t.realized_R is not None]
        buckets[label] = {
            "count": len(group),
            "win_rate": (sum(1 for t in group if (t.net_pnl or 0) > 0) / len(group)) if group else None,
            "realized_R": _stats(rs),
        }
    return {
        "n_trades": len(trades),
        "holding_bars_distribution": _stats([float(h) for h in holds]),
        "by_bucket": buckets,
        "usage_restriction": "DIAGNOSTIC ONLY -- do not alter the candidate based on these findings",
    }
