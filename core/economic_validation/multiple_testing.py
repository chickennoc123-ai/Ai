"""Generation 4, Phase 19 — Multiple testing and deflated Sharpe.

This phase is the one where a research factory most easily lies to
itself. The mechanism is simple: try many things, report the best one as
if it were the only one, and the reported statistics are wrong by exactly
the amount of the search that produced them.

The correction implemented here is the **Deflated Sharpe Ratio** (Bailey
& López de Prado, 2014), which asks: given that ``N`` independent-ish
strategy configurations were evaluated, what is the probability that the
observed Sharpe exceeds the maximum a *skill-free* process would have
produced across ``N`` tries? That requires knowing ``N``, and ``N`` is
read from the project's own ledgers rather than asserted.

**The honest limitation, stated before the numbers rather than after
them**: this project's tested population is 2 candidates from 1 search
space. A multiple-testing correction over N=2 is arithmetically valid and
epistemically nearly empty — it can barely move any conclusion. This
module says so explicitly through
``correction_meaningfulness`` and refuses to present a deflated figure as
if it settled significance. Three statuses are kept strictly separate,
because conflating them is the specific failure this phase exists to
prevent:

    ACCOUNTING_COMPLETE          -- we know how many things were tried
    STATISTICAL_CORRECTION_COMPLETE -- a correction was computed and applied
    ECONOMIC_EDGE_SUPPORTED      -- the corrected evidence supports an edge

The first can be true while the second and third are false. In this
project's current state, that is exactly the situation.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from utils.exceptions import EAFactoryError
from utils.helpers import utcnow

ACCOUNTING_COMPLETE = "ACCOUNTING_COMPLETE"
STATISTICAL_CORRECTION_COMPLETE = "STATISTICAL_CORRECTION_COMPLETE"
ECONOMIC_EDGE_SUPPORTED = "ECONOMIC_EDGE_SUPPORTED"
NOT_SUPPORTED = "NOT_SUPPORTED"

#: Below this many independent trials, a deflation correction is computed
#: but must be labelled as carrying almost no information.
MIN_TRIALS_FOR_MEANINGFUL_CORRECTION = 20

_EULER_MASCHERONI = 0.5772156649015329


class MultipleTestingError(EAFactoryError):
    pass


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF via Acklam's rational approximation.

    Implemented here rather than pulled from scipy because this package
    must not acquire a new heavy dependency for one function, and the
    approximation's error (< 1.15e-9) is far below anything that could
    change a verdict.
    """
    if not 0.0 < p < 1.0:
        raise MultipleTestingError("probability must be strictly between 0 and 1", p=p)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > p_high:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
        ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1
    )


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """Expected maximum Sharpe from ``n_trials`` skill-free strategies.

    Bailey & López de Prado's benchmark: the level a purely lucky search
    would be expected to reach, which is what the observed Sharpe must
    beat to mean anything.
    """
    if n_trials < 1:
        raise MultipleTestingError("n_trials must be >= 1", n_trials=n_trials)
    if n_trials == 1:
        return 0.0
    sd = math.sqrt(max(sharpe_variance, 0.0))
    term = (1 - _EULER_MASCHERONI) * _norm_ppf(1 - 1.0 / n_trials) + _EULER_MASCHERONI * _norm_ppf(
        1 - 1.0 / (n_trials * math.e)
    )
    return sd * term


def deflated_sharpe_ratio(
    observed_sharpe: float,
    *,
    n_observations: int,
    skewness: float,
    kurtosis: float,
    benchmark_sharpe: float,
) -> Optional[float]:
    """Probability the observed (non-annualized) Sharpe exceeds ``benchmark_sharpe``.

    ``observed_sharpe``/``benchmark_sharpe`` must be in the SAME units
    (both per-observation, not annualized) — mixing them is the most
    common way this statistic is computed wrongly.
    """
    if n_observations < 2:
        return None
    denom_sq = 1.0 - skewness * observed_sharpe + ((kurtosis - 1.0) / 4.0) * observed_sharpe**2
    if denom_sq <= 0:
        return None
    numerator = (observed_sharpe - benchmark_sharpe) * math.sqrt(n_observations - 1)
    return _norm_cdf(numerator / math.sqrt(denom_sq))


@dataclass(frozen=True)
class MultipleTestingReport:
    candidate_id: str
    validation_run_id: str
    partition_name: str

    total_strategies_tested: int
    total_hypotheses_tested: int
    total_search_spaces: int
    total_families: int
    total_candidates: int
    total_rejections: int
    search_space_size: int
    effective_trials: int
    trials_derivation: str

    observed_sharpe_annualized: Optional[float]
    observed_sharpe_per_observation: Optional[float]
    n_observations: int
    skewness: Optional[float]
    kurtosis: Optional[float]
    expected_max_sharpe_per_observation: Optional[float]
    deflated_sharpe_probability: Optional[float]

    correction_meaningfulness: str
    accounting_status: str
    statistical_correction_status: str
    economic_edge_status: str
    selection_bias_status: str
    interpretation: str
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def report_checksum(self) -> str:
        d = self.to_dict()
        d.pop("timestamp", None)
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def run_multiple_testing_analysis(
    *,
    candidate_id: str,
    validation_run_id: str,
    partition_name: str,
    bar_returns: List[float],
    accounting: Dict[str, Any],
    search_history: Dict[str, Any],
    n_families: int,
    bars_per_year: int = 6240,
) -> MultipleTestingReport:
    """Apply the deflation using trial counts read from the project's ledgers."""
    rets = np.asarray(list(bar_returns), dtype="float64")

    total_candidates = int(accounting.get("TOTAL_CANDIDATES_GENERATED", 0))
    total_tested = int(accounting.get("TOTAL_CANDIDATES_TESTED", 0))
    total_rejected = int(accounting.get("TOTAL_CANDIDATES_REJECTED", 0))
    total_hypotheses = int(accounting.get("TOTAL_HYPOTHESES", 0))
    total_spaces = int(accounting.get("TOTAL_SEARCH_SPACES", 0))
    search_space_size = int(accounting.get("SEARCH_SPACE_SIZE", 0))

    # Effective trials: every candidate the Factory has ever put through
    # economic evaluation, not just the ones that survived. Using only the
    # survivor would be the exact self-deception this phase prevents.
    effective_trials = max(total_candidates, 1)
    trials_derivation = (
        f"TOTAL_CANDIDATES_GENERATED={total_candidates} from the strategy registry, which counts every "
        f"candidate ever created including the {total_rejected} already rejected. The enumerable "
        f"SEARCH_SPACE_SIZE is {search_space_size} parameter combinations, but only {total_candidates} "
        "were ever evaluated -- the un-drawn combinations were never tested and are not counted as "
        "trials. Using the larger figure would overstate the correction, which would be conservative "
        "here but would also be fiction."
    )

    if rets.size > 2 and rets.std(ddof=1) > 0:
        sharpe_per_obs = float(rets.mean() / rets.std(ddof=1))
        sharpe_annual = sharpe_per_obs * math.sqrt(bars_per_year)
        import pandas as _pd

        skew = float(_pd.Series(rets).skew())
        kurt = float(_pd.Series(rets).kurtosis()) + 3.0  # pandas returns EXCESS kurtosis
        # Variance of Sharpe across trials is unobservable with 2 trials;
        # use the sampling variance of the single observed Sharpe as the
        # scale, and say so.
        sharpe_variance = (1.0 + 0.5 * sharpe_per_obs**2) / max(rets.size - 1, 1)
        benchmark = expected_max_sharpe(effective_trials, sharpe_variance)
        dsr = deflated_sharpe_ratio(
            sharpe_per_obs,
            n_observations=int(rets.size),
            skewness=skew,
            kurtosis=kurt,
            benchmark_sharpe=benchmark,
        )
    else:
        sharpe_per_obs = sharpe_annual = skew = kurt = benchmark = dsr = None

    if effective_trials < MIN_TRIALS_FOR_MEANINGFUL_CORRECTION:
        meaningfulness = (
            f"NEARLY_UNINFORMATIVE: only {effective_trials} candidate(s) have ever been evaluated by "
            f"this Factory. A deflation over {effective_trials} trials shifts the benchmark by a "
            "negligible amount, so a candidate that passes it has NOT thereby been shown to survive "
            "multiple-testing scrutiny -- there was barely any multiplicity to correct for. The "
            "correction is reported for completeness and for the audit trail it establishes for "
            "future generations, not because it discriminates."
        )
    else:
        meaningfulness = f"MEANINGFUL: {effective_trials} trials is enough for the deflation to discriminate."

    if dsr is None:
        edge_status = NOT_SUPPORTED
        interpretation = (
            "No Sharpe could be computed (insufficient return observations), so no deflation was "
            "possible. This is an absence of evidence, not evidence of absence."
        )
    elif sharpe_annual is not None and sharpe_annual <= 0:
        edge_status = NOT_SUPPORTED
        interpretation = (
            f"The observed annualized Sharpe is {sharpe_annual:.4f}, i.e. negative. A multiple-testing "
            "correction can only reduce confidence in a positive result; it has nothing to correct "
            "here. The candidate is refuted before multiplicity is even considered, and the deflated "
            f"probability ({dsr:.6f}) simply restates that."
        )
    elif dsr >= 0.95:
        edge_status = ECONOMIC_EDGE_SUPPORTED
        interpretation = (
            f"Deflated Sharpe probability {dsr:.4f} exceeds 0.95 -- but read this together with "
            "correction_meaningfulness above before treating it as significance."
        )
    else:
        edge_status = NOT_SUPPORTED
        interpretation = (
            f"Deflated Sharpe probability {dsr:.4f} does not exceed the 0.95 threshold: the observed "
            "Sharpe is not distinguishable from what this much searching could produce without skill."
        )

    return MultipleTestingReport(
        candidate_id=candidate_id,
        validation_run_id=validation_run_id,
        partition_name=partition_name,
        total_strategies_tested=total_tested,
        total_hypotheses_tested=total_hypotheses,
        total_search_spaces=total_spaces,
        total_families=int(n_families),
        total_candidates=total_candidates,
        total_rejections=total_rejected,
        search_space_size=search_space_size,
        effective_trials=effective_trials,
        trials_derivation=trials_derivation,
        observed_sharpe_annualized=sharpe_annual,
        observed_sharpe_per_observation=sharpe_per_obs,
        n_observations=int(rets.size),
        skewness=skew,
        kurtosis=kurt,
        expected_max_sharpe_per_observation=benchmark,
        deflated_sharpe_probability=dsr,
        correction_meaningfulness=meaningfulness,
        accounting_status=ACCOUNTING_COMPLETE,
        statistical_correction_status=STATISTICAL_CORRECTION_COMPLETE,
        economic_edge_status=edge_status,
        selection_bias_status=str(search_history.get("selection_bias_status", "UNACCOUNTED")),
        interpretation=interpretation,
        timestamp=utcnow().isoformat(),
    )
