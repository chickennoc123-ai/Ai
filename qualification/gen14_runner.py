"""
GEN 14: terminal qualification against the sealed holdout.

One candidate, one frozen specification, one shot. The gates below are
PRE-REGISTERED and are never relaxed after a result is seen.

    G1  n_trades      >= 30            (sample floor)
    G2  mean_net      >  0             (economic viability, net of frozen cost)
    G3  t_stat        >= 2.0           (raw significance)
    G4  profit_factor >= 1.10          (not a coin flip with fat winners)
    G5  bonferroni    p < 0.05 / M     (M = CUMULATIVE parameter evaluations
                                        across the entire factory history --
                                        never this cycle's count alone)

PASS -> candidate proceeds to packaging (EA generation).
FAIL -> terminal. The candidate is dead against this holdout forever: it may
        not be retuned, re-optimized, or retested. Only governance-safe
        information (mechanism, family, gate name) reaches failure memory --
        never holdout statistics, which would let a future candidate be tuned
        toward the sealed data.
"""

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from discovery.evaluation import Trade, _stats
from discovery.candidate_spec_registry import CandidateSpecRegistry
from discovery.holdout_authorization import HoldoutAuthorizationGate
from discovery.ledger import MultipleTestingLedger
from qualification.holdout_access import open_sealed_holdout

MIN_TRADES = 30
MIN_T = 2.0
MIN_PROFIT_FACTOR = 1.10
FAMILYWISE_ALPHA = 0.05

DEFAULT_OUT = REPO_ROOT / "reports/factory/gen14_qualification.json"


def _two_sided_p(t: float, n: int) -> float:
    """Normal-approximation two-sided p-value; adequate at n>=30."""
    z = abs(t)
    # Abramowitz & Stegun 7.1.26 error-function approximation
    x = z / math.sqrt(2.0)
    tt = 1.0 / (1.0 + 0.3275911 * x)
    erf = 1.0 - (((((1.061405429 * tt - 1.453152027) * tt) + 1.421413741) * tt
                  - 0.284496736) * tt + 0.254829592) * tt * math.exp(-x * x)
    return max(0.0, 1.0 - erf)


def qualify_on_sealed_holdout(candidate_id: str, symbol: str,
                              executor: Callable[..., List[Trade]],
                              cost: float,
                              registry: CandidateSpecRegistry,
                              gate: HoldoutAuthorizationGate,
                              ledger: MultipleTestingLedger,
                              out_path: Path = DEFAULT_OUT) -> Dict:
    """
    Consume the sealed holdout for exactly one frozen candidate.

    Raises HoldoutAccessDenied if any governance precondition is unmet.
    Returns the terminal verdict payload.
    """
    bars = open_sealed_holdout(candidate_id, symbol, registry, gate)
    trades = executor(bars, cost=cost)
    s = _stats(trades)

    m = max(1, ledger.total_parameter_evaluations())
    alpha = FAMILYWISE_ALPHA / m
    p = _two_sided_p(s.t_stat, s.n) if s.n >= 2 else 1.0

    gates = {
        "G1_min_trades": "PASS" if s.n >= MIN_TRADES else "FAIL",
        "G2_positive_expectancy": "PASS" if s.mean_net > 0 else "FAIL",
        "G3_significance": "PASS" if s.t_stat >= MIN_T else "FAIL",
        "G4_profit_factor": "PASS" if s.profit_factor >= MIN_PROFIT_FACTOR else "FAIL",
        "G5_multiple_testing": "PASS" if (p < alpha and s.mean_net > 0) else "FAIL",
    }
    verdict = "PASS" if all(v == "PASS" for v in gates.values()) else "FAIL"
    first_failed = next((k for k, v in gates.items() if v == "FAIL"), None)

    # Terminal, one-way. Recorded BEFORE anything else can touch the result.
    gate.record_gen14_result(candidate_id, verdict)

    payload = {
        "candidate_id": candidate_id,
        "symbol": symbol,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "spec_hash": registry.get_hash(candidate_id),
        "holdout_bars": len(bars),
        "gates": gates,
        "verdict": verdict,
        "first_failed_gate": first_failed,
        "multiple_testing": {
            "cumulative_parameter_evaluations": m,
            "bonferroni_alpha": alpha,
            "observed_p": round(p, 10),
        },
        "holdout_statistics": s.to_dict(),
        "terminal": True,
        "note": ("Holdout consumed for this candidate. On FAIL the candidate is "
                 "dead against this holdout permanently: no retuning, no retest."),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8")).get("qualifications", [])
    existing.append(payload)
    out_path.write_text(json.dumps(
        {"gates_preregistered": {"min_trades": MIN_TRADES, "min_t": MIN_T,
                                 "min_profit_factor": MIN_PROFIT_FACTOR,
                                 "familywise_alpha": FAMILYWISE_ALPHA},
         "qualifications": existing}, indent=2), encoding="utf-8")
    return payload


def governance_safe_failure_note(payload: Dict, mechanism: str) -> Dict:
    """
    Reduce a GEN 14 failure to information that CANNOT be used to tune a future
    candidate toward the sealed holdout.

    Kept:    candidate id, mechanism prose, which gate failed first, terminality.
    Dropped: every holdout statistic (n, expectancy, t, profit factor, p-value,
             window boundaries) -- these are the exact quantities an optimizer
             would hill-climb against.
    """
    return {
        "candidate_id": payload["candidate_id"],
        "symbol": payload["symbol"],
        "mechanism": mechanism,
        "stage": "GEN-14-SEALED-HOLDOUT",
        "first_failed_gate": payload["first_failed_gate"],
        "verdict": "TERMINAL_FAIL",
        "prevention_rule": (
            "This mechanism is terminally refuted on this holdout. It may not be "
            "retuned, re-parameterised, or resubmitted against the same sealed "
            "data. A successor must be a structurally different mechanism."),
        "holdout_statistics_withheld": True,
    }
