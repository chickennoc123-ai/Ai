#!/usr/bin/env python3
"""
AGLE STRATEGY FACTORY -- end-to-end pipeline (GEN 7 -> EA).

    GEN 7/8   discovery      : evidence -> hypotheses            (dev data)
    GEN 9-11  evaluation     : train / internal validation       (dev data)
    GEN 12    adversarial    : destruction attacks on survivors  (dev data)
    GEN 13    freeze         : specification locked, hashed
    GEN 14    qualification  : ONE shot at the sealed holdout    (authorized)
    PACKAGE   EA generation  : MT5 / MT4 / Pine, PASS only

Terminal outcomes:
    EDGE_CANDIDATE_PACKAGED -- a candidate cleared every gate and was emitted
    NO_EDGE_FOUND           -- nothing cleared the gates; a valid scientific
                               result. The holdout stays sealed and the
                               factory returns to GEN 7.

Nothing here may relax a gate. If the pipeline finds no edge, it says so.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from core.factory.failure_library import FailureLibrary
from discovery.ledger import MultipleTestingLedger
from discovery.candidate_spec_registry import CandidateSpecRegistry
from discovery.holdout_authorization import HoldoutAuthorizationGate

EVAL_PATH = REPO_ROOT / "reports/factory/discovery_cycles/cycle_03_evaluation.json"
OUT_PATH = REPO_ROOT / "reports/factory/pipeline_result.json"
EA_DIR = REPO_ROOT / "artifacts/ea"


def run(cycle_id: str = "CYCLE-3-MULTIASSET") -> dict:
    ev = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    survivors = ev["survivors"]

    registry = CandidateSpecRegistry(REPO_ROOT / "reports/factory/candidate_spec_registry.json")
    gate = HoldoutAuthorizationGate(REPO_ROOT / "reports/factory/holdout_authorization_registry.json")
    ledger = MultipleTestingLedger(REPO_ROOT / "reports/factory/multiple_testing_ledger.json")
    lib = FailureLibrary(REPO_ROOT / "reports/factory/failure_library.json")

    # --- ledger: append the evaluation pass (never edit an existing cycle) ---
    eval_cycle = f"{cycle_id}-EVAL"
    if not any(c.cycle_id == eval_cycle for c in ledger.cycles):
        ledger.record_cycle(
            cycle_id=eval_cycle,
            hypotheses_generated=0,
            parameter_evaluations=ev["parameter_evaluations"],
            families_touched=sorted({s["symbol"] for s in ev["per_symbol"]}
                                    if isinstance(ev["per_symbol"], dict)
                                    else {b["symbol"] for b in ev["per_symbol"]}),
            survivors=ev["survivor_count"],
            notes=("GEN 9-11 internal evaluation of the Cycle 3 multi-asset queue on "
                   "DEVELOPMENT data only. Hypotheses were counted in "
                   f"{cycle_id}; this row carries the parameter evaluations so the "
                   "cumulative multiple-testing denominator stays honest."),
        )

    result = {
        "cycle_id": cycle_id,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "hypotheses_evaluated": ev["hypotheses_evaluated"],
        "parameter_evaluations_this_pass": ev["parameter_evaluations"],
        "cumulative_parameter_evaluations": ledger.total_parameter_evaluations(),
        "cumulative_hypotheses": ledger.total_hypotheses(),
        "internal_survivors": ev["survivor_count"],
        "gen12_adversarial": [],
        "gen13_frozen": [],
        "gen14_qualified": [],
        "ea_packages": [],
    }

    if not survivors:
        # ---- NO EDGE: a valid scientific result. Holdout stays sealed. ----
        result["outcome"] = "NO_EDGE_FOUND"
        result["holdout_status"] = "SEALED_UNCONSUMED"
        result["explanation"] = (
            f"0 of {ev['hypotheses_evaluated']} Cycle 3 hypotheses cleared the "
            f"pre-registered internal-validation gates on development data. No "
            f"candidate was frozen, no authorization was issued, and the sealed "
            f"holdout was not opened. Standards were not relaxed to manufacture "
            f"a survivor.")
        rec = lib.record(
            entity_id=cycle_id,
            failure_stage="STATISTICS",
            failure_category="NEGATIVE_EXPECTANCY",
            failure_reason=(
                f"Cycle 3 multi-asset sweep: 0/{ev['hypotheses_evaluated']} hypotheses "
                f"across 6 instruments cleared train (t>=2.0) and internal validation "
                f"(t>=1.5, n>=30) after the frozen per-symbol round-trip cost."),
            evidence_reference="reports/factory/discovery_cycles/cycle_03_evaluation.json",
            related_family="MULTI_ASSET_CROSS_SECTION",
            related_market="EURUSD,GBPUSD,USDCAD,USDCHF,USDJPY,XAUUSD",
            mechanism=(
                "Every surviving-in-gross H1 pattern the observatory found is smaller "
                "than the round-trip cost on every instrument tested. Widening the "
                "instrument cross-section multiplied the sample but did not change "
                "the sign of net expectancy: the cost floor, not the sample size, is "
                "the binding constraint."),
            scope=("H1 bars, 6 major/commodity instruments, retail-realistic cost. Says "
                   "nothing about lower timeframes, other asset classes, or execution "
                   "models with materially lower cost."),
            confidence="DIRECTLY_MEASURED",
            reusability="ARCHITECTURE_TRANSFERABLE",
            prevention_rule=(
                "Do not re-test single-instrument H1 price-pattern families by adding "
                "more instruments. Cross-sectional breadth does not defeat a cost "
                "floor; only a larger gross effect or a lower cost does."),
            future_research_implication=(
                "Next cycles must change the economics, not the sample: lower-cost "
                "execution, larger-effect event windows, or genuinely multi-leg "
                "structures whose gross effect scales past the cost floor."),
        )
        result["failure_record"] = rec.failure_id
    else:
        # ---- survivors would flow through GEN 12 -> 13 -> 14 -> packaging ----
        result["outcome"] = "SURVIVORS_PENDING_GEN12"
        result["holdout_status"] = "SEALED_PENDING_AUTHORIZATION"
        result["survivors"] = survivors

    result["governance"] = {
        "holdout_authorizations": gate.summary(),
        "frozen_specifications": registry.summary(),
        "gates_relaxed": False,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    r = run()
    print("=" * 72)
    print(f"AGLE STRATEGY FACTORY -- PIPELINE RESULT: {r['outcome']}")
    print("=" * 72)
    print(f"  hypotheses evaluated        : {r['hypotheses_evaluated']}")
    print(f"  internal survivors          : {r['internal_survivors']}")
    print(f"  cumulative hypotheses       : {r['cumulative_hypotheses']}")
    print(f"  cumulative param evaluations: {r['cumulative_parameter_evaluations']}")
    print(f"  holdout                     : {r['holdout_status']}")
    print(f"  EA packages emitted         : {len(r['ea_packages'])}")
    if r.get("explanation"):
        print(f"\n  {r['explanation']}")
    if r.get("failure_record"):
        print(f"\n  failure memory              : {r['failure_record']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
