"""Generation 5, Phase 9 — Signal-quality vs execution-mechanics
separation, measured directly.

``SIGNAL ECONOMICS`` (what the entry alone predicts, at a fixed horizon,
with no stop/target/max-hold in the way) and ``EXECUTION ECONOMICS``
(what the stop/target/max-hold geometry does to that raw signal) together
compose ``OBSERVED ECONOMICS`` (the actual traded result). Generation 4's
post-mortem could only show this split algebraically, from aggregate
profit_factor/win_rate, because no independent signal-only measurement
existed. This module adds that independent measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from core.economic_validation.rule_engine import CrossoverRule, generate_signals
from utils.exceptions import EAFactoryError


class SignalSeparationError(EAFactoryError):
    pass


def compute_forward_returns(close: pd.Series, *, horizon_bars: int) -> pd.Series:
    """Pure price-path measurement: ``close[t+horizon] / close[t] - 1``,
    with NaN wherever the horizon runs past the end of the series."""
    if horizon_bars < 1:
        raise SignalSeparationError("horizon_bars must be >= 1", horizon_bars=horizon_bars)
    return close.shift(-horizon_bars) / close - 1.0


def compute_signal_quality(
    ohlcv: pd.DataFrame, features: pd.DataFrame, rule: CrossoverRule, *, horizon_bars: int,
) -> Dict[str, Any]:
    """Independent-of-execution signal quality: conditional forward
    return (in the rule's stated direction) when the entry condition
    fires, vs the unconditional baseline over the same series. This is
    IC-style evidence computed with NO stop-loss, take-profit, or
    max-holding-period involved at all -- a pure test of "does the signal
    predict anything," answerable even for a signal whose exits later
    destroy the edge.
    """
    signals = generate_signals(features, rule)
    fwd = compute_forward_returns(ohlcv["close"], horizon_bars=horizon_bars)
    directed_fwd = fwd * rule.direction  # positive = move in the rule's favour

    signal_mask = signals != 0
    conditional = directed_fwd.loc[signal_mask].dropna()
    unconditional = directed_fwd.dropna()

    if conditional.empty:
        return {
            "n_signals": 0, "n_bars": int(len(unconditional)), "horizon_bars": horizon_bars,
            "conditional_mean_forward_return": None, "unconditional_mean_forward_return": None,
            "signal_edge": None, "information_coefficient": None,
            "verdict": "INSUFFICIENT -- no signals fired in this window",
        }

    cond_mean = float(conditional.mean())
    uncond_mean = float(unconditional.mean()) if not unconditional.empty else None
    edge = (cond_mean - uncond_mean) if uncond_mean is not None else None

    # A simple, transparent IC proxy: correlation between "signal fired"
    # (1/0) and the directed forward return, over the full series. Not a
    # ranking-based Spearman IC (there is nothing to rank -- the rule is
    # binary), but the same spirit: does the binary signal state carry
    # information about the forward return's sign/magnitude.
    aligned = pd.DataFrame({"fired": signal_mask.astype(int), "fwd": directed_fwd}).dropna()
    ic = float(aligned["fired"].corr(aligned["fwd"])) if len(aligned) > 2 else None

    conditional_win_rate = float((conditional > 0).mean())
    return {
        "n_signals": int(len(conditional)), "n_bars": int(len(unconditional)), "horizon_bars": horizon_bars,
        "conditional_mean_forward_return": cond_mean,
        "conditional_forward_return_win_rate": conditional_win_rate,
        "unconditional_mean_forward_return": uncond_mean,
        "signal_edge": edge,
        "information_coefficient": ic,
        "verdict": (
            "NO_MEASURABLE_EDGE" if edge is not None and edge <= 0
            else "POSITIVE_EDGE_AT_THIS_HORIZON" if edge is not None else "INSUFFICIENT"
        ),
        "measurement_basis": (
            "raw price path only -- no stop-loss, take-profit, or max-holding-period involved; "
            "this measures the SIGNAL, independent of the EXECUTION mechanics that separately "
            "determine the observed traded result"
        ),
    }


def decompose_signal_vs_execution(
    signal_quality: Dict[str, Any], observed_metrics: Dict[str, Any], *, materiality_floor: Optional[float] = None,
) -> Dict[str, Any]:
    """Phase 9's required classification: SIGNAL_FAILURE vs
    EXECUTION_FAILURE vs BOTH, from the independent signal measurement
    above plus the already-computed observed (executed) result.

    **Statistical sign is not enough to call a signal "has edge"**
    (Non-Negotiable Principle 11: do not use significance to override
    economic implausibility -- and the mirror-image mistake, calling a
    tiny positive number "edge," is exactly what this guards against).
    ``materiality_floor`` is the minimum |signal_edge| required before a
    positive number counts as edge at all; the caller should pass the
    round-trip transaction cost expressed as a return fraction, so an
    "edge" smaller than the cost of trading it once is correctly treated
    as NOT material regardless of its sign.
    """
    signal_edge = signal_quality.get("signal_edge")
    observed_pf = observed_metrics.get("profit_factor")

    if materiality_floor is not None and signal_edge is not None:
        signal_has_edge = signal_edge > materiality_floor
    else:
        signal_has_edge = signal_edge is not None and signal_edge > 0
    execution_profitable = observed_pf is not None and observed_pf > 1.0

    if signal_has_edge and execution_profitable:
        classification = "NEITHER_FAILED"
    elif not signal_has_edge and not execution_profitable:
        classification = "SIGNAL_FAILURE"  # execution cannot be blamed if the raw signal has no edge to destroy
    elif signal_has_edge and not execution_profitable:
        classification = "EXECUTION_FAILURE"  # signal predicts something; the trading mechanics destroyed it
    else:
        classification = "BOTH_OR_INDETERMINATE"

    return {
        "signal_has_edge": signal_has_edge,
        "materiality_floor": materiality_floor,
        "execution_profitable": execution_profitable,
        "classification": classification,
        "signal_quality": signal_quality,
        "observed_profit_factor": observed_pf,
        "note": (
            "SIGNAL ECONOMICS (raw forward return at a fixed horizon, no stops/targets/timeouts) + "
            "EXECUTION ECONOMICS (what the stop/target/max-hold geometry does to it) = OBSERVED "
            "ECONOMICS (the actual traded result). This decomposition is diagnostic; it does not "
            "revise STRAT-000002's terminal verdict."
        ),
    }
