"""Generation 4, Phase 18 — Statistical validation.

Trading returns are serially dependent and trades overlap in the sense
that consecutive trades sample adjacent market regimes. An IID trade-level
bootstrap therefore understates uncertainty. Both are computed here and
reported side by side, with the block bootstrap treated as the primary
result and the IID one kept only to show how much the independence
assumption would have flattered the interval.

Two things this module deliberately does not do:

* It does not compute a p-value against a null of "no edge" and present
  it as significance. With a single candidate drawn from a search space
  the project can enumerate, the honest treatment of significance lives
  in ``multiple_testing.py``, not here.
* It does not extrapolate a probability of ruin from a fitted
  distribution. Probability of ruin is estimated by resampling the actual
  trade sequence, which makes it a statement about the observed sample
  and nothing more.

``trade_count_sufficiency`` is reported explicitly because a confidence
interval computed from too few trades is precise-looking noise, and the
Generation 4 contract asks for false precision to be avoided rather than
decorated with more decimals.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

#: Minimum trades below which an interval is reported but explicitly
#: labelled insufficient. 30 is the conventional floor for any resampled
#: interval to mean much; 100 is where a per-trade expectancy interval
#: starts to be narrow enough to act on.
MIN_TRADES_FOR_INTERVAL = 30
MIN_TRADES_FOR_CONFIDENT_INTERVAL = 100

DEFAULT_BOOTSTRAP_ITERATIONS = 10_000
DEFAULT_BLOCK_SIZE = 20
DEFAULT_SEED = 20260819


class StatisticalValidationError(EAFactoryError):
    pass


@dataclass(frozen=True)
class BootstrapInterval:
    method: str
    statistic: str
    point_estimate: Optional[float]
    ci_lower: Optional[float]
    ci_upper: Optional[float]
    confidence_level: float
    iterations: int
    block_size: Optional[int]
    straddles_zero: Optional[bool]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StatisticalValidationReport:
    candidate_id: str
    validation_run_id: str
    partition_name: str
    trade_count: int
    trade_count_sufficiency: str
    seed: int
    intervals: tuple
    return_distribution: Dict[str, Any]
    drawdown_distribution: Dict[str, Any]
    probability_of_ruin: Dict[str, Any]
    sharpe_uncertainty: Dict[str, Any]
    methodology: Dict[str, Any]
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["intervals"] = list(self.intervals)
        return d

    def report_checksum(self) -> str:
        d = self.to_dict()
        d.pop("timestamp", None)
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def _percentile_ci(samples: np.ndarray, confidence: float) -> tuple:
    alpha = (1.0 - confidence) / 2.0
    return float(np.percentile(samples, 100 * alpha)), float(np.percentile(samples, 100 * (1 - alpha)))


def iid_bootstrap(
    values: Sequence[float],
    statistic,
    *,
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    confidence: float = 0.95,
    seed: int = DEFAULT_SEED,
) -> np.ndarray:
    arr = np.asarray(values, dtype="float64")
    if arr.size == 0:
        return np.array([])
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(iterations, arr.size))
    return np.array([statistic(arr[row]) for row in idx], dtype="float64")


def block_bootstrap(
    values: Sequence[float],
    statistic,
    *,
    block_size: int = DEFAULT_BLOCK_SIZE,
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    seed: int = DEFAULT_SEED,
) -> np.ndarray:
    """Moving-block bootstrap: resamples contiguous runs, preserving local
    serial dependence that an IID resample destroys."""
    arr = np.asarray(values, dtype="float64")
    n = arr.size
    if n == 0:
        return np.array([])
    b = max(1, min(int(block_size), n))
    n_blocks = int(math.ceil(n / b))
    max_start = n - b
    rng = np.random.default_rng(seed)

    out = np.empty(iterations, dtype="float64")
    for i in range(iterations):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        sample = np.concatenate([arr[s : s + b] for s in starts])[:n]
        out[i] = statistic(sample)
    return out


def _max_drawdown_of_sequence(pnls: np.ndarray) -> float:
    equity = np.cumsum(pnls)
    running_max = np.maximum.accumulate(np.concatenate([[0.0], equity]))[1:]
    return float(np.max(running_max - equity)) if equity.size else 0.0


def run_statistical_validation(
    trade_pnls: Sequence[float],
    bar_returns: Sequence[float],
    *,
    candidate_id: str,
    validation_run_id: str,
    partition_name: str,
    initial_equity: float,
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    block_size: int = DEFAULT_BLOCK_SIZE,
    confidence: float = 0.95,
    seed: int = DEFAULT_SEED,
    bars_per_year: int = 6240,
) -> StatisticalValidationReport:
    pnls = np.asarray(list(trade_pnls), dtype="float64")
    rets = np.asarray(list(bar_returns), dtype="float64")
    n = int(pnls.size)

    if n < MIN_TRADES_FOR_INTERVAL:
        sufficiency = (
            f"INSUFFICIENT: {n} trades is below the {MIN_TRADES_FOR_INTERVAL}-trade floor at which a "
            "resampled interval carries meaning. Intervals below are reported but must not be acted on."
        )
    elif n < MIN_TRADES_FOR_CONFIDENT_INTERVAL:
        sufficiency = (
            f"MARGINAL: {n} trades supports a wide interval only; the point estimate carries little "
            "information relative to its own uncertainty."
        )
    else:
        sufficiency = f"SUFFICIENT: {n} trades supports a resampled interval."

    intervals: List[BootstrapInterval] = []

    if n > 0:
        for method, sampler in (
            ("BLOCK_BOOTSTRAP", lambda s: block_bootstrap(pnls, s, block_size=block_size, iterations=iterations, seed=seed)),
            ("IID_BOOTSTRAP", lambda s: iid_bootstrap(pnls, s, iterations=iterations, seed=seed)),
        ):
            exp_samples = sampler(np.mean)
            lo, hi = _percentile_ci(exp_samples, confidence)
            intervals.append(
                BootstrapInterval(
                    method=method,
                    statistic="expectancy_per_trade",
                    point_estimate=float(pnls.mean()),
                    ci_lower=lo,
                    ci_upper=hi,
                    confidence_level=confidence,
                    iterations=iterations,
                    block_size=block_size if method == "BLOCK_BOOTSTRAP" else None,
                    straddles_zero=bool(lo <= 0.0 <= hi),
                )
            )

            def _pf(sample: np.ndarray) -> float:
                gains = sample[sample > 0].sum()
                losses = -sample[sample < 0].sum()
                return float(gains / losses) if losses > 0 else float("nan")

            pf_samples = sampler(_pf)
            pf_samples = pf_samples[np.isfinite(pf_samples)]
            if pf_samples.size:
                lo, hi = _percentile_ci(pf_samples, confidence)
                intervals.append(
                    BootstrapInterval(
                        method=method,
                        statistic="profit_factor",
                        point_estimate=_pf(pnls) if np.isfinite(_pf(pnls)) else None,
                        ci_lower=lo,
                        ci_upper=hi,
                        confidence_level=confidence,
                        iterations=iterations,
                        block_size=block_size if method == "BLOCK_BOOTSTRAP" else None,
                        straddles_zero=bool(lo <= 1.0 <= hi),  # for PF the null is 1, not 0
                    )
                )

            net_samples = sampler(np.sum)
            lo, hi = _percentile_ci(net_samples, confidence)
            intervals.append(
                BootstrapInterval(
                    method=method,
                    statistic="net_profit",
                    point_estimate=float(pnls.sum()),
                    ci_lower=lo,
                    ci_upper=hi,
                    confidence_level=confidence,
                    iterations=iterations,
                    block_size=block_size if method == "BLOCK_BOOTSTRAP" else None,
                    straddles_zero=bool(lo <= 0.0 <= hi),
                )
            )

    # --- drawdown distribution from resampled trade sequences ---
    if n > 0:
        dd_samples = block_bootstrap(
            pnls, _max_drawdown_of_sequence, block_size=block_size, iterations=min(iterations, 2000), seed=seed
        )
        drawdown_distribution = {
            "method": "BLOCK_BOOTSTRAP over the trade-P&L sequence",
            "median": float(np.median(dd_samples)),
            "p95": float(np.percentile(dd_samples, 95)),
            "p99": float(np.percentile(dd_samples, 99)),
            "max_observed_in_resamples": float(dd_samples.max()),
            "observed": _max_drawdown_of_sequence(pnls),
        }
        ruin_thresholds = {"50pct": 0.5, "30pct": 0.3, "20pct": 0.2}
        probability_of_ruin = {
            "definition": (
                "fraction of block-bootstrap resampled trade sequences whose peak-to-trough drawdown "
                "exceeds the stated fraction of the starting equity"
            ),
            "initial_equity": initial_equity,
            "caveat": (
                "This is a statement about resamples of the OBSERVED trade sequence only. It is not a "
                "forward-looking probability and must not be read as one."
            ),
            **{
                f"p_drawdown_exceeds_{name}": float((dd_samples > frac * initial_equity).mean())
                for name, frac in ruin_thresholds.items()
            },
        }
    else:
        drawdown_distribution = {"n": 0}
        probability_of_ruin = {"n": 0}

    # --- Sharpe uncertainty ---
    if rets.size > 2 and rets.std(ddof=1) > 0:
        observed_sharpe = float(rets.mean() / rets.std(ddof=1) * math.sqrt(bars_per_year))

        def _sharpe(sample: np.ndarray) -> float:
            sd = sample.std(ddof=1)
            return float(sample.mean() / sd * math.sqrt(bars_per_year)) if sd > 0 else float("nan")

        sharpe_samples = block_bootstrap(
            rets, _sharpe, block_size=max(block_size, 24), iterations=min(iterations, 2000), seed=seed
        )
        sharpe_samples = sharpe_samples[np.isfinite(sharpe_samples)]
        lo, hi = _percentile_ci(sharpe_samples, confidence) if sharpe_samples.size else (None, None)
        # Lo/Bailey-style analytic standard error, for comparison with the resampled one.
        analytic_se = float(math.sqrt((1.0 + 0.5 * observed_sharpe**2) / max(rets.size - 1, 1)) * math.sqrt(bars_per_year))
        sharpe_uncertainty = {
            "observed_annualized_sharpe": observed_sharpe,
            "block_bootstrap_ci_lower": lo,
            "block_bootstrap_ci_upper": hi,
            "confidence_level": confidence,
            "analytic_standard_error": analytic_se,
            "n_return_observations": int(rets.size),
            "note": (
                "Computed on per-bar equity returns. The analytic standard error assumes IID normal "
                "returns and is shown only as a reference point against the resampled interval."
            ),
        }
    else:
        sharpe_uncertainty = {"n_return_observations": int(rets.size), "note": "insufficient return observations"}

    return StatisticalValidationReport(
        candidate_id=candidate_id,
        validation_run_id=validation_run_id,
        partition_name=partition_name,
        trade_count=n,
        trade_count_sufficiency=sufficiency,
        seed=seed,
        intervals=tuple(i.to_dict() for i in intervals),
        return_distribution={
            "n": int(rets.size),
            "mean": float(rets.mean()) if rets.size else None,
            "std": float(rets.std(ddof=1)) if rets.size > 1 else None,
            "skew": float(__import__("pandas").Series(rets).skew()) if rets.size > 2 else None,
            "kurtosis": float(__import__("pandas").Series(rets).kurtosis()) if rets.size > 3 else None,
        },
        drawdown_distribution=drawdown_distribution,
        probability_of_ruin=probability_of_ruin,
        sharpe_uncertainty=sharpe_uncertainty,
        methodology={
            "primary_method": "moving-block bootstrap",
            "block_size_trades": block_size,
            "block_size_rationale": (
                "20 consecutive trades spans roughly one market month at this trade frequency, which is "
                "the scale at which regime persistence shows up in the P&L sequence. Chosen before any "
                "interval was computed and not varied afterward."
            ),
            "secondary_method": "IID bootstrap, reported only to expose how much narrower the "
            "independence assumption would have made the intervals",
            "iterations": iterations,
            "seed": seed,
            "deterministic": True,
            "not_computed": [
                "p-value against a no-edge null (see multiple_testing.py -- a single-candidate p-value "
                "would ignore the search that produced the candidate)",
                "parametric probability of ruin (would require a distributional assumption the data "
                "does not support)",
            ],
        },
        timestamp=utcnow().isoformat(),
    )
